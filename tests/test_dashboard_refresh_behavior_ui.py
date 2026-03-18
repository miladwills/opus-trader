import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _extract_function_source(js_text: str, name: str) -> str:
    marker = f"function {name}("
    start = js_text.index(marker)
    brace_start = js_text.index("{", start)
    depth = 0
    for index in range(brace_start, len(js_text)):
        char = js_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return js_text[start:index + 1]
    raise AssertionError(f"Unable to extract function {name}")


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


def test_live_feed_connection_transitions_emit_single_disconnect_and_reconnect_events():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    function_source = _extract_function_source(js_text, "setLiveFeedConnected")
    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const context = {{
          console,
          liveFeedConnected: true,
          dashboardFeedState: {{ lastFeedConnectionState: null }},
          pollingStates: [],
          connectionStates: [],
          operatorWatchUpdates: 0,
          activityEvents: [],
          configureLivePolling: (isConnected) => context.pollingStates.push(isConnected),
          setConnectionStatus: (isConnected) => context.connectionStates.push(isConnected),
          appendActivityEvent: (payload) => context.activityEvents.push(payload),
          updateOperatorWatch: () => {{ context.operatorWatchUpdates += 1; }},
        }};
        vm.createContext(context);
        vm.runInContext({json.dumps(function_source)}, context);
        context.setLiveFeedConnected(true);
        context.setLiveFeedConnected(false);
        context.setLiveFeedConnected(false);
        context.setLiveFeedConnected(true);
        process.stdout.write(JSON.stringify({{
          activityMessages: context.activityEvents.map((item) => item.message),
          pollingStates: context.pollingStates,
          connectionStates: context.connectionStates,
          operatorWatchUpdates: context.operatorWatchUpdates,
        }}));
        """
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    payload = json.loads(result.stdout)

    assert payload["activityMessages"] == [
        "Live stream disconnected, fallback polling active",
        "Live stream reconnected",
    ]
    assert payload["pollingStates"] == [True, False, False, True]
    assert payload["connectionStates"] == [True, False, False, True]
    assert payload["operatorWatchUpdates"] == 4
