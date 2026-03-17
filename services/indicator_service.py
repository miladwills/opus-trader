"""
Bybit Control Center - Indicator Service

Fetches OHLCV data and computes technical indicators:
- RSI, ADX, ATR%, BBW%
- EMA/SMA crossovers
- MACD
- Volume analysis
- Candlestick patterns
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import math
import time
import threading
from config.strategy_config import INDICATOR_CACHE_TTL_1M, INDICATOR_CACHE_TTL_5M15M
from services.bybit_client import BybitClient


class IndicatorService:
    """
    Service for fetching market data and computing technical indicators.
    """

    def __init__(self, client: BybitClient):
        """
        Initialize the indicator service.

        Args:
            client: Initialized BybitClient instance
        """
        self.client = client
        self._ohlcv_cache: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        self._indicator_cache: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        self._stream_supported_intervals = {"1", "5", "15", "60"}
        self._canonical_transport_intervals = {"60", "240", "D"}
        self._canonical_transport_limit = 200
        self._fetch_lock = threading.RLock()
        self._inflight_ohlcv_fetches: Dict[Tuple[str, str, int], threading.Event] = {}

    def _normalize_interval(self, interval: str) -> str:
        if interval is None:
            return "15"
        interval_str = str(interval).strip().lower()
        if interval_str.endswith("m"):
            interval_str = interval_str[:-1]
        elif interval_str.endswith("h"):
            try:
                hours = int(interval_str[:-1])
                interval_str = str(hours * 60)
            except ValueError:
                return interval
        return interval_str

    def _get_cache_ttl(self, interval: str) -> int:
        normalized = self._normalize_interval(interval)
        if normalized == "1":
            return INDICATOR_CACHE_TTL_1M
        if normalized in ("5", "15"):
            return INDICATOR_CACHE_TTL_5M15M
        return INDICATOR_CACHE_TTL_5M15M

    def _get_stream_service(self):
        stream_service = getattr(self.client, "stream_service", None)
        return stream_service if stream_service is not None else None

    def _get_cached_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int,
        now: float,
        cache_ttl: int,
    ) -> List[Dict[str, Any]]:
        cache_key = (symbol, interval, limit)
        cached = self._ohlcv_cache.get(cache_key)
        if cached and (now - cached.get("ts", 0) <= cache_ttl):
            return cached.get("data", [])

        best_cached = None
        for (c_sym, c_int, c_lim), c_val in self._ohlcv_cache.items():
            if c_sym == symbol and c_int == interval and c_lim >= limit:
                if now - c_val.get("ts", 0) <= cache_ttl:
                    if best_cached is None or c_lim < best_cached[0]:
                        best_cached = (c_lim, c_val["data"])

        if best_cached:
            full_data = best_cached[1]
            return full_data[-limit:]
        return []

    def _fetch_ohlcv_from_api(
        self,
        symbol: str,
        interval: str,
        limit: int,
        now: float,
    ) -> List[Dict[str, Any]]:
        response = self.client.get_kline(symbol=symbol, interval=interval, limit=limit)
        if not response.get("success"):
            return []
        data = response.get("data", {})
        kline_list = data.get("list", [])
        if not kline_list:
            return []
        candles = self._parse_candles(kline_list)
        self._ohlcv_cache[(symbol, interval, limit)] = {"ts": now, "data": candles}
        self._seed_stream_ohlcv(symbol, interval, candles)
        return candles

    def _fetch_ohlcv_coalesced(
        self,
        symbol: str,
        interval: str,
        fetch_limit: int,
        requested_limit: int,
        now: float,
        cache_ttl: int,
    ) -> List[Dict[str, Any]]:
        fetch_key = (symbol, interval, fetch_limit)
        wait_event = None
        should_fetch = False

        with self._fetch_lock:
            cached = self._get_cached_ohlcv(
                symbol,
                interval,
                requested_limit,
                now,
                cache_ttl,
            )
            if cached:
                return cached
            wait_event = self._inflight_ohlcv_fetches.get(fetch_key)
            if wait_event is None:
                wait_event = threading.Event()
                self._inflight_ohlcv_fetches[fetch_key] = wait_event
                should_fetch = True

        if should_fetch:
            try:
                self._fetch_ohlcv_from_api(
                    symbol=symbol,
                    interval=interval,
                    limit=fetch_limit,
                    now=now,
                )
            finally:
                with self._fetch_lock:
                    event = self._inflight_ohlcv_fetches.pop(fetch_key, None)
                    if event is not None:
                        event.set()
        else:
            wait_event.wait(timeout=5.0)

        return self._get_cached_ohlcv(
            symbol,
            interval,
            requested_limit,
            self.client._get_now_ts(),
            cache_ttl,
        )

    def _parse_candles(self, kline_list: List[List[Any]]) -> List[Dict[str, Any]]:
        candles = []
        for kline in kline_list:
            try:
                open_time_ms = int(kline[0])
                open_time = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)

                candle = {
                    "open_time": open_time,
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                }
                if len(kline) > 6:
                    candle["turnover"] = float(kline[6] or 0)
                candles.append(candle)
            except (IndexError, ValueError, TypeError):
                continue

        candles.reverse()
        return candles

    def _get_stream_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        if interval not in self._stream_supported_intervals:
            return []
        stream_service = self._get_stream_service()
        if not stream_service or not hasattr(stream_service, "get_kline_response"):
            return []
        try:
            response = stream_service.get_kline_response(
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
        except Exception:
            return []
        if not response or not response.get("success"):
            return []
        data = response.get("data", {})
        kline_list = data.get("list", [])
        return self._parse_candles(kline_list)

    def _seed_stream_ohlcv(
        self,
        symbol: str,
        interval: str,
        candles: List[Dict[str, Any]],
    ) -> None:
        if interval not in self._stream_supported_intervals:
            return
        stream_service = self._get_stream_service()
        if not stream_service or not hasattr(stream_service, "seed_kline_snapshot"):
            return
        try:
            stream_service.seed_kline_snapshot(symbol, interval, candles)
        except Exception:
            return

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "15",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV candle data from Bybit with smart caching.
        Reuses cached data from larger limits if available.
        """
        normalized_interval = self._normalize_interval(interval)
        now = self.client._get_now_ts()
        cache_ttl = self._get_cache_ttl(normalized_interval)

        stream_candles = self._get_stream_ohlcv(symbol, normalized_interval, limit)
        if stream_candles:
            cache_key = (symbol, normalized_interval, limit)
            self._ohlcv_cache[cache_key] = {"ts": now, "data": stream_candles}
            return stream_candles

        cached = self._get_cached_ohlcv(
            symbol,
            normalized_interval,
            limit,
            now,
            cache_ttl,
        )
        if cached:
            return cached

        fetch_limit = limit
        if (
            normalized_interval in self._canonical_transport_intervals
            and limit <= self._canonical_transport_limit
        ):
            fetch_limit = self._canonical_transport_limit

        return self._fetch_ohlcv_coalesced(
            symbol=symbol,
            interval=normalized_interval,
            fetch_limit=fetch_limit,
            requested_limit=limit,
            now=now,
            cache_ttl=cache_ttl,
        )

    def compute_indicators(
        self,
        symbol: str,
        interval: str = "15",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """
        Compute all technical indicators for a symbol with smart caching.
        Reuses cached indicators from larger limits if available.
        """
        normalized_interval = self._normalize_interval(interval)
        now = self.client._get_now_ts()
        cache_ttl = self._get_cache_ttl(normalized_interval)

        # 1. Direct hit check
        cache_key = (symbol, normalized_interval, limit)
        cached = self._indicator_cache.get(cache_key)
        if cached and (now - cached.get("ts", 0) <= cache_ttl):
            return cached.get("data", {})

        # 2. Smart reuse: Any valid larger limit for this (symbol, interval)
        # provides the same latest-candle indicators.
        best_cached = None
        for (c_sym, c_int, c_lim), c_val in self._indicator_cache.items():
            if c_sym == symbol and c_int == normalized_interval and c_lim >= limit:
                if now - c_val.get("ts", 0) <= cache_ttl:
                    if best_cached is None or c_lim < best_cached[0]:
                        best_cached = (c_lim, c_val["data"])

        if best_cached:
            return best_cached[1]

        # 3. Cache miss: Compute indicators
        result = {
            # Basic
            "rsi": None,
            "adx": None,
            "atr_pct": None,
            "bbw_pct": None,
            "close": None,
            "volume": None,
            # EMA/SMA
            "ema_9": None,
            "ema_21": None,
            "sma_50": None,
            "ema_slope": None,  # EMA21 slope (% change)
            "ema_cross": None,  # "bullish", "bearish", or None
            "price_vs_ema": None,  # "above", "below", or None
            # MACD
            "macd_line": None,
            "macd_signal": None,
            "macd_histogram": None,
            "macd_cross": None,  # "bullish", "bearish", or None
            # Volume
            "volume_sma": None,
            "volume_ratio": None,  # Current volume / SMA volume
            "volume_trend": None,  # "high", "normal", "low"
            # Candlestick patterns
            "candle_pattern": None,  # Pattern name or None
            "candle_signal": None,  # "bullish", "bearish", or None
            # Price velocity
            "price_velocity": None,  # %/hr based on linear regression slope
        }

        candles = self.get_ohlcv(symbol, normalized_interval, limit)

        if not candles:
            return result

        # Extract OHLCV arrays
        opens = [c["open"] for c in candles]
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]

        # Set close and volume
        if closes:
            result["close"] = closes[-1]
        if volumes:
            result["volume"] = sum(volumes[-24:]) if len(volumes) >= 24 else sum(volumes)

        # Compute RSI (14-period)
        if len(closes) >= 15:
            result["rsi"] = self._compute_rsi(closes, period=14)

        # Compute ADX (14-period)
        if len(closes) >= 28:
            result["adx"] = self._compute_adx(highs, lows, closes, period=14)

        # Compute ATR% (14-period)
        if len(closes) >= 15:
            atr = self._compute_atr(highs, lows, closes, period=14)
            if atr is not None and result["close"] and result["close"] > 0:
                result["atr_pct"] = atr / result["close"]

        # Compute BBW% (20-period)
        if len(closes) >= 20:
            result["bbw_pct"] = self._compute_bbw(closes, period=20, std_dev=2.0)

        # Compute EMAs and SMAs
        if len(closes) >= 9:
            result["ema_9"] = self._compute_ema(closes, period=9)
        if len(closes) >= 21:
            result["ema_21"] = self._compute_ema(closes, period=21)
            ema_21_prev = self._compute_ema(closes[:-1], period=21) if len(closes) > 21 else None
            if ema_21_prev and ema_21_prev != 0:
                result["ema_slope"] = (result["ema_21"] - ema_21_prev) / ema_21_prev
        if len(closes) >= 50:
            result["sma_50"] = self._compute_sma(closes, period=50)

        # EMA crossover detection
        if result["ema_9"] and result["ema_21"]:
            ema_9_prev = self._compute_ema(closes[:-1], period=9) if len(closes) > 9 else None
            ema_21_prev = self._compute_ema(closes[:-1], period=21) if len(closes) > 21 else None
            
            if ema_9_prev and ema_21_prev:
                # Bullish cross: EMA9 crosses above EMA21
                if ema_9_prev <= ema_21_prev and result["ema_9"] > result["ema_21"]:
                    result["ema_cross"] = "bullish"
                # Bearish cross: EMA9 crosses below EMA21
                elif ema_9_prev >= ema_21_prev and result["ema_9"] < result["ema_21"]:
                    result["ema_cross"] = "bearish"
            
            # Price position relative to EMAs
            if result["close"]:
                if result["close"] > result["ema_9"] > result["ema_21"]:
                    result["price_vs_ema"] = "above"
                elif result["close"] < result["ema_9"] < result["ema_21"]:
                    result["price_vs_ema"] = "below"

        # Compute MACD
        if len(closes) >= 35:
            macd_result = self._compute_macd(closes)
            if macd_result:
                result["macd_line"] = macd_result["macd_line"]
                result["macd_signal"] = macd_result["signal_line"]
                result["macd_histogram"] = macd_result["histogram"]
                result["macd_cross"] = macd_result["cross"]

        # Volume analysis
        if len(volumes) >= 20:
            result["volume_sma"] = self._compute_sma(volumes, period=20)
            if result["volume_sma"] and result["volume_sma"] > 0:
                current_vol = volumes[-1]
                result["volume_ratio"] = current_vol / result["volume_sma"]
                if result["volume_ratio"] > 1.5:
                    result["volume_trend"] = "high"
                elif result["volume_ratio"] < 0.5:
                    result["volume_trend"] = "low"
                else:
                    result["volume_trend"] = "normal"

        # Compute price velocity (linear regression slope)
        if len(closes) >= 12:
            result["price_velocity"] = self._compute_price_velocity(closes, period=12, interval=normalized_interval)

        # Candlestick pattern detection
        if len(candles) >= 3:
            pattern_result = self._detect_candle_patterns(candles)
            if pattern_result:
                result["candle_pattern"] = pattern_result["pattern"]
                result["candle_signal"] = pattern_result["signal"]

        result["_cache_ts"] = now
        self._indicator_cache[cache_key] = {"ts": now, "data": result}
        return result

    def get_ema(
        self,
        symbol: str,
        interval: str = "15",
        period: int = 20,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Get EMA (Exponential Moving Average) for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (e.g., "15" for 15m)
            period: EMA period (default 20)
            limit: Number of candles to fetch

        Returns:
            Dict with EMA value and metadata
        """
        try:
            candles = self.get_ohlcv(symbol, interval, limit=max(limit, period + 10))
            if not candles or len(candles) < period:
                return {"success": False, "error": "Insufficient data", "ema": None}

            closes = [c["close"] for c in candles]
            ema_value = self._compute_ema(closes, period)

            if ema_value is None:
                return {"success": False, "error": "EMA calculation failed", "ema": None}

            current_price = closes[-1]
            deviation_pct = ((current_price - ema_value) / ema_value) * 100 if ema_value > 0 else 0

            return {
                "success": True,
                "ema": ema_value,
                "period": period,
                "current_price": current_price,
                "deviation_pct": deviation_pct,
                "above_ema": current_price > ema_value,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "ema": None}

    def get_rsi(
        self,
        symbol: str,
        interval: str = "15",
        period: int = 14,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Get RSI (Relative Strength Index) for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (e.g., "15" for 15m)
            period: RSI period (default 14)
            limit: Number of candles to fetch

        Returns:
            Dict with RSI value and metadata
        """
        try:
            candles = self.get_ohlcv(symbol, interval, limit=max(limit, period + 10))
            if not candles or len(candles) < period + 1:
                return {"success": False, "error": "Insufficient data", "rsi": None}

            closes = [c["close"] for c in candles]
            rsi_value = self._compute_rsi(closes, period)

            if rsi_value is None:
                return {"success": False, "error": "RSI calculation failed", "rsi": None}

            return {
                "success": True,
                "rsi": rsi_value,
                "period": period,
                "overbought": rsi_value >= 70,
                "oversold": rsi_value <= 30,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "rsi": None}

    def get_bbands(
        self,
        symbol: str,
        interval: str = "15",
        period: int = 20,
        std_dev: float = 2.0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Get Bollinger Bands for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (e.g., "15" for 15m)
            period: BB period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)
            limit: Number of candles to fetch

        Returns:
            Dict with upper, middle, lower bands and metadata
        """
        try:
            candles = self.get_ohlcv(symbol, interval, limit=max(limit, period + 10))
            if not candles or len(candles) < period:
                return {"success": False, "error": "Insufficient data"}

            closes = [c["close"] for c in candles]

            # Calculate SMA (middle band)
            middle_band = sum(closes[-period:]) / period

            # Calculate standard deviation
            variance = sum((p - middle_band) ** 2 for p in closes[-period:]) / period
            std = variance ** 0.5

            upper_band = middle_band + (std_dev * std)
            lower_band = middle_band - (std_dev * std)

            current_price = closes[-1]
            bb_width = (upper_band - lower_band) / middle_band * 100 if middle_band > 0 else 0

            # Position within bands (0-100%)
            if upper_band != lower_band:
                bb_position = (current_price - lower_band) / (upper_band - lower_band) * 100
            else:
                bb_position = 50

            return {
                "success": True,
                "upper_band": upper_band,
                "middle_band": middle_band,
                "lower_band": lower_band,
                "bb_width": bb_width,
                "bb_position": bb_position,
                "current_price": current_price,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _compute_rsi(self, closes: List[float], period: int = 14) -> Optional[float]:
        """Compute RSI using Wilder's smoothing method."""
        if len(closes) < period + 1:
            return None

        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    def _compute_sma(self, data: List[float], period: int) -> Optional[float]:
        """Compute Simple Moving Average."""
        if len(data) < period:
            return None
        return sum(data[-period:]) / period

    def _compute_ema(self, data: List[float], period: int) -> Optional[float]:
        """Compute Exponential Moving Average."""
        if len(data) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period  # Start with SMA
        
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        
        return round(ema, 8)

    def _compute_macd(
        self,
        closes: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Optional[Dict[str, Any]]:
        """Compute MACD (Moving Average Convergence Divergence)."""
        if len(closes) < slow_period + signal_period:
            return None

        # Calculate EMAs
        ema_fast = self._compute_ema(closes, fast_period)
        ema_slow = self._compute_ema(closes, slow_period)

        if ema_fast is None or ema_slow is None:
            return None

        # MACD line
        macd_line = ema_fast - ema_slow

        # Calculate MACD history for signal line
        macd_values = []
        for i in range(slow_period, len(closes) + 1):
            subset = closes[:i]
            fast = self._compute_ema(subset, fast_period)
            slow = self._compute_ema(subset, slow_period)
            if fast and slow:
                macd_values.append(fast - slow)

        if len(macd_values) < signal_period:
            return None

        # Signal line (EMA of MACD)
        signal_line = self._compute_ema(macd_values, signal_period)
        
        if signal_line is None:
            return None

        histogram = macd_line - signal_line

        # Detect crossover
        cross = None
        if len(macd_values) >= 2:
            prev_macd = macd_values[-2]
            prev_signal = self._compute_ema(macd_values[:-1], signal_period)
            if prev_signal:
                # Bullish cross: MACD crosses above signal
                if prev_macd <= prev_signal and macd_line > signal_line:
                    cross = "bullish"
                # Bearish cross: MACD crosses below signal
                elif prev_macd >= prev_signal and macd_line < signal_line:
                    cross = "bearish"

        return {
            "macd_line": round(macd_line, 8),
            "signal_line": round(signal_line, 8),
            "histogram": round(histogram, 8),
            "cross": cross,
        }

    def _compute_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Compute Average True Range."""
        if len(closes) < period + 1:
            return None

        tr_values = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            tr = max(high_low, high_close, low_close)
            tr_values.append(tr)

        if len(tr_values) < period:
            return None

        atr = sum(tr_values[:period]) / period
        for i in range(period, len(tr_values)):
            atr = (atr * (period - 1) + tr_values[i]) / period

        return atr

    def _compute_adx(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Compute Average Directional Index."""
        if len(closes) < period * 2:
            return None

        plus_dm = []
        minus_dm = []
        tr_values = []

        for i in range(1, len(closes)):
            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            if high_diff > low_diff and high_diff > 0:
                plus_dm.append(high_diff)
            else:
                plus_dm.append(0)

            if low_diff > high_diff and low_diff > 0:
                minus_dm.append(low_diff)
            else:
                minus_dm.append(0)

            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            tr_values.append(max(high_low, high_close, low_close))

        if len(tr_values) < period:
            return None

        smoothed_plus_dm = sum(plus_dm[:period])
        smoothed_minus_dm = sum(minus_dm[:period])
        smoothed_tr = sum(tr_values[:period])

        dx_values = []

        for i in range(period, len(tr_values)):
            smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm[i]
            smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm[i]
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr_values[i]

            if smoothed_tr > 0:
                plus_di = 100 * smoothed_plus_dm / smoothed_tr
                minus_di = 100 * smoothed_minus_dm / smoothed_tr

                di_sum = plus_di + minus_di
                if di_sum > 0:
                    dx = 100 * abs(plus_di - minus_di) / di_sum
                    dx_values.append(dx)

        if len(dx_values) < period:
            return None

        adx = sum(dx_values[:period]) / period
        for i in range(period, len(dx_values)):
            adx = (adx * (period - 1) + dx_values[i]) / period

        return round(adx, 2)

    def _compute_bbw(
        self,
        closes: List[float],
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Optional[float]:
        """Compute Bollinger Band Width as a percentage."""
        if len(closes) < period:
            return None

        recent_closes = closes[-period:]
        middle = sum(recent_closes) / period

        if middle == 0:
            return None

        variance = sum((c - middle) ** 2 for c in recent_closes) / period
        std = math.sqrt(variance)

        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)

        bbw = (upper - lower) / middle
        return round(bbw, 4)

    _CANDLES_PER_HOUR = {"1": 60, "3": 20, "5": 12, "15": 4, "30": 2, "60": 1, "120": 0.5, "240": 0.25, "D": 1/24}

    def _compute_price_velocity(
        self,
        closes: List[float],
        period: int = 12,
        interval: str = "15",
    ) -> Optional[float]:
        """
        Compute price velocity using linear regression slope.

        Args:
            closes: List of close prices (chronological order)
            period: Number of candles to use (default 12 = 3 hours on 15min)
            interval: Candle interval string (e.g. "5", "15", "60")

        Returns:
            Price change per hour as a decimal (e.g., 0.025 = +2.5%/hr)
        """
        if len(closes) < period:
            return None

        # Use last N candles
        recent_closes = closes[-period:]

        # Linear regression: slope = (n*sum_xy - sum_x*sum_y) / (n*sum_xx - sum_x^2)
        n = len(recent_closes)
        sum_x = sum(range(n))  # 0, 1, 2, ..., n-1
        sum_y = sum(recent_closes)
        sum_xy = sum(i * recent_closes[i] for i in range(n))
        sum_xx = sum(i * i for i in range(n))

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denom  # Price change per candle

        # Convert to percentage per hour
        candles_per_hour = self._CANDLES_PER_HOUR.get(str(interval), 4)
        avg_price = sum_y / n

        if avg_price == 0:
            return 0.0

        # Normalize to percentage per hour
        velocity_per_hour = (slope * candles_per_hour) / avg_price

        return round(velocity_per_hour, 6)

    def _detect_candle_patterns(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Detect candlestick patterns from recent candles.
        
        Returns dict with 'pattern' name and 'signal' (bullish/bearish).
        """
        if len(candles) < 3:
            return None

        # Get last 3 candles
        c1 = candles[-3]  # Oldest
        c2 = candles[-2]  # Middle
        c3 = candles[-1]  # Most recent (current)

        # Helper functions
        def body(c):
            return abs(c["close"] - c["open"])

        def upper_wick(c):
            return c["high"] - max(c["close"], c["open"])

        def lower_wick(c):
            return min(c["close"], c["open"]) - c["low"]

        def is_bullish(c):
            return c["close"] > c["open"]

        def is_bearish(c):
            return c["close"] < c["open"]

        def candle_range(c):
            return c["high"] - c["low"]

        # Current candle metrics
        current_body = body(c3)
        current_range = candle_range(c3)
        current_upper = upper_wick(c3)
        current_lower = lower_wick(c3)

        # Avoid division by zero
        if current_range == 0:
            return None

        body_ratio = current_body / current_range

        # =========================================================================
        # DOJI - Very small body (indecision)
        # =========================================================================
        if body_ratio < 0.1:
            # Dragonfly Doji (bullish) - long lower wick, no upper wick
            if current_lower > current_body * 2 and current_upper < current_body:
                return {"pattern": "dragonfly_doji", "signal": "bullish"}
            # Gravestone Doji (bearish) - long upper wick, no lower wick
            elif current_upper > current_body * 2 and current_lower < current_body:
                return {"pattern": "gravestone_doji", "signal": "bearish"}
            # Standard Doji
            else:
                return {"pattern": "doji", "signal": None}

        # =========================================================================
        # HAMMER / HANGING MAN - Small body at top, long lower wick
        # =========================================================================
        if (current_lower >= current_body * 2 and 
            current_upper <= current_body * 0.5 and
            body_ratio < 0.4):
            # After downtrend = Hammer (bullish)
            if c1["close"] > c2["close"] > c3["open"]:
                return {"pattern": "hammer", "signal": "bullish"}
            # After uptrend = Hanging Man (bearish)
            elif c1["close"] < c2["close"] < c3["open"]:
                return {"pattern": "hanging_man", "signal": "bearish"}

        # =========================================================================
        # INVERTED HAMMER / SHOOTING STAR - Small body at bottom, long upper wick
        # =========================================================================
        if (current_upper >= current_body * 2 and 
            current_lower <= current_body * 0.5 and
            body_ratio < 0.4):
            # After downtrend = Inverted Hammer (bullish)
            if c1["close"] > c2["close"]:
                return {"pattern": "inverted_hammer", "signal": "bullish"}
            # After uptrend = Shooting Star (bearish)
            elif c1["close"] < c2["close"]:
                return {"pattern": "shooting_star", "signal": "bearish"}

        # =========================================================================
        # ENGULFING PATTERNS - Current candle engulfs previous
        # =========================================================================
        prev_body = body(c2)
        if current_body > prev_body * 1.5:
            # Bullish Engulfing
            if (is_bearish(c2) and is_bullish(c3) and
                c3["open"] <= c2["close"] and c3["close"] >= c2["open"]):
                return {"pattern": "bullish_engulfing", "signal": "bullish"}
            # Bearish Engulfing
            elif (is_bullish(c2) and is_bearish(c3) and
                  c3["open"] >= c2["close"] and c3["close"] <= c2["open"]):
                return {"pattern": "bearish_engulfing", "signal": "bearish"}

        # =========================================================================
        # MORNING STAR (bullish) - Down candle, small body, up candle
        # =========================================================================
        if (is_bearish(c1) and body(c1) > candle_range(c1) * 0.5 and
            body(c2) < candle_range(c1) * 0.3 and
            is_bullish(c3) and body(c3) > candle_range(c3) * 0.5 and
            c3["close"] > (c1["open"] + c1["close"]) / 2):
            return {"pattern": "morning_star", "signal": "bullish"}

        # =========================================================================
        # EVENING STAR (bearish) - Up candle, small body, down candle
        # =========================================================================
        if (is_bullish(c1) and body(c1) > candle_range(c1) * 0.5 and
            body(c2) < candle_range(c1) * 0.3 and
            is_bearish(c3) and body(c3) > candle_range(c3) * 0.5 and
            c3["close"] < (c1["open"] + c1["close"]) / 2):
            return {"pattern": "evening_star", "signal": "bearish"}

        # =========================================================================
        # THREE WHITE SOLDIERS (bullish) - Three consecutive bullish candles
        # =========================================================================
        if (is_bullish(c1) and is_bullish(c2) and is_bullish(c3) and
            c2["close"] > c1["close"] and c3["close"] > c2["close"] and
            body(c1) > candle_range(c1) * 0.5 and
            body(c2) > candle_range(c2) * 0.5 and
            body(c3) > candle_range(c3) * 0.5):
            return {"pattern": "three_white_soldiers", "signal": "bullish"}

        # =========================================================================
        # THREE BLACK CROWS (bearish) - Three consecutive bearish candles
        # =========================================================================
        if (is_bearish(c1) and is_bearish(c2) and is_bearish(c3) and
            c2["close"] < c1["close"] and c3["close"] < c2["close"] and
            body(c1) > candle_range(c1) * 0.5 and
            body(c2) > candle_range(c2) * 0.5 and
            body(c3) > candle_range(c3) * 0.5):
            return {"pattern": "three_black_crows", "signal": "bearish"}

        # =========================================================================
        # PIERCING LINE (bullish) - Bearish then bullish closing above midpoint
        # =========================================================================
        if (is_bearish(c2) and is_bullish(c3) and
            c3["open"] < c2["low"] and
            c3["close"] > (c2["open"] + c2["close"]) / 2 and
            c3["close"] < c2["open"]):
            return {"pattern": "piercing_line", "signal": "bullish"}

        # =========================================================================
        # DARK CLOUD COVER (bearish) - Bullish then bearish closing below midpoint
        # =========================================================================
        if (is_bullish(c2) and is_bearish(c3) and
            c3["open"] > c2["high"] and
            c3["close"] < (c2["open"] + c2["close"]) / 2 and
            c3["close"] > c2["open"]):
            return {"pattern": "dark_cloud_cover", "signal": "bearish"}

        return None
