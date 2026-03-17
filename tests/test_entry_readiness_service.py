import time

import pytest

from services.entry_readiness_service import EntryReadinessService
from services.entry_gate_service import EntryGateService
from config import strategy_config as cfg


class FakeEntryGateService:
    def __init__(
        self,
        *,
        check_entry_result=None,
        setup_quality_result=None,
        buy_result=None,
        sell_result=None,
    ):
        self.has_custom_check_entry_result = check_entry_result is not None
        self.check_entry_result = check_entry_result or {
            "suitable": True,
            "reason": "Entry conditions favorable",
            "blocked_by": [],
            "scores": {
                "entry_signal": {
                    "code": "early_entry",
                    "label": "Early entry window",
                    "phase": "early",
                    "detail": "Strong directional confluence with limited extension.",
                    "preferred": True,
                    "late": False,
                    "executable": True,
                },
                "setup_quality": {
                    "enabled": True,
                    "score": 72.0,
                    "entry_allowed": True,
                    "breakout_ready": True,
                    "band": "strong",
                    "summary": "mode_fit=+8.0",
                }
            },
        }
        self.setup_quality_result = setup_quality_result or {
            "enabled": True,
            "score": 72.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
        self.buy_result = buy_result or {
            "suitable": True,
            "reason": "Side entry conditions favorable",
            "blocked_by": [],
        }
        self.sell_result = sell_result or {
            "suitable": True,
            "reason": "Side entry conditions favorable",
            "blocked_by": [],
        }

    def check_entry(self, symbol, mode, indicators=None, bot=None, current_price=None):
        return self.check_entry_result

    def get_setup_quality(
        self,
        symbol,
        mode,
        current_price=None,
        indicators=None,
        structure=None,
        price_action_context=None,
        side_result=None,
        suppress_components=None,
    ):
        return self.setup_quality_result

    def check_side_open(self, symbol, side, current_price=None, indicators=None):
        normalized = str(side or "").strip().lower()
        if normalized == "buy":
            return self.buy_result
        return self.sell_result

    def classify_directional_entry_signal(
        self,
        *,
        mode,
        setup_quality=None,
        breakout_confirmation=None,
    ):
        scores = (self.check_entry_result or {}).get("scores") or {}
        if self.has_custom_check_entry_result and scores.get("entry_signal") is not None:
            return scores.get("entry_signal") or {}
        quality = dict(setup_quality or {})
        components = dict(quality.get("components") or {})
        direction = str(
            (components.get("price_action_context") or {}).get("direction") or ""
        ).strip().lower()
        mode_fit_score = float((components.get("mode_fit") or {}).get("score") or 0.0)
        if direction not in {"bullish", "bearish"} or mode_fit_score < 2.5:
            return {
                "code": "continuation_entry",
                "label": "Continuation entry",
                "phase": "continuation",
                "detail": "Executable, but directional confluence is not fully aligned.",
                "preferred": False,
                "late": False,
                "executable": True,
            }
        return {
            "code": "early_entry",
            "label": "Early entry window",
            "phase": "early",
            "detail": "Strong directional confluence with limited extension.",
            "preferred": True,
            "late": False,
            "executable": True,
        }

    def check_breakout_confirmation(
        self,
        symbol,
        mode,
        current_price=None,
        structure=None,
        price_action_context=None,
        setup_quality=None,
    ):
        quality = dict(setup_quality or {})
        return {
            "required": True,
            "confirmed": bool(quality.get("breakout_ready", True)),
            "block_code": None if quality.get("breakout_ready", True) else "BREAKOUT_NOT_CONFIRMED",
            "reason": None if quality.get("breakout_ready", True) else "Breakout still forming",
        }


class FakeNeutralSuitabilityService:
    def __init__(self, result=None):
        self.result = result or {
            "suitable": True,
            "reason": "Conditions suitable (sideways)",
            "blocked_by": [],
        }

    def check_suitability(
        self,
        symbol,
        preset=None,
        indicators_15m=None,
        indicators_1m=None,
    ):
        return self.result


def make_service(
    *,
    entry_gate_service=None,
    neutral_suitability_service=None,
    live_preview_enabled=True,
    stopped_preview_enabled=False,
    cache_ttl_seconds=5,
):
    return EntryReadinessService(
        indicator_service=None,
        cache_ttl_seconds=cache_ttl_seconds,
        entry_gate_service=entry_gate_service or FakeEntryGateService(),
        neutral_suitability_service=neutral_suitability_service
        or FakeNeutralSuitabilityService(),
        live_preview_enabled=live_preview_enabled,
        stopped_preview_enabled=stopped_preview_enabled,
    )


@pytest.fixture(autouse=True)
def _enable_directional_gate(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)


def test_entry_readiness_reports_ready_for_good_directional_setup():
    service = make_service()

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "ready"
    assert result["entry_ready_reason"] == "early_entry"
    assert result["entry_ready_reason_text"] == "Early entry window"
    assert result["entry_ready_direction"] == "long"
    assert result["entry_ready_score"] == 72.0


def test_entry_readiness_preview_disabled_is_explicitly_non_blocking():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "watch"
    assert result["entry_ready_reason"] == "preview_disabled"
    assert result["entry_ready_reason_text"] == "Preview disabled"
    assert "not a trade block" in result["entry_ready_detail"]


def test_entry_readiness_distinguishes_global_gate_off_for_directional(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service()

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_reason"] == "entry_gate_disabled"
    assert result["entry_ready_reason_text"] == "Gate off globally"
    assert result["entry_ready_source"] == "entry_gate_disabled_global"
    assert "globally" in result["entry_ready_detail"]
    assert result["live_gate_bot_enabled"] is True
    assert result["live_gate_global_master_applicable"] is True
    assert result["live_gate_global_master_enabled"] is False
    assert result["live_gate_contract_active"] is False


def test_entry_readiness_distinguishes_bot_gate_off_for_directional(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    service = make_service()

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "entry_gate_enabled": False,
        }
    )

    assert result["entry_ready_reason"] == "entry_gate_disabled"
    assert result["entry_ready_reason_text"] == "Gate off for this bot"
    assert result["entry_ready_source"] == "entry_gate_disabled_bot"
    assert "for this bot" in result["entry_ready_detail"]
    assert result["live_gate_bot_enabled"] is False
    assert result["live_gate_global_master_enabled"] is True
    assert result["live_gate_contract_active"] is False


def test_analysis_readiness_can_be_ready_while_gate_is_off_globally(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=True)

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_reason"] == "entry_gate_disabled"
    assert result["live_gate_status"] == "off_global"
    assert result["analysis_ready_status"] == "ready"
    assert result["analysis_ready_reason"] == "early_entry"


def test_analysis_readiness_can_report_preview_off_while_gate_is_off_globally(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["live_gate_status"] == "off_global"
    assert result["analysis_ready_reason"] == "preview_disabled"
    assert result["analysis_ready_status"] == "watch"


def test_analysis_readiness_can_preview_stopped_bot_when_bounded_preview_enabled(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["live_gate_status"] == "off_global"
    assert result["entry_ready_reason"] == "entry_gate_disabled"
    assert result["analysis_ready_status"] == "ready"
    assert result["analysis_ready_reason"] == "early_entry"


def test_entry_readiness_maps_support_resistance_blocks():
    service = make_service(
        entry_gate_service=FakeEntryGateService(
            check_entry_result={
                "suitable": False,
                "reason": "Resistance 0.40% away @ 100.4000 (strength=7)",
                "blocked_by": ["RESISTANCE_NEARBY"],
                "scores": {
                    "setup_quality": {
                        "enabled": True,
                        "score": 58.0,
                        "entry_allowed": True,
                        "breakout_ready": True,
                        "band": "good",
                    }
                },
            }
        )
    )

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "near_resistance"
    assert "Resistance 0.40% away" in result["entry_ready_detail"]


def test_entry_readiness_maps_support_block_for_short_mode():
    service = make_service(
        entry_gate_service=FakeEntryGateService(
            check_entry_result={
                "suitable": False,
                "reason": "Support 0.35% away @ 99.6500 (strength=6)",
                "blocked_by": ["SUPPORT_NEARBY"],
                "scores": {
                    "setup_quality": {
                        "enabled": True,
                        "score": 57.0,
                        "entry_allowed": True,
                        "breakout_ready": True,
                        "band": "good",
                    }
                },
            }
        )
    )

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "short",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "near_support"
    assert "Support 0.35% away" in result["entry_ready_detail"]


def test_entry_readiness_maps_auto_pilot_loss_budget_block():
    service = make_service()

    result = service.evaluate_bot(
        {
            "symbol": "AUTO-PILOT",
            "mode": "long",
            "auto_pilot": True,
            "auto_pilot_loss_budget_state": "blocked",
            "auto_pilot_remaining_loss_budget_pct": 0.0,
            "auto_pilot_remaining_loss_budget_usdt": 0.0,
            "auto_pilot_loss_budget_usdt": 15.0,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "loss_budget_blocked"
    assert "remaining 0.00%" in result["entry_ready_detail"]


def test_entry_readiness_maps_breakout_confirmation_block():
    service = make_service(
        entry_gate_service=FakeEntryGateService(
            check_entry_result={
                "suitable": False,
                "reason": "Need 2 closed candles beyond 100.150000",
                "blocked_by": ["BREAKOUT_NOT_CONFIRMED"],
                "scores": {
                    "setup_quality": {
                        "enabled": True,
                        "score": 64.0,
                        "entry_allowed": True,
                        "breakout_ready": True,
                        "band": "good",
                    }
                },
            }
        )
    )

    result = service.evaluate_bot(
        {
            "symbol": "SOLUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
            "breakout_confirmed_entry": True,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "breakout_not_confirmed"


def test_entry_readiness_maps_breakout_no_chase_block():
    service = make_service(
        entry_gate_service=FakeEntryGateService(
            check_entry_result={
                "suitable": False,
                "reason": "Breakout entry blocked: no-chase extension too far from breakout confirmation",
                "blocked_by": ["BREAKOUT_CHASE_TOO_FAR"],
                "scores": {
                    "setup_quality": {
                        "enabled": True,
                        "score": 68.0,
                        "entry_allowed": True,
                        "breakout_ready": True,
                        "band": "good",
                    }
                },
            }
        )
    )

    result = service.evaluate_bot(
        {
            "symbol": "SOLUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
            "breakout_confirmed_entry": True,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "breakout_extended"


def test_entry_readiness_marks_caution_setup_as_watch():
    service = make_service(
        entry_gate_service=FakeEntryGateService(
            check_entry_result={
                "suitable": True,
                "reason": "Entry conditions favorable",
                "blocked_by": [],
                "scores": {
                    "setup_quality": {
                        "enabled": True,
                        "score": 55.0,
                        "entry_allowed": True,
                        "breakout_ready": True,
                        "band": "caution",
                        "summary": "adverse_structure=-2.0",
                    }
                },
            }
        )
    )

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "short",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "watch"
    assert result["entry_ready_reason"] == "low_setup_quality"
    assert result["entry_ready_score"] == 55.0


def test_entry_readiness_surfaces_runtime_insufficient_margin_block():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 76.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
            "setup_quality_breakout_ready": True,
            "entry_signal_code": "early_entry",
            "entry_signal_label": "Early entry window",
            "entry_signal_phase": "early",
            "entry_signal_detail": "Strong directional confluence with limited extension.",
            "entry_signal_preferred": True,
            "entry_signal_executable": True,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "insufficient_margin",
            "_capital_starved_warning_text": "Capital starved: need $2.45 opening margin, have $2.14",
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "insufficient_margin"
    assert "need $2.45" in result["entry_ready_detail"]
    assert result["execution_viability_bucket"] == "margin_limited"
    assert result["execution_margin_limited"] is True


def test_entry_readiness_surfaces_runtime_position_cap_block():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 76.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
            "setup_quality_breakout_ready": True,
            "entry_signal_code": "good_continuation",
            "entry_signal_label": "Good continuation entry",
            "entry_signal_phase": "continuation",
            "entry_signal_detail": "Trend continuation remains tradable, but this is not an early pullback entry.",
            "entry_signal_preferred": True,
            "entry_signal_executable": True,
            "_watchdog_position_cap_active": True,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "position_cap_hit"
    assert "opening exposure is already capped" in result["entry_ready_detail"]


def test_analysis_readiness_downgrades_runtime_good_but_not_strong_directional_setup():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 65.0,
            "setup_quality_band": "good",
            "setup_quality_summary": "mode_fit=+5.0, price_action_context=+2.0",
            "setup_quality_breakout_ready": True,
            "readiness_price_action_mode_fit_score": 1.5,
            "readiness_price_action_direction": "neutral",
        }
    )

    assert result["entry_ready_status"] == "ready"
    assert result["analysis_ready_status"] == "watch"
    assert result["analysis_ready_reason"] == "watch_setup"
    assert result["analysis_ready_fallback_used"] is False
    assert "not strong enough" in result["analysis_ready_detail"].lower() or "stronger directional confirmation" in result["analysis_ready_detail"].lower()


def test_active_directional_analysis_falls_back_when_runtime_setup_fields_were_cleared(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False, stopped_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": False,
            "setup_quality_score": None,
            "setup_quality_band": None,
            "setup_quality_summary": None,
            "setup_quality_breakout_ready": None,
            "entry_signal_code": None,
            "entry_signal_label": None,
            "entry_signal_detail": None,
        }
    )

    assert result["analysis_ready_status"] == "ready"
    assert result["analysis_ready_reason"] == "early_entry"
    assert result["analysis_ready_fallback_used"] is True
    assert result["analysis_ready_fallback_reason"] == "runtime_analysis_missing"
    assert result["setup_ready_status"] == "ready"
    assert result["setup_ready_reason"] == "early_entry"
    assert result["readiness_source_kind"] == "fresh_fallback"
    assert result["readiness_fallback_used"] is True
    assert result["readiness_eval_duration_ms"] >= 0.0


def test_active_directional_fallback_matches_stopped_preview_for_same_setup(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False, stopped_preview_enabled=False)
    active_bot = {
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "running",
        "entry_gate_enabled": True,
        "setup_quality_enabled": False,
        "setup_quality_score": None,
        "setup_quality_band": None,
        "setup_quality_summary": None,
        "setup_quality_breakout_ready": None,
    }
    stopped_bot = {
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "stopped",
        "entry_gate_enabled": True,
    }

    active_result = service.evaluate_bot(active_bot)
    stopped_result = service.evaluate_bot(
        stopped_bot,
        allow_stopped_analysis_preview=True,
    )

    assert active_result["setup_ready_status"] == "ready"
    assert stopped_result["setup_ready_status"] == "ready"
    assert active_result["setup_ready_reason"] == stopped_result["setup_ready_reason"]
    assert active_result["setup_ready_score"] == stopped_result["setup_ready_score"]
    assert active_result["setup_ready_fallback_used"] is True
    assert stopped_result["setup_ready_fallback_used"] is False
    assert active_result["readiness_source_kind"] == "fresh_fallback"
    assert stopped_result["readiness_source_kind"] == "stopped_preview"


def test_active_readiness_prefers_fresher_market_provider_snapshot():
    now_ts = time.time()

    class FakeMarketProvider:
        def get_last_price_metadata(self, symbol, max_age_sec=None):
            return {
                "symbol": symbol,
                "price": 101.75,
                "received_at": now_ts - 0.25,
                "exchange_ts": now_ts - 0.30,
                "source": "orderbook_mid",
                "transport": "stream_orderbook",
            }

    service = EntryReadinessService(
        indicator_service=None,
        cache_ttl_seconds=5,
        entry_gate_service=FakeEntryGateService(),
        neutral_suitability_service=FakeNeutralSuitabilityService(),
        live_preview_enabled=True,
        stopped_preview_enabled=False,
        market_data_provider=FakeMarketProvider(),
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "current_price": 99.5,
            "current_price_updated_at": EntryReadinessService._iso_from_ts(now_ts - 8.0),
            "current_price_source": "runtime_cycle",
            "current_price_transport": "runtime_bot",
        }
    )

    assert result["market_data_source"] == "orderbook_mid"
    assert result["market_data_transport"] == "stream_orderbook"
    assert result["market_data_price"] == 101.75
    assert result["market_provider_transport"] == "stream_orderbook"
    assert result["ticker_provider_updated_at"] is not None
    assert result["ticker_provider_age_ms"] is not None
    assert result["ticker_provider_age_ms"] < 2000.0
    assert result["fresher_ticker_available"] is True
    assert result["market_data_refreshed_just_in_time"] is True
    assert result["market_data_refresh_reason"] == "provider_newer_than_bot"
    assert result["bot_current_price_source"] == "runtime_cycle"
    assert result["market_data_refresh_delta_ms"] > 7000.0
    assert result["market_to_readiness_eval_start_ms"] < 2000.0


def test_setup_readiness_stays_ready_while_execution_viability_reports_margin_block(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False, stopped_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": False,
            "setup_quality_score": None,
            "setup_quality_band": None,
            "setup_quality_summary": None,
            "setup_quality_breakout_ready": None,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "insufficient_margin",
            "_capital_starved_warning_text": "Capital starved: need $4.16 opening margin, have $1.90",
        }
    )

    assert result["setup_ready"] is True
    assert result["setup_ready_status"] == "ready"
    assert result["setup_ready_reason"] == "early_entry"
    assert result["execution_blocked"] is True
    assert result["execution_viability_status"] == "blocked"
    assert result["execution_viability_reason"] == "insufficient_margin"
    assert result["execution_viability_bucket"] == "margin_limited"
    assert result["execution_margin_limited"] is True
    assert "need $4.16" in result["execution_viability_detail"]
    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "insufficient_margin"


def test_setup_readiness_stays_ready_while_execution_viability_reports_reserve_limit(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False, stopped_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": False,
            "setup_quality_score": None,
            "setup_quality_band": None,
            "setup_quality_summary": None,
            "setup_quality_breakout_ready": None,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "opening_margin_reserve",
            "_capital_starved_warning_text": "Reserve limited: need $4.16 opening margin, usable after reserve $1.90",
        }
    )

    assert result["setup_ready"] is True
    assert result["setup_ready_status"] == "ready"
    assert result["setup_ready_reason"] == "early_entry"
    assert result["execution_blocked"] is True
    assert result["execution_viability_status"] == "blocked"
    assert result["execution_viability_reason"] == "opening_margin_reserve"
    assert result["execution_viability_reason_text"] == "Reserve limited"
    assert result["execution_viability_bucket"] == "margin_limited"
    assert result["execution_margin_limited"] is True
    assert "Reserve limited" in result["execution_viability_detail"]
    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "opening_margin_reserve"


@pytest.mark.parametrize(
    ("bot_fields", "expected_reason"),
    [
        (
            {
                "position_assumption_stale": True,
            },
            "exchange_truth_stale",
        ),
        (
            {
                "order_assumption_stale": True,
            },
            "exchange_truth_stale",
        ),
        (
            {
                "exchange_reconciliation": {
                    "status": "diverged",
                    "reason": "orphaned_position",
                    "mismatches": ["orphaned_position"],
                },
            },
            "reconciliation_diverged",
        ),
    ],
)
def test_setup_can_stay_ready_while_exchange_truth_blocks_execution(
    monkeypatch,
    bot_fields,
    expected_reason,
):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(live_preview_enabled=False, stopped_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": False,
            "setup_quality_score": None,
            "setup_quality_band": None,
            "setup_quality_summary": None,
            "setup_quality_breakout_ready": None,
            **bot_fields,
        }
    )

    assert result["setup_ready"] is True
    assert result["setup_ready_status"] == "ready"
    assert result["setup_ready_reason"] == "early_entry"
    assert result["execution_blocked"] is True
    assert result["execution_viability_status"] == "blocked"
    assert result["execution_viability_reason"] == expected_reason
    assert result["execution_viability_bucket"] == "state_untrusted"
    assert result["execution_viability_diagnostic_reason"] == expected_reason
    assert result["entry_ready_reason"] != expected_reason
    assert result["entry_ready_status"] in {"ready", "watch"}


def test_stopped_setup_ready_margin_limit_keeps_setup_truth_and_margin_bucket(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    gate = FakeEntryGateService(
        setup_quality_result={
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "price_action=+8.2, mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
    )
    service = make_service(
        entry_gate_service=gate,
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "insufficient_margin",
            "_capital_starved_warning_text": "Capital starved: need $12.30 opening margin, have $4.50",
        },
        allow_stopped_analysis_preview=True,
    )

    assert result["setup_ready"] is True
    assert result["setup_ready_status"] == "ready"
    assert result["setup_timing_status"] == "trigger_ready"
    assert result["execution_blocked"] is True
    assert result["execution_viability_reason"] == "insufficient_margin"
    assert result["execution_viability_bucket"] == "margin_limited"
    assert result["execution_margin_limited"] is True


def test_stopped_setup_ready_ignores_stale_saved_margin_blocker(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    gate = FakeEntryGateService(
        setup_quality_result={
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "price_action=+8.2, mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
    )
    service = make_service(
        entry_gate_service=gate,
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "insufficient_margin",
            "_capital_starved_warning_text": "Capital starved: need $12.30 opening margin, have $4.50",
            "capital_starved_available_opening_margin_usdt": 4.5,
            "capital_starved_required_margin_usdt": 12.3,
            "capital_starved_order_notional_usdt": 123.0,
            "watchdog_bottleneck_summary": {
                "capital_starved_active": False,
            },
        },
        allow_stopped_analysis_preview=True,
    )

    assert result["setup_ready"] is True
    assert result["setup_timing_status"] == "trigger_ready"
    assert result["execution_blocked"] is False
    assert result["execution_viability_status"] == "viable"
    assert result["execution_viability_reason"] == "openings_clear"
    assert result["execution_viability_bucket"] == "viable"
    assert result["execution_margin_limited"] is False
    assert result["execution_viability_stale_data"] is True
    assert result["execution_viability_diagnostic_reason"] == "stale_balance"
    assert result["execution_viability_diagnostic_text"] == "Stale balance"
    assert result["execution_available_margin_usdt"] == 4.5
    assert result["execution_required_margin_usdt"] == 12.3
    assert result["execution_order_notional_usdt"] == 123.0
    assert result["setup_ready_status"] == "ready"
    assert result["setup_ready_reason"] == "early_entry"


@pytest.mark.parametrize(
    ("runtime_fields", "expected_source"),
    [
        ({"_watchdog_position_cap_active": True}, "runtime_position_cap_stale"),
        (
            {"_small_capital_block_opening_orders": True},
            "runtime_small_capital_stale",
        ),
        (
            {
                "_breakout_invalidation_block_opening_orders": True,
                "breakout_invalidation_reason": "reclaim below broken resistance",
            },
            "runtime_breakout_invalidation_stale",
        ),
        ({"_session_timer_block_opening_orders": True}, "runtime_session_timer_stale"),
        ({"_stall_overlay_block_opening_orders": True}, "runtime_stall_overlay_stale"),
        ({"_block_opening_orders": True}, "runtime_opening_block_stale"),
    ],
)
def test_stopped_setup_ready_demotes_stale_saved_runtime_blockers(
    monkeypatch,
    runtime_fields,
    expected_source,
):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    gate = FakeEntryGateService(
        setup_quality_result={
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "price_action=+8.2, mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
    )
    service = make_service(
        entry_gate_service=gate,
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
            **runtime_fields,
        },
        allow_stopped_analysis_preview=True,
    )

    assert result["setup_timing_status"] == "trigger_ready"
    assert result["execution_blocked"] is False
    assert result["execution_viability_status"] == "viable"
    assert result["execution_viability_reason"] == "openings_clear"
    assert result["execution_viability_stale_data"] is True
    assert result["execution_viability_diagnostic_reason"] == "stale_runtime_blocker"
    assert result["execution_viability_source"] == expected_source


def test_stop_cleanup_pending_readiness_is_explicitly_non_actionable():
    service = make_service(live_preview_enabled=True, stopped_preview_enabled=True)

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stop_cleanup_pending",
            "stop_cleanup_pending": True,
            "last_error": "UPnL SL HARD: cleanup pending",
            "_watchdog_position_cap_active": True,
        }
    )

    assert result["entry_ready_status"] == "watch"
    assert result["entry_ready_reason"] == "stop_cleanup_pending"
    assert result["setup_timing_status"] == "watch"
    # H5 audit: stop_cleanup_pending must block execution
    assert result["execution_blocked"] is True
    assert result["execution_viability_status"] == "blocked"
    assert result["execution_viability_reason"] == "stop_cleanup_pending"
    assert result["execution_viability_diagnostic_reason"] == "stop_cleanup_pending"
    assert result["readiness_source_kind"] == "stop_cleanup_pending"


def test_stopped_setup_ready_reports_notional_floor_precisely(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    gate = FakeEntryGateService(
        setup_quality_result={
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "price_action=+8.2, mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
    )
    service = make_service(
        entry_gate_service=gate,
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        {
            "symbol": "SUIUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
            "_capital_starved_block_opening_orders": True,
            "capital_starved_reason": "notional_below_min",
            "_capital_starved_warning_text": "Capital starved: order $0.00 below min $5.00",
            "capital_starved_available_opening_margin_usdt": 20.7423,
            "watchdog_bottleneck_summary": {
                "capital_starved_active": True,
            },
        },
        allow_stopped_analysis_preview=True,
    )

    assert result["setup_ready"] is True
    assert result["execution_blocked"] is True
    assert result["execution_viability_reason"] == "notional_below_min"
    assert result["execution_viability_reason_text"] == "Budget below first order"
    assert result["execution_viability_bucket"] == "size_limited"
    assert result["execution_margin_limited"] is False
    assert result["execution_available_margin_usdt"] == 20.7423
    assert result["setup_timing_status"] == "trigger_ready"


def test_directional_analysis_cache_expires_on_grid_scale_window(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    gate = FakeEntryGateService(
        setup_quality_result={
            "enabled": True,
            "score": 76.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "strong",
            "summary": "mode_fit=+8.0",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 8.0},
            },
        }
    )
    service = make_service(
        entry_gate_service=gate,
        live_preview_enabled=False,
        stopped_preview_enabled=True,
        cache_ttl_seconds=3,
    )
    clock = {"ts": 100.0}
    service._get_now_ts = lambda: clock["ts"]
    bot = {
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "stopped",
        "entry_gate_enabled": True,
    }

    first = service.evaluate_bot(bot, allow_stopped_analysis_preview=True)
    assert first["setup_ready_status"] == "ready"

    gate.setup_quality_result = {
        "enabled": True,
        "score": 55.0,
        "entry_allowed": True,
        "breakout_ready": True,
        "band": "caution",
        "summary": "volume=-2.0",
        "components": {
            "price_action_context": {"direction": "bullish"},
            "mode_fit": {"score": 8.0},
        },
    }

    clock["ts"] = 102.0
    cached = service.evaluate_bot(bot, allow_stopped_analysis_preview=True)
    assert cached["setup_ready_status"] == "ready"

    clock["ts"] = 104.1
    refreshed = service.evaluate_bot(bot, allow_stopped_analysis_preview=True)
    assert refreshed["setup_ready_status"] == "watch"
    assert refreshed["setup_ready_reason"] == "low_setup_quality"


@pytest.mark.parametrize(
    "name,bot,expected_setup_status,expected_setup_reason,expected_exec_status,expected_exec_reason,expected_source_kind",
    [
        (
            "late_breakout_chase",
            {
                "symbol": "XRPUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 76.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "late_continuation",
                "entry_signal_label": "Late continuation",
                "entry_signal_phase": "late",
                "entry_signal_detail": "Move is already extended; waiting for a pullback is safer.",
                "entry_signal_preferred": False,
                "entry_signal_late": True,
                "entry_signal_executable": True,
            },
            "watch",
            "late_continuation",
            "viable",
            "openings_clear",
            "runtime",
        ),
        (
            "clean_continuation_but_session_blocked",
            {
                "symbol": "XRPUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 76.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "good_continuation",
                "entry_signal_label": "Good continuation entry",
                "entry_signal_phase": "continuation",
                "entry_signal_detail": "Trend continuation remains tradable.",
                "entry_signal_preferred": True,
                "entry_signal_executable": True,
                "_session_timer_block_opening_orders": True,
            },
            "ready",
            "good_continuation",
            "blocked",
            "session_blocked",
            "runtime",
        ),
        (
            "clean_continuation_but_min_size_blocked",
            {
                "symbol": "XRPUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 76.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "good_continuation",
                "entry_signal_label": "Good continuation entry",
                "entry_signal_phase": "continuation",
                "entry_signal_detail": "Trend continuation remains tradable.",
                "entry_signal_preferred": True,
                "entry_signal_executable": True,
                "_capital_starved_block_opening_orders": True,
                "capital_starved_reason": "qty_below_min",
            },
            "ready",
            "good_continuation",
            "blocked",
            "qty_below_min",
            "runtime",
        ),
    ],
)
def test_readiness_scenario_matrix_core_execution_cases(
    name,
    bot,
    expected_setup_status,
    expected_setup_reason,
    expected_exec_status,
    expected_exec_reason,
    expected_source_kind,
):
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(bot)

    assert result["setup_ready_status"] == expected_setup_status, name
    assert result["setup_ready_reason"] == expected_setup_reason, name
    assert result["execution_viability_status"] == expected_exec_status, name
    assert result["execution_viability_reason"] == expected_exec_reason, name
    assert result["readiness_source_kind"] == expected_source_kind


@pytest.mark.parametrize(
    "name,entry_gate_service,bot,config_overrides,expected_setup,expected_execution",
    [
        (
            "clean_breakout_before_entry",
            FakeEntryGateService(
                check_entry_result={
                    "suitable": True,
                    "reason": "Breakout confirmed",
                    "blocked_by": [],
                    "scores": {
                        "entry_signal": {
                            "code": "confirmed_breakout",
                            "label": "Confirmed breakout",
                            "phase": "breakout",
                            "detail": "Breakout is confirmed and still within executable range.",
                            "preferred": True,
                            "late": False,
                            "executable": True,
                        },
                        "setup_quality": {
                            "enabled": True,
                            "score": 84.0,
                            "entry_allowed": True,
                            "breakout_ready": True,
                            "band": "strong",
                            "summary": "price_action=+9.0, mode_fit=+8.0",
                        },
                    },
                }
            ),
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "stopped",
                "entry_gate_enabled": True,
            },
            {},
            ("ready", "confirmed_breakout"),
            ("viable", "openings_clear"),
        ),
        (
            "pre_break_compression_waits_for_confirmation",
            FakeEntryGateService(
                check_entry_result={
                    "suitable": True,
                    "reason": "Breakout still forming",
                    "blocked_by": [],
                    "scores": {
                        "setup_quality": {
                            "enabled": True,
                            "score": 79.0,
                            "entry_allowed": True,
                            "breakout_ready": False,
                            "band": "strong",
                            "summary": "compression intact, waiting volume confirmation",
                        }
                    },
                }
            ),
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "stopped",
                "entry_gate_enabled": True,
                "breakout_confirmed_entry": True,
            },
            {"BREAKOUT_CONFIRMED_ENTRY_ENABLED": True},
            ("watch", "waiting_for_confirmation"),
            ("viable", "openings_clear"),
        ),
        (
            "breakout_then_rejection",
            FakeEntryGateService(
                check_entry_result={
                    "suitable": False,
                    "reason": "Price action reversed against the breakout",
                    "blocked_by": ["PRICE_ACTION_BEARISH"],
                    "scores": {
                        "setup_quality": {
                            "enabled": True,
                            "score": 52.0,
                            "entry_allowed": True,
                            "breakout_ready": False,
                            "band": "caution",
                            "summary": "rejection wick against entry",
                        }
                    },
                }
            ),
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "stopped",
                "entry_gate_enabled": True,
            },
            {},
            ("blocked", "structure_weak"),
            ("viable", "openings_clear"),
        ),
        (
            "late_breakout_chase",
            None,
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 78.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, price_action=+6.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "late_continuation",
                "entry_signal_label": "Late continuation",
                "entry_signal_phase": "late",
                "entry_signal_detail": "Move is already extended; waiting for a pullback is safer.",
                "entry_signal_executable": True,
                "entry_signal_late": True,
            },
            {},
            ("watch", "late_continuation"),
            ("viable", "openings_clear"),
        ),
        (
            "trend_continuation_after_pullback",
            None,
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 80.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, supportive_structure=+6.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "good_continuation",
                "entry_signal_label": "Good continuation entry",
                "entry_signal_phase": "continuation",
                "entry_signal_detail": "Continuation remains tradable without being late.",
                "entry_signal_executable": True,
            },
            {},
            ("ready", "good_continuation"),
            ("viable", "openings_clear"),
        ),
        (
            "strong_setup_insufficient_margin",
            None,
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 80.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, supportive_structure=+6.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "early_entry",
                "entry_signal_label": "Early entry window",
                "entry_signal_phase": "early",
                "entry_signal_detail": "Strong directional confluence with limited extension.",
                "entry_signal_executable": True,
                "_capital_starved_block_opening_orders": True,
                "capital_starved_reason": "insufficient_margin",
                "_capital_starved_warning_text": "Capital starved: need $4.16 opening margin, have $1.90",
            },
            {},
            ("ready", "early_entry"),
            ("blocked", "insufficient_margin"),
        ),
        (
            "strong_setup_min_size_blocked",
            None,
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 80.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, supportive_structure=+6.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "early_entry",
                "entry_signal_label": "Early entry window",
                "entry_signal_phase": "early",
                "entry_signal_detail": "Strong directional confluence with limited extension.",
                "entry_signal_executable": True,
                "_capital_starved_block_opening_orders": True,
                "capital_starved_reason": "qty_below_min",
                "_capital_starved_warning_text": "Order size falls below exchange minimum.",
            },
            {},
            ("ready", "early_entry"),
            ("blocked", "qty_below_min"),
        ),
        (
            "strong_setup_session_blocked",
            None,
            {
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "running",
                "entry_gate_enabled": True,
                "setup_quality_enabled": True,
                "setup_quality_score": 80.0,
                "setup_quality_band": "strong",
                "setup_quality_summary": "mode_fit=+8.0, supportive_structure=+6.0",
                "setup_quality_breakout_ready": True,
                "readiness_price_action_mode_fit_score": 6.0,
                "readiness_price_action_direction": "bullish",
                "entry_signal_code": "early_entry",
                "entry_signal_label": "Early entry window",
                "entry_signal_phase": "early",
                "entry_signal_detail": "Strong directional confluence with limited extension.",
                "entry_signal_executable": True,
                "_session_timer_block_opening_orders": True,
            },
            {},
            ("ready", "early_entry"),
            ("blocked", "session_blocked"),
        ),
    ],
)
def test_readiness_scenario_matrix(
    monkeypatch,
    name,
    entry_gate_service,
    bot,
    config_overrides,
    expected_setup,
    expected_execution,
):
    for attr, value in config_overrides.items():
        monkeypatch.setattr(cfg, attr, value)
    service = make_service(
        entry_gate_service=entry_gate_service or FakeEntryGateService(),
        live_preview_enabled=False,
        stopped_preview_enabled=True,
    )

    result = service.evaluate_bot(
        bot,
        allow_stopped_analysis_preview=True,
    )

    assert result["setup_ready_status"] == expected_setup[0], name
    assert result["setup_ready_reason"] == expected_setup[1], name
    assert result["execution_viability_status"] == expected_execution[0], name
    assert result["execution_viability_reason"] == expected_execution[1], name
    assert result["readiness_eval_duration_ms"] >= 0.0, name


