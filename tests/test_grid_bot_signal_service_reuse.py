from services.grid_bot_service import GridBotService


class _DummyIndicatorService:
    pass


def test_grid_bot_service_reuses_signal_services():
    service = GridBotService.__new__(GridBotService)
    service.indicator_service = _DummyIndicatorService()
    service._entry_gate_service = None
    service._neutral_suitability_service = None
    service._price_action_signal_service = None

    first_entry_gate = GridBotService._build_entry_gate_service(service)
    second_entry_gate = GridBotService._build_entry_gate_service(service)
    first_neutral_gate = GridBotService._build_neutral_suitability_service(service)
    second_neutral_gate = GridBotService._build_neutral_suitability_service(service)
    first_price_action = GridBotService._build_price_action_signal_service(service)
    second_price_action = GridBotService._build_price_action_signal_service(service)

    assert first_entry_gate is second_entry_gate
    assert first_neutral_gate is second_neutral_gate
    assert first_price_action is second_price_action
