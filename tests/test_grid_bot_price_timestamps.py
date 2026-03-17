from datetime import datetime, timezone

from services.grid_bot_service import GridBotService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._normalize_price_timestamp = GridBotService._normalize_price_timestamp
    service._isoformat_ts = GridBotService._isoformat_ts
    service._remember_last_price_snapshot = GridBotService._remember_last_price_snapshot.__get__(
        service,
        GridBotService,
    )
    service._set_bot_current_price = GridBotService._set_bot_current_price.__get__(
        service,
        GridBotService,
    )
    service._persist_early_current_price_runtime = (
        GridBotService._persist_early_current_price_runtime.__get__(
            service,
            GridBotService,
        )
    )
    service._apply_reevaluation_runtime_context = (
        GridBotService._apply_reevaluation_runtime_context.__get__(
            service,
            GridBotService,
        )
    )
    service._clear_bot_current_price_metadata = GridBotService._clear_bot_current_price_metadata
    service._save_runtime_bot = lambda bot: dict(bot)
    service._last_price_metadata_by_symbol = {}
    return service


def test_set_bot_current_price_uses_authoritative_snapshot_timestamp():
    service = _make_service()
    service._remember_last_price_snapshot(
        "BTCUSDT",
        {
            "price": 101.25,
            "received_at": 1_773_388_800.5,
            "exchange_ts": 1_773_388_800.2,
            "source": "stream_ticker",
            "transport": "stream_ticker",
        },
        fallback_source="stream_ticker",
        fallback_transport="stream_ticker",
    )

    bot = {"id": "bot-1", "symbol": "BTCUSDT"}
    service._set_bot_current_price(bot, 101.25, symbol="BTCUSDT")

    assert bot["current_price"] == 101.25
    assert bot["current_price_updated_at"] == "2026-03-13T08:00:00.500000+00:00"
    assert bot["current_price_source"] == "stream_ticker"
    assert bot["current_price_transport"] == "stream_ticker"
    assert bot["current_price_exchange_ts"] == 1_773_388_800.2
    assert bot["current_price_exchange_at"] == "2026-03-13T08:00:00.200000+00:00"


def test_set_bot_current_price_clears_metadata_when_price_is_empty():
    service = _make_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "current_price_updated_at": "2026-03-13T08:00:00+00:00",
        "current_price_source": "stream_ticker",
        "current_price_transport": "stream_ticker",
        "current_price_exchange_ts": 1_773_388_800.0,
        "current_price_exchange_at": "2026-03-13T08:00:00+00:00",
    }

    service._set_bot_current_price(bot, 0.0, symbol="BTCUSDT")

    assert bot["current_price"] == 0.0
    assert bot["current_price_updated_at"] is None
    assert bot["current_price_source"] is None
    assert bot["current_price_transport"] is None
    assert bot["current_price_exchange_ts"] is None
    assert bot["current_price_exchange_at"] is None


def test_persist_early_current_price_runtime_updates_runtime_metadata():
    service = _make_service()
    saved = []
    service._save_runtime_bot = lambda bot: saved.append(dict(bot)) or dict(bot)
    service._remember_last_price_snapshot(
        "BTCUSDT",
        {
            "price": 101.25,
            "received_at": 1_773_388_801.0,
            "exchange_ts": 1_773_388_800.8,
            "source": "orderbook_mid",
            "transport": "stream_orderbook",
        },
        fallback_source="orderbook_mid",
        fallback_transport="stream_orderbook",
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "current_price": 100.0,
        "current_price_updated_at": "2026-03-13T08:00:00+00:00",
        "current_price_source": "stream_ticker",
        "current_price_transport": "stream_ticker",
    }

    persisted = service._persist_early_current_price_runtime(
        bot,
        symbol="BTCUSDT",
        price=101.25,
        write_reason="trusted_price_ready",
        write_path="neutral_pre_guard",
        persisted_before_guard=True,
    )

    assert persisted is True
    assert saved
    assert bot["current_price_updated_at"] == "2026-03-13T08:00:01+00:00"
    assert bot["current_price_source"] == "orderbook_mid"
    assert bot["current_price_transport"] == "stream_orderbook"
    assert bot["current_price_exchange_at"] == "2026-03-13T08:00:00.800000+00:00"
    assert bot["price_metadata_written_early"] is True
    assert bot["price_metadata_write_reason"] == "trusted_price_ready"
    assert bot["price_metadata_write_path"] == "neutral_pre_guard"
    assert bot["current_price_persist_delta_ms"] == 1000.0
    assert bot["current_price_persisted_before_guard"] is True


