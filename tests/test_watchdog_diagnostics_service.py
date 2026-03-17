from services.watchdog_diagnostics_service import WatchdogDiagnosticsService


class _AuditCollector:
    def __init__(self):
        self.events = []
        self._keys = {}

    def enabled(self):
        return True

    def record_event(self, payload, throttle_key=None, throttle_sec=None, **_kwargs):
        key = throttle_key or ""
        previous = self._keys.get(key)
        if key and previous == payload:
            return False
        if key:
            self._keys[key] = dict(payload)
        self.events.append(dict(payload))
        return True


def test_emit_uses_unified_watchdog_schema():
    collector = _AuditCollector()
    service = WatchdogDiagnosticsService(collector)

    recorded = service.emit(
        watchdog_type="signal_drift",
        severity="warn",
        bot_id="bot-1",
        symbol="btcusdt",
        mode="long",
        reason="scanner_runtime_disagree",
        compact_metrics={"entry_ready_status": "ready", "gate_blocked": True},
        suggested_action="Review contract drift.",
        source_context={"entry_signal_label": "Good continuation"},
        throttle_sec=0,
    )

    assert recorded is True
    assert collector.events[0]["event_type"] == "watchdog_event"
    assert collector.events[0]["watchdog_type"] == "signal_drift"
    assert collector.events[0]["severity"] == "WARN"
    assert collector.events[0]["symbol"] == "BTCUSDT"
    assert collector.events[0]["compact_metrics"]["gate_blocked"] is True


def test_emit_dedupes_identical_payloads_for_same_watchdog_key():
    collector = _AuditCollector()
    service = WatchdogDiagnosticsService(collector)

    payload = {
        "watchdog_type": "small_bot_sizing",
        "severity": "WARN",
        "bot_id": "bot-2",
        "symbol": "ETHUSDT",
        "reason": "setup_blocked_by_min_size",
        "compact_metrics": {"signal_executable": True},
    }

    assert service.emit(**payload) is True
    assert service.emit(**payload) is False
    assert len(collector.events) == 1