def test_analysis_readiness_keeps_good_continuation_actionable_when_signal_is_honest():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 76.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "mode_fit=+8.0, price_action_context=+5.0",
            "setup_quality_breakout_ready": True,
            "readiness_price_action_mode_fit_score": 6.0,
            "readiness_price_action_direction": "bullish",
            "entry_signal_code": "good_continuation",
            "entry_signal_label": "Good continuation entry",
            "entry_signal_phase": "continuation",
            "entry_signal_detail": "Trend continuation remains tradable, but this is not an early pullback entry.",
            "entry_signal_preferred": True,
            "entry_signal_executable": True,
        }
    )

    assert result["analysis_ready_status"] == "ready"
    assert result["analysis_ready_reason"] == "good_continuation"
    assert result["analysis_ready_reason_text"] == "Good continuation entry"
    assert result["setup_timing_status"] == "trigger_ready"
    assert result["setup_timing_actionable"] is True
    assert result["setup_timing_reason"] == "good_continuation"


def test_analysis_timing_surfaces_continuation_entry_as_armed_not_actionable():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 76.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "mode_fit=+8.0, price_action_context=+5.0",
            "setup_quality_breakout_ready": True,
            "readiness_price_action_mode_fit_score": 6.0,
            "readiness_price_action_direction": "bullish",
            "entry_signal_code": "continuation_entry",
            "entry_signal_label": "Continuation entry",
            "entry_signal_phase": "continuation",
            "entry_signal_detail": "Structure is building, but a cleaner trigger is still preferred.",
            "entry_signal_preferred": False,
            "entry_signal_executable": True,
        }
    )

    assert result["entry_ready_status"] == "ready"
    assert result["setup_timing_status"] == "armed"
    assert result["setup_timing_actionable"] is False
    assert result["setup_timing_reason"] == "continuation_entry"


