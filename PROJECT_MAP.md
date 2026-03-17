# Project Overview
- Flask-based Bybit Futures control center with dashboard and JSON APIs to manage grid/ scalp bots and emergency controls against Bybit V5.
- Tech stack: Python 3, Flask, Requests; Tailwind + vanilla JS frontend; JSON file storage under `storage/`; Bybit V5 REST (linear USDT perps).
- Runtime pieces: `app.py` web/API server on :8000 with HTTP Basic Auth; `runner.py` background loop driving bots every ~10s; browser UI polls APIs every 3–10s; optional `start.bat` launches both.

# High-level Architecture
- Components: Web UI (`templates/dashboard.html`, `static/js/app.js`) → Flask routes (`app.py`) → services layer (`services/*`) → Bybit API + JSON storage; Background Runner (`runner.py`) → services → Bybit + storage.
- Data flow: Browser polls `/api/...` → Flask orchestrates Account/Position/Bot/PnL services → Bybit and storage JSON; Runner loads bots → computes ranges/indicators → places/cancels orders → syncs PnL → updates bots.json/trade logs.
- Patterns: Thin controllers, service layer for business logic, JSON persistence instead of DB, background worker coordinated via log/stop-flag files.

# Folder Structure and Responsibilities
- `config/` Static credentials, env labels, strategy/risk constants, Basic Auth decorator.
- `services/` All domain logic: Bybit client, bot CRUD/status, grid/range/indicator engines, scanners, risk, PnL, scalp logic.
- `templates/` Dashboard HTML (Tailwind).
- `static/js/` Frontend behavior, polling, modals, actions.
- `storage/` Runtime JSON state (bots, trade_logs, risk_state, symbol_pnl, runner log/stop flag).
- `runner.py` Background bot loop; `app.py` Flask server/APIs; `start.bat` convenience launcher.

# File Responsibilities (per folder)
- `app.py` Flask app; loads config/services, rebuilds symbol PnL on boot; serves dashboard; APIs for account, positions, summary, bot CRUD/lifecycle, symbol PnL, neutral scan, price info, PnL logs, runner start/stop, emergency stop, close/set TP/SL, status/log streaming.
- `runner.py` Infinite loop: load config/services, clear stop flag, every ~10s run running bots via GridBotService, sync closed PnL, update bot realized PnL, honor stop flag, log to storage/runner.log.
- `config/config.py` Hard-coded Bybit keys/base URL/env label and dashboard Basic Auth; `require_basic_auth` decorator; `load_config`.
- `config/strategy_config.py` Grid/risk constants (step %, default leverage/investment, TP defaults, range bounds, ATR bands, scalp thresholds).
- `services/bybit_client.py` Signed Bybit V5 REST helper (tickers, kline, positions, wallet balance, create/cancel orders, cancel all, closed PnL, instruments info, open orders, trading stop).
- `services/account_service.py` Wallet balance → equity/available/realized/unrealized PnL.
- `services/position_service.py` Normalize positions, leverage vs account equity, pct-to-liquidation, TP/SL, summaries.
- `services/bot_storage_service.py` JSON persistence for bots (UUIDs, timestamps, CRUD).
- `services/bot_manager_service.py` Validate/normalize bot configs (mode/profile/range/tp%), CRUD + start/pause/resume/stop/delete with order cancel.
- `services/bot_status_service.py` Enrich bots with live positions, PnL%, range info, symbol PnL; summaries; bot detail (trade history).
- `services/grid_engine_service.py` Geometric grid level builder + grid count estimation.
- `services/range_engine_service.py` Volatility-aware neutral range builder (ATR/BBW clamps).
- `services/indicator_service.py` OHLCV fetch + RSI/ADX/ATR%/BBW%, EMA/SMA, MACD, volume trends, candlestick detection.
- `services/entry_filter_service.py` Market regime classifier for scanner (choppy/trending/too_strong/illiquid).
- `services/neutral_scanner_service.py` Scores symbols, computes ranges, BTC correlation, neutral suitability.
- `services/pnl_service.py` Pull closed PnL, persist trade logs, compute today stats, update per-bot realized PnL, feed symbol PnL service, rebuild.
- `services/symbol_pnl_service.py` Cumulative PnL per symbol with recent trades, win rates; rebuild from logs.
- `services/risk_manager_service.py` Persisted risk state, track equity, per-bot loss checks, daily reset; (global kill switch disabled).
- `services/grid_bot_service.py` Core bot cycle: price/indicators, auto-direction mode, dynamic/trailing ranges, grid build, risk checks, TP %, scalp modes, order placement with tolerance, close/cancel helpers, instrument cache.
- `services/indicator_service.py` (already noted) + provides candle pattern detection for grid/scalp decisions.
- `services/position_service.py` (already noted) used across APIs/bot status.
- `services/scalp_pnl_service.py` Unrealized PnL scalp logic: market condition analysis, targets, scalp grid placement, choppiness detection.
- `services/neutral_scanner_service.py` (already noted) for `/api/neutral-scan`.
- `static/js/app.js` Dashboard logic: polling, flashing updates, bot form, actions (save/start/pause/resume/stop/delete), TP/SL, emergency stop, neutral scan UI, bot status/log modals, runner start/stop, sounds.
- `templates/dashboard.html` Tailwind UI layout with sections for summary, positions, bots, scanner, PnL, modals; loads `static/js/app.js`.
- `start.bat` Windows helper to start Flask + runner in separate consoles.

