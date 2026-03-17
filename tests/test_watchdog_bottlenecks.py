from services.bot_manager_service import BotManagerService
from services.grid_bot_service import GridBotService
import config.strategy_config as strategy_cfg


class _AuditCollector:
    def __init__(self):
        self.events = []
        self._keys = {}

    def enabled(self):
        return True

    def record_event(self, payload, throttle_key=None, throttle_sec=None, **_kwargs):
        if throttle_key:
            previous = self._keys.get(throttle_key)
            if previous == payload:
                return False
            self._keys[throttle_key] = dict(payload)
        self.events.append(dict(payload))
        return True


class _FakeClient:
    def __init__(self):
        self.now_ts = 1_700_000_000

    def _get_now_ts(self):
        return self.now_ts


def _make_grid_service():
    service = GridBotService.__new__(GridBotService)
    service.audit_diagnostics_service = _AuditCollector()
    service.client = _FakeClient()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._emit_audit_event = GridBotService._emit_audit_event.__get__(
        service, GridBotService
    )
    service._touch_watchdog_summary = GridBotService._touch_watchdog_summary
    service._get_watchdog_capital_context = (
        GridBotService._get_watchdog_capital_context.__get__(
            service, GridBotService
        )
    )
    service._record_watchdog_operational_event = (
        GridBotService._record_watchdog_operational_event.__get__(
            service, GridBotService
        )
    )
    service._record_recenter_happened_event = (
        GridBotService._record_recenter_happened_event.__get__(
            service, GridBotService
        )
    )
    service._record_quick_profit_rebuild_event = (
        GridBotService._record_quick_profit_rebuild_event.__get__(
            service, GridBotService
        )
    )
    service._record_capital_starved_transition_event = (
        GridBotService._record_capital_starved_transition_event.__get__(
            service, GridBotService
        )
    )
    service._record_failure_breaker_transition_event = (
        GridBotService._record_failure_breaker_transition_event.__get__(
            service, GridBotService
        )
    )
    service._record_position_cap_transition_event = (
        GridBotService._record_position_cap_transition_event.__get__(
            service, GridBotService
        )
    )
    service._record_quick_profit_rebuild_transition_event = (
        GridBotService._record_quick_profit_rebuild_transition_event.__get__(
            service, GridBotService
        )
    )
    service._maybe_record_opening_follow_through_restored = (
        GridBotService._maybe_record_opening_follow_through_restored.__get__(
            service, GridBotService
        )
    )
    service._record_cap_pressure_cleared_event = (
        GridBotService._record_cap_pressure_cleared_event.__get__(
            service, GridBotService
        )
    )
    service._record_opening_orders_cancelled_by_cap_event = (
        GridBotService._record_opening_orders_cancelled_by_cap_event.__get__(
            service, GridBotService
        )
    )
    service._record_opening_follow_through_event = (
        GridBotService._record_opening_follow_through_event.__get__(
            service, GridBotService
        )
    )
    service._record_failure_breaker_armed_event = (
        GridBotService._record_failure_breaker_armed_event.__get__(
            service, GridBotService
        )
    )
    service._register_failure_breaker_event = (
        GridBotService._register_failure_breaker_event.__get__(
            service, GridBotService
        )
    )
    service._record_position_cap_hit_event = (
        GridBotService._record_position_cap_hit_event.__get__(
            service, GridBotService
        )
    )
    service._record_qty_below_min_event = (
        GridBotService._record_qty_below_min_event.__get__(service, GridBotService)
    )
    service._log_skip_order = GridBotService._log_skip_order.__get__(
        service, GridBotService
    )
    service._record_insufficient_margin_event = (
        GridBotService._record_insufficient_margin_event.__get__(
            service, GridBotService
        )
    )
    service._get_watchdog_diagnostics_service = (
        GridBotService._get_watchdog_diagnostics_service.__get__(
            service, GridBotService
        )
    )
    service._get_runtime_entry_watchdog_blocker = (
        GridBotService._get_runtime_entry_watchdog_blocker.__get__(
            service, GridBotService
        )
    )
    service._maybe_emit_small_bot_sizing_watchdog = (
        GridBotService._maybe_emit_small_bot_sizing_watchdog.__get__(
            service, GridBotService
        )
    )
    service._maybe_emit_state_flapping_watchdog = (
        GridBotService._maybe_emit_state_flapping_watchdog.__get__(
            service, GridBotService
        )
    )
    service._activate_capital_starved_opening_block = (
        GridBotService._activate_capital_starved_opening_block.__get__(
            service, GridBotService
        )
    )
    service._clear_capital_starved_opening_block = (
        GridBotService._clear_capital_starved_opening_block.__get__(
            service, GridBotService
        )
    )
    service._compact_directional_opening_sizing_fields = (
        GridBotService._compact_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._build_directional_opening_sizing_fields = (
        GridBotService._build_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._augment_directional_opening_sizing_fields = (
        GridBotService._augment_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._ai_block_opening_orders = GridBotService._ai_block_opening_orders.__get__(
        service, GridBotService
    )
    service._maybe_emit_loss_asymmetry_snapshot = (
        GridBotService._maybe_emit_loss_asymmetry_snapshot.__get__(
            service, GridBotService
        )
    )
    return service


def _make_manager_service():
    service = BotManagerService.__new__(BotManagerService)
    service.audit_diagnostics_service = _AuditCollector()
    service._safe_float = BotManagerService._safe_float
    service._emit_capital_compression_snapshot = (
        BotManagerService._emit_capital_compression_snapshot.__get__(
            service, BotManagerService
        )
    )
    return service


def _events(service, event_type):
    return [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == event_type
    ]


def test_failure_breaker_armed_emits_diagnostic_and_summary():
    service = _make_grid_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "investment": 20.0,
        "capital_partition_usdt": 12.0,
        "leverage": 10,
        "runtime_grid_count_cap": 6,
        "runtime_open_order_cap_total": 4,
    }

    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=100.0
    ) is False
    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=120.0
    ) is False
    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=140.0
    ) is True

    events = _events(service, "failure_breaker_armed")
    assert len(events) == 1
    assert events[0]["reason"] == "insufficient_margin"
    assert events[0]["effective_investment"] == 12.0
    assert events[0]["open_order_cap_total"] == 4
    assert bot["watchdog_bottleneck_summary"]["failure_breaker_armed_count"] == 1


