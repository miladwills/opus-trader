import json
import sys
import time
from pathlib import Path
from types import MethodType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from services.runtime_snapshot_bridge_service import (
    RuntimeSnapshotBridgeService,
    extract_market_symbol_bot,
)


def test_read_section_exposes_snapshot_ownership_metadata(tmp_path):
    bridge_path = tmp_path / "runtime_snapshot_bridge.json"
    bridge_path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {
                    "producer": "runner",
                    "producer_pid": 4321,
                    "produced_at": 1000.0,
                    "stream_owner": "runner",
                    "snapshot_epoch": 7,
                },
                "sections": {
                    "market": {
                        "payload": {"prices": {}, "stale_data": False},
                        "published_at": time.time(),
                        "source": "runner_stream_snapshot",
                        "reason": "timer",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    bridge = RuntimeSnapshotBridgeService(file_path=str(bridge_path))

    section = bridge.read_section("market")

    assert section is not None
    assert section["snapshot_owner"] == "runner"
    assert section["snapshot_producer"] == "runner"
    assert section["snapshot_producer_pid"] == 4321
    assert section["snapshot_epoch"] == 7
    assert section["snapshot_fresh"] is True


def test_read_section_marks_stale_snapshot_as_not_fresh(tmp_path):
    bridge_path = tmp_path / "runtime_snapshot_bridge.json"
    published_at = time.time() - 20
    bridge_path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {
                    "producer": "runner",
                    "producer_pid": 4321,
                    "produced_at": published_at,
                    "stream_owner": "runner",
                    "snapshot_epoch": 8,
                },
                "sections": {
                    "positions": {
                        "payload": {"positions": []},
                        "published_at": published_at,
                        "source": "runner_runtime_snapshot",
                        "reason": "timer",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    bridge = RuntimeSnapshotBridgeService(file_path=str(bridge_path))

    section = bridge.read_section("positions", max_age_sec=1.0)

    assert section is not None
    assert section["stale_data"] is True
    assert section["snapshot_fresh"] is False
    assert section["snapshot_owner"] == "runner"


def test_read_section_exposes_bridge_and_runtime_snapshot_ages(tmp_path):
    bridge_path = tmp_path / "runtime_snapshot_bridge.json"
    published_at = time.time() - 2
    runtime_publish_ts = time.time() - 5
    bridge_path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {
                    "producer": "runner",
                    "producer_pid": 4321,
                    "produced_at": published_at,
                    "stream_owner": "runner",
                    "snapshot_epoch": 9,
                },
                "sections": {
                    "bots_runtime": {
                        "payload": {
                            "bots": [],
                            "runtime_publish_ts": runtime_publish_ts,
                            "runtime_publish_at": "2026-03-13T00:00:00+00:00",
                        },
                        "published_at": published_at,
                        "source": "runner_runtime_snapshot",
                        "reason": "ticker",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    bridge = RuntimeSnapshotBridgeService(file_path=str(bridge_path))

    section = bridge.read_section("bots_runtime")

    assert section is not None
    assert section["bridge_age_ms"] >= 1500
    assert section["runtime_snapshot_age_ms"] >= 4500


def test_capture_read_diagnostics_tracks_repeated_section_reads(tmp_path):
    bridge_path = tmp_path / "runtime_snapshot_bridge.json"
    bridge_path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {
                    "producer": "runner",
                    "producer_pid": 1234,
                    "produced_at": time.time(),
                    "stream_owner": "runner",
                    "snapshot_epoch": 1,
                },
                "sections": {
                    "summary": {
                        "payload": {"account": {}, "positions_summary": {}},
                        "published_at": time.time(),
                        "source": "runner_runtime_snapshot",
                        "reason": "timer",
                    },
                    "positions": {
                        "payload": {"positions": []},
                        "published_at": time.time(),
                        "source": "runner_runtime_snapshot",
                        "reason": "timer",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    bridge = RuntimeSnapshotBridgeService(file_path=str(bridge_path))

    with bridge.capture_read_diagnostics("test") as diag:
        bridge.read_section("summary")
        bridge.read_section("summary")
        bridge.read_section("positions")

    assert diag["operation_counts"]["read_snapshot"] == 3
    assert diag["section_call_counts"]["summary"] == 2
    assert diag["section_call_counts"]["positions"] == 1
    assert diag["top_repeated_section"]["name"] == "summary"
    assert diag["phase_ms"]["snapshot_file_read_ms"] >= 0.0
    assert diag["phase_ms"]["snapshot_json_parse_ms"] >= 0.0


def test_extract_section_from_shared_snapshot_reads_file_once(tmp_path):
    bridge_path = tmp_path / "runtime_snapshot_bridge.json"
    bridge_path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {
                    "producer": "runner",
                    "producer_pid": 1234,
                    "produced_at": time.time(),
                    "stream_owner": "runner",
                    "snapshot_epoch": 2,
                },
                "sections": {
                    "summary": {
                        "payload": {"account": {}, "positions_summary": {}},
                        "published_at": time.time(),
                        "source": "runner_runtime_snapshot",
                        "reason": "timer",
                    },
                    "positions": {
                        "payload": {"positions": []},
                        "published_at": time.time(),
                        "source": "runner_runtime_snapshot",
                        "reason": "timer",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    bridge = RuntimeSnapshotBridgeService(file_path=str(bridge_path))

    with bridge.capture_read_diagnostics("shared") as diag:
        snapshot = bridge.read_snapshot(copy_payload=False)
        bridge.extract_section_from_snapshot(snapshot, "summary")
        bridge.extract_section_from_snapshot(snapshot, "positions")

    assert diag["operation_counts"]["read_snapshot"] == 1
    assert diag["operation_counts"]["read_snapshot:shared_reference"] == 1
    assert diag["operation_counts"]["extract_section_from_snapshot"] == 2
    assert diag["phase_ms"]["snapshot_file_read_ms"] >= 0.0
    assert "snapshot_payload_copy_ms" not in diag["phase_ms"]


def test_bots_runtime_rebuild_interval_is_tightened_for_ticker_events(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))

    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"orderbook"}) == 0.35
    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"ticker"}) == 0.5
    assert bridge._resolve_rebuild_interval_sec("market", {"ticker"}) == 0.5
    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"timer"}) == 2.0


def test_publish_records_skipped_reused_section_diagnostics(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))
    now = time.time()
    bridge._last_snapshot = {
        "version": 1,
        "meta": {
            "producer": "runner",
            "producer_pid": 1,
            "produced_at": now - 1,
            "stream_owner": "runner",
        },
        "sections": {
            "market": {
                "payload": {"prices": {}, "stale_data": False},
                "published_at": now - 0.1,
                "source": "runner_stream_snapshot",
                "reason": "ticker",
            }
        },
    }
    bridge._last_publish_at["market"] = now

    writes = []

    def fake_write_snapshot(self, payload):
        writes.append(json.loads(json.dumps(payload)))

    bridge._write_snapshot = MethodType(fake_write_snapshot, bridge)
    bridge._publish(reason="ticker", event_types={"ticker"}, force=False)

    assert len(writes) == 2
    assert "publish_pass" not in (writes[0].get("meta") or {})
    publish_pass = writes[-1]["meta"]["publish_pass"]
    market_diag = publish_pass["sections"]["market"]
    assert market_diag["planned_rebuild"] is False
    assert market_diag["skipped"] is True
    assert market_diag["reused_previous"] is True
    assert market_diag["start_at"] is None
    assert market_diag["upstream_dependency"]
    assert publish_pass["write_events"][0]["stage"] == "final"
    assert publish_pass["final_write_requested_at"] is not None
    assert publish_pass["final_write_completed_at"] is not None
    assert publish_pass["serialization_ms"] == 0.0
    assert publish_pass["write_file_ms"] == 0.0
    assert publish_pass["total_bytes"] == 0
    assert publish_pass["long_pole_section"] in {
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    }
    assert publish_pass["max_section_age_at_final_ms"] is not None
    assert "market" in publish_pass["section_ages_at_final_ms"]


def test_publish_writes_core_sections_before_bots_runtime_light(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))
    bridge._cached_bots_runtime_payload = {
        "bots": [],
        "error": None,
        "stale_data": False,
        "runtime_state_source": "runner_runtime_bots",
        "bots_scope": "full",
    }
    bridge._last_snapshot = {
        "version": 1,
        "meta": {
            "producer": "runner",
            "producer_pid": 1,
            "produced_at": time.time() - 30,
            "stream_owner": "runner",
        },
        "sections": {
            "bots_runtime_light": {
                "payload": {
                    "bots": [{"id": "stale-light"}],
                    "stale_data": True,
                    "error": "old_light",
                    "bots_scope": "light",
                },
                "published_at": time.time() - 30,
                "source": "runner_runtime_snapshot_light",
                "reason": "timer",
            }
        },
    }

    bridge._build_meta = MethodType(
        lambda self, now_ts: {
            "producer": "runner",
            "producer_pid": 1,
            "produced_at": now_ts,
            "stream_owner": "runner",
            "stream_health": {},
        },
        bridge,
    )
    bridge._collect_market_symbols = MethodType(lambda self: [], bridge)
    bridge._build_market_health = MethodType(lambda self, now_ts: {}, bridge)
    bridge._build_market_payload = MethodType(
        lambda self, *, symbols, health: {
            "health": health,
            "prices": {},
            "symbols": list(symbols or []),
            "stale_data": False,
        },
        bridge,
    )
    bridge._build_open_orders_payload = MethodType(
        lambda self: {"symbols": {}, "stale_data": False, "error": None},
        bridge,
    )
    bridge._get_cached_account_snapshot = MethodType(
        lambda self, *, force: {
            "equity": 100.0,
            "available_balance": 80.0,
            "funding_balance": 0.0,
            "realized_pnl": 1.0,
            "unrealized_pnl": 0.0,
            "error": None,
        },
        bridge,
    )
    bridge._build_positions_payload = MethodType(
        lambda self, account_payload=None: {
            "positions": [],
            "summary": {
                "total_positions": 0,
                "longs": 0,
                "shorts": 0,
                "total_unrealized_pnl": 0.0,
            },
            "stale_data": False,
            "error": None,
        },
        bridge,
    )
    bridge._build_summary_payload = MethodType(
        lambda self, *, account_payload, positions_payload: {
            "account": dict(account_payload),
            "positions_summary": dict(positions_payload.get("summary") or {}),
            "stale_data": False,
        },
        bridge,
    )

    writes = []

    def fake_write_snapshot(self, payload):
        writes.append(json.loads(json.dumps(payload)))

    def fake_build_bots_runtime_light_payload(self):
        assert len(writes) == 1
        first = writes[0]
        assert first["meta"]["publish_pass"]["write_events"][0]["stage"] == "pre_bots_runtime_light"
        assert "summary" in first["sections"]
        assert first["sections"]["bots_runtime_light"]["payload"]["error"] == "old_light"
        return {
            "bots": [{"id": "fresh-light"}],
            "error": None,
            "stale_data": False,
            "runtime_state_source": "runner_runtime_bots_light",
            "runtime_publish_ts": time.time(),
            "bots_scope": "light",
        }

    bridge._write_snapshot = MethodType(fake_write_snapshot, bridge)
    bridge._build_bots_runtime_light_payload = MethodType(
        fake_build_bots_runtime_light_payload,
        bridge,
    )

    bridge._publish(reason="timer", event_types={"timer"}, force=True)

    assert len(writes) == 3
    first_pass = writes[0]["meta"]["publish_pass"]
    assert "publish_pass" not in (writes[1].get("meta") or {})
    final_pass = writes[2]["meta"]["publish_pass"]
    assert first_pass["write_events"][0]["stage"] == "pre_bots_runtime_light"
    assert final_pass["write_events"][-1]["stage"] == "final"
    assert final_pass["sections"]["bots_runtime_light"]["success"] is True
    assert final_pass["sections"]["bots_runtime_light"]["elapsed_ms"] is not None
    assert final_pass["sections"]["bots_runtime_light"]["upstream_dependency"]
    assert final_pass["final_write_completed_at"] is not None
    assert "serialization_ms" in final_pass
    assert "write_file_ms" in final_pass
    assert "total_bytes" in final_pass
    assert final_pass["long_pole_section"] in {
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    }
    assert final_pass["max_section_age_at_final_ms"] is not None
    assert set(final_pass["section_ages_at_final_ms"]) == {
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    }
    assert writes[2]["sections"]["bots_runtime_light"]["payload"]["bots"][0]["id"] == "fresh-light"


def test_publish_persists_finalized_publish_pass_fields_to_snapshot_file(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))
    bridge._cached_bots_runtime_payload = {
        "bots": [],
        "error": None,
        "stale_data": False,
        "runtime_state_source": "runner_runtime_bots",
        "bots_scope": "full",
    }
    bridge._build_meta = MethodType(
        lambda self, now_ts: {
            "producer": "runner",
            "producer_pid": 1,
            "produced_at": now_ts,
            "stream_owner": "runner",
            "stream_health": {},
        },
        bridge,
    )
    bridge._collect_market_symbols = MethodType(lambda self: ["BTCUSDT"], bridge)
    bridge._build_market_health = MethodType(lambda self, now_ts: {}, bridge)
    bridge._build_market_payload = MethodType(
        lambda self, *, symbols, health: {
            "health": dict(health),
            "prices": {"BTCUSDT": {"lastPrice": "100.0"}},
            "symbols": list(symbols or []),
            "stale_data": False,
        },
        bridge,
    )
    bridge._build_open_orders_payload = MethodType(
        lambda self: {
            "symbols": {
                "BTCUSDT": {
                    "open_order_count": 2,
                    "reduce_only_count": 1,
                    "entry_order_count": 1,
                }
            },
            "stale_data": False,
            "error": None,
        },
        bridge,
    )
    bridge._get_cached_account_snapshot = MethodType(
        lambda self, *, force: {
            "equity": 100.0,
            "available_balance": 80.0,
            "funding_balance": 0.0,
            "realized_pnl": 1.0,
            "unrealized_pnl": 0.0,
            "error": None,
        },
        bridge,
    )
    bridge._build_positions_payload = MethodType(
        lambda self, account_payload=None: {
            "positions": [{"symbol": "BTCUSDT"}],
            "summary": {
                "total_positions": 1,
                "longs": 1,
                "shorts": 0,
                "total_unrealized_pnl": 0.0,
            },
            "stale_data": False,
            "error": None,
        },
        bridge,
    )
    bridge._build_summary_payload = MethodType(
        lambda self, *, account_payload, positions_payload: {
            "account": dict(account_payload),
            "positions_summary": dict(positions_payload.get("summary") or {}),
            "stale_data": False,
        },
        bridge,
    )
    bridge._build_bots_runtime_light_payload = MethodType(
        lambda self: {
            "bots": [{"id": "bot-1"}],
            "error": None,
            "stale_data": False,
            "runtime_state_source": "runner_runtime_bots_light",
            "runtime_publish_ts": time.time(),
            "bots_scope": "light",
        },
        bridge,
    )

    bridge._publish(reason="timer", event_types={"timer"}, force=True)

    payload = json.loads((tmp_path / "runtime_snapshot_bridge.json").read_text(encoding="utf-8"))
    publish_pass = (payload.get("meta") or {}).get("publish_pass") or {}
    assert publish_pass["final_write_completed_at"] is not None
    assert publish_pass["pass_elapsed_ms"] > 0
    assert publish_pass["serialization_ms"] >= 0.0
    assert publish_pass["write_file_ms"] >= 0.0
    assert publish_pass["total_bytes"] > 0
    assert publish_pass["long_pole_section"] in {
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    }
    assert publish_pass["max_section_age_at_final_ms"] is not None
    assert set((publish_pass.get("section_ages_at_final_ms") or {}).keys()) == {
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    }
    for name in (
        "market",
        "open_orders",
        "positions",
        "summary",
        "bots_runtime_light",
        "bots_runtime",
    ):
        assert "elapsed_ms" in ((publish_pass.get("sections") or {}).get(name) or {})


