from datetime import datetime, timezone

from services.bot_preset_service import BotPresetService
from services.custom_bot_preset_service import CustomBotPresetService


class _AuditSink:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, **kwargs):
        self.events.append(dict(payload))
        return True


def _make_service(audit_sink=None, custom_preset_service=None):
    return BotPresetService(
        custom_preset_service=custom_preset_service,
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )


def test_bot_preset_catalog_exposes_expected_presets():
    service = _make_service()

    payload = service.list_presets()
    preset_ids = [item["preset_id"] for item in payload["items"]]

    assert payload["default_preset"] == "manual_blank"
    assert preset_ids == [
        "manual_blank",
        "eth_conservative",
        "small_balance_safe",
        "sleep_session",
        "high_volatility_safe",
    ]


def test_small_balance_safe_preset_prefills_conservative_fields():
    service = _make_service()

    preset = service.get_preset("small_balance_safe")

    assert preset["settings"]["leverage"] == 3.0
    assert preset["settings"]["grid_count"] == 6
    assert preset["settings"]["target_grid_count"] == 6
    assert preset["settings"]["grid_distribution"] == "balanced"
    assert preset["settings"]["session_timer_enabled"] is False


def test_auto_recommend_prefers_eth_conservative_for_major_symbol_moderate_budget():
    service = _make_service()

    payload = service.recommend(
        {
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "investment": 120.0,
        }
    )

    assert payload["recommended_preset"] == "eth_conservative"
    assert payload["confidence"] in {"medium", "high"}
    assert "major symbol with usable startup budget" in payload["reasons"]


def test_auto_recommend_prefers_small_balance_safe_for_small_budget():
    audit_sink = _AuditSink()
    service = _make_service(audit_sink)

    payload = service.recommend(
        {
            "symbol": "XRPUSDT",
            "mode": "neutral",
            "investment": 40.0,
        }
    )

    assert payload["recommended_preset"] == "small_balance_safe"
    assert payload["confidence"] == "high"
    assert "min_notional_sensitivity" in payload["matched_signals"]
    assert payload["preset"]["settings"]["grid_count"] == 6
    assert audit_sink.events[0]["event_type"] == "bot_preset_auto_recommended_phase2"


def test_auto_recommend_prefers_sleep_session_when_session_requested():
    service = _make_service()

    payload = service.recommend(
        {
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "investment": 120.0,
            "session_timer_enabled": True,
        }
    )

    assert payload["recommended_preset"] == "sleep_session"
    assert payload["confidence"] == "high"
    assert payload["preset"]["settings"]["session_timer_enabled"] is True
    assert payload["preset"]["settings"]["session_end_mode"] == "green_grace_then_stop"
    assert payload["preset"]["settings"]["session_stop_at"] == "2026-03-12T14:00:00+00:00"


def test_auto_recommend_prefers_high_volatility_safe_for_high_vol_symbol():
    service = _make_service()

    payload = service.recommend(
        {
            "symbol": "DOGEUSDT",
            "mode": "neutral",
            "investment": 150.0,
        }
    )

    assert payload["recommended_preset"] == "high_volatility_safe"
    assert payload["confidence"] == "high"
    assert payload["preset"]["settings"]["leverage"] == 2.0
    assert payload["preset"]["settings"]["neutral_volatility_gate_threshold_pct"] == 4.0


def test_ambiguous_manual_path_prefers_manual_blank():
    service = _make_service()

    payload = service.recommend(
        {
            "symbol": "",
            "mode": "scalp_pnl",
            "investment": 0.0,
        }
    )

    assert payload["recommended_preset"] == "manual_blank"
    assert payload["confidence"] == "medium"
    assert "manual_mode_bias" in payload["matched_signals"]


def test_manual_blank_keeps_editable_baseline_defaults():
    service = _make_service()

    preset = service.get_preset("manual_blank")

    assert preset["settings"]["leverage"] == 3.0
    assert preset["settings"]["grid_count"] == 10
    assert preset["settings"]["grid_distribution"] == "clustered"
    assert preset["settings"]["session_timer_enabled"] is False


def test_record_recommendation_overridden_emits_compact_event():
    audit_sink = _AuditSink()
    service = _make_service(audit_sink)

    service.record_recommendation_overridden(
        selected_preset="manual_blank",
        recommended_preset="eth_conservative",
        symbol="ETHUSDT",
        mode="neutral",
        investment=100.0,
    )

    assert audit_sink.events[-1]["event_type"] == "bot_preset_recommendation_overridden"
    assert audit_sink.events[-1]["preset_name"] == "manual_blank"
    assert audit_sink.events[-1]["recommended_preset"] == "eth_conservative"


def test_auto_recommend_prefers_strong_custom_match_when_it_clearly_fits(tmp_path):
    custom_service = CustomBotPresetService(str(tmp_path / "custom_bot_presets.json"))
    custom_service.create_preset(
        preset_name="ETH Session Safe",
        fields={
            "leverage": 2,
            "grid_count": 8,
            "grid_distribution": "balanced",
            "session_timer_enabled": True,
            "session_duration_min": 120,
            "session_end_mode": "green_grace_then_stop",
        },
        symbol_hint="ETHUSDT",
        mode_hint="neutral",
    )
    service = _make_service(custom_preset_service=custom_service)

    payload = service.recommend(
        {
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "investment": 120.0,
            "session_timer_enabled": True,
        }
    )

    assert payload["preset_type"] == "custom"
    assert payload["recommended_preset"].startswith("custom:")
    assert "custom_session_intent_match" in payload["matched_signals"]
    assert payload["prefill_settings"]["session_timer_enabled"] is True


def test_auto_recommend_does_not_overvalue_weak_custom_preset(tmp_path):
    custom_service = CustomBotPresetService(str(tmp_path / "custom_bot_presets.json"))
    custom_service.create_preset(
        preset_name="DOGE Volatile Copy",
        fields={"leverage": 2, "grid_count": 6, "grid_distribution": "balanced"},
        symbol_hint="DOGEUSDT",
        mode_hint="neutral",
    )
    service = _make_service(custom_preset_service=custom_service)

    payload = service.recommend(
        {
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "investment": 120.0,
        }
    )

    assert payload["preset_type"] == "built_in"
    assert payload["recommended_preset"] == "eth_conservative"


def test_auto_recommend_does_not_treat_min_qty_failure_as_viable():
    service = _make_service()

    payload = service.recommend(
        {
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "investment": 120.0,
            "reference_price": 4000.0,
            "price_source": "mark_price",
            "min_notional": 5.0,
            "min_qty": 0.02,
        }
    )

    assert payload["recommended_preset"] == "manual_blank"
    assert payload["sizing_guard"]["blocked_preset_id"] == "eth_conservative"
    assert payload["sizing_guard"]["blocked_viability"]["min_notional_passes"] is True
    assert payload["sizing_guard"]["blocked_viability"]["min_qty_passes"] is False
    assert payload["sizing_guard"]["blocked_reason"] == "below_min_qty"
    assert payload["matched_signals"][0] == "exchange_order_sizing_guard"
