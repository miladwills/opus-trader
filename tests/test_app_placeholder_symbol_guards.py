import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


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
    app_module.initialize_app_runtime()
    return app_module


def _basic_auth_headers(user="test-user", password="test-pass"):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_api_predictions_skips_auto_pilot_placeholder(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bots = [
        {"id": "bot-placeholder", "symbol": "Auto-Pilot", "status": "running"},
        {"id": "bot-real", "symbol": "BTCUSDT", "status": "running", "mode": "long"},
    ]
    predict_calls = []

    prediction_result = SimpleNamespace(
        direction="LONG",
        confidence=77,
        score=42.0,
        signals=[],
        pattern_signals={},
        divergence_signals={},
        sr_levels={},
        trend_structure={},
        timeframe_alignment={},
    )

    app_module.bot_storage = SimpleNamespace(list_bots=lambda: bots)
    app_module.price_prediction_service = SimpleNamespace(
        predict=lambda symbol, timeframe="15": predict_calls.append((symbol, timeframe))
        or prediction_result
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/predictions",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert predict_calls == [("BTCUSDT", "15")]
    assert payload["predictions"] == [
        {
            "bot_id": "bot-real",
            "symbol": "BTCUSDT",
            "mode": "long",
            "direction": "LONG",
            "confidence": 77,
            "score": 42.0,
            "signals": [],
            "patterns": [],
            "divergence": None,
            "sr_levels": {"support": None, "resistance": None},
            "trend_structure": "unknown",
            "mtf_alignment": "MIXED",
            "auto_direction": False,
            "direction_score": None,
            "direction_signals": None,
            "funding_signal": None,
            "funding_score": None,
            "orderbook_signal": None,
            "orderbook_score": None,
            "orderbook_imbalance": None,
            "liquidation_signal": None,
            "liquidation_score": None,
            "session_signal": None,
            "session_name": None,
            "mean_reversion_signal": None,
            "mean_reversion_score": None,
            "mean_reversion_deviation": None,
            "oi_signal": None,
            "oi_score": None,
            "whale_signal": None,
            "whale_score": None,
            "whale_bid_walls": None,
            "whale_ask_walls": None,
            "whale_reason": None,
        }
    ]


def test_api_bot_grid_skips_exchange_calls_for_placeholder_symbol(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bot = {
        "id": "bot-placeholder",
        "symbol": "Auto-Pilot",
        "status": "running",
        "lower_price": 10.0,
        "upper_price": 20.0,
        "grid_count": 2,
        "current_price": 15.0,
        "mode": "neutral",
        "range_mode": "dynamic",
    }

    def _unexpected_call(*args, **kwargs):
        raise AssertionError("exchange call should be skipped for placeholder symbol")

    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: bot)
    app_module.client = SimpleNamespace(
        get_tickers=_unexpected_call,
        get_open_orders=_unexpected_call,
        get_positions=_unexpected_call,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/bots/bot-placeholder/grid",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["symbol"] == "Auto-Pilot"
    assert payload["current_price"] == 15.0
    assert payload["lower_bound"] == 10.0
    assert payload["upper_bound"] == 20.0
    assert payload["grid_count"] == 2
    assert payload["grid_levels"] == [10.0, 15.0, 20.0]
    assert payload["orders"] == []
    assert payload["position"] is None
    assert payload["mode"] == "neutral"
    assert payload["range_mode"] == "dynamic"
    assert payload["placeholder_symbol"] is True
    assert payload["lower_price"] == 10.0
    assert payload["upper_price"] == 20.0
    assert payload["range_key_family"] == "price"


def test_api_price_rejects_auto_pilot_placeholder(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.client = Mock()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/price?symbol=Auto-Pilot",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "tradeable symbol is required"
    app_module.client.get_tickers.assert_not_called()
    app_module.client.get_instruments_info.assert_not_called()


def test_api_symbol_info_rejects_auto_pilot_placeholder(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.client = Mock()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/symbol/info?symbol=Auto-Pilot",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "tradeable symbol is required"
    app_module.client.get_instruments_info.assert_not_called()
    app_module.client.get_tickers.assert_not_called()


def test_api_ai_range_rejects_auto_pilot_placeholder(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.client = Mock()
    app_module.indicator_service = Mock()
    app_module.grid_bot_service = Mock()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/ai-range/Auto-Pilot?mode=neutral&range_mode=fixed",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "tradeable symbol is required"
    app_module.client.get_tickers.assert_not_called()
    app_module.indicator_service.compute_indicators.assert_not_called()
    app_module.grid_bot_service.get_auto_direction_analysis.assert_not_called()
