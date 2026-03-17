// FORM functions — extracted from app_lf.js
// 76 functions, 1299 lines
// Loaded before app_lf.js via <script> tag

function normalizeBotModeValue(mode) {
  const normalized = String(mode || "neutral").trim().toLowerCase();
  return SUPPORTED_BOT_MODES.has(normalized) ? normalized : "neutral";
}

function normalizeModePolicyValue(policy, bot = null) {
  const normalized = String(policy || "").trim().toLowerCase();
  if (SUPPORTED_MODE_POLICIES.has(normalized)) return normalized;
  if (bot?.auto_pilot || bot?.auto_direction || bot?.auto_neutral_mode_enabled) {
    return "runtime_auto_switch_non_persistent";
  }
  return "locked";
}

function getBotFormFieldDefinition(fieldKey) {
  return BOT_FORM_FIELD_REGISTRY[fieldKey] || null;
}

function getBotFormSurfaceFieldKeys(surface = "main") {
  return Array.isArray(BOT_FORM_SURFACE_DEFINITIONS?.[surface]?.fieldKeys)
    ? BOT_FORM_SURFACE_DEFINITIONS[surface].fieldKeys
    : [];
}

function getBotFormSurfaceOmittedFieldLabels(surface = "quick") {
  const surfaceKeys = new Set(getBotFormSurfaceFieldKeys(surface));
  return Object.entries(BOT_FORM_FIELD_REGISTRY)
    .filter(([fieldKey, definition]) => surface !== "main" && definition?.surfaces?.includes("main") && !surfaceKeys.has(fieldKey))
    .map(([, definition]) => String(definition.label || "").trim())
    .filter(Boolean);
}

function scopedDomId(scope = "main", id) {
  return scope === "quick" ? `quick-${id}` : id;
}

function getScopedElement(scope = "main", id) {
  return document.getElementById(scopedDomId(scope, id));
}

function createScopedGetter(scope = "main") {
  return (id) => getScopedElement(scope, id);
}

function getSelectedBotMode(getEl = $) {
  return normalizeBotModeValue(getEl("bot-mode")?.value || "neutral");
}

function getSelectedRangeMode(getEl = $) {
  const rangeMode = String(getEl("bot-range-mode")?.value || "fixed").trim().toLowerCase();
  return ["fixed", "dynamic", "trailing"].includes(rangeMode) ? rangeMode : "fixed";
}

function updateModeScopedBotOptions(scope = "main") {
  const getEl = createScopedGetter(scope);
  const mode = getSelectedBotMode(getEl);
  const rangeMode = getSelectedRangeMode(getEl);
  const autoDirectionSupported = AUTO_DIRECTION_SUPPORTED_MODES.has(mode);
  const breakoutConfirmedSupported = BREAKOUT_CONFIRMED_SUPPORTED_MODES.has(mode);
  const trailingSupported = TRAILING_SL_SUPPORTED_MODES.has(mode);
  const quickProfitSupported = isQuickProfitSupported(mode, rangeMode);
  const volatilityGateSupported = VOLATILITY_GATE_SUPPORTED_MODES.has(mode);

  setBotOptionRowState("bot-auto-direction-row", autoDirectionSupported, ["bot-auto-direction"], scope);
  setBotOptionRowState("bot-breakout-confirmed-entry-row", breakoutConfirmedSupported, [
    "bot-breakout-confirmed-entry",
  ], scope);
  setBotOptionRowState("bot-trailing-sl-row", trailingSupported, [
    "bot-trailing-sl",
    "bot-trailing-sl-activation",
    "bot-trailing-sl-distance",
  ], scope);
  setBotOptionRowState("bot-quick-profit-row", quickProfitSupported, [
    "bot-quick-profit-enabled",
    "bot-quick-profit-target",
    "bot-quick-profit-close-pct",
    "bot-quick-profit-cooldown",
  ], scope);
  setBotOptionRowState("bot-volatility-gate-row", volatilityGateSupported, [
    "bot-volatility-gate-enabled",
    "bot-volatility-gate-threshold",
  ], scope);

  const trailingToggle = getEl("bot-trailing-sl");
  const quickProfitToggle = getEl("bot-quick-profit-enabled");
  const volGateToggle = getEl("bot-volatility-gate-enabled");
  setOptionalInputDisabled(
    "bot-trailing-sl-activation",
    !trailingSupported || !trailingToggle || !trailingToggle.checked,
    scope
  );
  setOptionalInputDisabled(
    "bot-trailing-sl-distance",
    !trailingSupported || !trailingToggle || !trailingToggle.checked,
    scope
  );
  setOptionalInputDisabled(
    "bot-quick-profit-target",
    !quickProfitSupported || !quickProfitToggle || !quickProfitToggle.checked,
    scope
  );
  setOptionalInputDisabled(
    "bot-quick-profit-close-pct",
    !quickProfitSupported || !quickProfitToggle || !quickProfitToggle.checked,
    scope
  );
  setOptionalInputDisabled(
    "bot-quick-profit-cooldown",
    !quickProfitSupported || !quickProfitToggle || !quickProfitToggle.checked,
    scope
  );
  setOptionalInputDisabled(
    "bot-volatility-gate-threshold",
    !volatilityGateSupported || !volGateToggle || !volGateToggle.checked,
    scope
  );

  const noteEl = getEl("bot-mode-scope-note");
  if (!noteEl) return;

  const noteParts = [];
  if (!autoDirectionSupported) {
    noteParts.push("Auto Direction: Neutral/Long/Short only.");
  }
  if (!breakoutConfirmedSupported) {
    noteParts.push("Breakout-confirmed entry: Long/Short only.");
  }
  if (!trailingSupported) {
    noteParts.push("Trailing SL: Neutral/Long/Short only.");
  }
  if (!quickProfitSupported) {
    noteParts.push(
      QUICK_PROFIT_SUPPORTED_MODES.has(mode)
        ? "Quick Profit: Dynamic/Trailing range only."
        : "Quick Profit: Neutral/Long/Short with Dynamic/Trailing range only."
    );
  }
  if (!volatilityGateSupported) {
    noteParts.push("Volatility Gate: Neutral Classic only.");
  }

  noteEl.textContent = noteParts.join(" ");
  noteEl.classList.toggle("hidden", noteParts.length === 0);
}

function getConfiguredGridCount(bot) {
  const target = parseInt(bot?.target_grid_count, 10);
  if (Number.isFinite(target) && target > 0) return target;
  const gridCount = parseInt(bot?.grid_count, 10);
  if (Number.isFinite(gridCount) && gridCount > 0) return gridCount;
  return 10;
}

function formatBotModeLabel(mode) {
  const normalized = normalizeBotModeValue(mode);
  const labels = {
    neutral: "Dynamic Neutral",
    neutral_classic_bybit: "Neutral Classic",
    long: "Long",
    short: "Short",
    scalp_pnl: "Scalp PnL",
    scalp_market: "Scalp Market",
  };
  return labels[normalized] || humanizeReason(normalized);
}

