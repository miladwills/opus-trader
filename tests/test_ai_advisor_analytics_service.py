from pathlib import Path

import config.strategy_config as strategy_cfg
from services.ai_advisor_analytics_service import AIAdvisorAnalyticsService


class StubAuditDiagnosticsService:
    def __init__(self, events_by_type):
        self.events_by_type = {
            key: list(value or []) for key, value in (events_by_type or {}).items()
        }

    def get_recent_events(
        self,
        *,
        event_type=None,
        since_seconds=None,
        bot_id=None,
        symbol=None,
        limit=200,
    ):
        records = list(self.events_by_type.get(event_type, []))
        if bot_id:
            records = [
                item for item in records if str(item.get("bot_id") or "").strip() == str(bot_id)
            ]
        if symbol:
            normalized_symbol = str(symbol or "").strip().upper()
            records = [
                item
                for item in records
                if str(item.get("symbol") or "").strip().upper() == normalized_symbol
            ]
        if limit and len(records) > limit:
            return records[-limit:]
        return records


class StubPnlService:
    def __init__(self, logs):
        self.logs = list(logs or [])

    def get_log(self):
        return list(self.logs)


def _advisor_event(
    *,
    decision_id,
    timestamp,
    verdict,
    confidence,
    bot_id="bot-1",
    symbol="ETHUSDT",
    decision_type="initial_entry",
    status="ok",
    model="gpt-5-nano",
    compact_context=None,
    error=None,
    error_code=None,
    raw_response_excerpt=None,
):
    return {
        "event_type": "ai_advisor_decision",
        "decision_id": decision_id,
        "timestamp": timestamp,
        "recorded_at": timestamp,
        "bot_id": bot_id,
        "symbol": symbol,
        "mode": "long",
        "decision_type": decision_type,
        "status": status,
        "verdict": verdict,
        "confidence": confidence,
        "model": model,
        "escalated": False,
        "error": error,
        "error_code": error_code,
        "raw_response_excerpt": raw_response_excerpt,
        "compact_context": compact_context
        or {
            "setup_quality_score": 78.0,
            "gate_blocked": False,
            "entry_allowed": True,
        },
    }


def _execution_event(event_type, timestamp, *, bot_id="bot-1", symbol="ETHUSDT"):
    return {
        "event_type": event_type,
        "timestamp": timestamp,
        "recorded_at": timestamp,
        "bot_id": bot_id,
        "symbol": symbol,
    }


def _trade_log(timestamp, pnl, *, bot_id="bot-1", symbol="ETHUSDT", order_id=None):
    return {
        "id": order_id or f"trade-{timestamp}",
        "order_id": order_id or f"trade-{timestamp}",
        "time": timestamp,
        "symbol": symbol,
        "side": "Sell",
        "realized_pnl": pnl,
        "order_link_id": f"cls:{bot_id[:8]}:{timestamp[-8:]}",
        "attribution_source": "order_link_id",
        "bot_id": bot_id,
    }


def _build_service(tmp_path, *, audit_events, trade_logs, monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_DECISION_LIMIT", 50)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_RECENT_LIMIT", 20)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_LOOKBACK_SECONDS", 86400)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_EXECUTION_WINDOW_SECONDS", 1800)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_OUTCOME_WINDOW_SECONDS", 86400)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_SNAPSHOT_TTL_SECONDS", 30)
    return AIAdvisorAnalyticsService(
        audit_diagnostics_service=StubAuditDiagnosticsService(audit_events),
        pnl_service=StubPnlService(trade_logs),
        file_path=str(tmp_path / "ai_advisor_review.json"),
        now_fn=lambda: 1760000000.0,
    )


def test_refresh_snapshot_persists_and_returns_recent_reviews(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:1",
                    timestamp="2026-03-11T10:00:00+00:00",
                    verdict="APPROVE",
                    confidence=0.81,
                )
            ],
            "actual_entry": [
                _execution_event("actual_entry", "2026-03-11T10:01:00+00:00")
            ],
        },
        trade_logs=[_trade_log("2026-03-11T10:20:00+00:00", 4.25)],
        monkeypatch=monkeypatch,
    )

    payload = service.get_recent_reviews(limit=10, force_refresh=True)

    assert payload["decisions"][0]["decision_id"] == "adv:1"
    assert payload["decisions"][0]["entry_follow_through_status"] == "entry_action_seen"
    assert payload["decisions"][0]["outcome_status"] == "linked"
    assert payload["decisions"][0]["outcome"]["realized_pnl"] == 4.25
    assert Path(service.file_path).exists()


def test_outcome_linking_respects_next_decision_boundary(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:early",
                    timestamp="2026-03-11T10:00:00+00:00",
                    verdict="APPROVE",
                    confidence=0.78,
                ),
                _advisor_event(
                    decision_id="adv:late",
                    timestamp="2026-03-11T10:10:00+00:00",
                    verdict="CAUTION",
                    confidence=0.55,
                ),
            ],
            "actual_entry": [
                _execution_event("actual_entry", "2026-03-11T10:01:00+00:00"),
                _execution_event("actual_entry", "2026-03-11T10:11:00+00:00"),
            ],
        },
        trade_logs=[_trade_log("2026-03-11T10:12:00+00:00", -1.5)],
        monkeypatch=monkeypatch,
    )

    reviews = service.get_recent_reviews(limit=10, force_refresh=True)["decisions"]
    by_id = {item["decision_id"]: item for item in reviews}

    assert by_id["adv:late"]["outcome_status"] == "linked"
    assert by_id["adv:late"]["outcome"]["realized_pnl"] == -1.5
    assert by_id["adv:early"]["outcome_status"] == "unresolved"


