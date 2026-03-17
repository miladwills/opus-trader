from unittest.mock import Mock

from services.bot_manager_service import BotManagerService
from services.neutral_grid_service import NeutralGridService


class _StubStorage:
    def __init__(self, bot=None):
        self.bot = dict(bot or {})
        self.saved_bots = []

    def list_bots(self):
        return [dict(self.bot)] if self.bot else []

    def get_bot(self, bot_id):
        if self.bot.get("id") == bot_id:
            return dict(self.bot)
        return None

    def save_bot(self, bot):
        saved = dict(self.bot)
        saved.update(dict(bot))
        saved.setdefault("id", "bot-1")
        self.bot = saved
        self.saved_bots.append(dict(saved))
        return dict(saved)


def test_create_auto_pilot_skips_placeholder_instrument_lookup():
    client = Mock()
    storage = _StubStorage()
    service = BotManagerService(client=client, bot_storage=storage)

    saved = service.create_or_update_bot(
        {
            "auto_pilot": True,
            "investment": 100,
            "leverage": 3,
            "mode": "neutral",
        }
    )

    assert saved["symbol"] == "Auto-Pilot"
    client.get_instruments_info.assert_not_called()


def test_create_auto_pilot_neutral_classic_allows_missing_grid_bounds():
    client = Mock()
    storage = _StubStorage()
    service = BotManagerService(client=client, bot_storage=storage)

    saved = service.create_or_update_bot(
        {
            "auto_pilot": True,
            "investment": 100,
            "leverage": 3,
            "mode": "neutral_classic_bybit",
            "grid_count": 12,
        }
    )

    assert saved["symbol"] == "Auto-Pilot"
    assert saved["mode"] == "neutral_classic_bybit"
    assert saved["grid_lower_price"] == 0.0
    assert saved["grid_upper_price"] == 0.0
    assert saved["lower_price"] == 0.0
    assert saved["upper_price"] == 0.0
    assert saved["grid_levels_total"] == 12
    client.get_instruments_info.assert_not_called()


def test_start_auto_pilot_skips_placeholder_instrument_lookup():
    client = Mock()
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "auto_pilot": True,
            "mode": "neutral_classic_bybit",
            "status": "stopped",
            "investment": 100,
            "leverage": 3,
            "lower_price": 0,
            "upper_price": 0,
            "grid_lower_price": 5040.4,
            "grid_upper_price": 5246.1,
            "grid_levels_total": 10,
            "neutral_grid": {"slots": {"L00": {"state": "ENTRY"}}},
            "neutral_grid_initialized": True,
            "neutral_grid_last_reconcile_at": "2026-03-08T04:29:15+00:00",
            "levels_count": 11,
            "mid_index": 5,
            "entry_orders_open": 10,
            "active_long_slots": 5,
            "active_short_slots": 5,
            "current_price": 5143.8,
            "_entry_structure_buy_reason": "Resistance nearby",
            "_entry_structure_sell_reason": "Support nearby",
            "paper_trading": False,
            "trading_env": "mainnet",
        }
    )
    service = BotManagerService(client=client, bot_storage=storage)

    saved = service.start_bot("bot-1")

    assert saved["status"] == "running"
    assert saved["grid_lower_price"] is None
    assert saved["grid_upper_price"] is None
    assert saved["grid_levels_total"] is None
    assert saved["neutral_grid"] == {}
    assert saved["neutral_grid_initialized"] is False
    assert saved["neutral_grid_last_reconcile_at"] is None
    assert saved["levels_count"] is None
    assert saved["mid_index"] is None
    assert saved["entry_orders_open"] == 0
    assert saved["active_long_slots"] == 0
    assert saved["active_short_slots"] == 0
    assert saved["current_price"] == 0.0
    assert saved["_entry_structure_buy_reason"] is None
    assert saved["_entry_structure_sell_reason"] is None
    client.get_instruments_info.assert_not_called()


