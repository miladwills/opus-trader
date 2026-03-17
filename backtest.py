
import os
import sys
import argparse
import logging
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

from services.backtest.engine import BacktestEngine
from services.bybit_client import BybitClient

# Load env for API keys if needed (for downloading data)
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BacktestRunner")

def download_data(symbol: str, days: int, interval: str = "15"):
    """
    Download historical data using BybitClient.
    """
    logger.info(f"Downloading {days} days of data for {symbol}...")
    
    # Init real client (public endpoints don't strictly need keys but good to have)
    client = BybitClient(os.getenv("BYBIT_API_KEY"), os.getenv("BYBIT_API_SECRET"), "https://api.bybit.com")
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    all_klines = []
    
    # Bybit limit is 200 per request. We need to page.
    # get_kline takes end time? V5 uses 'end' parameter (timestamp ms).
    
    current_end = int(end_time.timestamp() * 1000)
    target_start = int(start_time.timestamp() * 1000)
    
    while current_end > target_start:
        # Fetch
        # We need to access the raw request or use get_kline loop. 
        # BybitClient.get_kline default limit is 200.
        # We need to manually construct requests to page backwards.
        
        # NOTE: The current BybitClient.get_kline doesn't expose 'end' param in signature,
        # but passes **kwargs to _request.
        
        resp = client.get_kline(symbol=symbol, interval=interval, limit=200, end=current_end)
        
        if not resp["success"]:
            logger.error(f"Error fetching data: {resp}")
            break
            
        data = resp["data"]["list"]
        if not data:
            break
            
        # Data is [start, open, high, low, close, vol, turnover]
        # Sorted by time descending (latest first)
        
        # Oldest in this batch
        oldest_ts = int(data[-1][0])
        
        # If we aren't making progress, break
        if oldest_ts >= current_end:
            break
            
        current_end = oldest_ts - 1
        all_klines.extend(data)
        
        print(f"Fetched {len(all_klines)} candles...", end="\r")
        time.sleep(0.1) # Rate limit
    
    print("")
    
    # Process
    # [ts, open, high, low, close, vol, turnover]
    records = []
    for k in all_klines:
        records.append({
            "timestamp": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })
        
    df = pd.DataFrame(records)
    df.sort_values("timestamp", inplace=True)
    df = df[df["timestamp"] >= target_start]
    
    os.makedirs("data", exist_ok=True)
    path = f"data/{symbol}_{interval}.csv"
    df.to_csv(path, index=False)
    logger.info(f"Saved to {path}")
    return path

import time

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Backtest")
    parser.add_argument("--symbol", type=str, default="ETHUSDT", help="Trading symbol")
    parser.add_argument("--days", type=int, default=3, help="Days of history")
    parser.add_argument("--capital", type=float, default=1000.0, help="Initial capital")
    parser.add_argument("--csv", type=str, help="Path to CSV file (optional)")
    
    args = parser.parse_args()
    
    csv_path = args.csv
    if not csv_path:
        csv_path = f"data/{args.symbol}_15.csv"
        if not os.path.exists(csv_path):
            csv_path = download_data(args.symbol, args.days)
            
    # Run Engine
    engine = BacktestEngine(args.symbol, "", "", args.capital)
    engine.load_data(csv_path)
    
    # Setup test bot
    engine.setup_bot({
        "grid_step_pct": 0.005,
        "mode": "neutral"
    })
    
    start_t = time.time()
    engine.run()
    duration = time.time() - start_t
    
    print(f"\nSimulation took {duration:.2f}s")
    print(f"Final Equity: {engine.client.usdt_equity:.2f}")
    profit = engine.client.usdt_equity - args.capital
    print(f"Profit: {profit:.2f} ({profit/args.capital*100:.2f}%)")