function formatRangeModeLabel(rangeMode) {
  const normalized = String(rangeMode || "fixed").trim().toLowerCase();
  const labels = {
    fixed: "Fixed",
    dynamic: "Dynamic",
    trailing: "Trailing",
  };
  return labels[normalized] || humanizeReason(normalized);
}

function formatModePolicyLabel(policy) {
  const normalized = normalizeModePolicyValue(policy);
  const labels = {
    locked: "Locked",
    suggest_only: "Suggest Only",
    runtime_auto_switch_non_persistent: "Runtime Auto Switch",
  };
  return labels[normalized] || humanizeReason(normalized);
}

function getConfiguredModeForUi(bot) {
  return normalizeBotModeValue(bot?.configured_mode || bot?.mode || "neutral");
}

function getConfiguredRangeModeForUi(bot) {
  return String(bot?.configured_range_mode || bot?.range_mode || "fixed").trim().toLowerCase() || "fixed";
}

function getPresetContextBits(bot) {
  const presetId = String(bot?.creation_preset_id || "").trim().toLowerCase();
  const presetName = String(bot?.creation_preset_name || "").trim();
  const presetSource = String(bot?.creation_preset_source || "").trim().toLowerCase();
  const presetType = String(bot?.creation_preset_type || "").trim().toLowerCase();
  const presetFields = Array.isArray(bot?.creation_preset_fields) ? bot.creation_preset_fields : [];
  if (!presetId && !presetName) {
    return {
      title: "Preset Context",
      summary: "No creation preset recorded",
      note: "Manual configuration. Open the full form to apply a new preset before creating another bot.",
    };
  }
  const title = presetName || humanizeReason(presetId);
  const meta = [
    presetType === "custom" ? "Custom preset" : "Creation preset",
    presetSource ? `source ${humanizeReason(presetSource)}` : "",
    presetFields.length ? `${presetFields.length} guided fields` : "",
  ].filter(Boolean).join(" • ");
  return {
    title,
    summary: meta || "Creation preset context",
    note: "Preset context is read-only on existing bots. Open a new bot flow to apply a different preset baseline.",
  };
}

function formatCurrency(value, decimals = 2) {
  if (value === null || value === undefined) return "$0.00";
  const num = parseFloat(value);
  const formatted = Math.abs(num).toFixed(decimals);
  return num < 0 ? `-$${formatted}` : `$${formatted}`;
}

function formatPnL(value, decimals = 2) {
  if (value === null || value === undefined) return { text: "$0.00", class: "text-slate-400" };
  const num = parseFloat(value);
  if (num > 0) return { text: `+$${num.toFixed(decimals)}`, class: "text-emerald-400" };
  if (num < 0) return { text: `-$${Math.abs(num).toFixed(decimals)}`, class: "text-red-400" };
  return { text: "$0.00", class: "text-slate-400" };
}

function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined) return "-";
  return parseFloat(value).toFixed(decimals);
}

function formatVolume(value) {
  if (value === null || value === undefined) return "-";
  const num = parseFloat(value);
  if (num >= 1_000_000_000) return `$${(num / 1_000_000_000).toFixed(2)}B`;
  if (num >= 1_000_000) return `$${(num / 1_000_000).toFixed(2)}M`;
  if (num >= 1_000) return `$${(num / 1_000).toFixed(2)}K`;
  return `$${num.toFixed(2)}`;
}

function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  return `${(parseFloat(value) * 100).toFixed(2)}%`;
}

function formatVelocity(velocity, velocityDisplay) {
  if (velocity === null || velocity === undefined || velocityDisplay === "-") {
    return `<span class="text-slate-500">-</span>`;
  }

  // Color based on direction and magnitude
  let colorClass = "text-slate-400";
  if (velocity > 0.01) {  // > 1%/hr = strong up
    colorClass = "text-emerald-400 font-medium";
  } else if (velocity > 0) {
    colorClass = "text-emerald-400/70";
  } else if (velocity < -0.01) {  // < -1%/hr = strong down
    colorClass = "text-red-400 font-medium";
  } else if (velocity < 0) {
    colorClass = "text-red-400/70";
  }

  return `<span class="${colorClass}">${velocityDisplay}</span>`;
}

function formatTime(isoString) {
  if (!isoString) return "-";
  try {
    return new Date(isoString).toLocaleString();
  } catch { return isoString; }
}

function formatShortDateTime(isoString) {
  if (!isoString) return "-";
  try {
    return new Date(isoString).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return formatTime(isoString);
  }
}

