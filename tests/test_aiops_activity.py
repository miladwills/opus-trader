"""Tests for AI Ops agent activity feed and heartbeat freshness."""

import asyncio
import time
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock

from opus_aiops.models import AgentState, SystemSnapshot
from opus_aiops.repo import Repository
from opus_aiops.agents import AgentSupervisor, AGENT_RUNNERS
from opus_aiops import db


@pytest_asyncio.fixture
async def repo():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(db.SCHEMA)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.commit()
    r = Repository(conn)
    yield r
    await conn.close()


@pytest.fixture
def mock_context():
    snap = SystemSnapshot(
        timestamp=time.time(),
        health_score=95.0,
        health_status="healthy",
        source_errors={},
        bridge_stale_count=0,
        active_incidents=[],
        collection_timing={},
        runner_active=True,
        bot_total=2,
        bot_status_counts={"running": 1, "stopped": 1},
        flash_crash_active=False,
    )
    collector = MagicMock()
    collector.latest_snapshot = snap
    collector.collection_count = 10
    collector.collect = AsyncMock(return_value=snap)

    engine = MagicMock()
    engine.evaluate = MagicMock(return_value=[])
    engine.open_cases = []

    return {
        "collector": collector,
        "triage_engine": engine,
    }


class TestActivityRecording:
    @pytest.mark.asyncio
    async def test_record_and_retrieve(self, repo):
        await repo.record_activity("monitor", "started", "Started by operator")
        await repo.record_activity("monitor", "run_completed", "Collected 3 cases")

        activity = await repo.get_agent_activity("monitor", limit=10)
        assert len(activity) == 2
        assert activity[0]["event_type"] == "run_completed"  # most recent first
        assert activity[1]["event_type"] == "started"

    @pytest.mark.asyncio
    async def test_activity_per_agent(self, repo):
        await repo.record_activity("monitor", "started", "Monitor started")
        await repo.record_activity("scout", "started", "Scout started")
        await repo.record_activity("monitor", "run_completed", "Monitor done")

        monitor = await repo.get_agent_activity("monitor")
        scout = await repo.get_agent_activity("scout")
        assert len(monitor) == 2
        assert len(scout) == 1

    @pytest.mark.asyncio
    async def test_activity_limit(self, repo):
        for i in range(10):
            await repo.record_activity("monitor", "run_completed", f"Run {i}")

        activity = await repo.get_agent_activity("monitor", limit=5)
        assert len(activity) == 5

    @pytest.mark.asyncio
    async def test_all_recent_activity(self, repo):
        await repo.record_activity("monitor", "started", "m")
        await repo.record_activity("scout", "started", "s")
        await repo.record_activity("evaluator", "started", "e")

        all_activity = await repo.get_all_recent_activity(limit=50)
        assert len(all_activity) == 3

    @pytest.mark.asyncio
    async def test_activity_detail_json(self, repo):
        await repo.record_activity("monitor", "run_completed", "done", {"cases": 3, "open": 1})

        activity = await repo.get_agent_activity("monitor")
        assert activity[0]["detail"]["cases"] == 3
        assert activity[0]["detail"]["open"] == 1


class TestActivityFromSupervisor:
    @pytest.mark.asyncio
    async def test_lifecycle_creates_activity(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.start_agent("monitor", actor="testuser")
        await supervisor.pause_agent("monitor", actor="testuser")
        await supervisor.resume_agent("monitor", actor="testuser")
        await supervisor.stop_agent("monitor", actor="testuser")

        activity = await repo.get_agent_activity("monitor")
        event_types = [e["event_type"] for e in activity]
        assert "started" in event_types
        assert "paused" in event_types
        assert "resumed" in event_types
        assert "stopped" in event_types

    @pytest.mark.asyncio
    async def test_run_once_creates_activity(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.run_once("monitor", actor="test")
        await asyncio.sleep(0.5)

        activity = await repo.get_agent_activity("monitor")
        event_types = [e["event_type"] for e in activity]
        assert "run_once" in event_types
        assert "run_started" in event_types
        assert "run_completed" in event_types

    @pytest.mark.asyncio
    async def test_run_error_creates_activity(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        original = AGENT_RUNNERS["scout"]
        AGENT_RUNNERS["scout"] = AsyncMock(side_effect=RuntimeError("test boom"))
        try:
            await supervisor.run_once("scout", actor="test")
            await asyncio.sleep(0.5)

            activity = await repo.get_agent_activity("scout")
            event_types = [e["event_type"] for e in activity]
            assert "run_error" in event_types
            error_entry = next(e for e in activity if e["event_type"] == "run_error")
            assert "test boom" in error_entry["summary"]
        finally:
            AGENT_RUNNERS["scout"] = original

    @pytest.mark.asyncio
    async def test_activity_contains_actor(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.start_agent("monitor", actor="ops_user")

        activity = await repo.get_agent_activity("monitor")
        started = next(e for e in activity if e["event_type"] == "started")
        assert "ops_user" in started["summary"]


class TestActivityPurge:
    @pytest.mark.asyncio
    async def test_purge_removes_old_activity(self, repo):
        # Insert old activity
        old_ts = time.time() - 8 * 86400  # 8 days ago
        await repo._db.execute(
            "INSERT INTO agent_activity (agent_id, timestamp, event_type, summary, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            ("monitor", old_ts, "started", "old", "{}"),
        )
        await repo._db.commit()

        # Insert recent activity
        await repo.record_activity("monitor", "started", "recent")

        await repo.purge_old_data()

        activity = await repo.get_agent_activity("monitor", limit=100)
        assert len(activity) == 1
        assert activity[0]["summary"] == "recent"


class TestHeartbeatFreshness:
    def test_fresh(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(time.time() - 10, 30)
        assert result["label"] == "fresh"

    def test_delayed(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(time.time() - 60, 30)
        assert result["label"] == "delayed"

    def test_stale(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(time.time() - 120, 30)
        assert result["label"] == "stale"

    def test_offline_long(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(time.time() - 300, 30)
        assert result["label"] == "offline"

    def test_offline_none(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(None, 30)
        assert result["label"] == "offline"
