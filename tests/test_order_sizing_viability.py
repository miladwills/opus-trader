from services.order_sizing_viability import build_order_sizing_viability


def test_build_order_sizing_viability_flags_min_qty_even_when_notional_passes():
    payload = build_order_sizing_viability(
        symbol="ETHUSDT",
        reference_price=4000.0,
        price_source="mark_price",
        leverage=3.0,
        investment=120.0,
        order_splits=8,
        min_notional=5.0,
        min_qty=0.02,
    )

    assert payload["estimated_per_order_notional"] == 45.0
    assert payload["min_notional_passes"] is True
    assert payload["min_qty_passes"] is False
    assert payload["effective_min_order_notional"] == 80.0
    assert payload["blocked_reason"] == "below_min_qty"
    assert payload["viable"] is False
