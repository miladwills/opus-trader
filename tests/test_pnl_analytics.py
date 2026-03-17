"""Tests for PnlService.get_analytics_data() extended analytics."""

import json
from datetime import datetime, timedelta, timezone

from services.pnl_service import PnlService
from services.symbol_pnl_service import SymbolPnlService


class StubClient:
    def get_closed_pnl(self, symbol=None, limit=100):
        return {"success": True, "data": {"list": []}}

    def get_wallet_balance(self):
        return {"success": True, "data": {"list": [{"coin": [{"coin": "USDT", "walletBalance": "100"}]}]}}

    def get_executions(self, symbol=None, limit=50, skip_cache=False):
        return {"success": True, "data": {"list": []}}


class StubBotStorage:
    def list_bots(self):
        return []


def _make_service(tmp_path):
    sps = SymbolPnlService(str(tmp_path / "symbol_pnl.json"))
    return PnlService(
        client=StubClient(),
        file_path=str(tmp_path / "trade_logs.json"),
        bot_storage=StubBotStorage(),
        symbol_pnl_service=sps,
    )


def _ts(days_ago=0, hours=12):
    """Return ISO timestamp N days ago at given hour."""
    dt = datetime.now(timezone.utc).replace(
        hour=hours, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)
    return dt.isoformat()


def _write_logs(svc, logs):
    with open(svc.file_path, "w") as f:
        json.dump(logs, f)


def _trade(pnl, days_ago=0, symbol="BTCUSDT", bot_id="bot-1", side="Sell"):
    return {
        "id": f"t-{pnl}-{days_ago}-{symbol}",
        "time": _ts(days_ago),
        "symbol": symbol,
        "side": side,
        "realized_pnl": pnl,
        "bot_id": bot_id,
        "bot_mode": "neutral",
    }


