import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MockBybitClient:
    """Candle-driven mock client for bounded replay backtests."""

    def __init__(
        self,
        initial_balance: float = 1000.0,
        *,
        maker_fee_bps: float = 2.0,
        taker_fee_bps: float = 5.5,
        market_slippage_bps: float = 5.0,
    ) -> None:
        self.wallet_balance = float(initial_balance)
        self.usdt_equity = float(initial_balance)
        self.positions: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.open_orders: List[Dict[str, Any]] = []
        self.history: Dict[str, List[List[str]]] = {}
        self.current_prices: Dict[str, float] = {}
        self.current_time_ms = 0
        self.current_candles: Dict[str, Dict[str, float]] = {}

        self.maker_fee_rate = max(float(maker_fee_bps), 0.0) / 10000.0
        self.taker_fee_rate = max(float(taker_fee_bps), 0.0) / 10000.0
        self.market_slippage_rate = max(float(market_slippage_bps), 0.0) / 10000.0

        self._order_id_counter = 0
        self._exec_id_counter = 0
        self.closed_pnl_records: List[Dict[str, Any]] = []
        self.execution_records: List[Dict[str, Any]] = []
        self.order_ownership_service = None
        self.trade_forensics_service = None
        self.order_router = None
        self.stream_service = None

    def set_time(self, timestamp_ms: int) -> None:
        self.current_time_ms = int(timestamp_ms)

    def set_order_router(self, order_router: Any) -> "MockBybitClient":
        self.order_router = order_router
        return self

    def set_stream_service(self, stream_service: Any) -> "MockBybitClient":
        self.stream_service = stream_service
        return self

    def set_order_ownership_service(self, order_ownership_service: Any) -> "MockBybitClient":
        self.order_ownership_service = order_ownership_service
        return self

    def set_trade_forensics_service(self, trade_forensics_service: Any) -> "MockBybitClient":
        self.trade_forensics_service = trade_forensics_service
        return self

    def _now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(self.current_time_ms / 1000.0, tz=timezone.utc).isoformat()

    def set_history(self, symbol: str, candles: List[Dict[str, Any]]) -> None:
        ordered = sorted(
            list(candles or []),
            key=lambda candle: int(candle.get("timestamp") or 0),
        )
        rows = []
        for candle in ordered:
            rows.append(
                [
                    str(int(candle["timestamp"])),
                    str(float(candle["open"])),
                    str(float(candle["high"])),
                    str(float(candle["low"])),
                    str(float(candle["close"])),
                    str(float(candle.get("volume", 0.0))),
                    "0",
                ]
            )
        self.history[symbol] = rows

    def feed_candle(
        self,
        symbol: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
    ) -> None:
        self.current_prices[symbol] = float(close)
        self.current_candles[symbol] = {
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume),
        }
        kline = [
            str(self.current_time_ms),
            str(float(open_price)),
            str(float(high)),
            str(float(low)),
            str(float(close)),
            str(float(volume)),
            "0",
        ]
        history = self.history.setdefault(symbol, [])
        if history and str(history[-1][0]) == str(self.current_time_ms):
            history[-1] = kline
        else:
            history.append(kline)
        self._process_orders(symbol, high=float(high), low=float(low))
        self._update_pnl(symbol, price=float(close))

    def get_wallet_balance(self, account_type: str = "UNIFIED") -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "accountType": account_type,
                        "totalEquity": str(self.usdt_equity),
                        "totalWalletBalance": str(self.wallet_balance),
                        "coin": [
                            {
                                "coin": "USDT",
                                "walletBalance": str(self.wallet_balance),
                                "equity": str(self.usdt_equity),
                            }
                        ],
                    }
                ]
            },
        }

    def get_position_mode(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        return {
            "success": True,
            "mode": "hedge",
            "data": {"list": [{"symbol": symbol or "", "mode": 3}]},
        }

    def get_instruments_info(
        self,
        symbol: Optional[str] = None,
        category: str = "linear",
        status: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        symbol_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": symbol or "BTCUSDT",
                        "lotSizeFilter": {
                            "minOrderQty": "0.001",
                            "maxOrderQty": "1000",
                            "qtyStep": "0.001",
                            "minNotionalValue": "5.0",
                        },
                        "priceFilter": {
                            "minPrice": "0.0001",
                            "tickSize": "0.0001",
                        },
                    }
                ]
            },
        }

    def get_qty_filters(self, symbol: str) -> Dict[str, float]:
        return {"min_qty": 0.001, "max_qty": 1000.0, "qty_step": 0.001}

    def normalize_qty(self, symbol: str, qty: Optional[float], log_skip: bool = True) -> Optional[float]:
        if qty is None:
            return None
        try:
            qty_value = float(qty)
        except (TypeError, ValueError):
            return None
        if qty_value <= 0:
            return None
        normalized = round(qty_value / 0.001) * 0.001
        return round(max(normalized, 0.001), 6)

    def get_kline(
        self,
        symbol: str,
        interval: str = "15",
        limit: int = 200,
        category: str = "linear",
        **kwargs,
    ) -> Dict[str, Any]:
        rows = list(self.history.get(symbol, []))
        if not rows:
            return {"success": True, "data": {"list": [], "category": category}}
        cutoff = int(kwargs.get("end") or self.current_time_ms or int(rows[-1][0]))
        filtered = [row for row in rows if int(row[0]) <= cutoff]
        subset = filtered[-int(limit):]
        subset.reverse()
        return {"success": True, "data": {"list": subset, "category": category}}

    def get_tickers(
        self,
        symbol: Optional[str] = None,
        category: str = "linear",
        skip_cache: bool = False,
    ) -> Dict[str, Any]:
        symbols = [symbol] if symbol else list(self.current_prices.keys())
        rows = []
        for sym in symbols:
            if sym not in self.current_prices:
                continue
            price = float(self.current_prices[sym])
            rows.append(
                {
                    "symbol": sym,
                    "lastPrice": str(price),
                    "indexPrice": str(price),
                    "markPrice": str(price),
                    "bid1Price": str(price * 0.9999),
                    "ask1Price": str(price * 1.0001),
                    "volume24h": "1000000",
                    "turnover24h": "50000000",
                    "highPrice24h": str(price * 1.05),
                    "lowPrice24h": str(price * 0.95),
                    "prevPrice24h": str(price),
                    "price24hPcnt": "0.01",
                }
            )
        return {"success": True, "data": {"list": rows}}

    def get_positions(self, symbol: Optional[str] = None, skip_cache: bool = False) -> Dict[str, Any]:
        rows = []
        for (sym, _idx), pos in self.positions.items():
            if symbol and sym != symbol:
                continue
            rows.append(dict(pos))
        if symbol and not rows:
            rows = [dict(self._get_or_create_position(symbol, 1)), dict(self._get_or_create_position(symbol, 2))]
        return {"success": True, "data": {"list": rows}}

    def get_open_orders(self, category: Optional[str] = None, symbol: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        rows = [dict(order) for order in self.open_orders if not symbol or order["symbol"] == symbol]
        return {"success": True, "data": {"list": rows}}

    def set_leverage(self, symbol: str, buyLeverage: Any = None, sellLeverage: Any = None, category: str = "linear", leverage: Any = None) -> Dict[str, Any]:
        target = leverage if leverage is not None else buyLeverage or sellLeverage or 10
        for idx in (1, 2):
            pos = self._get_or_create_position(symbol, idx)
            pos["leverage"] = str(target)
        return {"success": True, "data": {}}

    def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": symbol,
                        "fundingRate": "0.0",
                        "fundingRateTimestamp": str(self.current_time_ms),
                    }
                ]
            },
        }

    def get_account_info(self) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "marginMode": "REGULAR_MARGIN",
                "updatedTime": str(self.current_time_ms),
            },
        }

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float],
        order_type: str = "Market",
        price: Optional[float] = None,
        category: str = "linear",
        **kwargs,
    ) -> Dict[str, Any]:
        return self.create_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            price=price,
            reduce_only=kwargs.get("reduceOnly", False),
            time_in_force=kwargs.get("timeInForce", "GTC"),
            order_link_id=kwargs.get("orderLinkId"),
            position_idx=kwargs.get("positionIdx"),
            qty_is_normalized=False,
            ownership_snapshot=kwargs.get("ownership_snapshot"),
        )

    def create_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float],
        order_type: str = "Market",
        price: Optional[float] = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        order_link_id: Optional[str] = None,
        position_idx: Optional[int] = None,
        qty_is_normalized: bool = False,
        ownership_snapshot: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        normalized_qty = qty if qty_is_normalized else self.normalize_qty(symbol, qty)
        if not normalized_qty:
            return {"success": False, "error": "qty_below_min", "retCode": -1}

        self._order_id_counter += 1
        order_id = f"mock_oid_{self._order_id_counter}"
        pos_idx = int(position_idx or 0)
        created_time = str(self.current_time_ms)
        order = {
            "orderId": order_id,
            "orderLinkId": str(order_link_id or "").strip(),
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "price": float(price) if price is not None else 0.0,
            "qty": float(normalized_qty),
            "orderStatus": "New",
            "leavesQty": float(normalized_qty),
            "cumExecQty": 0.0,
            "createdTime": created_time,
            "reduceOnly": bool(reduce_only),
            "positionIdx": pos_idx,
            "_ownership_snapshot": dict(ownership_snapshot or {}),
        }
        self.orders[order_id] = order

        if order_type == "Market":
            base_price = float(self.current_prices.get(symbol, 0.0) or 0.0)
            if base_price <= 0:
                return {"success": False, "error": "missing_market_price", "retCode": -1}
            fill_price = self._apply_market_slippage(base_price, side=side)
            self._fill_order(
                order,
                fill_price,
                ownership_snapshot=(ownership_snapshot or order.get("_ownership_snapshot")),
            )
        else:
            self.open_orders.append(order)

        self._record_order_ownership(order, ownership_snapshot=ownership_snapshot)
        self._record_forensic_order_submission(
            order,
            ownership_snapshot=ownership_snapshot,
            reduce_only=reduce_only,
        )
        return {
            "success": True,
            "retCode": 0,
            "data": {
                "orderId": order_id,
                "orderLinkId": order["orderLinkId"],
            },
        }

    def cancel_order(self, symbol: str, order_id: Optional[str] = None, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        for order in list(self.open_orders):
            if order["symbol"] != symbol:
                continue
            if order_id and order["orderId"] != order_id:
                continue
            if order_link_id and order["orderLinkId"] != order_link_id:
                continue
            order["orderStatus"] = "Cancelled"
            self.open_orders.remove(order)
            return {"success": True, "data": {"orderId": order["orderId"]}}
        return {"success": True, "data": {}}

    def cancel_all_orders(self, symbol: str, category: str = "linear", **kwargs) -> Dict[str, Any]:
        for order in list(self.open_orders):
            if order["symbol"] != symbol:
                continue
            order["orderStatus"] = "Cancelled"
            self.open_orders.remove(order)
        return {"success": True, "data": {"list": []}}

    def close_position(self, symbol: str) -> Dict[str, Any]:
        for (sym, idx), pos in list(self.positions.items()):
            if sym != symbol:
                continue
            size = float(pos.get("size") or 0.0)
            if size <= 0:
                continue
            side = "Sell" if idx == 1 else "Buy"
            self.create_order(
                symbol=symbol,
                side=side,
                qty=size,
                order_type="Market",
                reduce_only=True,
                position_idx=idx,
            )
        return {"success": True, "data": {}}

    def set_trading_stop(
        self,
        symbol: str,
        position_idx: int = 0,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        tp_trigger_by: str = "LastPrice",
        sl_trigger_by: str = "LastPrice",
    ) -> Dict[str, Any]:
        return {"success": True, "data": {}}

    def get_closed_pnl(self, symbol: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        rows = [
            dict(record)
            for record in self.closed_pnl_records
            if not symbol or record.get("symbol") == symbol
        ]
        rows.sort(key=lambda item: int(item.get("createdTime") or 0), reverse=True)
        return {"success": True, "data": {"list": rows[: int(limit)]}}

    def get_executions(self, symbol: Optional[str] = None, limit: int = 50, skip_cache: bool = False) -> Dict[str, Any]:
        rows = [
            dict(record)
            for record in self.execution_records
            if not symbol or record.get("symbol") == symbol
        ]
        rows.sort(key=lambda item: int(item.get("execTime") or 0), reverse=True)
        return {"success": True, "data": {"list": rows[: int(limit)]}}

    def _apply_market_slippage(self, price: float, *, side: str) -> float:
        if price <= 0:
            return price
        normalized_side = str(side or "").strip().lower()
        if normalized_side == "buy":
            return round(price * (1.0 + self.market_slippage_rate), 8)
        return round(price * (1.0 - self.market_slippage_rate), 8)

    def _record_order_ownership(
        self,
        order: Dict[str, Any],
        *,
        ownership_snapshot: Optional[Dict[str, Any]],
    ) -> None:
        if not ownership_snapshot or not self.order_ownership_service:
            return
        try:
            payload = dict(ownership_snapshot)
            payload["symbol"] = order.get("symbol")
            payload["side"] = order.get("side")
            payload["position_idx"] = order.get("positionIdx")
            payload["reduce_only"] = bool(order.get("reduceOnly"))
            payload["order_id"] = order.get("orderId")
            payload["order_link_id"] = order.get("orderLinkId")
            self.order_ownership_service.record_order(payload)
        except Exception as exc:
            logger.warning(
                "[%s] Backtest ownership snapshot write failed for %s: %s",
                order.get("symbol"),
                order.get("orderId"),
                exc,
            )

    def _record_forensic_order_submission(
        self,
        order: Dict[str, Any],
        *,
        ownership_snapshot: Optional[Dict[str, Any]],
        reduce_only: bool,
    ) -> None:
        if not ownership_snapshot or not self.trade_forensics_service:
            return
        try:
            base_payload = {
                "timestamp": self._now_iso(),
                "forensic_decision_id": ownership_snapshot.get("forensic_decision_id"),
                "trade_context_id": ownership_snapshot.get("forensic_trade_context_id"),
                "bot_id": ownership_snapshot.get("bot_id"),
                "symbol": order.get("symbol"),
                "mode": ownership_snapshot.get("bot_mode"),
                "profile": ownership_snapshot.get("bot_profile"),
                "side": ownership_snapshot.get("forensic_side") or order.get("side"),
                "decision_type": ownership_snapshot.get("forensic_decision_type"),
                "linkage_method": (
                    "ownership_snapshot"
                    if ownership_snapshot.get("forensic_trade_context_id")
                    or ownership_snapshot.get("forensic_decision_id")
                    else "bot_symbol_only"
                ),
                "attribution_status": (
                    "linked"
                    if ownership_snapshot.get("forensic_trade_context_id")
                    or ownership_snapshot.get("forensic_decision_id")
                    else "unresolved"
                ),
                "order": {
                    "order_id": order.get("orderId"),
                    "order_link_id": order.get("orderLinkId"),
                    "order_type": order.get("orderType"),
                    "qty": round(float(order.get("qty") or 0.0), 8),
                    "price": round(float(order.get("price") or 0.0), 8)
                    if order.get("price")
                    else None,
                    "reduce_only": bool(order.get("reduceOnly")),
                    "position_idx": order.get("positionIdx"),
                    "action": ownership_snapshot.get("action"),
                },
            }
            if reduce_only:
                self.trade_forensics_service.record_event(
                    dict(
                        base_payload,
                        event_type="exit_decision",
                        event_status="submitted",
                        exit={
                            "action": ownership_snapshot.get("action"),
                            "close_reason": ownership_snapshot.get("close_reason"),
                        },
                    )
                )
            self.trade_forensics_service.record_event(
                dict(
                    base_payload,
                    event_type="order_submitted",
                    event_status="submitted",
                )
            )
        except Exception as exc:
            logger.warning(
                "[%s] Backtest forensic order submission failed for %s: %s",
                order.get("symbol"),
                order.get("orderId"),
                exc,
            )

    def _next_exec_id(self) -> str:
        self._exec_id_counter += 1
        return f"mock_exec_{self._exec_id_counter}"

    def _fill_order(
        self,
        order: Dict[str, Any],
        fill_price: float,
        *,
        ownership_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        if fill_price <= 0:
            return

        symbol = str(order.get("symbol") or "").strip().upper()
        side = str(order.get("side") or "").strip()
        qty = float(order.get("qty") or 0.0)
        if qty <= 0:
            return

        pos_idx = int(order.get("positionIdx") or 0)
        if pos_idx not in (1, 2):
            pos_idx = 1 if side.lower() == "buy" else 2
        ownership_snapshot = ownership_snapshot or order.get("_ownership_snapshot") or {}
        position = self._get_or_create_position(symbol, pos_idx)
        current_size = float(position.get("size") or 0.0)
        current_entry = float(position.get("avgPrice") or 0.0)
        accrued_open_fee = float(position.get("_accrued_open_fee") or 0.0)
        is_market = str(order.get("orderType") or "").strip().lower() == "market"
        fee_rate = self.taker_fee_rate if is_market else self.maker_fee_rate
        fee = fill_price * qty * fee_rate

        opening_side = "Buy" if pos_idx == 1 else "Sell"
        closing_side = "Sell" if pos_idx == 1 else "Buy"

        if side == opening_side:
            size_before = current_size
            total_qty = current_size + qty
            total_value = (current_size * current_entry) + (qty * fill_price)
            new_entry = total_value / total_qty if total_qty > 0 else fill_price
            position["size"] = str(round(total_qty, 8))
            position["avgPrice"] = str(round(new_entry, 8))
            position["_accrued_open_fee"] = round(accrued_open_fee + fee, 8)
            self.wallet_balance -= fee
            if size_before <= 0 and total_qty > 0:
                self._record_forensic_position_opened(
                    order,
                    fill_price=fill_price,
                    qty=qty,
                    ownership_snapshot=ownership_snapshot,
                )
        elif side == closing_side:
            closing_qty = min(current_size, qty)
            if closing_qty <= 0:
                order["orderStatus"] = "Filled"
                order["leavesQty"] = 0.0
                order["cumExecQty"] = qty
                return
            size_before = current_size
            allocated_open_fee = accrued_open_fee * (closing_qty / size_before) if size_before > 0 else 0.0
            if pos_idx == 1:
                gross_pnl = (fill_price - current_entry) * closing_qty
            else:
                gross_pnl = (current_entry - fill_price) * closing_qty
            close_fee = fill_price * closing_qty * fee_rate
            net_pnl = gross_pnl - allocated_open_fee - close_fee
            self.wallet_balance += gross_pnl
            self.wallet_balance -= close_fee
            remaining_size = max(0.0, current_size - closing_qty)
            remaining_fee = max(0.0, accrued_open_fee - allocated_open_fee)
            position["size"] = str(round(remaining_size, 8))
            position["avgPrice"] = str(round(current_entry if remaining_size > 0 else 0.0, 8))
            position["_accrued_open_fee"] = round(remaining_fee, 8)
            exec_id = self._next_exec_id()
            closed_record = {
                "orderId": order.get("orderId"),
                "execId": exec_id,
                "createdTime": str(self.current_time_ms),
                "symbol": symbol,
                "side": side,
                "closedPnl": round(net_pnl, 8),
                "orderLinkId": order.get("orderLinkId"),
                "positionIdx": pos_idx,
                "openFee": round(allocated_open_fee, 8),
                "closeFee": round(close_fee, 8),
                "execFee": round(close_fee, 8),
            }
            self.closed_pnl_records.append(closed_record)
        else:
            logger.debug(
                "[%s] Ignored unsupported fill direction side=%s pos_idx=%s",
                symbol,
                side,
                pos_idx,
            )

        exec_record = {
            "orderId": order.get("orderId"),
            "orderLinkId": order.get("orderLinkId"),
            "execId": self._next_exec_id(),
            "execTime": str(self.current_time_ms),
            "symbol": symbol,
            "side": side,
            "execPrice": str(round(fill_price, 8)),
            "execQty": str(round(qty, 8)),
        }
        self.execution_records.append(exec_record)
        order["orderStatus"] = "Filled"
        order["cumExecQty"] = qty
        order["leavesQty"] = 0.0
        if order in self.open_orders:
            self.open_orders.remove(order)

    def _record_forensic_position_opened(
        self,
        order: Dict[str, Any],
        *,
        fill_price: float,
        qty: float,
        ownership_snapshot: Optional[Dict[str, Any]],
    ) -> None:
        if not ownership_snapshot or not self.trade_forensics_service:
            return
        try:
            self.trade_forensics_service.record_event(
                {
                    "event_type": "position_opened",
                    "timestamp": self._now_iso(),
                    "forensic_decision_id": ownership_snapshot.get("forensic_decision_id"),
                    "trade_context_id": ownership_snapshot.get("forensic_trade_context_id"),
                    "bot_id": ownership_snapshot.get("bot_id"),
                    "symbol": order.get("symbol"),
                    "mode": ownership_snapshot.get("bot_mode"),
                    "profile": ownership_snapshot.get("bot_profile"),
                    "side": ownership_snapshot.get("forensic_side") or order.get("side"),
                    "decision_type": ownership_snapshot.get("forensic_decision_type"),
                    "linkage_method": (
                        "ownership_snapshot"
                        if ownership_snapshot.get("forensic_trade_context_id")
                        or ownership_snapshot.get("forensic_decision_id")
                        else "bot_symbol_only"
                    ),
                    "attribution_status": (
                        "linked"
                        if ownership_snapshot.get("forensic_trade_context_id")
                        or ownership_snapshot.get("forensic_decision_id")
                        else "unresolved"
                    ),
                    "order": {
                        "order_id": order.get("orderId"),
                        "order_link_id": order.get("orderLinkId"),
                        "order_type": order.get("orderType"),
                        "qty": round(float(qty or 0.0), 8),
                        "price": round(float(fill_price or 0.0), 8),
                        "reduce_only": bool(order.get("reduceOnly")),
                        "position_idx": order.get("positionIdx"),
                    },
                }
            )
        except Exception as exc:
            logger.warning(
                "[%s] Backtest forensic position_opened failed for %s: %s",
                order.get("symbol"),
                order.get("orderId"),
                exc,
            )

    def _get_or_create_position(self, symbol: str, idx: int) -> Dict[str, Any]:
        key = (symbol, idx)
        if key not in self.positions:
            side_map = {1: "Buy", 2: "Sell", 0: "None"}
            self.positions[key] = {
                "symbol": symbol,
                "side": side_map.get(idx, "None"),
                "size": "0",
                "avgPrice": "0",
                "positionValue": "0",
                "unrealisedPnl": "0",
                "leverage": "10",
                "positionIdx": idx,
                "markPrice": str(self.current_prices.get(symbol, 0.0)),
                "_accrued_open_fee": 0.0,
            }
        return self.positions[key]

    def _update_pnl(self, symbol: str, price: float) -> None:
        total_upnl = 0.0
        for (sym, idx), pos in self.positions.items():
            if sym != symbol:
                continue
            size = float(pos.get("size") or 0.0)
            if size <= 0:
                pos["unrealisedPnl"] = "0"
                pos["markPrice"] = str(price)
                pos["positionValue"] = "0"
                continue
            entry = float(pos.get("avgPrice") or 0.0)
            if idx == 1:
                unrealized = (price - entry) * size
            else:
                unrealized = (entry - price) * size
            pos["unrealisedPnl"] = str(round(unrealized, 8))
            pos["markPrice"] = str(round(price, 8))
            pos["positionValue"] = str(round(price * size, 8))
            total_upnl += unrealized
        self.usdt_equity = round(self.wallet_balance + total_upnl, 8)

    def _process_orders(self, symbol: str, high: float, low: float) -> None:
        ranked_orders = sorted(
            [order for order in self.open_orders if order.get("symbol") == symbol],
            key=lambda item: (
                0 if item.get("reduceOnly") else 1,
                int(item.get("createdTime") or 0),
            ),
        )
        for order in ranked_orders:
            price = float(order.get("price") or 0.0)
            side = str(order.get("side") or "").strip()
            if str(order.get("orderType") or "").strip().lower() != "limit":
                continue
            if side == "Buy" and low <= price:
                self._fill_order(order, price, ownership_snapshot=order.get("_ownership_snapshot"))
            elif side == "Sell" and high >= price:
                self._fill_order(order, price, ownership_snapshot=order.get("_ownership_snapshot"))
