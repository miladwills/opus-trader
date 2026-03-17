import logging

from services.order_ownership_service import build_order_ownership_snapshot
from services.pnl_service import PnlService
from services.symbol_pnl_service import SymbolPnlService


BOT_ID = "31b431db-9741-44ff-9e16-46eaf31a057a"
ORDER_ID = "84544d0a-3f85-4682-a77b-578181947282"


class FakeClient:
    def __init__(self, closed_records, executions):
        self.closed_records = closed_records
        self.executions = executions

    def get_closed_pnl(self, symbol=None, limit=100):
        return {"success": True, "data": {"list": list(self.closed_records)}}

    def get_wallet_balance(self):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "coin": [
                            {
                                "coin": "USDT",
                                "walletBalance": "19.50",
                            }
                        ]
                    }
                ]
            },
        }

    def get_executions(self, symbol=None, limit=50, skip_cache=False):
        return {"success": True, "data": {"list": list(self.executions)}}


class FakeBotStorage:
    def __init__(self, bots):
        self._bots = list(bots)

    def list_bots(self):
        return list(self._bots)


def make_service(tmp_path, closed_records=None, executions=None, bots=None):
    closed_records = closed_records or [
        {
            "orderId": ORDER_ID,
            "createdTime": "1772906881267",
            "symbol": "RIVERUSDT",
            "side": "Sell",
            "closedPnl": "-0.0855282",
            "orderLinkId": None,
        }
    ]
    executions = executions if executions is not None else [
        {
            "orderId": ORDER_ID,
            "orderLinkId": "cls:31b431db:068811370513SCTP",
        }
    ]
    client = FakeClient(closed_records=closed_records, executions=executions)
    bot_storage = FakeBotStorage(
        bots
        or [
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "investment": 18.15,
                "leverage": 9.0,
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "started_at": "2026-03-07T16:09:54.541590+00:00",
                "created_at": "2026-03-07T16:08:18.211961+00:00",
                "profile": "normal",
                "effective_step_pct": 0.0037,
                "fee_aware_min_step_pct": 0.0037,
                "runtime_open_order_cap_total": 18,
                "atr_5m_pct": 0.0158,
                "atr_15m_pct": 0.0320,
                "regime_effective": "SIDEWAYS",
            }
        ]
    )
    symbol_pnl_service = SymbolPnlService(str(tmp_path / "symbol_pnl.json"))
    return PnlService(
        client=client,
        file_path=str(tmp_path / "trade_logs.json"),
        bot_storage=bot_storage,
        symbol_pnl_service=symbol_pnl_service,
    )


def test_sync_closed_pnl_uses_executions_when_closed_pnl_omits_order_link_id(tmp_path):
    service = make_service(tmp_path)

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] == BOT_ID
    assert logs[0]["bot_mode"] == "scalp_pnl"
    assert logs[0]["bot_range_mode"] == "dynamic"
    assert logs[0]["order_id"] == ORDER_ID
    assert logs[0]["order_link_id"] == "cls:31b431db:068811370513SCTP"
    assert logs[0]["attribution_source"] == "order_link_id:execution_lookup"

    bot_pnl = service.symbol_pnl_service.get_bot_pnl(BOT_ID)
    assert bot_pnl is not None
    assert bot_pnl["trade_count"] == 1


def test_sync_closed_pnl_repairs_existing_unattributed_logs(tmp_path):
    service = make_service(tmp_path)
    service._write_logs(
        [
            {
                "id": ORDER_ID,
                "time": "2026-03-07T17:28:01.267000+00:00",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "realized_pnl": -0.0855282,
                "balance_after": 19.5,
                "bot_id": None,
                "bot_investment": None,
                "bot_leverage": None,
                "bot_mode": None,
                "bot_range_mode": None,
                "bot_started_at": None,
                "bot_profile": None,
                "effective_step_pct": None,
                "fee_aware_min_step_pct": None,
                "runtime_open_order_cap_total": None,
                "atr_5m_pct": None,
                "atr_15m_pct": None,
                "regime_effective": None,
            }
        ]
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] == BOT_ID
    assert logs[0]["bot_profile"] == "normal"
    assert logs[0]["order_link_id"] == "cls:31b431db:068811370513SCTP"
    assert logs[0]["attribution_source"] == "order_link_id:execution_lookup"


def test_sync_closed_pnl_leaves_trade_unattributed_when_multiple_eligible_same_symbol_bots(
    tmp_path,
):
    older_bot_id = "7fe5dc76-0f86-4233-a74d-581ccfb8fead"
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772906881267",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.0855282",
                "orderLinkId": None,
            }
        ],
        executions=[],
        bots=[
            {
                "id": older_bot_id,
                "symbol": "RIVERUSDT",
                "status": "stopped",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "status": "running",
                "investment": 18.15,
                "leverage": 9.0,
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T16:08:18.211961+00:00",
                "profile": "normal",
            },
        ],
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] is None
    assert logs[0]["attribution_source"] == "ambiguous_symbol"


