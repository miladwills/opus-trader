import base64
import importlib
import sys
import time
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
    app_module._maybe_sync_closed_pnl_for_api = lambda: None
    app_module.DASHBOARD_SNAPSHOT_WAIT_SEC = 0.01
    app_module.DASHBOARD_SNAPSHOT_REFRESH_TTL_SEC = 0.0
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()
    return app_module


def test_api_summary_returns_local_fallback_when_bridge_unavailable(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    # Bridge returns nothing usable — summary must NOT call _build_summary_payload (Bybit)
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: None,
    )
    app_module._build_summary_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_summary_payload from critical path")
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/summary", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale_data"] is True
    assert payload["error"] == "summary_bridge_unavailable"
    assert payload["account"]["equity"] == 0.0


def test_api_positions_fresh_request_prefers_runner_bridge_payload(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setenv("BYBIT_STREAM_OWNER", "runner")
    app_module.position_service = object()
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: (
            {
                "positions": [{"symbol": "BTCUSDT", "side": "Buy"}],
                "summary": {"total_positions": 1},
                "snapshot_source": "runner_runtime_snapshot",
                "stale_data": True,
                "error": "positions_stale",
            }
            if section_name == "positions"
            else None
        )
    )
    app_module._build_positions_payload = lambda: (_ for _ in ()).throw(
        AssertionError("direct positions refresh should not run")
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/positions?fresh=1", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["positions"][0]["symbol"] == "BTCUSDT"
    assert payload["fresh_request_degraded"] is True
    assert payload["fresh_request_reason"] == "positions_runner_bridge_preferred"


def test_api_summary_fresh_request_prefers_runner_bridge_payload(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setenv("BYBIT_STREAM_OWNER", "runner")
    app_module.account_service = object()
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: (
            {
                "account": {"equity": 42.0},
                "positions_summary": {"total_positions": 0},
                "today_pnl": {"net": 0.0},
                "snapshot_source": "runner_runtime_snapshot",
                "stale_data": True,
                "error": "summary_stale",
            }
            if section_name == "summary"
            else None
        )
    )
    app_module._build_summary_payload = lambda: (_ for _ in ()).throw(
        AssertionError("direct summary refresh should not run")
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/summary?fresh=1", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["account"]["equity"] == 42.0
    assert payload["fresh_request_degraded"] is True
    assert payload["fresh_request_reason"] == "summary_runner_bridge_preferred"


def test_api_bots_runtime_returns_empty_degraded_fallback_when_bridge_stale(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    # Bridge returns nothing usable — stale path must NOT trigger heavy builder
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: None,
    )
    # Heavy builder must NOT be called — stale bridge goes to degraded fallback
    app_module._build_runtime_bots_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_runtime_bots_payload when bridge stale")
    )
    # bot_storage.list_bots() must NOT be called
    app_module.bot_storage = SimpleNamespace(
        list_bots=lambda: (_ for _ in ()).throw(
            AssertionError("must not call bot_storage.list_bots() on critical path")
        )
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bots/runtime", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale_data"] is True
    assert "bridge" in payload.get("error", "")
    assert payload["bots"] == []
    assert payload["runtime_state_source"] == "critical_path_empty_fallback"


def test_runtime_bots_fallback_preserves_cached_payload_shape(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE["bots_runtime"] = {
            "ts": time.time() - 5.0,
            "value": {
                "bots": [{"id": "cached-bot", "symbol": "ETHUSDT"}],
                "error": None,
                "stale_data": False,
            },
        }

    payload = app_module._build_runtime_bots_fallback("bots_runtime_timeout")

    assert payload["stale_data"] is True
    assert payload["error"] == "bots_runtime_timeout"
    assert isinstance(payload["bots"], list)
    assert payload["bots"][0]["id"] == "cached-bot"


def test_api_bot_config_returns_canonical_persisted_bot_for_editor_hydration(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    canonical_bot = {
        "id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "short",
        "trailing_sl_enabled": False,
        "quick_profit_enabled": False,
        "settings_version": 9,
    }

    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: dict(canonical_bot) if bot_id == "bot-1" else None,
        list_bots=lambda: [],
    )
    app_module.bot_status_service = SimpleNamespace(
        get_runtime_bots=lambda: [
            {
                "id": "bot-1",
                "symbol": "ETHUSDT",
                "mode": "short",
                "trailing_sl_enabled": True,
                "quick_profit_enabled": True,
                "settings_version": 8,
            }
        ]
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bots/bot-1", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bot"]["id"] == canonical_bot["id"]
    assert payload["bot"]["symbol"] == canonical_bot["symbol"]
    assert payload["bot"]["mode"] == canonical_bot["mode"]
    assert payload["bot"]["trailing_sl_enabled"] is False
    assert payload["bot"]["quick_profit_enabled"] is False
    assert payload["bot"]["settings_version"] == canonical_bot["settings_version"]
    assert payload["bot"]["range_mode"] == "fixed"


def test_api_bot_config_returns_404_for_missing_bot(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bots/missing-bot", headers=_basic_auth_headers())

    assert response.status_code == 404
    assert response.get_json()["error"] == "bot not found"


def test_api_stream_events_falls_back_to_snapshot_poll_when_stream_service_disabled(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.stream_service = None
    app_module._build_dashboard_stream_payload = lambda reason, fast=False: {
        "reason": reason,
        "summary": {"account": {"equity": 10.0}},
        "positions": {"positions": []},
        "bots": [],
    }

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/stream/events",
            headers=_basic_auth_headers(),
            buffered=False,
        )
        try:
            chunks = response.response
            first_chunk = next(chunks).decode("utf-8")
            second_chunk = next(chunks).decode("utf-8")
        finally:
            response.close()

    assert response.status_code == 200
    # First event is an immediate heartbeat (fast SSE open)
    assert "event: heartbeat" in first_chunk
    # Second event is the dashboard snapshot poll
    assert "event: dashboard" in second_chunk
    assert '"reason":"snapshot_poll"' in second_chunk


def test_api_stream_events_prefers_snapshot_poll_when_bridge_is_canonical(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.stream_service = SimpleNamespace(
        get_latest_event_seq=lambda: (_ for _ in ()).throw(AssertionError("local stream unused")),
        get_dashboard_snapshot=lambda symbols: (_ for _ in ()).throw(AssertionError("local stream unused")),
    )
    app_module._prefer_runtime_snapshot_bridge = lambda: True
    app_module._build_dashboard_stream_payload = lambda reason, fast=False: {
        "reason": reason,
        "summary": {"account": {"equity": 10.0}},
        "positions": {"positions": []},
        "bots": [],
    }

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/stream/events",
            headers=_basic_auth_headers(),
            buffered=False,
        )
        try:
            chunks = response.response
            first_chunk = next(chunks).decode("utf-8")
            second_chunk = next(chunks).decode("utf-8")
        finally:
            response.close()

    assert response.status_code == 200
    # First event is an immediate heartbeat (fast SSE open)
    assert "event: heartbeat" in first_chunk
    # Second event is the dashboard snapshot poll
    assert "event: dashboard" in second_chunk
    assert '"reason":"snapshot_poll"' in second_chunk


def test_live_dashboard_bundle_does_not_keep_fresh_probe_hot_path():
    template = (PROJECT_ROOT / "templates" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert "js/app_lf.min.js" in template

    live_bundle = (PROJECT_ROOT / "static" / "js" / "app_lf.min.js").read_text(
        encoding="utf-8"
    )
    assert "refreshPositions(true).catch(() => {});" not in live_bundle
    assert "refreshSummary(true).catch(() => {});" not in live_bundle


def test_build_dashboard_stream_payload_exposes_section_snapshot_meta(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    market_payload = {
        "health": {"transport": "stream"},
        "snapshot_published_at": 101.0,
        "snapshot_produced_at": 101.5,
        "snapshot_age_sec": 0.5,
        "snapshot_fresh": True,
        "snapshot_source": "runner_stream_snapshot",
        "snapshot_reason": "ticker",
        "snapshot_owner": "runner",
        "snapshot_epoch": 9,
        "stale_data": False,
        "error": None,
    }
    summary_payload = {
        "account": {"equity": 10.0},
        "snapshot_published_at": 102.0,
        "snapshot_produced_at": 102.5,
        "snapshot_age_sec": 0.4,
        "snapshot_fresh": True,
        "snapshot_source": "runner_runtime_snapshot",
        "snapshot_reason": "timer",
        "snapshot_owner": "runner",
        "snapshot_epoch": 10,
        "stale_data": False,
        "error": None,
    }
    positions_payload = {
        "positions": [],
        "snapshot_published_at": 103.0,
        "snapshot_produced_at": 103.5,
        "snapshot_age_sec": 0.3,
        "snapshot_fresh": True,
        "snapshot_source": "runner_runtime_snapshot",
        "snapshot_reason": "timer",
        "snapshot_owner": "runner",
        "snapshot_epoch": 11,
        "stale_data": False,
        "error": None,
    }
    bots_payload = {
        "bots": [{"id": "bot-1", "setup_ready_status": "ready"}],
        "snapshot_published_at": 104.0,
        "snapshot_produced_at": 104.5,
        "snapshot_age_sec": 0.2,
        "snapshot_fresh": True,
        "snapshot_source": "runner_runtime_snapshot",
        "snapshot_reason": "ticker",
        "snapshot_owner": "runner",
        "snapshot_epoch": 12,
        "stale_data": False,
        "error": None,
    }

    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_market_snapshot=lambda: dict(market_payload),
    )
    app_module._get_summary_snapshot = lambda: dict(summary_payload)
    app_module._get_positions_snapshot = lambda: dict(positions_payload)
    app_module._get_runtime_bots_snapshot = lambda: dict(bots_payload)
    app_module._is_bridge_producer_alive = lambda: True

    payload = app_module._build_dashboard_stream_payload("snapshot_poll")

    assert payload["market_meta"]["snapshot_source"] == "runner_stream_snapshot"
    assert payload["summary_meta"]["snapshot_epoch"] == 10
    assert payload["positions_meta"]["snapshot_age_sec"] == 0.3
    assert payload["bots_meta"]["snapshot_reason"] == "ticker"


def test_prefer_runtime_snapshot_bridge_requires_fresh_bots_runtime(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setenv("BYBIT_STREAM_OWNER", "runner")
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_market_snapshot=lambda: {
            "snapshot_owner": "runner",
            "snapshot_fresh": True,
            "stale_data": False,
        },
        read_section=lambda section_name, max_age_sec=None: (
            {
                "snapshot_owner": "runner",
                "snapshot_fresh": False,
                "stale_data": True,
            }
            if section_name == "bots_runtime"
            else None
        ),
    )

    assert app_module._prefer_runtime_snapshot_bridge() is False


def test_get_runtime_bots_snapshot_returns_degraded_when_bridge_stale(
    monkeypatch,
    tmp_path,
):
    """When bridge is stale, the heavy builder is NOT called. Degraded
    fallback is returned instead — no bot_storage.list_bots() contention."""
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: (
            {
                "bots": [{"id": "stale-bot"}],
                "snapshot_source": "runner_runtime_snapshot",
                "snapshot_fresh": False,
                "stale_data": True,
                "error": "bots_runtime_stale",
            }
            if section_name == "bots_runtime"
            else None
        )
    )
    app_module._is_bridge_producer_alive = lambda: True
    # Heavy builder must NOT be called when bridge is stale
    app_module._build_runtime_bots_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_runtime_bots_payload when bridge stale")
    )
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()

    payload = app_module._get_runtime_bots_snapshot()

    # Stale bridge data is returned (watchdog resolves bridge vs degraded fallback)
    assert payload["stale_data"] is True
    assert isinstance(payload["bots"], list)


def test_build_dashboard_stream_payload_uses_degraded_when_bridge_stale(
    monkeypatch,
    tmp_path,
):
    """When bots_runtime bridge is stale, degraded fallback is used instead
    of triggering the heavy builder that hits bot_storage."""
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_dashboard_payload=lambda reason: {
            "reason": reason,
            "summary": {"account": {"equity": 10.0}},
            "positions": {"positions": []},
            "bots": [{"id": "stale-bot"}],
            "market": {"snapshot_owner": "runner", "snapshot_fresh": True, "stale_data": False},
        },
        read_section=lambda section_name, max_age_sec=None: (
            {
                "bots": [{"id": "stale-bot"}],
                "snapshot_source": "runner_runtime_snapshot",
                "snapshot_fresh": False,
                "stale_data": True,
                "error": "bots_runtime_stale",
            }
            if section_name == "bots_runtime"
            else None
        ),
        read_market_snapshot=lambda: {"snapshot_owner": "runner", "snapshot_fresh": True, "stale_data": False},
    )
    app_module._is_bridge_producer_alive = lambda: True
    # Heavy builder must NOT be called when bridge is stale
    app_module._build_runtime_bots_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_runtime_bots_payload when bridge stale")
    )
    app_module._get_summary_snapshot = lambda: {
        "account": {"equity": 10.0},
        "stale_data": False,
        "error": None,
    }
    app_module._get_positions_snapshot = lambda: {
        "positions": [],
        "stale_data": False,
        "error": None,
    }
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()

    payload = app_module._build_dashboard_stream_payload("snapshot_poll")

    # Stale bridge data used — heavy builder not invoked
    assert isinstance(payload["bots"], list)
    assert payload["bots_meta"]["stale_data"] is True


