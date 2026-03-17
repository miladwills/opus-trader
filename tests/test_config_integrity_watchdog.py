from services.config_integrity_watchdog_service import ConfigIntegrityWatchdogService


class DummyAuditService:
    def __init__(self):
        self.events = []

    def record_event(self, payload, **kwargs):
        self.events.append(dict(payload))
        return True


def _event_types(audit_service):
    return [event["event_type"] for event in audit_service.events]


def test_roundtrip_audit_flags_missing_expected_boolean_field_as_dropped():
    audit_sink = DummyAuditService()
    service = ConfigIntegrityWatchdogService(audit_service=audit_sink)

    audit = service.record_save_roundtrip(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": False,
        },
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": False,
        },
        persisted_bot={
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": False,
        },
        previous_bot={
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "quick_profit_enabled": True,
            "entry_gate_enabled": True,
            "auto_stop_loss_enabled": True,
        },
        ui_path="main",
    )

    assert "auto_stop_loss_enabled" in audit["missing_expected_fields"]
    assert audit["persisted_matches_intent"] is False
    assert "config_field_dropped" in _event_types(audit_sink)
    assert "config_roundtrip_mismatch" in _event_types(audit_sink)


def test_roundtrip_audit_flags_save_success_but_persisted_value_unchanged():
    audit_sink = DummyAuditService()
    service = ConfigIntegrityWatchdogService(audit_service=audit_sink)

    audit = service.record_save_roundtrip(
        {
            "id": "bot-2",
            "symbol": "DOGEUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": False,
        },
        {
            "id": "bot-2",
            "symbol": "DOGEUSDT",
            "quick_profit_enabled": True,
            "entry_gate_enabled": False,
        },
        persisted_bot={
            "id": "bot-2",
            "symbol": "DOGEUSDT",
            "quick_profit_enabled": True,
            "entry_gate_enabled": False,
        },
        previous_bot={
            "id": "bot-2",
            "symbol": "DOGEUSDT",
            "quick_profit_enabled": True,
            "entry_gate_enabled": True,
        },
        ui_path="quick",
    )

    assert audit["save_success_but_unchanged_fields"] == ["quick_profit_enabled"]
    assert "save_success_but_unchanged" in _event_types(audit_sink)
    assert "config_roundtrip_mismatch" in _event_types(audit_sink)


def test_roundtrip_audit_surfaces_unexpected_boolean_normalization():
    audit_sink = DummyAuditService()
    service = ConfigIntegrityWatchdogService(audit_service=audit_sink)

    audit = service.record_save_roundtrip(
        {
            "id": "bot-3",
            "symbol": "XRPUSDT",
            "quick_profit_enabled": True,
            "entry_gate_enabled": True,
        },
        {
            "id": "bot-3",
            "symbol": "XRPUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": True,
        },
        persisted_bot={
            "id": "bot-3",
            "symbol": "XRPUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": True,
        },
        previous_bot={
            "id": "bot-3",
            "symbol": "XRPUSDT",
            "quick_profit_enabled": False,
            "entry_gate_enabled": True,
        },
        ui_path="quick",
    )

    assert audit["normalized_fields"] == [
        {
            "field": "quick_profit_enabled",
            "requested": True,
            "persisted": False,
        }
    ]
    assert "config_field_normalized_unexpectedly" in _event_types(audit_sink)


def test_settings_version_conflict_emits_compact_config_integrity_event():
    audit_sink = DummyAuditService()
    service = ConfigIntegrityWatchdogService(audit_service=audit_sink)

    emitted = service.record_settings_version_conflict(
        {
            "id": "bot-9",
            "symbol": "ETHUSDT",
            "mode": "short",
            "trailing_sl_enabled": False,
            "quick_profit_enabled": False,
        },
        {
            "id": "bot-9",
            "symbol": "ETHUSDT",
            "mode": "short",
            "settings_version": 12,
        },
        ui_path="quick",
        conflict_reason="stale_incoming_version",
        incoming_settings_version=11,
        current_settings_version=12,
    )

    assert emitted is True
    assert _event_types(audit_sink) == ["settings_version_conflict"]
    event = audit_sink.events[0]
    assert event["bot_id"] == "bot-9"
    assert event["symbol"] == "ETHUSDT"
    assert event["mode"] == "short"
    assert event["ui_path"] == "quick"
    assert event["incoming_settings_version"] == 11
    assert event["current_settings_version"] == 12
    assert event["conflict_reason"] == "stale_incoming_version"
    assert event["fields"] == ["trailing_sl_enabled", "quick_profit_enabled"]