def test_sync_closed_pnl_uses_single_eligible_same_symbol_bot(tmp_path):
    older_bot_id = "7fe5dc76-0f86-4233-a74d-581ccfb8fead"
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772901000000",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.0855282",
                "orderLinkId": None,
            }
        ],
        executions=[],
        bots=[
            {
                "id": older_bot_id,
                "symbol": "RIVERUSDT",
                "status": "stopped",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "status": "running",
                "investment": 18.15,
                "leverage": 9.0,
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T17:08:18.211961+00:00",
                "profile": "normal",
            },
        ],
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] == older_bot_id
    assert logs[0]["attribution_source"] == "unique_symbol_fallback"


def test_sync_closed_pnl_uses_persisted_order_ownership_snapshot_after_owner_deletion(
    tmp_path,
):
    deleted_owner = {
        "id": BOT_ID,
        "symbol": "RIVERUSDT",
        "investment": 18.15,
        "leverage": 9.0,
        "mode": "scalp_pnl",
        "range_mode": "dynamic",
        "started_at": "2026-03-07T16:09:54.541590+00:00",
        "created_at": "2026-03-07T16:08:18.211961+00:00",
        "profile": "normal",
        "effective_step_pct": 0.0037,
        "fee_aware_min_step_pct": 0.0037,
        "runtime_open_order_cap_total": 18,
        "atr_5m_pct": 0.0158,
        "atr_15m_pct": 0.0320,
        "regime_effective": "SIDEWAYS",
    }
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772906881267",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.0855282",
                "orderLinkId": None,
            }
        ],
        executions=[],
        bots=[
            {
                "id": "bot-other-1",
                "symbol": "RIVERUSDT",
                "status": "running",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": "bot-other-2",
                "symbol": "RIVERUSDT",
                "status": "paused",
                "mode": "short",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:45:08.459557+00:00",
            },
        ],
    )
    ownership_snapshot = build_order_ownership_snapshot(
        deleted_owner,
        source="manual_close",
        action="manual_close",
        close_reason="MANL",
    )
    ownership_snapshot.update(
        {
            "order_id": ORDER_ID,
            "order_link_id": "cls:31b431db:068811370513MANL",
            "symbol": "RIVERUSDT",
            "side": "Sell",
            "position_idx": 2,
            "reduce_only": True,
        }
    )
    service.order_ownership_service.record_order(ownership_snapshot)

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] == BOT_ID
    assert logs[0]["order_link_id"] == "cls:31b431db:068811370513MANL"
    assert logs[0]["position_idx"] == 2
    assert logs[0]["attribution_source"] == "ownership_snapshot"
    assert logs[0]["ownership_source"] == "manual_close"
    assert logs[0]["ownership_action"] == "manual_close"


def test_sync_closed_pnl_warns_once_per_symbol_for_unresolved_ambiguous_symbol(
    tmp_path, caplog
):
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": "older-1",
                "createdTime": "0",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.1",
                "orderLinkId": None,
            },
            {
                "orderId": "older-2",
                "createdTime": "1",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.2",
                "orderLinkId": None,
            },
        ],
        executions=[],
        bots=[
            {
                "id": "bot-old",
                "symbol": "RIVERUSDT",
                "status": "stopped",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "status": "running",
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T16:08:18.211961+00:00",
            },
        ],
    )

    with caplog.at_level(logging.WARNING):
        service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 2
    assert all(log["bot_id"] is None for log in logs)

    warnings = [
        record.message
        for record in caplog.records
        if "Multiple bots found for symbol 'RIVERUSDT'" in record.message
    ]
    assert len(warnings) == 1


def test_sync_closed_pnl_recognizes_nlp_order_link_ids(tmp_path):
    nlp_bot_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772906881267",
                "symbol": "ETHUSDT",
                "side": "Sell",
                "closedPnl": "1.25",
                "orderLinkId": "nlp:a1b2c3d4e5f6:INV:2:0688113705:00",
            }
        ],
        executions=[],
        bots=[
            {
                "id": nlp_bot_id,
                "symbol": "ETHUSDT",
                "status": "running",
                "mode": "neutral_classic_bybit",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            }
        ],
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] == nlp_bot_id
    assert logs[0]["order_link_id"] == "nlp:a1b2c3d4e5f6:INV:2:0688113705:00"
    assert logs[0]["attribution_source"] == "order_link_id:closed_pnl"


def test_sync_closed_pnl_does_not_symbol_fallback_manual_close_order_link_id(tmp_path):
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772906881267",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.0855282",
                "orderLinkId": "close_manual_1772906881267_0",
            }
        ],
        executions=[],
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] is None
    assert logs[0]["order_link_id"] == "close_manual_1772906881267_0"
    assert logs[0]["attribution_source"] == "manual_close"