def test_structural_min_size_failures_do_not_arm_failure_breaker_cooldown():
    service = _make_grid_service()
    bot = {
        "id": "bot-1b",
        "symbol": "PEPEUSDT",
        "mode": "long",
        "investment": 12.0,
        "capital_partition_usdt": 10.0,
        "leverage": 10,
    }

    for now_ts in (100.0, 120.0, 140.0, 160.0):
        assert (
            service._register_failure_breaker_event(
                bot, "notional_below_min", now_ts=now_ts
            )
            is False
        )
    assert service._register_failure_breaker_event(
        bot, "qty_below_min", now_ts=180.0
    ) is False

    assert len(_events(service, "failure_breaker_armed")) == 0
    assert service._failure_breaker_skip_opening_orders(bot, now_ts=181.0) == (
        False,
        None,
    )
    assert bot["_structural_opening_fit"]["reason"] == "qty_below_min"


def test_position_cap_hit_event_dedupes_identical_payloads():
    service = _make_grid_service()
    bot = {
        "id": "bot-2",
        "symbol": "ETHUSDT",
        "mode": "long",
        "investment": 30.0,
        "capital_partition_usdt": 15.0,
        "leverage": 5,
    }

    service._record_position_cap_hit_event(
        bot,
        symbol="ETHUSDT",
        mode="long",
        side="buy",
        current_notional=52.3,
        cap_notional=50.0,
        current_position_size=2.5,
        suppression_kind="add",
    )
    service._record_position_cap_hit_event(
        bot,
        symbol="ETHUSDT",
        mode="long",
        side="buy",
        current_notional=52.3,
        cap_notional=50.0,
        current_position_size=2.5,
        suppression_kind="add",
    )

    events = _events(service, "position_cap_hit")
    assert len(events) == 1
    assert events[0]["suppression_kind"] == "add"
    assert bot["watchdog_bottleneck_summary"]["position_cap_hit_count"] == 2


