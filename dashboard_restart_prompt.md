# IMPLEMENT: Dashboard "Restart Services" Button

## YOUR TASK

Add a **"Restart Services"** button to the Opus Trader 2026 dashboard that lets the user restart the runner process with one click — no SSH required.

**RULES:**
- Follow existing code patterns (Flask + jQuery, `@require_basic_auth`, `jsonify`)
- The button must have a **confirmation dialog** — accidental restart could interrupt active trades
- The button should show a **spinner/status** during restart and auto-recover
- Do NOT restart [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py) itself — only restart [runner.py](file:///c:/laragon/www/opus%20trader%202026/runner.py) (app.py is serving the dashboard)
- Must work on both Linux (VPS) and Windows (local dev)

---

## PROJECT CONTEXT

### Files to Modify
```
c:\laragon\www\opus trader 2026\
├── app.py                          # Flask backend — ADD 3 new endpoints
└── templates/dashboard.html        # Dashboard UI — ADD restart button + modal
```

### Existing Infrastructure (already in [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py), DO NOT recreate)

The following functions already exist at module level. **Use them, do not duplicate:**

```python
# Line ~109: Stop flag path
RUNNER_STOP_FLAG = os.path.join("storage", "runner.stop")

# Line ~538: Get runner process info (returns {"active": bool, "pid": int|None, "source": str})
def _runner_process_info() -> dict:

# Line ~476: Check if runner lock file is held
def _runner_lock_held() -> bool:

# Line ~582: Spawn a new runner process (returns {"pid": int})
def _spawn_runner_process() -> dict:

# Line ~616: Ensure runner is active, spawn if needed (returns status dict)
def _ensure_runner_active(reason: str, force: bool = False) -> dict:
```

### [os](file:///c:/laragon/www/opus%20trader%202026/services/bybit_client.py#1520-1526) and [signal](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py#11731-11810) modules are already imported. [time](file:///c:/laragon/www/opus%20trader%202026/services/bybit_client.py#735-742) and `subprocess` are also available.

---

## BACKEND: Add 3 Endpoints to [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py)

Add these near the other API endpoints (after the existing route definitions, around line 800+).

### Endpoint 1: `POST /api/services/restart`

```python
@app.route("/api/services/restart", methods=["POST"])
@require_basic_auth
def api_restart_services():
    """Restart the runner process from the dashboard."""
    try:
        # 1. Signal the runner to stop gracefully
        with open(RUNNER_STOP_FLAG, "w", encoding="utf-8") as f:
            f.write("dashboard_restart")
        
        # 2. Wait for graceful shutdown
        time.sleep(2)
        
        # 3. Force kill if still alive
        runner_info = _runner_process_info()
        if runner_info.get("active") and runner_info.get("pid"):
            pid = runner_info["pid"]
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=5, check=False)
                else:
                    import signal as sig
                    os.kill(pid, sig.SIGTERM)
                    time.sleep(1)
                    # SIGKILL if still alive
                    try:
                        os.kill(pid, sig.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already dead
            except Exception as e:
                logging.warning("Force kill runner PID %d failed: %s", pid, e)
        
        # 4. Remove stop flag and spawn fresh runner
        if os.path.exists(RUNNER_STOP_FLAG):
            try:
                os.remove(RUNNER_STOP_FLAG)
            except Exception:
                pass
        
        result = _spawn_runner_process()
        logging.info("🔄 Services restarted from dashboard (new PID: %s)", result.get("pid"))
        
        return jsonify({
            "success": True,
            "message": "Runner restarted",
            "new_pid": result.get("pid"),
        })
    except Exception as e:
        logging.error("Service restart failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
```

### Endpoint 2: `GET /api/services/status`

```python
@app.route("/api/services/status")
@require_basic_auth
def api_services_status():
    """Get current service status for the dashboard."""
    runner_info = _runner_process_info()
    return jsonify({
        "runner_active": runner_info.get("active", False),
        "runner_pid": runner_info.get("pid"),
        "detected_via": runner_info.get("source", "unknown"),
        "stop_flag_exists": os.path.exists(RUNNER_STOP_FLAG),
    })
```

### Endpoint 3: `POST /api/services/stop`

```python
@app.route("/api/services/stop", methods=["POST"])
@require_basic_auth
def api_stop_services():
    """Stop the runner process without restarting."""
    try:
        with open(RUNNER_STOP_FLAG, "w", encoding="utf-8") as f:
            f.write("dashboard_stop")
        
        runner_info = _runner_process_info()
        if runner_info.get("active") and runner_info.get("pid"):
            pid = runner_info["pid"]
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=5, check=False)
                else:
                    import signal as sig
                    os.kill(pid, sig.SIGTERM)
            except Exception as e:
                logging.warning("Stop runner PID %d failed: %s", pid, e)
        
        logging.info("⏹️ Runner stopped from dashboard")
        return jsonify({"success": True, "message": "Runner stopped"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

---

## FRONTEND: Add Button + Modal to [dashboard.html](file:///c:/laragon/www/opus%20trader%202026/dashboard.html)

### Button Location

Find the dashboard header or top navigation area. Add a **service controls section** — a small button group near the top of the page, visible but not intrusive. If there's an existing status bar or header, add it there.

If you can't find a clear location, add it as a **floating control panel** in the top-right corner:

```html
<!-- Service Controls - Fixed position top-right -->
<div id="service-controls" style="
    position: fixed;
    top: 12px;
    right: 20px;
    z-index: 1000;
    display: flex;
    gap: 8px;
    align-items: center;
">
    <span id="runner-status-dot" style="
        width: 10px; height: 10px; border-radius: 50%;
        background: #10b981;
        display: inline-block;
        box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
    " title="Runner: Active"></span>
    <span id="runner-status-text" style="
        color: #94a3b8; font-size: 12px; font-family: monospace;
    ">Runner: Active</span>
    <button id="btn-restart-services" onclick="confirmRestartServices()" style="
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #fff;
        border: none;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
    " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
        🔄 Restart
    </button>
    <button id="btn-stop-services" onclick="confirmStopServices()" style="
        background: linear-gradient(135deg, #ef4444, #dc2626);
        color: #fff;
        border: none;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
    " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
        ⏹️ Stop
    </button>
</div>
```

### JavaScript (add at bottom of the file, inside existing `<script>` block)

```javascript
// ============================================================
// Service Controls
// ============================================================

function confirmRestartServices() {
    if (!confirm('⚠️ Restart Runner?\n\nThis will stop all active bot cycles, then restart the runner process.\nActive positions will NOT be closed.\n\nContinue?')) return;
    
    const btn = document.getElementById('btn-restart-services');
    btn.disabled = true;
    btn.innerHTML = '⏳ Restarting...';
    btn.style.opacity = '0.6';
    
    fetch('/api/services/restart', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                btn.innerHTML = '✅ Restarted!';
                btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
                setTimeout(() => {
                    btn.innerHTML = '🔄 Restart';
                    btn.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
                    btn.disabled = false;
                    btn.style.opacity = '1';
                    pollRunnerStatus();
                }, 3000);
            } else {
                alert('Restart failed: ' + (data.error || 'Unknown error'));
                btn.innerHTML = '🔄 Restart';
                btn.disabled = false;
                btn.style.opacity = '1';
            }
        })
        .catch(err => {
            alert('Restart request failed: ' + err);
            btn.innerHTML = '🔄 Restart';
            btn.disabled = false;
            btn.style.opacity = '1';
        });
}

