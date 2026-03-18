import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _basic_auth_headers(user="test-user", password="test-pass"):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


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
    app_module._sync_stream_subscriptions_once = lambda: None
    app_module._maybe_sync_closed_pnl_for_api = lambda force=False: None
    return app_module


def test_neutral_scan_legacy_route_alias_serves_default_results(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    expected_results = [
        {
            "symbol": "BTCUSDT",
            "neutral_score": 78.0,
            "recommended_mode": "neutral",
            "volume_24h_usdt": 125000000.0,
        }
    ]
    observed = {}

    def _capture_cached_or_compute(key, ttl_sec, compute_fn, timeout_sec=None):
        observed["key"] = key
        observed["ttl_sec"] = ttl_sec
        observed["timeout_sec"] = timeout_sec
        return compute_fn()

    app_module._get_cached_or_compute = _capture_cached_or_compute
    def _scan(symbols):
        observed["symbols"] = list(symbols)
        return expected_results

    app_module.neutral_scanner = SimpleNamespace(scan=_scan)

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/neutral-scan", headers=_basic_auth_headers())

    assert response.status_code == 200
    assert response.get_json() == {"results": expected_results}
    assert observed["key"] == "neutral_scan"
    assert observed["ttl_sec"] == 30.0
    assert observed["timeout_sec"] == 20.0
    assert observed["symbols"][0] == "BTCUSDT"
    assert len(observed["symbols"]) >= 30
