import json

bots = json.load(open('/var/www/opus_trader/storage/bots.json'))
print(f'Before: {len(bots)} bots')

# Keep bots that are NOT (PIPPINUSDT AND stopped)
filtered = [b for b in bots if not (b.get('symbol') == 'PIPPINUSDT' and b.get('status') == 'stopped')]
print(f'After: {len(filtered)} bots')
print(f'Removed {len(bots) - len(filtered)} stopped PIPPINUSDT bots')

# Write back
with open('/var/www/opus_trader/storage/bots.json', 'w') as f:
    json.dump(filtered, f, indent=2)
print('Done!')