def test_qty_below_min_event_captures_opening_context():
    service = _make_grid_service()
    bot = {
        "id": "bot-3",
        "symbol": "SOLUSDT",
        "mode": "long",
        "investment": 12.0,
        "capital_partition_usdt": 10.0,
        "leverage": 8,
    }

    service._log_skip_order(
        bot,
        "SOLUSDT",
        "Buy",
        0.01,
        0.0,
        0.1,
        0.01,
        150.0,
        min_notional_value=5.0,
        reason="qty_below_min",
        diagnostic_context={
            "action": "grid_order",
            "opening_kind": "add",
        },
    )

    events = _events(service, "qty_below_min")
    assert len(events) == 1
    assert events[0]["attempted_action"] == "grid_order"
    assert events[0]["opening_kind"] == "add"
    assert bot["watchdog_bottleneck_summary"]["qty_below_min_count"] == 1


def test_insufficient_margin_event_dedupes_identical_context():
    service = _make_grid_service()
    bot = {
        "id": "bot-4",
        "symbol": "XRPUSDT",
        "mode": "neutral",
        "investment": 18.0,
        "capital_partition_usdt": 9.0,
        "leverage": 6,
    }

    service._record_insufficient_margin_event(
        bot,
        symbol="XRPUSDT",
        side="Buy",
        action="grid_order",
        attempted_qty=12.0,
        price=0.5,
        available_balance=1.2,
        reserve_usd=0.6,
        margin_per_order=0.8,
        current_order_count=4,
        opening_order_count=2,
        opening_order_cap=4,
    )
    service._record_insufficient_margin_event(
        bot,
        symbol="XRPUSDT",
        side="Buy",
        action="grid_order",
        attempted_qty=12.0,
        price=0.5,
        available_balance=1.2,
        reserve_usd=0.6,
        margin_per_order=0.8,
        current_order_count=4,
        opening_order_count=2,
        opening_order_cap=4,
    )

    events = _events(service, "insufficient_margin_event")
    assert len(events) == 1
    assert events[0]["attempted_action"] == "grid_order"
    assert events[0]["attempted_notional"] == 6.0
    assert bot["watchdog_bottleneck_summary"]["insufficient_margin_event_count"] == 2


def test_capital_starved_margin_block_dedupes_and_sets_opening_guard():
    service = _make_grid_service()
    bot = {
        "id": "bot-4b",
        "symbol": "PIPPINUSDT",
        "mode": "long",
        "investment": 12.0,
        "capital_partition_usdt": 10.0,
        "leverage": 10,
        "runtime_open_order_cap_total": 6,
    }

    warning = service._activate_capital_starved_opening_block(
        bot,
        symbol="PIPPINUSDT",
        reason="insufficient_margin_guard",
        side="Buy",
        action="grid_order",
        opening_kind="initial_opening",
        attempted_qty=12.5,
        price=0.5,
        min_qty=0.1,
        min_notional_value=5.0,
        leverage=10,
        available_balance=0.2,
        reserve_usd=0.1,
        opening_order_cap=6,
        current_order_count=0,
        opening_order_count=0,
    )
    service._activate_capital_starved_opening_block(
        bot,
        symbol="PIPPINUSDT",
        reason="insufficient_margin_guard",
        side="Buy",
        action="grid_order",
        opening_kind="initial_opening",
        attempted_qty=12.5,
        price=0.5,
        min_qty=0.1,
        min_notional_value=5.0,
        leverage=10,
        available_balance=0.2,
        reserve_usd=0.1,
        opening_order_cap=6,
        current_order_count=0,
        opening_order_count=0,
    )

    assert "Capital starved" in warning
    assert service._ai_block_opening_orders(bot) is True
    assert len(_events(service, "insufficient_margin_event")) == 1
    assert bot["watchdog_bottleneck_summary"]["capital_starved_opening_block_count"] == 1

    service._clear_capital_starved_opening_block(bot)
    assert service._ai_block_opening_orders(bot) is False
    assert bot["watchdog_bottleneck_summary"]["capital_starved_active"] is False
    assert len(_events(service, "capital_starved_opening_block")) == 1
    assert len(_events(service, "capital_starved_block_cleared")) == 1


