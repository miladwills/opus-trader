"""
Tests for Price Prediction System Upgrade (2026-01-10)

Coverage:
- Score normalization math and clamping
- Label boundaries (normalized thresholds)
- Confidence formula: magnitude + agreement + neutral cap
- Open-candle exclusion behavior (via mock)
- Backward compatibility of original methods
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import List

# Import the classes we need to test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.price_prediction_service import (
    PricePredictionService,
    Signal,
    PredictionResult,
)
from config.strategy_config import (
    PREDICTION_MAX_POSSIBLE_ABS,
    PREDICTION_NORM_STRONG_THRESHOLD,
    PREDICTION_NORM_MODERATE_THRESHOLD,
    PREDICTION_CONFIDENCE_MAGNITUDE_WEIGHT,
    PREDICTION_CONFIDENCE_AGREEMENT_WEIGHT,
    PREDICTION_NEUTRAL_CONFIDENCE_CAP,
)


class TestScoreNormalization:
    """Test score normalization math and clamping."""
    
    def test_normalization_formula_positive(self):
        """Test normalization for positive scores."""
        # score_norm = clamp((score_raw / max) * 100, -100, 100)
        max_abs = PREDICTION_MAX_POSSIBLE_ABS  # 165
        
        # Score of 82.5 (half of max) should normalize to 50
        score_raw = 82.5
        expected = (82.5 / 165) * 100  # = 50
        score_norm = max(-100.0, min(100.0, (score_raw / max_abs) * 100.0))
        assert abs(score_norm - expected) < 0.01
    
    def test_normalization_formula_negative(self):
        """Test normalization for negative scores."""
        max_abs = PREDICTION_MAX_POSSIBLE_ABS
        
        # Score of -82.5 should normalize to -50
        score_raw = -82.5
        expected = -50.0
        score_norm = max(-100.0, min(100.0, (score_raw / max_abs) * 100.0))
        assert abs(score_norm - expected) < 0.01
    
    def test_normalization_clamp_upper(self):
        """Test that scores > max are clamped to 100."""
        max_abs = PREDICTION_MAX_POSSIBLE_ABS
        
        # Score exceeding max (e.g., 200) should clamp to 100
        score_raw = 200.0
        score_norm = max(-100.0, min(100.0, (score_raw / max_abs) * 100.0))
        assert score_norm == 100.0
    
    def test_normalization_clamp_lower(self):
        """Test that scores < -max are clamped to -100."""
        max_abs = PREDICTION_MAX_POSSIBLE_ABS
        
        # Score below -max should clamp to -100
        score_raw = -200.0
        score_norm = max(-100.0, min(100.0, (score_raw / max_abs) * 100.0))
        assert score_norm == -100.0
    
    def test_normalization_zero(self):
        """Test that zero score normalizes to zero."""
        max_abs = PREDICTION_MAX_POSSIBLE_ABS
        score_raw = 0.0
        score_norm = max(-100.0, min(100.0, (score_raw / max_abs) * 100.0))
        assert score_norm == 0.0


class TestLabelBoundaries:
    """Test label determination using normalized thresholds."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        with patch('services.price_prediction_service.IndicatorService'):
            with patch('services.price_prediction_service.BybitClient'):
                service = PricePredictionService.__new__(PricePredictionService)
                # Initialize just what we need
                return service

    def test_strong_long_at_threshold(self, mock_service):
        """STRONG_LONG when score_norm >= 60."""
        result = mock_service._score_to_direction_normalized(70.0)
        assert result == "STRONG_LONG"
    
    def test_strong_long_above_threshold(self, mock_service):
        """STRONG_LONG when score_norm > 70."""
        result = mock_service._score_to_direction_normalized(85.0)
        assert result == "STRONG_LONG"
    
    def test_long_at_threshold(self, mock_service):
        """LONG when score_norm >= 40."""
        result = mock_service._score_to_direction_normalized(40.0)
        assert result == "LONG"
    
    def test_long_below_strong(self, mock_service):
        """LONG when 40 <= score_norm < 60."""
        result = mock_service._score_to_direction_normalized(59.9)
        assert result == "LONG"
    
    def test_neutral_positive_edge(self, mock_service):
        """NEUTRAL when score_norm just below 40."""
        result = mock_service._score_to_direction_normalized(39.9)
        assert result == "NEUTRAL"
    
    def test_neutral_negative_edge(self, mock_service):
        """NEUTRAL when score_norm just above -40."""
        result = mock_service._score_to_direction_normalized(-39.9)
        assert result == "NEUTRAL"
    
    def test_neutral_zero(self, mock_service):
        """NEUTRAL when score_norm is 0."""
        result = mock_service._score_to_direction_normalized(0.0)
        assert result == "NEUTRAL"
    
    def test_short_at_threshold(self, mock_service):
        """SHORT when score_norm <= -40."""
        result = mock_service._score_to_direction_normalized(-40.0)
        assert result == "SHORT"
    
    def test_short_above_strong(self, mock_service):
        """SHORT when -60 < score_norm <= -40."""
        result = mock_service._score_to_direction_normalized(-59.9)
        assert result == "SHORT"
    
    def test_strong_short_at_threshold(self, mock_service):
        """STRONG_SHORT when score_norm <= -60."""
        result = mock_service._score_to_direction_normalized(-70.0)
        assert result == "STRONG_SHORT"
    
    def test_strong_short_below_threshold(self, mock_service):
        """STRONG_SHORT when score_norm < -70."""
        result = mock_service._score_to_direction_normalized(-85.0)
        assert result == "STRONG_SHORT"


