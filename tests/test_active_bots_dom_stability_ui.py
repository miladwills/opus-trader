import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "js" / "app_lf.js"
DASHBOARD_HTML = ROOT / "templates" / "dashboard.html"


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


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _run_apply_bots_data_scenario(scenario_js: str, *, same_structure: bool) -> dict:
    js_text = APP_JS.read_text()
    apply_source = _extract_function_source(js_text, "applyBotsData")
    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const applySource = {json.dumps(apply_source)};

        function makeElement() {{
          return {{
            textContent: "",
            innerHTML: "",
            title: "",
            disabled: false,
            hidden: false,
            style: {{}},
            classList: {{
              toggled: [],
              added: [],
              removed: [],
              toggle(name, value) {{ this.toggled.push([name, Boolean(value)]); }},
              add(name) {{ this.added.push(name); }},
              remove(name) {{ this.removed.push(name); }},
            }},
          }};
        }}

        const elementIds = [
          "active-bots-total",
          "active-bots-running",
          "active-bots-paused",
          "active-bots-ready",
          "active-bots-watch",
          "active-bots-blocked",
          "active-bots-armed",
          "active-bots-limited",
          "active-bots-recent-stopped",
          "emergency-stop-section",
          "emergency-stop-card",
          "btn-emergency-stop",
        ];
        const elements = Object.fromEntries(elementIds.map((id) => [id, makeElement()]));

        const context = {{
          console,
          window: {{ _lastSummaryData: {{ positions_summary: {{}} }} }},
          appliedBotsStateSeq: 0,
          previousValues: {{ botPnls: {{}} }},
          pendingBotActions: {{}},
          liveOpenExposureRecommendation: null,
          activeBotFilter: "watch",
          _isRecentlyStopped: () => false,
          isArmedStatus: () => false,
          isLateStatus: () => false,
          isTriggerReadyStatus: () => false,
          getSetupReadiness: () => ({{ status: "watch", score: null }}),
          $: (id) => elements[id] || null,
          sortBotsForDisplay: (bots) => bots,
          pruneActiveBotFrontendState: (bots) => {{
            context.prunedIds = bots.map((bot) => bot.id);
          }},
          getEffectiveActiveBotReadyCategory: (bot) => `cat:${{String(bot.analysis_ready_status || bot.entry_ready_status || "").trim().toLowerCase()}}`,
          trackActiveBotCategoryTransitions: (bots) => {{
            context.trackedCategoryBots = bots.map((bot) => bot.id);
          }},
          detectBotRuntimeEvents: () => {{
            context.detected = true;
          }},
          renderReadyTradeBoard: (bots) => {{
            context.readyBoardBots = bots.map((bot) => ({{
              id: bot.id,
              analysis_ready_status: bot.analysis_ready_status,
              analysis_ready_reason: bot.analysis_ready_reason,
              runtime_snapshot_stale: Boolean(bot.runtime_snapshot_stale),
              active_ready_cat: bot._active_bots_ready_cat,
            }}));
          }},
          updateOpenExposureMeta: () => {{}},
          renderEmergencyRestartPanel: () => {{}},
          updateRunningBotsStatus: (bots) => {{
            context.runningStatusBots = bots.map((bot) => bot.id);
          }},
          updateOperatorWatch: () => {{
            context.operatorWatchUpdated = true;
          }},
          hasSameActiveBotStructure: () => {str(same_structure).lower()},
          patchActiveBotRowsInPlace: (bots) => {{
            context.patchCalls = (context.patchCalls || 0) + 1;
            context.patchedBots = bots.map((bot) => ({{
              id: bot.id,
              analysis_ready_status: bot.analysis_ready_status,
              analysis_ready_reason: bot.analysis_ready_reason,
              runtime_snapshot_stale: Boolean(bot.runtime_snapshot_stale),
              active_ready_cat: bot._active_bots_ready_cat,
            }}));
            return true;
          }},
          renderMobileBotsData: (bots) => {{
            context.renderCalls = (context.renderCalls || 0) + 1;
            context.renderedBots = bots.map((bot) => ({{
              id: bot.id,
              analysis_ready_status: bot.analysis_ready_status,
              analysis_ready_reason: bot.analysis_ready_reason,
              runtime_snapshot_stale: Boolean(bot.runtime_snapshot_stale),
              active_ready_cat: bot._active_bots_ready_cat,
            }}));
          }},
          setActiveBotsGlobalStaleState: (...args) => {{
            context.globalStaleArgs = args;
          }},
          Date: {{ now: () => 12345 }},
          parseFloat,
          Number,
          String,
          Boolean,
          Object,
          Array,
          Set,
          Map,
        }};

        vm.createContext(context);
        vm.runInContext(applySource, context);
        {scenario_js}
        """
    )
    return _run_node(node_script)


def test_patch_bot_row_fields_updates_only_fields_and_preserves_action_node():
    js_text = APP_JS.read_text()
    function_names = [
        "setElementHtmlIfChanged",
        "setElementTextIfChanged",
        "setElementClassNameIfChanged",
        "setElementHiddenState",
        "setElementAttributeIfChanged",
        "setElementDisplayIfChanged",
        "getActiveBotRowField",
        "patchBotRowFields",
    ]
    function_sources = [_extract_function_source(js_text, name) for name in function_names]

    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const functionSources = {json.dumps(function_sources)};

        function makeField(overrides = {{}}) {{
          const attrs = {{ ...(overrides.attrs || {{}}) }};
          return {{
            innerHTML: overrides.innerHTML || "",
            textContent: overrides.textContent || "",
            className: overrides.className || "",
            hidden: Boolean(overrides.hidden),
            title: overrides.title || "",
            style: {{ display: overrides.display || "" }},
            attrs,
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : "";
            }},
            setAttribute(name, value) {{
              this.attrs[name] = String(value);
            }},
          }};
        }}

        const fields = {{
          "symbol-button": makeField({{ textContent: "BTCUSDT", title: "BTCUSDT", attrs: {{ onclick: "old()" }} }}),
          "symbol-scan": makeField(),
          "auto-pilot-status": makeField(),
          "profile-badge": makeField({{ innerHTML: "old-profile" }}),
          "badges": makeField({{ innerHTML: "<span>old badge</span>" }}),
          "meta-strip": makeField({{ innerHTML: "<span>old meta</span>" }}),
          "metrics": makeField({{ innerHTML: "<div>old metrics</div>" }}),
          "actions": makeField({{ innerHTML: "<button>Keep</button>" }}),
          "alert": makeField({{ className: "bot-ops-alert", textContent: "old alert", hidden: false }}),
          "footer": makeField({{ innerHTML: "<div>old footer</div>", hidden: false }}),
        }};
        const actionListener = {{ preserved: true }};
        fields.actions.listenerToken = actionListener;

        const currentRow = {{
          className: "old-row",
          style: {{ display: "none" }},
          dataset: {{
            symbol: "BTCUSDT",
            autoPilot: "false",
            status: "paused",
            readyCat: "blocked",
          }},
          querySelector(selector) {{
            const match = selector.match(/\\[data-bot-field="([^"]+)"\\]/);
            return match ? fields[match[1]] : null;
          }},
        }};

        const context = {{
          console,
          getActiveBotRowViewModel: () => ({{
            rowClass: "bot-ops-row",
            rowDisplay: "",
            rowDataset: {{
              symbol: "BTCUSDT",
              autoPilot: "false",
              status: "running",
              readyCat: "watch",
            }},
            symbolText: "BTCUSDT",
            symbolTitle: "BTCUSDT",
            symbolOnclick: "openBotDetailModal('bot-1')",
            symbolScanHtml: "",
            autoPilotBadgeHtml: "",
            profileHtml: "new-profile",
            badgesHtml: "<span>new badge</span>",
            metaStripHtml: "<span>new meta</span>",
            metricsHtml: "<div>new metrics</div>",
            actionsHtml: "<button>Keep</button>",
            hasAlert: false,
            alertClass: "bot-ops-alert",
            alertText: "",
            hasFooter: false,
            footerHtml: "",
          }}),
        }};

        vm.createContext(context);
        for (const source of functionSources) {{
          vm.runInContext(source, context);
        }}

        const actionsFieldBefore = fields.actions;
        context.patchBotRowFields(currentRow, {{ id: "bot-1" }});

        process.stdout.write(JSON.stringify({{
          rowClass: currentRow.className,
          rowDisplay: currentRow.style.display,
          datasetStatus: currentRow.dataset.status,
          datasetReadyCat: currentRow.dataset.readyCat,
          symbolOnclick: fields["symbol-button"].getAttribute("onclick"),
          badgesHtml: fields.badges.innerHTML,
          metricsHtml: fields.metrics.innerHTML,
          actionsSameObject: fields.actions === actionsFieldBefore,
          actionListenerPreserved: fields.actions.listenerToken === actionListener,
          actionInnerHtml: fields.actions.innerHTML,
          alertHidden: fields.alert.hidden,
          footerHidden: fields.footer.hidden,
        }}));
        """
    )
    result = _run_node(node_script)

    assert result == {
        "rowClass": "bot-ops-row",
        "rowDisplay": "",
        "datasetStatus": "running",
        "datasetReadyCat": "watch",
        "symbolOnclick": "openBotDetailModal('bot-1')",
        "badgesHtml": "<span>new badge</span>",
        "metricsHtml": "<div>new metrics</div>",
        "actionsSameObject": True,
        "actionListenerPreserved": True,
        "actionInnerHtml": "<button>Keep</button>",
        "alertHidden": True,
        "footerHidden": True,
    }