function confirmStopServices() {
    if (!confirm('🛑 Stop Runner?\n\nThis will stop the runner. Bots will NOT process cycles.\nActive positions remain open but unmanaged.\n\nContinue?')) return;
    
    const btn = document.getElementById('btn-stop-services');
    btn.disabled = true;
    btn.innerHTML = '⏳ Stopping...';
    
    fetch('/api/services/stop', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                btn.innerHTML = '✅ Stopped';
                setTimeout(() => {
                    btn.innerHTML = '⏹️ Stop';
                    btn.disabled = false;
                    pollRunnerStatus();
                }, 2000);
            } else {
                alert('Stop failed: ' + (data.error || 'Unknown error'));
                btn.innerHTML = '⏹️ Stop';
                btn.disabled = false;
            }
        })
        .catch(err => {
            alert('Stop request failed: ' + err);
            btn.innerHTML = '⏹️ Stop';
            btn.disabled = false;
        });
}

function pollRunnerStatus() {
    fetch('/api/services/status')
        .then(r => r.json())
        .then(data => {
            const dot = document.getElementById('runner-status-dot');
            const text = document.getElementById('runner-status-text');
            if (data.runner_active) {
                dot.style.background = '#10b981';
                dot.style.boxShadow = '0 0 6px rgba(16, 185, 129, 0.5)';
                dot.title = 'Runner: Active (PID ' + data.runner_pid + ')';
                text.textContent = 'Runner: Active';
                text.style.color = '#10b981';
            } else {
                dot.style.background = '#ef4444';
                dot.style.boxShadow = '0 0 6px rgba(239, 68, 68, 0.5)';
                dot.title = 'Runner: Stopped';
                text.textContent = 'Runner: Stopped';
                text.style.color = '#ef4444';
            }
        })
        .catch(() => {});
}

// Poll runner status every 10 seconds
setInterval(pollRunnerStatus, 10000);
pollRunnerStatus();  // Initial check
```

---

## IMPORTANT NOTES

1. **The watchdog thread** in [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py) ([_watch_runner_forever](file:///c:/laragon/www/opus%20trader%202026/app.py#666-673) / [_start_runner_watchdog](file:///c:/laragon/www/opus%20trader%202026/app.py#675-687)) may auto-restart the runner after you stop it. The `RUNNER_STOP_FLAG` file prevents this — the watchdog checks for it. So the stop endpoint MUST leave the flag file in place.
2. **The restart endpoint** MUST remove the flag file before spawning, otherwise the watchdog won't allow the new runner to stay alive.
3. **[signal](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py#11731-11810) module**: On Linux the VPS uses `SIGTERM`/`SIGKILL`. On Windows use `taskkill`. The existing [_spawn_runner_process()](file:///c:/laragon/www/opus%20trader%202026/app.py#582-617) already handles both platforms.
4. **No app restart**: Restarting [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py) from within itself would kill the HTTP response. Only restart [runner.py](file:///c:/laragon/www/opus%20trader%202026/runner.py).

---

## VERIFICATION

1. Run `python -m py_compile app.py` — no syntax errors
2. Start the app locally: `python app.py`
3. Open dashboard, verify the controls appear in the top-right
4. Click "Restart" → confirm dialog → button shows spinner → "Restarted!" → status dot stays green
5. Click "Stop" → confirm → status dot turns red → runner is not running
6. Click "Restart" again → runner comes back → dot turns green
7. Verify runner logs: `tail -f storage/runner.log` should show fresh startup after restart

## DELIVERABLES

1. Modified [app.py](file:///c:/laragon/www/opus%20trader%202026/app.py) — 3 new endpoints (~60 lines)
2. Modified [templates/dashboard.html](file:///c:/laragon/www/opus%20trader%202026/templates/dashboard.html) — Button controls + JS (~100 lines)
