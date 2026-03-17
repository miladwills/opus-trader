from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_bot_config_advisor_panel():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="bot-config-advisor-panel"' in template
    assert 'id="bot-config-advisor-last-updated"' in template
    assert 'id="bot-config-advisor-summary-reduce"' in template
    assert 'id="bot-config-advisor-summary-widen"' in template
    assert 'id="bot-config-advisor-summary-review"' in template
    assert 'id="bot-config-advisor-summary-keep"' in template
    assert 'id="bot-config-advisor-list"' in template
    assert "Bot Config Advisor" in template
    # verbose description removed for cleaner UI; title is sufficient


def test_dashboard_js_renders_bot_config_advisor_panel():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "let botConfigAdvisorState = {" in js
    assert "function getBotConfigAdvisorVerdictMeta(verdict)" in js
    assert "function getBotConfigAdvisorConfidenceMeta(confidence)" in js
    assert "function getBotConfigAdvisorQueueMeta(state)" in js
    assert "function getBotConfigAdvisorDiffRows(item)" in js
    assert "async function beginBotConfigAdvisorApply(botId)" in js
    assert "function cancelBotConfigAdvisorApply()" in js
    assert "function renderBotConfigAdvisorConfirmation(item)" in js
    assert "async function executeBotConfigAdvisorApply(botId)" in js
    assert "async function cancelBotConfigAdvisorQueue(botId)" in js
    assert "function renderBotConfigAdvisor()" in js
    assert "function applyBotConfigAdvisorData(data)" in js
    assert "async function refreshBotConfigAdvisor()" in js
    assert 'const data = await fetchDashboardJSON("/bot-config-advisor");' in js
    assert "if (payload.bot_config_advisor) {" in js
    assert 'data-bot-config-advisor-verdict="' in js
    assert 'data-bot-config-advisor-confidence="' in js
    assert 'data-bot-config-advisor-queue-state="' in js
    assert "const current = item?.current_settings || {};" in js
    assert "const recommended = item?.recommended_settings || {};" in js
    assert "Apply Recommended Tune" in js
    assert "Queue Until Flat" in js
    assert "Cancel Queued Apply" in js
    assert "Queued until flat." in js
    assert "Apply blocked by config drift or conflict." in js
    assert "Advisory only, not auto-applied:" in js
    assert "Bot must be flat before applying recommended tune." in js
    assert 'fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/apply`' in js
    assert 'fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/queue-apply`' in js
    assert 'fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/cancel-queued-apply`' in js
    assert "item?.supports_apply" in js
    assert "item?.can_queue_until_flat" in js
    assert "queuedApply ? `<button type=\"button\" onclick='cancelBotConfigAdvisorQueue(" in js
    assert 'Preset:' in js
    assert '->' in js