function formatTimeAgo(date) {
  if (!date) return "Never";
  const seconds = Math.floor((new Date() - date) / 1000);
  if (seconds < 5) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function formatElapsed(isoString) {
  if (!isoString) return "";
  try {
    const start = new Date(isoString);
    const now = new Date();
    const seconds = Math.floor((now - start) / 1000);
    if (seconds < 0) return "";
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    const remainMins = mins % 60;
    if (hours < 24) return `${hours}h ${remainMins}m`;
    const days = Math.floor(hours / 24);
    const remainHours = hours % 24;
    return `${days}d ${remainHours}h`;
  } catch { return ""; }
}

function formatDuration(startIso, endIso) {
  // Calculate duration between two ISO timestamps
  if (!startIso || !endIso) return "-";
  try {
    const start = new Date(startIso);
    const end = new Date(endIso);
    const seconds = Math.floor((end - start) / 1000);
    if (seconds < 0) return "-";
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    const remainMins = mins % 60;
    if (hours < 24) return `${hours}h${remainMins}m`;
    const days = Math.floor(hours / 24);
    const remainHours = hours % 24;
    return `${days}d${remainHours}h`;
  } catch { return "-"; }
}

function formatDateTimeLocalInputValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatCountdownSeconds(seconds) {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric)) return "-";
  if (numeric <= 0) return "now";
  const total = Math.floor(numeric);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  if (hours < 24) return `${hours}h ${remainMinutes}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function formatFeedClock(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch (error) {
    return "-";
  }
}

function formatFeedTimeAgo(ts) {
  return formatTimeAgo(new Date(ts));
}

function configureLivePolling(useLiveFeed) {
  if (liveQuickRefreshInterval) clearInterval(liveQuickRefreshInterval);
  if (liveFullRefreshInterval) clearInterval(liveFullRefreshInterval);
  if (_liveFreshPositionInterval) clearInterval(_liveFreshPositionInterval);
  liveQuickRefreshInterval = null;
  liveFullRefreshInterval = null;
  _liveFreshPositionInterval = null;

  if (useLiveFeed) {
    // SSE already carries bridge-backed dashboard snapshots. Do not run a
    // steady-state ?fresh=1 loop here; that bypasses the runner bridge and
    // can stall app workers during exchange or storage contention.
    liveFullRefreshInterval = setInterval(refreshAll, 60000);
    return;
  }

  // Fallback polling when SSE is disconnected
  liveQuickRefreshInterval = setInterval(refreshPnlQuick, LIVE_FALLBACK_PNL_REFRESH_MS);
  liveFullRefreshInterval = setInterval(refreshAll, LIVE_FALLBACK_FULL_REFRESH_MS);
}

function formatWatchdogLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatWatchdogMetricValue(value) {
  if (typeof value === "number") {
    if (Math.abs(value) >= 100) return String(Math.round(value));
    if (Math.abs(value) >= 10) return value.toFixed(1).replace(/\.0$/, "");
    return value.toFixed(2).replace(/\.00$/, "");
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return Object.entries(value).map(([key, nested]) => `${key}:${nested}`).join(", ");
  return String(value ?? "");
}

function formatPerformanceBaselineSummary(meta, options = {}) {
  const normalized = meta || {};
  const effective = normalized.effective || {};
  const globalMeta = normalized.global || {};
  const scope = String(effective.scope || "legacy").trim().toLowerCase();
  const startedAt = effective.baseline_started_at || globalMeta.baseline_started_at || null;
  const prefix = String(options.prefix || "").trim();
  if (!startedAt) {
    return `${prefix ? `${prefix}: ` : ""}Legacy full-history view active`;
  }
  const date = new Date(startedAt);
  const stamp = Number.isNaN(date.getTime()) ? String(startedAt) : date.toLocaleString();
  const scopeLabel = scope === "bot" ? "Bot baseline" : scope === "global" ? "Global baseline" : "Baseline";
  const epochId = effective.epoch_id ? ` (${String(effective.epoch_id)})` : "";
  return `${prefix ? `${prefix}: ` : ""}${scopeLabel} since ${stamp}${epochId}`;
}

function setPerformanceBaselineButtonState(button, isLoading, loadingLabel, idleLabel) {
  if (!button) return;
  button.disabled = Boolean(isLoading);
  button.classList.toggle("opacity-60", Boolean(isLoading));
  button.classList.toggle("cursor-not-allowed", Boolean(isLoading));
  button.textContent = isLoading ? loadingLabel : idleLabel;
}

async function executePerformanceBaselineReset(url, payload, options = {}) {
  const {
    button = null,
    loadingLabel = "Resetting...",
    idleLabel = "Reset Performance Baseline",
    successMessage = "Performance baseline reset",
    afterRefresh = null,
  } = options;
  setPerformanceBaselineButtonState(button, true, loadingLabel, idleLabel);
  try {
    const response = await fetchJSON(url, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    await Promise.allSettled([
      refreshWatchdogHub(),
      refreshBotTriage(),
      refreshBotConfigAdvisor(),
      refreshPnl(),
      refreshBots(),
      refreshSummary(),
      typeof afterRefresh === "function" ? afterRefresh(response) : Promise.resolve(),
    ]);
    showToast(successMessage, "success");
    return response;
  } catch (error) {
    showToast(`Baseline reset failed: ${error.message}`, "error");
    throw error;
  } finally {
    setPerformanceBaselineButtonState(button, false, loadingLabel, idleLabel);
  }
}

async function beginGlobalPerformanceBaselineReset() {
  if (performanceBaselineResetInFlight) return;
  const baselineSummary = formatPerformanceBaselineSummary(
    watchdogHubState.data?.performance_baseline,
    { prefix: "Current baseline" }
  );
  const confirmed = window.confirm(
    `Start a new global measurement epoch?\n\n${baselineSummary}\n\nThis resets Opus Trader derived performance views only. Raw trade logs, exchange/account history, and audit records stay preserved.`
  );
  if (!confirmed) return;
  const note = window.prompt("Optional reset note for the archive snapshot:", "");
  if (note === null) return;
  performanceBaselineResetInFlight = true;
  const button = $("btn-reset-performance-baseline");
  try {
    await executePerformanceBaselineReset(
      "/performance-baseline/reset",
      { note: String(note || "").trim() || null },
      {
        button,
        loadingLabel: "Resetting Baseline...",
        idleLabel: "Reset Performance Baseline",
        successMessage: "New global measurement epoch started",
      }
    );
  } finally {
    performanceBaselineResetInFlight = false;
  }
}

async function beginBotPerformanceBaselineReset(botId, symbol) {
  const normalizedBotId = String(botId || "").trim();
  if (!normalizedBotId || botBaselineResetInFlight) return;
  const label = String(symbol || normalizedBotId || "bot").trim();
  const detailMetaText = $("botDetailBaselineMeta")?.textContent || "";
  const confirmed = window.confirm(
    `Start a new measurement epoch for ${label}?\n\n${detailMetaText}\n\nThis resets Opus Trader derived performance views for this bot only. Raw trade logs, exchange/account history, and audit records stay preserved.`
  );
  if (!confirmed) return;
  const note = window.prompt("Optional reset note for the archived bot snapshot:", "");
  if (note === null) return;
  botBaselineResetInFlight = true;
  const button = $("btn-reset-bot-baseline");
  try {
    await executePerformanceBaselineReset(
      `/bots/${encodeURIComponent(normalizedBotId)}/performance-baseline/reset`,
      { note: String(note || "").trim() || null },
      {
        button,
        loadingLabel: "Resetting Bot Baseline...",
        idleLabel: "Reset Bot Baseline",
        successMessage: `${label} baseline reset`,
        afterRefresh: async () => {
          if (String(window.currentDetailBotId || "") === normalizedBotId) {
            await openBotDetailModal(normalizedBotId);
          }
        },
      }
    );
  } finally {
    botBaselineResetInFlight = false;
  }
}

function formatRuntimeIntegrityAge(value, fallback = "n/a") {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return fallback;
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatOpportunityFunnelWindow(windowSec) {
  const seconds = Number(windowSec || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return "recent";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds % 3600 === 0) return `${Math.round(seconds / 3600)}h`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatBotTriageMode(mode) {
  const normalized = String(mode || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  if (normalized === "neutral_classic_bybit") return "Neutral Classic";
  if (normalized === "scalp_pnl") return "Scalp PnL";
  if (normalized === "scalp_market") return "Scalp Market";
  return formatWatchdogLabel(normalized);
}

function formatBotTriageUpdatedAt(value) {
  const ts = String(value || "").trim();
  if (!ts) return "Last updated: never";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return `Last updated: ${ts}`;
  return `Last updated: ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function getBotTriageActionButtonClass(tone = "default") {
  if (tone === "danger") return "lower-console-button bg-rose-700/80 text-white hover:bg-rose-600";
  if (tone === "accent") return "lower-console-button lower-console-button--accent";
  return "lower-console-button";
}

function formatBotConfigAdvisorValue(key, value) {
  if (value === null || value === undefined || value === "") return "n/a";
  if (key === "leverage") {
    const num = Number(value);
    return Number.isFinite(num) ? `${num}x` : String(value);
  }
  if (key === "session_timer") {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized === "enabled") return "enabled";
    if (normalized === "disabled") return "disabled";
    if (normalized === "recommend_sleep_session_preset") return "sleep preset";
    if (normalized === "keep_enabled") return "keep enabled";
    if (normalized === "keep_disabled") return "keep disabled";
  }
  return String(value || "").replaceAll("_", " ");
}

