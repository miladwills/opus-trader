"""Tests for incident classifier dedup and cooldown logic."""

import asyncio
import time
import pytest
import pytest_asyncio
import aiosqlite
from opus_platform_watchdog.classifiers.incident_classifier import IncidentClassifier
from opus_platform_watchdog.storage.repo import Repository
from opus_platform_watchdog import db


@pytest_asyncio.fixture
async def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    r = Repository(conn)
    yield r
    await conn.close()


@pytest.mark.asyncio
async def test_scan_creates_incident(repo):
    classifier = IncidentClassifier(repo)
    lines = ["2026-03-17 10:00:00 [ERROR] Unhandled error in main loop: KeyError('x')"]
    incidents = await classifier.scan_lines(lines, "runner")
    assert len(incidents) == 1
    assert incidents[0].severity == "critical"
    assert incidents[0].pattern_key == "unhandled_main_loop"


@pytest.mark.asyncio
async def test_cooldown_dedup(repo):
    classifier = IncidentClassifier(repo)
    lines = ["Unhandled error in main loop: KeyError('x')"]
    # First call creates incident
    incidents1 = await classifier.scan_lines(lines, "runner")
    assert len(incidents1) == 1
    # Second call within cooldown should NOT create new incident
    incidents2 = await classifier.scan_lines(lines, "runner")
    assert len(incidents2) == 0


@pytest.mark.asyncio
async def test_multiple_patterns_detected(repo):
    classifier = IncidentClassifier(repo)
    lines = [
        "Unhandled error in main loop: something",
        "Dashboard snapshot timeout for summary after 3s",
        "Normal log line that should not match anything",
    ]
    incidents = await classifier.scan_lines(lines, "mixed")
    assert len(incidents) == 2
    keys = {i.pattern_key for i in incidents}
    assert "unhandled_main_loop" in keys
    assert "snapshot_timeout" in keys


@pytest.mark.asyncio
async def test_neutral_scan_snapshot_timeout_is_suppressed(repo):
    classifier = IncidentClassifier(repo)
    lines = [
        "2026-03-18 09:37:22,885 [INFO] Dashboard snapshot timeout for neutral_scan after 2.5s",
        "2026-03-18 09:37:25,001 [WARNING] Dashboard snapshot timeout for summary after 3.0s",
    ]
    incidents = await classifier.scan_lines(lines, "app")
    assert len(incidents) == 1
    assert incidents[0].pattern_key == "snapshot_timeout"
    assert incidents[0].detail["match_groups"] == ["summary"]


@pytest.mark.asyncio
async def test_no_match_returns_empty(repo):
    classifier = IncidentClassifier(repo)
    lines = ["Everything is fine, no errors here"]
    incidents = await classifier.scan_lines(lines, "runner")
    assert len(incidents) == 0


@pytest.mark.asyncio
async def test_suppresses_bot_error_state_in_explicit_synthetic_runner_window(repo):
    classifier = IncidentClassifier(repo)
    lines = [
        "2026-03-17 20:14:14,597 [INFO] [test] Connected to public Bybit stream",
        "2026-03-17 20:14:15,849 [WARNING] [BTCUSDT] Failed to persist auto-margin state for bot bot-1: disk full",
        "2026-03-17 20:14:18,995 [INFO] [TESTUSDT] Placed 0 new orders, 0 failed",
        "2026-03-17 20:14:19,015 [ERROR] [BTCUSDT:bot-1] Persisted bot error state after cycle exception",
    ]
    incidents = await classifier.scan_lines(lines, "runner")
    assert incidents == []


@pytest.mark.asyncio
async def test_bot_error_state_still_detected_for_uuid_bot_without_synthetic_context(repo):
    classifier = IncidentClassifier(repo)
    lines = [
        "2026-03-17 19:32:23,474 [INFO] BOT_RUNTIME_PERSIST path=exchange_reconciliation bot_id=a3e88849-66b6-4cb4-8fb3-46eb61d3b60a symbol=SOLUSDT reason=ambiguous_follow_up",
        "2026-03-17 19:32:29,015 [ERROR] [SOLUSDT:a3e88849-66b6-4cb4-8fb3-46eb61d3b60a] Persisted bot error state after cycle exception",
    ]
    incidents = await classifier.scan_lines(lines, "runner")
    assert len(incidents) == 1
    assert incidents[0].pattern_key == "bot_error_state"


@pytest.mark.asyncio
async def test_synthetic_markers_do_not_suppress_non_test_bot_error_state(repo):
    classifier = IncidentClassifier(repo)
    lines = [
        "2026-03-17 20:14:14,597 [INFO] [test] Connected to public Bybit stream",
        "2026-03-17 20:14:19,015 [ERROR] [SOLUSDT:a3e88849-66b6-4cb4-8fb3-46eb61d3b60a] Persisted bot error state after cycle exception",
    ]
    incidents = await classifier.scan_lines(lines, "runner")
    assert len(incidents) == 1
    assert incidents[0].pattern_key == "bot_error_state"