def test_patch_active_bot_rows_in_place_keeps_existing_row_nodes():
    js_text = APP_JS.read_text()
    patch_source = _extract_function_source(js_text, "patchActiveBotRowsInPlace")
    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const patchSource = {json.dumps(patch_source)};

        const currentRow = {{
          id: "bot-row-bot-1",
          replaceWith() {{
            throw new Error("replaceWith should not be called");
          }},
        }};

        const context = {{
          console,
          $: () => ({{}}),
          document: {{
            getElementById(id) {{
              return id === "bot-row-bot-1" ? currentRow : null;
            }},
          }},
          hasSameActiveBotStructure: () => true,
          rememberActiveBotStructure: (bots) => {{
            context.rememberedIds = bots.map((bot) => bot.id);
          }},
          patchBotRowFields: (row, bot) => {{
            context.patchCalls = (context.patchCalls || 0) + 1;
            context.sameRowObject = row === currentRow;
            context.lastBotId = bot.id;
            return true;
          }},
        }};

        vm.createContext(context);
        vm.runInContext(patchSource, context);
        const result = context.patchActiveBotRowsInPlace([{{ id: "bot-1" }}]);

        process.stdout.write(JSON.stringify({{
          result,
          patchCalls: context.patchCalls,
          sameRowObject: context.sameRowObject,
          lastBotId: context.lastBotId,
          rememberedIds: context.rememberedIds,
        }}));
        """
    )
    result = _run_node(node_script)

    assert result == {
        "result": True,
        "patchCalls": 1,
        "sameRowObject": True,
        "lastBotId": "bot-1",
        "rememberedIds": ["bot-1"],
    }


def test_apply_bots_data_keeps_filter_stable_when_structure_is_unchanged():
    result = _run_apply_bots_data_scenario(
        """
        context.applyBotsData({
          stale_data: false,
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "running",
            analysis_ready_status: "watch",
            analysis_ready_reason: "watch_setup",
          }],
        });

        process.stdout.write(JSON.stringify({
          patchCalls: context.patchCalls || 0,
          renderCalls: context.renderCalls || 0,
          activeBotFilter: context.activeBotFilter,
          patchedBots: context.patchedBots,
          globalStaleArgs: context.globalStaleArgs || null,
        }));
        """,
        same_structure=True,
    )

    assert result == {
        "patchCalls": 1,
        "renderCalls": 0,
        "activeBotFilter": "watch",
        "patchedBots": [
            {
                "id": "bot-1",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "watch_setup",
                "runtime_snapshot_stale": False,
                "active_ready_cat": "cat:watch",
            }
        ],
        "globalStaleArgs": [False, ""],
    }


def test_apply_bots_data_uses_global_stale_indicator_without_mass_ready_category_rewrite():
    result = _run_apply_bots_data_scenario(
        """
        context.applyBotsData({
          stale_data: true,
          error: "snapshot delayed",
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "running",
            analysis_ready_status: "ready",
            analysis_ready_reason: "watch_setup",
          }],
        });

        process.stdout.write(JSON.stringify({
          globalStaleArgs: context.globalStaleArgs,
          patchedBots: context.patchedBots,
          readyBoardBots: context.readyBoardBots,
        }));
        """,
        same_structure=True,
    )

    expected_bot = {
        "id": "bot-1",
        "analysis_ready_status": "ready",
        "analysis_ready_reason": "watch_setup",
        "runtime_snapshot_stale": True,
        "active_ready_cat": "cat:ready",
    }
    assert result == {
        "globalStaleArgs": [True, "snapshot delayed"],
        "patchedBots": [expected_bot],
        "readyBoardBots": [expected_bot],
    }


def test_apply_bots_data_preserves_last_good_state_when_stale_payload_loses_runtime_truth():
    result = _run_apply_bots_data_scenario(
        """
        context.applyBotsData({
          stale_data: false,
          _request_seq: 2,
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "stopped",
            setup_ready_status: "ready",
            analysis_ready_status: "ready",
            analysis_ready_reason: "early_entry",
          }],
        });

        context.applyBotsData({
          stale_data: true,
          error: "bots_runtime_timeout",
          _request_seq: 3,
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "stopped",
          }],
        });

        process.stdout.write(JSON.stringify({
          globalStaleArgs: context.globalStaleArgs,
          renderCalls: context.renderCalls || 0,
          patchCalls: context.patchCalls || 0,
          readyBoardBots: context.readyBoardBots,
          renderedBots: context.renderedBots || null,
          lastBots: context.window._lastBots,
          lastMeta: context.window._lastBotsStateMeta,
        }));
        """,
        same_structure=True,
    )

    assert result["globalStaleArgs"] == [True, "bots_runtime_timeout"]
    assert result["patchCalls"] == 1
    assert result["renderCalls"] == 0
    assert result["readyBoardBots"] == [
        {
            "id": "bot-1",
            "analysis_ready_status": "ready",
            "analysis_ready_reason": "early_entry",
            "runtime_snapshot_stale": False,
            "active_ready_cat": "cat:ready",
        }
    ]
    assert result["lastBots"] == [
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "stopped",
            "setup_ready_status": "ready",
            "analysis_ready_status": "ready",
            "analysis_ready_reason": "early_entry",
            "_active_bots_ready_cat": "cat:ready",
        }
    ]
    assert result["lastMeta"]["stale_overlay_active"] is True
    assert result["lastMeta"]["dropped_reason"] == "stale_overlay_preserved"


def test_apply_bots_data_ignores_older_response_that_returns_after_newer_state():
    result = _run_apply_bots_data_scenario(
        """
        context.applyBotsData({
          stale_data: false,
          _request_seq: 4,
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "stopped",
            analysis_ready_status: "ready",
            analysis_ready_reason: "early_entry",
          }],
        });

        context.applyBotsData({
          stale_data: false,
          _request_seq: 3,
          bots: [{
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "stopped",
            analysis_ready_status: "watch",
            analysis_ready_reason: "watch_setup",
          }],
        });

        process.stdout.write(JSON.stringify({
          patchCalls: context.patchCalls || 0,
          readyBoardBots: context.readyBoardBots,
          lastBots: context.window._lastBots,
          lastMeta: context.window._lastBotsStateMeta,
        }));
        """,
        same_structure=True,
    )

    assert result["patchCalls"] == 1
    assert result["readyBoardBots"] == [
        {
            "id": "bot-1",
            "analysis_ready_status": "ready",
            "analysis_ready_reason": "early_entry",
            "runtime_snapshot_stale": False,
            "active_ready_cat": "cat:ready",
        }
    ]
    assert result["lastBots"][0]["analysis_ready_status"] == "ready"
    assert result["lastMeta"]["dropped_as_stale"] is True
    assert result["lastMeta"]["dropped_reason"] == "older_request"


def test_apply_bots_data_rerenders_when_bot_structure_changes():
    result = _run_apply_bots_data_scenario(
        """
        context.applyBotsData({
          stale_data: false,
          bots: [
            {
              id: "bot-1",
              symbol: "BTCUSDT",
              status: "running",
              analysis_ready_status: "watch",
              analysis_ready_reason: "watch_setup",
            },
            {
              id: "bot-2",
              symbol: "ETHUSDT",
              status: "paused",
              analysis_ready_status: "blocked",
              analysis_ready_reason: "position_cap_hit",
            },
          ],
        });

        process.stdout.write(JSON.stringify({
          patchCalls: context.patchCalls || 0,
          renderCalls: context.renderCalls || 0,
          renderedBots: context.renderedBots,
        }));
        """,
        same_structure=False,
    )

    assert result == {
        "patchCalls": 0,
        "renderCalls": 1,
        "renderedBots": [
            {
                "id": "bot-1",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "watch_setup",
                "runtime_snapshot_stale": False,
                "active_ready_cat": "cat:watch",
            },
            {
                "id": "bot-2",
                "analysis_ready_status": "blocked",
                "analysis_ready_reason": "position_cap_hit",
                "runtime_snapshot_stale": False,
                "active_ready_cat": "cat:blocked",
            },
        ],
    }


def test_active_bots_dom_stability_sources_are_wired():
    js_text = APP_JS.read_text()
    html_text = DASHBOARD_HTML.read_text()

    assert "function patchBotRowFields(currentRow, bot) {" in js_text
    assert "currentRow.replaceWith(nextRow);" not in js_text
    assert "setActiveBotsGlobalStaleState(runtimeSnapshotStale, runtimeSnapshotDetail);" in js_text
    assert '_state_source: "dashboard_stream"' in js_text
    assert "_request_seq: requestSeq" in js_text
    assert "stale_overlay_preserved" in js_text
    assert 'data-bot-field="actions"' in js_text
    assert 'id="active-bots-stale-indicator"' in html_text
