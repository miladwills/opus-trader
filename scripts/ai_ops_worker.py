#!/usr/bin/env python3
"""
AI Ops Worker — Subprocess wrapper for Claude Code agent runs.

Launched by ai_ops_orchestrator.py. Manages a single agent run:
- Launches claude CLI with the appropriate skill
- Writes heartbeat file periodically
- Checks for stop-request file
- Captures output to log file
- Exits cleanly on stop or timeout
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKILL_MAP = {
    "monitor": "monitor-live",
    "fixer": "fix-queue",
    "gate": "gate-review",
    "deploy": "deploy-approved",
    "scout": "scout-ideas",
    "evaluator": "evaluate-ideas",
    "planner": "plan-approved-ideas",
    "implementer": "implement-approved-ideas",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def write_heartbeat(slug, run_id, status="running"):
    path = os.path.join(PROJECT_ROOT, "storage", f"ai_ops_heartbeat_{slug}.json")
    try:
        with open(path, "w") as f:
            json.dump({
                "slug": slug,
                "run_id": run_id,
                "status": status,
                "heartbeat_at": now_iso(),
                "pid": os.getpid(),
            }, f)
    except OSError:
        pass


def check_stop_requested(slug):
    path = os.path.join(PROJECT_ROOT, "storage", f"ai_ops_stop_{slug}")
    return os.path.isfile(path)


def main():
    if len(sys.argv) < 3:
        print("Usage: ai_ops_worker.py <agent_slug> <run_id> [timeout_seconds]", file=sys.stderr)
        sys.exit(1)

    slug = sys.argv[1]
    run_id = sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 14400
    model = sys.argv[4] if len(sys.argv) > 4 else "sonnet"

    skill = SKILL_MAP.get(slug)
    if not skill:
        print(f"Unknown agent slug: {slug}", file=sys.stderr)
        sys.exit(1)

    effort = sys.argv[5] if len(sys.argv) > 5 else "high"

    # Build claude command with stream-json for live output
    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--model", model,
        "--effort", effort,
        "--no-session-persistence",
        "--verbose",
        "--output-format", "stream-json",
        "-p", f"/{skill}",
    ]

    def log(msg):
        ts = now_iso()[:19]
        sys.stdout.write(f"[{ts}] {msg}\n")
        sys.stdout.flush()

    write_heartbeat(slug, run_id, "starting")
    log(f"Starting {slug} agent (model={model}, effort={effort})")

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        start_time = time.time()
        write_heartbeat(slug, run_id, "running")
        log(f"Agent process started (PID {proc.pid})")

        # Reader thread: parse stream-json events into human-readable log lines
        import threading
        line_count = [0]
        def _reader():
            try:
                for raw_line in proc.stdout:
                    text = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    if not text:
                        continue
                    line_count[0] += 1
                    # Try to parse stream-json event for readable output
                    readable = _parse_stream_event(text)
                    if readable:
                        log(readable)
            except (IOError, ValueError):
                pass
        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        while proc.poll() is None:
            # Check stop request
            if check_stop_requested(slug):
                log("Stop requested — terminating agent")
                write_heartbeat(slug, run_id, "stopping")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                proc.wait(timeout=30)
                write_heartbeat(slug, run_id, "stopped")
                log("Agent stopped by operator")
                sys.exit(0)

            # Check timeout
            if time.time() - start_time > timeout:
                log(f"Timeout after {timeout}s — terminating agent")
                write_heartbeat(slug, run_id, "timeout")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                proc.wait(timeout=30)
                sys.exit(1)

            # Heartbeat
            write_heartbeat(slug, run_id, "running")
            time.sleep(5)

        # Wait for reader to finish
        reader_thread.join(timeout=5)

        exit_code = proc.returncode
        log(f"Agent exited with code {exit_code} ({line_count[0]} events)")
        write_heartbeat(slug, run_id, "completed" if exit_code == 0 else "failed")
        sys.exit(exit_code or 0)

    except Exception as exc:
        print(f"Worker error: {exc}", file=sys.stderr)
        write_heartbeat(slug, run_id, "failed")
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        sys.exit(1)


def _parse_stream_event(raw_json):
    """Parse a stream-json line into a human-readable log message."""
    try:
        event = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None

    etype = event.get("type", "")

    # System/init messages
    if etype == "system":
        return f"[system] {event.get('message', '')}"[:200]

    # Assistant text output
    if etype == "assistant":
        msg = event.get("message", "")
        if isinstance(msg, dict):
            content = msg.get("content", [])
            parts = []
            for block in (content if isinstance(content, list) else []):
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", "")[:300])
                    elif block.get("type") == "tool_use":
                        tool = block.get("name", "?")
                        parts.append(f"[tool: {tool}]")
            if parts:
                return " ".join(parts)[:500]
        return None

    # Tool results
    if etype == "result":
        cost = event.get("cost_usd")
        duration = event.get("duration_ms")
        turns = event.get("num_turns")
        parts = []
        if turns: parts.append(f"{turns} turns")
        if cost: parts.append(f"${cost:.4f}")
        if duration: parts.append(f"{duration/1000:.1f}s")
        if parts:
            return f"[result] {', '.join(parts)}"
        return None

    # Tool use events
    if etype == "tool_use":
        tool = event.get("name", event.get("tool", "?"))
        return f"[using: {tool}]"

    # Content block delta (streaming text)
    if etype == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if len(text) > 80:
                return text[:80] + "..."
            return text if text.strip() else None
        return None

    return None


if __name__ == "__main__":
    main()
