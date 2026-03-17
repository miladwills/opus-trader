import csv
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.audit_diagnostics_service import AuditDiagnosticsService
from services.backtest.mock_client import MockBybitClient
from services.bot_storage_service import BotStorageService
from services.decision_snapshot_service import DecisionSnapshotService
from services.grid_bot_service import GridBotService
from services.grid_engine_service import GridEngineService
from services.indicator_service import IndicatorService
from services.order_ownership_service import OrderOwnershipService
from services.pnl_service import PnlService
from services.risk_manager_service import RiskManagerService
from services.symbol_pnl_service import SymbolPnlService
from services.trade_forensics_service import TradeForensicsService

logger = logging.getLogger(__name__)

MIN_WARMUP_CANDLES = 100


class BacktestEngine:
    """Bounded candle-driven replay engine that reuses live decision logic."""

    SUPPORTED_MODES = {"long", "short"}

    def __init__(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1000.0,
        *,
        timeframe: str = "15",
        storage_root: str = "storage/backtest_runs",
        run_id: Optional[str] = None,
        warmup_candles: int = MIN_WARMUP_CANDLES,
        maker_fee_bps: float = 2.0,
        taker_fee_bps: float = 5.5,
        market_slippage_bps: float = 5.0,
    ) -> None:
        self.symbol = str(symbol or "").strip().upper()
        self.start_date = start_date
        self.end_date = end_date
        self.timeframe = str(timeframe or "15").strip() or "15"
        self.initial_capital = float(initial_capital)
        self.warmup_candles = max(int(warmup_candles or 0), 1)
        self.maker_fee_bps = max(float(maker_fee_bps or 0.0), 0.0)
        self.taker_fee_bps = max(float(taker_fee_bps or 0.0), 0.0)
        self.market_slippage_bps = max(float(market_slippage_bps or 0.0), 0.0)
        self.run_id = str(run_id or self._build_run_id(self.symbol)).strip()

        root_path = Path(storage_root)
        self.run_dir = root_path / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.paths = {
            "run_dir": str(self.run_dir),
            "bots": str(self.run_dir / "bots.json"),
            "trade_logs": str(self.run_dir / "trade_logs.json"),
            "symbol_pnl": str(self.run_dir / "symbol_pnl.json"),
            "risk_state": str(self.run_dir / "risk_state.json"),
            "order_ownership": str(self.run_dir / "order_ownership.json"),
            "trade_forensics": str(self.run_dir / "trade_forensics.jsonl"),
            "decision_snapshots": str(self.run_dir / "decision_snapshots.json"),
            "audit_diagnostics": str(self.run_dir / "audit_diagnostics.jsonl"),
            "results": str(self.run_dir / "results.json"),
        }

        self.client = MockBybitClient(
            initial_balance=self.initial_capital,
            maker_fee_bps=self.maker_fee_bps,
            taker_fee_bps=self.taker_fee_bps,
            market_slippage_bps=self.market_slippage_bps,
        )
        self.bot_storage = BotStorageService(self.paths["bots"])
        self.trade_forensics_service = TradeForensicsService(self.paths["trade_forensics"])
        self.order_ownership_service = OrderOwnershipService(self.paths["order_ownership"])
        self.decision_snapshot_service = DecisionSnapshotService(
            trade_forensics_service=self.trade_forensics_service,
            file_path=self.paths["decision_snapshots"],
            lookback_seconds=315360000,
        )
        self.audit_diagnostics_service = AuditDiagnosticsService(self.paths["audit_diagnostics"])
        self.symbol_pnl_service = SymbolPnlService(self.paths["symbol_pnl"])
        self.risk_manager = RiskManagerService(self.paths["risk_state"], 0.05, 0.08)
        self.client.set_order_ownership_service(self.order_ownership_service)
        self.client.set_trade_forensics_service(self.trade_forensics_service)
        self.pnl_service = PnlService(
            self.client,
            self.paths["trade_logs"],
            self.bot_storage,
            symbol_pnl_service=self.symbol_pnl_service,
            order_ownership_service=self.order_ownership_service,
            trade_forensics_service=self.trade_forensics_service,
            risk_manager=self.risk_manager,
            audit_diagnostics_service=self.audit_diagnostics_service,
        )
        self.indicator_service = IndicatorService(self.client)
        self.grid_engine = GridEngineService()
        self.bot_service = GridBotService(
            self.client,
            self.bot_storage,
            self.pnl_service,
            self.risk_manager,
            self.grid_engine,
            indicator_service=self.indicator_service,
            trade_forensics_service=self.trade_forensics_service,
        )
        self.bot_service.audit_diagnostics_service = self.audit_diagnostics_service
        if getattr(self.bot_service, "ai_advisor_service", None) is not None:
            self.bot_service.ai_advisor_service.audit_diagnostics_service = (
                self.audit_diagnostics_service
            )

        self.candles: List[Dict[str, Any]] = []
        self.test_bot: Optional[Dict[str, Any]] = None

    @staticmethod
    def _build_run_id(symbol: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        token = str(symbol or "symbol").strip().lower() or "symbol"
        return f"bt_{token}_{ts}_{int(time.time() * 1000) % 100000}"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _load_json_file(path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _write_json_file(self, path: str, payload: Dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            Path(temp_path).replace(target)
        except Exception:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _normalize_candles(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for candle in list(candles or []):
            try:
                normalized.append(
                    {
                        "timestamp": int(candle["timestamp"]),
                        "open": float(candle["open"]),
                        "high": float(candle["high"]),
                        "low": float(candle["low"]),
                        "close": float(candle["close"]),
                        "volume": float(candle.get("volume", 0.0)),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        normalized.sort(key=lambda row: row["timestamp"])
        return normalized

    def load_candles(self, candles: List[Dict[str, Any]]) -> None:
        self.candles = self._normalize_candles(candles)
        self.client.set_history(self.symbol, self.candles)
        logger.info(
            "Backtest %s loaded %s candles for %s",
            self.run_id,
            len(self.candles),
            self.symbol,
        )

    def load_data(self, csv_path: str) -> None:
        rows = []
        with open(csv_path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(row)
        self.load_candles(rows)

    def setup_bot(self, strategy_config: Dict[str, Any]) -> None:
        mode = str(strategy_config.get("mode") or "long").strip().lower()
        if mode not in self.SUPPORTED_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_MODES))
            raise ValueError(
                f"Replayable Backtest Engine v1 supports modes [{supported}] only; got '{mode}'"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        investment = self._safe_float(strategy_config.get("investment"), 100.0)
        leverage = self._safe_float(strategy_config.get("leverage"), 5.0)
        grid_count = max(self._safe_int(strategy_config.get("grid_count"), 10), 2)
        lower_price = self._safe_float(strategy_config.get("lower_price"), 0.0)
        upper_price = self._safe_float(strategy_config.get("upper_price"), 0.0)

        bot = {
            "id": str(strategy_config.get("bot_id") or f"backtest_bot_{self.symbol.lower()}"),
            "symbol": self.symbol,
            "status": "running",
            "mode": mode,
            "profile": str(strategy_config.get("profile") or "normal"),
            "investment": investment,
            "leverage": leverage,
            "grid_lower_price": lower_price,
            "grid_upper_price": upper_price,
            "lower_price": lower_price,
            "upper_price": upper_price,
            "grid_count": grid_count,
            "target_grid_count": grid_count,
            "range_mode": str(strategy_config.get("range_mode") or "fixed"),
            "created_at": now_iso,
            "started_at": now_iso,
            "trading_env": "backtest",
            "paper_trading": False,
            "auto_direction": False,
            "trailing_sl_enabled": bool(strategy_config.get("trailing_sl_enabled", False)),
            "tp_pct": self._safe_float(strategy_config.get("tp_pct"), 0.01),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "auto_margin": {"enabled": bool(strategy_config.get("auto_margin", False))},
            "neutral_volatility_gate_enabled": False,
            "ai_advisor_enabled": False,
            "neutral_grid_initialized": False,
            "neutral_grid": {},
            "replay_run_id": self.run_id,
        }
        for key, value in strategy_config.items():
            if key not in bot:
                bot[key] = value

        self.test_bot = bot
        self.bot_storage.save_bot(bot)
        logger.info(
            "Backtest %s bot setup: %s %s range=%s-%s",
            self.run_id,
            bot["id"],
            mode,
            lower_price,
            upper_price,
        )

    def _build_equity_point(self, candle: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestamp": int(candle["timestamp"]),
            "equity": round(self._safe_float(self.client.usdt_equity), 8),
            "wallet_balance": round(self._safe_float(self.client.wallet_balance), 8),
            "price": round(self._safe_float(candle.get("close")), 8),
            "position_count": len(
                [
                    position
                    for position in list(self.client.positions.values())
                    if self._safe_float(position.get("size")) > 0
                ]
            ),
            "open_order_count": len(list(self.client.open_orders)),
        }

    @staticmethod
    def _decision_status(snapshot: Dict[str, Any]) -> str:
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("closed"):
            return "closed"
        if lifecycle.get("opened"):
            return "opened"
        if lifecycle.get("submitted"):
            return "submitted"
        if lifecycle.get("blocked"):
            return "blocked"
        if lifecycle.get("outcome_status") == "awaiting":
            return "awaiting"
        return "candidate"

    def _build_decision_stream(self, snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        stream = []
        for snapshot in list(snapshots or []):
            lifecycle = dict(snapshot.get("lifecycle") or {})
            decision = dict(snapshot.get("decision") or {})
            gate = dict(decision.get("gate") or {})
            advisor = dict(snapshot.get("advisor") or {})
            stream.append(
                {
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "forensic_decision_id": snapshot.get("forensic_decision_id"),
                    "trade_context_id": snapshot.get("trade_context_id"),
                    "decision_at": snapshot.get("decision_at"),
                    "symbol": snapshot.get("symbol"),
                    "bot_id": snapshot.get("bot_id"),
                    "side": snapshot.get("side"),
                    "mode": snapshot.get("mode"),
                    "decision_type": snapshot.get("decision_type"),
                    "status": self._decision_status(snapshot),
                    "blocked": bool(lifecycle.get("blocked")),
                    "submitted": bool(lifecycle.get("submitted")),
                    "opened": bool(lifecycle.get("opened")),
                    "closed": bool(lifecycle.get("closed")),
                    "outcome_status": lifecycle.get("outcome_status"),
                    "realized_pnl": lifecycle.get("realized_pnl"),
                    "exit_reason": lifecycle.get("exit_reason"),
                    "gate_blocked": gate.get("blocked"),
                    "gate_reason": gate.get("reason"),
                    "blockers": list(decision.get("blockers") or []),
                    "reason_summary": list(decision.get("reason_summary") or []),
                    "advisor_verdict": advisor.get("verdict"),
                    "advisor_confidence": advisor.get("confidence"),
                }
            )
        stream.sort(key=lambda row: str(row.get("decision_at") or ""))
        return stream

    def _build_trade_stream(self, trade_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        stream = []
        for trade in list(trade_logs or []):
            stream.append(
                {
                    "id": trade.get("id"),
                    "time": trade.get("time"),
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "bot_id": trade.get("bot_id"),
                    "realized_pnl": round(self._safe_float(trade.get("realized_pnl")), 8),
                    "total_fee": trade.get("total_fee"),
                    "funding_fee": trade.get("funding_fee"),
                    "order_id": trade.get("order_id"),
                    "order_link_id": trade.get("order_link_id"),
                    "position_idx": trade.get("position_idx"),
                    "exit_reason": trade.get("ownership_close_reason"),
                    "attribution_source": trade.get("attribution_source"),
                }
            )
        stream.sort(key=lambda row: str(row.get("time") or ""))
        return stream

    @staticmethod
    def _max_drawdown_pct(history: List[Dict[str, Any]]) -> float:
        if not history:
            return 0.0
        peak = float(history[0].get("equity") or 0.0)
        max_dd = 0.0
        for point in history:
            equity = float(point.get("equity") or 0.0)
            if equity > peak:
                peak = equity
            if peak > 0:
                max_dd = max(max_dd, ((peak - equity) / peak) * 100.0)
        return round(max_dd, 4)

    @staticmethod
    def _expectancy(trade_logs: List[Dict[str, Any]]) -> float:
        if not trade_logs:
            return 0.0
        total = 0.0
        for trade in trade_logs:
            total += float(trade.get("realized_pnl") or 0.0)
        return round(total / len(trade_logs), 8)

    def _build_exit_reason_summary(self, trade_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Dict[str, Any]] = {}
        for trade in list(trade_logs or []):
            reason = str(trade.get("ownership_close_reason") or "unknown").strip() or "unknown"
            bucket = summary.setdefault(reason, {"count": 0, "net_pnl": 0.0})
            bucket["count"] += 1
            bucket["net_pnl"] = round(
                float(bucket.get("net_pnl") or 0.0)
                + float(trade.get("realized_pnl") or 0.0),
                8,
            )
        return summary

    def _build_by_symbol_summary(self, trade_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Dict[str, Any]] = {}
        for trade in list(trade_logs or []):
            symbol = str(trade.get("symbol") or "").strip().upper() or "UNKNOWN"
            bucket = summary.setdefault(
                symbol,
                {"trade_count": 0, "net_pnl": 0.0, "wins": 0, "losses": 0},
            )
            pnl = float(trade.get("realized_pnl") or 0.0)
            bucket["trade_count"] += 1
            bucket["net_pnl"] = round(float(bucket["net_pnl"]) + pnl, 8)
            if pnl > 0:
                bucket["wins"] += 1
            elif pnl < 0:
                bucket["losses"] += 1
        return summary

    def _build_decision_summary(self, snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {
            "total_decisions": 0,
            "blocked_decisions": 0,
            "executed_decisions": 0,
            "opened_decisions": 0,
            "closed_decisions": 0,
            "awaiting_outcome_decisions": 0,
            "unresolved_outcomes": 0,
        }
        for snapshot in list(snapshots or []):
            lifecycle = dict(snapshot.get("lifecycle") or {})
            summary["total_decisions"] += 1
            if lifecycle.get("blocked"):
                summary["blocked_decisions"] += 1
            if lifecycle.get("submitted"):
                summary["executed_decisions"] += 1
            if lifecycle.get("opened"):
                summary["opened_decisions"] += 1
            if lifecycle.get("closed"):
                summary["closed_decisions"] += 1
            if lifecycle.get("outcome_status") == "awaiting":
                summary["awaiting_outcome_decisions"] += 1
            if lifecycle.get("outcome_status") not in ("realized", "closed"):
                summary["unresolved_outcomes"] += 1
        return summary

    def _build_assumptions(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "warmup_candles": self.warmup_candles,
            "supported_modes": sorted(self.SUPPORTED_MODES),
            "entry_execution_policy": (
                "market orders fill at candle close with configured slippage; "
                "limit orders fill only when the replay candle range touches the order price"
            ),
            "exit_execution_policy": (
                "reduce-only market exits fill at candle close with configured slippage; "
                "limit exits fill on candle touch"
            ),
            "fees": {
                "maker_fee_bps": self.maker_fee_bps,
                "taker_fee_bps": self.taker_fee_bps,
            },
            "slippage": {
                "market_slippage_bps": self.market_slippage_bps,
            },
            "limitations": [
                "candle-driven replay only; no tick-level sequencing",
                "no exact exchange queue modeling or liquidation simulation",
                "unsupported live-only paths remain deferred rather than guessed",
            ],
        }

    def _build_result(
        self,
        *,
        equity_curve: List[Dict[str, Any]],
        cycle_errors: List[str],
    ) -> Dict[str, Any]:
        trade_logs = self._load_json_file(self.paths["trade_logs"], [])
        snapshot_payload = self.decision_snapshot_service.get_recent_snapshots(
            limit=500,
            force_refresh=True,
        )
        snapshots = list(snapshot_payload.get("snapshots") or [])
        decision_stream = self._build_decision_stream(snapshots)
        trade_stream = self._build_trade_stream(trade_logs)
        trade_stats = PnlService._build_trade_window_stats(trade_logs)
        final_equity = round(self._safe_float(self.client.usdt_equity), 8)
        profit = round(final_equity - self.initial_capital, 8)
        roi_pct = round(
            ((profit / self.initial_capital) * 100.0) if self.initial_capital > 0 else 0.0,
            4,
        )
        result = {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": (self.test_bot or {}).get("mode"),
            "start_time": self.start_date,
            "end_time": self.end_date,
            "candles_used": len(self.candles),
            "warmup_candles": min(len(self.candles), self.warmup_candles),
            "decision_summary": self._build_decision_summary(snapshots),
            "trade_summary": {
                **trade_stats,
                "profit": profit,
                "roi_pct": roi_pct,
                "final_equity": final_equity,
                "max_drawdown_pct": self._max_drawdown_pct(equity_curve),
                "expectancy": self._expectancy(trade_logs),
                "closed_trade_count": len(trade_stream),
            },
            "by_symbol_summary": self._build_by_symbol_summary(trade_logs),
            "by_exit_reason_summary": self._build_exit_reason_summary(trade_logs),
            "equity_curve": equity_curve,
            "decision_stream": decision_stream[-200:],
            "trade_stream": trade_stream[-200:],
            "forensics_summary": self.trade_forensics_service.get_summary(),
            "snapshot_summary": self.decision_snapshot_service.get_summary(force_refresh=True).get(
                "summary",
                {},
            ),
            "assumptions": self._build_assumptions(),
            "artifacts": dict(self.paths),
            "cycle_errors": list(cycle_errors or []),
        }
        self._write_json_file(self.paths["results"], result)
        return result

    def run(self) -> Dict[str, Any]:
        logger.info("Starting replayable backtest %s for %s", self.run_id, self.symbol)
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.candles:
            raise ValueError("no candles loaded for backtest")
        if not self.test_bot:
            raise ValueError("bot must be configured before running the backtest")
        if len(self.candles) <= self.warmup_candles:
            raise ValueError(
                f"not enough candles for warmup; need > {self.warmup_candles}, got {len(self.candles)}"
            )

        self.client.set_history(self.symbol, self.candles)

        for candle in self.candles[: self.warmup_candles]:
            self.client.set_time(int(candle["timestamp"]))
            self.client.feed_candle(
                self.symbol,
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle.get("volume", 0.0),
            )

        equity_curve: List[Dict[str, Any]] = []
        cycle_errors: List[str] = []
        for candle in self.candles[self.warmup_candles :]:
            self.client.set_time(int(candle["timestamp"]))
            self.client.feed_candle(
                self.symbol,
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle.get("volume", 0.0),
            )
            try:
                current_bot = self.bot_storage.get_bot(self.test_bot["id"]) or dict(self.test_bot)
                updated_bot = self.bot_service.run_bot_cycle(current_bot)
                if not isinstance(updated_bot, dict):
                    updated_bot = current_bot
                self.pnl_service.sync_closed_pnl(self.symbol)
                self.test_bot = updated_bot
                self.bot_storage.save_bot(updated_bot)
                if str(updated_bot.get("status") or "").strip().lower() == "error":
                    last_error = str(updated_bot.get("last_error") or "unknown_error")
                    cycle_errors.append(last_error)
                    logger.error("Backtest %s bot entered error state: %s", self.run_id, last_error)
                    equity_curve.append(self._build_equity_point(candle))
                    break
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                cycle_errors.append(message)
                logger.error(
                    "Backtest %s cycle error at %s: %s",
                    self.run_id,
                    candle["timestamp"],
                    message,
                    exc_info=True,
                )
                break
            equity_curve.append(self._build_equity_point(candle))

        result = self._build_result(equity_curve=equity_curve, cycle_errors=cycle_errors)
        logger.info(
            "Backtest %s complete: final_equity=%s closed_trades=%s",
            self.run_id,
            result.get("trade_summary", {}).get("final_equity"),
            result.get("trade_summary", {}).get("closed_trade_count"),
        )
        return result
