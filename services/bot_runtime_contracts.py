"""
Bot runtime field contracts.

Defines which fields belong to the LIGHT (dashboard-critical) vs HEAVY
(analytics/diagnostic) tiers.  The light set is derived from an exhaustive
audit of every consumer in app_lf.js, app_v5.js, and backend secondary
services (watchdog, triage, advisor).

Heavy-only fields are used exclusively in the bot-detail modal or have
zero frontend references.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# HEAVY-ONLY fields — bot detail modal, diagnostics, or zero frontend refs
# ---------------------------------------------------------------------------
BOT_RUNTIME_HEAVY_ONLY_FIELDS: frozenset = frozenset(
    {
        # Mode readiness matrix — modal table only (app_lf.js:12426)
        "mode_readiness_matrix",
        # Performance baseline / summary — modal only
        "performance_baseline",
        "performance_summary",
        # Analysis timing diagnostics (11 fields, zero frontend references)
        "analysis_timing_status",
        "analysis_timing_reason",
        "analysis_timing_reason_text",
        "analysis_timing_detail",
        "analysis_timing_next",
        "analysis_timing_score",
        "analysis_timing_direction",
        "analysis_timing_mode",
        "analysis_timing_updated_at",
        "analysis_timing_source",
        # analysis_timing_actionable and analysis_timing_near_trigger are used
        # by watchdog_hub_service but via the full payload path, not light.
        "analysis_timing_actionable",
        "analysis_timing_near_trigger",
        "analysis_timing_late",
        # Readiness evaluation diagnostics (zero frontend references)
        "readiness_evaluated_at",
        "readiness_eval_started_at",
        "readiness_eval_finished_at",
        "readiness_eval_duration_ms",
        "readiness_eval_ms",
        "readiness_generated_at",
        "readiness_observed_at",
        # Readiness preview TTL diagnostics (zero frontend references)
        "readiness_preview_cached_at",
        "readiness_preview_fresh_ttl_sec",
        "readiness_preview_refresh_ttl_sec",
        "readiness_preview_stale_after_sec",
        # Market data diagnostics (12+ fields, zero frontend references)
        "market_data_ts",
        "market_data_at",
        "market_data_age_ms",
        "market_data_source",
        "market_data_transport",
        "market_data_ts_source",
        "market_data_price",
        "market_data_refreshed_just_in_time",
        "market_data_refresh_reason",
        "market_data_refresh_delta_ms",
        "market_to_readiness_eval_start_ms",
        "market_to_readiness_eval_finished_ms",
        # Ticker/market provider diagnostics (zero frontend references)
        "bot_current_price_at",
        "bot_current_price_source",
        "market_provider_at",
        "market_provider_source",
        "market_provider_transport",
        "market_provider_age_ms",
        "ticker_provider_updated_at",
        "ticker_provider_age_ms",
        "ticker_used_at_eval",
        "fresher_ticker_available",
        # Price persist diagnostics (zero frontend references)
        "price_metadata_written_early",
        "price_metadata_write_reason",
        "price_metadata_write_path",
        "current_price_persist_delta_ms",
        "current_price_persisted_before_guard",
        "provider_update_seen_at",
        "provider_update_to_eval_ms",
        "reevaluation_trigger_reason",
        "reevaluation_trigger_path",
        "blocked_guarded_fast_path_used",
        "evaluation_deferred_reason",
        "fresh_provider_seen_before_eval",
        # AI advisor detail fields (16 fields, zero critical-path references)
        "ai_advisor_enabled",
        "ai_advisor_last_status",
        "ai_advisor_last_verdict",
        "ai_advisor_last_confidence",
        "ai_advisor_last_reasons",
        "ai_advisor_last_risk_note",
        "ai_advisor_last_summary",
        "ai_advisor_last_model",
        "ai_advisor_last_provider",
        "ai_advisor_last_base_url",
        "ai_advisor_last_escalated",
        "ai_advisor_last_error",
        "ai_advisor_last_latency_ms",
        "ai_advisor_last_decision_at",
        "ai_advisor_last_decision_type",
        "ai_advisor_call_count",
        "ai_advisor_error_count",
        "ai_advisor_timeout_count",
        "ai_advisor_cached_hits",
        "ai_advisor_total_tokens",
        # Raw readiness detail (frontend uses stable_readiness_* instead)
        "raw_readiness_stage",
        "raw_readiness_reason",
        "raw_readiness_reason_text",
        "raw_readiness_detail",
        # Stable readiness detail / stability internals
        "stable_readiness_detail",
        "stable_readiness_next",
        "stable_readiness_updated_at",
        "readiness_stability_state",
        "readiness_stability_policy",
        "readiness_stable_since",
        "readiness_hold_until",
        "readiness_flip_suppressed",
        # Analysis ready fallback detail
        "analysis_ready_fallback_used",
        "analysis_ready_fallback_reason",
        "analysis_ready_fallback_source",
        "analysis_ready_severity",
        "analysis_ready_next",
        # Setup ready fallback detail
        "setup_ready_fallback_used",
        "setup_ready_fallback_reason",
        "setup_ready_fallback_source",
        "setup_ready_severity",
        "setup_ready_next",
        # Alternative mode deep detail (frontend cards only use summary flags)
        "alternative_mode_reason",
        "alternative_mode_reason_text",
        "alternative_mode_detail",
        "alternative_mode_readiness_source_kind",
        "alternative_mode_preview_state",
        "alternative_mode_execution_blocked",
        "alternative_mode_execution_viability_status",
        "alternative_mode_execution_reason",
        "alternative_mode_execution_reason_text",
        "alternative_mode_execution_detail",
        "alternative_mode_setup_ready_fallback_used",
        # Individual signal breakdown (modal-only deep diagnostics)
        "rsi_signal",
        "rsi_score",
        "adx_signal",
        "adx_score",
        "macd_signal",
        "macd_score",
        "ema_signal",
        "ema_score",
        "volume_profile_signal",
        "volume_profile_score",
        "oi_signal",
        "oi_score",
        "orderbook_signal",
        "orderbook_score",
        "orderbook_imbalance",
        "liquidation_signal",
        "liquidation_score",
        "session_signal",
        "session_name",
        "session_modifier",
        "is_weekend",
        "mean_reversion_signal",
        "mean_reversion_score",
        "mean_reversion_deviation",
        # UPnL stoploss detail (beyond the basics used in badges/alerts)
        "upnl_stoploss_cooldown_until",
        "upnl_stoploss_last_trigger",
        "upnl_pct",
        "effective_upnl_soft",
        "effective_upnl_hard",
        "effective_upnl_liq_pct",
        "effective_upnl_k1",
        "effective_cooldown",
        # Profit protection detail (modal-only)
        "profit_protection_mode",
        "profit_protection_advisory",
        "profit_protection_shadow",
        "profit_protection_decision",
        "profit_protection_reason_family",
        "profit_protection_wait_justified",
        "profit_protection_actionable",
        "profit_protection_armed",
        "profit_protection_blocked",
        "profit_protection_blocked_reason",
        "profit_protection_blocked_detail",
        "profit_protection_current_profit_pct",
        "profit_protection_peak_profit_pct",
        "profit_protection_giveback_pct",
        "profit_protection_giveback_threshold_pct",
        "profit_protection_shadow_status",
        "profit_protection_last_action",
        "profit_protection_last_action_at",
        # Auto margin detail
        "auto_margin_remaining_cap",
        "auto_margin_total_added",
        "auto_margin_last_reason",
        "auto_margin_last_pct_to_liq",
        # Scalp live targets (runtime diagnostic)
        "_scalp_adapted_target",
        "_scalp_adapted_quick",
        "scalp_live_target",
        "scalp_live_quick_profit",
        "scalp_live_min_profit",
        "scalp_live_position_notional",
        # Partial TP detail
        "partial_tp_state",
        "last_partial_tp_level",
        "last_partial_tp_profit_pct",
        # Execution counters
        "partial_tp_executed_count",
        "partial_tp_skipped_small_qty_count",
        "profit_lock_executed_count",
        "profit_lock_skipped_fee_guard_count",
        # Exchange reconciliation deep detail
        "exchange_reconciliation_mismatches",
        "exchange_reconciliation_reason",
        "exchange_reconciliation_source",
        "exchange_reconciliation_updated_at",
        # Ambiguous execution follow-up deep detail
        "ambiguous_execution_follow_up_action",
        "ambiguous_execution_follow_up_reason",
        "ambiguous_execution_follow_up_updated_at",
        "ambiguous_execution_follow_up_truth_check_expired",
        # Directional reanchor detail
        "directional_reanchor_requested_at",
        "directional_reanchor_last_expired_at",
        "directional_reanchor_last_cancelled_opening_orders",
        # Live gate detail (beyond status/contract_active used in cards)
        "live_gate_reason",
        "live_gate_reason_text",
        "live_gate_detail",
        "live_gate_source",
        "live_gate_bot_enabled",
        "live_gate_global_master_applicable",
        "live_gate_global_master_enabled",
        "live_gate_updated_at",
        # Breakout detail
        "breakout_reference_level",
        "breakout_reference_type",
        "breakout_no_chase_blocked",
        "breakout_no_chase_reason",
        "breakout_invalidation_state",
        "breakout_invalidation_reason",
        # Regime detail
        "regime_primary",
        "regime_secondary",
        "regime_effective",
        "regime_confidence",
        # Neutral grid detail
        "neutral_volatility_gate_enabled",
        "neutral_volatility_gate_threshold_pct",
        "levels_count",
        "mid_index",
        "active_long_slots",
        "active_short_slots",
        # Internal block flags (diagnostic, not rendered directly)
        "_small_capital_block_opening_orders",
        "_session_timer_block_opening_orders",
        "_auto_pilot_loss_budget_block_openings",
        "_stall_overlay_block_opening_orders",
        "_nlp_block_opening_orders",
        "_breakout_invalidation_block_opening_orders",
        # Misc diagnostic
        "current_price_updated_at",
        "current_price_source",
        "current_price_transport",
        "current_price_exchange_at",
        "flow_score",
        "flow_signal",
        "flow_confidence",
        "flow_volume_spike",
        "composite_confidence",
        "composite_signals_aligned",
        "composite_confidence_reasons",
        "sentiment_score",
        "sentiment_signal",
        "oi_conviction",
        "long_short_ratio",
        "liq_distance_pct",
        "effective_levels",
        "per_order_notional",
        "effective_step_pct",
        "effective_range_pct",
        "atr_5m_pct",
        "atr_15m_pct",
        "grid_tick_seconds",
        "risk_tick_seconds",
        "btc_guard_status",
        "skipped_small_qty_count",
        "readiness_source",
        "readiness_stage",
        "readiness_fallback_used",
        "runtime_mode_source",
        "runtime_mode_non_persistent",
        "runtime_mode_updated_at",
        # Entry signal deep detail
        "entry_signal_phase",
        "entry_signal_detail",
        "entry_signal_raw_preferred",
        "entry_signal_effective_preferred",
        "entry_signal_raw_executable",
        "entry_signal_effective_executable",
        # Readiness preview age (used for staleness, but light path
        # still includes readiness_preview_state)
        "readiness_preview_age_sec",
        # Session timer config detail (not runtime state)
        "session_start_at",
        "session_stop_at",
        "session_no_new_entries_before_stop_min",
        "session_end_mode",
        "session_green_grace_min",
        "session_force_close_max_loss_pct",
        "session_cancel_pending_orders_on_end",
        "session_reduce_only_on_end",
        "session_timer_started_at",
        "session_timer_pre_stop_at",
        "session_timer_end_triggered_at",
        "session_timer_grace_started_at",
        "session_timer_grace_expires_at",
        "session_timer_completed_reason",
        "session_timer_reduce_only_active",
        # Watchdog diagnostic
        "watchdog_position_cap_active",
        # Safety toggles (config-only, not runtime display)
        "auto_stop_loss_enabled",
        "auto_take_profit_enabled",
        "trend_protection_enabled",
        "danger_zone_enabled",
        "auto_neutral_mode_enabled",
        # Trailing SL detail
        "trailing",
        # Entry gate config detail
        "entry_gate_enabled",
        "entry_gate_bot_enabled",
        "entry_gate_global_master_applicable",
        "entry_gate_global_master_enabled",
        # Funding detail
        "funding_score",
        "funding_protection_enabled",
        "funding_protection_active",
        "funding_protection_reason",
        # Small capital detail
        "small_capital_mode_active",
        "small_capital_profile",
        # Cap detail
        "runtime_open_order_cap_total",
        "volatility_derisk_open_cap_total",
        "scalp_learned_opening_order_cap",
        "effective_opening_order_cap_reason",
        # Scalp direction detail
        "scalp_signal_direction",
        "last_scalp_trade_time",
        # Direction change guard deep detail (beyond what events/badges use)
        "direction_change_guard_enabled",
        "direction_change_guard_score",
        "direction_change_guard_detail",
        "direction_change_guard_updated_at",
        "direction_change_guard_last_reason",
        "direction_change_guard_last_position_action",
        "direction_change_guard_last_unrealized_pnl",
        # Misc
        "last_fill_event",
        "exchange_position_scope",
    }
)


def extract_light_bot(full_bot: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the light (dashboard-critical) fields from an enriched bot dict.

    Any key NOT in BOT_RUNTIME_HEAVY_ONLY_FIELDS is kept.  This means newly
    added fields default to LIGHT unless explicitly classified as heavy.
    """
    return {
        key: value
        for key, value in full_bot.items()
        if key not in BOT_RUNTIME_HEAVY_ONLY_FIELDS
    }


def is_heavy_only_field(name: str) -> bool:
    """Return True if *name* is classified as heavy-only (not needed on dashboard critical path)."""
    return name in BOT_RUNTIME_HEAVY_ONLY_FIELDS
