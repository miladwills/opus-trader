"""Tests for incident classifier dedup and cooldown logic."""

import asyncio
import time
import pytest
import aiosqlite
from opus_platform_watchdog.classifiers.incident_classifier import IncidentClassifier
from opus_platform_watchdog.storage.repo import Repository
from opus_platform_watchdog import db


@pytest.fixture
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
async def test_no_match_returns_empty(repo):
    classifier = IncidentClassifier(repo)
    lines = ["Everything is fine, no errors here"]
    incidents = await classifier.scan_lines(lines, "runner")
    assert len(incidents) == 0