function getBotConfigAdvisorDiffRows(item) {
  const current = item?.current_settings || {};
  const recommended = item?.recommended_settings || {};
  const keys = ["leverage", "grid_count", "target_grid_count", "grid_distribution", "range_posture", "step_posture", "session_timer"];
  const rows = keys.filter((key) => Object.prototype.hasOwnProperty.call(current, key) || Object.prototype.hasOwnProperty.call(recommended, key)).map((key) => ({
    key,
    label: formatWatchdogLabel(key),
    current: formatBotConfigAdvisorValue(key, current[key]),
    recommended: formatBotConfigAdvisorValue(key, recommended[key]),
    changed: JSON.stringify(current[key]) !== JSON.stringify(recommended[key]),
  }));
  const changedRows = rows.filter((row) => row.changed);
  return (changedRows.length ? changedRows : rows).slice(0, changedRows.length ? 5 : 4);
}

function fillBotForm(bot) {
  const isExistingBot = !!(bot && bot.id);
  mainBotFormContext = bot || null;
  const cachedSpec = bot?.symbol ? window._botFormSymbolSpecs?.[String(bot.symbol).toUpperCase()] : null;
  const tickSizeRaw = cachedSpec?.tick_size_raw || cachedSpec?.tick_size || "";
  const { configuredGridCount, normalizedMode } = hydrateSharedBotConfigFields($, bot, {
    booleanFields: [
      ...SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
      ...MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS,
    ],
    auditContext: "main",
    tickSizeRaw,
  });

  if (cachedSpec) {
    applyPriceInputPrecision(cachedSpec, { reformatExisting: true });
  }
  gridCountManuallyEdited = configuredGridCount > 0;  // Keep existing value if bot has grid_count

  const rangeModeSelect = $("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.disabled = normalizedMode === "scalp_pnl" || normalizedMode === "scalp_market";
  }

  resetBotFormSizingState({
    preserveInvestment: false,
    preserveLeverage: false,
  });
  updateRiskInfo();
  updateScalpPnlInfoVisibility();
  updateAutoPilotVisibility();
  updateSessionTimerVisibility();
  renderSessionTimerRuntimeSummary(bot);
  renderModeSemanticsPanel("main", bot);
  renderPresetContext("main", bot);
  resetBotFormAutoRangeState({
    preserveCurrentRange: false,
  });
  if (isExistingBot && bot.symbol && !bot.auto_pilot) {
    requestAiRange({ force: true, silent: true });
  }
  updateBotPresetSectionVisibility();
  if (isExistingBot) {
    resetBotPresetState({ preserveCatalog: true, preserveSelection: false });
  }
}

function getBotPresetCatalogItems() {
  return Array.isArray(botPresetState?.catalog?.items) ? botPresetState.catalog.items : [];
}

function getCustomBotPresetCatalogItems() {
  return Array.isArray(botPresetState?.catalog?.custom_items) ? botPresetState.catalog.custom_items : [];
}

function getBotPresetById(presetId) {
  const normalized = String(presetId || "").trim().toLowerCase() || "manual_blank";
  return getBotPresetCatalogItems().find((item) => String(item?.preset_id || "") === normalized) || null;
}

function getBotPresetFieldValueForSummary(field, value) {
  if (field === "leverage") return `${Number(value || 0)}x`;
  if (field === "session_timer_enabled") return value ? "enabled" : "disabled";
  if (field === "session_stop_at") return formatTime(value);
  if (field === "session_duration_min") return `${Number(value || 0)} min`;
  if (field === "session_time_selection_required") return value ? "pick fresh times" : "not required";
  return String(value ?? "").replaceAll("_", " ");
}

function clearBotPresetFieldHighlights() {
  BOT_PRESET_MANAGED_FIELD_IDS.forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.classList.remove("ring-1", "ring-cyan-500/40", "border-cyan-500/40");
    delete el.dataset.presetApplied;
  });
}

function markBotPresetFieldsApplied(fieldIds) {
  clearBotPresetFieldHighlights();
  fieldIds.forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.classList.add("ring-1", "ring-cyan-500/40", "border-cyan-500/40");
    el.dataset.presetApplied = "true";
  });
}

function updateBotPresetSectionVisibility() {
  const section = $("bot-preset-section");
  const isEditing = isEditingExistingBotForm();
  if (section) {
    section.classList.remove("hidden");
  }
  const saveCustomButton = $("btn-save-custom-preset");
  if (saveCustomButton) {
    saveCustomButton.classList.toggle("hidden", !isEditing);
  }
  const selectEl = $("bot-preset-select");
  const autoButton = $("bot-preset-auto-recommend");
  if (selectEl) {
    selectEl.classList.toggle("hidden", isEditing);
  }
  if (autoButton) {
    autoButton.classList.toggle("hidden", isEditing);
  }
  const deletePresetButton = $("bot-preset-delete-selected");
  const renamePresetButton = $("bot-preset-rename-selected");
  const activePreset = botPresetState.appliedPreset || getBotPresetById(botPresetState.selectedPreset);
  const isCustomPreset = String(activePreset?.preset_type || "").trim().toLowerCase() === "custom";
  if (deletePresetButton) {
    deletePresetButton.classList.toggle("hidden", isEditing || !isCustomPreset);
  }
  if (renamePresetButton) {
    renamePresetButton.classList.toggle("hidden", isEditing || !isCustomPreset);
  }
}

function getBotPresetSizingViability() {
  const symbol = ($("bot-symbol")?.value || "").trim().toUpperCase();
  if (!isTradeableDashboardSymbol(symbol)) return null;
  const spec = getCurrentBotFormSymbolSpecs();
  if (!spec) return null;

  const referencePrice = Number(spec.mark_price || spec.last_price || 0);
  const minNotional = Number(spec.min_order_value || 0);
  const minQty = Number(spec.min_order_qty || 0);
  const investment = Number(parseFloat($("bot-investment")?.value || 0) || 0);
  const leverage = Math.max(Number(parseFloat($("bot-leverage")?.value || 0) || 0), 1);
  const orderSplits = Math.max(Number(parseInt($("bot-grids")?.value || 0, 10) || 0), 1);
  if (!(referencePrice > 0) || !(investment > 0) || !(orderSplits > 0)) return null;

  const estimatedPerOrderNotional = (investment * leverage) / orderSplits;
  const estimatedPerOrderQty = estimatedPerOrderNotional / referencePrice;
  const minQtyNotional = minQty > 0 ? referencePrice * minQty : null;
  const effectiveMinOrderNotional = Math.max(minNotional || 0, minQtyNotional || 0);
  const blockedReasons = [];
  if (minNotional > 0 && estimatedPerOrderNotional + 1e-9 < minNotional) {
    blockedReasons.push("below_min_notional");
  }
  if (minQty > 0 && estimatedPerOrderQty + 1e-12 < minQty) {
    blockedReasons.push("below_min_qty");
  }

  return {
    symbol,
    priceSource: spec.mark_price ? "mark_price" : (spec.last_price ? "last_price" : null),
    referencePrice,
    estimatedPerOrderNotional,
    estimatedPerOrderQty,
    minNotional: minNotional > 0 ? minNotional : null,
    minQty: minQty > 0 ? minQty : null,
    minQtyNotional,
    effectiveMinOrderNotional: effectiveMinOrderNotional > 0 ? effectiveMinOrderNotional : null,
    blockedReasons,
    viable: blockedReasons.length === 0,
  };
}