def test_capital_starved_qty_block_reuses_qty_watchdog_event_once():
    service = _make_grid_service()
    bot = {
        "id": "bot-4c",
        "symbol": "DOGEUSDT",
        "mode": "neutral",
        "investment": 9.0,
        "capital_partition_usdt": 7.0,
        "leverage": 5,
    }

    service._activate_capital_starved_opening_block(
        bot,
        symbol="DOGEUSDT",
        reason="qty_below_min",
        side="Sell",
        action="scalp_market_entry",
        opening_kind="initial_opening",
        attempted_qty=3.0,
        price=0.1,
        min_qty=5.0,
        min_notional_value=5.0,
        leverage=5,
        available_balance=1.0,
        reserve_usd=0.2,
        opening_order_cap=2,
        current_order_count=0,
        opening_order_count=0,
    )
    service._activate_capital_starved_opening_block(
        bot,
        symbol="DOGEUSDT",
        reason="qty_below_min",
        side="Sell",
        action="scalp_market_entry",
        opening_kind="initial_opening",
        attempted_qty=3.0,
        price=0.1,
        min_qty=5.0,
        min_notional_value=5.0,
        leverage=5,
        available_balance=1.0,
        reserve_usd=0.2,
        opening_order_cap=2,
        current_order_count=0,
        opening_order_count=0,
    )

    qty_events = _events(service, "qty_below_min")
    assert len(qty_events) == 1
    assert qty_events[0]["attempted_action"] == "scalp_market_entry"
    assert bot["watchdog_bottleneck_summary"]["capital_starved_opening_block_count"] == 1


def test_loss_asymmetry_snapshot_emits_compact_ratio_once_per_state():
    service = _make_grid_service()
    bot = {
        "id": "bot-5",
        "symbol": "PIPPINUSDT",
        "mode": "long",
        "quick_profit_count": 7,
        "quick_profit_total": 0.57,
        "profit_lock_executed_count": 3,
        "realized_pnl": -7.1,
        "total_pnl": -7.1,
    }

    service._maybe_emit_loss_asymmetry_snapshot(
        bot,
        symbol="PIPPINUSDT",
        mode="long",
    )
    service._maybe_emit_loss_asymmetry_snapshot(
        bot,
        symbol="PIPPINUSDT",
        mode="long",
    )

    events = _events(service, "loss_asymmetry_snapshot")
    assert len(events) == 1
    assert events[0]["summary"] == "small_wins_outweighed_by_losses"
    assert events[0]["harvest_to_loss_ratio"] < 1.0


