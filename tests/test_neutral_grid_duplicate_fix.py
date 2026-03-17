import threading
from unittest.mock import Mock, patch

from services.grid_bot_service import GridBotService
from services.neutral_grid_service import NeutralGridService


class _FakeBotStorage:
    def __init__(self, bot=None):
        self._bot = bot

    def get_bot(self, bot_id):
        return self._bot

    def save_bot(self, bot):
        self._bot = bot
        return bot

    def save_runtime_bot(self, bot):
        self._bot = bot
        return bot


def _make_fast_refill_bot(slot_count=5, last_reconcile_ts=0.0):
    slots = {
        f"S{i:02d}": {
            "state": "ENTRY",
        }
        for i in range(slot_count)
    }
    return {
        "id": "29c36d6e-d066-4450-a320-63dcd88fec51",
        "mode": "neutral_classic_bybit",
        "status": "running",
        "symbol": "BTCUSDT",
        "neutral_grid_initialized": True,
        "neutral_grid": {
            "slots": slots,
            "_last_reconcile_ts": last_reconcile_ts,
        },
    }


def _build_fast_refill_service(bot, neutral_grid_service):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.stream_service = None
    service.bot_storage = _FakeBotStorage(bot)
    service.neutral_grid_service = neutral_grid_service
    service._bot_run_locks = {}
    service._bot_run_locks_guard = threading.Lock()
    return service


def _make_neutral_grid_bot():
    return {
        "id": "29c36d6e-d066-4450-a320-63dcd88fec51",
        "status": "running",
        "symbol": "BTCUSDT",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_lower_price": 10.0,
        "grid_upper_price": 12.0,
        "grid_levels_total": 2,
        "grid_count": 2,
        "neutral_grid": {
            "levels": [10.0, 11.0, 12.0],
            "lower_price": 10.0,
            "upper_price": 12.0,
            "total_levels": 2,
            "mid_index": 1,
            "slots": {
                "L00": {
                    "leg": "LONG",
                    "level": 0,
                    "state": "ENTRY",
                    "entry_price": 10.0,
                    "exit_price": 11.0,
                    "order_id": None,
                    "order_link_id": None,
                },
                "S02": {
                    "leg": "SHORT",
                    "level": 2,
                    "state": "ENTRY",
                    "entry_price": 12.0,
                    "exit_price": 11.0,
                    "order_id": None,
                    "order_link_id": None,
                },
            },
            "seq": 0,
            "processed_exec_ids": [],
            "slot_width": 2,
        },
    }


