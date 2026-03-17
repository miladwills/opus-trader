import config.strategy_config as cfg
from services.grid_bot_service import GridBotService


class DummyEntryGate:
    def __init__(self, structure):
        self._structure = structure

    def get_structure_context(self, symbol, current_price=None):
        return self._structure


def test_sr_aware_grid_overlay_adjusts_for_nearby_resistance(monkeypatch):
    monkeypatch.setattr(cfg, "SR_AWARE_GRID_ENABLED", True)
    monkeypatch.setattr(cfg, "SR_AWARE_GRID_MIN_LEVEL_DISTANCE_PCT", 0.003)
    monkeypatch.setattr(cfg, "SR_AWARE_GRID_SPACING_MULT_NEAR_ADVERSE_LEVEL", 1.25)
    monkeypatch.setattr(cfg, "SR_AWARE_GRID_MAX_LEVEL_REDUCTION", 3)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.02)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    service = GridBotService.__new__(GridBotService)
    bot = {"id": "bot-1"}
    result = GridBotService._apply_sr_aware_grid_overlay(
        service,
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=110.0,
        target_grid_levels=10,
        entry_gate=DummyEntryGate(
            {
                "nearest_support": {"price": 98.0, "strength": 6, "distance_pct": 0.02},
                "nearest_resistance": {
                    "price": 101.2,
                    "strength": 8,
                    "distance_pct": 0.012,
                },
            }
        ),
    )

    assert result["applied"] is True
    assert result["upper_price"] < 110.0
    assert result["spacing_mult"] > 1.0
    assert result["target_grid_levels"] < 10
    assert bot["sr_aware_grid_applied"] is True


def test_sr_aware_grid_overlay_disabled_preserves_legacy_bounds(monkeypatch):
    monkeypatch.setattr(cfg, "SR_AWARE_GRID_ENABLED", False)

    service = GridBotService.__new__(GridBotService)
    bot = {"id": "bot-1"}
    result = GridBotService._apply_sr_aware_grid_overlay(
        service,
        bot=bot,
        symbol="ETHUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=110.0,
        target_grid_levels=10,
        entry_gate=DummyEntryGate({}),
    )

    assert result["applied"] is False
    assert result["lower_price"] == 95.0
    assert result["upper_price"] == 110.0
    assert result["target_grid_levels"] == 10
    assert bot["sr_aware_grid_applied"] is False
