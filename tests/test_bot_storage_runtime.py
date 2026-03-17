import json
import threading
import time

from services.bot_storage_service import BotStorageService


class _HeldLock:
    def __init__(self, lock):
        self._lock = lock
        self._acquired = threading.Event()
        self._release = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        with self._lock:
            self._acquired.set()
            self._release.wait(timeout=2.0)

    def __enter__(self):
        self._thread.start()
        assert self._acquired.wait(timeout=1.0)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._release.set()
        self._thread.join(timeout=1.0)


def test_save_runtime_bot_batches_disk_write_until_flush(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    bot = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    updated = dict(bot)
    updated["current_price"] = 50123.0
    updated["last_run_at"] = "2026-03-07T02:00:00+00:00"
    storage.save_runtime_bot(updated, flush_delay_sec=60.0)

    cached = storage.get_bot("bot-1")
    assert cached["current_price"] == 50123.0

    on_disk_before_flush = json.loads(storage_path.read_text(encoding="utf-8"))
    assert on_disk_before_flush[0].get("current_price") is None

    assert storage.flush_runtime_updates() == 1

    on_disk_after_flush = json.loads(storage_path.read_text(encoding="utf-8"))
    assert on_disk_after_flush[0]["current_price"] == 50123.0


def test_save_runtime_bot_falls_back_to_immediate_save_for_control_fields(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    bot = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    updated = dict(bot)
    updated["status"] = "paused"
    storage.save_runtime_bot(updated, flush_delay_sec=60.0)

    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))
    assert on_disk[0]["status"] == "paused"
    assert storage.flush_runtime_updates() == 0


def test_save_bot_preserves_control_fields_during_stale_control_state_merge(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))

    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "status": "running",
            "auto_pilot": True,
            "control_version": 1,
            "control_updated_at": "2026-03-08T08:20:00+00:00",
            "last_error": None,
        }
    )
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "mode": "neutral",
            "status": "stopped",
            "auto_pilot": True,
            "control_version": 2,
            "control_updated_at": "2026-03-08T08:21:00+00:00",
            "last_error": "Manual stop",
        }
    )

    merged = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "status": "running",
            "auto_pilot": True,
            "control_version": 1,
            "control_updated_at": "2026-03-08T08:20:30+00:00",
            "last_error": None,
            "last_run_at": "2026-03-08T08:21:30+00:00",
        }
    )

    assert merged["status"] == "stopped"
    assert merged["symbol"] == "Auto-Pilot"
    assert merged["control_version"] == 2
    assert merged["last_error"] == "Manual stop"


def test_save_bot_clears_stale_stop_cleanup_and_pause_fields_on_restart(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))

    current = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "status": "stop_cleanup_pending",
            "control_version": 1,
            "control_updated_at": "2026-03-14T07:31:49+00:00",
            "stop_cleanup_pending": True,
            "stop_cleanup_target_status": "stopped",
            "stop_cleanup_scope": "emergency_stop",
            "stop_cleanup_reason": "emergency_stop",
            "stop_cleanup_requested_at": "2026-03-14T07:31:49+00:00",
            "pause_reason": "Stop cleanup pending",
            "pause_reason_type": "stop_cleanup_pending",
            "paused_at": 1773473509.0,
            "reduce_only_mode": True,
            "auto_stop_paused": True,
        }
    )

    restarted = dict(current)
    restarted["status"] = "running"
    restarted["control_version"] = 2
    restarted["control_updated_at"] = "2026-03-14T07:32:15+00:00"
    restarted["started_at"] = "2026-03-14T07:32:15+00:00"
    restarted["reduce_only_mode"] = False
    restarted["auto_stop_paused"] = False
    restarted["last_error"] = None
    for key in (
        "stop_cleanup_pending",
        "stop_cleanup_target_status",
        "stop_cleanup_scope",
        "stop_cleanup_reason",
        "stop_cleanup_requested_at",
        "stop_cleanup_final_last_error",
        "pause_reason",
        "pause_reason_type",
        "paused_at",
    ):
        restarted.pop(key, None)

    saved = storage.save_bot(restarted)
    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))

    assert saved["status"] == "running"
    assert saved["control_version"] == 2
    assert "stop_cleanup_pending" not in saved
    assert "stop_cleanup_target_status" not in saved
    assert "stop_cleanup_reason" not in saved
    assert "pause_reason" not in saved
    assert "paused_at" not in saved
    assert on_disk[0]["status"] == "running"
    assert "stop_cleanup_pending" not in on_disk[0]
    assert "stop_cleanup_target_status" not in on_disk[0]
    assert "stop_cleanup_reason" not in on_disk[0]
    assert "pause_reason" not in on_disk[0]
    assert "paused_at" not in on_disk[0]


