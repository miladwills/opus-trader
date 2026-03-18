import time

import services.bot_status_service as bot_status_module
from services.bot_status_service import BotStatusService
from services.position_service import PositionService


def make_service():
    service = BotStatusService.__new__(BotStatusService)
    service.neutral_scanner = None
    service.price_action_service = None
    service.scanner_cache_ttl_seconds = 20
    service._scanner_cache = {}
    service._readiness_stability_cache = {}
    service.stopped_preview_enabled = False
    service.stopped_preview_max_bots = 0
    service.stopped_preview_ttl_sec = 30
    service.stopped_preview_stale_sec = 120
    service._stopped_preview_cache = {}
    return service


class SequencedEntryReadinessService:
    def __init__(self, payloads):
        self.payloads = [dict(item) for item in list(payloads or [])]
        self.calls = 0

    def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
        if not self.payloads:
            return {}
        index = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return dict(self.payloads[index])


def readiness_payload(
    *,
    stage,
    reason,
    source_kind="runtime",
    preview_state=None,
    age_sec=None,
):
    normalized_stage = str(stage or "").strip().lower()
    readiness_status = "ready" if normalized_stage == "trigger_ready" else (
        "blocked" if normalized_stage == "blocked" else "watch"
    )
    payload = {
        "entry_ready_status": readiness_status,
        "entry_ready_reason": reason,
        "entry_ready_reason_text": reason.replace("_", " "),
        "analysis_ready_status": readiness_status,
        "analysis_ready_reason": reason,
        "analysis_ready_reason_text": reason.replace("_", " "),
        "analysis_ready_detail": f"{reason} detail",
        "setup_ready": normalized_stage == "trigger_ready",
        "setup_ready_status": readiness_status,
        "setup_ready_reason": reason,
        "setup_ready_reason_text": reason.replace("_", " "),
        "setup_ready_detail": f"{reason} detail",
        "setup_timing_status": normalized_stage,
        "setup_timing_reason": reason,
        "setup_timing_reason_text": reason.replace("_", " "),
        "setup_timing_detail": f"{reason} detail",
        "setup_timing_updated_at": "2026-03-13T00:00:00+00:00",
        "setup_timing_actionable": normalized_stage == "trigger_ready",
        "setup_timing_near_trigger": normalized_stage == "armed",
        "setup_timing_late": normalized_stage == "late",
        "readiness_source_kind": source_kind,
    }
    if preview_state is not None:
        payload["readiness_preview_state"] = preview_state
    if age_sec is not None:
        payload["readiness_preview_age_sec"] = age_sec
    return payload


def test_get_runtime_bots_skips_live_fetches_when_no_active_symbol_owners():
    service = make_service()
    service.bot_storage = type(
        "BotStorage",
        (),
        {
            "list_bots": lambda self: [
                {
                    "id": "bot-1",
                    "symbol": "BTCUSDT",
                    "mode": "long",
                    "status": "stopped",
                    "investment": 100.0,
                    "realized_pnl": 5.0,
                }
            ]
        },
    )()
    service.position_service = type(
        "PositionService",
        (),
        {
            "get_positions": lambda self: (_ for _ in ()).throw(
                AssertionError("position fetch should be skipped")
            )
        },
    )()
    service.symbol_pnl_service = type(
        "SymbolPnlService",
        (),
        {
            "get_all_symbols_pnl": lambda self: {},
            "get_all_bot_pnl": lambda self: {},
        },
    )()

    bots = service.get_runtime_bots()

    assert len(bots) == 1
    assert bots[0]["id"] == "bot-1"
    assert bots[0]["status"] == "stopped"


def test_runtime_positions_payload_restores_leverage_and_pct_to_liq():
    service = make_service()
    service.position_service = PositionService.__new__(PositionService)

    payload = service._normalize_runtime_positions_rows(
        [
            {
                "symbol": "BTCUSDT",
                "side": "Buy",
                "size": "1",
                "positionIdx": "1",
                "avgPrice": "100",
                "markPrice": "105",
                "liqPrice": "90",
                "leverage": "7",
                "positionValue": "105",
                "unrealisedPnl": "5",
            }
        ]
    )

    assert payload["positions"][0]["leverage"] == 7.0
    assert payload["positions"][0]["pct_to_liq"] == 14.29