function formatBotPresetSizingWarningText(viability) {
  if (!viability || viability.viable) return "";
  const qtyText = `${Number(viability.estimatedPerOrderQty || 0).toFixed(6)} qty`;
  const notionalText = `$${Number(viability.estimatedPerOrderNotional || 0).toFixed(2)} notional`;
  const minQtyText = viability.minQty != null ? `${Number(viability.minQty).toFixed(6)}` : "n/a";
  const minNotionalText = viability.minNotional != null ? `$${Number(viability.minNotional).toFixed(2)}` : "n/a";
  const effectiveText = viability.effectiveMinOrderNotional != null
    ? `$${Number(viability.effectiveMinOrderNotional).toFixed(2)}`
    : "n/a";

  if (viability.blockedReasons.includes("below_min_qty") && viability.blockedReasons.includes("below_min_notional")) {
    return `Per-order slice is below both min_qty ${minQtyText} and min_notional ${minNotionalText}. Effective minimum notional at the current reference price is ${effectiveText}. Estimated slice: ${qtyText} / ${notionalText}.`;
  }
  if (viability.blockedReasons.includes("below_min_qty")) {
    return `Per-order slice passes min_notional ${minNotionalText} but fails min_qty ${minQtyText}. Effective minimum notional at the current reference price is ${effectiveText}. Estimated slice: ${qtyText} / ${notionalText}.`;
  }
  return `Per-order slice fails min_notional ${minNotionalText}. Estimated slice: ${qtyText} / ${notionalText}.`;
}

function resetBotPresetState({ preserveCatalog = true, preserveSelection = true } = {}) {
  botPresetState = {
    catalog: preserveCatalog ? botPresetState.catalog : null,
    selectedPreset: preserveSelection ? "manual_blank" : "",
    appliedPreset: preserveSelection ? getBotPresetById("manual_blank") : null,
    source: "",
    autoReason: "",
    autoReasons: [],
    confidence: "low",
    matchedSignals: [],
    alternativePresets: [],
    autoRecommendedPreset: "",
    loading: false,
  };
  clearBotPresetFieldHighlights();
  renderBotPresetSummary();
}

function applyBotPresetSettings(settings, {
  presetId,
  source = "manual",
  autoReason = "",
  autoReasons = [],
  confidence = "low",
  matchedSignals = [],
  alternativePresets = [],
  autoRecommendedPreset = "",
} = {}) {
  const appliedFieldIds = [];
  const nextSettings = settings || {};

  const rangeModeEl = $("bot-range-mode");
  if (rangeModeEl && nextSettings.range_mode) {
    rangeModeEl.value = String(nextSettings.range_mode);
    appliedFieldIds.push("bot-range-mode");
  }
  const leverageEl = $("bot-leverage");
  if (leverageEl && nextSettings.leverage != null) {
    leverageEl.value = String(nextSettings.leverage);
    botFormAutoLeverageManualOverride = true;
    appliedFieldIds.push("bot-leverage");
  }
  const gridsEl = $("bot-grids");
  if (gridsEl && nextSettings.grid_count != null) {
    gridsEl.value = String(nextSettings.grid_count);
    gridCountManuallyEdited = true;
    appliedFieldIds.push("bot-grids");
  }
  const distributionEl = $("bot-grid-distribution");
  if (distributionEl && nextSettings.grid_distribution) {
    distributionEl.value = String(nextSettings.grid_distribution);
    appliedFieldIds.push("bot-grid-distribution");
  }
  const volatilityEl = $("bot-volatility-gate-threshold");
  if (volatilityEl && nextSettings.neutral_volatility_gate_threshold_pct != null) {
    volatilityEl.value = String(nextSettings.neutral_volatility_gate_threshold_pct);
    appliedFieldIds.push("bot-volatility-gate-threshold");
  }
  const sessionTimerEnabled = $("bot-session-timer-enabled");
  if (sessionTimerEnabled && nextSettings.session_timer_enabled != null) {
    sessionTimerEnabled.checked = !!nextSettings.session_timer_enabled;
    appliedFieldIds.push("bot-session-timer-enabled");
  }
  const sessionStartAt = $("bot-session-start-at");
  if (sessionStartAt) {
    sessionStartAt.value = formatDateTimeLocalInputValue(nextSettings.session_start_at);
    if (nextSettings.session_start_at !== undefined) {
      appliedFieldIds.push("bot-session-start-at");
    }
  }
  const sessionStopAt = $("bot-session-stop-at");
  if (sessionStopAt) {
    sessionStopAt.value = formatDateTimeLocalInputValue(nextSettings.session_stop_at);
    if (nextSettings.session_stop_at !== undefined) {
      appliedFieldIds.push("bot-session-stop-at");
    }
  }
  const sessionNoNew = $("bot-session-no-new-entries-before-stop-min");
  if (sessionNoNew && nextSettings.session_no_new_entries_before_stop_min != null) {
    sessionNoNew.value = String(nextSettings.session_no_new_entries_before_stop_min);
    appliedFieldIds.push("bot-session-no-new-entries-before-stop-min");
  }
  const sessionEndMode = $("bot-session-end-mode");
  if (sessionEndMode && nextSettings.session_end_mode) {
    sessionEndMode.value = String(nextSettings.session_end_mode);
    appliedFieldIds.push("bot-session-end-mode");
  }
  const sessionGrace = $("bot-session-green-grace-min");
  if (sessionGrace && nextSettings.session_green_grace_min != null) {
    sessionGrace.value = String(nextSettings.session_green_grace_min);
    appliedFieldIds.push("bot-session-green-grace-min");
  }
  const sessionCancel = $("bot-session-cancel-pending-orders-on-end");
  if (sessionCancel && nextSettings.session_cancel_pending_orders_on_end != null) {
    sessionCancel.checked = !!nextSettings.session_cancel_pending_orders_on_end;
    appliedFieldIds.push("bot-session-cancel-pending-orders-on-end");
  }
  const sessionReduceOnly = $("bot-session-reduce-only-on-end");
  if (sessionReduceOnly && nextSettings.session_reduce_only_on_end != null) {
    sessionReduceOnly.checked = !!nextSettings.session_reduce_only_on_end;
    appliedFieldIds.push("bot-session-reduce-only-on-end");
  }

  botPresetState.selectedPreset = String(presetId || "manual_blank");
  botPresetState.appliedPreset = getBotPresetById(botPresetState.selectedPreset);
  botPresetState.source = source;
  botPresetState.autoReason = autoReason;
  botPresetState.autoReasons = Array.isArray(autoReasons) ? autoReasons.slice(0, 4) : [];
  botPresetState.confidence = String(confidence || "low");
  botPresetState.matchedSignals = Array.isArray(matchedSignals) ? matchedSignals.slice(0, 5) : [];
  botPresetState.alternativePresets = Array.isArray(alternativePresets) ? alternativePresets.slice(0, 2) : [];
  botPresetState.autoRecommendedPreset = String(autoRecommendedPreset || botPresetState.autoRecommendedPreset || "");
  markBotPresetFieldsApplied(appliedFieldIds);
  updateScalpPnlInfoVisibility();
  updateSessionTimerVisibility();
  updateRiskInfo();
  renderBotPresetSummary();
}

