from unittest.mock import Mock

from services.neutral_grid_service import NeutralGridService


class _FakeBotStorage:
    def save_runtime_bot(self, bot):
        return bot

    def save_bot(self, bot):
        return bot


def make_service():
    return NeutralGridService(
        bot_storage=_FakeBotStorage(),
        adaptive_config_service=Mock(),
    )


def test_volatility_gate_interprets_threshold_input_as_percent():
    service = make_service()

    bot = {
        "neutral_volatility_gate_enabled": True,
        "neutral_volatility_gate_threshold_pct": 5.0,
        "atr_5m_pct": 0.06,
    }

    assert service._is_volatility_gate_active(bot) is True


def test_volatility_gate_accepts_legacy_fraction_thresholds():
    service = make_service()

    bot = {
        "neutral_volatility_gate_enabled": True,
        "neutral_volatility_gate_threshold_pct": 0.05,
        "atr_5m_pct": 0.06,
    }

    assert service._is_volatility_gate_active(bot) is True


def test_volatility_gate_respects_disabled_toggle():
    service = make_service()

    bot = {
        "neutral_volatility_gate_enabled": False,
        "neutral_volatility_gate_threshold_pct": 5.0,
        "atr_5m_pct": 0.50,
    }

    assert service._is_volatility_gate_active(bot) is False
