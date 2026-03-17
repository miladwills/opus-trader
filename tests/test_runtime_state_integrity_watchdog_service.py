import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from services.runtime_state_integrity_watchdog_service import (
    RuntimeStateIntegrityWatchdogService,
)


def _bot(
    bot_id: str,
    *,
    status: str = "running",
    setup_status: str = "watch",
    analysis_status: str | None = None,
    entry_status: str | None = None,
) -> dict:
    return {
        "id": bot_id,
        "symbol": "BTCUSDT" if bot_id == "bot-1" else "ETHUSDT",
        "status": status,
        "setup_ready_status": setup_status,
        "analysis_ready_status": analysis_status or setup_status,
        "entry_ready_status": entry_status or setup_status,
        "execution_viability_status": "open",
    }


def _payload(
    bots,
    *,
    snapshot_ts: float,
    owner: str = "runner",
    source: str = "runner_runtime_snapshot",
    stale_data: bool = False,
    error: str | None = None,
) -> dict:
    return {
        "bots": list(bots),
        "stale_data": stale_data,
        "error": error,
        "snapshot_published_at": snapshot_ts,
        "snapshot_produced_at": snapshot_ts,
        "runtime_publish_ts": max(snapshot_ts - 1.0, 0.0),
        "runtime_publish_at": "2026-03-13T00:00:00+00:00",
        "readiness_latency": {
            "latest_readiness_generated_ts": max(snapshot_ts - 2.0, 0.0),
            "latest_readiness_generated_at": "2026-03-13T00:00:00+00:00",
            "paths": {
                "live_runtime": {"bot_count": len(list(bots))},
                "stopped_preview": {"bot_count": 0},
            },
        },
        "snapshot_owner": owner,
        "snapshot_source": source,
        "snapshot_epoch": int(snapshot_ts),
        "snapshot_fresh": not stale_data,
    }


def test_stale_runtime_payload_does_not_wipe_last_known_good_state():
    service = RuntimeStateIntegrityWatchdogService(hold_last_good_sec=30.0)

    first = service.resolve_bots_payload(
        bridge_payload=None,
        direct_payload=_payload([_bot("bot-1", setup_status="ready")], snapshot_ts=100.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=100.0,
    )
    preserved = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=105.0, stale_data=True, error="bots_runtime_bridge_stale"),
        direct_payload=None,
        runner_heartbeat_age_sec=5.0,
        runner_active=True,
        now_ts=110.0,
    )

    assert first["stale_data"] is False
    assert preserved["bots"][0]["id"] == "bot-1"
    assert preserved["stale_data"] is True
    assert preserved["runtime_integrity"]["stale_guard_active"] is True
    assert preserved["runtime_integrity"]["stale_guard_reason"] == "stale_partial_regression"
    assert preserved["runtime_integrity"]["held_last_good"] is True
    assert preserved["runtime_integrity"]["bridge_action"] == "held_last_good"


def test_older_payload_is_ignored_after_newer_snapshot_was_applied():
    service = RuntimeStateIntegrityWatchdogService()

    service.resolve_bots_payload(
        bridge_payload=_payload([_bot("bot-1", setup_status="ready")], snapshot_ts=200.0),
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=200.0,
    )
    preserved = service.resolve_bots_payload(
        bridge_payload=None,
        direct_payload=_payload([_bot("bot-1", setup_status="watch")], snapshot_ts=190.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=201.0,
    )

    assert preserved["bots"][0]["setup_ready_status"] == "ready"
    assert preserved["runtime_integrity"]["dropped_as_stale"] is True
    assert preserved["runtime_integrity"]["dropped_reason"] == "older_snapshot"


def test_malformed_payload_cannot_replace_valid_runtime_state():
    service = RuntimeStateIntegrityWatchdogService()

    service.resolve_bots_payload(
        bridge_payload=None,
        direct_payload=_payload([_bot("bot-1")], snapshot_ts=300.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=300.0,
    )
    preserved = service.resolve_bots_payload(
        bridge_payload={"bots": {"id": "not-a-list"}, "snapshot_published_at": 305.0},
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=306.0,
    )

    assert preserved["bots"][0]["id"] == "bot-1"
    assert preserved["runtime_integrity"]["dropped_reason"] in {"invalid_shape", "no_valid_candidate"}
    assert preserved["runtime_integrity"]["stale_guard_active"] is True


def test_source_divergence_is_detected_and_classified():
    service = RuntimeStateIntegrityWatchdogService()

    payload = service.resolve_bots_payload(
        bridge_payload=_payload([_bot("bot-1", status="running", setup_status="ready")], snapshot_ts=400.0),
        direct_payload=_payload([_bot("bot-1", status="stopped", setup_status="watch")], snapshot_ts=401.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=401.0,
    )

    assert payload["runtime_integrity"]["divergence_detected"] is True
    assert "bot_status_conflict" in payload["runtime_integrity"]["divergence_reasons"]
    assert "readiness_conflict" in payload["runtime_integrity"]["divergence_reasons"]
    assert payload["runtime_integrity"]["bridge_action"] == "accepted"
    assert payload["runtime_integrity"]["runtime_snapshot_age_ms"] is not None


def test_rebuilt_from_app_marks_bridge_rejection_reason():
    service = RuntimeStateIntegrityWatchdogService()

    payload = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=500.0, stale_data=True, error="bots_runtime_bridge_stale"),
        direct_payload=_payload([_bot("bot-1", setup_status="ready")], snapshot_ts=501.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=501.5,
    )

    assert payload["runtime_integrity"]["rebuilt_from_app"] is True
    assert payload["runtime_integrity"]["bridge_action"] == "rebuilt_from_app"
    assert payload["runtime_integrity"]["bridge_rejected_reason"] == "stale"
    assert payload["readiness_latency"]["paths"]["live_runtime"]["bot_count"] == 1


def test_start_acceptance_surfaces_pending_until_runner_owned_snapshot_picks_it_up():
    service = RuntimeStateIntegrityWatchdogService(start_pending_sec=10.0, start_stalled_sec=20.0)
    service.register_start(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "started_at": "1970-01-01T00:08:20+00:00",
        }
    )

    payload = service.resolve_bots_payload(
        bridge_payload=None,
        direct_payload=_payload([_bot("bot-1", status="running")], snapshot_ts=500.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=505.0,
    )

    assert payload["bots"][0]["startup_pending"] is True
    assert payload["bots"][0]["runtime_start_lifecycle"] == "pending_runner_pickup"
    assert payload["runtime_integrity"]["startup_pending"] is True


def test_fresh_bridge_does_not_force_direct_probe_for_pending_start():
    service = RuntimeStateIntegrityWatchdogService(start_pending_sec=10.0, start_stalled_sec=20.0)
    service.register_start(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "started_at": "1970-01-01T00:08:20+00:00",
        }
    )

    should_probe = service.should_probe_direct_runtime(
        _payload([_bot("bot-1", status="running")], snapshot_ts=500.0)
    )

    assert should_probe is False


def test_start_acceptance_is_preserved_from_fresh_bridge_without_direct_payload():
    service = RuntimeStateIntegrityWatchdogService(start_pending_sec=10.0, start_stalled_sec=20.0)
    service.register_start(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "started_at": "1970-01-01T00:08:20+00:00",
        }
    )

    payload = service.resolve_bots_payload(
        bridge_payload=_payload([_bot("bot-1", status="running")], snapshot_ts=500.0),
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=505.0,
    )

    assert payload["bots"][0]["startup_pending"] is True
    assert payload["bots"][0]["runtime_start_lifecycle"] == "pending_runner_pickup"
    assert payload["runtime_integrity"]["startup_pending"] is True
    assert payload["runtime_integrity"]["bridge_action"] == "accepted"


