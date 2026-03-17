from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.bot_storage_service import BotStorageService
from services.performance_baseline_service import PerformanceBaselineService
from services.pnl_service import PnlService


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_per_bot_reset_only_counts_trades_since_baseline_and_preserves_raw_logs(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    before_reset = now - timedelta(hours=2)
    after_reset = now + timedelta(hours=2)

    bot_storage = BotStorageService(str(tmp_path / "storage" / "bots.json"))
    bot_storage.save_bot({"id": "bot-1", "symbol": "BTCUSDT", "status": "paused", "unrealized_pnl": 0.0})
    bot_storage.save_bot({"id": "bot-2", "symbol": "ETHUSDT", "status": "paused", "unrealized_pnl": 0.0})

    baseline_service = PerformanceBaselineService(
        file_path=str(tmp_path / "storage" / "performance_baselines.json"),
    )
    baseline_service.reset(scope="bot", bot_id="bot-1", snapshot={"reason": "test"})

    pnl_service = PnlService(
        SimpleNamespace(),
        str(tmp_path / "storage" / "trade_logs.json"),
        bot_storage=bot_storage,
        performance_baseline_service=baseline_service,
    )

    pnl_service._write_logs(
        [
            {"id": "t1", "bot_id": "bot-1", "symbol": "BTCUSDT", "time": _iso(before_reset), "realized_pnl": -10.0},
            {"id": "t2", "bot_id": "bot-1", "symbol": "BTCUSDT", "time": _iso(after_reset), "realized_pnl": 6.5},
            {"id": "t3", "bot_id": "bot-2", "symbol": "ETHUSDT", "time": _iso(before_reset), "realized_pnl": 3.0},
            {"id": "t4", "bot_id": "bot-2", "symbol": "ETHUSDT", "time": _iso(after_reset), "realized_pnl": 2.0},
        ]
    )

    pnl_service.update_bots_realized_pnl()

    bot_one = bot_storage.get_bot("bot-1")
    bot_two = bot_storage.get_bot("bot-2")
    assert bot_one["realized_pnl"] == 6.5
    assert bot_two["realized_pnl"] == 5.0
    assert len(pnl_service.get_log()) == 4


def test_global_reset_filters_trade_statistics_to_active_epoch(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    before_reset = now - timedelta(hours=2)
    after_reset = now + timedelta(hours=2)

    bot_storage = BotStorageService(str(tmp_path / "storage" / "bots.json"))
    baseline_service = PerformanceBaselineService(
        file_path=str(tmp_path / "storage" / "performance_baselines.json"),
    )
    baseline_service.reset(scope="global", snapshot={"reason": "test"})

    pnl_service = PnlService(
        SimpleNamespace(),
        str(tmp_path / "storage" / "trade_logs.json"),
        bot_storage=bot_storage,
        performance_baseline_service=baseline_service,
    )
    pnl_service._write_logs(
        [
            {"id": "g1", "bot_id": "bot-a", "symbol": "BTCUSDT", "time": _iso(before_reset), "realized_pnl": -8.0},
            {"id": "g2", "bot_id": "bot-a", "symbol": "BTCUSDT", "time": _iso(after_reset), "realized_pnl": 5.5},
            {"id": "g3", "bot_id": "bot-b", "symbol": "ETHUSDT", "time": _iso(after_reset), "realized_pnl": 1.5},
        ]
    )

    stats = pnl_service.get_trade_statistics("all", use_global_baseline=True)

    assert stats["total_trades"] == 2
    assert stats["net_pnl"] == 7.0
    assert stats["wins"] == 2
    assert stats["losses"] == 0
