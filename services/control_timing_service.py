from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def now_ts() -> float:
    return time.time()


def iso_from_ts(ts: Optional[float] = None) -> str:
    value = now_ts() if ts is None else float(ts)
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def elapsed_ms(start_ts: Optional[float], end_ts: Optional[float] = None) -> Optional[float]:
    if start_ts in (None, ""):
        return None
    try:
        start = float(start_ts)
    except (TypeError, ValueError):
        return None
    finish = now_ts() if end_ts is None else float(end_ts)
    return round(max(finish - start, 0.0) * 1000.0, 2)


def ensure_bot_timing_scope(bot: Optional[Dict[str, Any]], scope: str) -> Dict[str, Any]:
    if not isinstance(bot, dict):
        return {}
    timing = bot.get("control_timing")
    if not isinstance(timing, dict):
        timing = {}
        bot["control_timing"] = timing
    scoped = timing.get(scope)
    if not isinstance(scoped, dict):
        scoped = {}
        timing[scope] = scoped
    return scoped


def update_bot_timing(bot: Optional[Dict[str, Any]], scope: str, **fields: Any) -> Dict[str, Any]:
    scoped = ensure_bot_timing_scope(bot, scope)
    for key, value in fields.items():
        scoped[key] = value
    return scoped


def merge_result_timing(result: Optional[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    timing = result.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        result["timing"] = timing
    for key, value in fields.items():
        timing[key] = value
    return result
