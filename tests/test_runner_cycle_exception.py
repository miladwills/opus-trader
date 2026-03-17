from datetime import datetime, timezone

import runner


class _FakeBotStorage:
    def __init__(self, persisted_bot=None):
        self.persisted_bot = dict(persisted_bot or {})
        self.saved = []

    def get_bot(self, bot_id):
        if not self.persisted_bot:
            return None
        if self.persisted_bot.get("id") != bot_id:
            return None
        return dict(self.persisted_bot)

    def save_bot(self, bot):
        snapshot = dict(bot)
        self.saved.append(snapshot)
        self.persisted_bot = snapshot
        return snapshot


class _FakeGridBotService:
    def __init__(self, reconcile_status="error_no_exchange_exposure"):
        self.calls = []
        self.reconcile_status = reconcile_status

    def reconcile_bots_exchange_truth(self, bots, *, reason, force=False):
        snapshots = []
        for bot in list(bots or []):
            updated = dict(bot)
            updated["exchange_reconciliation"] = {
                "status": self.reconcile_status,
                "reason": self.reconcile_status,
                "source": reason,
            }
            snapshots.append(updated)
        self.calls.append(
            {
                "reason": reason,
                "force": force,
                "bot_ids": [bot.get("id") for bot in list(bots or [])],
            }
        )
        return snapshots


def test_persist_bot_cycle_exception_marks_active_bot_error():
    storage = _FakeBotStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "running",
            "last_error": None,
        }
    )
    grid_service = _FakeGridBotService()

    reconciled = runner._persist_bot_cycle_exception(
        storage,
        grid_service,
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        RuntimeError("boom"),
    )

    assert len(storage.saved) == 1
    saved = storage.saved[0]
    assert saved["status"] == "error"
    assert "Unhandled bot cycle exception: RuntimeError: boom" == saved["last_error"]
    assert datetime.fromisoformat(saved["last_run_at"]).tzinfo == timezone.utc
    assert reconciled["exchange_reconciliation"]["status"] == "error_no_exchange_exposure"
    assert grid_service.calls == [
        {"reason": "cycle_exception", "force": True, "bot_ids": ["bot-1"]}
    ]


def test_persist_bot_cycle_exception_does_not_override_newer_stopped_status():
    storage = _FakeBotStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "stopped",
            "last_error": "manual stop",
        }
    )
    grid_service = _FakeGridBotService()

    runner._persist_bot_cycle_exception(
        storage,
        grid_service,
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        RuntimeError("boom"),
    )

    assert storage.saved == []
    assert grid_service.calls == []


def test_startup_reconciliation_targets_include_error_cleanup_and_pending_follow_up():
    targets = runner._startup_reconciliation_targets(
        [
            {"id": "bot-1", "status": "running"},
            {"id": "bot-2", "status": "error"},
            {"id": "bot-3", "status": "stop_cleanup_pending"},
            {
                "id": "bot-4",
                "status": "stopped",
                "ambiguous_execution_follow_up": {"pending": True},
            },
            {"id": "bot-5", "status": "stopped"},
        ]
    )

    assert [bot["id"] for bot in targets] == ["bot-1", "bot-2", "bot-3", "bot-4"]
