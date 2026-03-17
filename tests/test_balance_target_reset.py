from unittest.mock import Mock

import pytest

from services.bot_manager_service import BotManagerService


def make_service():
    return BotManagerService(client=Mock(), bot_storage=Mock())


def test_balance_target_uses_absolute_threshold_before_first_hit():
    service = make_service()
    bot = {"auto_stop_target_usdt": 25.0}

    service._arm_auto_stop_target_for_session(bot, current_balance=20.0)

    assert bot["auto_stop_target_effective_usdt"] == pytest.approx(25.0)
    assert bot["auto_stop_target_session_base_usdt"] is None
    assert bot["auto_stop_armed"] is True
    assert bot["auto_stop_triggered"] is False


def test_balance_target_rearms_from_current_balance_after_hit():
    service = make_service()
    bot = {
        "auto_stop_target_usdt": 25.0,
        "auto_stop_triggered": True,
        "auto_stop_target_rearm_on_start": True,
        "auto_stop_hit_balance": 25.4,
    }

    service._arm_auto_stop_target_for_session(bot, current_balance=24.8)

    assert bot["auto_stop_target_session_base_usdt"] == pytest.approx(24.8)
    assert bot["auto_stop_target_effective_usdt"] == pytest.approx(49.8)
    assert bot["auto_stop_target_rearm_on_start"] is False
    assert bot["auto_stop_triggered"] is False
    assert bot["auto_stop_armed"] is True