def test_bot_manager_capital_compression_snapshot_records_launch_context():
    service = _make_manager_service()
    bot = {
        "id": "bot-6",
        "symbol": "ADAUSDT",
        "mode": "long",
        "investment": 25.0,
        "runtime_grid_count_cap": 5,
        "runtime_open_order_cap_total": 4,
    }
    launch_analysis = {
        "requested_investment": 25.0,
        "capital_partition_usdt": 10.0,
        "reserve_usdt": 1.5,
        "usable_investment": 8.5,
        "effective_leverage": 7.0,
        "requested_grid_count": 8,
    }

    service._emit_capital_compression_snapshot(
        bot,
        launch_analysis,
        symbol="ADAUSDT",
        mode="long",
    )

    events = _events(service, "capital_compression_snapshot")
    assert len(events) == 1
    assert events[0]["capital_compression_active"] is True
    assert events[0]["requested_investment"] == 25.0
    assert events[0]["effective_investment"] == 10.0
    assert bot["watchdog_bottleneck_summary"]["capital_compression_snapshot_count"] == 1


def test_quick_profit_rebuild_event_records_positive_follow_through():
    service = _make_grid_service()
    bot = {
        "id": "bot-7",
        "symbol": "PIPPINUSDT",
        "mode": "long",
    }

    service._record_quick_profit_rebuild_event(
        bot,
        symbol="PIPPINUSDT",
        mode="long",
        current_price=0.3912,
        new_lower=0.3846,
        new_upper=0.3978,
        cancelled_orders=3,
        remaining_position_size=120.0,
        rebuild_width_mult=0.8,
        rebuild_width_source="subset_dynamic_long_clustered",
        rebuild_width_pct=0.036,
    )

    events = _events(service, "quick_profit_rebuild_happened")
    assert len(events) == 1
    assert events[0]["cancelled_orders"] == 3
    assert events[0]["rebuild_width_source"] == "subset_dynamic_long_clustered"
    assert bot["watchdog_bottleneck_summary"]["quick_profit_rebuild_count"] == 1


def test_opening_follow_through_events_capture_success_and_blocked_states():
    service = _make_grid_service()
    bot = {
        "id": "bot-8",
        "symbol": "XRPUSDT",
        "mode": "long",
    }
    opening_sizing = service._build_directional_opening_sizing_fields(
        planned_qty=0.9,
        price=89.32,
        leverage=5.0,
        opening_qty_adjustment={
            "qty": 0.3,
            "candidate_qty": 0.3,
            "adjusted": True,
            "planned_notional": 80.388,
            "candidate_notional": 26.796,
            "available_opening_margin": 5.9097,
        },
    )

    service._record_opening_follow_through_event(
        bot,
        event_type="opening_orders_placed",
        symbol="XRPUSDT",
        mode="long",
        buy_candidates=3,
        sell_candidates=0,
        buy_orders_placed=2,
        sell_orders_placed=0,
        initial_opening_orders_placed=1,
        add_follow_through_placed=1,
        skipped_reasons={"spread_check": 1},
        opening_order_cap=4,
        current_order_count=2,
        opening_sizing=service._augment_directional_opening_sizing_fields(
            opening_sizing,
            submitted_qty=0.3,
            submitted_price=88.8,
        ),
    )
    service._record_opening_follow_through_event(
        bot,
        event_type="add_follow_through_blocked",
        symbol="XRPUSDT",
        mode="long",
        buy_candidates=2,
        sell_candidates=0,
        buy_orders_placed=0,
        sell_orders_placed=0,
        initial_opening_orders_placed=0,
        add_follow_through_placed=0,
        skipped_reasons={"position_cap_hit": 1},
        primary_reason="position_cap_hit",
        opening_order_cap=4,
        current_order_count=4,
        opening_sizing=service._augment_directional_opening_sizing_fields(
            opening_sizing,
            final_blocker_reason="position_cap_hit",
        ),
    )

    placed = _events(service, "opening_orders_placed")
    assert len(placed) == 1
    assert placed[0]["planned_qty"] == 0.9
    assert placed[0]["capped_qty"] == 0.3
    assert placed[0]["submitted_qty"] == 0.3
    assert placed[0]["affordability_cap_applied"] is True
    blocked = _events(service, "add_follow_through_blocked")
    assert len(blocked) == 1
    assert blocked[0]["primary_reason"] == "position_cap_hit"
    assert blocked[0]["final_blocker_reason"] == "position_cap_hit"
    assert bot["watchdog_bottleneck_summary"]["opening_orders_placed_event_count"] == 1
    assert bot["watchdog_bottleneck_summary"]["add_follow_through_blocked_count"] == 1


