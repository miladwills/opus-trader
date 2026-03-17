from pathlib import Path


ROOT = Path("/var/www")


def test_session_timer_controls_render_in_main_bot_form():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert "Trading Session Timer" in template
    assert 'id="bot-session-timer-enabled"' in template
    assert 'id="bot-session-start-at"' in template
    assert 'id="bot-session-stop-at"' in template
    assert 'id="bot-session-no-new-entries-before-stop-min"' in template
    assert 'id="bot-session-end-mode"' in template
    assert 'id="bot-session-green-grace-min"' in template
    assert 'id="bot-session-force-close-max-loss-pct"' in template
    assert 'id="bot-session-cancel-pending-orders-on-end"' in template
    assert 'id="bot-session-reduce-only-on-end"' in template
    assert 'id="bot-session-runtime-summary"' in template
    assert 'id="bot-session-runtime-state"' in template
    assert 'id="bot-session-runtime-no-new"' in template
    assert 'id="bot-session-runtime-grace"' in template


def test_session_timer_frontend_payload_and_visibility_hooks_exist():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'session_timer_enabled: !!sessionTimerEnabledEl.checked,' in js_text
    assert 'session_start_at: parseOptionalDateTimeInput("bot-session-start-at", getEl),' in js_text
    assert 'session_stop_at: parseOptionalDateTimeInput("bot-session-stop-at", getEl),' in js_text
    assert 'session_end_mode: String(getEl("bot-session-end-mode")?.value || "hard_stop").trim().toLowerCase(),' in js_text
    assert 'session_cancel_pending_orders_on_end: !!getEl("bot-session-cancel-pending-orders-on-end")?.checked,' in js_text
    assert 'session_reduce_only_on_end: !!getEl("bot-session-reduce-only-on-end")?.checked,' in js_text
    assert "function updateSessionTimerVisibility(scope = \"main\") {" in js_text
    assert "function renderSessionTimerRuntimeSummary(bot = {}, scope = \"main\") {" in js_text
    assert 'sessionTimerToggle.addEventListener("change", () => updateSessionTimerVisibility());' in js_text
    assert 'renderSessionTimerRuntimeSummary(bot);' in js_text
    assert 'buildMetricChip(`Session ${humanizeReason(bot.session_timer_state || "inactive")}`' in js_text
