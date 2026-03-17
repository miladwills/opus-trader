"""
Neutral Suitability Gate Service.

Determines if market conditions are suitable for neutral/grid trading.
Blocks neutral mode during trending markets to prevent losses.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import config.strategy_config as cfg

logger = logging.getLogger(__name__)


class NeutralSuitabilityService:
    """
    Gate service that checks if conditions are suitable for neutral mode.

    Checks multiple indicators across timeframes to determine if market
    conditions are sideways (suitable for grid trading) or trending
    (unsuitable - should block neutral mode).

    Checks:
    - ADX on 15m: Must be < threshold (sideways market)
    - RSI on 15m: Must be in neutral zone (35-65)
    - ATR%: Must be reasonable (not extreme volatility)
    - Optional: 1m momentum for immediate trend detection
    """

    def __init__(self, indicator_service):
        """
        Initialize with required dependencies.

        Args:
            indicator_service: IndicatorService for fetching technical indicators
        """
        self.indicator_service = indicator_service
        self._cache = {}  # Simple cache for recent checks
        self._cache_ttl = 30  # Cache TTL in seconds

    def _get_now_ts(self) -> float:
        """Get current timestamp (allows for mocking in tests)."""
        return time.time()

    def get_preset_for_symbol(self, symbol: str) -> str:
        """
        Determine the appropriate preset for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")

        Returns:
            Preset name ("MAJOR" or "MEME")
        """
        if symbol in cfg.NEUTRAL_MAJOR_SYMBOLS:
            return "MAJOR"
        return "MEME"

    def get_preset_config(self, preset_name: str) -> Dict[str, Any]:
        """
        Get the configuration for a preset.

        Args:
            preset_name: Preset name ("MAJOR" or "MEME")

        Returns:
            Preset configuration dict
        """
        return cfg.NEUTRAL_PRESETS.get(preset_name, cfg.NEUTRAL_PRESETS[cfg.NEUTRAL_DEFAULT_PRESET])

    def check_suitability(
        self,
        symbol: str,
        preset: Optional[str] = None,
        indicators_15m: Optional[Dict[str, Any]] = None,
        indicators_1m: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if neutral mode is suitable for current market conditions.

        Args:
            symbol: Trading symbol (e.g., "ETHUSDT")
            preset: Optional preset name, auto-detected if not provided
            indicators_15m: Optional pre-fetched 15m indicators
            indicators_1m: Optional pre-fetched 1m indicators

        Returns:
            {
                "suitable": bool,
                "reason": str,
                "blocked_by": List[str],  # Which checks failed
                "scores": {
                    "adx_15m": float,
                    "rsi_15m": float,
                    "atr_pct": float,
                    "adx_1m": float,  # Optional
                },
                "thresholds": {
                    "adx_15m_max": float,
                    "rsi_upper": float,
                    "rsi_lower": float,
                    "atr_pct_max": float,
                    "adx_1m_max": float,
                },
                "preset": str,
            }
        """
        if not cfg.NEUTRAL_GATE_ENABLED:
            return {
                "suitable": True,
                "reason": "Gate disabled",
                "blocked_by": [],
                "scores": {},
                "thresholds": {},
                "preset": preset or self.get_preset_for_symbol(symbol),
            }

        # Auto-detect preset if not provided
        if not preset:
            preset = self.get_preset_for_symbol(symbol)

        # Get preset configuration
        preset_config = self.get_preset_config(preset)

        # Get preset-specific thresholds with fallback to global defaults
        # Presets can optionally define gate_* keys, otherwise use momentum thresholds
        # which are slightly stricter than gate defaults for MEME assets
        thresholds = {
            "adx_15m_max": preset_config.get(
                "gate_adx_15m_max",
                preset_config.get("momentum_adx_threshold", cfg.NEUTRAL_GATE_ADX_15M_MAX)
            ),
            "rsi_upper": preset_config.get(
                "gate_rsi_upper",
                preset_config.get("momentum_rsi_upper", cfg.NEUTRAL_GATE_RSI_15M_UPPER)
            ),
            "rsi_lower": preset_config.get(
                "gate_rsi_lower",
                preset_config.get("momentum_rsi_lower", cfg.NEUTRAL_GATE_RSI_15M_LOWER)
            ),
            "atr_pct_max": preset_config.get(
                "gate_atr_pct_max",
                cfg.NEUTRAL_GATE_ATR_PCT_MAX
            ),
            "adx_1m_max": preset_config.get(
                "gate_adx_1m_max",
                cfg.NEUTRAL_GATE_ADX_1M_MAX
            ),
        }

        # Fetch indicators if not provided
        if indicators_15m is None:
            try:
                indicators_15m = self.indicator_service.compute_indicators(
                    symbol, interval="15", limit=100
                )
            except Exception as e:
                logger.warning(f"[{symbol}] Failed to fetch 15m indicators: {e}")
                indicators_15m = {}

        if cfg.NEUTRAL_GATE_1M_ENABLED and indicators_1m is None:
            try:
                indicators_1m = self.indicator_service.compute_indicators(
                    symbol, interval="1", limit=50
                )
            except Exception as e:
                logger.warning(f"[{symbol}] Failed to fetch 1m indicators: {e}")
                indicators_1m = {}

        # Extract indicator values
        adx_15m = indicators_15m.get("adx") if indicators_15m else None
        rsi_15m = indicators_15m.get("rsi") if indicators_15m else None
        atr_pct = indicators_15m.get("atr_pct") if indicators_15m else None
        adx_1m = indicators_1m.get("adx") if indicators_1m else None

        scores = {
            "adx_15m": adx_15m,
            "rsi_15m": rsi_15m,
            "atr_pct": atr_pct,
            "adx_1m": adx_1m,
        }

        # Run checks
        blocked_by = []
        reasons = []

        # Check 1: ADX on 15m - must be low (sideways)
        if adx_15m is not None and adx_15m > thresholds["adx_15m_max"]:
            blocked_by.append("ADX_15M")
            reasons.append(f"ADX15={adx_15m:.1f}>{thresholds['adx_15m_max']} (trending)")

        # Check 2: RSI on 15m - must be in neutral zone
        if rsi_15m is not None:
            if rsi_15m > thresholds["rsi_upper"]:
                blocked_by.append("RSI_OVERBOUGHT")
                reasons.append(f"RSI15={rsi_15m:.1f}>{thresholds['rsi_upper']} (overbought)")
            elif rsi_15m < thresholds["rsi_lower"]:
                blocked_by.append("RSI_OVERSOLD")
                reasons.append(f"RSI15={rsi_15m:.1f}<{thresholds['rsi_lower']} (oversold)")

        # Check 3: ATR% - volatility must be reasonable
        if atr_pct is not None and atr_pct > thresholds["atr_pct_max"]:
            blocked_by.append("ATR_HIGH")
            reasons.append(f"ATR%={atr_pct:.2%}>{thresholds['atr_pct_max']:.2%} (volatile)")

        # Check 4: 1m momentum (optional)
        if cfg.NEUTRAL_GATE_1M_ENABLED and adx_1m is not None:
            if adx_1m > thresholds["adx_1m_max"]:
                blocked_by.append("ADX_1M")
                reasons.append(f"ADX1m={adx_1m:.1f}>{thresholds['adx_1m_max']} (strong move)")

        suitable = len(blocked_by) == 0
        reason = "; ".join(reasons) if reasons else "Conditions suitable (sideways)"

        if not suitable:
            logger.debug(f"[{symbol}] NEUTRAL_GATE blocked: {reason}")

        return {
            "suitable": suitable,
            "reason": reason,
            "blocked_by": blocked_by,
            "scores": scores,
            "thresholds": thresholds,
            "preset": preset,
        }

    def should_recheck(self, bot: Dict[str, Any]) -> bool:
        """
        Check if the gate should be rechecked (cooldown expired).

        Args:
            bot: Bot configuration dict

        Returns:
            True if recheck is needed
        """
        blocked_until = bot.get("_gate_blocked_until", 0)
        now = self._get_now_ts()
        return now >= blocked_until

    def set_blocked(self, bot: Dict[str, Any], reason: str) -> None:
        """
        Set the bot to blocked state.

        Args:
            bot: Bot configuration dict
            reason: Reason for blocking
        """
        now = self._get_now_ts()
        bot["_nlp_block_opening_orders"] = True
        bot["_gate_blocked_until"] = now + cfg.NEUTRAL_GATE_RECHECK_SECONDS
        bot["_gate_blocked_reason"] = reason

    def clear_blocked(self, bot: Dict[str, Any]) -> None:
        """
        Clear the blocked state from the bot.

        Args:
            bot: Bot configuration dict
        """
        bot["_nlp_block_opening_orders"] = False
        bot.pop("_gate_blocked_until", None)
        bot.pop("_gate_blocked_reason", None)

    def get_status(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the current gate status for a bot.

        Args:
            bot: Bot configuration dict

        Returns:
            {
                "blocked": bool,
                "reason": str,
                "blocked_until": float,
                "time_remaining": float,
            }
        """
        now = self._get_now_ts()
        blocked_until = bot.get("_gate_blocked_until", 0)
        blocked = bot.get("_nlp_block_opening_orders", False) and now < blocked_until

        return {
            "blocked": blocked,
            "reason": bot.get("_gate_blocked_reason", ""),
            "blocked_until": blocked_until,
            "time_remaining": max(0, blocked_until - now) if blocked else 0,
        }