def test_save_bot_preserves_placeholder_when_late_same_stop_save_arrives(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))

    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "SIGNUSDT",
            "mode": "scalp_pnl",
            "status": "running",
            "auto_pilot": True,
            "control_version": 1,
            "control_updated_at": "2026-03-08T08:31:00+00:00",
        }
    )
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "SIGNUSDT",
            "mode": "scalp_pnl",
            "status": "stopped",
            "auto_pilot": True,
            "control_version": 2,
            "control_updated_at": "2026-03-08T08:32:03+00:00",
        }
    )
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "mode": "neutral_classic_bybit",
            "status": "stopped",
            "auto_pilot": True,
            "control_version": 3,
            "control_updated_at": "2026-03-08T08:32:04+00:00",
            "grid_lower_price": None,
            "grid_upper_price": None,
            "grid_levels_total": None,
            "neutral_grid": {},
            "neutral_grid_initialized": False,
            "neutral_grid_last_reconcile_at": None,
        }
    )

    merged = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "ALTUSDT",
            "mode": "neutral_classic_bybit",
            "status": "stopped",
            "auto_pilot": True,
            "control_version": 2,
            "control_updated_at": "2026-03-08T08:32:03+00:00",
            "last_skip_reason": "insufficient_margin",
            "grid_lower_price": 1.9,
            "grid_upper_price": 2.1,
            "grid_levels_total": 8,
            "neutral_grid": {"slots": {"L00": {"state": "ENTRY"}}},
            "neutral_grid_initialized": True,
            "neutral_grid_last_reconcile_at": "2026-03-08T08:32:05+00:00",
        }
    )

    assert merged["status"] == "stopped"
    assert merged["symbol"] == "Auto-Pilot"
    assert merged["control_version"] == 3
    assert merged["grid_lower_price"] is None
    assert merged["grid_upper_price"] is None
    assert merged["grid_levels_total"] is None
    assert merged["neutral_grid"] == {}
    assert merged["neutral_grid_initialized"] is False
    assert merged["neutral_grid_last_reconcile_at"] is None


def test_save_bot_preserves_authoritative_pnl_against_stale_generic_save(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))

    current = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "running",
            "realized_pnl": 0.0,
            "total_pnl": 0.0,
        }
    )
    stale_snapshot = dict(current)

    pnl_refreshed = dict(current)
    pnl_refreshed["realized_pnl"] = 12.34
    pnl_refreshed["total_pnl"] = 12.34
    storage.save_bot(pnl_refreshed, allow_pnl_override=True)

    stale_snapshot["last_run_at"] = "2026-03-08T13:34:26.690621+00:00"
    merged = storage.save_bot(stale_snapshot)

    assert merged["realized_pnl"] == 12.34
    assert merged["total_pnl"] == 12.34
    assert merged["last_run_at"] == "2026-03-08T13:34:26.690621+00:00"


