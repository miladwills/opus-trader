"""Agent registry, supervisor, and agent logic for AI Ops.

Agents are operational (not trading). They run deterministic,
rule-based logic inside the AI Ops process. Each agent's failure
is isolated — one broken agent does not kill the supervisor.
"""

from __future__ import annotations
import asyncio
import datetime
import logging
import time
from typing import Any

from . import config
from .models import AgentState, AuditEntry, Proposal
from .repo import Repository
from .actions import is_action_allowed

logger = logging.getLogger("aiops.agents")


# ---------------------------------------------------------------------------
# Agent logic implementations — deterministic, no LLM
# ---------------------------------------------------------------------------

async def _run_monitor(ctx: dict) -> str:
    """Monitor agent: triggers collection + triage evaluation."""
    collector = ctx.get("collector")
    engine = ctx.get("triage_engine")
    repo = ctx.get("repo")
    if not collector or not engine or not repo:
        return "Missing context"

    snapshot = await collector.collect()
    await repo.store_snapshot(snapshot)
    cases = engine.evaluate(snapshot)
    open_count = len(engine.open_cases)

    for case in cases:
        await repo.upsert_triage_case(case)

    return f"Collected snapshot, {len(cases)} cases evaluated, {open_count} open"


async def _run_scout(ctx: dict) -> str:
    """Scout agent: analyzes open triage cases for patterns and clusters."""
    repo = ctx.get("repo")
    if not repo:
        return "Missing context"

    active = await repo.get_active_cases()
    if not active:
        return "No active cases to analyze"

    # Group by category
    categories: dict[str, list] = {}
    for case in active:
        cat = case.get("category", "unknown")
        categories.setdefault(cat, []).append(case)

    clusters = []
    for cat, cases_in_cat in categories.items():
        if len(cases_in_cat) >= 2:
            clusters.append(f"{cat}: {len(cases_in_cat)} cases")

    return f"Analyzed {len(active)} cases, {len(clusters)} clusters: {', '.join(clusters) if clusters else 'none'}"


async def _run_evaluator(ctx: dict) -> str:
    """Evaluator agent: ranks active cases, creates proposals for actionable items."""
    repo = ctx.get("repo")
    if not repo:
        return "Missing context"

    active = await repo.get_active_cases()
    if not active:
        return "No active cases to evaluate"

    proposals_created = 0
    for case in active:
        # Only create proposals for high-severity cases with strong signal evidence
        if case.get("severity") in ("critical", "high") and case.get("matched_signals", 0) >= 2:
            # Check if a pending proposal already exists for this case
            existing = await repo.get_recent_proposals(limit=10, status_filter="pending")
            already_proposed = any(
                p.get("category") == case.get("rule_id") for p in existing
            )
            if already_proposed:
                continue

            seq = await repo.get_next_proposal_seq()
            date_str = datetime.date.today().strftime("%Y%m%d")
            prop = Proposal(
                proposal_id=f"PRP-{date_str}-{seq:03d}",
                title=f"Investigate: {case.get('title', 'Unknown')}",
                category=case.get("rule_id", "unknown"),
                source_agent="evaluator",
                severity=case.get("severity", "medium"),
                rationale=f"Auto-detected: {case.get('diagnosis', '')}",
                evidence_refs=[{"case_id": case.get("case_id"), "type": "triage_case"}],
                affected_components=case.get("affected_components", []),
                action_type="collect_diagnostics",
                action_params={"case_id": case.get("case_id")},
                risk_level="low",
                reversibility="reversible",
                status="candidate",
                created_at=time.time(),
            )
            await repo.create_proposal(prop)
            proposals_created += 1

    return f"Evaluated {len(active)} cases, created {proposals_created} proposal candidates"


async def _run_fix(ctx: dict) -> str:
    """Fix agent: reviews candidate proposals and prepares action plans.

    In V2, fix only proposes allowlisted operational actions — never direct fixes.
    """
    repo = ctx.get("repo")
    if not repo:
        return "Missing context"

    candidates = await repo.get_recent_proposals(limit=20, status_filter="candidate")
    if not candidates:
        return "No candidate proposals to process"

    prepared = 0
    for prop in candidates:
        action_type = prop.get("action_type", "")
        if is_action_allowed(action_type):
            await repo.update_proposal_status(
                prop["proposal_id"],
                status="pending",
                gate_verdict="pending_review",
            )
            prepared += 1
        else:
            await repo.update_proposal_status(
                prop["proposal_id"],
                status="rejected",
                gate_verdict="rejected",
                gate_reason=f"Action '{action_type}' not in allowlist",
                rejected_at=time.time(),
            )

    return f"Processed {len(candidates)} candidates, {prepared} moved to pending"


