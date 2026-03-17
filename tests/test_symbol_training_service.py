from datetime import datetime, timedelta, timezone
from typing import Optional

from services.symbol_training_service import SymbolTrainingService


def _make_trade(
    idx: int,
    *,
    symbol: str = "BTCUSDT",
    pnl: float = 0.1,
    time_value: Optional[datetime] = None,
    step: float | None = 0.004,
    open_cap: int | None = 8,
    investment: float = 10.0,
    mode: str = "neutral",
    range_mode: str = "dynamic",
) -> dict:
    trade_dt = time_value or (datetime.now(timezone.utc) - timedelta(minutes=idx))
    return {
        "id": f"trade-{idx}",
        "time": trade_dt.isoformat(),
        "symbol": symbol,
        "realized_pnl": pnl,
        "bot_investment": investment,
        "bot_mode": mode,
        "bot_range_mode": range_mode,
        "effective_step_pct": step,
        "runtime_open_order_cap_total": open_cap,
    }


def _make_service(tmp_path) -> SymbolTrainingService:
    return SymbolTrainingService(data_dir=str(tmp_path / "training"))


def test_default_training_structure_is_valid(tmp_path):
    service = _make_service(tmp_path)

    data = service.get_training_data("BTCUSDT")

    assert data["symbol"] == "BTCUSDT"
    assert data["phase"] == "collecting"
    assert data["total_trades"] == 0
    assert data["confidence_score"] == 0.0
    assert "trade_outcomes" in data
    assert "step_analysis" in data
    assert "open_cap_analysis" in data


def test_record_trade_outcome_dedupes_trade_ids(tmp_path):
    service = _make_service(tmp_path)
    trade = _make_trade(1, pnl=0.2)

    service.record_trade_outcome("BTCUSDT", trade)
    service.record_trade_outcome("BTCUSDT", trade)

    data = service.get_training_data("BTCUSDT")
    assert data["total_trades"] == 1
    assert len(data["processed_trade_ids"]) == 1
    assert len(data["recent_outcomes"]) == 1


def test_below_min_trades_stays_collecting_and_applies_no_adaptation(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(49):
        service.record_trade_outcome("BTCUSDT", _make_trade(idx, pnl=0.1))

    result = service.get_adapted_parameters(
        "BTCUSDT",
        {
            "effective_step_pct": 0.005,
            "runtime_open_order_cap_total": 10,
        },
    )

    assert result["training_status"] == "collecting"
    assert result["confidence"] == 0.0
    assert "effective_step_pct" not in result
    assert "runtime_open_order_cap_total" not in result


def test_one_hundred_trades_produces_learning_analysis(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(100):
        pnl = 0.2 if idx % 4 else -0.05
        step = 0.004 if idx % 3 else 0.006
        service.record_trade_outcome("BTCUSDT", _make_trade(idx, pnl=pnl, step=step))

    data = service.get_training_data("BTCUSDT")

    assert data["phase"] == "learning"
    assert data["total_trades"] == 100
    assert data["confidence_score"] > 0.0
    assert data["trade_outcomes"]["trades"] == 100
    assert data["step_analysis"]["samples"] > 0
    assert data["learned_parameters"].get("effective_step_pct") is not None


def test_step_guardrails_limit_extreme_learned_values(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(100):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(idx, pnl=0.25, step=0.04, open_cap=8),
        )

    result = service.get_adapted_parameters(
        "BTCUSDT",
        {
            "effective_step_pct": 0.005,
            "runtime_open_order_cap_total": 8,
        },
    )

    assert "effective_step_pct" in result
    assert result["effective_step_pct"] <= 0.005 * 1.25 + 1e-9


def test_blended_step_stays_between_base_and_learned(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(100):
        pnl = 0.2 if idx % 5 else -0.02
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(idx, pnl=pnl, step=0.0032, open_cap=8),
        )

    data = service.get_training_data("BTCUSDT")
    learned_step = data["learned_parameters"]["effective_step_pct"]
    base_step = 0.005
    result = service.get_adapted_parameters(
        "BTCUSDT",
        {
            "effective_step_pct": base_step,
            "runtime_open_order_cap_total": 8,
        },
    )

    assert "effective_step_pct" in result
    assert learned_step < result["effective_step_pct"] < base_step


def test_outlier_filter_excludes_extreme_trades_from_step_learning(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(55):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(idx, pnl=0.12, step=0.004, open_cap=8),
        )

    for idx in range(55, 60):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(idx, pnl=10.0, step=0.02, open_cap=12),
        )

    data = service.get_training_data("BTCUSDT")

    assert data["learned_parameters"]["effective_step_pct"] < 0.01


def test_exponential_decay_favors_recent_trades(tmp_path):
    service = _make_service(tmp_path)
    now = datetime.now(timezone.utc)

    for idx in range(30):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(
                idx,
                pnl=0.5,
                step=0.006,
                open_cap=10,
                time_value=now - timedelta(days=40, minutes=idx),
            ),
        )

    for idx in range(30, 60):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(
                idx,
                pnl=0.25,
                step=0.004,
                open_cap=6,
                time_value=now - timedelta(hours=idx),
            ),
        )

    data = service.get_training_data("BTCUSDT")

    assert data["learned_parameters"]["effective_step_pct"] < 0.005


def test_rebuild_from_trade_logs_handles_missing_optional_snapshots(tmp_path):
    service = _make_service(tmp_path)
    logs = [
        {
            "id": "legacy-1",
            "time": "2026-03-01T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "realized_pnl": 0.1,
            "bot_mode": "neutral",
        },
        {
            "id": "legacy-2",
            "time": "2026-03-02T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "realized_pnl": -0.03,
            "bot_mode": "neutral",
        },
    ]

    rebuilt = service.rebuild_from_trade_logs(logs)
    data = service.get_training_data("BTCUSDT")

    assert rebuilt["BTCUSDT"]["total_trades"] == 2
    assert data["total_trades"] == 2
    assert data["step_analysis"]["samples"] == 0


def test_session_and_day_are_derived_from_trade_timestamp(tmp_path):
    service = _make_service(tmp_path)
    saturday_trade = _make_trade(
        1,
        pnl=0.2,
        time_value=datetime(2026, 3, 7, 14, 0, tzinfo=timezone.utc),
    )

    service.record_trade_outcome("BTCUSDT", saturday_trade)
    data = service.get_training_data("BTCUSDT")
    outcome = data["recent_outcomes"][0]

    assert outcome["day_of_week"] == 5
    assert outcome["session_key"] != "unknown"


def test_open_cap_adaptation_stays_within_bounds(tmp_path):
    service = _make_service(tmp_path)

    for idx in range(100):
        service.record_trade_outcome(
            "BTCUSDT",
            _make_trade(idx, pnl=0.18, step=0.004, open_cap=4),
        )

    result = service.get_adapted_parameters(
        "BTCUSDT",
        {
            "effective_step_pct": 0.005,
            "runtime_open_order_cap_total": 10,
        },
    )

    assert "runtime_open_order_cap_total" in result
    assert 5 <= result["runtime_open_order_cap_total"] <= 11
    assert result["runtime_open_order_cap_total"] < 10
