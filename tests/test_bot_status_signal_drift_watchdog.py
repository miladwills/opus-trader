from services.bot_status_service import BotStatusService


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


class _PnlStub:
    def __init__(self):
        self.audit_diagnostics_service = _AuditCollector()


def test_signal_drift_watchdog_emits_when_readiness_disagrees_with_runtime_blocker():
    service = BotStatusService.__new__(BotStatusService)
    service.pnl_service = _PnlStub()
    service._get_watchdog_diagnostics_service = (
        BotStatusService._get_watchdog_diagnostics_service.__get__(
            service, BotStatusService
        )
    )
    service._get_runtime_signal_blocker = BotStatusService._get_runtime_signal_blocker
    service._maybe_emit_signal_drift_watchdog = (
        BotStatusService._maybe_emit_signal_drift_watchdog.__get__(
            service, BotStatusService
        )
    )

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "scanner_recommendation_differs": True,
        "scanner_recommended_mode": "short",
        "entry_signal_code": "good_continuation",
        "entry_signal_label": "Good continuation",
        "entry_signal_executable": True,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "insufficient_margin",
    }
    entry_readiness = {
        "entry_ready_status": "ready",
        "entry_ready_reason": "good_continuation",
        "analysis_ready_status": "watch",
        "analysis_ready_reason": "wait",
        "live_gate_status": "ready",
        "live_gate_reason": "clear",
    }

    service._maybe_emit_signal_drift_watchdog(bot, entry_readiness)

    events = service.pnl_service.audit_diagnostics_service.events
    assert len(events) == 2
    reasons = sorted(event["reason"] for event in events)
    assert reasons == ["analysis_runtime_disagree", "scanner_runtime_disagree"]
    assert all(event["watchdog_type"] == "signal_drift" for event in events)


def test_signal_drift_watchdog_ignores_stale_capital_starved_blocker_when_structure_now_blocks():
    service = BotStatusService.__new__(BotStatusService)
    service.pnl_service = _PnlStub()
    service._get_watchdog_diagnostics_service = (
        BotStatusService._get_watchdog_diagnostics_service.__get__(
            service, BotStatusService
        )
    )
    service._get_runtime_signal_blocker = BotStatusService._get_runtime_signal_blocker
    service._maybe_emit_signal_drift_watchdog = (
        BotStatusService._maybe_emit_signal_drift_watchdog.__get__(
            service, BotStatusService
        )
    )

    bot = {
        "id": "bot-2",
        "symbol": "BTCUSDT",
        "mode": "long",
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "insufficient_margin",
    }
    entry_readiness = {
        "entry_ready_status": "blocked",
        "entry_ready_reason": "near_resistance",
        "analysis_ready_status": "watch",
        "analysis_ready_reason": "wait",
        "live_gate_status": "ready",
        "live_gate_reason": "clear",
    }

    service._maybe_emit_signal_drift_watchdog(bot, entry_readiness)

    events = service.pnl_service.audit_diagnostics_service.events
    assert events == []


def test_signal_drift_watchdog_does_not_flag_split_model_setup_ready_with_execution_block():
    service = BotStatusService.__new__(BotStatusService)
    service.pnl_service = _PnlStub()
    service._get_watchdog_diagnostics_service = (
        BotStatusService._get_watchdog_diagnostics_service.__get__(
            service, BotStatusService
        )
    )
    service._get_runtime_signal_blocker = BotStatusService._get_runtime_signal_blocker
    service._maybe_emit_signal_drift_watchdog = (
        BotStatusService._maybe_emit_signal_drift_watchdog.__get__(
            service, BotStatusService
        )
    )

    bot = {
        "id": "bot-3",
        "symbol": "ETHUSDT",
        "mode": "long",
        "entry_signal_code": "good_continuation",
        "entry_signal_label": "Good continuation",
        "entry_signal_executable": True,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "insufficient_margin",
    }
    entry_readiness = {
        "entry_ready_status": "blocked",
        "entry_ready_reason": "insufficient_margin",
        "analysis_ready_status": "ready",
        "analysis_ready_reason": "good_continuation",
        "setup_ready_status": "ready",
        "setup_ready_reason": "good_continuation",
        "execution_blocked": True,
        "execution_viability_status": "blocked",
        "execution_viability_reason": "insufficient_margin",
        "live_gate_status": "on",
        "live_gate_reason": "gate_on",
    }

    service._maybe_emit_signal_drift_watchdog(bot, entry_readiness)

    assert service.pnl_service.audit_diagnostics_service.events == []


def test_runtime_signal_blocker_prefers_exchange_truth_reason():
    blocker = BotStatusService._get_runtime_signal_blocker(
        {
            "exchange_reconciliation": {
                "status": "diverged",
                "reason": "orphaned_position",
                "mismatches": ["orphaned_position"],
            }
        }
    )

    assert blocker == "reconciliation_diverged"
