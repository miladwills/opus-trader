# Operations Guide

## Service Management

```bash
# Start / stop / restart
sudo systemctl start opus_watchdog
sudo systemctl stop opus_watchdog
sudo systemctl restart opus_watchdog

# Check status
sudo systemctl status opus_watchdog

# View logs
sudo journalctl -u opus_watchdog -f
```

## Configuration

Edit `/var/www/opus_platform_watchdog/.env` then restart:

```bash
sudo systemctl restart opus_watchdog
```

Key settings:
- `WATCHDOG_AUTH_USER/PASS` - UI authentication
- `OPUS_TRADER_BASE_URL` - where to probe (default: http://127.0.0.1:8000)
- `OPUS_TRADER_AUTH_USER/PASS` - credentials for API probes
- `LOG_SCAN_BYTES` - how many bytes to tail per scan (default: 65536)

## Database

SQLite at `/var/www/opus_platform_watchdog/watchdog.db`.

To reset: stop service, delete `watchdog.db`, start service. Tables are auto-created.

To inspect:
```bash
sqlite3 /var/www/opus_platform_watchdog/watchdog.db
.tables
SELECT COUNT(*) FROM probe_results;
SELECT * FROM incidents WHERE status = 'open';
```

## Nginx

Config at `/etc/nginx/sites-available/watchdog.madowlab.online`.

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/watchdog.madowlab.online /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Troubleshooting

**Watchdog can't reach Opus Trader API:**
- Check `OPUS_TRADER_BASE_URL` in .env
- Check `OPUS_TRADER_AUTH_USER/PASS`
- Verify opus_trader is running: `systemctl is-active opus_trader`

**No incidents appearing:**
- Check log paths in .env match actual log locations
- Check log files exist and are being written to
- View debug page at `/debug` for raw probe results

**High memory usage:**
- Check retention settings (reduce days)
- Run manual purge: restart service (purge runs on hourly schedule)
