from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_bot_triage_panel():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="watchdog-center-hub"' in template
    assert 'id="bot-triage-panel"' in template
    assert 'id="bot-triage-last-updated"' in template
    assert 'id="bot-triage-summary-pause"' in template
    assert 'id="bot-triage-summary-reduce"' in template
    assert 'id="bot-triage-summary-review"' in template
    assert 'id="bot-triage-summary-keep"' in template
    assert 'id="bot-triage-list"' in template
    assert "Bot Triage" in template
    # verbose description removed for cleaner UI; title is sufficient


def test_dashboard_js_renders_bot_triage_panel():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "let botTriageState = {" in js
    assert "function getBotTriageVerdictMeta(verdict)" in js
    assert "function getBotTriageSeverityMeta(severity)" in js
    assert "function renderBotTriage()" in js
    assert "function applyBotTriageData(data)" in js
    assert "async function refreshBotTriage()" in js
    assert 'const data = await fetchDashboardJSON("/bot-triage");' in js
    assert 'if (payload.bot_triage) {' in js
    assert 'data-bot-triage-verdict="' in js
    assert 'data-bot-triage-severity="' in js
    assert "item.suggested_action" in js
    assert "buildBotTriageActionButtons(item)" in js
    assert 'if (verdict === "PAUSE" && runtimeStatus === "running")' in js
    assert 'else if (verdict === "REDUCE")' in js
    assert 'else if (verdict === "REVIEW")' in js
    assert "function beginBotTriageStaticAction(botId, actionType)" in js
    assert "async function beginBotTriagePreset(botId, preset)" in js
    assert "function renderBotTriageConfirmation(item)" in js
    assert "async function executeBotTriageAction(botId)" in js
    assert "function openBotTriageDiagnostics(botId, symbol)" in js
    assert "Apply Safe Preset" in js
    assert "Enable Session Timer Preset" in js
    assert "Pause + Cancel Pending" in js
    assert "Dismiss" in js
    assert "Snooze" in js
    assert 'fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/apply-preset`' in js
    assert 'fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/pause-action`' in js
    assert 'fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/dismiss`' in js
    assert 'fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/snooze`' in js
