import config.strategy_config as cfg


def test_breakout_protection_defaults_are_enabled():
    assert cfg.BREAKOUT_NO_CHASE_FILTER_ENABLED is True
    assert cfg.BREAKOUT_INVALIDATION_EXIT_ENABLED is True
