import logging
from unittest.mock import Mock

from services.grid_bot_service import GridBotService


def _make_order_service():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.bot_storage.get_bot.return_value = {"status": "running"}
    service.client = Mock()
    service.client.create_order.return_value = {
        "success": True,
        "retCode": 0,
        "data": {"orderId": "order-1"},
    }
    service._resolve_position_idx = Mock(return_value=1)
    service._normalize_order_qty = Mock(return_value=1.0)
    service._get_instrument_info = Mock(
        return_value={"min_order_qty": 0.001, "qty_step": 0.001}
    )
    service._build_persistent_ownership_snapshot = Mock(return_value={})
    return service


def test_auto_pilot_loss_budget_state_is_healthy_with_room_remaining():
    service = GridBotService.__new__(GridBotService)
    bot = {
        "auto_pilot": True,
        "investment": 100.0,
        "leverage": 3,
        "realized_pnl": -2.0,
    }

    state = GridBotService._compute_auto_pilot_loss_budget_state(
        service,
        bot,
        symbol="BTCUSDT",
        available_equity=1000.0,
        symbol_unrealized_pnl=-1.0,
    )

    assert state["loss_budget_usdt"] == 15.0
    assert state["remaining_usdt"] == 12.0
    assert state["remaining_pct"] == 0.8
    assert state["status"] == "healthy"


def test_auto_pilot_loss_budget_state_respects_manual_realized_baseline_reset():
    service = GridBotService.__new__(GridBotService)
    bot = {
        "auto_pilot": True,
        "investment": 82.61,
        "leverage": 3,
        "realized_pnl": -32.6054,
        "auto_pilot_loss_budget_realized_baseline": -32.6054,
    }

    state = GridBotService._compute_auto_pilot_loss_budget_state(
        service,
        bot,
        symbol=None,
        available_equity=1000.0,
        symbol_unrealized_pnl=0.0,
    )

    assert state["realized_pnl_since_reset"] == 0.0
    assert state["remaining_usdt"] == state["loss_budget_usdt"]
    assert state["remaining_pct"] == 1.0
    assert state["status"] == "healthy"


def test_auto_pilot_pick_refreshes_latest_persisted_bot_snapshot_before_save():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.client = Mock()
    service._get_ranked_auto_pilot_candidates = Mock(
        return_value=[
            {
                "symbol": "BTCUSDT",
                "recommended_mode": "neutral_classic_bybit",
                "recommended_profile": "normal",
                "recommended_range_mode": "fixed",
                "recommended_grid_levels": 8,
                "recommended_leverage": 3,
                "suggested_range": {"lower": 99000.0, "upper": 101000.0},
                "_auto_pilot_score": 80.0,
                "_auto_pilot_rank_reasons": ["entry_zone=80.0"],
            }
        ]
    )
    service._refresh_auto_pilot_loss_budget_state = Mock(
        return_value={
            "status": "healthy",
            "remaining_pct": 1.0,
            "remaining_usdt": 15.0,
            "loss_budget_usdt": 15.0,
        }
    )
    service._check_auto_pilot_low_budget_candidate = Mock(
        return_value={"allowed": True}
    )
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}
    service.bot_storage.get_bot.return_value = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "auto_pilot": True,
        "status": "running",
        "investment": 100.0,
        "leverage": 3,
        "control_version": 93,
        "settings_version": 26,
    }

    updated = GridBotService._auto_pilot_pick_symbol(
        service,
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "auto_pilot": True,
            "status": "running",
            "investment": 100.0,
            "leverage": 3,
            "control_version": 90,
            "settings_version": 25,
        },
    )

    saved = service.bot_storage.save_bot.call_args.args[0]
    assert saved["control_version"] == 93
    assert saved["settings_version"] == 26
    assert updated["symbol"] == "BTCUSDT"
    assert updated["grid_lower_price"] == 99000.0
    assert updated["grid_upper_price"] == 101000.0