def test_apply_reevaluation_runtime_context_records_guarded_fast_path_latency():
    service = _make_service()
    bot = {
        "id": "bot-1",
        "_reevaluation_trigger_received_at": 1_773_388_800.0,
        "_reevaluation_trigger_reason": "orderbook",
        "_reevaluation_trigger_path": "stream_guarded_price_lane",
        "_blocked_guarded_fast_path_requested": True,
        "_fresh_provider_seen_before_eval": True,
        "_evaluation_deferred_reason": "bot_cycle_lock_busy",
    }

    applied = service._apply_reevaluation_runtime_context(
        bot,
        now_ts=1_773_388_800.35,
    )

    assert applied is True
    assert bot["provider_update_seen_at"] == "2026-03-13T08:00:00+00:00"
    assert bot["provider_update_to_eval_ms"] == 350.0
    assert bot["reevaluation_trigger_reason"] == "orderbook"
    assert bot["reevaluation_trigger_path"] == "stream_guarded_price_lane"
    assert bot["blocked_guarded_fast_path_used"] is True
    assert bot["evaluation_deferred_reason"] == "bot_cycle_lock_busy"
    assert bot["fresh_provider_seen_before_eval"] is True


def test_run_bot_cycle_impl_persists_price_metadata_before_neutral_cooldown_return():
    service = _make_service()
    saved_runtime = []
    service._save_runtime_bot = lambda bot: saved_runtime.append(dict(bot)) or dict(bot)
    service._try_acquire_bot_run_lock = lambda bot_id: (True, None)
    service._release_bot_run_lock = lambda lock: None
    service._ensure_stream_symbol = lambda symbol: None
    service._normalize_mode_range_state = lambda bot: None
    service._get_position_mode = lambda bot, symbol: "hedge"
    service._get_client_for_bot = lambda bot: service.client
    service._auto_margin_guard = lambda bot, symbol: None
    service._refresh_multi_tf_regime_snapshot = lambda bot, symbol: None
    service._maybe_auto_select_neutral_mode = lambda **kwargs: (kwargs["bot"], False)
    service._get_volatility_derisk_profile = (
        lambda **kwargs: {
            "tier": "normal",
            "step_mult": 1.0,
            "size_mult": 1.0,
            "open_cap_total": 8,
            "block_opening_orders": False,
        }
    )
    service._apply_session_timer_control = lambda *args, **kwargs: None
    service._clear_capital_starved_opening_block = lambda bot: None
    service._ai_block_opening_orders = lambda bot: False
    service._clear_runtime_experiment_state = lambda bot: None
    service._clear_directional_entry_runtime_state = lambda bot: None
    service._clear_directional_audit_runtime_state = lambda bot: None
    service._get_last_price = lambda symbol: 101.25
    service.indicator_service = type(
        "IndicatorService",
        (),
        {"compute_indicators": lambda self, symbol, interval="15", limit=200: {}},
    )()
    service.client = type(
        "Client",
        (),
        {
            "set_leverage": lambda self, symbol, leverage: None,
            "get_positions": lambda self: {"success": True, "data": {"list": []}},
            "get_open_orders": lambda self, symbol: {"success": True, "data": {"list": []}},
        },
    )()
    service.bot_storage = type(
        "BotStorage",
        (),
        {
            "get_bot": lambda self, bot_id: None,
            "save_bot": lambda self, bot: dict(bot),
            "save_runtime_bot": lambda self, bot: saved_runtime.append(dict(bot)) or dict(bot),
        },
    )()
    service._remember_last_price_snapshot(
        "SOLUSDT",
        {
            "price": 101.25,
            "received_at": 1_773_388_801.0,
            "exchange_ts": 1_773_388_800.9,
            "source": "orderbook_mid",
            "transport": "stream_orderbook",
        },
        fallback_source="orderbook_mid",
        fallback_transport="stream_orderbook",
    )

    bot = {
        "id": "bot-1",
        "symbol": "SOLUSDT",
        "mode": "neutral",
        "status": "running",
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "current_price": 100.0,
        "current_price_updated_at": "2026-03-13T08:00:00+00:00",
        "current_price_source": "stream_ticker",
        "current_price_transport": "stream_ticker",
    }

    result = GridBotService._run_bot_cycle_impl(service, bot, fast_refill_tick=False)

    assert result["current_price"] == 101.25
    assert result["current_price_source"] == "orderbook_mid"
    assert result["current_price_transport"] == "stream_orderbook"
    assert result["price_metadata_written_early"] is True
    assert result["price_metadata_write_path"] == "neutral_pre_guard"
    assert result["current_price_persisted_before_guard"] is True
    assert saved_runtime
    assert saved_runtime[-1]["current_price_updated_at"] == "2026-03-13T08:00:01+00:00"


