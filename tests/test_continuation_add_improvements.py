import pytest

import config.strategy_config as strategy_cfg
from services.grid_bot_service import GridBotService


def make_service():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._round_to_step = GridBotService._round_to_step.__get__(
        service, GridBotService
    )
    service._get_opening_size_limit_reason = (
        GridBotService._get_opening_size_limit_reason.__get__(
            service, GridBotService
        )
    )
    return service


def _strong_profitable_long_bot(**overrides):
    bot = {
        "mode": "long",
        "setup_timing_status": "trigger_ready",
        "setup_quality_score": 82.0,
        "entry_signal_code": "good_continuation",
        "entry_ready_reason": "good_continuation",
        "analysis_ready_reason": "good_continuation",
        "entry_signal_late": False,
        "entry_signal_extension_ratio": 0.34,
        "breakout_no_chase_blocked": False,
        "unrealized_pnl": 2.5,
    }
    bot.update(overrides)
    return bot


def test_short_slot_allocator_prefers_opening_sell_when_only_one_slot_remains():
    service = make_service()

    buy_levels, sell_levels = service._limit_levels_for_available_order_slots(
        buy_levels=[99.8],
        sell_levels=[100.1, 100.2],
        max_new=1,
        buy_reduce_only=True,
        sell_reduce_only=False,
    )

    assert buy_levels == []
    assert sell_levels == [100.1]


def test_short_slot_allocator_still_keeps_reduce_only_buy_when_capacity_remains():
    service = make_service()

    buy_levels, sell_levels = service._limit_levels_for_available_order_slots(
        buy_levels=[99.8],
        sell_levels=[100.1, 100.2, 100.3],
        max_new=3,
        buy_reduce_only=True,
        sell_reduce_only=False,
    )

    assert buy_levels == [99.8]
    assert sell_levels == [100.1, 100.2]


def test_long_near_price_continuation_add_flag_defaults_on():
    assert strategy_cfg.EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED is True


def test_long_near_price_continuation_add_can_be_rolled_back_off_explicitly(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED",
        False,
    )
    service = make_service()

    candidate = service._get_long_near_price_continuation_level(
        bot=_strong_profitable_long_bot(),
        levels=[99.5, 100.12, 100.26, 100.7],
        last_price=100.0,
        mode="long",
        range_mode="dynamic",
        current_position_side="buy",
        current_position_size=1.0,
        current_position_unrealized_pnl=2.0,
        planned_qty=0.2,
        leverage=5.0,
        min_order_qty=0.1,
        min_notional_value=5.0,
        available_balance=20.0,
    )

    assert candidate is None


def test_long_near_price_continuation_add_allows_one_fresh_profitable_candidate(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED",
        True,
    )
    service = make_service()
    bot = _strong_profitable_long_bot()

    candidate = service._get_long_near_price_continuation_level(
        bot=bot,
        levels=[99.5, 100.12, 100.26, 100.7],
        last_price=100.0,
        mode="long",
        range_mode="dynamic",
        current_position_side="buy",
        current_position_size=1.0,
        current_position_unrealized_pnl=2.0,
        planned_qty=0.2,
        leverage=5.0,
        min_order_qty=0.1,
        min_notional_value=5.0,
        available_balance=20.0,
    )

    assert candidate == pytest.approx(100.12)
    assert bot["runtime_experiment_tags"] == [
        "exp_long_near_price_continuation_add_used"
    ]


def test_long_near_price_continuation_add_rejects_borderline_quality(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED",
        True,
    )
    service = make_service()

    candidate = service._get_long_near_price_continuation_level(
        bot=_strong_profitable_long_bot(setup_quality_score=71.0),
        levels=[99.5, 100.12, 100.26, 100.7],
        last_price=100.0,
        mode="long",
        range_mode="dynamic",
        current_position_side="buy",
        current_position_size=1.0,
        current_position_unrealized_pnl=2.0,
        planned_qty=0.2,
        leverage=5.0,
        min_order_qty=0.1,
        min_notional_value=5.0,
        available_balance=20.0,
    )

    assert candidate is None