def test_stop_auto_pilot_placeholder_skips_order_cancel():
    client = Mock()
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "auto_pilot": True,
            "mode": "neutral_classic_bybit",
            "status": "running",
            "grid_lower_price": 5040.4,
            "grid_upper_price": 5246.1,
            "grid_levels_total": 10,
            "neutral_grid": {"slots": {"L00": {"state": "ENTRY"}}},
            "neutral_grid_initialized": True,
            "neutral_grid_last_reconcile_at": "2026-03-08T04:29:15+00:00",
            "levels_count": 11,
            "mid_index": 5,
            "entry_orders_open": 10,
            "active_long_slots": 5,
            "active_short_slots": 5,
            "current_price": 5143.8,
            "_entry_structure_buy_reason": "Resistance nearby",
            "_entry_structure_sell_reason": "Support nearby",
            "paper_trading": False,
            "trading_env": "mainnet",
        }
    )
    service = BotManagerService(client=client, bot_storage=storage)
    service._cancel_all_bot_orders = Mock(return_value={"success": True})

    saved = service.stop_bot("bot-1")

    assert saved["symbol"] == "Auto-Pilot"
    assert saved["grid_lower_price"] is None
    assert saved["grid_upper_price"] is None
    assert saved["grid_levels_total"] is None
    assert saved["neutral_grid"] == {}
    assert saved["neutral_grid_initialized"] is False
    assert saved["neutral_grid_last_reconcile_at"] is None
    assert saved["levels_count"] is None
    assert saved["mid_index"] is None
    assert saved["entry_orders_open"] == 0
    assert saved["active_long_slots"] == 0
    assert saved["active_short_slots"] == 0
    assert saved["current_price"] == 0.0
    assert saved["_entry_structure_buy_reason"] is None
    assert saved["_entry_structure_sell_reason"] is None
    service._cancel_all_bot_orders.assert_not_called()


def test_stop_auto_pilot_tradable_symbol_bumps_control_version_on_placeholder_reset():
    client = Mock()
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "SIGNUSDT",
            "auto_pilot": True,
            "mode": "scalp_pnl",
            "status": "running",
            "control_version": 1,
            "control_updated_at": "2026-03-08T08:31:00+00:00",
            "paper_trading": False,
            "trading_env": "mainnet",
        }
    )
    service = BotManagerService(client=client, bot_storage=storage)
    service._cancel_all_bot_orders = Mock(return_value={"success": True})

    saved = service.stop_bot("bot-1")

    assert saved["status"] == "stopped"
    assert saved["symbol"] == "Auto-Pilot"
    assert saved["control_version"] == 3
    assert storage.saved_bots[0]["symbol"] == "SIGNUSDT"
    assert storage.saved_bots[0]["control_version"] == 2
    assert storage.saved_bots[-1]["symbol"] == "Auto-Pilot"
    assert storage.saved_bots[-1]["control_version"] == 3


def test_neutral_grid_reconcile_skips_and_scrubs_auto_pilot_placeholder():
    storage = Mock()
    service = NeutralGridService(bot_storage=storage)
    client = Mock()
    bot = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "auto_pilot": True,
        "status": "running",
        "grid_lower_price": 1.9,
        "grid_upper_price": 2.1,
        "grid_levels_total": 8,
        "neutral_grid": {"slots": {"L00": {"state": "ENTRY"}}},
        "neutral_grid_initialized": True,
        "neutral_grid_last_reconcile_at": "2026-03-08T04:29:15+00:00",
        "levels_count": 9,
        "mid_index": 4,
        "current_price": 2.0,
    }

    updated = service.reconcile_on_start(bot, "Auto-Pilot", client)

    assert updated["status"] == "running"
    assert updated["grid_lower_price"] is None
    assert updated["grid_upper_price"] is None
    assert updated["grid_levels_total"] is None
    assert updated["neutral_grid"] == {}
    assert updated["neutral_grid_initialized"] is False
    assert updated["neutral_grid_last_reconcile_at"] is None
    assert updated["levels_count"] is None
    assert updated["mid_index"] is None
    assert updated["current_price"] == 0.0
    storage.save_bot.assert_called_once()
    client.get_position_mode.assert_not_called()
