import pytest

import config.strategy_config as cfg
from services.entry_gate_service import EntryGateService


def _service():
    return EntryGateService(indicator_service=None)


def test_classify_directional_signal_marks_early_entry_when_strong_and_not_extended():
    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 78.0,
            "band": "strong",
            "entry_allowed": True,
                "components": {
                    "price_action_context": {"direction": "bullish"},
                    "mode_fit": {"score": 6.0},
                    "indicators": {
                        "price_vs_ema_pct": 0.003,
                        "bb_position": 45.0,
                    },
                },
            },
        )

    assert signal["code"] == "early_entry"
    assert signal["preferred"] is True
    assert signal["late"] is False


def test_classify_directional_signal_marks_good_continuation_when_aligned_but_not_early():
    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 66.0,
            "band": "good",
            "entry_allowed": True,
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 4.0},
                "indicators": {
                    "price_vs_ema_pct": 0.011,
                    "bb_position": 79.0,
                },
            },
        },
    )

    assert signal["code"] == "good_continuation"
    assert signal["preferred"] is True
    assert signal["phase"] == "continuation"


def test_classify_directional_signal_keeps_strong_supported_continuation_armed_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_PROMOTION_ENABLED", False)

    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 75.0,
            "band": "strong",
            "entry_allowed": True,
                "components": {
                    "price_action_context": {"direction": "neutral"},
                    "mode_fit": {"score": 5.0},
                    "indicators": {
                        "price_vs_ema_pct": 0.006,
                        "bb_position": 40.0,
                    },
                },
            "component_points": {
                "price_action": 2.4,
                "supportive_structure": 5.2,
                "volume": 1.3,
                "mtf": 0.8,
            },
        },
    )

    assert signal["code"] == "continuation_entry"
    assert signal["preferred"] is False
    assert signal["late"] is False


def test_classify_directional_signal_promotes_strong_supported_continuation_earlier(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_PROMOTION_ENABLED", True)

    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 75.0,
            "band": "strong",
            "entry_allowed": True,
                "components": {
                    "price_action_context": {"direction": "neutral"},
                    "mode_fit": {"score": 5.0},
                    "indicators": {
                        "price_vs_ema_pct": 0.006,
                        "bb_position": 40.0,
                    },
                },
            "component_points": {
                "price_action": 2.4,
                "supportive_structure": 5.2,
                "volume": 1.3,
                "mtf": 0.8,
            },
        },
    )

    assert signal["code"] == "good_continuation"
    assert signal["preferred"] is True
    assert signal["late"] is False
    assert signal["experiment_tags"] == ["exp_strong_continuation_promotion_used"]
    assert signal["experiment_details"]["exp_strong_continuation_promotion_used"][
        "extension_ratio"
    ] == pytest.approx(0.4082, rel=1e-3)


def test_classify_directional_signal_keeps_borderline_continuation_armed():
    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 75.0,
            "band": "strong",
            "entry_allowed": True,
                "components": {
                    "price_action_context": {"direction": "neutral"},
                    "mode_fit": {"score": 3.1},
                    "indicators": {
                        "price_vs_ema_pct": 0.006,
                        "bb_position": 40.0,
                    },
                },
            "component_points": {
                "price_action": 1.2,
                "supportive_structure": 0.6,
                "volume": 0.4,
                "mtf": 0.5,
            },
        },
    )

    assert signal["code"] == "continuation_entry"
    assert signal["preferred"] is False
    assert signal["phase"] == "continuation"


def test_classify_directional_signal_marks_late_continuation_when_extension_is_high():
    signal = _service().classify_directional_entry_signal(
        mode="short",
        setup_quality={
            "score": 74.0,
            "band": "strong",
            "entry_allowed": True,
            "components": {
                "price_action_context": {"direction": "bearish"},
                "mode_fit": {"score": 6.0},
                "indicators": {
                    "price_vs_ema_pct": -0.019,
                    "bb_position": 7.0,
                },
            },
        },
    )

    assert signal["code"] == "late_continuation"
    assert signal["late"] is True
    assert signal["preferred"] is False


def test_classify_directional_signal_marks_confirmed_breakout_when_confirmation_is_fresh():
    signal = _service().classify_directional_entry_signal(
        mode="long",
        setup_quality={
            "score": 79.0,
            "band": "strong",
            "entry_allowed": True,
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 5.0},
                "indicators": {
                    "price_vs_ema_pct": 0.009,
                    "bb_position": 78.0,
                },
            },
        },
        breakout_confirmation={
            "required": True,
            "confirmed": True,
            "no_chase_extension_pct": 0.001,
        },
    )

    assert signal["code"] == "confirmed_breakout"
    assert signal["preferred"] is True
    assert signal["phase"] == "breakout"
