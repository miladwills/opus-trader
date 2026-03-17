import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "js" / "app_lf.js"


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


def _run_active_bot_helper_scenario(assertions_js: str) -> dict:
    js_text = APP_JS.read_text()
    function_names = [
        "getSetupReadiness",
        "getExecutionViability",
        "isTriggerReadyStatus",
        "hasAnalyticalSetupReady",
        "getActiveBotReadinessStatus",
        "getActiveBotReadinessReason",
        "getBaseActiveBotReadyCategory",
        "getEffectiveActiveBotReadyCategory",
        "pruneActiveBotFrontendState",
        "getActiveBotDisplayBucket",
        "trackActiveBotCategoryTransitions",
        "getActiveBotRenderIds",
        "hasSameActiveBotStructure",
        "rememberActiveBotStructure",
        "doesActiveBotMatchFilterState",
        "sortBotsForDisplay",
        "getActiveBotRowDisplayStyle",
    ]
    function_sources = [_extract_function_source(js_text, name) for name in function_names]

    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const functionSources = {json.dumps(function_sources)};
        const context = {{
          console,
          Date,
          Map,
          Set,
          isTradeableBotSymbol: () => true,
          activeBotFilter: "watch",
          activeBotSearchQuery: "",
          pendingBotActions: {{}},
          activeBotRenderedIds: [],
          activeBotWatchGraceState: new Map(),
          activeBotCategoryChangeState: new Map(),
          ACTIVE_BOT_WATCH_STALE_GRACE_MS: 15000,
          ACTIVE_BOT_WATCH_STATUSES: new Set(["watch", "wait", "caution", "armed", "late"]),
          ACTIVE_BOT_LIMITED_STATUSES: new Set(["preview_disabled", "stale", "stale_snapshot", "preview_limited"]),
          ACTIVE_BOT_WATCH_GRACE_REASONS: new Set(["stale", "stale_snapshot", "preview_limited"]),
        }};
        vm.createContext(context);
        for (const source of functionSources) {{
          vm.runInContext(source, context);
        }}
        {assertions_js}
        """
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _run_margin_warning_helper_scenario(assertions_js: str) -> dict:
    js_text = APP_JS.read_text()
    function_names = [
        "getSetupReadiness",
        "getExecutionViability",
        "isTriggerReadyStatus",
        "isLateStatus",
        "hasAnalyticalSetupReady",
        "isSetupReadyMarginLimited",
        "isSetupReadyButBlocked",
        "getActiveBotReadinessStatus",
        "getActiveBotReadinessReason",
        "getBaseActiveBotReadyCategory",
    ]
    function_sources = [_extract_function_source(js_text, name) for name in function_names]

    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const functionSources = {json.dumps(function_sources)};
        const context = {{
          console,
          isTradeableBotSymbol: () => true,
          ACTIVE_BOT_WATCH_STATUSES: new Set(["watch", "wait", "caution", "armed", "late"]),
          ACTIVE_BOT_LIMITED_STATUSES: new Set(["preview_disabled", "stale", "stale_snapshot", "preview_limited"]),
        }};
        vm.createContext(context);
        for (const source of functionSources) {{
          vm.runInContext(source, context);
        }}
        {assertions_js}
        """
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def _run_exchange_truth_ui_scenario(assertions_js: str) -> dict:
    js_text = APP_JS.read_text()
    function_names = [
        "humanizeReason",
        "formatFeedClock",
        "getSetupReadiness",
        "getExecutionViability",
        "isExchangeTruthExecutionReason",
        "getExchangeTruthState",
        "isTriggerReadyStatus",
        "isArmedStatus",
        "isLateStatus",
        "hasAnalyticalSetupReady",
        "entryReadinessBadge",
        "exchangeTruthBadge",
        "renderBotDetailExchangeTruth",
        "escapeHtml",
    ]
    function_sources = [_extract_function_source(js_text, name) for name in function_names]

    node_script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const functionSources = {json.dumps(function_sources)};
        const context = {{
          console,
          Date,
          Map,
          Set,
          Number,
          String,
          Boolean,
          Object,
          Array,
          EXCHANGE_TRUTH_EXECUTION_REASONS: new Set([
            "exchange_truth_stale",
            "reconciliation_diverged",
            "exchange_state_untrusted",
          ]),
          document: {{
            createElement() {{
              return {{
                _textContent: "",
                set textContent(value) {{ this._textContent = String(value ?? ""); }},
                get textContent() {{ return this._textContent; }},
                get innerHTML() {{
                  return this._textContent
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
                }},
              }};
            }},
          }},
        }};
        vm.createContext(context);
        for (const source of functionSources) {{
          vm.runInContext(source, context);
        }}
        {assertions_js}
        """
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_watch_filter_grace_keeps_transient_stale_visible_then_expires():
    result = _run_active_bot_helper_scenario(
        """
        const now = 1_000_000;
        const watchBot = { id: "bot-1", status: "running", analysis_ready_status: "watch", analysis_ready_reason: "watch_setup" };
        const transientStaleBot = { id: "bot-1", status: "running", analysis_ready_status: "preview_limited", analysis_ready_reason: "preview_limited" };
        const unrelatedLimitedBot = { id: "bot-2", status: "running", analysis_ready_status: "preview_limited", analysis_ready_reason: "preview_limited" };

        const initialCategory = context.getEffectiveActiveBotReadyCategory(watchBot, now);
        const withinGraceCategory = context.getEffectiveActiveBotReadyCategory(transientStaleBot, now + 5000);
        const afterGraceCategory = context.getEffectiveActiveBotReadyCategory(transientStaleBot, now + 16000);
        const limitedWithoutHistory = context.getEffectiveActiveBotReadyCategory(unrelatedLimitedBot, now + 5000);

        process.stdout.write(JSON.stringify({
          initialCategory,
          withinGraceCategory,
          afterGraceCategory,
          limitedWithoutHistory,
        }));
        """
    )

    assert result == {
        "initialCategory": "watch",
        "withinGraceCategory": "watch",
        "afterGraceCategory": "limited",
        "limitedWithoutHistory": "limited",
    }


def test_active_bot_structure_match_and_filtered_visibility_stay_stable():
    result = _run_active_bot_helper_scenario(
        """
        context.rememberActiveBotStructure([{ id: "bot-1" }, { id: "bot-2" }]);

        const sameStructure = context.hasSameActiveBotStructure([
          { id: "bot-1", analysis_ready_status: "watch" },
          { id: "bot-2", analysis_ready_status: "blocked" },
        ]);
        const addedBot = context.hasSameActiveBotStructure([
          { id: "bot-1" },
          { id: "bot-2" },
          { id: "bot-3" },
        ]);
        const removedBot = context.hasSameActiveBotStructure([{ id: "bot-1" }]);

        context.activeBotFilter = "watch";
        const visibleWatchStyle = context.getActiveBotRowDisplayStyle({
          id: "bot-1",
          status: "running",
          _active_bots_ready_cat: "watch",
        });
        const hiddenBlockedStyle = context.getActiveBotRowDisplayStyle({
          id: "bot-2",
          status: "running",
          _active_bots_ready_cat: "blocked",
        });
        const runningMatchesWatch = context.doesActiveBotMatchFilterState("running", "watch", "watch");
        const runningMatchesBlocked = context.doesActiveBotMatchFilterState("running", "blocked", "watch");

        process.stdout.write(JSON.stringify({
          sameStructure,
          addedBot,
          removedBot,
          visibleWatchStyle,
          hiddenBlockedStyle,
          runningMatchesWatch,
          runningMatchesBlocked,
        }));
        """
    )

    assert result == {
        "sameStructure": True,
        "addedBot": False,
        "removedBot": False,
        "visibleWatchStyle": "",
        "hiddenBlockedStyle": ' style="display: none;"',
        "runningMatchesWatch": True,
        "runningMatchesBlocked": False,
    }


def test_apply_bots_data_uses_effective_category_and_patch_path():
    js_text = APP_JS.read_text()

    # Category assignment now uses a stability mechanism instead of a single direct assignment
    assert "const rawCat = getEffectiveActiveBotReadyCategory(bot, nowMs);" in js_text
    assert "bot._active_bots_ready_cat = rawCat;" in js_text
    assert "trackActiveBotCategoryTransitions(bots, nowMs);" in js_text
    assert "const sortedBots = sortBotsForDisplay(bots);" in js_text
    assert "const sameStructure = hasSameActiveBotStructure(sortedBots);" in js_text
    assert "if (!sameStructure || !patchActiveBotRowsInPlace(sortedBots)) {" in js_text
    assert 'data-ready-cat="${readyCat}"${getActiveBotRowDisplayStyle(bot)}' in js_text
    assert 'const readyCats = sortedBots.map((bot) => String(bot._active_bots_ready_cat || "other").trim().toLowerCase());' in js_text


def test_active_bot_search_overrides_tab_filter_and_recent_watch_blocked_transitions_sort_last():
    result = _run_active_bot_helper_scenario(
        """
        const initialWatchBots = [
          { id: "bot-1", symbol: "BTCUSDT", status: "stopped", _active_bots_ready_cat: "blocked" },
          { id: "bot-2", symbol: "ETHUSDT", status: "stopped", _active_bots_ready_cat: "watch" },
        ];
        context.trackActiveBotCategoryTransitions(initialWatchBots, 1000);

        const transitionedWatchBots = [
          { id: "bot-1", symbol: "BTCUSDT", status: "stopped", _active_bots_ready_cat: "watch" },
          { id: "bot-2", symbol: "ETHUSDT", status: "stopped", _active_bots_ready_cat: "watch" },
        ];
        context.trackActiveBotCategoryTransitions(transitionedWatchBots, 2000);

        const initialBlockedBots = [
          { id: "bot-3", symbol: "SOLUSDT", status: "stopped", _active_bots_ready_cat: "watch" },
          { id: "bot-4", symbol: "XRPUSDT", status: "stopped", _active_bots_ready_cat: "blocked" },
        ];
        context.trackActiveBotCategoryTransitions(initialBlockedBots, 1000);

        const transitionedBlockedBots = [
          { id: "bot-3", symbol: "SOLUSDT", status: "stopped", _active_bots_ready_cat: "blocked" },
          { id: "bot-4", symbol: "XRPUSDT", status: "stopped", _active_bots_ready_cat: "blocked" },
        ];
        context.trackActiveBotCategoryTransitions(transitionedBlockedBots, 2000);

        context.activeBotFilter = "blocked";
        context.activeBotSearchQuery = "BTC";

        process.stdout.write(JSON.stringify({
          sortedWatchIds: context.sortBotsForDisplay(transitionedWatchBots).map((bot) => bot.id),
          sortedBlockedIds: context.sortBotsForDisplay(transitionedBlockedBots).map((bot) => bot.id),
          visibleAcrossTabsStyle: context.getActiveBotRowDisplayStyle({
            id: "bot-1",
            symbol: "BTCUSDT",
            status: "stopped",
            _active_bots_ready_cat: "watch",
          }),
          hiddenNonMatchStyle: context.getActiveBotRowDisplayStyle({
            id: "bot-2",
            symbol: "ETHUSDT",
            status: "stopped",
            _active_bots_ready_cat: "watch",
          }),
        }));
        """
    )

    assert result == {
        "sortedWatchIds": ["bot-2", "bot-1"],
        "sortedBlockedIds": ["bot-4", "bot-3"],
        "visibleAcrossTabsStyle": "",
        "hiddenNonMatchStyle": ' style="display: none;"',
    }


def test_margin_limited_setup_ready_is_not_bucketed_as_generic_blocked():
    result = _run_margin_warning_helper_scenario(
        """
        const bot = {
          id: "bot-margin",
          symbol: "ETHUSDT",
          status: "running",
          setup_timing_status: "trigger_ready",
          setup_timing_reason: "good_continuation",
          setup_ready: true,
          setup_ready_status: "ready",
          execution_blocked: true,
          execution_viability_status: "blocked",
          execution_viability_reason: "insufficient_margin",
          execution_viability_reason_text: "Insufficient margin",
          execution_viability_bucket: "margin_limited",
          execution_margin_limited: true,
        };
        process.stdout.write(JSON.stringify({
          setupReadyMarginLimited: context.isSetupReadyMarginLimited(bot),
          setupReadyBlocked: context.isSetupReadyButBlocked(bot),
          readinessStatus: context.getActiveBotReadinessStatus(bot),
          readinessReason: context.getActiveBotReadinessReason(bot),
          readyCategory: context.getBaseActiveBotReadyCategory(bot),
        }));
        """
    )

    assert result == {
        "setupReadyMarginLimited": True,
        "setupReadyBlocked": False,
        "readinessStatus": "margin_warning",
        "readinessReason": "insufficient_margin",
        "readyCategory": "watch",
    }


def test_exchange_truth_helpers_render_distinct_active_bot_and_detail_markup():
    result = _run_exchange_truth_ui_scenario(
        """
        const bot = {
          id: "bot-truth",
          symbol: "BTCUSDT",
          status: "running",
          setup_timing_status: "trigger_ready",
          setup_timing_reason: "good_continuation",
          setup_timing_reason_text: "Good continuation",
          setup_ready: true,
          setup_ready_status: "ready",
          execution_blocked: true,
          execution_viability_status: "blocked",
          execution_viability_reason: "reconciliation_diverged",
          execution_viability_reason_text: "Reconciliation diverged",
          execution_viability_detail: "Mismatch: orphaned position",
          exchange_reconciliation_status: "diverged",
          exchange_reconciliation_source: "startup",
          exchange_reconciliation_mismatches: ["orphaned_position"],
          ambiguous_execution_follow_up_status: "still_unresolved",
          ambiguous_execution_follow_up_pending: true,
          ambiguous_execution_follow_up_action: "create_order",
          ambiguous_execution_follow_up_reason: "exchange_owner_ambiguous",
        };
        const truth = context.getExchangeTruthState(bot);
        const activeBadge = context.exchangeTruthBadge(bot);
        const readinessBadge = context.entryReadinessBadge(bot);
        const detailHtml = context.renderBotDetailExchangeTruth(bot);
        process.stdout.write(JSON.stringify({
          truthLabel: truth.label,
          activeBadgeHasTruth: activeBadge.includes("Reconciliation Diverged"),
          readinessBadgeHasTruthTone: readinessBadge.includes("border-sky-400/30"),
          readinessBadgeHasShortTruthLabel: readinessBadge.includes("TRIGGER / Truth Diverged"),
          detailShowsMismatch: detailHtml.includes("Orphaned Position"),
          detailShowsFollowUp: detailHtml.includes("Follow-up Pending"),
          detailShowsAction: detailHtml.includes("Create Order"),
        }));
        """
    )

    assert result == {
        "truthLabel": "Reconciliation Diverged",
        "activeBadgeHasTruth": True,
        "readinessBadgeHasTruthTone": True,
        "readinessBadgeHasShortTruthLabel": True,
        "detailShowsMismatch": True,
        "detailShowsFollowUp": True,
        "detailShowsAction": True,
    }


def test_setup_readiness_prefers_stable_operator_facing_stage_over_raw_stage():
    result = _run_margin_warning_helper_scenario(
        """
        const bot = {
          id: "bot-stable",
          symbol: "BTCUSDT",
          status: "running",
          raw_readiness_stage: "watch",
          raw_readiness_reason: "watch_setup",
          stable_readiness_stage: "trigger_ready",
          stable_readiness_reason: "good_continuation",
          stable_readiness_reason_text: "Good continuation",
          stable_readiness_detail: "Still actionable",
          stable_readiness_actionable: true,
          setup_timing_status: "watch",
          setup_timing_reason: "watch_setup",
        };
        const setup = context.getSetupReadiness(bot);
        process.stdout.write(JSON.stringify({
          status: setup.status,
          rawStatus: setup.rawStatus,
          reason: setup.reason,
          actionable: setup.actionable,
        }));
        """
    )

    assert result == {
        "status": "trigger_ready",
        "rawStatus": "watch",
        "reason": "good_continuation",
        "actionable": True,
    }
