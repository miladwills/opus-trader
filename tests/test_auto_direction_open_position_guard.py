from services.grid_bot_service import GridBotService


class _AuditCollector:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, throttle_key=None, throttle_sec=None, **_kwargs):
        self.events.append(dict(payload))
        return True


class _FakeClient:
    def __init__(self, positions):
        self.positions = list(positions)

    def get_positions(self, skip_cache=True):
        return {"success": True, "data": {"list": list(self.positions)}}


def _make_service(positions):
    service = GridBotService.__new__(GridBotService)
    service.client = _FakeClient(positions)
    service.audit_diagnostics_service = _AuditCollector()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._emit_audit_event = GridBotService._emit_audit_event.__get__(
        service, GridBotService
    )
    service._record_watchdog_operational_event = (
        GridBotService._record_watchdog_operational_event.__get__(
            service, GridBotService
        )
    )
    service._touch_watchdog_summary = GridBotService._touch_watchdog_summary
    service._is_auto_pilot_placeholder_symbol = (
        GridBotService._is_auto_pilot_placeholder_symbol
    )
    service._clear_auto_direction_deferred_state = (
        GridBotService._clear_auto_direction_deferred_state
    )
    service._get_symbol_live_exposure_state = (
        GridBotService._get_symbol_live_exposure_state.__get__(
            service, GridBotService
        )
    )
    service._should_defer_auto_direction_neutral_switch = (
        GridBotService._should_defer_auto_direction_neutral_switch.__get__(
            service, GridBotService
        )
    )
    return service


def _event_types(service):
    return [event.get("event_type") for event in service.audit_diagnostics_service.events]


def test_auto_direction_neutral_switch_blocked_when_live_exposure_exists():
    service = _make_service(
        [{"symbol": "BTCUSDT", "size": "1.25", "side": "Buy", "positionIdx": 1}]
    )
    bot = {"id": "bot-1", "symbol": "BTCUSDT", "mode": "long"}

    deferred, exposure_state = service._should_defer_auto_direction_neutral_switch(
        bot,
        symbol="BTCUSDT",
        current_mode="long",
        target_mode="neutral",
    )

    assert deferred is True
    assert exposure_state["has_live_exposure"] is True
    assert bot["runtime_mode_deferred_target"] == "neutral"
    assert bot["runtime_mode_deferred_applied"] == "long"
    assert (
        bot["runtime_mode_deferred_reason"]
        == "neutral_switch_deferred_due_to_live_exposure"
    )
    assert _event_types(service) == [
        "auto_direction_switch_with_open_position_attempt",
        "auto_direction_switch_blocked_open_position",
    ]
    blocked_event = service.audit_diagnostics_service.events[-1]
    assert blocked_event["desired_target_mode"] == "neutral"
    assert blocked_event["actual_applied_mode"] == "long"
    assert blocked_event["position_count"] == 1
    assert blocked_event["total_position_size"] == 1.25
    assert blocked_event["deferred_reason"] == "neutral_switch_deferred_due_to_live_exposure"
    assert (
        bot["watchdog_bottleneck_summary"]["auto_direction_switch_blocked_open_position_count"]
        == 1
    )


def test_auto_direction_neutral_switch_allowed_when_position_is_flat():
    service = _make_service(
        [{"symbol": "BTCUSDT", "size": "0", "side": "Buy", "positionIdx": 1}]
    )
    bot = {
        "id": "bot-2",
        "symbol": "BTCUSDT",
        "mode": "long",
        "runtime_mode_deferred_target": "neutral",
        "runtime_mode_deferred_applied": "long",
        "runtime_mode_deferred_reason": "neutral_switch_deferred_due_to_live_exposure",
        "runtime_mode_deferred_at": "2026-03-13T00:00:00+00:00",
    }

    deferred, exposure_state = service._should_defer_auto_direction_neutral_switch(
        bot,
        symbol="BTCUSDT",
        current_mode="long",
        target_mode="neutral",
    )

    assert deferred is False
    assert exposure_state["has_live_exposure"] is False
    assert "runtime_mode_deferred_target" not in bot
    assert "runtime_mode_deferred_applied" not in bot
    assert "runtime_mode_deferred_reason" not in bot
    assert service.audit_diagnostics_service.events == []


def test_auto_direction_non_neutral_switch_is_not_blocked_by_open_position_guard():
    service = _make_service(
        [{"symbol": "BTCUSDT", "size": "2", "side": "Buy", "positionIdx": 1}]
    )
    bot = {"id": "bot-3", "symbol": "BTCUSDT", "mode": "long"}

    deferred, exposure_state = service._should_defer_auto_direction_neutral_switch(
        bot,
        symbol="BTCUSDT",
        current_mode="long",
        target_mode="short",
    )

    assert deferred is False
    assert exposure_state["has_live_exposure"] is True
    assert bot.get("runtime_mode_deferred_reason") is None
    assert service.audit_diagnostics_service.events == []
