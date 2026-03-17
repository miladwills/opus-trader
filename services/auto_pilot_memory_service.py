"""
Auto-Pilot Performance Memory Service

Tracks per-coin historical performance to help Auto-Pilot make smarter picks:
- Which coins made money vs lost money
- Win rate and average profit per coin
- Best/worst hours for trading
- Risk scaling: reduce size after losses, increase after wins
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AutoPilotMemoryService:
    """Per-coin performance tracking for Auto-Pilot coin selection."""

    def __init__(self):
        self._symbol_stats: Dict[str, Dict[str, Any]] = {}
        self._last_rebuild_at = 0.0
        self._rebuild_interval = 300.0  # Rebuild every 5 minutes
        self._stats_lock = threading.Lock()

    def rebuild_from_trade_logs(self, trade_logs: List[Dict[str, Any]]) -> None:
        """Build per-symbol performance stats from trade history."""
        stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "recent_pnl": 0.0,  # Last 20 trades
            "recent_wins": 0,
            "recent_trades": 0,
        })

        # Group by symbol
        by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for log in trade_logs or []:
            sym = str(log.get("symbol") or "").strip().upper()
            if sym:
                by_symbol[sym].append(log)

        for sym, logs in by_symbol.items():
            s = stats[sym]
            # Sort by time to get recent trades
            sorted_logs = sorted(logs, key=lambda x: str(x.get("time") or ""))
            recent = sorted_logs[-20:]  # Last 20 trades

            for log in sorted_logs:
                pnl = float(log.get("realized_pnl") or 0)
                s["trades"] += 1
                s["total_pnl"] += pnl
                if pnl > 0:
                    s["wins"] += 1
                    s["total_profit"] += pnl
                    s["max_win"] = max(s["max_win"], pnl)
                elif pnl < 0:
                    s["losses"] += 1
                    s["total_loss"] += pnl
                    s["max_loss"] = min(s["max_loss"], pnl)

            for log in recent:
                pnl = float(log.get("realized_pnl") or 0)
                s["recent_trades"] += 1
                s["recent_pnl"] += pnl
                if pnl > 0:
                    s["recent_wins"] += 1

            s["win_rate"] = s["wins"] / s["trades"] if s["trades"] > 0 else 0.0
            s["avg_pnl"] = s["total_pnl"] / s["trades"] if s["trades"] > 0 else 0.0
            s["recent_win_rate"] = (
                s["recent_wins"] / s["recent_trades"]
                if s["recent_trades"] > 0
                else 0.0
            )

        with self._stats_lock:
            self._symbol_stats = dict(stats)
        self._last_rebuild_at = time.time()
        logger.info(
            "Auto-Pilot memory rebuilt: %d symbols, top=%s",
            len(stats),
            sorted(stats.keys(), key=lambda s: stats[s]["total_pnl"], reverse=True)[:3],
        )

    def get_symbol_score_adjustment(self, symbol: str) -> float:
        """Get a score adjustment for Auto-Pilot candidate scoring.

        Returns:
            -20 to +20 adjustment based on historical performance.
            Positive = coin has been profitable, prefer it.
            Negative = coin has been losing money, avoid it.
        """
        with self._stats_lock:
            s = self._symbol_stats.get(symbol)
        if not s or s["trades"] < 5:
            return 0.0  # Not enough data

        adjustment = 0.0

        # Recent performance (most important — markets change)
        if s["recent_trades"] >= 5:
            if s["recent_win_rate"] >= 0.65:
                adjustment += 10.0  # Recently profitable
            elif s["recent_win_rate"] <= 0.35:
                adjustment -= 10.0  # Recently losing
            if s["recent_pnl"] > 0:
                adjustment += min(5.0, s["recent_pnl"] * 2.0)
            else:
                adjustment += max(-5.0, s["recent_pnl"] * 2.0)

        # Overall track record
        if s["trades"] >= 20:
            if s["win_rate"] >= 0.60:
                adjustment += 5.0
            elif s["win_rate"] <= 0.40:
                adjustment -= 5.0

        return max(-20.0, min(20.0, round(adjustment, 1)))

    def get_risk_multiplier(self, symbol: str) -> float:
        """Get position size multiplier based on recent performance.

        Returns:
            0.5 to 1.5 multiplier.
            < 1.0 = reduce size (losing streak)
            > 1.0 = increase size (winning streak)
        """
        s = self._symbol_stats.get(symbol)
        if not s or s["recent_trades"] < 5:
            return 1.0

        if s["recent_win_rate"] >= 0.70 and s["recent_pnl"] > 0:
            return 1.3  # Winning — scale up slightly
        elif s["recent_win_rate"] <= 0.30 and s["recent_pnl"] < 0:
            return 0.8  # Losing — scale down (was 0.6, raised to prevent death spiral)
        elif s["recent_pnl"] < -2.0:
            return 0.85  # Significant recent losses (was 0.7)
        return 1.0

    def should_avoid_symbol(self, symbol: str) -> bool:
        """Check if a symbol should be avoided entirely based on track record."""
        s = self._symbol_stats.get(symbol)
        if not s:
            return False
        # Avoid if: 20+ trades AND win rate < 35% AND total PnL deeply negative
        if s["trades"] >= 20 and s["win_rate"] < 0.35 and s["total_pnl"] < -5.0:
            return True
        # Avoid if: recent 20 trades are strongly negative
        if s["recent_trades"] >= 10 and s["recent_pnl"] < -3.0 and s["recent_win_rate"] < 0.30:
            return True
        return False

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get all symbol stats for display."""
        return dict(self._symbol_stats)

    def record_trade(self, symbol: str, pnl: float, is_win: bool) -> None:
        """Incrementally update stats for a single trade (real-time path)."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return
        with self._stats_lock:
            s = self._symbol_stats.get(sym)
            if not s:
                s = {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0.0, "total_profit": 0.0, "total_loss": 0.0,
                    "max_win": 0.0, "max_loss": 0.0,
                    "recent_pnl": 0.0, "recent_wins": 0, "recent_trades": 0,
                    "win_rate": 0.0, "avg_pnl": 0.0, "recent_win_rate": 0.0,
                }
                self._symbol_stats[sym] = s
            s["trades"] += 1
            s["total_pnl"] += pnl
            if is_win:
                s["wins"] += 1
                s["total_profit"] += pnl
                s["max_win"] = max(s["max_win"], pnl)
                s["recent_wins"] += 1
            else:
                s["losses"] += 1
                s["total_loss"] += pnl
                s["max_loss"] = min(s["max_loss"], pnl)
            s["recent_pnl"] += pnl
            s["recent_trades"] += 1
            # Recalc derived stats
            s["win_rate"] = s["wins"] / s["trades"] if s["trades"] > 0 else 0.0
            s["avg_pnl"] = s["total_pnl"] / s["trades"] if s["trades"] > 0 else 0.0
            s["recent_win_rate"] = (
                s["recent_wins"] / s["recent_trades"] if s["recent_trades"] > 0 else 0.0
            )
            # If recent window drifts too far, force full rebuild to reset
            if s["recent_trades"] > 25:
                self._last_rebuild_at = 0
        logger.debug("[Auto-Pilot Memory] Recorded trade: %s pnl=%.4f win=%s", sym, pnl, is_win)

    def needs_rebuild(self) -> bool:
        """Check if stats need refreshing."""
        return time.time() - self._last_rebuild_at > self._rebuild_interval
