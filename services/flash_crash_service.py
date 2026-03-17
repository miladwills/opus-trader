"""
Bybit Control Center - Flash Crash Protection Service

Detects extreme price moves and auto-pauses all bots.
Resumes trading after volatility normalizes.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Flash crash state file path
FLASH_CRASH_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "storage",
    "flash_crash_state.json"
)


class FlashCrashService:
    """
    Service for detecting flash crashes and protecting running bots.
    """

    def __init__(
        self,
        indicator_service: Any = None,
        bot_storage: Any = None,
    ):
        """
        Initialize flash crash service.

        Args:
            indicator_service: IndicatorService for fetching price data
            bot_storage: BotStorageService for pausing/resuming bots
        """
        self.indicator_service = indicator_service
        self.bot_storage = bot_storage

    def _list_bots(self) -> List[Dict[str, Any]]:
        """Support both legacy and current bot storage interfaces."""
        if not self.bot_storage:
            return []
        if hasattr(self.bot_storage, "list_bots"):
            return self.bot_storage.list_bots()
        if hasattr(self.bot_storage, "get_bots"):
            return self.bot_storage.get_bots()
        return []

    def detect_flash_crash(
        self,
        symbol: str,
        candles: List[Dict[str, Any]],
        threshold_pct: float = 0.03,
        lookback_minutes: int = 5,
    ) -> Dict[str, Any]:
        """
        Detect if a flash crash has occurred based on price movement.

        Args:
            symbol: Trading symbol to check
            candles: Recent candle data (1m interval preferred)
            threshold_pct: Price change threshold to trigger (default 3%)
            lookback_minutes: Time window to check (default 5 minutes)

        Returns:
            Dict with:
            - triggered: bool - whether flash crash detected
            - price_change_pct: float - actual price change
            - direction: str - "up" or "down"
            - current_price: float
            - lookback_price: float
        """
        if not candles or len(candles) < lookback_minutes:
            return {
                "triggered": False,
                "price_change_pct": 0,
                "direction": "none",
                "current_price": 0,
                "lookback_price": 0,
                "reason": "Insufficient candle data",
            }

        # Get current price (last candle close)
        current_price = float(candles[-1].get("close", 0))

        # Get price from lookback_minutes ago
        lookback_index = max(0, len(candles) - lookback_minutes - 1)
        lookback_price = float(candles[lookback_index].get("close", 0))

        if lookback_price <= 0 or current_price <= 0:
            return {
                "triggered": False,
                "price_change_pct": 0,
                "direction": "none",
                "current_price": current_price,
                "lookback_price": lookback_price,
                "reason": "Invalid price data",
            }

        # Calculate price change
        price_change_pct = (current_price - lookback_price) / lookback_price
        direction = "up" if price_change_pct > 0 else "down"

        # Check if flash crash threshold exceeded
        triggered = abs(price_change_pct) >= threshold_pct

        return {
            "triggered": triggered,
            "price_change_pct": price_change_pct,
            "direction": direction,
            "current_price": current_price,
            "lookback_price": lookback_price,
            "reason": f"Price moved {abs(price_change_pct)*100:.2f}% in {lookback_minutes}m"
                      if triggered else "Normal volatility",
        }

    def is_volatility_normalized(
        self,
        indicators: Dict[str, Any],
        bbw_threshold: float = 0.05,
        rsi_low: float = 40,
        rsi_high: float = 60,
    ) -> Dict[str, Any]:
        """
        Check if market volatility has normalized after a flash crash.

        Conditions for normalization:
        - BBW% below threshold (default 5%)
        - RSI between low and high thresholds (default 40-60)

        Args:
            indicators: Current indicator values
            bbw_threshold: BBW% threshold for normalization
            rsi_low: Lower RSI bound
            rsi_high: Upper RSI bound

        Returns:
            Dict with:
            - normalized: bool - whether volatility is normalized
            - bbw: float - current BBW%
            - rsi: float - current RSI
            - reasons: List[str] - normalization status details
        """
        bbw = indicators.get("bbw_pct", 0)
        rsi = indicators.get("rsi", 50)
        reasons = []

        # Check BBW
        bbw_ok = bbw <= bbw_threshold
        if bbw_ok:
            reasons.append(f"BBW {bbw:.2%} <= {bbw_threshold:.2%} ✓")
        else:
            reasons.append(f"BBW {bbw:.2%} > {bbw_threshold:.2%} ✗")

        # Check RSI
        rsi_ok = rsi_low <= rsi <= rsi_high
        if rsi_ok:
            reasons.append(f"RSI {rsi:.1f} in range [{rsi_low}-{rsi_high}] ✓")
        else:
            reasons.append(f"RSI {rsi:.1f} outside range [{rsi_low}-{rsi_high}] ✗")

        normalized = bbw_ok and rsi_ok

        return {
            "normalized": normalized,
            "bbw": bbw,
            "rsi": rsi,
            "reasons": reasons,
        }

    def get_flash_crash_state(self) -> Dict[str, Any]:
        """
        Get current flash crash state from storage.

        Returns:
            Dict with flash crash status or default empty state
        """
        default_state = {
            "flash_crash_active": False,
            "triggered_at": None,
            "normalized_at": None,
            "affected_symbols": [],
            "trigger_details": {},
            "paused_bots": [],
        }

        try:
            if os.path.exists(FLASH_CRASH_STATE_FILE):
                with open(FLASH_CRASH_STATE_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read flash crash state: {e}")

        return default_state

    def save_flash_crash_state(self, state: Dict[str, Any]) -> bool:
        """
        Save flash crash state to storage.

        Args:
            state: Flash crash state dict

        Returns:
            True if saved successfully
        """
        try:
            # Ensure storage directory exists
            os.makedirs(os.path.dirname(FLASH_CRASH_STATE_FILE), exist_ok=True)

            with open(FLASH_CRASH_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"Failed to save flash crash state: {e}")
            return False

    def trigger_flash_crash(
        self,
        symbol: str,
        price_change_pct: float,
        direction: str,
    ) -> Dict[str, Any]:
        """
        Trigger flash crash protection - pause all running bots.

        Args:
            symbol: Symbol that triggered the flash crash
            price_change_pct: Price change that triggered
            direction: "up" or "down"

        Returns:
            Dict with trigger result and list of paused bots
        """
        paused_bots = []

        try:
            # Get all running bots
            if self.bot_storage:
                bots = self._list_bots()
                running_bots = [b for b in bots if b.get("status") == "running"]

                # Pause each running bot
                for bot in running_bots:
                    bot_id = bot.get("id")
                    try:
                        bot["status"] = "flash_crash_paused"
                        bot["flash_crash_paused_at"] = datetime.now(timezone.utc).isoformat()
                        self.bot_storage.save_bot(bot)
                        paused_bots.append(bot_id)
                        logger.warning(f"🚨 Flash crash: Paused bot {bot_id} ({bot.get('symbol')})")
                    except Exception as e:
                        logger.error(f"Failed to pause bot {bot_id}: {e}")

            # Save state
            state = {
                "flash_crash_active": True,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "normalized_at": None,
                "affected_symbols": [symbol],
                "trigger_details": {
                    "symbol": symbol,
                    "price_change_pct": price_change_pct,
                    "direction": direction,
                },
                "paused_bots": paused_bots,
            }
            self.save_flash_crash_state(state)

            logger.warning(
                f"🚨 FLASH CRASH PROTECTION ACTIVATED: {symbol} moved {price_change_pct*100:.2f}% {direction}. "
                f"Paused {len(paused_bots)} bots."
            )

            return {
                "success": True,
                "paused_bots": paused_bots,
                "state": state,
            }

        except Exception as e:
            logger.error(f"Failed to trigger flash crash protection: {e}")
            return {
                "success": False,
                "error": str(e),
                "paused_bots": paused_bots,
            }

    def resume_after_normalization(self) -> Dict[str, Any]:
        """
        Resume bots after volatility has normalized.

        Returns:
            Dict with resume result and list of resumed bots
        """
        resumed_bots = []

        try:
            state = self.get_flash_crash_state()

            if not state.get("flash_crash_active"):
                return {
                    "success": True,
                    "message": "No active flash crash",
                    "resumed_bots": [],
                }

            # Get bots that were paused by flash crash
            if self.bot_storage:
                bots = self._list_bots()
                paused_bots = [b for b in bots if b.get("status") == "flash_crash_paused"]

                # Resume each paused bot
                for bot in paused_bots:
                    bot_id = bot.get("id")
                    try:
                        bot["status"] = "running"
                        bot["flash_crash_resumed_at"] = datetime.now(timezone.utc).isoformat()
                        self.bot_storage.save_bot(bot)
                        resumed_bots.append(bot_id)
                        logger.info(f"✅ Flash crash normalized: Resumed bot {bot_id} ({bot.get('symbol')})")
                    except Exception as e:
                        logger.error(f"Failed to resume bot {bot_id}: {e}")

            # Update state
            state["flash_crash_active"] = False
            state["normalized_at"] = datetime.now(timezone.utc).isoformat()
            self.save_flash_crash_state(state)

            logger.info(
                f"✅ FLASH CRASH PROTECTION DEACTIVATED: Volatility normalized. "
                f"Resumed {len(resumed_bots)} bots."
            )

            return {
                "success": True,
                "resumed_bots": resumed_bots,
                "state": state,
            }

        except Exception as e:
            logger.error(f"Failed to resume after flash crash: {e}")
            return {
                "success": False,
                "error": str(e),
                "resumed_bots": resumed_bots,
            }

    def check_and_protect(
        self,
        symbol: str = "BTCUSDT",
    ) -> Dict[str, Any]:
        """
        Main entry point: Check for flash crash and take protective action.

        Args:
            symbol: Symbol to monitor (default BTCUSDT)

        Returns:
            Dict with check result
        """
        from config.strategy_config import (
            ENABLE_FLASH_CRASH_PROTECTION,
            FLASH_CRASH_THRESHOLD_PCT,
            FLASH_CRASH_LOOKBACK_MINUTES,
            FLASH_CRASH_NORMALIZE_BBW,
            FLASH_CRASH_NORMALIZE_RSI_LOW,
            FLASH_CRASH_NORMALIZE_RSI_HIGH,
        )

        if not ENABLE_FLASH_CRASH_PROTECTION:
            return {
                "action": "disabled",
                "message": "Flash crash protection is disabled",
            }

        state = self.get_flash_crash_state()

        # If flash crash is active, check for normalization
        if state.get("flash_crash_active"):
            # Fetch indicators
            if self.indicator_service:
                try:
                    indicators = self.indicator_service.compute_indicators(
                        symbol=symbol,
                        interval="5",
                        limit=50,
                    )

                    norm_result = self.is_volatility_normalized(
                        indicators=indicators,
                        bbw_threshold=FLASH_CRASH_NORMALIZE_BBW,
                        rsi_low=FLASH_CRASH_NORMALIZE_RSI_LOW,
                        rsi_high=FLASH_CRASH_NORMALIZE_RSI_HIGH,
                    )

                    if norm_result.get("normalized"):
                        resume_result = self.resume_after_normalization()
                        return {
                            "action": "resumed",
                            "result": resume_result,
                            "normalization": norm_result,
                        }
                    else:
                        return {
                            "action": "still_active",
                            "message": "Flash crash still active, waiting for normalization",
                            "normalization": norm_result,
                        }

                except Exception as e:
                    logger.warning(f"Failed to check normalization: {e}")
                    return {
                        "action": "error",
                        "error": str(e),
                    }

        # No active flash crash - check for new one
        if self.indicator_service:
            try:
                # Fetch 1-minute candles for flash crash detection
                candles = self.indicator_service.get_ohlcv(
                    symbol=symbol,
                    interval="1",
                    limit=FLASH_CRASH_LOOKBACK_MINUTES + 5,
                )

                if candles:
                    crash_result = self.detect_flash_crash(
                        symbol=symbol,
                        candles=candles,
                        threshold_pct=FLASH_CRASH_THRESHOLD_PCT,
                        lookback_minutes=FLASH_CRASH_LOOKBACK_MINUTES,
                    )

                    if crash_result.get("triggered"):
                        trigger_result = self.trigger_flash_crash(
                            symbol=symbol,
                            price_change_pct=crash_result.get("price_change_pct"),
                            direction=crash_result.get("direction"),
                        )
                        return {
                            "action": "triggered",
                            "detection": crash_result,
                            "result": trigger_result,
                        }
                    else:
                        return {
                            "action": "normal",
                            "message": "No flash crash detected",
                            "detection": crash_result,
                        }

            except Exception as e:
                logger.warning(f"Failed to check for flash crash: {e}")
                return {
                    "action": "error",
                    "error": str(e),
                }

        return {
            "action": "no_data",
            "message": "No indicator service available",
        }