def test_capital_starved_transition_event_carries_directional_opening_sizing_proof():
    service = _make_grid_service()
    bot = {
        "id": "bot-proof",
        "symbol": "TAOUSDT",
        "mode": "long",
    }
    opening_sizing = service._build_directional_opening_sizing_fields(
        planned_qty=0.538,
        price=231.86,
        leverage=10.0,
        opening_qty_adjustment={
            "qty": 0.538,
            "candidate_qty": 0.538,
            "adjusted": False,
            "blocked_reason": "insufficient_margin",
            "planned_notional": 124.74068,
            "candidate_notional": 124.74068,
            "available_opening_margin": 2.58407868,
        },
        final_blocker_reason="insufficient_margin",
    )

    service._record_capital_starved_transition_event(
        bot,
        event_type="capital_starved_opening_block",
        symbol="TAOUSDT",
        mode="long",
        reason="insufficient_margin",
        side="Buy",
        action="grid_order",
        opening_kind="add",
        available_opening_margin=2.58407868,
        required_margin=12.474068,
        opening_order_cap=6,
        opening_sizing=opening_sizing,
    )

    event = _events(service, "capital_starved_opening_block")[0]
    assert event["planned_notional"] == 124.74068
    assert event["capped_notional"] == 124.74068
    assert event["available_opening_margin"] == 2.58407868
    assert event["required_margin"] == 12.474068
    assert event["final_blocker_reason"] == "insufficient_margin"


def test_failure_breaker_transition_events_emit_start_and_clear():
    service = _make_grid_service()
    bot = {
        "id": "bot-9",
        "symbol": "PIPPINUSDT",
        "mode": "long",
        "investment": 12.0,
        "capital_partition_usdt": 10.0,
        "leverage": 10,
    }

    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=100.0
    ) is False
    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=120.0
    ) is False
    assert service._register_failure_breaker_event(
        bot, "insufficient_margin", now_ts=140.0
    ) is True

    service._clear_failure_breaker(bot, clear_cooldown=True)

    assert len(_events(service, "failure_breaker_cooldown_started")) == 1
    assert len(_events(service, "failure_breaker_cooldown_cleared")) == 1


def test_transition_aliases_emit_for_position_cap_and_follow_through_restore():
    service = _make_grid_service()
    bot = {
        "id": "bot-10",
        "symbol": "XRPUSDT",
        "mode": "long",
        "last_watchdog_follow_through_state": "opening_orders_suppressed",
    }

    service._record_position_cap_transition_event(
        bot,
        event_type="position_cap_suppression_started",
        symbol="XRPUSDT",
        mode="long",
        current_notional=62.0,
        cap_notional=60.0,
        side="buy",
    )
    service._maybe_record_opening_follow_through_restored(
        bot,
        symbol="XRPUSDT",
        mode="long",
        restored_to="opening_orders_placed",
        buy_orders_placed=2,
        sell_orders_placed=0,
    )
    service._record_quick_profit_rebuild_transition_event(
        bot,
        event_type="quick_profit_rebuild_started",
        symbol="XRPUSDT",
        mode="long",
        current_price=0.39,
    )
    service._record_quick_profit_rebuild_transition_event(
        bot,
        event_type="quick_profit_rebuild_completed",
        symbol="XRPUSDT",
        mode="long",
        current_price=0.39,
        cancelled_orders=2,
        new_lower=0.384,
        new_upper=0.396,
        rebuild_width_source="subset_dynamic_long_clustered",
        rebuild_width_pct=0.036,
    )

    assert len(_events(service, "position_cap_suppression_started")) == 1
    restored = _events(service, "opening_follow_through_restored")
    assert len(restored) == 1
    assert restored[0]["restored_from"] == "opening_orders_suppressed"
    assert len(_events(service, "quick_profit_rebuild_started")) == 1
    assert len(_events(service, "quick_profit_rebuild_completed")) == 1


