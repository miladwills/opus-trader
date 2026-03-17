"""
Bybit Control Center - Symbol PnL Service

Tracks cumulative profit/loss per trading symbol across all bots and time.
Data persists even when bots are deleted.
"""

from pathlib import Path
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


class SymbolPnlService:
    """
    Service for tracking and persisting cumulative PnL per trading symbol.
    """

    def __init__(self, file_path: str = "storage/symbol_pnl.json"):
        """
        Initialize the symbol PnL service.

        Args:
            file_path: Path to the JSON file for symbol PnL storage
        """
        self.file_path = Path(file_path)

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create file with empty dict if it doesn't exist
        if not self.file_path.exists():
            self._write_data({})

    def _read_data(self) -> Dict[str, Any]:
        """
        Read all symbol PnL data from the JSON file.

        Returns:
            Dict of symbol -> pnl data, or empty dict on error
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            return {}

    def _write_data(self, data: Dict[str, Any]) -> None:
        """
        Write all symbol PnL data to the JSON file.

        Args:
            data: Dict of symbol -> pnl data to write
        """
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except (IOError, OSError):
            pass  # Silently fail on write errors

    def record_trade(
        self,
        symbol: str,
        realized_pnl: float,
        side: str,
        bot_id: Optional[str] = None,
        trade_id: Optional[str] = None,
    ) -> None:
        """
        Record a closed trade for a symbol and bot.
        Tracks both symbol-level and bot-level P&L.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            realized_pnl: Realized profit/loss from the trade
            side: Trade side ("Buy" or "Sell")
            bot_id: Optional bot ID that made the trade
            trade_id: Optional unique trade identifier
        """
        data = self._read_data()
        now_iso = datetime.now(timezone.utc).isoformat()

        # --- Symbol-level tracking ---
        if symbol not in data:
            data[symbol] = {
                "symbol": symbol,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "net_pnl": 0.0,
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "first_trade_at": now_iso,
                "last_trade_at": now_iso,
                "bot_ids_used": [],
                "recent_trades": [],  # Last 50 trades for detail view
            }

        symbol_data = data[symbol]

        # Update symbol totals
        if realized_pnl > 0:
            symbol_data["total_profit"] += realized_pnl
            symbol_data["win_count"] += 1
        elif realized_pnl < 0:
            symbol_data["total_loss"] += abs(realized_pnl)
            symbol_data["loss_count"] += 1

        symbol_data["net_pnl"] = symbol_data["total_profit"] - symbol_data["total_loss"]
        symbol_data["trade_count"] += 1
        symbol_data["last_trade_at"] = now_iso

        # Track bot IDs used
        if bot_id and bot_id not in symbol_data["bot_ids_used"]:
            symbol_data["bot_ids_used"].append(bot_id)

        # Add to recent trades (keep last 50)
        trade_entry = {
            "time": now_iso,
            "pnl": realized_pnl,
            "side": side,
            "bot_id": bot_id,
            "trade_id": trade_id,
        }
        symbol_data["recent_trades"].insert(0, trade_entry)
        symbol_data["recent_trades"] = symbol_data["recent_trades"][:50]

        # --- Bot-level tracking ---
        if bot_id:
            bot_key = f"bot:{bot_id}"
            if bot_key not in data:
                data[bot_key] = {
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "total_profit": 0.0,
                    "total_loss": 0.0,
                    "net_pnl": 0.0,
                    "trade_count": 0,
                    "win_count": 0,
                    "loss_count": 0,
                    "first_trade_at": now_iso,
                    "last_trade_at": now_iso,
                    "recent_trades": [],
                }

            bot_data = data[bot_key]
            bot_data["symbol"] = symbol  # Update symbol in case it changed

            # Update bot totals
            if realized_pnl > 0:
                bot_data["total_profit"] += realized_pnl
                bot_data["win_count"] += 1
            elif realized_pnl < 0:
                bot_data["total_loss"] += abs(realized_pnl)
                bot_data["loss_count"] += 1

            bot_data["net_pnl"] = bot_data["total_profit"] - bot_data["total_loss"]
            bot_data["trade_count"] += 1
            bot_data["last_trade_at"] = now_iso

            # Add to bot's recent trades (keep last 50)
            bot_data["recent_trades"].insert(0, trade_entry)
            bot_data["recent_trades"] = bot_data["recent_trades"][:50]

        self._write_data(data)

    def get_symbol_pnl(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get PnL data for a specific symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Symbol PnL data dict, or None if not found
        """
        data = self._read_data()
        return data.get(symbol)

    def get_all_symbols_pnl(self) -> Dict[str, Any]:
        """
        Get PnL data for all symbols.

        Returns:
            Dict of symbol -> pnl data, excluding bot-scoped entries
        """
        data = self._read_data()
        return {
            key: value
            for key, value in data.items()
            if not str(key).startswith("bot:")
        }

    def get_symbol_summary(self, symbol: str) -> Dict[str, Any]:
        """
        Get a summary of PnL for a symbol (for display in bot table).

        Args:
            symbol: Trading symbol

        Returns:
            Summary dict with key metrics
        """
        pnl_data = self.get_symbol_pnl(symbol)
        
        if not pnl_data:
            return {
                "symbol": symbol,
                "net_pnl": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
            }

        trade_count = pnl_data.get("trade_count", 0)
        win_count = pnl_data.get("win_count", 0)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

        return {
            "symbol": symbol,
            "net_pnl": round(pnl_data.get("net_pnl", 0.0), 4),
            "total_profit": round(pnl_data.get("total_profit", 0.0), 4),
            "total_loss": round(pnl_data.get("total_loss", 0.0), 4),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 1),
            "win_count": win_count,
            "loss_count": pnl_data.get("loss_count", 0),
            "first_trade_at": pnl_data.get("first_trade_at"),
            "last_trade_at": pnl_data.get("last_trade_at"),
        }

    def get_bot_pnl(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get PnL data for a specific bot.

        Args:
            bot_id: Bot ID

        Returns:
            Bot PnL data dict, or None if not found
        """
        data = self._read_data()
        return data.get(f"bot:{bot_id}")

    def get_bot_pnl_summary(self, bot_id: str) -> Dict[str, Any]:
        """
        Get a summary of PnL for a specific bot (for display in bot table).

        Args:
            bot_id: Bot ID

        Returns:
            Summary dict with key metrics for the bot
        """
        pnl_data = self.get_bot_pnl(bot_id)

        if not pnl_data:
            return {
                "bot_id": bot_id,
                "net_pnl": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
            }

        trade_count = pnl_data.get("trade_count", 0)
        win_count = pnl_data.get("win_count", 0)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

        return {
            "bot_id": bot_id,
            "symbol": pnl_data.get("symbol"),
            "net_pnl": round(pnl_data.get("net_pnl", 0.0), 4),
            "total_profit": round(pnl_data.get("total_profit", 0.0), 4),
            "total_loss": round(pnl_data.get("total_loss", 0.0), 4),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 1),
            "win_count": win_count,
            "loss_count": pnl_data.get("loss_count", 0),
            "first_trade_at": pnl_data.get("first_trade_at"),
            "last_trade_at": pnl_data.get("last_trade_at"),
        }

    def get_all_bot_pnl(self) -> Dict[str, Dict[str, Any]]:
        """
        Get PnL data for all bots.

        Returns:
            Dict of bot_id -> pnl data (excluding symbol-level entries)
        """
        data = self._read_data()
        return {k.replace("bot:", ""): v for k, v in data.items() if k.startswith("bot:")}

    def rebuild_from_logs(self, trade_logs: List[Dict[str, Any]]) -> None:
        """
        Rebuild symbol PnL data from existing trade logs.
        Useful for initial migration or data recovery.

        Args:
            trade_logs: List of trade log entries from PnlService
        """
        # Clear existing data
        data = {}

        for log in trade_logs:
            symbol = log.get("symbol")
            if not symbol:
                continue

            realized_pnl = log.get("realized_pnl", 0)
            try:
                realized_pnl = float(realized_pnl)
            except (ValueError, TypeError):
                continue

            side = log.get("side", "")
            bot_id = log.get("bot_id")
            trade_id = log.get("id")
            time_str = log.get("time", datetime.now(timezone.utc).isoformat())

            if symbol not in data:
                data[symbol] = {
                    "symbol": symbol,
                    "total_profit": 0.0,
                    "total_loss": 0.0,
                    "net_pnl": 0.0,
                    "trade_count": 0,
                    "win_count": 0,
                    "loss_count": 0,
                    "first_trade_at": time_str,
                    "last_trade_at": time_str,
                    "bot_ids_used": [],
                    "recent_trades": [],
                }

            symbol_data = data[symbol]

            # Update totals
            if realized_pnl > 0:
                symbol_data["total_profit"] += realized_pnl
                symbol_data["win_count"] += 1
            elif realized_pnl < 0:
                symbol_data["total_loss"] += abs(realized_pnl)
                symbol_data["loss_count"] += 1

            symbol_data["net_pnl"] = symbol_data["total_profit"] - symbol_data["total_loss"]
            symbol_data["trade_count"] += 1
            symbol_data["last_trade_at"] = time_str

            # Track bot IDs used
            if bot_id and bot_id not in symbol_data["bot_ids_used"]:
                symbol_data["bot_ids_used"].append(bot_id)

            # Add to recent trades (keep last 50)
            trade_entry = {
                "time": time_str,
                "pnl": realized_pnl,
                "side": side,
                "bot_id": bot_id,
                "trade_id": trade_id,
            }
            symbol_data["recent_trades"].append(trade_entry)

            # --- Bot-level tracking ---
            if bot_id:
                bot_key = f"bot:{bot_id}"
                if bot_key not in data:
                    data[bot_key] = {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "total_profit": 0.0,
                        "total_loss": 0.0,
                        "net_pnl": 0.0,
                        "trade_count": 0,
                        "win_count": 0,
                        "loss_count": 0,
                        "first_trade_at": time_str,
                        "last_trade_at": time_str,
                        "recent_trades": [],
                    }
                
                bot_data = data[bot_key]
                bot_data["symbol"] = symbol
                
                if realized_pnl > 0:
                    bot_data["total_profit"] += realized_pnl
                    bot_data["win_count"] += 1
                elif realized_pnl < 0:
                    bot_data["total_loss"] += abs(realized_pnl)
                    bot_data["loss_count"] += 1
                
                bot_data["net_pnl"] = bot_data["total_profit"] - bot_data["total_loss"]
                bot_data["trade_count"] += 1
                bot_data["last_trade_at"] = time_str
                bot_data["recent_trades"].append(trade_entry)

        # Sort recent trades by time and keep last 50
        for symbol in data:
            trades = data[symbol]["recent_trades"]
            trades.sort(key=lambda x: x.get("time", ""), reverse=True)
            data[symbol]["recent_trades"] = trades[:50]

        self._write_data(data)

