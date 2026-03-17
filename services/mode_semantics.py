from __future__ import annotations

from typing import Any, Dict


SUPPORTED_BOT_MODES = {
    "neutral",
    "neutral_classic_bybit",
    "long",
    "short",
    "scalp_pnl",
    "scalp_market",
}

SUPPORTED_RANGE_MODES = {"fixed", "dynamic", "trailing"}

MODE_POLICY_LOCKED = "locked"
MODE_POLICY_SUGGEST_ONLY = "suggest_only"
MODE_POLICY_RUNTIME_AUTO_SWITCH = "runtime_auto_switch_non_persistent"
SUPPORTED_MODE_POLICIES = {
    MODE_POLICY_LOCKED,
    MODE_POLICY_SUGGEST_ONLY,
    MODE_POLICY_RUNTIME_AUTO_SWITCH,
}


def normalize_bot_mode(value: Any, default: str = "neutral") -> str:
    normalized = str(value or default).strip().lower() or default
    return normalized if normalized in SUPPORTED_BOT_MODES else default


def normalize_range_mode(value: Any, default: str = "fixed") -> str:
    normalized = str(value or default).strip().lower() or default
    return normalized if normalized in SUPPORTED_RANGE_MODES else default


def derive_default_mode_policy(bot: Dict[str, Any] | None) -> str:
    safe_bot = dict(bot or {})
    if bool(safe_bot.get("auto_pilot")):
        return MODE_POLICY_RUNTIME_AUTO_SWITCH
    if bool(safe_bot.get("auto_direction")):
        return MODE_POLICY_RUNTIME_AUTO_SWITCH
    if bool(safe_bot.get("auto_neutral_mode_enabled")):
        return MODE_POLICY_RUNTIME_AUTO_SWITCH
    return MODE_POLICY_LOCKED


def normalize_mode_policy(value: Any, bot: Dict[str, Any] | None = None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_MODE_POLICIES:
        return normalized
    return derive_default_mode_policy(bot)


def configured_mode(bot: Dict[str, Any] | None) -> str:
    safe_bot = dict(bot or {})
    return normalize_bot_mode(safe_bot.get("configured_mode") or safe_bot.get("mode"))


def configured_range_mode(bot: Dict[str, Any] | None) -> str:
    safe_bot = dict(bot or {})
    return normalize_range_mode(
        safe_bot.get("configured_range_mode") or safe_bot.get("range_mode")
    )


def runtime_auto_switch_allowed(bot: Dict[str, Any] | None) -> bool:
    return normalize_mode_policy((bot or {}).get("mode_policy"), bot) == MODE_POLICY_RUNTIME_AUTO_SWITCH


def runtime_mode_is_non_persistent(bot: Dict[str, Any] | None) -> bool:
    safe_bot = dict(bot or {})
    if not safe_bot:
        return False
    if not safe_bot.get("runtime_mode_non_persistent"):
        return False
    return runtime_auto_switch_allowed(safe_bot)