def test_build_dashboard_stream_payload_does_not_use_raw_dashboard_bridge_bundle(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_dashboard_payload=lambda reason: (_ for _ in ()).throw(
            AssertionError("raw dashboard bridge bundle should not be used")
        ),
        read_market_snapshot=lambda: {"snapshot_source": "runner_stream_snapshot"},
    )
    app_module._get_summary_snapshot = lambda: {
        "account": {"equity": 25.0},
        "snapshot_epoch": 10,
        "stale_data": False,
        "error": None,
    }
    app_module._get_positions_snapshot = lambda: {
        "positions": [{"symbol": "BTCUSDT"}],
        "snapshot_epoch": 11,
        "stale_data": False,
        "error": None,
    }
    app_module._get_runtime_bots_snapshot = lambda: {
        "bots": [{"id": "bot-1"}],
        "snapshot_epoch": 12,
        "stale_data": False,
        "error": None,
    }
    app_module._is_bridge_producer_alive = lambda: True

    payload = app_module._build_dashboard_stream_payload("snapshot_poll")

    assert payload["summary"]["account"]["equity"] == 25.0
    assert payload["positions"]["positions"][0]["symbol"] == "BTCUSDT"
    assert payload["bots"][0]["id"] == "bot-1"


def test_api_dashboard_bootstrap_recovery_never_calls_bybit_builders(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    stale_section = {
        "snapshot_fresh": False,
        "stale_data": True,
        "error": "bridge_stale",
    }
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: dict(stale_section),
        read_market_snapshot=lambda: None,
    )
    # Bybit-calling builders must NEVER be invoked from bootstrap recovery
    app_module._build_summary_payload = lambda: (_ for _ in ()).throw(
        AssertionError("bootstrap must not call _build_summary_payload")
    )
    app_module._build_positions_payload = lambda account=None: (_ for _ in ()).throw(
        AssertionError("bootstrap must not call _build_positions_payload")
    )
    app_module._build_runtime_bots_light_payload = lambda: (_ for _ in ()).throw(
        AssertionError("bootstrap must not call _build_runtime_bots_light_payload")
    )

    client = app_module.app.test_client()
    response = client.get("/api/dashboard/bootstrap", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    # Recovery returns degraded fallback data (local only, no Bybit)
    assert payload["summary"]["stale_data"] is True
    assert payload["positions"]["stale_data"] is True
    assert payload["summary"]["error"] == "bootstrap_recovery"
    assert payload["positions"]["error"] == "bootstrap_recovery"


def test_recover_bootstrap_uses_local_only_fallbacks_and_completes_fast(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    # Bybit-calling builders must not be invoked — recovery uses local fallbacks
    app_module._build_summary_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_summary_payload")
    )
    app_module._build_positions_payload = lambda account=None: (_ for _ in ()).throw(
        AssertionError("must not call _build_positions_payload")
    )
    app_module._build_runtime_bots_light_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_runtime_bots_light_payload")
    )

    started_at = time.monotonic()
    results, section_elapsed_ms = app_module._recover_bootstrap_dashboard_sections(
        timeout_sec=3.0
    )
    elapsed = time.monotonic() - started_at

    # Local-only fallbacks complete near-instantly
    assert elapsed < 0.5
    assert section_elapsed_ms["summary"] < 100.0
    assert section_elapsed_ms["positions"] < 100.0
    assert section_elapsed_ms["bots"] < 100.0
    assert results["summary"]["error"] == "bootstrap_recovery"
    assert results["positions"]["error"] == "bootstrap_recovery"
    assert results["bots"]["error"] == "bootstrap_recovery"
    assert results["summary"]["stale_data"] is True
    assert results["positions"]["stale_data"] is True
    assert results["bots"]["stale_data"] is True