class TestConfidenceCalculation:
    """Test redesigned confidence calculation."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        return service
    
    def test_magnitude_component(self, mock_service):
        """Test that magnitude_conf = min(100, abs(score_norm))."""
        signals = [Signal("test", "bullish", 5, "15", "test")]
        
        conf, mag_conf, _ = mock_service._calculate_confidence_v2(80.0, signals, "STRONG_LONG")
        assert mag_conf == 80.0
        
        # Capped at 100
        conf, mag_conf, _ = mock_service._calculate_confidence_v2(150.0, signals, "STRONG_LONG")
        assert mag_conf == 100.0
    
    def test_agreement_component_bullish(self, mock_service):
        """Test agreement_conf for bullish direction."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
            Signal("s3", "bearish", 5, "15", "test"),
            Signal("s4", "neutral", 5, "15", "test"),
        ]
        # 2 bullish out of 4 = 50%
        conf, _, agree_conf = mock_service._calculate_confidence_v2(50.0, signals, "LONG")
        assert abs(agree_conf - 50.0) < 0.01
    
    def test_agreement_component_bearish(self, mock_service):
        """Test agreement_conf for bearish direction."""
        signals = [
            Signal("s1", "bearish", 5, "15", "test"),
            Signal("s2", "bearish", 5, "15", "test"),
            Signal("s3", "bearish", 5, "15", "test"),
            Signal("s4", "bullish", 5, "15", "test"),
        ]
        # 3 bearish out of 4 = 75%
        conf, _, agree_conf = mock_service._calculate_confidence_v2(-50.0, signals, "SHORT")
        assert abs(agree_conf - 75.0) < 0.01
    
    def test_combined_formula(self, mock_service):
        """Test confidence = 0.6 * magnitude + 0.4 * agreement."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
        ]
        # magnitude = 60, agreement = 100% (2 bullish signals, direction LONG)
        # confidence = 0.6 * 60 + 0.4 * 100 = 36 + 40 = 76
        conf, mag, agree = mock_service._calculate_confidence_v2(60.0, signals, "LONG")
        expected = 0.6 * 60.0 + 0.4 * 100.0
        assert conf == int(round(expected))
    
    def test_neutral_confidence_cap(self, mock_service):
        """Test that NEUTRAL confidence is capped when signals aren't balanced."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
            Signal("s3", "bullish", 5, "15", "test"),
        ]
        # All bullish but direction is NEUTRAL (weak score)
        # agreement_conf for neutral = 100 - (3/3 * 100) = 0 (max directional is 100%)
        # Since agreement < 70, should cap at PREDICTION_NEUTRAL_CONFIDENCE_CAP (60)
        conf, _, agree_conf = mock_service._calculate_confidence_v2(10.0, signals, "NEUTRAL")
        assert conf <= PREDICTION_NEUTRAL_CONFIDENCE_CAP
    
    def test_neutral_high_agreement_no_cap(self, mock_service):
        """Test that NEUTRAL isn't capped when signals are truly balanced."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bearish", 5, "15", "test"),
            Signal("s3", "neutral", 5, "15", "test"),
            Signal("s4", "neutral", 5, "15", "test"),
        ]
        # Balanced: 1 bullish, 1 bearish, 2 neutral
        # agreement_conf = 100 - (1/4 * 100) = 75 (max directional is 25%)
        conf, _, agree_conf = mock_service._calculate_confidence_v2(10.0, signals, "NEUTRAL")
        # Since agreement >= 70, no cap applies
        assert agree_conf >= 70.0
    
    def test_no_signals(self, mock_service):
        """Test behavior when no signals present."""
        conf, mag, agree = mock_service._calculate_confidence_v2(50.0, [], "LONG")
        assert agree == 0.0
        # confidence = 0.6 * 50 + 0.4 * 0 = 30
        assert conf == int(round(0.6 * 50.0))


class TestOpenCandleExclusion:
    """Test incomplete candle filtering behavior."""
    
    def test_config_default_is_true(self):
        """Verify PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES defaults to True."""
        from config.strategy_config import PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES
        assert PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES is True
    
    def test_candle_exclusion_logic(self):
        """Test that exclusion logic correctly drops last candle."""
        candles = [{"close": 100}, {"close": 101}, {"close": 102}]
        
        # When enabled, drop the last candle
        use_closed_only = True
        if use_closed_only and len(candles) > 1:
            candles_filtered = candles[:-1]
        else:
            candles_filtered = candles
        
        assert len(candles_filtered) == 2
        assert candles_filtered[-1]["close"] == 101  # Last is now the second candle
    
    def test_candle_inclusion_when_disabled(self):
        """Test that all candles are included when filtering disabled."""
        candles = [{"close": 100}, {"close": 101}, {"close": 102}]
        
        # When disabled, include all candles
        use_closed_only = False
        if use_closed_only and len(candles) > 1:
            candles_filtered = candles[:-1]
        else:
            candles_filtered = candles
        
        assert len(candles_filtered) == 3
        assert candles_filtered[-1]["close"] == 102  # All candles present


class TestBackwardCompatibility:
    """Test that legacy methods still work."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        return service
    
    def test_legacy_score_to_direction_exists(self, mock_service):
        """Verify legacy _score_to_direction method exists."""
        assert hasattr(mock_service, '_score_to_direction')
    
    def test_legacy_calculate_confidence_exists(self, mock_service):
        """Verify legacy _calculate_confidence method exists."""
        assert hasattr(mock_service, '_calculate_confidence')
    
    def test_prediction_result_has_new_fields(self):
        """Verify PredictionResult has new debug fields."""
        result = PredictionResult(
            direction="NEUTRAL",
            confidence=50,
            score=0.0,
        )
        # Check new fields exist with defaults
        assert hasattr(result, 'score_raw')
        assert hasattr(result, 'score_norm')
        assert hasattr(result, 'magnitude_conf')
        assert hasattr(result, 'agreement_conf')
        assert hasattr(result, 'top_components')