def test_analysis_timing_promotes_strong_supported_continuation_to_trigger_ready():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 75.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "supportive_structure=+5.2, price_action=+2.4, mode_fit=+5.0",
            "setup_quality_breakout_ready": True,
            "readiness_price_action_mode_fit_score": 5.0,
            "readiness_price_action_direction": "neutral",
            "entry_signal_code": "good_continuation",
            "entry_signal_label": "Good continuation entry",
            "entry_signal_phase": "continuation",
            "entry_signal_detail": "Strong continuation remains tradable before the move gets extended.",
            "entry_signal_preferred": True,
            "entry_signal_executable": True,
        }
    )

    assert result["analysis_ready_status"] == "ready"
    assert result["analysis_ready_reason"] == "good_continuation"
    assert result["setup_timing_status"] == "trigger_ready"
    assert result["setup_timing_actionable"] is True


def test_live_directional_readiness_promotes_strong_supported_continuation_signal(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_PROMOTION_ENABLED", True)

    class PromotingFakeEntryGateService(FakeEntryGateService):
        def __init__(self):
            super().__init__(
                check_entry_result={
                    "suitable": True,
                    "reason": "Entry conditions favorable",
                    "blocked_by": [],
                    "scores": {},
                }
            )
            self._classifier = EntryGateService(indicator_service=None)

        def check_entry(self, symbol, mode, indicators=None, bot=None, current_price=None):
            quality = {
                "enabled": True,
                "score": 75.0,
                "entry_allowed": True,
                "breakout_ready": True,
                "band": "strong",
                "summary": "supportive_structure=+5.2, price_action=+2.4, mode_fit=+5.0",
                    "components": {
                        "price_action_context": {"direction": "neutral"},
                        "mode_fit": {"score": 5.0},
                        "indicators": {
                            "price_vs_ema_pct": 0.006,
                            "bb_position": 40.0,
                        },
                    },
                "component_points": {
                    "price_action": 2.4,
                    "supportive_structure": 5.2,
                    "volume": 1.3,
                    "mtf": 0.8,
                },
            }
            return {
                "suitable": True,
                "reason": "Entry conditions favorable",
                "blocked_by": [],
                "scores": {
                    "setup_quality": quality,
                    "entry_signal": self._classifier.classify_directional_entry_signal(
                        mode=mode,
                        setup_quality=quality,
                        breakout_confirmation={"required": False, "confirmed": True},
                    ),
                },
            }

    service = make_service(
        live_preview_enabled=True,
        entry_gate_service=PromotingFakeEntryGateService(),
    )

    result = service.evaluate_bot(
        {
            "symbol": "LINKUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["entry_ready_status"] == "ready"
    assert result["entry_ready_reason"] == "good_continuation"
    assert result["analysis_ready_status"] == "ready"
    assert result["setup_timing_status"] == "trigger_ready"
    assert result["setup_timing_actionable"] is True


def test_analysis_readiness_downgrades_late_continuation_even_if_live_entry_is_executable():
    service = make_service(live_preview_enabled=False)

    result = service.evaluate_bot(
        {
            "symbol": "XRPUSDT",
            "mode": "long",
            "status": "running",
            "entry_gate_enabled": True,
            "setup_quality_enabled": True,
            "setup_quality_score": 76.0,
            "setup_quality_band": "strong",
            "setup_quality_summary": "mode_fit=+8.0, price_action=+5.0",
            "setup_quality_breakout_ready": True,
            "readiness_price_action_mode_fit_score": 6.0,
            "readiness_price_action_direction": "bullish",
            "entry_signal_code": "late_continuation",
            "entry_signal_label": "Late continuation",
            "entry_signal_phase": "late",
            "entry_signal_detail": "Move is already extended; waiting for a pullback is safer.",
            "entry_signal_preferred": False,
            "entry_signal_late": True,
            "entry_signal_executable": True,
        }
    )

    assert result["entry_ready_status"] == "ready"
    assert result["analysis_ready_status"] == "watch"
    assert result["analysis_ready_reason"] == "late_continuation"
    assert "pullback" in result["analysis_ready_next"].lower()
    assert result["setup_timing_status"] == "late"
    assert result["setup_timing_late"] is True


def test_analysis_timing_surfaces_strong_pre_break_confirmation_setup_as_armed(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(
        live_preview_enabled=False,
        stopped_preview_enabled=True,
        entry_gate_service=FakeEntryGateService(
            setup_quality_result={
                "enabled": True,
                "score": 79.0,
                "entry_allowed": True,
                "breakout_ready": False,
                "band": "strong",
                "summary": "compression intact, waiting volume confirmation",
                "components": {
                    "price_action_context": {"direction": "bullish"},
                    "mode_fit": {"score": 8.0},
                },
            }
        ),
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
            "breakout_confirmed_entry": True,
        },
        allow_stopped_analysis_preview=True,
    )

    assert result["analysis_ready_status"] == "blocked"
    assert result["analysis_ready_reason"] == "breakout_not_confirmed"
    assert result["setup_timing_status"] == "armed"
    assert result["setup_timing_actionable"] is False


def test_analysis_readiness_downgrades_stopped_directional_setup_without_aligned_directional_context(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", False)
    service = make_service(
        live_preview_enabled=False,
        stopped_preview_enabled=True,
        entry_gate_service=FakeEntryGateService(
            setup_quality_result={
                "enabled": True,
                "score": 76.0,
                "entry_allowed": True,
                "breakout_ready": True,
                "band": "strong",
                "summary": "mixed confluence",
                "components": {
                    "price_action_context": {"direction": "neutral"},
                    "mode_fit": {"score": 1.0},
                },
            }
        ),
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "stopped",
            "entry_gate_enabled": True,
        }
    )

    assert result["analysis_ready_status"] == "watch"
    assert result["analysis_ready_reason"] == "continuation_entry"


def test_entry_readiness_prefers_runtime_snapshot_without_live_preview_calls():
    class ExplodingEntryGateService(FakeEntryGateService):
        def check_entry(self, symbol, mode, indicators=None, bot=None):
            raise AssertionError("live preview should not run")

    service = make_service(
        entry_gate_service=ExplodingEntryGateService(),
        live_preview_enabled=False,
    )

    result = service.evaluate_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "entry_gate_enabled": True,
            "_entry_gate_blocked": True,
            "_entry_gate_blocked_reason": "Resistance 0.40% away @ 100.4000 (strength=7)",
            "setup_quality_score": 58.0,
        }
    )

    assert result["entry_ready_status"] == "blocked"
    assert result["entry_ready_reason"] == "near_resistance"