function populateBotPresetSelector() {
  const selectEl = $("bot-preset-select");
  if (!selectEl) return;
  const catalog = botPresetState.catalog || {};
  const builtInItems = Array.isArray(catalog?.built_in_items)
    ? catalog.built_in_items
    : getBotPresetCatalogItems().filter((item) => String(item?.preset_type || "").trim().toLowerCase() !== "custom");
  const customItems = getCustomBotPresetCatalogItems();
  const renderOptions = (items, kind = "built_in") => items.map((item) => {
    let label = String(item?.name || item?.preset_id || "");
    if (kind === "custom") {
      const metaBits = [];
      if (item?.symbol_hint) metaBits.push(String(item.symbol_hint));
      if (item?.mode_hint) metaBits.push(String(item.mode_hint));
      if (item?.session_oriented) metaBits.push("session");
      if (metaBits.length) {
        label = `${label} • ${metaBits.join(" / ")}`;
      }
    }
    return `<option value="${escapeHtml(String(item?.preset_id || ""))}">${escapeHtml(label)}</option>`;
  }).join("");
  const groups = [];
  if (builtInItems.length) {
    groups.push(`<optgroup label="Built-in Presets">${renderOptions(builtInItems, "built_in")}</optgroup>`);
  }
  if (customItems.length) {
    groups.push(`<optgroup label="My Custom Presets">${renderOptions(customItems, "custom")}</optgroup>`);
  }
  selectEl.innerHTML = groups.join("") || '<option value="manual_blank">Manual Blank</option>';
  selectEl.value = String(botPresetState.selectedPreset || "manual_blank");
}

async function loadBotPresetCatalog() {
  const data = await fetchJSON("/bot-presets");
  botPresetState.catalog = data || { items: [] };
  if (!getBotPresetById(botPresetState.selectedPreset || "manual_blank")) {
    botPresetState.selectedPreset = "manual_blank";
  }
  populateBotPresetSelector();
  botPresetState.appliedPreset = getBotPresetById(botPresetState.selectedPreset || "manual_blank");
  botPresetState.confidence = "low";
  botPresetState.matchedSignals = [];
  botPresetState.alternativePresets = [];
  renderBotPresetSummary();
  return data;
}

function applySelectedBotPreset(presetId, options = {}) {
  const preset = getBotPresetById(presetId);
  if (!preset) return;
  applyBotPresetSettings(preset.settings, {
    presetId: preset.preset_id,
    source: options.source || "manual",
    autoReason: options.autoReason || "",
    autoReasons: options.autoReasons || preset.reasons || [],
    confidence: options.confidence || (options.source === "auto" ? botPresetState.confidence || "low" : "low"),
    matchedSignals: options.matchedSignals || [],
    alternativePresets: options.alternativePresets || [],
    autoRecommendedPreset: options.autoRecommendedPreset || "",
  });
  if (String(preset?.preset_type || "").trim().toLowerCase() === "custom") {
    if (!isEditingExistingBotForm()) {
      void emitCustomBotPresetAppliedToNewForm(preset, options.source || "manual");
    }
    if (preset?.session_time_safety?.requires_time_selection) {
      showToast("Custom preset applied. Pick fresh session times before saving the new bot.", "info");
    } else if (preset?.session_time_safety?.duration_min) {
      showToast(`Custom preset applied with a refreshed ${preset.session_time_safety.duration_min} minute session window.`, "success");
    }
  }
}

async function emitCustomBotPresetAppliedToNewForm(preset, source = "manual") {
  if (!preset || String(preset?.preset_type || "").trim().toLowerCase() !== "custom") return;
  try {
    await fetchJSON("/bot-presets/apply-event", {
      method: "POST",
      body: JSON.stringify({
        preset_id: String(preset?.preset_id || ""),
        target_flow: "new_bot_form",
        source: String(source || "manual"),
        symbol: $("bot-symbol")?.value || "",
        mode: $("bot-mode")?.value || "neutral",
      }),
    });
  } catch (error) {
    console.debug("Custom preset apply audit failed:", error);
  }
}

async function saveCurrentBotAsCustomPreset() {
  const botId = String($("bot-id")?.value || "").trim();
  if (!botId) return;
  const symbol = String($("bot-symbol")?.value || "").trim().toUpperCase();
  const mode = String($("bot-mode")?.value || "neutral").trim().toLowerCase();
  const suggestedName = [symbol || "Bot", mode.replaceAll("_", " ")].filter(Boolean).join(" ");
  const presetName = window.prompt("Custom preset name", suggestedName);
  if (presetName == null) return;
  const normalizedName = String(presetName || "").trim();
  if (!normalizedName) {
    showToast("Preset name is required.", "error");
    return;
  }
  try {
    const response = await fetchJSON(`/custom-bot-presets/from-bot/${encodeURIComponent(botId)}`, {
      method: "POST",
      body: JSON.stringify({ preset_name: normalizedName }),
    });
    await loadBotPresetCatalog();
    showToast(`Saved custom preset ${response?.preset?.name || normalizedName}`, "success");
  } catch (error) {
    showToast(`Unable to save custom preset: ${error.message}`, "error");
  }
}

async function deleteSelectedCustomBotPreset() {
  const preset = botPresetState.appliedPreset || getBotPresetById(botPresetState.selectedPreset);
  if (!preset || String(preset?.preset_type || "").trim().toLowerCase() !== "custom") return;
  const presetId = String(preset?.preset_id || "").trim();
  if (!presetId) return;
  const presetName = String(preset?.name || "custom preset");
  if (!window.confirm(`Delete ${presetName}?`)) return;
  try {
    await fetchJSON(`/custom-bot-presets/${encodeURIComponent(presetId)}`, { method: "DELETE" });
    botPresetState.selectedPreset = "manual_blank";
    await loadBotPresetCatalog();
    applySelectedBotPreset("manual_blank", { source: "manual" });
    showToast(`Deleted ${presetName}`, "success");
  } catch (error) {
    showToast(`Unable to delete preset: ${error.message}`, "error");
  }
}

