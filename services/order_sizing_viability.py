from __future__ import annotations

from typing import Any, Dict, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_order_sizing_viability(
    *,
    symbol: Any = None,
    reference_price: Any = None,
    price_source: Any = None,
    leverage: Any = None,
    investment: Any = None,
    order_splits: Any = None,
    min_notional: Any = None,
    min_qty: Any = None,
) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper() or None
    normalized_price_source = str(price_source or "").strip().lower() or None
    normalized_reference_price = _safe_float(reference_price, 0.0)
    normalized_leverage = max(_safe_float(leverage, 0.0), 0.0)
    normalized_investment = max(_safe_float(investment, 0.0), 0.0)
    normalized_order_splits = max(_safe_int(order_splits, 0), 1)
    normalized_min_notional = max(_safe_float(min_notional, 0.0), 0.0)
    normalized_min_qty = max(_safe_float(min_qty, 0.0), 0.0)

    estimated_per_order_notional = 0.0
    if normalized_order_splits > 0:
        estimated_per_order_notional = (
            normalized_investment * max(normalized_leverage, 1.0)
        ) / normalized_order_splits

    estimated_per_order_qty = None
    if normalized_reference_price > 0:
        estimated_per_order_qty = estimated_per_order_notional / normalized_reference_price

    effective_min_order_notional = normalized_min_notional
    min_qty_notional = None
    if normalized_reference_price > 0 and normalized_min_qty > 0:
        min_qty_notional = normalized_reference_price * normalized_min_qty
        effective_min_order_notional = max(
            effective_min_order_notional,
            min_qty_notional,
        )

    min_notional_passes = (
        estimated_per_order_notional + 1e-9 >= normalized_min_notional
        if normalized_min_notional > 0
        else True
    )
    min_qty_passes = (
        (estimated_per_order_qty is not None and estimated_per_order_qty + 1e-12 >= normalized_min_qty)
        if normalized_min_qty > 0
        else True
    )

    blocked_reasons: List[str] = []
    warnings: List[str] = []

    if normalized_reference_price <= 0:
        warnings.append("reference_price_unavailable")
    if normalized_min_notional <= 0:
        warnings.append("min_notional_unavailable")
    if normalized_min_qty <= 0:
        warnings.append("min_qty_unavailable")

    if normalized_min_notional > 0 and not min_notional_passes:
        blocked_reasons.append("below_min_notional")
    if normalized_min_qty > 0 and not min_qty_passes:
        blocked_reasons.append("below_min_qty")

    if blocked_reasons:
        blocked_reason = (
            "below_min_notional_and_min_qty"
            if len(blocked_reasons) > 1
            else blocked_reasons[0]
        )
    else:
        blocked_reason = None

    return {
        "symbol": normalized_symbol,
        "reference_price": round(normalized_reference_price, 8)
        if normalized_reference_price > 0
        else None,
        "price_source": normalized_price_source,
        "investment": round(normalized_investment, 8),
        "leverage": round(normalized_leverage, 8),
        "order_splits": int(normalized_order_splits),
        "estimated_per_order_notional": round(estimated_per_order_notional, 8),
        "estimated_per_order_qty": round(estimated_per_order_qty, 12)
        if estimated_per_order_qty is not None
        else None,
        "min_notional": round(normalized_min_notional, 8)
        if normalized_min_notional > 0
        else None,
        "min_qty": round(normalized_min_qty, 12) if normalized_min_qty > 0 else None,
        "min_qty_notional": round(min_qty_notional, 8)
        if min_qty_notional is not None
        else None,
        "effective_min_order_notional": round(effective_min_order_notional, 8)
        if effective_min_order_notional > 0
        else None,
        "min_notional_passes": bool(min_notional_passes),
        "min_qty_passes": bool(min_qty_passes),
        "viable": not blocked_reasons,
        "blocked_reason": blocked_reason,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
    }
