from datetime import datetime, timezone
from types import SimpleNamespace

from services.bot_triage_service import BotTriageService


def _base_bot(**overrides):
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "total_pnl": 12.5,
        "watchdog_position_cap_active": False,
        "session_timer_enabled": False,
        "ai_advisor_enabled": False,
    }
    bot.update(overrides)
    return bot


def _make_service(*, review_bot=None, active_issues=None):
    watchdog_hub_service = SimpleNamespace(
        build_snapshot=lambda runtime_bots=None: {
            "active_issues": list(active_issues or []),
        },
        audit_diagnostics_service=SimpleNamespace(
            get_review_snapshot=lambda: {
                "bots": {
                    "bot-1": dict(review_bot or {}),
                }
            }
        ),
    )
    return BotTriageService(
        watchdog_hub_service=watchdog_hub_service,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )


def test_pause_classification_for_repeated_margin_and_loss_asymmetry():
    service = _make_service(
        review_bot={
            "current_operational_status": "BLOCKED",
            "config_integrity_state": "clean",
            "margin_viability_state": "starved",
            "cap_headroom_state": "clear",
            "recent_suppressions": {
                "insufficient_margin": 3,
                "opening_orders_blocked": 4,
            },
            "recent_positive_actions": {},
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "loss_asymmetry",
                "reason": "high_win_rate_negative_pnl",
                "severity": "ERROR",
            },
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            },
        ],
    )

    payload = service.build_snapshot(
        runtime_bots=[_base_bot(total_pnl=-44.0)],
    )

    item = payload["items"][0]
    assert item["verdict"] == "PAUSE"
    assert item["severity"] == "high"
    assert "strong loss asymmetry" in item["reasons"]
    assert "repeated insufficient margin" in item["reasons"]
    assert item["suggested_action"].startswith("pause bot")


def test_reduce_classification_for_capital_compression():
    service = _make_service(
        review_bot={
            "current_operational_status": "DEGRADED",
            "config_integrity_state": "clean",
            "margin_viability_state": "compressed",
            "cap_headroom_state": "clear",
            "recent_suppressions": {},
            "recent_positive_actions": {"opening_orders_placed": 1},
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "capital_compression_active",
                "severity": "WARN",
            }
        ],
    )

    payload = service.build_snapshot(runtime_bots=[_base_bot(total_pnl=-6.0)])
    item = payload["items"][0]

    assert item["verdict"] == "REDUCE"
    assert item["severity"] == "medium"
    assert "capital compression active" in item["reasons"]
    assert item["suggested_action"] == "reduce leverage / grid count"


def test_keep_classification_for_stable_bot():
    service = _make_service(
        review_bot={
            "current_operational_status": "OK",
            "config_integrity_state": "clean",
            "margin_viability_state": "viable",
            "cap_headroom_state": "clear",
            "recent_suppressions": {},
            "recent_positive_actions": {"opening_orders_placed": 2},
        },
        active_issues=[],
    )

    payload = service.build_snapshot(runtime_bots=[_base_bot(total_pnl=8.0)])
    item = payload["items"][0]

    assert item["verdict"] == "KEEP"
    assert item["severity"] == "low"
    assert item["reasons"][:2] == ["runtime stable", "no severe watchdog issues"]
    assert item["suggested_action"] == "keep as-is and use session timer only"


def test_review_classification_for_config_integrity_issue():
    service = _make_service(
        review_bot={
            "current_operational_status": "WATCH",
            "config_integrity_state": "degraded",
            "margin_viability_state": "viable",
            "cap_headroom_state": "clear",
            "recent_suppressions": {"config_integrity_issues": 2},
            "recent_positive_actions": {},
        },
        active_issues=[],
    )

    payload = service.build_snapshot(runtime_bots=[_base_bot(total_pnl=1.0)])
    item = payload["items"][0]

    assert item["verdict"] == "REVIEW"
    assert item["severity"] == "high"
    assert item["reasons"][0] == "config integrity degraded"
    assert item["suggested_action"] == "review config integrity"


def test_missing_diagnostics_returns_conservative_review():
    service = BotTriageService(watchdog_hub_service=None)

    payload = service.build_snapshot(
        runtime_bots=[
            _base_bot(
                symbol="ETHUSDT",
                runtime_snapshot_stale=True,
                total_pnl=0.0,
            )
        ],
        stale_data=True,
        error="bots_runtime_bridge_unavailable",
    )

    item = payload["items"][0]
    assert payload["stale_data"] is True
    assert payload["error"] == "bots_runtime_bridge_unavailable"
    assert item["verdict"] == "REVIEW"
    assert item["severity"] == "medium"
    assert "runtime snapshot stale" in item["reasons"]
