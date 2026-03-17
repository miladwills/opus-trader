from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from services.grid_bot_service import GridBotService


class _AuditCollector:
    def __init__(self):
        self.events = []
        self._throttle = {}

    def enabled(self):
        return True

    def record_event(self, payload, throttle_key=None, throttle_sec=None, **_kwargs):
        key = throttle_key or ""
        if key and self._throttle.get(key) == payload:
            return False
        if key:
            self._throttle[key] = dict(payload)
        self.events.append(dict(payload))
        return True


class _BotStorage:
    def __init__(self, bots):
        self._bots = [dict(bot) for bot in list(bots or [])]
        self.saved = []
        self.runtime_saved = []
        self.cache_only = []
        self.list_bots_calls = []

    def list_bots(self, *, source=None):
        self.list_bots_calls.append(source)
        return [dict(bot) for bot in self._bots]

    def save_bot(self, bot):
        snapshot = dict(bot)
        bot_id = str(bot.get("id") or "").strip()
        self._bots = [
            snapshot if str(item.get("id") or "").strip() == bot_id else dict(item)
            for item in self._bots
        ]
        self.saved.append(snapshot)
        return snapshot

    def save_runtime_bot(self, bot, persist=True, **kwargs):
        snapshot = dict(bot)
        bot_id = str(bot.get("id") or "").strip()
        self._bots = [
            snapshot if str(item.get("id") or "").strip() == bot_id else dict(item)
            for item in self._bots
        ]
        record = {
            "bot": snapshot,
            "persist": bool(persist),
            "kwargs": dict(kwargs),
        }
        if persist:
            self.runtime_saved.append(record)
        else:
            self.cache_only.append(record)
        return snapshot


class _ClientStub:
    def __init__(self, *, positions=None, orders_by_symbol=None):
        self.positions = [dict(item) for item in list(positions or [])]
        self.orders_by_symbol = {
            str(symbol): [dict(item) for item in list(items or [])]
            for symbol, items in dict(orders_by_symbol or {}).items()
        }
        self.create_order = Mock()
        self.cancel_all_orders = Mock()
        self.cancel_order = Mock()
        self.close_position = Mock()

    def get_positions(self, skip_cache=False):
        return {"success": True, "data": {"list": [dict(item) for item in self.positions]}}

    def get_open_orders(self, symbol=None, limit=200, skip_cache=False):
        return {
            "success": True,
            "data": {
                "list": [
                    dict(item)
                    for item in self.orders_by_symbol.get(str(symbol or ""), [])
                ]
            },
        }


def _make_service(*, bots, positions=None, orders_by_symbol=None):
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = _BotStorage(bots)
    service.client = _ClientStub(
        positions=positions,
        orders_by_symbol=orders_by_symbol,
    )
    service.audit_diagnostics_service = _AuditCollector()
    return service


@pytest.mark.parametrize(
    ("positions", "orders_by_symbol", "mismatch", "stale_field"),
    [
        (
            [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.02",
                    "positionIdx": 1,
                }
            ],
            {},
            "orphaned_position",
            "position_assumption_stale",
        ),
        (
            [],
            {
                "BTCUSDT": [
                    {
                        "symbol": "BTCUSDT",
                        "orderId": "order-1",
                        "orderLinkId": "bot:bot-1:123:1",
                    }
                ]
            },
            "orphaned_order",
            "order_assumption_stale",
        ),
    ],
)
def test_startup_reconciliation_detects_exchange_persist_mismatch_without_trading(
    positions,
    orders_by_symbol,
    mismatch,
    stale_field,
):
    service = _make_service(
        bots=[
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "status": "running",
                "position_size": 0.0,
                "open_order_count": 0,
            }
        ],
        positions=positions,
        orders_by_symbol=orders_by_symbol,
    )

    updated = service.reconcile_bots_exchange_truth(
        service.bot_storage.list_bots(),
        reason="startup",
        force=True,
    )

    assert len(updated) == 1
    reconciled = updated[0]
    assert reconciled["exchange_reconciliation"]["source"] == "startup"
    assert reconciled["exchange_reconciliation"]["status"] == "diverged"
    assert reconciled["exchange_reconciliation"]["reason"] == mismatch
    assert mismatch in reconciled["exchange_reconciliation"]["mismatches"]
    assert reconciled[stale_field] is True
    assert reconciled["position_size"] == 0.0
    assert reconciled["open_order_count"] == 0

    events = service.audit_diagnostics_service.events
    exchange_event = next(
        event for event in events if event.get("event_type") == "exchange_reconciliation"
    )
    assert exchange_event["reconciliation_source"] == "startup"
    assert mismatch in list(exchange_event.get("mismatches") or [])

    service.client.create_order.assert_not_called()
    service.client.cancel_all_orders.assert_not_called()
    service.client.cancel_order.assert_not_called()
    service.client.close_position.assert_not_called()
    assert service.bot_storage.list_bots_calls == [None, "exchange_reconciliation:startup"]