def test_small_bot_sizing_watchdog_emits_when_valid_setup_is_min_size_blocked():
    service = _make_grid_service()
    bot = {
        "id": "bot-small",
        "symbol": "DOGEUSDT",
        "mode": "long",
        "entry_signal_executable": True,
        "entry_signal_preferred": False,
        "_small_capital_block_opening_orders": True,
        "last_skip_reason": "qty_below_min",
        "watchdog_bottleneck_summary": {
            "capital_compression_active": True,
        },
        "investment": 12.0,
        "capital_partition_usdt": 7.5,
        "runtime_open_order_cap_total": 2,
    }

    service._maybe_emit_small_bot_sizing_watchdog(
        bot,
        symbol="DOGEUSDT",
        mode="long",
        blockers=[],
    )

    watchdog_events = [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "watchdog_event"
    ]
    assert len(watchdog_events) == 1
    assert watchdog_events[0]["watchdog_type"] == "small_bot_sizing"
    assert watchdog_events[0]["reason"] == "setup_blocked_by_min_size"
    assert watchdog_events[0]["compact_metrics"]["signal_executable"] is True


def test_small_bot_sizing_watchdog_surfaces_exchange_truth_blocker_reason():
    service = _make_grid_service()
    bot = {
        "id": "bot-truth",
        "symbol": "BTCUSDT",
        "mode": "long",
        "entry_signal_executable": True,
        "entry_signal_preferred": True,
        "exchange_reconciliation": {
            "status": "diverged",
            "reason": "orphaned_position",
            "mismatches": ["orphaned_position"],
        },
    }

    service._maybe_emit_small_bot_sizing_watchdog(
        bot,
        symbol="BTCUSDT",
        mode="long",
        blockers=[],
    )

    watchdog_events = [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "watchdog_event"
    ]
    assert len(watchdog_events) == 1
    assert watchdog_events[0]["watchdog_type"] == "small_bot_sizing"
    assert watchdog_events[0]["reason"] == "reconciliation_diverged"
    assert watchdog_events[0]["compact_metrics"]["runtime_blocker"] == (
        "reconciliation_diverged"
    )


def test_state_flapping_watchdog_emits_after_repeated_actionable_flips(monkeypatch):
    service = _make_grid_service()
    bot = {
        "id": "bot-flap",
        "symbol": "BTCUSDT",
        "mode": "long",
    }
    monkeypatch.setattr(strategy_cfg, "STATE_FLAPPING_WATCHDOG_WINDOW_SEC", 180)
    monkeypatch.setattr(strategy_cfg, "STATE_FLAPPING_WATCHDOG_MIN_CHANGES", 4)
    monkeypatch.setattr(strategy_cfg, "STATE_FLAPPING_WATCHDOG_MIN_ACTIONABLE_FLIPS", 2)
    states = [
        {"entry_signal_executable": True, "_entry_gate_blocked": False},
        {"entry_signal_executable": False, "_entry_gate_blocked": True},
        {"entry_signal_executable": True, "_entry_gate_blocked": False},
        {"entry_signal_executable": False, "_entry_gate_blocked": True},
    ]
    for index, state in enumerate(states):
        bot.update(state)
        service._maybe_emit_state_flapping_watchdog(
            bot,
            symbol="BTCUSDT",
            mode="long",
            signal_code=f"state_{index}",
            signal_phase="live",
            blockers=[],
        )

    watchdog_events = [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "watchdog_event"
    ]
    assert len(watchdog_events) == 1
    assert watchdog_events[0]["watchdog_type"] == "state_flapping"
    assert watchdog_events[0]["reason"] == "actionable_wait_flapping"
