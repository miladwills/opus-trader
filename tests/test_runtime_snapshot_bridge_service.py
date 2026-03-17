import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService


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


def test_bots_runtime_rebuild_interval_is_tightened_for_ticker_events(tmp_path):
    bridge = RuntimeSnapshotBridgeService(file_path=str(tmp_path / "runtime_snapshot_bridge.json"))

    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"orderbook"}) == 0.35
    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"ticker"}) == 0.5
    assert bridge._resolve_rebuild_interval_sec("market", {"ticker"}) == 0.5
    assert bridge._resolve_rebuild_interval_sec("bots_runtime", {"timer"}) == 2.0
