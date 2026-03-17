"""
Bybit Control Center - Session-Based Trading Service

Analyzes market conditions based on trading sessions:
- Asian Session: 00:00-08:00 UTC (typically lower volatility, range-bound)
- European Session: 08:00-16:00 UTC (moderate volatility, trending)
- US Session: 13:00-21:00 UTC (highest volatility, strong moves)
- Late Session: 21:00-00:00 UTC (declining volume, consolidation)

Session overlaps (EU+US 13:00-16:00 UTC) often produce biggest moves.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SessionService:
    """
    Service for session-based trading analysis.

    Helps identify optimal trading times and adjust strategy based on
    expected volatility and market behavior patterns.
    """

    # Session definitions (UTC times)
    SESSIONS = {
        "asian": {
            "name": "Asian",
            "start_hour": 0,
            "end_hour": 8,
            "volatility": "low",
            "behavior": "range_bound",
            "score_modifier": 0.0,  # Neutral - good for grid trading
        },
        "european": {
            "name": "European",
            "start_hour": 8,
            "end_hour": 16,
            "volatility": "moderate",
            "behavior": "trending",
            "score_modifier": 0.1,  # Slight boost for trend trading
        },
        "us": {
            "name": "US",
            "start_hour": 13,
            "end_hour": 21,
            "volatility": "high",
            "behavior": "volatile",
            "score_modifier": 0.0,  # High vol can go either way
        },
        "late": {
            "name": "Late",
            "start_hour": 21,
            "end_hour": 24,
            "volatility": "low",
            "behavior": "consolidation",
            "score_modifier": -0.1,  # Lower confidence in signals
        },
    }

    # Session overlaps with their characteristics
    OVERLAPS = {
        "eu_us": {
            "name": "EU/US Overlap",
            "start_hour": 13,
            "end_hour": 16,
            "volatility": "very_high",
            "behavior": "breakout_prone",
            "score_modifier": 0.15,  # Strong moves more likely
        },
        "asian_eu": {
            "name": "Asian/EU Overlap",
            "start_hour": 7,
            "end_hour": 9,
            "volatility": "moderate_high",
            "behavior": "transitional",
            "score_modifier": 0.05,
        },
    }

    # Day of week modifiers (0=Monday, 6=Sunday)
    DAY_MODIFIERS = {
        0: {"name": "Monday", "modifier": 0.0, "note": "Week opens, institutional positioning"},
        1: {"name": "Tuesday", "modifier": 0.1, "note": "Often trending day"},
        2: {"name": "Wednesday", "modifier": 0.1, "note": "Mid-week, good volume"},
        3: {"name": "Thursday", "modifier": 0.05, "note": "Pre-Friday positioning"},
        4: {"name": "Friday", "modifier": -0.1, "note": "Weekend risk, position squaring"},
        5: {"name": "Saturday", "modifier": -0.2, "note": "Low volume, weekend"},
        6: {"name": "Sunday", "modifier": -0.2, "note": "Low volume, Sunday gap risk"},
    }

    def __init__(self):
        """Initialize Session service."""
        pass

    def get_current_session(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get the current trading session information.

        Args:
            now: Optional datetime (defaults to current UTC time)

        Returns:
            Dict with session info
        """
        if now is None:
            now = datetime.now(timezone.utc)

        hour = now.hour
        day_of_week = now.weekday()

        # Check for overlaps first (more specific)
        current_overlap = None
        for overlap_key, overlap in self.OVERLAPS.items():
            if overlap["start_hour"] <= hour < overlap["end_hour"]:
                current_overlap = {
                    "key": overlap_key,
                    **overlap,
                }
                break

        # Determine primary session
        primary_session = None
        for session_key, session in self.SESSIONS.items():
            start = session["start_hour"]
            end = session["end_hour"]

            # Handle late session that wraps at midnight
            if start > end:  # e.g., 21-24
                if hour >= start or hour < end:
                    primary_session = {"key": session_key, **session}
                    break
            else:
                if start <= hour < end:
                    primary_session = {"key": session_key, **session}
                    break

        # Get day modifier
        day_info = self.DAY_MODIFIERS.get(day_of_week, {"name": "Unknown", "modifier": 0})

        return {
            "success": True,
            "timestamp": now.isoformat(),
            "hour_utc": hour,
            "day_of_week": day_of_week,
            "day_name": day_info["name"],
            "day_modifier": day_info["modifier"],
            "day_note": day_info.get("note", ""),
            "primary_session": primary_session,
            "overlap": current_overlap,
            "is_overlap": current_overlap is not None,
            "is_weekend": day_of_week >= 5,
        }

    def get_session_signal(
        self,
        now: Optional[datetime] = None,
        max_score: float = 10,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on current session characteristics.

        Logic:
        - EU/US overlap = Best for directional trades (boost signals)
        - Asian session = Best for range/grid trading (neutral)
        - Weekend = Reduce confidence (lower scores)
        - Friday late = Caution (position squaring)

        Args:
            now: Optional datetime (defaults to current UTC time)
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        session_data = self.get_current_session(now)

        score = 0
        signals = []
        recommendations = []

        # Base session analysis
        primary = session_data.get("primary_session", {})
        overlap = session_data.get("overlap")
        day_modifier = session_data.get("day_modifier", 0)
        is_weekend = session_data.get("is_weekend", False)

        # Calculate session score modifier
        session_modifier = primary.get("score_modifier", 0) if primary else 0

        if overlap:
            # Overlap takes precedence
            session_modifier = overlap.get("score_modifier", 0)
            signals.append(f"{overlap['name']}: High activity period")
            recommendations.append("Good for breakout trades")

        elif primary:
            volatility = primary.get("volatility", "moderate")
            behavior = primary.get("behavior", "unknown")

            if volatility == "low":
                signals.append(f"{primary['name']} Session: Low volatility expected")
                recommendations.append("Good for range/grid trading")
            elif volatility == "high":
                signals.append(f"{primary['name']} Session: High volatility expected")
                recommendations.append("Use wider stops, expect fast moves")
            else:
                signals.append(f"{primary['name']} Session: Moderate volatility")

        # Apply day modifier
        if is_weekend:
            session_modifier += day_modifier
            signals.append("Weekend: Lower liquidity and volume")
            recommendations.append("Consider smaller position sizes")
        elif day_modifier < 0:
            signals.append(f"{session_data['day_name']}: {session_data.get('day_note', '')}")
            recommendations.append("Be cautious with new positions")
        elif day_modifier > 0:
            signals.append(f"{session_data['day_name']}: {session_data.get('day_note', '')}")

        # Calculate final score (modifier affects how much we trust other signals)
        # Positive modifier = boost directional confidence
        # Negative modifier = reduce directional confidence
        score = max_score * session_modifier

        # Determine signal type
        if session_modifier > 0.1:
            signal = "FAVORABLE"
        elif session_modifier < -0.1:
            signal = "UNFAVORABLE"
        else:
            signal = "NEUTRAL"

        return {
            "score": score,
            "signal": signal,
            "modifier": session_modifier,
            "reason": ", ".join(signals) if signals else "Normal trading conditions",
            "recommendations": recommendations,
            "session": primary.get("name", "Unknown") if primary else "Unknown",
            "session_key": primary.get("key", "unknown") if primary else "unknown",
            "volatility_expected": primary.get("volatility", "moderate") if primary else "moderate",
            "behavior_expected": primary.get("behavior", "unknown") if primary else "unknown",
            "is_overlap": session_data.get("is_overlap", False),
            "overlap_name": overlap.get("name") if overlap else None,
            "is_weekend": is_weekend,
            "day_name": session_data.get("day_name", "Unknown"),
            "hour_utc": session_data.get("hour_utc", 0),
        }

    def get_volatility_adjustment(
        self,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get suggested volatility adjustments for the current session.

        Can be used to adjust:
        - Grid spacing (wider in high vol sessions)
        - Take profit targets (larger in high vol)
        - Stop loss distances
        - Position sizes

        Args:
            now: Optional datetime

        Returns:
            Dict with adjustment multipliers
        """
        session_data = self.get_current_session(now)
        primary = session_data.get("primary_session", {})
        overlap = session_data.get("overlap")
        is_weekend = session_data.get("is_weekend", False)

        # Base adjustments by volatility level
        volatility_adjustments = {
            "very_high": {
                "grid_spacing_mult": 1.5,    # Wider grids
                "tp_mult": 1.3,               # Larger TPs
                "sl_mult": 1.4,               # Wider stops
                "position_mult": 0.7,         # Smaller positions
            },
            "high": {
                "grid_spacing_mult": 1.25,
                "tp_mult": 1.15,
                "sl_mult": 1.2,
                "position_mult": 0.85,
            },
            "moderate_high": {
                "grid_spacing_mult": 1.15,
                "tp_mult": 1.1,
                "sl_mult": 1.1,
                "position_mult": 0.9,
            },
            "moderate": {
                "grid_spacing_mult": 1.0,
                "tp_mult": 1.0,
                "sl_mult": 1.0,
                "position_mult": 1.0,
            },
            "low": {
                "grid_spacing_mult": 0.85,
                "tp_mult": 0.9,
                "sl_mult": 0.9,
                "position_mult": 1.1,
            },
        }

        # Determine effective volatility
        if overlap:
            vol_level = overlap.get("volatility", "moderate")
        elif primary:
            vol_level = primary.get("volatility", "moderate")
        else:
            vol_level = "moderate"

        adjustments = volatility_adjustments.get(vol_level, volatility_adjustments["moderate"])

        # Weekend adjustment
        if is_weekend:
            adjustments = {
                "grid_spacing_mult": adjustments["grid_spacing_mult"] * 0.9,
                "tp_mult": adjustments["tp_mult"] * 0.85,
                "sl_mult": adjustments["sl_mult"] * 0.9,
                "position_mult": adjustments["position_mult"] * 0.8,
            }

        return {
            "success": True,
            "volatility_level": vol_level,
            "is_weekend": is_weekend,
            **adjustments,
        }

    def should_trade(
        self,
        now: Optional[datetime] = None,
        allow_weekend: bool = True,
        allow_low_vol: bool = True,
    ) -> Dict[str, Any]:
        """
        Determine if current session is suitable for trading.

        Args:
            now: Optional datetime
            allow_weekend: Whether to allow weekend trading
            allow_low_vol: Whether to allow low volatility sessions

        Returns:
            Dict with recommendation
        """
        session_data = self.get_current_session(now)
        primary = session_data.get("primary_session", {})
        is_weekend = session_data.get("is_weekend", False)

        should_trade = True
        reasons = []

        if is_weekend and not allow_weekend:
            should_trade = False
            reasons.append("Weekend trading disabled")

        if primary and primary.get("volatility") == "low" and not allow_low_vol:
            should_trade = False
            reasons.append("Low volatility session")

        # Check for specific bad times
        hour = session_data.get("hour_utc", 12)
        day = session_data.get("day_of_week", 2)

        # Sunday 21:00-00:00 UTC - gap risk
        if day == 6 and hour >= 21:
            reasons.append("Sunday close - gap risk on Monday open")

        # Friday 20:00+ - weekend positioning
        if day == 4 and hour >= 20:
            reasons.append("Late Friday - weekend risk")

        return {
            "should_trade": should_trade,
            "confidence": 1.0 if should_trade and not reasons else 0.7,
            "reasons": reasons,
            "session": primary.get("name", "Unknown") if primary else "Unknown",
            "is_weekend": is_weekend,
        }

    def get_optimal_sessions(self, strategy: str = "grid") -> Dict[str, Any]:
        """
        Get optimal trading sessions for a given strategy type.

        Args:
            strategy: Trading strategy type (grid, trend, scalp, breakout)

        Returns:
            Dict with optimal session recommendations
        """
        strategy_sessions = {
            "grid": {
                "optimal": ["asian"],
                "good": ["late"],
                "avoid": ["eu_us_overlap"],
                "reason": "Grid trading works best in range-bound, low volatility conditions",
            },
            "trend": {
                "optimal": ["european", "us"],
                "good": ["eu_us_overlap"],
                "avoid": ["late", "weekend"],
                "reason": "Trend trading needs directional moves and volume",
            },
            "scalp": {
                "optimal": ["eu_us_overlap", "us"],
                "good": ["european"],
                "avoid": ["asian", "weekend"],
                "reason": "Scalping benefits from high volatility and tight spreads",
            },
            "breakout": {
                "optimal": ["eu_us_overlap", "asian_eu_overlap"],
                "good": ["european"],
                "avoid": ["late"],
                "reason": "Breakouts often occur at session transitions",
            },
        }

        return strategy_sessions.get(strategy, strategy_sessions["grid"])