async def _run_promotion_gate(ctx: dict) -> str:
    """Promotion gate: validates pending proposals before they enter approval queue."""
    repo = ctx.get("repo")
    if not repo:
        return "Missing context"

    pending = await repo.get_recent_proposals(limit=20, status_filter="pending")
    if not pending:
        return "No pending proposals to review"

    reviewed = 0
    for prop in pending:
        verdict = "approved_for_review"
        reason = ""

        # Gate checks
        action_type = prop.get("action_type", "")
        if not is_action_allowed(action_type):
            verdict = "rejected"
            reason = f"Action '{action_type}' not allowlisted"
        elif prop.get("risk_level") == "high":
            verdict = "needs_review"
            reason = "High risk — requires manual operator review"
        else:
            reason = "Allowlisted action, low risk, approved for operator approval"

        if verdict == "rejected":
            await repo.update_proposal_status(
                prop["proposal_id"],
                gate_verdict=verdict,
                gate_reason=reason,
                status="rejected",
                rejected_at=time.time(),
            )
        else:
            await repo.update_proposal_status(
                prop["proposal_id"],
                gate_verdict=verdict,
                gate_reason=reason,
            )
        reviewed += 1

    return f"Reviewed {reviewed} proposals"


AGENT_RUNNERS: dict[str, Any] = {
    "monitor": _run_monitor,
    "scout": _run_scout,
    "evaluator": _run_evaluator,
    "fix": _run_fix,
    "promotion_gate": _run_promotion_gate,
}


# ---------------------------------------------------------------------------
# Agent Supervisor
# ---------------------------------------------------------------------------

