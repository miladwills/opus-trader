#!/usr/bin/env python3
import os
import sys
import tempfile
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.bybit_client import BybitClient
from services.grid_bot_service import GridBotService
from services.lock_service import acquire_process_lock


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _set_instrument_cache(service, symbol: str) -> None:
    service._instrument_cache = {
        symbol: {
            "min_order_qty": 0.01,
            "qty_step": 0.01,
            "tick_size": 0.01,
            "min_notional_value": 5.0,
        }
    }


def acquire_runner_lock(lock_path: str):
    try:
        lock_fd = acquire_process_lock(lock_path)
        if not lock_fd:
            return None

        lock_fd.seek(0)
        lock_fd.truncate()
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except Exception:
        return None


def check_emergency_close_calls_create_order() -> None:
    client = BybitClient(api_key="k", api_secret="s", base_url="http://example.com")
    called = {"create_order": 0}

    def fake_create_order(**_kwargs):
        called["create_order"] += 1
        return {"success": True}

    client.create_order = fake_create_order
    client.normalize_qty = lambda _symbol, _qty, log_skip=True: 1.0
    client._get_qty_filters = lambda _symbol: {
        "min_qty": 0.01,
        "qty_step": 0.01,
        "max_qty": None,
    }
    client.get_position_mode = lambda symbol=None: {"success": True, "mode": "one_way"}

    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type(
        "DummyStorage",
        (),
        {"save_bot": lambda _self, _bot: None, "get_bot": lambda _self, _id: None},
    )()
    service._get_usdt_available_balance = lambda: 0.0
    _set_instrument_cache(service, "BTCUSDT")

    import time as _t

    bot = {"_position_mode": "one_way", "_position_mode_ts": _t.time()}
    ok = service._emergency_partial_close(
        bot=bot,
        symbol="BTCUSDT",
        position_size=10.0,
        position_side="Buy",
        pct_to_liq=5.0,
    )
    _assert(ok is True, "Emergency partial close did not return success")
    _assert(called["create_order"] == 1, "Emergency close did not call create_order")


def check_qty_normalization() -> None:
    client = BybitClient(api_key="k", api_secret="s", base_url="http://example.com")
    client._get_qty_filters = lambda _symbol: {
        "min_qty": 0.01,
        "qty_step": 0.01,
        "max_qty": None,
    }

    below_min = client.normalize_qty("BTCUSDT", 0.005)
    _assert(below_min is None, "normalize_qty should return None below minQty")

    rounded = client.normalize_qty("BTCUSDT", 0.019)
    _assert(
        rounded is not None and rounded > 0, "normalize_qty should return positive qty"
    )


def check_trend_reversal_close_hard_fail() -> None:
    client = BybitClient(api_key="k", api_secret="s", base_url="http://example.com")
    client._get_qty_filters = lambda _symbol: {
        "min_qty": 0.01,
        "qty_step": 0.01,
        "max_qty": None,
    }
    client.get_positions = lambda: {
        "success": True,
        "data": {
            "list": [{"symbol": "BTCUSDT", "side": "Buy", "size": 1, "markPrice": 100}]
        },
    }
    client.create_order = lambda **_kwargs: {"success": False, "error": "close_failed"}

    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type(
        "DummyStorage",
        (),
        {"save_bot": lambda _self, _bot: None, "get_bot": lambda _self, _id: None},
    )()
    _set_instrument_cache(service, "BTCUSDT")

    import time as _t2

    bot = {
        "id": "bot1",
        "symbol": "BTCUSDT",
        "status": "running",
        "_position_mode": "one_way",
        "_position_mode_ts": _t2.time(),
    }
    try:
        service._close_position_or_hard_fail(bot, "BTCUSDT", "trend_reversal")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected RuntimeError for close failure")

    _assert(bot.get("status") == "error", "Bot status should be error on close failure")
    _assert(
        bot.get("error_code") == "CLOSE_FAILED", "Bot error_code should be CLOSE_FAILED"
    )
    _assert(
        bot.get("_block_opening_orders") is True,
        "Bot should block opening orders on close failure",
    )
    _assert(
        "CLOSE_FAILED trend_reversal" in (bot.get("last_error") or ""),
        "Expected CLOSE_FAILED in last_error",
    )


def check_tp_hit_close_hard_fail() -> None:
    class DummyClient:
        def cancel_all_orders(self, _symbol):
            return {"success": True}

        def get_positions(self):
            return {
                "success": True,
                "data": {"list": [{"symbol": "BTCUSDT", "side": "Buy", "size": 1}]},
            }

        def get_position_mode(self, symbol=None):
            return {"success": True, "mode": "one_way"}

        def get_qty_filters(self, _symbol):
            return {"min_qty": 0.01, "qty_step": 0.01, "max_qty": None}

        def normalize_qty(self, _symbol, _qty, log_skip=True):
            return 1.0

        def create_order(self, **_kwargs):
            return {"success": False, "error": "close_failed"}

    service = GridBotService.__new__(GridBotService)
    service.client = DummyClient()
    service.bot_storage = type(
        "DummyStorage",
        (),
        {"save_bot": lambda _self, _bot: None, "get_bot": lambda _self, _id: None},
    )()
    _set_instrument_cache(service, "BTCUSDT")

    import time as _t3

    bot = {
        "id": "bot_tp",
        "symbol": "BTCUSDT",
        "status": "running",
        "_position_mode": "one_way",
        "_position_mode_ts": _t3.time(),
    }
    try:
        service._close_bot_symbol(bot, hard_fail=True, fail_reason="tp_hit")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected RuntimeError for TP hit close failure")

    _assert(
        bot.get("status") == "error", "Bot status should be error on TP close failure"
    )
    _assert(
        bot.get("error_code") == "CLOSE_FAILED", "Bot error_code should be CLOSE_FAILED"
    )
    _assert(
        bot.get("_block_opening_orders") is True,
        "Bot should block opening orders on TP close failure",
    )
    _assert(
        "CLOSE_FAILED tp_hit" in (bot.get("last_error") or ""),
        "Expected CLOSE_FAILED in last_error",
    )


