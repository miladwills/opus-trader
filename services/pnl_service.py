"""
Bybit Control Center - PnL Service

Syncs closed PnL data from Bybit and computes daily statistics.
Implements file locking to prevent race conditions.
"""

from pathlib import Path
import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Optional, Any, Iterable, Set

from config.strategy_config import (
    EXIT_STACK_WATCHDOG_MIN_EVENTS,
    EXIT_STACK_WATCHDOG_WARN_FORCED_EXIT_SHARE,
    EXIT_STACK_WATCHDOG_WINDOW_SECONDS,
    LOSS_ASYMMETRY_WATCHDOG_HIGH_WIN_RATE_PCT,
    LOSS_ASYMMETRY_WATCHDOG_MIN_TRADES,
    LOSS_ASYMMETRY_WATCHDOG_WARN_PAYOFF_RATIO,
    LOSS_ASYMMETRY_WATCHDOG_WARN_PROFIT_FACTOR,
    LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES,
    PNL_ATTRIBUTION_WATCHDOG_MIN_TRADES,
    PNL_ATTRIBUTION_WATCHDOG_WARN_AMBIGUOUS_SHARE,
    PNL_ATTRIBUTION_WATCHDOG_WARN_UNATTRIBUTED_SHARE,
    PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES,
)
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.bybit_client import BybitClient
from services.bot_storage_service import BotStorageService
from services.order_ownership_service import OrderOwnershipService
from services.symbol_pnl_service import SymbolPnlService
from services.lock_service import file_lock
from services.trade_forensics_service import TradeForensicsService
from services.watchdog_diagnostics_service import WatchdogDiagnosticsService
from services.performance_baseline_service import PerformanceBaselineService

logger = logging.getLogger(__name__)