async function renameSelectedCustomBotPreset() {
  const preset = botPresetState.appliedPreset || getBotPresetById(botPresetState.selectedPreset);
  if (!preset || String(preset?.preset_type || "").trim().toLowerCase() !== "custom") return;
  const presetId = String(preset?.preset_id || "").trim();
  if (!presetId) return;
  const presetName = String(preset?.name || "Custom Preset");
  const nextName = window.prompt("Rename custom preset", presetName);
  if (nextName == null) return;
  const normalizedName = String(nextName || "").trim();
  if (!normalizedName) {
    showToast("Preset name is required.", "error");
    return;
  }
  try {
    const response = await fetchJSON(`/custom-bot-presets/${encodeURIComponent(presetId)}`, {
      method: "PATCH",
      body: JSON.stringify({ preset_name: normalizedName }),
    });
    botPresetState.selectedPreset = String(response?.preset?.preset_id || presetId);
    await loadBotPresetCatalog();
    applySelectedBotPreset(botPresetState.selectedPreset, { source: botPresetState.source || "manual" });
    showToast(`Renamed preset to ${response?.preset?.name || normalizedName}`, "success");
  } catch (error) {
    showToast(`Unable to rename preset: ${error.message}`, "error");
  }
}

async function autoRecommendBotPreset() {
  if (isEditingExistingBotForm()) return;
  const button = $("bot-preset-auto-recommend");
  if (botPresetState.loading || !button) return;
  botPresetState.loading = true;
  button.disabled = true;
  try {
    const response = await fetchJSON("/bot-presets/recommend", {
      method: "POST",
      body: JSON.stringify({
        symbol: $("bot-symbol")?.value || "",
        mode: $("bot-mode")?.value || "neutral",
        investment: parseFloat($("bot-investment")?.value || 0) || 0,
        session_timer_enabled: !!$("bot-session-timer-enabled")?.checked,
        session_stop_at: parseOptionalDateTimeInput("bot-session-stop-at"),
      }),
    });
    const preset = response?.preset || null;
    if (!preset?.preset_id) {
      showToast("No preset recommendation available.", "error");
      return;
    }
    botPresetState.catalog = botPresetState.catalog || { items: [] };
    applyBotPresetSettings(preset.settings || {}, {
      presetId: preset.preset_id,
      source: "auto",
      autoReason: String(response?.reason || ""),
      autoReasons: Array.isArray(response?.reasons) ? response.reasons : [],
      confidence: String(response?.confidence || "low"),
      matchedSignals: Array.isArray(response?.matched_signals) ? response.matched_signals : [],
      alternativePresets: Array.isArray(response?.alternative_presets) ? response.alternative_presets : [],
      autoRecommendedPreset: String(response?.recommended_preset || preset.preset_id || ""),
    });
    if (String(preset?.preset_type || "").trim().toLowerCase() === "custom") {
      void emitCustomBotPresetAppliedToNewForm(preset, "auto");
    }
    showToast(`Applied ${preset.name || "recommended preset"}`, "success");
  } catch (error) {
    showToast(`Auto recommend failed: ${error.message}`, "error");
  } finally {
    botPresetState.loading = false;
    button.disabled = false;
  }
}

function resetBotForm() {
  mainBotFormContext = null;
  if ($("bot-id")) $("bot-id").value = "";
  if ($("bot-settings-version")) $("bot-settings-version").value = "";
  if ($("bot-symbol")) $("bot-symbol").value = "";
  if ($("bot-lower")) $("bot-lower").value = "";
  if ($("bot-upper")) $("bot-upper").value = "";
  if ($("bot-lower")) { $("bot-lower").step = "any"; $("bot-lower").placeholder = "0.00"; }
  if ($("bot-upper")) { $("bot-upper").step = "any"; $("bot-upper").placeholder = "0.00"; }
  if ($("bot-grid-distribution")) $("bot-grid-distribution").value = "clustered";
  if ($("bot-grids")) $("bot-grids").value = 10;
  gridCountManuallyEdited = false;
  if ($("bot-investment")) $("bot-investment").value = "";
  if ($("bot-leverage")) $("bot-leverage").value = 3;
  if ($("bot-mode")) $("bot-mode").value = "neutral";
  if ($("bot-mode-policy")) $("bot-mode-policy").value = normalizeModePolicyValue("", {});
  if ($("bot-profile")) $("bot-profile").value = "normal";
  if ($("bot-auto-direction")) $("bot-auto-direction").checked = false;
  if ($("bot-breakout-confirmed-entry")) $("bot-breakout-confirmed-entry").checked = false;
  if ($("bot-auto-stop")) $("bot-auto-stop").value = "";
  if ($("bot-balance-target")) $("bot-balance-target").value = "";
  if ($("bot-auto-pilot-universe-mode")) $("bot-auto-pilot-universe-mode").value = "default_safe";

  const rangeModeSelect = $("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.value = "fixed";
    rangeModeSelect.disabled = false;
  }

  const tpInput = $("bot-tp-pct");
  if (tpInput) tpInput.value = "";

  $("bot-risk-info").innerHTML = "";
  const volGateThresh = $("bot-volatility-gate-threshold");
  if (volGateThresh) volGateThresh.value = 5.0;
  const quickProfitTarget = $("bot-quick-profit-target");
  if (quickProfitTarget) quickProfitTarget.value = "";
  const quickProfitClosePct = $("bot-quick-profit-close-pct");
  if (quickProfitClosePct) quickProfitClosePct.value = "";
  const quickProfitCooldown = $("bot-quick-profit-cooldown");
  if (quickProfitCooldown) quickProfitCooldown.value = "";
  if ($("bot-session-timer-enabled")) $("bot-session-timer-enabled").checked = false;
  if ($("bot-session-start-at")) $("bot-session-start-at").value = "";
  if ($("bot-session-stop-at")) $("bot-session-stop-at").value = "";
  if ($("bot-session-no-new-entries-before-stop-min")) $("bot-session-no-new-entries-before-stop-min").value = "15";
  if ($("bot-session-end-mode")) $("bot-session-end-mode").value = "hard_stop";
  if ($("bot-session-green-grace-min")) $("bot-session-green-grace-min").value = "5";
  if ($("bot-session-force-close-max-loss-pct")) $("bot-session-force-close-max-loss-pct").value = "";
  if ($("bot-session-cancel-pending-orders-on-end")) $("bot-session-cancel-pending-orders-on-end").checked = true;
  if ($("bot-session-reduce-only-on-end")) $("bot-session-reduce-only-on-end").checked = false;
  applyBotConfigBooleanFields($, {}, [
    ...SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
    ...MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS,
  ]);

  resetBotFormSizingState();
  updateTpUsdt();
  updateScalpPnlInfoVisibility();
  updateAutoPilotVisibility();
  updateSessionTimerVisibility();
  renderSessionTimerRuntimeSummary({});
  renderModeSemanticsPanel("main", {});
  renderPresetContext("main", {});
  applyAutoInvestmentFromBalance({ force: true });
  updateRiskInfo();
  resetBotFormAutoRangeState();
  updateBotPresetSectionVisibility();
  resetBotPresetState({ preserveCatalog: true, preserveSelection: true });
}

