from services.grid_bot_service import GridBotService


def test_calculate_effective_capital_uses_reserve_adjusted_investment():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._calculate_auto_margin_reserve = (
        lambda bot, investment, available_equity=None: (25.0, 80.0)
    )

    effective_capital = service._calculate_effective_capital(
        bot={"symbol": "SOLUSDT"},
        investment=100.0,
        leverage=5.0,
        available_equity=42.0,
    )

    assert effective_capital == 400.0


def test_calculate_effective_capital_clamps_negative_inputs():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._calculate_auto_margin_reserve = (
        lambda bot, investment, available_equity=None: (0.0, -10.0)
    )

    effective_capital = service._calculate_effective_capital(
        bot={"symbol": "SOLUSDT"},
        investment=100.0,
        leverage=-3.0,
        available_equity=42.0,
    )

    assert effective_capital == 0.0
