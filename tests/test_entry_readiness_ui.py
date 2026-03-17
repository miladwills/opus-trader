from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_bots_ui_renders_entry_readiness_badges():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function entryReadinessBadge(bot)" in js_text
    assert "function getSetupReadiness(bot)" in js_text
    assert "stable_readiness_stage" in js_text
    assert "raw_readiness_stage" in js_text
    assert "readiness_stability_state" in js_text
    assert "readiness_flip_suppressed" in js_text
    assert "function getExecutionViability(bot)" in js_text
    assert 'early_entry: "✅ EARLY"' in js_text
    assert 'good_continuation: "✅ GOOD CONT."' in js_text
    assert 'late_continuation: "🟠 LATE CONT."' in js_text
    assert 'position_cap_hit: "⛔ BLOCKED · Cap"' in js_text
    assert 'insufficient_margin: "⛔ BLOCKED · Margin"' in js_text
    assert 'notional_below_min: "⛔ BLOCKED · Min Notional"' in js_text
    assert 'stale_balance: "⚠️ STALE · Balance"' in js_text
    assert "execution_viability_bucket" in js_text
    assert "margin_limited" in js_text
    assert "execution_viability_stale_data" in js_text
    assert 'label: "TRIGGER READY / BLOCKED"' in js_text
    assert 'label: "SETUP READY / MARGIN WARNING"' in js_text
    assert '"✅ SETUP · Margin"' in js_text
    assert '`✅ TRIGGER / ${blockedText}`' in js_text
    assert "actionState.label" in js_text
    assert "entryReadinessBadge(bot)," in js_text
    assert "readinessFreshnessBadge(bot)" in js_text
    assert "function getReadinessFreshnessMeta(bot, override = null)" in js_text
    assert "Runtime ·" in js_text or "Fresh fallback" in js_text
    assert "ACTIONABLE NOW" in js_text
    assert 'isTriggerReadyStatus(status) && execution.blocked' in js_text
    assert 'trigger_ready: "✅ TRIGGER"' in js_text
    assert 'armed: "🟦 ARMED"' in js_text
    assert 'late: "🟠 LATE"' in js_text
    assert 'exchange_truth_stale: "Truth Stale"' in js_text
    assert 'reconciliation_diverged: "Truth Diverged"' in js_text
    assert 'exchange_state_untrusted: "Follow-up Pending"' in js_text


def test_active_bots_ui_exposes_exchange_truth_badges_and_bot_detail_section():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert "const EXCHANGE_TRUTH_EXECUTION_REASONS = new Set([" in js_text
    assert "function isExchangeTruthExecutionReason(reason) {" in js_text
    assert "function getExchangeTruthState(bot) {" in js_text
    assert "function exchangeTruthBadge(bot) {" in js_text
    assert "function renderBotDetailExchangeTruth(bot) {" in js_text
    assert "Exchange Truth Stale" in js_text
    assert "Reconciliation Diverged" in js_text
    assert "Follow-up Pending" in js_text
    assert "Execution Blocked" in js_text
    assert "exchangeTruthBadge(bot)," in js_text
    assert 'id="botDetailTruthSection"' in template_text
    assert 'id="botDetailTruthBody"' in template_text
    assert "Exchange Truth" in template_text
    assert "Loading exchange truth" in template_text


def test_ready_trade_board_shows_setup_ready_but_blocked_bucket():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function renderReadyTradeBoard(bots)" in js_text
    assert "buildReadyTradeSymbolContext(bots)" in js_text
    assert "function getReadyTradeSourceMeta(bot, symbolContext = null)" in js_text
    assert "function renderReadyTradeSourceBadge(bot, symbolContext = null)" in js_text
    assert "isActionableReadyBot(bot)" in js_text
    assert "isSetupReadyMarginLimited(bot)" in js_text
    assert "isSetupReadyButBlocked(bot)" in js_text
    assert "hasAlternativeModeReady(bot)" in js_text
    assert "Setup Ready / Margin Warning" in js_text
    assert "Armed / Near Trigger" in js_text
    assert "Late / Decayed" in js_text
    assert "Setup Ready / Opening Blocked" in js_text
    assert "Cross-Mode Preview" in js_text
    assert "Other bot" in js_text
    assert "Stopped bot" in js_text
    assert "Alternative mode ${stageText.toLowerCase()}" in js_text
    assert "No actionable directional setups right now" in js_text


def test_bot_detail_ui_renders_mode_readiness_comparison_and_runtime_labels():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="botDetailConfiguredMode"' in template_text
    assert 'id="botDetailRuntimeMode"' in template_text
    assert 'id="botDetailModePolicy"' in template_text
    assert 'id="botDetailModeMatrixSection"' in template_text
    assert 'id="botDetailModeMatrix"' in template_text
    assert "Mode Readiness Comparison" in template_text
    # verbose description removed for cleaner UI; section title is sufficient
    assert 'function renderBotDetailModeReadinessMatrix(matrix, botId = "") {' in js_text
    assert '"Current Mode"' in js_text
    assert '"If Switched"' in js_text
    assert '"Runtime View"' in js_text
    assert '"Scanner"' in js_text
    assert 'renderBotDetailModeReadinessMatrix(bot.mode_readiness_matrix, bot.id);' in js_text
    assert "Review Mode" in js_text
    assert "freshness.label" in js_text


def test_profit_protection_ui_renders_bot_detail_section_and_badges():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert "function getProfitProtectionMeta(bot) {" in js_text
    assert "function profitProtectionBadge(bot) {" in js_text
    assert "function renderBotDetailProfitProtection(bot) {" in js_text
    assert "Protect Blocked" in js_text
    assert "Take Partial" in js_text
    assert "Exit Now" in js_text
    assert "Shadow Triggered" in js_text
    assert 'id="botDetailProfitProtectionSection"' in template_text
    assert 'id="botDetailProfitProtectionBody"' in template_text
    assert "Profit Protection" in template_text
    assert "Loading profit protection" in template_text


def test_active_bots_ui_surfaces_alternative_mode_ready_summary_and_review_action():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function getAlternativeModeReadiness(bot)" in js_text
    assert "function renderAlternativeModeSummary(bot)" in js_text
    assert "function getLiveExecutionIntentMeta(bot)" in js_text
    assert "function renderLiveExecutionIntentBadge(bot)" in js_text
    assert "Cross-Mode Preview" in js_text
    assert "If switched:" in js_text
    assert "Current ${configuredMode}" in js_text
    assert 'label: `Live ${upperDirection}`' in js_text
    assert "Cross-mode readiness is advisory only until you switch modes." in js_text
    assert "reviewSuggestedMode(" in js_text


def test_emergency_ready_history_tracks_ready_entries_per_bot_not_just_symbol():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function updateEmergencyReadyHistory(readyBots, symbolContext = null)" in js_text
    assert "bot_id" in js_text
    assert "symbolContext" in js_text
    assert "Other bot" in js_text


def test_readiness_freshness_ui_handles_missing_metadata_without_breaking():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "if (!meta.label) return \"\";" in js_text
    assert "formatCompactAgeSeconds(ageSec)" in js_text


def test_bot_detail_fetch_retries_once_after_stale_404_and_refreshes_dashboard():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "async function fetchBotDetailPayload(botId) {" in js_text
    assert 'return await fetchJSON(`/bots/${encodeURIComponent(normalizedBotId)}/details`,' in js_text
    assert "await refreshBots().catch(() => null);" in js_text
    assert 'showToast("Bot detail was stale. The dashboard list was refreshed.", "warning");' in js_text
    assert "Bot no longer exists or the dashboard list was stale. The bot list was refreshed." in js_text
