# AI Ops Console — Setup Guide

## Quick Start (development)

```bash
cd /var/www
source venv/bin/activate
uvicorn ai_ops_console.app:app --host 127.0.0.1 --port 8001 --reload
```

Open http://localhost:8001 (uses same BASIC_AUTH_USER/PASS as main dashboard).

## Production Setup

### 1. Fix file permissions

```bash
sudo chown -R claude:claude /var/www/storage/ai_ops_*
sudo chown -R claude:claude /var/www/logs/ai_ops*
```

### 2. Install systemd service

```bash
sudo cp /var/www/docs/opus_ai_ops_console.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable opus_ai_ops_console
sudo systemctl start opus_ai_ops_console
```

### 3. Setup nginx + SSL

```bash
# Add DNS A record for aiops.madowlab.online → server IP
sudo cp /var/www/docs/aiops_console_nginx.conf /etc/nginx/sites-available/aiops.madowlab.online
sudo ln -sf /etc/nginx/sites-available/aiops.madowlab.online /etc/nginx/sites-enabled/
sudo certbot --nginx -d aiops.madowlab.online
sudo nginx -t && sudo systemctl reload nginx
```

### 4. Enable dashboard redirect (optional)

Add to `/var/www/.env`:
```
AIOPS_CONSOLE_ENABLED=1
AIOPS_CONSOLE_URL=https://aiops.madowlab.online
```

Then restart the main dashboard:
```bash
sudo systemctl restart opus_trader
```

## Service Management

```bash
# Console
sudo systemctl status opus_ai_ops_console
sudo systemctl restart opus_ai_ops_console
sudo systemctl stop opus_ai_ops_console

# Logs
journalctl -u opus_ai_ops_console -f

# Terminal audit log
tail -f /var/www/logs/ai_ops_console/terminal_audit.jsonl
```

## Rollback

1. Set `AIOPS_CONSOLE_ENABLED=0` in .env
2. Restart main dashboard: `sudo systemctl restart opus_trader`
3. Stop console: `sudo systemctl stop opus_ai_ops_console`

The main dashboard's embedded AI Ops panel works as before.

## Architecture

- Port 8001 (console) is independent from port 8000 (main dashboard)
- Both can read/write the same AI Ops files (fcntl-locked)
- Console does NOT initialize the trading runtime
- Console runs as `claude` user, not root
