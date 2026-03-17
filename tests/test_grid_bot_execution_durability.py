import logging
from unittest.mock import Mock, patch

import pytest

from services.grid_bot_service import GridBotService


def _make_service() -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.bot_storage.list_bots.return_value = []
    service.client = Mock()
    service._close_attempt_fences = {}
    service._last_close_position_result = None
    service._record_control_timing = lambda *args, **kwargs: None
    service._resolve_position_idx = lambda *args, **kwargs: 1
    return service


def test_close_intent_reuses_fenced_order_link_id_within_same_window(caplog):
    service = _make_service()
    bot = {"id": "bot-1", "symbol": "BTCUSDT"}

    with caplog.at_level(logging.WARNING):
        first = service._get_full_close_attempt_order_link_id(
            bot=bot,
            symbol="BTCUSDT",
            close_side="Sell",
            position_idx=1,
            close_reason="CLOS",
        )
        second = service._get_full_close_attempt_order_link_id(
            bot=bot,
            symbol="BTCUSDT",
            close_side="Sell",
            position_idx=1,
            close_reason="CLOS",
        )

    assert first == second
    assert "CLOSE_INTENT_REUSED symbol=BTCUSDT bot_id=bot-1" in caplog.text

    service._clear_full_close_attempt_fence(
        bot=bot,
        symbol="BTCUSDT",
        close_side="Sell",
        position_idx=1,
    )
    third = service._get_full_close_attempt_order_link_id(
        bot=bot,
        symbol="BTCUSDT",
        close_side="Sell",
        position_idx=1,
        close_reason="CLOS",
    )

    assert third != first


def test_close_position_market_does_not_retry_ambiguous_close_result(caplog):
    service = _make_service()
    bot = {"id": "bot-1", "symbol": "BTCUSDT"}
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.01",
                    "markPrice": "42000",
                    "positionIdx": 1,
                }
            ]
        },
    }
    service._create_order_checked = Mock(
        return_value={
            "success": None,
            "status": "in_flight",
            "error": "order_router_timeout",
            "retCode": -2,
            "retry_safe": False,
        }
    )

    with caplog.at_level(logging.WARNING):
        result = service._close_position_market("BTCUSDT", bot=bot)

    assert result is False
    service._create_order_checked.assert_called_once()
    assert service._last_close_position_result["success"] is None
    assert service._last_close_position_result["retry_safe"] is False
    assert "CLOSE_RETRY_NOT_SAFE symbol=BTCUSDT bot_id=bot-1" in caplog.text


def test_force_cancel_all_orders_does_not_retry_ambiguous_cancel_result(caplog):
    service = _make_service()
    service.client.cancel_all_orders.return_value = {
        "success": None,
        "status": "unknown_outcome",
        "error": "order_router_timeout",
        "retCode": -2,
        "retry_safe": False,
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": [{"orderId": "order-1"}]},
    }

    with patch("services.grid_bot_service.time.sleep", return_value=None):
        with caplog.at_level(logging.WARNING):
            result = service._force_cancel_all_orders(
                "BTCUSDT",
                max_retries=3,
                bot={"id": "bot-1", "symbol": "BTCUSDT"},
            )

    assert result["success"] is None
    assert result["retry_safe"] is False
    assert result["diagnostic_reason"] == "cancel_all_orders_ambiguous"
    service.client.cancel_all_orders.assert_called_once_with("BTCUSDT")
    service.client.cancel_order.assert_not_called()
    assert "CANCEL_RETRY_NOT_SAFE symbol=BTCUSDT" in caplog.text


@pytest.mark.parametrize(
    ("bot_fields", "expected_reason"),
    [
        ({"position_assumption_stale": True}, "exchange_truth_stale"),
        ({"order_assumption_stale": True}, "exchange_truth_stale"),
        (
            {
                "exchange_reconciliation": {
                    "status": "diverged",
                    "reason": "orphaned_order",
                    "mismatches": ["orphaned_order"],
                }
            },
            "reconciliation_diverged",
        ),
    ],
)
@patch("services.grid_bot_service.now_ts", return_value=1_700_000_000.0)
def test_create_order_checked_blocks_non_reduce_only_when_exchange_truth_is_untrusted(
    _mock_now_ts,
    bot_fields,
    expected_reason,
):
    service = _make_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        **bot_fields,
    }

    result = service._create_order_checked(
        bot=bot,
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=42000.0,
        reduce_only=False,
    )

    assert result["success"] is False
    assert result["error"] == expected_reason
    assert result["skip_reason"] == expected_reason
    assert result["diagnostic_reason"] == expected_reason
    service.client.create_order.assert_not_called()


@patch("services.grid_bot_service.now_ts", return_value=1_700_000_000.0)
@patch("services.grid_bot_service.iso_from_ts", return_value="2026-03-13T22:00:00+00:00")
def test_create_order_checked_allows_reduce_only_when_exchange_truth_is_untrusted(
    _mock_iso_from_ts,
    _mock_now_ts,
):
    service = _make_service()
    service._normalize_order_qty = Mock(return_value=0.01)
    service._get_instrument_info = Mock(return_value=None)
    service._build_persistent_ownership_snapshot = Mock(return_value=None)
    service._augment_directional_opening_sizing_fields = Mock(return_value=None)
    service._record_first_start_order = Mock()
    service.client.create_order.return_value = {"success": True}

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "_position_mode": "hedge",
        "position_assumption_stale": True,
    }

    result = service._create_order_checked(
        bot=bot,
        symbol="BTCUSDT",
        side="Sell",
        qty=0.01,
        price=42000.0,
        reduce_only=True,
    )

    assert result["success"] is True
    service.client.create_order.assert_called_once()


def test_ai_block_opening_orders_blocks_diverged_reconciliation_state():
    service = _make_service()

    assert service._ai_block_opening_orders(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "exchange_reconciliation": {
                "status": "diverged",
                "reason": "orphaned_order",
                "mismatches": ["orphaned_order"],
            },
        }
    )
