"""
Directional breakout runtime guard helpers.

These helpers keep the breakout-entry context and breakout-invalidation
mini-state-machine out of GridBotService while preserving the existing
GridBotService orchestration API.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from config.strategy_config import (
    BREAKOUT_INVALIDATION_CLOSE_ON_PERSIST_ENABLED,
    BREAKOUT_INVALIDATION_CONFIRM_CANDLES,
    BREAKOUT_INVALIDATION_EXIT_ENABLED,
    BREAKOUT_INVALIDATION_LOGGING_ENABLED,
    BREAKOUT_INVALIDATION_PARTIAL_TRIM_CLOSE_PCT,
    BREAKOUT_INVALIDATION_PARTIAL_TRIM_ENABLED,
    BREAKOUT_INVALIDATION_PERSIST_SECONDS,
    BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT,
)

logger = logging.getLogger(__name__)


def mark_breakout_entry_context(
    service: Any,
    bot: Dict[str, Any],
    mode: str,
    breakout_confirmation: Optional[Dict[str, Any]],
) -> None:
    if not bot or mode not in {"long", "short"}:
        return
    confirmation = dict(breakout_confirmation or {})
    if not confirmation.get("confirmed"):
        return
    reference_level = service._safe_float(confirmation.get("level_price"), 0.0)
    if reference_level <= 0:
        return
    bot["_breakout_entry_pending_context"] = {
        "mode": mode,
        "level_price": round(reference_level, 8),
        "level_type": confirmation.get("level_type"),
        "required_close": confirmation.get("required_close"),
        "queued_at_ts": service._get_cycle_now_ts(),
    }


def clear_breakout_invalidation_runtime_state(
    bot: Dict[str, Any],
    *,
    clear_entry_context: bool = False,
) -> None:
    if not bot:
        return
    bot["_breakout_invalidation_block_opening_orders"] = False
    bot.pop("_breakout_invalidation_state", None)
    bot["breakout_invalidation_state"] = "inactive"
    bot["breakout_invalidation_reason"] = None
    if clear_entry_context:
        bot["breakout_entry_confirmed"] = False
        bot["breakout_entry_mode"] = None
        bot["breakout_entry_confirmed_at"] = None
        bot["breakout_reference_level"] = None
        bot["breakout_reference_type"] = None
        bot["breakout_required_close"] = None


def activate_breakout_entry_context_from_position(
    service: Any,
    bot: Dict[str, Any],
    symbol: str,
    mode: str,
    position: Dict[str, Any],
) -> None:
    if not bot or mode not in {"long", "short"}:
        clear_breakout_invalidation_runtime_state(bot, clear_entry_context=True)
        return
    if not bool(bot.get("breakout_confirmed_entry", False)):
        clear_breakout_invalidation_runtime_state(bot, clear_entry_context=True)
        return

    pos_side = str(position.get("side") or "").strip()
    pos_size = max(service._safe_float(position.get("size"), 0.0), 0.0)
    expected_side = "Buy" if mode == "long" else "Sell"
    if pos_size <= 0 or pos_side != expected_side:
        clear_breakout_invalidation_runtime_state(bot, clear_entry_context=True)
        return

    pending = bot.get("_breakout_entry_pending_context") or {}
    if str(bot.get("breakout_entry_mode") or "").strip().lower() == mode and bool(
        bot.get("breakout_entry_confirmed", False)
    ):
        return

    pending_mode = str(pending.get("mode") or "").strip().lower()
    reference_level = service._safe_float(pending.get("level_price"), 0.0)
    if pending_mode != mode or reference_level <= 0:
        return

    bot["breakout_entry_confirmed"] = True
    bot["breakout_entry_mode"] = mode
    bot["breakout_entry_confirmed_at"] = datetime.now(timezone.utc).isoformat()
    bot["breakout_reference_level"] = round(reference_level, 8)
    bot["breakout_reference_type"] = pending.get("level_type")
    bot["breakout_required_close"] = pending.get("required_close")
    bot["_breakout_invalidation_block_opening_orders"] = False
    bot["breakout_invalidation_state"] = "inactive"
    bot["breakout_invalidation_reason"] = None
    bot.pop("_breakout_invalidation_state", None)
    bot.pop("_breakout_entry_pending_context", None)


def get_breakout_invalidation_settings(
    service: Any,
    bot: Optional[Dict[str, Any]] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    safe_bot = bot or {}
    safe_defaults = defaults or {}
    return {
        "enabled": bool(
            safe_bot.get(
                "breakout_invalidation_exit_enabled",
                safe_defaults.get(
                    "enabled",
                    BREAKOUT_INVALIDATION_EXIT_ENABLED,
                ),
            )
        ),
        "confirm_candles": max(
            1,
            int(
                service._safe_float(
                    safe_bot.get("breakout_invalidation_confirm_candles"),
                    safe_defaults.get(
                        "confirm_candles",
                        BREAKOUT_INVALIDATION_CONFIRM_CANDLES,
                    ),
                )
            ),
        ),
        "reclaim_buffer_pct": max(
            0.0,
            service._safe_float(
                safe_bot.get("breakout_invalidation_reclaim_buffer_pct"),
                safe_defaults.get(
                    "reclaim_buffer_pct",
                    BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT,
                ),
            ),
        ),
        "partial_trim_enabled": bool(
            safe_bot.get(
                "breakout_invalidation_partial_trim_enabled",
                safe_defaults.get(
                    "partial_trim_enabled",
                    BREAKOUT_INVALIDATION_PARTIAL_TRIM_ENABLED,
                ),
            )
        ),
        "partial_trim_close_pct": max(
            0.0,
            min(
                0.5,
                service._safe_float(
                    safe_bot.get("breakout_invalidation_partial_trim_close_pct"),
                    safe_defaults.get(
                        "partial_trim_close_pct",
                        BREAKOUT_INVALIDATION_PARTIAL_TRIM_CLOSE_PCT,
                    ),
                ),
            ),
        ),
        "close_on_persist_enabled": bool(
            safe_bot.get(
                "breakout_invalidation_close_on_persist_enabled",
                safe_defaults.get(
                    "close_on_persist_enabled",
                    BREAKOUT_INVALIDATION_CLOSE_ON_PERSIST_ENABLED,
                ),
            )
        ),
        "persist_seconds": max(
            30.0,
            service._safe_float(
                safe_bot.get("breakout_invalidation_persist_seconds"),
                safe_defaults.get(
                    "persist_seconds",
                    BREAKOUT_INVALIDATION_PERSIST_SECONDS,
                ),
            ),
        ),
        "logging_enabled": bool(
            safe_bot.get(
                "breakout_invalidation_logging_enabled",
                safe_defaults.get(
                    "logging_enabled",
                    BREAKOUT_INVALIDATION_LOGGING_ENABLED,
                ),
            )
        ),
    }


def evaluate_breakout_invalidation(
    service: Any,
    bot: Dict[str, Any],
    symbol: str,
    mode: str,
    position: Dict[str, Any],
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = get_breakout_invalidation_settings(service, bot, defaults=defaults)
    result = {
        "enabled": settings["enabled"],
        "eligible": False,
        "confirmed": False,
        "reason": "breakout invalidation disabled",
        "reference_level": None,
        "reference_type": None,
        "threshold_price": None,
        "confirm_candles": settings["confirm_candles"],
        "recent_closes": [],
    }

    normalized_mode = str(mode or "").strip().lower()
    if not settings["enabled"] or normalized_mode not in {"long", "short"}:
        return result
    if not bool(bot.get("breakout_confirmed_entry", False)):
        result["reason"] = "breakout confirmed entry not enabled for bot"
        return result
    if not bool(bot.get("breakout_entry_confirmed", False)):
        result["reason"] = "breakout entry context not active"
        return result
    if str(bot.get("breakout_entry_mode") or "").strip().lower() != normalized_mode:
        result["reason"] = "breakout entry mode does not match active mode"
        return result

    pos_side = str(position.get("side") or "").strip()
    if (
        (normalized_mode == "long" and pos_side != "Buy")
        or (normalized_mode == "short" and pos_side != "Sell")
    ):
        result["reason"] = "position side does not match breakout mode"
        return result

    reference_level = service._safe_float(bot.get("breakout_reference_level"), 0.0)
    if reference_level <= 0:
        result["reason"] = "missing breakout reference level"
        return result

    try:
        entry_gate = service._build_entry_gate_service()
        invalidation = entry_gate.check_breakout_invalidation(
            symbol=symbol,
            mode=normalized_mode,
            reference_level=reference_level,
            reference_type=bot.get("breakout_reference_type"),
        )
    except Exception as exc:
        result["reason"] = f"breakout invalidation unavailable: {exc}"
        return result

    if not invalidation.get("eligible"):
        result["reason"] = invalidation.get("reason", result["reason"])
        return result

    reference_type = str(bot.get("breakout_reference_type") or "").strip() or None
    result.update(
        {
            "eligible": True,
            "confirmed": bool(invalidation.get("invalidated")),
            "reason": invalidation.get("reason"),
            "reference_level": round(reference_level, 8),
            "reference_type": reference_type,
            "threshold_price": invalidation.get("required_close"),
            "confirm_candles": invalidation.get(
                "confirm_candles", settings["confirm_candles"]
            ),
            "recent_closes": [invalidation.get("latest_close")]
            if invalidation.get("latest_close") is not None
            else [],
        }
    )
    return result


def handle_breakout_invalidation_guard(
    service: Any,
    bot: Dict[str, Any],
    symbol: str,
    position: Dict[str, Any],
    *,
    mode: str,
    last_price: float,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = get_breakout_invalidation_settings(service, bot, defaults=defaults)
    evaluation = evaluate_breakout_invalidation(
        service,
        bot=bot,
        symbol=symbol,
        mode=mode,
        position=position,
        defaults=defaults,
    )
    pos_side = str(position.get("side") or "").strip()
    pos_size = max(service._safe_float(position.get("size"), 0.0), 0.0)
    position_idx = int(service._safe_float(position.get("positionIdx"), 0.0))
    position_key = f"{symbol}:{pos_side}:{position_idx}:{mode}"
    existing_state = bot.get("_breakout_invalidation_state") or {}
    if not evaluation.get("eligible") or not evaluation.get("confirmed"):
        if existing_state.get("position_key") == position_key and pos_size > 0:
            bot["_breakout_invalidation_block_opening_orders"] = True
            bot["breakout_invalidation_state"] = "recovered_blocked"
            bot["breakout_invalidation_reason"] = existing_state.get(
                "reason"
            ) or evaluation.get("reason")
            return {
                **evaluation,
                "active": True,
                "action": "recovered_blocked",
                "position_closed": False,
            }
        clear_breakout_invalidation_runtime_state(bot)
        return {
            **evaluation,
            "active": False,
            "action": "inactive",
            "position_closed": False,
        }

    now_ts = service._get_cycle_now_ts()

    state = (
        existing_state if existing_state.get("position_key") == position_key else {}
    )
    first_detection = not state
    active_since_ts = service._safe_float(state.get("active_since_ts"), 0.0) or now_ts
    persisted_seconds = max(0.0, now_ts - active_since_ts)

    bot["_breakout_invalidation_block_opening_orders"] = True
    bot["breakout_invalidation_state"] = "risk"
    bot["breakout_invalidation_reason"] = evaluation["reason"]
    bot["last_warning"] = f"BREAKOUT_INVALIDATION: {evaluation['reason']}"

    if first_detection:
        cancelled = service._cancel_opening_orders_only(bot, symbol)
        state["cancelled_opening_orders"] = cancelled
        if settings["logging_enabled"]:
            logger.warning(
                "[%s] Breakout invalidation detected: %s, blocking new openings",
                symbol,
                evaluation["reason"],
            )

    state.update(
        {
            "position_key": position_key,
            "active_since_ts": active_since_ts,
            "last_seen_ts": now_ts,
            "reason": evaluation["reason"],
            "reference_level": evaluation["reference_level"],
            "threshold_price": evaluation["threshold_price"],
            "persisted_seconds": persisted_seconds,
        }
    )

    if (
        settings["close_on_persist_enabled"]
        and persisted_seconds >= settings["persist_seconds"]
    ):
        conflict = service._get_shared_symbol_conflict(
            bot,
            symbol,
            "breakout invalidation persist close",
        )
        if conflict:
            if settings["logging_enabled"]:
                logger.warning(
                    "[%s] Breakout invalidation persisted but close skipped due to active sibling bot ownership",
                    symbol,
                )
        else:
            bot["breakout_invalidation_state"] = "closing"
            state["persist_close_attempted_ts"] = now_ts
            close_result = service._close_position_or_hard_fail(
                bot,
                symbol,
                "breakout_invalidation",
            )
            bot["_breakout_invalidation_state"] = state
            if close_result.get("success"):
                if settings["logging_enabled"]:
                    logger.warning(
                        "[%s] Breakout invalidation persisted, closing directional breakout trade",
                        symbol,
                    )
                return {
                    **evaluation,
                    "active": True,
                    "action": "closed",
                    "position_closed": True,
                }

    if settings["partial_trim_enabled"] and pos_size > 0 and not state.get(
        "partial_trim_done"
    ):
        conflict = service._get_shared_symbol_conflict(
            bot,
            symbol,
            "breakout invalidation partial trim",
        )
        if conflict:
            if settings["logging_enabled"]:
                logger.warning(
                    "[%s] Breakout invalidation trim skipped due to active sibling bot ownership",
                    symbol,
                )
        else:
            close_pct = settings["partial_trim_close_pct"]
            close_qty = pos_size * close_pct
            close_side = "Sell" if pos_side == "Buy" else "Buy"
            trim_result = service._create_order_checked(
                bot=bot,
                symbol=symbol,
                side=close_side,
                qty=close_qty,
                order_type="Market",
                price=last_price,
                reduce_only=True,
                time_in_force="GTC",
                order_link_id=service._build_close_order_link_id(
                    bot.get("id"),
                    "BINV",
                ),
                position_idx=position_idx,
                full_close_qty=pos_size,
            )
            if service._is_position_empty_close_result(trim_result):
                state["partial_trim_done"] = True
                state["partial_trim_ts"] = now_ts
                bot["breakout_invalidation_state"] = "trimmed"
                if settings["logging_enabled"]:
                    logger.info(
                        "[%s] Breakout invalidation trim skipped: position already flat",
                        symbol,
                    )
                bot["_breakout_invalidation_state"] = state
                return {
                    **evaluation,
                    "active": True,
                    "action": "position_empty",
                    "position_closed": True,
                }
            if trim_result.get("success") or trim_result.get("retCode") == 0:
                state["partial_trim_done"] = True
                state["partial_trim_ts"] = now_ts
                bot["breakout_invalidation_state"] = "trimmed"
                if settings["logging_enabled"]:
                    logger.warning(
                        "[%s] Breakout invalidation detected: %s, trimming %.0f%%",
                        symbol,
                        evaluation["reason"],
                        close_pct * 100.0,
                    )
                bot["_breakout_invalidation_state"] = state
                return {
                    **evaluation,
                    "active": True,
                    "action": "trimmed",
                    "position_closed": False,
                }
            if trim_result.get("skipped"):
                state["partial_trim_done"] = True
                state["partial_trim_ts"] = now_ts
                if settings["logging_enabled"]:
                    logger.info(
                        "[%s] Breakout invalidation trim skipped: %s",
                        symbol,
                        trim_result.get("skip_reason") or trim_result.get("error"),
                    )
            elif settings["logging_enabled"]:
                logger.warning(
                    "[%s] Breakout invalidation trim failed: %s",
                    symbol,
                    trim_result.get("error", trim_result),
                )

    bot["_breakout_invalidation_state"] = state
    return {
        **evaluation,
        "active": True,
        "action": "blocked",
        "position_closed": False,
    }
