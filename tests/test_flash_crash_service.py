from services.flash_crash_service import FlashCrashService


class _FakeStorage:
    def __init__(self, bots):
        self._bots = [dict(bot) for bot in bots]

    def list_bots(self):
        return [dict(bot) for bot in self._bots]

    def save_bot(self, bot):
        for index, existing in enumerate(self._bots):
            if existing.get("id") == bot.get("id"):
                self._bots[index] = dict(bot)
                break
        else:
            self._bots.append(dict(bot))
        return dict(bot)


def test_trigger_flash_crash_uses_list_bots_storage_interface():
    storage = _FakeStorage(
        [
            {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
            {"id": "bot-2", "symbol": "ETHUSDT", "status": "paused"},
        ]
    )
    service = FlashCrashService(bot_storage=storage)
    saved_states = []
    service.save_flash_crash_state = lambda state: saved_states.append(dict(state)) or True

    result = service.trigger_flash_crash(
        symbol="BTCUSDT",
        price_change_pct=-0.05,
        direction="down",
    )

    assert result["success"] is True
    assert result["paused_bots"] == ["bot-1"]
    assert storage.list_bots()[0]["status"] == "flash_crash_paused"
    assert saved_states[0]["flash_crash_active"] is True


def test_resume_after_normalization_uses_list_bots_storage_interface():
    storage = _FakeStorage(
        [
            {"id": "bot-1", "symbol": "BTCUSDT", "status": "flash_crash_paused"},
            {"id": "bot-2", "symbol": "ETHUSDT", "status": "running"},
        ]
    )
    service = FlashCrashService(bot_storage=storage)
    service.get_flash_crash_state = lambda: {"flash_crash_active": True}
    saved_states = []
    service.save_flash_crash_state = lambda state: saved_states.append(dict(state)) or True

    result = service.resume_after_normalization()

    assert result["success"] is True
    assert result["resumed_bots"] == ["bot-1"]
    assert storage.list_bots()[0]["status"] == "running"
    assert saved_states[0]["flash_crash_active"] is False
