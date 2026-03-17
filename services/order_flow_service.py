"""
Tick-Level Order Flow Analysis Service

Buffers public trade events and orderbook snapshots to detect:
- Buy/sell aggression (who's pushing the price)
- Volume spikes (sudden activity = move starting)
- Orderbook imbalance (demand vs supply pressure)
- Trade flow momentum (large trades, sweeps)

Outputs a real-time "flow_score" per symbol:
  -100 to +100 where:
    +100 = extreme buy pressure (price very likely to go up)
    -100 = extreme sell pressure (price very likely to go down)
    0 = balanced / no signal
"""

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Rolling window sizes
TRADE_WINDOW_SEC = 30.0  # Analyze last 30 seconds of trades
TRADE_BUFFER_MAX = 2000  # Max trades to buffer per symbol
FLOW_SCORE_DECAY_SEC = 5.0  # Score decays after this many seconds of no activity
VOLUME_SPIKE_MULT = 3.0  # Volume > 3x average = spike
LARGE_TRADE_MULT = 5.0  # Trade size > 5x average = large/institutional


class OrderFlowService:
    """Real-time order flow analysis from WebSocket trade events."""

    def __init__(self):
        self._lock = threading.Lock()
        # Per-symbol trade buffers: deque of (timestamp, price, qty, side, is_buyer_maker)
        self._trade_buffers: Dict[str, deque] = {}
        # Per-symbol flow state
        self._flow_state: Dict[str, Dict[str, Any]] = {}
        # Per-symbol orderbook imbalance
        self._book_imbalance: Dict[str, Dict[str, Any]] = {}
        # Momentum exhaustion tracking — rolling flow score history
        self._flow_history: Dict[str, deque] = {}  # symbol → deque of (timestamp, score)

    def record_trades(self, symbol: str, trades: List[Dict[str, Any]]) -> None:
        """Buffer incoming public trade events for a symbol.

        Each trade dict should contain:
            T: timestamp (ms), p: price, v: qty, S: side ("Buy"/"Sell"),
            BM: is_buyer_maker (bool)
        """
        if not trades or not symbol:
            return
        now = time.time()
        with self._lock:
            buf = self._trade_buffers.setdefault(
                symbol, deque(maxlen=TRADE_BUFFER_MAX)
            )
            for t in trades:
                ts = float(t.get("T", 0)) / 1000.0 if t.get("T") else now
                price = float(t.get("p", 0))
                qty = float(t.get("v", 0))
                side = str(t.get("S", "")).strip()
                is_buyer_maker = bool(t.get("BM", False))
                if price > 0 and qty > 0:
                    buf.append((ts, price, qty, side, is_buyer_maker))

    def update_orderbook_imbalance(
        self,
        symbol: str,
        bids: Dict[str, str],
        asks: Dict[str, str],
        levels: int = 5,
    ) -> None:
        """Compute bid/ask volume imbalance from top N orderbook levels."""
        if not symbol:
            return
        try:
            sorted_bids = sorted(
                ((float(p), float(q)) for p, q in bids.items() if float(q) > 0),
                key=lambda x: -x[0],
            )[:levels]
            sorted_asks = sorted(
                ((float(p), float(q)) for p, q in asks.items() if float(q) > 0),
                key=lambda x: x[0],
            )[:levels]
            bid_vol = sum(q for _, q in sorted_bids)
            ask_vol = sum(q for _, q in sorted_asks)
            total = bid_vol + ask_vol
            imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0
            with self._lock:
                self._book_imbalance[symbol] = {
                    "imbalance": round(imbalance, 4),
                    "bid_vol": round(bid_vol, 2),
                    "ask_vol": round(ask_vol, 2),
                    "updated_at": time.time(),
                }
        except (ValueError, ZeroDivisionError):
            pass

    def compute_flow_score(self, symbol: str) -> Dict[str, Any]:
        """Compute the real-time order flow score for a symbol.

        Returns:
            {
                "flow_score": -100 to +100,
                "buy_volume": float,
                "sell_volume": float,
                "volume_spike": bool,
                "large_trade_detected": bool,
                "book_imbalance": -1.0 to +1.0,
                "signal": "strong_buy" | "buy" | "neutral" | "sell" | "strong_sell",
                "confidence": 0.0 to 1.0,
            }
        """
        now = time.time()
        cutoff = now - TRADE_WINDOW_SEC
        result = {
            "flow_score": 0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "trade_count": 0,
            "volume_spike": False,
            "large_trade_detected": False,
            "book_imbalance": 0.0,
            "signal": "neutral",
            "confidence": 0.0,
            "updated_at": now,
        }

        with self._lock:
            buf = self._trade_buffers.get(symbol)
            if not buf:
                return result

            # Filter trades within the analysis window
            recent = [(ts, p, q, side, bm) for ts, p, q, side, bm in buf if ts >= cutoff]
            if len(recent) < 3:
                return result

            # Compute buy/sell volumes
            buy_vol = 0.0
            sell_vol = 0.0
            total_qty = 0.0
            max_trade_qty = 0.0
            recent_5s = []
            cutoff_5s = now - 5.0

            for ts, price, qty, side, is_buyer_maker in recent:
                notional = price * qty
                if side == "Buy" or (not side and not is_buyer_maker):
                    buy_vol += notional
                else:
                    sell_vol += notional
                total_qty += qty
                if qty > max_trade_qty:
                    max_trade_qty = qty
                if ts >= cutoff_5s:
                    recent_5s.append((ts, price, qty, side, is_buyer_maker))

            result["buy_volume"] = round(buy_vol, 2)
            result["sell_volume"] = round(sell_vol, 2)
            result["trade_count"] = len(recent)

            # Volume imbalance score (-1 to +1)
            total_vol = buy_vol + sell_vol
            if total_vol > 0:
                vol_imbalance = (buy_vol - sell_vol) / total_vol
            else:
                vol_imbalance = 0.0

            # Average trade size for spike/large detection
            avg_qty = total_qty / len(recent) if recent else 0
            if avg_qty > 0:
                result["volume_spike"] = (
                    len(recent_5s) > 0
                    and sum(q for _, _, q, _, _ in recent_5s) / max(len(recent_5s), 1)
                    > avg_qty * VOLUME_SPIKE_MULT
                )
                result["large_trade_detected"] = max_trade_qty > avg_qty * LARGE_TRADE_MULT

            # Orderbook imbalance
            book = self._book_imbalance.get(symbol, {})
            book_imbalance = float(book.get("imbalance", 0.0))
            book_age = now - float(book.get("updated_at", 0))
            if book_age > 5.0:
                book_imbalance = 0.0  # stale book data
            result["book_imbalance"] = round(book_imbalance, 4)

            # Composite flow score: weighted combination
            # Volume imbalance: 50% weight (most reliable)
            # Orderbook imbalance: 30% weight (predictive but can be spoofed)
            # Volume spike bonus: 20% weight (confirms conviction)
            score = vol_imbalance * 50.0
            score += book_imbalance * 30.0
            if result["volume_spike"]:
                # Spike amplifies the direction
                spike_direction = 1.0 if vol_imbalance > 0 else -1.0
                score += spike_direction * 20.0
            if result["large_trade_detected"]:
                # Large trade = institutional, amplify signal
                score *= 1.3

            # Clamp to -100..+100
            score = max(-100.0, min(100.0, score))
            result["flow_score"] = round(score, 1)

            # Confidence based on trade count and recency
            recency = len(recent_5s) / max(len(recent), 1)
            trade_density = min(1.0, len(recent) / 50.0)
            result["confidence"] = round(min(1.0, recency * 0.5 + trade_density * 0.5), 3)

            # Signal classification
            if score >= 40:
                result["signal"] = "strong_buy"
            elif score >= 15:
                result["signal"] = "buy"
            elif score <= -40:
                result["signal"] = "strong_sell"
            elif score <= -15:
                result["signal"] = "sell"
            else:
                result["signal"] = "neutral"

            # ===== MOMENTUM EXHAUSTION DETECTION =====
            # Track flow score history to detect when momentum is FADING.
            # A score that was +60 and dropped to +15 = momentum exhausting.
            # This is the earliest exit signal — happens before price reverses.
            history = self._flow_history.setdefault(symbol, deque(maxlen=30))
            history.append((now, score))

            # Compute momentum change over last 15-30 seconds
            momentum_fading = False
            momentum_exhausted = False
            peak_recent_score = score
            fade_amount = 0.0

            if len(history) >= 3:
                # Find peak score in last 30 seconds
                for ts_h, score_h in history:
                    if now - ts_h <= 30.0:
                        if abs(score_h) > abs(peak_recent_score):
                            peak_recent_score = score_h

                # Momentum fade = peak was strong, current is weak or opposite
                if peak_recent_score > 0:  # Was buying
                    fade_amount = peak_recent_score - score
                    if fade_amount >= 25 and peak_recent_score >= 35:
                        momentum_fading = True
                    if fade_amount >= 45 or (score <= 0 and peak_recent_score >= 30):
                        momentum_exhausted = True
                elif peak_recent_score < 0:  # Was selling
                    fade_amount = score - peak_recent_score  # Both negative, fade = less negative
                    if fade_amount >= 25 and peak_recent_score <= -35:
                        momentum_fading = True
                    if fade_amount >= 45 or (score >= 0 and peak_recent_score <= -30):
                        momentum_exhausted = True

            result["momentum_fading"] = momentum_fading
            result["momentum_exhausted"] = momentum_exhausted
            result["peak_recent_score"] = round(peak_recent_score, 1)
            result["fade_amount"] = round(fade_amount, 1)

            # Cache the flow state
            self._flow_state[symbol] = dict(result)

        return result

    def get_flow_state(self, symbol: str) -> Dict[str, Any]:
        """Get the last computed flow state for a symbol."""
        with self._lock:
            state = self._flow_state.get(symbol)
            if state:
                age = time.time() - float(state.get("updated_at", 0))
                if age > FLOW_SCORE_DECAY_SEC:
                    state = dict(state)
                    # Decay the score toward 0
                    decay = max(0.0, 1.0 - (age - FLOW_SCORE_DECAY_SEC) / 10.0)
                    state["flow_score"] = round(state["flow_score"] * decay, 1)
                    state["confidence"] = round(state["confidence"] * decay, 3)
                    if abs(state["flow_score"]) < 5:
                        state["signal"] = "neutral"
                return state
        return {
            "flow_score": 0,
            "signal": "neutral",
            "confidence": 0.0,
        }

    def prune_stale_symbols(self, active_symbols: set) -> None:
        """Remove buffers for symbols no longer being tracked."""
        with self._lock:
            stale = set(self._trade_buffers.keys()) - active_symbols
            for sym in stale:
                self._trade_buffers.pop(sym, None)
                self._flow_state.pop(sym, None)
                self._book_imbalance.pop(sym, None)