def test_reject_without_follow_through_stays_not_executed(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:reject",
                    timestamp="2026-03-11T11:00:00+00:00",
                    verdict="REJECT",
                    confidence=0.88,
                    compact_context={
                        "setup_quality_score": 30.0,
                        "gate_blocked": True,
                        "entry_allowed": False,
                    },
                )
            ]
        },
        trade_logs=[],
        monkeypatch=monkeypatch,
    )

    decision = service.get_recent_reviews(limit=5, force_refresh=True)["decisions"][0]

    assert decision["entry_follow_through_status"] == "no_entry_action_seen"
    assert decision["outcome_status"] == "not_executed"
    assert decision["local_alignment"] == "aligned"


def test_summary_and_calibration_aggregate_by_verdict(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:a",
                    timestamp="2026-03-11T10:00:00+00:00",
                    verdict="APPROVE",
                    confidence=0.84,
                    symbol="ETHUSDT",
                ),
                _advisor_event(
                    decision_id="adv:c",
                    timestamp="2026-03-11T11:00:00+00:00",
                    verdict="CAUTION",
                    confidence=0.58,
                    symbol="SOLUSDT",
                    compact_context={
                        "setup_quality_score": 58.0,
                        "gate_blocked": False,
                        "entry_allowed": True,
                    },
                ),
                _advisor_event(
                    decision_id="adv:r",
                    timestamp="2026-03-11T12:00:00+00:00",
                    verdict="REJECT",
                    confidence=0.91,
                    symbol="XRPUSDT",
                    compact_context={
                        "setup_quality_score": 28.0,
                        "gate_blocked": True,
                        "entry_allowed": False,
                    },
                ),
            ],
            "actual_entry": [
                _execution_event("actual_entry", "2026-03-11T10:02:00+00:00", symbol="ETHUSDT"),
                _execution_event("actual_entry", "2026-03-11T11:02:00+00:00", symbol="SOLUSDT"),
            ],
        },
        trade_logs=[
            _trade_log("2026-03-11T10:30:00+00:00", 3.0, symbol="ETHUSDT"),
            _trade_log("2026-03-11T11:35:00+00:00", -2.0, symbol="SOLUSDT"),
        ],
        monkeypatch=monkeypatch,
    )

    summary = service.get_summary(force_refresh=True)["summary"]
    calibration = service.get_calibration(force_refresh=False)["calibration"]

    assert summary["total_decisions"] == 3
    assert summary["follow_through_counts"]["entry_action_seen"] == 2
    assert summary["outcome_status_counts"]["linked"] == 2
    assert calibration["approve_count"] == 1
    assert calibration["caution_count"] == 1
    assert calibration["reject_count"] == 1
    assert calibration["executed_after_approve_count"] == 1
    assert calibration["executed_after_caution_count"] == 1
    assert calibration["executed_after_reject_count"] == 0
    assert calibration["avg_pnl_by_verdict"]["approve"] == 3.0
    assert calibration["avg_pnl_by_verdict"]["caution"] == -2.0
    assert calibration["avg_pnl_by_verdict"]["reject"] is None


def test_error_code_is_preserved_in_recent_and_summary(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:err",
                    timestamp="2026-03-11T09:00:00+00:00",
                    verdict=None,
                    confidence=None,
                    status="error",
                    error="invalid verdict: missing",
                    error_code="invalid_verdict_missing",
                    raw_response_excerpt='{"confidence":0.52,"reasons":["No verdict supplied"]}',
                )
            ]
        },
        trade_logs=[],
        monkeypatch=monkeypatch,
    )

    recent = service.get_recent_reviews(limit=5, force_refresh=True)["decisions"]
    summary = service.get_summary(force_refresh=False)["summary"]

    assert recent[0]["error_code"] == "invalid_verdict_missing"
    assert recent[0]["raw_response_excerpt"] == '{"confidence":0.52,"reasons":["No verdict supplied"]}'
    assert summary["error_code_counts"]["invalid_verdict_missing"] == 1
    assert summary["error_count"] == 1


def test_refresh_snapshot_safe_failure_uses_last_snapshot(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        audit_events={
            "ai_advisor_decision": [
                _advisor_event(
                    decision_id="adv:ok",
                    timestamp="2026-03-11T10:00:00+00:00",
                    verdict="APPROVE",
                    confidence=0.72,
                )
            ],
            "actual_entry": [
                _execution_event("actual_entry", "2026-03-11T10:01:00+00:00")
            ],
        },
        trade_logs=[_trade_log("2026-03-11T10:20:00+00:00", 1.25)],
        monkeypatch=monkeypatch,
    )
    initial = service.refresh_snapshot(force=True)

    class FailingAuditDiagnosticsService:
        def get_recent_events(self, **kwargs):
            raise RuntimeError("boom")

    failing_service = AIAdvisorAnalyticsService(
        audit_diagnostics_service=FailingAuditDiagnosticsService(),
        pnl_service=StubPnlService([]),
        file_path=str(tmp_path / "ai_advisor_review.json"),
        now_fn=lambda: 1760000000.0,
    )

    fallback = failing_service.get_recent_reviews(limit=5, force_refresh=True)

    assert initial["recent"][0]["decision_id"] == "adv:ok"
    assert fallback["decisions"][0]["decision_id"] == "adv:ok"
    assert fallback["error"] == "boom"
