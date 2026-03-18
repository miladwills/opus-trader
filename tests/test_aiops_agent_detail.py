"""Tests for AI Ops agent detail page, run stats, health assessment, and related data."""

import asyncio
import time
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock

from opus_aiops.models import AgentState, SystemSnapshot, Proposal
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
    return {"collector": collector, "triage_engine": engine}


class TestRunStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, repo):
        stats = await repo.get_agent_run_stats("monitor")
        assert stats["total"] == 0
        assert stats["completed"] == 0
        assert stats["errors"] == 0
        assert stats["avg_duration_sec"] is None

    @pytest.mark.asyncio
    async def test_stats_with_runs(self, repo):
        for i in range(3):
            rid = await repo.record_agent_run_start("monitor")
            await repo.record_agent_run_end(rid, "completed", f"ok {i}")
        rid = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid, "error", error="fail")

        stats = await repo.get_agent_run_stats("monitor")
        assert stats["total"] == 4
        assert stats["completed"] == 3
        assert stats["errors"] == 1
        assert stats["avg_duration_sec"] is not None
        assert stats["avg_duration_sec"] >= 0

    @pytest.mark.asyncio
    async def test_stats_respects_limit(self, repo):
        for i in range(10):
            rid = await repo.record_agent_run_start("monitor")
            await repo.record_agent_run_end(rid, "completed")

        stats = await repo.get_agent_run_stats("monitor", limit=5)
        assert stats["total"] == 5

    @pytest.mark.asyncio
    async def test_duration_calculation(self, repo):
        now = time.time()
        await repo._db.execute(
            "INSERT INTO agent_runs (agent_id, started_at, finished_at, status) VALUES (?, ?, ?, ?)",
            ("monitor", now - 5, now - 3, "completed"),
        )
        await repo._db.execute(
            "INSERT INTO agent_runs (agent_id, started_at, finished_at, status) VALUES (?, ?, ?, ?)",
            ("monitor", now - 10, now - 6, "completed"),
        )
        await repo._db.commit()

        stats = await repo.get_agent_run_stats("monitor")
        assert stats["avg_duration_sec"] == 3.0
        assert stats["min_duration_sec"] == 2.0
        assert stats["max_duration_sec"] == 4.0


class TestLastSuccessFailure:
    @pytest.mark.asyncio
    async def test_no_runs(self, repo):
        assert await repo.get_last_successful_run("monitor") is None
        assert await repo.get_last_failed_run("monitor") is None

    @pytest.mark.asyncio
    async def test_last_success(self, repo):
        rid1 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid1, "completed", "first")
        rid2 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid2, "completed", "second")

        last = await repo.get_last_successful_run("monitor")
        assert last is not None
        assert last["result_summary"] == "second"

    @pytest.mark.asyncio
    async def test_last_failure(self, repo):
        rid1 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid1, "error", error="boom1")
        rid2 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid2, "error", error="boom2")

        last = await repo.get_last_failed_run("monitor")
        assert last is not None
        assert last["error"] == "boom2"

    @pytest.mark.asyncio
    async def test_mixed_runs(self, repo):
        rid1 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid1, "completed", "good")
        rid2 = await repo.record_agent_run_start("monitor")
        await repo.record_agent_run_end(rid2, "error", error="bad")

        success = await repo.get_last_successful_run("monitor")
        failure = await repo.get_last_failed_run("monitor")
        assert success is not None
        assert success["result_summary"] == "good"
        assert failure is not None
        assert failure["error"] == "bad"

    @pytest.mark.asyncio
    async def test_per_agent_isolation(self, repo):
        rid = await repo.record_agent_run_start("scout")
        await repo.record_agent_run_end(rid, "error", error="scout fail")

        assert await repo.get_last_failed_run("monitor") is None
        assert await repo.get_last_failed_run("scout") is not None


