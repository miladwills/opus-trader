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


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(result.stdout)


def test_render_opportunity_funnel_handles_full_and_partial_payloads():
    js_text = APP_JS.read_text()
    function_sources = [
        _extract_function_source(js_text, "formatOpportunityFunnelWindow"),
        _extract_function_source(js_text, "renderOpportunityFunnelChips"),
        _extract_function_source(js_text, "renderOpportunityFunnel"),
    ]
    script = textwrap.dedent(
        f"""
        const vm = require("vm");
        const functionSources = {json.dumps(function_sources)};

        function makeElement() {{
          return {{
            textContent: "",
            innerHTML: "",
          }};
        }}

        const elementIds = [
          "opportunity-funnel-watch",
          "opportunity-funnel-armed",
          "opportunity-funnel-trigger-ready",
          "opportunity-funnel-executed",
          "opportunity-funnel-blocked",
          "opportunity-funnel-context",
          "opportunity-funnel-rate",
          "opportunity-funnel-blockers",
          "opportunity-funnel-repeat-failures",
          "opportunity-funnel-structural",
        ];
        const elements = Object.fromEntries(elementIds.map((id) => [id, makeElement()]));

        const context = {{
          console,
          watchdogHubState: {{ data: {{}} }},
          $: (id) => elements[id] || null,
          escapeHtml: (value) => String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;"),
          Number,
          String,
          Boolean,
          Object,
          Array,
          Math,
        }};

        vm.createContext(context);
        functionSources.forEach((source) => vm.runInContext(source, context));

        context.watchdogHubState.data = {{
          opportunity_funnel: {{
            snapshot: {{ watch: 4, armed: 2, trigger_ready: 1, late: 1, bot_count: 7 }},
            follow_through: {{ window_sec: 900, executed: 3, blocked: 2, trigger_to_execute_rate: 60.0 }},
            blocked_reasons: [{{ key: "insufficient_margin", label: "Margin", count: 2 }}],
            repeat_failures: [{{ label: "TAOUSDT · long", reason_label: "Margin", count: 2 }}],
            structural_untradeable: [{{ label: "SUIUSDT · long", reason_label: "Min notional" }}],
          }},
        }};
        context.renderOpportunityFunnel();

        const fullResult = {{
          watch: elements["opportunity-funnel-watch"].textContent,
          rate: elements["opportunity-funnel-rate"].textContent,
          context: elements["opportunity-funnel-context"].textContent,
          blockersHtml: elements["opportunity-funnel-blockers"].innerHTML,
          failuresHtml: elements["opportunity-funnel-repeat-failures"].innerHTML,
          structuralHtml: elements["opportunity-funnel-structural"].innerHTML,
        }};

        context.watchdogHubState.data = {{
          opportunity_funnel: {{
            snapshot: {{}},
            follow_through: {{}},
            blocked_reasons: [],
            repeat_failures: [],
            structural_untradeable: [],
          }},
        }};
        context.renderOpportunityFunnel();

        const partialResult = {{
          watch: elements["opportunity-funnel-watch"].textContent,
          executed: elements["opportunity-funnel-executed"].textContent,
          rate: elements["opportunity-funnel-rate"].textContent,
          blockersHtml: elements["opportunity-funnel-blockers"].innerHTML,
          failuresHtml: elements["opportunity-funnel-repeat-failures"].innerHTML,
          structuralHtml: elements["opportunity-funnel-structural"].innerHTML,
        }};

        process.stdout.write(JSON.stringify({{ fullResult, partialResult }}));
        """
    )
    result = _run_node(script)
    assert result["fullResult"]["watch"] == "4"
    assert result["fullResult"]["rate"] == "T→E 60.0%"
    assert result["fullResult"]["context"] == "Live 7 · 15m flow · Late 1"
    assert "Margin 2" in result["fullResult"]["blockersHtml"]
    assert "TAOUSDT · long · Margin 2" in result["fullResult"]["failuresHtml"]
    assert "SUIUSDT · long · Min notional" in result["fullResult"]["structuralHtml"]

    assert result["partialResult"]["watch"] == "0"
    assert result["partialResult"]["executed"] == "0"
    assert result["partialResult"]["rate"] == "T→E n/a"
    assert "No recent blockers" in result["partialResult"]["blockersHtml"]
    assert "No repeat failures" in result["partialResult"]["failuresHtml"]
    assert "No structural mismatches" in result["partialResult"]["structuralHtml"]