def test_sync_closed_pnl_marks_explicit_ambiguous_close_order_link_id(tmp_path):
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "1772906881267",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.0855282",
                "orderLinkId": "ambg:12345678:2:beef",
                "positionIdx": 2,
            }
        ],
        executions=[],
        bots=[
            {
                "id": "bot-old",
                "symbol": "RIVERUSDT",
                "status": "running",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "status": "running",
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T16:08:18.211961+00:00",
            },
        ],
    )

    service.sync_closed_pnl()

    logs = service.get_log()
    assert len(logs) == 1
    assert logs[0]["bot_id"] is None
    assert logs[0]["order_link_id"] == "ambg:12345678:2:beef"
    assert logs[0]["position_idx"] == 2
    assert logs[0]["attribution_source"] == "explicit_ambiguous_close"


def test_sync_closed_pnl_does_not_rewarn_for_existing_unresolved_trade(
    tmp_path, caplog
):
    service = make_service(
        tmp_path,
        closed_records=[
            {
                "orderId": ORDER_ID,
                "createdTime": "0",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "closedPnl": "-0.1",
                "orderLinkId": None,
            }
        ],
        executions=[],
        bots=[
            {
                "id": "bot-old",
                "symbol": "RIVERUSDT",
                "status": "stopped",
                "mode": "long",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T15:41:08.459557+00:00",
            },
            {
                "id": BOT_ID,
                "symbol": "RIVERUSDT",
                "status": "running",
                "mode": "scalp_pnl",
                "range_mode": "dynamic",
                "created_at": "2026-03-07T16:08:18.211961+00:00",
            },
        ],
    )
    service._write_logs(
        [
            {
                "id": ORDER_ID,
                "time": "1970-01-01T00:00:00+00:00",
                "symbol": "RIVERUSDT",
                "side": "Sell",
                "realized_pnl": -0.1,
                "balance_after": 19.5,
                "bot_id": None,
                "bot_investment": None,
                "bot_leverage": None,
                "bot_mode": None,
                "bot_range_mode": None,
                "bot_started_at": None,
                "bot_profile": None,
                "effective_step_pct": None,
                "fee_aware_min_step_pct": None,
                "runtime_open_order_cap_total": None,
                "atr_5m_pct": None,
                "atr_15m_pct": None,
                "regime_effective": None,
            }
        ]
    )

    with caplog.at_level(logging.WARNING):
        service.sync_closed_pnl()

    warnings = [
        record.message
        for record in caplog.records
        if "Multiple bots found for symbol 'RIVERUSDT'" in record.message
    ]
    assert warnings == []


def test_sync_closed_pnl_preserves_existing_trade_metadata_snapshot(tmp_path):
    bot_id = "bot12345-aaaa-bbbb-cccc-000000000000"

    class SnapshotClient:
        def __init__(self):
            self.closed_records = [
                {
                    "orderId": "oid-1",
                    "createdTime": "1772906881267",
                    "symbol": "BTCUSDT",
                    "side": "Sell",
                    "closedPnl": "1.0",
                    "orderLinkId": "cls:bot12345:abc",
                }
            ]

        def get_closed_pnl(self, symbol=None, limit=100):
            return {"success": True, "data": {"list": list(self.closed_records)}}

        def get_wallet_balance(self):
            return {
                "success": True,
                "data": {"list": [{"coin": [{"coin": "USDT", "walletBalance": "100"}]}]},
            }

        def get_executions(self, symbol=None, limit=50, skip_cache=False):
            return {"success": True, "data": {"list": []}}

    class SnapshotStorage:
        def __init__(self):
            self.bots = [
                {
                    "id": bot_id,
                    "symbol": "BTCUSDT",
                    "investment": 100,
                    "leverage": 2,
                    "mode": "neutral",
                    "range_mode": "dynamic",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ]

        def list_bots(self):
            return list(self.bots)

    service = PnlService(
        client=SnapshotClient(),
        file_path=str(tmp_path / "trade_logs.json"),
        bot_storage=SnapshotStorage(),
        symbol_pnl_service=SymbolPnlService(str(tmp_path / "symbol_pnl.json")),
    )

    service.sync_closed_pnl()
    initial_logs = service.get_log()
    assert initial_logs[0]["bot_mode"] == "neutral"
    assert initial_logs[0]["bot_leverage"] == 2

    service.bot_storage.bots = [
        {
            "id": bot_id,
            "symbol": "BTCUSDT",
            "investment": 250,
            "leverage": 5,
            "mode": "long",
            "range_mode": "fixed",
            "started_at": "2026-02-01T00:00:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]

    service.sync_closed_pnl()
    repaired_logs = service.get_log()

    assert repaired_logs[0]["bot_mode"] == "neutral"
    assert repaired_logs[0]["bot_range_mode"] == "dynamic"
    assert repaired_logs[0]["bot_investment"] == 100
    assert repaired_logs[0]["bot_leverage"] == 2
