python3 << 'EOF'
import sys

# Patch bybit_client.py
with open('/var/www/services/bybit_client.py', 'r') as f:
    client_code = f.read()

old_qty = '        "qty": str(normalized_qty),'
new_qty = '        "qty": f"{normalized_qty:f}".rstrip("0").rstrip("."),'
if old_qty in client_code:
    client_code = client_code.replace(old_qty, new_qty)
    with open('/var/www/services/bybit_client.py', 'w') as f:
        f.write(client_code)
    print("Patched bybit_client.py")
else:
    if new_qty in client_code:
        print("bybit_client.py is already patched.")
    else:
        print("ERROR: Could not find old_qty in bybit_client.py")

# Patch grid_bot_service.py
with open('/var/www/services/grid_bot_service.py', 'r') as f:
    grid_code = f.read()

old_grid = '''        if not mode or (self.client._get_now_ts() - float(ts or 0) > 60):
            mode = self._get_position_mode(bot, symbol)
        if mode is None:'''

new_grid = '''        if not mode or (self.client._get_now_ts() - float(ts or 0) > 60):
            mode = self._get_position_mode(bot, symbol)
            if mode:
                bot["_position_mode"] = mode
                bot["_position_mode_ts"] = self.client._get_now_ts()
        if mode is None:'''

if old_grid in grid_code:
    grid_code = grid_code.replace(old_grid, new_grid)
    with open('/var/www/services/grid_bot_service.py', 'w') as f:
        f.write(grid_code)
    print("Patched grid_bot_service.py")
else:
    if new_grid in grid_code:
        print("grid_bot_service.py is already patched.")
    else:
        print("ERROR: Could not find old_grid in grid_bot_service.py")
EOF

echo "Restarting opus_runner service..."
systemctl restart opus_runner
echo "Restart complete."
