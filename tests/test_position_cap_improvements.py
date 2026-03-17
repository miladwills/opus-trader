import pytest

import config.strategy_config as strategy_cfg
from services.grid_bot_service import GridBotService


def make_service():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    return service


def test_directional_position_cap_allows_more_headroom_but_still_caps():
    service = make_service()

    long_cap_pct = service._get_effective_max_position_cap_pct(
        {"mode": "long"},
        mode="long",
    )
    neutral_cap_pct = service._get_effective_max_position_cap_pct(
        {"mode": "neutral"},
        mode="neutral",
    )

    assert long_cap_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)
    assert neutral_cap_pct == pytest.approx(strategy_cfg.MAX_POSITION_PCT)

    investment = 100.0
    leverage = 2.0
    previously_blocked_notional = 175.0
    still_blocked_notional = 181.0

    assert previously_blocked_notional > investment * leverage * strategy_cfg.MAX_POSITION_PCT
    assert previously_blocked_notional < investment * leverage * long_cap_pct
    assert still_blocked_notional > investment * leverage * long_cap_pct


def test_ai_position_cap_override_still_wins_over_mode_default():
    service = make_service()

    capped_pct = service._get_effective_max_position_cap_pct(
        {"mode": "long", "ai_max_position_cap_pct": 55.0},
        symbol="PEPEUSDT",
        mode="long",
    )

    assert capped_pct == pytest.approx(0.55)


def test_experimental_directional_position_cap_disabled_keeps_baseline(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        False,
    )
    service = make_service()

    capped_pct = service._get_effective_max_position_cap_pct(
        {
            "mode": "long",
            "setup_quality_score": 82.0,
            "setup_timing_status": "trigger_ready",
            "entry_signal_code": "good_continuation",
        },
        mode="long",
    )

    assert capped_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)


def test_experimental_directional_position_cap_adds_small_trigger_ready_headroom(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        True,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_BONUS_PCT",
        0.02,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_HARD_CEILING_PCT",
        0.93,
    )
    service = make_service()
    bot = {
        "mode": "long",
        "setup_quality_score": 82.0,
        "setup_timing_status": "trigger_ready",
        "entry_signal_code": "good_continuation",
    }

    capped_pct = service._get_effective_max_position_cap_pct(bot, mode="long")

    assert capped_pct == pytest.approx(0.92)
    assert capped_pct <= strategy_cfg.EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_HARD_CEILING_PCT
    assert bot["runtime_experiment_tags"] == [
        "exp_directional_position_cap_headroom_used"
    ]