def test_open_orders_payload_includes_runtime_diagnostics_when_available(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))

    class FakeBotStatusService:
        def get_live_open_order_summary_by_symbol(self, bots=None):
            return {
                "BTCUSDT": {
                    "open_order_count": 2,
                    "reduce_only_count": 1,
                    "entry_order_count": 1,
                }
            }

        def get_last_live_open_orders_diagnostics(self):
            return {
                "path": "all_orders_stream",
                "symbol_count": 1,
                "client_query_ms": 0.5,
            }

    bridge.bot_status_service = FakeBotStatusService()
    payload = bridge._build_open_orders_payload()

    assert payload["symbols"]["BTCUSDT"]["open_order_count"] == 2
    assert payload["symbols"]["BTCUSDT"]["reduce_only_count"] == 1
    assert payload["symbols"]["BTCUSDT"]["entry_order_count"] == 1
    assert payload["open_orders_runtime_diagnostics"]["path"] == "all_orders_stream"
    assert payload["open_orders_runtime_diagnostics"]["symbol_count"] == 1


def test_collect_market_symbols_uses_projected_bot_storage_path(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))

    class FakeCapture:
        def __init__(self, trace):
            self.trace = trace

        def __enter__(self):
            return self.trace

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeBotStorage:
        def __init__(self):
            self.calls = []

        def capture_read_diagnostics(self, label):
            return FakeCapture(
                {
                    "cache_result_counts": {"hit": 1},
                    "phase_ms": {"projection_cache_lookup_ms": 0.05},
                    "lock_wait_ms": {"cache_lock": 0.0},
                }
            )

        def list_bots(self, **kwargs):
            self.calls.append(kwargs)
            return [
                {"symbol": "BTCUSDT", "status": "running"},
                {"symbol": "ETHUSDT", "status": "paused"},
                {"symbol": "AUTO-PILOT", "status": "running"},
            ]

    bridge.bot_storage = FakeBotStorage()

    symbols = bridge._collect_market_symbols()

    assert symbols == ["BTCUSDT"]
    assert bridge.bot_storage.calls == [
        {
            "source": "runtime_bridge_market_symbols",
            "projector": extract_market_symbol_bot,
            "read_only_projected_cache": True,
        }
    ]
    diagnostics = bridge._last_market_symbol_diagnostics
    assert diagnostics["path"] == "running_bots"
    assert diagnostics["symbol_count"] == 1
    assert diagnostics["bot_storage_cache_result_counts"] == {"hit": 1}


