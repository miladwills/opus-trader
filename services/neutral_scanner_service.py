"""
Bybit Control Center - Neutral Scanner Service

Scans symbols to find candidates suitable for neutral grid trading.
"""

from typing import List, Dict, Any, Optional, Set
import copy
import logging
import math
import time
from services.bybit_client import BybitClient
from services.indicator_service import IndicatorService
from services.entry_filter_service_v2 import EntryFilterService
from services.range_engine_service import RangeEngineService
from services.price_prediction_service import PricePredictionService
import config.strategy_config as cfg

logger = logging.getLogger(__name__)


class NeutralScannerService:
    """
    Service for scanning and scoring symbols for neutral grid trading.
    """

    # Scoring thresholds
    NEUTRAL_SCORE_THRESHOLD = 60.0
    _SYMBOL_CATALOG_TTL_SECONDS = 1800
    _SCAN_RESULT_TTL_SECONDS = 15
    _NON_TRADABLE_SYMBOLS = {"AUTO-PILOT"}

    def __init__(
        self,
        client: BybitClient,
        indicator_service: IndicatorService,
        range_engine: RangeEngineService,
        prediction_service: Optional[PricePredictionService] = None,
    ):
        """
        Initialize the neutral scanner service.

        Args:
            client: Initialized BybitClient instance
            indicator_service: IndicatorService for computing indicators
            range_engine: RangeEngineService for building ranges
            prediction_service: Optional PricePredictionService for conflict detection
        """
        self.client = client
        self.indicator_service = indicator_service
        self.range_engine = range_engine
        self.prediction_service = prediction_service or PricePredictionService(
            indicator_service, client
        )
        self.entry_filter_service = EntryFilterService(
            indicator_service=indicator_service,
            enable_btc_filter=cfg.ENABLE_BTC_CORRELATION_FILTER,
            max_btc_correlation=cfg.MAX_ALLOWED_CORRELATION_BTC,
            btc_strong_adx=cfg.BTC_STRONG_TREND_ADX_THRESHOLD,
            btc_lookback=cfg.BTC_CORRELATION_LOOKBACK,
        )
        self._symbol_catalog_cache: Dict[str, Any] = {
            "fetched_at": 0.0,
            "actual_symbols": set(),
            "alias_map": {},
        }
        self._scan_result_cache: Dict[Any, Dict[str, Any]] = {}

    @staticmethod
    def _normalize_symbol_text(symbol: Any) -> str:
        return str(symbol or "").strip().upper()

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _symbol_alias_variants(symbol: str, base_coin: Optional[str] = None) -> Set[str]:
        normalized_symbol = NeutralScannerService._normalize_symbol_text(symbol)
        variants: Set[str] = set()
        if normalized_symbol:
            variants.add(normalized_symbol)

        normalized_base = NeutralScannerService._normalize_symbol_text(base_coin)
        base_candidates = set()
        if normalized_symbol.endswith("USDT"):
            base_candidates.add(normalized_symbol[:-4])
        if normalized_base:
            base_candidates.add(normalized_base)

        for base in list(base_candidates):
            cleaned = str(base or "").strip().upper()
            if not cleaned:
                continue
            variants.add(f"{cleaned}USDT")
            stripped = cleaned.lstrip("0123456789")
            if stripped:
                variants.add(f"{stripped}USDT")

        return {variant for variant in variants if variant}

    def _get_symbol_catalog(self) -> Dict[str, Any]:
        now_ts = time.time()
        cache = self._symbol_catalog_cache
        actual_symbols = cache.get("actual_symbols")
        alias_map = cache.get("alias_map")
        fetched_at = float(cache.get("fetched_at") or 0.0)
        if (
            isinstance(actual_symbols, set)
            and actual_symbols
            and isinstance(alias_map, dict)
            and (now_ts - fetched_at) < self._SYMBOL_CATALOG_TTL_SECONDS
        ):
            return cache

        actual_symbols = set()
        alias_candidates: Dict[str, Set[str]] = {}
        cursor: Optional[str] = None
        seen_cursors = set()

        try:
            while True:
                response = self.client.get_instruments_info(
                    status="Trading",
                    limit=1000,
                    cursor=cursor,
                )
                if not response.get("success"):
                    logger.debug(
                        "Neutral scanner symbol catalog fetch failed: %s",
                        response.get("error"),
                    )
                    break

                data = response.get("data", {}) or {}
                for instrument in data.get("list", []) or []:
                    symbol = self._normalize_symbol_text(instrument.get("symbol"))
                    if not symbol:
                        continue
                    actual_symbols.add(symbol)
                    for alias in self._symbol_alias_variants(
                        symbol,
                        base_coin=instrument.get("baseCoin"),
                    ):
                        alias_candidates.setdefault(alias, set()).add(symbol)

                next_cursor = str(data.get("nextPageCursor") or "").strip()
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except Exception as exc:
            logger.debug("Neutral scanner symbol catalog fetch error: %s", exc)

        alias_map = {}
        for alias, matches in alias_candidates.items():
            sorted_matches = sorted(matches)
            if len(sorted_matches) == 1:
                alias_map[alias] = sorted_matches[0]

        self._symbol_catalog_cache = {
            "fetched_at": now_ts,
            "actual_symbols": actual_symbols,
            "alias_map": alias_map,
        }
        return self._symbol_catalog_cache

    def _resolve_scan_symbols(self, symbols: List[str]) -> List[str]:
        catalog = self._get_symbol_catalog()
        actual_symbols = catalog.get("actual_symbols") or set()
        alias_map = catalog.get("alias_map") or {}
        has_catalog = bool(actual_symbols)
        resolved_symbols: List[str] = []
        seen = set()

        for raw_symbol in symbols or []:
            symbol = self._normalize_symbol_text(raw_symbol)
            if not symbol or symbol in self._NON_TRADABLE_SYMBOLS:
                continue

            resolved = symbol
            if has_catalog:
                if symbol in actual_symbols:
                    resolved = symbol
                else:
                    resolved = alias_map.get(symbol)
                    if resolved:
                        logger.debug(
                            "Neutral scanner resolved alias %s -> %s",
                            symbol,
                            resolved,
                        )
                    else:
                        logger.debug(
                            "Neutral scanner skipped unresolved symbol %s",
                            symbol,
                        )
                        continue

            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_symbols.append(resolved)

        return resolved_symbols

    def _compute_correlation(
        self,
        base_closes: List[float],
        sym_closes: List[float],
    ) -> Optional[float]:
        """
        Compute Pearson correlation between two price series.

        Args:
            base_closes: Base asset close prices (e.g., BTCUSDT)
            sym_closes: Symbol close prices

        Returns:
            Correlation coefficient (-1 to 1), or None if insufficient data
        """
        # Align arrays to same length
        n = min(len(base_closes), len(sym_closes))

        if n < 10:
            return None

        # Use last n values
        x = base_closes[-n:]
        y = sym_closes[-n:]

        # Calculate means
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        # Calculate covariance and standard deviations
        covariance = 0.0
        var_x = 0.0
        var_y = 0.0

        for i in range(n):
            dx = x[i] - mean_x
            dy = y[i] - mean_y
            covariance += dx * dy
            var_x += dx * dx
            var_y += dy * dy

        # Check for zero variance
        if var_x == 0 or var_y == 0:
            return None

        std_x = math.sqrt(var_x)
        std_y = math.sqrt(var_y)

        if std_x == 0 or std_y == 0:
            return None

        correlation = covariance / (std_x * std_y)

        return round(correlation, 4)

    def _detect_trend_direction(
        self,
        indicators: Dict[str, Any],
    ) -> str:
        """
        Detect trend direction based on indicators.

        Args:
            indicators: Dict containing rsi, macd, ema values

        Returns:
            Trend direction: "uptrend", "downtrend", or "neutral"
        """
        bullish_signals = 0
        bearish_signals = 0

        # RSI-based trend detection (more sensitive thresholds)
        rsi = indicators.get("rsi")
        if rsi is not None:
            if rsi > 52:
                bullish_signals += 1
            elif rsi < 48:
                bearish_signals += 1

        # MACD-based trend detection (use macd_line key from indicator_service)
        macd = indicators.get("macd_line") or indicators.get("macd")
        macd_signal = indicators.get("macd_signal")
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                bullish_signals += 1
            elif macd < macd_signal:
                bearish_signals += 1

        # EMA-based trend detection (use ema_21 key from indicator_service)
        close = indicators.get("close")
        ema = (
            indicators.get("ema_21") or indicators.get("ema_9") or indicators.get("ema")
        )
        if close is not None and ema is not None:
            if close > ema * 1.001:  # 0.1% above EMA
                bullish_signals += 1
            elif close < ema * 0.999:  # 0.1% below EMA
                bearish_signals += 1

        # Candle pattern detection
        candle_pattern = indicators.get("candle_pattern")
        if candle_pattern:
            if "bullish" in candle_pattern.lower():
                bullish_signals += 1
            elif "bearish" in candle_pattern.lower():
                bearish_signals += 1

        # Determine trend direction
        if bullish_signals >= 2 and bullish_signals > bearish_signals:
            return "uptrend"
        elif bearish_signals >= 2 and bearish_signals > bullish_signals:
            return "downtrend"
        else:
            return "neutral"

    def _recommend_mode(
        self,
        neutral_score: float,
        regime: str,
        trend: str,
        rsi: Optional[float],
        adx: Optional[float],
        atr_pct: Optional[float],
        speed: str,
        prediction_score: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        price_change_24h_pct: Optional[float] = None,
        funding_rate: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Recommend trading mode based on market conditions.

        Args:
            prediction_score: Optional prediction score from PricePredictionService.
                              If negative while trend is uptrend (or positive while downtrend),
                              this indicates conflicting signals and will downgrade to neutral.
            prediction_direction: Optional direction from PricePredictionService.
                              STRONG_LONG, LONG, NEUTRAL, SHORT, STRONG_SHORT.
                              If NEUTRAL while trend is directional, indicates mixed signals.
            funding_rate: Optional current funding rate. Negative = shorts pay longs.

        Returns:
            Dict with recommended_mode, confidence (0-1), and reasoning
        """
        # Default
        mode = "neutral"
        confidence = 0.5
        reasoning = ""

        # "illiquid" regime = low volume, avoid scalping (needs liquidity)
        if regime == "illiquid":
            # Never recommend scalp for illiquid markets
            if trend == "uptrend" and adx and adx > 20:
                mode = "long"
                confidence = 0.5
                reasoning = (
                    "Illiquid market with uptrend - long with caution, avoid scalping"
                )
            elif trend == "downtrend" and adx and adx > 20:
                mode = "short"
                confidence = 0.5
                reasoning = "Illiquid market with downtrend - short with caution, avoid scalping"
            else:
                mode = "neutral"
                confidence = 0.35
                reasoning = "Illiquid market - neutral grid safer than scalping"
            return {
                "recommended_mode": mode,
                "mode_confidence": round(confidence, 2),
                "mode_reasoning": reasoning,
            }

        # "too_strong" regime = very strong momentum, risky for grids
        # But if there's a clear trend, follow it instead of scalping
        if regime == "too_strong":
            # First check if there's a clear trend - follow it
            if trend == "uptrend":
                mode = "long"
                confidence = 0.7
                reasoning = f"Strong upward momentum - long to ride the trend"
            elif trend == "downtrend":
                mode = "short"
                confidence = 0.7
                reasoning = f"Strong downward momentum - short to ride the trend"
            # No clear trend - use scalp
            elif adx and adx > 30:
                mode = "scalp_pnl"
                confidence = 0.8
                reasoning = f"Strong momentum (ADX {adx:.0f}) but no trend - scalp quick profits"
            elif atr_pct and atr_pct >= 0.02:
                mode = "scalp_pnl"
                confidence = 0.75
                reasoning = f"High volatility but no trend - scalp safer"
            else:
                mode = "scalp_pnl"
                confidence = 0.65
                reasoning = "Too strong but unclear direction - scalp safer"

        # Massive 24h move (>=10%) - grids are too risky regardless of current indicators
        # The 15m ADX/RSI may look calm after the move, but the coin is unstable
        elif price_change_24h_pct is not None and abs(price_change_24h_pct) >= 0.10:
            abs_change_str = f"{abs(price_change_24h_pct)*100:.1f}%"
            if trend == "uptrend":
                mode = "long"
                confidence = 0.6
                reasoning = f"Massive 24h move ({abs_change_str}) with uptrend - ride momentum"
            elif trend == "downtrend":
                mode = "short"
                confidence = 0.6
                reasoning = f"Massive 24h move ({abs_change_str}) with downtrend - follow correction"
            else:
                mode = "scalp_pnl"
                confidence = 0.7
                reasoning = f"Massive 24h move ({abs_change_str}), no clear trend - scalp safer than grid"

        # High volatility (ATR >= 2.5% or speed High) - but still respect trend
        elif speed == "High" or (atr_pct and atr_pct >= 0.025):
            atr_str = f"ATR {atr_pct * 100:.1f}%" if atr_pct else speed
            # If there's a clear trend, follow it even with high volatility
            if trend == "uptrend":
                mode = "long"
                confidence = 0.7
                reasoning = (
                    f"High volatility ({atr_str}) but uptrend - long with caution"
                )
            elif trend == "downtrend":
                mode = "short"
                confidence = 0.7
                reasoning = (
                    f"High volatility ({atr_str}) but downtrend - short with caution"
                )
            else:
                mode = "scalp_pnl"
                confidence = 0.8
                reasoning = (
                    f"High volatility ({atr_str}) no trend - scalp quick profits"
                )

        # Very high ADX (> 35) = strong trend, use scalp or directional
        elif adx and adx > 35:
            if trend == "uptrend" and rsi and rsi < 75:
                mode = "long"
                confidence = 0.7
                reasoning = f"Strong uptrend (ADX {adx:.0f}) - ride the trend"
            elif trend == "downtrend" and rsi and rsi > 25:
                mode = "short"
                confidence = 0.7
                reasoning = f"Strong downtrend (ADX {adx:.0f}) - short the trend"
            else:
                mode = "scalp_pnl"
                confidence = 0.7
                reasoning = f"Very strong trend (ADX {adx:.0f}) - scalp safer"

        # Good neutral conditions
        elif neutral_score >= 70 and regime == "choppy":
            mode = "neutral"
            confidence = 0.85
            reasoning = (
                f"Choppy market, score {neutral_score:.0f} - ideal for neutral grid"
            )

        # Strong uptrend
        elif trend == "uptrend" and adx and adx > 25:
            if rsi and rsi < 70:
                mode = "long"
                confidence = 0.75
                reasoning = f"Uptrend (ADX {adx:.0f}, RSI {rsi:.0f}) - ride the trend"
            else:
                mode = "scalp_pnl"
                confidence = 0.6
                reasoning = f"Uptrend but RSI {rsi:.0f} overbought - scalp safer"

        # Strong downtrend
        elif trend == "downtrend" and adx and adx > 25:
            if rsi and rsi > 30:
                mode = "short"
                confidence = 0.75
                reasoning = (
                    f"Downtrend (ADX {adx:.0f}, RSI {rsi:.0f}) - short the trend"
                )
            else:
                mode = "scalp_pnl"
                confidence = 0.6
                reasoning = f"Downtrend but RSI {rsi:.0f} oversold - scalp safer"

        # Trending regime with clear direction - follow the trend (only if ADX confirms strength)
        elif regime == "trending":
            # Require ADX >= 25 for long/short to match auto-direction thresholds
            if trend == "uptrend" and adx and adx >= 25:
                mode = "long"
                confidence = 0.6
                reasoning = f"Trending up (ADX {adx:.0f}) - long to follow direction"
            elif trend == "downtrend" and adx and adx >= 25:
                mode = "short"
                confidence = 0.6
                reasoning = f"Trending down (ADX {adx:.0f}) - short to follow direction"
            else:
                # Weak trend (ADX < 25) or no clear direction - recommend neutral
                adx_str = f"{adx:.0f}" if adx else "N/A"
                if neutral_score >= 60:
                    mode = "neutral"
                    confidence = 0.6
                    reasoning = f"Weak trend (ADX {adx_str} < 25), neutral score {neutral_score:.0f}"
                else:
                    mode = "neutral"
                    confidence = 0.5
                    reasoning = f"Weak trend (ADX {adx_str} < 25) - neutral safer"

        # Moderate neutral score (only if not trending)
        elif neutral_score >= 60:
            mode = "neutral"
            confidence = 0.65
            reasoning = f"Decent neutral score {neutral_score:.0f}"

        # Fallback
        else:
            mode = "neutral"
            confidence = 0.4
            reasoning = "Unclear conditions - neutral as fallback"

        # Conflict detection: If prediction contradicts the recommended direction,
        # downgrade to neutral. Treat "NEUTRAL" prediction as a soft signal only
        # when the score is weak.
        if mode in ("long", "short"):
            neutral_dir_score_threshold = 5
            # Check 1: Score-based conflict (threshold: -5 for long, +5 for short)
            if prediction_score is not None:
                if mode == "long" and prediction_score < -5:
                    mode = "neutral"
                    confidence = 0.5
                    reasoning = f"Uptrend detected but bearish prediction ({prediction_score:.0f}) - mixed signals, neutral safer"
                elif mode == "short" and prediction_score > 5:
                    mode = "neutral"
                    confidence = 0.5
                    reasoning = f"Downtrend detected but bullish prediction ({prediction_score:.0f}) - mixed signals, neutral safer"

            # Check 2: Direction-based conflict (prediction says NEUTRAL but we want long/short)
            # Only downgrade if the score is weak; strong scores can override NEUTRAL direction.
            if mode in ("long", "short") and prediction_direction == "NEUTRAL":
                if prediction_score is None or abs(prediction_score) < neutral_dir_score_threshold:
                    mode = "neutral"
                    confidence = 0.5
                    if prediction_score is None:
                        reasoning = (
                            "Trend detected but prediction is NEUTRAL - mixed signals, neutral safer"
                        )
                    else:
                        reasoning = (
                            f"Trend detected but prediction is NEUTRAL (score {prediction_score:.0f}) "
                            f"- mixed signals, neutral safer"
                        )

        # Funding rate direction bias — when neutral/indecisive, prefer the
        # side that EARNS funding payments (harvesting).
        # Only flip on significant funding AND trend must not contradict.
        if (
            funding_rate is not None
            and abs(funding_rate) > 0.001
            and mode in ("neutral", "neutral_classic_bybit")
        ):
            if funding_rate < 0 and trend != "downtrend":
                mode = "long"
                confidence = max(confidence, 0.45)
                reasoning += f" | Funding bias long ({funding_rate*100:+.4f}%)"
            elif funding_rate > 0 and trend != "uptrend":
                mode = "short"
                confidence = max(confidence, 0.45)
                reasoning += f" | Funding bias short ({funding_rate*100:+.4f}%)"

        return {
            "recommended_mode": mode,
            "mode_confidence": round(confidence, 2),
            "mode_reasoning": reasoning,
        }

    def _recommend_range_mode(
        self,
        recommended_mode: str,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
        btc_correlation: Optional[float],
        trend: str,
        adx: Optional[float] = None,
        prediction_score: Optional[float] = None,
        prediction_direction: Optional[str] = None,
    ) -> str:
        """
        Recommend range mode based on volatility and market conditions.

        Args:
            prediction_score: If provided, used to detect conflicting signals
            prediction_direction: If provided, used to detect conflicting signals

        Returns:
            Recommended range_mode: "fixed", "dynamic", or "trailing"
        """
        # Scalp always uses dynamic
        if recommended_mode == "scalp_pnl":
            return "dynamic"

        # Neutral classic is always fixed
        if recommended_mode == "neutral_classic_bybit":
            return "fixed"

        # Conflicting signals = dynamic range (prediction contradicts trend)
        # This handles cases where mode was downgraded to neutral due to conflicts
        if recommended_mode == "neutral" and trend in ("uptrend", "downtrend"):
            # Score-based conflict
            if prediction_score is not None:
                if (trend == "uptrend" and prediction_score < -5) or (
                    trend == "downtrend" and prediction_score > 5
                ):
                    return "dynamic"
            # Direction-based conflict (prediction is NEUTRAL but trend is directional)
            if prediction_direction == "NEUTRAL":
                return "dynamic"

        # High volatility = dynamic to adapt
        if atr_pct and atr_pct >= 0.03:
            return "dynamic"
        if bbw_pct and bbw_pct >= 0.06:
            return "dynamic"

        # Trending modes with clear direction = trailing (only if strong trend ADX >= 25)
        if (
            recommended_mode in ("long", "short")
            and trend in ("uptrend", "downtrend")
            and adx
            and adx >= 25
        ):
            return "trailing"

        # High BTC correlation in trending market = trailing
        if btc_correlation and abs(btc_correlation) > 0.7 and trend != "neutral":
            return "trailing"

        # Default for neutral/stable = fixed
        return "fixed"

    def _select_neutral_variant(
        self,
        adx: Optional[float],
        atr_pct: Optional[float],
    ) -> str:
        """
        Decide whether neutral should be classic (fixed) or dynamic based on ADX/ATR thresholds.

        Returns: "classic", "dynamic", or "neutral" (no strong preference).
        """
        if adx is not None and atr_pct is not None:
            if (
                adx <= cfg.AUTO_NEUTRAL_CLASSIC_ADX_MAX
                and atr_pct <= cfg.AUTO_NEUTRAL_CLASSIC_ATR_MAX
            ):
                return "classic"
            if adx >= cfg.AUTO_NEUTRAL_DYNAMIC_ADX_MIN or atr_pct >= cfg.AUTO_NEUTRAL_DYNAMIC_ATR_MIN:
                return "dynamic"
            return "neutral"

        if adx is not None:
            if adx <= cfg.AUTO_NEUTRAL_CLASSIC_ADX_MAX:
                return "classic"
            if adx >= cfg.AUTO_NEUTRAL_DYNAMIC_ADX_MIN:
                return "dynamic"
            return "neutral"

        if atr_pct is not None:
            if atr_pct <= cfg.AUTO_NEUTRAL_CLASSIC_ATR_MAX:
                return "classic"
            if atr_pct >= cfg.AUTO_NEUTRAL_DYNAMIC_ATR_MIN:
                return "dynamic"
            return "neutral"

        return "neutral"

    def _append_reason(self, base: str, extra: str) -> str:
        if base:
            return f"{base} | {extra}"
        return extra

    def _recommend_profile(
        self,
        volume_24h_usdt: Optional[float],
        atr_pct: Optional[float],
        speed: str,
    ) -> str:
        """
        Recommend risk profile based on liquidity and volatility.

        Returns:
            Recommended profile: "safe", "normal", or "aggressive"
        """
        # Low liquidity = safe
        if volume_24h_usdt and volume_24h_usdt < 5_000_000:
            return "safe"

        # Very high volatility = aggressive (wider ranges)
        if atr_pct and atr_pct > 0.05:
            return "aggressive"
        if speed == "High":
            return "aggressive"

        # Default
        return "normal"

    def _recommend_leverage(
        self,
        atr_pct: Optional[float],
        speed: str,
    ) -> int:
        """
        Recommend leverage based on volatility.

        Returns:
            Recommended leverage (integer)
        """
        if atr_pct is None:
            return 3  # Safe default

        if atr_pct >= 0.04 or speed == "High":
            return 2
        elif atr_pct >= 0.02 or speed == "Medium":
            return 3
        else:
            return 5  # Low volatility, can use higher leverage

    def _recommend_grid_levels(
        self,
        range_width_pct: float,
    ) -> int:
        """
        Recommend number of grid levels based on range width.

        Returns:
            Recommended number of grid levels (integer)
        """
        if range_width_pct <= 0:
            return 10

        # Baseline: ~0.6% per level
        base_step = 0.006
        suggested = int(range_width_pct / base_step)

        # Clamp between 8 and 20 for safety/fees
        return max(8, min(20, suggested))

    def _classify_speed(
        self,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
    ) -> str:
        """
        Classify volatility speed based on ATR% and BBW%.

        Args:
            atr_pct: ATR as percentage of price
            bbw_pct: Bollinger Band Width percentage

        Returns:
            Speed classification: "High", "Medium", or "Low"
        """
        # Use ATR% as primary volatility measure
        if atr_pct is not None:
            if atr_pct >= 0.03:  # 3%+
                return "High"
            elif atr_pct >= 0.015:  # 1.5% - 3%
                return "Medium"
            else:
                return "Low"

        # Fall back to BBW%
        if bbw_pct is not None:
            if bbw_pct >= 0.06:  # 6%+
                return "High"
            elif bbw_pct >= 0.03:  # 3% - 6%
                return "Medium"
            else:
                return "Low"

        return "Medium"  # Default

    def _format_velocity(self, velocity: Optional[float]) -> str:
        """
        Format velocity as a human-readable string.

        Args:
            velocity: Price velocity as decimal (e.g., 0.025 = 2.5%/hr)

        Returns:
            Formatted string like "+2.5%/hr" or "-1.8%/hr"
        """
        if velocity is None:
            return "-"

        pct = velocity * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%/hr"

    def _compute_neutral_score(
        self,
        regime: str,
        adx: Optional[float],
        rsi: Optional[float],
        bbw_pct: Optional[float],
        volume: Optional[float],
    ) -> float:
        """
        Compute a neutral trading suitability score (0-100).

        Higher scores indicate better suitability for neutral grid trading.

        Args:
            regime: Classified market regime
            adx: ADX indicator value
            rsi: RSI indicator value
            bbw_pct: Bollinger Band Width percentage
            volume: Trading volume

        Returns:
            Score from 0 to 100
        """
        score = 50.0  # Start at neutral

        # Regime-based adjustments
        if regime == "choppy":
            score += 30.0
        elif regime == "illiquid":
            score -= 40.0
        elif regime == "too_strong":
            score -= 25.0
        elif regime == "trending":
            score -= 10.0

        # ADX adjustments (lower is better for neutral)
        if adx is not None:
            if adx < 15:
                score += 15.0
            elif adx < 20:
                score += 10.0
            elif adx < 25:
                score += 5.0
            elif adx > 35:
                score -= 15.0
            elif adx > 30:
                score -= 10.0

        # RSI adjustments (closer to 50 is better)
        if rsi is not None:
            rsi_distance = abs(rsi - 50)
            if rsi_distance < 10:
                score += 10.0
            elif rsi_distance < 15:
                score += 5.0
            elif rsi_distance > 25:
                score -= 10.0

        # BBW adjustments (moderate volatility is good)
        if bbw_pct is not None:
            if 0.02 <= bbw_pct <= 0.05:
                score += 10.0
            elif bbw_pct < 0.01:
                score -= 5.0  # Too tight
            elif bbw_pct > 0.10:
                score -= 10.0  # Too volatile

        # Volume bonus
        if volume is not None and volume > 5_000_000:
            score += 5.0

        # Clamp to 0-100
        return max(0.0, min(100.0, round(score, 2)))

    def _calculate_smart_momentum_score(
        self,
        adx: Optional[float],
        rsi: Optional[float],
        volume: Optional[float],
        price_velocity: Optional[float],
        atr_pct: Optional[float],
        trend: str,
    ) -> Dict[str, Any]:
        """
        Calculate "Smart Momentum" score based on Audit Spec.

        Components (Total 85-100 depending on exact bonus scaling):
        1. Safety (RSI) - Max 30 pts
        2. Momentum (ADX) - Max 20 pts
        3. Volatility (ATR) - Max 20 pts
        4. Velocity (Price Change) - Max 15 pts

        Pump Risk: Velocity > 3% AND Volume < 5M
        """
        score = 0.0
        details = []
        is_safe = True
        pump_risk = False

        # Data validation
        if not all(
            [
                adx is not None,
                rsi is not None,
                volume is not None,
                price_velocity is not None,
                atr_pct is not None,
            ]
        ):
            return {"score": 0.0, "details": ["Missing data"], "pump_risk": False}

        # 1. Safety Component (RSI) (Max 30 pts)
        # Penalize < 30 or > 70. Optimal 45-65.
        if 45 <= rsi <= 65:
            score += 30
            details.append("RSI Optimal (+30)")
        elif 30 <= rsi <= 70:
            score += 15
            details.append("RSI Neutral (+15)")
        else:
            # Penalize extremes
            score -= 10
            details.append(f"RSI Extreme {rsi:.0f} (-10)")
            if rsi > 80:
                is_safe = False

        # 2. Momentum Component (ADX) (Max 20 pts)
        # Linear scaling, max score at ADX > 50.
        if adx > 50:
            score += 20
            details.append("ADX Max (+20)")
        elif adx > 20:
            pts = (adx - 20) / 30 * 20  # Map 20-50 to 0-20
            score += pts
            details.append(f"ADX {adx:.0f} (+{pts:.0f})")

        # 3. Volatility Component (ATR%) (Max 20 pts)
        # Penalize ATR% < 0.5% (Dead) or > 5% (Too Wild)
        if (
            cfg.SMART_MOMENTUM_OPTIMAL_ATR_MIN
            <= atr_pct
            <= cfg.SMART_MOMENTUM_OPTIMAL_ATR_MAX
        ):
            score += 20
            details.append("Volatility Optimal (+20)")
        elif atr_pct < cfg.SMART_MOMENTUM_OPTIMAL_ATR_MIN:
            score -= 10
            details.append("Volatility Low (-10)")
        else:  # > 5%
            score -= 20
            details.append("Volatility High (-20)")

        # 4. Velocity Component (Max 15 pts)
        # Rewards positive price velocity (0-2%/hr).
        if 0 < price_velocity <= cfg.SMART_MOMENTUM_OPTIMAL_VELOCITY_MAX:
            # Scale 0-2% to 0-15 pts
            pts = (price_velocity / cfg.SMART_MOMENTUM_OPTIMAL_VELOCITY_MAX) * 15
            score += pts
            details.append(f"Velocity +{price_velocity * 100:.1f}% (+{pts:.0f})")
        elif price_velocity > cfg.SMART_MOMENTUM_OPTIMAL_VELOCITY_MAX:
            score += 15  # Cap at 15
            details.append("Velocity Strong (+15)")

        # Pump Risk Check
        # Logic: price_velocity > 3.0 AND volume_24h < 5M
        if (
            price_velocity > cfg.SMART_MOMENTUM_PUMP_RISK_VELOCITY
            and volume < cfg.SMART_MOMENTUM_PUMP_RISK_VOLUME
        ):
            pump_risk = True
            score = 0  # Kill score
            details.append("PUMP RISK DETECTED")
            is_safe = False

        return {
            "score": max(0.0, min(100.0, score)),
            "details": details,
            "pump_risk": pump_risk,
            "is_safe": is_safe,
        }

    def _get_ticker_data(
        self,
        symbol: str,
        ticker_snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch ticker data including volume, funding rate, 24h change, and OI.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")

        Returns:
            Dict with volume_24h_usdt, funding_rate, price_change_24h_pct,
            last_price, open_interest_value
        """
        data = {
            "volume_24h_usdt": None,
            "funding_rate": None,
            "price_change_24h_pct": None,
            "last_price": None,
            "open_interest_value": None,
        }
        normalized_symbol = self._normalize_symbol_text(symbol)
        snapshot_row = (ticker_snapshot or {}).get(normalized_symbol)
        if snapshot_row:
            data.update(snapshot_row)
            return data
        try:
            ticker_resp = self.client.get_tickers(symbol=normalized_symbol or symbol)
            if ticker_resp.get("success"):
                ticker_list = ticker_resp.get("data", {}).get("list", [])
                if ticker_list:
                    t = ticker_list[0]
                    turnover_24h = t.get("turnover24h")
                    if turnover_24h:
                        data["volume_24h_usdt"] = float(turnover_24h)
                    fr = t.get("fundingRate")
                    if fr:
                        data["funding_rate"] = float(fr)
                    pct = t.get("price24hPcnt")
                    if pct:
                        data["price_change_24h_pct"] = float(pct)
                    lp = t.get("lastPrice")
                    if lp:
                        data["last_price"] = float(lp)
                    oiv = t.get("openInterestValue")
                    if oiv:
                        data["open_interest_value"] = float(oiv)
        except Exception:
            pass
        return data

    def _build_ticker_snapshot(
        self,
        symbols: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build a per-scan ticker snapshot with one bulk ticker request.

        Falls back to per-symbol lookups when the bulk response is unavailable
        or a specific symbol is missing from the snapshot.
        """
        requested = {
            self._normalize_symbol_text(symbol)
            for symbol in (symbols or [])
            if self._normalize_symbol_text(symbol)
        }
        if not requested:
            return {}

        snapshot: Dict[str, Dict[str, Any]] = {}
        stream_service = getattr(self.client, "stream_service", None)
        if stream_service is not None and hasattr(stream_service, "get_ticker_rows"):
            try:
                stream_rows = stream_service.get_ticker_rows(requested)
            except Exception:
                stream_rows = {}
            if not isinstance(stream_rows, dict):
                stream_rows = {}
            for symbol, ticker in (stream_rows or {}).items():
                snapshot[symbol] = {
                    "volume_24h_usdt": self._safe_float(ticker.get("turnover24h")),
                    "funding_rate": self._safe_float(ticker.get("fundingRate")),
                    "price_change_24h_pct": self._safe_float(ticker.get("price24hPcnt")),
                    "last_price": self._safe_float(ticker.get("lastPrice")),
                    "open_interest_value": self._safe_float(
                        ticker.get("openInterestValue")
                    ),
                }

        missing = requested.difference(snapshot.keys())
        if not missing:
            return snapshot

        try:
            ticker_resp = self.client.get_tickers()
            if not ticker_resp.get("success"):
                return snapshot

            ticker_list = (ticker_resp.get("data", {}) or {}).get("list", []) or []
            for ticker in ticker_list:
                symbol = self._normalize_symbol_text(ticker.get("symbol"))
                if symbol not in missing:
                    continue
                snapshot[symbol] = {
                    "volume_24h_usdt": self._safe_float(ticker.get("turnover24h")),
                    "funding_rate": self._safe_float(ticker.get("fundingRate")),
                    "price_change_24h_pct": self._safe_float(ticker.get("price24hPcnt")),
                    "last_price": self._safe_float(ticker.get("lastPrice")),
                    "open_interest_value": self._safe_float(
                        ticker.get("openInterestValue")
                    ),
                }
            return snapshot
        except Exception:
            return snapshot

    def _get_cached_scan_results(
        self,
        scan_symbols: List[str],
    ) -> Optional[List[Dict[str, Any]]]:
        cache = getattr(self, "_scan_result_cache", None)
        if not isinstance(cache, dict):
            self._scan_result_cache = {}
            cache = self._scan_result_cache

        cache_key = tuple(scan_symbols or [])
        if not cache_key:
            return None

        cached = cache.get(cache_key)
        if not cached:
            return None

        now_ts = time.time()
        if (now_ts - float(cached.get("ts") or 0.0)) > self._SCAN_RESULT_TTL_SECONDS:
            cache.pop(cache_key, None)
            return None

        return copy.deepcopy(cached.get("data") or [])

    def _store_scan_results(
        self,
        scan_symbols: List[str],
        results: List[Dict[str, Any]],
    ) -> None:
        cache = getattr(self, "_scan_result_cache", None)
        if not isinstance(cache, dict):
            self._scan_result_cache = {}
            cache = self._scan_result_cache

        cache_key = tuple(scan_symbols or [])
        if not cache_key:
            return

        cache[cache_key] = {
            "ts": time.time(),
            "data": copy.deepcopy(results),
        }

    def _get_24h_volume_usdt(self, symbol: str) -> Optional[float]:
        """Legacy wrapper — prefer _get_ticker_data() for full data."""
        return self._get_ticker_data(symbol).get("volume_24h_usdt")

    def _compute_entry_zone_analysis(
        self,
        adx: Optional[float],
        rsi: Optional[float],
        atr_pct: Optional[float],
        regime: str,
        trend: str,
        speed: str,
        neutral_score: float,
        smart_score: float,
        volume_24h_usdt: Optional[float],
        funding_rate: Optional[float],
        price_change_24h_pct: Optional[float],
        recommended_mode: str,
        recommended_range_mode: str,
        recommended_profile: str,
        recommended_leverage: int,
        recommended_grid_levels: int,
    ) -> Dict[str, Any]:
        """
        Compute an entry zone analysis verdict for a symbol.

        Returns a structured analysis with verdict, reasons, warnings,
        risk level, and best trading mode for current conditions.
        """
        reasons = []
        warnings = []
        score = 50  # Start neutral

        # --- ADX Analysis ---
        if adx is not None:
            if adx < 15:
                score += 15
                reasons.append(f"ADX {adx:.0f} → Flat range, ideal for neutral ✅")
            elif adx < 20:
                score += 10
                reasons.append(f"ADX {adx:.0f} → Range-bound ✅")
            elif adx < 25:
                score += 3
                reasons.append(f"ADX {adx:.0f} → Mild trend, acceptable")
            elif adx < 35:
                score -= 5
                warnings.append(f"ADX {adx:.0f} → Moderate trend, caution ⚠️")
            else:
                score -= 15
                warnings.append(f"ADX {adx:.0f} → Strong trend, risky for grids 🔴")

        # --- RSI Analysis ---
        if rsi is not None:
            if 40 <= rsi <= 60:
                score += 12
                reasons.append(f"RSI {rsi:.0f} → Neutral zone ✅")
            elif 30 <= rsi < 40:
                score += 3
                reasons.append(f"RSI {rsi:.0f} → Slightly oversold, watch for bounce")
            elif 60 < rsi <= 70:
                score += 3
                reasons.append(f"RSI {rsi:.0f} → Slightly overbought, watch for dip")
            elif rsi < 30:
                score -= 8
                warnings.append(f"RSI {rsi:.0f} → Oversold, potential reversal ⚠️")
            elif rsi > 70:
                score -= 8
                warnings.append(f"RSI {rsi:.0f} → Overbought, potential drop ⚠️")
            if rsi > 80:
                score -= 10
                warnings.append(f"RSI {rsi:.0f} → Extreme overbought 🔴")
            elif rsi < 20:
                score -= 10
                warnings.append(f"RSI {rsi:.0f} → Extreme oversold 🔴")

        # --- 24h Price Change ---
        if price_change_24h_pct is not None:
            abs_change = abs(price_change_24h_pct) * 100
            if abs_change < 3:
                score += 8
                reasons.append(f"24h change {price_change_24h_pct*100:+.1f}% → Stable ✅")
            elif abs_change < 5:
                score += 3
                reasons.append(f"24h change {price_change_24h_pct*100:+.1f}% → Normal movement")
            elif abs_change < 10:
                score -= 8
                warnings.append(f"24h change {price_change_24h_pct*100:+.1f}% → Big move, late entry risk ⚠️")
            else:
                score -= 18
                warnings.append(f"24h change {price_change_24h_pct*100:+.1f}% → Massive move, high risk 🔴")

        # --- Funding Rate ---
        if funding_rate is not None:
            abs_fr = abs(funding_rate) * 100
            if abs_fr < 0.01:
                score += 5
                reasons.append(f"Funding {funding_rate*100:+.4f}% → Balanced ✅")
            elif abs_fr < 0.03:
                score += 0
                reasons.append(f"Funding {funding_rate*100:+.4f}% → Normal")
            elif abs_fr < 0.05:
                score -= 5
                warnings.append(f"Funding {funding_rate*100:+.4f}% → Elevated, crowded trade ⚠️")
            else:
                score -= 12
                warnings.append(f"Funding {funding_rate*100:+.4f}% → Very high, squeeze risk 🔴")

        # --- Volume / Liquidity ---
        if volume_24h_usdt is not None:
            if volume_24h_usdt >= 50_000_000:
                score += 8
                reasons.append(f"Volume ${volume_24h_usdt/1e6:.0f}M → Excellent liquidity ✅")
            elif volume_24h_usdt >= 10_000_000:
                score += 5
                reasons.append(f"Volume ${volume_24h_usdt/1e6:.0f}M → Good liquidity ✅")
            elif volume_24h_usdt >= 1_000_000:
                score += 0
                reasons.append(f"Volume ${volume_24h_usdt/1e6:.1f}M → Acceptable")
            else:
                score -= 12
                warnings.append(f"Volume ${volume_24h_usdt/1e6:.2f}M → Low liquidity, wide spreads 🔴")

        # --- Regime ---
        if regime == "choppy":
            score += 8
            reasons.append("Market regime: Choppy → Perfect for grid ✅")
        elif regime == "trending":
            score -= 3
            reasons.append("Market regime: Trending → Follow trend with caution")
        elif regime == "too_strong":
            score -= 12
            warnings.append("Market regime: Too Strong → Avoid grids 🔴")
        elif regime == "illiquid":
            score -= 15
            warnings.append("Market regime: Illiquid → Dangerous for grids 🔴")

        # --- ATR / Speed ---
        if atr_pct is not None:
            if atr_pct < 0.01:
                score -= 3
                warnings.append(f"ATR {atr_pct*100:.2f}% → Very low movement, slow fills")
            elif atr_pct < 0.025:
                score += 5
                reasons.append(f"ATR {atr_pct*100:.2f}% → Healthy volatility ✅")
            elif atr_pct < 0.04:
                score += 0
                reasons.append(f"ATR {atr_pct*100:.2f}% → Moderate volatility")
            else:
                score -= 8
                warnings.append(f"ATR {atr_pct*100:.2f}% → High volatility ⚠️")

        # Clamp score
        score = max(0, min(100, score))

        # Determine verdict
        if score >= 65:
            verdict = "GOOD"
            risk_level = "LOW"
        elif score >= 40:
            verdict = "CAUTION"
            risk_level = "MEDIUM"
        else:
            verdict = "AVOID"
            risk_level = "HIGH"

        # Determine best mode for current conditions
        best_for = recommended_mode
        if best_for == "neutral_classic_bybit":
            best_for = "neutral_classic"

        return {
            "verdict": verdict,
            "score": round(score, 1),
            "confidence": round(min(1.0, score / 100), 2),
            "reasons": reasons,
            "warnings": warnings,
            "risk_level": risk_level,
            "best_for": best_for,
            "suggested_settings": {
                "mode": recommended_mode,
                "range_mode": recommended_range_mode,
                "profile": recommended_profile,
                "leverage": recommended_leverage,
                "grid_levels": recommended_grid_levels,
            },
        }

    def scan(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Scan symbols for neutral grid trading suitability.

        Args:
            symbols: List of symbol strings to scan

        Returns:
            List of scan results sorted by neutral_score descending
        """
        results = []
        scan_symbols = self._resolve_scan_symbols(symbols)
        if not scan_symbols:
            return results
        cached_results = self._get_cached_scan_results(scan_symbols)
        if cached_results is not None:
            return cached_results
        ticker_snapshot = self._build_ticker_snapshot(scan_symbols)

        # Fetch BTC closes for correlation calculation
        btc_candles = self.indicator_service.get_ohlcv(
            "BTCUSDT", interval="15", limit=200
        )
        btc_closes = [c["close"] for c in btc_candles] if btc_candles else []

        for symbol in scan_symbols:
            try:
                # Run prediction first so the largest 15m OHLCV pull can warm the
                # indicator cache for the lighter indicator and correlation reads.
                prediction_score = None
                prediction_direction = None
                try:
                    prediction = self.prediction_service.predict(symbol, timeframe="15")
                    if prediction:
                        prediction_score = prediction.score
                        prediction_direction = prediction.direction
                except Exception:
                    pass

                # Compute indicators
                indicators = self.indicator_service.compute_indicators(
                    symbol=symbol, interval="15", limit=200
                )

                # Reuse the same per-scan ticker row for regime, scoring, and output.
                ticker_data = self._get_ticker_data(
                    symbol,
                    ticker_snapshot=ticker_snapshot,
                )
                volume_24h_usdt = ticker_data["volume_24h_usdt"]
                funding_rate = ticker_data["funding_rate"]
                price_change_24h_pct = ticker_data["price_change_24h_pct"]
                volume = volume_24h_usdt  # Use USDT volume for scoring

                # Classify regime
                regime_info = self.entry_filter_service.classify_regime(
                    symbol=symbol,
                    indicators=indicators,
                    turnover_24h_usdt=volume_24h_usdt,
                )
                regime = regime_info["regime"]

                # Extract indicator values
                rsi = indicators.get("rsi")
                adx = indicators.get("adx")
                atr_pct = indicators.get("atr_pct")
                bbw_pct = indicators.get("bbw_pct")
                close = indicators.get("close")
                price_velocity = indicators.get("price_velocity")

                # Compute correlation with BTC
                btc_correlation = None
                if btc_closes and symbol != "BTCUSDT":
                    # Reuse the same limit as indicators (200) to maximize cache hits
                    sym_candles = self.indicator_service.get_ohlcv(
                        symbol, interval="15", limit=200
                    )
                    sym_closes = (
                        [c["close"] for c in sym_candles] if sym_candles else []
                    )
                    if sym_closes:
                        btc_correlation = self._compute_correlation(
                            btc_closes, sym_closes
                        )

                # Multi-timeframe confirmation (1h ADX)
                htf_adx = None
                try:
                    from config.strategy_config import (
                        AUTO_PILOT_HTF_CONFIRMATION_ENABLED,
                        AUTO_PILOT_HTF_INTERVAL,
                        AUTO_PILOT_HTF_TREND_ADX_THRESHOLD,
                        AUTO_PILOT_HTF_FLAT_ADX_THRESHOLD,
                    )
                    if AUTO_PILOT_HTF_CONFIRMATION_ENABLED:
                        htf_ind = self.indicator_service.compute_indicators(
                            symbol=symbol, interval=AUTO_PILOT_HTF_INTERVAL, limit=50
                        )
                        htf_adx = htf_ind.get("adx")
                except Exception:
                    pass

                # Classify speed
                speed = self._classify_speed(atr_pct, bbw_pct)

                # Compute neutral score
                neutral_score = self._compute_neutral_score(
                    regime=regime, adx=adx, rsi=rsi, bbw_pct=bbw_pct, volume=volume
                )

                # HTF score adjustments
                if htf_adx is not None:
                    if regime == "choppy" and htf_adx > AUTO_PILOT_HTF_TREND_ADX_THRESHOLD:
                        neutral_score -= 15  # 15m choppy but 1h trending — hidden trend
                    elif htf_adx < AUTO_PILOT_HTF_FLAT_ADX_THRESHOLD:
                        neutral_score += 5  # Both timeframes agree: truly flat

                # Compute Smart Momentum Score
                smart_data = self._calculate_smart_momentum_score(
                    adx=adx,
                    rsi=rsi,
                    volume=volume,
                    price_velocity=price_velocity,
                    atr_pct=atr_pct,
                    trend=self._detect_trend_direction(indicators),
                )

                # Detect trend direction (uptrend/downtrend/neutral)
                trend = self._detect_trend_direction(indicators)

                # Determine if neutral candidate
                is_neutral = (
                    regime == "choppy" and neutral_score >= self.NEUTRAL_SCORE_THRESHOLD
                )

                # Compute recommendations
                mode_rec = self._recommend_mode(
                    neutral_score=neutral_score,
                    regime=regime,
                    trend=trend,
                    rsi=rsi,
                    adx=adx,
                    atr_pct=atr_pct,
                    speed=speed,
                    prediction_score=prediction_score,
                    prediction_direction=prediction_direction,
                    price_change_24h_pct=price_change_24h_pct,
                    funding_rate=funding_rate,
                )
                recommended_mode = mode_rec["recommended_mode"]
                recommended_range_mode = self._recommend_range_mode(
                    recommended_mode=recommended_mode,
                    atr_pct=atr_pct,
                    bbw_pct=bbw_pct,
                    btc_correlation=btc_correlation,
                    trend=trend,
                    adx=adx,
                    prediction_score=prediction_score,
                    prediction_direction=prediction_direction,
                )

                # If neutral is recommended, pick classic vs dynamic using auto-neutral thresholds
                # BUT: if regime is "too_strong", neutral grids are dangerous — use scalp instead
                if recommended_mode == "neutral" and regime == "too_strong":
                    # Conflict detection downgraded directional→neutral, but regime is dangerous
                    recommended_mode = "scalp_pnl"
                    recommended_range_mode = "dynamic"
                    mode_rec["mode_reasoning"] = self._append_reason(
                        mode_rec.get("mode_reasoning", ""),
                        "Regime too_strong - neutral unsafe, using scalp_pnl instead",
                    )
                elif recommended_mode == "neutral":
                    neutral_variant = self._select_neutral_variant(adx, atr_pct)
                    if neutral_variant == "classic":
                        recommended_mode = "neutral_classic_bybit"
                        recommended_range_mode = "fixed"
                        mode_rec["mode_reasoning"] = self._append_reason(
                            mode_rec.get("mode_reasoning", ""),
                            "Auto-neutral: low ADX/ATR -> neutral classic (fixed)",
                        )
                    elif neutral_variant == "dynamic":
                        recommended_range_mode = "dynamic"
                        mode_rec["mode_reasoning"] = self._append_reason(
                            mode_rec.get("mode_reasoning", ""),
                            "Auto-neutral: elevated ADX/ATR -> neutral dynamic",
                        )

                # Build suggested range after mode recommendation so the bot form
                # matches the width floor the runtime will actually use.
                suggested_range = {"lower": 0.0, "upper": 0.0, "width_pct": 0.0}
                if close and close > 0:
                    range_settings = cfg.get_dynamic_range_settings(recommended_mode)
                    suggested_range = self.range_engine.build_neutral_range(
                        last_price=close,
                        atr_pct=atr_pct,
                        bbw_pct=bbw_pct,
                        width_floor_pct=range_settings.get("width_floor_pct"),
                    )

                recommended_profile = self._recommend_profile(
                    volume_24h_usdt=volume_24h_usdt,
                    atr_pct=atr_pct,
                    speed=speed,
                )
                recommended_leverage = self._recommend_leverage(atr_pct, speed)
                recommended_grid_levels = self._recommend_grid_levels(
                    suggested_range.get("width_pct", 0.06)
                )

                # Compute entry zone analysis
                entry_zone = self._compute_entry_zone_analysis(
                    adx=adx,
                    rsi=rsi,
                    atr_pct=atr_pct,
                    regime=regime,
                    trend=trend,
                    speed=speed,
                    neutral_score=neutral_score,
                    smart_score=smart_data["score"],
                    volume_24h_usdt=volume_24h_usdt,
                    funding_rate=funding_rate,
                    price_change_24h_pct=price_change_24h_pct,
                    recommended_mode=recommended_mode,
                    recommended_range_mode=recommended_range_mode,
                    recommended_profile=recommended_profile,
                    recommended_leverage=recommended_leverage,
                    recommended_grid_levels=recommended_grid_levels,
                )

                result = {
                    "symbol": symbol,
                    "rsi": rsi,
                    "adx": adx,
                    "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
                    "bbw_pct": round(bbw_pct, 4) if bbw_pct is not None else None,
                    "volume_24h_usdt": volume_24h_usdt,  # 24hr volume in USDT
                    "funding_rate": funding_rate,
                    "price_change_24h_pct": price_change_24h_pct,
                    "btc_correlation": btc_correlation,
                    "htf_adx": round(htf_adx, 2) if htf_adx is not None else None,
                    "neutral_score": neutral_score,
                    "regime": regime,
                    "trend": trend,  # uptrend/downtrend/neutral
                    "suggested_range": suggested_range,
                    "speed": speed,
                    "price_velocity": round(price_velocity, 6)
                    if price_velocity is not None
                    else None,
                    "velocity_display": self._format_velocity(price_velocity),
                    "neutral": is_neutral,
                    # Recommendations
                    "recommended_mode": recommended_mode,
                    "recommended_range_mode": recommended_range_mode,
                    "recommended_profile": recommended_profile,
                    "recommended_leverage": recommended_leverage,
                    "recommended_grid_levels": recommended_grid_levels,
                    "mode_confidence": mode_rec["mode_confidence"],
                    "mode_reasoning": mode_rec["mode_reasoning"],
                    "prediction_score": round(prediction_score, 1)
                    if prediction_score is not None
                    else None,
                    "prediction_direction": prediction_direction,
                    # Smart Momentum Data
                    "smart_score": smart_data["score"],
                    "smart_details": smart_data["details"],
                    "smart_pump_risk": smart_data["pump_risk"],
                    # Entry Zone Analysis
                    "entry_zone": entry_zone,
                }

                results.append(result)

            except Exception as scan_err:
                # Log first few failures for debugging
                if len(results) == 0:
                    import logging as _log
                    _log.getLogger(__name__).debug(f"[Scanner] {symbol} scan failed: {scan_err}")
                continue

        # Sort by neutral_score descending
        results.sort(key=lambda x: x["neutral_score"], reverse=True)
        self._store_scan_results(scan_symbols, results)

        return results
