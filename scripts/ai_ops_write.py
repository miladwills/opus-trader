#!/usr/bin/env python3
"""
AI Ops Structured Write Path — CLI for workflow agents.

All agents must use this tool instead of writing directly to JSONL files.
Provides validation, ID management, status-transition enforcement, and locking.

Usage:
    python scripts/ai_ops_write.py create-incident --severity high --category execution --summary "..."
    python scripts/ai_ops_write.py update-incident MON-042 --status fixed --changed-files a.py,b.py
    python scripts/ai_ops_write.py create-idea --title "..." --theme execution --expected-impact high
    python scripts/ai_ops_write.py update-idea SCOUT-020 --evaluator-status APPROVED_HIGH_PRIORITY
"""

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Paths (relative to project root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES_PATH = os.path.join(PROJECT_ROOT, "issues_queue.jsonl")
IDEAS_PATH = os.path.join(PROJECT_ROOT, "development_ideas.jsonl")

# ---- Enum constants ----

VALID_SEVERITIES = ("critical", "high", "medium", "low")
VALID_CATEGORIES = (
    "state", "execution", "risk", "latency", "config", "logic",
    "diagnostics", "process", "runtime_pattern", "integrity",
    "watchdog", "code_review", "readiness", "margin", "sizing",
    "router", "deploy", "ui", "visibility", "workflow", "other",
)
VALID_INCIDENT_SOURCES = ("operator", "monitor", "system")
VALID_TRIAGE_STATUSES = ("awaiting_triage", "confirmed", "duplicate", "rejected", "needs_more_evidence")
VALID_PRIORITIES = ("P1", "P2", "P3", "P4")
VALID_ISSUE_STATUSES = (
    "open", "investigating", "root_cause_confirmed", "fix_in_progress",
    "fixed", "reviewed", "approved", "dashboard_approved",
    "rejected", "closed",
)
VALID_GATE_VERDICTS = (
    "REJECT", "NEEDS_MORE_EVIDENCE", "NEEDS_MORE_VALIDATION",
    "APPROVE_PAPER_ONLY", "APPROVE_SHADOW_ONLY",
    "APPROVE_FOR_HUMAN_REVIEW",
    "APPROVE_FOR_STAGED_PRODUCTION_AFTER_HUMAN_APPROVAL",
)
VALID_CONFIDENCES = ("high", "medium", "low")
VALID_IMPACTS = ("critical", "high", "medium", "low", "none", "unknown")
VALID_IDEA_THEMES = (
    "execution", "risk", "grid", "readiness", "sizing", "diagnostics",
    "analytics", "state", "ui", "operator_control",
)
VALID_IDEA_STATUSES = (
    "candidate", "APPROVED_HIGH_PRIORITY", "APPROVED_MEDIUM_PRIORITY",
    "APPROVED_LOW_PRIORITY", "DEFERRED", "REJECTED", "REDUNDANT",
    "NEEDS_MORE_EVIDENCE", "FUTURE_ROADMAP",
)
VALID_RECOMMENDATIONS = (
    "pursue_now", "pursue_later", "needs_more_evidence", "reject",
)

# ---- Status transition rules ----

ALLOWED_TRANSITIONS = {
    "open": ("investigating", "root_cause_confirmed", "fix_in_progress", "closed"),
    "investigating": ("root_cause_confirmed", "fix_in_progress", "closed"),
    "root_cause_confirmed": ("fix_in_progress", "closed"),
    "fix_in_progress": ("fixed", "closed"),
    "fixed": ("reviewed", "closed"),
    "reviewed": ("approved", "rejected", "closed"),
    "approved": ("dashboard_approved", "closed"),
    "dashboard_approved": ("closed",),
    "rejected": ("closed",),
    "closed": (),
}


# ---- JSONL helpers ----

def read_jsonl_deduped(path: str, id_field: str) -> Dict[str, Dict[str, Any]]:
    """Read JSONL, return dict keyed by id_field (merged, latest wins)."""
    records: Dict[str, Dict[str, Any]] = {}
    if not os.path.isfile(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                rid = obj.get(id_field)
                if rid:
                    if rid in records:
                        records[rid].update(obj)
                    else:
                        records[rid] = obj
            except (json.JSONDecodeError, TypeError):
                continue
    return records


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    """Append a record to a JSONL file with file locking."""
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def next_id(records: Dict[str, Dict], prefix: str) -> str:
    """Compute next sequential ID like MON-042 or SCOUT-028."""
    pattern = re.compile(rf"^{prefix}-(\d+)$")
    max_num = 0
    for rid in records:
        m = pattern.match(rid)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{max_num + 1:03d}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_ok(record_id: str, status: str, ts: str) -> None:
    print(json.dumps({"ok": True, "id": record_id, "status": status, "updated_at": ts}))
    sys.exit(0)


def result_error(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


# ---- Commands ----

def cmd_create_incident(args):
    """Create a new incident in issues_queue.jsonl."""
    if args.severity not in VALID_SEVERITIES:
        result_error(f"Invalid severity '{args.severity}'. Must be one of: {', '.join(VALID_SEVERITIES)}")
    if args.category not in VALID_CATEGORIES:
        result_error(f"Invalid category '{args.category}'. Must be one of: {', '.join(VALID_CATEGORIES)}")

    records = read_jsonl_deduped(ISSUES_PATH, "issue_id")
    new_id = next_id(records, "MON")
    ts = now_iso()

    record = {
        "issue_id": new_id,
        "created_at": ts,
        "updated_at": ts,
        "status": "open",
        "severity": args.severity,
        "category": args.category,
        "summary": args.summary,
        "symptom": args.symptom or args.summary,
        "affected_bot_ids": [b.strip() for b in args.affected_bots.split(",") if b.strip()] if args.affected_bots else [],
        "symbols": [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else [],
        "evidence": [e.strip() for e in args.evidence.split("|") if e.strip()] if args.evidence else [],
        "suspected_root_cause": args.suspected_root_cause or "",
        "root_cause_confidence": args.root_cause_confidence or "low",
        "profit_impact": args.profit_impact or "unknown",
        "safety_impact": args.safety_impact or "unknown",
        "operator_truthfulness_impact": args.operator_truthfulness_impact or "none",
        "auto_fix_allowed": args.auto_fix_allowed,
        "fix_scope_hint": args.fix_scope_hint or args.category,
        "notes_for_fixer": args.notes_for_fixer or "",
    }

    if record["root_cause_confidence"] not in VALID_CONFIDENCES:
        result_error(f"Invalid root_cause_confidence. Must be one of: {', '.join(VALID_CONFIDENCES)}")

    # Operator-reported incident fields
    source = getattr(args, "incident_source", None)
    if source:
        if source not in VALID_INCIDENT_SOURCES:
            result_error(f"Invalid incident_source '{source}'. Must be one of: {', '.join(VALID_INCIDENT_SOURCES)}")
        record["incident_source"] = source
    if getattr(args, "operator_reported", False):
        record["operator_reported"] = True
        record["incident_source"] = record.get("incident_source", "operator")
    if getattr(args, "operator_severity", None):
        record["operator_severity"] = args.operator_severity
    if getattr(args, "operator_priority", None):
        if args.operator_priority not in VALID_PRIORITIES:
            result_error(f"Invalid operator_priority. Must be one of: {', '.join(VALID_PRIORITIES)}")
        record["operator_priority"] = args.operator_priority
    if getattr(args, "triage_status", None):
        if args.triage_status not in VALID_TRIAGE_STATUSES:
            result_error(f"Invalid triage_status. Must be one of: {', '.join(VALID_TRIAGE_STATUSES)}")
        record["triage_status"] = args.triage_status
    if getattr(args, "urgent_review", False):
        record["urgent_review_requested"] = True
    if getattr(args, "pinned", False):
        record["pinned_by_operator"] = True
    if getattr(args, "operator_notes", None):
        record["operator_notes"] = args.operator_notes
    if getattr(args, "duplicate_of", None):
        record["duplicate_of"] = args.duplicate_of

    append_jsonl(ISSUES_PATH, record)
    result_ok(new_id, "open", ts)


def cmd_update_incident(args):
    """Update an existing incident."""
    records = read_jsonl_deduped(ISSUES_PATH, "issue_id")
    issue_id = args.issue_id
    if issue_id not in records:
        result_error(f"Issue '{issue_id}' not found")

    current = records[issue_id]
    current_status = current.get("status", "open")
    ts = now_iso()
    update: Dict[str, Any] = {"issue_id": issue_id, "updated_at": ts}

    # Status transition
    if args.status:
        new_status = args.status
        if new_status not in VALID_ISSUE_STATUSES:
            result_error(f"Invalid status '{new_status}'. Must be one of: {', '.join(VALID_ISSUE_STATUSES)}")
        if new_status != current_status:
            allowed = ALLOWED_TRANSITIONS.get(current_status, ())
            if new_status not in allowed and new_status != "closed":
                result_error(
                    f"Invalid transition: {current_status} -> {new_status}. "
                    f"Allowed: {', '.join(allowed) if allowed else 'none (terminal)'}"
                )
        update["status"] = new_status

    # Optional fields
    if args.severity:
        if args.severity not in VALID_SEVERITIES:
            result_error(f"Invalid severity '{args.severity}'")
        update["severity"] = args.severity
    if args.confirmed_root_cause:
        update["confirmed_root_cause"] = args.confirmed_root_cause
    if args.changed_files:
        update["changed_files"] = [f.strip() for f in args.changed_files.split(",") if f.strip()]
    if args.branch:
        update["branch_name"] = args.branch
    if args.validation_run:
        update["validation_run"] = args.validation_run
    if args.focused_test_results:
        update["focused_test_results"] = args.focused_test_results
    if args.replay_or_shadow:
        update["replay_or_shadow_results"] = args.replay_or_shadow
    if args.regression_risk:
        update["regression_risk"] = args.regression_risk
    if args.rollback_plan:
        update["rollback_plan"] = args.rollback_plan
    if args.approved_scope:
        update["approved_scope"] = args.approved_scope
    if args.additional_validation:
        update["additional_validation_required"] = args.additional_validation
    if args.fixer_summary:
        update["fixer_summary"] = args.fixer_summary
    if args.reviewer_summary:
        update["reviewer_summary"] = args.reviewer_summary
    if args.gate_verdict:
        if args.gate_verdict not in VALID_GATE_VERDICTS:
            result_error(f"Invalid gate verdict '{args.gate_verdict}'. Must be one of: {', '.join(VALID_GATE_VERDICTS)}")
        update["promotion_gate_status"] = args.gate_verdict
    if args.gate_reason:
        update["promotion_gate_reason"] = args.gate_reason

    append_jsonl(ISSUES_PATH, update)
    result_ok(issue_id, update.get("status", current_status), ts)


def cmd_create_idea(args):
    """Create a new idea in development_ideas.jsonl."""
    if args.theme not in VALID_IDEA_THEMES:
        result_error(f"Invalid theme '{args.theme}'. Must be one of: {', '.join(VALID_IDEA_THEMES)}")
    if args.expected_impact not in VALID_SEVERITIES:
        result_error(f"Invalid expected_impact '{args.expected_impact}'. Must be one of: {', '.join(VALID_SEVERITIES)}")

    records = read_jsonl_deduped(IDEAS_PATH, "idea_id")
    new_id = next_id(records, "SCOUT")
    ts = now_iso()

    record = {
        "idea_id": new_id,
        "created_at": ts,
        "updated_at": ts,
        "status": "candidate",
        "title": args.title,
        "theme": args.theme,
        "problem_detected": args.problem or "",
        "proposed_improvement": args.proposed_improvement or "",
        "expected_value": args.expected_value or "multi-benefit",
        "expected_impact": args.expected_impact,
        "implementation_cost": args.implementation_cost or "medium",
        "risk_level": args.risk_level or "medium",
        "affected_areas": [a.strip() for a in args.affected_areas.split(",") if a.strip()] if args.affected_areas else [],
        "evidence": [e.strip() for e in args.evidence.split("|") if e.strip()] if args.evidence else [],
        "why_now": args.why_now or "",
        "notes_for_evaluator": args.notes_for_evaluator or "",
    }

    append_jsonl(IDEAS_PATH, record)
    result_ok(new_id, "candidate", ts)


def cmd_update_idea(args):
    """Update an existing idea."""
    records = read_jsonl_deduped(IDEAS_PATH, "idea_id")
    idea_id = args.idea_id
    if idea_id not in records:
        result_error(f"Idea '{idea_id}' not found")

    ts = now_iso()
    update: Dict[str, Any] = {"idea_id": idea_id, "updated_at": ts}

    if args.evaluator_status:
        if args.evaluator_status not in VALID_IDEA_STATUSES:
            result_error(f"Invalid evaluator_status '{args.evaluator_status}'")
        update["status"] = args.evaluator_status
        update["evaluator_status"] = args.evaluator_status
    if args.evaluator_summary:
        update["evaluator_summary"] = args.evaluator_summary
    if args.evaluator_confidence:
        update["evaluator_confidence"] = args.evaluator_confidence
    if args.priority_score is not None:
        update["priority_score"] = max(1, min(10, args.priority_score))
    if args.value_score is not None:
        update["value_score"] = max(1, min(10, args.value_score))
    if args.complexity_score is not None:
        update["complexity_score"] = max(1, min(10, args.complexity_score))
    if args.risk_score is not None:
        update["risk_score"] = max(1, min(10, args.risk_score))
    if args.recommendation:
        if args.recommendation not in VALID_RECOMMENDATIONS:
            result_error(f"Invalid recommendation '{args.recommendation}'")
        update["recommendation"] = args.recommendation
    if args.implementation_shape:
        update["implementation_shape"] = args.implementation_shape
    if args.next_step:
        update["next_step"] = args.next_step

    append_jsonl(IDEAS_PATH, update)
    result_ok(idea_id, update.get("status", records[idea_id].get("status", "candidate")), ts)


# ---- Argument parser ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Ops structured write path")
    sub = parser.add_subparsers(dest="command")

    # create-incident
    ci = sub.add_parser("create-incident", help="Create new incident")
    ci.add_argument("--severity", required=True)
    ci.add_argument("--category", required=True)
    ci.add_argument("--summary", required=True)
    ci.add_argument("--symptom")
    ci.add_argument("--symbols")
    ci.add_argument("--affected-bots")
    ci.add_argument("--evidence")
    ci.add_argument("--suspected-root-cause")
    ci.add_argument("--root-cause-confidence")
    ci.add_argument("--profit-impact")
    ci.add_argument("--safety-impact")
    ci.add_argument("--operator-truthfulness-impact")
    ci.add_argument("--auto-fix-allowed", action="store_true", default=False)
    ci.add_argument("--fix-scope-hint")
    ci.add_argument("--notes-for-fixer")
    ci.add_argument("--incident-source")
    ci.add_argument("--operator-reported", action="store_true", default=False)
    ci.add_argument("--operator-severity")
    ci.add_argument("--operator-priority")
    ci.add_argument("--triage-status")
    ci.add_argument("--urgent-review", action="store_true", default=False)
    ci.add_argument("--pinned", action="store_true", default=False)
    ci.add_argument("--operator-notes")
    ci.add_argument("--duplicate-of")

    # update-incident
    ui = sub.add_parser("update-incident", help="Update existing incident")
    ui.add_argument("issue_id")
    ui.add_argument("--status")
    ui.add_argument("--severity")
    ui.add_argument("--confirmed-root-cause")
    ui.add_argument("--changed-files")
    ui.add_argument("--branch")
    ui.add_argument("--validation-run")
    ui.add_argument("--focused-test-results")
    ui.add_argument("--replay-or-shadow")
    ui.add_argument("--regression-risk")
    ui.add_argument("--rollback-plan")
    ui.add_argument("--approved-scope")
    ui.add_argument("--additional-validation")
    ui.add_argument("--fixer-summary")
    ui.add_argument("--reviewer-summary")
    ui.add_argument("--gate-verdict")
    ui.add_argument("--gate-reason")

    # create-idea
    cid = sub.add_parser("create-idea", help="Create new idea")
    cid.add_argument("--title", required=True)
    cid.add_argument("--theme", required=True)
    cid.add_argument("--expected-impact", required=True)
    cid.add_argument("--problem")
    cid.add_argument("--proposed-improvement")
    cid.add_argument("--expected-value")
    cid.add_argument("--implementation-cost")
    cid.add_argument("--risk-level")
    cid.add_argument("--affected-areas")
    cid.add_argument("--evidence")
    cid.add_argument("--why-now")
    cid.add_argument("--notes-for-evaluator")

    # update-idea
    uid = sub.add_parser("update-idea", help="Update existing idea")
    uid.add_argument("idea_id")
    uid.add_argument("--evaluator-status")
    uid.add_argument("--evaluator-summary")
    uid.add_argument("--evaluator-confidence")
    uid.add_argument("--priority-score", type=int)
    uid.add_argument("--value-score", type=int)
    uid.add_argument("--complexity-score", type=int)
    uid.add_argument("--risk-score", type=int)
    uid.add_argument("--recommendation")
    uid.add_argument("--implementation-shape")
    uid.add_argument("--next-step")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "create-incident":
        cmd_create_incident(args)
    elif args.command == "update-incident":
        cmd_update_incident(args)
    elif args.command == "create-idea":
        cmd_create_idea(args)
    elif args.command == "update-idea":
        cmd_update_idea(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
