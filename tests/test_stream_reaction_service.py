import threading
import time

from services.stream_reaction_service import StreamReactionService


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=False, cancel_futures=True):
        return None


class _FakeStreamService:
    def has_fresh_private_state(self, topics=("execution", "order", "position")):
        return True


class _FakeBotStorage:
    def __init__(self, bots):
        self._bots = {bot["id"]: dict(bot) for bot in bots}

    def list_bots(self):
        return [dict(bot) for bot in self._bots.values()]

    def get_bot(self, bot_id):
        bot = self._bots.get(bot_id)
        return dict(bot) if bot else None


class _FakeGridBotService:
    def __init__(self):
        self.calls = []
        self.cycle_results = []

    def run_neutral_classic_fast_refill(self, bot, execution_events=None):
        self.calls.append(("neutral_classic_bybit", bot["id"], execution_events))
        return bot

    def run_bot_cycle(self, bot, fast_refill_tick=False):
        self.calls.append(("cycle", bot["id"], fast_refill_tick, dict(bot)))
        if self.cycle_results:
            return self.cycle_results.pop(0)
        return bot


def test_stream_reaction_dispatches_execution_to_fast_refill_mode():
    bot_storage = _FakeBotStorage(
        [
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "neutral_classic_bybit",
                "status": "running",
            }
        ]
    )
    grid_bot_service = _FakeGridBotService()
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=bot_storage,
        grid_bot_service=grid_bot_service,
    )
    service._executor = _ImmediateExecutor()

    service._dispatch_event(
        {
            "type": "execution",
            "payload": {
                "symbol": "BTCUSDT",
                "symbols": ["BTCUSDT"],
                "executions": [{"execId": "exec-1"}],
            },
        }
    )

    assert grid_bot_service.calls == [
        ("neutral_classic_bybit", "bot-1", [{"execId": "exec-1"}])
    ]


def test_stream_reaction_can_skip_fast_refill_poll_when_private_streams_are_fresh():
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=_FakeBotStorage([]),
        grid_bot_service=_FakeGridBotService(),
        fallback_poll_sec=5.0,
    )
    service._running = True
    service._thread = threading.current_thread()

    bot = {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"}
    assert service.should_poll_fast_refill(bot) is True

    service.note_fast_refill_poll(bot)

    assert service.should_poll_fast_refill(bot) is False


def test_stream_reaction_dispatches_confirmed_kline_to_fast_cycle():
    bot_storage = _FakeBotStorage(
        [
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
            }
        ]
    )
    grid_bot_service = _FakeGridBotService()
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=bot_storage,
        grid_bot_service=grid_bot_service,
    )
    service._executor = _ImmediateExecutor()

    service._dispatch_event(
        {
            "type": "kline",
            "payload": {
                "symbol": "BTCUSDT",
                "symbols": ["BTCUSDT"],
                "interval": "15",
                "confirmed": True,
            },
        }
    )

    assert grid_bot_service.calls == [("cycle", "bot-1", True, {"id": "bot-1", "symbol": "BTCUSDT", "mode": "long", "status": "running"})]


def test_stream_reaction_dispatches_orderbook_to_fast_cycle():
    bot_storage = _FakeBotStorage(
        [
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
            }
        ]
    )
    grid_bot_service = _FakeGridBotService()
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=bot_storage,
        grid_bot_service=grid_bot_service,
    )
    service._executor = _ImmediateExecutor()

    service._dispatch_event(
        {
            "type": "orderbook",
            "payload": {
                "symbol": "BTCUSDT",
                "symbols": ["BTCUSDT"],
                "mid_price": 50011.0,
            },
        }
    )

    call = grid_bot_service.calls[0]
    assert call[:3] == ("cycle", "bot-1", True)


def test_guarded_price_lane_uses_tighter_debounce():
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=_FakeBotStorage([]),
        grid_bot_service=_FakeGridBotService(),
    )

    guarded_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "_entry_gate_blocked": True,
    }
    regular_bot = {
        "id": "bot-2",
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "running",
    }

    guarded_debounce = service._get_debounce_sec(guarded_bot, "orderbook")
    regular_debounce = service._get_debounce_sec(regular_bot, "orderbook")

    assert guarded_debounce < regular_debounce


def test_guarded_price_lane_retries_after_cycle_lock_busy():
    bot_storage = _FakeBotStorage(
        [
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "_entry_gate_blocked": True,
            }
        ]
    )
    grid_bot_service = _FakeGridBotService()
    grid_bot_service.cycle_results = [
        {"id": "bot-1", "_cycle_lock_busy": True, "_cycle_lock_busy_reason": "bot_cycle_lock_busy"},
        {"id": "bot-1", "status": "running"},
    ]
    service = StreamReactionService(
        stream_service=_FakeStreamService(),
        bot_storage=bot_storage,
        grid_bot_service=grid_bot_service,
    )
    service._executor = _ImmediateExecutor()

    service._run_bot_reaction(
        "bot-1",
        "orderbook",
        {"symbol": "BTCUSDT", "received_at": 123.45},
    )

    assert "bot-1" in service._deferred_retries
    service._deferred_retries["bot-1"]["retry_at"] = time.time() - 1.0
    service._dispatch_due_retries()

    assert len(grid_bot_service.calls) == 2
    first_call = grid_bot_service.calls[0]
    second_call = grid_bot_service.calls[1]
    assert first_call[:3] == ("cycle", "bot-1", True)
    assert second_call[:3] == ("cycle", "bot-1", True)
    assert first_call[3]["_reevaluation_trigger_path"] == "stream_guarded_price_lane"
    assert first_call[3]["_blocked_guarded_fast_path_requested"] is True
    assert second_call[3]["_evaluation_deferred_reason"] == "bot_cycle_lock_busy"
