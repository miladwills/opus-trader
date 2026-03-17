
import sys
import os
import time
from typing import List, Dict, Any

# Add current directory to path so we can import services
sys.path.append(os.getcwd())

from services.client_factory import create_bybit_client

def scan_funding_rates():
    """
    Scan all USDT perpetuals for high funding rates.
    """
    print("Initializing Bybit Client...")
    try:
        # Create client (defaults to mainnet)
        client = create_bybit_client()
    except Exception as e:
        print(f"Failed to create client: {e}")
        return

    print("Fetching all USDT perpetual tickers...")
    
    # Fetch all linear tickers (USDT perps)
    # Using specific category 'linear' for USDT perpetuals
    response = client.get_tickers()
    
    if not response.get("success"):
        print(f"API Error: {response.get('error')}")
        return

    data = response.get("data", {})
    tickers = data.get("list", [])
    
    if not tickers:
        print("No tickers found.")
        return

    print(f"Scanned {len(tickers)} symbols. Filtering and sorting...")

    funding_opportunities = []

    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        
        # Only interest in USDT perps
        if not symbol.endswith("USDT"):
            continue

        funding_rate_str = ticker.get("fundingRate", "0")
        
        try:
            funding_rate = float(funding_rate_str)
            funding_rate_pct = funding_rate * 100
            
            # Filter out zero or near-zero to reduce noise (optional, but good for focus)
            # keeping everything for now to sort accurately
            
            funding_opportunities.append({
                "symbol": symbol,
                "rate": funding_rate,
                "rate_pct": funding_rate_pct,
                "price": ticker.get("lastPrice", "0")
            })
            
        except ValueError:
            continue

    # Sort by funding rate (ascending) -> Highest Negative first (Best Longs)
    funding_opportunities.sort(key=lambda x: x["rate"])

    print("\n" + "="*60)
    print(f"TOP 10 NEGATIVE FUNDING (Shorts Pay Longs) - BULLISH")
    print("="*60)
    print(f"{'SYMBOL':<15} {'FUNDING RATE':<15} {'PRICE':<15}")
    print("-" * 60)
    
    for item in funding_opportunities[:10]:
        rate_str = f"{item['rate_pct']:.4f}%"
        print(f"{item['symbol']:<15} {rate_str:<15} {item['price']:<15}")


    print("\n" + "="*60)
    print(f"TOP 10 POSITIVE FUNDING (Longs Pay Shorts) - BEARISH")
    print("="*60)
    print(f"{'SYMBOL':<15} {'FUNDING RATE':<15} {'PRICE':<15}")
    print("-" * 60)
    
    # Sort descending for positive
    funding_opportunities.sort(key=lambda x: x["rate"], reverse=True)
    
    for item in funding_opportunities[:10]:
        rate_str = f"{item['rate_pct']:.4f}%"
        print(f"{item['symbol']:<15} {rate_str:<15} {item['price']:<15}")

if __name__ == "__main__":
    scan_funding_rates()