def test_run_bot_cycle_impl_persists_guarded_reevaluation_context_early():
    service = _make_service()
    saved_runtime = []
    service._save_runtime_bot = lambda bot: saved_runtime.append(dict(bot)) or dict(bot)
    service._try_acquire_bot_run_lock = lambda bot_id: (True, None)
    service._release_bot_run_lock = lambda lock: None
    service._ensure_stream_symbol = lambda symbol: None
    service._normalize_mode_range_state = lambda bot: None
    service._get_position_mode = lambda bot, symbol: "hedge"
    service._get_client_for_bot = lambda bot: service.client
    service._auto_margin_guard = lambda bot, symbol: None
    service._refresh_multi_tf_regime_snapshot = lambda bot, symbol: None
    service._maybe_auto_select_neutral_mode = lambda **kwargs: (kwargs["bot"], False)
    service._get_volatility_derisk_profile = (
        lambda **kwargs: {
            "tier": "normal",
            "step_mult": 1.0,
            "size_mult": 1.0,
            "open_cap_total": 8,
            "block_opening_orders": False,
        }
    )
    service._apply_session_timer_control = lambda *args, **kwargs: None
    service._clear_capital_starved_opening_block = lambda bot: None
    service._ai_block_opening_orders = lambda bot: False
    service._get_last_price = lambda symbol: 101.25
    service._clear_runtime_experiment_state = lambda bot: None
    service._clear_directional_entry_runtime_state = lambda bot: None
    service._clear_directional_audit_runtime_state = lambda bot: None
    service.indicator_service = type(
        "IndicatorService",
        (),
        {"compute_indicators": lambda self, symbol, interval="15", limit=200: {}},
    )()
    service.client = type(
        "Client",
        (),
        {
            "set_leverage": lambda self, symbol, leverage: None,
            "get_positions": lambda self: {"success": True, "data": {"list": []}},
            "get_open_orders": lambda self, symbol: {"success": True, "data": {"list": []}},
        },
    )()
    service.bot_storage = type(
        "BotStorage",
        (),
        {
            "get_bot": lambda self, bot_id: None,
            "save_bot": lambda self, bot: dict(bot),
            "save_runtime_bot": lambda self, bot: saved_runtime.append(dict(bot)) or dict(bot),
        },
    )()
    service._remember_last_price_snapshot(
        "BTCUSDT",
        {
            "price": 101.25,
            "received_at": 1_773_388_801.0,
            "exchange_ts": 1_773_388_800.9,
            "source": "orderbook_mid",
            "transport": "stream_orderbook",
        },
        fallback_source="orderbook_mid",
        fallback_transport="stream_orderbook",
    )

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "neutral",
        "status": "running",
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "current_price": 100.0,
        "current_price_updated_at": "2026-03-13T08:00:00+00:00",
        "current_price_source": "stream_ticker",
        "current_price_transport": "stream_ticker",
        "_reevaluation_trigger_received_at": 1_773_388_800.5,
        "_reevaluation_trigger_reason": "orderbook",
        "_reevaluation_trigger_path": "stream_guarded_price_lane",
        "_blocked_guarded_fast_path_requested": True,
        "_fresh_provider_seen_before_eval": True,
        "_evaluation_deferred_reason": "bot_cycle_lock_busy",
    }

    result = GridBotService._run_bot_cycle_impl(service, bot, fast_refill_tick=False)

    assert result["provider_update_to_eval_ms"] is not None
    assert result["reevaluation_trigger_reason"] == "orderbook"
    assert result["reevaluation_trigger_path"] == "stream_guarded_price_lane"
    assert result["blocked_guarded_fast_path_used"] is True
    assert result["evaluation_deferred_reason"] == "bot_cycle_lock_busy"
    assert result["fresh_provider_seen_before_eval"] is True
    assert saved_runtime
    assert saved_runtime[-1]["blocked_guarded_fast_path_used"] is True