def test_market_payload_includes_runtime_diagnostics_and_reuses_meta_health(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))
    bridge._last_market_symbol_diagnostics = {
        "path": "running_bots",
        "symbol_collection_ms": 1.25,
        "symbol_count": 1,
    }

    class FakeStreamService:
        def __init__(self):
            self.calls = []

        def get_dashboard_snapshot(self, symbols, **kwargs):
            self.calls.append({"symbols": list(symbols or []), **kwargs})
            return {
                "prices": {"BTCUSDT": {"lastPrice": "100.0"}},
                "missing_symbols": [],
                "fresh_symbol_count": 1,
                "requested_symbol_count": 1,
                "price_received_at": {"BTCUSDT": 1234.5},
                "ticker_topic_fresh": True,
                "stale_data": False,
                "health": {"transport": "stream"},
            }

    bridge.stream_service = FakeStreamService()

    payload = bridge._build_market_payload(
        symbols=["BTCUSDT"],
        health={"transport": "meta_stream"},
    )

    diagnostics = payload["market_runtime_diagnostics"]
    assert payload["health"] == {"transport": "meta_stream"}
    assert diagnostics["path"] == "stream_dashboard_snapshot"
    assert diagnostics["symbol_source"] == "running_bots"
    assert diagnostics["health_source"] == "meta_stream_health"
    assert diagnostics["requested_symbol_count"] == 1
    assert diagnostics["fresh_symbol_count"] == 1
    assert diagnostics["missing_symbol_count"] == 0
    assert diagnostics["snapshot_fetch_ms"] >= 0.0
    assert diagnostics["shaping_ms"] >= 0.0
    assert bridge.stream_service.calls == [
        {
            "symbols": ["BTCUSDT"],
            "include_health": False,
            "symbols_are_normalized": True,
        }
    ]
