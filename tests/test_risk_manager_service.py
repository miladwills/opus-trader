import json
from datetime import datetime, timezone

import pytest

import config.strategy_config as strategy_config
from services.risk_manager_service import RiskManagerService


def test_update_equity_state_does_not_trigger_global_kill_switch_when_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(strategy_config, "GLOBAL_KILL_SWITCH_ENABLED", False)
    service = RiskManagerService(
        str(tmp_path / "risk_state.json"),
        max_bot_loss_pct=0.05,
        max_daily_loss_pct=0.08,
    )

    service.reset_daily_state(new_start_equity=100.0)
    state = service.update_equity_state(90.0)

    assert state["daily_loss_pct"] == pytest.approx(0.1)
    assert state["global_kill_switch"] is False
    assert state["kill_switch_triggered"] is False
    assert state["kill_switch_enforced"] is False


def test_update_equity_state_clears_stale_global_kill_switch_when_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(strategy_config, "GLOBAL_KILL_SWITCH_ENABLED", False)
    state_path = tmp_path / "risk_state.json"
    state_path.write_text(
        json.dumps(
            {
                "daily_start_equity": 100.0,
                "peak_equity": 100.0,
                "global_kill_switch": True,
                "kill_switch_triggered": True,
                "kill_switch_triggered_at": 123.0,
                "daily_loss_pct": 0.08,
                "last_daily_reset": datetime.now(timezone.utc).date().isoformat(),
                "per_bot": {},
                "symbol_daily": {},
                "kill_switch_enforced": True,
            }
        ),
        encoding="utf-8",
    )
    service = RiskManagerService(
        str(state_path),
        max_bot_loss_pct=0.05,
        max_daily_loss_pct=0.08,
    )

    state = service.update_equity_state(92.0)

    assert state["daily_loss_pct"] == pytest.approx(0.08)
    assert state["global_kill_switch"] is False
    assert state["kill_switch_triggered"] is False
    assert state["kill_switch_triggered_at"] is None
    assert state["kill_switch_enforced"] is False