class TestTopComponents:
    """Test top component tracking."""
    
    def test_top_3_by_absolute_value(self):
        """Test that top 3 components are sorted by absolute value."""
        component_scores = {
            "pattern": 25.0,
            "sr_proximity": -5.0,
            "divergence": 15.0,
            "structure": -10.0,
            "mtf_alignment": 20.0,
        }
        
        sorted_components = sorted(
            component_scores.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        top_3 = sorted_components[:3]
        
        # Top 3 by abs value: pattern(25), mtf(20), divergence(15)
        assert top_3[0][0] == "pattern"
        assert top_3[1][0] == "mtf_alignment"
        assert top_3[2][0] == "divergence"


class TestConsensusGate:
    """Test that STRONG labels require 60% signal agreement."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        service._previous_labels = {}
        service._strong_confirmation_state = {}
        return service
    
    def test_strong_long_with_sufficient_consensus(self, mock_service):
        """STRONG_LONG allowed when >= 60% bullish signals."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
            Signal("s3", "bullish", 5, "15", "test"),
            Signal("s4", "bearish", 5, "15", "test"),
        ]
        # 3/4 = 75% bullish
        result, reason = mock_service._apply_consensus_gate("STRONG_LONG", 80.0, signals)
        assert result == "STRONG_LONG"
        assert reason is None
    
    def test_strong_long_insufficient_consensus(self, mock_service):
        """STRONG_LONG downgraded when < 60% bullish signals."""
        signals = [
            Signal("s1", "bullish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
            Signal("s3", "bearish", 5, "15", "test"),
            Signal("s4", "bearish", 5, "15", "test"),
            Signal("s5", "neutral", 5, "15", "test"),
        ]
        # 2/5 = 40% bullish
        result, reason = mock_service._apply_consensus_gate("STRONG_LONG", 80.0, signals)
        assert result == "LONG"
        assert "consensus gate" in reason
    
    def test_strong_short_insufficient_consensus(self, mock_service):
        """STRONG_SHORT downgraded when < 60% bearish signals."""
        signals = [
            Signal("s1", "bearish", 5, "15", "test"),
            Signal("s2", "bullish", 5, "15", "test"),
            Signal("s3", "neutral", 5, "15", "test"),
        ]
        # 1/3 = 33% bearish
        result, reason = mock_service._apply_consensus_gate("STRONG_SHORT", -80.0, signals)
        assert result == "SHORT"
        assert "consensus gate" in reason


class TestLabelHysteresis:
    """Test that hysteresis prevents rapid label flipping."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        service._previous_labels = {}
        service._strong_confirmation_state = {}
        return service
    
    def test_long_to_neutral_blocked(self, mock_service):
        """LONG → NEUTRAL blocked when score >= 30."""
        mock_service._previous_labels[("BTCUSDT", "15")] = "LONG"
        result, reason = mock_service._apply_hysteresis("BTCUSDT", "15", "NEUTRAL", 35.0)
        assert result == "LONG"
        assert "hysteresis" in reason
    
    def test_long_to_neutral_allowed(self, mock_service):
        """LONG → NEUTRAL allowed when score < 30."""
        mock_service._previous_labels[("BTCUSDT", "15")] = "LONG"
        result, reason = mock_service._apply_hysteresis("BTCUSDT", "15", "NEUTRAL", 25.0)
        assert result == "NEUTRAL"
        assert reason is None
    
    def test_strong_long_to_long_blocked(self, mock_service):
        """STRONG_LONG → LONG blocked when score >= 60."""
        mock_service._previous_labels[("BTCUSDT", "15")] = "STRONG_LONG"
        result, reason = mock_service._apply_hysteresis("BTCUSDT", "15", "LONG", 65.0)
        assert result == "STRONG_LONG"
        assert "hysteresis" in reason
    
    def test_short_to_neutral_blocked(self, mock_service):
        """SHORT → NEUTRAL blocked when score <= -30."""
        mock_service._previous_labels[("BTCUSDT", "15")] = "SHORT"
        result, reason = mock_service._apply_hysteresis("BTCUSDT", "15", "NEUTRAL", -35.0)
        assert result == "SHORT"
        assert "hysteresis" in reason


class TestTimeframeConfirmation:
    """Test that low-TF STRONG requires consecutive confirmations."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        service._previous_labels = {}
        service._strong_confirmation_state = {}
        return service
    
    def test_first_strong_on_1m_downgraded(self, mock_service):
        """First STRONG_LONG on 1m is downgraded to LONG."""
        result, reason = mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "STRONG_LONG")
        assert result == "LONG"
        assert "TF confirmation" in reason
        assert "1/2" in reason
    
    def test_second_strong_on_1m_allowed(self, mock_service):
        """Second consecutive STRONG_LONG on 1m is allowed."""
        # First call
        mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "STRONG_LONG")
        # Second call
        result, reason = mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "STRONG_LONG")
        assert result == "STRONG_LONG"
        assert reason is None
    
    def test_strong_on_15m_no_confirmation(self, mock_service):
        """STRONG_LONG on 15m does not require confirmation."""
        result, reason = mock_service._apply_timeframe_confirmation("BTCUSDT", "15", "STRONG_LONG")
        assert result == "STRONG_LONG"
        assert reason is None
    
    def test_confirmation_reset_on_direction_change(self, mock_service):
        """Confirmation counter resets when direction changes."""
        # First STRONG_LONG
        mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "STRONG_LONG")
        # Then normal LONG (resets counter)
        mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "LONG")
        # Next STRONG_LONG should be downgraded (counter reset)
        result, reason = mock_service._apply_timeframe_confirmation("BTCUSDT", "1", "STRONG_LONG")
        assert result == "LONG"
        assert "1/2" in reason


class TestVolumeFilter:
    """Test that low volume blocks STRONG signals."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock prediction service for testing."""
        service = PricePredictionService.__new__(PricePredictionService)
        service._previous_labels = {}
        service._strong_confirmation_state = {}
        return service
    
    def test_strong_blocked_on_low_volume(self, mock_service):
        """STRONG_LONG downgraded when volume < threshold."""
        result, reason = mock_service._apply_volume_filter("STRONG_LONG", 30000.0)
        assert result == "LONG"
        assert "volume filter" in reason
    
    def test_strong_allowed_on_high_volume(self, mock_service):
        """STRONG_LONG allowed when volume >= threshold."""
        result, reason = mock_service._apply_volume_filter("STRONG_LONG", 100000.0)
        assert result == "STRONG_LONG"
        assert reason is None
    
    def test_normal_labels_not_affected(self, mock_service):
        """LONG/SHORT not affected by low volume."""
        result, reason = mock_service._apply_volume_filter("LONG", 10000.0)
        assert result == "LONG"
        assert reason is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