def test_start_acceptance_holds_missing_bot_from_fresh_bridge_without_direct_payload():
    service = RuntimeStateIntegrityWatchdogService(start_pending_sec=10.0, start_stalled_sec=20.0)
    service.register_start(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "started_at": "1970-01-01T00:08:20+00:00",
            "last_run_at": None,
        }
    )

    payload = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=500.0),
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=505.0,
    )

    assert payload["bots"][0]["id"] == "bot-1"
    assert payload["bots"][0]["runtime_state_held"] is True
    assert payload["bots"][0]["runtime_state_held_reason"] == "startup_pending"
    assert payload["bots"][0]["startup_pending"] is True
    assert payload["runtime_integrity"]["startup_pending"] is True


def test_start_acceptance_surfaces_stalled_when_runner_never_confirms_runtime_state():
    service = RuntimeStateIntegrityWatchdogService(start_pending_sec=2.0, start_stalled_sec=4.0)
    service.register_start(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "started_at": "1970-01-01T00:10:00+00:00",
        }
    )

    payload = service.resolve_bots_payload(
        bridge_payload=None,
        direct_payload=_payload([_bot("bot-1", status="running")], snapshot_ts=600.0, owner="app", source="app_runtime_rebuild"),
        runner_heartbeat_age_sec=6.0,
        runner_active=True,
        now_ts=605.0,
    )

    assert payload["bots"][0]["startup_stalled"] is True
    assert payload["bots"][0]["runtime_start_lifecycle"] == "startup_stalled"
    assert payload["runtime_integrity"]["startup_stalled"] is True
    assert payload["runtime_integrity"]["resync_requested"] is True


def test_ready_to_trade_state_stays_stable_when_competing_source_goes_stale():
    service = RuntimeStateIntegrityWatchdogService(hold_last_good_sec=30.0)

    service.resolve_bots_payload(
        bridge_payload=_payload([_bot("bot-1", setup_status="ready")], snapshot_ts=700.0),
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=700.0,
    )
    payload = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=705.0, stale_data=True, error="bridge_stale"),
        direct_payload=None,
        runner_heartbeat_age_sec=5.0,
        runner_active=True,
        now_ts=706.0,
    )

    assert payload["bots"][0]["setup_ready_status"] == "ready"
    assert payload["runtime_integrity"]["effective_ready_count"] == 1
    assert payload["runtime_integrity"]["stale_guard_active"] is True


def test_empty_board_remains_stable_without_flicker_when_no_bots_are_active():
    service = RuntimeStateIntegrityWatchdogService()

    first = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=800.0),
        direct_payload=None,
        runner_heartbeat_age_sec=0.0,
        runner_active=True,
        now_ts=800.0,
    )
    second = service.resolve_bots_payload(
        bridge_payload=_payload([], snapshot_ts=799.0, stale_data=True, error="older_empty"),
        direct_payload=None,
        runner_heartbeat_age_sec=1.0,
        runner_active=True,
        now_ts=801.0,
    )

    assert first["bots"] == []
    assert second["bots"] == []
    assert second["runtime_integrity"]["no_active_bot_stable"] is True
