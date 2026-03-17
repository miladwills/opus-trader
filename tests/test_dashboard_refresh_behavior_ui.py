from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quick_refresh_does_not_poll_bots_runtime_every_cycle():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    quick_refresh_section = js_text.split("async function refreshPnlQuick() {", 1)[1].split("function applySummaryData", 1)[0]

    assert "async function refreshPnlQuick() {" in js_text
    assert "await refreshPnlCritical();" in quick_refresh_section
    assert "refreshBots()" not in quick_refresh_section
    assert "refreshSummary()" not in quick_refresh_section


def test_refresh_bots_is_single_flight():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "let refreshBotsPromise = null;" in js_text
    assert "if (refreshBotsPromise && !window._forceNextBotsApply) return refreshBotsPromise;" in js_text
    assert 'const data = await fetchDashboardJSON("/bots/runtime");' in js_text


def test_start_action_focuses_working_now_filter_and_refreshes_runtime_panels():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    action_section = js_text.split("async function botAction(", 1)[1].split("async function removeAllBots", 1)[0]

    assert 'if (action === "start") {' in action_section
    assert "focusActiveBotsWorkingNow();" in action_section
    # Refresh logic was restructured: positions + summary are pushed conditionally
    assert "tasks.push(refreshPositions(), refreshSummary());" in action_section