def test_save_bot_keeps_configured_mode_persisted_when_runtime_mode_is_non_persistent(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))

    saved = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "short",
            "configured_mode": "long",
            "range_mode": "trailing",
            "configured_range_mode": "dynamic",
            "mode_policy": "runtime_auto_switch_non_persistent",
            "effective_runtime_mode": "short",
            "effective_runtime_range_mode": "trailing",
            "runtime_mode_source": "auto_direction",
            "runtime_mode_non_persistent": True,
            "status": "running",
            "lower_price": 90000.0,
            "upper_price": 100000.0,
            "investment": 100.0,
            "leverage": 3.0,
        }
    )

    persisted = storage.get_bot("bot-1")
    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))

    assert saved["mode"] == "short"
    assert saved["configured_mode"] == "long"
    assert persisted["mode"] == "long"
    assert persisted["configured_mode"] == "long"
    assert persisted["range_mode"] == "dynamic"
    assert persisted["effective_runtime_mode"] == "short"
    assert persisted["effective_runtime_range_mode"] == "trailing"
    assert on_disk[0]["mode"] == "long"
    assert on_disk[0]["range_mode"] == "dynamic"


def test_list_bots_falls_back_when_runtime_lock_is_unavailable(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    storage.internal_lock_timeout_sec = 0.01
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    started_at = time.perf_counter()
    with _HeldLock(storage._runtime_lock):
        bots = storage.list_bots()
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.25
    assert bots[0]["id"] == "bot-1"


def test_list_bots_falls_back_when_cache_lock_is_unavailable(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    storage.internal_lock_timeout_sec = 0.01
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "ETHUSDT",
            "mode": "long",
            "status": "running",
        }
    )

    started_at = time.perf_counter()
    with _HeldLock(storage._cache_lock):
        bots = storage.list_bots()
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.25
    assert bots[0]["symbol"] == "ETHUSDT"


def test_save_bot_skips_runtime_drain_when_runtime_lock_is_unavailable(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    storage.internal_lock_timeout_sec = 0.01
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    started_at = time.perf_counter()
    with _HeldLock(storage._runtime_lock):
        updated = storage.save_bot(
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "neutral",
                "status": "paused",
            }
        )
    elapsed = time.perf_counter() - started_at

    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))
    assert elapsed < 0.25
    assert updated["status"] == "paused"
    assert on_disk[0]["status"] == "paused"


def test_save_bot_writes_disk_when_cache_lock_is_unavailable(tmp_path):
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    storage.internal_lock_timeout_sec = 0.01
    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    started_at = time.perf_counter()
    with _HeldLock(storage._cache_lock):
        updated = storage.save_bot(
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "neutral",
                "status": "paused",
            }
        )
    elapsed = time.perf_counter() - started_at

    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))
    assert elapsed < 0.25
    assert updated["status"] == "paused"
    assert on_disk[0]["status"] == "paused"


def test_save_runtime_bot_skips_disk_when_runtime_lock_is_unavailable(tmp_path):
    """When runtime_lock times out, save_runtime_bot should return the
    cache-updated bot without falling back to the heavier save_bot() path.
    The data is in the memory cache and will be flushed or recomputed next cycle."""
    storage_path = tmp_path / "bots.json"
    storage = BotStorageService(str(storage_path))
    storage.internal_lock_timeout_sec = 0.01
    bot = storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "status": "running",
        }
    )

    updated = dict(bot)
    updated["current_price"] = 99999.0

    started_at = time.perf_counter()
    with _HeldLock(storage._runtime_lock):
        result = storage.save_runtime_bot(updated, flush_delay_sec=60.0)
    elapsed = time.perf_counter() - started_at

    # Should complete quickly (no save_bot fallback)
    assert elapsed < 0.25
    # Returned bot reflects the update
    assert result["current_price"] == 99999.0
    # Cache reflects the update
    cached = storage.get_bot("bot-1")
    assert cached["current_price"] == 99999.0
    # Disk does NOT have the update (no fallback to save_bot)
    on_disk = json.loads(storage_path.read_text(encoding="utf-8"))
    assert on_disk[0].get("current_price") is None
