from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_watchdog_center_hub_sections():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="watchdog-center-hub"' in template
    assert 'id="btn-export-ai-layer"' in template
    assert 'id="btn-export-watchdog"' in template
    assert 'id="btn-export-all-diagnostics"' in template
    assert 'id="diagnostics-export-status"' in template
    assert 'id="performance-baseline-summary"' in template
    assert 'id="btn-reset-performance-baseline"' in template
    assert 'id="watchdog-summary-active"' in template
    assert 'id="runtime-integrity-panel"' in template
    assert 'id="runtime-integrity-status"' in template
    assert 'id="runtime-integrity-source"' in template
    assert 'id="runtime-integrity-freshness"' in template
    assert 'id="runtime-integrity-startup"' in template
    assert 'id="runtime-integrity-recovery"' in template
    assert 'id="opportunity-funnel-panel"' in template
    assert 'id="opportunity-funnel-watch"' in template
    assert 'id="opportunity-funnel-armed"' in template
    assert 'id="opportunity-funnel-trigger-ready"' in template
    assert 'id="opportunity-funnel-executed"' in template
    assert 'id="opportunity-funnel-blocked"' in template
    assert 'id="opportunity-funnel-blockers"' in template
    assert 'id="opportunity-funnel-repeat-failures"' in template
    assert 'id="opportunity-funnel-structural"' in template
    assert 'id="watchdog-active-issues"' in template
    assert 'id="watchdog-cards-grid"' in template
    assert 'id="watchdog-recent-timeline"' in template
    assert 'id="watchdog-detail-panel"' in template
    assert 'id="watchdog-filter-severity"' in template
    assert 'id="btn-refresh-watchdog-hub"' in template
    assert 'id="botDetailBaselineMeta"' in template
    assert 'id="btn-reset-bot-baseline"' in template
    assert 'data-export-endpoint="/export/ai-layer"' in template
    assert 'data-export-endpoint="/export/watchdog"' in template
    assert 'data-export-endpoint="/export/all-diagnostics"' in template
    # verbose description removed for cleaner UI
    assert ">Download AI Layer JSON</button>" in template
    assert ">Download Watchdog JSON</button>" in template
    assert ">Download All Diagnostics JSON</button>" in template
    assert "Active Issues" in template
    assert "Recent Timeline" in template


def test_dashboard_js_renders_watchdog_center_hub():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "let watchdogHubState = {" in js
    assert "function initWatchdogHubControls()" in js
    assert "function applyWatchdogHubData(data)" in js
    assert "function refreshWatchdogHub()" in js
    assert "function renderRuntimeIntegrityPanel()" in js
    assert "function runtimeStartLifecycleBadge(bot)" in js
    assert "function beginGlobalPerformanceBaselineReset()" in js
    assert "function beginBotPerformanceBaselineReset(botId, symbol)" in js
    assert "function renderWatchdogBaselineSummary(meta)" in js
    assert "function formatOpportunityFunnelWindow(windowSec)" in js
    assert "function renderOpportunityFunnelChips(containerId, items, fallbackText, formatter)" in js
    assert "function renderOpportunityFunnel()" in js
    assert 'if (payload.watchdog_hub) {' in js
    assert 'const data = await fetchDashboardJSON("/watchdog-center");' in js
    assert "renderRuntimeIntegrityPanel();" in js
    assert "runtime_integrity" in js
    assert 'data-watchdog-kind="active"' in js
    assert 'data-watchdog-kind="recent"' in js
    assert 'ACTIVE NOW' in js
    assert 'RECENT / HISTORICAL' in js
    assert 'renderOpportunityFunnel();' in js
    assert '"opportunity-funnel-watch"' in js
    assert '"opportunity-funnel-blockers"' in js
    assert "function renderWatchdogExchangeTruthTag(item) {" in js
    assert "Truth Diverged" in js
    assert "Truth Stale" in js
    assert "Follow-up Pending" in js
    assert "const truthTag = renderWatchdogExchangeTruthTag(issue);" in js
    assert "const truthTag = renderWatchdogExchangeTruthTag(event);" in js
    assert "const truthTag = renderWatchdogExchangeTruthTag(selected);" in js


def test_dashboard_js_wires_diagnostics_export_buttons_with_loading_and_feedback():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'const DIAGNOSTICS_EXPORT_BUTTON_IDS = Object.freeze([' in js
    assert '"btn-export-ai-layer"' in js
    assert '"btn-export-watchdog"' in js
    assert '"btn-export-all-diagnostics"' in js
    assert 'function setDiagnosticsExportStatus(message, type = "info") {' in js
    assert 'function getDownloadFilenameFromDisposition(disposition, fallback = "opus-trader-diagnostics.json") {' in js
    assert 'function triggerBrowserDownload(blob, filename) {' in js
    assert 'async function triggerDiagnosticsExport(button) {' in js
    assert 'const response = await fetch(API_BASE + endpoint, {' in js
    assert 'const blob = await response.blob();' in js
    assert 'triggerBrowserDownload(blob, filename);' in js
    assert 'response.headers.get("Content-Disposition")' in js
    assert 'response.headers.get("X-Opus-Archive-Path")' in js
    assert 'button.disabled = Boolean(isLoading);' in js
    assert 'button.classList.toggle("opacity-60", Boolean(isLoading));' in js
    assert 'button.classList.toggle("cursor-not-allowed", Boolean(isLoading));' in js
    assert 'showToast(successMessage, "success");' in js
    assert 'showToast(errorMessage, "error");' in js
    assert 'showToast(`Baseline reset failed: ${error.message}`, "error");' in js
    assert 'error?.status === 404' in js
    assert 'export unavailable on this server' in js
    assert 'button.addEventListener("click", () => triggerDiagnosticsExport(button));' in js


def test_dashboard_js_targets_all_three_export_endpoints_without_navigation():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'type="button"' in template
    assert 'data-export-endpoint="/export/ai-layer"' in template
    assert 'data-export-endpoint="/export/watchdog"' in template
    assert 'data-export-endpoint="/export/all-diagnostics"' in template
    assert 'data-export-loading-label="Preparing AI Layer JSON..."' in template
    assert 'data-export-loading-label="Preparing Watchdog JSON..."' in template
    assert 'data-export-loading-label="Preparing All Diagnostics JSON..."' in template
    assert 'setDiagnosticsExportStatus(`${label} download in progress...`);' in js
    assert 'setDiagnosticsExportButtonLoading(button, false);' in js