window.updateAutoPilotVisibility = updateAutoPilotVisibility;

function isEditingExistingBotForm() {
  return !!(($("bot-id")?.value || "").trim());
}

function getBotFormTradingBalance() {
  const availableBalance = Number(window._currentUnifiedBalance || 0);
  const walletEquity = Number(window._currentWalletEquity || previousValues.totalAssets || 0);
  return availableBalance > 0 ? availableBalance : Math.max(walletEquity, 0);
}

function resetBotFormSizingState({
  preserveInvestment = false,
  preserveLeverage = false,
} = {}) {
  botFormAutoInvestmentManualOverride = !!preserveInvestment;
  botFormAutoLeverageManualOverride = !!preserveLeverage;
}

function formatUsdtInputValue(value) {
  const numeric = Number(value || 0);
  if (!isFinite(numeric) || numeric <= 0) return "";
  return numeric.toFixed(2);
}

function formatPriceForBybitInput(value, tickSizeRaw) {
  const numeric = Number(value);
  if (!isFinite(numeric)) return "";
  const decimals = decimalsFromStep(tickSizeRaw);
  if (decimals == null) return String(numeric);
  return numeric.toFixed(decimals);
}

function getCurrentBotFormSymbolSpecs() {
  const symbol = ($("bot-symbol")?.value || "").trim().toUpperCase();
  if (!symbol) return null;
  return window._botFormSymbolSpecs?.[symbol] || null;
}

function formatLeverageInputValue(value) {
  const numeric = Number(value || 0);
  if (!isFinite(numeric) || numeric <= 0) return "1";
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2);
}

function formatRuntimeHours(hours) {
  if (!hours || hours <= 0) return "-";
  const totalMinutes = Math.floor(hours * 60);
  if (totalMinutes <= 0) return "<1m";
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  if (h < 24) return `${h}h ${m}m`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return `${d}d ${rh}h`;
}

function getBotFormAutoRangeContext() {
  const symbol = ($("bot-symbol")?.value || "").trim().toUpperCase();
  const mode = ($("bot-mode")?.value || "neutral").trim().toLowerCase();
  const rangeMode = ($("bot-range-mode")?.value || "fixed").trim().toLowerCase();
  return `${symbol}|${mode}|${rangeMode}`;
}

function resetBotFormAutoRangeState({ preserveCurrentRange = false } = {}) {
  clearTimeout(autoFillDebounceTimer);
  botFormAutoRangeRequestSeq += 1;
  botFormAutoRangeContextKey = getBotFormAutoRangeContext();
  botFormAutoRangeManualOverride = !!preserveCurrentRange;
}

function applyAutoRangeToForm(lower, upper, referencePrice, options = {}) {
  const { preserveGridCountManual = false } = options;
  const lowerInput = $("bot-lower");
  const upperInput = $("bot-upper");
  if (!lowerInput || !upperInput) return false;

  const currentSpec = getCurrentBotFormSymbolSpecs();
  const tickSizeRaw = currentSpec?.tick_size_raw || currentSpec?.tick_size || "";

  botFormSuppressRangeTracking = true;
  lowerInput.value = formatPriceForBotFormDisplay(lower, tickSizeRaw);
  upperInput.value = formatPriceForBotFormDisplay(upper, tickSizeRaw);
  botFormSuppressRangeTracking = false;

  if (!preserveGridCountManual) {
    gridCountManuallyEdited = false;
  }
  botFormAutoRangeManualOverride = false;
  botFormAutoRangeContextKey = getBotFormAutoRangeContext();
  updateRiskInfo();
  return true;
}

// Auto-fill range and grids based on selected symbol + mode.
// let autoFillDebounceTimer = null;  // Defined in app_v5.js
async function autoFillRangeAndGrids(options = {}) {
  const { force = false, debounceMs = 400 } = options;
  const symbol = ($("bot-symbol")?.value || "").trim().toUpperCase();
  const autoPilot = $("bot-auto-pilot")?.checked;
  if (!symbol || symbol.length < 4 || autoPilot) return;

  clearTimeout(autoFillDebounceTimer);
  autoFillDebounceTimer = setTimeout(() => {
    requestAiRange({ force, silent: true });
  }, debounceMs);
}

function allPnlFormatCompactTime(isoString) {
  if (!isoString) return "-";
  try {
    const d = new Date(isoString);
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const dy = String(d.getDate()).padStart(2, "0");
    let hr = d.getHours();
    const ampm = hr >= 12 ? "PM" : "AM";
    hr = hr % 12 || 12;
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    return `${mo}-${dy} ${hr}:${mm}:${ss} ${ampm}`;
  } catch (e) { return isoString; }
}

function formatPrice(price) {
  if (!price) return "?";
  if (price >= 1000) return price.toFixed(0);
  if (price >= 1) return price.toFixed(2);
  return price.toFixed(6);
}

function getBotConfigBooleanFallback(field) {
  return Object.prototype.hasOwnProperty.call(BOT_CONFIG_BOOLEAN_DEFAULTS, field)
    ? !!BOT_CONFIG_BOOLEAN_DEFAULTS[field]
    : false;
}

function getBotConfigBooleanValue(bot, field) {
  if (bot && bot[field] !== undefined && bot[field] !== null) {
    return !!bot[field];
  }
  return getBotConfigBooleanFallback(field);
}

function populateQuickEditForm(bot) {
  const getEl = createScopedGetter("quick");
  const cachedSpec = bot?.symbol ? window._botFormSymbolSpecs?.[String(bot.symbol).toUpperCase()] : null;
  const tickSizeRaw = cachedSpec?.tick_size_raw || cachedSpec?.tick_size || "";
  const summary = $("quick-edit-summary");
  const fullBtn = $("quick-edit-open-full-btn");

  quickEditState.botId = bot.id || "";
  quickEditState.bot = bot || null;

  if (summary) {
    const parts = [
      bot.symbol || "Auto-Pilot",
      humanizeReason(bot.mode || "neutral"),
      humanizeReason(bot.status || "configured"),
    ].filter(Boolean);
    summary.textContent = parts.join(" • ");
  }

  if (fullBtn) {
    fullBtn.disabled = !quickEditState.botId;
    fullBtn.classList.toggle("opacity-60", !quickEditState.botId);
    fullBtn.classList.toggle("cursor-not-allowed", !quickEditState.botId);
  }

  hydrateSharedBotConfigFields(getEl, bot, {
    booleanFields: SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
    auditContext: "quick",
    tickSizeRaw,
  });

  updateScalpPnlInfoVisibility("quick");
  updateAutoPilotVisibility("quick");
  renderModeSemanticsPanel("quick", bot);
  renderPresetContext("quick", bot);
}
