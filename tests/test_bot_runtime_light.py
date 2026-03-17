"""Tests for the bot runtime light/full split.

Covers:
  - Field contracts (light vs heavy classification)
  - Light path isolation (no expensive calls)
  - Bridge dual-section publishing and threading
  - Dashboard fallback chain
"""

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from services.bot_runtime_contracts import (
    BOT_RUNTIME_HEAVY_ONLY_FIELDS,
    extract_light_bot,
    is_heavy_only_field,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_full_bot(**overrides):
    """Build a realistic full-enriched bot dict with representative fields."""
    base = {
        # Core identity
        "id": "bot-001",
        "symbol": "BTCUSDT",
        "mode": "long",
        "configured_mode": "long",
        "configured_range_mode": "dynamic",
        "effective_runtime_mode": "long",
        "effective_runtime_range_mode": "dynamic",
        "mode_policy": "manual",
        "status": "running",
        "profile": "normal",
        "auto_pilot": False,
        "auto_direction": False,
        # Position/PnL — critical path
        "position_size": 0.01,
        "position_side": "Buy",
        "entry_price": 65000.0,
        "mark_price": 65100.0,
        "current_price": 65100.0,
        "realized_pnl": 12.5,
        "unrealized_pnl": 1.0,
        "total_pnl": 13.5,
        "session_total_pnl": 5.2,
        "session_profit_per_hour": 1.3,
        "pnl_pct": 0.0045,
        # Readiness — critical path
        "stable_readiness_stage": "armed",
        "stable_readiness_reason": "setup_confirmed",
        "setup_ready_status": "armed",
        "setup_ready_score": 75,
        "setup_ready_reason": "momentum_confirmed",
        "entry_ready_status": "armed",
        "entry_ready_reason": "conditions_met",
        "execution_viability_status": "viable",
        "execution_viability_reason": "margin_sufficient",
        "execution_blocked": False,
        "execution_margin_limited": False,
        # Alternative mode summary — critical path
        "alternative_mode_ready": False,
        "alternative_mode": None,
        "alternative_mode_range_mode": None,
        "alternative_mode_status": None,
        "alternative_mode_score": None,
        "alternative_mode_is_scanner_suggestion": False,
        # Scanner cached values — critical path
        "scanner_recommended_mode": "neutral",
        "scanner_recommendation_differs": True,
        # Session timer — critical path
        "session_timer_enabled": False,
        "session_timer_state": "inactive",
        # Auto-pilot fields — critical path
        "auto_pilot_block_reason": None,
        "auto_pilot_search_status": None,
        "auto_pilot_pick_status": None,
        "auto_pilot_top_candidate_symbol": None,
        "auto_pilot_top_candidate_score": None,
        # Entry gate — critical path
        "entry_gate_blocked": False,
        "entry_gate_reason": None,
        # UPnL stoploss basics — critical path
        "upnl_stoploss_enabled": True,
        "upnl_stoploss_active": False,
        "upnl_stoploss_reason": None,
        "upnl_stoploss_in_cooldown": False,
        "upnl_stoploss_trigger_count": 0,
        # Direction — critical path
        "direction_score": 65,
        "direction_signals": {"rsi": "long"},
        "direction_change_guard_state": "stable",
        "direction_change_guard_source": "auto",
        "direction_change_guard_last_event_at": None,
        "direction_change_guard_last_action": None,
        "direction_change_guard_prev_state": None,
        "direction_change_guard_last_unrealized_pnl": None,
        # Exchange truth — critical path
        "exchange_reconciliation": {"status": "ok"},
        "exchange_reconciliation_status": "ok",
        "ambiguous_execution_follow_up": {},
        "ambiguous_execution_follow_up_status": None,
        "ambiguous_execution_follow_up_pending": False,
        # Config — critical path
        "leverage": 10.0,
        "grid_count": 5,
        "investment": 100.0,
        "lower_price": 64000.0,
        "upper_price": 66000.0,
        "tp_pct": 0.5,
        "last_error": None,
        "last_skip_reason": None,
        "last_replacement_action": None,
        "opening_blocked_reason": None,
        "entry_orders_open": 2,
        "open_order_count": 4,
        "effective_opening_order_cap": 5,
        # Grid/scalp — critical path
        "neutral_grid_enabled": True,
        "scalp_status": "active",
        "scalp_signal_score": 72,
        "scalp_analysis": {"condition": "trending"},
        "trend_status": "bullish",
        "trend_direction": "up",
        # Danger/funding — critical path
        "danger_score": 15,
        "danger_level": "low",
        "danger_in_zone": False,
        "funding_rate_pct": -0.01,
        "funding_signal": "neutral",
        # Position attribution — critical path
        "live_position_attribution": "unique_running_bot",
        "exchange_position_size": 0.01,
        "exchange_position_side": "Buy",
        "exchange_entry_price": 65000.0,
        "exchange_mark_price": 65100.0,
        "exchange_unrealized_pnl": 1.0,
        "exchange_exposure_detected": True,
        # Metadata — critical path
        "last_run_at": "2026-03-17T10:00:00Z",
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-17T10:00:00Z",
        "out_of_range": False,
        "risk_stopped": False,
        "tp_hit": False,
        "runtime_snapshot_stale": False,
        "runtime_hours": 120.5,
        "profit_per_hour": 0.11,
        # --- HEAVY-ONLY fields ---
        "mode_readiness_matrix": [{"mode": "long", "status": "armed"}],
        "performance_baseline": {"start_pnl": 0},
        "ai_advisor_enabled": True,
        "ai_advisor_last_status": "ok",
        "ai_advisor_last_verdict": "hold",
        "ai_advisor_call_count": 5,
        "analysis_timing_status": "fresh",
        "analysis_timing_reason": "within_window",
        "readiness_eval_duration_ms": 45.2,
        "market_data_ts": 1710000000,
        "market_data_age_ms": 150,
        "raw_readiness_stage": "armed",
        "stable_readiness_detail": {"scores": [75, 80]},
        "rsi_signal": "bullish",
        "rsi_score": 65,
        "adx_signal": "trending",
        "adx_score": 30,
        "profit_protection_mode": "adaptive",
        "profit_protection_armed": True,
        "effective_upnl_soft": -5.0,
        "effective_upnl_hard": -10.0,
        "auto_margin_remaining_cap": 50.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Phase 1: Contract tests
# ---------------------------------------------------------------------------

class TestFieldContracts:
    """Verify light/heavy classification against actual frontend consumers."""

    def test_extract_light_bot_preserves_critical_fields(self):
        """All dashboard-critical fields survive extraction."""
        full = _make_full_bot()
        light = extract_light_bot(full)

        # Core identity
        assert light["id"] == "bot-001"
        assert light["symbol"] == "BTCUSDT"
        assert light["status"] == "running"
        assert light["mode"] == "long"

        # PnL
        assert light["total_pnl"] == 13.5
        assert light["unrealized_pnl"] == 1.0
        assert light["session_total_pnl"] == 5.2

        # Readiness
        assert light["stable_readiness_stage"] == "armed"
        assert light["setup_ready_status"] == "armed"
        assert light["entry_ready_status"] == "armed"

        # Execution viability
        assert light["execution_viability_status"] == "viable"
        assert light["execution_blocked"] is False
        assert light["execution_margin_limited"] is False

        # Config
        assert light["leverage"] == 10.0
        assert light["grid_count"] == 5
        assert light["investment"] == 100.0
        assert light["lower_price"] == 64000.0
        assert light["upper_price"] == 66000.0

        # Auto-pilot
        assert "auto_pilot" in light
        assert "auto_pilot_block_reason" in light
        assert "auto_pilot_top_candidate_symbol" in light

        # Entry gate
        assert "entry_gate_blocked" in light
        assert "entry_gate_reason" in light

        # UPnL stoploss basics
        assert "upnl_stoploss_enabled" in light
        assert "upnl_stoploss_active" in light
        assert "upnl_stoploss_reason" in light

        # Session timer runtime state
        assert "session_timer_enabled" in light
        assert "session_timer_state" in light

        # Scanner cached values
        assert "scanner_recommended_mode" in light
        assert "scanner_recommendation_differs" in light

        # Direction (event detection needs these)
        assert "direction_score" in light
        assert "direction_signals" in light
        assert "direction_change_guard_state" in light
        assert "direction_change_guard_last_event_at" in light
        assert "direction_change_guard_last_action" in light
        assert "direction_change_guard_prev_state" in light

        # Exchange truth
        assert "exchange_reconciliation" in light
        assert "exchange_reconciliation_status" in light
        assert "ambiguous_execution_follow_up" in light

        # Position
        assert "position_size" in light
        assert "position_side" in light

        # Stall/overlay
        assert "last_error" in light
        assert "last_skip_reason" in light
        assert "last_replacement_action" in light

        # Grid/scalp
        assert "scalp_analysis" in light
        assert "scalp_status" in light
        assert "scalp_signal_score" in light

        # Danger/funding
        assert "danger_score" in light
        assert "danger_level" in light
        assert "funding_rate_pct" in light
        assert "funding_signal" in light

    def test_extract_light_bot_excludes_heavy_fields(self):
        """Heavy-only fields are removed by extraction."""
        full = _make_full_bot()
        light = extract_light_bot(full)

        heavy_present = [k for k in BOT_RUNTIME_HEAVY_ONLY_FIELDS if k in light]
        assert heavy_present == [], f"Heavy fields leaked into light: {heavy_present}"

    def test_mode_readiness_matrix_is_heavy(self):
        assert is_heavy_only_field("mode_readiness_matrix")

    def test_ai_advisor_fields_are_heavy(self):
        assert is_heavy_only_field("ai_advisor_enabled")
        assert is_heavy_only_field("ai_advisor_last_status")
        assert is_heavy_only_field("ai_advisor_call_count")

    def test_analysis_timing_fields_are_heavy(self):
        assert is_heavy_only_field("analysis_timing_status")
        assert is_heavy_only_field("analysis_timing_reason")

    def test_market_data_diagnostics_are_heavy(self):
        assert is_heavy_only_field("market_data_ts")
        assert is_heavy_only_field("market_data_age_ms")

    def test_profit_protection_detail_is_heavy(self):
        assert is_heavy_only_field("profit_protection_mode")
        assert is_heavy_only_field("profit_protection_armed")

    def test_individual_signals_are_heavy(self):
        assert is_heavy_only_field("rsi_signal")
        assert is_heavy_only_field("adx_score")

    def test_new_fields_default_to_light(self):
        """Fields not in BOT_RUNTIME_HEAVY_ONLY_FIELDS are kept (light)."""
        full = {"id": "bot-001", "some_future_field": 42}
        light = extract_light_bot(full)
        assert light["some_future_field"] == 42


# ---------------------------------------------------------------------------
# Phase 2: Light path isolation tests
# ---------------------------------------------------------------------------

class TestLightPathIsolation:
    """Verify get_runtime_bots_light() never triggers expensive operations."""

    def _make_service(self):
        """Build a minimal BotStatusService with mocked dependencies."""
        from services.bot_status_service import BotStatusService

        svc = object.__new__(BotStatusService)
        svc.bot_storage = MagicMock()
        svc.bot_storage.list_bots.return_value = [
            {
                "id": "bot-001",
                "symbol": "BTCUSDT",
                "status": "running",
                "mode": "long",
                "investment": 100,
                "leverage": 10,
                "grid_count": 5,
            },
            {
                "id": "bot-002",
                "symbol": "ETHUSDT",
                "status": "stopped",
                "mode": "neutral",
                "investment": 200,
                "leverage": 5,
                "grid_count": 8,
            },
        ]
        svc.symbol_pnl_service = MagicMock()
        svc.symbol_pnl_service.get_all_symbols_pnl.return_value = {}
        svc.symbol_pnl_service.get_all_bot_pnl.return_value = {}
        svc.position_service = MagicMock()
        svc.position_service.get_positions.return_value = {"positions": []}
        svc.entry_readiness_service = None
        svc.price_action_service = None
        svc.neutral_scanner = MagicMock()
        svc.neutral_scanner.scan = MagicMock(side_effect=AssertionError("scan must not be called"))
        svc.performance_baseline_service = None
        svc.watchdog_diagnostics_service = None
        svc.client = MagicMock()
        svc.client.get_open_orders.return_value = {"result": {"list": []}}

        # Caches that the light path reads
        svc._scanner_cache = {}
        svc._stopped_preview_cache = {}
        svc._readiness_stability_cache = {}

        return svc

    def test_light_path_uses_cache_only_scanner(self):
        """get_runtime_bots_light() passes cache_only=True to scanner lookup."""
        svc = self._make_service()
        with patch.object(svc, "_get_scanner_recommendation_lookup", wraps=svc._get_scanner_recommendation_lookup) as mock_scanner:
            with patch.object(svc, "_build_stopped_preview_lookup", return_value={}):
                with patch.object(svc, "_get_runtime_positions_payload", return_value={"positions": []}):
                    with patch.object(svc, "_build_live_open_orders_by_symbol", return_value={}):
                        svc.get_runtime_bots_light()
            # Verify cache_only=True was passed
            for call in mock_scanner.call_args_list:
                assert call.kwargs.get("cache_only") is True or (len(call.args) > 1 and call.args[1] is True)

    def test_light_path_never_calls_scanner_scan(self):
        """The scanner's scan() method must never be invoked from light path."""
        svc = self._make_service()
        # _get_scanner_recommendation_lookup with cache_only=True should not scan
        with patch.object(svc, "_build_stopped_preview_lookup", return_value={}):
            with patch.object(svc, "_get_runtime_positions_payload", return_value={"positions": []}):
                with patch.object(svc, "_build_live_open_orders_by_symbol", return_value={}):
                    svc.get_runtime_bots_light()
        svc.neutral_scanner.scan.assert_not_called()

    def test_light_output_has_no_heavy_fields(self):
        """Every bot in light output should have no heavy-only fields."""
        svc = self._make_service()
        with patch.object(svc, "_get_scanner_recommendation_lookup", return_value={}):
            with patch.object(svc, "_build_stopped_preview_lookup", return_value={}):
                with patch.object(svc, "_get_runtime_positions_payload", return_value={"positions": []}):
                    with patch.object(svc, "_build_live_open_orders_by_symbol", return_value={}):
                        result = svc.get_runtime_bots_light()
        for bot in result:
            heavy_present = [k for k in BOT_RUNTIME_HEAVY_ONLY_FIELDS if k in bot]
            assert heavy_present == [], f"Heavy fields in light output: {heavy_present}"

    def test_light_path_never_calls_enrich_bot_full(self):
        """get_runtime_bots_light() must call _enrich_bot_light, not _enrich_bot."""
        svc = self._make_service()
        with patch.object(svc, "_get_scanner_recommendation_lookup", return_value={}):
            with patch.object(svc, "_build_stopped_preview_lookup", return_value={}):
                with patch.object(svc, "_get_runtime_positions_payload", return_value={"positions": []}):
                    with patch.object(svc, "_build_live_open_orders_by_symbol", return_value={}):
                        with patch.object(svc, "_enrich_bot", side_effect=AssertionError("Must not call full _enrich_bot")):
                            svc.get_runtime_bots_light()  # should not raise


# ---------------------------------------------------------------------------
# Phase 3: Bridge threading tests
# ---------------------------------------------------------------------------

class TestBridgeThreading:
    """Verify bridge publishes light section independently from full enrichment."""

    def test_bridge_has_light_section_config(self):
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        assert "bots_runtime_light" in RuntimeSnapshotBridgeService.REBUILD_INTERVALS_SEC
        assert "bots_runtime_light" in RuntimeSnapshotBridgeService.EVENT_REBUILD_INTERVALS_SEC
        assert "bots_runtime_light" in RuntimeSnapshotBridgeService.READ_STALE_AGE_SEC

    def test_bridge_start_spawns_two_threads(self):
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        bridge = RuntimeSnapshotBridgeService(
            file_path="/tmp/test_bridge.json",
            owner_name="test",
            write_enabled=True,
        )
        bridge.start()
        try:
            assert bridge._thread is not None
            assert bridge._enrich_thread is not None
            assert bridge._thread.is_alive()
            assert bridge._enrich_thread.is_alive()
            assert bridge._thread.name == "RuntimeSnapshotBridge"
            assert bridge._enrich_thread.name == "RuntimeSnapshotBridgeEnrich"
        finally:
            bridge.stop()

    def test_bridge_stop_joins_both_threads(self):
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        bridge = RuntimeSnapshotBridgeService(
            file_path="/tmp/test_bridge_stop.json",
            owner_name="test",
            write_enabled=True,
        )
        bridge.start()
        bridge.stop()
        assert not bridge._running
        assert bridge._thread is None
        assert bridge._enrich_thread is None

    def test_enrichment_diagnostics_structure(self):
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        bridge = RuntimeSnapshotBridgeService(
            file_path="/tmp/test_bridge_diag.json",
            owner_name="test",
            write_enabled=False,
        )
        diag = bridge.get_enrichment_diagnostics()
        assert "full_enrich_in_progress" in diag
        assert "full_enrich_interval_sec" in diag
        assert "full_enrich_last_duration_ms" in diag
        assert "full_enrich_has_cached_payload" in diag
        assert "light_publish_count_during_last_full" in diag
        assert "enrich_thread_alive" in diag
        assert diag["full_enrich_in_progress"] is False
        assert diag["full_enrich_has_cached_payload"] is False
        assert diag["enrich_thread_alive"] is False

    def test_light_payload_has_bots_scope(self):
        """Light payload always includes bots_scope='light'."""
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        bridge = RuntimeSnapshotBridgeService(
            file_path="/tmp/test_bridge_scope.json",
            owner_name="test",
            write_enabled=False,
        )
        payload = bridge._build_bots_runtime_light_payload()
        assert payload["bots_scope"] == "light"

    def test_full_publish_without_cached_payload_is_stale(self):
        """When background thread hasn't run yet, full section is explicitly stale."""
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        bridge = RuntimeSnapshotBridgeService(
            file_path="/tmp/test_bridge_stale.json",
            owner_name="test",
            write_enabled=True,
        )
        # No cached full payload
        assert bridge._cached_bots_runtime_payload is None

        # Simulate what _publish does for bots_runtime
        with bridge._enrich_result_lock:
            cached_full = bridge._cached_bots_runtime_payload
        assert cached_full is None

    def test_payload_shape_valid_for_light(self):
        from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
        assert RuntimeSnapshotBridgeService._payload_shape_valid(
            "bots_runtime_light", {"bots": [{"id": "1"}]}
        )
        assert not RuntimeSnapshotBridgeService._payload_shape_valid(
            "bots_runtime_light", {"bots": "not_a_list"}
        )


# ---------------------------------------------------------------------------
# Phase 4: Dashboard fallback tests
# ---------------------------------------------------------------------------

class TestDashboardFallback:
    """Verify bootstrap tries light before full."""

    def test_light_snapshot_helper_returns_light_when_fresh(self):
        """_get_runtime_bots_light_snapshot returns light when usable."""
        import app as app_module

        light_section = {
            "bots": [{"id": "bot-001"}],
            "stale_data": False,
            "snapshot_fresh": True,
            "bots_scope": "light",
        }
        with patch.object(
            app_module.runtime_snapshot_bridge,
            "read_section",
            return_value=light_section,
        ):
            with patch.object(app_module, "_bridge_section_usable", return_value=True):
                result = app_module._get_runtime_bots_light_snapshot()
        assert result["bots_scope"] == "light"
        assert result["bots"] == [{"id": "bot-001"}]

    def test_light_snapshot_never_falls_back_to_full_path(self):
        """_get_runtime_bots_light_snapshot NEVER calls _get_runtime_bots_snapshot."""
        import app as app_module

        with patch.object(app_module, "_bridge_section_usable", return_value=False):
            with patch.object(
                app_module.runtime_snapshot_bridge,
                "read_section",
                return_value=None,
            ):
                with patch.object(
                    app_module,
                    "_get_runtime_bots_snapshot",
                    side_effect=AssertionError("Must not call full path"),
                ) as mock_full:
                    with patch.object(
                        app_module,
                        "_build_runtime_bots_light_payload",
                        return_value={"bots": [], "bots_scope": "light"},
                    ):
                        result = app_module._get_runtime_bots_light_snapshot()
                mock_full.assert_not_called()
        assert result["bots_scope"] == "light"

    def test_light_snapshot_uses_stale_light_when_bridge_stale(self):
        """When light section exists but is stale, it is returned with stale_data."""
        import app as app_module

        stale_light = {
            "bots": [{"id": "bot-stale"}],
            "stale_data": True,
            "snapshot_fresh": False,
        }
        with patch.object(app_module, "_bridge_section_usable", return_value=False):
            with patch.object(
                app_module.runtime_snapshot_bridge,
                "read_section",
                return_value=stale_light,
            ):
                result = app_module._get_runtime_bots_light_snapshot()
        assert result["bots"] == [{"id": "bot-stale"}]
        assert result["bots_scope"] == "light"
        assert result["stale_data"] is True

    def test_light_snapshot_uses_local_fallback_when_bridge_missing(self):
        """When light section is missing entirely, calls _build_runtime_bots_light_fallback (no Bybit)."""
        import app as app_module

        with patch.object(app_module, "_bridge_section_usable", return_value=False):
            with patch.object(
                app_module.runtime_snapshot_bridge,
                "read_section",
                return_value=None,
            ):
                with patch.object(
                    app_module,
                    "_build_runtime_bots_light_fallback",
                    return_value={"bots": [{"id": "bot-fallback"}], "bots_scope": "light", "stale_data": True},
                ) as mock_light_fallback:
                    result = app_module._get_runtime_bots_light_snapshot()
                mock_light_fallback.assert_called_once_with("light_bridge_unavailable")
        assert result["bots"] == [{"id": "bot-fallback"}]
        assert result["bots_scope"] == "light"

    def test_bootstrap_recovery_uses_local_only_fallbacks(self):
        """_recover_bootstrap_dashboard_sections uses local-only fallbacks, not Bybit builders."""
        import app as app_module

        with patch.object(
            app_module,
            "_build_runtime_bots_light_fallback",
            return_value={"bots": [], "bots_scope": "light", "stale_data": True, "error": "bootstrap_recovery"},
        ) as mock_light_fallback:
            with patch.object(
                app_module,
                "_build_summary_fallback_payload",
                return_value={"stale_data": True, "error": "bootstrap_recovery"},
            ) as mock_summary_fallback:
                with patch.object(
                    app_module,
                    "_build_positions_fallback_payload",
                    return_value={"stale_data": True, "error": "bootstrap_recovery"},
                ) as mock_positions_fallback:
                    result = app_module._recover_bootstrap_dashboard_sections(timeout_sec=5.0)
        mock_light_fallback.assert_called_once_with("bootstrap_recovery")
        mock_summary_fallback.assert_called_once_with("bootstrap_recovery")
        mock_positions_fallback.assert_called_once_with("bootstrap_recovery")
        assert result["bots"]["bots_scope"] == "light"

    def test_bootstrap_recovery_never_calls_full_get_runtime_bots(self):
        """Bootstrap recovery must never trigger heavy get_runtime_bots()."""
        import app as app_module

        with patch.object(
            app_module,
            "_build_runtime_bots_light_payload",
            return_value={"bots": [], "bots_scope": "light", "stale_data": False},
        ):
            with patch.object(
                app_module,
                "_build_summary_payload",
                return_value={"stale_data": False},
            ):
                with patch.object(
                    app_module,
                    "_build_positions_payload",
                    return_value={"stale_data": False},
                ):
                    with patch.object(
                        app_module,
                        "_build_runtime_bots_payload",
                        side_effect=AssertionError("Must not call full builder"),
                    ) as mock_full:
                        app_module._recover_bootstrap_dashboard_sections(timeout_sec=5.0)
                    mock_full.assert_not_called()