def check_partial_tp_close_hard_fail() -> None:
    client = BybitClient(api_key="k", api_secret="s", base_url="http://example.com")

    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type(
        "DummyStorage", (), {"save_bot": lambda _self, _bot: None}
    )()
    _set_instrument_cache(service, "BTCUSDT")

    import time as _t4

    bot = {
        "id": "bot_partial",
        "symbol": "BTCUSDT",
        "status": "running",
        "_position_mode": "one_way",
        "_position_mode_ts": _t4.time(),
    }
    try:
        service._hard_fail_close(bot, "BTCUSDT", "partial_tp", "close_failed")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected RuntimeError for partial TP close failure")

    _assert(
        bot.get("status") == "error",
        "Bot status should be error on partial TP close failure",
    )
    _assert(
        bot.get("error_code") == "CLOSE_FAILED", "Bot error_code should be CLOSE_FAILED"
    )
    _assert(
        bot.get("_block_opening_orders") is True,
        "Bot should block opening orders on partial TP close failure",
    )
    _assert(
        "CLOSE_FAILED partial_tp" in (bot.get("last_error") or ""),
        "Expected CLOSE_FAILED in last_error",
    )


def check_skip_small_qty_and_close_fallback() -> None:
    client = BybitClient(api_key="k", api_secret="s", base_url="http://example.com")
    client._get_qty_filters = lambda _symbol: {
        "min_qty": 1.0,
        "qty_step": 1.0,
        "max_qty": None,
    }

    called = {"create_order": []}

    def fake_create_order(**_kwargs):
        called["create_order"].append(_kwargs)
        return {"success": True, "retCode": 0}

    client.create_order = fake_create_order
    client.get_position_mode = lambda symbol=None: {"success": True, "mode": "one_way"}

    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type(
        "DummyStorage", (), {"save_bot": lambda _self, _bot: None}
    )()
    _set_instrument_cache(service, "WIFUSDT")

    import time as _t5

    bot = {
        "id": "bot_low_qty",
        "symbol": "WIFUSDT",
        "status": "running",
        "_position_mode": "one_way",
        "_position_mode_ts": _t5.time(),
    }

    skip_result = service._create_order_checked(
        bot=bot,
        symbol="WIFUSDT",
        side="Buy",
        qty=0.5,
        order_type="Limit",
        price=0.1,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id=f"close_{bot_id}_{int(time.time() * 1000)}",
    )
    _assert(
        skip_result.get("skipped") is True, "Expected skip for below-min open order"
    )
    _assert(
        len(called["create_order"]) == 0, "No API call should be made for below-min qty"
    )

    fallback_result = service._create_order_checked(
        bot=bot,
        symbol="WIFUSDT",
        side="Sell",
        qty=0.5,
        order_type="Market",
        price=0.1,
        reduce_only=True,
        time_in_force="GTC",
        order_link_id=f"close_{bot_id}_{int(time.time() * 1000)}",
        full_close_qty=3.0,
    )
    _assert(
        fallback_result.get("success") is True,
        "Expected full close fallback to succeed",
    )
    _assert(
        len(called["create_order"]) == 1,
        "Expected a single create_order call for fallback close",
    )
    _assert(
        called["create_order"][0].get("qty") == 3.0,
        "Expected full close qty to be used",
    )
    _assert(
        all(call.get("qty", 0) > 0 for call in called["create_order"]),
        "No API call should be made with qty=0",
    )
    _assert(
        bot.get("skipped_small_qty_count", 0) >= 1,
        "Expected skipped_small_qty_count to increment",
    )


def check_runner_lock() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = os.path.join(tmpdir, "runner.lock")
        first = acquire_runner_lock(lock_path=lock_path)
        try:
            _assert(first is not None, "First lock acquisition should succeed")
            second = acquire_runner_lock(lock_path=lock_path)
            _assert(
                second is None, "Second lock acquisition should fail when already held"
            )
        finally:
            if first is not None:
                first.close()


def check_mainnet_missing_keys_fails() -> None:
    env = os.environ.copy()
    env["BYBIT_MAINNET_API_KEY"] = ""
    env["BYBIT_MAINNET_API_SECRET"] = ""
    env["BYBIT_API_KEY"] = ""
    env["BYBIT_API_SECRET"] = ""
    env["BYBIT_ACTIVE_ENV"] = "mainnet"
    env["DEFAULT_TRADING_ENV"] = "mainnet"
    env["BASIC_AUTH_USER"] = "user"
    env["BASIC_AUTH_PASS"] = "pass"

    cmd = [
        sys.executable,
        "-c",
        "from config.config import load_config; load_config()",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    _assert(proc.returncode != 0, "load_config should fail without mainnet credentials")


def main() -> None:
    check_emergency_close_calls_create_order()
    check_qty_normalization()
    check_trend_reversal_close_hard_fail()
    check_tp_hit_close_hard_fail()
    check_partial_tp_close_hard_fail()
    check_skip_small_qty_and_close_fallback()
    check_runner_lock()
    check_mainnet_missing_keys_fails()
    print("Self-checks passed.")


if __name__ == "__main__":
    main()
