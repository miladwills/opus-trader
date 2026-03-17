import runner
from runner import risk_check_all_bots, should_process_full_cycle_status


class _FakeBotStorage:
    def __init__(self, bots):
        self._bots = [dict(bot) for bot in bots]

    def list_bots(self):
        return [dict(bot) for bot in self._bots]


class _FakeGridBotService:
    def __init__(self, should_poll_fast_refill):
        self.stream_service = None
        self.should_poll_fast_refill_value = should_poll_fast_refill
        self.fast_refill_calls = []
        self.noted_bots = []
        self.upnl_checks = []

    def should_poll_fast_refill(self, bot):
        return self.should_poll_fast_refill_value

    def note_fast_refill_poll(self, bot):
        self.noted_bots.append(bot["id"])

    def run_neutral_classic_fast_refill(self, bot):
        self.fast_refill_calls.append(bot["id"])
        return dict(bot)

    def check_upnl_stoploss_fast(self, bot):
        self.upnl_checks.append(bot["id"])
        return {"action_taken": False}


def test_risk_check_skips_fast_refill_poll_when_stream_reactor_is_healthy():
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "neutral_classic_bybit",
        "status": "running",
        "upnl_stoploss_enabled": True,
    }
    grid_bot_service = _FakeGridBotService(should_poll_fast_refill=False)

    original_flag = runner.ENABLE_UPNL_STOPLOSS
    runner.ENABLE_UPNL_STOPLOSS = True
    try:
        risk_check_all_bots(_FakeBotStorage([bot]), grid_bot_service)
    finally:
        runner.ENABLE_UPNL_STOPLOSS = original_flag

    assert grid_bot_service.fast_refill_calls == []
    assert grid_bot_service.noted_bots == []
    assert grid_bot_service.upnl_checks == ["bot-1"]


def test_risk_check_runs_fast_refill_poll_when_stream_reactor_requests_fallback():
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "neutral_classic_bybit",
        "status": "running",
        "upnl_stoploss_enabled": True,
    }
    grid_bot_service = _FakeGridBotService(should_poll_fast_refill=True)

    original_flag = runner.ENABLE_UPNL_STOPLOSS
    runner.ENABLE_UPNL_STOPLOSS = True
    try:
        risk_check_all_bots(_FakeBotStorage([bot]), grid_bot_service)
    finally:
        runner.ENABLE_UPNL_STOPLOSS = original_flag

    assert grid_bot_service.fast_refill_calls == ["bot-1"]
    assert grid_bot_service.noted_bots == ["bot-1"]
    assert grid_bot_service.upnl_checks == ["bot-1"]


def test_full_cycle_status_helper_includes_pause_maintenance_states():
    assert should_process_full_cycle_status("running") is True
    assert should_process_full_cycle_status("paused") is True
    assert should_process_full_cycle_status("recovering") is True
    assert should_process_full_cycle_status("stop_cleanup_pending") is True
    assert should_process_full_cycle_status("stopped") is False
