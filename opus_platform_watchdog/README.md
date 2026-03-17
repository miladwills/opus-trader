# Opus Platform Watchdog

Independent, read-only monitoring service for Opus Trader platform health.

## Quick Start

```bash
# 1. Copy and edit environment config
cp .env.example .env
nano .env

# 2. Install (if not using shared venv)
pip install -r requirements.txt

# 3. Run directly
cd /var/www
uvicorn opus_platform_watchdog.main:app --host 127.0.0.1 --port 9000

# 4. Or install as systemd service
sudo cp opus_watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opus_watchdog

# 5. Configure nginx subdomain
sudo cp watchdog.madowlab.online.nginx /etc/nginx/sites-available/watchdog.madowlab.online
sudo ln -s /etc/nginx/sites-available/watchdog.madowlab.online /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## What It Monitors

| Component | Method | Cadence |
|-----------|--------|---------|
| Bootstrap API | HTTP probe | 30s |
| Bridge diagnostics | HTTP probe | 15s |
| Services status | HTTP probe | 15s |
| Bridge JSON file | File read | 10s |
| Runner lock file | File read | 15s |
| Log freshness | File stat | 15s |
| opus_trader service | systemctl | 30s |
| opus_runner service | systemctl | 30s |
| System resources | /proc read | 30s |
| Runner log patterns | File tail | 10s |
| App log patterns | File tail | 15s |

## Pages

| URL | Content |
|-----|---------|
| `/` | Dashboard - health score, component cards, incidents |
| `/incidents` | Incident timeline with filtering |
| `/probes` | Per-probe status and latency sparklines |
| `/bridge` | Bridge section freshness detail |
| `/system` | CPU, RAM, disk, services, runner lock |
| `/debug` | Raw JSON of all probe results and health |

## Architecture

See [docs/architecture.md](docs/architecture.md) for details.

## Safety

- Read-only: no write actions to Opus Trader
- No shell execution from browser
- No service restart buttons
- No file modification
- No imports from Opus Trader codebase
- Auth-protected UI (HTTP Basic)