def test_reconciliation_reuses_passed_full_snapshot_without_relisting_storage():
    bots = [
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "running",
            "position_size": 0.0,
            "open_order_count": 0,
        },
        {
            "id": "bot-2",
            "symbol": "BTCUSDT",
            "status": "paused",
            "position_size": 0.0,
            "open_order_count": 0,
        },
    ]
    service = _make_service(
        bots=bots,
        positions=[],
        orders_by_symbol={},
    )

    updated = service.reconcile_bots_exchange_truth(
        [bots[0]],
        reason="startup",
        force=True,
        all_bots_snapshot=bots,
    )

    assert len(updated) == 1
    assert updated[0]["exchange_reconciliation"]["same_symbol_bot_count"] == 2
    assert service.bot_storage.list_bots_calls == []


@pytest.mark.parametrize(
    ("bot", "positions", "orders_by_symbol", "expected_status"),
    [
        (
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "status": "error",
                "position_size": 0.02,
                "open_order_count": 0,
            },
            [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.02",
                    "positionIdx": 1,
                }
            ],
            {},
            "error_with_open_position",
        ),
        (
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "status": "error",
                "position_size": 0.0,
                "open_order_count": 1,
            },
            [],
            {
                "BTCUSDT": [
                    {
                        "symbol": "BTCUSDT",
                        "orderId": "order-1",
                        "orderLinkId": "bot:bot-1:123:1",
                    }
                ]
            },
            "error_with_open_orders",
        ),
    ],
)
def test_error_state_reconciliation_classifies_exchange_exposure(
    bot,
    positions,
    orders_by_symbol,
    expected_status,
):
    service = _make_service(
        bots=[bot],
        positions=positions,
        orders_by_symbol=orders_by_symbol,
    )

    updated = service.reconcile_bots_exchange_truth(
        service.bot_storage.list_bots(),
        reason="error_maintenance",
        force=True,
    )

    assert updated[0]["exchange_reconciliation"]["status"] == expected_status
    exchange_event = next(
        event for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "exchange_reconciliation"
    )
    assert exchange_event["reconciliation_status"] == expected_status
    service.client.create_order.assert_not_called()
    service.client.cancel_all_orders.assert_not_called()
    service.client.close_position.assert_not_called()


def test_error_state_reconciliation_skips_duplicate_persist_when_only_timestamps_change():
    service = _make_service(
        bots=[
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "status": "error",
                "position_size": 0.0,
                "open_order_count": 0,
            }
        ],
        positions=[],
        orders_by_symbol={},
    )

    baseline = service.reconcile_bots_exchange_truth(
        service.bot_storage.list_bots(),
        reason="error_maintenance",
        force=True,
    )[0]
    assert len(service.bot_storage.runtime_saved) == 1

    service.bot_storage._bots = [dict(baseline)]
    service.bot_storage.runtime_saved.clear()
    service.bot_storage.cache_only.clear()

    updated = service.reconcile_bots_exchange_truth(
        service.bot_storage.list_bots(),
        reason="error_maintenance",
        force=True,
    )

    assert len(updated) == 1
    assert service.bot_storage.runtime_saved == []
    assert len(service.bot_storage.cache_only) == 1
    cache_only_save = service.bot_storage.cache_only[0]
    assert cache_only_save["persist"] is False
    assert cache_only_save["kwargs"]["path"] == "exchange_reconciliation"
    assert cache_only_save["kwargs"]["reason"] == "error_maintenance"
    assert cache_only_save["kwargs"]["persistence_class"] == "error_path"


def test_ambiguous_execution_follow_up_is_revisited_and_resolved_from_exchange_truth():
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    service = _make_service(
        bots=[
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "status": "running",
                "position_size": 0.0,
                "open_order_count": 0,
                "ambiguous_execution_follow_up": {
                    "status": "pending",
                    "pending": True,
                    "action": "create_order",
                    "symbol": "BTCUSDT",
                    "order_link_id": "bot:bot-1:123:1",
                    "diagnostic_reason": "order_router_timeout",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": expires_at,
                },
            }
        ],
        positions=[],
        orders_by_symbol={
            "BTCUSDT": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "order-1",
                    "orderLinkId": "bot:bot-1:123:1",
                }
            ]
        },
    )

    updated = service.reconcile_bots_exchange_truth(
        service.bot_storage.list_bots(),
        reason="ambiguous_follow_up",
        force=True,
    )

    marker = updated[0]["ambiguous_execution_follow_up"]
    assert marker["status"] == "success_reflected"
    assert marker["pending"] is False
    assert marker["exchange_effect_reason"] == "matching_open_order_visible"
    assert marker["resolved_at"] is not None

    resolved_event = next(
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "ambiguous_execution_follow_up_resolved"
    )
    assert resolved_event["status"] == "success_reflected"
    service.client.create_order.assert_not_called()
    service.client.cancel_all_orders.assert_not_called()
    service.client.close_position.assert_not_called()
