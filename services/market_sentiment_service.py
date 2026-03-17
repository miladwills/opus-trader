"""
Market Sentiment Service

Combines Open Interest, Long/Short Ratio, and Funding Rate into a unified
sentiment signal that detects whether a price move has real conviction or
is likely to reverse.

Outputs a sentiment_score (-100 to +100):
  +100 = extremely bullish conviction (OI rising + longs dominant + positive funding)
  -100 = extremely bearish conviction (OI rising + shorts dominant + negative funding)
  0 = neutral / no clear signal
"""

import logging
import time
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Cache TTL — don't spam Bybit API
SENTIMENT_CACHE_TTL_SEC = 10.0  # Was 30 — more responsive to OI/funding changes


class MarketSentimentService:
    """Combines OI + L/S ratio + funding rate into a conviction signal."""

    def __init__(self, client):
        self.client = client
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Get the combined market sentiment for a symbol.

        Returns:
            {
                "sentiment_score": -100 to +100,
                "signal": "strong_conviction" | "conviction" | "neutral" | "weak" | "reversal_risk",
                "oi_change_pct": float,  # OI change over last period
                "long_short_ratio": float,  # >1 = more longs
                "funding_rate": float,  # positive = longs pay
                "oi_conviction": str,  # "new_money_in" | "squeeze" | "capitulation" | "shorts_piling"
            }
        """
        now = time.time()

        # Check cache
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and now - cached.get("ts", 0) < SENTIMENT_CACHE_TTL_SEC:
                return cached.get("data", {})

        result = {
            "sentiment_score": 0,
            "signal": "neutral",
            "oi_change_pct": 0.0,
            "long_short_ratio": 1.0,
            "funding_rate": 0.0,
            "oi_conviction": "unknown",
            "updated_at": now,
        }

        # Fetch OI
        oi_change = 0.0
        try:
            oi_resp = self.client.get_open_interest(symbol)
            if oi_resp.get("success"):
                oi_list = oi_resp.get("data", {}).get("list", []) or []
                if len(oi_list) >= 2:
                    current_oi = float(oi_list[0].get("openInterest") or 0)
                    prev_oi = float(oi_list[1].get("openInterest") or 0)
                    if prev_oi > 0:
                        oi_change = (current_oi - prev_oi) / prev_oi
                        result["oi_change_pct"] = round(oi_change * 100, 2)
        except Exception as exc:
            logger.debug("[%s] OI fetch failed: %s", symbol, exc)

        # Fetch L/S ratio
        ls_ratio = 1.0
        try:
            ls_resp = self.client.get_long_short_ratio(symbol)
            if ls_resp.get("success"):
                ls_list = ls_resp.get("data", {}).get("list", []) or []
                if ls_list:
                    buy_ratio = float(ls_list[0].get("buyRatio") or 0.5)
                    sell_ratio = float(ls_list[0].get("sellRatio") or 0.5)
                    if sell_ratio > 0:
                        ls_ratio = buy_ratio / sell_ratio
                    result["long_short_ratio"] = round(ls_ratio, 3)
        except Exception as exc:
            logger.debug("[%s] L/S ratio fetch failed: %s", symbol, exc)

        # Fetch funding rate
        funding = 0.0
        try:
            fr_resp = self.client.get_funding_rate(symbol)
            if fr_resp.get("success"):
                fr_list = fr_resp.get("data", {}).get("list", []) or []
                if fr_list:
                    funding = float(fr_list[0].get("fundingRate") or 0)
                    result["funding_rate"] = round(funding, 6)
        except Exception as exc:
            logger.debug("[%s] Funding rate fetch failed: %s", symbol, exc)

        # ===== Compute conviction signal =====

        # OI conviction type
        oi_rising = oi_change > 0.005  # >0.5% increase
        oi_falling = oi_change < -0.005
        price_rising = funding >= 0  # Rough proxy: positive funding = price trending up

        if oi_rising and price_rising:
            result["oi_conviction"] = "new_money_in"  # Strongest: real conviction
        elif oi_rising and not price_rising:
            result["oi_conviction"] = "shorts_piling"  # Bearish conviction
        elif oi_falling and price_rising:
            result["oi_conviction"] = "short_squeeze"  # Weak rise, likely reversal
        elif oi_falling and not price_rising:
            result["oi_conviction"] = "capitulation"  # Longs giving up
        else:
            result["oi_conviction"] = "neutral"

        # Composite sentiment score
        score = 0.0

        # OI change contribution (0-30 points)
        oi_pts = min(30.0, abs(oi_change) * 1000)  # 3% OI change = 30 pts
        if oi_rising:
            score += oi_pts if price_rising else -oi_pts
        elif oi_falling:
            score -= oi_pts * 0.5  # Falling OI = less conviction either way

        # L/S ratio contribution (0-30 points)
        # Extreme ratios = reversal risk (crowd is usually wrong)
        if ls_ratio > 1.0:
            if ls_ratio > 2.5:
                score -= 15.0  # TOO many longs = reversal risk
                result["signal"] = "reversal_risk"
            elif ls_ratio > 1.5:
                score += 10.0  # Moderate long bias = mild bullish
            else:
                score += 5.0
        elif ls_ratio < 1.0:
            if ls_ratio < 0.4:
                score += 15.0  # TOO many shorts = squeeze potential
            elif ls_ratio < 0.67:
                score -= 10.0  # Moderate short bias = mild bearish
            else:
                score -= 5.0

        # Funding rate contribution (0-20 points)
        funding_pct = funding * 100  # Convert to percentage
        if abs(funding_pct) > 0.05:
            # High funding = crowded trade, reversal risk
            if funding_pct > 0.1:
                score -= 10.0  # Very high positive = longs crowded
            elif funding_pct > 0.03:
                score += 10.0  # Moderate positive = healthy bullish
            elif funding_pct < -0.1:
                score += 10.0  # Very high negative = shorts crowded (squeeze potential)
            elif funding_pct < -0.03:
                score -= 10.0  # Moderate negative = healthy bearish

        # Clamp
        score = max(-100.0, min(100.0, score))
        result["sentiment_score"] = round(score, 1)

        # Signal classification
        if result.get("signal") != "reversal_risk":
            if abs(score) >= 40:
                result["signal"] = "strong_conviction"
            elif abs(score) >= 20:
                result["signal"] = "conviction"
            elif abs(score) >= 10:
                result["signal"] = "weak"
            else:
                result["signal"] = "neutral"

        # Cache result
        with self._lock:
            self._cache[symbol] = {"ts": now, "data": result}

        return result