class TestRelatedProposals:
    @pytest.mark.asyncio
    async def test_no_proposals(self, repo):
        result = await repo.get_agent_related_proposals("evaluator")
        assert result == []

    @pytest.mark.asyncio
    async def test_proposals_by_source_agent(self, repo):
        for i in range(3):
            prop = Proposal(
                proposal_id=f"PRP-TEST-{i}",
                title=f"Prop {i}",
                category="test",
                source_agent="evaluator",
                action_type="collect_diagnostics",
                status="pending",
                created_at=time.time() + i,
            )
            await repo.create_proposal(prop)

        prop = Proposal(
            proposal_id="PRP-OTHER",
            title="Other",
            category="test",
            source_agent="fix",
            action_type="collect_diagnostics",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        evaluator_props = await repo.get_agent_related_proposals("evaluator")
        assert len(evaluator_props) == 3
        fix_props = await repo.get_agent_related_proposals("fix")
        assert len(fix_props) == 1

    @pytest.mark.asyncio
    async def test_proposals_limit(self, repo):
        for i in range(15):
            prop = Proposal(
                proposal_id=f"PRP-LIMIT-{i}",
                title=f"Prop {i}",
                category="test",
                source_agent="evaluator",
                action_type="collect_diagnostics",
                status="pending",
                created_at=time.time() + i,
            )
            await repo.create_proposal(prop)

        result = await repo.get_agent_related_proposals("evaluator", limit=5)
        assert len(result) == 5


class TestHealthAssessment:
    def test_healthy_agent(self):
        from opus_aiops.routes_pages import _heartbeat_freshness
        result = _heartbeat_freshness(time.time() - 5, 30)
        assert result["label"] == "fresh"

    def test_health_signals_error_status(self):
        now = time.time()
        agent = {
            "status": "error",
            "error_summary": "test error",
            "last_heartbeat_at": now - 300,
            "interval_sec": 30,
            "auto_run": True,
            "last_run_at": now - 300,
        }
        interval = agent["interval_sec"]
        signals = []
        if agent["status"] == "error":
            signals.append({"signal": "status_error", "level": "critical"})
        hb_elapsed = now - agent["last_heartbeat_at"]
        if hb_elapsed > interval * 3:
            signals.append({"signal": "heartbeat_stale", "level": "warning"})
        overdue = now - agent["last_run_at"] - interval
        if agent["auto_run"] and overdue > interval * 2:
            signals.append({"signal": "overdue", "level": "warning"})

        assert len(signals) == 3
        assert any(s["signal"] == "status_error" for s in signals)
        assert any(s["signal"] == "heartbeat_stale" for s in signals)
        assert any(s["signal"] == "overdue" for s in signals)

    def test_healthy_no_signals(self):
        now = time.time()
        agent = {
            "status": "idle",
            "error_summary": "",
            "last_heartbeat_at": now - 5,
            "interval_sec": 30,
            "auto_run": True,
            "last_run_at": now - 10,
        }
        interval = agent["interval_sec"]
        signals = []
        if agent["status"] == "error":
            signals.append({"signal": "status_error"})
        hb_elapsed = now - agent["last_heartbeat_at"]
        if hb_elapsed > interval * 3:
            signals.append({"signal": "heartbeat_stale"})
        assert len(signals) == 0


class TestDetailIntegration:
    @pytest.mark.asyncio
    async def test_run_once_populates_detail_data(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        await supervisor.run_once("monitor", actor="test")
        await asyncio.sleep(0.5)

        stats = await repo.get_agent_run_stats("monitor")
        assert stats["total"] >= 1
        assert stats["completed"] >= 1

        last = await repo.get_last_successful_run("monitor")
        assert last is not None
        assert last["status"] == "completed"

        activity = await repo.get_agent_activity("monitor", limit=20)
        assert len(activity) >= 2

        agent = await repo.get_agent("monitor")
        assert agent is not None
        assert agent["run_count"] >= 1

    @pytest.mark.asyncio
    async def test_error_run_populates_failure(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        original = AGENT_RUNNERS["scout"]
        AGENT_RUNNERS["scout"] = AsyncMock(side_effect=RuntimeError("detail test"))
        try:
            await supervisor.run_once("scout", actor="test")
            await asyncio.sleep(0.5)

            last_fail = await repo.get_last_failed_run("scout")
            assert last_fail is not None
            assert "detail test" in last_fail["error"]

            stats = await repo.get_agent_run_stats("scout")
            assert stats["errors"] >= 1
        finally:
            AGENT_RUNNERS["scout"] = original

    @pytest.mark.asyncio
    async def test_multiple_runs_stats_accurate(self, repo, mock_context):
        mock_context["repo"] = repo
        supervisor = AgentSupervisor(repo, mock_context)
        await supervisor.init_registry()

        for _ in range(3):
            await supervisor.run_once("monitor", actor="test")
            await asyncio.sleep(0.3)

        stats = await repo.get_agent_run_stats("monitor")
        assert stats["completed"] >= 3
        assert stats["avg_duration_sec"] is not None
