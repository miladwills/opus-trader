from services.adaptive_profit_protection_service import (
    AdaptiveProfitProtectionService,
)


def test_profit_protection_service_holds_strong_trend_with_small_giveback():
    result = AdaptiveProfitProtectionService.evaluate(
        bot={"profit_protection_mode": "advisory_only"},
        position_side="Buy",
        current_profit_pct=0.012,
        current_profit_usdt=2.0,
        peak_profit_pct=0.013,
        indicators={
            "atr_pct": 0.008,
            "adx": 28,
            "rsi": 62,
            "price_velocity": 0.02,
            "ema_slope": 0.01,
        },
        regime_effective="UP",
        regime_confidence="high",
        previous_state={},
    )

    assert result["decision"] == "wait"
    assert result["reason_family"] == "trend_intact"
    assert result["armed"] is True
    assert result["actionable"] is False
    assert result["trend_bucket"] == "strong"


def test_profit_protection_service_recommends_exit_in_sideways_exhaustion():
    result = AdaptiveProfitProtectionService.evaluate(
        bot={"profit_protection_mode": "shadow"},
        position_side="Buy",
        current_profit_pct=0.009,
        current_profit_usdt=1.2,
        peak_profit_pct=0.014,
        indicators={
            "atr_pct": 0.01,
            "adx": 12,
            "rsi": 71,
            "price_velocity": -0.02,
            "ema_slope": -0.01,
        },
        regime_effective="SIDEWAYS",
        regime_confidence="low",
        previous_state={},
    )

    assert result["decision"] == "exit_now"
    assert result["reason_family"] == "exhaustion_risk"
    assert result["actionable"] is True
    assert result["trend_bucket"] == "weak"
    assert result["momentum_state"] == "exhausted"
