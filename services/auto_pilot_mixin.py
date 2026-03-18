"""
Auto-Pilot Mixin — Coin Selection, Rotation, and Scoring

Extracted from grid_bot_service.py to reduce the mega-file.
Handles all auto-pilot coin picking, rotation logic, scoring,
filtering, and universe management.

Usage: GridBotService inherits from AutoPilotMixin.
All methods access self.client, self.bot_storage, etc. through GridBotService.
"""

import math
import re
import time
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple
import logging

import config.strategy_config as strategy_cfg
from config.strategy_config import (
    SESSION_TRADING_ENABLED,
    SESSION_MAX_SCORE,
    AUTO_PILOT_MIN_HOLD_SECONDS,
    AUTO_PILOT_MAX_ROTATIONS_PER_HOUR,
    AUTO_PILOT_CHURN_PENALTY_PER_ROTATION,
    AUTO_PILOT_ROTATION_INTERVAL_SECONDS,
    AUTO_PILOT_ROTATION_SCORE_THRESHOLD,
    AUTO_PILOT_ADAPTIVE_ROTATION_ENABLED,
    AUTO_PILOT_ADAPTIVE_ROTATION_MIN_SECONDS,
    AUTO_PILOT_ADAPTIVE_ROTATION_MAX_SECONDS,
    AUTO_PILOT_ROTATION_WEAK_SCORE,
    AUTO_PILOT_ROTATION_HEALTHY_SCORE,
    AUTO_PILOT_ROTATION_HIGH_VOLATILITY_ATR_PCT,
    AUTO_PILOT_VELOCITY_FACTOR_ENABLED,
    AUTO_PILOT_VELOCITY_WEIGHT,
    AUTO_PILOT_VELOCITY_REFERENCE_PER_HOUR,
    AUTO_PILOT_VELOCITY_COLLAPSE_PCT_PER_HOUR,
    AUTO_PILOT_LOSS_BUDGET_GUARD_ENABLED,
    AUTO_PILOT_LOW_REMAINING_LOSS_BUDGET_PCT,
    AUTO_PILOT_BLOCK_OPENINGS_BELOW_REMAINING_LOSS_PCT,
    AUTO_PILOT_LOW_BUDGET_SCORE_BONUS_REQUIRED,
    AUTO_PILOT_LOW_BUDGET_MAX_OPENING_NOTIONAL_MULT,
    AUTO_PILOT_LOW_BUDGET_LOGGING_ENABLED,
    AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
    AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL,
    AUTO_PILOT_STRONG_FILTERS_ENABLED,
    AUTO_PILOT_EXCLUDE_INNOVATION_SYMBOLS,
    AUTO_PILOT_EXCLUDE_NEW_LISTINGS_ENABLED,
    AUTO_PILOT_NEW_LISTING_MIN_DAYS,
    AUTO_PILOT_MAX_SCAN_SYMBOLS,
    AUTO_PILOT_SYMBOL_BLACKLIST,
    AUTO_PILOT_SYMBOL_NAME_BLACKLIST_PATTERNS,
    AUTO_PILOT_MIN_24H_TURNOVER_USDT,
    AUTO_PILOT_MIN_24H_VOLUME,
    AUTO_PILOT_MIN_OPEN_INTEREST_USDT,
    AUTO_PILOT_VOLATILITY_CAP_ENABLED,
    AUTO_PILOT_MIN_ATR_PCT,
    AUTO_PILOT_MAX_ATR_PCT,
    AUTO_PILOT_MAX_INTRADAY_MOVE_PCT,
    AUTO_PILOT_MAX_PRICE_VELOCITY_PER_HOUR,
    AUTO_PILOT_AGGRESSIVE_FULL_STRONG_FILTERS_ENABLED,
    AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_INNOVATION_SYMBOLS,
    AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_NEW_LISTINGS_ENABLED,
    AUTO_PILOT_AGGRESSIVE_FULL_NEW_LISTING_MIN_DAYS,
    AUTO_PILOT_AGGRESSIVE_FULL_MAX_SCAN_SYMBOLS,
    AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_BLACKLIST,
    AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_NAME_BLACKLIST_PATTERNS,
    AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_TURNOVER_USDT,
    AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_VOLUME,
    AUTO_PILOT_AGGRESSIVE_FULL_MIN_OPEN_INTEREST_USDT,
    AUTO_PILOT_AGGRESSIVE_FULL_VOLATILITY_CAP_ENABLED,
    AUTO_PILOT_AGGRESSIVE_FULL_MIN_ATR_PCT,
    AUTO_PILOT_AGGRESSIVE_FULL_MAX_ATR_PCT,
    AUTO_PILOT_AGGRESSIVE_FULL_MAX_INTRADAY_MOVE_PCT,
    AUTO_PILOT_AGGRESSIVE_FULL_MAX_PRICE_VELOCITY_PER_HOUR,
    AUTO_PILOT_CANDIDATE_CACHE_ENABLED,
    AUTO_PILOT_CANDIDATE_CACHE_REFRESH_SECONDS,
    AUTO_PILOT_CANDIDATE_CACHE_MAX_ITEMS,
    AUTO_PILOT_CANDIDATE_CACHE_MAX_AGE_SECONDS,
    AUTO_PILOT_CANDIDATE_CACHE_PERSIST_ENABLED,
    AUTO_PILOT_PENDING_ROTATION_TIMEOUT_SEC,
    AUTO_PILOT_ADX_MOMENTUM_BONUS_ENABLED,
    AUTO_PILOT_ADX_MOMENTUM_BONUS_MIN_ADX,
    AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_ADX,
    AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_POINTS,
    AUTO_PILOT_ADX_MOMENTUM_BONUS_OVERHEATED_PENALTY,
    AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_ENABLED,
    AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_WEIGHT,
    ADX_EXTREME_FREEZE_THRESHOLD,
    DEFAULT_INVESTMENT_USDT,
    DEFAULT_LEVERAGE,
    normalize_auto_pilot_universe_mode,
    FUNDING_FEE_IN_LOSS_BUDGET_ENABLED,
    TIME_OF_DAY_WEIGHTING_ENABLED,
    TIME_OF_DAY_BUCKET_HOURS,
    TIME_OF_DAY_MAX_BONUS,
    TIME_OF_DAY_MAX_PENALTY,
    TIME_OF_DAY_MIN_TRADES,
    REGIME_ADAPTIVE_ROTATION_ENABLED,
    REGIME_DETERIORATION_FAST_CHECK_SEC,
    CROSS_SYMBOL_CORRELATION_FILTER_ENABLED,
    CROSS_SYMBOL_MAX_CORRELATION,
    CROSS_SYMBOL_PENALTY_POINTS,
)

logger = logging.getLogger(__name__)


