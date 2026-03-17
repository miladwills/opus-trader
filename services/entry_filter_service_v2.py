"""
Bybit Control Center - Entry Filter Service V2

Enhanced regime classification with BTC correlation filter from mytrading parity.
"""

from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Threshold constants
MIN_LIQ_NOTIONAL_TURNOVER_USDT = 1_000_000  # Minimum 24h turnover (USDT) for liquidity

# Multi-Timeframe ADX Thresholds (NEW - from mytrading parity)
STRONG_ADX_MAIN = 25.0          # Main TF (15m) ADX threshold for strong trend
STRONG_ADX_HIGHER = 28.0        # Higher TF (1h) ADX threshold for strong trend

EXTREME_RSI_HIGH = 70.0         # RSI above this is overbought
EXTREME_RSI_LOW = 30.0          # RSI below this is oversold
LOW_ADX = 15.0                  # ADX below this indicates weak trend
LOW_BBW = 0.01                  # BBW below 1% indicates low volatility


class EntryFilterService:
    """
    Service for regime classification and entry filtering with BTC correlation support.
    """

    def __init__(
        self,
        indicator_service: Any,
        enable_btc_filter: bool = True,
        max_btc_correlation: float = 0.70,
        btc_strong_adx: float = 25.0,
        btc_lookback: int = 100
    ):
        """
        Initialize entry filter service.

        Args:
            indicator_service: IndicatorService for fetching market data
            enable_btc_filter: Enable BTC correlation filter
            max_btc_correlation: Max allowed correlation with BTC (0-1)
            btc_strong_adx: BTC ADX threshold for strong trend
            btc_lookback: Number of candles for correlation calculation
        """
        self.indicator_service = indicator_service
        self.enable_btc_filter = enable_btc_filter
        self.max_btc_correlation = max_btc_correlation
        self.btc_strong_adx = btc_strong_adx
        self.btc_lookback = btc_lookback

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
            Correlation coefficient (-1 to 1), or None if calculation fails
        """
        if not base_closes or not sym_closes:
            return None

        # Align lengths (use shorter length)
        n = min(len(base_closes), len(sym_closes))
        if n < 10:  # Need minimum data points
            return None

        x = base_closes[:n]
        y = sym_closes[:n]

        # Calculate means
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        # Calculate covariance and standard deviations
        covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n

        variance_x = sum((xi - mean_x) ** 2 for xi in x) / n
        variance_y = sum((yi - mean_y) ** 2 for yi in y) / n

        std_x = variance_x ** 0.5
        std_y = variance_y ** 0.5

        # Avoid division by zero
        if std_x == 0 or std_y == 0:
            return None

        correlation = covariance / (std_x * std_y)

        return round(correlation, 4)

    def _get_24h_turnover_usdt(self, symbol: str) -> Optional[float]:
        """
        Fetch 24h notional turnover (USDT) for a symbol from ticker data.

        Returns:
            24h turnover in USDT, or None if unavailable.
        """
        try:
            client = getattr(self.indicator_service, "client", None)
            if not client:
                return None

            ticker_resp = client.get_tickers(symbol=symbol)
            if not ticker_resp.get("success"):
                return None

            ticker_list = ticker_resp.get("data", {}).get("list", []) or []
            if not ticker_list:
                return None

            turnover_24h = ticker_list[0].get("turnover24h")
            if turnover_24h is None:
                return None

            turnover_value = float(turnover_24h)
            return turnover_value if turnover_value >= 0 else None

        except Exception:
            return None

    def classify_regime(
        self,
        symbol: str,
        indicators: Optional[Dict[str, Any]] = None,
        turnover_24h_usdt: Optional[float] = None,
        include_btc_filter: bool = True,
        use_multi_tf_adx: bool = True
    ) -> Dict[str, Any]:
        """
        Classify the market regime based on indicators with optional BTC correlation filter
        and multi-timeframe ADX analysis.

        Args:
            symbol: Trading symbol (e.g., "ETHUSDT")
            indicators: Optional dict containing rsi, adx, atr_pct, bbw_pct, volume, close (main TF)
            include_btc_filter: Whether to apply BTC correlation check
            use_multi_tf_adx: Whether to fetch and check higher timeframe ADX (1h)

        Returns:
            Dict with:
            - regime: str (illiquid, too_strong, choppy, trending, blocked)
            - reason: str (explanation)
            - btc_correlation: Optional[float] (if checked)
            - btc_adx: Optional[float] (if checked)
            - adx_main: Optional[float] (main TF ADX)
            - adx_higher: Optional[float] (higher TF ADX, if checked)
        """
        if indicators is None:
            indicators = self.indicator_service.compute_indicators(
                symbol=symbol,
                interval="15",
                limit=200,
            )

        volume = indicators.get("volume")
        if turnover_24h_usdt is None:
            turnover_24h_usdt = self._get_24h_turnover_usdt(symbol)
        liquidity_value = turnover_24h_usdt if turnover_24h_usdt is not None else volume
        liquidity_label = "turnover24h" if turnover_24h_usdt is not None else "volume_fallback"
        adx_main = indicators.get("adx")
        rsi = indicators.get("rsi")
        bbw_pct = indicators.get("bbw_pct")

        result = {
            "regime": "trending",
            "reason": "",
            "btc_correlation": None,
            "btc_adx": None,
            "adx_main": adx_main,
            "adx_higher": None,
            "liquidity_value": liquidity_value,
            "liquidity_label": liquidity_label,
        }

        # =====================================================================
        # CHECK 1: Liquidity filter
        # =====================================================================
        if (
            liquidity_value is None
            or liquidity_value < MIN_LIQ_NOTIONAL_TURNOVER_USDT
        ):
            result["regime"] = "illiquid"
            if turnover_24h_usdt is not None:
                result["reason"] = (
                    "Low liquidity "
                    f"(turnover24h: {turnover_24h_usdt:,.0f} < "
                    f"{MIN_LIQ_NOTIONAL_TURNOVER_USDT:,.0f})"
                )
            else:
                result["reason"] = (
                    "Low liquidity "
                    f"(turnover24h unavailable; volume fallback: {volume or 0:,.0f} < "
                    f"{MIN_LIQ_NOTIONAL_TURNOVER_USDT:,.0f})"
                )
            return result

        # =====================================================================
        # CHECK 2: Multi-Timeframe ADX Analysis (NEW - from mytrading parity)
        # =====================================================================
        # Fetch higher timeframe (1h) ADX for stronger trend detection
        adx_higher = None
        if use_multi_tf_adx:
            try:
                higher_indicators = self.indicator_service.compute_indicators(
                    symbol=symbol,
                    interval="60",  # 1h timeframe
                    limit=50  # Fewer candles needed for ADX
                )
                adx_higher = higher_indicators.get("adx")
                result["adx_higher"] = adx_higher

            except Exception as e:
                logger.warning(f"Failed to fetch higher TF ADX for {symbol}: {e}")

        # =====================================================================
        # CHECK 3: BTC Correlation Filter (from mytrading parity)
        # =====================================================================
        if include_btc_filter and self.enable_btc_filter and symbol != "BTCUSDT":
            try:
                # Fetch BTC indicators to check if BTC is in strong trend
                btc_indicators = self.indicator_service.compute_indicators(
                    symbol="BTCUSDT",
                    interval="15",
                    limit=self.btc_lookback
                )

                btc_adx = btc_indicators.get("adx")
                result["btc_adx"] = btc_adx

                # Only check correlation if BTC is in strong trend
                if btc_adx is not None and btc_adx >= self.btc_strong_adx:
                    # Fetch price data for correlation
                    btc_candles = self.indicator_service.get_ohlcv(
                        "BTCUSDT",
                        interval="15",
                        limit=self.btc_lookback
                    )
                    sym_candles = self.indicator_service.get_ohlcv(
                        symbol,
                        interval="15",
                        limit=self.btc_lookback
                    )

                    if btc_candles and sym_candles:
                        btc_closes = [c["close"] for c in btc_candles]
                        sym_closes = [c["close"] for c in sym_candles]

                        correlation = self._compute_correlation(btc_closes, sym_closes)
                        result["btc_correlation"] = correlation

                        # Block if correlation too high
                        if correlation is not None and abs(correlation) > self.max_btc_correlation:
                            result["regime"] = "blocked"
                            result["reason"] = (
                                f"High BTC correlation blocked: corr={correlation:.2f} > {self.max_btc_correlation:.2f}, "
                                f"BTC ADX={btc_adx:.1f} >= {self.btc_strong_adx:.1f} (strong trend)"
                            )
                            logger.debug(f"🚫 {symbol} blocked by BTC correlation filter: {result['reason']}")
                            return result

            except Exception as e:
                logger.warning(f"BTC correlation check failed for {symbol}: {e}")
                # Continue without BTC filter if it fails

        # =====================================================================
        # CHECK 4: Strong trend / extreme conditions filter (Multi-TF ADX)
        # =====================================================================
        reasons = []

        # Check BOTH timeframes for strong trend (mytrading parity)
        if adx_main is not None and adx_main >= STRONG_ADX_MAIN:
            reasons.append(f"ADX_15m={adx_main:.1f} >= {STRONG_ADX_MAIN}")

        if adx_higher is not None and adx_higher >= STRONG_ADX_HIGHER:
            reasons.append(f"ADX_1h={adx_higher:.1f} >= {STRONG_ADX_HIGHER}")

        if rsi is not None:
            if rsi >= EXTREME_RSI_HIGH:
                reasons.append(f"RSI={rsi:.1f} >= {EXTREME_RSI_HIGH} (overbought)")
            elif rsi <= EXTREME_RSI_LOW:
                reasons.append(f"RSI={rsi:.1f} <= {EXTREME_RSI_LOW} (oversold)")

        if reasons:
            result["regime"] = "too_strong"
            result["reason"] = "Strong trend/extreme: " + "; ".join(reasons)
            return result

        # =====================================================================
        # CHECK 5: Choppy/sideways detection (good for neutral grid)
        # =====================================================================
        # Use main TF ADX for choppy detection
        is_low_adx = adx_main is not None and adx_main <= LOW_ADX
        is_low_bbw = bbw_pct is not None and bbw_pct <= LOW_BBW

        if is_low_adx and is_low_bbw:
            result["regime"] = "choppy"
            result["reason"] = f"Sideways market (ADX_15m={adx_main:.1f} <= {LOW_ADX}, BBW={bbw_pct:.2%} <= {LOW_BBW:.0%})"
            return result

        if is_low_adx:
            result["regime"] = "choppy"
            result["reason"] = f"Weak trend (ADX_15m={adx_main:.1f} <= {LOW_ADX})"
            return result

        # =====================================================================
        # Default to trending (normal conditions)
        # =====================================================================
        adx_main_str = f"{adx_main:.1f}" if adx_main is not None else "N/A"
        adx_higher_str = f"{adx_higher:.1f}" if adx_higher is not None else "N/A"
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        bbw_str = f"{bbw_pct:.2%}" if bbw_pct is not None else "N/A"

        result["regime"] = "trending"
        result["reason"] = f"Normal conditions (ADX_15m={adx_main_str}, ADX_1h={adx_higher_str}, RSI={rsi_str}, BBW={bbw_str})"
        return result
