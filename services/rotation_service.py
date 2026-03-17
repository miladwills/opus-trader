
import logging
import time
from typing import List, Dict, Any, Optional
from services.neutral_scanner_service import NeutralScannerService
from services.bot_storage_service import BotStorageService

logger = logging.getLogger(__name__)

class RotationService:
    """
    Smart Rotation Service (Opportunity Hunter).
    Periodically scans the market and rotates capital from weak bots to strong opportunities.
    """
    def __init__(self, scanner: NeutralScannerService, bot_storage: BotStorageService):
        self.scanner = scanner
        self.bot_storage = bot_storage
        self.last_rotation_check = 0
        self.rotation_interval = 3600  # Check every hour
        self.min_score_diff = 20       # New opp must be 20 points better
        self.min_active_score = 40     # If bot score > 40, keep it (don't churn)
        
    def check_rotation(self, active_bots: List[Dict[str, Any]]):
        """
        Check if we should rotate any bots.
        """
        if time.time() - self.last_rotation_check < self.rotation_interval:
            return []
            
        self.last_rotation_check = time.time()
        logger.info("Checking for rotation opportunities...")
        
        # 1. Scan Market
        # We need a list of candidate symbols. 
        # Ideally, we scan a top 50 list. For MVP, we'll scan a hardcoded list or fetch tickers.
        # Let's assume scanner has a default list or we pass one.
        candidates = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "POLUSDT", "DOTUSDT", "LTCUSDT"]
        
        scan_results = self.scanner.scan(candidates)
        if not scan_results:
            return []
            
        top_pick = scan_results[0]
        top_score = top_pick["neutral_score"]
        top_symbol = top_pick["symbol"]
        
        logger.info(f"Top market opportunity: {top_symbol} (Score: {top_score})")
        
        # 2. Evaluate Active Bots
        start_requests = []
        stop_requests = []
        
        active_symbols = [b["symbol"] for b in active_bots]
        
        if top_symbol in active_symbols:
            logger.info("Top opportunity is already running.")
            return []
            
        # Find weakest bot
        weakest_bot = None
        min_score = 100
        
        for bot in active_bots:
            # We need to re-score the active bot
            # This requires calling scan on its symbol
            res = self.scanner.scan([bot["symbol"]])
            if not res: continue
            
            score = res[0]["neutral_score"]
            if score < min_score:
                min_score = score
                weakest_bot = bot
                
        if not weakest_bot:
            return []
            
        logger.info(f"Weakest running bot: {weakest_bot['symbol']} (Score: {min_score})")
        
        # 3. Decision
        # Logic: If Top Score > Weakest Score + Diff AND Weakest < Threshold
        if (top_score > min_score + self.min_score_diff) and (min_score < self.min_active_score):
            logger.info(f"ROTATION SIGNAL: Swap {weakest_bot['symbol']} -> {top_symbol}")
            
            # Request Stop
            stop_requests.append(weakest_bot["id"])
            
            # Request Start (we return the config to start)
            # We can't start immediately until funds released.
            # So typically we just signal the user or queue it.
            # For this MVP, we will return the instructions.
            
            return {
                "stop_bot_ids": stop_requests,
                "start_symbol": top_symbol,
                "start_config": {
                    "symbol": top_symbol,
                    "mode": "neutral", # or derived from scanner recommendation
                    "leverage": 3,     # safe default
                    "investment": weakest_bot.get("investment", 0) # recycle capital
                }
            }
            
        return None