# Data & Domain Model
- Bot record (`storage/bots.json`): `id`, `symbol`, `mode` (neutral/long/short/scalp_pnl/scalp_market), `profile` (normal/scalp), `range_mode` (fixed/dynamic/trailing), `lower_price`, `upper_price`, `investment`, `leverage`, `grid_count`, `tp_pct`, `auto_stop`, `auto_direction`, `last_range_width_pct`, `status` (running/paused/stopped/out_of_range/risk_stopped/tp_hit/error), PnL fields (`realized_pnl`, `unrealized_pnl`, `total_pnl`), runtime metadata (`current_price`, `last_run_at`, `last_error`, timestamps), scalp fields (`scalp_status`, `scalp_signal_score`, etc.).
- Trade logs (`storage/trade_logs.json` via PnlService): entries with `id`, `time`, `symbol`, `side`, `realized_pnl`, `bot_id`.
- Risk state (`storage/risk_state.json`): `daily_start_equity`, `peak_equity`, `global_kill_switch`, per-bot loss state.
- Symbol PnL (`storage/symbol_pnl.json`): per symbol totals (profit/loss/net, counts, win_rate, bot_ids_used, recent_trades, first/last trade).
- Runner artifacts: `storage/runner.log` for log streaming; `storage/runner.stop` flag to halt loop.

# External Integrations
- Bybit V5 (linear USDT perps): tickers `/v5/market/tickers`, kline `/v5/market/kline`, instruments `/v5/market/instruments-info`, wallet balance `/v5/account/wallet-balance`, positions `/v5/position/list`, closed PnL `/v5/position/closed-pnl`, open orders `/v5/order/realtime`, create order `/v5/order/create`, cancel `/v5/order/cancel`, cancel-all `/v5/order/cancel-all`, trading stop `/v5/position/trading-stop`.
- Auth: HMAC SHA256 signature with `timestamp+api_key+recv_window+params/body`; keys from `config/config.py`.
- Dashboard protection: HTTP Basic Auth (`admin`/`112233` by default) via `require_basic_auth`.

# Jobs, Cron, Background Workers
- `runner.py` main loop (every ~10s, checks stop flag each second): refresh account equity, risk state; iterate running bots → GridBotService.run_bot_cycle; sync closed PnL; update per-bot realized PnL; graceful exit on `storage/runner.stop`.
- Runner controlled via APIs `/api/runner/start` (detached subprocess) and `/api/runner/stop` (creates stop flag); status inferred from runner.log mtime.

# Configuration & Environment
- Credentials/base URL/env label and Basic Auth in `config/config.py` (currently hard-coded); `load_config()` consumed by app/runner.
- Strategy/risk constants in `config/strategy_config.py` (grid step, default leverage/investment, TP defaults, range bounds, ATR bands, scalp thresholds).
- No .env loader; update config file directly for keys/labels.

# How to Run (Quick Start)
- Install deps: `pip install -r requirements.txt`.
- Start web server: `python app.py` (port 8000).
- Start runner: `python runner.py` (or via dashboard “Start Runner” or `start.bat` to launch both).
- Ensure `storage/` exists (created automatically) and Bybit API keys set in `config/config.py`.