def test_long_near_price_continuation_add_rejects_late_extension(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED",
        True,
    )
    service = make_service()

    candidate = service._get_long_near_price_continuation_level(
        bot=_strong_profitable_long_bot(
            entry_signal_late=True,
            entry_signal_extension_ratio=0.86,
        ),
        levels=[99.5, 100.12, 100.26, 100.7],
        last_price=100.0,
        mode="long",
        range_mode="dynamic",
        current_position_side="buy",
        current_position_size=1.0,
        current_position_unrealized_pnl=2.0,
        planned_qty=0.2,
        leverage=5.0,
        min_order_qty=0.1,
        min_notional_value=5.0,
        available_balance=20.0,
    )

    assert candidate is None


def test_long_near_price_continuation_add_rejects_true_floor_margin_failure(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED",
        True,
    )
    service = make_service()

    candidate = service._get_long_near_price_continuation_level(
        bot=_strong_profitable_long_bot(),
        levels=[99.5, 100.12, 100.26, 100.7],
        last_price=100.0,
        mode="long",
        range_mode="dynamic",
        current_position_side="buy",
        current_position_size=1.0,
        current_position_unrealized_pnl=2.0,
        planned_qty=0.2,
        leverage=5.0,
        min_order_qty=0.1,
        min_notional_value=5.0,
        available_balance=0.5,
    )

    assert candidate is None


def test_profitable_add_cap_headroom_keeps_baseline_when_flag_is_off(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED",
        False,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        False,
    )
    service = make_service()

    capped_pct = service._get_effective_max_position_cap_pct(
        _strong_profitable_long_bot(),
        mode="long",
        position_side="buy",
        position_size=1.0,
        position_unrealized_pnl=2.0,
        continuation_add_candidate_active=True,
    )

    assert capped_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)


def test_profitable_add_cap_headroom_flag_defaults_on():
    assert (
        strategy_cfg.EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED
        is True
    )


def test_profitable_add_cap_headroom_adds_small_bonus_under_hard_ceiling(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_BONUS_PCT",
        0.02,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_HARD_CEILING_PCT",
        0.915,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        False,
    )
    service = make_service()
    bot = _strong_profitable_long_bot()

    capped_pct = service._get_effective_max_position_cap_pct(
        bot,
        mode="long",
        position_side="buy",
        position_size=1.0,
        position_unrealized_pnl=2.0,
        continuation_add_candidate_active=True,
    )

    assert capped_pct == pytest.approx(0.915)
    assert bot["runtime_experiment_tags"] == [
        "exp_profitable_add_cap_headroom_used"
    ]


def test_profitable_add_cap_headroom_requires_actual_continuation_candidate(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        False,
    )
    service = make_service()

    capped_pct = service._get_effective_max_position_cap_pct(
        _strong_profitable_long_bot(),
        mode="long",
        position_side="buy",
        position_size=1.0,
        position_unrealized_pnl=2.0,
        continuation_add_candidate_active=False,
    )

    assert capped_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)


def test_profitable_add_cap_headroom_does_not_apply_to_unprofitable_or_late_positions(monkeypatch):
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        strategy_cfg,
        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED",
        False,
    )
    service = make_service()

    losing_pct = service._get_effective_max_position_cap_pct(
        _strong_profitable_long_bot(unrealized_pnl=-0.2),
        mode="long",
        position_side="buy",
        position_size=1.0,
        position_unrealized_pnl=-0.2,
        continuation_add_candidate_active=True,
    )
    late_pct = service._get_effective_max_position_cap_pct(
        _strong_profitable_long_bot(
            entry_signal_late=True,
            entry_signal_extension_ratio=0.9,
        ),
        mode="long",
        position_side="buy",
        position_size=1.0,
        position_unrealized_pnl=2.0,
        continuation_add_candidate_active=True,
    )

    assert losing_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)
    assert late_pct == pytest.approx(strategy_cfg.DIRECTIONAL_MAX_POSITION_PCT)
