"""
Neutral Loss Prevention Service for neutral_classic_bybit mode.

Implements loss-prevention features to prevent inventory accumulation
and breakout losses:
- Breakout Guard: Detect range breakouts, flatten positions
- Inventory Cap: Limit net exposure, block orders that worsen skew
- Recenter Logic: Rebuild grid around current price
- Max Loss Stop: Hard uPnL-based emergency exit
- Momentum Filter: Block neutral mode during strong trends
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.strategy_config import (
    # Breakout Guard
    NEUTRAL_BREAKOUT_GUARD_ENABLED,
    NEUTRAL_BREAKOUT_THRESHOLD_PCT,
    NEUTRAL_BREAKOUT_HOLD_SECONDS,
    NEUTRAL_BREAKOUT_CANDLE_CONFIRM,
    NEUTRAL_BREAKOUT_COOLDOWN_SEC,
    NEUTRAL_BREAKOUT_FLATTEN_ON_TRIGGER,
    # Inventory Cap
    NEUTRAL_INVENTORY_CAP_ENABLED,
    NEUTRAL_INVENTORY_CAP_PCT,
    NEUTRAL_INVENTORY_EMERGENCY_MULT,
    NEUTRAL_INVENTORY_REDUCE_TO_PCT,
    NEUTRAL_HEDGE_LEG_CAP_ENABLED,
    # Recenter
    NEUTRAL_RECENTER_ENABLED,
    NEUTRAL_RECENTER_MID_DEVIATION_PCT,
    NEUTRAL_RECENTER_INTERVAL_SEC,
    NEUTRAL_RECENTER_ON_BOUNDARY_TOUCH,
    NEUTRAL_RECENTER_COOLDOWN_SEC,
    # Max Loss
    NEUTRAL_MAX_LOSS_ENABLED,
    NEUTRAL_MAX_LOSS_USD,
    NEUTRAL_MAX_LOSS_PCT,
    NEUTRAL_MAX_LOSS_USE_PCT,
    NEUTRAL_MAX_LOSS_COOLDOWN_SEC,
    # Momentum Filter
    NEUTRAL_MOMENTUM_FILTER_ENABLED,
    NEUTRAL_MOMENTUM_ADX_THRESHOLD,
    NEUTRAL_MOMENTUM_RSI_UPPER,
    NEUTRAL_MOMENTUM_RSI_LOWER,
    NEUTRAL_MOMENTUM_BB_TOUCH_FILTER,
    NEUTRAL_MOMENTUM_BLOCK_ACTION,
    NEUTRAL_MOMENTUM_TIGHTEN_CAP_MULT,
    # Presets
    NEUTRAL_PRESET_ENABLED,
    NEUTRAL_PRESETS,
    NEUTRAL_DEFAULT_PRESET,
    NEUTRAL_MAJOR_SYMBOLS,
)
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.order_ownership_service import build_order_ownership_snapshot

logger = logging.getLogger(__name__)


class NeutralLossPreventionService:
    """
    Loss-prevention features for neutral_classic_bybit mode.

    Provides protection against:
    - Breakout losses when price exits grid range
    - Inventory accumulation (one-sided exposure)
    - Stale grids that drift from current price
    - Large unrealized losses
    - Trading during strong momentum (unsuitable for neutral)
    """

    def __init__(
        self,
        client,
        bot_storage,
        indicator_service=None,
        neutral_grid_service=None,
    ):
        """
        Initialize with required dependencies.

        Args:
            client: BybitClient instance for API calls
            bot_storage: BotStorageService for persisting bot state
            indicator_service: Optional IndicatorService for momentum filter
            neutral_grid_service: Optional NeutralGridService for grid operations
        """
        self.client = client
        self.bot_storage = bot_storage
        self.indicator_service = indicator_service
        self.neutral_grid_service = neutral_grid_service
        self.audit_diagnostics_service = AuditDiagnosticsService()

    def _record_exit_reason(
        self,
        bot: Dict[str, Any],
        *,
        symbol: str,
        reason: str,
        severity: str = "WARN",
        **fields: Any,
    ) -> None:
        if not self.audit_diagnostics_service.enabled():
            return
        payload = {
            "event_type": "exit_reason",
            "severity": severity,
            "symbol": symbol,
            "bot_id": bot.get("id"),
            "mode": bot.get("mode"),
            "reason": str(reason or "").strip().lower(),
        }
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        self.audit_diagnostics_service.record_event(
            payload,
            throttle_key=(
                f"nlp_exit:{bot.get('id')}:{payload['reason']}:{time.time_ns()}"
            ),
            throttle_sec=0,
        )

    def _get_now_ts(self) -> float:
        """Get current timestamp (allows for mocking in tests)."""
        if hasattr(self.client, "_get_now_ts"):
            return self.client._get_now_ts()
        return time.time()

    def _get_nlp_state(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        """Get or initialize loss-prevention state from bot dict."""
        if "_nlp_state" not in bot:
            bot["_nlp_state"] = {}
        return bot["_nlp_state"]

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _get_symbol_positions(
        self,
        symbol: str,
        *,
        skip_cache: bool = True,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return fresh non-empty symbol positions when available."""
        try:
            positions_resp = self.client.get_positions(skip_cache=skip_cache)
        except TypeError:
            positions_resp = self.client.get_positions()
        if not positions_resp.get("success"):
            return None
        positions = (positions_resp.get("data") or {}).get("list") or []
        active_positions: List[Dict[str, Any]] = []
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            if self._safe_float(pos.get("size"), 0.0) <= 0:
                continue
            active_positions.append(pos)
        return active_positions

    def _get_symbol_open_orders(
        self,
        symbol: str,
        *,
        skip_cache: bool = True,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return fresh symbol open orders when available."""
        try:
            orders_resp = self.client.get_open_orders(
                symbol=symbol,
                limit=200,
                skip_cache=skip_cache,
            )
        except TypeError:
            orders_resp = self.client.get_open_orders(symbol=symbol, limit=200)
        if not orders_resp.get("success"):
            return None
        return (orders_resp.get("data") or {}).get("list") or []

    def _verify_protection_execution(
        self,
        symbol: str,
        *,
        require_flatten: bool,
    ) -> Dict[str, Any]:
        """
        Confirm that symbol orders are cancelled and, when required, positions are flat.
        """
        open_orders = self._get_symbol_open_orders(symbol, skip_cache=True)
        open_positions = self._get_symbol_positions(symbol, skip_cache=True)
        verification_error = None
        if open_orders is None or open_positions is None:
            verification_error = "fresh_state_unavailable"
            open_orders = open_orders or []
            open_positions = open_positions or []
        confirmed = not open_orders and (not require_flatten or not open_positions)
        if verification_error:
            confirmed = False
        return {
            "confirmed": confirmed,
            "verification_error": verification_error,
            "open_orders_remaining": len(open_orders),
            "open_positions_remaining": len(open_positions),
            "position_sizes": [
                self._safe_float(pos.get("size"), 0.0) for pos in open_positions
            ],
        }

    # =========================================================================
    # PRESET CONFIGURATION
    # =========================================================================

    def get_preset_for_symbol(self, symbol: str) -> str:
        """
        Determine the appropriate preset for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")

        Returns:
            Preset name ("MAJOR" or "MEME")
        """
        if symbol in NEUTRAL_MAJOR_SYMBOLS:
            return "MAJOR"
        return "MEME"

    def apply_preset(self, preset_name: str) -> Dict[str, Any]:
        """
        Get preset configuration values.

        Args:
            preset_name: Preset name ("MAJOR" or "MEME")

        Returns:
            Preset configuration dict with all threshold values
        """
        if not NEUTRAL_PRESET_ENABLED:
            return {}
        return NEUTRAL_PRESETS.get(
            preset_name, NEUTRAL_PRESETS.get(NEUTRAL_DEFAULT_PRESET, {})
        )

    def get_config_value(self, bot: Dict[str, Any], key: str, default: Any) -> Any:
        """
        Get config value, checking bot preset first, then global config.

        This allows preset-specific overrides for various thresholds.

        Args:
            bot: Bot configuration dict
            key: Configuration key (e.g., "breakout_threshold_pct")
            default: Default value if not found in preset

        Returns:
            Configuration value from preset or default
        """
        if not NEUTRAL_PRESET_ENABLED:
            return default

        preset_name = bot.get("neutral_preset")
        if not preset_name:
            symbol = bot.get("symbol", "")
            preset_name = self.get_preset_for_symbol(symbol)

        preset = NEUTRAL_PRESETS.get(preset_name, {})
        return preset.get(key, default)

    def get_effective_config(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get all effective configuration values for a bot.

        Merges preset values with global defaults.

        Args:
            bot: Bot configuration dict

        Returns:
            Dict with all effective configuration values
        """
        preset_name = bot.get("neutral_preset")
        if not preset_name:
            symbol = bot.get("symbol", "")
            preset_name = self.get_preset_for_symbol(symbol)

        preset = self.apply_preset(preset_name)

        return {
            # Breakout Guard
            "breakout_threshold_pct": preset.get(
                "breakout_threshold_pct", NEUTRAL_BREAKOUT_THRESHOLD_PCT
            ),
            "breakout_hold_seconds": preset.get(
                "breakout_hold_seconds", NEUTRAL_BREAKOUT_HOLD_SECONDS
            ),
            "breakout_cooldown_sec": preset.get(
                "breakout_cooldown_sec", NEUTRAL_BREAKOUT_COOLDOWN_SEC
            ),
            "breakout_candle_confirm": preset.get(
                "breakout_candle_confirm", NEUTRAL_BREAKOUT_CANDLE_CONFIRM
            ),
            "breakout_flatten_on_trigger": preset.get(
                "breakout_flatten_on_trigger", NEUTRAL_BREAKOUT_FLATTEN_ON_TRIGGER
            ),
            # Inventory Cap
            "inventory_cap_pct": preset.get(
                "inventory_cap_pct", NEUTRAL_INVENTORY_CAP_PCT
            ),
            "inventory_emergency_mult": preset.get(
                "inventory_emergency_mult", NEUTRAL_INVENTORY_EMERGENCY_MULT
            ),
            "inventory_reduce_to_pct": preset.get(
                "inventory_reduce_to_pct", NEUTRAL_INVENTORY_REDUCE_TO_PCT
            ),
            "inventory_hedge_leg_cap_enabled": preset.get(
                "inventory_hedge_leg_cap_enabled", NEUTRAL_HEDGE_LEG_CAP_ENABLED
            ),
            # Max Loss
            "max_loss_pct": preset.get("max_loss_pct", NEUTRAL_MAX_LOSS_PCT),
            "max_loss_usd": preset.get("max_loss_usd", NEUTRAL_MAX_LOSS_USD),
            "max_loss_use_pct": preset.get(
                "max_loss_use_pct", NEUTRAL_MAX_LOSS_USE_PCT
            ),
            "max_loss_cooldown_sec": preset.get(
                "max_loss_cooldown_sec", NEUTRAL_MAX_LOSS_COOLDOWN_SEC
            ),
            # Momentum Filter
            "momentum_adx_threshold": preset.get(
                "momentum_adx_threshold", NEUTRAL_MOMENTUM_ADX_THRESHOLD
            ),
            "momentum_rsi_upper": preset.get(
                "momentum_rsi_upper", NEUTRAL_MOMENTUM_RSI_UPPER
            ),
            "momentum_rsi_lower": preset.get(
                "momentum_rsi_lower", NEUTRAL_MOMENTUM_RSI_LOWER
            ),
            "momentum_bb_touch_filter": preset.get(
                "momentum_bb_touch_filter", NEUTRAL_MOMENTUM_BB_TOUCH_FILTER
            ),
            "momentum_block_action": preset.get(
                "momentum_block_action", NEUTRAL_MOMENTUM_BLOCK_ACTION
            ),
            # Recenter
            "recenter_mid_deviation_pct": preset.get(
                "recenter_mid_deviation_pct", NEUTRAL_RECENTER_MID_DEVIATION_PCT
            ),
            "recenter_interval_sec": preset.get(
                "recenter_interval_sec", NEUTRAL_RECENTER_INTERVAL_SEC
            ),
            "recenter_cooldown_sec": preset.get(
                "recenter_cooldown_sec", NEUTRAL_RECENTER_COOLDOWN_SEC
            ),
            "recenter_on_boundary_touch": preset.get(
                "recenter_on_boundary_touch", NEUTRAL_RECENTER_ON_BOUNDARY_TOUCH
            ),
            # Preset info
            "preset_name": preset_name,
        }

    def _generate_emergency_order_link_id(
        self, bot: Dict[str, Any], action: str, position_idx: int
    ) -> str:
        """
        Generate unique orderLinkId for emergency orders (hedge-safe).

        Format: nlp:{bot_id_12}:{action}:{pidx}:{ms_last10}:{c2}
        - bot_id_12: First 12 chars of bot ID (no dashes)
        - action: Short action code (BRK=breakout, INV=inventory, MAX=max_loss)
        - pidx: positionIdx (0=one-way, 1=hedge long, 2=hedge short)
        - ms_last10: Last 10 digits of millisecond timestamp
        - c2: 2-digit counter (00-99, wraps) for same-ms collision protection

        Total length: 36 chars (Bybit orderLinkId limit)

        Args:
            bot: Bot configuration dict
            action: Action code (BRK, INV, MAX)
            position_idx: Position index (0, 1, or 2)

        Returns:
            orderLinkId string for the emergency order
        """
        bot_id = bot.get("id", "unknown")
        bot_id_12 = bot_id.replace("-", "")[:12]

        # Millisecond timestamp (last 10 digits)
        now_ms = int(self._get_now_ts() * 1000)
        ms_suffix = str(now_ms)[-10:]

        # Per-bot counter (00-99, wraps) for same-ms collision protection
        nlp_state = self._get_nlp_state(bot)
        counter = nlp_state.get("emergency_olid_counter", 0)
        nlp_state["emergency_olid_counter"] = (counter + 1) % 100

        return f"nlp:{bot_id_12}:{action}:{position_idx}:{ms_suffix}:{counter:02d}"

    # =========================================================================
    # FEATURE A: Breakout Guard
    # =========================================================================

    def check_breakout_guard(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mark_price: float,
        candles_1m: Optional[List[Dict[str, Any]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if price has broken out of grid range.

        Triggers on either:
        1. Price outside range by threshold_pct for hold_seconds
        2. N consecutive 1m candle closes outside range

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            mark_price: Current mark price
            candles_1m: Optional 1-minute candle data for candle-close detection
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with triggered, side, action, reason
        """
        if not NEUTRAL_BREAKOUT_GUARD_ENABLED:
            return {
                "triggered": False,
                "side": None,
                "action": None,
                "reason": "disabled",
            }

        # Use preset config or fall back to global defaults
        if config is None:
            config = self.get_effective_config(bot)

        threshold_pct = config.get(
            "breakout_threshold_pct", NEUTRAL_BREAKOUT_THRESHOLD_PCT
        )
        hold_seconds = config.get(
            "breakout_hold_seconds", NEUTRAL_BREAKOUT_HOLD_SECONDS
        )
        candle_confirm = config.get(
            "breakout_candle_confirm", NEUTRAL_BREAKOUT_CANDLE_CONFIRM
        )
        flatten_on_trigger = config.get(
            "breakout_flatten_on_trigger", NEUTRAL_BREAKOUT_FLATTEN_ON_TRIGGER
        )

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()

        # Check if in cooldown
        cooldown_until = nlp_state.get("breakout_cooldown_until")
        if cooldown_until and now_ts < cooldown_until:
            return {
                "triggered": False,
                "side": None,
                "action": "in_cooldown",
                "reason": f"cooldown_remaining={int(cooldown_until - now_ts)}s",
            }

        # Get grid bounds
        neutral_grid = bot.get("neutral_grid") or {}
        lower_price = self._safe_float(
            neutral_grid.get("lower_price")
            or bot.get("grid_lower_price")
            or bot.get("lower_price"),
            0,
        )
        upper_price = self._safe_float(
            neutral_grid.get("upper_price")
            or bot.get("grid_upper_price")
            or bot.get("upper_price"),
            0,
        )

        if lower_price <= 0 or upper_price <= 0 or upper_price <= lower_price:
            return {
                "triggered": False,
                "side": None,
                "action": None,
                "reason": "invalid_bounds",
            }

        # Calculate breakout thresholds using preset config
        breakout_upper = upper_price * (1 + threshold_pct)
        breakout_lower = lower_price * (1 - threshold_pct)

        # Determine current breakout status
        current_side = None
        if mark_price > breakout_upper:
            current_side = "UP"
        elif mark_price < breakout_lower:
            current_side = "DOWN"

        # Track time-based breakout
        if current_side:
            prev_side = nlp_state.get("breakout_side")
            first_ts = nlp_state.get("breakout_first_ts")

            if prev_side != current_side or first_ts is None:
                # New breakout direction or first breach
                nlp_state["breakout_side"] = current_side
                nlp_state["breakout_first_ts"] = now_ts
                nlp_state["breakout_candle_count"] = 0
                return {
                    "triggered": False,
                    "side": current_side,
                    "action": None,
                    "reason": f"breakout_started side={current_side}",
                }

            # Check if held long enough (using preset hold_seconds)
            held_seconds = now_ts - first_ts
            if held_seconds >= hold_seconds:
                return {
                    "triggered": True,
                    "side": current_side,
                    "action": "flatten" if flatten_on_trigger else "pause",
                    "reason": f"hold_time={held_seconds:.0f}s",
                }
        else:
            # Price back in range - reset tracking
            if nlp_state.get("breakout_side"):
                nlp_state["breakout_side"] = None
                nlp_state["breakout_first_ts"] = None
                nlp_state["breakout_candle_count"] = 0

        # Check candle-based breakout
        if candles_1m and candle_confirm > 0:
            candle_side = self._check_candle_breakout(
                candles_1m, lower_price, upper_price, candle_confirm
            )
            if candle_side:
                return {
                    "triggered": True,
                    "side": candle_side,
                    "action": "flatten" if flatten_on_trigger else "pause",
                    "reason": f"candle_closes={candle_confirm}",
                }

        return {
            "triggered": False,
            "side": current_side,
            "action": None,
            "reason": "within_range",
        }

    def _check_candle_breakout(
        self,
        candles: List[Dict[str, Any]],
        lower: float,
        upper: float,
        required_closes: int,
    ) -> Optional[str]:
        """Check if N consecutive candle closes are outside range."""
        if not candles or len(candles) < required_closes:
            return None

        # Check last N candles (most recent first)
        recent = candles[-required_closes:]

        # Check all closes above upper
        all_above = all(self._safe_float(c.get("close"), 0) > upper for c in recent)
        if all_above:
            return "UP"

        # Check all closes below lower
        all_below = all(self._safe_float(c.get("close"), 0) < lower for c in recent)
        if all_below:
            return "DOWN"

        return None

    def execute_breakout_flatten(
        self,
        bot: Dict[str, Any],
        symbol: str,
        side: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute breakout protection: cancel orders, flatten position, enter cooldown.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            side: Breakout side ("UP" or "DOWN")
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with success status and details
        """
        # Use preset config or fall back to global defaults
        if config is None:
            config = self.get_effective_config(bot)

        cooldown_sec = config.get(
            "breakout_cooldown_sec", NEUTRAL_BREAKOUT_COOLDOWN_SEC
        )
        flatten_on_trigger = config.get(
            "breakout_flatten_on_trigger", NEUTRAL_BREAKOUT_FLATTEN_ON_TRIGGER
        )

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()
        results = {
            "success": False,
            "orders_cancelled": False,
            "position_closed": False,
            "verification": {},
        }

        # Cancel all orders
        try:
            cancel_result = self.client.cancel_all_orders(symbol)
            results["orders_cancelled"] = cancel_result.get("success", False)
            logger.info(
                "BREAKOUT_GUARD symbol=%s side=%s cancel_orders=%s",
                symbol,
                side,
                results["orders_cancelled"],
            )
        except Exception as e:
            logger.warning("BREAKOUT_GUARD %s cancel error: %s", symbol, e)

        # Flatten positions (using preset config)
        if flatten_on_trigger:
            try:
                positions = self._get_symbol_positions(symbol, skip_cache=True) or []
                if not positions:
                    results["position_closed"] = True
                for pos in positions:
                    size = self._safe_float(pos.get("size"), 0)
                    if size <= 0:
                        continue

                    pos_side = pos.get("side")
                    close_side = "Sell" if pos_side == "Buy" else "Buy"
                    position_idx = int(pos.get("positionIdx", 0) or 0)

                    # Generate orderLinkId for PnL attribution (hedge-safe)
                    order_link_id = self._generate_emergency_order_link_id(
                        bot, "BRK", position_idx
                    )

                    # Normalize qty to exchange step/min before submitting
                    normalized_qty = self.client.normalize_qty(symbol, size, log_skip=True)
                    if not normalized_qty:
                        logger.error(
                            "BREAKOUT_GUARD symbol=%s flatten FAILED: qty %.6f below exchange minimum",
                            symbol,
                            size,
                        )
                        continue

                    order_result = self.client.create_order(
                        symbol=symbol,
                        side=close_side,
                        qty=normalized_qty,
                        order_type="Market",
                        reduce_only=True,
                        position_idx=position_idx,
                        order_link_id=order_link_id,
                        ownership_snapshot=build_order_ownership_snapshot(
                            bot,
                            source="neutral_loss_prevention_service",
                            action="nlp_close",
                            close_reason="BRK",
                        ),
                    )
                    if order_result.get("success") or order_result.get("position_empty"):
                        results["position_closed"] = True
                        logger.info(
                            "BREAKOUT_GUARD symbol=%s side=%s flatten size=%.4f link_id=%s",
                            symbol,
                            side,
                            size,
                            order_link_id,
                        )
            except Exception as e:
                logger.warning("BREAKOUT_GUARD %s flatten error: %s", symbol, e)

        verification = self._verify_protection_execution(
            symbol,
            require_flatten=bool(flatten_on_trigger),
        )
        results["verification"] = verification

        if verification.get("confirmed"):
            # Enter cooldown (using preset cooldown_sec)
            nlp_state["breakout_cooldown_until"] = now_ts + cooldown_sec
            nlp_state["breakout_side"] = None
            nlp_state["breakout_first_ts"] = None

            # Keep bot running (NOT paused) - cooldown check will block new orders
            # The run_all_checks() method handles cooldown and auto-rebuild after expiry
            # bot["status"] stays "running" to allow the runner to continue processing
            bot["_nlp_block_opening_orders"] = True  # Block new orders during cooldown
            bot["last_error"] = (
                f"BREAKOUT_GUARD: {side} breakout, cooldown {cooldown_sec}s"
            )

            results["success"] = True
            self._record_exit_reason(
                bot,
                symbol=symbol,
                reason="breakout_flatten",
                side=side,
                cooldown_sec=cooldown_sec,
            )
            logger.warning(
                "BREAKOUT_GUARD symbol=%s side=%s mark=%.4f action=flatten cooldown=%ds",
                symbol,
                side,
                bot.get("current_price", 0),
                cooldown_sec,
            )
        else:
            bot["_nlp_block_opening_orders"] = True
            bot["last_error"] = (
                "BREAKOUT_GUARD pending: flatten/cancel not confirmed "
                f"(orders={verification.get('open_orders_remaining', 0)}, "
                f"positions={verification.get('open_positions_remaining', 0)})"
            )
            logger.error(
                "BREAKOUT_GUARD symbol=%s side=%s confirmation_failed orders=%s positions=%s",
                symbol,
                side,
                verification.get("open_orders_remaining", 0),
                verification.get("open_positions_remaining", 0),
            )
        return results

    def check_breakout_cooldown_expired(self, bot: Dict[str, Any]) -> bool:
        """Check if breakout cooldown has expired."""
        nlp_state = self._get_nlp_state(bot)
        cooldown_until = nlp_state.get("breakout_cooldown_until")
        if not cooldown_until:
            return True
        return self._get_now_ts() >= cooldown_until

    def rebuild_grid_after_breakout(
        self,
        bot: Dict[str, Any],
        symbol: str,
        current_price: float,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Rebuild grid centered around current price after cooldown.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            current_price: Current market price
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with success status
        """
        nlp_state = self._get_nlp_state(bot)

        # Clear cooldown state
        nlp_state["breakout_cooldown_until"] = None
        nlp_state["breakout_side"] = None

        # Clear grid state to trigger rebuild
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False
        bot["_nlp_block_opening_orders"] = False  # Re-enable order placement
        bot["last_error"] = None

        logger.info(
            "BREAKOUT_GUARD symbol=%s action=rebuild_grid price=%.4f",
            symbol,
            current_price,
        )
        return {"success": True, "action": "rebuild"}

    # =========================================================================
    # FEATURE B: Inventory/Skew Cap
    # =========================================================================

    def check_inventory_cap(
        self,
        bot: Dict[str, Any],
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if exposure exceeds inventory cap (hedge-mode aware).

        In one-way mode: Uses net exposure (long - short).
        In hedge mode with NEUTRAL_HEDGE_LEG_CAP_ENABLED: Applies cap to EACH leg
        independently, since net exposure can be zero while both legs are huge.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with:
            - exceeded: bool (True if any cap exceeded)
            - net_notional: float (abs(long - short))
            - cap_notional: float (per-leg cap in hedge mode, net cap otherwise)
            - excess_pct: float (for one-way mode or max of legs)
            - action: str or None
            - net_side: "long" | "short" | None
            - long_notional: float
            - short_notional: float
            - hedge_mode: bool (True if hedge mode detected)
            - long_exceeded: bool (hedge mode only)
            - short_exceeded: bool (hedge mode only)
            - long_action: str or None (hedge mode only)
            - short_action: str or None (hedge mode only)
        """
        base_result = {
            "exceeded": False,
            "net_notional": 0,
            "cap_notional": 0,
            "excess_pct": 0,
            "action": None,
            "net_side": None,
            "long_notional": 0,
            "short_notional": 0,
            "hedge_mode": False,
            "long_exceeded": False,
            "short_exceeded": False,
            "long_action": None,
            "short_action": None,
        }

        if not NEUTRAL_INVENTORY_CAP_ENABLED:
            return base_result

        # Use preset config or fall back to global defaults
        if config is None:
            config = self.get_effective_config(bot)

        inventory_cap_pct = config.get("inventory_cap_pct", NEUTRAL_INVENTORY_CAP_PCT)
        emergency_mult = config.get(
            "inventory_emergency_mult", NEUTRAL_INVENTORY_EMERGENCY_MULT
        )
        hedge_leg_cap_enabled = config.get(
            "inventory_hedge_leg_cap_enabled", NEUTRAL_HEDGE_LEG_CAP_ENABLED
        )

        # Calculate target notional and cap
        investment = self._safe_float(
            bot.get("investment") or bot.get("investment_usdt"), 0
        )
        leverage = self._safe_float(bot.get("leverage"), 1)
        target_notional = investment * leverage
        cap_notional = target_notional * inventory_cap_pct

        # 001-trading-bot-audit T067: Tighten inventory cap when momentum is high
        # When ADX exceeds threshold, reduce inventory cap to limit exposure
        nlp_state = self._get_nlp_state(bot)
        if nlp_state.get("momentum_blocked"):
            tighten_mult = config.get(
                "momentum_tighten_cap_mult", NEUTRAL_MOMENTUM_TIGHTEN_CAP_MULT
            )
            original_cap = cap_notional
            cap_notional = cap_notional * tighten_mult
            logger.info(
                "INVENTORY_CAP_TIGHTEN symbol=%s cap=%.2f->%.2f (momentum blocked)",
                symbol,
                original_cap,
                cap_notional,
            )

        if cap_notional <= 0:
            return base_result

        # Get current positions
        try:
            positions = self.client.get_positions()
            if not positions.get("success"):
                base_result["cap_notional"] = cap_notional
                return base_result

            positions_list = positions.get("data", {}).get("list", []) or []

            long_notional = 0.0
            short_notional = 0.0
            position_idxs = set()

            for pos in positions_list:
                if pos.get("symbol") != symbol:
                    continue
                size = self._safe_float(pos.get("size"), 0)
                if size <= 0:
                    continue
                avg_price = self._safe_float(pos.get("avgPrice"), 0)
                notional = round(size * avg_price, 2)
                pidx = int(pos.get("positionIdx", 0) or 0)
                position_idxs.add(pidx)

                if pos.get("side") == "Buy":
                    long_notional += notional
                else:
                    short_notional += notional

            # Detect hedge mode (positionIdx 1 or 2 present)
            is_hedge_mode = any(idx in (1, 2) for idx in position_idxs)

            net_notional = abs(long_notional - short_notional)
            net_side = (
                "long"
                if long_notional > short_notional
                else "short"
                if short_notional > long_notional
                else None
            )

            # Hedge mode with per-leg caps (using preset config)
            if is_hedge_mode and hedge_leg_cap_enabled:
                leg_cap = cap_notional  # Same cap for each leg

                long_exceeded = long_notional > leg_cap + 0.01
                short_exceeded = short_notional > leg_cap + 0.01
                exceeded = long_exceeded or short_exceeded

                long_excess_pct = long_notional / leg_cap if leg_cap > 0 else 0
                short_excess_pct = short_notional / leg_cap if leg_cap > 0 else 0
                excess_pct = max(long_excess_pct, short_excess_pct)

                # Determine per-leg actions (using preset emergency_mult)
                long_action = None
                if long_exceeded:
                    if long_excess_pct >= emergency_mult:
                        long_action = "emergency_reduce_long"
                    else:
                        long_action = "block_long_opening"

                short_action = None
                if short_exceeded:
                    if short_excess_pct >= emergency_mult:
                        short_action = "emergency_reduce_short"
                    else:
                        short_action = "block_short_opening"

                # Determine overall action (emergency takes priority)
                action = None
                if (
                    long_action == "emergency_reduce_long"
                    or short_action == "emergency_reduce_short"
                ):
                    action = "emergency_reduce"
                elif long_action or short_action:
                    action = "block_opening"

                # Log hedge-aware cap check
                if exceeded:
                    logger.info(
                        "INVENTORY_CAP_HEDGE symbol=%s long_notional=%.2f short_notional=%.2f "
                        "leg_cap=%.2f long_exceeded=%s short_exceeded=%s action=%s",
                        symbol,
                        long_notional,
                        short_notional,
                        leg_cap,
                        long_exceeded,
                        short_exceeded,
                        action,
                    )

                return {
                    "exceeded": exceeded,
                    "net_notional": net_notional,
                    "cap_notional": leg_cap,
                    "excess_pct": excess_pct,
                    "action": action,
                    "net_side": net_side,
                    "long_notional": long_notional,
                    "short_notional": short_notional,
                    "hedge_mode": True,
                    "long_exceeded": long_exceeded,
                    "short_exceeded": short_exceeded,
                    "long_action": long_action,
                    "short_action": short_action,
                }

            # One-way mode: use net exposure (existing behavior)
            exceeded = net_notional > cap_notional
            excess_pct = net_notional / cap_notional if cap_notional > 0 else 0

            action = None
            if exceeded:
                if excess_pct >= emergency_mult:
                    action = "emergency_reduce"
                else:
                    action = "block_opening"

            return {
                "exceeded": exceeded,
                "net_notional": net_notional,
                "cap_notional": cap_notional,
                "excess_pct": excess_pct,
                "action": action,
                "net_side": net_side,
                "long_notional": long_notional,
                "short_notional": short_notional,
                "hedge_mode": False,
                "long_exceeded": False,
                "short_exceeded": False,
                "long_action": None,
                "short_action": None,
            }

        except Exception as e:
            logger.warning("INVENTORY_CAP %s position check error: %s", symbol, e)
            return {
                "exceeded": False,
                "net_notional": 0,
                "cap_notional": cap_notional,
                "excess_pct": 0,
                "action": None,
                "net_side": None,
            }

    def should_block_order(
        self,
        bot: Dict[str, Any],
        symbol: str,
        side: str,
        reduce_only: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """
        Check if an order should be blocked due to inventory cap (hedge-mode aware).

        In one-way mode: Blocks orders that increase net exposure in dominant direction.
        In hedge mode: Blocks orders that increase the exceeded leg independently.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            side: Order side ("Buy" or "Sell")
            reduce_only: Whether the order is reduce-only
            config: Optional preset config (from get_effective_config)

        Returns:
            (should_block, reason)
        """
        # Never block reduce-only orders
        if reduce_only:
            return False, ""

        if not NEUTRAL_INVENTORY_CAP_ENABLED:
            return False, ""

        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        cap_result = self.check_inventory_cap(bot, symbol, config=config)
        if not cap_result["exceeded"]:
            return False, ""

        # Hedge mode: block orders independently per leg
        if cap_result.get("hedge_mode"):
            # Block buys if long leg exceeded (buys increase long exposure)
            if cap_result.get("long_exceeded") and side == "Buy":
                reason = (
                    f"INVENTORY_CAP_HEDGE block_order=Buy long_notional={cap_result['long_notional']:.2f} "
                    f"cap={cap_result['cap_notional']:.2f}"
                )
                logger.info(reason)
                return True, reason

            # Block sells if short leg exceeded (sells increase short exposure)
            if cap_result.get("short_exceeded") and side == "Sell":
                reason = (
                    f"INVENTORY_CAP_HEDGE block_order=Sell short_notional={cap_result['short_notional']:.2f} "
                    f"cap={cap_result['cap_notional']:.2f}"
                )
                logger.info(reason)
                return True, reason

            return False, ""

        # One-way mode: block based on net exposure direction
        net_side = cap_result.get("net_side")

        # Block orders that would increase exposure in the dominant direction
        # Net long -> block buys
        # Net short -> block sells
        if net_side == "long" and side == "Buy":
            reason = f"INVENTORY_CAP block_order=Buy net_notional={cap_result['net_notional']:.2f} cap={cap_result['cap_notional']:.2f}"
            logger.info(reason)
            return True, reason

        if net_side == "short" and side == "Sell":
            reason = f"INVENTORY_CAP block_order=Sell net_notional={cap_result['net_notional']:.2f} cap={cap_result['cap_notional']:.2f}"
            logger.info(reason)
            return True, reason

        return False, ""

    def execute_emergency_inventory_reduce(
        self,
        bot: Dict[str, Any],
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute emergency reduce-only market order to bring exposure back to cap (hedge-mode aware).

        In hedge mode: Reduces each exceeded leg independently (positionIdx=1 for long, 2 for short).
        In one-way mode: Reduces the dominant net side.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with success status and details
        """
        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()

        # Check emergency cooldown (prevent spam)
        last_emergency = nlp_state.get("inventory_emergency_ts")
        if last_emergency and now_ts - last_emergency < 60:  # 1 minute cooldown
            return {"success": False, "reason": "emergency_cooldown"}

        cap_result = self.check_inventory_cap(bot, symbol, config=config)
        if cap_result.get("action") != "emergency_reduce":
            return {"success": False, "reason": "not_emergency"}

        # Get positions
        try:
            positions = self.client.get_positions()
            if not positions.get("success"):
                return {"success": False, "reason": "position_fetch_failed"}

            positions_list = positions.get("data", {}).get("list", []) or []

            # Hedge mode: reduce each exceeded leg independently
            if cap_result.get("hedge_mode"):
                return self._execute_hedge_mode_reduce(
                    bot, symbol, cap_result, positions_list, nlp_state, now_ts, config
                )

            # One-way mode: reduce dominant net side (existing behavior)
            return self._execute_one_way_mode_reduce(
                bot, symbol, cap_result, positions_list, nlp_state, now_ts, config
            )

        except Exception as e:
            logger.warning("INVENTORY_CAP %s emergency reduce error: %s", symbol, e)
            return {"success": False, "reason": str(e)}

    def _execute_hedge_mode_reduce(
        self,
        bot: Dict[str, Any],
        symbol: str,
        cap_result: Dict[str, Any],
        positions_list: List[Dict[str, Any]],
        nlp_state: Dict[str, Any],
        now_ts: float,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute emergency reduce for hedge mode (per-leg reduction)."""
        results = {"success": False, "legs_reduced": [], "orders": []}

        # Use preset config values
        if config is None:
            config = self.get_effective_config(bot)

        reduce_to_pct = config.get(
            "inventory_reduce_to_pct", NEUTRAL_INVENTORY_REDUCE_TO_PCT
        )
        cap_pct = config.get("inventory_cap_pct", NEUTRAL_INVENTORY_CAP_PCT)

        # Calculate target notional per leg (using preset config)
        target_notional = (
            cap_result["cap_notional"] * (reduce_to_pct / cap_pct)
            if cap_pct > 0
            else cap_result["cap_notional"]
        )

        # Reduce long leg if emergency
        if cap_result.get("long_action") == "emergency_reduce_long":
            long_excess = cap_result["long_notional"] - target_notional
            if long_excess > 0:
                for pos in positions_list:
                    if pos.get("symbol") != symbol:
                        continue
                    if pos.get("side") != "Buy":
                        continue
                    pidx = int(pos.get("positionIdx", 0) or 0)
                    # In hedge mode, long should be positionIdx=1
                    if pidx != 1:
                        continue

                    size = self._safe_float(pos.get("size"), 0)
                    avg_price = self._safe_float(pos.get("avgPrice"), 0)
                    if size <= 0 or avg_price <= 0:
                        continue

                    reduce_qty = min(size, long_excess / avg_price)
                    if reduce_qty <= 0:
                        continue

                    # Normalize to exchange step/min
                    normalized_reduce = self.client.normalize_qty(symbol, reduce_qty, log_skip=False)
                    if not normalized_reduce:
                        logger.error(
                            "INVENTORY_CAP_HEDGE symbol=%s CANNOT reduce long: qty %.6f below exchange minimum. "
                            "Inventory cap violation persists — operator intervention may be needed.",
                            symbol,
                            reduce_qty,
                        )
                        continue

                    order_link_id = self._generate_emergency_order_link_id(
                        bot, "INV", 1
                    )
                    order_result = self.client.create_order(
                        symbol=symbol,
                        side="Sell",  # Close long
                        qty=normalized_reduce,
                        order_type="Market",
                        reduce_only=True,
                        position_idx=1,
                        order_link_id=order_link_id,
                        ownership_snapshot=build_order_ownership_snapshot(
                            bot,
                            source="neutral_loss_prevention_service",
                            action="nlp_close",
                            close_reason="INV",
                        ),
                    )

                    logger.warning(
                        "INVENTORY_CAP_HEDGE symbol=%s reduce_long qty=%.4f long_notional=%.2f cap=%.2f link_id=%s",
                        symbol,
                        reduce_qty,
                        cap_result["long_notional"],
                        cap_result["cap_notional"],
                        order_link_id,
                    )

                    results["legs_reduced"].append("long")
                    results["orders"].append(
                        {"leg": "long", "qty": reduce_qty, "result": order_result}
                    )
                    if order_result.get("success"):
                        results["success"] = True
                    break

        # Reduce short leg if emergency
        if cap_result.get("short_action") == "emergency_reduce_short":
            short_excess = cap_result["short_notional"] - target_notional
            if short_excess > 0:
                for pos in positions_list:
                    if pos.get("symbol") != symbol:
                        continue
                    if pos.get("side") != "Sell":
                        continue
                    pidx = int(pos.get("positionIdx", 0) or 0)
                    # In hedge mode, short should be positionIdx=2
                    if pidx != 2:
                        continue

                    size = self._safe_float(pos.get("size"), 0)
                    avg_price = self._safe_float(pos.get("avgPrice"), 0)
                    if size <= 0 or avg_price <= 0:
                        continue

                    reduce_qty = min(size, short_excess / avg_price)
                    if reduce_qty <= 0:
                        continue

                    # Normalize to exchange step/min
                    normalized_reduce = self.client.normalize_qty(symbol, reduce_qty, log_skip=False)
                    if not normalized_reduce:
                        logger.error(
                            "INVENTORY_CAP_HEDGE symbol=%s CANNOT reduce short: qty %.6f below exchange minimum. "
                            "Inventory cap violation persists — operator intervention may be needed.",
                            symbol,
                            reduce_qty,
                        )
                        continue

                    order_link_id = self._generate_emergency_order_link_id(
                        bot, "INV", 2
                    )
                    order_result = self.client.create_order(
                        symbol=symbol,
                        side="Buy",  # Close short
                        qty=normalized_reduce,
                        order_type="Market",
                        reduce_only=True,
                        position_idx=2,
                        order_link_id=order_link_id,
                        ownership_snapshot=build_order_ownership_snapshot(
                            bot,
                            source="neutral_loss_prevention_service",
                            action="nlp_close",
                            close_reason="INV",
                        ),
                    )

                    logger.warning(
                        "INVENTORY_CAP_HEDGE symbol=%s reduce_short qty=%.4f short_notional=%.2f cap=%.2f link_id=%s",
                        symbol,
                        reduce_qty,
                        cap_result["short_notional"],
                        cap_result["cap_notional"],
                        order_link_id,
                    )

                    results["legs_reduced"].append("short")
                    results["orders"].append(
                        {"leg": "short", "qty": reduce_qty, "result": order_result}
                    )
                    if order_result.get("success"):
                        results["success"] = True
                    break

        if results["legs_reduced"]:
            nlp_state["inventory_emergency_ts"] = now_ts
            self._record_exit_reason(
                bot,
                symbol=symbol,
                reason="inventory_emergency_reduce",
                legs_reduced=list(results["legs_reduced"]),
            )

        if not results["legs_reduced"]:
            results["reason"] = "no_position_to_reduce"

        return results

    def _execute_one_way_mode_reduce(
        self,
        bot: Dict[str, Any],
        symbol: str,
        cap_result: Dict[str, Any],
        positions_list: List[Dict[str, Any]],
        nlp_state: Dict[str, Any],
        now_ts: float,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute emergency reduce for one-way mode (net-based reduction)."""
        # Use preset config values
        if config is None:
            config = self.get_effective_config(bot)

        reduce_to_pct = config.get(
            "inventory_reduce_to_pct", NEUTRAL_INVENTORY_REDUCE_TO_PCT
        )
        cap_pct = config.get("inventory_cap_pct", NEUTRAL_INVENTORY_CAP_PCT)

        # Calculate how much to reduce (using preset config)
        target_notional = (
            cap_result["cap_notional"] * (reduce_to_pct / cap_pct)
            if cap_pct > 0
            else cap_result["cap_notional"]
        )
        excess = cap_result["net_notional"] - target_notional
        if excess <= 0:
            return {"success": False, "reason": "no_excess"}

        for pos in positions_list:
            if pos.get("symbol") != symbol:
                continue
            size = self._safe_float(pos.get("size"), 0)
            avg_price = self._safe_float(pos.get("avgPrice"), 0)
            if size <= 0 or avg_price <= 0:
                continue

            pos_side = pos.get("side")
            # Only reduce the dominant side
            if cap_result["net_side"] == "long" and pos_side != "Buy":
                continue
            if cap_result["net_side"] == "short" and pos_side != "Sell":
                continue

            # Calculate qty to reduce
            reduce_qty = min(size, excess / avg_price)
            if reduce_qty <= 0:
                continue

            # Normalize to exchange step/min
            normalized_reduce = self.client.normalize_qty(symbol, reduce_qty, log_skip=False)
            if not normalized_reduce:
                logger.error(
                    "INVENTORY_CAP symbol=%s CANNOT reduce %s: qty %.6f below exchange minimum. "
                    "Inventory cap violation persists — operator intervention may be needed.",
                    symbol,
                    pos_side,
                    reduce_qty,
                )
                continue

            close_side = "Sell" if pos_side == "Buy" else "Buy"
            position_idx = int(pos.get("positionIdx", 0) or 0)

            # Generate orderLinkId for PnL attribution (hedge-safe)
            order_link_id = self._generate_emergency_order_link_id(
                bot, "INV", position_idx
            )

            order_result = self.client.create_order(
                symbol=symbol,
                side=close_side,
                qty=normalized_reduce,
                order_type="Market",
                reduce_only=True,
                position_idx=position_idx,
                order_link_id=order_link_id,
                ownership_snapshot=build_order_ownership_snapshot(
                    bot,
                    source="neutral_loss_prevention_service",
                    action="nlp_close",
                    close_reason="INV",
                ),
            )

            nlp_state["inventory_emergency_ts"] = now_ts

            logger.warning(
                "INVENTORY_CAP symbol=%s emergency_reduce qty=%.4f net=%.2f cap=%.2f link_id=%s",
                symbol,
                reduce_qty,
                cap_result["net_notional"],
                cap_result["cap_notional"],
                order_link_id,
            )
            if order_result.get("success"):
                self._record_exit_reason(
                    bot,
                    symbol=symbol,
                    reason="inventory_emergency_reduce",
                    reduced_qty=reduce_qty,
                    net_notional=cap_result["net_notional"],
                    cap_notional=cap_result["cap_notional"],
                )
            return {
                "success": order_result.get("success", False),
                "reduced_qty": reduce_qty,
                "order_result": order_result,
            }

        return {"success": False, "reason": "no_position_to_reduce"}

    # =========================================================================
    # FEATURE C: Recenter/Range Freshness
    # =========================================================================

    def check_recenter_needed(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mark_price: float,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if grid needs recentering based on mid deviation, interval, or boundary touch.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            mark_price: Current mark price
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with needed, reason, mid_old, mid_new, deviation_pct
        """
        if not NEUTRAL_RECENTER_ENABLED:
            return {"needed": False, "reason": "disabled"}

        # SAFETY: NEVER recenter while any position is open (prevents churn on fresh fills)
        try:
            positions_resp = self.client.get_positions(skip_cache=True)
            if not positions_resp.get("success"):
                return {"needed": False, "reason": "position_check_failed"}

            positions = positions_resp.get("data", {}).get("list", []) or []
            for pos in positions:
                if pos.get("symbol") == symbol:
                    size = abs(self._safe_float(pos.get("size"), 0.0))
                    if size > 0:
                        return {"needed": False, "reason": "position_open"}
        except Exception as e:
            logger.warning(
                "[%s] Skipping recenter check: position fetch error: %s", symbol, e
            )
            return {"needed": False, "reason": "position_check_error"}

        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        cooldown_sec = config.get(
            "recenter_cooldown_sec", NEUTRAL_RECENTER_COOLDOWN_SEC
        )
        mid_deviation_pct = config.get(
            "recenter_mid_deviation_pct", NEUTRAL_RECENTER_MID_DEVIATION_PCT
        )
        interval_sec = config.get(
            "recenter_interval_sec", NEUTRAL_RECENTER_INTERVAL_SEC
        )
        on_boundary_touch = config.get(
            "recenter_on_boundary_touch", NEUTRAL_RECENTER_ON_BOUNDARY_TOUCH
        )

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()

        # Check cooldown (using preset config)
        last_recenter = nlp_state.get("last_recenter_ts")
        if last_recenter and now_ts - last_recenter < cooldown_sec:
            return {"needed": False, "reason": "cooldown"}

        # Get current grid bounds
        neutral_grid = bot.get("neutral_grid") or {}
        lower = self._safe_float(
            neutral_grid.get("lower_price") or bot.get("lower_price"), 0
        )
        upper = self._safe_float(
            neutral_grid.get("upper_price") or bot.get("upper_price"), 0
        )

        if lower <= 0 or upper <= 0 or upper <= lower:
            return {"needed": False, "reason": "invalid_bounds"}

        mid_old = (lower + upper) / 2
        deviation_pct = abs(mark_price - mid_old) / mid_old if mid_old > 0 else 0

        # Check mid deviation (using preset config)
        if deviation_pct > mid_deviation_pct:
            return {
                "needed": True,
                "reason": "mid_deviation",
                "mid_old": mid_old,
                "mid_new": mark_price,
                "deviation_pct": deviation_pct,
            }

        # Check interval (using preset config)
        if last_recenter and now_ts - last_recenter >= interval_sec:
            return {
                "needed": True,
                "reason": "interval",
                "mid_old": mid_old,
                "mid_new": mark_price,
                "deviation_pct": deviation_pct,
            }

        # Check boundary touch (using preset config)
        if on_boundary_touch:
            boundary_tolerance = (upper - lower) * 0.02  # 2% of range width
            if (
                mark_price <= lower + boundary_tolerance
                or mark_price >= upper - boundary_tolerance
            ):
                return {
                    "needed": True,
                    "reason": "boundary_touch",
                    "mid_old": mid_old,
                    "mid_new": mark_price,
                    "deviation_pct": deviation_pct,
                }

        return {
            "needed": False,
            "reason": "no_trigger",
            "mid_old": mid_old,
            "deviation_pct": deviation_pct,
        }

    def execute_recenter(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mark_price: float,
        reason: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute grid recenter: cancel orders and trigger grid rebuild.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            mark_price: Current mark price
            reason: Reason for recenter
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with success status
        """
        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()

        neutral_grid = bot.get("neutral_grid") or {}
        mid_old = (
            self._safe_float(neutral_grid.get("lower_price"), 0)
            + self._safe_float(neutral_grid.get("upper_price"), 0)
        ) / 2

        # Cancel existing orders (scoped to this bot)
        try:
            self.client.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning("RECENTER_GRID %s cancel error: %s", symbol, e)

        # Update recenter timestamp
        nlp_state["last_recenter_ts"] = now_ts

        # Keep grid width, recenter around mark_price
        old_lower = self._safe_float(
            neutral_grid.get("lower_price") or bot.get("lower_price"), 0
        )
        old_upper = self._safe_float(
            neutral_grid.get("upper_price") or bot.get("upper_price"), 0
        )
        grid_width = (
            old_upper - old_lower if old_upper > old_lower else mark_price * 0.06
        )  # Default 6%

        new_lower = mark_price - grid_width / 2
        new_upper = mark_price + grid_width / 2

        # Update bot with new bounds
        bot["grid_lower_price"] = new_lower
        bot["grid_upper_price"] = new_upper
        bot["lower_price"] = new_lower
        bot["upper_price"] = new_upper

        # Clear grid state to trigger rebuild
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False

        logger.info(
            "RECENTER_GRID symbol=%s reason=%s mid_old=%.4f mid_new=%.4f upper_new=%.4f lower_new=%.4f",
            symbol,
            reason,
            mid_old,
            mark_price,
            new_upper,
            new_lower,
        )

        return {
            "success": True,
            "mid_old": mid_old,
            "mid_new": mark_price,
            "new_lower": new_lower,
            "new_upper": new_upper,
        }

    # =========================================================================
    # FEATURE D: Max Loss / Equity Stop
    # =========================================================================

    def check_max_loss(
        self,
        bot: Dict[str, Any],
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if unrealized PnL exceeds max loss threshold.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with triggered, upnl, threshold, action
        """
        if not NEUTRAL_MAX_LOSS_ENABLED:
            return {"triggered": False, "upnl": 0, "threshold": 0, "action": None}

        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        use_pct = config.get("max_loss_use_pct", NEUTRAL_MAX_LOSS_USE_PCT)
        max_loss_pct = config.get("max_loss_pct", NEUTRAL_MAX_LOSS_PCT)
        max_loss_usd = config.get("max_loss_usd", NEUTRAL_MAX_LOSS_USD)

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()

        # Check cooldown
        cooldown_until = nlp_state.get("max_loss_cooldown_until")
        if cooldown_until and now_ts < cooldown_until:
            return {
                "triggered": False,
                "upnl": 0,
                "threshold": 0,
                "action": "in_cooldown",
            }

        # Calculate threshold (using preset config)
        if use_pct:
            # Investment IS the margin (collateral) - NOT multiplied by leverage
            # Leverage determines notional exposure, but max loss % should be vs margin
            investment = self._safe_float(
                bot.get("investment") or bot.get("investment_usdt"), 0
            )
            threshold = -abs(investment * max_loss_pct)
        else:
            threshold = -abs(max_loss_usd)

        # Get total unrealized PnL for symbol
        try:
            positions = self.client.get_positions()
            if not positions.get("success"):
                return {
                    "triggered": False,
                    "upnl": 0,
                    "threshold": threshold,
                    "action": None,
                }

            total_upnl = 0.0
            for pos in positions.get("data", {}).get("list", []) or []:
                if pos.get("symbol") != symbol:
                    continue
                upnl = self._safe_float(pos.get("unrealisedPnl"), 0)
                total_upnl += upnl

            triggered = total_upnl < threshold

            return {
                "triggered": triggered,
                "upnl": total_upnl,
                "threshold": threshold,
                "action": "flatten" if triggered else None,
            }

        except Exception as e:
            logger.warning("MAX_LOSS %s check error: %s", symbol, e)
            return {
                "triggered": False,
                "upnl": 0,
                "threshold": threshold,
                "action": None,
            }

    def execute_max_loss_stop(
        self,
        bot: Dict[str, Any],
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute max loss stop: cancel orders, flatten position, enter cooldown.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with success status
        """
        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        cooldown_sec = config.get(
            "max_loss_cooldown_sec", NEUTRAL_MAX_LOSS_COOLDOWN_SEC
        )

        nlp_state = self._get_nlp_state(bot)
        now_ts = self._get_now_ts()
        results = {
            "success": False,
            "orders_cancelled": False,
            "position_closed": False,
            "verification": {},
        }

        # Get current uPnL for logging (pass config to avoid re-computing)
        check_result = self.check_max_loss(bot, symbol, config=config)
        upnl = check_result.get("upnl", 0)
        threshold = check_result.get("threshold", 0)

        # Cancel all orders
        try:
            cancel_result = self.client.cancel_all_orders(symbol)
            results["orders_cancelled"] = cancel_result.get("success", False)
        except Exception as e:
            logger.warning("MAX_LOSS_STOP %s cancel error: %s", symbol, e)

        # Flatten all positions
        try:
            positions = self._get_symbol_positions(symbol, skip_cache=True) or []
            if not positions:
                results["position_closed"] = True
            for pos in positions:
                size = self._safe_float(pos.get("size"), 0)
                if size <= 0:
                    continue

                pos_side = pos.get("side")
                close_side = "Sell" if pos_side == "Buy" else "Buy"
                position_idx = int(pos.get("positionIdx", 0) or 0)

                # Generate orderLinkId for PnL attribution (hedge-safe)
                order_link_id = self._generate_emergency_order_link_id(
                    bot, "MAX", position_idx
                )

                order_result = self.client.create_order(
                    symbol=symbol,
                    side=close_side,
                    qty=size,
                    order_type="Market",
                    reduce_only=True,
                    position_idx=position_idx,
                    order_link_id=order_link_id,
                    ownership_snapshot=build_order_ownership_snapshot(
                        bot,
                        source="neutral_loss_prevention_service",
                        action="nlp_close",
                        close_reason="MAX",
                    ),
                )
                if order_result.get("success") or order_result.get("position_empty"):
                    results["position_closed"] = True
                    logger.info(
                        "MAX_LOSS_STOP symbol=%s flatten size=%.4f link_id=%s",
                        symbol,
                        size,
                        order_link_id,
                    )
        except Exception as e:
            logger.warning("MAX_LOSS_STOP %s flatten error: %s", symbol, e)

        verification = self._verify_protection_execution(symbol, require_flatten=True)
        results["verification"] = verification

        if verification.get("confirmed"):
            # Enter cooldown (using preset config)
            nlp_state["max_loss_cooldown_until"] = now_ts + cooldown_sec
            nlp_state["max_loss_triggered"] = True

            # Update bot status
            bot["status"] = "stopped"
            bot["started_at"] = None
            bot["last_run_at"] = datetime.now(timezone.utc).isoformat()
            bot["last_error"] = f"MAX_LOSS_STOP: uPnL ${upnl:.2f} < ${threshold:.2f}"

            results["success"] = True
            self._record_exit_reason(
                bot,
                symbol=symbol,
                reason="max_loss_stop",
                upnl=upnl,
                threshold=threshold,
                cooldown_sec=cooldown_sec,
            )
            logger.warning(
                "MAX_LOSS_STOP symbol=%s trigger upnl=%.4f threshold=%.4f action=flatten cooldown=%ds",
                symbol,
                upnl,
                threshold,
                cooldown_sec,
            )
        else:
            bot["_nlp_block_opening_orders"] = True
            bot["last_error"] = (
                "MAX_LOSS_STOP pending: flatten/cancel not confirmed "
                f"(orders={verification.get('open_orders_remaining', 0)}, "
                f"positions={verification.get('open_positions_remaining', 0)})"
            )
            logger.error(
                "MAX_LOSS_STOP symbol=%s confirmation_failed orders=%s positions=%s",
                symbol,
                verification.get("open_orders_remaining", 0),
                verification.get("open_positions_remaining", 0),
            )
        return results

    # =========================================================================
    # FEATURE E: Momentum Filter
    # =========================================================================

    def check_momentum_filter(
        self,
        bot: Dict[str, Any],
        symbol: str,
        indicators: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if market momentum is too strong for neutral mode.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            indicators: Optional pre-fetched indicators
            config: Optional preset config (from get_effective_config)

        Returns:
            Dict with blocked, reason, adx, rsi, bb_position
        """
        if not NEUTRAL_MOMENTUM_FILTER_ENABLED:
            # Clear any stale momentum block state so it doesn't linger when disabled.
            nlp_state = self._get_nlp_state(bot)
            if nlp_state.get("momentum_blocked") or nlp_state.get(
                "momentum_blocked_reason"
            ):
                nlp_state["momentum_blocked"] = False
                nlp_state["momentum_blocked_reason"] = None
            return {"blocked": False, "reason": "disabled"}

        # Bypass check: If user disabled entry gate, ignore momentum filter
        entry_gate_enabled = bot.get("entry_gate_enabled", True)
        if entry_gate_enabled == False:
            return {"blocked": False, "reason": "bypass"}

        if symbol == "PIPPINUSDT":
            logger.info(
                "[PIPPINUSDT] NLP bypass check failed: entry_gate_enabled=%s (type=%s)",
                entry_gate_enabled,
                type(entry_gate_enabled),
            )

        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        adx_threshold = config.get(
            "momentum_adx_threshold", NEUTRAL_MOMENTUM_ADX_THRESHOLD
        )
        rsi_upper = config.get("momentum_rsi_upper", NEUTRAL_MOMENTUM_RSI_UPPER)
        rsi_lower = config.get("momentum_rsi_lower", NEUTRAL_MOMENTUM_RSI_LOWER)
        bb_touch_filter = config.get(
            "momentum_bb_touch_filter", NEUTRAL_MOMENTUM_BB_TOUCH_FILTER
        )
        block_action = config.get(
            "momentum_block_action", NEUTRAL_MOMENTUM_BLOCK_ACTION
        )

        if not indicators:
            if not self.indicator_service:
                return {"blocked": False, "reason": "no_indicator_service"}
            try:
                indicators = self.indicator_service.compute_indicators(
                    symbol, interval="1", limit=50
                )
            except Exception as e:
                logger.warning("MOMENTUM_FILTER %s indicator error: %s", symbol, e)
                return {"blocked": False, "reason": "indicator_error"}

        if not indicators:
            return {"blocked": False, "reason": "no_indicators"}

        adx = self._safe_float(indicators.get("adx"), 0)
        rsi = self._safe_float(indicators.get("rsi"), 50)
        close = self._safe_float(indicators.get("close"), 0)
        bb_upper = self._safe_float(indicators.get("bb_upper"), 0)
        bb_lower = self._safe_float(indicators.get("bb_lower"), 0)

        # Calculate BB position (0-100, 50 = middle)
        bb_position = 50.0
        if bb_upper > bb_lower and close > 0:
            bb_range = bb_upper - bb_lower
            bb_position = ((close - bb_lower) / bb_range) * 100 if bb_range > 0 else 50

        blocked = False
        reasons = []

        # Check ADX (using preset config)
        if adx > adx_threshold:
            blocked = True
            reasons.append(f"ADX={adx:.1f}>{adx_threshold}")

        # Check RSI overbought (using preset config)
        if rsi > rsi_upper:
            blocked = True
            reasons.append(f"RSI={rsi:.1f}>{rsi_upper}")

        # Check RSI oversold (using preset config)
        if rsi < rsi_lower:
            blocked = True
            reasons.append(f"RSI={rsi:.1f}<{rsi_lower}")

        # Check BB touch (using preset config)
        if bb_touch_filter:
            if bb_position >= 95:  # Near/above upper BB
                blocked = True
                reasons.append(f"BB_upper={bb_position:.0f}%")
            elif bb_position <= 5:  # Near/below lower BB
                blocked = True
                reasons.append(f"BB_lower={bb_position:.0f}%")

        nlp_state = self._get_nlp_state(bot)
        nlp_state["momentum_blocked"] = blocked
        nlp_state["momentum_blocked_reason"] = ", ".join(reasons) if reasons else None

        if blocked:
            reason_str = ", ".join(reasons)
            logger.info(
                "MOMENTUM_BLOCK symbol=%s adx=%.1f rsi=%.1f bb=%.0f%% action=%s reason=%s",
                symbol,
                adx,
                rsi,
                bb_position,
                block_action,
                reason_str,
            )

        return {
            "blocked": blocked,
            "reason": ", ".join(reasons) if reasons else "clear",
            "adx": adx,
            "rsi": rsi,
            "bb_position": bb_position,
            "action": block_action if blocked else None,
        }

    def should_block_grid_placement(
        self,
        bot: Dict[str, Any],
        symbol: str,
        indicators: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """
        Combined check for whether grid placement should be blocked.
        Combines momentum filter with inventory cap blocking.

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            indicators: Optional pre-fetched indicators
            config: Optional preset config (from get_effective_config)

        Returns:
            (should_block, reason)
        """
        # Use preset config or fall back
        if config is None:
            config = self.get_effective_config(bot)

        # Check momentum filter (pass config to use preset thresholds)
        momentum_result = self.check_momentum_filter(
            bot, symbol, indicators, config=config
        )
        if momentum_result.get("blocked"):
            return True, momentum_result.get("reason", "momentum")

        # Also check if in breakout cooldown
        nlp_state = self._get_nlp_state(bot)
        cooldown_until = nlp_state.get("breakout_cooldown_until")
        if cooldown_until and self._get_now_ts() < cooldown_until:
            return True, "breakout_cooldown"

        return False, ""

    # =========================================================================
    # MASTER CHECK METHOD
    # =========================================================================

    def run_all_checks(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mark_price: float,
        indicators: Optional[Dict[str, Any]] = None,
        candles_1m: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Run all loss-prevention checks in priority order.

        Order:
        1. Max Loss Stop (immediate exit) - FIRST
        2. Breakout Guard (range exit) - SECOND
        3. Inventory Cap (exposure check) - THIRD
        4. Momentum Filter (entry block) - FOURTH
        5. Recenter logic (grid maintenance) - FIFTH

        Args:
            bot: Bot configuration dict
            symbol: Trading symbol
            mark_price: Current mark price
            indicators: Optional pre-fetched indicators
            candles_1m: Optional 1-minute candle data

        Returns:
            Dict with action, details, and updated bot
        """
        # Only apply to neutral modes
        mode = (bot.get("mode") or "").lower()
        if mode not in ("neutral", "neutral_classic_bybit"):
            return {
                "action": "continue",
                "details": {"reason": "not_neutral_mode"},
                "bot": bot,
            }

        # Compute effective config once (preset + global defaults)
        eff = self.get_effective_config(bot)

        # 1. Max Loss Stop (highest priority - immediate exit)
        max_loss_result = self.check_max_loss(bot, symbol, config=eff)
        if max_loss_result.get("triggered"):
            execute_result = self.execute_max_loss_stop(bot, symbol, config=eff)
            return {
                "action": (
                    "max_loss_stop"
                    if execute_result.get("success")
                    else "max_loss_stop_failed"
                ),
                "details": {
                    "upnl": max_loss_result.get("upnl"),
                    "threshold": max_loss_result.get("threshold"),
                    "execute_result": execute_result,
                },
                "bot": bot,
            }

        # 2. Breakout Guard
        breakout_result = self.check_breakout_guard(
            bot, symbol, mark_price, candles_1m, config=eff
        )
        if breakout_result.get("triggered"):
            execute_result = self.execute_breakout_flatten(
                bot, symbol, breakout_result.get("side"), config=eff
            )
            return {
                "action": (
                    "breakout_flatten"
                    if execute_result.get("success")
                    else "breakout_flatten_failed"
                ),
                "details": {
                    "side": breakout_result.get("side"),
                    "reason": breakout_result.get("reason"),
                    "execute_result": execute_result,
                },
                "bot": bot,
            }

        # Check if breakout cooldown expired - trigger rebuild
        nlp_state = self._get_nlp_state(bot)
        cooldown_until = nlp_state.get("breakout_cooldown_until")
        if cooldown_until:
            if self._get_now_ts() >= cooldown_until:
                rebuild_result = self.rebuild_grid_after_breakout(
                    bot, symbol, mark_price, config=eff
                )
                return {
                    "action": "breakout_rebuild",
                    "details": {"rebuild_result": rebuild_result},
                    "bot": bot,
                }
            else:
                # Still in cooldown
                return {
                    "action": "breakout_cooldown",
                    "details": {"remaining": int(cooldown_until - self._get_now_ts())},
                    "bot": bot,
                }

        # 3. Inventory Cap - emergency reduce
        inventory_result = self.check_inventory_cap(bot, symbol, config=eff)
        if inventory_result.get("action") == "emergency_reduce":
            execute_result = self.execute_emergency_inventory_reduce(
                bot, symbol, config=eff
            )
            return {
                "action": "inventory_reduce",
                "details": {
                    "net_notional": inventory_result.get("net_notional"),
                    "cap_notional": inventory_result.get("cap_notional"),
                    "execute_result": execute_result,
                },
                "bot": bot,
            }

        # 4. Momentum Filter
        momentum_result = self.check_momentum_filter(
            bot, symbol, indicators, config=eff
        )

        # 5. Recenter Logic
        recenter_result = self.check_recenter_needed(
            bot, symbol, mark_price, config=eff
        )
        if recenter_result.get("needed"):
            execute_result = self.execute_recenter(
                bot, symbol, mark_price, recenter_result.get("reason"), config=eff
            )
            return {
                "action": "recenter",
                "details": {
                    "reason": recenter_result.get("reason"),
                    "mid_old": recenter_result.get("mid_old"),
                    "mid_new": mark_price,
                    "execute_result": execute_result,
                },
                "bot": bot,
            }

        # Combined blocking check (momentum + inventory cap for new orders)
        should_block = momentum_result.get("blocked") or inventory_result.get(
            "exceeded"
        )
        if should_block:
            return {
                "action": "block_grid",
                "details": {
                    "momentum_blocked": momentum_result.get("blocked"),
                    "inventory_exceeded": inventory_result.get("exceeded"),
                    "momentum_reason": momentum_result.get("reason"),
                    "inventory_net_side": inventory_result.get("net_side"),
                },
                "bot": bot,
            }

        # All clear
        return {
            "action": "continue",
            "details": {
                "checks_passed": True,
                "adx": momentum_result.get("adx"),
                "rsi": momentum_result.get("rsi"),
                "net_notional": inventory_result.get("net_notional"),
            },
            "bot": bot,
        }
