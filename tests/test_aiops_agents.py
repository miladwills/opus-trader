"""Tests for AI Ops agent registry, supervisor, and lifecycle controls."""

import asyncio
import time
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

from opus_aiops.models import AgentState
from opus_aiops.repo import Repository
from opus_aiops.agents import AgentSupervisor, AGENT_RUNNERS
from opus_aiops import db, config


@pytest_asyncio.fixture
async def repo():
    """Create an in-memory DB + Repository for testing."""
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
    from opus_aiops.models import SystemSnapshot
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


class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_init_seeds_default_agents(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        agents = await repo.get_all_agents()
        agent_ids = {a["agent_id"] for a in agents}
        assert "monitor" in agent_ids
        assert "scout" in agent_ids
        assert "evaluator" in agent_ids
        assert "fix" in agent_ids
        assert "promotion_gate" in agent_ids
        assert len(agents) == 5

    @pytest.mark.asyncio
    async def test_init_preserves_existing(self, repo, mock_context):
        # Pre-insert a modified agent
        agent = AgentState(
            agent_id="monitor", name="Custom Monitor", role="custom",
            status="paused", enabled=True, auto_run=False, interval_sec=999,
        )
        await repo.upsert_agent(agent)

        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        loaded = supervisor.agents["monitor"]
        assert loaded.name == "Custom Monitor"
        assert loaded.interval_sec == 999
        assert loaded.status == "paused"

    @pytest.mark.asyncio
    async def test_agent_persistence(self, repo):
        agent = AgentState(
            agent_id="test_agent", name="Test", role="testing",
            status="idle", run_count=42,
        )
        await repo.upsert_agent(agent)

        loaded = await repo.get_agent("test_agent")
        assert loaded is not None
        assert loaded["run_count"] == 42
        assert loaded["status"] == "idle"


class TestAgentLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.start_agent("monitor", actor="test")
        assert "started" in result
        agent = supervisor.agents["monitor"]
        assert agent.status in ("idle", "running")
        assert agent.enabled is True

        result = await supervisor.stop_agent("monitor", actor="test")
        assert "stopped" in result
        agent = supervisor.agents["monitor"]
        assert agent.status == "stopped"
        assert agent.auto_run is False

    @pytest.mark.asyncio
    async def test_pause_resume(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.start_agent("scout", actor="test")

        result = await supervisor.pause_agent("scout", actor="test")
        assert "paused" in result
        assert supervisor.agents["scout"].status == "paused"

        result = await supervisor.resume_agent("scout", actor="test")
        assert "resumed" in result
        assert supervisor.agents["scout"].status == "idle"

    @pytest.mark.asyncio
    async def test_pause_invalid_state(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.pause_agent("fix", actor="test")
        assert "cannot be paused" in result

    @pytest.mark.asyncio
    async def test_resume_not_paused(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.resume_agent("fix", actor="test")
        assert "not paused" in result

    @pytest.mark.asyncio
    async def test_run_once(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.run_once("monitor", actor="test")
        assert "run-once" in result

        # Give the task time to complete
        await asyncio.sleep(0.5)

        agent = supervisor.agents["monitor"]
        assert agent.run_count >= 1

    @pytest.mark.asyncio
    async def test_restart(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()
        await supervisor.start_agent("monitor", actor="test")

        result = await supervisor.restart_agent("monitor", actor="test")
        assert "started" in result
        assert supervisor.agents["monitor"].enabled is True

    @pytest.mark.asyncio
    async def test_nonexistent_agent(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.start_agent("nonexistent", actor="test")
        assert "not found" in result


class TestBulkControls:
    @pytest.mark.asyncio
    async def test_start_all_enabled(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        result = await supervisor.start_all_enabled(actor="test")
        assert "Started" in result

        # Check enabled agents are now active
        for agent_id, agent in supervisor.agents.items():
            if agent_id != "fix":  # fix is disabled by default
                assert agent.status in ("idle", "running")

    @pytest.mark.asyncio
    async def test_stop_all(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()
        await supervisor.start_all_enabled(actor="test")

        result = await supervisor.stop_all(actor="test")
        assert "Stopped" in result

        for agent in supervisor.agents.values():
            assert agent.status == "stopped"

    @pytest.mark.asyncio
    async def test_pause_all(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()
        await supervisor.start_all_enabled(actor="test")

        result = await supervisor.pause_all(actor="test")
        assert "Paused" in result


class TestAgentExecution:
    @pytest.mark.asyncio
    async def test_agent_failure_isolated(self, repo, mock_context):
        """One agent failing must not crash the supervisor."""
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        # Make scout runner raise an exception
        original_runner = AGENT_RUNNERS["scout"]
        AGENT_RUNNERS["scout"] = AsyncMock(side_effect=RuntimeError("test failure"))

        try:
            await supervisor.run_once("scout", actor="test")
            await asyncio.sleep(0.5)

            agent = supervisor.agents["scout"]
            assert agent.status == "error"
            assert "test failure" in agent.error_summary

            # Other agents should still work
            await supervisor.run_once("monitor", actor="test")
            await asyncio.sleep(0.5)
            assert supervisor.agents["monitor"].run_count >= 1
        finally:
            AGENT_RUNNERS["scout"] = original_runner

    @pytest.mark.asyncio
    async def test_run_records_in_db(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.run_once("monitor", actor="test")
        await asyncio.sleep(0.5)

        runs = await repo.get_agent_runs("monitor")
        assert len(runs) >= 1
        assert runs[0]["status"] in ("completed", "running")


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_lifecycle_audited(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.start_agent("monitor", actor="testuser")
        await supervisor.pause_agent("monitor", actor="testuser")
        await supervisor.resume_agent("monitor", actor="testuser")
        await supervisor.stop_agent("monitor", actor="testuser")

        audit = await repo.get_audit_log(limit=10)
        actions = [e["action"] for e in audit]
        assert "agent_started" in actions
        assert "agent_paused" in actions
        assert "agent_resumed" in actions
        assert "agent_stopped" in actions

        # Verify actor is recorded
        for entry in audit:
            assert entry["actor"] == "testuser"
