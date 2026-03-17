import csv
from pathlib import Path

from services.backtest.engine import BacktestEngine
from services.backtest.mock_client import MockBybitClient
from services.order_ownership_service import build_order_ownership_snapshot


def _build_candles(count: int, *, start_price: float = 100.0, step: float = 1.0):
    candles = []
    timestamp = 1700000000000
    for index in range(count):
        close_price = start_price + (index * step)
        candles.append(
            {
                "timestamp": timestamp + (index * 900000),
                "open": close_price - 0.4,
                "high": close_price + 0.8,
                "low": close_price - 0.8,
                "close": close_price,
                "volume": 1000 + index,
            }
        )
    return candles


def _decision_event_payload(engine: BacktestEngine, bot_id: str, ids: dict, *, event_type: str):
    return {
        "event_type": event_type,
        "timestamp": engine.client._now_iso(),
        "forensic_decision_id": ids["forensic_decision_id"],
        "trade_context_id": ids["trade_context_id"],
        "bot_id": bot_id,
        "symbol": engine.symbol,
        "mode": "long",
        "profile": "normal",
        "side": "Buy",
        "decision_type": "initial_entry",
        "linkage_method": "direct_runtime",
        "attribution_status": "linked",
        "event_status": "candidate" if event_type == "decision" else "blocked",
        "decision_context": {
            "local_decision": {
                "reason_to_enter": ["test replay decision"],
                "setup_quality": {
                    "score": 0.71,
                    "band": "good",
                    "entry_allowed": True,
                    "summary": "synthetic replay context",
                },
                "entry_signal": {
                    "code": "test_signal",
                    "phase": "replay",
                    "preferred": True,
                    "executable": True,
                },
                "gate": {
                    "blocked": event_type == "skip_blocked",
                    "reason": "test_blocker" if event_type == "skip_blocked" else None,
                },
                "blockers": (
                    [{"code": "test_blocker", "reason": "synthetic block", "phase": "entry"}]
                    if event_type == "skip_blocked"
                    else []
                ),
            },
            "market": {"last_price": 100.0, "regime_effective": "trend"},
        },
    }


def test_backtest_load_data_from_csv_sorts_candles(tmp_path):
    csv_path = tmp_path / "candles.csv"
    candles = list(reversed(_build_candles(3)))
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(candles)

    engine = BacktestEngine("BTCUSDT", "", "", 1000.0, storage_root=str(tmp_path))
    engine.load_data(str(csv_path))

    assert [row["timestamp"] for row in engine.candles] == sorted(
        row["timestamp"] for row in candles
    )
    assert len(engine.client.history["BTCUSDT"]) == 3


def test_backtest_run_respects_warmup_and_uses_isolated_storage(tmp_path, monkeypatch):
    engine = BacktestEngine(
        "BTCUSDT",
        "",
        "",
        1000.0,
        storage_root=str(tmp_path),
        warmup_candles=100,
    )
    engine.load_candles(_build_candles(105))
    engine.setup_bot(
        {
            "mode": "long",
            "investment": 1000.0,
            "leverage": 2,
            "lower_price": 80.0,
            "upper_price": 130.0,
        }
    )

    calls = {"count": 0}

    def fake_run_bot_cycle(bot):
        calls["count"] += 1
        return bot

    monkeypatch.setattr(engine.bot_service, "run_bot_cycle", fake_run_bot_cycle)

    result = engine.run()

    assert calls["count"] == 5
    assert len(result["equity_curve"]) == 5
    assert result["trade_summary"]["closed_trade_count"] == 0
    for key, path in result["artifacts"].items():
        assert str(path).startswith(str(tmp_path)), key
    assert Path(result["artifacts"]["results"]).exists()


def test_mock_client_applies_market_fee_and_slippage():
    client = MockBybitClient(
        initial_balance=1000.0,
        taker_fee_bps=10.0,
        market_slippage_bps=50.0,
    )
    client.set_time(1700000000000)
    client.feed_candle("BTCUSDT", 100.0, 101.0, 99.0, 100.0, 1000.0)
    client.create_order("BTCUSDT", "Buy", 1.0, order_type="Market")
    client.create_order(
        "BTCUSDT",
        "Sell",
        1.0,
        order_type="Market",
        reduce_only=True,
        position_idx=1,
    )

    assert len(client.closed_pnl_records) == 1
    assert float(client.execution_records[0]["execPrice"]) > 100.0
    assert float(client.execution_records[1]["execPrice"]) < 100.0
    assert float(client.closed_pnl_records[0]["closeFee"]) > 0.0
    assert float(client.closed_pnl_records[0]["closedPnl"]) < 0.0