class AgentSupervisor:
    """Manages agent lifecycle: scheduling, start/stop/pause/resume/run-once."""

    def __init__(self, repo: Repository, context: dict):
        self._repo = repo
        self._context = context  # collector, triage_engine, repo references
        self._agents: dict[str, AgentState] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._supervisor_task: asyncio.Task | None = None
        self._started = False

    @property
    def agents(self) -> dict[str, AgentState]:
        return dict(self._agents)

    async def init_registry(self):
        """Load agents from DB, seed defaults if missing."""
        existing = await self._repo.get_all_agents()
        existing_ids = {a["agent_id"] for a in existing}

        for default in config.DEFAULT_AGENTS:
            if default["agent_id"] not in existing_ids:
                agent = AgentState(
                    agent_id=default["agent_id"],
                    name=default["name"],
                    role=default["role"],
                    interval_sec=default["interval_sec"],
                    enabled=default["enabled"],
                    auto_run=default["auto_run"],
                    status="stopped",
                )
                await self._repo.upsert_agent(agent)
                self._agents[agent.agent_id] = agent
            else:
                # Load from DB
                row = next(a for a in existing if a["agent_id"] == default["agent_id"])
                agent = AgentState(**{k: v for k, v in row.items() if k in AgentState.__dataclass_fields__})
                self._agents[agent.agent_id] = agent

        logger.info("Agent registry initialized: %d agents", len(self._agents))

    async def start_supervisor(self):
        """Start the supervisor scheduling loop."""
        if self._started:
            return
        self._started = True
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(), name="agent_supervisor"
        )
        logger.info("Agent supervisor started")

    async def stop_supervisor(self):
        """Stop the supervisor and all running agents."""
        self._started = False
        if self._supervisor_task:
            self._supervisor_task.cancel()
            self._supervisor_task = None
        # Stop all running agent tasks
        for agent_id in list(self._running_tasks.keys()):
            await self._stop_agent_task(agent_id)
        logger.info("Agent supervisor stopped")

    async def _supervisor_loop(self):
        """Main loop: checks which agents need to run based on interval."""
        while self._started:
            try:
                now = time.time()
                for agent_id, agent in self._agents.items():
                    if not agent.enabled or not agent.auto_run:
                        continue
                    if agent.status == "paused":
                        continue
                    if agent.cooldown_until and now < agent.cooldown_until:
                        continue
                    # Check if it's time to run
                    last_run = agent.last_run_at or 0
                    if (now - last_run) >= agent.interval_sec:
                        if agent_id not in self._running_tasks or self._running_tasks[agent_id].done():
                            asyncio.create_task(self._execute_agent(agent_id))
            except Exception as exc:
                logger.error("Supervisor loop error: %s", exc)

            await asyncio.sleep(config.SUPERVISOR_TICK_SEC)

    async def _execute_agent(self, agent_id: str):
        """Execute a single agent run with full lifecycle tracking."""
        agent = self._agents.get(agent_id)
        if not agent:
            return

        runner = AGENT_RUNNERS.get(agent_id)
        if not runner:
            logger.warning("No runner for agent %s", agent_id)
            return

        run_id = await self._repo.record_agent_run_start(agent_id)
        now = time.time()

        agent.status = "running"
        agent.last_started_at = now
        agent.last_heartbeat_at = now
        agent.current_task = f"Run #{agent.run_count + 1}"
        await self._repo.upsert_agent(agent)

        try:
            result = await asyncio.wait_for(runner(self._context), timeout=60)
            agent.last_result_summary = result or ""
            agent.error_summary = ""
            agent.status = "idle"
            agent.run_count += 1
            agent.last_run_at = time.time()
            agent.current_task = ""
            await self._repo.record_agent_run_end(run_id, "completed", result or "")
        except asyncio.TimeoutError:
            agent.status = "error"
            agent.error_summary = "Execution timed out (60s)"
            agent.current_task = ""
            await self._repo.record_agent_run_end(run_id, "error", error="Timeout after 60s")
        except Exception as exc:
            agent.status = "error"
            agent.error_summary = str(exc)[:200]
            agent.current_task = ""
            logger.error("Agent %s error: %s", agent_id, exc, exc_info=True)
            await self._repo.record_agent_run_end(run_id, "error", error=str(exc)[:500])

        agent.last_heartbeat_at = time.time()
        await self._repo.upsert_agent(agent)

    async def _stop_agent_task(self, agent_id: str):
        task = self._running_tasks.pop(agent_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # --- Operator controls ---

    async def start_agent(self, agent_id: str, actor: str = "operator") -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found"
        if agent.status == "running":
            return f"Agent '{agent_id}' already running"

        agent.enabled = True
        agent.auto_run = True
        agent.status = "idle"
        agent.error_summary = ""
        agent.last_started_at = time.time()
        await self._repo.upsert_agent(agent)
        await self._audit(actor, "agent_started", "agent", agent_id)
        return f"Agent '{agent_id}' started"

    async def stop_agent(self, agent_id: str, actor: str = "operator") -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found"

        await self._stop_agent_task(agent_id)
        agent.status = "stopped"
        agent.auto_run = False
        agent.current_task = ""
        agent.last_stopped_at = time.time()
        await self._repo.upsert_agent(agent)
        await self._audit(actor, "agent_stopped", "agent", agent_id)
        return f"Agent '{agent_id}' stopped"

    async def pause_agent(self, agent_id: str, actor: str = "operator") -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found"
        if agent.status not in ("running", "idle"):
            return f"Agent '{agent_id}' cannot be paused (status: {agent.status})"

        agent.status = "paused"
        agent.current_task = ""
        await self._repo.upsert_agent(agent)
        await self._audit(actor, "agent_paused", "agent", agent_id)
        return f"Agent '{agent_id}' paused"

    async def resume_agent(self, agent_id: str, actor: str = "operator") -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found"
        if agent.status != "paused":
            return f"Agent '{agent_id}' is not paused (status: {agent.status})"

        agent.status = "idle"
        await self._repo.upsert_agent(agent)
        await self._audit(actor, "agent_resumed", "agent", agent_id)
        return f"Agent '{agent_id}' resumed"

    async def run_once(self, agent_id: str, actor: str = "operator") -> str:
        agent = self._agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found"
        if agent_id in self._running_tasks and not self._running_tasks[agent_id].done():
            return f"Agent '{agent_id}' already has a run in progress"

        await self._audit(actor, "agent_run_once", "agent", agent_id)
        task = asyncio.create_task(self._execute_agent(agent_id))
        self._running_tasks[agent_id] = task
        return f"Agent '{agent_id}' run-once triggered"

    async def restart_agent(self, agent_id: str, actor: str = "operator") -> str:
        await self.stop_agent(agent_id, actor=actor)
        return await self.start_agent(agent_id, actor=actor)

    async def start_all_enabled(self, actor: str = "operator") -> str:
        results = []
        for agent_id, agent in self._agents.items():
            if agent.enabled and agent.status != "running":
                r = await self.start_agent(agent_id, actor=actor)
                results.append(r)
        return f"Started {len(results)} agents"

    async def stop_all(self, actor: str = "operator") -> str:
        results = []
        for agent_id in list(self._agents.keys()):
            r = await self.stop_agent(agent_id, actor=actor)
            results.append(r)
        return f"Stopped {len(results)} agents"

    async def pause_all(self, actor: str = "operator") -> str:
        results = []
        for agent_id, agent in self._agents.items():
            if agent.status in ("running", "idle"):
                r = await self.pause_agent(agent_id, actor=actor)
                results.append(r)
        return f"Paused {len(results)} agents"

    async def _audit(self, actor: str, action: str, target_type: str, target_id: str, detail: dict | None = None):
        seq = await self._repo.get_next_audit_seq()
        date_str = datetime.date.today().strftime("%Y%m%d")
        await self._repo.create_audit_entry(AuditEntry(
            entry_id=f"AUD-{date_str}-{seq:04d}",
            timestamp=time.time(),
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        ))