def _build_neutral_grid_service(open_orders):
    service = NeutralGridService(
        bot_storage=_FakeBotStorage(),
        adaptive_config_service=Mock(),
    )
    service.ensure_hedge_mode = Mock(side_effect=lambda bot, symbol, client: bot)
    service._update_status_fields = Mock()
    service._get_instrument_info = Mock(
        return_value={
            "min_order_qty": 0.1,
            "qty_step": 0.1,
            "tick_size": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_usdt_available_balance = Mock(return_value=100.0)
    service._compute_per_order_qty = Mock(return_value=1.0)
    service._get_open_orders = Mock(return_value=open_orders)
    service._get_position_sizes = Mock(return_value={1: 0.0, 2: 0.0})
    return service


def test_fast_refill_cooldown_skips_recent_over_count():
    bot = _make_fast_refill_bot(last_reconcile_ts=98.0)
    neutral_grid_service = Mock()
    neutral_grid_service.process_execution_events.side_effect = (
        lambda bot, symbol, client, execution_events=None: bot
    )
    neutral_grid_service.count_bot_open_orders.return_value = 7
    neutral_grid_service.reconcile_on_start.return_value = bot
    service = _build_fast_refill_service(bot, neutral_grid_service)

    with patch("services.grid_bot_service.time.time", return_value=100.0):
        result = service.run_neutral_classic_fast_refill(bot)

    assert result is bot
    neutral_grid_service.reconcile_on_start.assert_not_called()
    assert bot["neutral_grid"]["_last_reconcile_ts"] == 98.0


def test_fast_refill_reconciles_on_under_count_always():
    bot = _make_fast_refill_bot(last_reconcile_ts=99.0)
    neutral_grid_service = Mock()
    neutral_grid_service.process_execution_events.side_effect = (
        lambda bot, symbol, client, execution_events=None: bot
    )
    neutral_grid_service.count_bot_open_orders.return_value = 2
    neutral_grid_service.reconcile_on_start.return_value = bot
    service = _build_fast_refill_service(bot, neutral_grid_service)

    with patch("services.grid_bot_service.time.time", return_value=100.0):
        result = service.run_neutral_classic_fast_refill(bot)

    assert result is bot
    neutral_grid_service.reconcile_on_start.assert_called_once_with(
        bot,
        "BTCUSDT",
        service.client,
    )
    assert bot["neutral_grid"]["_last_reconcile_ts"] == 100.0


def test_fast_refill_reconciles_on_large_over_count():
    bot = _make_fast_refill_bot(last_reconcile_ts=99.0)
    neutral_grid_service = Mock()
    neutral_grid_service.process_execution_events.side_effect = (
        lambda bot, symbol, client, execution_events=None: bot
    )
    neutral_grid_service.count_bot_open_orders.return_value = 10
    neutral_grid_service.reconcile_on_start.return_value = bot
    service = _build_fast_refill_service(bot, neutral_grid_service)

    with patch("services.grid_bot_service.time.time", return_value=100.0):
        result = service.run_neutral_classic_fast_refill(bot)

    assert result is bot
    neutral_grid_service.reconcile_on_start.assert_called_once_with(
        bot,
        "BTCUSDT",
        service.client,
    )
    assert bot["neutral_grid"]["_last_reconcile_ts"] == 100.0


def test_duplicate_cancelled_slots_skip_duplicate_replacement():
    bot = _make_neutral_grid_bot()
    service = _build_neutral_grid_service(
        open_orders=[
            {
                "orderId": "order-1",
                "orderLinkId": "bv2:29c36d6ed0664450:000001:L00:E",
                "price": "10",
            },
            {
                "orderId": "order-2",
                "orderLinkId": "bv2:29c36d6ed0664450:000002:L00:E",
                "price": "10",
            },
        ]
    )
    service._place_slot_order = Mock(return_value={"success": True})
    client = Mock()
    client._get_now_ts.return_value = 1000.0

    with patch("services.neutral_grid_service.time.sleep"):
        result = service.reconcile_on_start(bot, "BTCUSDT", client)

    assert result["neutral_grid"]["slots"]["L00"]["order_id"] == "order-1"
    assert result["neutral_grid"]["slots"]["L00"]["order_link_id"] == (
        "bv2:29c36d6ed0664450:000001:L00:E"
    )
    client.cancel_order.assert_called_once_with(
        symbol="BTCUSDT",
        order_id="order-2",
        order_link_id="bv2:29c36d6ed0664450:000002:L00:E",
    )
    placed_slots = [call.kwargs["slot_id"] for call in service._place_slot_order.call_args_list]
    assert placed_slots == ["S02"]


def test_duplicate_cancel_delay():
    bot = _make_neutral_grid_bot()
    service = _build_neutral_grid_service(
        open_orders=[
            {
                "orderId": "order-1",
                "orderLinkId": "bv2:29c36d6ed0664450:000001:L00:E",
                "price": "10",
            },
            {
                "orderId": "order-2",
                "orderLinkId": "bv2:29c36d6ed0664450:000002:L00:E",
                "price": "10",
            },
        ]
    )
    service._place_slot_order = Mock(return_value={"success": True})
    client = Mock()
    client._get_now_ts.return_value = 1000.0

    with patch("services.neutral_grid_service.time.sleep") as sleep_mock:
        service.reconcile_on_start(bot, "BTCUSDT", client)

    sleep_mock.assert_called_once_with(0.5)