def test_auto_pilot_pick_skips_weak_candidate_when_remaining_budget_is_low():
    service = GridBotService.__new__(GridBotService)
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service.client = Mock()
    service.client._get_now_ts.return_value = 1_700_000_000.0

    # Score must be below weak_score (65) + bonus (8) = 73.0 to be blocked
    weak_score = 68.0

    def ranked_side_effect(bot_arg, reason):
        bot_arg["_auto_pilot_candidate_source_hint"] = "live"
        return [
            {
                "symbol": "BTCUSDT",
                "recommended_mode": "long",
                "recommended_profile": "normal",
                "recommended_range_mode": "dynamic",
                "recommended_grid_levels": 8,
                "recommended_leverage": 3,
                "suggested_range": {"lower": 99.0, "upper": 101.0},
                "_auto_pilot_score": weak_score,
                "_auto_pilot_rank_reasons": ["entry_zone=good"],
            }
        ]

    service._get_ranked_auto_pilot_candidates = Mock(side_effect=ranked_side_effect)
    service._refresh_auto_pilot_loss_budget_state = Mock(
        return_value={
            "status": "low",
            "remaining_pct": 0.23,
            "remaining_usdt": 3.5,
            "loss_budget_usdt": 15.0,
        }
    )
    service._get_usdt_available_balance = Mock(return_value=1000.0)
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    bot = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "auto_pilot": True,
        "investment": 100.0,
        "leverage": 3,
        "realized_pnl": -11.5,
    }

    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "Auto-Pilot"
    assert updated["auto_pilot_search_status"] == "ok"
    assert updated["auto_pilot_pick_status"] == "candidate_ready"
    assert updated["auto_pilot_top_candidate_symbol"] == "BTCUSDT"
    assert updated["auto_pilot_top_candidate_score"] == weak_score
    assert updated["auto_pilot_top_candidate_mode"] == "long"
    assert updated["auto_pilot_candidate_source"] == "live"
    assert service.client.set_margin_mode.call_count == 0
    assert service.bot_storage.save_bot.call_count == 1


def test_auto_pilot_pick_blocked_by_loss_budget_exposes_top_candidate_and_throttles_logs(
    caplog,
):
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.client = Mock()
    service.client._get_now_ts.return_value = 1_700_000_000.0

    candidates = [
        {
            "symbol": "SUIUSDT",
            "recommended_mode": "long",
            "recommended_profile": "normal",
            "recommended_range_mode": "dynamic",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 0.9, "upper": 1.1},
            "_auto_pilot_score": 99.4,
            "_auto_pilot_rank_reasons": ["entry_zone=99.4"],
            "_auto_pilot_eligibility_status": "eligible_conservative",
        },
        {
            "symbol": "SUIUSDT",
            "recommended_mode": "long",
            "recommended_profile": "normal",
            "recommended_range_mode": "dynamic",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 0.9, "upper": 1.1},
            "_auto_pilot_score": 99.4,
            "_auto_pilot_rank_reasons": ["entry_zone=99.4"],
            "_auto_pilot_eligibility_status": "eligible_conservative",
        },
        {
            "symbol": "SOLUSDT",
            "recommended_mode": "short",
            "recommended_profile": "normal",
            "recommended_range_mode": "dynamic",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 98.0, "upper": 102.0},
            "_auto_pilot_score": 97.1,
            "_auto_pilot_rank_reasons": ["entry_zone=97.1"],
            "_auto_pilot_eligibility_status": "eligible_conservative",
        },
    ]

    def ranked_side_effect(bot_arg, reason):
        bot_arg["_auto_pilot_candidate_source_hint"] = "cache"
        return [dict(candidates.pop(0))]

    service._get_ranked_auto_pilot_candidates = Mock(side_effect=ranked_side_effect)
    service._refresh_auto_pilot_loss_budget_state = Mock(
        return_value={
            "status": "blocked",
            "remaining_pct": 0.0,
            "remaining_usdt": 0.0,
            "loss_budget_usdt": 13.21,
        }
    )

    bot = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "auto_pilot": True,
        "investment": 100.0,
        "leverage": 3,
    }

    with caplog.at_level(logging.INFO):
        GridBotService._auto_pilot_pick_symbol(service, bot)
        assert bot["symbol"] == "Auto-Pilot"
        assert bot["auto_pilot_search_status"] == "ok"
        assert bot["auto_pilot_pick_status"] == "blocked_loss_budget"
        assert bot["auto_pilot_block_reason"] == "remaining_loss_budget"
        assert bot["auto_pilot_top_candidate_symbol"] == "SUIUSDT"
        assert bot["auto_pilot_top_candidate_score"] == 99.4
        assert bot["auto_pilot_top_candidate_mode"] == "long"
        assert bot["auto_pilot_top_candidate_eligibility"] == "eligible_conservative"
        assert bot["auto_pilot_candidate_source"] == "cache"
        assert "Search ok; top candidate=SUIUSDT" in caplog.text
        assert "Pick blocked by loss budget: remaining 0.00% ($0.00 / $13.21)" in caplog.text
        assert service._refresh_auto_pilot_loss_budget_state.call_args.args[1] is None

        GridBotService._auto_pilot_pick_symbol(service, bot)
        assert caplog.text.count("Search ok; top candidate=SUIUSDT") == 1
        assert caplog.text.count("Pick blocked by loss budget") == 1

        GridBotService._auto_pilot_pick_symbol(service, bot)
        assert bot["auto_pilot_top_candidate_symbol"] == "SOLUSDT"
        assert bot["auto_pilot_top_candidate_mode"] == "short"
        assert caplog.text.count("Pick blocked by loss budget") == 2
        assert "Search ok; top candidate=SOLUSDT" in caplog.text

    service.client.set_margin_mode.assert_not_called()
    assert service.bot_storage.save_bot.call_count == 3