def test_enrich_bot_exposes_analysis_readiness_and_live_gate_fields():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            return {
                "entry_ready_status": "watch",
                "entry_ready_reason": "entry_gate_disabled",
                "entry_ready_reason_text": "Gate off globally",
                "entry_ready_detail": "Directional entry gate disabled globally.",
                "entry_ready_source": "entry_gate_disabled_global",
                "analysis_ready_status": "ready",
                "analysis_ready_reason": "ready",
                "analysis_ready_reason_text": "Enter now",
                "analysis_ready_detail": "Entry conditions are clear right now.",
                "analysis_ready_source": "analysis_directional",
                "analysis_ready_severity": "INFO",
                "analysis_ready_next": "Analytically tradable now.",
                "analysis_ready_fallback_used": True,
                "analysis_ready_fallback_reason": "runtime_analysis_missing",
                "setup_ready": True,
                "setup_ready_status": "ready",
                "setup_ready_reason": "early_entry",
                "setup_ready_reason_text": "Early entry window",
                "setup_ready_detail": "Entry conditions are clear right now.",
                "setup_ready_source": "analysis_directional",
                "setup_ready_score": 83.0,
                "setup_ready_direction": "long",
                "setup_ready_mode": "long",
                "setup_ready_updated_at": "2026-03-13T00:00:00+00:00",
                "setup_ready_fallback_used": True,
                "setup_ready_fallback_reason": "runtime_analysis_missing",
                "execution_blocked": True,
                "execution_viability_status": "blocked",
                "execution_viability_reason": "insufficient_margin",
                "execution_viability_reason_text": "Insufficient margin",
                "execution_viability_bucket": "margin_limited",
                "execution_margin_limited": True,
                "execution_viability_detail": "Capital starved: need $4.16 opening margin, have $1.90",
                "execution_viability_source": "runtime_margin_guard",
                "execution_viability_diagnostic_reason": "insufficient_free_margin",
                "execution_viability_diagnostic_text": "Margin low",
                "execution_viability_diagnostic_detail": "Capital starved: need $4.16 opening margin, have $1.90",
                "execution_viability_stale_data": False,
                "execution_available_margin_usdt": 1.9,
                "execution_required_margin_usdt": 4.16,
                "execution_order_notional_usdt": 41.6,
                "execution_viability_updated_at": "2026-03-13T00:00:00+00:00",
                "readiness_source_kind": "fresh_fallback",
                "readiness_fallback_used": True,
                "readiness_evaluated_at": "2026-03-13T00:00:01+00:00",
                "readiness_eval_duration_ms": 12.5,
                "live_gate_status": "off_global",
                "live_gate_reason": "gate_off_global",
                "live_gate_reason_text": "Gate off globally",
                "live_gate_detail": "Directional live entry gate is disabled globally.",
                "live_gate_source": "entry_gate_disabled_global",
                "live_gate_bot_enabled": True,
                "live_gate_global_master_applicable": True,
                "live_gate_global_master_enabled": False,
                "live_gate_contract_active": False,
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-readiness-split",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 0.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["analysis_ready_status"] == "ready"
    assert enriched["analysis_ready_reason_text"] == "Enter now"
    assert enriched["analysis_ready_fallback_used"] is True
    assert enriched["setup_ready_status"] == "ready"
    assert enriched["setup_ready_reason"] == "early_entry"
    assert enriched["execution_blocked"] is True
    assert enriched["execution_viability_reason"] == "insufficient_margin"
    assert enriched["execution_viability_bucket"] == "margin_limited"
    assert enriched["execution_margin_limited"] is True
    assert enriched["execution_viability_diagnostic_reason"] == "insufficient_free_margin"
    assert enriched["execution_available_margin_usdt"] == 1.9
    assert enriched["execution_required_margin_usdt"] == 4.16
    assert enriched["execution_order_notional_usdt"] == 41.6
    assert enriched["readiness_source_kind"] == "fresh_fallback"
    assert enriched["readiness_eval_duration_ms"] == 12.5
    assert enriched["raw_readiness_stage"] == "trigger_ready"
    assert enriched["stable_readiness_stage"] == "trigger_ready"
    assert enriched["readiness_stability_state"] == "stable"
    assert enriched["setup_ready_age_sec"] is not None
    assert enriched["execution_viability_age_sec"] is not None
    assert enriched["live_gate_status"] == "off_global"
    assert enriched["live_gate_reason_text"] == "Gate off globally"
    assert enriched["live_gate_bot_enabled"] is True
    assert enriched["live_gate_global_master_enabled"] is False
    assert enriched["live_gate_contract_active"] is False
    assert enriched["entry_gate_enabled"] is True
    assert enriched["entry_gate_bot_enabled"] is True
    assert enriched["entry_gate_global_master_enabled"] is True
    assert enriched["entry_gate_contract_active"] is True


def test_enrich_bot_exposes_exchange_reconciliation_and_ambiguous_follow_up_fields():
    service = make_service()
    bot = {
        "id": "bot-reconcile",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "error",
        "investment": 100.0,
        "realized_pnl": 0.0,
        "exchange_reconciliation": {
            "status": "error_with_exchange_persist_divergence",
            "reason": "orphaned_position",
            "source": "startup",
            "updated_at": "2026-03-13T00:00:00+00:00",
            "mismatches": ["orphaned_position"],
        },
        "exchange_exposure_detected": True,
        "exchange_position_detected": True,
        "exchange_open_orders_detected": False,
        "position_assumption_stale": True,
        "order_assumption_stale": False,
        "ambiguous_execution_follow_up": {
            "status": "still_unresolved",
            "pending": False,
            "action": "create_order",
            "exchange_effect_reason": "exchange_owner_ambiguous",
            "updated_at": "2026-03-13T00:00:05+00:00",
            "truth_check_expired": True,
        },
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        positions_by_symbol={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["exchange_reconciliation_status"] == "error_with_exchange_persist_divergence"
    assert enriched["exchange_reconciliation_reason"] == "orphaned_position"
    assert enriched["exchange_reconciliation_source"] == "startup"
    assert enriched["exchange_reconciliation_mismatches"] == ["orphaned_position"]
    assert enriched["exchange_exposure_detected"] is True
    assert enriched["exchange_position_detected"] is True
    assert enriched["position_assumption_stale"] is True
    assert enriched["ambiguous_execution_follow_up_status"] == "still_unresolved"
    assert enriched["ambiguous_execution_follow_up_pending"] is False
    assert enriched["ambiguous_execution_follow_up_action"] == "create_order"
    assert enriched["ambiguous_execution_follow_up_reason"] == "exchange_owner_ambiguous"
    assert enriched["ambiguous_execution_follow_up_truth_check_expired"] is True


def test_get_runtime_bots_adds_latency_publish_markers():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            return {
                "entry_ready_status": "watch",
                "entry_ready_reason": "watch_setup",
                "entry_ready_reason_text": "Watch setup",
                "entry_ready_detail": "Waiting for follow through",
                "entry_ready_mode": "long",
                "entry_ready_direction": "long",
                "entry_ready_updated_at": "2026-03-13T00:00:00+00:00",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "watch_setup",
                "analysis_ready_reason_text": "Watch setup",
                "analysis_ready_detail": "Waiting for follow through",
                "analysis_ready_source": "analysis_directional",
                "analysis_ready_updated_at": "2026-03-13T00:00:00+00:00",
                "setup_ready_status": "watch",
                "setup_timing_status": "armed",
                "setup_timing_reason": "waiting_for_confirmation",
                "setup_timing_reason_text": "Armed for confirmation",
                "setup_timing_updated_at": "2026-03-13T00:00:00+00:00",
                "readiness_source_kind": "fresh_analysis",
                "market_data_ts": time.time() - 3.0,
                "market_data_at": "2026-03-13T00:00:00+00:00",
                "market_data_age_ms": 3000.0,
                "market_data_source": "stream_ticker",
                "readiness_eval_started_at": "2026-03-13T00:00:01+00:00",
                "readiness_eval_finished_at": "2026-03-13T00:00:01.100000+00:00",
                "readiness_generated_at": "2026-03-13T00:00:01.100000+00:00",
                "readiness_evaluated_at": "2026-03-13T00:00:01.100000+00:00",
                "readiness_eval_duration_ms": 100.0,
                "readiness_eval_ms": 100.0,
                "readiness_stage": "armed",
                "market_to_readiness_eval_start_ms": 2500.0,
                "market_to_readiness_eval_finished_ms": 2600.0,
            }

    service = make_service()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 1
    service.entry_readiness_service = FakeEntryReadinessService()
    service.bot_storage = type(
        "BotStorage",
        (),
        {
            "list_bots": lambda self: [
                {
                    "id": "bot-latency",
                    "symbol": "BTCUSDT",
                    "mode": "long",
                    "status": "stopped",
                    "investment": 100.0,
                    "realized_pnl": 0.0,
                }
            ]
        },
    )()
    service.position_service = type(
        "PositionService",
        (),
        {"get_positions": lambda self, skip_cache=False: {"positions": []}},
    )()
    service.symbol_pnl_service = type(
        "SymbolPnlService",
        (),
        {
            "get_all_symbols_pnl": lambda self: {},
            "get_all_bot_pnl": lambda self: {},
        },
    )()

    bots = service.get_runtime_bots()
    batch_context = service.get_last_runtime_batch_context()

    assert bots[0]["market_data_source"] == "stream_ticker"
    assert bots[0]["readiness_stage"] == "armed"
    assert bots[0]["runtime_publish_at"] is not None
    assert bots[0]["runtime_publish_age_ms"] is not None
    assert bots[0]["market_to_runtime_publish_ms"] >= bots[0]["market_to_readiness_eval_finished_ms"]
    assert bots[0]["readiness_latency_path"] == "stopped_preview"
    assert batch_context["runtime_publish_at"] is not None
    assert batch_context["readiness_latency"]["paths"]["stopped_preview"]["bot_count"] == 1
    assert batch_context["readiness_latency"]["dominant_segment"] is not None


def test_get_runtime_bots_separates_live_runtime_and_stopped_preview_latency():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            now_ts = time.time()
            if allow_stopped_analysis_preview:
                return {
                    "entry_ready_status": "trigger_ready",
                    "analysis_ready_status": "trigger_ready",
                    "setup_ready_status": "trigger_ready",
                    "setup_timing_status": "trigger_ready",
                    "analysis_ready_source": "analysis_directional",
                    "market_data_ts": now_ts - 4.0,
                    "market_data_source": "indicator_close",
                    "readiness_eval_finished_at": "2026-03-13T00:00:02+00:00",
                    "readiness_generated_at": "2026-03-13T00:00:02+00:00",
                    "readiness_eval_duration_ms": 8.0,
                    "readiness_stage": "trigger_ready",
                }
            return {
                "entry_ready_status": "ready",
                "analysis_ready_status": "ready",
                "setup_ready_status": "ready",
                "setup_timing_status": "armed",
                "analysis_ready_source": "runtime_analysis",
                "market_data_ts": now_ts - 0.5,
                "market_data_source": "orderbook_mid",
                "market_data_transport": "stream_orderbook",
                "market_data_price": 101.5,
                "bot_current_price_at": "2026-03-13T00:00:00+00:00",
                "bot_current_price_source": "runtime_cycle",
                "market_provider_at": "2026-03-13T00:00:01+00:00",
                "market_provider_source": "orderbook_mid",
                "market_provider_transport": "stream_orderbook",
                "market_provider_age_ms": 250.0,
                "ticker_provider_updated_at": "2026-03-13T00:00:01+00:00",
                "ticker_provider_age_ms": 250.0,
                "ticker_used_at_eval": "2026-03-13T00:00:01+00:00",
                "fresher_ticker_available": True,
                "market_data_refreshed_just_in_time": True,
                "market_data_refresh_reason": "provider_newer_than_bot",
                "market_data_refresh_delta_ms": 8500.0,
                "readiness_eval_finished_at": "2026-03-13T00:00:01+00:00",
                "readiness_generated_at": "2026-03-13T00:00:01+00:00",
                "readiness_eval_duration_ms": 1.5,
                "readiness_stage": "armed",
            }

    service = make_service()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 4
    service.entry_readiness_service = FakeEntryReadinessService()
    service.bot_storage = type(
        "BotStorage",
        (),
        {
            "list_bots": lambda self: [
                {
                    "id": "bot-live",
                    "symbol": "BTCUSDT",
                    "mode": "long",
                    "status": "running",
                    "investment": 100.0,
                    "realized_pnl": 0.0,
                    "current_price": 101.0,
                "current_price_updated_at": "2026-03-13T00:00:00+00:00",
                "price_metadata_written_early": True,
                "price_metadata_write_reason": "trusted_price_ready",
                "price_metadata_write_path": "neutral_pre_guard",
                "current_price_persist_delta_ms": 350.0,
                "current_price_persisted_before_guard": True,
                "provider_update_seen_at": "2026-03-13T00:00:00+00:00",
                "provider_update_to_eval_ms": 220.0,
                "reevaluation_trigger_reason": "orderbook",
                "reevaluation_trigger_path": "stream_guarded_price_lane",
                "blocked_guarded_fast_path_used": True,
                "evaluation_deferred_reason": "bot_cycle_lock_busy",
                "fresh_provider_seen_before_eval": True,
                },
                {
                    "id": "bot-preview",
                    "symbol": "ETHUSDT",
                    "mode": "long",
                    "status": "stopped",
                    "investment": 100.0,
                    "realized_pnl": 0.0,
                },
            ]
        },
    )()
    service.position_service = type(
        "PositionService",
        (),
        {
            "get_positions": lambda self, skip_cache=False: {
                "positions": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": 1.0,
                        "entry_price": 100.0,
                        "mark_price": 101.0,
                        "unrealized_pnl": 1.0,
                    }
                ]
            }
        },
    )()
    service.symbol_pnl_service = type(
        "SymbolPnlService",
        (),
        {
            "get_all_symbols_pnl": lambda self: {},
            "get_all_bot_pnl": lambda self: {},
        },
    )()
    service._build_live_open_orders_by_symbol = lambda bots, cache_only=False: {}
    service._get_scanner_recommendation_lookup = lambda bots, cache_only=False: {}

    bots = service.get_runtime_bots()
    batch_context = service.get_last_runtime_batch_context()
    by_id = {bot["id"]: bot for bot in bots}
    paths = batch_context["readiness_latency"]["paths"]

    assert by_id["bot-live"]["readiness_latency_path"] == "live_runtime"
    assert by_id["bot-preview"]["readiness_latency_path"] == "stopped_preview"
    assert by_id["bot-live"]["current_price_updated_at"] == "2026-03-13T00:00:00+00:00"
    assert by_id["bot-live"]["price_metadata_written_early"] is True
    assert by_id["bot-live"]["price_metadata_write_reason"] == "trusted_price_ready"
    assert by_id["bot-live"]["price_metadata_write_path"] == "neutral_pre_guard"
    assert by_id["bot-live"]["current_price_persist_delta_ms"] == 350.0
    assert by_id["bot-live"]["current_price_persisted_before_guard"] is True
    assert by_id["bot-live"]["provider_update_to_eval_ms"] == 220.0
    assert by_id["bot-live"]["reevaluation_trigger_reason"] == "orderbook"
    assert by_id["bot-live"]["reevaluation_trigger_path"] == "stream_guarded_price_lane"
    assert by_id["bot-live"]["blocked_guarded_fast_path_used"] is True
    assert by_id["bot-live"]["evaluation_deferred_reason"] == "bot_cycle_lock_busy"
    assert by_id["bot-live"]["fresh_provider_seen_before_eval"] is True
    assert by_id["bot-live"]["market_data_refreshed_just_in_time"] is True
    assert by_id["bot-live"]["market_data_refresh_reason"] == "provider_newer_than_bot"
    assert by_id["bot-live"]["market_provider_source"] == "orderbook_mid"
    assert by_id["bot-live"]["market_provider_transport"] == "stream_orderbook"
    assert by_id["bot-live"]["ticker_provider_age_ms"] == 250.0
    assert by_id["bot-live"]["fresher_ticker_available"] is True
    assert by_id["bot-preview"]["readiness_preview_refresh_ttl_sec"] == 6.0
    assert paths["live_runtime"]["bot_count"] == 1
    assert paths["stopped_preview"]["bot_count"] == 1
    assert paths["live_runtime"]["market_timestamp_missing_count"] == 0
    assert paths["live_runtime"]["provider_update_to_eval_ms"]["avg"] == 220.0
    assert paths["stopped_preview"]["stage_counts"]["trigger_ready"] == 1


def test_enrich_bot_exposes_configured_runtime_mode_split_and_readiness_matrix():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            mode = str(bot.get("mode") or "").strip().lower()
            statuses = {
                "long": ("ready", "good_continuation", 92.0),
                "short": ("blocked", "trend_conflict", 18.0),
                "neutral": ("watch", "waiting_range_confirmation", 55.0),
                "neutral_classic_bybit": ("ready", "range_established", 81.0),
                "scalp_pnl": ("watch", "waiting_pullback", 48.0),
            }
            status, reason, score = statuses.get(mode, ("watch", "preview_disabled", 0.0))
            return {
                "entry_ready_status": status,
                "entry_ready_reason": reason,
                "entry_ready_reason_text": reason.replace("_", " "),
                "entry_ready_detail": f"{mode} detail",
                "analysis_ready_status": status,
                "analysis_ready_reason": reason,
                "analysis_ready_reason_text": reason.replace("_", " "),
                "analysis_ready_detail": f"{mode} detail",
                "analysis_ready_score": score,
                "live_gate_status": "active",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-mode-split",
        "symbol": "BTCUSDT",
        "mode": "long",
        "configured_mode": "long",
        "range_mode": "dynamic",
        "configured_range_mode": "dynamic",
        "effective_runtime_mode": "short",
        "effective_runtime_range_mode": "trailing",
        "runtime_mode_source": "auto_direction",
        "runtime_mode_non_persistent": True,
        "mode_policy": "suggest_only",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 0.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )
    matrix = service._build_mode_readiness_matrix(
        enriched,
        configured_readiness={"analysis_ready_status": "ready", "analysis_ready_reason": "good_continuation"},
        scanner_recommended_mode="neutral_classic_bybit",
    )

    assert enriched["mode"] == "long"
    assert enriched["configured_mode"] == "long"
    assert enriched["effective_runtime_mode"] == "short"
    assert enriched["mode_policy"] == "suggest_only"
    assert enriched["runtime_mode_non_persistent"] is True
    assert matrix["configured_mode"] == "long"
    assert matrix["effective_runtime_mode"] == "short"
    assert matrix["mode_policy"] == "suggest_only"
    assert any(item["is_configured_mode"] and item["mode"] == "long" for item in matrix["items"])
    assert any(item["is_runtime_view"] and item["mode"] == "short" for item in matrix["items"])
    assert any(item["is_scanner_suggestion"] and item["mode"] == "neutral_classic_bybit" for item in matrix["items"])


def test_enrich_bot_exposes_best_alternative_mode_when_configured_mode_is_not_ready():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            mode = str(bot.get("mode") or "").strip().lower()
            statuses = {
                "long": ("watch", "waiting_pullback", 54.0),
                "short": ("watch", "trend_conflict", 22.0),
                "neutral": ("watch", "waiting_range_confirmation", 48.0),
                "neutral_classic_bybit": ("ready", "range_established", 81.0),
                "scalp_pnl": ("watch", "waiting_pullback", 40.0),
            }
            status, reason, score = statuses.get(mode, ("watch", "preview_disabled", 0.0))
            return {
                "entry_ready_status": status,
                "entry_ready_reason": reason,
                "analysis_ready_status": status,
                "analysis_ready_reason": reason,
                "analysis_ready_reason_text": reason.replace("_", " "),
                "analysis_ready_detail": f"{mode} detail",
                "analysis_ready_score": score,
                "setup_ready": status == "ready",
                "setup_ready_status": status,
                "setup_ready_reason": reason,
                "setup_ready_reason_text": reason.replace("_", " "),
                "setup_ready_detail": f"{mode} detail",
                "setup_ready_score": score,
                "execution_blocked": False,
                "execution_viability_status": "viable",
                "execution_viability_reason": "openings_clear",
                "execution_viability_reason_text": "Opening clear",
                "readiness_source_kind": "fresh_analysis",
                "live_gate_status": "on",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-alt-mode",
        "symbol": "ETHUSDT",
        "mode": "long",
        "configured_mode": "long",
        "range_mode": "dynamic",
        "configured_range_mode": "dynamic",
        "effective_runtime_mode": "long",
        "effective_runtime_range_mode": "dynamic",
        "mode_policy": "locked",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 0.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["setup_ready_status"] == "watch"
    assert enriched["alternative_mode_ready"] is True
    assert enriched["alternative_mode"] == "neutral_classic_bybit"
    assert enriched["alternative_mode_label"] == "Neutral Classic"
    assert enriched["alternative_mode_status"] == "trigger_ready"
    assert enriched["alternative_mode_reason"] == "range_established"
    assert enriched["alternative_mode_score"] == 81.0
    assert enriched["alternative_mode_actionable"] is True
    assert enriched["alternative_mode_is_scanner_suggestion"] is False


def test_build_stopped_preview_lookup_returns_bounded_preview_when_enabled():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            if allow_stopped_analysis_preview:
                return {
                    "entry_ready_status": "watch",
                    "entry_ready_reason": "preview_disabled",
                    "analysis_ready_status": "ready",
                    "analysis_ready_reason": "ready",
                    "analysis_ready_reason_text": "Enter now",
                    "analysis_ready_detail": "Entry conditions are clear right now.",
                    "analysis_ready_source": "analysis_directional",
                    "analysis_ready_severity": "INFO",
                    "analysis_ready_next": "Analytically tradable now.",
                    "setup_ready": True,
                    "setup_ready_status": "ready",
                    "setup_ready_reason": "early_entry",
                    "setup_ready_reason_text": "Early entry window",
                    "live_gate_status": "off_global",
                }
            return {
                "entry_ready_status": "watch",
                "entry_ready_reason": "preview_disabled",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "preview_disabled",
                "analysis_ready_reason_text": "Preview disabled",
                "analysis_ready_detail": "Stopped-bot analysis preview unavailable.",
                "analysis_ready_source": "runtime_only",
                "analysis_ready_severity": "INFO",
                "analysis_ready_next": "Enable preview.",
                "live_gate_status": "off_global",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 2

    lookup = service._build_stopped_preview_lookup(
        [
            {
                "id": "bot-stop-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "stopped",
            }
        ]
    )

    assert lookup["bot-stop-1"]["analysis_ready_status"] == "ready"
    assert lookup["bot-stop-1"]["setup_ready_status"] == "ready"
    assert lookup["bot-stop-1"]["live_gate_status"] == "off_global"
    assert lookup["bot-stop-1"]["readiness_source_kind"] == "stopped_preview"
    assert lookup["bot-stop-1"]["readiness_preview_age_sec"] == 0.0


def test_stopped_preview_ready_setup_uses_tighter_fresh_window_and_ages_out_earlier():
    service = make_service()
    service.entry_readiness_service = object()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 0
    service.stopped_preview_ttl_sec = 30
    service.stopped_preview_stale_sec = 120
    service._stopped_preview_cache = {
        "bot-stop-ready": {
            "payload": {
                "analysis_ready_status": "ready",
                "analysis_ready_reason": "good_continuation",
                "setup_ready": True,
                "setup_ready_status": "ready",
                "setup_ready_reason": "good_continuation",
            },
            "cached_at": time.time() - 13,
        }
    }

    lookup = service._build_stopped_preview_lookup(
        [
            {
                "id": "bot-stop-ready",
                "symbol": "ETHUSDT",
                "mode": "long",
                "status": "stopped",
            }
        ]
    )

    assert lookup["bot-stop-ready"]["analysis_ready_status"] == "watch"
    assert lookup["bot-stop-ready"]["setup_ready_status"] == "watch"
    assert lookup["bot-stop-ready"]["readiness_preview_state"] == "stale"
    assert lookup["bot-stop-ready"]["readiness_preview_fresh_ttl_sec"] == 9.0
    assert lookup["bot-stop-ready"]["readiness_preview_stale_after_sec"] == 27.0


def test_stopped_preview_watch_setup_can_remain_fresh_but_mark_preview_aging():
    service = make_service()
    service.entry_readiness_service = object()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 0
    service.stopped_preview_ttl_sec = 30
    service.stopped_preview_stale_sec = 120
    service._stopped_preview_cache = {
        "bot-stop-watch": {
            "payload": {
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "waiting_range_confirmation",
                "setup_ready": False,
                "setup_ready_status": "watch",
                "setup_ready_reason": "waiting_range_confirmation",
            },
            "cached_at": time.time() - 13,
        }
    }

    lookup = service._build_stopped_preview_lookup(
        [
            {
                "id": "bot-stop-watch",
                "symbol": "BTCUSDT",
                "mode": "neutral",
                "status": "stopped",
            }
        ]
    )

    assert lookup["bot-stop-watch"]["analysis_ready_status"] == "watch"
    assert lookup["bot-stop-watch"]["setup_ready_status"] == "watch"
    assert lookup["bot-stop-watch"]["readiness_source_kind"] == "stopped_preview"
    assert lookup["bot-stop-watch"]["readiness_preview_state"] == "aging"
    assert lookup["bot-stop-watch"]["readiness_preview_fresh_ttl_sec"] == 18.0
    assert lookup["bot-stop-watch"]["readiness_preview_stale_after_sec"] == 60.0


def test_build_stopped_preview_lookup_marks_cached_preview_stale_when_refresh_window_expires():
    service = make_service()
    service.entry_readiness_service = object()
    service.stopped_preview_enabled = True
    service.stopped_preview_max_bots = 0
    service.stopped_preview_ttl_sec = 5
    service.stopped_preview_stale_sec = 120
    service._stopped_preview_cache = {
        "bot-stop-1": {
            "payload": {
                "entry_ready_status": "ready",
                "entry_ready_reason": "good_continuation",
                "analysis_ready_status": "ready",
                "analysis_ready_reason": "ready",
                "analysis_ready_reason_text": "Enter now",
                "analysis_ready_detail": "Fresh preview",
                "setup_ready": True,
                "setup_ready_status": "ready",
                "setup_ready_reason": "early_entry",
                "setup_timing_status": "trigger_ready",
                "setup_timing_reason": "good_continuation",
                "setup_timing_reason_text": "Good continuation",
                "setup_timing_detail": "Fresh timing preview",
                "setup_timing_actionable": True,
                "live_gate_status": "off_global",
            },
            "cached_at": time.time() - 15,
        }
    }

    lookup = service._build_stopped_preview_lookup(
        [
            {
                "id": "bot-stop-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "status": "stopped",
            }
        ]
    )

    assert lookup["bot-stop-1"]["analysis_ready_reason"] == "stale_snapshot"
    assert lookup["bot-stop-1"]["entry_ready_status"] == "watch"
    assert lookup["bot-stop-1"]["analysis_ready_status"] == "watch"
    assert lookup["bot-stop-1"]["setup_ready_status"] == "watch"
    assert lookup["bot-stop-1"]["setup_ready_reason"] == "stale_snapshot"
    assert lookup["bot-stop-1"]["setup_timing_status"] == "watch"
    assert lookup["bot-stop-1"]["setup_timing_reason"] == "stale_snapshot"
    assert lookup["bot-stop-1"]["setup_timing_actionable"] is False
    assert lookup["bot-stop-1"]["readiness_source_kind"] == "stopped_preview_stale"
    assert lookup["bot-stop-1"]["readiness_preview_age_sec"] >= 15.0


def test_stale_stopped_preview_never_leaks_trigger_ready_from_surviving_timing_fields():
    service = make_service()
    service.entry_readiness_service = object()
    bot = {
        "id": "bot-stop-stale",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "stopped",
    }

    payload = service._get_entry_readiness(
        bot=bot,
        symbol_position={},
        position={},
        stopped_preview_lookup={
            "bot-stop-stale": {
                **readiness_payload(
                    stage="trigger_ready",
                    reason="good_continuation",
                    source_kind="stopped_preview_stale",
                    preview_state="stale",
                    age_sec=45.0,
                ),
                "setup_timing_status": "trigger_ready",
                "setup_timing_reason": "good_continuation",
                "setup_timing_actionable": True,
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "stale_snapshot",
                "setup_ready_status": "watch",
                "setup_ready_reason": "stale_snapshot",
            }
        },
    )

    assert payload["raw_readiness_stage"] == "watch"
    assert payload["stable_readiness_stage"] == "watch"
    assert payload["stable_readiness_actionable"] is False
    assert payload["readiness_hard_invalidated"] is True


def test_get_entry_readiness_propagates_stopped_preview_age_metadata():
    service = make_service()
    service.entry_readiness_service = object()

    payload = service._get_entry_readiness(
        bot={"id": "bot-stop-1", "symbol": "BTCUSDT", "mode": "long", "status": "stopped"},
        symbol_position={},
        position={},
        stopped_preview_lookup={
            "bot-stop-1": {
                "analysis_ready_status": "ready",
                "setup_ready_status": "ready",
                "readiness_source_kind": "stopped_preview",
                "readiness_preview_age_sec": 7.5,
            }
        },
    )

    assert payload["readiness_source_kind"] == "stopped_preview"
    assert payload["readiness_source_age_sec"] == 7.5


def test_live_readiness_stability_holds_soft_near_threshold_flap(monkeypatch):
    service = make_service()
    service.entry_readiness_service = SequencedEntryReadinessService(
        [
            readiness_payload(stage="trigger_ready", reason="good_continuation"),
            readiness_payload(stage="armed", reason="continuation_entry"),
            readiness_payload(stage="trigger_ready", reason="good_continuation"),
        ]
    )
    now = {"value": 1000.0}
    monkeypatch.setattr(bot_status_module.time, "time", lambda: now["value"])
    bot = {
        "id": "bot-live-stable",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
    }

    first = service._get_entry_readiness(bot=bot, symbol_position={}, position={})
    now["value"] = 1001.0
    second = service._get_entry_readiness(bot=bot, symbol_position={}, position={})
    now["value"] = 1002.0
    third = service._get_entry_readiness(bot=bot, symbol_position={}, position={})

    assert first["raw_readiness_stage"] == "trigger_ready"
    assert first["stable_readiness_stage"] == "trigger_ready"
    assert second["raw_readiness_stage"] == "armed"
    assert second["stable_readiness_stage"] == "trigger_ready"
    assert second["stable_readiness_actionable"] is True
    assert second["readiness_stability_state"] == "holding"
    assert second["readiness_flip_suppressed"] is True
    assert second["readiness_hard_invalidated"] is False
    assert third["raw_readiness_stage"] == "trigger_ready"
    assert third["stable_readiness_stage"] == "trigger_ready"
    assert third["readiness_stability_state"] == "stable"


def test_live_readiness_stability_drops_immediately_on_hard_invalidation(monkeypatch):
    service = make_service()
    service.entry_readiness_service = SequencedEntryReadinessService(
        [
            readiness_payload(stage="trigger_ready", reason="good_continuation"),
            readiness_payload(stage="late", reason="late_continuation"),
        ]
    )
    now = {"value": 2000.0}
    monkeypatch.setattr(bot_status_module.time, "time", lambda: now["value"])
    bot = {
        "id": "bot-live-hard",
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "running",
    }

    service._get_entry_readiness(bot=bot, symbol_position={}, position={})
    now["value"] = 2001.0
    second = service._get_entry_readiness(bot=bot, symbol_position={}, position={})

    assert second["raw_readiness_stage"] == "late"
    assert second["stable_readiness_stage"] == "late"
    assert second["stable_readiness_actionable"] is False
    assert second["readiness_stability_state"] == "hard_invalidated"
    assert second["readiness_hard_invalidated"] is True
    assert second["readiness_flip_suppressed"] is False


def test_live_readiness_stability_remains_bounded_and_demotes_after_repeat(monkeypatch):
    service = make_service()
    service.entry_readiness_service = SequencedEntryReadinessService(
        [
            readiness_payload(stage="trigger_ready", reason="good_continuation"),
            readiness_payload(stage="watch", reason="watch_setup"),
            readiness_payload(stage="watch", reason="watch_setup"),
        ]
    )
    now = {"value": 3000.0}
    monkeypatch.setattr(bot_status_module.time, "time", lambda: now["value"])
    bot = {
        "id": "bot-live-repeat",
        "symbol": "SOLUSDT",
        "mode": "long",
        "status": "running",
    }

    service._get_entry_readiness(bot=bot, symbol_position={}, position={})
    now["value"] = 3001.0
    second = service._get_entry_readiness(bot=bot, symbol_position={}, position={})
    now["value"] = 3002.0
    third = service._get_entry_readiness(bot=bot, symbol_position={}, position={})

    assert second["stable_readiness_stage"] == "trigger_ready"
    assert second["readiness_stability_state"] == "holding"
    assert third["raw_readiness_stage"] == "watch"
    assert third["stable_readiness_stage"] == "watch"
    assert third["readiness_stability_state"] == "stable"
    assert third["stable_readiness_actionable"] is False


def test_stopped_preview_stability_is_stronger_but_stale_preview_cuts_through(monkeypatch):
    service = make_service()
    service.entry_readiness_service = object()
    now = {"value": 4000.0}
    monkeypatch.setattr(bot_status_module.time, "time", lambda: now["value"])
    bot = {
        "id": "bot-preview-stable",
        "symbol": "XRPUSDT",
        "mode": "long",
        "status": "stopped",
    }

    first = service._get_entry_readiness(
        bot=bot,
        symbol_position={},
        position={},
        stopped_preview_lookup={
            "bot-preview-stable": readiness_payload(
                stage="trigger_ready",
                reason="good_continuation",
                source_kind="stopped_preview",
                preview_state="fresh",
                age_sec=0.0,
            )
        },
    )
    now["value"] = 4002.0
    second = service._get_entry_readiness(
        bot=bot,
        symbol_position={},
        position={},
        stopped_preview_lookup={
            "bot-preview-stable": readiness_payload(
                stage="watch",
                reason="watch_setup",
                source_kind="stopped_preview",
                preview_state="aging",
                age_sec=4.0,
            )
        },
    )
    now["value"] = 4004.0
    third = service._get_entry_readiness(
        bot=bot,
        symbol_position={},
        position={},
        stopped_preview_lookup={
            "bot-preview-stable": readiness_payload(
                stage="watch",
                reason="stale_snapshot",
                source_kind="stopped_preview_stale",
                preview_state="stale",
                age_sec=20.0,
            )
        },
    )

    assert first["readiness_stability_policy"] == "stopped_preview"
    assert second["raw_readiness_stage"] == "watch"
    assert second["stable_readiness_stage"] == "trigger_ready"
    assert second["readiness_stability_state"] == "holding"
    assert second["readiness_flip_suppressed"] is True
    assert third["raw_readiness_reason"] == "stale_snapshot"
    assert third["stable_readiness_stage"] == "watch"
    assert third["readiness_hard_invalidated"] is True
    assert third["stable_readiness_actionable"] is False


def test_build_preview_disabled_stopped_payload_keeps_setup_fields_in_sync():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot, allow_stopped_analysis_preview=None):
            return {
                "analysis_ready_status": "ready",
                "analysis_ready_reason": "good_continuation",
                "setup_ready": True,
                "setup_ready_status": "ready",
                "setup_ready_reason": "good_continuation",
            }

    # When preview is enabled, deferred bots compute full analysis
    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    service.stopped_preview_enabled = True

    payload = service._build_preview_disabled_stopped_payload(
        {"id": "bot-stop-2", "symbol": "ETHUSDT", "mode": "long", "status": "stopped"}
    )

    assert payload["analysis_ready_status"] == "ready"
    assert payload["setup_ready_status"] == "ready"
    assert payload["setup_ready_reason"] == "good_continuation"
    assert payload["readiness_source_kind"] == "stopped_preview_deferred"

    # When preview is disabled, fields are overwritten to watch/preview_disabled
    service2 = make_service()
    service2.entry_readiness_service = FakeEntryReadinessService()
    service2.stopped_preview_enabled = False

    payload2 = service2._build_preview_disabled_stopped_payload(
        {"id": "bot-stop-3", "symbol": "ETHUSDT", "mode": "long", "status": "stopped"}
    )

    assert payload2["analysis_ready_status"] == "watch"
    assert payload2["setup_ready_status"] == "watch"
    assert payload2["setup_ready_reason"] == "preview_disabled"
    assert payload2["readiness_source_kind"] == "stopped_preview_unavailable"


def test_enrich_bot_uses_symbol_wide_pnl_and_investment_based_tp_progress():
    service = make_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "range_mode": "dynamic",
        "status": "running",
        "investment": 100.0,
        "leverage": 10.0,
        "realized_pnl": 5.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={
            "BTCUSDT": {
                "size": 1.0,
                "side": "Buy",
                "unrealized_pnl": 20.0,
                "entry_price": 100.0,
                "mark_price": 102.0,
            }
        },
        symbol_pnl_lookup={
            "BTCUSDT": {
                "net_pnl": 300.0,
                "total_profit": 420.0,
                "total_loss": 120.0,
                "trade_count": 20,
                "win_count": 12,
            }
        },
        bot_pnl_lookup={
            "bot-1": {
                "net_pnl": 25.0,
                "total_profit": 35.0,
                "total_loss": 10.0,
                "trade_count": 2,
                "win_count": 1,
            }
        },
        running_bot_ids_by_symbol={"BTCUSDT": ["bot-1"]},
    )

    assert enriched["pnl_pct"] == 0.25
    assert enriched["position_profit_pct"] == 0.02
    assert enriched["symbol_pnl"]["net_pnl"] == 300.0
    assert enriched["bot_pnl"]["net_pnl"] == 25.0


def test_enrich_bot_exposes_current_session_pnl_from_realized_baseline():
    service = make_service()
    bot = {
        "id": "bot-session",
        "symbol": "BTCUSDT",
        "mode": "long",
        "range_mode": "dynamic",
        "status": "running",
        "investment": 100.0,
        "leverage": 10.0,
        "realized_pnl": 5.0,
        "tp_session_realized_baseline": 3.0,
        "started_at": "2026-03-07T10:00:00+00:00",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={
            "BTCUSDT": {
                "size": 1.0,
                "side": "Buy",
                "unrealized_pnl": 1.5,
                "entry_price": 100.0,
                "mark_price": 101.0,
            }
        },
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={"BTCUSDT": ["bot-session"]},
    )

    assert enriched["total_pnl"] == 6.5
    assert enriched["session_realized_pnl"] == 2.0
    assert enriched["session_total_pnl"] == 3.5
    assert enriched["session_profit_per_hour"] is not None


def test_enrich_bot_suppresses_profit_per_hour_for_sub_minute_runtime():
    service = make_service()
    bot = {
        "id": "bot-2",
        "symbol": "ETHUSDT",
        "mode": "neutral",
        "status": "stopped",
        "investment": 50.0,
        "realized_pnl": 4.0,
        "accumulated_runtime_hours": 0.0005,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["runtime_hours"] == 0.0005
    assert enriched["profit_per_hour"] is None


def test_enrich_bot_freezes_lifetime_at_stop_control_timestamp():
    service = make_service()
    bot = {
        "id": "bot-3",
        "symbol": "SOLUSDT",
        "mode": "neutral",
        "status": "stopped",
        "investment": 50.0,
        "realized_pnl": 6.0,
        "created_at": "2026-03-07T10:00:00+00:00",
        "started_at": "2026-03-07T11:30:00+00:00",
        "control_updated_at": "2026-03-07T12:00:00+00:00",
        "updated_at": "2026-03-07T14:30:00+00:00",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["started_at"] is None
    assert enriched["lifetime_hours"] == 2.0


def test_enrich_bot_attributes_live_position_to_unique_paused_bot():
    service = make_service()
    bot = {
        "id": "bot-paused",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "paused",
        "investment": 100.0,
        "realized_pnl": 2.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={
            "BTCUSDT": {
                "size": 1.5,
                "side": "Buy",
                "unrealized_pnl": 3.5,
                "entry_price": 100.0,
                "mark_price": 101.0,
            }
        },
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={"BTCUSDT": ["bot-paused"]},
    )

    assert enriched["position_size"] == 1.5
    assert enriched["position_side"] == "Buy"
    assert enriched["unrealized_pnl"] == 3.5


def test_enrich_bot_marks_multi_leg_symbol_positions_without_claiming_single_leg():
    service = make_service()
    bot = {
        "id": "bot-hedge",
        "symbol": "BTCUSDT",
        "mode": "neutral",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
    }
    positions_by_symbol = {
        "BTCUSDT": [
            {
                "size": 1.5,
                "side": "Buy",
                "position_idx": 1,
                "unrealized_pnl": 3.5,
                "entry_price": 100.0,
                "mark_price": 101.0,
            },
            {
                "size": 1.0,
                "side": "Sell",
                "position_idx": 2,
                "unrealized_pnl": -1.25,
                "entry_price": 102.0,
                "mark_price": 101.0,
            },
        ]
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={
            "BTCUSDT": {
                "size": 1.0,
                "side": "Sell",
                "unrealized_pnl": -1.25,
                "entry_price": 102.0,
                "mark_price": 101.0,
            }
        },
        positions_by_symbol=positions_by_symbol,
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={"BTCUSDT": ["bot-hedge"]},
    )

    assert enriched["live_position_attribution"] == "symbol_multi_leg"
    # Multi-leg now uses the largest leg as primary position reference
    assert enriched["position_size"] == 1.5
    assert enriched["position_side"] == "Buy"
    assert enriched["unrealized_pnl"] == 2.25


def test_position_owner_lookup_includes_paused_and_recovering_bots():
    lookup = BotStatusService._build_running_bot_ids_by_symbol(
        [
            {"id": "bot-run", "symbol": "BTCUSDT", "status": "running"},
            {"id": "bot-pause", "symbol": "ETHUSDT", "status": "paused"},
            {"id": "bot-rec", "symbol": "SOLUSDT", "status": "recovering"},
            {"id": "bot-stop", "symbol": "XRPUSDT", "status": "stopped"},
        ]
    )

    assert lookup == {
        "BTCUSDT": ["bot-run"],
        "ETHUSDT": ["bot-pause"],
        "SOLUSDT": ["bot-rec"],
    }


def test_enrich_bot_exposes_price_action_runtime_fields():
    class FakePriceActionService:
        def analyze(self, symbol, current_price=None):
            return {
                "direction": "bearish",
                "net_score": -9.5,
                "summary": "Bearish liquidity sweep + wick rejection",
            }

        def score_mode_fit(self, context, mode):
            return {"score": 6.5, "summary": f"{mode} fit net={context['net_score']:.1f}"}

    service = make_service()
    service.price_action_service = FakePriceActionService()
    bot = {
        "id": "bot-price-action",
        "symbol": "BTCUSDT",
        "mode": "short",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["price_action_direction"] == "bearish"
    assert enriched["price_action_score"] == -9.5
    assert enriched["price_action_summary"] == "Bearish liquidity sweep + wick rejection"
    assert enriched["price_action_mode_fit_score"] == 6.5


def test_enrich_bot_exposes_entry_readiness_runtime_fields():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "blocked",
                "entry_ready_reason": "near_resistance",
                "entry_ready_reason_text": "Near resistance",
                "entry_ready_detail": "Resistance 0.40% away @ 100.4000 (strength=7)",
                "entry_ready_score": 58.0,
                "entry_ready_direction": "long",
                "entry_ready_mode": "long",
                "entry_ready_updated_at": "2026-03-09T10:00:00+00:00",
                "entry_ready_source": "entry_gate",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-readiness",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_status"] == "blocked"
    assert enriched["entry_ready_reason"] == "near_resistance"
    assert enriched["entry_ready_reason_text"] == "Near resistance"
    assert enriched["entry_ready_detail"].startswith("Resistance 0.40% away")
    assert enriched["entry_ready_score"] == 58.0
    assert enriched["entry_ready_direction"] == "long"
    assert enriched["entry_ready_mode"] == "long"
    assert enriched["entry_ready_source"] == "entry_gate"


def test_enrich_bot_keeps_symbol_daily_kill_switch_cleanup_pending_truthful():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "watch",
                "entry_ready_reason": "stop_cleanup_pending",
                "entry_ready_reason_text": "Stop cleanup pending",
                "entry_ready_detail": "Cleanup is still pending.",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "stop_cleanup_pending",
                "analysis_ready_reason_text": "Stop cleanup pending",
                "analysis_ready_detail": "Cleanup is still pending.",
                "setup_ready": False,
                "setup_ready_status": "watch",
                "setup_ready_reason": "stop_cleanup_pending",
                "setup_ready_reason_text": "Stop cleanup pending",
                "setup_ready_detail": "Cleanup is still pending.",
                "setup_timing_status": "watch",
                "setup_timing_reason": "stop_cleanup_pending",
                "setup_timing_reason_text": "Stop cleanup pending",
                "setup_timing_detail": "Cleanup is still pending.",
                "execution_blocked": True,
                "execution_viability_status": "blocked",
                "execution_viability_reason": "stop_cleanup_pending",
                "execution_viability_reason_text": "Stop cleanup pending",
                "execution_viability_detail": "Waiting for symbol-level cleanup confirmation.",
                "execution_viability_diagnostic_reason": "stop_cleanup_pending",
                "execution_viability_diagnostic_text": "Stop cleanup pending",
                "execution_viability_diagnostic_detail": "Waiting for flat/orders clear.",
                "readiness_source_kind": "stop_cleanup_pending",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-symbol-daily-pending",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "stop_cleanup_pending",
        "stop_cleanup_pending": True,
        "stop_cleanup_reason": "symbol_daily_kill_switch",
        "reduce_only_mode": True,
        "_block_opening_orders": True,
        "investment": 100.0,
        "realized_pnl": 0.0,
        "last_error": "Symbol daily loss stop triggered: $-12.50 <= -$5.00 (cleanup pending: waiting for flat/orders clear)",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["status"] == "stop_cleanup_pending"
    assert enriched["risk_stopped"] is False
    assert enriched["execution_viability_reason"] == "stop_cleanup_pending"
    assert enriched["execution_viability_diagnostic_reason"] == "stop_cleanup_pending"
    assert enriched["readiness_source_kind"] == "stop_cleanup_pending"
    assert enriched["last_error"].startswith("Symbol daily loss stop triggered:")


def test_enrich_bot_hides_stale_capital_starved_fields_when_structure_is_current_blocker():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "blocked",
                "entry_ready_reason": "near_resistance",
                "entry_ready_reason_text": "Near resistance",
                "entry_ready_detail": "Resistance 0.40% away @ 100.4000 (strength=7)",
                "entry_ready_source": "entry_gate",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-stale-capital",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "notional_below_min",
        "_capital_starved_warning_text": "Capital starved: order $0.00 below min $5.00",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_reason"] == "near_resistance"
    assert enriched["capital_starved_block_opening_orders"] is False
    assert enriched["capital_starved_reason"] is None
    assert enriched["capital_starved_warning_text"] is None
    assert bot["_capital_starved_block_opening_orders"] is True
    assert bot["capital_starved_reason"] == "notional_below_min"


def test_enrich_bot_preserves_active_capital_starved_fields_when_current_blocker_is_margin():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "blocked",
                "entry_ready_reason": "insufficient_margin",
                "entry_ready_reason_text": "Insufficient margin",
                "entry_ready_detail": "Capital starved: need $2.45 opening margin, have $2.14",
                "entry_ready_source": "runtime_margin_guard",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-live-capital",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "insufficient_margin",
        "_capital_starved_warning_text": "Capital starved: need $2.45 opening margin, have $2.14",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_reason"] == "insufficient_margin"
    assert enriched["capital_starved_block_opening_orders"] is True
    assert enriched["capital_starved_reason"] == "insufficient_margin"
    assert "need $2.45 opening margin" in enriched["capital_starved_warning_text"]


def test_enrich_bot_treats_reserve_limited_execution_as_margin_limited():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "blocked",
                "entry_ready_reason": "opening_margin_reserve",
                "entry_ready_reason_text": "Reserve limited",
                "entry_ready_detail": "Reserve limited: need $2.45 opening margin, usable after reserve $2.14",
                "entry_ready_source": "runtime_opening_margin_reserve",
                "execution_blocked": True,
                "execution_viability_status": "blocked",
                "execution_viability_reason": "opening_margin_reserve",
                "execution_viability_reason_text": "Reserve limited",
                "execution_viability_bucket": "margin_limited",
                "execution_margin_limited": True,
                "execution_viability_detail": "Reserve limited: need $2.45 opening margin, usable after reserve $2.14",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-live-reserve",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "opening_margin_reserve",
        "_capital_starved_warning_text": "Reserve limited: need $2.45 opening margin, usable after reserve $2.14",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_reason"] == "opening_margin_reserve"
    assert enriched["execution_viability_bucket"] == "margin_limited"
    assert enriched["execution_margin_limited"] is True
    assert enriched["capital_starved_reason"] == "opening_margin_reserve"


def test_enrich_bot_preserves_active_capital_starved_fields_for_live_min_size_blocker():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "blocked",
                "entry_ready_reason": "qty_below_min",
                "entry_ready_reason_text": "Entry size below minimum",
                "entry_ready_detail": "Capital starved: order $0.00 below min $5.00",
                "entry_ready_source": "runtime_qty_floor",
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-live-min-size",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 2.0,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "notional_below_min",
        "_capital_starved_warning_text": "Capital starved: order $0.00 below min $5.00",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_reason"] == "qty_below_min"
    assert enriched["capital_starved_block_opening_orders"] is True
    assert enriched["capital_starved_reason"] == "notional_below_min"
    assert "below min $5.00" in enriched["capital_starved_warning_text"]


def test_enrich_bot_hides_stale_capital_starved_fields_when_watchdog_marks_them_inactive():
    class FakeEntryReadinessService:
        def evaluate_bot(self, bot):
            return {
                "entry_ready_status": "ready",
                "entry_ready_reason": "early_entry",
                "entry_ready_reason_text": "Early entry window",
                "entry_ready_detail": "Entry conditions are clear right now.",
                "entry_ready_source": "analysis_directional",
                "setup_ready": True,
                "setup_ready_status": "ready",
                "execution_blocked": False,
                "execution_viability_status": "viable",
                "execution_viability_reason": "openings_clear",
                "execution_viability_reason_text": "Opening clear",
                "execution_viability_bucket": "viable",
                "execution_margin_limited": False,
                "execution_viability_diagnostic_reason": "stale_balance",
                "execution_viability_diagnostic_text": "Stale balance",
                "execution_viability_diagnostic_detail": "Saved capital check is stale for this stopped bot.",
                "execution_viability_stale_data": True,
            }

    service = make_service()
    service.entry_readiness_service = FakeEntryReadinessService()
    bot = {
        "id": "bot-stale-watchdog",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "stopped",
        "investment": 100.0,
        "realized_pnl": 2.0,
        "_capital_starved_block_opening_orders": True,
        "capital_starved_reason": "insufficient_margin",
        "_capital_starved_warning_text": "Capital starved: need $2.45 opening margin, have $2.14",
        "watchdog_bottleneck_summary": {
            "capital_starved_active": False,
        },
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["entry_ready_reason"] == "early_entry"
    assert enriched["capital_starved_block_opening_orders"] is False
    assert enriched["capital_starved_reason"] is None
    assert enriched["capital_starved_warning_text"] is None
    assert enriched["execution_viability_diagnostic_reason"] == "stale_balance"
    assert enriched["execution_viability_stale_data"] is True


def test_runtime_signal_blocker_hides_stale_inactive_blocker_diagnostics():
    bot = {
        "status": "stopped",
        "_watchdog_position_cap_active": True,
    }
    entry_readiness = {
        "execution_blocked": False,
        "execution_viability_stale_data": True,
        "execution_viability_diagnostic_reason": "stale_runtime_blocker",
    }

    blocker = BotStatusService._get_runtime_signal_blocker(
        bot,
        entry_readiness=entry_readiness,
    )

    assert blocker is None


def test_enrich_bot_exposes_auto_pilot_blocked_pick_runtime_fields():
    service = make_service()
    bot = {
        "id": "bot-auto-pilot",
        "symbol": "Auto-Pilot",
        "mode": "neutral",
        "status": "running",
        "auto_pilot": True,
        "investment": 100.0,
        "realized_pnl": 0.0,
        "auto_pilot_search_status": "ok",
        "auto_pilot_pick_status": "blocked_loss_budget",
        "auto_pilot_block_reason": "remaining_loss_budget",
        "auto_pilot_top_candidate_symbol": "SUIUSDT",
        "auto_pilot_top_candidate_score": 99.4,
        "auto_pilot_top_candidate_mode": "long",
        "auto_pilot_top_candidate_eligibility": "eligible_conservative",
        "auto_pilot_candidate_source": "cache",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["auto_pilot_search_status"] == "ok"
    assert enriched["auto_pilot_pick_status"] == "blocked_loss_budget"
    assert enriched["auto_pilot_block_reason"] == "remaining_loss_budget"
    assert enriched["auto_pilot_top_candidate_symbol"] == "SUIUSDT"
    assert enriched["auto_pilot_top_candidate_score"] == 99.4
    assert enriched["auto_pilot_top_candidate_mode"] == "long"
    assert enriched["auto_pilot_top_candidate_eligibility"] == "eligible_conservative"
    assert enriched["auto_pilot_candidate_source"] == "cache"


def test_enrich_bot_exposes_auto_pilot_universe_runtime_fields():
    service = make_service()
    bot = {
        "id": "bot-auto-pilot-mode",
        "symbol": "Auto-Pilot",
        "mode": "neutral",
        "status": "running",
        "auto_pilot": True,
        "investment": 100.0,
        "realized_pnl": 0.0,
        "auto_pilot_universe_mode": "aggressive_full",
        "auto_pilot_universe_summary": (
            "mode=aggressive_full | innovation=allowed | new_listings=allowed"
        ),
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["auto_pilot_universe_mode"] == "aggressive_full"
    assert "mode=aggressive_full" in enriched["auto_pilot_universe_summary"]


def test_enrich_bot_exposes_breakout_confirmed_entry_flag():
    service = make_service()
    bot = {
        "id": "bot-breakout",
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 0.0,
        "breakout_confirmed_entry": True,
        "breakout_entry_confirmed": True,
        "breakout_reference_level": 100.0,
        "breakout_reference_type": "resistance",
        "breakout_no_chase_blocked": True,
        "breakout_no_chase_reason": "Breakout entry blocked: no-chase extension too far",
        "breakout_invalidation_state": "trimmed",
        "breakout_invalidation_reason": "reclaim below broken resistance",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["breakout_confirmed_entry"] is True
    assert enriched["breakout_entry_confirmed"] is True
    assert enriched["breakout_reference_level"] == 100.0
    assert enriched["breakout_reference_type"] == "resistance"
    assert enriched["breakout_no_chase_blocked"] is True
    assert "no-chase" in enriched["breakout_no_chase_reason"]
    assert enriched["breakout_invalidation_state"] == "trimmed"
    assert enriched["breakout_invalidation_reason"] == "reclaim below broken resistance"


def test_enrich_bot_exposes_profit_protection_fields():
    service = make_service()
    bot = {
        "id": "bot-profit-protect",
        "symbol": "ETHUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "realized_pnl": 0.0,
        "profit_protection_mode": "shadow",
        "profit_protection_advisory": {
            "mode": "shadow",
            "decision": "watch_closely",
            "reason_family": "momentum_fading",
            "current_profit_pct": 0.007,
            "peak_profit_pct": 0.011,
            "giveback_pct": 0.004,
            "giveback_threshold_pct": 0.0045,
        },
        "profit_protection_shadow": {
            "status": "triggered",
            "result": "saved_giveback",
        },
        "profit_protection_decision": "watch_closely",
        "profit_protection_reason_family": "momentum_fading",
        "profit_protection_wait_justified": False,
        "profit_protection_actionable": False,
        "profit_protection_armed": True,
        "profit_protection_blocked": False,
        "profit_protection_current_profit_pct": 0.007,
        "profit_protection_peak_profit_pct": 0.011,
        "profit_protection_giveback_pct": 0.004,
        "profit_protection_giveback_threshold_pct": 0.0045,
        "profit_protection_shadow_status": "triggered",
        "profit_protection_last_action": "profit_protection_partial",
        "profit_protection_last_action_at": "2026-03-14T09:00:00+00:00",
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["profit_protection_mode"] == "shadow"
    assert enriched["profit_protection_advisory"]["decision"] == "watch_closely"
    assert enriched["profit_protection_shadow"]["result"] == "saved_giveback"
    assert enriched["profit_protection_decision"] == "watch_closely"
    assert enriched["profit_protection_reason_family"] == "momentum_fading"
    assert enriched["profit_protection_armed"] is True
    assert enriched["profit_protection_giveback_threshold_pct"] == 0.0045
    assert enriched["profit_protection_shadow_status"] == "triggered"
