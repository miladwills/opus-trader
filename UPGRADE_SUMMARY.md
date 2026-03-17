# Price Prediction System Upgrade Summary

## Date: 2026-01-10

## Problem Statement

The current "Price Predictions" system has three critical issues:

1. **Unbounded Score**: The raw score can exceed ±165 but thresholds assume 0-100 scale, making `STRONG_*` labels too easy to trigger.
2. **Inflated Confidence**: Confidence saturates to 100% quickly because `min(100, abs(score))` alone doesn't represent actual signal agreement.
3. **Unstable Indicators**: Using the still-forming (incomplete) candle destabilizes RSI/ADX/ATR calculations, causing spurious STRONG signals.

---

## Current Implementation Analysis

### Component Max Scores (Unbounded Sum)

| Component | Max Score | Config Key |
|-----------|-----------|------------|
| Patterns | ±30 | `PREDICTION_PATTERN_MAX_SCORE` |
| S/R Proximity | ±15 | `PREDICTION_SR_MAX_SCORE` |
| Divergence | ±25 | `PREDICTION_DIVERGENCE_MAX_SCORE` |
| Trend Structure | ±15 | `PREDICTION_STRUCTURE_MAX_SCORE` |
| MTF Alignment | ±20 | `PREDICTION_MTF_MAX_SCORE` |
| Long-Term Trend | ±25 | `LONG_TERM_TREND_WEIGHT` |
| Trend Duration | ±15 | `TREND_DURATION_WEIGHT` |
| Higher TF Bias | ±20 | `HIGHER_TF_BIAS_WEIGHT` |
| **TOTAL** | **±165** | - |

### Current Label Thresholds (Raw Score)

```python
STRONG_LONG_THRESHOLD = 70   # >= 70
LONG_THRESHOLD = 35          # >= 35
NEUTRAL_BAND = 20            # within ±20
SHORT_THRESHOLD = -35        # <= -35
STRONG_SHORT_THRESHOLD = -70 # <= -70
```

**Problem**: With max possible score of 165, reaching 70 (42% of max) is too easy.

### Current Confidence Calculation

```python
base_confidence = min(100, abs(score))
if score > 0 and bullish_count >= 3:
    base_confidence += 10
```

**Problem**: A score of 90 gives 90% confidence even if only 2 of 8 components agree.

---

## Planned Changes

### A. Deterministic Score Normalization

**Formula**:
```python
MAX_POSSIBLE_ABS = 165  # Sum of all component max scores
score_norm = clamp((score_raw / MAX_POSSIBLE_ABS) * 100, -100, 100)
```

**Output**:
- `score_raw`: Original unbounded sum (for debugging)
- `score_norm`: Normalized to [-100, +100] range

### B. Recalibrated Label Thresholds (Using score_norm)

| Label | score_norm Range | Rationale |
|-------|------------------|-----------|
| STRONG_LONG | >= +70 | ~70% of max possible bullish evidence |
| LONG | +40 to +70 | Moderate bullish consensus |
| NEUTRAL | -40 to +40 | Insufficient directional evidence |
| SHORT | -70 to -40 | Moderate bearish consensus |
| STRONG_SHORT | <= -70 | ~70% of max possible bearish evidence |

### C. Redesigned Confidence Formula

```python
# Magnitude component (0-100): How strong is the signal?
magnitude_conf = min(100, abs(score_norm))

# Agreement component (0-100): What % of signals agree with direction?
if score_norm > 0:
    agreement_conf = (bullish_count / total_signals) * 100
elif score_norm < 0:
    agreement_conf = (bearish_count / total_signals) * 100
else:
    agreement_conf = (neutral_count / total_signals) * 100

# Combined confidence
confidence = round(0.6 * magnitude_conf + 0.4 * agreement_conf)

# Neutral cap: Don't show high confidence for neutral predictions
if label == "NEUTRAL":
    confidence = min(60, confidence)
```

### D. Incomplete Candle Filtering

**Config Flag**:
```python
PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES = True  # Default: exclude forming candle
```

**Implementation**:
- When enabled, drop the last candle from the OHLCV data before analysis
- Rationale: The last candle is still forming and its OHLC values change until close

### E. Debug Fields

New fields in `PredictionResult`:
- `score_raw`: Original unbounded score
- `score_norm`: Normalized score used for labeling
- `magnitude_conf`: Score magnitude contribution to confidence
- `agreement_conf`: Signal agreement contribution to confidence
- `top_components`: Top 3 contributing components by absolute value

### F. Compact Logging

Example output:
```
PRED BTCUSDT 15m raw=87.5 norm=53.0 label=LONG conf=62 top=[mtf_alignment:+20,pattern:+18,divergence:+15]
```

---

## Files Changed

1. `config/strategy_config.py` - New config flags
2. `services/price_prediction_service.py` - Core logic changes
3. `tests/test_price_prediction.py` - New test file (created)

## New Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES` | `True` | Exclude incomplete candle |
| `PREDICTION_MAX_POSSIBLE_ABS` | `165` | Max absolute score for normalization |
| `PREDICTION_NORM_STRONG_THRESHOLD` | `70` | score_norm threshold for STRONG_* |
| `PREDICTION_NORM_MODERATE_THRESHOLD` | `40` | score_norm threshold for LONG/SHORT |
| `PREDICTION_CONFIDENCE_MAGNITUDE_WEIGHT` | `0.6` | Weight for magnitude in confidence |
| `PREDICTION_CONFIDENCE_AGREEMENT_WEIGHT` | `0.4` | Weight for agreement in confidence |
| `PREDICTION_NEUTRAL_CONFIDENCE_CAP` | `60` | Max confidence for NEUTRAL label |

## How to Test

```bash
cd /var/www/opus_trader
pytest tests/test_price_prediction.py -v
```

## Backward Compatibility

- `PredictionResult.score` now returns `score_norm` (normalized) for label decisions
- `PredictionResult.score_raw` added for debugging/logging
- All existing callers using `.score` will get the normalized value
- The `.direction` and `.confidence` semantics remain the same (just more accurate)
