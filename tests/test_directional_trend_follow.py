"""Tests for directional trend-following threshold alignment."""

from config.strategy_config import (
    get_dynamic_range_settings,
    EXPERIMENTAL_LONG_CONTINUATION_ADD_NEAR_BAND_PCT,
    ENTRY_READINESS_STRONG_CONTINUATION_EXTENSION_RATIO_MAX,
)


def test_long_short_recalc_threshold_equal():
    """LONG and SHORT recalc thresholds are now equal (both 0.004)."""
    long_settings = get_dynamic_range_settings("long")
    short_settings = get_dynamic_range_settings("short")
    assert long_settings["recalc_threshold_pct"] == short_settings["recalc_threshold_pct"]
    assert long_settings["recalc_threshold_pct"] == 0.004


def test_short_recalc_threshold_unchanged():
    """SHORT recalc threshold remains at 0.004."""
    short_settings = get_dynamic_range_settings("short")
    assert short_settings["recalc_threshold_pct"] == 0.004


def test_continuation_extension_ratio_unchanged():
    """Extension ratio max for strong continuation is unchanged at 0.45."""
    assert ENTRY_READINESS_STRONG_CONTINUATION_EXTENSION_RATIO_MAX == 0.45


def test_long_continuation_band_unchanged():
    """LONG continuation add band is unchanged at 0.003."""
    assert EXPERIMENTAL_LONG_CONTINUATION_ADD_NEAR_BAND_PCT == 0.003
