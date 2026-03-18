from pathlib import Path


ROOT = Path("/var/www")


def test_dashboard_workspace_grid_is_orchestrated_around_operations():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    css = (ROOT / "static" / "css" / "dashboard.css").read_text()

    assert "dashboard-workspace-grid" in template
    # grid-template-areas now lives in the separate CSS file, not inline in HTML
    assert "grid-template-areas:" in css
    assert '"bots"' in css
    assert '"sidebar"' in css
    assert '"workbench"' in css
    assert "workspace-slot workspace-slot--bots" in template
    assert "workspace-slot workspace-slot--sidebar workspace-sidebar" in template
    assert "workspace-slot workspace-slot--workbench" in template


def test_active_bots_uses_glanceable_operations_list_not_table():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'id="active-bots-list"' in template
    assert 'id="active-bots-total"' in template
    assert 'id="active-bots-running"' in template
    assert 'id="active-bots-ready"' in template
    assert 'id="active-bots-watch"' in template
    assert 'id="active-bots-blocked"' in template
    assert 'id="active-bots-limited"' in template
    assert 'id="active-bots-stale-indicator"' in template
    assert 'id="active-bots-table"' not in template
    assert 'id="mobile-bots-list"' not in template
    assert 'const container = $("active-bots-list");' in js
    assert 'class="bot-ops-row' in js
    # bot-ops-row__primary and bot-ops-row__summary are rendered in JS template literals, not in HTML
    assert "bot-ops-row__primary" in js
    assert "bot-ops-row__summary" in js
    assert 'class="bot-ops-row__meta-strip"' in js
    # bot-ops-alert is rendered in JS, not in HTML template
    assert "bot-ops-alert" in js
    assert 'const topAlert = getPrimaryBotAlert(bot);' in js


def test_open_positions_use_compact_board_not_table_shell():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'id="positions-board"' in template
    assert 'id="open-positions-table"' not in template
    assert 'id="positions-cards"' not in template
    assert 'const container = $("positions-board");' in js
    assert 'class="position-row-card"' in js
    assert 'positions-board--single' in js


def test_scanner_uses_result_rows_not_scroll_table():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'id="scanner-body"' in template
    assert "scanner-results-board" in template
    assert 'id="scanner-table"' not in template
    assert "scanner-empty-state" in template
    assert 'class="scanner-result-row"' in js
    assert "scanner-result-row__grid" in js
    assert "scanner-empty-state" in js


def test_predictions_realized_and_workbench_panels_remain_paired():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    # workspace-predictions-panel was renamed to workspace-slot--predictions during refactoring
    assert "workspace-slot--predictions" in template
    assert "workspace-slot--scalp" in template
    assert "predictions-card-grid" in template
    # predictions-card-grid--compact is toggled in JS, not present in HTML
    assert "predictions-card-grid--compact" in js
    assert "scalp-safety-panel" in template
    assert "lower-workbench-grid" in template
    assert "config-workbench" in template
    # scanner-workbench was replaced by workspace-slot--scanner during refactoring
    assert "workspace-slot--scanner" in template
    assert 'gridEl.classList.toggle("predictions-card-grid--compact", predictions.length <= 2)' in js


def test_ready_counts_and_bot_actions_remain_wired():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    # Ready To Trade table removed; counts still tracked in JS for emergency card
    assert "emergency-ready-list" in template
    assert "buildBotActionButtons(bot, false)" in js
    assert "watchCount" in js
    assert "blockedCount" in js
    assert "limitedCount" in js


def test_active_bots_score_kpi_surfaces_unavailable_readiness_states():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'if (reason === "preview_disabled") return "Off";' in js
    assert 'if (reason === "preview_limited") return "Lim";' in js
    assert 'if (reason.includes("stale")) return "Stale";' in js
    assert 'if (reason === "preview_disabled") return "Preview";' in js
    assert 'if (reason === "preview_limited") return "Limited";' in js
    assert 'if (reason.includes("stale")) return "Snapshot";' in js


def test_stopped_preview_score_shows_preview_band_not_live_band():
    """Stopped-preview bots with valid scores show 'Preview' band, not Strong/Good/etc."""
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    # _bandDisplay checks readiness_source_kind for stopped preview distinction
    assert 'sourceKind.startsWith("stopped_preview")' in js
    assert 'sourceKind === "stopped_preview_stale"' in js
    # Fresh/deferred stopped previews show "Preview" as band
    assert 'return "Preview";' in js
    # Stale stopped previews show "Stale" as band
    assert 'return "Stale";' in js


def test_stopped_preview_pending_shows_pending_not_off():
    """Unavailable stopped previews show PENDING, not PREVIEW OFF."""
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    # _scoreDisplay returns "..." for unavailable/placeholder sources
    assert 'sourceKind === "stopped_preview_unavailable"' in js
    assert 'sourceKind === "stopped_placeholder"' in js
    assert 'return "...";' in js
    # _bandDisplay returns "Pending" for unavailable sources
    assert 'return "Pending";' in js
    # shortLabels includes preview_pending
    assert 'preview_pending: "⏳ PENDING"' in js
    # entryReadinessBadge overrides preview_disabled label for pending sources
    assert 'label = shortLabels.preview_pending' in js


def test_stopped_preview_freshness_meta_handles_deferred_source():
    """getReadinessFreshnessMeta handles stopped_preview_deferred source kind."""
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'sourceKind === "stopped_preview_deferred"' in js
    # Deferred and unavailable show distinct freshness labels
    assert '"Preview Pending"' in js


def test_running_bot_score_display_unaffected():
    """Running bots still show numeric score with Strong/Good/Caution/Poor band."""
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    # Band thresholds for live scores remain
    assert 'if (score >= 72) return "Strong";' in js
    assert 'if (score >= 60) return "Good";' in js
    assert 'if (score >= 50) return "Caution";' in js
    assert 'return "Poor";' in js


def test_active_bots_toolbar_and_bot_forms_expose_clear_and_save_start_controls():
    template = (ROOT / "templates" / "dashboard.html").read_text()
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    active_bots_toolbar = template.split('id="active-bots-search"', 1)[1].split('id="active-bots-list"', 1)[0]

    assert "clearActiveBotSearch()" in active_bots_toolbar
    assert "↻ Refresh" not in active_bots_toolbar
    assert 'id="btn-save-start-bot"' in template
    assert 'id="quick-edit-save-start-btn"' in template
    assert "Save &amp; Start" in template
    assert "function clearActiveBotSearch() {" in js
    assert "function focusActiveBotsWorkingNow() {" in js
    assert '$("btn-save-start-bot").addEventListener("click", saveBotAndStart);' in js
    assert "function saveQuickEditAndStart() {" in js