class AutoPilotMixin:
    """Mixin providing all auto-pilot methods for GridBotService."""

    def _notify_auto_pilot_memory(
        self, bot: Dict[str, Any], symbol: str, pnl: float
    ) -> None:
        """Notify auto-pilot memory of a trade result (real-time path)."""
        if not bot.get("auto_pilot"):
            return
        memory = getattr(self, "auto_pilot_memory", None)
        if memory is None:
            return
        try:
            memory.record_trade(symbol, pnl, pnl > 0)
        except Exception:
            pass

    def _reset_auto_pilot_on_stop(self, bot: Dict[str, Any]) -> None:
        """Reset auto-pilot bot symbol to placeholder when stopping."""
        if not bot.get("auto_pilot"):
            return
        sym = str(bot.get("symbol") or "").strip()
        if sym and sym.lower() != "auto-pilot":
            bot["symbol"] = "Auto-Pilot"
            for key in (
                "lower_price", "upper_price",
                "auto_pilot_rotation_pending", "auto_pilot_rotation_pending_since",
                "auto_pilot_rotation_pending_target", "_auto_pilot_entry_hold",
                "_auto_pilot_entry_hold_until",
            ):
                bot.pop(key, None)

    def _get_auto_pilot_loss_budget_guard_settings(
        self, bot: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        low_remaining_pct = max(
            0.0,
            min(
                1.0,
                self._safe_float(
                    AUTO_PILOT_LOW_REMAINING_LOSS_BUDGET_PCT,
                    0.35,
                ),
            ),
        )
        block_remaining_pct = max(
            0.0,
            min(
                low_remaining_pct,
                self._safe_float(
                    AUTO_PILOT_BLOCK_OPENINGS_BELOW_REMAINING_LOSS_PCT,
                    0.15,
                ),
            ),
        )
        return {
            "enabled": bool(
                AUTO_PILOT_LOSS_BUDGET_GUARD_ENABLED and (bot or {}).get("auto_pilot")
            ),
            "low_remaining_pct": low_remaining_pct,
            "block_remaining_pct": block_remaining_pct,
            "score_bonus_required": max(
                0.0,
                self._safe_float(AUTO_PILOT_LOW_BUDGET_SCORE_BONUS_REQUIRED, 0.0),
            ),
            "max_opening_notional_mult": max(
                0.0,
                self._safe_float(
                    AUTO_PILOT_LOW_BUDGET_MAX_OPENING_NOTIONAL_MULT,
                    0.0,
                ),
            ),
            "logging_enabled": bool(AUTO_PILOT_LOW_BUDGET_LOGGING_ENABLED),
        }

    def _get_auto_pilot_realized_pnl_for_loss_budget(
        self,
        bot: Optional[Dict[str, Any]],
    ) -> float:
        safe_bot = bot or {}
        realized_total = self._safe_float(safe_bot.get("realized_pnl"), 0.0)
        baseline_raw = safe_bot.get("auto_pilot_loss_budget_realized_baseline")
        if baseline_raw is None:
            pnl_since_reset = realized_total
        else:
            try:
                baseline = float(baseline_raw)
            except (TypeError, ValueError):
                return realized_total
            pnl_since_reset = realized_total - baseline

        if FUNDING_FEE_IN_LOSS_BUDGET_ENABLED:
            try:
                bot_id = safe_bot.get("id") or safe_bot.get("bot_id")
                pnl_service = getattr(self, "pnl_service", None)
                if pnl_service is not None and bot_id:
                    trade_logs = pnl_service.get_log(bot_id=bot_id)
                    funding_total = sum(
                        self._safe_float(entry.get("funding_fee"), 0.0)
                        for entry in trade_logs
                        if entry.get("funding_fee") is not None
                    )
                    if funding_total != 0.0:
                        logger.debug(
                            "[Auto-Pilot:%s] Funding fee adjustment to loss budget: %.6f USDT",
                            bot_id,
                            funding_total,
                        )
                        pnl_since_reset += funding_total
            except Exception:
                pass  # pnl_service unavailable — skip adjustment

        return pnl_since_reset

    def _compute_auto_pilot_loss_budget_state(
        self,
        bot: Dict[str, Any],
        symbol: Optional[str],
        *,
        investment: Optional[float] = None,
        leverage: Optional[float] = None,
        available_equity: Optional[float] = None,
        symbol_unrealized_pnl: Optional[float] = None,
        positions_resp: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        settings = self._get_auto_pilot_loss_budget_guard_settings(bot)
        state: Dict[str, Any] = {
            "enabled": settings["enabled"],
            "status": "disabled",
            "remaining_pct": None,
            "remaining_usdt": None,
            "consumed_loss_usdt": None,
            "loss_budget_usdt": None,
            "effective_capital": None,
            "realized_pnl_since_reset": None,
            "total_pnl": None,
            "max_opening_notional_usdt": None,
        }
        if not settings["enabled"]:
            return state

        effective_investment = (
            self._safe_float(bot.get("investment"), DEFAULT_INVESTMENT_USDT)
            if investment is None
            else self._safe_float(investment, DEFAULT_INVESTMENT_USDT)
        )
        leverage_value = (
            self._safe_float(bot.get("leverage"), DEFAULT_LEVERAGE)
            if leverage is None
            else self._safe_float(leverage, DEFAULT_LEVERAGE)
        )

        if available_equity is None:
            try:
                available_equity = self._get_usdt_available_balance()
            except Exception as exc:
                logger.debug(
                    "[%s] Auto-Pilot loss budget equity lookup failed: %s",
                    symbol,
                    exc,
                )
                available_equity = None

        effective_capital = self._calculate_effective_capital(
            bot=bot,
            investment=effective_investment,
            leverage=leverage_value,
            available_equity=available_equity,
        )
        max_bot_loss_pct = self._safe_float(
            getattr(getattr(self, "risk_manager", None), "max_bot_loss_pct", 0.05),
            0.05,
        )
        loss_budget_usdt = max(0.0, effective_capital * max_bot_loss_pct)
        realized_pnl = self._get_auto_pilot_realized_pnl_for_loss_budget(bot)
        if symbol_unrealized_pnl is None:
            symbol_unrealized_pnl = self._get_symbol_unrealized_pnl_total(
                symbol,
                positions_resp=positions_resp,
            )
        else:
            symbol_unrealized_pnl = self._safe_float(symbol_unrealized_pnl, 0.0)
        total_pnl = realized_pnl + symbol_unrealized_pnl
        consumed_loss_usdt = max(0.0, -total_pnl)
        remaining_usdt = max(0.0, loss_budget_usdt - consumed_loss_usdt)
        remaining_pct = (
            (remaining_usdt / loss_budget_usdt) if loss_budget_usdt > 0 else 0.0
        )

        status = "healthy"
        if loss_budget_usdt <= 0 or remaining_pct <= settings["block_remaining_pct"]:
            status = "blocked"
        elif remaining_pct <= settings["low_remaining_pct"]:
            status = "low"

        max_opening_notional_usdt = None
        if status == "low" and settings["max_opening_notional_mult"] > 0:
            max_opening_notional_usdt = (
                remaining_usdt * settings["max_opening_notional_mult"]
            )

        state.update(
            {
                "status": status,
                "remaining_pct": remaining_pct,
                "remaining_usdt": remaining_usdt,
                "consumed_loss_usdt": consumed_loss_usdt,
                "loss_budget_usdt": loss_budget_usdt,
                "effective_capital": effective_capital,
                "realized_pnl_since_reset": realized_pnl,
                "total_pnl": total_pnl,
                "max_opening_notional_usdt": max_opening_notional_usdt,
            }
        )
        return state

    def _apply_auto_pilot_loss_budget_runtime_state(
        self,
        bot: Optional[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not bot:
            return state

        enabled = bool(state.get("enabled"))
        status = state.get("status") if enabled else None
        bot["auto_pilot_loss_budget_state"] = status
        bot["auto_pilot_remaining_loss_budget_pct"] = (
            round(self._safe_float(state.get("remaining_pct"), 0.0), 6)
            if enabled and state.get("remaining_pct") is not None
            else None
        )
        bot["auto_pilot_remaining_loss_budget_usdt"] = (
            round(self._safe_float(state.get("remaining_usdt"), 0.0), 4)
            if enabled and state.get("remaining_usdt") is not None
            else None
        )
        bot["auto_pilot_loss_budget_usdt"] = (
            round(self._safe_float(state.get("loss_budget_usdt"), 0.0), 4)
            if enabled and state.get("loss_budget_usdt") is not None
            else None
        )
        bot["auto_pilot_loss_budget_total_pnl"] = (
            round(self._safe_float(state.get("total_pnl"), 0.0), 4)
            if enabled and state.get("total_pnl") is not None
            else None
        )
        bot["auto_pilot_loss_budget_realized_since_reset"] = (
            round(self._safe_float(state.get("realized_pnl_since_reset"), 0.0), 4)
            if enabled and state.get("realized_pnl_since_reset") is not None
            else None
        )
        bot["auto_pilot_low_budget_max_opening_notional_usdt"] = (
            round(self._safe_float(state.get("max_opening_notional_usdt"), 0.0), 4)
            if enabled and state.get("max_opening_notional_usdt") is not None
            else None
        )
        blocked = bool(enabled and status == "blocked")
        bot["_auto_pilot_loss_budget_block_openings"] = blocked
        bot["auto_pilot_opening_blocked_by_loss_budget"] = blocked
        return state

    def _get_auto_pilot_opening_order_price(
        self,
        bot: Dict[str, Any],
        symbol: str,
        price: Optional[float],
    ) -> Optional[float]:
        order_price = self._safe_float(price, 0.0)
        if order_price > 0:
            return order_price
        current_price = self._safe_float(bot.get("current_price"), 0.0)
        if current_price > 0:
            return current_price
        try:
            return self._safe_float(self._get_last_price(symbol), 0.0)
        except Exception as exc:
            logger.debug(
                "[%s] Auto-Pilot loss budget price lookup failed: %s",
                symbol,
                exc,
            )
            return None

    def _get_auto_pilot_filter_settings(
        self,
        bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        bot = bot or {}
        universe_mode = self._get_auto_pilot_universe_mode(bot)
        mode_defaults = self._get_auto_pilot_universe_mode_defaults(universe_mode)
        return {
            "universe_mode": universe_mode,
            "strong_filters_enabled": bool(
                bot.get(
                    "auto_pilot_strong_filters_enabled",
                    mode_defaults["strong_filters_enabled"],
                )
            ),
            "exclude_innovation": bool(
                bot.get(
                    "auto_pilot_exclude_innovation_symbols",
                    mode_defaults["exclude_innovation"],
                )
            ),
            "exclude_new_listings": bool(
                bot.get(
                    "auto_pilot_exclude_new_listings_enabled",
                    mode_defaults["exclude_new_listings"],
                )
            ),
            "new_listing_min_days": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_new_listing_min_days"),
                    mode_defaults["new_listing_min_days"],
                ),
            ),
            "max_scan_symbols": max(
                0,
                int(
                    self._safe_float(
                        bot.get("auto_pilot_max_scan_symbols"),
                        mode_defaults["max_scan_symbols"],
                    )
                ),
            ),
            "symbol_blacklist": {
                str(symbol or "").strip().upper()
                for symbol in (
                    bot.get("auto_pilot_symbol_blacklist")
                    or mode_defaults["symbol_blacklist"]
                    or ()
                )
                if str(symbol or "").strip()
            },
            "symbol_name_blacklist_patterns": [
                str(pattern).strip()
                for pattern in (
                    bot.get("auto_pilot_symbol_name_blacklist_patterns")
                    or mode_defaults["symbol_name_blacklist_patterns"]
                    or ()
                )
                if str(pattern).strip()
            ],
            "min_turnover_usdt": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_min_24h_turnover_usdt"),
                    mode_defaults["min_turnover_usdt"],
                ),
            ),
            "min_volume_24h": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_min_24h_volume"),
                    mode_defaults["min_volume_24h"],
                ),
            ),
            "min_open_interest_usdt": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_min_open_interest_usdt"),
                    mode_defaults["min_open_interest_usdt"],
                ),
            ),
            "volatility_cap_enabled": bool(
                bot.get(
                    "auto_pilot_volatility_cap_enabled",
                    mode_defaults["volatility_cap_enabled"],
                )
            ),
            "min_atr_pct": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_min_atr_pct"),
                    mode_defaults["min_atr_pct"],
                ),
            ),
            "max_atr_pct": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_max_atr_pct"),
                    mode_defaults["max_atr_pct"],
                ),
            ),
            "max_intraday_move_pct": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_max_intraday_move_pct"),
                    mode_defaults["max_intraday_move_pct"],
                ),
            ),
            "max_price_velocity_per_hour": max(
                0.0,
                self._safe_float(
                    bot.get("auto_pilot_max_price_velocity_per_hour"),
                    mode_defaults["max_price_velocity_per_hour"],
                ),
            ),
        }

    @staticmethod
    def _get_auto_pilot_universe_mode(
        bot: Optional[Dict[str, Any]] = None,
    ) -> str:
        configured_mode = None
        if isinstance(bot, dict):
            configured_mode = bot.get("auto_pilot_universe_mode")
        return normalize_auto_pilot_universe_mode(configured_mode)

    @staticmethod
    def _get_auto_pilot_universe_mode_defaults(
        universe_mode: str,
    ) -> Dict[str, Any]:
        normalized_mode = normalize_auto_pilot_universe_mode(universe_mode)
        if normalized_mode == AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL:
            return {
                "strong_filters_enabled": AUTO_PILOT_AGGRESSIVE_FULL_STRONG_FILTERS_ENABLED,
                "exclude_innovation": AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_INNOVATION_SYMBOLS,
                "exclude_new_listings": AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_NEW_LISTINGS_ENABLED,
                "new_listing_min_days": AUTO_PILOT_AGGRESSIVE_FULL_NEW_LISTING_MIN_DAYS,
                "max_scan_symbols": AUTO_PILOT_AGGRESSIVE_FULL_MAX_SCAN_SYMBOLS,
                "symbol_blacklist": AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_BLACKLIST,
                "symbol_name_blacklist_patterns": AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_NAME_BLACKLIST_PATTERNS,
                "min_turnover_usdt": AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_TURNOVER_USDT,
                "min_volume_24h": AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_VOLUME,
                "min_open_interest_usdt": AUTO_PILOT_AGGRESSIVE_FULL_MIN_OPEN_INTEREST_USDT,
                "volatility_cap_enabled": AUTO_PILOT_AGGRESSIVE_FULL_VOLATILITY_CAP_ENABLED,
                "min_atr_pct": AUTO_PILOT_AGGRESSIVE_FULL_MIN_ATR_PCT,
                "max_atr_pct": AUTO_PILOT_AGGRESSIVE_FULL_MAX_ATR_PCT,
                "max_intraday_move_pct": AUTO_PILOT_AGGRESSIVE_FULL_MAX_INTRADAY_MOVE_PCT,
                "max_price_velocity_per_hour": AUTO_PILOT_AGGRESSIVE_FULL_MAX_PRICE_VELOCITY_PER_HOUR,
            }
        return {
            "strong_filters_enabled": AUTO_PILOT_STRONG_FILTERS_ENABLED,
            "exclude_innovation": AUTO_PILOT_EXCLUDE_INNOVATION_SYMBOLS,
            "exclude_new_listings": AUTO_PILOT_EXCLUDE_NEW_LISTINGS_ENABLED,
            "new_listing_min_days": AUTO_PILOT_NEW_LISTING_MIN_DAYS,
            "max_scan_symbols": AUTO_PILOT_MAX_SCAN_SYMBOLS,
            "symbol_blacklist": AUTO_PILOT_SYMBOL_BLACKLIST,
            "symbol_name_blacklist_patterns": AUTO_PILOT_SYMBOL_NAME_BLACKLIST_PATTERNS,
            "min_turnover_usdt": AUTO_PILOT_MIN_24H_TURNOVER_USDT,
            "min_volume_24h": AUTO_PILOT_MIN_24H_VOLUME,
            "min_open_interest_usdt": AUTO_PILOT_MIN_OPEN_INTEREST_USDT,
            "volatility_cap_enabled": AUTO_PILOT_VOLATILITY_CAP_ENABLED,
            "min_atr_pct": AUTO_PILOT_MIN_ATR_PCT,
            "max_atr_pct": AUTO_PILOT_MAX_ATR_PCT,
            "max_intraday_move_pct": AUTO_PILOT_MAX_INTRADAY_MOVE_PCT,
            "max_price_velocity_per_hour": AUTO_PILOT_MAX_PRICE_VELOCITY_PER_HOUR,
        }

    def _build_auto_pilot_universe_summary(
        self,
        settings: Dict[str, Any],
        stats: Optional[Dict[str, Any]] = None,
    ) -> str:
        scan_cap = int(settings.get("max_scan_symbols", 0) or 0)
        parts = [
            f"mode={settings.get('universe_mode') or AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE}",
            f"innovation={'excluded' if settings.get('exclude_innovation') else 'allowed'}",
            (
                f"new_listings<{int(round(self._safe_float(settings.get('new_listing_min_days'), 0.0)))}d excluded"
                if settings.get("exclude_new_listings")
                else "new_listings=allowed"
            ),
            f"pattern_blacklist={'on' if settings.get('symbol_name_blacklist_patterns') else 'off'}",
            f"symbol_blacklist={len(settings.get('symbol_blacklist') or [])}",
            f"quality=turnover>={int(self._safe_float(settings.get('min_turnover_usdt'), 0.0))}",
            (
                f"vol_caps=on({self._safe_float(settings.get('max_atr_pct'), 0.0):.3f}/"
                f"{self._safe_float(settings.get('max_intraday_move_pct'), 0.0):.3f}/"
                f"{self._safe_float(settings.get('max_price_velocity_per_hour'), 0.0):.3f})"
                if settings.get("volatility_cap_enabled")
                else "vol_caps=off"
            ),
            f"scan_cap={scan_cap if scan_cap > 0 else 'off'}",
        ]
        if isinstance(stats, dict) and stats:
            parts.extend(
                [
                    f"pre={int(stats.get('eligible_pre_scan', 0) or 0)}",
                    f"scan={int(stats.get('scan_universe', 0) or 0)}",
                    f"eligible={int(stats.get('eligible_final', 0) or 0)}",
                ]
            )
        return " | ".join(parts)

    def _apply_auto_pilot_universe_runtime_state(
        self,
        bot: Optional[Dict[str, Any]],
        settings: Dict[str, Any],
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not isinstance(bot, dict):
            return
        bot["auto_pilot_universe_mode"] = settings.get(
            "universe_mode",
            AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        )
        bot["auto_pilot_universe_summary"] = self._build_auto_pilot_universe_summary(
            settings,
            stats,
        )

    def _get_auto_pilot_instrument_catalog(self) -> Dict[str, Dict[str, Any]]:
        cache = getattr(self, "_auto_pilot_instrument_meta_cache", None)
        now_ts = self._get_cycle_now_ts()
        if isinstance(cache, dict):
            cached_symbols = cache.get("symbols")
            fetched_at = self._safe_float(cache.get("fetched_at"), 0.0)
            if (
                isinstance(cached_symbols, dict)
                and cached_symbols
                and fetched_at > 0
                and (now_ts - fetched_at) < 1800
            ):
                return cached_symbols

        instrument_map: Dict[str, Dict[str, Any]] = {}
        cursor: Optional[str] = None
        seen_cursors = set()

        try:
            while True:
                response = self.client.get_instruments_info(
                    status="Trading",
                    limit=1000,
                    cursor=cursor,
                )
                if not response.get("success"):
                    logger.warning(
                        "[Auto-Pilot] Failed to fetch instrument catalog: %s",
                        response.get("error"),
                    )
                    break

                data = response.get("data", {}) or {}
                for instrument in data.get("list", []) or []:
                    symbol = str(instrument.get("symbol") or "").strip().upper()
                    if symbol:
                        instrument_map[symbol] = instrument

                next_cursor = str(data.get("nextPageCursor") or "").strip()
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except Exception as exc:
            logger.warning(
                "[Auto-Pilot] Instrument catalog fetch error: %s",
                exc,
            )

        self._auto_pilot_instrument_meta_cache = {
            "fetched_at": now_ts,
            "symbols": instrument_map,
        }
        return instrument_map

    @staticmethod
    def _get_auto_pilot_summary_bucket(status: str) -> Optional[str]:
        if status in {"excluded_blacklist", "excluded_meme_pattern"}:
            return "blacklist"
        if status == "excluded_innovation":
            return "innovation"
        if status == "excluded_new_listing":
            return "new_listing"
        if status in {
            "excluded_low_quality_turnover",
            "excluded_low_quality_volume",
            "excluded_low_quality_open_interest",
        }:
            return "quality"
        if status == "excluded_high_volatility":
            return "volatility"
        return None

    def _record_auto_pilot_exclusion(
        self,
        stats: Dict[str, Any],
        status: str,
        symbol: str,
    ) -> None:
        bucket = self._get_auto_pilot_summary_bucket(status)
        if not bucket:
            return
        excluded = stats.setdefault("excluded", {})
        samples = stats.setdefault("samples", {})
        excluded[bucket] = int(excluded.get(bucket, 0) or 0) + 1
        bucket_samples = samples.setdefault(bucket, [])
        if symbol and symbol not in bucket_samples and len(bucket_samples) < 3:
            bucket_samples.append(symbol)

    def _symbol_matches_auto_pilot_patterns(
        self,
        symbol: str,
        patterns: List[str],
    ) -> bool:
        for pattern in patterns or []:
            try:
                if re.search(pattern, symbol, re.IGNORECASE):
                    return True
            except re.error as exc:
                logger.warning(
                    "[Auto-Pilot] Invalid symbol blacklist pattern %r: %s",
                    pattern,
                    exc,
                )
        return False

    def _get_auto_pilot_listing_age_days(
        self,
        instrument: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        if not isinstance(instrument, dict) or not instrument:
            return None

        raw_launch_time = instrument.get("launchTime")
        if raw_launch_time in (None, ""):
            return None

        launch_ts = self._safe_float(raw_launch_time, 0.0)
        if launch_ts <= 0:
            return None
        if launch_ts > 10_000_000_000:
            launch_ts /= 1000.0

        age_seconds = max(0.0, self._get_cycle_now_ts() - launch_ts)
        return age_seconds / 86400.0

    def _get_auto_pilot_pre_scan_status(
        self,
        symbol: str,
        ticker: Dict[str, Any],
        instrument: Optional[Dict[str, Any]],
        settings: Dict[str, Any],
    ) -> Optional[str]:
        if symbol in settings["symbol_blacklist"]:
            return "excluded_blacklist"

        if self._symbol_matches_auto_pilot_patterns(
            symbol,
            settings["symbol_name_blacklist_patterns"],
        ):
            return "excluded_meme_pattern"

        if (
            settings["exclude_innovation"]
            and self._is_auto_pilot_innovation_symbol(instrument)
        ):
            return "excluded_innovation"

        if settings["exclude_new_listings"]:
            listing_age_days = self._get_auto_pilot_listing_age_days(instrument)
            if (
                listing_age_days is not None
                and listing_age_days < settings["new_listing_min_days"]
            ):
                return "excluded_new_listing"

        turnover = max(0.0, self._safe_float(ticker.get("turnover24h"), 0.0))
        if (
            settings["min_turnover_usdt"] > 0
            and turnover < settings["min_turnover_usdt"]
        ):
            return "excluded_low_quality_turnover"

        volume_24h = max(0.0, self._safe_float(ticker.get("volume24h"), 0.0))
        if settings["min_volume_24h"] > 0 and volume_24h < settings["min_volume_24h"]:
            return "excluded_low_quality_volume"

        oi_raw = ticker.get("openInterestValue")
        if oi_raw not in (None, ""):
            open_interest_value = max(0.0, self._safe_float(oi_raw, 0.0))
            if (
                settings["min_open_interest_usdt"] > 0
                and open_interest_value < settings["min_open_interest_usdt"]
            ):
                return "excluded_low_quality_open_interest"

        return None

    def _get_auto_pilot_volatility_status(
        self,
        candidate: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> Optional[str]:
        if not settings["volatility_cap_enabled"]:
            return None

        atr_pct = candidate.get("atr_pct")
        if (
            atr_pct is not None
            and settings["max_atr_pct"] > 0
            and self._to_float(atr_pct) > settings["max_atr_pct"]
        ):
            return "excluded_high_volatility"

        if (
            atr_pct is not None
            and settings.get("min_atr_pct", 0) > 0
            and self._to_float(atr_pct) < settings["min_atr_pct"]
        ):
            return "excluded_low_volatility"

        intraday_move = candidate.get("price_change_24h_pct")
        if (
            intraday_move is not None
            and settings["max_intraday_move_pct"] > 0
            and abs(self._to_float(intraday_move)) > settings["max_intraday_move_pct"]
        ):
            return "excluded_high_volatility"

        velocity = candidate.get("price_velocity")
        if (
            velocity is not None
            and settings["max_price_velocity_per_hour"] > 0
            and abs(self._to_float(velocity))
            > settings["max_price_velocity_per_hour"]
        ):
            return "excluded_high_volatility"

        return None

    def _classify_auto_pilot_eligible_status(
        self,
        candidate: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> str:
        turnover = max(0.0, self._to_float(candidate.get("volume_24h_usdt")))
        atr_pct = abs(self._to_float(candidate.get("atr_pct")))
        intraday_move = abs(self._to_float(candidate.get("price_change_24h_pct")))
        velocity = abs(self._to_float(candidate.get("price_velocity")))

        borderline = False
        if settings["min_turnover_usdt"] > 0 and turnover > 0:
            borderline = turnover < (settings["min_turnover_usdt"] * 1.5)
        if (
            not borderline
            and settings["volatility_cap_enabled"]
            and settings["max_atr_pct"] > 0
            and atr_pct >= (settings["max_atr_pct"] * 0.8)
        ):
            borderline = True
        if (
            not borderline
            and settings["volatility_cap_enabled"]
            and settings["max_intraday_move_pct"] > 0
            and intraday_move >= (settings["max_intraday_move_pct"] * 0.75)
        ):
            borderline = True
        if (
            not borderline
            and settings["volatility_cap_enabled"]
            and settings["max_price_velocity_per_hour"] > 0
            and velocity >= (settings["max_price_velocity_per_hour"] * 0.75)
        ):
            borderline = True

        return "eligible_borderline" if borderline else "eligible_conservative"

    def _filter_auto_pilot_scan_results(
        self,
        bot: Dict[str, Any],
        scan_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        settings = self._get_auto_pilot_filter_settings(bot)
        self._apply_auto_pilot_universe_runtime_state(bot, settings)
        if not settings["strong_filters_enabled"]:
            return [dict(result) for result in (scan_results or [])]

        stats = getattr(self, "_auto_pilot_last_universe_stats", None)
        if not isinstance(stats, dict):
            stats = {}
        stats["scanned"] = len(scan_results or [])

        # Portfolio guard: exclude symbols already active in other running bots
        bot_id = str(bot.get("id") or "").strip()
        active_symbols = set()
        try:
            for b in self.bot_storage.list_bots():
                b_status = str(b.get("status") or "").strip().lower()
                b_id = str(b.get("id") or "").strip()
                if b_id == bot_id:
                    continue
                if b_status in ("running", "recovering", "paused"):
                    b_sym = str(b.get("symbol") or "").strip().upper()
                    if b_sym and b_sym != "AUTO-PILOT":
                        active_symbols.add(b_sym)
        except Exception:
            pass

        filtered_results: List[Dict[str, Any]] = []
        for raw_result in scan_results or []:
            candidate = dict(raw_result)
            symbol = str(candidate.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            if symbol in active_symbols:
                self._record_auto_pilot_exclusion(
                    stats, "excluded_active_in_other_bot", symbol,
                )
                continue

            if symbol in settings["symbol_blacklist"]:
                self._record_auto_pilot_exclusion(
                    stats,
                    "excluded_blacklist",
                    symbol,
                )
                continue
            if self._symbol_matches_auto_pilot_patterns(
                symbol,
                settings["symbol_name_blacklist_patterns"],
            ):
                self._record_auto_pilot_exclusion(
                    stats,
                    "excluded_meme_pattern",
                    symbol,
                )
                continue

            status = self._get_auto_pilot_volatility_status(candidate, settings)
            if status:
                self._record_auto_pilot_exclusion(stats, status, symbol)
                continue

            candidate["_auto_pilot_eligibility_status"] = (
                self._classify_auto_pilot_eligible_status(candidate, settings)
            )
            filtered_results.append(candidate)

        stats["eligible_final"] = len(filtered_results)
        self._auto_pilot_last_universe_stats = stats
        self._apply_auto_pilot_universe_runtime_state(bot, settings, stats)
        self._log_auto_pilot_universe_summary(settings, stats)
        return filtered_results

    def _get_auto_pilot_top_symbols(
        self,
        bot: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Return the Auto-Pilot scan universe after pre-ranking eligibility filters."""
        settings = self._get_auto_pilot_filter_settings(bot)
        self._apply_auto_pilot_universe_runtime_state(bot, settings)
        if not settings["strong_filters_enabled"]:
            try:
                ticker_resp = self.client.get_tickers()
                if ticker_resp.get("success"):
                    all_tickers = ticker_resp.get("data", {}).get("list", [])
                    usdt_pairs = []
                    for ticker in all_tickers:
                        symbol = str(ticker.get("symbol") or "").strip().upper()
                        if not symbol.endswith("USDT"):
                            continue
                        if symbol in settings["symbol_blacklist"]:
                            continue
                        turnover = self._safe_float(ticker.get("turnover24h"), 0.0)
                        price = self._safe_float(ticker.get("lastPrice"), 0.0)
                        if turnover < 5_000_000 or price <= 0:
                            continue
                        usdt_pairs.append((symbol, turnover))
                    usdt_pairs.sort(key=lambda item: item[1], reverse=True)
                    return [symbol for symbol, _turnover in usdt_pairs[:30]]
                logger.warning("[Auto-Pilot] Failed to fetch tickers, using fallback list")
            except Exception as exc:
                logger.warning("[Auto-Pilot] Ticker fetch error: %s, using fallback", exc)
            return ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]

        stats: Dict[str, Any] = {
            "universe_mode": settings["universe_mode"],
            "active_usdt": 0,
            "eligible_pre_scan": 0,
            "scan_universe": 0,
            "scanned": 0,
            "eligible_final": 0,
            "excluded": {
                "blacklist": 0,
                "innovation": 0,
                "new_listing": 0,
                "quality": 0,
                "volatility": 0,
            },
            "samples": {},
        }
        ticker_snapshot: Dict[str, Dict[str, float]] = {}

        try:
            ticker_resp = self.client.get_tickers()
            if not ticker_resp.get("success"):
                logger.warning("[Auto-Pilot] Failed to fetch tickers, using fallback list")
                self._auto_pilot_last_universe_stats = stats
                self._auto_pilot_last_ticker_snapshot = ticker_snapshot
                return ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]

            instrument_map = self._get_auto_pilot_instrument_catalog()
            eligible_pairs: List[Tuple[str, float, float, float]] = []
            for ticker in ticker_resp.get("data", {}).get("list", []) or []:
                symbol = str(ticker.get("symbol") or "").strip().upper()
                if not symbol.endswith("USDT"):
                    continue

                price = self._safe_float(ticker.get("lastPrice"), 0.0)
                if price <= 0:
                    continue

                stats["active_usdt"] += 1
                status = self._get_auto_pilot_pre_scan_status(
                    symbol=symbol,
                    ticker=ticker,
                    instrument=instrument_map.get(symbol),
                    settings=settings,
                )
                if status:
                    self._record_auto_pilot_exclusion(stats, status, symbol)
                    continue

                turnover = max(0.0, self._safe_float(ticker.get("turnover24h"), 0.0))
                volume_24h = max(
                    0.0,
                    self._safe_float(ticker.get("volume24h"), 0.0),
                )
                open_interest_value = max(
                    0.0,
                    self._safe_float(ticker.get("openInterestValue"), 0.0),
                )
                abs_price_pct = abs(self._safe_float(ticker.get("price24hPcnt"), 0.0))
                eligible_pairs.append(
                    (symbol, turnover, open_interest_value, volume_24h, abs_price_pct)
                )
                ticker_snapshot[symbol] = {
                    "turnover24h": turnover,
                    "volume24h": volume_24h,
                    "open_interest_value": open_interest_value,
                    "price24hPcnt": self._safe_float(ticker.get("price24hPcnt"), 0.0),
                }

            if AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_ENABLED and len(eligible_pairs) > 1:
                # Blend turnover rank with momentum rank for universe pre-sort
                mom_w = max(0.0, min(1.0, AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_WEIGHT))
                turn_w = 1.0 - mom_w
                by_turnover = sorted(eligible_pairs, key=lambda p: -p[1])
                by_momentum = sorted(eligible_pairs, key=lambda p: -p[4])
                turn_rank = {p[0]: i for i, p in enumerate(by_turnover)}
                mom_rank = {p[0]: i for i, p in enumerate(by_momentum)}
                eligible_pairs.sort(
                    key=lambda p: turn_w * turn_rank[p[0]] + mom_w * mom_rank[p[0]]
                )
            else:
                eligible_pairs.sort(
                    key=lambda item: (-item[1], -item[2], -item[3], item[0])
                )
            symbols = [p[0] for p in eligible_pairs]
            stats["eligible_pre_scan"] = len(symbols)
            max_scan_symbols = max(0, int(settings.get("max_scan_symbols", 0) or 0))
            if max_scan_symbols > 0 and len(symbols) > max_scan_symbols:
                logger.info(
                    "[Auto-Pilot] Universe scan cap applied pre_eligible=%d scan_universe=%d limit=%d",
                    len(symbols),
                    max_scan_symbols,
                    max_scan_symbols,
                )
                symbols = symbols[:max_scan_symbols]
            stats["scan_universe"] = len(symbols)
            self._auto_pilot_last_universe_stats = stats
            self._auto_pilot_last_ticker_snapshot = ticker_snapshot
            self._apply_auto_pilot_universe_runtime_state(bot, settings, stats)

            if not symbols:
                logger.warning("[Auto-Pilot] Strong filters removed all Auto-Pilot symbols")
            return symbols
        except Exception as exc:
            logger.warning("[Auto-Pilot] Ticker fetch error: %s, using fallback", exc)
            self._auto_pilot_last_universe_stats = stats
            self._auto_pilot_last_ticker_snapshot = ticker_snapshot
            self._apply_auto_pilot_universe_runtime_state(bot, settings, stats)
            return ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]

    def _get_auto_pilot_candidate_cache_service(
        self,
        bot: Optional[Dict[str, Any]] = None,
    ):
        universe_mode = self._get_auto_pilot_universe_mode(bot)
        services = getattr(self, "auto_pilot_candidate_cache_services", None)
        if not isinstance(services, dict):
            services = {}
            legacy_service = getattr(self, "auto_pilot_candidate_cache_service", None)
            if legacy_service is not None:
                services[AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE] = legacy_service
            self.auto_pilot_candidate_cache_services = services

        service = services.get(universe_mode)
        if service is not None:
            return service
        try:
            from services.auto_pilot_candidate_cache_service import (
                AutoPilotCandidateCacheService,
            )

            if universe_mode == AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE:
                file_path = "/var/www/storage/auto_pilot_candidate_cache.json"
            else:
                file_path = (
                    f"/var/www/storage/auto_pilot_candidate_cache_{universe_mode}.json"
                )
            service = AutoPilotCandidateCacheService(
                file_path=file_path,
                persist_enabled=AUTO_PILOT_CANDIDATE_CACHE_PERSIST_ENABLED,
            )
        except Exception as exc:
            logger.warning(
                "[Auto-Pilot] Candidate cache service init failed: %s",
                exc,
            )
            service = None
        services[universe_mode] = service
        if universe_mode == AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE:
            self.auto_pilot_candidate_cache_service = service
        return service

    def _get_auto_pilot_candidate_cache_settings(
        self,
        bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        safe_bot = bot or {}
        return {
            "enabled": bool(
                safe_bot.get(
                    "auto_pilot_candidate_cache_enabled",
                    AUTO_PILOT_CANDIDATE_CACHE_ENABLED,
                )
            ),
            "refresh_seconds": max(
                60,
                int(
                    self._safe_float(
                        safe_bot.get("auto_pilot_candidate_cache_refresh_seconds"),
                        AUTO_PILOT_CANDIDATE_CACHE_REFRESH_SECONDS,
                    )
                ),
            ),
            "max_items": max(
                1,
                int(
                    self._safe_float(
                        safe_bot.get("auto_pilot_candidate_cache_max_items"),
                        AUTO_PILOT_CANDIDATE_CACHE_MAX_ITEMS,
                    )
                ),
            ),
            "max_age_seconds": max(
                60,
                int(
                    self._safe_float(
                        safe_bot.get("auto_pilot_candidate_cache_max_age_seconds"),
                        AUTO_PILOT_CANDIDATE_CACHE_MAX_AGE_SECONDS,
                    )
                ),
            ),
        }

    def _get_auto_pilot_rotation_settings(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        base_seconds = max(
            60,
            int(
                self._safe_float(
                    bot.get("auto_pilot_rotation_interval_seconds"),
                    AUTO_PILOT_ROTATION_INTERVAL_SECONDS,
                )
            ),
        )
        min_seconds = max(
            60,
            int(
                self._safe_float(
                    bot.get("auto_pilot_adaptive_rotation_min_seconds"),
                    AUTO_PILOT_ADAPTIVE_ROTATION_MIN_SECONDS,
                )
            ),
        )
        max_seconds = max(
            base_seconds,
            int(
                self._safe_float(
                    bot.get("auto_pilot_adaptive_rotation_max_seconds"),
                    AUTO_PILOT_ADAPTIVE_ROTATION_MAX_SECONDS,
                )
            ),
        )
        if min_seconds > max_seconds:
            min_seconds = max_seconds
        return {
            "adaptive_enabled": bool(
                bot.get(
                    "auto_pilot_adaptive_rotation_enabled",
                    AUTO_PILOT_ADAPTIVE_ROTATION_ENABLED,
                )
            ),
            "base_seconds": base_seconds,
            "min_seconds": min_seconds,
            "max_seconds": max_seconds,
            "score_threshold": self._safe_float(
                bot.get("auto_pilot_rotation_score_threshold"),
                AUTO_PILOT_ROTATION_SCORE_THRESHOLD,
            ),
        }

    def _get_effective_auto_pilot_rotation_interval(
        self,
        bot: Dict[str, Any],
    ) -> int:
        settings = self._get_auto_pilot_rotation_settings(bot)
        if not settings["adaptive_enabled"]:
            return settings["base_seconds"]
        stored_interval = int(
            self._safe_float(
                bot.get("auto_pilot_effective_rotation_interval_sec"),
                settings["base_seconds"],
            )
        )
        return max(
            settings["min_seconds"],
            min(settings["max_seconds"], stored_interval),
        )

    def _check_auto_pilot_low_budget_candidate(
        self,
        bot: Dict[str, Any],
        budget_state: Dict[str, Any],
        *,
        best_score: float,
        current_score: Optional[float] = None,
        second_best_score: Optional[float] = None,
        base_score_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        status = str(budget_state.get("status") or "")
        result = {
            "allowed": True,
            "status": status,
            "required_abs_score": None,
            "required_score_gap": None,
            "actual_score_gap": None,
            "reason": None,
        }
        if status != "low":
            return result

        settings = self._get_auto_pilot_loss_budget_guard_settings(bot)
        bonus = self._safe_float(settings.get("score_bonus_required"), 0.0)
        required_abs_score = max(
            0.0,
            self._safe_float(AUTO_PILOT_ROTATION_WEAK_SCORE, 0.0) + bonus,
        )
        result["required_abs_score"] = required_abs_score

        if best_score < required_abs_score:
            result["allowed"] = False
            result["reason"] = (
                f"best_score={best_score:.1f} below low-budget floor {required_abs_score:.1f}"
            )
            return result

        if current_score is not None:
            actual_gap = best_score - self._safe_float(current_score, 0.0)
            required_gap = max(0.0, self._safe_float(base_score_threshold, 0.0) + bonus)
            result["actual_score_gap"] = actual_gap
            result["required_score_gap"] = required_gap
            if actual_gap < required_gap:
                result["allowed"] = False
                result["reason"] = (
                    f"score_gap={actual_gap:.1f} below low-budget requirement {required_gap:.1f}"
                )
            return result

        if second_best_score is not None:
            actual_gap = best_score - self._safe_float(second_best_score, 0.0)
            result["actual_score_gap"] = actual_gap
            result["required_score_gap"] = bonus
            if actual_gap < bonus:
                result["allowed"] = False
                result["reason"] = (
                    f"top gap={actual_gap:.1f} below low-budget requirement {bonus:.1f}"
                )
        return result

    def _get_auto_pilot_velocity_score_adjustment(
        self,
        candidate: Dict[str, Any],
    ) -> Tuple[float, Optional[str]]:
        if not AUTO_PILOT_VELOCITY_FACTOR_ENABLED:
            return 0.0, None

        raw_velocity = candidate.get("price_velocity")
        if raw_velocity is None:
            return 0.0, None

        velocity = self._to_float(raw_velocity)
        reference = max(AUTO_PILOT_VELOCITY_REFERENCE_PER_HOUR, 0.0001)
        normalized = max(-1.0, min(1.0, velocity / reference))
        mode = str(candidate.get("recommended_mode") or "").strip().lower()
        adjustment = 0.0

        if mode == "long":
            adjustment = normalized * AUTO_PILOT_VELOCITY_WEIGHT
        elif mode == "short":
            adjustment = -normalized * AUTO_PILOT_VELOCITY_WEIGHT
        elif mode in {"neutral", "neutral_classic_bybit"}:
            # Dampened neutral penalty: full weight only above 0.7 normalized
            dampen = 1.0 if abs(normalized) > 0.7 else 0.25
            adjustment = -abs(normalized) * AUTO_PILOT_VELOCITY_WEIGHT * dampen
        elif mode in {"scalp_pnl", "scalp_market"}:
            adjustment = abs(normalized) * (AUTO_PILOT_VELOCITY_WEIGHT * 0.5)

        if abs(adjustment) < 0.01:
            return 0.0, None

        return round(adjustment, 2), (
            f"velocity{adjustment:+.1f}@{velocity * 100:.2f}%/hr"
        )

    def _compute_auto_pilot_rotation_interval(
        self,
        bot: Dict[str, Any],
        current_candidate: Optional[Dict[str, Any]],
        best_candidate: Optional[Dict[str, Any]],
        score_gap: float,
        urgent_rotation: bool = False,
    ) -> Dict[str, Any]:
        settings = self._get_auto_pilot_rotation_settings(bot)
        base_seconds = settings["base_seconds"]
        effective_seconds = base_seconds
        reasons: List[str] = []

        if settings["adaptive_enabled"] and not urgent_rotation:
            weak_score = self._safe_float(
                bot.get("auto_pilot_rotation_weak_score"),
                AUTO_PILOT_ROTATION_WEAK_SCORE,
            )
            healthy_score = self._safe_float(
                bot.get("auto_pilot_rotation_healthy_score"),
                AUTO_PILOT_ROTATION_HEALTHY_SCORE,
            )
            high_volatility_atr = self._safe_float(
                bot.get("auto_pilot_rotation_high_volatility_atr_pct"),
                AUTO_PILOT_ROTATION_HIGH_VOLATILITY_ATR_PCT,
            )
            velocity_collapse = self._safe_float(
                bot.get("auto_pilot_velocity_collapse_pct_per_hour"),
                AUTO_PILOT_VELOCITY_COLLAPSE_PCT_PER_HOUR,
            )
            current_score = self._to_float(
                (current_candidate or {}).get("_auto_pilot_score"),
                self._to_float(bot.get("auto_pilot_current_score")),
            )
            current_atr = max(
                0.0,
                self._to_float((current_candidate or {}).get("atr_pct")),
            )
            current_velocity = abs(
                self._to_float((current_candidate or {}).get("price_velocity"))
            )
            best_velocity = abs(
                self._to_float((best_candidate or {}).get("price_velocity"))
            )
            current_mode = str(
                (current_candidate or {}).get("recommended_mode")
                or bot.get("mode")
                or ""
            ).strip().lower()

            if current_score > 0 and current_score < weak_score:
                effective_seconds *= 0.75
                reasons.append("current_symbol_weak")

            if current_atr >= high_volatility_atr:
                effective_seconds *= 0.8
                reasons.append("volatility_high")
            elif (
                current_atr > 0
                and current_atr < (high_volatility_atr * 0.5)
                and current_score >= healthy_score
                and score_gap <= (settings["score_threshold"] * 0.5)
            ):
                effective_seconds *= 1.1
                reasons.append("volatility_calm")

            if score_gap >= max(settings["score_threshold"] + 5.0, 20.0):
                effective_seconds *= 0.75
                reasons.append("score_gap_strong")
            elif (
                current_score >= healthy_score
                and score_gap <= (settings["score_threshold"] * 0.5)
            ):
                effective_seconds *= 1.15
                reasons.append("current_symbol_healthy")

            if (
                current_mode in {"long", "short", "scalp_pnl", "scalp_market"}
                and current_velocity <= velocity_collapse
            ):
                effective_seconds *= 0.9
                reasons.append("velocity_collapsing")

            if (
                best_velocity >= (current_velocity + velocity_collapse)
                and score_gap >= max(5.0, settings["score_threshold"] * 0.5)
            ):
                effective_seconds *= 0.85
                reasons.append("better_velocity")

        effective_seconds = int(
            max(
                settings["min_seconds"],
                min(settings["max_seconds"], round(effective_seconds)),
            )
        )

        # Feature 4C: Regime-adaptive rotation speed — floor on deterioration
        if REGIME_ADAPTIVE_ROTATION_ENABLED and not urgent_rotation:
            current_symbol = str(
                (current_candidate or {}).get("symbol")
                or bot.get("symbol")
                or ""
            ).strip().upper()
            if current_symbol and current_symbol != "AUTO-PILOT":
                deterioration_floor = self._check_regime_deterioration(bot, current_symbol)
                if deterioration_floor is not None:
                    if effective_seconds > deterioration_floor:
                        effective_seconds = deterioration_floor
                        reasons.append("regime_deterioration_fast_check")

        if not reasons:
            reasons = ["base_interval"]

        return {
            "base_seconds": base_seconds,
            "effective_seconds": effective_seconds,
            "reasons": reasons,
            "score_threshold": settings["score_threshold"],
        }

    def _get_time_of_day_adjustment(self, symbol: str, category: str) -> float:
        """
        Feature 1D: Time-of-Day Performance Weighting.

        Computes a score adjustment based on historical win rate in the current
        2-hour UTC bucket. Returns a bonus (up to TIME_OF_DAY_MAX_BONUS) for
        high win-rate periods and a penalty (up to TIME_OF_DAY_MAX_PENALTY) for
        poor win-rate periods. Returns 0.0 if disabled or insufficient data.
        """
        try:
            if not TIME_OF_DAY_WEIGHTING_ENABLED:
                return 0.0

            now_utc = datetime.now(timezone.utc)
            hour = now_utc.hour
            bucket = (hour // TIME_OF_DAY_BUCKET_HOURS) * TIME_OF_DAY_BUCKET_HOURS

            pnl_service = getattr(self, "pnl_service", None)
            if pnl_service is None:
                return 0.0

            try:
                trade_logs = pnl_service.get_log()
            except Exception:
                return 0.0

            if not trade_logs:
                return 0.0

            bucket_wins = 0
            bucket_total = 0
            for entry in trade_logs:
                # Filter by category/mode when available
                entry_mode = str(entry.get("mode") or "").strip().lower()
                entry_category = str(category or "").strip().lower()
                if entry_category and entry_mode and entry_mode != entry_category:
                    continue

                time_str = str(entry.get("time") or "").strip()
                if not time_str:
                    continue
                try:
                    if time_str.endswith("Z"):
                        time_str = time_str[:-1] + "+00:00"
                    trade_dt = datetime.fromisoformat(time_str)
                    if trade_dt.tzinfo is None:
                        trade_dt = trade_dt.replace(tzinfo=timezone.utc)
                    trade_hour = trade_dt.astimezone(timezone.utc).hour
                    trade_bucket = (trade_hour // TIME_OF_DAY_BUCKET_HOURS) * TIME_OF_DAY_BUCKET_HOURS
                    if trade_bucket != bucket:
                        continue
                except Exception:
                    continue

                try:
                    pnl_val = float(entry.get("pnl") or 0.0)
                except (TypeError, ValueError):
                    continue

                bucket_total += 1
                if pnl_val > 0:
                    bucket_wins += 1

            if bucket_total < TIME_OF_DAY_MIN_TRADES:
                return 0.0

            win_rate = bucket_wins / bucket_total

            if win_rate > 0.60:
                # Linear bonus: 0 at 60%, max at 100%
                factor = (win_rate - 0.60) / 0.40
                return round(min(TIME_OF_DAY_MAX_BONUS, factor * TIME_OF_DAY_MAX_BONUS), 2)
            elif win_rate < 0.40:
                # Linear penalty: 0 at 40%, max at 0%
                factor = (0.40 - win_rate) / 0.40
                return round(-min(TIME_OF_DAY_MAX_PENALTY, factor * TIME_OF_DAY_MAX_PENALTY), 2)

            return 0.0

        except Exception:
            return 0.0

    def _check_regime_deterioration(
        self, bot: Dict[str, Any], symbol: str
    ) -> Optional[int]:
        """
        Feature 4C: Regime-Adaptive Rotation Speed.

        Detects if the regime has deteriorated (e.g., trending→choppy,
        trending→illiquid) since the last known state for this symbol.
        Returns REGIME_DETERIORATION_FAST_CHECK_SEC if a recent deterioration
        is detected and hasn't already triggered a fast check within 120s.
        Returns None if no deterioration or feature is disabled.
        """
        if not REGIME_ADAPTIVE_ROTATION_ENABLED:
            return None

        try:
            entry_filter = getattr(self, "entry_filter", None)
            if entry_filter is None:
                entry_filter = getattr(self, "entry_filter_service", None)
            if entry_filter is None:
                return None

            try:
                regime_result = entry_filter.classify_regime(symbol)
            except Exception:
                return None

            current_regime = str(regime_result.get("regime") or "").lower()

            last_regimes = bot.get("_last_regime_per_symbol") or {}
            last_regime = str(last_regimes.get(symbol) or "").lower()

            # Update stored regime
            if not isinstance(bot.get("_last_regime_per_symbol"), dict):
                bot["_last_regime_per_symbol"] = {}
            bot["_last_regime_per_symbol"][symbol] = current_regime

            if not last_regime or last_regime == current_regime:
                return None

            # Deterioration: was trending/good, now choppy/illiquid/blocked
            deteriorated_from = {"trending"}
            deteriorated_to = {"choppy", "illiquid", "blocked", "too_strong"}
            if last_regime in deteriorated_from and current_regime in deteriorated_to:
                # Guard against triggering more frequently than every 120s
                last_fast_check_ts = self._safe_float(
                    bot.get("_regime_deterioration_last_fast_check_ts"), 0.0
                )
                now_ts = time.time()
                if now_ts - last_fast_check_ts < 120:
                    return None
                bot["_regime_deterioration_last_fast_check_ts"] = now_ts
                return REGIME_DETERIORATION_FAST_CHECK_SEC

        except Exception:
            pass

        return None

    def _get_cross_symbol_correlation_adjustment(
        self, bot: Dict[str, Any], symbol: str
    ) -> float:
        """
        Feature 4D: Cross-Symbol Correlation Filter.

        Checks the correlation of `symbol` against all symbols held by other
        running bots. If the maximum Pearson correlation exceeds
        CROSS_SYMBOL_MAX_CORRELATION, returns a penalty of
        -CROSS_SYMBOL_PENALTY_POINTS. Uses a 300s TTL cache per symbol-pair
        to avoid repeated OHLCV fetches. Returns 0.0 if disabled or no
        correlation concern.
        """
        if not CROSS_SYMBOL_CORRELATION_FILTER_ENABLED:
            return 0.0

        try:
            # Collect symbols held by other running bots
            bot_id = str(bot.get("id") or "").strip()
            held_symbols: List[str] = []
            try:
                for b in self.bot_storage.list_bots():
                    b_id = str(b.get("id") or "").strip()
                    if b_id == bot_id:
                        continue
                    b_status = str(b.get("status") or "").strip().lower()
                    if b_status not in ("running", "recovering", "paused"):
                        continue
                    b_sym = str(b.get("symbol") or "").strip().upper()
                    if b_sym and b_sym != "AUTO-PILOT" and b_sym != symbol:
                        held_symbols.append(b_sym)
            except Exception:
                return 0.0

            if not held_symbols:
                return 0.0

            indicator_service = getattr(self, "indicator_service", None)
            if indicator_service is None:
                return 0.0

            # Correlation cache: {(sym_a, sym_b): {"ts": float, "corr": float}}
            if not hasattr(self, "_cross_symbol_corr_cache"):
                self._cross_symbol_corr_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

            now_ts = time.time()
            cache_ttl = 300.0

            max_corr = 0.0
            for held_sym in held_symbols:
                cache_key = (
                    (symbol, held_sym) if symbol < held_sym else (held_sym, symbol)
                )
                cached = self._cross_symbol_corr_cache.get(cache_key)
                if cached and (now_ts - cached.get("ts", 0.0)) < cache_ttl:
                    corr = cached["corr"]
                else:
                    try:
                        candles_a = indicator_service.get_ohlcv(symbol, interval="15", limit=50)
                        candles_b = indicator_service.get_ohlcv(held_sym, interval="15", limit=50)
                        closes_a = [float(c["close"]) for c in (candles_a or []) if c.get("close") is not None]
                        closes_b = [float(c["close"]) for c in (candles_b or []) if c.get("close") is not None]
                        min_len = min(len(closes_a), len(closes_b))
                        if min_len < 10:
                            corr = 0.0
                        else:
                            closes_a = closes_a[-min_len:]
                            closes_b = closes_b[-min_len:]
                            corr = self._compute_pearson_correlation(closes_a, closes_b)
                    except Exception:
                        corr = 0.0
                    self._cross_symbol_corr_cache[cache_key] = {"ts": now_ts, "corr": corr}

                if abs(corr) > max_corr:
                    max_corr = abs(corr)

            if max_corr > CROSS_SYMBOL_MAX_CORRELATION:
                return -CROSS_SYMBOL_PENALTY_POINTS

        except Exception:
            pass

        return 0.0

    def _compute_pearson_correlation(
        self, x: List[float], y: List[float]
    ) -> float:
        """Compute Pearson correlation coefficient between two equal-length series."""
        n = len(x)
        if n < 2 or len(y) != n:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((v - mean_x) ** 2 for v in x))
        std_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))
        if std_x == 0.0 or std_y == 0.0:
            return 0.0
        return cov / (std_x * std_y)

    def _score_auto_pilot_candidate(
        self,
        bot: Dict[str, Any],
        candidate: Dict[str, Any],
        entry_gate: Optional[Any] = None,
        neutral_gate: Optional[Any] = None,
        price_action_service: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Build a composite Auto-Pilot score centered on real entry suitability.

        The scanner's raw neutral_score is still useful context, but the picker
        should prioritize candidates whose entry zone and structure gates are safer.
        """
        symbol = str(candidate.get("symbol") or "").strip().upper()
        mode = str(candidate.get("recommended_mode") or "neutral").strip().lower()
        entry_zone = candidate.get("entry_zone") or {}
        entry_zone_score = self._to_float(entry_zone.get("score"))
        neutral_score = self._to_float(candidate.get("neutral_score"))
        mode_confidence = self._to_float(candidate.get("mode_confidence"))
        smart_score = self._to_float(candidate.get("smart_score"))
        score = entry_zone_score if entry_zone_score > 0 else neutral_score

        reasons: List[str] = []
        gate_summary = ""
        price_action_score = 0.0
        setup_quality_score = None

        if entry_zone_score > 0:
            reasons.append(f"entry_zone={entry_zone_score:.1f}")
        elif neutral_score > 0:
            reasons.append(f"neutral_score={neutral_score:.1f}")

        verdict = str(entry_zone.get("verdict") or "").strip().upper()
        if verdict == "GOOD":
            score += 8.0
            reasons.append("verdict=GOOD")
        elif verdict == "AVOID":
            score -= 15.0
            reasons.append("verdict=AVOID")

        confidence_bonus = min(15.0, mode_confidence * 15.0)
        if confidence_bonus > 0:
            score += confidence_bonus
            reasons.append(f"confidence+={confidence_bonus:.1f}")

        smart_bonus = min(10.0, smart_score * 0.10)
        if smart_bonus > 0:
            score += smart_bonus
            reasons.append(f"smart+={smart_bonus:.1f}")

        # Tier 1: Flow score bonus — prefer coins with directional conviction
        order_flow = getattr(self, "order_flow_service", None)
        if order_flow is not None:
            flow_state = order_flow.get_flow_state(symbol)
            flow_score = abs(self._safe_float(flow_state.get("flow_score"), 0.0))
            flow_conf = self._safe_float(flow_state.get("flow_confidence"), 0.0)
            if flow_score >= 25 and flow_conf >= 0.35:
                flow_bonus = min(12.0, flow_score * 0.15)
                score += flow_bonus
                reasons.append(f"flow+={flow_bonus:.1f}({flow_state.get('signal','?')})")

        # Tier 3: Per-coin performance memory — prefer coins that made money
        memory = getattr(self, "auto_pilot_memory", None)
        if memory is not None:
            # Rebuild periodically
            if memory.needs_rebuild():
                try:
                    memory.rebuild_from_trade_logs(self.pnl_service.get_log())
                except Exception:
                    pass
            # Score adjustment from historical performance
            mem_adjustment = memory.get_symbol_score_adjustment(symbol)
            if mem_adjustment != 0:
                score += mem_adjustment
                reasons.append(f"memory{mem_adjustment:+.0f}")
            # Block coins that consistently lose money
            if memory.should_avoid_symbol(symbol):
                score -= 30.0
                reasons.append("AVOID:track_record")

        velocity_adjustment, velocity_reason = (
            self._get_auto_pilot_velocity_score_adjustment(candidate)
        )
        if velocity_adjustment != 0:
            score += velocity_adjustment
            if velocity_reason:
                reasons.append(velocity_reason)

        # ADX momentum bonus — reward trending candidates, penalize overheated
        if AUTO_PILOT_ADX_MOMENTUM_BONUS_ENABLED:
            adx_val = self._to_float(candidate.get("adx"))
            if adx_val > 0:
                min_adx = AUTO_PILOT_ADX_MOMENTUM_BONUS_MIN_ADX
                max_adx = AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_ADX
                max_pts = AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_POINTS
                if adx_val > max_adx:
                    adx_bonus = AUTO_PILOT_ADX_MOMENTUM_BONUS_OVERHEATED_PENALTY
                    reasons.append(f"adx_overheated{adx_bonus:+.1f}@{adx_val:.1f}")
                    score += adx_bonus
                elif adx_val >= min_adx:
                    midpoint = (min_adx + max_adx) / 2.0
                    half_range = (max_adx - min_adx) / 2.0
                    # Triangle peak at midpoint
                    raw_bonus = max_pts * (1.0 - abs(adx_val - midpoint) / half_range)
                    # Neutral modes get half bonus
                    if mode in {"neutral", "neutral_classic_bybit"}:
                        raw_bonus *= 0.5
                    adx_bonus = round(raw_bonus, 2)
                    if adx_bonus != 0:
                        score += adx_bonus
                        reasons.append(f"adx_momentum+={adx_bonus:.1f}@{adx_val:.1f}")

        # 1h ADX extreme check — coin will be immediately frozen by grid bot
        from config.strategy_config import ADX_EXTREME_FREEZE_THRESHOLD
        htf_adx_val = self._to_float(candidate.get("htf_adx"))
        if htf_adx_val > 0 and htf_adx_val >= ADX_EXTREME_FREEZE_THRESHOLD:
            score -= 50.0
            reasons.append(f"htf_adx_frozen{-50.0:+.1f}@{htf_adx_val:.1f}")

        # Funding rate harvesting bonus — reward candidates where mode earns funding
        funding_rate_val = self._to_float(candidate.get("funding_rate"))
        if funding_rate_val != 0:
            earns_funding = (
                (funding_rate_val < 0 and mode == "long")
                or (funding_rate_val > 0 and mode == "short")
            )
            abs_rate = abs(funding_rate_val)
            if earns_funding and abs_rate > 0.0005:
                funding_bonus = min(6.0, abs_rate * 100 * 20)
                score += funding_bonus
                reasons.append(f"funding_harvest+={funding_bonus:.1f}({funding_rate_val*100:+.4f}%)")
            elif not earns_funding and abs_rate > 0.0008:
                funding_penalty = min(4.0, abs_rate * 100 * 10)
                score -= funding_penalty
                reasons.append(f"funding_cost-={funding_penalty:.1f}({funding_rate_val*100:+.4f}%)")

        best_for = str(entry_zone.get("best_for") or "").strip().lower()
        if best_for == "neutral_classic":
            best_for = "neutral_classic_bybit"
        if best_for and best_for == mode:
            score += 4.0
            reasons.append("best_for_match")

        if price_action_service and symbol:
            try:
                price_action_context = price_action_service.analyze(symbol=symbol)
                mode_price_action = price_action_service.score_mode_fit(
                    context=price_action_context,
                    mode=mode,
                )
                price_action_score = self._to_float(mode_price_action.get("score"))
                if price_action_score != 0:
                    score += price_action_score
                    reasons.append(f"price_action{price_action_score:+.1f}")
                price_action_direction = str(
                    price_action_context.get("direction") or ""
                ).strip()
                if price_action_direction:
                    reasons.append(f"price_dir={price_action_direction}")
            except Exception as price_action_exc:
                logger.debug(
                    "[Auto-Pilot] Price-action scoring failed for %s: %s",
                    symbol,
                    price_action_exc,
                )

        if entry_gate and symbol:
            try:
                from config.strategy_config import (
                    SETUP_QUALITY_AUTO_PILOT_SCORE_WEIGHT,
                    SETUP_QUALITY_AUTO_PILOT_MIN_SCORE,
                )

                quality_indicators = {
                    "atr_pct": candidate.get("atr_pct"),
                    "bbw_pct": candidate.get("bbw_pct"),
                    "price_velocity": candidate.get("price_velocity"),
                }
                setup_quality = entry_gate.get_setup_quality(
                    symbol=symbol,
                    mode=mode,
                    indicators=quality_indicators,
                )
                if isinstance(setup_quality, dict):
                    setup_quality_score = self._to_float(setup_quality.get("score"))
                if isinstance(setup_quality, dict) and setup_quality.get("enabled"):
                    if setup_quality_score < SETUP_QUALITY_AUTO_PILOT_MIN_SCORE:
                        score -= 100.0
                        reasons.append(
                            f"setup_quality_blocked@{setup_quality_score:.1f}"
                            f"<{SETUP_QUALITY_AUTO_PILOT_MIN_SCORE:.0f}"
                        )
                    else:
                        quality_adjustment = (
                            (setup_quality_score - 50.0)
                            * self._to_float(
                                SETUP_QUALITY_AUTO_PILOT_SCORE_WEIGHT, 0.20
                            )
                        )
                        if quality_adjustment != 0:
                            score += quality_adjustment
                            reasons.append(
                                f"setup_quality{quality_adjustment:+.1f}@{setup_quality_score:.1f}"
                            )
            except Exception as setup_quality_exc:
                logger.debug(
                    "[Auto-Pilot] Setup-quality scoring failed for %s: %s",
                    symbol,
                    setup_quality_exc,
                )

        if entry_gate and symbol:
            try:
                neutral_modes = {"neutral", "neutral_classic_bybit"}
                scalp_modes = {"scalp_pnl", "scalp_market"}
                if mode in ("long", "short"):
                    gate_result = entry_gate.check_entry(symbol=symbol, mode=mode, bot=bot)
                    if gate_result.get("suitable", True):
                        score += 8.0
                        gate_summary = "entry_gate=clear"
                    else:
                        score -= 35.0
                        gate_summary = (
                            "entry_gate=blocked:"
                            f"{gate_result.get('reason', 'unsafe entry')}"
                        )
                elif mode in neutral_modes or mode in scalp_modes:
                    buy_result = entry_gate.check_side_open(symbol=symbol, side="Buy")
                    sell_result = entry_gate.check_side_open(symbol=symbol, side="Sell")
                    blocked_sides = []
                    if not buy_result.get("suitable", True):
                        blocked_sides.append("buy")
                    if not sell_result.get("suitable", True):
                        blocked_sides.append("sell")

                    if blocked_sides:
                        if len(blocked_sides) == 2:
                            score -= 30.0 if mode in neutral_modes else 18.0
                        else:
                            score -= 14.0 if mode in neutral_modes else 8.0
                        gate_summary = (
                            "structure_gate="
                            f"{'/'.join(blocked_sides)} blocked"
                        )
                    else:
                        score += 6.0 if mode in neutral_modes else 4.0
                        gate_summary = "structure_gate=clear"
                if gate_summary:
                    reasons.append(gate_summary)
            except Exception as gate_exc:
                logger.debug(
                    "[Auto-Pilot] Candidate gate scoring failed for %s: %s",
                    symbol,
                    gate_exc,
                )

        if neutral_gate and symbol and mode in {"neutral", "neutral_classic_bybit"}:
            try:
                gate_result = neutral_gate.check_suitability(
                    symbol=symbol,
                    preset=bot.get("neutral_preset"),
                )
                if gate_result.get("suitable", True):
                    score += 8.0
                    reasons.append("neutral_gate=clear")
                else:
                    score -= 45.0
                    reasons.append("neutral_gate=blocked")
            except Exception as neutral_gate_exc:
                logger.debug(
                    "[Auto-Pilot] Neutral suitability scoring failed for %s: %s",
                    symbol,
                    neutral_gate_exc,
                )

        # Session-aware scoring: adjust based on time-of-day suitability
        from config.strategy_config import SESSION_TRADING_ENABLED, SESSION_MAX_SCORE
        if SESSION_TRADING_ENABLED and hasattr(self, "session_service") and self.session_service:
            try:
                session_sig = self.session_service.get_session_signal(max_score=SESSION_MAX_SCORE)
                session_mod = float(session_sig.get("score_modifier") or 0) * SESSION_MAX_SCORE
                if session_mod != 0:
                    score += session_mod
                    reasons.append(f"session{session_mod:+.0f}")
                # Penalize volatile coins during low-liquidity sessions
                session_name = str(session_sig.get("session") or "").lower()
                if session_name in ("late", "weekend"):
                    atr_pct = float(candidate.get("atr_pct") or candidate.get("atr_percent") or 0)
                    if atr_pct > 0.03:
                        score -= 5.0
                        reasons.append("volatile_low_liq")
            except Exception:
                pass

        # Feature 1D: Time-of-day performance weighting
        if TIME_OF_DAY_WEIGHTING_ENABLED and symbol:
            tod_adjustment = self._get_time_of_day_adjustment(symbol, mode)
            if tod_adjustment != 0.0:
                score += tod_adjustment
                reasons.append(f"tod{tod_adjustment:+.1f}")

        # Feature 4D: Cross-symbol correlation filter
        if CROSS_SYMBOL_CORRELATION_FILTER_ENABLED and symbol:
            corr_adjustment = self._get_cross_symbol_correlation_adjustment(bot, symbol)
            if corr_adjustment != 0.0:
                score += corr_adjustment
                reasons.append(f"corr_penalty{corr_adjustment:+.1f}")

        return {
            "score": round(score, 2),
            "reasons": reasons,
            "gate_summary": gate_summary,
            "price_action_score": round(price_action_score, 2),
            "setup_quality_score": round(setup_quality_score, 2)
            if setup_quality_score is not None
            else None,
        }

    def _rank_auto_pilot_candidates(
        self, bot: Dict[str, Any], scan_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        ranked_results: List[Dict[str, Any]] = []
        entry_gate = None
        neutral_gate = None
        price_action_service = None
        try:
            entry_gate = self._build_entry_gate_service()
        except Exception as entry_gate_exc:
            logger.debug(
                "[Auto-Pilot] Entry gate unavailable during ranking: %s",
                entry_gate_exc,
            )
        try:
            neutral_gate = self._build_neutral_suitability_service()
        except Exception as neutral_gate_exc:
            logger.debug(
                "[Auto-Pilot] Neutral suitability unavailable during ranking: %s",
                neutral_gate_exc,
            )
        try:
            price_action_service = self._build_price_action_signal_service()
        except Exception as price_action_exc:
            logger.debug(
                "[Auto-Pilot] Price-action service unavailable during ranking: %s",
                price_action_exc,
            )

        for raw_result in scan_results or []:
            candidate = dict(raw_result)
            score_data = self._score_auto_pilot_candidate(
                bot,
                candidate,
                entry_gate=entry_gate,
                neutral_gate=neutral_gate,
                price_action_service=price_action_service,
            )
            candidate["_auto_pilot_score"] = score_data["score"]
            candidate["_auto_pilot_rank_reasons"] = score_data["reasons"]
            candidate["_auto_pilot_gate_summary"] = score_data["gate_summary"]
            candidate["_auto_pilot_price_action_score"] = score_data.get(
                "price_action_score",
                0.0,
            )
            candidate["_auto_pilot_setup_quality_score"] = score_data.get(
                "setup_quality_score"
            )
            ranked_results.append(candidate)

        ranked_results.sort(
            key=lambda candidate: (
                self._to_float(candidate.get("_auto_pilot_score")),
                self._to_float(candidate.get("_auto_pilot_setup_quality_score")),
                self._to_float(candidate.get("_auto_pilot_price_action_score")),
                self._to_float((candidate.get("entry_zone") or {}).get("score")),
                self._to_float(candidate.get("neutral_score")),
            ),
            reverse=True,
        )
        return ranked_results

    def _auto_pilot_should_force_repick(
        self,
        bot: Dict[str, Any],
        current_symbol: str,
    ) -> bool:
        # Tier 2: Immediate rotation on flow reversal
        if bot.get("_auto_pilot_force_rotation"):
            bot.pop("_auto_pilot_force_rotation", None)
            logger.warning(
                "[%s] Auto-Pilot forced rotation due to: %s",
                current_symbol,
                bot.get("auto_pilot_rotation_forced_reason", "manual"),
            )
            return True

        # Idle/no-fill detection: orders placed but no fills for N seconds
        from config.strategy_config import AUTO_PILOT_IDLE_NO_FILL_ROTATION_SECONDS
        idle_timeout = max(0, int(AUTO_PILOT_IDLE_NO_FILL_ROTATION_SECONDS or 0))
        if idle_timeout > 0:
            first_orders_ts = self._safe_float(bot.get("auto_pilot_first_orders_at"), 0.0)
            last_fill_ts = self._safe_float(bot.get("auto_pilot_last_fill_at"), 0.0)
            if first_orders_ts > 0 and last_fill_ts <= 0:
                idle_duration = time.time() - first_orders_ts
                if idle_duration >= idle_timeout:
                    try:
                        positions_resp = self.client.get_positions(skip_cache=True)
                        pos_list = (
                            positions_resp.get("data", {}).get("list", [])
                            if positions_resp.get("success") else []
                        )
                        has_position = any(
                            float(p.get("size", 0) or 0) > 0
                            for p in (pos_list or [])
                            if p.get("symbol") == current_symbol
                        )
                        if not has_position:
                            logger.warning(
                                "[%s] Auto-Pilot IDLE ROTATION: no fills after %.0fs",
                                current_symbol, idle_duration,
                            )
                            return True
                    except Exception:
                        pass

        force_after_seconds = 120
        current_mode = str(bot.get("mode") or "").lower()
        neutral_modes = {"neutral", "neutral_classic_bybit"}

        structure_fully_blocked = (
            current_mode in neutral_modes
            and bot.get("_entry_structure_skip_buy")
            and bot.get("_entry_structure_skip_sell")
        )
        opening_blocked = (
            bot.get("_block_opening_orders")
            or bot.get("_small_capital_block_opening_orders")
            or bot.get("_nlp_block_opening_orders")
            or bot.get("_entry_gate_blocked")
            or structure_fully_blocked
        )
        if not opening_blocked:
            bot.pop("auto_pilot_opening_blocked_since", None)
            return False

        try:
            positions_resp = self.client.get_positions(skip_cache=True)
            pos_list = (
                positions_resp.get("data", {}).get("list", [])
                if positions_resp.get("success")
                else []
            )
            for pos in pos_list or []:
                if pos.get("symbol") != current_symbol:
                    continue
                size = float(pos.get("size", 0) or 0)
                if size > 0:
                    bot.pop("auto_pilot_opening_blocked_since", None)
                    return False
        except Exception as exc:
            logger.debug(
                "[Auto-Pilot] Force re-pick position check failed for %s: %s",
                current_symbol,
                exc,
            )
            return False

        try:
            orders_resp = self.client.get_open_orders(
                symbol=current_symbol,
                skip_cache=True,
            )
            if self._extract_order_list_from_response(orders_resp):
                bot.pop("auto_pilot_opening_blocked_since", None)
                return False
        except Exception as exc:
            logger.debug(
                "[Auto-Pilot] Force re-pick order check failed for %s: %s",
                current_symbol,
                exc,
            )
            return False

        now_ts = time.time()
        blocked_since = self._safe_float(
            bot.get("auto_pilot_opening_blocked_since"),
            0.0,
        )
        if blocked_since <= 0:
            bot["auto_pilot_opening_blocked_since"] = now_ts
            return False
        return (now_ts - blocked_since) >= force_after_seconds

    def _auto_pilot_pending_rotation_ready(
        self,
        bot: Dict[str, Any],
        current_symbol: str,
    ) -> bool:
        if not bot.get("auto_pilot_rotation_pending"):
            return False

        # Timeout check — don't wait forever for a losing position
        from config.strategy_config import AUTO_PILOT_PENDING_ROTATION_TIMEOUT_SEC
        pending_since = str(bot.get("auto_pilot_rotation_pending_since") or "").strip()
        if pending_since:
            try:
                since_ts = datetime.fromisoformat(pending_since.replace("Z", "+00:00")).timestamp()
                age = time.time() - since_ts
                if age >= AUTO_PILOT_PENDING_ROTATION_TIMEOUT_SEC:
                    bot_id = str(bot.get("id") or "")[:8]
                    logger.warning(
                        "[Auto-Pilot:%s] Pending rotation TIMED OUT after %.0fs on %s — forcing rotation",
                        bot_id, age, current_symbol,
                    )
                    return True  # Force ready even if position exists
            except (ValueError, TypeError):
                pass

        try:
            positions_resp = self.client.get_positions(skip_cache=True)
            pos_list = (
                positions_resp.get("data", {}).get("list", [])
                if positions_resp.get("success")
                else []
            )
            for pos in pos_list or []:
                if pos.get("symbol") != current_symbol:
                    continue
                size = float(pos.get("size", 0) or 0)
                if size > 0:
                    return False
            return True
        except Exception as exc:
            logger.debug(
                "[Auto-Pilot] Pending rotation readiness check failed for %s: %s",
                current_symbol,
                exc,
            )
            return False

    def _apply_auto_pilot_selection(
        self,
        bot: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> str:
        picked_symbol = str(candidate.get("symbol") or "").strip().upper()
        selected_mode = str(candidate.get("recommended_mode") or "neutral").strip().lower()
        selected_levels = max(
            2,
            int(self._safe_float(candidate.get("recommended_grid_levels"), 10)),
        )
        suggested_range = candidate.get("suggested_range", {}) or {}
        lower = suggested_range.get("lower")
        upper = suggested_range.get("upper")

        self._clear_opening_block_flags(bot)
        bot["symbol"] = picked_symbol
        bot["mode"] = selected_mode
        bot["profile"] = candidate.get("recommended_profile", "normal")
        bot["range_mode"] = candidate.get("recommended_range_mode", "dynamic")

        # ===== TIER 1: Smart Auto-Config =====
        investment = self._safe_float(bot.get("investment"), 35.0)

        # Tier 3: Risk scaling — adjust EFFECTIVE investment (not stored value) based on performance
        memory = getattr(self, "auto_pilot_memory", None)
        if memory is not None:
            risk_mult = memory.get_risk_multiplier(picked_symbol)
            if risk_mult != 1.0:
                effective_investment = round(investment * risk_mult, 2)
                bot["_auto_pilot_effective_investment"] = effective_investment
                logger.info(
                    "[%s] Auto-Pilot risk scaling: %.1fx (effective=$%.2f, base=$%.2f)",
                    picked_symbol, risk_mult, effective_investment, investment,
                )
            else:
                bot.pop("_auto_pilot_effective_investment", None)

        # Auto-leverage: use scanner recommendation, cap for neutral modes (need margin for both sides)
        scanner_leverage = self._safe_float(candidate.get("recommended_leverage"), 5)
        atr_pct = self._safe_float(candidate.get("atr_pct"), 0.01)
        is_neutral_mode = selected_mode in ("neutral", "neutral_classic_bybit", "neutral_dynamic")

        if is_neutral_mode:
            # Neutral grids need 2x margin (buy + sell active simultaneously)
            auto_leverage = min(scanner_leverage, 5.0)
        elif atr_pct >= 0.03:
            auto_leverage = 5.0
        elif atr_pct >= 0.015:
            auto_leverage = 7.0
        else:
            auto_leverage = 8.0
        bot["leverage"] = auto_leverage

        # Auto-grid count: investment × leverage ÷ min_notional, capped 5-15
        notional = investment * auto_leverage
        min_notional = self._safe_float(candidate.get("min_notional_value"), 5.0) or 5.0
        # Neutral modes need margin for both sides — halve available notional for grid sizing
        effective_notional = notional / 2.0 if is_neutral_mode else notional
        auto_grids = max(5, min(15, int(effective_notional / (min_notional * 1.5))))
        # Leverage-aware grid cap — fewer levels at high leverage to prevent
        # tight spacing that causes premature fills and fee-dominated losses
        leverage_grid_cap = max(5, int(15 / max(1.0, auto_leverage / 5.0)))
        auto_grids = min(auto_grids, leverage_grid_cap)
        # Respect scanner's recommended grid count (based on range width)
        scanner_grids = int(self._safe_float(candidate.get("recommended_grid_levels"), auto_grids))
        if scanner_grids >= 5:
            auto_grids = min(auto_grids, scanner_grids)
        bot["grids"] = auto_grids
        bot["grid_count"] = auto_grids
        bot["target_grid_count"] = auto_grids

        # Auto-range: ATR-based, tight enough for small capital
        # Range = 3x ATR (captures 1 normal move above + below current price)
        last_price = self._safe_float(candidate.get("last_price"), 0.0)
        if last_price > 0 and atr_pct > 0:
            range_half = last_price * atr_pct * 1.5  # 1.5x ATR on each side
            lower = round(last_price - range_half, 8)
            upper = round(last_price + range_half, 8)
            if lower > 0 and upper > lower:
                suggested_range = {"lower": lower, "upper": upper}

        # Don't auto-enable auto_direction — causes MEME guard conflicts
        bot["auto_direction"] = False
        bot["last_error"] = None
        bot["error_code"] = None
        self._set_bot_current_price(bot, 0.0, symbol=picked_symbol)
        bot["last_trade_price"] = None
        bot["open_order_count"] = 0
        bot["entry_orders_open"] = 0
        bot["exit_orders_open"] = 0
        bot["active_long_slots"] = 0
        bot["active_short_slots"] = 0
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False
        bot["neutral_grid_last_reconcile_at"] = None
        bot["grid_levels_total_effective"] = None
        bot["levels_count"] = None
        bot["mid_index"] = None
        bot["last_fill_event"] = None
        bot["auto_pilot_first_orders_at"] = None
        bot["auto_pilot_last_fill_at"] = None
        bot["last_replacement_action"] = None
        bot["_last_recenter_ts"] = None
        bot["_position_mode"] = None
        bot["_position_mode_ts"] = None
        # Tier 1: Auto-Pilot always uses profit protection in live mode
        bot["profit_protection_mode"] = "partial_live"
        bot["auto_margin"] = {"enabled": True}  # Enabled but fresh state — reserve only activates when position exists
        bot["auto_margin_state"] = {}  # Clear state so no stale reserve from previous coin
        bot.pop("_margin_insufficient_block", None)
        bot.pop("_auto_margin_skip_until", None)
        bot.pop("_margin_reserve_held", None)
        # Reset loss budget baseline so new coin starts fresh
        bot["auto_pilot_loss_budget_realized_baseline"] = self._safe_float(
            bot.get("realized_pnl"), 0.0
        )
        # Tier 2: Wait for flow confirmation before placing orders
        bot["_auto_pilot_entry_hold"] = True
        bot["_auto_pilot_entry_hold_until"] = time.time() + 10.0  # Max 10s wait (was 60s — too much slippage)
        bot["_auto_pilot_picked_mode"] = selected_mode
        auto_pilot_score = self._to_float(
            candidate.get("_auto_pilot_score"),
            self._to_float(candidate.get("neutral_score")),
        )
        auto_pilot_reasons = [
            str(reason)
            for reason in (candidate.get("_auto_pilot_rank_reasons") or [])
            if str(reason).strip()
        ]
        bot["auto_pilot_last_pick_score"] = round(auto_pilot_score, 2)
        bot["auto_pilot_last_pick_summary"] = ", ".join(auto_pilot_reasons[:4]) or None
        bot["auto_pilot_last_pick_eligibility"] = candidate.get(
            "_auto_pilot_eligibility_status"
        )
        bot["auto_pilot_last_pick_at"] = datetime.now(timezone.utc).isoformat()
        self._set_runtime_mode_metadata(
            bot,
            effective_mode=selected_mode,
            effective_range_mode=bot.get("range_mode"),
            source="auto_pilot_selection",
            non_persistent=True,
        )

        if lower and upper:
            bot["lower_price"] = lower
            bot["upper_price"] = upper
        else:
            bot["lower_price"] = None
            bot["upper_price"] = None

        if selected_mode == "neutral_classic_bybit":
            bot["grid_levels_total"] = selected_levels
            bot["grid_lower_price"] = lower if lower and upper else None
            bot["grid_upper_price"] = upper if lower and upper else None
        else:
            bot["grid_levels_total"] = None
            bot["grid_lower_price"] = None
            bot["grid_upper_price"] = None

        self._normalize_mode_range_state(bot)

        return picked_symbol

    def _get_auto_pilot_pick_block_log_cache(self) -> Dict[str, Dict[str, Any]]:
        cache = getattr(self, "_auto_pilot_pick_block_log_state", None)
        if not isinstance(cache, dict):
            cache = {}
            self._auto_pilot_pick_block_log_state = cache
        return cache

    @staticmethod
    def _get_auto_pilot_pick_block_log_key(bot: Optional[Dict[str, Any]]) -> str:
        bot_id = str((bot or {}).get("id") or "").strip()
        return bot_id or f"anon:{id(bot)}"

    def _clear_auto_pilot_pick_block_log_state(
        self,
        bot: Optional[Dict[str, Any]],
    ) -> None:
        cache = self._get_auto_pilot_pick_block_log_cache()
        cache.pop(self._get_auto_pilot_pick_block_log_key(bot), None)

    def _auto_pilot_pick_symbol(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-Pilot: scan top coins and pick the best one for trading.
        
        Called when symbol is 'Auto-Pilot' — before any exchange API calls.
        Picks a coin, configures the bot, sets up exchange, saves, and returns.
        The NEXT cycle will use the real symbol.
        """
        try:
            # Refresh the authoritative bot row before mutating it so a stale
            # runner snapshot cannot lose newer control/settings versions.
            bot = self._refresh_persisted_bot_snapshot(bot)
            ranked_results = self._get_ranked_auto_pilot_candidates(
                bot,
                reason="pick",
            )
            if not ranked_results:
                self._clear_auto_pilot_pick_block_log_state(bot)
                self._set_auto_pilot_pick_runtime_state(
                    bot,
                    search_status="empty",
                    pick_status="no_candidate",
                )
                logger.warning("[Auto-Pilot] No ranked candidates available, skipping cycle")
                return bot
            best = ranked_results[0]
            candidate_source = self._normalize_auto_pilot_candidate_source(
                bot.get("_auto_pilot_candidate_source_hint")
            )
            self._set_auto_pilot_pick_runtime_state(
                bot,
                search_status="ok",
                pick_status="candidate_ready",
                top_candidate=best,
                candidate_source=candidate_source,
            )
            budget_state = self._refresh_auto_pilot_loss_budget_state(
                bot,
                None
                if self._is_auto_pilot_placeholder_symbol(bot.get("symbol"))
                else bot.get("symbol"),
            )
            if budget_state.get("status") == "blocked":
                self._set_auto_pilot_pick_runtime_state(
                    bot,
                    search_status="ok",
                    pick_status="blocked_loss_budget",
                    block_reason="remaining_loss_budget",
                    top_candidate=best,
                    candidate_source=candidate_source,
                )
                self._log_auto_pilot_pick_blocked_by_loss_budget(
                    bot,
                    budget_state,
                    top_candidate=best,
                    candidate_source=candidate_source,
                )
                self.bot_storage.save_bot(bot)
                return bot

            second_best_score = None
            if len(ranked_results) > 1:
                second_best_score = self._to_float(
                    ranked_results[1].get(
                        "_auto_pilot_score",
                        ranked_results[1].get("neutral_score", 0.0),
                    )
                )
            low_budget_check = self._check_auto_pilot_low_budget_candidate(
                bot,
                budget_state,
                best_score=self._to_float(
                    best.get("_auto_pilot_score", best.get("neutral_score", 0.0))
                ),
                second_best_score=second_best_score,
            )
            if not low_budget_check.get("allowed"):
                self._clear_auto_pilot_pick_block_log_state(bot)
                logger.info(
                    "[Auto-Pilot] Pick skipped under low remaining loss budget: %s",
                    low_budget_check.get("reason") or "candidate not strong enough",
                )
                self.bot_storage.save_bot(bot)
                return bot

            picked_symbol = best.get("symbol", "")

            if not picked_symbol:
                self._clear_auto_pilot_pick_block_log_state(bot)
                logger.warning("[Auto-Pilot] Scanner returned empty symbol, skipping cycle")
                return bot

            # Apply scanner recommendations to bot
            picked_symbol = self._apply_auto_pilot_selection(bot, best)
            self._clear_auto_pilot_pick_block_log_state(bot)
            self._set_auto_pilot_pick_runtime_state(
                bot,
                search_status="ok",
                pick_status="selected",
                top_candidate=best,
                candidate_source=candidate_source,
            )

            # Set up exchange for the new symbol
            try:
                leverage_to_set = int(bot.get("leverage", 3))
                self.client.set_margin_mode(picked_symbol, "ISOLATED_MARGIN")
                self.client.set_leverage(picked_symbol, leverage_to_set)
                logger.info(f"[Auto-Pilot] Exchange setup: {picked_symbol} leverage={leverage_to_set}x isolated")
            except Exception as ex_err:
                logger.warning(f"[Auto-Pilot] Exchange setup warning for {picked_symbol}: {ex_err}")

            self.bot_storage.save_bot(bot)
            score = best.get("_auto_pilot_score", best.get("neutral_score", 0))
            score_basis = ", ".join(best.get("_auto_pilot_rank_reasons", [])[:4])
            eligibility_status = best.get("_auto_pilot_eligibility_status")
            logger.info(
                f"[Auto-Pilot] Picked {picked_symbol} (score={score:.1f}) | mode={bot['mode']} "
                f"| profile={bot['profile']} | range={bot.get('lower_price')}-{bot.get('upper_price')} "
                f"| eligibility={eligibility_status or 'n/a'} | basis={score_basis}"
            )
            return bot

        except Exception as e:
            logger.error(f"[Auto-Pilot] Failed to pick symbol: {e}")
            return bot

    def _auto_pilot_check_rotation(self, bot: Dict[str, Any], current_symbol: str) -> Optional[Dict[str, Any]]:
        """Auto-Pilot rotation: periodically re-scan and switch to a better coin.
        
        Returns:
            bot dict if switched (caller should return immediately), 
            None if no switch needed (caller should continue normal cycle)
        """
        bot_id = bot.get("id", "")[:8]
        rotation_settings = self._get_auto_pilot_rotation_settings(bot)
        effective_rotation_interval = self._get_effective_auto_pilot_rotation_interval(
            bot
        )
        
        # Check if enough time has passed since last scan
        last_scan = bot.get("auto_pilot_last_scan_at")
        now = datetime.now(timezone.utc)
        force_repick = self._auto_pilot_should_force_repick(bot, current_symbol)
        pending_rotation = bool(bot.get("auto_pilot_rotation_pending"))

        # Score-floor auto-drop: if current score is below threshold, force immediate rotation
        from config.strategy_config import AUTO_PILOT_SCORE_FLOOR_DROP_THRESHOLD
        score_floor = float(AUTO_PILOT_SCORE_FLOOR_DROP_THRESHOLD or 0)
        current_ap_score = float(bot.get("auto_pilot_current_score") or 0)
        if score_floor > 0 and current_ap_score > 0 and current_ap_score < score_floor:
            if not force_repick:
                logger.warning(
                    "[Auto-Pilot:%s] SCORE FLOOR DROP: %s score %.1f < floor %.1f — forcing immediate rotation check",
                    bot_id, current_symbol, current_ap_score, score_floor,
                )
                bot["auto_pilot_score_floor_triggered"] = True
                force_repick = True

        if pending_rotation and not self._auto_pilot_pending_rotation_ready(
            bot, current_symbol
        ):
            bot["_block_opening_orders"] = True
            return None

        # Anti-churn: enforce minimum hold time before considering rotation
        from config.strategy_config import (
            AUTO_PILOT_MIN_HOLD_SECONDS,
            AUTO_PILOT_MAX_ROTATIONS_PER_HOUR,
            AUTO_PILOT_CHURN_PENALTY_PER_ROTATION,
        )
        if not force_repick and not pending_rotation:
            last_rotation_raw = str(bot.get("auto_pilot_last_rotation_at") or "").strip()
            if last_rotation_raw:
                try:
                    last_rot_dt = datetime.fromisoformat(last_rotation_raw.replace("Z", "+00:00"))
                    hold_elapsed = (now - last_rot_dt).total_seconds()
                    if hold_elapsed < AUTO_PILOT_MIN_HOLD_SECONDS:
                        return None  # Hold time not met
                except (ValueError, TypeError):
                    pass

        if last_scan and not force_repick and not pending_rotation:
            try:
                last_scan_dt = datetime.fromisoformat(str(last_scan).replace("Z", "+00:00"))
                elapsed = (now - last_scan_dt).total_seconds()
                if elapsed < effective_rotation_interval:
                    return None  # Not time yet
            except (ValueError, TypeError):
                pass  # Invalid timestamp, proceed with scan
        
        # Time to re-scan
        if force_repick:
            logger.info(
                f"[Auto-Pilot:{bot_id}] Force re-pick — current symbol {current_symbol} is flat and opening-blocked"
            )
        elif pending_rotation:
            logger.info(
                f"[Auto-Pilot:{bot_id}] Pending rotation — {current_symbol} is flat after loss hold, re-scanning now"
            )
        else:
            logger.info(f"[Auto-Pilot:{bot_id}] Rotation check — re-scanning for better opportunities...")
        bot["auto_pilot_last_scan_at"] = now.isoformat()
        
        try:
            ranked_results = self._get_ranked_auto_pilot_candidates(
                bot,
                reason="rotation",
            )
            if not ranked_results:
                logger.info(
                    f"[Auto-Pilot:{bot_id}] Rotation scan found no ranked candidates, staying on {current_symbol}"
                )
                self.bot_storage.save_bot(bot)
                return None

            budget_state = self._refresh_auto_pilot_loss_budget_state(
                bot,
                current_symbol,
            )
            best = ranked_results[0]
            best_symbol = best.get("symbol", "")
            best_score = best.get("_auto_pilot_score", best.get("neutral_score", 0))
            urgent_rotation = force_repick or pending_rotation
            score_threshold = (
                0 if urgent_rotation else rotation_settings["score_threshold"]
            )
            
            # Get current coin's score from scan (if it was scanned)
            current_candidate = None
            current_score = 0
            for r in ranked_results:
                if r.get("symbol") == current_symbol:
                    current_candidate = r
                    current_score = r.get(
                        "_auto_pilot_score",
                        r.get("neutral_score", 0),
                    )
                    break

            if urgent_rotation and best_symbol == current_symbol:
                alternative = next(
                    (
                        candidate
                        for candidate in ranked_results
                        if str(candidate.get("symbol") or "").strip().upper()
                        != current_symbol
                    ),
                    None,
                )
                if alternative is None:
                    logger.info(
                        f"[Auto-Pilot:{bot_id}] Urgent re-pick found no alternative candidate beyond {current_symbol}"
                    )
                    self.bot_storage.save_bot(bot)
                    return None
                best = alternative
                best_symbol = best.get("symbol", "")
                best_score = best.get(
                    "_auto_pilot_score",
                    best.get("neutral_score", 0),
                )
                logger.info(
                    f"[Auto-Pilot:{bot_id}] Urgent re-pick disqualified current symbol {current_symbol}; "
                    f"next best={best_symbol} (score={best_score:.1f})"
                )
            
            # Store current score for monitoring
            bot["auto_pilot_current_score"] = current_score
            bot["auto_pilot_best_available"] = f"{best_symbol}:{best_score:.1f}"
            if current_candidate:
                bot["auto_pilot_current_velocity"] = current_candidate.get(
                    "price_velocity"
                )
                bot["auto_pilot_current_atr_pct"] = current_candidate.get("atr_pct")
            
            # Check if best coin is significantly better
            score_diff = best_score - current_score
            interval_plan = self._compute_auto_pilot_rotation_interval(
                bot=bot,
                current_candidate=current_candidate,
                best_candidate=best,
                score_gap=score_diff,
                urgent_rotation=urgent_rotation,
            )
            bot["auto_pilot_effective_rotation_interval_sec"] = interval_plan[
                "effective_seconds"
            ]
            bot["auto_pilot_effective_rotation_reason"] = ", ".join(
                interval_plan["reasons"]
            )
            if not urgent_rotation:
                if interval_plan["effective_seconds"] != interval_plan["base_seconds"]:
                    logger.info(
                        "[Auto-Pilot:%s] Adaptive rotation interval %ss -> %ss (%s)",
                        bot_id,
                        interval_plan["base_seconds"],
                        interval_plan["effective_seconds"],
                        ", ".join(interval_plan["reasons"]),
                    )
                else:
                    logger.info(
                        "[Auto-Pilot:%s] Adaptive rotation interval kept at base %ss (%s)",
                        bot_id,
                        interval_plan["base_seconds"],
                        ", ".join(interval_plan["reasons"]),
                    )
            if budget_state.get("status") == "blocked":
                logger.info(
                    "[Auto-Pilot:%s] Rotation blocked by remaining loss budget %.2f%% ($%.2f / $%.2f)",
                    bot_id,
                    self._safe_float(budget_state.get("remaining_pct"), 0.0) * 100.0,
                    self._safe_float(budget_state.get("remaining_usdt"), 0.0),
                    self._safe_float(budget_state.get("loss_budget_usdt"), 0.0),
                )
                self.bot_storage.save_bot(bot)
                return None

            low_budget_check = self._check_auto_pilot_low_budget_candidate(
                bot,
                budget_state,
                best_score=self._safe_float(best_score, 0.0),
                current_score=self._safe_float(current_score, 0.0),
                base_score_threshold=self._safe_float(score_threshold, 0.0),
            )
            if not low_budget_check.get("allowed"):
                logger.info(
                    "[Auto-Pilot:%s] Staying on %s under low remaining loss budget: %s",
                    bot_id,
                    current_symbol,
                    low_budget_check.get("reason") or "candidate not strong enough",
                )
                self.bot_storage.save_bot(bot)
                return None

            # Anti-churn: raise threshold based on recent rotation frequency
            effective_threshold = score_threshold
            total_rotations = int(bot.get("auto_pilot_rotations") or 0)
            last_rotation_raw = str(bot.get("auto_pilot_last_rotation_at") or "").strip()
            if total_rotations > 0 and last_rotation_raw:
                try:
                    last_rot_ts = datetime.fromisoformat(
                        last_rotation_raw.replace("Z", "+00:00")
                    ).timestamp()
                    hour_ago = time.time() - 3600
                    # Approximate recent rotations: if average interval < 15min, churn is high
                    if last_rot_ts > hour_ago and total_rotations >= AUTO_PILOT_MAX_ROTATIONS_PER_HOUR:
                        churn_extra = AUTO_PILOT_CHURN_PENALTY_PER_ROTATION * min(total_rotations, 8)
                        effective_threshold += churn_extra
                        logger.info(
                            "[Auto-Pilot:%s] Churn guard: threshold raised %.1f→%.1f (rotations=%d)",
                            bot_id, score_threshold, effective_threshold, total_rotations,
                        )
                except (ValueError, TypeError):
                    pass

            if best_symbol == current_symbol or (
                not urgent_rotation and score_diff < effective_threshold
            ):
                logger.info(
                    f"[Auto-Pilot:{bot_id}] Staying on {current_symbol} (score={current_score:.1f}) — "
                    f"best={best_symbol} (score={best_score:.1f}, diff={score_diff:.1f} < {effective_threshold})"
                )
                self.bot_storage.save_bot(bot)
                return None  # No switch needed
            
            # Better coin found! Check if safe to switch (no losing position)
            try:
                positions = self.client.get_positions(skip_cache=True)
                pos_list = positions.get("data", {}).get("list", []) if positions.get("success") else []
                has_position = False
                unrealized_pnl = 0.0
                position_value = 0.0
                for p in pos_list:
                    if p.get("symbol") != current_symbol:
                        continue
                    size = float(p.get("size", 0) or 0)
                    if size > 0:
                        has_position = True
                        unrealized_pnl = float(p.get("unrealisedPnl", 0) or 0)
                        position_value = float(p.get("positionValue", 0) or 0)
                        break

                # Don't switch if we have a losing position (let it recover)
                if has_position and unrealized_pnl < -0.5:
                    cancelled_opening_orders = 0
                    try:
                        cancelled_opening_orders = self._cancel_opening_orders_only(
                            bot, current_symbol
                        )
                    except Exception as cancel_exc:
                        logger.warning(
                            f"[Auto-Pilot:{bot_id}] Pending-rotation cancel warning on {current_symbol}: {cancel_exc}"
                        )
                    bot["_block_opening_orders"] = True
                    bot["auto_pilot_rotation_pending"] = True
                    bot["auto_pilot_rotation_pending_since"] = now.isoformat()
                    bot["auto_pilot_rotation_pending_target"] = (
                        f"{best_symbol}:{best_score:.1f}"
                    )
                    logger.info(
                        f"[Auto-Pilot:{bot_id}] Better coin found ({best_symbol}={best_score:.1f}) "
                        f"but freezing new entries on {current_symbol} until flat "
                        f"(uPnL=${unrealized_pnl:.2f}, cancelled_opening={cancelled_opening_orders})"
                    )
                    self.bot_storage.save_bot(bot)
                    return None

                # Don't close profitable positions to rotate — let TP/Profit Lock capture gains first.
                # Only enter pending rotation (block new entries) if profit exceeds round-trip fee cost.
                if has_position and unrealized_pnl > 0 and position_value > 0:
                    round_trip_fee_cost = position_value * (2 * strategy_cfg.FAST_EXEC_TAKER_FEE_RATE + strategy_cfg.FAST_EXEC_SLIPPAGE_BUFFER_PCT)
                    if unrealized_pnl > round_trip_fee_cost:
                        bot["_block_opening_orders"] = True
                        bot["auto_pilot_rotation_pending"] = True
                        bot["auto_pilot_rotation_pending_since"] = now.isoformat()
                        bot["auto_pilot_rotation_pending_target"] = (
                            f"{best_symbol}:{best_score:.1f}"
                        )
                        logger.info(
                            f"[Auto-Pilot:{bot_id}] Better coin found ({best_symbol}={best_score:.1f}) "
                            f"but profitable position on {current_symbol} — freezing new entries until TP captured "
                            f"(uPnL=${unrealized_pnl:.2f} > fee_cost=${round_trip_fee_cost:.2f})"
                        )
                        self.bot_storage.save_bot(bot)
                        return None

            except Exception as e:
                logger.warning(f"[Auto-Pilot:{bot_id}] Position check failed: {e}, skipping rotation")
                self.bot_storage.save_bot(bot)
                return None
            
            # force_repick with profitable position: defer to pending_rotation
            # instead of immediately closing. Let TP/exits capture gains.
            if force_repick and has_position and unrealized_pnl > 0:
                bot["_block_opening_orders"] = True
                bot["auto_pilot_rotation_pending"] = True
                bot["auto_pilot_rotation_pending_since"] = now.isoformat()
                bot["auto_pilot_rotation_pending_target"] = (
                    f"{best_symbol}:{best_score:.1f}"
                )
                logger.info(
                    "[Auto-Pilot:%s] Force-repick deferred: profitable position on %s "
                    "(uPnL=$%.2f) — pending_rotation instead of immediate close",
                    bot_id, current_symbol, unrealized_pnl,
                )
                self.bot_storage.save_bot(bot)
                return None

            # === SWITCH TO BETTER COIN ===
            if force_repick:
                logger.warning(
                    f"[Auto-Pilot:{bot_id}] 🔄 ROTATING (force re-pick): {current_symbol} "
                    f"(score={current_score:.1f}, blocked) → {best_symbol} "
                    f"(score={best_score:.1f}, diff={score_diff:+.1f})"
                )
            elif pending_rotation:
                logger.warning(
                    f"[Auto-Pilot:{bot_id}] 🔄 ROTATING (pending flat): {current_symbol} "
                    f"(score={current_score:.1f}) → {best_symbol} "
                    f"(score={best_score:.1f}, diff={score_diff:+.1f})"
                )
            else:
                logger.warning(
                    f"[Auto-Pilot:{bot_id}] 🔄 ROTATING: {current_symbol} (score={current_score:.1f}) "
                    f"→ {best_symbol} (score={best_score:.1f}, diff={score_diff:+.1f})"
                )
            
            # 1. Close position on current coin (if any)
            if has_position:
                try:
                    close_success = self._close_position_market(current_symbol, bot=bot)
                    if close_success:
                        logger.info(f"[Auto-Pilot:{bot_id}] ✓ Closed position on {current_symbol}")
                        try:
                            self.pnl_service.sync_closed_pnl(current_symbol)
                        except Exception:
                            pass
                        self._notify_auto_pilot_memory(bot, current_symbol, unrealized_pnl)
                    else:
                        logger.error(
                            f"[Auto-Pilot:{bot_id}] ❌ Rotation ABORTED: failed to close position on {current_symbol}"
                        )
                        self.bot_storage.save_bot(bot)
                        return None  # Stay on current coin - don't orphan positions
                except Exception as e:
                    logger.error(f"[Auto-Pilot:{bot_id}] Position close error: {e} - aborting rotation")
                    self.bot_storage.save_bot(bot)
                    return None  # Stay on current coin
            
            # 2. Cancel all orders on current coin
            try:
                self._force_cancel_all_orders(current_symbol, max_retries=2, bot=bot)
                logger.info(f"[Auto-Pilot:{bot_id}] ✓ Orders cancelled on {current_symbol}")
            except Exception as e:
                logger.warning(f"[Auto-Pilot:{bot_id}] Order cancel warning: {e}")

            # 3. Apply new coin settings
            best_symbol = self._apply_auto_pilot_selection(bot, best)
            
            # Track rotation history
            bot["auto_pilot_rotations"] = bot.get("auto_pilot_rotations", 0) + 1
            bot["auto_pilot_last_rotation_at"] = now.isoformat()
            bot["auto_pilot_rotation_from"] = current_symbol
            
            # 4. Set up exchange for new symbol
            try:
                leverage_to_set = int(bot.get("leverage", 3))
                self.client.set_margin_mode(best_symbol, "ISOLATED_MARGIN")
                self.client.set_leverage(best_symbol, leverage_to_set)
                logger.info(f"[Auto-Pilot:{bot_id}] ✓ Exchange setup: {best_symbol} leverage={leverage_to_set}x")
            except Exception as ex_err:
                logger.warning(f"[Auto-Pilot:{bot_id}] Exchange setup warning: {ex_err}")
            
            self.bot_storage.save_bot(bot)
            logger.warning(
                f"[Auto-Pilot:{bot_id}] ✅ Rotation complete → {best_symbol} | "
                f"mode={bot['mode']} | range={bot.get('lower_price')}-{bot.get('upper_price')} | "
                f"total rotations: {bot.get('auto_pilot_rotations', 0)}"
            )
            return bot  # Return to skip rest of cycle, new coin used next cycle

        except Exception as e:
            logger.error(f"[Auto-Pilot:{bot_id}] Rotation check failed: {e}")
            self.bot_storage.save_bot(bot)
            return None  # Continue with current coin

