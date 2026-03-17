import base64
import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _basic_auth_headers(user="test-user", password="test-pass"):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _reload_config_module():
    if "config.config" in sys.modules:
        return importlib.reload(sys.modules["config.config"])
    return importlib.import_module("config.config")


def _load_app_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _reload_config_module()
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_load_core_config_does_not_require_dashboard_auth(monkeypatch):
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "mainnet-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "mainnet-secret")
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASS", raising=False)

    cfg_module = _reload_config_module()
    monkeypatch.setattr(cfg_module, "BASIC_AUTH_USER", "")
    monkeypatch.setattr(cfg_module, "BASIC_AUTH_PASS", "")

    core_cfg = cfg_module.load_core_config()

    assert core_cfg["api_key"] == "mainnet-key"
    assert core_cfg["api_secret"] == "mainnet-secret"
    with pytest.raises(ValueError):
        cfg_module.load_dashboard_config()


def test_importing_app_does_not_create_client_or_stream(monkeypatch, tmp_path):
    import services.bybit_client as bybit_client_module
    import services.bybit_stream_service as stream_module

    calls = {"client": 0, "stream": 0}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            calls["client"] += 1

    class DummyStream:
        def __init__(self, *args, **kwargs):
            calls["stream"] += 1

        def start(self):
            raise AssertionError("stream start should not run during import")

    monkeypatch.setattr(bybit_client_module, "BybitClient", DummyClient)
    monkeypatch.setattr(stream_module, "BybitStreamService", DummyStream)
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASS", raising=False)
    monkeypatch.delenv("BYBIT_STREAM_OWNER", raising=False)

    app_module = _load_app_module(monkeypatch, tmp_path)

    assert app_module.APP_RUNTIME_INITIALIZED is False
    assert calls == {"client": 0, "stream": 0}


def test_localhost_requests_no_longer_bypass_basic_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("BASIC_AUTH_USER", "test-user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "test-pass")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "test-secret")
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "0")
    monkeypatch.delenv("DASH_LOCALHOST_BYPASS", raising=False)

    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.APP_RUNTIME_INITIALIZED = True
    app_module.cfg = {"env_label": "Test"}

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

    assert response.status_code == 401


def test_trusted_proxy_allowlist_uses_forwarded_client_ip(monkeypatch, tmp_path):
    monkeypatch.setenv("BASIC_AUTH_USER", "test-user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "test-pass")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "test-secret")
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "0")
    monkeypatch.setenv("DASH_ALLOW_IPS", "198.51.100.9")
    monkeypatch.setenv("DASH_TRUSTED_PROXY_HOPS", "1")

    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.APP_RUNTIME_INITIALIZED = True
    app_module.cfg = {"env_label": "Test"}

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    allowed_headers = {
        **_basic_auth_headers(),
        "X-Forwarded-For": "198.51.100.9",
    }
    denied_headers = {
        **_basic_auth_headers(),
        "X-Forwarded-For": "203.0.113.7",
    }

    with flask_app.test_client() as client:
        allowed_response = client.get(
            "/",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=allowed_headers,
        )
        denied_response = client.get(
            "/",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=denied_headers,
        )

    assert allowed_response.status_code == 200
    assert denied_response.status_code == 403


def test_app_streams_are_disabled_by_default_when_runner_owns_streams(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "1")
    monkeypatch.delenv("BYBIT_STREAM_OWNER", raising=False)

    app_module = _load_app_module(monkeypatch, tmp_path)

    calls = {"stream": 0}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.stream_service = None
            self.order_router = None

        def set_order_router(self, router):
            self.order_router = router
            return self

        def set_stream_service(self, stream):
            self.stream_service = stream
            return self

    class DummyOrderRouter:
        pass

    class DummyStream:
        def __init__(self, *args, **kwargs):
            calls["stream"] += 1

        def start(self):
            calls["stream"] += 100

    monkeypatch.setattr(app_module, "BybitClient", DummyClient)
    monkeypatch.setattr(app_module, "OrderRouterService", DummyOrderRouter)
    monkeypatch.setattr(app_module, "BybitStreamService", DummyStream)

    runtime_client, runtime_order_router, runtime_stream_service = (
        app_module._create_app_client_and_stream(
            {
                "api_key": "test-key",
                "api_secret": "test-secret",
                "base_url": "https://api.bybit.com",
            }
        )
    )

    assert runtime_client.order_router is runtime_order_router
    assert runtime_client.stream_service is None
    assert runtime_stream_service is None
    assert calls["stream"] == 0


def test_app_does_not_start_local_stream_in_both_mode_when_runner_bridge_is_fresh(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "1")
    monkeypatch.setenv("BYBIT_STREAM_OWNER", "both")

    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module.runtime_snapshot_bridge,
        "read_market_snapshot",
        lambda: {
            "stale_data": False,
            "snapshot_owner": "runner",
            "snapshot_fresh": True,
        },
    )
    monkeypatch.setattr(
        app_module.runtime_snapshot_bridge,
        "read_section",
        lambda section: {
            "stale_data": False,
            "snapshot_owner": "runner",
        },
    )

    calls = {"stream": 0}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.stream_service = None
            self.order_router = None

        def set_order_router(self, router):
            self.order_router = router
            return self

        def set_stream_service(self, stream):
            self.stream_service = stream
            return self

    class DummyOrderRouter:
        pass

    class DummyStream:
        def __init__(self, *args, **kwargs):
            calls["stream"] += 1

        def start(self):
            calls["stream"] += 100

    monkeypatch.setattr(app_module, "BybitClient", DummyClient)
    monkeypatch.setattr(app_module, "OrderRouterService", DummyOrderRouter)
    monkeypatch.setattr(app_module, "BybitStreamService", DummyStream)

    runtime_client, _, runtime_stream_service = app_module._create_app_client_and_stream(
        {
            "api_key": "test-key",
            "api_secret": "test-secret",
            "base_url": "https://api.bybit.com",
        }
    )

    assert runtime_client.stream_service is None
    assert runtime_stream_service is None
    assert calls["stream"] == 0


def test_backtest_api_requires_basic_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("BASIC_AUTH_USER", "test-user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "test-pass")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "test-secret")
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "0")

    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.APP_RUNTIME_INITIALIZED = True

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/backtest",
            json={},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert response.status_code == 401