def test_analytics_basic_metrics(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(2.0, days_ago=3),   # win
        _trade(1.0, days_ago=2),   # win
        _trade(-4.0, days_ago=1),  # loss
        _trade(0.5, days_ago=0),   # win
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["total_trades"] == 4
    assert m["wins"] == 3
    assert m["losses"] == 1
    assert m["breakeven_trades"] == 0
    assert abs(m["net_pnl"] - (-0.5)) < 0.001
    assert abs(m["total_profit"] - 3.5) < 0.001
    assert abs(m["total_loss"] - 4.0) < 0.001
    assert m["win_rate"] == 75.0

    # avg_win = 3.5/3 = 1.1667, avg_loss = 4.0/1 = 4.0
    assert abs(m["avg_win"] - 1.1667) < 0.001
    assert abs(m["avg_loss"] - 4.0) < 0.001

    # expectancy = (0.75 * 1.1667) - (0.25 * 4.0) = 0.875 - 1.0 = -0.125
    assert m["expectancy"] < 0

    # payoff_ratio = 1.1667 / 4.0 = 0.29
    pr = m["payoff_ratio"]
    assert isinstance(pr, float) and abs(pr - 0.29) < 0.01

    # profit_factor = 3.5 / 4.0 = 0.875
    pf = m["profit_factor"]
    assert isinstance(pf, float) and abs(pf - 0.88) < 0.01


def test_analytics_streaks(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(1.0, days_ago=6),   # W
        _trade(1.0, days_ago=5),   # WW
        _trade(1.0, days_ago=4),   # WWW
        _trade(-1.0, days_ago=3),  # L
        _trade(-1.0, days_ago=2),  # LL
        _trade(1.0, days_ago=1),   # W
        _trade(1.0, days_ago=0),   # WW
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["longest_win_streak"] == 3
    assert m["longest_loss_streak"] == 2
    assert m["current_streak"] == 2  # ends with 2 wins


def test_analytics_best_worst_day(tmp_path):
    svc = _make_service(tmp_path)
    # Day 3: +2.0, Day 2: -5.0, Day 1: +1.0
    _write_logs(svc, [
        _trade(2.0, days_ago=3),
        _trade(-5.0, days_ago=2),
        _trade(1.0, days_ago=1),
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["best_day"]["value"] == 2.0
    assert m["worst_day"]["value"] == -5.0


def test_analytics_empty_logs(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["total_trades"] == 0
    assert m["wins"] == 0
    assert m["losses"] == 0
    assert m["net_pnl"] == 0
    assert m["expectancy"] == 0
    assert m["current_streak"] == 0
    assert m["max_drawdown"] == 0
    assert result["equity_curve"] == []
    assert result["daily_pnl"] == []


def test_analytics_symbol_filter(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(3.0, days_ago=2, symbol="BTCUSDT"),
        _trade(-1.0, days_ago=1, symbol="ETHUSDT"),
        _trade(1.0, days_ago=0, symbol="BTCUSDT"),
    ])
    result = svc.get_analytics_data("all", symbol="BTCUSDT")
    m = result["metrics"]

    assert m["total_trades"] == 2
    assert m["wins"] == 2
    assert m["losses"] == 0
    assert abs(m["net_pnl"] - 4.0) < 0.001

    # available_filters should still show all symbols from the period
    assert "BTCUSDT" in result["available_filters"]["symbols"]
    assert "ETHUSDT" in result["available_filters"]["symbols"]


def test_analytics_bot_filter(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(5.0, days_ago=2, bot_id="bot-A"),
        _trade(-2.0, days_ago=1, bot_id="bot-B"),
        _trade(1.0, days_ago=0, bot_id="bot-A"),
    ])
    result = svc.get_analytics_data("all", bot_id="bot-A")
    m = result["metrics"]

    assert m["total_trades"] == 2
    assert abs(m["net_pnl"] - 6.0) < 0.001

    # available_filters should show both bots
    bot_ids = [b["id"] for b in result["available_filters"]["bots"]]
    assert "bot-A" in bot_ids
    assert "bot-B" in bot_ids


def test_analytics_all_wins(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(1.0, days_ago=2),
        _trade(2.0, days_ago=1),
        _trade(3.0, days_ago=0),
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["wins"] == 3
    assert m["losses"] == 0
    assert m["profit_factor"] == "\u221e"
    assert m["payoff_ratio"] == "\u221e"
    assert m["longest_loss_streak"] == 0
    assert m["current_streak"] == 3
    assert m["max_drawdown"] == 0


def test_analytics_breakeven_handling(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(1.0, days_ago=2),
        _trade(0.0, days_ago=1),   # breakeven
        _trade(-1.0, days_ago=0),
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert m["total_trades"] == 3
    assert m["wins"] == 1
    assert m["losses"] == 1
    assert m["breakeven_trades"] == 1
    # Breakeven should not break streaks
    assert m["current_streak"] == -1  # ends on a loss


def test_analytics_drawdown_pct(tmp_path):
    svc = _make_service(tmp_path)
    # Cumulative: +10, +5 (dd=5 from peak 10, dd_pct = 50%)
    _write_logs(svc, [
        _trade(10.0, days_ago=1),
        _trade(-5.0, days_ago=0),
    ])
    result = svc.get_analytics_data("all")
    m = result["metrics"]

    assert abs(m["max_drawdown"] - 5.0) < 0.001
    assert abs(m["max_drawdown_pct"] - 50.0) < 0.01


def test_analytics_period_filter(tmp_path):
    svc = _make_service(tmp_path)
    _write_logs(svc, [
        _trade(10.0, days_ago=40),  # outside 30d
        _trade(-1.0, days_ago=5),   # within 7d and 30d
        _trade(2.0, days_ago=0),    # within all periods
    ])
    result_7d = svc.get_analytics_data("7d")
    result_30d = svc.get_analytics_data("30d")
    result_all = svc.get_analytics_data("all")

    assert result_7d["metrics"]["total_trades"] == 2
    assert result_30d["metrics"]["total_trades"] == 2
    assert result_all["metrics"]["total_trades"] == 3