# Important Flows to Know
1. Dashboard load → `dashboard.html` pulls Tailwind/JS → `app.js` kicks off `refreshAll()` timers (3s/10s) for summary/positions/bots/pnl.
2. Summary fetch `/api/summary` → AccountService + PositionService + PnlService.today stats → app.js flashes values & updates title (unrealized PnL).
3. Positions fetch `/api/positions` → PositionService normalizes leverage, pct-to-liq, TP/SL → table renders with close/TP actions.
4. Price fetch `/api/price` → Bybit tickers + instruments info → returns min qty/value, tick size for bot presets/form validation.
5. Bot create/update `/api/bots` (POST) → BotManagerService.normalize (defaults, tp%, range_mode, mode/profile) → BotStorageService.save_bot.
6. Bot start/pause/resume/stop/delete APIs → BotManagerService updates status and cancels orders on stop/delete.
7. Runner start via `/api/runner/start` → subprocess Popen on `runner.py`; stop via `/api/runner/stop` creates stop flag checked each second.
8. Runner cycle (`runner.py` loop) → load bots + account equity → risk_manager.update_equity_state → for each running bot call GridBotService.run_bot_cycle.
9. GridBotService bot reload → fetch latest bot from storage to avoid stale status; skip if not running.
10. Indicator fetch inside run_cycle → IndicatorService.compute_indicators (15m; sometimes 1h for auto-direction) → ATR/BBW etc for range/step sizing.
11. Auto-direction (if enabled) → `_compute_smart_auto_direction` scores RSI/ADX/EMA/MACD/volume/candles to flip mode neutral/long/short.
12. Range handling → fixed/dynamic/trailing via RangeEngineService.build_neutral_range when price moves >0.8% from last grid center; stores last_range_width_pct.
13. TP check → compares realized_pnl vs tp_pct * (investment*leverage); on hit closes symbol orders/positions, marks status `tp_hit`.
14. Risk checks → RiskManagerService.check_bot_limits and extra unrealized-aware check; may cancel/close and mark `risk_stopped`.
15. Grid build → GridEngineService.build_levels with ATR-adjusted step; biased buy/sell levels by mode/trend; tolerance check avoids duplicate orders near existing.
16. Order sizing → investment * leverage / (levels * price) rounded to qty_step; validates min order qty/value ($5) using instrument filters; creates limit orders via Bybit client.
17. Scalp PnL mode → ScalpPnlService analyzes momentum/volatility/choppiness to decide profit-taking and tight grid placement near price; may hold/exit dynamically.
18. Scalp Market mode → uses constants (tp/sl USD or pct, cooldown, min signal) with GridBotService `_run_scalp_market_cycle` to place market trades rapidly.
19. Closed PnL sync → runner calls PnlService.sync_closed_pnl (Bybit closed-pnl API) → append new trades to trade_logs.json + SymbolPnlService.record_trade.
20. Bots realized PnL aggregation → PnlService.update_bots_realized_pnl sums trade logs by bot_id → writes realized/total_pnl back to bots.json.
21. Symbol PnL rebuild → `app.py` startup or `/api/symbol-pnl/rebuild` rebuilds symbol_pnl.json from trade logs for continuity.
22. Bot status enrichment → BotStatusService.get_runtime_bots merges positions, PnL%, symbol PnL, range info for `/api/bots/runtime` table.
23. Bot detail modal → `/api/bots/<id>/details` returns bot status + trade history (filtered logs) + symbol PnL metadata for modal rendering.
24. Emergency stop → `/api/emergency-stop` closes all positions (market reduce-only), cancels orders for affected symbols, marks bots stopped/cancels; returns results.
25. TP/SL actions → `/api/set-take-profit` or `/api/set-stop-loss` delegate to Bybit `set_trading_stop`; inputs from position row fields.

# Risky / Complex Areas
- `services/grid_bot_service.py` is large and stateful (auto-direction, scalp modes, dynamic ranges, order tolerance). Small changes can break order placement or risk gates.
- JSON storage concurrency: runner and API both mutate `bots.json`; no locking—race conditions possible if frequent edits.
- Bybit rate limits/HTTP failures are lightly handled; client returns success flags but services often proceed optimistically.
- Hard-coded credentials/Basic Auth in `config/config.py`; must be secured before production.
- Order sizing/minimum value logic needs care; incorrect rounding or step handling can reject orders.

# Suggested Entry Points for Future Agents
- To adjust API/UI: start with `app.py`, `templates/dashboard.html`, `static/js/app.js` (polling/actions).
- To change trading logic: read `services/grid_bot_service.py`, `services/scalp_pnl_service.py`, `services/range_engine_service.py`, `services/grid_engine_service.py`, `services/indicator_service.py`.
- To tweak risk/strategy constants: `config/strategy_config.py`, `services/risk_manager_service.py`.
- To modify persistence/reporting: `services/pnl_service.py`, `services/symbol_pnl_service.py`, `services/bot_storage_service.py`.
- When extending: keep diffs small; reuse service boundaries; consider locking or atomic writes if adding concurrent operations; validate Bybit params (tick size/qty step) before placing orders; add graceful error handling in runner to avoid bot stoppage loops.
