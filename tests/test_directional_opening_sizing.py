from unittest.mock import Mock

from services.bybit_client import BybitClient
from services.grid_bot_service import GridBotService
from services.trade_forensics_service import TradeForensicsService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._round_to_step = GridBotService._round_to_step.__get__(
        service, GridBotService
    )
    service._get_opening_size_limit_reason = (
        GridBotService._get_opening_size_limit_reason.__get__(
            service, GridBotService
        )
    )
    service._cap_directional_opening_qty_to_affordability = (
        GridBotService._cap_directional_opening_qty_to_affordability.__get__(
            service, GridBotService
        )
    )
    service._get_opening_margin_guard_reason = (
        GridBotService._get_opening_margin_guard_reason.__get__(
            service, GridBotService
        )
    )
    service._compact_directional_opening_sizing_fields = (
        GridBotService._compact_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._build_directional_opening_sizing_fields = (
        GridBotService._build_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._augment_directional_opening_sizing_fields = (
        GridBotService._augment_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._build_order_link_id = GridBotService._build_order_link_id.__get__(
        service, GridBotService
    )
    return service


def test_directional_opening_qty_cap_reduces_first_slice_when_margin_is_tight():
    service = _make_service()

    result = service._cap_directional_opening_qty_to_affordability(
        mode="long",
        planned_qty=0.9,
        price=89.32,
        leverage=5.0,
        qty_step=0.1,
        min_qty=0.1,
        min_notional_value=5.0,
        available_balance=13.4662,
        reserve_usd=7.5565,
    )

    assert result["adjusted"] is True
    assert result["blocked_reason"] is None
    assert result["qty"] == 0.3
    assert round(result["candidate_notional"], 3) == 26.796


def test_directional_opening_qty_cap_reports_reserve_limited_when_only_reserve_blocks_min_order():
    service = _make_service()

    result = service._cap_directional_opening_qty_to_affordability(
        mode="long",
        planned_qty=0.4,
        price=100.0,
        leverage=5.0,
        qty_step=0.1,
        min_qty=0.1,
        min_notional_value=5.0,
        available_balance=2.0,
        reserve_usd=1.2,
    )

    assert result["adjusted"] is False
    assert result["candidate_qty"] == 0.1
    assert result["blocked_reason"] == "opening_margin_reserve"


def test_directional_opening_qty_cap_reports_structural_min_size_when_even_raw_balance_cannot_support_floor():
    service = _make_service()

    result = service._cap_directional_opening_qty_to_affordability(
        mode="short",
        planned_qty=1.0,
        price=100.0,
        leverage=5.0,
        qty_step=0.1,
        min_qty=0.1,
        min_notional_value=5.0,
        available_balance=0.6,
        reserve_usd=0.0,
    )

    assert result["adjusted"] is False
    assert result["blocked_reason"] == "qty_below_min"


def test_directional_opening_sizing_fields_capture_planned_capped_and_submitted_values():
    service = _make_service()

    adjustment = service._cap_directional_opening_qty_to_affordability(
        mode="long",
        planned_qty=0.9,
        price=89.32,
        leverage=5.0,
        qty_step=0.1,
        min_qty=0.1,
        min_notional_value=5.0,
        available_balance=13.4662,
        reserve_usd=7.5565,
    )
    opening_sizing = service._build_directional_opening_sizing_fields(
        planned_qty=0.9,
        price=89.32,
        leverage=5.0,
        opening_qty_adjustment=adjustment,
    )
    submitted = service._augment_directional_opening_sizing_fields(
        opening_sizing,
        submitted_qty=0.3,
        submitted_price=88.8,
    )

    assert submitted["planned_qty"] == 0.9
    assert submitted["capped_qty"] == 0.3
    assert submitted["submitted_qty"] == 0.3
    assert submitted["affordability_cap_evaluated"] is True
    assert submitted["affordability_cap_applied"] is True
    assert submitted["affordability_cap_material"] is True
    assert submitted["affordability_cap_immaterial"] is False
    assert submitted["affordability_cap_reason"] == "opening_margin_affordability_cap"
    assert submitted["affordability_qty_reduction"] == 0.6
    assert submitted["affordability_notional_reduction"] == 53.592
    assert submitted["planned_notional"] == 80.388
    assert submitted["capped_notional"] == 26.796
    assert submitted["submitted_notional"] == 26.64


def test_directional_opening_sizing_fields_stay_truthful_when_no_cap_is_needed():
    service = _make_service()

    adjustment = service._cap_directional_opening_qty_to_affordability(
        mode="long",
        planned_qty=0.2,
        price=100.0,
        leverage=5.0,
        qty_step=0.1,
        min_qty=0.1,
        min_notional_value=5.0,
        available_balance=50.0,
        reserve_usd=0.0,
    )
    opening_sizing = service._build_directional_opening_sizing_fields(
        planned_qty=0.2,
        price=100.0,
        leverage=5.0,
        opening_qty_adjustment=adjustment,
    )

    assert opening_sizing["planned_qty"] == 0.2
    assert opening_sizing["capped_qty"] == 0.2
    assert opening_sizing["planned_notional"] == 20.0
    assert opening_sizing["capped_notional"] == 20.0
    assert opening_sizing["affordability_cap_evaluated"] is True
    assert opening_sizing["affordability_cap_applied"] is False
    assert opening_sizing["affordability_cap_material"] is False
    assert opening_sizing["affordability_cap_immaterial"] is False
    assert "affordability_cap_reason" not in opening_sizing


def test_directional_opening_sizing_fields_flag_immaterial_affordability_checks_separately():
    service = _make_service()

    opening_sizing = service._build_directional_opening_sizing_fields(
        planned_qty=0.2,
        price=100.0,
        leverage=5.0,
        opening_qty_adjustment={
            "adjusted": True,
            "candidate_qty": 0.2,
            "candidate_notional": 20.0,
        },
    )

    assert opening_sizing["affordability_cap_evaluated"] is True
    assert opening_sizing["affordability_cap_applied"] is False
    assert opening_sizing["affordability_cap_material"] is False
    assert opening_sizing["affordability_cap_immaterial"] is True
    assert opening_sizing["affordability_cap_reason"] == "opening_margin_affordability_cap"


def test_place_initial_entry_uses_affordable_qty_instead_of_full_capital():
    service = _make_service()
    service._get_usdt_available_balance = Mock(return_value=13.4662)
    service._calculate_auto_margin_reserve = Mock(return_value=(7.5565, 42.8202))
    service._normalize_order_qty = Mock(side_effect=lambda **kwargs: kwargs["raw_qty"])
    service._create_order_checked = Mock(
        return_value={"retCode": 0, "data": {"orderId": "init-1"}}
    )
    service._record_trade_forensic_position_opened = Mock()
    service._mark_audit_actual_entry = Mock()
    service._mark_breakout_entry_context = Mock()
    service._record_audit_cycle = Mock()
    service._activate_capital_starved_opening_block = Mock()
    service.client.get_instruments_info.return_value = {
        "data": {
            "list": [
                {
                    "lotSizeFilter": {
                        "qtyStep": "0.1",
                        "minOrderQty": "0.1",
                        "minNotionalValue": "5",
                    }
                }
            ]
        }
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": []},
    }

    result = service._place_initial_entry(
        bot={"id": "bot-1", "investment": 51.48, "leverage": 5.0, "grid_count": 1},
        symbol="SOLUSDT",
        last_price=89.32,
        mode="long",
        now_iso="2026-03-13T05:30:00+00:00",
    )

    assert result is True
    assert service._create_order_checked.call_args.kwargs["qty"] == 0.3
    service._activate_capital_starved_opening_block.assert_not_called()


def test_place_initial_entry_still_reports_true_insufficient_margin_when_no_funds_exist():
    service = _make_service()
    service._get_usdt_available_balance = Mock(return_value=0.0)
    service._calculate_auto_margin_reserve = Mock(return_value=(0.0, 20.0))
    service._normalize_order_qty = Mock(side_effect=lambda **kwargs: kwargs["raw_qty"])
    service._activate_capital_starved_opening_block = Mock()
    service.client.get_instruments_info.return_value = {
        "data": {
            "list": [
                {
                    "lotSizeFilter": {
                        "qtyStep": "0.1",
                        "minOrderQty": "0.1",
                        "minNotionalValue": "5",
                    }
                }
            ]
        }
    }

    result = service._place_initial_entry(
        bot={"id": "bot-2", "investment": 20.0, "leverage": 5.0},
        symbol="BTCUSDT",
        last_price=100.0,
        mode="long",
        now_iso="2026-03-13T05:31:00+00:00",
    )

    assert result is False
    assert service._activate_capital_starved_opening_block.call_args.kwargs["reason"] == (
        "insufficient_margin_guard"
    )


def test_order_submitted_forensics_persists_directional_opening_sizing(tmp_path):
    trade_forensics = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))
    client = BybitClient.__new__(BybitClient)
    client.trade_forensics_service = trade_forensics
    client.order_ownership_service = None
    client.stream_service = None
    client._run_order_command = lambda symbol, command, fn: {
        "success": True,
        "data": {"orderId": "ord-1", "orderLinkId": "lnk-1"},
    }
    client._invalidate_order_caches = lambda: None
    client._mark_stream_open_orders_dirty = lambda symbol: None
    client._forget_recent_open_order_hints_for_symbol = lambda symbol: None
    client._remember_open_order_hint = lambda **kwargs: None
    client.normalize_qty = lambda symbol, qty: qty

    ownership_snapshot = {
        "bot_id": "bot-1",
        "bot_mode": "long",
        "bot_profile": "normal",
        "forensic_decision_id": "fdc:test",
        "forensic_trade_context_id": "ftc:test",
        "forensic_decision_type": "grid_opening",
        "forensic_side": "Buy",
        "action": "entry",
        "experiment_attribution_state": "none",
        "entry_story": {
            "entry_kind": "initial_opening",
            "readiness_stage": "trigger_ready",
            "signal_code": "breakout",
            "signal_executable": True,
            "experiment_attribution_state": "none",
        },
        "opening_sizing": {
            "planned_qty": 0.9,
            "capped_qty": 0.3,
            "submitted_qty": 0.3,
            "planned_notional": 80.388,
            "capped_notional": 26.796,
            "submitted_notional": 26.64,
            "affordability_cap_applied": True,
            "affordability_cap_reason": "opening_margin_affordability_cap",
            "available_opening_margin": 5.9097,
            "required_margin": 5.3592,
        },
    }

    result = BybitClient.create_order(
        client,
        symbol="SOLUSDT",
        side="Buy",
        qty=0.3,
        order_type="Limit",
        price=88.8,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id="lnk-1",
        qty_is_normalized=True,
        ownership_snapshot=ownership_snapshot,
    )

    assert result["success"] is True
    event = trade_forensics.get_recent_events(event_type="order_submitted", limit=5)[-1]
    assert event["order"]["opening_sizing"]["planned_qty"] == 0.9
    assert event["order"]["opening_sizing"]["capped_qty"] == 0.3
    assert event["order"]["opening_sizing"]["submitted_qty"] == 0.3
    assert event["order"]["opening_sizing"]["affordability_cap_applied"] is True
    assert event["order"]["experiment_attribution_state"] == "none"
    assert event["order"]["entry_story"]["entry_kind"] == "initial_opening"
