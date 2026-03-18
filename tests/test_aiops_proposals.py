"""Tests for AI Ops proposal workflow, approval, and action bridge."""

import time
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock

from opus_aiops.models import Proposal, ActionExecution
from opus_aiops.repo import Repository
from opus_aiops.proposals import approve_proposal, reject_proposal
from opus_aiops.actions import (
    is_action_allowed,
    ALLOWED_ACTIONS,
    FORBIDDEN_PREFIXES,
    execute_action,
)
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
    return {
        "collector": MagicMock(
            latest_snapshot=MagicMock(
                health_score=95.0, health_status="healthy",
                source_errors={}, bridge_stale_count=0,
                bridge_stale_sections=[], active_incidents=[],
                runner_active=True, collection_timing={},
                timestamp=time.time(),
            ),
            collect=AsyncMock(return_value=MagicMock(health_score=95.0)),
            _last_fast=time.time(),
            _last_medium=time.time(),
        ),
        "triage_engine": MagicMock(
            evaluate=MagicMock(return_value=[]),
            open_cases=[],
        ),
    }


class TestActionAllowlist:
    def test_allowed_actions_defined(self):
        assert "refresh_collection" in ALLOWED_ACTIONS
        assert "rerun_triage" in ALLOWED_ACTIONS
        assert "collect_diagnostics" in ALLOWED_ACTIONS
        assert "refresh_probes" in ALLOWED_ACTIONS
        assert "recheck_health" in ALLOWED_ACTIONS
        assert "mark_manual_followup" in ALLOWED_ACTIONS
        assert "export_evidence" in ALLOWED_ACTIONS

    def test_allowed_returns_true(self):
        for action_type in ALLOWED_ACTIONS:
            assert is_action_allowed(action_type) is True

    def test_forbidden_rejected(self):
        forbidden = [
            "order_place", "cancel_order", "close_position",
            "bot_start_abc", "bot_stop_xyz",
            "config_mutate_setting", "storage_write_file",
            "exchange_call", "trader_restart", "runner_restart",
            "position_close",
        ]
        for action_type in forbidden:
            assert is_action_allowed(action_type) is False, f"{action_type} should be forbidden"

    def test_unknown_rejected(self):
        assert is_action_allowed("random_unknown_action") is False


class TestActionExecution:
    @pytest.mark.asyncio
    async def test_execute_allowed_action(self, mock_context):
        result = await execute_action("refresh_collection", {}, mock_context)
        assert result["status"] == "completed"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execute_forbidden_action(self, mock_context):
        result = await execute_action("order_place", {}, mock_context)
        assert result["status"] == "failed"
        assert "not in the allowlist" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_rerun_triage(self, mock_context):
        result = await execute_action("rerun_triage", {}, mock_context)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_collect_diagnostics(self, mock_context):
        result = await execute_action("collect_diagnostics", {}, mock_context)
        assert result["status"] == "completed"
        assert "Diagnostics" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_export_evidence(self, mock_context):
        result = await execute_action("export_evidence", {}, mock_context)
        assert result["status"] == "completed"
        assert "Evidence exported" in result["result"]


