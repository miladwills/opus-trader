from pathlib import Path

import config.strategy_config as cfg


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_form_exposes_breakout_confirmed_entry_toggle():
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="bot-breakout-confirmed-entry-row"' in template_text
    assert 'id="bot-breakout-confirmed-entry"' in template_text
    assert "Breakout-confirmed entry" in template_text
    assert "Long/Short only" in template_text


def test_frontend_limits_breakout_confirmed_entry_to_directional_modes_and_saves_it():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'const BREAKOUT_CONFIRMED_SUPPORTED_MODES = new Set(["long", "short"]);' in js_text
    assert (
        'setBotOptionRowState("bot-breakout-confirmed-entry-row", breakoutConfirmedSupported, ['
        in js_text
    )
    assert "Breakout-confirmed entry: Long/Short only." in js_text
    assert 'breakout_confirmed_entry: "bot-breakout-confirmed-entry"' in js_text
    assert 'breakout_confirmed_entry: breakoutConfirmedSupported' in js_text
    assert "applyBotConfigBooleanFields(getEl, bot, booleanFields);" in js_text
    assert "breakout_confirmed_entry: breakoutConfirmedSupported" in js_text


def test_active_conservative_breakout_related_config_stays_unchanged_and_moderate_reference_exists():
    config_text = (ROOT / "config" / "strategy_config.py").read_text()

    assert cfg.SETUP_QUALITY_SCORE_ENABLED is True
    assert cfg.SETUP_QUALITY_MIN_ENTRY_SCORE == 42.0
    assert cfg.SETUP_QUALITY_MIN_BREAKOUT_SCORE == 50.0
    assert cfg.SETUP_QUALITY_LOGGING_ENABLED is True

    assert cfg.SR_AWARE_GRID_ENABLED is True
    assert cfg.SR_AWARE_GRID_MIN_LEVEL_DISTANCE_PCT == 0.0030
    assert cfg.SR_AWARE_GRID_SPACING_MULT_NEAR_ADVERSE_LEVEL == 1.15
    assert cfg.SR_AWARE_GRID_MAX_LEVEL_REDUCTION == 2
    assert cfg.SR_AWARE_GRID_LOGGING_ENABLED is True

    assert cfg.BREAKOUT_CONFIRMED_ENTRY_ENABLED is True
    assert cfg.BREAKOUT_CONFIRM_CANDLES == 1
    assert cfg.BREAKOUT_CONFIRM_BUFFER_PCT == 0.001
    assert cfg.BREAKOUT_CONFIRM_REQUIRE_VOLUME is True
    assert cfg.BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN is False
    assert cfg.BREAKOUT_CONFIRM_DIRECTIONAL_ONLY is True

    assert "Future moderate preset reference (inactive; do not enable automatically)" in config_text
    assert "# SETUP_QUALITY_MODERATE_SCORE_ENABLED = True" in config_text
    assert "# SETUP_QUALITY_MODERATE_MIN_ENTRY_SCORE = 50.0" in config_text
    assert "# SETUP_QUALITY_MODERATE_MIN_BREAKOUT_SCORE = 58.0" in config_text
    assert "# SR_AWARE_GRID_MODERATE_ENABLED = True" in config_text
    assert "# SR_AWARE_GRID_MODERATE_SPACING_MULT_NEAR_ADVERSE_LEVEL = 1.10" in config_text
    assert "# SR_AWARE_GRID_MODERATE_MAX_LEVEL_REDUCTION = 1" in config_text
    assert "# BREAKOUT_CONFIRM_MODERATE_ENABLED = True" in config_text
    assert "# BREAKOUT_CONFIRM_MODERATE_CANDLES = 1" in config_text
    assert "# BREAKOUT_CONFIRM_MODERATE_BUFFER_PCT = 0.0010" in config_text
    assert (
        "# Even under this moderate reference, keep per-bot breakout_confirmed_entry"
        in config_text
    )