def test_recover_bootstrap_bypasses_shared_snapshot_executor(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    class ExplodingExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError("bootstrap recovery must not use shared executor")

    monkeypatch.setattr(
        app_module,
        "DASHBOARD_SNAPSHOT_EXECUTOR",
        ExplodingExecutor(),
        raising=False,
    )

    results, section_elapsed_ms = app_module._recover_bootstrap_dashboard_sections(
        timeout_sec=3.0
    )

    assert results["summary"]["error"] == "bootstrap_recovery"
    assert results["positions"]["error"] == "bootstrap_recovery"
    assert results["bots"]["error"] == "bootstrap_recovery"
    assert section_elapsed_ms["summary"] >= 0.0


def test_bootstrap_recovery_returns_degraded_when_bridge_stale_and_cache_empty(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module._is_bridge_producer_alive = lambda: True

    def stale_bridge(section_name, max_age_sec=None):
        if section_name in {"summary", "positions", "bots_runtime", "bots_runtime_light"}:
            return {
                "snapshot_fresh": False,
                "stale_data": True,
                "error": f"{section_name}_stale",
            }
        return None

    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=stale_bridge,
        read_market_snapshot=lambda: None,
    )

    # Ensure dashboard cache is empty
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()

    # Bybit-calling builders must not be invoked
    app_module._build_summary_payload = lambda: (_ for _ in ()).throw(
        AssertionError("must not call _build_summary_payload")
    )
    app_module._build_positions_payload = lambda account=None: (_ for _ in ()).throw(
        AssertionError("must not call _build_positions_payload")
    )

    client = app_module.app.test_client()
    response = client.get("/api/dashboard/bootstrap", headers=_basic_auth_headers())
    assert response.status_code == 200

    payload = response.get_json()
    # All sections return degraded fallback (local only)
    assert payload["summary"]["stale_data"] is True
    assert payload["positions"]["stale_data"] is True
    assert payload["summary"]["error"] == "bootstrap_recovery"
    assert payload["positions"]["error"] == "bootstrap_recovery"


def test_api_bots_runtime_exposes_response_and_integrity_latency_fields(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.runtime_snapshot_bridge = SimpleNamespace(
        read_section=lambda section_name, max_age_sec=None: (
            {
                "bots": [{"id": "bot-1", "setup_ready_status": "armed"}],
                "snapshot_published_at": time.time() - 1.0,
                "snapshot_produced_at": time.time() - 1.0,
                "snapshot_source": "runner_runtime_snapshot",
                "runtime_publish_ts": time.time() - 2.0,
                "runtime_publish_at": "2026-03-13T00:00:00+00:00",
                "runtime_snapshot_age_ms": 2000.0,
                "bridge_age_ms": 1000.0,
                "stale_data": False,
                "error": None,
                "runtime_integrity": {
                    "status": "healthy",
                    "runtime_integrity_state": "healthy",
                    "rebuilt_from_app": False,
                    "held_last_good": False,
                    "startup_pending": False,
                    "startup_stalled": False,
                },
                "readiness_latency": {
                    "dominant_segment": "market_to_eval_start_ms",
                },
            }
            if section_name == "bots_runtime"
            else None
        ),
    )
    app_module._is_bridge_producer_alive = lambda: True

    client = app_module.app.test_client()
    response = client.get("/api/bots/runtime", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["response_generated_at"] is not None
    assert payload["response_build_ms"] is not None
    assert payload["response_age_ms"] is not None
    assert payload["bridge_age_ms"] is not None
    assert payload["runtime_snapshot_age_ms"] is not None
    assert payload["runtime_integrity_state"] is not None
    assert payload["rebuilt_from_app"] is False


def test_build_watchdog_hub_payload_includes_readiness_latency_summary(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.watchdog_hub_service = SimpleNamespace(
        build_snapshot=lambda **kwargs: {"overview": {}, "active_issues": [], "recent_events": []}
    )

    payload = app_module._build_watchdog_hub_payload(
        bots_payload={
            "bots": [],
            "stale_data": False,
            "runtime_integrity": {"status": "healthy"},
            "readiness_latency": {
                "dominant_segment": "eval_to_runtime_publish_ms",
                "paths": {"live_runtime": {"bot_count": 1}},
            },
        }
    )

    assert payload["readiness_latency"]["dominant_segment"] == "eval_to_runtime_publish_ms"
    assert payload["readiness_latency"]["paths"]["live_runtime"]["bot_count"] == 1