class TestProposalCreation:
    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, repo):
        prop = Proposal(
            proposal_id="PRP-20260318-001",
            title="Test proposal",
            category="test",
            source_agent="evaluator",
            severity="medium",
            rationale="Testing",
            action_type="refresh_collection",
            action_params={},
            risk_level="low",
            reversibility="reversible",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        loaded = await repo.get_proposal("PRP-20260318-001")
        assert loaded is not None
        assert loaded["title"] == "Test proposal"
        assert loaded["status"] == "pending"

    @pytest.mark.asyncio
    async def test_pending_proposals(self, repo):
        for i in range(3):
            prop = Proposal(
                proposal_id=f"PRP-20260318-{i:03d}",
                title=f"Proposal {i}",
                category="test",
                source_agent="evaluator",
                action_type="refresh_collection",
                status="pending",
                created_at=time.time() - (3 - i),
            )
            await repo.create_proposal(prop)

        pending = await repo.get_pending_proposals()
        assert len(pending) == 3

    @pytest.mark.asyncio
    async def test_proposal_stats(self, repo):
        for status in ["pending", "pending", "approved", "rejected"]:
            prop = Proposal(
                proposal_id=f"PRP-TEST-{status}-{time.time()}",
                title=f"Test {status}",
                category="test",
                source_agent="test",
                action_type="refresh_collection",
                status=status,
                created_at=time.time(),
            )
            await repo.create_proposal(prop)

        stats = await repo.get_proposal_stats()
        assert stats.get("pending") == 2
        assert stats.get("approved") == 1
        assert stats.get("rejected") == 1


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_approve_executes_action(self, repo, mock_context):
        mock_context["repo"] = repo
        prop = Proposal(
            proposal_id="PRP-APPROVE-001",
            title="Test approval",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            action_params={},
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        result = await approve_proposal("PRP-APPROVE-001", "testuser", repo, mock_context)
        assert result["ok"] is True
        assert result["execution_status"] == "completed"

        # Check proposal status
        loaded = await repo.get_proposal("PRP-APPROVE-001")
        assert loaded["status"] == "executed"
        assert loaded["approved_by"] == "testuser"
        assert loaded["approved_at"] is not None
        assert loaded["execution_finished_at"] is not None

    @pytest.mark.asyncio
    async def test_approve_forbidden_action_rejected(self, repo, mock_context):
        mock_context["repo"] = repo
        prop = Proposal(
            proposal_id="PRP-FORBIDDEN-001",
            title="Forbidden action",
            category="test",
            source_agent="evaluator",
            action_type="order_place",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        result = await approve_proposal("PRP-FORBIDDEN-001", "testuser", repo, mock_context)
        assert result["ok"] is False
        assert "not in allowlist" in result["error"]

    @pytest.mark.asyncio
    async def test_approve_nonexistent(self, repo, mock_context):
        result = await approve_proposal("PRP-NONE-001", "testuser", repo, mock_context)
        assert result["ok"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_approve_already_approved(self, repo, mock_context):
        mock_context["repo"] = repo
        prop = Proposal(
            proposal_id="PRP-DUP-001",
            title="Already done",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            status="approved",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        result = await approve_proposal("PRP-DUP-001", "testuser", repo, mock_context)
        assert result["ok"] is False
        assert "not pending" in result["error"]

    @pytest.mark.asyncio
    async def test_reject(self, repo):
        prop = Proposal(
            proposal_id="PRP-REJECT-001",
            title="To reject",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        result = await reject_proposal("PRP-REJECT-001", "testuser", "Not needed", repo)
        assert result["ok"] is True

        loaded = await repo.get_proposal("PRP-REJECT-001")
        assert loaded["status"] == "rejected"
        assert loaded["rejected_by"] == "testuser"

    @pytest.mark.asyncio
    async def test_reject_already_rejected(self, repo):
        prop = Proposal(
            proposal_id="PRP-DUP-REJ-001",
            title="Already rejected",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            status="rejected",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)

        result = await reject_proposal("PRP-DUP-REJ-001", "testuser", "reason", repo)
        assert result["ok"] is False


class TestAuditTrailForProposals:
    @pytest.mark.asyncio
    async def test_approve_creates_audit(self, repo, mock_context):
        mock_context["repo"] = repo
        prop = Proposal(
            proposal_id="PRP-AUD-001",
            title="Audit test",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)
        await approve_proposal("PRP-AUD-001", "audituser", repo, mock_context)

        audit = await repo.get_audit_log(limit=10)
        actions = [e["action"] for e in audit]
        assert "proposal_approved" in actions
        assert "proposal_executed" in actions

        # Check actor
        approved = next(e for e in audit if e["action"] == "proposal_approved")
        assert approved["actor"] == "audituser"

    @pytest.mark.asyncio
    async def test_reject_creates_audit(self, repo):
        prop = Proposal(
            proposal_id="PRP-AUD-REJ-001",
            title="Reject audit",
            category="test",
            source_agent="evaluator",
            action_type="refresh_collection",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)
        await reject_proposal("PRP-AUD-REJ-001", "rejectuser", "test reason", repo)

        audit = await repo.get_audit_log(limit=10)
        actions = [e["action"] for e in audit]
        assert "proposal_rejected" in actions


class TestNoTraderMutation:
    """Verify no direct trader mutation path exists."""

    def test_no_trader_write_actions(self):
        for action_type in ALLOWED_ACTIONS:
            info = ALLOWED_ACTIONS[action_type]
            assert info.get("risk") in ("none", "low", None), \
                f"Action {action_type} has unexpected risk level"

    def test_forbidden_prefixes_comprehensive(self):
        dangerous = [
            "order_", "cancel_", "close_", "bot_start", "bot_stop",
            "config_mutate", "storage_write", "exchange_",
            "position_",
        ]
        for prefix in dangerous:
            assert prefix in FORBIDDEN_PREFIXES, f"Missing forbidden prefix: {prefix}"

    @pytest.mark.asyncio
    async def test_execution_records_persisted(self, repo, mock_context):
        mock_context["repo"] = repo
        prop = Proposal(
            proposal_id="PRP-EXEC-001",
            title="Exec test",
            category="test",
            source_agent="evaluator",
            action_type="collect_diagnostics",
            status="pending",
            created_at=time.time(),
        )
        await repo.create_proposal(prop)
        await approve_proposal("PRP-EXEC-001", "testuser", repo, mock_context)

        execs = await repo.get_recent_executions(limit=5)
        assert len(execs) >= 1
        assert execs[0]["action_type"] == "collect_diagnostics"
        assert execs[0]["status"] == "completed"
