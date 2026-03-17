import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_app_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BASIC_AUTH_USER", "test-user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "test-pass")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "test-secret")
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "0")

    if "config.config" in sys.modules:
        importlib.reload(sys.modules["config.config"])

    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")
    app_module.APP_RUNTIME_INITIALIZED = True
    return app_module


def test_build_positions_payload_attributes_unique_paused_bot(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.position_service = SimpleNamespace(
        get_positions=lambda skip_cache=True: {
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": 1.5,
                    "entry_price": 100.0,
                    "mark_price": 101.0,
                    "unrealized_pnl": 3.5,
                }
            ],
            "summary": {"total_positions": 1},
            "error": None,
        }
    )
    app_module.account_service = SimpleNamespace(
        get_overview=lambda: {
            "equity": 250.0,
            "available_balance": 150.0,
            "realized_pnl": 4.0,
            "unrealized_pnl": 3.5,
        }
    )
    app_module.bot_storage = SimpleNamespace(
        list_bots=lambda: [
            {
                "id": "bot-paused",
                "symbol": "BTCUSDT",
                "status": "paused",
                "mode": "long",
                "range_mode": "dynamic",
                "tp_pct": 0.05,
                "auto_stop": 5.0,
                "auto_stop_target_usdt": 120.0,
            }
        ]
    )
    app_module._sync_stream_subscriptions_once = lambda: None

    payload = app_module._build_positions_payload()

    position = payload["positions"][0]
    assert position["bot_id"] == "bot-paused"
    assert position["bot_mode"] == "long"
    assert position["bot_count_for_symbol"] == 1