def test_backtest_reports_blocked_skip_decisions(tmp_path, monkeypatch):
    engine = BacktestEngine(
        "BTCUSDT",
        "",
        "",
        1000.0,
        storage_root=str(tmp_path),
        warmup_candles=100,
    )
    engine.load_candles(_build_candles(102))
    engine.setup_bot(
        {
            "mode": "long",
            "investment": 1000.0,
            "leverage": 2,
            "lower_price": 80.0,
            "upper_price": 130.0,
        }
    )
    bot_id = engine.test_bot["id"]
    state = {"recorded": False}

    def fake_run_bot_cycle(bot):
        if not state["recorded"]:
            ids = engine.trade_forensics_service.create_lifecycle_ids(
                bot_id=bot_id,
                symbol=engine.symbol,
                decision_type="initial_entry",
                side="Buy",
            )
            engine.trade_forensics_service.record_event(
                _decision_event_payload(engine, bot_id, ids, event_type="skip_blocked")
            )
            state["recorded"] = True
        return bot

    monkeypatch.setattr(engine.bot_service, "run_bot_cycle", fake_run_bot_cycle)

    result = engine.run()

    assert result["decision_summary"]["blocked_decisions"] == 1
    assert result["trade_summary"]["closed_trade_count"] == 0
    assert result["decision_stream"][-1]["status"] == "blocked"


def test_backtest_generates_lifecycle_outcomes_and_snapshots(tmp_path, monkeypatch):
    engine = BacktestEngine(
        "BTCUSDT",
        "",
        "",
        1000.0,
        storage_root=str(tmp_path),
        warmup_candles=100,
        taker_fee_bps=5.0,
        market_slippage_bps=10.0,
    )
    engine.load_candles(_build_candles(103, start_price=100.0, step=2.0))
    engine.setup_bot(
        {
            "mode": "long",
            "investment": 1000.0,
            "leverage": 2,
            "lower_price": 80.0,
            "upper_price": 160.0,
        }
    )
    bot_id = engine.test_bot["id"]
    state = {"step": 0, "ids": None, "started_at": None}

    def fake_run_bot_cycle(bot):
        if state["step"] == 0:
            ids = engine.trade_forensics_service.create_lifecycle_ids(
                bot_id=bot_id,
                symbol=engine.symbol,
                decision_type="initial_entry",
                side="Buy",
            )
            state["ids"] = ids
            state["started_at"] = engine.client._now_iso()
            engine.trade_forensics_service.record_event(
                _decision_event_payload(engine, bot_id, ids, event_type="decision")
            )
            ownership_snapshot = build_order_ownership_snapshot(
                bot,
                source="backtest_test",
                action="entry",
                forensic_decision_id=ids["forensic_decision_id"],
                forensic_trade_context_id=ids["trade_context_id"],
                forensic_decision_type="initial_entry",
                forensic_side="Buy",
                forensic_lifecycle_started_at=state["started_at"],
            )
            engine.client.create_order(
                engine.symbol,
                "Buy",
                1.0,
                order_type="Market",
                order_link_id="bot:test_entry",
                ownership_snapshot=ownership_snapshot,
            )
        elif state["step"] == 1:
            ownership_snapshot = build_order_ownership_snapshot(
                bot,
                source="backtest_test",
                action="reduce_only_close",
                close_reason="quick_profit",
                forensic_decision_id=state["ids"]["forensic_decision_id"],
                forensic_trade_context_id=state["ids"]["trade_context_id"],
                forensic_decision_type="initial_entry",
                forensic_side="Buy",
                forensic_lifecycle_started_at=state["started_at"],
            )
            engine.client.create_order(
                engine.symbol,
                "Sell",
                1.0,
                order_type="Market",
                reduce_only=True,
                position_idx=1,
                order_link_id="cls:testQP",
                ownership_snapshot=ownership_snapshot,
            )
        state["step"] += 1
        return bot

    monkeypatch.setattr(engine.bot_service, "run_bot_cycle", fake_run_bot_cycle)

    result = engine.run()

    assert result["trade_summary"]["closed_trade_count"] == 1
    assert result["decision_summary"]["executed_decisions"] >= 1
    assert result["decision_summary"]["closed_decisions"] >= 1
    assert result["by_exit_reason_summary"]["quick_profit"]["count"] == 1
    assert result["decision_stream"][-1]["status"] == "closed"
    assert result["trade_stream"][-1]["total_fee"] is not None
    assert Path(result["artifacts"]["trade_logs"]).exists()
    assert Path(result["artifacts"]["decision_snapshots"]).exists()