def test_low_remaining_budget_caps_auto_pilot_opening_notional_without_full_block():
    service = _make_order_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "auto_pilot": True,
        "_position_mode": "hedge",
        "auto_pilot_loss_budget_state": "low",
        "auto_pilot_remaining_loss_budget_pct": 0.2,
        "auto_pilot_remaining_loss_budget_usdt": 3.0,
        "auto_pilot_loss_budget_usdt": 15.0,
        "auto_pilot_low_budget_max_opening_notional_usdt": 150.0,
    }

    result = GridBotService._create_order_checked(
        service,
        bot=bot,
        symbol="BTCUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=100.0,
        reduce_only=False,
    )

    assert result["success"] is True
    service.client.create_order.assert_called_once()


def test_very_low_remaining_budget_blocks_new_openings_but_not_reduce_only():
    service = _make_order_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "auto_pilot": True,
        "_position_mode": "hedge",
        "auto_pilot_loss_budget_state": "blocked",
        "auto_pilot_remaining_loss_budget_pct": 0.05,
        "auto_pilot_remaining_loss_budget_usdt": 0.75,
        "auto_pilot_loss_budget_usdt": 15.0,
        "_auto_pilot_loss_budget_block_openings": True,
    }

    opening_result = GridBotService._create_order_checked(
        service,
        bot=bot,
        symbol="BTCUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=100.0,
        reduce_only=False,
    )

    reduce_only_result = GridBotService._create_order_checked(
        service,
        bot=bot,
        symbol="BTCUSDT",
        side="Sell",
        qty=1.0,
        order_type="Market",
        price=None,
        reduce_only=True,
    )

    assert opening_result["skip_reason"] == "auto_pilot_loss_budget_blocked"
    assert reduce_only_result["success"] is True
    assert service.client.create_order.call_count == 1


def test_non_auto_pilot_openings_ignore_loss_budget_guard_fields():
    service = _make_order_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "auto_pilot": False,
        "_position_mode": "hedge",
        "auto_pilot_loss_budget_state": "blocked",
        "_auto_pilot_loss_budget_block_openings": True,
    }

    result = GridBotService._create_order_checked(
        service,
        bot=bot,
        symbol="BTCUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=100.0,
        reduce_only=False,
    )

    assert result["success"] is True
    service.client.create_order.assert_called_once()


def test_incident_style_large_prior_loss_caps_new_auto_pilot_opening():
    service = _make_order_service()
    bot = {
        "id": "bot-1",
        "symbol": "KITEUSDT",
        "auto_pilot": True,
        "_position_mode": "hedge",
        "investment": 100.0,
        "leverage": 3,
        "realized_pnl": -11.0,
    }

    state = GridBotService._compute_auto_pilot_loss_budget_state(
        service,
        bot,
        symbol="KITEUSDT",
        available_equity=1000.0,
        symbol_unrealized_pnl=-1.0,
    )
    GridBotService._apply_auto_pilot_loss_budget_runtime_state(service, bot, state)

    result = GridBotService._create_order_checked(
        service,
        bot=bot,
        symbol="KITEUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=100.0,
        reduce_only=False,
    )

    assert state["status"] == "low"
    assert result["skip_reason"] == "auto_pilot_low_budget_notional_cap"
    service.client.create_order.assert_not_called()
