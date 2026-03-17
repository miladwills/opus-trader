import base64
import importlib
import sys
import time
from pathlib import Path
from threading import Event


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
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()
    app_module.PNL_API_LAST_SYNC_AT = 0.0
    app_module.PNL_API_SYNC_THREAD = None
    return app_module


class _SlowSyncPnlService:
    def __init__(self):
        self.sync_started = Event()
        self.release_sync = Event()
        self.sync_calls = 0
        self.update_calls = 0

    def sync_closed_pnl(self):
        self.sync_calls += 1
        self.sync_started.set()
        self.release_sync.wait(timeout=2.0)

    def update_bots_realized_pnl(self):
        self.update_calls += 1

    def get_log(self, use_global_baseline=False):
        return [
            {
                "time": "2026-03-13T00:00:00+00:00",
                "realized_pnl": 1.25,
                "symbol": "BTCUSDT",
            }
        ]

    def get_today_stats(self, use_global_baseline=False):
        return {"net": 1.25, "wins": 1, "losses": 0}

    def get_trade_statistics(self, period="all", use_global_baseline=False):
        return {"period": period, "total_trades": 1, "net_pnl": 1.25, "wins": 1, "losses": 0}


def test_closed_pnl_api_sync_runs_in_background_without_blocking(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    pnl_service = _SlowSyncPnlService()
    app_module.pnl_service = pnl_service

    start = time.time()
    app_module._maybe_sync_closed_pnl_for_api()
    elapsed = time.time() - start

    assert elapsed < 0.2
    assert pnl_service.sync_started.wait(timeout=0.5)

    app_module._maybe_sync_closed_pnl_for_api()
    assert pnl_service.sync_calls == 1

    pnl_service.release_sync.set()
    worker = app_module.PNL_API_SYNC_THREAD
    assert worker is not None
    worker.join(timeout=1.0)
    assert pnl_service.update_calls == 1


def test_api_pnl_log_returns_local_payload_while_sync_runs(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    pnl_service = _SlowSyncPnlService()
    app_module.pnl_service = pnl_service

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    start = time.time()
    with flask_app.test_client() as client:
        response = client.get("/api/pnl/log", headers=_basic_auth_headers())
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 0.5
    payload = response.get_json()
    assert payload["today"]["net"] == 1.25
    assert len(payload["logs"]) == 1
    assert pnl_service.sync_started.wait(timeout=0.5)

    pnl_service.release_sync.set()
    worker = app_module.PNL_API_SYNC_THREAD
    assert worker is not None
    worker.join(timeout=1.0)


def test_api_pnl_stats_returns_local_payload_while_sync_runs(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    pnl_service = _SlowSyncPnlService()
    app_module.pnl_service = pnl_service

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    start = time.time()
    with flask_app.test_client() as client:
        response = client.get("/api/pnl/stats?period=all", headers=_basic_auth_headers())
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 0.5
    payload = response.get_json()
    assert payload["total_trades"] == 1
    assert payload["period"] == "all"
    assert pnl_service.sync_started.wait(timeout=0.5)

    pnl_service.release_sync.set()
    worker = app_module.PNL_API_SYNC_THREAD
    assert worker is not None
    worker.join(timeout=1.0)
