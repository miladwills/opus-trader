"""
Bybit Control Center - Stop Loss Service

Automatic, adaptive stop-loss calculation and management.
SL derived from volatility, grid range, risk profile, and account equity.
100% automatic - no manual per-symbol configuration required.
"""

from typing import Dict, Any, Optional
import logging

from services.position_mode_helper import resolve_position_idx

logger = logging.getLogger(__name__)


class StopLossService:
    """
    Service for calculating and managing automatic adaptive stop-loss levels.
    """

    def __init__(
        self,
        bybit_client: Any,
        safe_atr_multiplier: float = 1.5,
        normal_atr_multiplier: float = 2.0,
        aggressive_atr_multiplier: float = 2.5,
        min_sl_distance_pct: float = 0.02,
        max_sl_distance_pct: float = 0.15,
    ):
        """
        Initialize stop-loss service.

        Args:
            bybit_client: BybitClient for placing SL orders
            safe_atr_multiplier: ATR multiplier for SAFE profile
            normal_atr_multiplier: ATR multiplier for NORMAL profile
            aggressive_atr_multiplier: ATR multiplier for AGGRESSIVE profile
            min_sl_distance_pct: Minimum SL distance from price (2% default)
            max_sl_distance_pct: Maximum SL distance from price (15% default)
        """
        self.client = bybit_client
        self.safe_atr_multiplier = safe_atr_multiplier
        self.normal_atr_multiplier = normal_atr_multiplier
        self.aggressive_atr_multiplier = aggressive_atr_multiplier
        self.min_sl_distance_pct = min_sl_distance_pct
        self.max_sl_distance_pct = max_sl_distance_pct

    def calculate_stop_loss(
        self,
        symbol: str,
        mode: str,
        current_price: float,
        grid_lower: float,
        grid_upper: float,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
        profile: str = "normal",
        bot_investment: float = 0,
        bot_leverage: float = 1,
        account_equity: float = 0,
        position_side: Optional[str] = None,
        actual_entry_price: float = 0,
    ) -> Dict[str, Any]:
        """
        Calculate automatic adaptive stop-loss level.

        Strategy:
        1. For neutral/long modes: SL below grid lower boundary
        2. For short mode: SL above grid upper boundary
        3. Distance from boundary = N × ATR (N depends on profile)
        4. Alternative: Max loss % of bot capital (whichever is stricter)
        5. Clamp between min/max distance from current price

        Args:
            symbol: Trading symbol
            mode: Bot mode (neutral, long, short, scalp_pnl, scalp_market)
            current_price: Current market price
            grid_lower: Grid lower boundary
            grid_upper: Grid upper boundary
            atr_pct: ATR as % of price
            bbw_pct: Bollinger Band Width %
            profile: Risk profile (safe, normal, aggressive)
            bot_investment: Bot investment in USDT
            bot_leverage: Bot leverage
            account_equity: Total account equity

        Returns:
            Dict with:
            - sl_price: Stop-loss price level
            - sl_distance_pct: Distance from current price (%)
            - sl_method: Calculation method used
            - reasons: List of calculation steps
            - enabled: Whether SL should be enabled
        """
        reasons = []
        sl_price = None
        sl_method = "none"
        enabled = False

        # =====================================================================
        # STEP 1: Determine ATR multiplier based on profile
        # =====================================================================
        if profile.lower() == "safe":
            atr_multiplier = self.safe_atr_multiplier
        elif profile.lower() == "aggressive":
            atr_multiplier = self.aggressive_atr_multiplier
        else:
            atr_multiplier = self.normal_atr_multiplier

        reasons.append(f"Profile={profile}, ATR_multiplier={atr_multiplier}")

        # =====================================================================
        # STEP 2: Calculate volatility-based SL distance
        # =====================================================================
        # Use ATR% or BBW% (prefer ATR, fallback to BBW)
        volatility_pct = atr_pct if atr_pct is not None else bbw_pct

        if volatility_pct is None:
            reasons.append("No volatility data available - SL disabled")
            return {
                "sl_price": None,
                "sl_distance_pct": None,
                "sl_method": "disabled_no_volatility",
                "reasons": reasons,
                "enabled": False,
            }

        # Calculate SL distance based on volatility
        sl_distance_from_boundary_pct = volatility_pct * atr_multiplier

        # Clamp to min/max
        sl_distance_from_boundary_pct = max(
            self.min_sl_distance_pct,
            min(sl_distance_from_boundary_pct, self.max_sl_distance_pct)
        )

        reasons.append(
            f"Volatility={volatility_pct:.4f}, "
            f"SL_distance_from_boundary={sl_distance_from_boundary_pct:.4f}"
        )

        # =====================================================================
        # STEP 3: Calculate SL price based on mode
        # =====================================================================
        if mode in ("neutral", "long"):
            # SL below grid lower boundary
            sl_price = grid_lower * (1 - sl_distance_from_boundary_pct)
            sl_method = "below_grid_lower"
            reasons.append(
                f"Mode={mode}: SL below lower bound "
                f"({grid_lower:.8f} × {1 - sl_distance_from_boundary_pct:.6f})"
            )

        elif mode == "short":
            # SL above grid upper boundary
            sl_price = grid_upper * (1 + sl_distance_from_boundary_pct)
            sl_method = "above_grid_upper"
            reasons.append(
                f"Mode={mode}: SL above upper bound "
                f"({grid_upper:.8f} × {1 + sl_distance_from_boundary_pct:.6f})"
            )

        elif mode in ("scalp_pnl", "scalp_market"):
            # Scalp modes: Tight SL very close to current price
            # Use smaller multiplier for scalp modes
            scalp_multiplier = atr_multiplier * 0.5  # Half the normal multiplier
            scalp_sl_distance = volatility_pct * scalp_multiplier
            scalp_sl_distance = max(0.01, min(scalp_sl_distance, 0.05))  # 1-5% max

            normalized_position_side = str(position_side or "").strip().lower()
            if normalized_position_side == "buy":
                sl_price = current_price * (1 - scalp_sl_distance)
                sl_method = "scalp_below_price"
            elif normalized_position_side == "sell":
                sl_price = current_price * (1 + scalp_sl_distance)
                sl_method = "scalp_above_price"
            else:
                # Fallback only when the live position side is unavailable.
                mid_price = (grid_lower + grid_upper) / 2
                if current_price > mid_price:
                    sl_price = current_price * (1 - scalp_sl_distance)
                    sl_method = "scalp_below_price"
                else:
                    sl_price = current_price * (1 + scalp_sl_distance)
                    sl_method = "scalp_above_price"

            reasons.append(
                f"Mode={mode}: Tight scalp SL at {scalp_sl_distance:.4f} from price"
            )

        else:
            reasons.append(f"Unknown mode={mode} - SL disabled")
            return {
                "sl_price": None,
                "sl_distance_pct": None,
                "sl_method": "disabled_unknown_mode",
                "reasons": reasons,
                "enabled": False,
            }

        # =====================================================================
        # STEP 3b: Clamp final SL distance from CURRENT PRICE
        # =====================================================================
        # The boundary-based clamp above guards the offset from the grid edge,
        # but when price diverges far from the boundary the resulting SL can
        # exceed the configured max distance from current price.
        if sl_price and current_price > 0 and mode not in ("scalp_pnl", "scalp_market"):
            final_distance = abs(sl_price - current_price) / current_price
            if final_distance > self.max_sl_distance_pct:
                if mode in ("neutral", "long"):
                    sl_price = current_price * (1 - self.max_sl_distance_pct)
                elif mode == "short":
                    sl_price = current_price * (1 + self.max_sl_distance_pct)
                sl_method = "price_distance_clamped"
                reasons.append(
                    f"SL distance {final_distance:.4f} exceeded max "
                    f"{self.max_sl_distance_pct:.4f} — clamped to current price"
                )
            elif final_distance < self.min_sl_distance_pct:
                if mode in ("neutral", "long"):
                    sl_price = current_price * (1 - self.min_sl_distance_pct)
                elif mode == "short":
                    sl_price = current_price * (1 + self.min_sl_distance_pct)
                sl_method = "price_distance_floor"
                reasons.append(
                    f"SL distance {final_distance:.4f} below min "
                    f"{self.min_sl_distance_pct:.4f} — floored to current price"
                )

        # =====================================================================
        # STEP 4: Alternative calculation - Max loss % of bot capital
        # =====================================================================
        # Ensure SL doesn't allow more than X% loss of bot capital
        # This acts as a backup limit
        if bot_investment > 0 and bot_leverage > 0:
            bot_capital = bot_investment * bot_leverage
            max_loss_pct = 0.10 if profile.lower() == "safe" else 0.15  # 10% or 15% max loss

            # H4 audit: use actual entry price from position avgPrice when available,
            # and divide max_loss_pct by leverage to get effective max price move.
            actual_entry = float(actual_entry_price or 0)
            approx_entry = actual_entry if actual_entry > 0 else (grid_lower + grid_upper) / 2
            effective_max_loss_pct = max_loss_pct / max(bot_leverage, 1.0)

            if mode in ("neutral", "long"):
                max_loss_price = approx_entry * (1 - effective_max_loss_pct)
                # Use stricter of the two (higher SL price = closer to entry)
                if max_loss_price > sl_price:
                    sl_price = max_loss_price
                    sl_method = "max_loss_limit"
                    reasons.append(
                        f"Applied max_loss_limit: {max_loss_pct:.1%} of capital = ${max_loss_price:.8f}"
                    )

            elif mode == "short":
                max_loss_price = approx_entry * (1 + effective_max_loss_pct)
                # Use stricter of the two (lower SL price = closer to entry)
                if max_loss_price < sl_price:
                    sl_price = max_loss_price
                    sl_method = "max_loss_limit"
                    reasons.append(
                        f"Applied max_loss_limit: {max_loss_pct:.1%} of capital = ${max_loss_price:.8f}"
                    )

        # =====================================================================
        # STEP 5: Calculate final distance from current price
        # =====================================================================
        if sl_price and current_price > 0:
            sl_distance_pct = abs(sl_price - current_price) / current_price
            enabled = True

            reasons.append(
                f"Final SL: ${sl_price:.8f} "
                f"({sl_distance_pct:.2%} from current price ${current_price:.8f})"
            )
        else:
            sl_distance_pct = None
            enabled = False

        return {
            "sl_price": sl_price,
            "sl_distance_pct": sl_distance_pct,
            "sl_method": sl_method,
            "reasons": reasons,
            "enabled": enabled,
        }

    def set_stop_loss(
        self,
        symbol: str,
        position_side: str,
        sl_price: float,
        tick_size: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Set stop-loss on Bybit via trading-stop endpoint.

        Args:
            symbol: Trading symbol
            position_side: Position side ("Buy" or "Sell")
            sl_price: Stop-loss price
            tick_size: Price tick size for rounding

        Returns:
            Dict with success status and result
        """
        try:
            pmode_resp = self.client.get_position_mode(symbol=symbol) if hasattr(self.client, "get_position_mode") else {"success": False}
            if pmode_resp.get("success"):
                position_mode = pmode_resp.get("mode")
            else:
                position_mode = None

            # Round SL price to tick size
            sl_price_rounded = round(sl_price / tick_size) * tick_size
            sl_price_str = f"{sl_price_rounded:.8f}".rstrip('0').rstrip('.')

            # Call Bybit set_trading_stop (if method exists)
            if hasattr(self.client, 'set_trading_stop'):
                position_idx = resolve_position_idx(position_mode, position_side, reduce_only=True)
                if position_mode is None:
                    return {"success": False, "error": "position_mode_unknown"}
                if position_idx is None:
                    position_idx = 0  # one-way

                result = self.client.set_trading_stop(
                    symbol=symbol,
                    position_idx=position_idx,
                    stop_loss=sl_price_str,
                )

                if result.get("success"):
                    logger.info(
                        f"✅ Set SL for {symbol} ({position_side}): ${sl_price_str}"
                    )
                    return {
                        "success": True,
                        "sl_price": sl_price_rounded,
                        "result": result,
                    }
                else:
                    logger.warning(
                        f"⚠️ Failed to set SL for {symbol}: {result.get('error')}"
                    )
                    return {
                        "success": False,
                        "error": result.get("error"),
                    }
            else:
                logger.warning(
                    f"⚠️ set_trading_stop method not available on client"
                )
                return {
                    "success": False,
                    "error": "set_trading_stop method not implemented",
                }

        except Exception as e:
            logger.error(f"❌ Exception setting SL for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def should_update_stop_loss(
        self,
        current_sl: Optional[float],
        new_sl: Optional[float],
        current_price: float,
        threshold_pct: float = 0.02,
    ) -> bool:
        """
        Determine if SL should be updated (avoid excessive updates).

        Args:
            current_sl: Current stop-loss price
            new_sl: Newly calculated stop-loss price
            current_price: Current market price
            threshold_pct: Minimum change threshold (2% default)

        Returns:
            True if SL should be updated
        """
        if current_sl is None and new_sl is not None:
            return True  # No SL set, should set one

        if current_sl is not None and new_sl is None:
            return False  # Don't remove existing SL

        if current_sl is None and new_sl is None:
            return False  # Nothing to do

        # Calculate change percentage
        if current_price > 0:
            change_pct = abs(new_sl - current_sl) / current_price
            return change_pct >= threshold_pct

        return False

    def calculate_trailing_stop_loss(
        self,
        symbol: str,
        position_side: str,
        entry_price: float,
        current_price: float,
        current_sl: Optional[float],
        atr_pct: Optional[float] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate trailing stop-loss level for a profitable position.

        The trailing SL follows price at a fixed distance, locking in profits.
        It only moves in the profitable direction (never backwards).

        For LONG positions:
        - Trail SL below current price
        - SL can only move UP (never down)
        - Activates after position reaches activation_pct profit

        For SHORT positions:
        - Trail SL above current price
        - SL can only move DOWN (never up)
        - Activates after position reaches activation_pct profit

        Args:
            symbol: Trading symbol
            position_side: Position side ("Buy" for long, "Sell" for short)
            entry_price: Position entry price
            current_price: Current market price
            current_sl: Current stop-loss price (if set)
            atr_pct: Current ATR as percentage of price (for ATR-based trailing)
            config: Trailing SL configuration dict with:
                - activation_pct: Profit % required to activate trailing (default 0.5%)
                - distance_pct: Trail distance % behind price (default 0.3%)
                - step_pct: Minimum price movement to update SL (default 0.1%)
                - use_atr: Use ATR-based distance instead of fixed % (default True)
                - atr_multiplier: ATR multiplier for trail distance (default 1.0)

        Returns:
            Dict with:
            - should_update: bool - whether to update SL
            - new_sl_price: float - new trailing SL price (or None)
            - profit_pct: float - current profit percentage
            - trail_distance_pct: float - actual trail distance used
            - reason: str - explanation of result
        """
        # Import defaults from config
        from config.strategy_config import (
            TRAILING_SL_ACTIVATION_PCT,
            TRAILING_SL_DISTANCE_PCT,
            TRAILING_SL_STEP_PCT,
            TRAILING_SL_USE_ATR,
            TRAILING_SL_ATR_MULTIPLIER,
        )

        # Use provided config or defaults
        cfg = config or {}
        activation_pct = cfg.get("activation_pct", TRAILING_SL_ACTIVATION_PCT)
        distance_pct = cfg.get("distance_pct", TRAILING_SL_DISTANCE_PCT)
        step_pct = cfg.get("step_pct", TRAILING_SL_STEP_PCT)
        use_atr = cfg.get("use_atr", TRAILING_SL_USE_ATR)
        atr_multiplier = cfg.get("atr_multiplier", TRAILING_SL_ATR_MULTIPLIER)

        # Validate inputs
        if entry_price <= 0 or current_price <= 0:
            return {
                "should_update": False,
                "new_sl_price": None,
                "profit_pct": 0,
                "trail_distance_pct": distance_pct,
                "reason": "Invalid entry or current price",
            }

        # Calculate profit percentage
        is_long = position_side == "Buy"
        if is_long:
            profit_pct = round((current_price - entry_price) / entry_price, 6)
        else:
            profit_pct = round((entry_price - current_price) / entry_price, 6)

        # Check if trailing is activated (position must be profitable enough)
        if profit_pct < activation_pct:
            return {
                "should_update": False,
                "new_sl_price": None,
                "profit_pct": profit_pct,
                "trail_distance_pct": distance_pct,
                "reason": f"Profit {profit_pct:.2%} < activation threshold {activation_pct:.2%}",
            }

        # Calculate trail distance
        if use_atr and atr_pct is not None and atr_pct > 0:
            # Use ATR-based distance
            trail_distance = atr_pct * atr_multiplier
            # Clamp between 0.2% and 3%
            trail_distance = max(0.002, min(trail_distance, 0.03))
        else:
            # Use fixed percentage
            trail_distance = distance_pct

        # Calculate new trailing SL price
        if is_long:
            new_sl = current_price * (1 - trail_distance)
        else:
            new_sl = current_price * (1 + trail_distance)

        # Check if SL should be updated (only move in profitable direction)
        should_update = False
        reason = ""

        if current_sl is None or current_sl <= 0:
            # No SL set yet - set it
            should_update = True
            reason = f"Setting initial trailing SL at ${new_sl:.4f}"

        elif is_long:
            # Long position: SL can only move UP
            if new_sl > current_sl:
                # Check minimum step size
                step_change = (new_sl - current_sl) / current_price
                if step_change >= step_pct:
                    should_update = True
                    reason = f"Moving SL up: ${current_sl:.4f} -> ${new_sl:.4f} (+{step_change:.2%})"
                else:
                    reason = f"Step change {step_change:.2%} < minimum {step_pct:.2%}"
            else:
                reason = f"SL would move down (${current_sl:.4f} -> ${new_sl:.4f}), keeping current"

        else:
            # Short position: SL can only move DOWN
            if new_sl < current_sl:
                # Check minimum step size
                step_change = (current_sl - new_sl) / current_price
                if step_change >= step_pct:
                    should_update = True
                    reason = f"Moving SL down: ${current_sl:.4f} -> ${new_sl:.4f} (-{step_change:.2%})"
                else:
                    reason = f"Step change {step_change:.2%} < minimum {step_pct:.2%}"
            else:
                reason = f"SL would move up (${current_sl:.4f} -> ${new_sl:.4f}), keeping current"

        return {
            "should_update": should_update,
            "new_sl_price": new_sl if should_update else None,
            "profit_pct": profit_pct,
            "trail_distance_pct": trail_distance,
            "reason": reason,
        }
