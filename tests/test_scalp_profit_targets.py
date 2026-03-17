from services.scalp_pnl_service import ScalpPnlService, MarketCondition


def test_position_scaled_targets_grow_with_position_notional():
    service = ScalpPnlService()

    base = service.calculate_position_scaled_targets(20.0)
    large = service.calculate_position_scaled_targets(120.0)

    assert base["recommended_target"] == service.target_profit
    assert large["recommended_target"] > base["recommended_target"]
    assert large["quick_profit"] > service.quick_profit
    assert large["min_profit"] > service.min_profit


def test_should_take_profit_uses_scaled_target_for_large_position():
    service = ScalpPnlService()
    market_analysis = {
        "condition": MarketCondition.CALM,
        "recommended_profit_target": service.target_profit,
        "momentum_strength": 0.6,
        "momentum_direction": "up",
        "is_choppy": False,
    }

    should_exit_small, _ = service.should_take_profit(
        unrealized_pnl=0.20,
        market_analysis=market_analysis,
        position_side="Buy",
        position_notional=20.0,
    )
    should_exit_large, reason_large = service.should_take_profit(
        unrealized_pnl=0.20,
        market_analysis=market_analysis,
        position_side="Buy",
        position_notional=120.0,
    )

    assert should_exit_small is True
    assert should_exit_large is False
    assert "target" in reason_large.lower() or "minimum" in reason_large.lower()
