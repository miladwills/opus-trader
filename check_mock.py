
from services.backtest.mock_client import MockBybitClient
import sys

print("Checking MockClient...")
try:
    client = MockBybitClient()
    
    # Check get_position_mode
    print("1. Testing get_position_mode...")
    if hasattr(client, 'get_position_mode'):
        res = client.get_position_mode()
        print(f"   Success: {res}")
    else:
        print("   FAILED: Method missing!")

    # Check place_order
    print("2. Testing place_order...")
    res = client.place_order('linear', 'BTCUSDT', 'Buy', 'Market', '0.1')
    print(f"   Success: {res}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