class PnlService:
    """
    Service for tracking and analyzing PnL data.
    """

    def __init__(
        self,
        client: BybitClient,
        file_path: str,
        bot_storage: Optional[BotStorageService] = None,
        symbol_pnl_service: Optional[SymbolPnlService] = None,
        order_ownership_service: Optional[OrderOwnershipService] = None,
        trade_forensics_service: Optional[TradeForensicsService] = None,
        risk_manager: Optional[Any] = None,
        symbol_training_service: Optional[Any] = None,
        audit_diagnostics_service: Optional[AuditDiagnosticsService] = None,
        performance_baseline_service: Optional[PerformanceBaselineService] = None,
    ):
        """
        Initialize the PnL service.

        Args:
            client: Initialized BybitClient instance
            file_path: Path to the JSON file for trade logs
            bot_storage: Optional BotStorageService for updating per-bot realized PnL
            symbol_pnl_service: Optional SymbolPnlService for tracking per-symbol cumulative PnL
            order_ownership_service: Optional durable order ownership store
            risk_manager: Optional RiskManagerService for daily symbol-loss tracking
            symbol_training_service: Optional SymbolTrainingService for per-symbol learning
        """
        self.client = client
        self.file_path = Path(file_path)
        self.lock_path = Path(str(file_path) + ".lock")
        self.bot_storage = bot_storage
        self.symbol_pnl_service = symbol_pnl_service or SymbolPnlService()
        self.order_ownership_service = order_ownership_service or OrderOwnershipService(
            str(self.file_path.parent / "order_ownership.json")
        )
        self.trade_forensics_service = trade_forensics_service or TradeForensicsService(
            str(self.file_path.parent / "trade_forensics.jsonl")
        )
        self.risk_manager = risk_manager
        self.symbol_training_service = symbol_training_service
        self.audit_diagnostics_service = audit_diagnostics_service or AuditDiagnosticsService()
        self.performance_baseline_service = performance_baseline_service

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create lock file if it doesn't exist
        if not self.lock_path.exists():
            self.lock_path.touch()

        # Create file with empty array if it doesn't exist
        if not self.file_path.exists():
            self._write_logs([])

    def _get_watchdog_diagnostics_service(self) -> WatchdogDiagnosticsService:
        service = getattr(self, "_watchdog_diagnostics_service", None)
        if service is None:
            service = WatchdogDiagnosticsService(
                getattr(self, "audit_diagnostics_service", None)
            )
            self._watchdog_diagnostics_service = service
        return service

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _resolve_bot_from_prefix(
        self, parsed_bot_id: Optional[str], symbol: str, all_bots: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not parsed_bot_id:
            return None

        bot_id_len = len(parsed_bot_id)
        matching_bots = []
        for bot in all_bots:
            full_id = bot.get("id", "")
            full_id_clean = full_id.replace("-", "")
            if parsed_bot_id == full_id or parsed_bot_id == full_id_clean:
                return bot
            if bot_id_len <= 8:
                if full_id.startswith(parsed_bot_id):
                    matching_bots.append(bot)
            elif full_id_clean.startswith(parsed_bot_id):
                matching_bots.append(bot)

        if len(matching_bots) == 1:
            return matching_bots[0]

        if len(matching_bots) > 1:
            symbol_matches = [bot for bot in matching_bots if bot.get("symbol") == symbol]
            if len(symbol_matches) == 1:
                return symbol_matches[0]
            logger.warning(
                "PnL: Ambiguous bot_id prefix '%s' matches %s bots for symbol '%s'; skipping bot attribution",
                parsed_bot_id,
                len(matching_bots),
                symbol,
            )
        return None

    @staticmethod
    def _parse_datetime_value(raw_value: Any) -> Optional[datetime]:
        if raw_value is None:
            return None

        raw_text = str(raw_value).strip()
        if not raw_text:
            return None

        try:
            if raw_text.isdigit():
                return datetime.fromtimestamp(int(raw_text) / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

        normalized = raw_text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _baseline_started_at(
        self,
        *,
        bot_id: Optional[str] = None,
        use_global_baseline: bool = False,
        baseline_started_at: Optional[Any] = None,
    ) -> Optional[datetime]:
        if baseline_started_at is not None:
            return self._parse_datetime_value(baseline_started_at)
        service = getattr(self, "performance_baseline_service", None)
        if service is None:
            return None
        if use_global_baseline or not str(bot_id or "").strip():
            return service.get_global_started_at()
        return service.get_effective_started_at(bot_id=str(bot_id or "").strip())

    def _filter_logs(
        self,
        logs: List[Dict[str, Any]],
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        cutoff_dt: Optional[datetime] = None,
        use_global_baseline: bool = False,
        baseline_started_at: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        baseline_dt = self._baseline_started_at(
            bot_id=normalized_bot_id or None,
            use_global_baseline=use_global_baseline,
            baseline_started_at=baseline_started_at,
        )
        filtered: List[Dict[str, Any]] = []
        for log in logs:
            if normalized_bot_id and str(log.get("bot_id") or "").strip() != normalized_bot_id:
                continue
            if normalized_symbol and str(log.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            log_dt = self._parse_datetime_value(log.get("time"))
            if cutoff_dt is not None:
                if log_dt is None or log_dt < cutoff_dt:
                    continue
            if baseline_dt is not None:
                if log_dt is None or log_dt < baseline_dt:
                    continue
            filtered.append(log)
        return filtered

    def summarize_logs(
        self,
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
        use_global_baseline: bool = False,
        baseline_started_at: Optional[Any] = None,
    ) -> Dict[str, Any]:
        logs = self._filter_logs(
            self.get_log(),
            bot_id=bot_id,
            symbol=symbol,
            use_global_baseline=use_global_baseline,
            baseline_started_at=baseline_started_at,
        )
        total_profit = 0.0
        total_loss = 0.0
        win_count = 0
        loss_count = 0
        recent_trades: List[Dict[str, Any]] = []
        first_trade_at = None
        last_trade_at = None
        for log in logs:
            pnl = self._safe_float(log.get("realized_pnl"), 0.0) or 0.0
            if pnl > 0:
                total_profit += pnl
                win_count += 1
            elif pnl < 0:
                total_loss += abs(pnl)
                loss_count += 1
            trade_time = str(log.get("time") or "").strip() or None
            if first_trade_at is None:
                first_trade_at = trade_time
            last_trade_at = trade_time or last_trade_at
            recent_trades.append(
                {
                    "time": trade_time,
                    "pnl": round(pnl, 8),
                    "side": log.get("side"),
                    "bot_id": log.get("bot_id"),
                    "trade_id": log.get("id") or log.get("order_id"),
                }
            )
        recent_trades.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
        if limit is not None and limit >= 0:
            recent_trades = recent_trades[:limit]
        trade_count = len(logs)
        win_rate = (win_count / trade_count * 100.0) if trade_count > 0 else 0.0
        return {
            "net_pnl": round(total_profit - total_loss, 4),
            "total_profit": round(total_profit, 4),
            "total_loss": round(total_loss, 4),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 1),
            "win_count": win_count,
            "loss_count": loss_count,
            "first_trade_at": first_trade_at,
            "last_trade_at": last_trade_at,
            "recent_trades": recent_trades,
        }

    @staticmethod
    def _get_symbol_bots(
        symbol: str, all_bots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not symbol:
            return []

        return [
            bot
            for bot in all_bots
            if bot.get("symbol") == symbol
            and not bot.get("is_deleted")
            and not bot.get("deleted_at")
        ]

    @staticmethod
    def _exit_reason_bucket(reason: str) -> str:
        normalized = str(reason or "").strip().lower()
        if not normalized:
            return "unknown"
        if any(
            token in normalized
            for token in (
                "emergency",
                "breakout",
                "max_loss",
                "risk",
                "flatten",
                "manual_close",
                "inventory",
                "stoploss",
            )
        ):
            return "forced"
        if any(
            token in normalized
            for token in (
                "quick_profit",
                "profit_lock",
                "take_profit",
                "trailing",
                "tp",
            )
        ):
            return "profit"
        return "other"

    def _extract_cost_fields(self, record: Dict[str, Any]) -> Dict[str, Any]:
        open_fee = self._safe_float(record.get("openFee"), None)
        close_fee = self._safe_float(record.get("closeFee"), None)
        exec_fee = self._safe_float(record.get("execFee"), None)
        funding_fee = self._safe_float(
            record.get("fundingFee", record.get("funding_fee", record.get("funding"))),
            None,
        )
        total_fee = None
        if open_fee is not None or close_fee is not None:
            total_fee = abs(self._safe_float(open_fee, 0.0) or 0.0) + abs(
                self._safe_float(close_fee, 0.0) or 0.0
            )
        elif exec_fee is not None:
            total_fee = abs(exec_fee)
        payload = {
            "open_fee": round(open_fee, 8) if open_fee is not None else None,
            "close_fee": round(close_fee, 8) if close_fee is not None else None,
            "exec_fee": round(exec_fee, 8) if exec_fee is not None else None,
            "total_fee": round(total_fee, 8) if total_fee is not None else None,
            "funding_fee": round(funding_fee, 8) if funding_fee is not None else None,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _build_trade_window_stats(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        wins = 0
        losses = 0
        total_profit = 0.0
        total_loss = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        known_fee_total = 0.0
        known_fee_trades = 0
        known_funding_total = 0.0
        known_funding_trades = 0
        unresolved_sources = 0
        ambiguous_sources = 0
        for log in logs:
            pnl = PnlService._safe_float(log.get("realized_pnl"), 0.0) or 0.0
            if pnl > 0:
                wins += 1
                total_profit += pnl
                largest_win = max(largest_win, pnl)
            elif pnl < 0:
                losses += 1
                total_loss += abs(pnl)
                largest_loss = max(largest_loss, abs(pnl))
            total_fee = PnlService._safe_float(log.get("total_fee"), None)
            if total_fee is not None:
                known_fee_total += abs(total_fee)
                known_fee_trades += 1
            funding_fee = PnlService._safe_float(log.get("funding_fee"), None)
            if funding_fee is not None:
                known_funding_total += funding_fee
                known_funding_trades += 1
            attribution_source = str(log.get("attribution_source") or "").strip().lower()
            has_resolved_bot_metadata = bool(
                str(log.get("bot_id") or "").strip()
                or str(log.get("ownership_source") or "").strip()
            )
            if (
                attribution_source in (
                "unattributed",
                "order_link_id_unresolved",
                "explicit_order_link_id_unmapped",
                "ambiguous_symbol",
                )
                and not has_resolved_bot_metadata
            ):
                unresolved_sources += 1
            if (
                attribution_source in ("ambiguous_symbol", "explicit_ambiguous_close")
                and not has_resolved_bot_metadata
            ):
                ambiguous_sources += 1
        total_trades = len(logs)
        net_pnl = total_profit - total_loss
        avg_win = (total_profit / wins) if wins > 0 else 0.0
        avg_loss = (total_loss / losses) if losses > 0 else 0.0
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        profit_factor = (
            (total_profit / total_loss)
            if total_loss > 0
            else (float("inf") if total_profit > 0 else 0.0)
        )
        payoff_ratio = (
            (avg_win / avg_loss)
            if avg_loss > 0
            else (float("inf") if avg_win > 0 else 0.0)
        )
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "payoff_ratio": round(payoff_ratio, 4)
            if payoff_ratio != float("inf")
            else None,
            "profit_factor": round(profit_factor, 4)
            if profit_factor != float("inf")
            else None,
            "largest_win": round(largest_win, 4),
            "largest_loss": round(largest_loss, 4),
            "net_pnl": round(net_pnl, 4),
            "known_fee_total": round(known_fee_total, 4),
            "known_fee_trades": known_fee_trades,
            "known_funding_total": round(known_funding_total, 4),
            "known_funding_trades": known_funding_trades,
            "unresolved_sources": unresolved_sources,
            "ambiguous_sources": ambiguous_sources,
        }

    @staticmethod
    def _normalize_experiment_tags(*values: Any) -> List[str]:
        tags: List[str] = []
        for value in values:
            if isinstance(value, (list, tuple, set)):
                items = value
            else:
                items = [value]
            for item in items:
                tag = str(item or "").strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
        return sorted(tags)

    @staticmethod
    def _merge_experiment_details(*values: Any) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            for key, detail in value.items():
                tag = str(key or "").strip().lower()
                if not tag:
                    continue
                if isinstance(detail, dict):
                    existing = merged.get(tag)
                    if isinstance(existing, dict):
                        combined = dict(existing)
                        combined.update(detail)
                        merged[tag] = combined
                    else:
                        merged[tag] = dict(detail)
                elif detail is not None:
                    merged[tag] = detail
        return merged

    @staticmethod
    def _derive_experiment_outcome_kind(realized_pnl: Optional[float]) -> str:
        pnl_value = PnlService._safe_float(realized_pnl, 0.0) or 0.0
        if pnl_value > 0:
            return "profit"
        if pnl_value < 0:
            return "loss"
        return "neutral"

    @classmethod
    def _derive_experiment_outcome_tags(
        cls,
        experiment_tags: Optional[List[str]],
        outcome_kind: str,
    ) -> List[str]:
        prefix = {
            "profit": "exp_profit_after_",
            "loss": "exp_loss_after_",
            "neutral": "exp_neutral_after_",
        }.get(str(outcome_kind or "").strip().lower())
        if not prefix:
            return []
        derived: List[str] = []
        for tag in cls._normalize_experiment_tags(experiment_tags):
            base = str(tag).strip().lower()
            if base.startswith("exp_"):
                base = base[4:]
            for suffix in ("_used", "_created"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            if not base:
                continue
            outcome_tag = f"{prefix}{base}"
            if outcome_tag not in derived:
                derived.append(outcome_tag)
        return derived

    def _record_trade_forensic_outcome(
        self,
        entry: Dict[str, Any],
        *,
        ownership_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        service = getattr(self, "trade_forensics_service", None)
        if service is None:
            return
        try:
            trade_time = str(entry.get("time") or "").strip() or datetime.now(
                timezone.utc
            ).isoformat()
            lifecycle_started_at = (
                str((ownership_snapshot or {}).get("forensic_lifecycle_started_at") or "").strip()
                or None
            )
            hold_time_sec = None
            trade_dt = self._parse_datetime_value(trade_time)
            started_dt = self._parse_datetime_value(lifecycle_started_at)
            if trade_dt and started_dt:
                hold_time_sec = round(
                    max((trade_dt - started_dt).total_seconds(), 0.0),
                    3,
                )
            experiment_tags = self._normalize_experiment_tags(
                (ownership_snapshot or {}).get("experiment_tags"),
                entry.get("experiment_tags"),
            )
            experiment_details = self._merge_experiment_details(
                (ownership_snapshot or {}).get("experiment_details"),
                entry.get("experiment_details"),
            )
            experiment_attribution_state = (
                str(
                    (ownership_snapshot or {}).get("experiment_attribution_state")
                    or entry.get("experiment_attribution_state")
                    or ("present" if experiment_tags else "none")
                ).strip()
                or ("present" if experiment_tags else "none")
            )
            entry_story = dict(
                (ownership_snapshot or {}).get("entry_story")
                or entry.get("entry_story")
                or {}
            )
            opening_sizing = dict(
                (ownership_snapshot or {}).get("opening_sizing")
                or entry.get("opening_sizing")
                or {}
            )
            profit_protection_advisory = dict(
                (ownership_snapshot or {}).get("profit_protection_advisory")
                or entry.get("profit_protection_advisory")
                or {}
            )
            profit_protection_shadow = dict(
                (ownership_snapshot or {}).get("profit_protection_shadow")
                or entry.get("profit_protection_shadow")
                or {}
            )
            realized_pnl = self._safe_float(entry.get("realized_pnl"), 0.0)
            experiment_outcome_kind = self._derive_experiment_outcome_kind(realized_pnl)
            experiment_outcome_tags = self._derive_experiment_outcome_tags(
                experiment_tags,
                experiment_outcome_kind,
            )

            base_payload = {
                "timestamp": trade_time,
                "forensic_decision_id": (
                    (ownership_snapshot or {}).get("forensic_decision_id")
                    or entry.get("forensic_decision_id")
                ),
                "trade_context_id": (
                    (ownership_snapshot or {}).get("forensic_trade_context_id")
                    or entry.get("forensic_trade_context_id")
                ),
                "bot_id": entry.get("bot_id"),
                "symbol": entry.get("symbol"),
                "mode": entry.get("bot_mode"),
                "profile": entry.get("bot_profile"),
                "side": (
                    (ownership_snapshot or {}).get("forensic_side")
                    or entry.get("side")
                ),
                "decision_type": (
                    (ownership_snapshot or {}).get("forensic_decision_type")
                ),
                "linkage_method": (
                    "ownership_snapshot"
                    if ownership_snapshot
                    and (
                        ownership_snapshot.get("forensic_trade_context_id")
                        or ownership_snapshot.get("forensic_decision_id")
                    )
                    else str(entry.get("attribution_source") or "unresolved")
                ),
                "attribution_status": (
                    "linked"
                    if (ownership_snapshot or {}).get("forensic_trade_context_id")
                    or (ownership_snapshot or {}).get("forensic_decision_id")
                    else "unresolved"
                ),
                "exit": {
                    "close_reason": (
                        (ownership_snapshot or {}).get("close_reason")
                        or entry.get("ownership_close_reason")
                    ),
                    "ownership_action": (
                        (ownership_snapshot or {}).get("action")
                        or entry.get("ownership_action")
                    ),
                    "hold_time_sec": hold_time_sec,
                },
                "outcome": {
                    "realized_pnl": realized_pnl,
                    "balance_after": self._safe_float(entry.get("balance_after"), None),
                    "win": bool(realized_pnl > 0),
                    "order_id": entry.get("order_id"),
                    "exec_id": entry.get("exec_id"),
                    "order_link_id": entry.get("order_link_id"),
                    "position_idx": entry.get("position_idx"),
                    "attribution_source": entry.get("attribution_source"),
                    "total_fee": self._safe_float(entry.get("total_fee"), None),
                    "funding_fee": self._safe_float(entry.get("funding_fee"), None),
                    "experiment_attribution_state": experiment_attribution_state,
                    "entry_story": entry_story or None,
                    "opening_sizing": opening_sizing or None,
                    "profit_protection_advisory": profit_protection_advisory or None,
                    "profit_protection_shadow": profit_protection_shadow or None,
                },
            }
            if experiment_tags:
                base_payload["outcome"]["experiment_tags"] = experiment_tags
            if experiment_details:
                base_payload["outcome"]["experiment_details"] = experiment_details
            if experiment_outcome_tags:
                base_payload["outcome"]["experiment_outcome_tags"] = experiment_outcome_tags
            service.record_event(
                dict(base_payload, event_type="position_closed", event_status="closed")
            )
            service.record_event(
                dict(
                    base_payload,
                    event_type="realized_outcome",
                    event_status="realized",
                )
            )
            diagnostics_service = getattr(self, "audit_diagnostics_service", None)
            if (
                diagnostics_service is not None
                and diagnostics_service.enabled()
                and experiment_tags
            ):
                diagnostics_service.record_event(
                    {
                        "event_type": "experiment_trade_outcome",
                        "severity": (
                            "WARN"
                            if experiment_outcome_kind == "loss"
                            else "INFO"
                        ),
                        "timestamp": trade_time,
                        "bot_id": entry.get("bot_id"),
                        "symbol": entry.get("symbol"),
                        "mode": entry.get("bot_mode"),
                        "realized_pnl": realized_pnl,
                        "attribution_source": entry.get("attribution_source"),
                        "ownership_action": entry.get("ownership_action"),
                        "ownership_close_reason": entry.get("ownership_close_reason"),
                        "experiment_tags": experiment_tags,
                        "experiment_details": experiment_details or None,
                        "experiment_attribution_state": experiment_attribution_state,
                        "experiment_outcome_kind": experiment_outcome_kind,
                        "experiment_outcome_tags": experiment_outcome_tags or None,
                        "entry_story": entry_story or None,
                        "opening_sizing": opening_sizing or None,
                        "profit_protection_advisory": profit_protection_advisory or None,
                        "profit_protection_shadow": profit_protection_shadow or None,
                    },
                    throttle_key=(
                        f"experiment_trade_outcome:{entry.get('id')}:{experiment_outcome_kind}"
                    ),
                    throttle_sec=0,
                )
        except Exception as exc:
            logger.warning(
                "Trade forensics realized outcome logging failed for %s: %s",
                entry.get("id") or entry.get("order_id") or "?",
                exc,
            )

    @staticmethod
    def _filter_scope_logs(
        logs: List[Dict[str, Any]],
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        scoped = []
        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        for log in logs:
            if normalized_bot_id and str(log.get("bot_id") or "").strip() != normalized_bot_id:
                continue
            if normalized_symbol and str(log.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            scoped.append(log)
        scoped.sort(key=lambda row: row.get("time", ""))
        if limit > 0 and len(scoped) > limit:
            scoped = scoped[-limit:]
        return scoped

    def _maybe_emit_loss_asymmetry_watchdog(
        self,
        logs: List[Dict[str, Any]],
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> None:
        watchdog_service = self._get_watchdog_diagnostics_service()
        if not watchdog_service.enabled("loss_asymmetry"):
            return
        scoped_logs = self._filter_scope_logs(
            logs,
            bot_id=bot_id,
            symbol=symbol,
            limit=max(int(LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES or 0), 1),
        )
        stats = self._build_trade_window_stats(scoped_logs)
        if stats["total_trades"] < max(int(LOSS_ASYMMETRY_WATCHDOG_MIN_TRADES or 0), 1):
            return
        net_pnl = self._safe_float(stats.get("net_pnl"), 0.0) or 0.0
        win_rate = self._safe_float(stats.get("win_rate"), 0.0) or 0.0
        payoff_ratio = self._safe_float(stats.get("payoff_ratio"), None)
        profit_factor = self._safe_float(stats.get("profit_factor"), None)
        reason = None
        severity = "WARN"
        if (
            net_pnl < 0
            and win_rate >= float(LOSS_ASYMMETRY_WATCHDOG_HIGH_WIN_RATE_PCT)
            and payoff_ratio is not None
            and payoff_ratio < float(LOSS_ASYMMETRY_WATCHDOG_WARN_PAYOFF_RATIO)
        ):
            reason = "high_win_rate_negative_pnl"
        elif net_pnl < 0 and payoff_ratio is not None and payoff_ratio < float(
            LOSS_ASYMMETRY_WATCHDOG_WARN_PAYOFF_RATIO
        ):
            reason = "losses_dwarf_wins"
        elif net_pnl < 0 and profit_factor is not None and profit_factor < float(
            LOSS_ASYMMETRY_WATCHDOG_WARN_PROFIT_FACTOR
        ):
            reason = "profit_factor_deteriorated"
        if not reason:
            return
        if (
            payoff_ratio is not None
            and payoff_ratio < 0.5
            and profit_factor is not None
            and profit_factor < 0.75
        ):
            severity = "ERROR"
        watchdog_service.emit(
            watchdog_type="loss_asymmetry",
            severity=severity,
            bot_id=bot_id,
            symbol=symbol,
            reason=reason,
            throttle_key=f"loss_asymmetry_watchdog:{bot_id or 'na'}:{symbol or 'na'}:{reason}",
            compact_metrics=stats,
            suggested_action=(
                "Review payoff asymmetry before changing win-rate filters; small wins are not covering losses."
            ),
            source_context={
                "scope": "bot" if bot_id else "symbol",
                "window_trades": stats.get("total_trades"),
            },
        )

    def _maybe_emit_exit_stack_watchdog(
        self,
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        scope_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        watchdog_service = self._get_watchdog_diagnostics_service()
        diagnostics_service = getattr(self, "audit_diagnostics_service", None)
        if not watchdog_service.enabled("exit_stack") or diagnostics_service is None:
            return
        exit_events = diagnostics_service.get_recent_events(
            event_type="exit_reason",
            since_seconds=max(float(EXIT_STACK_WATCHDOG_WINDOW_SECONDS or 0), 60.0),
            bot_id=bot_id,
            symbol=symbol,
            limit=200,
        )
        if len(exit_events) < max(int(EXIT_STACK_WATCHDOG_MIN_EVENTS or 0), 1):
            return
        reason_counts: Dict[str, int] = {}
        forced_count = 0
        capture_ratios: List[float] = []
        for event in exit_events:
            reason = str(event.get("reason") or "unknown").strip().lower() or "unknown"
            reason_counts[reason] = int(reason_counts.get(reason, 0) or 0) + 1
            if self._exit_reason_bucket(reason) == "forced":
                forced_count += 1
            unrealized_pnl = self._safe_float(event.get("unrealized_pnl"), None)
            profit_taken = self._safe_float(event.get("profit_taken"), None)
            if unrealized_pnl is not None and unrealized_pnl > 0 and profit_taken is not None:
                capture_ratios.append(max(0.0, min(profit_taken / unrealized_pnl, 1.0)))
        forced_share = forced_count / len(exit_events)
        reason = None
        if forced_share >= float(EXIT_STACK_WATCHDOG_WARN_FORCED_EXIT_SHARE):
            reason = "forced_exit_concentration"
        elif capture_ratios and (sum(capture_ratios) / len(capture_ratios)) < 0.45:
            reason = "low_favorable_capture"
        if not reason:
            return
        sorted_reasons = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        metrics = {
            "window_exit_events": len(exit_events),
            "forced_exit_share": round(forced_share, 4),
            "top_exit_reasons": [f"{key}:{value}" for key, value in sorted_reasons[:4]],
            "captured_fraction_avg": round(sum(capture_ratios) / len(capture_ratios), 4)
            if capture_ratios
            else None,
            "capture_samples": len(capture_ratios),
            "net_pnl": (scope_stats or {}).get("net_pnl"),
        }
        watchdog_service.emit(
            watchdog_type="exit_stack",
            severity="WARN",
            bot_id=bot_id,
            symbol=symbol,
            reason=reason,
            throttle_key=f"exit_stack_watchdog:{bot_id or 'na'}:{symbol or 'na'}:{reason}",
            compact_metrics=metrics,
            suggested_action=(
                "Review why forced exits are dominating or why favorable excursion capture is staying low."
            ),
            source_context={
                "scope": "bot" if bot_id else "symbol",
                "data_quality": "distribution_only" if not capture_ratios else "distribution_plus_capture_samples",
            },
        )

    def _maybe_emit_pnl_attribution_watchdog(
        self,
        logs: List[Dict[str, Any]],
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> None:
        watchdog_service = self._get_watchdog_diagnostics_service()
        if not watchdog_service.enabled("pnl_attribution"):
            return
        scoped_logs = self._filter_scope_logs(
            logs,
            bot_id=bot_id,
            symbol=symbol,
            limit=max(int(PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES or 0), 1),
        )
        stats = self._build_trade_window_stats(scoped_logs)
        total_trades = int(stats.get("total_trades") or 0)
        if total_trades < max(int(PNL_ATTRIBUTION_WATCHDOG_MIN_TRADES or 0), 1):
            return
        unresolved_share = float(stats.get("unresolved_sources") or 0) / float(total_trades)
        ambiguous_share = float(stats.get("ambiguous_sources") or 0) / float(total_trades)
        known_fee_total = self._safe_float(stats.get("known_fee_total"), 0.0) or 0.0
        net_pnl = self._safe_float(stats.get("net_pnl"), 0.0) or 0.0
        reasons = []
        if unresolved_share >= float(PNL_ATTRIBUTION_WATCHDOG_WARN_UNATTRIBUTED_SHARE):
            reasons.append("attribution_gap")
        if ambiguous_share >= float(PNL_ATTRIBUTION_WATCHDOG_WARN_AMBIGUOUS_SHARE):
            reasons.append("ambiguous_attribution")
        if known_fee_total > 0 and net_pnl <= known_fee_total:
            reasons.append("known_cost_drag_material")
        for reason in reasons:
            watchdog_service.emit(
                watchdog_type="pnl_attribution",
                severity="WARN",
                bot_id=bot_id,
                symbol=symbol,
                reason=reason,
                throttle_key=f"pnl_attribution_watchdog:{bot_id or 'na'}:{symbol or 'na'}:{reason}",
                compact_metrics={
                    **stats,
                    "unresolved_share": round(unresolved_share, 4),
                    "ambiguous_share": round(ambiguous_share, 4),
                    "cost_data_coverage": round(
                        float(stats.get("known_fee_trades") or 0) / float(total_trades),
                        4,
                    ),
                },
                suggested_action=(
                    "Separate attribution gaps from actual strategy weakness before drawing conclusions from headline PnL."
                ),
                source_context={
                    "scope": "bot" if bot_id else "symbol",
                    "cost_limitations": (
                        "Funding/slippage are only reported when the exchange record carries explicit fields."
                    ),
                },
            )

    def _run_scope_watchdogs(
        self,
        logs: List[Dict[str, Any]],
        *,
        bot_ids: Optional[Set[str]] = None,
        symbols: Optional[Set[str]] = None,
    ) -> None:
        for bot_id in sorted({str(item).strip() for item in (bot_ids or set()) if str(item).strip()}):
            scoped_logs = self._filter_scope_logs(
                logs,
                bot_id=bot_id,
                limit=max(
                    int(LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES or 0),
                    int(PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES or 0),
                    1,
                ),
            )
            if not scoped_logs:
                continue
            primary_symbol = str(scoped_logs[-1].get("symbol") or "").strip().upper() or None
            stats = self._build_trade_window_stats(scoped_logs)
            self._maybe_emit_loss_asymmetry_watchdog(logs, bot_id=bot_id, symbol=primary_symbol)
            self._maybe_emit_exit_stack_watchdog(bot_id=bot_id, symbol=primary_symbol, scope_stats=stats)
            self._maybe_emit_pnl_attribution_watchdog(logs, bot_id=bot_id, symbol=primary_symbol)
        for symbol in sorted({str(item).strip().upper() for item in (symbols or set()) if str(item).strip()}):
            scoped_logs = self._filter_scope_logs(
                logs,
                symbol=symbol,
                limit=max(
                    int(LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES or 0),
                    int(PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES or 0),
                    1,
                ),
            )
            if not scoped_logs:
                continue
            stats = self._build_trade_window_stats(scoped_logs)
            self._maybe_emit_loss_asymmetry_watchdog(logs, symbol=symbol)
            self._maybe_emit_exit_stack_watchdog(symbol=symbol, scope_stats=stats)
            self._maybe_emit_pnl_attribution_watchdog(logs, symbol=symbol)

    @classmethod
    def _resolve_unique_bot_for_symbol(
        cls,
        symbol: str,
        all_bots: List[Dict[str, Any]],
        trade_time: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not symbol:
            return None

        symbol_matches = cls._get_symbol_bots(symbol, all_bots)
        if len(symbol_matches) == 1:
            return symbol_matches[0]

        trade_dt = cls._parse_datetime_value(trade_time)
        if trade_dt and symbol_matches:
            eligible_matches = []
            for bot in symbol_matches:
                created_dt = cls._parse_datetime_value(bot.get("created_at"))
                if created_dt and created_dt <= trade_dt:
                    eligible_matches.append((created_dt, bot))

            if len(eligible_matches) == 1:
                return eligible_matches[0][1]
        return None

    @staticmethod
    def _extract_bot_id_from_order_link_id(
        raw_order_link_id: Optional[str],
    ) -> Optional[str]:
        if not isinstance(raw_order_link_id, str):
            return None

        order_link_id = raw_order_link_id.strip()
        if not order_link_id:
            return None

        if order_link_id.startswith("bv2:"):
            parts = order_link_id.split(":")
            if len(parts) >= 2 and parts[1]:
                logger.debug(
                    "PnL: Parsed v2 orderLinkId, bot_id_16=%s",
                    parts[1],
                )
                return parts[1]

        for prefix in (
            "bot:",
            "scalp:",
            "init:",
            "qtp:",
            "scalp_mkt:",
            "cls:",
            "nlp:",
        ):
            if order_link_id.startswith(prefix):
                parts = order_link_id.split(":")
                if len(parts) >= 2 and parts[1]:
                    logger.debug(
                        "PnL: Parsed %s orderLinkId, bot_id prefix=%s",
                        prefix.rstrip(":"),
                        parts[1],
                    )
                    return parts[1]

        for pattern in (
            r"^(?:close|gen)_([0-9a-fA-F-]{8,36})_",
            r"^recovery_so_([0-9a-fA-F-]{8,36})_",
        ):
            match = re.match(pattern, order_link_id)
            if match:
                logger.debug(
                    "PnL: Parsed synthetic orderLinkId, bot_id prefix=%s",
                    match.group(1),
                )
                return match.group(1)

        return None

    @staticmethod
    def _classify_order_link_id_source(
        record_order_link_id: Optional[str],
        execution_order_link_id: Optional[str],
    ) -> Optional[str]:
        if str(record_order_link_id or "").strip():
            return "closed_pnl"
        if str(execution_order_link_id or "").strip():
            return "execution_lookup"
        return None

    def _build_execution_order_link_lookup(
        self,
        order_ids: Iterable[str],
        symbols: Iterable[str],
    ) -> Dict[str, str]:
        pending_ids: Set[str] = {
            str(order_id or "").strip()
            for order_id in order_ids
            if str(order_id or "").strip()
        }
        if not pending_ids:
            return {}

        order_link_lookup: Dict[str, str] = {}
        unique_symbols = [
            symbol_name
            for symbol_name in sorted(
                {
                    str(symbol or "").strip().upper()
                    for symbol in symbols
                    if str(symbol or "").strip()
                }
            )
            if symbol_name
        ]

        def consume_execution_response(response: Dict[str, Any]) -> None:
            if not response.get("success"):
                return
            rows = (response.get("data") or {}).get("list", []) or []
            for row in rows:
                order_id = str(row.get("orderId") or "").strip()
                order_link_id = str(row.get("orderLinkId") or "").strip()
                if (
                    order_id
                    and order_link_id
                    and order_id in pending_ids
                    and order_id not in order_link_lookup
                ):
                    order_link_lookup[order_id] = order_link_id
                    pending_ids.discard(order_id)

        try:
            consume_execution_response(
                self.client.get_executions(
                    limit=min(100, max(20, len(pending_ids) * 4)),
                    skip_cache=False,
                )
            )
        except Exception as exc:
            logger.debug("PnL: Execution lookup failed: %s", exc)

        if not pending_ids:
            return order_link_lookup

        try:
            consume_execution_response(
                self.client.get_executions(
                    limit=min(100, max(20, len(pending_ids) * 4)),
                    skip_cache=True,
                )
            )
        except Exception as exc:
            logger.debug("PnL: Execution REST fallback failed: %s", exc)

        if not pending_ids:
            return order_link_lookup

        for symbol_name in unique_symbols[:5]:
            try:
                consume_execution_response(
                    self.client.get_executions(
                        symbol=symbol_name,
                        limit=100,
                        skip_cache=True,
                    )
                )
            except Exception as exc:
                logger.debug(
                    "PnL: Symbol execution lookup failed for %s (%s)",
                    symbol_name,
                    exc,
                )
            if not pending_ids:
                break

        return order_link_lookup

    @staticmethod
    def _apply_bot_metadata(
        entry: Dict[str, Any],
        bot: Dict[str, Any],
        overwrite: bool = True,
    ) -> bool:
        updated = False
        metadata = {
            "bot_id": bot.get("id"),
            "bot_investment": bot.get("investment"),
            "bot_leverage": bot.get("leverage"),
            "bot_mode": bot.get("mode"),
            "bot_range_mode": bot.get("range_mode"),
            "bot_started_at": bot.get("started_at"),
            "bot_profile": bot.get("small_capital_profile") or bot.get("profile"),
            "effective_step_pct": bot.get("effective_step_pct"),
            "fee_aware_min_step_pct": bot.get("fee_aware_min_step_pct"),
            "runtime_open_order_cap_total": bot.get("runtime_open_order_cap_total"),
            "atr_5m_pct": bot.get("atr_5m_pct"),
            "atr_15m_pct": bot.get("atr_15m_pct"),
            "regime_effective": bot.get("regime_effective"),
        }

        for field_name, value in metadata.items():
            current_value = entry.get(field_name)
            if not overwrite and current_value not in (None, ""):
                continue
            if current_value != value:
                entry[field_name] = value
                updated = True

        return updated

    @staticmethod
    def _apply_order_ownership_snapshot(
        entry: Dict[str, Any],
        snapshot: Dict[str, Any],
        overwrite: bool = True,
    ) -> bool:
        updated = False
        metadata_fields = (
            "bot_id",
            "bot_investment",
            "bot_leverage",
            "bot_mode",
            "bot_range_mode",
            "bot_started_at",
            "bot_profile",
            "effective_step_pct",
            "fee_aware_min_step_pct",
            "runtime_open_order_cap_total",
            "atr_5m_pct",
            "atr_15m_pct",
            "regime_effective",
            "ownership_state",
            "ownership_source",
            "ownership_action",
            "ownership_close_reason",
            "experiment_tags",
            "experiment_details",
            "experiment_attribution_state",
            "entry_story",
            "opening_sizing",
            "profit_protection_advisory",
            "profit_protection_shadow",
        )
        snapshot_mapping = {
            "bot_id": snapshot.get("bot_id"),
            "bot_investment": snapshot.get("bot_investment"),
            "bot_leverage": snapshot.get("bot_leverage"),
            "bot_mode": snapshot.get("bot_mode"),
            "bot_range_mode": snapshot.get("bot_range_mode"),
            "bot_started_at": snapshot.get("bot_started_at"),
            "bot_profile": snapshot.get("bot_profile"),
            "effective_step_pct": snapshot.get("effective_step_pct"),
            "fee_aware_min_step_pct": snapshot.get("fee_aware_min_step_pct"),
            "runtime_open_order_cap_total": snapshot.get("runtime_open_order_cap_total"),
            "atr_5m_pct": snapshot.get("atr_5m_pct"),
            "atr_15m_pct": snapshot.get("atr_15m_pct"),
            "regime_effective": snapshot.get("regime_effective"),
            "ownership_state": snapshot.get("owner_state"),
            "ownership_source": snapshot.get("source"),
            "ownership_action": snapshot.get("action"),
            "ownership_close_reason": snapshot.get("close_reason"),
            "experiment_tags": list(snapshot.get("experiment_tags") or []),
            "experiment_details": dict(snapshot.get("experiment_details") or {}),
            "experiment_attribution_state": (
                str(snapshot.get("experiment_attribution_state") or "").strip()
                or "none"
            ),
            "entry_story": dict(snapshot.get("entry_story") or {}),
            "opening_sizing": dict(snapshot.get("opening_sizing") or {}),
            "profit_protection_advisory": dict(
                snapshot.get("profit_protection_advisory") or {}
            ),
            "profit_protection_shadow": dict(
                snapshot.get("profit_protection_shadow") or {}
            ),
        }
        for field_name in metadata_fields:
            value = snapshot_mapping.get(field_name)
            current_value = entry.get(field_name)
            if not overwrite and current_value not in (None, ""):
                continue
            if current_value != value:
                entry[field_name] = value
                updated = True
        return updated

    def _get_order_ownership_snapshot(
        self,
        *,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.order_ownership_service:
            return None
        try:
            return self.order_ownership_service.get_order_ownership(
                order_id=order_id,
                order_link_id=order_link_id,
            )
        except Exception as exc:
            logger.debug(
                "PnL: Ownership snapshot lookup failed for order_id=%s order_link_id=%s (%s)",
                order_id,
                order_link_id,
                exc,
            )
            return None

    @contextmanager
    def _file_lock(self, exclusive: bool = False):
        """
        Context manager for file locking.

        Args:
            exclusive: If True, acquire exclusive lock (for writes).
                      If False, acquire shared lock (for reads).
        """
        with file_lock(self.lock_path, exclusive=exclusive) as lock_fd:
            yield lock_fd

    def _read_logs(self) -> List[Dict[str, Any]]:
        """
        Read all trade logs from the JSON file with locking.

        Returns:
            List of log entries, or empty list on error
        """
        try:
            with self._file_lock(exclusive=False):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            return []

    def _write_logs(self, logs: List[Dict[str, Any]]) -> None:
        """
        Write all trade logs to the JSON file with locking.
        Uses atomic write pattern.

        Args:
            logs: List of log entries to write
        """
        try:
            with self._file_lock(exclusive=True):
                # Write to temporary file first (atomic write pattern)
                dir_path = self.file_path.parent
                fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(logs, f, indent=2, ensure_ascii=False)
                    # Atomic rename
                    os.replace(temp_path, self.file_path)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
        except (IOError, OSError) as e:
            logger.warning(f"Failed to write trade logs: {e}")

    def sync_closed_pnl(self, symbol: Optional[str] = None) -> None:
        """
        Sync closed PnL records from Bybit to local storage.

        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT")
        """
        response = self.client.get_closed_pnl(symbol=symbol, limit=100)

        if not response.get("success"):
            return

        # Get current wallet balance to store with new entries
        current_balance = None
        try:
            wallet_resp = self.client.get_wallet_balance()
            if wallet_resp.get("success"):
                coins = wallet_resp.get("data", {}).get("list", [{}])[0].get("coin", [])
                for coin in coins:
                    if coin.get("coin") == "USDT":
                        current_balance = float(coin.get("walletBalance", 0) or 0)
                        break
        except Exception:
            pass  # Continue without balance if fetch fails

        try:
            data = response.get("data", {})
            pnl_list = data.get("list", [])

            if not pnl_list:
                return

            logs = self._read_logs()
            existing_entries_by_id = {
                str(log.get("id") or "").strip(): log
                for log in logs
                if str(log.get("id") or "").strip()
            }
            all_bots = self.bot_storage.list_bots() if self.bot_storage else []

            candidate_order_ids = []
            candidate_symbols = []
            for record in pnl_list:
                record_id = str(record.get("orderId") or record.get("execId") or "").strip()
                if not record_id:
                    created_time = record.get("createdTime", "")
                    symbol_name = record.get("symbol", "")
                    record_id = f"{symbol_name}_{created_time}"
                existing_entry = existing_entries_by_id.get(record_id)
                raw_order_link_id = record.get("orderLinkId") or record.get(
                    "order_link_id"
                )
                ownership_snapshot = self._get_order_ownership_snapshot(
                    order_id=record_id,
                    order_link_id=raw_order_link_id,
                )
                snapshot_order_link_id = (
                    str((ownership_snapshot or {}).get("order_link_id") or "").strip()
                    or None
                )
                if raw_order_link_id:
                    continue
                if snapshot_order_link_id:
                    continue
                if (
                    existing_entry
                    and existing_entry.get("bot_id")
                    and existing_entry.get("order_link_id")
                ):
                    continue
                candidate_order_ids.append(record_id)
                candidate_symbols.append(record.get("symbol"))

            execution_order_link_lookup = self._build_execution_order_link_lookup(
                candidate_order_ids,
                candidate_symbols,
            )

            new_entries = []
            updated_existing = False
            warned_ambiguous_symbols = set()
            changed_bot_ids: Set[str] = set()
            changed_symbols: Set[str] = set()
            unattributed_symbols: Set[str] = set()
            for record in pnl_list:
                record_id = str(record.get("orderId") or record.get("execId") or "").strip()
                if not record_id:
                    created_time = record.get("createdTime", "")
                    symbol_name = record.get("symbol", "")
                    record_id = f"{symbol_name}_{created_time}"

                # Parse timestamp
                created_time = record.get("createdTime", "")
                try:
                    if created_time:
                        ts_ms = int(created_time)
                        time_iso = datetime.fromtimestamp(
                            ts_ms / 1000, tz=timezone.utc
                        ).isoformat()
                    else:
                        time_iso = datetime.now(timezone.utc).isoformat()
                except (ValueError, TypeError):
                    time_iso = datetime.now(timezone.utc).isoformat()

                # Parse realized PnL
                try:
                    realized_pnl = float(record.get("closedPnl", 0) or 0)
                except (ValueError, TypeError):
                    realized_pnl = 0.0

                closed_pnl_order_link_id = record.get("orderLinkId") or record.get(
                    "order_link_id"
                )
                ownership_snapshot = self._get_order_ownership_snapshot(
                    order_id=record_id,
                    order_link_id=closed_pnl_order_link_id,
                )
                snapshot_order_link_id = (
                    str((ownership_snapshot or {}).get("order_link_id") or "").strip()
                    or None
                )
                execution_order_link_id = execution_order_link_lookup.get(record_id)
                raw_order_link_id = (
                    closed_pnl_order_link_id
                    or snapshot_order_link_id
                    or execution_order_link_id
                )
                order_link_id_source = self._classify_order_link_id_source(
                    closed_pnl_order_link_id,
                    execution_order_link_id,
                )
                if not order_link_id_source and snapshot_order_link_id:
                    order_link_id_source = "ownership_snapshot"
                parsed_bot_id = self._extract_bot_id_from_order_link_id(raw_order_link_id)

                symbol = record.get("symbol", "")
                side = record.get("side", "")
                order_id = str(record.get("orderId") or record_id or "").strip() or None
                exec_id = str(record.get("execId") or "").strip() or None
                cost_fields = self._extract_cost_fields(record)
                raw_position_idx = record.get("positionIdx", record.get("position_idx"))
                try:
                    position_idx = int(raw_position_idx)
                except (TypeError, ValueError):
                    position_idx = None
                if position_idx is None and ownership_snapshot:
                    try:
                        raw_snapshot_position_idx = ownership_snapshot.get("position_idx")
                        position_idx = (
                            int(raw_snapshot_position_idx)
                            if raw_snapshot_position_idx is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        position_idx = None
                attribution_source = "unattributed"

                # Look up bot config if available
                bot = None
                if ownership_snapshot and ownership_snapshot.get("bot_id"):
                    bot = ownership_snapshot
                    attribution_source = "ownership_snapshot"
                elif all_bots:
                    if parsed_bot_id:
                        bot = self._resolve_bot_from_prefix(
                            parsed_bot_id, symbol, all_bots
                        )
                        if bot:
                            logger.debug(
                                "PnL: Matched parsed bot_id '%s' to bot '%s'",
                                parsed_bot_id,
                                bot.get("id"),
                            )
                            attribution_source = (
                                f"order_link_id:{order_link_id_source}"
                                if order_link_id_source
                                else "order_link_id"
                            )
                        else:
                            logger.debug(
                                "PnL: Could not resolve parsed bot_id '%s' for symbol '%s'",
                                parsed_bot_id,
                                symbol,
                            )
                            attribution_source = "order_link_id_unresolved"

                    if not bot and symbol and not raw_order_link_id:
                        bot = self._resolve_unique_bot_for_symbol(
                            symbol, all_bots, time_iso
                        )
                        if bot:
                            logger.debug(
                                "PnL: Fallback - unique bot found for symbol '%s'",
                                symbol,
                            )
                            attribution_source = "unique_symbol_fallback"
                        elif (
                            not existing_entries_by_id.get(record_id)
                            and
                            len(self._get_symbol_bots(symbol, all_bots)) > 1
                            and symbol not in warned_ambiguous_symbols
                        ):
                            warned_ambiguous_symbols.add(symbol)
                            logger.warning(
                                "PnL: Multiple bots found for symbol '%s'; leaving trade unattributed",
                                symbol,
                            )
                            attribution_source = "ambiguous_symbol"
                    elif not bot and raw_order_link_id:
                        if str(raw_order_link_id).startswith("close_manual_"):
                            attribution_source = "manual_close"
                        elif str(raw_order_link_id).startswith("ambg:"):
                            attribution_source = "explicit_ambiguous_close"
                        elif parsed_bot_id:
                            attribution_source = "order_link_id_unresolved"
                        else:
                            attribution_source = "explicit_order_link_id_unmapped"

                existing_entry = existing_entries_by_id.get(record_id)
                if existing_entry:
                    entry_updated = False
                    if (
                        current_balance is not None
                        and existing_entry.get("balance_after") is None
                    ):
                        existing_entry["balance_after"] = current_balance
                        entry_updated = True
                    if raw_order_link_id and existing_entry.get("order_link_id") != raw_order_link_id:
                        existing_entry["order_link_id"] = raw_order_link_id
                        entry_updated = True
                    if order_id and existing_entry.get("order_id") != order_id:
                        existing_entry["order_id"] = order_id
                        entry_updated = True
                    if exec_id and existing_entry.get("exec_id") != exec_id:
                        existing_entry["exec_id"] = exec_id
                        entry_updated = True
                    if position_idx is not None and existing_entry.get("position_idx") != position_idx:
                        existing_entry["position_idx"] = position_idx
                        entry_updated = True
                    if existing_entry.get("attribution_source") != attribution_source:
                        existing_entry["attribution_source"] = attribution_source
                        entry_updated = True
                    for key, value in cost_fields.items():
                        if existing_entry.get(key) != value:
                            existing_entry[key] = value
                            entry_updated = True
                    if ownership_snapshot and ownership_snapshot.get("bot_id"):
                        entry_updated = (
                            self._apply_order_ownership_snapshot(
                                existing_entry,
                                ownership_snapshot,
                                overwrite=False,
                            )
                            or entry_updated
                        )
                    elif bot:
                        entry_updated = (
                            self._apply_bot_metadata(
                                existing_entry,
                                bot,
                                overwrite=False,
                            )
                            or entry_updated
                        )
                    if entry_updated:
                        updated_existing = True
                        if existing_entry.get("bot_id"):
                            changed_bot_ids.add(str(existing_entry.get("bot_id")))
                        if symbol:
                            changed_symbols.add(str(symbol).strip().upper())
                        if attribution_source in (
                            "unattributed",
                            "order_link_id_unresolved",
                            "explicit_order_link_id_unmapped",
                            "ambiguous_symbol",
                        ) and symbol:
                            unattributed_symbols.add(str(symbol).strip().upper())
                    continue

                entry = {
                    "id": record_id,
                    "order_id": order_id,
                    "exec_id": exec_id,
                    "time": time_iso,
                    "symbol": symbol,
                    "side": side,
                    "realized_pnl": realized_pnl,
                    "balance_after": current_balance,
                    "order_link_id": raw_order_link_id,
                    "position_idx": position_idx,
                    "attribution_source": attribution_source,
                    "bot_id": None,
                    "bot_investment": None,
                    "bot_leverage": None,
                    "bot_mode": None,
                    "bot_range_mode": None,
                    "bot_started_at": None,
                    "bot_profile": None,
                    "effective_step_pct": None,
                    "fee_aware_min_step_pct": None,
                    "runtime_open_order_cap_total": None,
                    "atr_5m_pct": None,
                    "atr_15m_pct": None,
                    "regime_effective": None,
                    "ownership_state": None,
                    "ownership_source": None,
                    "ownership_action": None,
                    "ownership_close_reason": None,
                    "experiment_tags": [],
                    "experiment_details": {},
                }
                entry.update(cost_fields)

                if ownership_snapshot and ownership_snapshot.get("bot_id"):
                    self._apply_order_ownership_snapshot(entry, ownership_snapshot)
                elif bot:
                    self._apply_bot_metadata(entry, bot)

                new_entries.append(entry)
                existing_entries_by_id[record_id] = entry
                self._record_trade_forensic_outcome(
                    entry,
                    ownership_snapshot=ownership_snapshot,
                )
                if entry.get("bot_id"):
                    changed_bot_ids.add(str(entry.get("bot_id")))
                if symbol:
                    changed_symbols.add(str(symbol).strip().upper())
                if attribution_source in (
                    "unattributed",
                    "order_link_id_unresolved",
                    "explicit_order_link_id_unmapped",
                    "ambiguous_symbol",
                ) and symbol:
                    unattributed_symbols.add(str(symbol).strip().upper())

                if self.risk_manager and symbol:
                    try:
                        self.risk_manager.record_symbol_trade(symbol, realized_pnl, time_iso)
                    except Exception as exc:
                        logger.debug(
                            "PnL: Failed to record symbol daily trade for %s (%s)",
                            symbol,
                            exc,
                        )

                if self.symbol_training_service and symbol:
                    try:
                        self.symbol_training_service.record_trade_outcome(symbol, entry)
                    except Exception as exc:
                        logger.debug(
                            "PnL: Failed to record symbol training trade for %s (%s)",
                            symbol,
                            exc,
                        )

            if new_entries or updated_existing:
                logs.extend(new_entries)
                logs.sort(key=lambda row: row.get("time", ""))
                self._write_logs(logs)
                if self.symbol_pnl_service:
                    self.symbol_pnl_service.rebuild_from_logs(logs)
                self._run_scope_watchdogs(
                    logs,
                    bot_ids=changed_bot_ids,
                    symbols=unattributed_symbols or changed_symbols,
                )

        except (KeyError, TypeError, ValueError):
            pass  # Silently fail on parse errors

    def backfill_bot_info(self) -> int:
        """
        Backfill bot info (investment, leverage, mode, range_mode) for existing trade logs.

        Matches trades to bots by symbol and updates logs that are missing bot info.

        Returns:
            Number of records updated
        """
        if not self.bot_storage:
            return 0

        logs = self._read_logs()
        all_bots = self.bot_storage.list_bots()

        updated_count = 0
        for log in logs:
            # Skip if already has bot info
            if log.get("bot_investment") is not None:
                continue

            symbol = log.get("symbol")
            if not symbol:
                continue

            bot = None
            existing_bot_id = log.get("bot_id")
            if existing_bot_id:
                bot = self._resolve_bot_from_prefix(existing_bot_id, symbol, all_bots)
            if not bot:
                bot = self._resolve_unique_bot_for_symbol(
                    symbol, all_bots, log.get("time")
                )
            if bot:
                log["bot_id"] = bot.get("id")
                log["bot_investment"] = bot.get("investment")
                log["bot_leverage"] = bot.get("leverage")
                log["bot_mode"] = bot.get("mode")
                log["bot_range_mode"] = bot.get("range_mode")
                updated_count += 1

        if updated_count > 0:
            self._write_logs(logs)

        return updated_count

    def update_bots_realized_pnl(self) -> None:
        """
        Aggregate realized PnL per bot_id from the trade logs and write the totals into bots.json.

        Behavior:
          - If self.bot_storage is None, do nothing.
          - Read all logs via self._read_logs().
          - Build a dict totals = { bot_id: sum(realized_pnl) } for all log entries with a non-empty bot_id.
          - Load all bots via self.bot_storage.list_bots().
          - For each bot:
              - Determine its id (bot["id"]).
              - Look up total_realized = totals.get(bot_id, 0.0).
              - Set bot["realized_pnl"] = total_realized (float).
              - Keep bot["unrealized_pnl"] as-is if present (or default 0.0).
              - Set bot["total_pnl"] = realized_pnl + unrealized_pnl.
              - Save the bot back via self.bot_storage.save_bot(bot).
        """
        if self.bot_storage is None:
            return

        logs = self._read_logs()

        # Build totals dict: { bot_id: sum(realized_pnl) }
        totals: Dict[str, float] = {}
        baseline_cache: Dict[str, Optional[datetime]] = {}
        for log in logs:
            bot_id = log.get("bot_id")
            if not bot_id:
                continue
            bot_id = str(bot_id).strip()
            if not bot_id:
                continue

            baseline_dt = baseline_cache.get(bot_id)
            if bot_id not in baseline_cache:
                baseline_dt = self._baseline_started_at(bot_id=bot_id)
                baseline_cache[bot_id] = baseline_dt
            if baseline_dt is not None:
                log_dt = self._parse_datetime_value(log.get("time"))
                if log_dt is None or log_dt < baseline_dt:
                    continue

            realized_pnl = log.get("realized_pnl")
            try:
                realized_pnl = float(realized_pnl)
            except (ValueError, TypeError):
                continue

            if bot_id in totals:
                totals[bot_id] += realized_pnl
            else:
                totals[bot_id] = realized_pnl

        # Load all bots and update their realized_pnl
        bots = self.bot_storage.list_bots()
        for bot in bots:
            bot_id = bot.get("id")
            if not bot_id:
                continue

            total_realized = totals.get(bot_id, 0.0)

            # Get current unrealized_pnl or default to 0.0
            try:
                unrealized_pnl = float(bot.get("unrealized_pnl") or 0.0)
            except (ValueError, TypeError):
                unrealized_pnl = 0.0

            bot["realized_pnl"] = total_realized
            bot["total_pnl"] = total_realized + unrealized_pnl
            tp_baseline = self._safe_float(bot.get("tp_session_realized_baseline"), 0.0) or 0.0
            if tp_baseline > total_realized:
                bot["tp_session_realized_baseline"] = total_realized

            self.bot_storage.save_bot(bot, allow_pnl_override=True)

    def get_log(
        self,
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        use_global_baseline: bool = False,
        baseline_started_at: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all trade logs sorted by time (oldest first).

        Returns:
            List of log entries sorted by time
        """
        logs = self._read_logs()
        logs = self._filter_logs(
            logs,
            bot_id=bot_id,
            symbol=symbol,
            use_global_baseline=use_global_baseline,
            baseline_started_at=baseline_started_at,
        )

        # Sort by time field (ISO 8601 strings sort correctly)
        logs.sort(key=lambda x: x.get("time", ""))

        return logs

    def get_today_stats(
        self,
        today: Optional[date] = None,
        *,
        use_global_baseline: bool = False,
    ) -> Dict[str, Any]:
        """
        Get statistics for today's trades.

        Args:
            today: Optional date to use (defaults to UTC today)

        Returns:
            Dict with net PnL, wins count, and losses count
        """
        if today is None:
            today = datetime.now(timezone.utc).date()

        logs = self._filter_logs(
            self._read_logs(),
            use_global_baseline=use_global_baseline,
        )

        net = 0.0
        wins = 0
        losses = 0

        for log in logs:
            time_str = log.get("time", "")
            if not time_str:
                continue

            try:
                # Parse ISO 8601 timestamp
                log_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                log_date = log_time.date()
            except (ValueError, TypeError):
                continue

            if log_date != today:
                continue

            realized_pnl = log.get("realized_pnl", 0)
            try:
                realized_pnl = float(realized_pnl)
            except (ValueError, TypeError):
                realized_pnl = 0.0

            net += realized_pnl

            if realized_pnl > 0:
                wins += 1
            elif realized_pnl < 0:
                losses += 1

        return {"net": round(net, 4), "wins": wins, "losses": losses}

    def get_trade_statistics(
        self,
        period: str = "all",
        *,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        use_global_baseline: bool = False,
    ) -> Dict[str, Any]:
        """
        Get comprehensive trade statistics like Bybit's profitable trades panel.

        Args:
            period: "today", "7d", "30d", or "all"

        Returns:
            Dict with win rate, profit factor, average win/loss, etc.
        """
        logs = self._filter_logs(
            self._read_logs(),
            bot_id=bot_id,
            symbol=symbol,
            use_global_baseline=use_global_baseline,
        )

        # Filter by period
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "7d":
            cutoff = now - timedelta(days=7)
        elif period == "30d":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None

        filtered_logs = []
        for log in logs:
            if cutoff:
                time_str = log.get("time", "")
                if not time_str:
                    continue
                try:
                    log_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if log_time < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            filtered_logs.append(log)

        # Calculate statistics
        total_trades = len(filtered_logs)
        wins = 0
        losses = 0
        total_profit = 0.0
        total_loss = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        win_pnls = []
        loss_pnls = []

        for log in filtered_logs:
            try:
                pnl = float(log.get("realized_pnl", 0) or 0)
            except (ValueError, TypeError):
                continue

            if pnl > 0:
                wins += 1
                total_profit += pnl
                win_pnls.append(pnl)
                if pnl > largest_win:
                    largest_win = pnl
            elif pnl < 0:
                losses += 1
                total_loss += abs(pnl)
                loss_pnls.append(abs(pnl))
                if abs(pnl) > largest_loss:
                    largest_loss = abs(pnl)

        # Calculate derived stats
        net_pnl = total_profit - total_loss
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        profit_factor = (
            (total_profit / total_loss)
            if total_loss > 0
            else (float("inf") if total_profit > 0 else 0.0)
        )
        avg_win = (total_profit / wins) if wins > 0 else 0.0
        avg_loss = (total_loss / losses) if losses > 0 else 0.0

        return {
            "period": period,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "total_profit": round(total_profit, 4),
            "total_loss": round(total_loss, 4),
            "total_pnl": round(net_pnl, 4),  # Legacy field name support
            "net_pnl": round(net_pnl, 4),
            "profit_factor": round(profit_factor, 2)
            if profit_factor != float("inf")
            else "∞",
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "largest_win": round(largest_win, 4),
            "largest_loss": round(largest_loss, 4),
        }

    def get_analytics_data(
        self,
        period: str = "all",
        symbol: str = None,
        bot_id: str = None,
        use_global_baseline: bool = False,
    ) -> Dict[str, Any]:
        """
        Get structured analytics data for charting with optional filters.

        Args:
            period: "today", "7d", "30d", or "all"
            symbol: Optional symbol filter (e.g. "BTCUSDT")
            bot_id: Optional bot ID filter

        Returns:
            Dict with equity_curve, daily_pnl, aggregate metrics, and
            available_filters for dropdown population.
        """
        # Fetch all logs (unfiltered) for available_filters, then narrow for metrics.
        all_logs = self.get_log(
            use_global_baseline=use_global_baseline and not bool(bot_id),
        )
        filtered_logs = self.get_log(
            bot_id=bot_id,
            symbol=symbol,
            use_global_baseline=use_global_baseline and not bool(bot_id),
        )

        # Determine period cutoff
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "7d":
            cutoff = now - timedelta(days=7)
        elif period == "30d":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None

        def _apply_period_cutoff(logs_list):
            result = []
            for log in logs_list:
                time_str = log.get("time", "")
                if not time_str:
                    continue
                if cutoff:
                    try:
                        log_time = datetime.fromisoformat(
                            time_str.replace("Z", "+00:00")
                        )
                        if log_time < cutoff:
                            continue
                    except (ValueError, TypeError):
                        continue
                result.append(log)
            return result

        # All period-scoped logs (for available_filters — shows ALL symbols/bots)
        all_period_logs = _apply_period_cutoff(all_logs)
        # Filtered period-scoped logs (for metrics computation)
        period_logs = _apply_period_cutoff(filtered_logs)

        # Collect available filters from ALL period-scoped logs (not filtered ones)
        avail_symbols = sorted(
            set(l.get("symbol", "") for l in all_period_logs if l.get("symbol"))
        )
        seen_bots = {}
        for l in all_period_logs:
            bid = l.get("bot_id")
            if bid and bid not in seen_bots:
                seen_bots[bid] = {
                    "id": bid,
                    "symbol": l.get("symbol", ""),
                    "mode": l.get("bot_mode", ""),
                }
        avail_bots = list(seen_bots.values())

        # Pass 2: optionally narrow by symbol/bot, then compute everything
        equity_curve = []
        daily_map = {}  # date_str -> pnl sum
        cum_pnl = 0.0
        max_pnl = 0.0
        max_drawdown = 0.0

        wins = 0
        losses = 0
        breakeven_trades = 0
        total_profit = 0.0
        total_loss = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        outcomes = []  # +1 win, -1 loss, 0 breakeven

        for log in period_logs:
            if symbol and log.get("symbol") != symbol:
                continue
            if bot_id and log.get("bot_id") != bot_id:
                continue

            time_str = log.get("time", "")
            try:
                log_time = datetime.fromisoformat(
                    time_str.replace("Z", "+00:00")
                )
                pnl = float(log.get("realized_pnl", 0) or 0)
            except (ValueError, TypeError):
                continue

            # Equity curve
            cum_pnl += pnl
            if cum_pnl > max_pnl:
                max_pnl = cum_pnl
            drawdown = max_pnl - cum_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

            equity_curve.append(
                {
                    "time": time_str,
                    "value": round(cum_pnl, 4),
                    "drawdown": round(drawdown, 4),
                }
            )

            # Daily aggregation
            log_date = log_time.date().isoformat()
            daily_map[log_date] = daily_map.get(log_date, 0.0) + pnl

            # Win/loss tracking
            if pnl > 0:
                wins += 1
                total_profit += pnl
                if pnl > largest_win:
                    largest_win = pnl
                outcomes.append(1)
            elif pnl < 0:
                losses += 1
                total_loss += abs(pnl)
                if abs(pnl) > largest_loss:
                    largest_loss = abs(pnl)
                outcomes.append(-1)
            else:
                breakeven_trades += 1
                outcomes.append(0)

        # Daily PnL sorted
        daily_pnl = []
        for d in sorted(daily_map.keys()):
            daily_pnl.append({"date": d, "value": round(daily_map[d], 4)})

        # Derived statistics
        total_trades = wins + losses + breakeven_trades
        net_pnl = total_profit - total_loss
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        loss_rate = 100.0 - win_rate if total_trades > 0 else 0.0
        profit_factor = (
            (total_profit / total_loss)
            if total_loss > 0
            else (float("inf") if total_profit > 0 else 0.0)
        )
        avg_win = (total_profit / wins) if wins > 0 else 0.0
        avg_loss = (total_loss / losses) if losses > 0 else 0.0
        avg_trade = (net_pnl / total_trades) if total_trades > 0 else 0.0
        payoff_ratio = (
            (avg_win / avg_loss)
            if avg_loss > 0
            else (float("inf") if avg_win > 0 else 0.0)
        )
        expectancy = (win_rate / 100 * avg_win) - (loss_rate / 100 * avg_loss)
        max_drawdown_pct = (
            (max_drawdown / max_pnl * 100) if max_pnl > 0 else 0.0
        )

        # Best / worst day
        best_day = {"date": None, "value": 0.0}
        worst_day = {"date": None, "value": 0.0}
        for d, val in daily_map.items():
            if best_day["date"] is None or val > best_day["value"]:
                best_day = {"date": d, "value": round(val, 4)}
            if worst_day["date"] is None or val < worst_day["value"]:
                worst_day = {"date": d, "value": round(val, 4)}

        # Streaks
        current_streak = 0
        longest_win_streak = 0
        longest_loss_streak = 0
        temp_streak = 0
        for outcome in outcomes:
            if outcome == 0:
                continue
            if outcome > 0:
                temp_streak = temp_streak + 1 if temp_streak > 0 else 1
            else:
                temp_streak = temp_streak - 1 if temp_streak < 0 else -1
            if temp_streak > 0:
                longest_win_streak = max(longest_win_streak, temp_streak)
            elif temp_streak < 0:
                longest_loss_streak = max(longest_loss_streak, abs(temp_streak))
        current_streak = temp_streak

        pf_display = (
            round(profit_factor, 2)
            if profit_factor != float("inf")
            else "\u221e"
        )
        pr_display = (
            round(payoff_ratio, 2)
            if payoff_ratio != float("inf")
            else "\u221e"
        )

        return {
            "period": period,
            "equity_curve": equity_curve,
            "daily_pnl": daily_pnl,
            "available_filters": {
                "symbols": avail_symbols,
                "bots": avail_bots,
            },
            "metrics": {
                # Existing fields (backward compat)
                "max_drawdown": round(max_drawdown, 4),
                "total_profit": round(total_profit, 4),
                "total_loss": round(total_loss, 4),
                "net_pnl": round(net_pnl, 4),
                "profit_factor": pf_display,
                "win_rate": round(win_rate, 2),
                "total_trades": total_trades,
                # New fields
                "wins": wins,
                "losses": losses,
                "breakeven_trades": breakeven_trades,
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "avg_trade": round(avg_trade, 4),
                "largest_win": round(largest_win, 4),
                "largest_loss": round(largest_loss, 4),
                "payoff_ratio": pr_display,
                "expectancy": round(expectancy, 4),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "best_day": best_day,
                "worst_day": worst_day,
                "current_streak": current_streak,
                "longest_win_streak": longest_win_streak,
                "longest_loss_streak": longest_loss_streak,
            },
        }
