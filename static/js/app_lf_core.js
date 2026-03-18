/**
 * Bybit Control Center - Frontend Application
 * Plain JavaScript client with LIVE real-time updates
 */

// const API_BASE = "/api"; // Defined in app_v5.js

// Variables are defined in app_v5.js: API_BASE, previousValues, audioContext, soundEnabled, gridCountManuallyEdited
// Defensive defaults in case app_v5.js is not loaded or variables are missing
// NOTE: Cannot use var/let/const here — app_v5.js uses 'const' which cannot be redeclared.
// Instead, we check and assign to globalThis (window) only if truly missing.
try { if (typeof API_BASE === 'undefined') globalThis.API_BASE = '/api'; } catch (e) { }
try { if (typeof previousValues === 'undefined') globalThis.previousValues = { totalAssets: null, realizedPnl: null, unrealizedPnl: null, todayNet: null, botPnls: {}, positionPnls: {}, positionCount: 0, pnlLogIds: new Set(), botMarketStates: {}, backtestResults: {} }; } catch (e) { }
try { if (typeof soundEnabled === 'undefined') globalThis.soundEnabled = false; } catch (e) { }
try { if (typeof gridCountManuallyEdited === 'undefined') globalThis.gridCountManuallyEdited = false; } catch (e) { }
try { if (typeof pendingBotActions === 'undefined') globalThis.pendingBotActions = {}; } catch (e) { }
try { if (typeof recentlyStoppedBots === 'undefined') globalThis.recentlyStoppedBots = {}; } catch (e) { }
try { if (typeof autoFillDebounceTimer === 'undefined') globalThis.autoFillDebounceTimer = null; } catch (e) { }
try { if (typeof _currentUnifiedBalance === 'undefined') globalThis._currentUnifiedBalance = 0; } catch (e) { }
try { if (typeof _currentWalletEquity === 'undefined') globalThis._currentWalletEquity = 0; } catch (e) { }
try { if (typeof _botFormSymbolSpecs === 'undefined') globalThis._botFormSymbolSpecs = {}; } catch (e) { }

// Track bots that are currently performing an action to prevent UI flicker
// pendingBotActions is defined in app_v5.js
const STOP_TO_START_GUARD_MS = 5000;
let emergencyRestartBotId = "";
let liveOpenExposureRecommendation = { mode: "", rangeMode: "", differs: false };
let botFormAutoRangeContextKey = "";
let botFormAutoRangeManualOverride = false;
let botFormAutoRangeRequestSeq = 0;
let botFormSuppressRangeTracking = false;
let botFormAutoInvestmentManualOverride = false;
let botFormAutoLeverageManualOverride = false;
let botFormSuppressSizingTracking = false;
let botFormRiskUpdateSeq = 0;
let liveEventSource = null;
let liveQuickRefreshInterval = null;
let liveFullRefreshInterval = null;
let liveQuickRefreshTimeout = null;
let liveFullRefreshTimeout = null;
let livePnlRefreshTimeout = null;
let liveFeedConnected = false;
let lastLiveDashboardUpdateAt = 0;
let lastPnlRefreshAt = 0;
let refreshBotsPromise = null;
let refreshBotsRequestSeq = 0;
let appliedBotsStateSeq = 0;
let allPnlModalRefreshInterval = null;
const LIVE_CONNECTED_PNL_REFRESH_MS = 5000;
const LIVE_CONNECTED_FULL_REFRESH_MS = 15000;
const LIVE_FALLBACK_PNL_REFRESH_MS = 4000;
const LIVE_FALLBACK_FULL_REFRESH_MS = 10000;
const LIVE_DASHBOARD_PNL_REFRESH_MIN_INTERVAL_MS = 3000;
const DASHBOARD_UI_PREFS_KEY = "dashboard_ui_prefs_v20260309";
const ACTIVITY_FEED_LIMIT = 60;
const FEED_DEDUPE_WINDOW_MS = 90000;
const IMPORTANT_PNL_ALERT_THRESHOLD = 1.0;
const PROFIT_RAIN_COOLDOWN_MS = 6000;
const ACTIVE_BOT_WATCH_STALE_GRACE_MS = 15000;
const ACTIVE_BOT_WATCH_STATUSES = new Set(["watch", "wait", "caution", "armed", "late"]);
const ACTIVE_BOT_LIMITED_STATUSES = new Set(["preview_disabled", "stale", "stale_snapshot", "preview_limited"]);
const ACTIVE_BOT_WATCH_GRACE_REASONS = new Set(["stale", "stale_snapshot", "preview_limited"]);
const EXCHANGE_TRUTH_EXECUTION_REASONS = new Set([
  "exchange_truth_stale",
  "reconciliation_diverged",
  "exchange_state_untrusted",
]);
const CONFETTI_COLORS = ["#34d399", "#22d3ee", "#fbbf24", "#f8fafc"];
const DEFAULT_TRAILING_SL_ACTIVATION_PCT = 0.5;
const DEFAULT_TRAILING_SL_DISTANCE_PCT = 0.3;
let dashboardUiPrefs = null;
let dashboardTitlePnlText = "$0.00";
let activeBotRenderedIds = [];
let activeBotWatchGraceState = new Map();
let activeBotCategoryChangeState = new Map();
let floatingScrollButtonState = {
  target: "scanner",
  ticking: false,
};
let readyTitleAlertState = {
  visible: false,
  readyCount: 0,
  intervalId: null,
  timeoutId: null,
};
let quickEditState = {
  botId: "",
  bot: null,
};
let mainBotFormContext = null;
let dashboardFeedState = {
  events: [],
  recentEventKeys: new Map(),
  latestEvent: null,
  botsById: {},
  positionsByKey: {},
  hasBotBaseline: false,
  hasPositionBaseline: false,
  hasPnlBaseline: false,
  lastTodayNet: null,
  lastMilestoneKey: "",
  winStreak: 0,
  lossStreak: 0,
  lastFeedConnectionState: null,
  lastProfitRainAt: 0,
};
let watchdogHubState = {
  data: null,
  selectedKey: "",
  selectedKind: "",
  filters: {
    severity: "",
    watchdogType: "",
    botId: "",
    symbol: "",
    activeOnly: false,
  },
};
let performanceBaselineResetInFlight = false;
let botBaselineResetInFlight = false;
let botTriageState = {
  data: null,
  confirmation: null,
  actionInFlight: false,
};
let botConfigAdvisorState = {
  data: null,
  confirmation: null,
  actionInFlight: false,
};
let botPresetState = {
  catalog: null,
  selectedPreset: "manual_blank",
  appliedPreset: null,
  source: "",
  autoReason: "",
  autoReasons: [],
  confidence: "low",
  matchedSignals: [],
  alternativePresets: [],
  autoRecommendedPreset: "",
  loading: false,
};
const BOT_PRESET_MANAGED_FIELD_IDS = Object.freeze([
  "bot-range-mode",
  "bot-leverage",
  "bot-grids",
  "bot-grid-distribution",
  "bot-volatility-gate-threshold",
  "bot-session-timer-enabled",
  "bot-session-start-at",
  "bot-session-stop-at",
  "bot-session-no-new-entries-before-stop-min",
  "bot-session-end-mode",
  "bot-session-green-grace-min",
  "bot-session-cancel-pending-orders-on-end",
  "bot-session-reduce-only-on-end",
]);
const DIAGNOSTICS_EXPORT_BUTTON_IDS = Object.freeze([
  "btn-export-ai-layer",
  "btn-export-watchdog",
  "btn-export-all-diagnostics",
]);

// Track previous values for change detection
/*
let previousValues = {
  totalAssets: null,
  realizedPnl: null,
  unrealizedPnl: null,
  todayNet: null,
  botPnls: {},
  positionPnls: {},
  positionCount: 0,
  pnlLogIds: new Set(),
  botMarketStates: {},  // Track market state per bot for auto-stop
  backtestResults: {},
};
*/

// Audio context for sound effects
/*
let audioContext = null;
let soundEnabled = false;
*/

// Track if grid count was manually edited (don't auto-override)
// let gridCountManuallyEdited = false;

// Toast notification system
function showToast(message, type = "info") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.style.cssText = "position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:10px;pointer-events:none;";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  const tone = type === "success"
    ? { bg: "rgba(16,185,129,0.88)", border: "rgba(110,231,183,0.38)" }
    : type === "error"
      ? { bg: "rgba(239,68,68,0.9)", border: "rgba(252,165,165,0.38)" }
      : type === "warning"
        ? { bg: "rgba(245,158,11,0.9)", border: "rgba(253,230,138,0.36)" }
        : { bg: "rgba(14,165,233,0.9)", border: "rgba(125,211,252,0.38)" };
  toast.style.cssText = `pointer-events:auto;background:${tone.bg};border:1px solid ${tone.border};backdrop-filter:blur(10px);color:#fff;padding:12px 16px;border-radius:14px;box-shadow:0 14px 36px rgba(2,6,23,0.35);font-size:13px;font-weight:600;transform:translateX(120%);transition:transform 0.28s ease;max-width:min(360px,calc(100vw - 32px));line-height:1.4;`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.style.transform = "translateX(0)", 10);
  setTimeout(() => { toast.style.transform = "translateX(120%)"; setTimeout(() => toast.remove(), 300); }, 4000);
}

// Toggle sound on/off
function logout() {
  // Clear localStorage
  localStorage.clear();

  // Clear sessionStorage
  sessionStorage.clear();

  // Clear all cookies
  document.cookie.split(";").forEach(function (c) {
    document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
  });

  // Redirect to logout endpoint which will clear Basic Auth
  window.location.href = "/logout";
}

// Track if we've unlocked audio context
let audioUnlocked = false;










const SUPPORTED_BOT_MODES = new Set([
  "neutral",
  "neutral_classic_bybit",
  "long",
  "short",
  "scalp_pnl",
  "scalp_market",
]);
const AUTO_DIRECTION_SUPPORTED_MODES = new Set(["neutral", "long", "short"]);
const BREAKOUT_CONFIRMED_SUPPORTED_MODES = new Set(["long", "short"]);
const TRAILING_SL_SUPPORTED_MODES = new Set(["neutral", "long", "short"]);
const QUICK_PROFIT_SUPPORTED_MODES = new Set(["neutral", "long", "short", "neutral_classic_bybit"]);
const VOLATILITY_GATE_SUPPORTED_MODES = new Set(["neutral_classic_bybit"]);
const SUPPORTED_MODE_POLICIES = new Set([
  "locked",
  "suggest_only",
  "runtime_auto_switch_non_persistent",
]);



const BOT_FORM_SECTION_REGISTRY = Object.freeze([
  { key: "market", label: "Symbol / Market" },
  { key: "capital", label: "Capital / Leverage / Sizing" },
  { key: "mode", label: "Mode / Profile / Distribution / Range" },
  { key: "safety", label: "Automation / Protection / Safety" },
  { key: "session", label: "Session / Timing" },
  { key: "preset", label: "Preset Context / Summary" },
]);

const BOT_FORM_FIELD_REGISTRY = Object.freeze({
  symbol: { label: "Symbol", section: "market", surfaces: ["main", "quick"] },
  lower_price: { label: "Lower Price", section: "market", surfaces: ["main", "quick"] },
  upper_price: { label: "Upper Price", section: "market", surfaces: ["main", "quick"] },
  investment: { label: "Investment (USDT)", section: "capital", surfaces: ["main", "quick"] },
  leverage: { label: "Leverage", section: "capital", surfaces: ["main", "quick"] },
  mode: { label: "Configured Mode", section: "mode", surfaces: ["main", "quick"] },
  mode_policy: { label: "Mode Policy", section: "mode", surfaces: ["main", "quick"] },
  profile: { label: "Profile", section: "mode", surfaces: ["main", "quick"] },
  range_mode: { label: "Range Mode", section: "mode", surfaces: ["main", "quick"] },
  grid_distribution: { label: "Grid Distribution", section: "mode", surfaces: ["main", "quick"] },
  grid_count: { label: "Grid Count", section: "mode", surfaces: ["main", "quick"] },
  auto_stop: { label: "Auto Stop (USDT)", section: "capital", surfaces: ["main", "quick"] },
  tp_pct: { label: "Global TP %", section: "capital", surfaces: ["main", "quick"] },
  auto_stop_target_usdt: { label: "Balance Target (USDT)", section: "capital", surfaces: ["main", "quick"] },
  auto_pilot_universe_mode: { label: "Auto-Pilot Universe Mode", section: "market", surfaces: ["main", "quick"] },
  auto_neutral_mode_enabled: { label: "Auto Neutral Mode", section: "safety", surfaces: ["main", "quick"] },
  session_timer_enabled: { label: "Trading Session Timer", section: "session", surfaces: ["main"] },
  auto_stop_loss_enabled: { label: "Auto Stop-Loss", section: "safety", surfaces: ["main"] },
  auto_take_profit_enabled: { label: "Auto Take-Profit", section: "safety", surfaces: ["main"] },
  trend_protection_enabled: { label: "Trend Protection", section: "safety", surfaces: ["main"] },
  danger_zone_enabled: { label: "Danger Zone", section: "safety", surfaces: ["main"] },
  preset_context: { label: "Preset Context", section: "preset", surfaces: ["main", "quick"] },
});

const BOT_FORM_SURFACE_DEFINITIONS = Object.freeze({
  main: {
    fieldKeys: Object.keys(BOT_FORM_FIELD_REGISTRY).filter((key) => BOT_FORM_FIELD_REGISTRY[key].surfaces.includes("main")),
    presetMode: "interactive_or_readonly",
    variant: "full",
  },
  quick: {
    fieldKeys: Object.keys(BOT_FORM_FIELD_REGISTRY).filter((key) => BOT_FORM_FIELD_REGISTRY[key].surfaces.includes("quick")),
    presetMode: "readonly",
    variant: "limited",
  },
});









function isQuickProfitSupported(mode, rangeMode) {
  return QUICK_PROFIT_SUPPORTED_MODES.has(mode) && ["dynamic", "trailing"].includes(rangeMode);
}

function parseOptionalFloatInput(id, transform = null, getEl = $) {
  const el = getEl(id);
  if (!el || el.value.trim() === "") return null;
  const parsed = Number(el.value.trim());
  if (!Number.isFinite(parsed)) return null;
  return typeof transform === "function" ? transform(parsed) : parsed;
}

function parseOptionalIntInput(id, getEl = $) {
  const el = getEl(id);
  if (!el || el.value.trim() === "") return null;
  const parsed = parseInt(el.value.trim(), 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function setOptionalInputDisabled(id, disabled, scope = "main") {
  const el = getScopedElement(scope, id);
  if (el) el.disabled = !!disabled;
}

function setBotOptionRowState(rowId, supported, inputIds = [], scope = "main") {
  const row = getScopedElement(scope, rowId);
  if (row) {
    row.classList.toggle("opacity-40", !supported);
    row.title = supported ? "" : "Not available for the current mode";
  }
  inputIds.forEach((inputId) => {
    const el = getScopedElement(scope, inputId);
    if (el) el.disabled = !supported;
  });
}








function getEffectiveRuntimeModeForUi(bot) {
  return normalizeBotModeValue(bot?.effective_runtime_mode || getConfiguredModeForUi(bot));
}

function getEffectiveRuntimeRangeModeForUi(bot) {
  return String(bot?.effective_runtime_range_mode || getConfiguredRangeModeForUi(bot)).trim().toLowerCase() || "fixed";
}



function buildModeSemanticsContextFromInputs(scope = "main", bot = null) {
  const getEl = createScopedGetter(scope);
  return {
    ...(bot || {}),
    configured_mode: getEl("bot-mode")?.value || bot?.configured_mode || bot?.mode || "neutral",
    configured_range_mode: getEl("bot-range-mode")?.value || bot?.configured_range_mode || bot?.range_mode || "fixed",
    mode_policy: getEl("bot-mode-policy")?.value || bot?.mode_policy || "",
    auto_pilot: getEl("bot-auto-pilot")?.checked ?? bot?.auto_pilot ?? false,
    auto_direction: getEl("bot-auto-direction")?.checked ?? bot?.auto_direction ?? false,
    auto_neutral_mode_enabled: getEl("bot-auto-neutral-mode-enabled")?.checked ?? bot?.auto_neutral_mode_enabled ?? true,
  };
}



function isTradeableDashboardSymbol(symbol) {
  const normalized = String(symbol || "").trim().toUpperCase();
  return !!normalized && normalized !== "AUTO-PILOT";
}

async function fetchJSON(path, options = {}) {
  const { suppress404Log = false, ...fetchOptions } = options;
  try {
    const response = await fetch(API_BASE + path, {
      ...fetchOptions,
      cache: fetchOptions.cache || "no-store",
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const error = new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
      error.status = response.status;
      error.data = errorData;
      throw error;
    }
    return await response.json();
  } catch (error) {
    if (!(suppress404Log && error?.status === 404)) {
      console.error(`API Error (${path}):`, error);
    }
    throw error;
  }
}



function composeDashboardTitle() {
  const readyCount = Math.max(1, Number(readyTitleAlertState.readyCount) || 1);
  const suffix = readyTitleAlertState.visible ? `(${readyCount}) Ready!` : "Opus Trader";
  return `${dashboardTitlePnlText} - ${suffix}`;
}

function syncDashboardTitle() {
  document.title = composeDashboardTitle();
}

function clearReadyTitleAlert() {
  if (readyTitleAlertState.intervalId) {
    window.clearInterval(readyTitleAlertState.intervalId);
    readyTitleAlertState.intervalId = null;
  }
  if (readyTitleAlertState.timeoutId) {
    window.clearTimeout(readyTitleAlertState.timeoutId);
    readyTitleAlertState.timeoutId = null;
  }
  readyTitleAlertState.visible = false;
  readyTitleAlertState.readyCount = 0;
  syncDashboardTitle();
}

function triggerReadyTitleAlert(readyCount = 1) {
  readyTitleAlertState.readyCount = Math.max(1, Number(readyCount) || 1);
  readyTitleAlertState.visible = true;

  if (readyTitleAlertState.intervalId) {
    window.clearInterval(readyTitleAlertState.intervalId);
    readyTitleAlertState.intervalId = null;
  }
  if (readyTitleAlertState.timeoutId) {
    window.clearTimeout(readyTitleAlertState.timeoutId);
    readyTitleAlertState.timeoutId = null;
  }

  syncDashboardTitle();

  if (!prefersReducedMotion()) {
    readyTitleAlertState.intervalId = window.setInterval(() => {
      readyTitleAlertState.visible = !readyTitleAlertState.visible;
      syncDashboardTitle();
    }, 650);
  }

  readyTitleAlertState.timeoutId = window.setTimeout(() => {
    clearReadyTitleAlert();
  }, prefersReducedMotion() ? 4200 : 7200);
}

function updatePageTitle(unrealizedPnl) {
  const num = parseFloat(unrealizedPnl || 0);
  let pnlText;

  if (num > 0) {
    pnlText = `+$${num.toFixed(2)}`;
  } else if (num < 0) {
    pnlText = `-$${Math.abs(num).toFixed(2)}`;
  } else {
    pnlText = "$0.00";
  }

  dashboardTitlePnlText = pnlText;
  syncDashboardTitle();
}











function parseOptionalDateTimeInput(inputId, getEl = $) {
  const el = getEl(inputId);
  const raw = String(el?.value || "").trim();
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}



// =============================================================================
// UPnL Stop-Loss Badges (NEW - Part 10)
// =============================================================================





function pickFiniteReadinessScore(...candidates) {
  for (const candidate of candidates) {
    if (candidate === null || candidate === undefined) continue;
    if (typeof candidate === "string" && candidate.trim() === "") continue;
    const score = Number(candidate);
    if (Number.isFinite(score)) return score;
  }
  return null;
}

function getSetupReadiness(bot) {
  const stableStatusRaw = String(
    bot?.stable_readiness_stage
    || ""
  ).trim().toLowerCase();
  const rawStatus = String(
    bot?.raw_readiness_stage
    || bot?.setup_timing_status
    || bot?.setup_ready_status
    || bot?.analysis_ready_status
    || bot?.entry_ready_status
    || ""
  ).trim().toLowerCase();
  const fallbackStatus = String(
    bot?.setup_timing_status
    || bot?.setup_ready_status
    || bot?.analysis_ready_status
    || bot?.entry_ready_status
    || ""
  ).trim().toLowerCase();
  const statusSource = stableStatusRaw || rawStatus || fallbackStatus;
  const status = statusSource === "ready" ? "trigger_ready" : statusSource;
  return {
    status,
    rawStatus,
    stableStatus: stableStatusRaw || status,
    reason: String(bot?.stable_readiness_reason || bot?.setup_timing_reason || bot?.setup_ready_reason || bot?.analysis_ready_reason || bot?.entry_ready_reason || "").trim().toLowerCase(),
    rawReason: String(bot?.raw_readiness_reason || bot?.setup_timing_reason || bot?.setup_ready_reason || bot?.analysis_ready_reason || bot?.entry_ready_reason || "").trim().toLowerCase(),
    reasonText: String(bot?.stable_readiness_reason_text || bot?.setup_timing_reason_text || bot?.setup_ready_reason_text || bot?.analysis_ready_reason_text || bot?.entry_ready_reason_text || "").trim(),
    detail: String(bot?.stable_readiness_detail || bot?.setup_timing_detail || bot?.setup_ready_detail || bot?.analysis_ready_detail || bot?.entry_ready_detail || "").trim(),
    source: String(bot?.setup_timing_source || bot?.setup_ready_source || bot?.analysis_ready_source || bot?.entry_ready_source || "").trim().toLowerCase(),
    direction: String(bot?.setup_timing_direction || bot?.setup_ready_direction || bot?.analysis_ready_direction || bot?.entry_ready_direction || "").trim().toLowerCase(),
    mode: String(bot?.setup_timing_mode || bot?.setup_ready_mode || bot?.analysis_ready_mode || bot?.entry_ready_mode || "").trim().toLowerCase(),
    updatedAt: String(bot?.stable_readiness_updated_at || bot?.setup_timing_updatedAt || bot?.setup_timing_updated_at || bot?.setup_ready_updated_at || bot?.analysis_ready_updated_at || bot?.entry_ready_updated_at || "").trim(),
    score: pickFiniteReadinessScore(
      bot?.setup_timing_score,
      bot?.setup_ready_score,
      bot?.analysis_ready_score,
      bot?.entry_ready_score,
    ),
    severity: String(bot?.setup_ready_severity || bot?.analysis_ready_severity || "").trim().toUpperCase(),
    next: String(bot?.stable_readiness_next || bot?.setup_timing_next || bot?.setup_ready_next || bot?.analysis_ready_next || "").trim(),
    fallbackUsed: Boolean(bot?.setup_ready_fallback_used || bot?.analysis_ready_fallback_used),
    actionable: Boolean(bot?.stable_readiness_actionable) || Boolean(bot?.setup_timing_actionable) || status === "trigger_ready",
    nearTrigger: Boolean(bot?.stable_readiness_near_trigger) || Boolean(bot?.setup_timing_near_trigger) || status === "armed",
    late: Boolean(bot?.stable_readiness_late) || Boolean(bot?.setup_timing_late) || status === "late",
    stabilityState: String(bot?.readiness_stability_state || "").trim().toLowerCase(),
    stableSince: String(bot?.readiness_stable_since || "").trim(),
    holdUntil: String(bot?.readiness_hold_until || "").trim(),
    flipSuppressed: Boolean(bot?.readiness_flip_suppressed),
    hardInvalidated: Boolean(bot?.readiness_hard_invalidated),
  };
}

function getSetupReadinessSortScore(bot) {
  const score = getSetupReadiness(bot)?.score;
  return Number.isFinite(score) ? score : Number.NEGATIVE_INFINITY;
}

function getAnalysisReadiness(bot) {
  return getSetupReadiness(bot);
}

function getExecutionViability(bot) {
  const status = String(bot?.execution_viability_status || "").trim().toLowerCase();
  const reason = String(bot?.execution_viability_reason || "").trim().toLowerCase();
  const reasonText = String(bot?.execution_viability_reason_text || "").trim();
  const bucket = String(bot?.execution_viability_bucket || "").trim().toLowerCase();
  const detail = String(bot?.execution_viability_detail || "").trim();
  const source = String(bot?.execution_viability_source || "").trim().toLowerCase();
  const updatedAt = String(bot?.execution_viability_updated_at || "").trim();
  const diagnosticReason = String(bot?.execution_viability_diagnostic_reason || "").trim().toLowerCase();
  const diagnosticText = String(bot?.execution_viability_diagnostic_text || "").trim();
  const diagnosticDetail = String(bot?.execution_viability_diagnostic_detail || "").trim();
  const availableMargin = Number.isFinite(Number(bot?.execution_available_margin_usdt)) ? Number(bot.execution_available_margin_usdt) : null;
  const requiredMargin = Number.isFinite(Number(bot?.execution_required_margin_usdt)) ? Number(bot.execution_required_margin_usdt) : null;
  const orderNotional = Number.isFinite(Number(bot?.execution_order_notional_usdt)) ? Number(bot.execution_order_notional_usdt) : null;
  const knownExecutionReasons = new Set([
    "loss_budget_blocked",
    "position_cap_hit",
    "insufficient_margin",
    "qty_below_min",
    "notional_below_min",
    "stale_balance",
    "exchange_truth_stale",
    "reconciliation_diverged",
    "exchange_state_untrusted",
    "breakout_invalidated",
    "session_blocked",
    "stall_blocked",
    "opening_blocked",
  ]);
  const inferredEntryStatus = String(bot?.entry_ready_status || "").trim().toLowerCase();
  const inferredEntryReason = String(bot?.entry_ready_reason || "").trim().toLowerCase();
  if (status) {
    return {
      status,
      reason,
      reasonText,
      bucket: bucket || (
        reason === "insufficient_margin"
          ? "margin_limited"
          : ((reason === "qty_below_min" || reason === "notional_below_min")
            ? "size_limited"
            : (status === "blocked" ? "blocked" : "viable"))
      ),
      detail,
      source,
      updatedAt,
      diagnosticReason,
      diagnosticText,
      diagnosticDetail,
      availableMargin,
      requiredMargin,
      orderNotional,
      marginLimited: Boolean(bot?.execution_margin_limited) || bucket === "margin_limited" || reason === "insufficient_margin",
      staleData: Boolean(bot?.execution_viability_stale_data) || bucket === "stale_balance" || reason === "stale_balance",
      blocked: Boolean(bot?.execution_blocked) || status === "blocked",
    };
  }
  if (inferredEntryStatus === "blocked" && knownExecutionReasons.has(inferredEntryReason)) {
    return {
      status: "blocked",
      reason: inferredEntryReason,
      reasonText: String(bot?.entry_ready_reason_text || "").trim(),
      bucket: inferredEntryReason === "insufficient_margin"
        ? "margin_limited"
        : ((inferredEntryReason === "qty_below_min" || inferredEntryReason === "notional_below_min") ? "size_limited" : "blocked"),
      detail: String(bot?.entry_ready_detail || "").trim(),
      source: String(bot?.entry_ready_source || "").trim().toLowerCase(),
      updatedAt: String(bot?.entry_ready_updated_at || "").trim(),
      diagnosticReason: "",
      diagnosticText: "",
      diagnosticDetail: "",
      availableMargin: null,
      requiredMargin: null,
      orderNotional: null,
      marginLimited: inferredEntryReason === "insufficient_margin",
      staleData: inferredEntryReason === "stale_balance",
      blocked: true,
    };
  }
  return {
    status: "viable",
    reason: "openings_clear",
    reasonText: "Opening clear",
    bucket: "viable",
    detail: "",
    source: "runtime_opening_clear",
    updatedAt: "",
    diagnosticReason: "",
    diagnosticText: "",
    diagnosticDetail: "",
    availableMargin: null,
    requiredMargin: null,
    orderNotional: null,
    marginLimited: false,
    staleData: false,
    blocked: false,
  };
}

function isExchangeTruthExecutionReason(reason) {
  return EXCHANGE_TRUTH_EXECUTION_REASONS.has(String(reason || "").trim().toLowerCase());
}

function getExchangeTruthState(bot) {
  const execution = getExecutionViability(bot);
  const reconcilePayload = bot?.exchange_reconciliation && typeof bot.exchange_reconciliation === "object"
    ? bot.exchange_reconciliation
    : {};
  const reconcileStatus = String(
    bot?.exchange_reconciliation_status || reconcilePayload.status || ""
  ).trim().toLowerCase();
  const reconcileReason = String(
    bot?.exchange_reconciliation_reason || reconcilePayload.reason || ""
  ).trim().toLowerCase();
  const reconcileSource = String(
    bot?.exchange_reconciliation_source || reconcilePayload.source || ""
  ).trim().toLowerCase();
  const updatedAt = String(
    bot?.exchange_reconciliation_updated_at || reconcilePayload.updated_at || ""
  ).trim();
  const mismatches = (Array.isArray(bot?.exchange_reconciliation_mismatches)
    ? bot.exchange_reconciliation_mismatches
    : (Array.isArray(reconcilePayload.mismatches) ? reconcilePayload.mismatches : [])
  )
    .map((item) => String(item || "").trim().toLowerCase())
    .filter(Boolean);
  const followUpPayload = bot?.ambiguous_execution_follow_up && typeof bot.ambiguous_execution_follow_up === "object"
    ? bot.ambiguous_execution_follow_up
    : {};
  const followUpStatus = String(
    bot?.ambiguous_execution_follow_up_status || followUpPayload.status || ""
  ).trim().toLowerCase();
  const followUpPending = Boolean(
    bot?.ambiguous_execution_follow_up_pending ?? followUpPayload.pending
  );
  const followUpAction = String(
    bot?.ambiguous_execution_follow_up_action || followUpPayload.action || ""
  ).trim().toLowerCase();
  const followUpReason = String(
    bot?.ambiguous_execution_follow_up_reason
    || followUpPayload.exchange_effect_reason
    || followUpPayload.reason
    || ""
  ).trim().toLowerCase();
  const truthCheckExpired = Boolean(
    bot?.ambiguous_execution_follow_up_truth_check_expired
    || followUpPayload.truth_check_expired
  );
  const state = {
    visible: false,
    subtle: false,
    blocked: Boolean(execution.blocked && isExchangeTruthExecutionReason(execution.reason)),
    trusted: false,
    reasonKey: "",
    label: "",
    shortLabel: "",
    tone: "slate",
    detail: "",
    reconcileStatus,
    reconcileReason,
    reconcileSource,
    mismatches,
    followUpStatus,
    followUpPending,
    followUpAction,
    followUpReason,
    truthCheckExpired,
    updatedAt,
  };

  if (state.blocked && execution.reason === "reconciliation_diverged") {
    return {
      ...state,
      visible: true,
      reasonKey: "reconciliation_diverged",
      label: "Reconciliation Diverged",
      shortLabel: "Truth Diverged",
      tone: "blue",
      detail: execution.detail || "Exchange reconciliation diverged from local assumptions.",
    };
  }
  if (state.blocked && execution.reason === "exchange_truth_stale") {
    return {
      ...state,
      visible: true,
      reasonKey: "exchange_truth_stale",
      label: "Exchange Truth Stale",
      shortLabel: "Truth Stale",
      tone: "sky",
      detail: execution.detail || "Local exchange assumptions are stale.",
    };
  }
  if (state.blocked && execution.reason === "exchange_state_untrusted") {
    return {
      ...state,
      visible: true,
      reasonKey: "exchange_state_untrusted",
      label: "Follow-up Pending",
      shortLabel: "Follow-up Pending",
      tone: "cyan",
      detail: execution.detail || "A prior exchange action is still awaiting truth confirmation.",
    };
  }
  if (reconcileStatus === "diverged" || reconcileStatus === "error_with_exchange_persist_divergence" || mismatches.length) {
    return {
      ...state,
      visible: true,
      reasonKey: "reconciliation_diverged",
      label: "Reconciliation Diverged",
      shortLabel: "Truth Diverged",
      tone: "blue",
      detail: mismatches.length
        ? `Mismatch: ${mismatches.map((item) => humanizeReason(item)).join(" • ")}`
        : (reconcileReason ? humanizeReason(reconcileReason) : "Reconciliation diverged"),
    };
  }
  if (Boolean(bot?.position_assumption_stale) || Boolean(bot?.order_assumption_stale)) {
    const staleParts = [];
    if (Boolean(bot?.position_assumption_stale)) staleParts.push("Position");
    if (Boolean(bot?.order_assumption_stale)) staleParts.push("Orders");
    return {
      ...state,
      visible: true,
      reasonKey: "exchange_truth_stale",
      label: "Exchange Truth Stale",
      shortLabel: "Truth Stale",
      tone: "sky",
      detail: staleParts.length ? `${staleParts.join(" + ")} assumptions stale` : "Exchange truth stale",
    };
  }
  if (followUpPending || followUpStatus === "still_unresolved" || truthCheckExpired) {
    return {
      ...state,
      visible: true,
      reasonKey: "exchange_state_untrusted",
      label: followUpPending ? "Follow-up Pending" : "Follow-up Unresolved",
      shortLabel: followUpPending ? "Follow-up Pending" : "Follow-up Unresolved",
      tone: "cyan",
      detail: [followUpAction ? humanizeReason(followUpAction) : "", followUpReason ? humanizeReason(followUpReason) : ""]
        .filter(Boolean)
        .join(" • ") || "Exchange truth follow-up still unresolved",
    };
  }
  if (followUpStatus) {
    return {
      ...state,
      visible: true,
      subtle: true,
      trusted: followUpStatus === "success_reflected" || followUpStatus === "no_visible_exchange_effect",
      reasonKey: "follow_up_resolved",
      label: "Follow-up Resolved",
      shortLabel: "Follow-up Resolved",
      tone: "slate",
      detail: [followUpAction ? humanizeReason(followUpAction) : "", followUpReason ? humanizeReason(followUpReason) : humanizeReason(followUpStatus)]
        .filter(Boolean)
        .join(" • "),
    };
  }
  if (reconcileStatus) {
    return {
      ...state,
      visible: true,
      subtle: true,
      trusted: reconcileStatus === "in_sync" || reconcileStatus === "cleanup_flat_confirmed",
      reasonKey: reconcileStatus,
      label: reconcileStatus === "in_sync" ? "In Sync" : humanizeReason(reconcileStatus),
      shortLabel: reconcileStatus === "in_sync" ? "In Sync" : humanizeReason(reconcileStatus),
      tone: "slate",
      detail: reconcileReason ? humanizeReason(reconcileReason) : "",
    };
  }
  return state;
}


function renderBotDetailExchangeTruth(bot) {
  const truth = getExchangeTruthState(bot);
  const toneMap = {
    sky: "border-sky-400/30 bg-sky-500/10 text-sky-100",
    blue: "border-blue-400/30 bg-blue-500/10 text-blue-100",
    cyan: "border-cyan-400/30 bg-cyan-500/10 text-cyan-100",
    slate: "border-slate-700 bg-slate-900/70 text-slate-200",
  };
  const summaryLabel = truth.visible ? truth.label : "No Truth Data";
  const summaryTone = truth.visible ? truth.tone : "slate";
  const statusLabel = truth.reconcileStatus ? humanizeReason(truth.reconcileStatus) : "No reconciliation data";
  const sourceLabel = truth.reconcileSource ? humanizeReason(truth.reconcileSource) : "";
  const updatedLabel = truth.updatedAt ? formatFeedClock(truth.updatedAt) : "";
  const mismatchHtml = truth.mismatches.length
    ? truth.mismatches.map((item) => `<span class="inline-flex items-center rounded-full border border-blue-400/20 bg-blue-500/10 px-2 py-1 text-[11px] font-medium text-blue-100">${escapeHtml(humanizeReason(item))}</span>`).join("")
    : `<span class="text-slate-500">No mismatches</span>`;
  const followUpChips = [];
  if (truth.followUpStatus) {
    followUpChips.push(`<span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-medium ${toneMap[truth.followUpPending ? "cyan" : "slate"]}">${escapeHtml(truth.followUpPending ? "Follow-up Pending" : "Follow-up Resolved")}</span>`);
    followUpChips.push(`<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(humanizeReason(truth.followUpStatus))}</span>`);
    if (truth.followUpAction) {
      followUpChips.push(`<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(humanizeReason(truth.followUpAction))}</span>`);
    }
    if (truth.followUpReason) {
      followUpChips.push(`<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(humanizeReason(truth.followUpReason))}</span>`);
    }
  }
  return `
    <div class="flex flex-wrap items-center gap-2">
      <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${toneMap[summaryTone] || toneMap.slate}">${escapeHtml(summaryLabel)}</span>
      ${truth.blocked ? '<span class="inline-flex items-center rounded-full border border-sky-400/25 bg-sky-500/10 px-2 py-1 text-[11px] font-semibold text-sky-100">Execution Blocked</span>' : ""}
    </div>
    <div class="mt-2 text-xs text-slate-400">${escapeHtml([statusLabel, sourceLabel, updatedLabel ? `Updated ${updatedLabel}` : ""].filter(Boolean).join(" • "))}</div>
    <div class="mt-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">Mismatches</div>
      <div class="mt-2 flex flex-wrap gap-2">${mismatchHtml}</div>
    </div>
    <div class="mt-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">Follow-up</div>
      <div class="mt-2 flex flex-wrap gap-2">${followUpChips.length ? followUpChips.join("") : '<span class="text-slate-500">No follow-up marker</span>'}</div>
    </div>
  `;
}



function renderBotDetailProfitProtection(bot) {
  const meta = getProfitProtectionMeta(bot);
  const advisory = bot?.profit_protection_advisory && typeof bot.profit_protection_advisory === "object"
    ? bot.profit_protection_advisory
    : {};
  const shadow = bot?.profit_protection_shadow && typeof bot.profit_protection_shadow === "object"
    ? bot.profit_protection_shadow
    : {};
  if (!meta.visible) {
    return `<div class="text-sm text-slate-500">Adaptive profit protection is off for this bot.</div>`;
  }
  const toneMap = {
    slate: "border-slate-700 bg-slate-900/70 text-slate-200",
    amber: "border-amber-400/30 bg-amber-500/10 text-amber-100",
    emerald: "border-emerald-400/30 bg-emerald-500/10 text-emerald-100",
    rose: "border-rose-400/30 bg-rose-500/10 text-rose-100",
  };
  const stats = [
    advisory.current_profit_pct != null ? `Now ${formatPercent(advisory.current_profit_pct)}` : "",
    advisory.peak_profit_pct != null ? `Peak ${formatPercent(advisory.peak_profit_pct)}` : "",
    advisory.giveback_pct != null ? `Giveback ${formatPercent(advisory.giveback_pct)}` : "",
    advisory.giveback_threshold_pct != null ? `Threshold ${formatPercent(advisory.giveback_threshold_pct)}` : "",
  ].filter(Boolean);
  const shadowBits = [
    shadow.status ? `Shadow ${humanizeReason(shadow.status)}` : "",
    shadow.result ? humanizeReason(shadow.result) : "",
    shadow.saved_giveback_pct != null ? `Saved ${formatPercent(shadow.saved_giveback_pct)}` : "",
    shadow.trend_cut_pct != null ? `Regret ${formatPercent(shadow.trend_cut_pct)}` : "",
  ].filter(Boolean);
  const detailText = meta.blocked
    ? (bot?.profit_protection_blocked_detail || advisory.blocked_detail || "Profit protection is blocked until runtime truth is trusted.")
    : [
      advisory.reason_family ? humanizeReason(advisory.reason_family) : "",
      advisory.trend_bucket ? `Trend ${humanizeReason(advisory.trend_bucket)}` : "",
      advisory.momentum_state ? `Momentum ${humanizeReason(advisory.momentum_state)}` : "",
      advisory.regime_state ? `Regime ${humanizeReason(advisory.regime_state)}` : "",
    ].filter(Boolean).join(" • ");
  return `
    <div class="flex flex-wrap items-center gap-2">
      <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${toneMap[meta.tone] || toneMap.slate}">${escapeHtml(meta.label)}</span>
      <span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(`Mode ${humanizeReason(meta.mode)}`)}</span>
      ${advisory.armed ? '<span class="inline-flex items-center rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2 py-1 text-[11px] font-medium text-cyan-100">Armed</span>' : ""}
      ${advisory.shadow_status === "triggered" || shadow.status === "triggered" ? '<span class="inline-flex items-center rounded-full border border-amber-400/25 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-100">Shadow Triggered</span>' : ""}
      ${bot?.profit_protection_last_action ? `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(humanizeReason(bot.profit_protection_last_action))}</span>` : ""}
    </div>
    <div class="mt-2 text-xs text-slate-400">${escapeHtml(detailText || "No active profit-protection signal.")}</div>
    <div class="mt-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">Position Snapshot</div>
      <div class="mt-2 flex flex-wrap gap-2">
        ${stats.length ? stats.map((item) => `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(item)}</span>`).join("") : '<span class="text-slate-500">No profit snapshot yet</span>'}
      </div>
    </div>
    <div class="mt-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">Shadow / Outcome</div>
      <div class="mt-2 flex flex-wrap gap-2">
        ${shadowBits.length ? shadowBits.map((item) => `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-slate-200">${escapeHtml(item)}</span>`).join("") : '<span class="text-slate-500">No shadow outcome yet</span>'}
      </div>
    </div>
  `;
}


function getAlternativeModeReadiness(bot) {
  if (!bot?.alternative_mode_ready) return null;
  const mode = normalizeBotModeValue(bot?.alternative_mode || "");
  if (!mode) return null;
  const rangeMode = String(bot?.alternative_mode_range_mode || "fixed").trim().toLowerCase() || "fixed";
  const rawStatus = String(bot?.alternative_mode_stage_status || bot?.alternative_mode_status || "").trim().toLowerCase();
  return {
    mode,
    rangeMode,
    label: String(bot?.alternative_mode_label || formatBotModeLabel(mode)).trim(),
    status: rawStatus === "ready" ? "trigger_ready" : rawStatus,
    reason: String(bot?.alternative_mode_reason || "").trim().toLowerCase(),
    reasonText: String(bot?.alternative_mode_reason_text || "").trim(),
    detail: String(bot?.alternative_mode_detail || "").trim(),
    score: Number.isFinite(Number(bot?.alternative_mode_score)) ? Number(bot.alternative_mode_score) : null,
    updatedAt: String(bot?.alternative_mode_updated_at || "").trim(),
    ageSec: Number.isFinite(Number(bot?.alternative_mode_age_sec)) ? Number(bot.alternative_mode_age_sec) : null,
    sourceKind: String(bot?.alternative_mode_readiness_source_kind || "").trim().toLowerCase(),
    previewState: String(bot?.alternative_mode_preview_state || "").trim().toLowerCase(),
    executionBlocked: Boolean(bot?.alternative_mode_execution_blocked),
    executionStatus: String(bot?.alternative_mode_execution_viability_status || "").trim().toLowerCase(),
    executionReason: String(bot?.alternative_mode_execution_reason || "").trim().toLowerCase(),
    executionReasonText: String(bot?.alternative_mode_execution_reason_text || "").trim(),
    executionDetail: String(bot?.alternative_mode_execution_detail || "").trim(),
    actionable: Boolean(bot?.alternative_mode_actionable),
    nearTrigger: Boolean(bot?.alternative_mode_near_trigger),
    late: Boolean(bot?.alternative_mode_late),
    scannerSuggestion: Boolean(bot?.alternative_mode_is_scanner_suggestion),
    runtimeView: Boolean(bot?.alternative_mode_is_runtime_view),
  };
}

function hasAlternativeModeReady(bot) {
  const alt = getAlternativeModeReadiness(bot);
  return Boolean(alt && ["trigger_ready", "armed", "late"].includes(alt.status));
}

function isTriggerReadyStatus(status) {
  return String(status || "").trim().toLowerCase() === "trigger_ready";
}

function isArmedStatus(status) {
  return String(status || "").trim().toLowerCase() === "armed";
}

function isLateStatus(status) {
  return String(status || "").trim().toLowerCase() === "late";
}






const _readyBoardGrace = new Map();
const READY_BOARD_GRACE_MS = 60000;

function isActionableReadyBot(bot) {
  if (!isTradeableBotSymbol(bot?.symbol)) return false;
  const botId = bot?.id;
  const setup = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  const rawReady = isTriggerReadyStatus(setup.status) && !execution.blocked;

  if (rawReady) {
    // Entering or staying in ready — refresh grace
    if (botId) _readyBoardGrace.set(botId, Date.now() + READY_BOARD_GRACE_MS);
    return true;
  }

  // Not raw-ready — check grace period
  if (botId) {
    const graceUntil = _readyBoardGrace.get(botId) || 0;
    if (Date.now() < graceUntil) {
      return true; // Still within grace — keep on board
    }
    _readyBoardGrace.delete(botId);
  }
  return false;
}

function hasAnalyticalSetupReady(bot) {
  const setupStatus = String(bot?.setup_ready_status || "").trim().toLowerCase();
  return Boolean(bot?.setup_ready) || setupStatus === "ready";
}

function isSetupReadyMarginLimited(bot) {
  if (!isTradeableBotSymbol(bot?.symbol)) return false;
  const setup = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  if (!hasAnalyticalSetupReady(bot) || !execution.marginLimited) return false;
  return !isLateStatus(setup.status);
}

function isSetupReadyButBlocked(bot) {
  if (!isTradeableBotSymbol(bot?.symbol)) return false;
  const setup = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  if (!execution.blocked || execution.marginLimited) return false;
  return isTriggerReadyStatus(setup.status);
}

function getLiveGateStatus(bot) {
  return {
    status: String(bot?.live_gate_status || "").trim().toLowerCase(),
    reason: String(bot?.live_gate_reason || "").trim().toLowerCase(),
    reasonText: String(bot?.live_gate_reason_text || "").trim(),
    detail: String(bot?.live_gate_detail || "").trim(),
    source: String(bot?.live_gate_source || "").trim().toLowerCase(),
    updatedAt: String(bot?.live_gate_updated_at || "").trim(),
  };
}
















function calculateRisk(r) {
  // Calculate risk score based on volatility indicators
  // Higher ATR%, BBW%, and ADX contribute to higher risk
  // Returns: { level: 'low'|'medium'|'high'|'extreme', score: 0-100, factors: [] }

  let score = 0;
  const factors = [];

  // ATR% contribution (0-35 points)
  // Normal: <1%, High: 1-2%, Very High: >2%
  const atrPct = r.atr_pct || 0;
  if (atrPct > 0.025) {
    score += 35;
    factors.push(`ATR ${(atrPct * 100).toFixed(1)}% (extreme)`);
  } else if (atrPct > 0.018) {
    score += 28;
    factors.push(`ATR ${(atrPct * 100).toFixed(1)}% (high)`);
  } else if (atrPct > 0.012) {
    score += 18;
    factors.push(`ATR ${(atrPct * 100).toFixed(1)}% (moderate)`);
  } else if (atrPct > 0.008) {
    score += 10;
  }

  // BBW% contribution (0-30 points)
  // Bollinger Band Width indicates volatility expansion
  const bbwPct = r.bbw_pct || 0;
  if (bbwPct > 0.08) {
    score += 30;
    factors.push(`BBW ${(bbwPct * 100).toFixed(1)}% (extreme)`);
  } else if (bbwPct > 0.05) {
    score += 22;
    factors.push(`BBW ${(bbwPct * 100).toFixed(1)}% (high)`);
  } else if (bbwPct > 0.03) {
    score += 12;
  } else if (bbwPct > 0.02) {
    score += 6;
  }

  // ADX contribution (0-20 points)
  // High ADX = strong trend = higher directional risk
  const adx = r.adx || 0;
  if (adx > 40) {
    score += 20;
    factors.push(`ADX ${adx.toFixed(0)} (strong trend)`);
  } else if (adx > 30) {
    score += 14;
    factors.push(`ADX ${adx.toFixed(0)} (trending)`);
  } else if (adx > 25) {
    score += 8;
  }

  // Regime penalty (0-15 points)
  const regime = r.regime || '';
  if (regime === 'too_strong') {
    score += 15;
    factors.push('Regime: too strong');
  } else if (regime === 'trending') {
    score += 8;
  } else if (regime === 'illiquid') {
    score += 10;
    factors.push('Low liquidity');
  }

  // Determine risk level
  let level;
  if (score >= 70) {
    level = 'extreme';
  } else if (score >= 50) {
    level = 'high';
  } else if (score >= 30) {
    level = 'medium';
  } else {
    level = 'low';
  }

  return { level, score: Math.min(score, 100), factors };
}



function prefersReducedMotion() {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function ensureDashboardUiPrefs() {
  if (dashboardUiPrefs) {
    return dashboardUiPrefs;
  }
  const defaults = {
    browserAlerts: false,
    confetti: true,
    profitRain: true,
    profitRainMinPnl: 3,
  };
  try {
    const stored = localStorage.getItem(DASHBOARD_UI_PREFS_KEY);
    dashboardUiPrefs = stored ? { ...defaults, ...JSON.parse(stored) } : defaults;
  } catch (error) {
    dashboardUiPrefs = defaults;
  }
  dashboardUiPrefs.profitRainMinPnl = Number(dashboardUiPrefs.profitRainMinPnl || defaults.profitRainMinPnl);
  if (!Number.isFinite(dashboardUiPrefs.profitRainMinPnl) || dashboardUiPrefs.profitRainMinPnl <= 0) {
    dashboardUiPrefs.profitRainMinPnl = defaults.profitRainMinPnl;
  }
  return dashboardUiPrefs;
}

function saveDashboardUiPrefs() {
  const prefs = ensureDashboardUiPrefs();
  try {
    localStorage.setItem(DASHBOARD_UI_PREFS_KEY, JSON.stringify(prefs));
  } catch (error) {
    console.debug("Failed to persist dashboard UI prefs:", error);
  }
  updateDashboardPreferenceButtons();
}

function updateDashboardPreferenceButtons() {
  const prefs = ensureDashboardUiPrefs();
  const browserBtn = $("browser-alerts-toggle");
  const confettiBtn = $("confetti-toggle");
  const profitRainBtn = $("profit-rain-toggle");
  const profitRainThreshold = $("profit-rain-threshold");

  if (browserBtn) {
    const supported = typeof window !== "undefined" && "Notification" in window;
    const permission = supported ? Notification.permission : "unsupported";
    let label = "Alerts Off";
    let classes = "metric-pill transition hover:border-cyan-400/40 hover:text-white";
    browserBtn.disabled = false;

    if (!supported) {
      label = "Alerts Unsupported";
      browserBtn.disabled = true;
      classes += " opacity-60 cursor-not-allowed";
    } else if (permission === "denied") {
      label = "Alerts Blocked";
      classes += " border-red-400/35 bg-red-500/10 text-red-300";
    } else if (prefs.browserAlerts && permission === "granted") {
      label = "Alerts On";
      classes += " border-cyan-400/35 bg-cyan-500/10 text-cyan-200";
    } else {
      classes += " text-slate-200";
    }

    browserBtn.textContent = label;
    browserBtn.className = classes;
  }

  if (confettiBtn) {
    confettiBtn.textContent = prefs.confetti ? "Confetti On" : "Confetti Off";
    confettiBtn.className = `metric-pill transition hover:border-emerald-400/40 hover:text-white ${prefs.confetti
      ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-200"
      : "text-slate-200"
      }`;
  }

  if (profitRainBtn) {
    const reducedMotion = prefersReducedMotion();
    const enabled = prefs.profitRain && !reducedMotion;
    profitRainBtn.textContent = reducedMotion ? "Profit FX Reduced" : (prefs.profitRain ? "Profit FX On" : "Profit FX Off");
    profitRainBtn.disabled = reducedMotion;
    profitRainBtn.title = reducedMotion
      ? "Profit FX is disabled because reduced-motion is enabled in this browser"
      : "Enable or disable realized-profit visual effects";
    profitRainBtn.className = `metric-pill transition hover:border-emerald-400/40 hover:text-white ${enabled
      ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-200"
      : reducedMotion
        ? "border-slate-700 text-slate-500 opacity-70 cursor-not-allowed"
        : "text-slate-200"
      }`;
  }

  if (profitRainThreshold) {
    profitRainThreshold.value = String(prefs.profitRainMinPnl || 3);
    profitRainThreshold.disabled = !prefs.profitRain || prefersReducedMotion();
    profitRainThreshold.classList.toggle("opacity-60", profitRainThreshold.disabled);
    profitRainThreshold.classList.toggle("cursor-not-allowed", profitRainThreshold.disabled);
  }
}

async function toggleBrowserAlerts() {
  const prefs = ensureDashboardUiPrefs();
  if (!("Notification" in window)) {
    showToast("Browser notifications are not supported here", "warning");
    updateDashboardPreferenceButtons();
    return;
  }

  if (prefs.browserAlerts) {
    prefs.browserAlerts = false;
    saveDashboardUiPrefs();
    showToast("Browser alerts disabled", "info");
    return;
  }

  if (Notification.permission === "granted") {
    prefs.browserAlerts = true;
    saveDashboardUiPrefs();
    showToast("Browser alerts enabled", "success");
    return;
  }

  if (Notification.permission === "denied") {
    showToast("Browser notifications are blocked in this browser", "warning");
    updateDashboardPreferenceButtons();
    return;
  }

  try {
    const permission = await Notification.requestPermission();
    prefs.browserAlerts = permission === "granted";
    saveDashboardUiPrefs();
    showToast(
      permission === "granted" ? "Browser alerts enabled" : "Browser alerts were not allowed",
      permission === "granted" ? "success" : "warning"
    );
  } catch (error) {
    showToast("Browser alert permission request failed", "warning");
    updateDashboardPreferenceButtons();
  }
}




function humanizeReason(value) {
  const text = String(value || "").trim().replace(/[_-]+/g, " ");
  if (!text) return "";
  return text.replace(/\b\w/g, (char) => char.toUpperCase());
}

function truncateText(text, maxLength = 96) {
  const value = String(text || "").trim();
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(maxLength - 1, 1))}…`;
}





function buildMetricChip(label, tone = "slate") {
  const classes = {
    slate: "border-slate-700 bg-slate-800/70 text-slate-200",
    cyan: "border-cyan-400/30 bg-cyan-500/10 text-cyan-200",
    emerald: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
    amber: "border-amber-400/30 bg-amber-500/10 text-amber-200",
    rose: "border-rose-400/30 bg-rose-500/10 text-rose-200",
  };
  return `<span class="metric-pill ${classes[tone] || classes.slate}">${escapeHtml(label)}</span>`;
}

function isMeaningfulPnl(value) {
  return Math.abs(Number(value || 0)) >= IMPORTANT_PNL_ALERT_THRESHOLD;
}

function isTradeableBotSymbol(symbol) {
  return isTradeableDashboardSymbol(symbol || "");
}

function isStallOverlaySignal(bot) {
  const haystack = [
    bot?.last_replacement_action,
    bot?.last_skip_reason,
    bot?.scalp_status,
    bot?.last_error,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return /stall|stall overlay|stall_overlay|defensive trim|defensive_trim/.test(haystack);
}

function getPrimaryBotAlert(bot) {
  if (!bot) return "";

  // Opening-order block alerts — show WHY a running bot can't place orders
  // with recommended fix action
  if (bot.status === "running") {
    if (bot._small_capital_block_opening_orders) {
      const skip = String(bot.last_skip_reason || "").toLowerCase();
      if (skip === "meme_mode_guard")
        return "⛔ MEME guard: only trailing_long allowed · Switch mode or invest >$50";
      if (skip === "budget_below_min_notional")
        return "⛔ Budget too small for min order · Increase investment or leverage";
      return "⛔ Small capital block · Increase investment or leverage";
    }
    if (bot._capital_starved_block_opening_orders)
      return "⛔ Capital starved: orders below min notional · Increase leverage or investment";
    if (bot._session_timer_block_opening_orders)
      return "⏱️ Session timer: new entries blocked until session completes";
    if (bot._auto_pilot_loss_budget_block_openings)
      return "⛔ Auto-pilot loss budget exhausted · Add capital or reset";
    if (bot._stall_overlay_block_opening_orders)
      return "⏸️ Trade stalled — tighter exit rules active · Wait or close manually";
    if (bot._nlp_block_opening_orders)
      return "⛔ Neutral gate blocked: momentum/inventory exceeded";
    if (bot._breakout_invalidation_block_opening_orders)
      return "⛔ Breakout invalidated — waiting for new confirmation";
    if (bot._block_opening_orders)
      return "⛔ Opening orders blocked · Check exchange state or wait for resolution";
    // Fallback: use server-computed opening_blocked_reason if no specific flag matched
    if (bot.opening_blocked_reason) {
      const reason = String(bot.opening_blocked_reason).replace(/_/g, " ");
      return `⛔ Orders blocked: ${reason} · Check bot config`;
    }
  }
  if (bot.status === "stop_cleanup_pending")
    return "🔄 Stop cleanup pending — waiting for orders/position to clear";
  if (bot.status === "error")
    return "❌ Error state — check exchange for orphaned orders/positions";

  if (bot.session_timer_enabled) {
    if (bot.session_timer_state === "scheduled_not_started") {
      return truncateText(
        bot.session_timer_starts_in_sec != null
          ? `Session starts in ${formatCountdownSeconds(bot.session_timer_starts_in_sec)}`
          : "Session scheduled",
        84,
      );
    }
    if (bot.session_timer_state === "pre_stop_no_new_entries") {
      return "Session pre-stop active: new entries blocked";
    }
    if (bot.session_timer_state === "grace_active") {
      return truncateText(
        bot.session_timer_grace_remaining_sec != null
          ? `Session grace active: ${formatCountdownSeconds(bot.session_timer_grace_remaining_sec)} left`
          : "Session grace active",
        84,
      );
    }
    if (bot.session_timer_state === "completed") {
      return "Session complete";
    }
  }
  if (bot.status === "risk_stopped") {
    return `Risk stop on ${bot.symbol}`;
  }
  if (bot.last_error) {
    return truncateText(bot.last_error, 84);
  }
  if (bot.auto_pilot_block_reason) {
    return `Pick blocked: ${humanizeReason(bot.auto_pilot_block_reason)}`;
  }
  if (bot.entry_gate_blocked) {
    return truncateText(bot.entry_gate_reason || "Entry Gate blocked", 84);
  }
  const analysis = getAnalysisReadiness(bot);
  const execution = getExecutionViability(bot);
  if (hasAnalyticalSetupReady(bot) && execution.marginLimited) {
    return truncateText(
      execution.detail
      || `${analysis.reasonText || "Setup ready"} • ${execution.reasonText || "Margin warning"}`,
      84
    );
  }
  if (isTriggerReadyStatus(analysis.status) && execution.blocked) {
    return truncateText(
      execution.detail
      || `${analysis.reasonText || "Trigger ready"} • ${execution.reasonText || "Opening blocked"}`,
      84
    );
  }
  if (isArmedStatus(analysis.status) || isLateStatus(analysis.status)) {
    return truncateText(
      analysis.detail
      || analysis.reasonText
      || formatReadinessStageLabel(analysis.status),
      84
    );
  }
  if (analysis.status === "blocked" || analysis.status === "watch") {
    return truncateText(
      analysis.detail
      || analysis.reasonText
      || humanizeReason(analysis.reason || analysis.status),
      84
    );
  }
  if (bot.upnl_stoploss_active) {
    return truncateText(bot.upnl_stoploss_reason || "Soft loss guard active", 84);
  }
  if (isStallOverlaySignal(bot)) {
    return truncateText(humanizeReason(bot.last_replacement_action || bot.last_skip_reason || "stall overlay active"), 84);
  }
  if (bot.last_skip_reason) {
    return truncateText(humanizeReason(bot.last_skip_reason), 84);
  }
  return "";
}

function buildSessionTimerStateChips(bot) {
  if (!bot?.session_timer_enabled) return [];
  const chips = [];
  chips.push(buildMetricChip(`Session ${humanizeReason(bot.session_timer_state || "inactive")}`, "cyan"));
  if (bot.session_stop_at) {
    chips.push(buildMetricChip(`Ends ${formatShortDateTime(bot.session_stop_at)}`, "slate"));
  }
  if (bot.session_timer_no_new_entries_active) {
    chips.push(buildMetricChip("No New Entries", "amber"));
  } else if (Number.isFinite(Number(bot.session_timer_pre_stop_in_sec)) && Number(bot.session_timer_pre_stop_in_sec) > 0) {
    chips.push(buildMetricChip(`No New In ${formatCountdownSeconds(bot.session_timer_pre_stop_in_sec)}`, "slate"));
  }
  if (bot.session_timer_grace_active) {
    chips.push(buildMetricChip(
      bot.session_timer_grace_remaining_sec != null
        ? `Grace ${formatCountdownSeconds(bot.session_timer_grace_remaining_sec)}`
        : "Grace Active",
      "emerald",
    ));
  }
  if (bot.session_timer_complete) {
    chips.push(buildMetricChip("Session Complete", "emerald"));
  }
  return chips;
}

function buildBotStateChips(bot, limit = 3) {
  // Safety-critical chips first, informational last
  const chips = [];

  if (bot.upnl_stoploss_active) {
    chips.push(buildMetricChip("Soft SL", "rose"));
  }
  if (bot.entry_gate_blocked) {
    chips.push(buildMetricChip("Entry Gate", "amber"));
  }
  if (isStallOverlaySignal(bot)) {
    chips.push(buildMetricChip("Stall Active", "amber"));
  }
  const protectionBadge = profitProtectionBadge(bot);
  if (protectionBadge) {
    chips.push(protectionBadge);
  }
  const exchangeTruth = getExchangeTruthState(bot);
  if (exchangeTruth.visible && !exchangeTruth.subtle) {
    const truthTone = exchangeTruth.tone === "blue"
      ? "cyan"
      : (exchangeTruth.tone === "sky" ? "cyan" : "cyan");
    chips.push(buildMetricChip(exchangeTruth.shortLabel, truthTone));
  }

  // Session timer chips
  chips.push(...buildSessionTimerStateChips(bot));

  if (Number(bot.profit_lock_executed_count || 0) > 0) {
    chips.push(buildMetricChip(`Profit Lock ×${Number(bot.profit_lock_executed_count || 0)}`, "emerald"));
  }

  // Auto-pilot informational chips (lowest priority)
  if (bot.auto_pilot_block_reason) {
    chips.push(buildMetricChip("Pick Blocked", "amber"));
  }
  if (bot.auto_pilot_candidate_source) {
    chips.push(buildMetricChip(`Source ${String(bot.auto_pilot_candidate_source).toUpperCase()}`, "cyan"));
  }
  if (bot.auto_pilot_search_status) {
    chips.push(buildMetricChip(`Search ${humanizeReason(bot.auto_pilot_search_status)}`, "slate"));
  }
  if (bot.auto_pilot_pick_status && !bot.auto_pilot_block_reason) {
    chips.push(buildMetricChip(`Pick ${humanizeReason(bot.auto_pilot_pick_status)}`, "cyan"));
  }

  return chips.slice(0, limit);
}


function buildBotActionButtons(bot, mobile = false) {
  const activePendingAction = pendingBotActions[bot.id];
  const recentlyStoppedAt = Number(recentlyStoppedBots[bot.id] || 0);
  const canResume = ["paused", "recovering", "flash_crash_paused"].includes(bot.status);
  const canStart = !["running", "paused", "recovering", "flash_crash_paused"].includes(bot.status);
  const stopGuardActive =
    bot.status === "stopped" && (Date.now() - recentlyStoppedAt) < STOP_TO_START_GUARD_MS;
  const stopGuardSec = Math.max(
    1,
    Math.ceil((STOP_TO_START_GUARD_MS - (Date.now() - recentlyStoppedAt)) / 1000)
  );
  const resumeTitle = bot.status === "recovering" ? "Force Resume" : "Resume";
  const baseClass = mobile
    ? "bot-action-btn bot-action-btn--mobile"
    : "bot-action-btn bot-action-btn--compact";

  const primaryClass = `${baseClass} bot-action-btn--primary`;

  // Top row: utility buttons (Pause, Resume, Edit, Config, Delete)
  const utilityButtons = [
    bot.status === "running" && activePendingAction === "pause"
      ? `<button disabled class="${baseClass} bot-action-btn--pause" style="opacity:0.7;cursor:not-allowed"><span class="animate-spin inline-block">↻</span><span>Pausing…</span></button>`
      : bot.status === "running"
        ? `<button onclick="botAction('pause', '${bot.id}', event)" class="${baseClass} bot-action-btn--pause"><span>⏸</span><span>Pause</span></button>`
        : "",
    canResume && activePendingAction === "resume"
      ? `<button disabled class="${baseClass} bot-action-btn--resume" style="opacity:0.7;cursor:not-allowed"><span class="animate-spin inline-block">↻</span><span>Resuming…</span></button>`
      : canResume
        ? `<button onclick="botAction('resume', '${bot.id}', event)" class="${baseClass} bot-action-btn--resume"><span>▶</span><span>${escapeHtml(resumeTitle)}</span></button>`
        : "",
    `<button onclick="editBotWithFeedback('${bot.id}', this)" class="${baseClass} bot-action-btn--edit"><span>✏</span><span>Edit</span></button>`,
    `<button onclick="showQuickEditWithFeedback('${bot.id}', this)" class="${baseClass} bot-action-btn--config"><span>⚙</span><span>Config</span></button>`,
    `<button onclick="botAction('delete', '${bot.id}', event)" class="${baseClass} bot-action-btn--delete"><span>🗑</span><span>Delete</span></button>`,
  ].filter(Boolean).join("");

  // Bottom row: primary action (Start or Stop) — bigger, full-width
  let primaryButton = "";
  if (bot.status !== "stopped") {
    primaryButton = activePendingAction === "stop"
      ? `<button disabled class="${primaryClass} bot-action-btn--stop" style="opacity:0.7;cursor:not-allowed"><span class="animate-spin inline-block">↻</span><span>Stopping…</span></button>`
      : `<button onclick="botAction('stop', '${bot.id}', event)" class="${primaryClass} bot-action-btn--stop"><span>⏹</span><span>Stop</span></button>`;
  } else if (stopGuardActive) {
    primaryButton = `<button disabled class="${primaryClass} bot-action-btn--disabled"><span>⏳</span><span>Wait ${stopGuardSec}s</span></button>`;
  } else if (canStart) {
    primaryButton = activePendingAction === "start"
      ? `<button disabled class="${primaryClass} bot-action-btn--start" style="opacity:0.7;cursor:not-allowed"><span class="animate-spin inline-block">↻</span><span>Starting…</span></button>`
      : `<button onclick="botAction('start', '${bot.id}', event)" class="${primaryClass} bot-action-btn--start"><span>▶</span><span>Start</span></button>`;
  }

  const utilityRow = `<div class="bot-action-group--utility">${utilityButtons}</div>`;
  const primaryRow = primaryButton ? `<div class="bot-action-primary">${primaryButton}</div>` : "";
  return `<div class="bot-action-stack">${utilityRow}${primaryRow}</div>`;
}

// Active Bots filter stability helpers keep runtime readiness updates from rebuilding
// or temporarily ejecting rows from the current filtered view on every poll.
function getActiveBotReadinessStatus(bot) {
  const setup = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  if (hasAnalyticalSetupReady(bot) && execution.marginLimited) return "margin_warning";
  if (isTriggerReadyStatus(setup.status) && execution.blocked) return "blocked";
  const status = String(setup.status || "").trim().toLowerCase();
  // If status is empty during stale snapshot, demote to watch — NEVER preserve old ready/trigger_ready
  if (!status && bot.runtime_snapshot_stale) return "watch";
  return status;
}

function getActiveBotReadinessReason(bot) {
  const setup = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  if (hasAnalyticalSetupReady(bot) && execution.marginLimited) {
    return String(execution.reason || "insufficient_margin").trim().toLowerCase();
  }
  if (isTriggerReadyStatus(setup.status) && execution.blocked) {
    return String(execution.reason || "blocked").trim().toLowerCase();
  }
  return String(setup.reason || "").trim().toLowerCase();
}

function getBaseActiveBotReadyCategory(bot) {
  const status = getActiveBotReadinessStatus(bot);
  if (isTriggerReadyStatus(status)) return "ready";
  if (status === "margin_warning") return "watch";
  if (ACTIVE_BOT_WATCH_STATUSES.has(status)) return "watch";
  if (status === "blocked") return "blocked";
  if (ACTIVE_BOT_LIMITED_STATUSES.has(status)) return "limited";
  return "other";
}

function getEffectiveActiveBotReadyCategory(bot, nowMs = Date.now()) {
  const botId = String(bot?.id || "").trim();
  const baseCategory = getBaseActiveBotReadyCategory(bot);
  if (!botId) return baseCategory;

  if (baseCategory === "watch") {
    activeBotWatchGraceState.set(botId, nowMs + ACTIVE_BOT_WATCH_STALE_GRACE_MS);
    return "watch";
  }

  if (baseCategory === "limited") {
    const reason = getActiveBotReadinessReason(bot);
    const graceUntil = Number(activeBotWatchGraceState.get(botId) || 0);
    if (ACTIVE_BOT_WATCH_GRACE_REASONS.has(reason) && graceUntil > nowMs) {
      return "watch";
    }
  }

  activeBotWatchGraceState.delete(botId);
  return baseCategory;
}

function pruneActiveBotFrontendState(bots) {
  const activeIds = new Set(
    (bots || [])
      .map((bot) => String(bot?.id || "").trim())
      .filter(Boolean)
  );

  activeBotRenderedIds = activeBotRenderedIds.filter((botId) => activeIds.has(botId));
  for (const botId of Array.from(activeBotWatchGraceState.keys())) {
    if (!activeIds.has(botId)) {
      activeBotWatchGraceState.delete(botId);
    }
  }
  for (const botId of Array.from(activeBotCategoryChangeState.keys())) {
    if (!activeIds.has(botId)) {
      activeBotCategoryChangeState.delete(botId);
    }
  }
  // Prune ready board grace and prev ready IDs for deleted bots
  for (const botId of Array.from(_readyBoardGrace.keys())) {
    if (!activeIds.has(botId)) _readyBoardGrace.delete(botId);
  }
  _prevReadyBotIds = new Set([..._prevReadyBotIds].filter(id => activeIds.has(id)));
}


function trackActiveBotCategoryTransitions(bots, nowMs = Date.now()) {
  for (const bot of bots || []) {
    const botId = String(bot?.id || "").trim();
    const readyCat = String(bot?._active_bots_ready_cat || getBaseActiveBotReadyCategory(bot)).trim().toLowerCase();
    const displayBucket = getActiveBotDisplayBucket(bot?.status, readyCat);
    const previous = botId ? activeBotCategoryChangeState.get(botId) : null;
    let changedAt = Number(previous?.changedAt || 0);

    if (previous && previous.displayBucket !== displayBucket) {
      changedAt = nowMs;
    }

    if (botId) {
      activeBotCategoryChangeState.set(botId, {
        displayBucket,
        changedAt,
      });
    }

    bot._active_bots_category_changed_at = changedAt;
  }
}


function hasSameActiveBotStructure(bots) {
  const nextIds = getActiveBotRenderIds(bots);
  if (nextIds.length !== activeBotRenderedIds.length) return false;
  return nextIds.every((botId, index) => botId === activeBotRenderedIds[index]);
}

function rememberActiveBotStructure(bots) {
  activeBotRenderedIds = getActiveBotRenderIds(bots);
}

function doesActiveBotMatchFilterState(status, readyCat, filterName, botId) {
  const normalizedFilter = String(filterName || "all").trim().toLowerCase();
  if (normalizedFilter === "all") return true;

  const normalizedStatus = String(status || "").trim().toLowerCase();
  if (normalizedFilter === "running") return normalizedStatus === "running" || normalizedStatus === "paused";

  if (normalizedFilter === "recent_stopped") {
    return normalizedStatus === "stopped" && _isRecentlyStopped(botId);
  }

  if (normalizedFilter === "trigger") {
    const bot = (window._lastBots || []).find(b => b.id === botId);
    if (!bot) return false;
    return isTriggerReadyStatus(getSetupReadiness(bot).status);
  }

  if (normalizedFilter === "armed") {
    const bot = (window._lastBots || []).find(b => b.id === botId);
    if (!bot) return false;
    const setup = getSetupReadiness(bot);
    return isArmedStatus(setup.status);
  }

  return String(readyCat || "other").trim().toLowerCase() === normalizedFilter;
}

function _isRecentlyStopped(botId) {
  if (!botId) return false;
  const bot = (window._lastBots || []).find(b => b.id === botId);
  if (!bot || bot.status !== "stopped") return false;
  // Must have actually run before (last_run_at set by runner)
  const lastRunAt = bot.last_run_at;
  if (!lastRunAt) return false;
  const ageMs = Date.now() - Date.parse(lastRunAt);
  return ageMs < 24 * 60 * 60 * 1000; // Last 24 hours
}




function setElementHtmlIfChanged(element, html) {
  if (!element) return false;
  const nextHtml = String(html || "");
  if (element.innerHTML === nextHtml) return false;
  element.innerHTML = nextHtml;
  return true;
}

function setElementTextIfChanged(element, text) {
  if (!element) return false;
  const nextText = String(text || "");
  if (element.textContent === nextText) return false;
  element.textContent = nextText;
  return true;
}

function setElementClassNameIfChanged(element, className) {
  if (!element) return false;
  const nextClassName = String(className || "");
  if (element.className === nextClassName) return false;
  element.className = nextClassName;
  return true;
}

function setElementHiddenState(element, hidden) {
  if (!element) return false;
  const nextHidden = Boolean(hidden);
  if (Boolean(element.hidden) === nextHidden) return false;
  element.hidden = nextHidden;
  return true;
}

function setElementAttributeIfChanged(element, name, value) {
  if (!element) return false;
  const nextValue = String(value || "");
  if (typeof element.getAttribute === "function" && element.getAttribute(name) === nextValue) return false;
  if (typeof element.setAttribute === "function") {
    element.setAttribute(name, nextValue);
    return true;
  }
  if (element[name] === nextValue) return false;
  element[name] = nextValue;
  return true;
}


function getActiveBotRowField(row, fieldName) {
  if (!row || typeof row.querySelector !== "function") return null;
  return row.querySelector(`[data-bot-field="${fieldName}"]`);
}



function _scoreTint(bot) {
  const setup = getSetupReadiness(bot);
  const score = setup.score;
  if (score === null || score === undefined || !Number.isFinite(score)) return "";
  if (score >= 72) return " bot-ops-kpi--strong-score";
  if (score >= 60) return " bot-ops-kpi--good-score";
  if (score >= 50) return " bot-ops-kpi--caution-score";
  return " bot-ops-kpi--poor-score";
}

function getActiveBotRowViewModel(bot) {
  const pnl = formatPnL(bot.total_pnl || 0);
  const realized = formatPnL(bot.realized_pnl || 0);
  const unrealized = formatPnL(bot.unrealized_pnl || 0);
  const session = formatPnL(bot.session_total_pnl || 0);
  const perHour = bot.session_profit_per_hour != null ? formatPnL(bot.session_profit_per_hour || 0) : null;
  const netTint = (bot.total_pnl || 0) > 0 ? " bot-ops-kpi--profit" : (bot.total_pnl || 0) < 0 ? " bot-ops-kpi--loss" : "";
  const sessTint = (bot.session_total_pnl || 0) > 0 ? " bot-ops-kpi--profit" : (bot.session_total_pnl || 0) < 0 ? " bot-ops-kpi--loss" : "";
  const topAlert = getPrimaryBotAlert(bot);
  const profile = bot.profile || "normal";
  const autoDirection = bot.auto_direction || false;
  const rangeMode = bot.range_mode || "fixed";
  const tpPct = bot.tp_pct;
  const pnlPct = bot.pnl_pct;
  const tpStr = (typeof tpPct === "number" && !isNaN(tpPct) && tpPct > 0 && tpPct < 1)
    ? `${(tpPct * 100).toFixed(1)}%`
    : (bot.mode === "scalp_pnl" ? "Dynamic" : "-");
  const pnlPctStr = (typeof pnlPct === "number" && !isNaN(pnlPct))
    ? `${(pnlPct * 100).toFixed(2)}%`
    : "0.00%";
  const runtimeText = formatRuntimeHours(bot.runtime_hours);
  const botIdShort = escapeHtml(bot.id ? bot.id.slice(0, 8) : "-");
  const investmentText = `$${formatNumber(bot.investment || 0, 0)}`;
  const leverageText = `${formatNumber(bot.leverage || 0, 0)}x`;
  const gridsText = `${getConfiguredGridCount(bot)}g`;
  const autoPilotSummary = bot.auto_pilot
    ? truncateText([
      bot.auto_pilot_pick_status ? humanizeReason(bot.auto_pilot_pick_status) : "",
      bot.auto_pilot_top_candidate_symbol ? `Top ${bot.auto_pilot_top_candidate_symbol}` : "",
      Number.isFinite(Number(bot.auto_pilot_top_candidate_score))
        ? `${Number(bot.auto_pilot_top_candidate_score).toFixed(1)}`
        : "",
    ].filter(Boolean).join(" • "), 86)
    : "";
  const statusHtml = pendingBotActions[bot.id]
    ? `<span class="px-2 py-0.5 bg-amber-500/20 text-amber-400 text-[10px] font-medium rounded-full animate-pulse">${escapeHtml(humanizeReason(pendingBotActions[bot.id]))}</span>`
    : statusBadge(bot.status);
  const rowClass = bot.auto_pilot
    ? `bot-ops-row auto-pilot-row${bot.status === "running" ? " auto-pilot-row-live" : ""}`
    : "bot-ops-row";
  const stateChips = [
    ...buildBotStateChips(bot),
    trailingSlBadge(bot),
    upnlSlBadges(bot),
    aiGuardBadge(bot),
  ].filter(Boolean).join("");
  const alternativeModeHtml = renderAlternativeModeSummary(bot);
  const readyCat = String(bot._active_bots_ready_cat || getBaseActiveBotReadyCategory(bot)).trim().toLowerCase();
  const symbolText = String(bot.symbol || "Auto-Pilot");
  const alertText = String(topAlert || autoPilotSummary || "");

  return {
    rowClass,
    rowDisplay: getActiveBotRowDisplayValue(bot),
    rowDataset: {
      symbol: symbolText,
      autoPilot: bot.auto_pilot ? "true" : "false",
      status: String(bot.status || ""),
      readyCat,
    },
    symbolText,
    symbolTitle: symbolText,
    symbolOnclick: `openBotDetailModal('${bot.id}')`,
    symbolScanHtml: bot.symbol ? `<button type="button" onclick="scanSymbol('${bot.symbol}')" title="Scan this coin in Neutral Scanner" class="p-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-200 hover:text-white transition">🔍</button>` : "",
    autoPilotBadgeHtml: bot.auto_pilot ? autoPilotStatusBadge(bot) : "",
    profileHtml: profileBadge(profile, autoDirection),
    badgesHtml: [
      modeBadge(bot.mode, bot.scalp_analysis, bot),
      rangeModeBadge(rangeMode, bot.last_range_width_pct),
      statusHtml,
      runtimeStartLifecycleBadge(bot),
      renderLiveExecutionIntentBadge(bot),
      entryReadinessBadge(bot),
      exchangeTruthBadge(bot),
      readinessFreshnessBadge(bot),
    ].filter(Boolean).join(""),
    metaStripHtml: (() => {
      const ppMode = String(bot.profit_protection_mode || "off").toLowerCase();
      const ppDecision = String(bot.profit_protection_decision || "wait").toLowerCase();
      const ppArmed = Boolean(bot.profit_protection_armed);
      const ppLockCount = Number(bot.profit_lock_executed_count || 0);
      let ppText = "", ppClass = "text-slate-500";
      if (ppMode === "off" || !ppMode) { ppText = ""; }
      else if (ppDecision === "exit_now") { ppText = "PP EXIT"; ppClass = "text-rose-400 font-semibold"; }
      else if (ppDecision === "take_partial") { ppText = "PP partial"; ppClass = "text-amber-400"; }
      else if (ppDecision === "watch_closely") { ppText = "PP watch"; ppClass = "text-cyan-300"; }
      else if (ppArmed) { ppText = "PP armed"; ppClass = "text-emerald-400"; }
      else { ppText = "PP wait"; ppClass = "text-slate-400"; }
      if (ppLockCount > 0) ppText += ppText ? ` x${ppLockCount}` : `PL x${ppLockCount}`;
      const ppSpan = ppText ? `<span class="${ppClass}">${ppText}</span>` : "";
      return `
        <span>${botIdShort}</span>
        <span>${escapeHtml(gridsText)}</span>
        <span class="${(bot.open_order_count || 0) > 0 ? 'text-cyan-300' : 'text-slate-500'}">${bot.open_order_count || 0} orders</span>
        ${ppSpan}
        <span>${escapeHtml(runtimeText)}</span>
      `;
    })(),
    metricsHtml: `
      <div class="bot-ops-kpi bot-ops-kpi--size">
        <div class="bot-ops-kpi__label">Size</div>
        <div class="bot-ops-kpi__value">${escapeHtml(investmentText)}</div>
        <div class="bot-ops-kpi__hint">${escapeHtml(leverageText)}</div>
      </div>
      <div class="bot-ops-kpi bot-ops-kpi--net${netTint}">
        <div class="bot-ops-kpi__label">Net</div>
        <div class="bot-ops-kpi__value ${pnl.class}">${pnl.text}</div>
        <div class="bot-ops-kpi__hint">${realized.text}/${unrealized.text}</div>
      </div>
      <div class="bot-ops-kpi${sessTint}">
        <div class="bot-ops-kpi__label">Sess</div>
        <div class="bot-ops-kpi__value ${session.class}">${session.text}</div>
        <div class="bot-ops-kpi__hint">${perHour ? `${perHour.text}/h` : runtimeText}</div>
      </div>
      <div class="bot-ops-kpi bot-ops-kpi--score${_scoreTint(bot)}">
        <div class="bot-ops-kpi__label">Score</div>
        <div class="bot-ops-kpi__value">${_scoreDisplay(bot)}</div>
        <div class="bot-ops-kpi__hint">${_bandDisplay(bot)}</div>
      </div>
    `,
    actionsHtml: buildBotActionButtons(bot, false),
    hasAlert: Boolean(alertText),
    alertClass: `bot-ops-alert${bot.status === "risk_stopped" ? " bot-ops-alert--danger" : ""}`,
    alertText,
    hasFooter: Boolean(stateChips || alternativeModeHtml),
    footerHtml: `${alternativeModeHtml}${stateChips ? `<div class="bot-ops-row__statechips">${stateChips}</div>` : ""}`,
  };
}

function buildActiveBotRowMarkup(bot) {
  const view = getActiveBotRowViewModel(bot);
  const readyCat = String(view.rowDataset.readyCat || "other").trim().toLowerCase();

  return `
    <article class="${view.rowClass}" id="bot-row-${bot.id}" data-symbol="${escapeHtml(view.rowDataset.symbol)}" data-bot-id="${escapeHtml(bot.id)}" data-auto-pilot="${view.rowDataset.autoPilot}" data-status="${escapeHtml(view.rowDataset.status)}" data-ready-cat="${readyCat}"${getActiveBotRowDisplayStyle(bot)}>
      <div class="bot-ops-row__layout">
        <div class="bot-ops-row__primary">
          <div class="bot-ops-row__headline">
            <button data-bot-field="symbol-button" onclick="${view.symbolOnclick}" class="text-left bot-ops-row__symbol" title="${escapeHtml(view.symbolTitle)}">
              ${escapeHtml(view.symbolText)}
            </button>
            <span data-bot-field="symbol-scan">${view.symbolScanHtml}</span>
            <span data-bot-field="auto-pilot-status">${view.autoPilotBadgeHtml}</span>
            <span data-bot-field="profile-badge">${view.profileHtml}</span>
          </div>
          <div class="bot-ops-row__badges" data-bot-field="badges">
            ${view.badgesHtml}
          </div>
          <div class="bot-ops-row__meta-strip" data-bot-field="meta-strip">
            ${view.metaStripHtml}
          </div>
        </div>

        <div class="bot-ops-row__summary">
          <div class="bot-ops-row__metrics" data-bot-field="metrics">
            ${view.metricsHtml}
          </div>
        </div>

        <div class="bot-ops-row__actions">
          <div class="bot-action-group" data-bot-field="actions">
            ${view.actionsHtml}
          </div>
        </div>
      </div>

      <div class="${view.alertClass}" data-bot-field="alert"${view.hasAlert ? "" : " hidden"}>
        ${escapeHtml(view.alertText)}
      </div>

      <div class="bot-ops-row__footer" data-bot-field="footer"${view.hasFooter ? "" : " hidden"}>${view.footerHtml}</div>
    </article>
  `;
}

function patchBotRowFields(currentRow, bot) {
  if (!currentRow || !bot) return false;

  const view = getActiveBotRowViewModel(bot);
  setElementClassNameIfChanged(currentRow, view.rowClass);
  setElementDisplayIfChanged(currentRow, view.rowDisplay);

  if (currentRow.dataset) {
    if (currentRow.dataset.symbol !== view.rowDataset.symbol) currentRow.dataset.symbol = view.rowDataset.symbol;
    if (currentRow.dataset.autoPilot !== view.rowDataset.autoPilot) currentRow.dataset.autoPilot = view.rowDataset.autoPilot;
    if (currentRow.dataset.status !== view.rowDataset.status) currentRow.dataset.status = view.rowDataset.status;
    if (currentRow.dataset.readyCat !== view.rowDataset.readyCat) currentRow.dataset.readyCat = view.rowDataset.readyCat;
  }

  const symbolButton = getActiveBotRowField(currentRow, "symbol-button");
  setElementTextIfChanged(symbolButton, view.symbolText);
  if (symbolButton) {
    if (symbolButton.title !== view.symbolTitle) symbolButton.title = view.symbolTitle;
    setElementAttributeIfChanged(symbolButton, "onclick", view.symbolOnclick);
  }

  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "symbol-scan"), view.symbolScanHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "auto-pilot-status"), view.autoPilotBadgeHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "profile-badge"), view.profileHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "badges"), view.badgesHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "meta-strip"), view.metaStripHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "metrics"), view.metricsHtml);
  setElementHtmlIfChanged(getActiveBotRowField(currentRow, "actions"), view.actionsHtml);

  const alertEl = getActiveBotRowField(currentRow, "alert");
  setElementClassNameIfChanged(alertEl, view.alertClass);
  setElementHiddenState(alertEl, !view.hasAlert);
  setElementTextIfChanged(alertEl, view.alertText);

  const footerEl = getActiveBotRowField(currentRow, "footer");
  setElementHiddenState(footerEl, !view.hasFooter);
  setElementHtmlIfChanged(footerEl, view.footerHtml);
  return true;
}

function patchActiveBotRowsInPlace(bots) {
  const container = $("active-bots-list");
  if (!container || !bots.length || !hasSameActiveBotStructure(bots)) return false;

  for (const bot of bots) {
    const currentRow = document.getElementById(`bot-row-${bot.id}`);
    if (!currentRow) return false;
    if (!patchBotRowFields(currentRow, bot)) return false;
  }

  rememberActiveBotStructure(bots);
  return true;
}






function updateActivityFeedHighlight() {
  const latest = dashboardFeedState.latestEvent;
  const textEl = $("activity-feed-highlight-text");
  const timeEl = $("activity-feed-highlight-time");
  const watchEl = $("watch-last-event");
  if (!textEl || !timeEl) return;

  if (!latest) {
    textEl.textContent = "Waiting for live events…";
    timeEl.textContent = "Feed idle";
    if (watchEl) {
      watchEl.textContent = "Waiting for the first live event.";
    }
    return;
  }

  textEl.textContent = latest.message;
  timeEl.textContent = `${formatFeedClock(latest.ts)} • ${formatFeedTimeAgo(latest.ts)}`;
  if (watchEl) {
    watchEl.textContent = latest.message;
  }
}

function maybeSendBrowserNotification(item) {
  const prefs = ensureDashboardUiPrefs();
  if (!prefs.browserAlerts || !("Notification" in window) || Notification.permission !== "granted") {
    return;
  }
  if (document.visibilityState === "visible" && item.tone !== "danger") {
    return;
  }
  try {
    const notification = new Notification(`Opus Trader · ${item.label}`, {
      body: item.message,
      tag: item.key,
      renotify: item.tone === "danger",
      silent: false,
    });
    window.setTimeout(() => notification.close(), 6000);
  } catch (error) {
    console.debug("Browser notification failed:", error);
  }
}





function updateOperatorWatch() {
  const bots = window._lastBots || [];
  const summary = window._lastSummaryData || {};
  const overviewEl = $("operator-watch-overview");
  const chipsEl = $("operator-watch-chips");
  const autoPilotEl = $("watch-autopilot-summary");
  const guardEl = $("watch-guard-summary");
  const alertBanner = $("critical-alert-banner");
  const alertLabelEl = $("critical-alert-label");
  const alertTextEl = $("critical-alert-text");

  if (!overviewEl || !chipsEl || !autoPilotEl || !guardEl) return;

  const runningBots = bots.filter((bot) => ["running", "recovering"].includes(bot.status));
  const autoPilotBots = bots.filter((bot) => bot.auto_pilot);
  const blockedBots = bots.filter((bot) => !!bot.auto_pilot_block_reason || bot.entry_gate_blocked);
  const hardGuardBots = bots.filter((bot) => bot.status === "risk_stopped" || !!bot.last_error);
  const guardBots = bots.filter((bot) =>
    bot.status === "risk_stopped"
    || !!bot.last_error
    || !!bot.auto_pilot_block_reason
    || bot.entry_gate_blocked
    || bot.upnl_stoploss_active
    || isStallOverlaySignal(bot)
  );
  const stallBots = bots.filter((bot) => isStallOverlaySignal(bot));
  const todayNet = Number(summary?.today_pnl?.net || 0);

  overviewEl.textContent = guardBots.length
    ? `${runningBots.length} live • ${guardBots.length} alert${guardBots.length === 1 ? "" : "s"} • Today ${formatPnL(todayNet).text}`
    : `${runningBots.length} live • Clear • Today ${formatPnL(todayNet).text}`;

  const chips = [buildMetricChip(liveFeedConnected ? "Feed Live" : "Feed Fallback", liveFeedConnected ? "emerald" : "amber")];

  if (guardBots.length) {
    chips.push(buildMetricChip(`Alerts ${guardBots.length}`, hardGuardBots.length ? "rose" : "amber"));
  } else {
    chips.push(buildMetricChip("Clear", "emerald"));
  }
  if (autoPilotBots.length) {
    chips.push(buildMetricChip(`Pilot ${autoPilotBots.length}`, "cyan"));
  }
  if (blockedBots.length) {
    chips.push(buildMetricChip(`Blocked ${blockedBots.length}`, "amber"));
  } else if (stallBots.length) {
    chips.push(buildMetricChip(`Stall ${stallBots.length}`, "amber"));
  }

  chipsEl.innerHTML = chips.join("");

  const focusBot = autoPilotBots.find((bot) => ["running", "recovering"].includes(bot.status)) || autoPilotBots[0];
  if (focusBot) {
    const focusParts = [];
    if (focusBot.auto_pilot_pick_status) {
      focusParts.push(humanizeReason(focusBot.auto_pilot_pick_status));
    }
    if (focusBot.auto_pilot_top_candidate_symbol) {
      const score = Number(focusBot.auto_pilot_top_candidate_score);
      focusParts.push(`Top ${focusBot.auto_pilot_top_candidate_symbol}${Number.isFinite(score) ? ` ${score.toFixed(1)}` : ""}`);
    }
    if (focusBot.auto_pilot_candidate_source) {
      focusParts.push(String(focusBot.auto_pilot_candidate_source).toUpperCase());
    }
    autoPilotEl.textContent = focusParts.length
      ? `${focusBot.symbol}: ${focusParts.join(" • ")}`
      : `${focusBot.symbol}: Auto Pilot online`;
  } else {
    autoPilotEl.textContent = "No Auto Pilot bot active.";
  }

  const criticalGuardBot = bots.find((bot) => bot.status === "risk_stopped")
    || bots.find((bot) => !!bot.last_error)
    || bots.find((bot) => !!bot.auto_pilot_block_reason)
    || bots.find((bot) => bot.entry_gate_blocked)
    || bots.find((bot) => bot.upnl_stoploss_active)
    || bots.find((bot) => isStallOverlaySignal(bot));

  if (criticalGuardBot) {
    guardEl.textContent = getPrimaryBotAlert(criticalGuardBot) || `${criticalGuardBot.symbol}: monitoring guards`;
    if (alertBanner && alertLabelEl && alertTextEl) {
      const isDanger = criticalGuardBot.status === "risk_stopped" || Boolean(criticalGuardBot.last_error);
      alertBanner.className = isDanger
        ? "mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3"
        : "mt-4 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3";
      alertLabelEl.className = isDanger
        ? "text-[10px] font-semibold uppercase tracking-[0.22em] text-red-300"
        : "text-[10px] font-semibold uppercase tracking-[0.22em] text-amber-300";
      alertLabelEl.textContent = isDanger ? "Critical" : "Blocked";
      alertTextEl.textContent = getPrimaryBotAlert(criticalGuardBot) || `${criticalGuardBot.symbol}: monitoring guards`;
    }
  } else {
    guardEl.textContent = "No active guard alerts.";
    if (alertBanner) {
      alertBanner.classList.add("hidden");
    }
  }

  updateActivityFeedHighlight();
  updateStreakBadge();
}

function appendActivityEvent(event) {
  const ts = Number(event?.ts || Date.now());
  const normalized = {
    key: String(event?.key || `${event?.category || "info"}:${event?.symbol || ""}:${event?.message || ""}`).trim(),
    ts,
    category: String(event?.category || "info"),
    tone: String(event?.tone || "info"),
    icon: String(event?.icon || "•"),
    label: humanizeReason(event?.category || "info"),
    message: String(event?.message || "").trim(),
    symbol: String(event?.symbol || "").trim(),
    meta: String(event?.meta || "").trim(),
    toast: Boolean(event?.toast),
    notify: Boolean(event?.notify),
    confetti: Boolean(event?.confetti),
    bannerText: String(event?.bannerText || "").trim(),
  };

  if (!normalized.message) {
    return;
  }

  const dedupeWindowMs = Number(event?.dedupeWindowMs || FEED_DEDUPE_WINDOW_MS);
  const seenAt = dashboardFeedState.recentEventKeys.get(normalized.key);
  if (seenAt && (ts - seenAt) < dedupeWindowMs) {
    return;
  }

  dashboardFeedState.recentEventKeys.set(normalized.key, ts);
  for (const [key, value] of [...dashboardFeedState.recentEventKeys.entries()]) {
    if ((ts - value) > FEED_DEDUPE_WINDOW_MS * 4) {
      dashboardFeedState.recentEventKeys.delete(key);
    }
  }

  dashboardFeedState.events.unshift(normalized);
  dashboardFeedState.events = dashboardFeedState.events.slice(0, ACTIVITY_FEED_LIMIT);
  dashboardFeedState.latestEvent = normalized;

  renderActivityFeed();
  updateOperatorWatch();

  if (normalized.toast) {
    const toastType = normalized.tone === "danger" || normalized.tone === "loss"
      ? "error"
      : normalized.tone === "warning"
        ? "warning"
        : normalized.tone === "profit"
          ? "success"
          : "info";
    showToast(normalized.message, toastType);
  }

  if (normalized.notify) {
    maybeSendBrowserNotification(normalized);
  }

  if (normalized.bannerText) {
    showMilestoneBanner(normalized.bannerText, normalized.tone);
  }

  if (normalized.confetti) {
    maybeTriggerConfetti();
  }
}

function computeCurrentStreaks(logs) {
  const ordered = (logs || [])
    .slice()
    .sort((a, b) => new Date(b.time || 0).getTime() - new Date(a.time || 0).getTime());

  let winStreak = 0;
  let lossStreak = 0;

  for (const log of ordered) {
    const pnl = Number(log.realized_pnl || 0);
    if (pnl > 0) {
      if (lossStreak > 0) break;
      winStreak += 1;
    } else if (pnl < 0) {
      if (winStreak > 0) break;
      lossStreak += 1;
    }
  }

  dashboardFeedState.winStreak = winStreak;
  dashboardFeedState.lossStreak = lossStreak;
  updateStreakBadge();
}


function inferPnlEventContext(log) {
  const attribution = String(log?.attribution_source || "").toLowerCase();
  const orderLinkId = String(log?.order_link_id || "").toLowerCase();

  if (orderLinkId.startsWith("nlp:")) return "risk";
  if (orderLinkId.startsWith("ambg:")) return "emergency";
  if (attribution.includes("manual")) return "manual";
  if (attribution.includes("ambiguous")) return "emergency";
  return "realized";
}

function registerNewPnlEvents(logs, today) {
  const seenIds = new Set(previousValues.pnlLogIds || []);
  computeCurrentStreaks(logs);

  if (!dashboardFeedState.hasPnlBaseline) {
    dashboardFeedState.hasPnlBaseline = true;
    dashboardFeedState.lastTodayNet = Number(today?.net || 0);
    updateOperatorWatch();
    return;
  }

  const newLogs = logs.filter((log) => !seenIds.has(log.id));
  dashboardFeedState.lastPnlEventIds = new Set(
    newLogs.map((log) => log.id || log.exec_id || `${log.time}:${log.symbol}`)
  );

  newLogs
    .slice()
    .sort((a, b) => new Date(a.time || 0).getTime() - new Date(b.time || 0).getTime())
    .forEach((log) => {
      const pnlValue = Number(log.realized_pnl || 0);
      if (!pnlValue) return;

      const context = inferPnlEventContext(log);
      const prefix = context === "risk"
        ? "Risk stop closed"
        : context === "emergency"
          ? "Emergency stop flattened"
          : context === "manual"
            ? "Manual close"
            : pnlValue > 0
              ? "Realized profit"
              : "Realized loss";

      appendActivityEvent({
        key: `pnl:${log.id || log.exec_id || `${log.time}:${log.symbol}`}`,
        category: pnlValue >= 0 ? "profit" : "loss",
        tone: pnlValue >= 0 ? "profit" : "loss",
        icon: pnlValue >= 0 ? "💸" : "🧯",
        symbol: log.symbol,
        meta: humanizeReason(log.bot_mode || context),
        message: `${prefix} on ${log.symbol} (${formatPnL(pnlValue).text})`,
        toast: isMeaningfulPnl(pnlValue),
        notify: isMeaningfulPnl(pnlValue),
        confetti: pnlValue >= 3,
      });

      if (pnlValue > 0 && isMeaningfulPnl(pnlValue)) {
        maybeTriggerProfitRain(pnlValue);
      }
    });
  maybeEmitDailyMilestone(today?.net || 0);
}

function detectBotRuntimeEvents(bots) {
  const nextSnapshot = {};
  const readyTradeCount = (bots || []).filter((bot) => isActionableReadyBot(bot)).length;
  bots.forEach((bot) => {
    nextSnapshot[bot.id] = JSON.parse(JSON.stringify(bot));
  });

  if (!dashboardFeedState.hasBotBaseline) {
    dashboardFeedState.botsById = nextSnapshot;
    dashboardFeedState.hasBotBaseline = true;
    updateOperatorWatch();
    return;
  }

  for (const bot of bots) {
    const prev = dashboardFeedState.botsById[bot.id];
    if (!prev) continue;

    if (
      bot.auto_pilot
      && isTradeableBotSymbol(bot.symbol)
      && isTradeableBotSymbol(prev.symbol)
      && prev.symbol !== bot.symbol
    ) {
      appendActivityEvent({
        key: `rotation:${bot.id}:${prev.symbol}:${bot.symbol}`,
        category: "rotation",
        tone: "autopilot",
        icon: "🧭",
        symbol: bot.symbol,
        meta: Number.isFinite(Number(bot.auto_pilot_last_pick_score)) ? `score ${Number(bot.auto_pilot_last_pick_score).toFixed(1)}` : "Auto Pilot",
        message: `Smart Rotation switched from ${prev.symbol} to ${bot.symbol}`,
        toast: true,
        notify: true,
      });
    } else if (
      bot.auto_pilot
      && bot.auto_pilot_last_pick_at
      && bot.auto_pilot_last_pick_at !== prev.auto_pilot_last_pick_at
      && isTradeableBotSymbol(bot.symbol)
    ) {
      appendActivityEvent({
        key: `pick:${bot.id}:${bot.auto_pilot_last_pick_at}`,
        category: "autopilot",
        tone: "autopilot",
        icon: "🤖",
        symbol: bot.symbol,
        meta: Number.isFinite(Number(bot.auto_pilot_last_pick_score)) ? `score ${Number(bot.auto_pilot_last_pick_score).toFixed(1)}` : "",
        message: `Auto Pilot picked ${bot.symbol}${bot.mode ? ` (${humanizeReason(bot.mode)})` : ""}`,
        toast: true,
        notify: true,
      });
    }

    if (bot.auto_pilot_block_reason && bot.auto_pilot_block_reason !== prev.auto_pilot_block_reason) {
      appendActivityEvent({
        key: `block:${bot.id}:${bot.auto_pilot_block_reason}`,
        category: "guard",
        tone: "warning",
        icon: "⛔",
        symbol: bot.symbol,
        meta: bot.auto_pilot_top_candidate_symbol || "",
        message: `Pick blocked by ${humanizeReason(bot.auto_pilot_block_reason)}`,
        toast: true,
        notify: true,
      });
    }

    if (
      bot.auto_pilot_candidate_source
      && bot.auto_pilot_candidate_source !== prev.auto_pilot_candidate_source
    ) {
      appendActivityEvent({
        key: `candidate-source:${bot.id}:${bot.auto_pilot_candidate_source}`,
        category: "cache",
        tone: "info",
        icon: "🗂️",
        symbol: bot.symbol,
        meta: bot.auto_pilot_candidate_source.toUpperCase(),
        message: `Candidate source switched to ${String(bot.auto_pilot_candidate_source).toUpperCase()}`,
        dedupeWindowMs: 180000,
      });
    }

    if (
      bot.auto_pilot_top_candidate_symbol
      && (
        bot.auto_pilot_top_candidate_symbol !== prev.auto_pilot_top_candidate_symbol
        || Number(bot.auto_pilot_top_candidate_score || 0) !== Number(prev.auto_pilot_top_candidate_score || 0)
      )
      && bot.auto_pilot_top_candidate_symbol !== bot.symbol
    ) {
      const score = Number(bot.auto_pilot_top_candidate_score);
      appendActivityEvent({
        key: `top-candidate:${bot.id}:${bot.auto_pilot_top_candidate_symbol}:${score}`,
        category: "autopilot",
        tone: "info",
        icon: "🎯",
        symbol: bot.auto_pilot_top_candidate_symbol,
        meta: bot.auto_pilot_top_candidate_eligibility || "",
        message: `Top candidate now ${bot.auto_pilot_top_candidate_symbol}${Number.isFinite(score) ? ` (${score.toFixed(1)})` : ""}`,
        dedupeWindowMs: 180000,
      });
    }

    const prevReadyStatus = isActionableReadyBot(prev) ? "ready" : "not_ready";
    const nextReadyStatus = isActionableReadyBot(bot) ? "ready" : "not_ready";
    if (
      nextReadyStatus === "ready"
      && prevReadyStatus !== "ready"
      && isTradeableBotSymbol(bot.symbol)
    ) {
      const setup = getSetupReadiness(bot);
      const score = pickFiniteReadinessScore(setup.score);
      const direction = normalizeMarketStateHint(setup.direction || bot.mode);
      appendActivityEvent({
        key: `entry-ready:${bot.id}:${setup.updatedAt || Date.now()}`,
        category: "ready",
        tone: "profit",
        icon: "✅",
        symbol: bot.symbol,
        meta: direction === "neutral"
          ? humanizeReason(bot.mode || "ready")
          : humanizeReason(direction),
        message: `${bot.symbol} is actionable${Number.isFinite(score) ? ` (${score.toFixed(0)})` : ""}`,
        toast: true,
        notify: true,
        dedupeWindowMs: 300000,  // 5 minutes — prevent repeated alerts for same coin
      });
      playReadyAlertSound();
      triggerReadyTitleAlert(readyTradeCount || 1);
    }

    if (
      bot.direction_change_guard_last_event_at
      && bot.direction_change_guard_last_event_at !== prev.direction_change_guard_last_event_at
      && isTradeableBotSymbol(bot.symbol)
    ) {
      const action = String(bot.direction_change_guard_last_action || "").trim().toLowerCase();
      const prevState = humanizeReason(bot.direction_change_guard_prev_state || "unknown");
      const nextState = humanizeReason(bot.direction_change_guard_state || "unknown");
      const pnlValue = Number(bot.direction_change_guard_last_unrealized_pnl || 0);
      const tone = action === "reduce_only" ? "warning" : "danger";
      const icon = action === "reduce_only" ? "🧯" : "🛑";
      const actionText = action === "reduce_only"
        ? "moved to reduce-only"
        : action === "stopped_after_close"
          ? "stopped after closing the position"
          : action === "stopped_flat"
            ? "stopped after the reduce-only unwind finished"
            : "stopped";
      appendActivityEvent({
        key: `direction-change:${bot.id}:${bot.direction_change_guard_last_event_at}`,
        category: "direction change",
        tone,
        icon,
        symbol: bot.symbol,
        meta: `${prevState} → ${nextState}`,
        message: `${bot.symbol}: ${actionText}${Number.isFinite(pnlValue) ? ` (${formatPnL(pnlValue).text})` : ""}`,
        toast: true,
        notify: true,
        dedupeWindowMs: 180000,
      });
    }

    if (bot.status !== prev.status) {
      if (bot.status === "risk_stopped") {
        appendActivityEvent({
          key: `status:${bot.id}:risk_stopped:${bot.updated_at || Date.now()}`,
          category: "risk",
          tone: "danger",
          icon: "🛑",
          symbol: bot.symbol,
          meta: humanizeReason(bot.mode),
          message: `Risk stop triggered on ${bot.symbol}`,
          toast: true,
          notify: true,
        });
      } else if (bot.status === "flash_crash_paused") {
        appendActivityEvent({
          key: `status:${bot.id}:flash_crash_paused`,
          category: "risk",
          tone: "warning",
          icon: "🌪️",
          symbol: bot.symbol,
          message: `Flash crash protection paused ${bot.symbol}`,
          toast: true,
          notify: true,
        });
      } else if (bot.status === "error") {
        appendActivityEvent({
          key: `status:${bot.id}:error:${bot.last_error || ""}`,
          category: "risk",
          tone: "danger",
          icon: "⚠️",
          symbol: bot.symbol,
          message: `Bot error on ${bot.symbol}: ${truncateText(bot.last_error || "Unknown error", 72)}`,
          toast: true,
          notify: true,
        });
      }
    }

    if (Number(prev.position_size || 0) <= 0 && Number(bot.position_size || 0) > 0) {
      appendActivityEvent({
        key: `position-open:${bot.id}:${bot.position_side}:${bot.position_size}:${bot.symbol}`,
        category: "execution",
        tone: "info",
        icon: "📥",
        symbol: bot.symbol,
        meta: humanizeReason(bot.position_side === "Buy" ? "Long" : "Short"),
        message: `Opened ${bot.position_side === "Buy" ? "long" : "short"} position on ${bot.symbol}`,
        dedupeWindowMs: 120000,
      });
    }

    if (Number(prev.position_size || 0) > 0 && Number(bot.position_size || 0) <= 0) {
      appendActivityEvent({
        key: `position-close:${bot.id}:${prev.position_side}:${prev.position_size}:${bot.symbol}`,
        category: "execution",
        tone: "info",
        icon: "📤",
        symbol: bot.symbol,
        message: `Position closed on ${bot.symbol}`,
        dedupeWindowMs: 120000,
      });
    }

    if (Number(bot.profit_lock_executed_count || 0) > Number(prev.profit_lock_executed_count || 0)) {
      appendActivityEvent({
        key: `profit-lock:${bot.id}:${bot.profit_lock_executed_count}`,
        category: "profit",
        tone: "profit",
        icon: "🧷",
        symbol: bot.symbol,
        message: `Profit lock executed on ${bot.symbol}`,
        toast: true,
        notify: true,
      });
    }

    if (isStallOverlaySignal(bot) && !isStallOverlaySignal(prev)) {
      appendActivityEvent({
        key: `stall:${bot.id}:${bot.last_replacement_action || bot.last_skip_reason || "stall"}`,
        category: "stall overlay",
        tone: "warning",
        icon: "🪫",
        symbol: bot.symbol,
        message: `Stall overlay pressure increased on ${bot.symbol}`,
        toast: true,
        notify: true,
      });
    }

    if (bot.entry_gate_blocked && !prev.entry_gate_blocked) {
      appendActivityEvent({
        key: `entry-gate:${bot.id}:${bot.entry_gate_reason || "blocked"}`,
        category: "guard",
        tone: "warning",
        icon: "🛡️",
        symbol: bot.symbol,
        message: truncateText(bot.entry_gate_reason || `Entry Gate blocked ${bot.symbol}`, 96),
      });
    }

    if (bot.upnl_stoploss_active && !prev.upnl_stoploss_active) {
      appendActivityEvent({
        key: `soft-sl:${bot.id}:${bot.upnl_stoploss_reason || "active"}`,
        category: "guard",
        tone: "warning",
        icon: "🧯",
        symbol: bot.symbol,
        message: truncateText(bot.upnl_stoploss_reason || `Soft loss guard active on ${bot.symbol}`, 96),
        toast: true,
        notify: true,
      });
    }
  }

  dashboardFeedState.botsById = nextSnapshot;
  updateOperatorWatch();
}

function registerExecutionStreamEvent(payload) {
  const count = Number(payload?.count || 0);
  const symbols = (payload?.symbols || []).filter(Boolean);
  if (!count && !symbols.length) return;

  const symbolSummary = symbols.length === 1
    ? symbols[0]
    : symbols.length > 1
      ? `${symbols.slice(0, 2).join(", ")}${symbols.length > 2 ? ` +${symbols.length - 2}` : ""}`
      : "portfolio";

  appendActivityEvent({
    key: `stream-execution:${symbols.join(",")}:${count}`,
    category: "execution",
    tone: "info",
    icon: "⚙️",
    symbol: symbols.length === 1 ? symbols[0] : "",
    meta: count > 0 ? `${count} fill${count === 1 ? "" : "s"}` : "",
    message: `${count || symbols.length} execution update${(count || symbols.length) === 1 ? "" : "s"} on ${symbolSummary}`,
    dedupeWindowMs: 12000,
  });
}

function flashElement(elementId, isPositive) {
  const el = $(elementId);
  if (!el) return;
  el.classList.remove("flash-green", "flash-red", "flash-neutral");
  void el.offsetWidth;
  if (isPositive === true) el.classList.add("flash-green");
  else if (isPositive === false) el.classList.add("flash-red");
  else el.classList.add("flash-neutral");
  setTimeout(() => el.classList.remove("flash-green", "flash-red", "flash-neutral"), 1000);
}

function updateValueWithFlash(elementId, newValue, formatFn, prevKey) {
  const el = $(elementId);
  if (!el) return;
  const oldValue = previousValues[prevKey];
  const formattedValue = formatFn ? formatFn(newValue) : newValue;
  if (typeof formattedValue === 'object') {
    el.textContent = formattedValue.text;
    el.className = el.className.replace(/\btext-(emerald|red|amber|slate|white|green|blue|purple|orange|yellow|pink|cyan)-\d{3}\b/g, '').trim() + ' ' + formattedValue.class;
  } else {
    el.textContent = formattedValue;
  }
  if (oldValue !== null && oldValue !== newValue) {
    flashElement(elementId, newValue > oldValue);
  }
  previousValues[prevKey] = newValue;
}

function setConnectionStatus(isConnected) {
  const el = $("connection-status");
  if (!el) return;
  if (isConnected) {
    el.innerHTML = `<span class="inline-block w-2 h-2 bg-emerald-400 rounded-full mr-1 animate-pulse"></span>Live`;
    el.className = "px-2 py-1 text-xs font-medium rounded bg-emerald-500/20 text-emerald-400 flex items-center";
  } else {
    el.innerHTML = `<span class="inline-block w-2 h-2 bg-red-400 rounded-full mr-1"></span>Error`;
    el.className = "px-2 py-1 text-xs font-medium rounded bg-red-500/20 text-red-400 flex items-center";
  }
}

function updateLastRefreshTime() {
  lastUpdateTime = new Date();
  const el = $("last-update-time");
  if (el) el.textContent = formatTimeAgo(lastUpdateTime);
}

let _liveFreshPositionInterval = null;

function scheduleLiveQuickRefresh(delay = 250) {
  if (liveQuickRefreshTimeout) clearTimeout(liveQuickRefreshTimeout);
  liveQuickRefreshTimeout = setTimeout(() => {
    refreshPnlQuick();
  }, delay);
}

function scheduleLiveFullRefresh(delay = 400) {
  if (liveFullRefreshTimeout) clearTimeout(liveFullRefreshTimeout);
  liveFullRefreshTimeout = setTimeout(() => {
    refreshAll();
  }, delay);
}

function scheduleLivePnlRefresh(delay = 900) {
  if (livePnlRefreshTimeout) clearTimeout(livePnlRefreshTimeout);
  livePnlRefreshTimeout = setTimeout(async () => {
    try {
      await refreshPnl();
      updateLastRefreshTime();
    } catch (error) {
      console.error("Live PnL refresh error:", error);
    }
  }, delay);
}

function setLiveFeedConnected(isConnected) {
  const previous = dashboardFeedState.lastFeedConnectionState;
  liveFeedConnected = isConnected;
  configureLivePolling(isConnected);
  setConnectionStatus(isConnected);
  dashboardFeedState.lastFeedConnectionState = isConnected;

  if (previous !== null && previous !== isConnected) {
    appendActivityEvent({
      key: `live-feed:${isConnected ? "up" : "down"}`,
      category: "notification",
      tone: isConnected ? "info" : "warning",
      icon: isConnected ? "🟢" : "🟠",
      message: isConnected
        ? "Live stream reconnected"
        : "Live stream disconnected, fallback polling active",
      toast: !isConnected,
      notify: !isConnected,
      dedupeWindowMs: 30000,
    });
  }

  updateOperatorWatch();
}

function parseLiveEventPayload(event) {
  try {
    return JSON.parse(event.data || "{}");
  } catch (error) {
    console.warn("Live event payload parse failed:", error);
    return null;
  }
}

function maybeScheduleDashboardPnlRefresh(delay = 450) {
  if ((Date.now() - lastPnlRefreshAt) < LIVE_DASHBOARD_PNL_REFRESH_MIN_INTERVAL_MS) {
    return;
  }
  scheduleLivePnlRefresh(delay);
}

function applyLiveDashboardUpdate(payload) {
  if (!payload || typeof payload !== "object") {
    return;
  }
  if (payload.summary) {
    applySummaryData(payload.summary);
  }
  if (payload.positions) {
    applyPositionsData(payload.positions);
  }
  // Suppress SSE bot updates briefly after save to prevent stale overwrite
  if (window._suppressSseBotsUntil && Date.now() < window._suppressSseBotsUntil) {
    return;
  }
  if (payload.bots) {
    applyBotsData({
      bots: payload.bots,
      bots_meta: payload.bots_meta,
      _state_source: "dashboard_stream",
    });
  }
  if (payload.watchdog_hub) {
    applyWatchdogHubData(payload.watchdog_hub);
  }
  if (payload.bot_triage) {
    applyBotTriageData(payload.bot_triage);
  }
  if (payload.bot_config_advisor) {
    applyBotConfigAdvisorData(payload.bot_config_advisor);
  }
  maybeScheduleDashboardPnlRefresh();
  lastLiveDashboardUpdateAt = Date.now();
  setConnectionStatus(true);
  updateLastRefreshTime();
}

function connectLiveFeed() {
  if (!window.EventSource) {
    configureLivePolling(false);
    return;
  }

  if (liveEventSource) {
    liveEventSource.close();
    liveEventSource = null;
  }

  const source = new EventSource(`${API_BASE}/stream/events`);
  liveEventSource = source;

  // SSE stale detection: if no data event within 5s of open, the stream
  // is stuck (server building slow payload). Fall back to polling.
  let _sseReceivedData = false;
  if (window._sseStaleTimer) clearTimeout(window._sseStaleTimer);
  window._sseStaleTimer = setTimeout(() => {
    if (!_sseReceivedData) {
      console.warn("SSE stream stale (no data in 5s), enabling fallback polling");
      configureLivePolling(false);
    }
    window._sseStaleTimer = null;
  }, 5000);

  source.addEventListener("open", () => {
    setLiveFeedConnected(true);
    updateLastRefreshTime();
  });

  source.addEventListener("error", () => {
    setLiveFeedConnected(false);
  });

  source.addEventListener("snapshot", (event) => {
    _sseReceivedData = true;
    if (window._sseStaleTimer) { clearTimeout(window._sseStaleTimer); window._sseStaleTimer = null; }
    setLiveFeedConnected(true);
    const payload = parseLiveEventPayload(event);
    if (payload?.dashboard) {
      applyLiveDashboardUpdate(payload.dashboard);
      return;
    }
    updateLastRefreshTime();
    scheduleLiveFullRefresh(0);
  });

  source.addEventListener("dashboard", (event) => {
    setLiveFeedConnected(true);
    const payload = parseLiveEventPayload(event);
    if (payload) {
      applyLiveDashboardUpdate(payload);
    }
  });

  source.addEventListener("heartbeat", () => {
    setLiveFeedConnected(true);
    updateLastRefreshTime();
  });

  ["ticker", "position", "execution", "order", "health"].forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      setLiveFeedConnected(true);
      updateLastRefreshTime();
      if (eventName === "execution") {
        const payload = parseLiveEventPayload(event);
        if (payload) {
          registerExecutionStreamEvent(payload);
        }
      }
      if (eventName === "position" || eventName === "execution" || eventName === "order") {
        scheduleLivePnlRefresh();
        // Refresh via bridge-backed endpoints. Direct ?fresh probes on the
        // live SSE path were enough to reintroduce dashboard stalls.
        setTimeout(() => {
          refreshPositions().catch(() => {});
          refreshSummary().catch(() => {});
        }, 300);
        // Trigger incremental refresh of All PnL modal if open
        const allPnlModal = $("allPnlModal");
        if (allPnlModal && !allPnlModal.classList.contains("hidden") && allPnlAutoRefreshEnabled) {
          if (!allPnlIsRefreshing) {
            setTimeout(() => refreshAllPnlModal(false), 1500);
          }
        }
      }
    });
  });
}

let _refreshAllCycle = 0;
async function refreshAll() {
  try {
    // Critical data refreshed every cycle: account, positions, bots, PnL
    const critical = [refreshSummary(), refreshPositions(), refreshBots(), refreshPnl()];
    // Non-critical data refreshed every 3rd cycle to reduce API load
    _refreshAllCycle = (_refreshAllCycle + 1) % 3;
    if (_refreshAllCycle === 0) {
      critical.push(refreshWatchdogHub(), refreshBotTriage(), refreshBotConfigAdvisor(), refreshPredictions());
    }
    await Promise.all(critical);
    setConnectionStatus(true);
    updateLastRefreshTime();
  } catch (error) {
    console.error("Refresh error:", error);
    setConnectionStatus(false);
  }
}

async function refreshPnlQuick() {
  try {
    await refreshPnl();
    setConnectionStatus(true);
    updateLastRefreshTime();
  } catch (error) {
    console.error("Quick refresh error:", error);
    setConnectionStatus(false);
  }
}

function applySummaryData(data) {
  window._lastSummaryData = data;
  const account = data.account || {};

  updateValueWithFlash("summary-total-assets", parseFloat(account.equity || 0), (v) => formatNumber(v, 2), "totalAssets");
  $("summary-available-balance").textContent = formatNumber(account.available_balance, 2);

  // Update global balances for modal (ALWAYS update even if UI elements missing)
  window._currentUnifiedBalance = parseFloat(account.available_balance || 0);
  window._currentWalletEquity = parseFloat(account.equity || 0);
  window._currentFundingBalance = parseFloat(account.funding_balance || 0);

  if (!($("bot-id")?.value || "").trim() && !botFormAutoInvestmentManualOverride) {
    const changed = applyAutoInvestmentFromBalance();
    if (changed) {
      updateRiskInfo();
    }
  }

  // Update funding balance display if element exists
  const fundingBalanceEl = $("summary-funding-balance");
  if (fundingBalanceEl) {
    fundingBalanceEl.textContent = formatNumber(account.funding_balance, 2);
  }

  // Update page title with unrealized PnL
  const unrealizedPnl = parseFloat(account.unrealized_pnl || 0);
  updatePageTitle(unrealizedPnl);

  const realizedVal = parseFloat(account.realized_pnl || 0);
  const realizedPnL = formatPnL(realizedVal);
  const realizedEl = $("summary-realized-pnl");
  if (previousValues.realizedPnl !== null && previousValues.realizedPnl !== realizedVal) {
    flashElement("summary-realized-pnl", realizedVal > previousValues.realizedPnl);
  }
  realizedEl.textContent = realizedPnL.text;
  realizedEl.className = `text-sm font-medium ${realizedVal > 0 ? 'text-cyan-400' : realizedPnL.class}`;
  previousValues.realizedPnl = realizedVal;

  const unrealizedVal = parseFloat(account.unrealized_pnl || 0);
  const unrealizedPnL = formatPnL(unrealizedVal);
  const unrealizedEl = $("summary-unrealized-pnl");
  if (previousValues.unrealizedPnl !== null && previousValues.unrealizedPnl !== unrealizedVal) {
    flashElement("summary-unrealized-pnl", unrealizedVal > previousValues.unrealizedPnl);
  }
  unrealizedEl.textContent = unrealizedPnL.text;
  unrealizedEl.className = `text-sm font-medium ${unrealizedPnL.class}`;
  previousValues.unrealizedPnl = unrealizedVal;

  const today = data.today_pnl || {};
  const todayNetVal = parseFloat(today.net || 0);
  const todayNet = formatPnL(todayNetVal);
  const todayEl = $("summary-today-net");
  if (previousValues.todayNet !== null && previousValues.todayNet !== todayNetVal) {
    flashElement("summary-today-net", todayNetVal > previousValues.todayNet);
  }
  todayEl.textContent = todayNet.text;
  todayEl.className = todayNet.class;
  previousValues.todayNet = todayNetVal;

  $("summary-today-wins").textContent = today.wins || 0;
  $("summary-today-losses").textContent = today.losses || 0;

  const posSummary = data.positions_summary || {};
  $("summary-positions-count").textContent = posSummary.total_positions || 0;
  $("summary-positions-longs").textContent = posSummary.longs || 0;
  $("summary-positions-shorts").textContent = posSummary.shorts || 0;
  updateOpenExposureMeta(posSummary.total_position_value || 0);
  updateOperatorWatch();
}

async function refreshSummary(fresh = false) {
  const url = fresh ? "/summary?fresh=1" : "/summary";
  const data = await fetchJSON(url);
  applySummaryData(data);
}

function applyPositionsData(data) {
  const payload = Array.isArray(data) ? { positions: data } : (data || {});
  window._lastPositionsPayload = payload;
  const positions = Array.isArray(payload.positions) ? payload.positions : [];

  const currentCount = positions.length;
  if (previousValues.positionCount !== null && currentCount > previousValues.positionCount) {
    playPositionOpenSound();
  }
  previousValues.positionCount = currentCount;

  // Calculate position stats
  let longCount = 0, shortCount = 0;
  let totalPnl = 0, profitSum = 0, lossSum = 0;
  let totalPositionValue = 0;
  for (const pos of positions) {
    if (pos.side === "Buy") longCount++;
    else if (pos.side === "Sell") shortCount++;
    const pnl = parseFloat(pos.unrealized_pnl || 0);
    totalPnl += pnl;
    if (pnl > 0) profitSum += pnl;
    else if (pnl < 0) lossSum += Math.abs(pnl);
    totalPositionValue += parseFloat(pos.position_value || pos.positionValue || 0);
  }
  // Update open exposure from live position data (more current than bridge summary)
  if (totalPositionValue > 0) {
    updateOpenExposureMeta(totalPositionValue);
    // Also update the summary cache so bot card renders pick it up
    if (window._lastSummaryData) {
      if (!window._lastSummaryData.positions_summary) window._lastSummaryData.positions_summary = {};
      window._lastSummaryData.positions_summary.total_position_value = totalPositionValue;
      window._lastSummaryData.positions_summary.total_positions = positions.length;
      window._lastSummaryData.positions_summary.longs = longCount;
      window._lastSummaryData.positions_summary.shorts = shortCount;
    }
  } else if (positions.length === 0) {
    updateOpenExposureMeta(0);
  }

  // Update position stats display
  const totalCountEl = document.getElementById('pos-total-count');
  const longCountEl = document.getElementById('pos-long-count');
  const shortCountEl = document.getElementById('pos-short-count');
  const totalPnlEl = document.getElementById('pos-total-pnl');
  const profitSumEl = document.getElementById('pos-profit-sum');
  const lossSumEl = document.getElementById('pos-loss-sum');

  if (totalCountEl) totalCountEl.textContent = positions.length;
  if (longCountEl) longCountEl.textContent = longCount;
  if (shortCountEl) shortCountEl.textContent = shortCount;
  if (totalPnlEl) {
    totalPnlEl.textContent = `$${totalPnl.toFixed(2)}`;
    totalPnlEl.className = 'text-sm font-semibold ' + (totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400');
  }
  if (profitSumEl) profitSumEl.textContent = profitSum.toFixed(2);
  if (lossSumEl) lossSumEl.textContent = lossSum.toFixed(2);

  // Update wallet balance display
  const walletBalance = payload.wallet_balance || 0;
  const walletBalanceEl = document.getElementById('pos-wallet-balance');
  if (walletBalanceEl) {
    walletBalanceEl.textContent = `$${walletBalance.toFixed(2)}`;
  }

  // Update available balance display (001-trading-bot-audit: FR-001, FR-002)
  const availableBalance = payload.available_balance || 0;
  const availableBalanceEl = document.getElementById('pos-available-balance');
  if (availableBalanceEl) {
    availableBalanceEl.textContent = `$${availableBalance.toFixed(2)}`;
  }

  if (positions.length === 0) {
    previousValues.positionPnls = {};
    renderMobilePositionsData([]);
    return;
  }

  previousValues.positionPnls = {};
  for (const pos of positions) {
    const posKey = `${pos.symbol}_${pos.side}`;
    previousValues.positionPnls[posKey] = parseFloat(pos.unrealized_pnl || 0);
  }
  renderMobilePositionsData(positions);
}

async function refreshPositions(fresh = false) {
  try {
    const url = fresh ? "/positions?fresh=1" : "/positions";
    const data = await fetchJSON(url);
    applyPositionsData(data);
    return data;
  } catch (error) {
    const cachedPayload = window._lastPositionsPayload;
    if (cachedPayload && Array.isArray(cachedPayload.positions)) {
      applyPositionsData(cachedPayload);
    } else {
      renderPositionsStatusMessage("Unable to load positions");
    }
    throw error;
  }
}

function setActiveBotsGlobalStaleState(isStale, detail) {
  const indicator = $("active-bots-stale-indicator");
  if (!indicator) return;

  if (!isStale) {
    indicator.classList.add("hidden");
    indicator.textContent = "Snapshot stale";
    indicator.title = "";
    return;
  }

  const staleDetail = String(detail || "").trim();
  indicator.classList.remove("hidden");
  indicator.textContent = "Snapshot stale";
  indicator.title = staleDetail
    ? `Runner snapshot is stale. Detail: ${staleDetail}`
    : "Runner snapshot is stale. Wait for a fresh runner snapshot before acting.";
}

function applyBotsData(data) {
  const payload = data || {};
  const incomingBots = Array.isArray(payload?.bots) ? payload.bots : [];
  const runtimeIntegrity = (payload?.runtime_integrity && typeof payload.runtime_integrity === "object")
    ? payload.runtime_integrity
    : null;
  const payloadMeta = (payload?.bots_meta && typeof payload.bots_meta === "object")
    ? payload.bots_meta
    : payload;
  const runtimeSnapshotStale = Boolean(payloadMeta?.stale_data || payload?.stale_data);
  const runtimeSnapshotDetail = String(payloadMeta?.error || payload?.error || "").trim();
  const snapshotPublishedAt = Number(payloadMeta?.snapshot_published_at || 0);
  const snapshotProducedAt = Number(payloadMeta?.snapshot_produced_at || 0);
  const snapshotTs = snapshotPublishedAt > 0
    ? snapshotPublishedAt
    : (snapshotProducedAt > 0 ? snapshotProducedAt : 0);
  const requestSeq = Number(payload?._request_seq || 0);
  const stateSource = String(payload?._state_source || payloadMeta?.snapshot_source || "unknown").trim() || "unknown";
  const previousMeta = (window._lastBotsStateMeta && typeof window._lastBotsStateMeta === "object")
    ? window._lastBotsStateMeta
    : null;
  const previousBots = Array.isArray(window._lastBots) ? window._lastBots : [];
  const runtimeTruthCount = incomingBots.reduce((count, bot) => {
    const setupStatus = String(
      bot?.setup_timing_status
      || bot?.setup_ready_status
      || bot?.analysis_ready_status
      || bot?.entry_ready_status
      || ""
    ).trim();
    const executionStatus = String(bot?.execution_viability_status || "").trim();
    const hasScore = bot?.setup_ready_score !== undefined || bot?.analysis_ready_score !== undefined;
    return count + (setupStatus || executionStatus || hasScore ? 1 : 0);
  }, 0);
  const olderRequest = Boolean(
    requestSeq > 0
    && Number(previousMeta?.requestSeq || 0) > 0
    && requestSeq < Number(previousMeta?.requestSeq || 0)
  );
  const olderSnapshot = Boolean(
    snapshotTs > 0
    && Number(previousMeta?.snapshotTs || 0) > 0
    && snapshotTs + 0.0001 < Number(previousMeta?.snapshotTs || 0)
  );
  // After CRUD operations, accept refreshes even if snapshot looks older
  const forcedRefresh = Boolean(window._forceNextBotsApply);
  if (forcedRefresh) window._forceNextBotsApply = false;

  const neverRendered = previousBots.length === 0;
  if ((olderRequest || olderSnapshot) && !forcedRefresh && !neverRendered) {
    if (runtimeSnapshotStale || Boolean(runtimeIntegrity?.stale_guard_active)) {
      setActiveBotsGlobalStaleState(
        true,
        String(
          runtimeIntegrity?.stale_guard_reason
          || runtimeIntegrity?.dropped_reason
          || runtimeSnapshotDetail
          || ""
        ).trim()
      );
    }
    window._lastBotsStateMeta = {
      ...(previousMeta || {}),
      dropped_as_stale: true,
      dropped_source: stateSource,
      dropped_request_seq: requestSeq || null,
      dropped_snapshot_ts: snapshotTs || null,
      dropped_reason: olderRequest ? "older_request" : "older_snapshot",
      runtimeIntegrity: runtimeIntegrity || previousMeta?.runtimeIntegrity || null,
    };
    return;
  }

  const shouldPreserveFreshState = Boolean(
    runtimeSnapshotStale
    && previousMeta
    && !Boolean(previousMeta.staleData)
    && previousBots.length > 0
    && (
      incomingBots.length === 0
      || runtimeTruthCount === 0
      || runtimeTruthCount < Number(previousMeta.runtimeTruthCount || 0)
    )
  );
  if (shouldPreserveFreshState && !forcedRefresh && !neverRendered) {
    setActiveBotsGlobalStaleState(
      true,
      String(
        runtimeIntegrity?.stale_guard_reason
        || runtimeIntegrity?.dropped_reason
        || runtimeSnapshotDetail
        || "bots_runtime snapshot is stale"
      ).trim()
    );
    window._lastBotsStateMeta = {
      ...previousMeta,
      stale_overlay_active: true,
      stale_overlay_source: stateSource,
      stale_overlay_error: runtimeSnapshotDetail || "bots_runtime snapshot is stale",
      stale_overlay_snapshot_ts: snapshotTs || null,
      stale_overlay_request_seq: requestSeq || null,
      dropped_as_stale: true,
      dropped_reason: "stale_overlay_preserved",
      runtimeIntegrity: runtimeIntegrity || previousMeta?.runtimeIntegrity || null,
    };
    return;
  }

  const bots = incomingBots.map((bot) => {
    const enrichedBot = { ...bot };
    if (runtimeSnapshotStale) {
      enrichedBot.runtime_snapshot_stale = true;
      enrichedBot.runtime_snapshot_stale_detail = runtimeSnapshotDetail || "bots_runtime snapshot is stale";
    }
    return enrichedBot;
  });
  if (!runtimeIntegrity) {
    setActiveBotsGlobalStaleState(runtimeSnapshotStale, runtimeSnapshotDetail);
  } else {
    setActiveBotsGlobalStaleState(
      runtimeSnapshotStale || Boolean(runtimeIntegrity?.stale_guard_active),
      String(
        runtimeIntegrity?.stale_guard_reason
        || runtimeIntegrity?.dropped_reason
        || runtimeSnapshotDetail
        || ""
      ).trim()
    );
  }
  window._lastRuntimeIntegrity = runtimeIntegrity || null;
  window._lastBotsStateMeta = {
    requestSeq,
    snapshotTs,
    staleData: runtimeSnapshotStale,
    stateSource,
    botCount: bots.length,
    runtimeTruthCount,
    runtimeIntegrity,
    appliedSeq: ++appliedBotsStateSeq,
    appliedAtMs: Date.now(),
    stale_overlay_active: false,
    dropped_as_stale: false,
  };
  pruneActiveBotFrontendState(bots);
  const nowMs = Date.now();
  // Category stability: prevent stale-snapshot-induced flickering by requiring
  // a category to be consistent for 2+ refreshes before applying it.
  if (!window._botCatStability) window._botCatStability = {};
  const runtimeStale = Boolean(
    window._lastBotsStateMeta?.stale_overlay_active
    || payload?.stale_data
    || (payload?.bots_meta || {}).stale_data
  );
  for (const bot of bots) {
    const rawCat = getEffectiveActiveBotReadyCategory(bot, nowMs);
    const botId = bot.id;
    const prev = window._botCatStability[botId];
    if (!prev) {
      // First time seeing this bot — apply immediately
      window._botCatStability[botId] = { cat: rawCat, count: 1, applied: rawCat };
      bot._active_bots_ready_cat = rawCat;
    } else if (rawCat === prev.cat) {
      // Same category as last refresh — increment stability count
      prev.count++;
      if (prev.count >= 2 || rawCat === "ready") {
        prev.applied = rawCat;
      }
      bot._active_bots_ready_cat = prev.applied;
    } else if (rawCat === "ready") {
      // "ready" is always applied immediately — never delay good news
      prev.cat = rawCat;
      prev.count = 2;
      prev.applied = rawCat;
      bot._active_bots_ready_cat = rawCat;
    } else if (runtimeStale) {
      // During stale data, keep the previous applied category
      prev.cat = rawCat;
      prev.count = 1;
      bot._active_bots_ready_cat = prev.applied;
    } else {
      // Category changed — reset counter, keep old applied for now
      prev.cat = rawCat;
      prev.count = 1;
      bot._active_bots_ready_cat = prev.applied;
    }
  }
  // Prune stability map for bots no longer present
  const activeBotIds = new Set(bots.map(b => b.id));
  for (const id of Object.keys(window._botCatStability)) {
    if (!activeBotIds.has(id)) delete window._botCatStability[id];
  }
  trackActiveBotCategoryTransitions(bots, nowMs);
  const sortedBots = sortBotsForDisplay(bots);
  window._lastBotsStateMeta.botCount = sortedBots.length;
  detectBotRuntimeEvents(sortedBots);
  renderReadyTradeBoard(sortedBots);
  window._lastBots = sortedBots;  // Cache for backtest lookup

  // Count running bots and toggle emergency button visibility
  const runningBotsCount = sortedBots.filter(b => b.status === "running").length;
  const primaryRunningBot = sortedBots.find(b => b.status === "running");
  liveOpenExposureRecommendation = {
    mode: String(primaryRunningBot?.scanner_recommended_mode || "").trim(),
    rangeMode: String(primaryRunningBot?.scanner_recommended_range_mode || "").trim(),
    differs: Boolean(primaryRunningBot?.scanner_recommendation_differs),
  };
  updateOpenExposureMeta((window._lastSummaryData?.positions_summary || {}).total_position_value || 0);
  const emergencySection = $("emergency-stop-section");
  if (emergencySection) {
    emergencySection.style.display = sortedBots.length > 0 ? "flex" : "none";
  }
  const emergencyCard = $("emergency-stop-card");
  if (emergencyCard) {
    emergencyCard.classList.toggle("hidden", runningBotsCount === 0);
  }
  const emergencyButton = $("btn-emergency-stop");
  if (emergencyButton) {
    const disableEmergency = runningBotsCount === 0;
    emergencyButton.disabled = disableEmergency;
    emergencyButton.classList.toggle("cursor-not-allowed", disableEmergency);
    emergencyButton.style.backgroundColor = disableEmergency ? "#000000" : "";
    emergencyButton.style.borderColor = disableEmergency ? "rgb(51 65 85)" : "";
    emergencyButton.style.color = disableEmergency ? "rgb(148 163 184)" : "";
    emergencyButton.style.boxShadow = disableEmergency ? "none" : "";
    emergencyButton.title = disableEmergency
      ? "No running bots to stop"
      : "Stop all running bots and flatten live exposure";
  }
  renderEmergencyRestartPanel(sortedBots);

  // Update filter chip counts
  const readyCats = sortedBots.map((bot) => String(bot._active_bots_ready_cat || "other").trim().toLowerCase());
  const readyCount = readyCats.filter((cat) => cat === "ready").length;
  const watchCount = readyCats.filter((cat) => cat === "watch").length;
  const blockedCount = readyCats.filter((cat) => cat === "blocked").length;
  const limitedCount = readyCats.filter((cat) => cat === "limited").length;
  const totalBotsEl = $("active-bots-total");
  if (totalBotsEl) totalBotsEl.textContent = String(sortedBots.length);
  const workingNowCount = sortedBots.filter(b => b.status === "running" || b.status === "paused").length;
  const runningEl = $("active-bots-running"); if (runningEl) runningEl.textContent = String(workingNowCount);
  const readyEl = $("active-bots-ready"); if (readyEl) readyEl.textContent = String(readyCount);
  const watchEl = $("active-bots-watch"); if (watchEl) watchEl.textContent = String(watchCount);
  const triggerCount = sortedBots.filter(b => isTriggerReadyStatus(getSetupReadiness(b).status)).length;
  const triggerEl = $("active-bots-trigger"); if (triggerEl) triggerEl.textContent = String(triggerCount);
  const armedCount = sortedBots.filter(b => isArmedStatus(getSetupReadiness(b).status)).length;
  const armedEl = $("active-bots-armed"); if (armedEl) armedEl.textContent = String(armedCount);
  const blockedEl = $("active-bots-blocked"); if (blockedEl) blockedEl.textContent = String(blockedCount);
  const limitedEl = $("active-bots-limited"); if (limitedEl) limitedEl.textContent = String(limitedCount);
  const recentStoppedCount = sortedBots.filter(b => b.status === "stopped" && _isRecentlyStopped(b.id)).length;
  const recentStoppedEl = $("active-bots-recent-stopped"); if (recentStoppedEl) recentStoppedEl.textContent = String(recentStoppedCount);

  for (const bot of sortedBots) {
    const pendingAction = pendingBotActions[bot.id];
    if (pendingAction === "start" && (bot.status === "running" || bot.status === "recovering")) {
      delete pendingBotActions[bot.id];
    } else if (pendingAction === "stop" && bot.status === "stopped") {
      delete pendingBotActions[bot.id];
    } else if (pendingAction === "pause" && bot.status === "paused") {
      delete pendingBotActions[bot.id];
    } else if (pendingAction === "resume" && bot.status === "running") {
      delete pendingBotActions[bot.id];
    }
    previousValues.botPnls[bot.id] = parseFloat(bot.total_pnl || 0);
  }

  if (sortedBots.length === 0) {
    renderReadyTradeBoard([]);
    renderMobileBotsData([]);
    updateRunningBotsStatus([]);
    updateOperatorWatch();
    return;
  }

  // Update running bots status display
  updateRunningBotsStatus(sortedBots);
  const sameStructure = hasSameActiveBotStructure(sortedBots);
  if (!sameStructure || !patchActiveBotRowsInPlace(sortedBots)) {
    renderMobileBotsData(sortedBots);
  }
  updateOperatorWatch();
}

async function refreshBots() {
  // If a forced refresh is pending, don't reuse in-flight request
  if (refreshBotsPromise && !window._forceNextBotsApply) return refreshBotsPromise;
  const requestSeq = ++refreshBotsRequestSeq;
  refreshBotsPromise = (async () => {
    try {
      const data = await fetchJSON("/bots/runtime");
      applyBotsData({
        ...(data || {}),
        _request_seq: requestSeq,
        _state_source: "runtime_api",
      });
    } finally {
      refreshBotsPromise = null;
    }
  })();
  return refreshBotsPromise;
}





function summarizeWatchdogMetrics(metrics, limit = 3) {
  const entries = Object.entries(metrics || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return entries.slice(0, limit).map(([key, value]) => `${formatWatchdogLabel(key)} ${formatWatchdogMetricValue(value)}`).join(" · ");
}

function summarizeWatchdogConfig(config) {
  const entries = Object.entries(config || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return entries.slice(0, 3).map(([key, value]) => `${formatWatchdogLabel(key)} ${formatWatchdogMetricValue(value)}`).join(" · ");
}

function setDiagnosticsExportStatus(message, type = "info") {
  const statusEl = $("diagnostics-export-status");
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.className = "mt-3 text-xs";
  statusEl.classList.add(
    type === "success"
      ? "text-emerald-300"
      : type === "error"
        ? "text-rose-300"
        : "text-slate-400"
  );
}

function buildDiagnosticsExportSuccessMessage(label, payload) {
  const parts = [`${label} export saved`];
  if (payload?.generated_at) parts.push(String(payload.generated_at));
  if (payload?.latest_path) {
    parts.push(String(payload.latest_path));
  } else if (payload?.archive_path) {
    parts.push(String(payload.archive_path));
  }
  return parts.join(" · ");
}

function setDiagnosticsExportButtonLoading(button, isLoading) {
  if (!button) return;
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = String(button.textContent || "").trim();
  }
  button.disabled = Boolean(isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
  button.classList.toggle("opacity-60", Boolean(isLoading));
  button.classList.toggle("cursor-not-allowed", Boolean(isLoading));
  button.textContent = isLoading
    ? (button.dataset.exportLoadingLabel || "Exporting...")
    : button.dataset.defaultLabel;
}

function getDownloadFilenameFromDisposition(disposition, fallback = "opus-trader-diagnostics.json") {
  const value = String(disposition || "").trim();
  if (!value) return fallback;
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (error) {
      return utf8Match[1];
    }
  }
  const asciiMatch = value.match(/filename=\"?([^\";]+)\"?/i);
  return asciiMatch?.[1] || fallback;
}

function triggerBrowserDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function triggerDiagnosticsExport(button) {
  if (!button) return;
  const endpoint = String(button.dataset.exportEndpoint || "").trim();
  const label = String(button.dataset.exportLabel || button.textContent || "Diagnostics").trim();
  if (!endpoint) {
    const message = `${label} export is not configured`;
    setDiagnosticsExportStatus(message, "error");
    showToast(message, "error");
    return;
  }

  setDiagnosticsExportButtonLoading(button, true);
  setDiagnosticsExportStatus(`${label} download in progress...`);
  try {
    const response = await fetch(API_BASE + endpoint, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const error = new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    const blob = await response.blob();
    const filename = getDownloadFilenameFromDisposition(
      response.headers.get("Content-Disposition"),
      `opus-trader-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`,
    );
    triggerBrowserDownload(blob, filename);
    const archivePath = String(response.headers.get("X-Opus-Archive-Path") || "").trim();
    const successMessage = archivePath
      ? `${label} downloaded as ${filename}. Server archive also updated: ${archivePath}`
      : `${label} downloaded as ${filename}`;
    setDiagnosticsExportStatus(successMessage, "success");
    showToast(successMessage, "success");
  } catch (error) {
    const errorMessage = error?.status === 404
      ? `${label} export unavailable on this server`
      : `${label} export failed: ${error?.message || "Unknown error"}`;
    setDiagnosticsExportStatus(errorMessage, "error");
    showToast(errorMessage, "error");
  } finally {
    setDiagnosticsExportButtonLoading(button, false);
  }
}

function populateWatchdogFilterOptions(selectId, values, emptyLabel) {
  const select = $(selectId);
  if (!select) return;
  const current = String(select.value || "");
  const options = [`<option value="">${escapeHtml(emptyLabel)}</option>`].concat(
    (values || []).filter(Boolean).map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
  );
  select.innerHTML = options.join("");
  if ((values || []).includes(current)) {
    select.value = current;
  } else {
    select.value = "";
  }
}




function initWatchdogHubControls() {
  const refreshBtn = $("btn-refresh-watchdog-hub");
  if (refreshBtn && !refreshBtn.dataset.bound) {
    refreshBtn.dataset.bound = "1";
    refreshBtn.addEventListener("click", () => Promise.allSettled([refreshWatchdogHub(), refreshBotTriage(), refreshBotConfigAdvisor()]));
  }

  for (const buttonId of DIAGNOSTICS_EXPORT_BUTTON_IDS) {
    const button = $(buttonId);
    if (!button || button.dataset.bound) continue;
    button.dataset.bound = "1";
    button.dataset.defaultLabel = String(button.textContent || "").trim();
    button.addEventListener("click", () => triggerDiagnosticsExport(button));
  }

  const baselineBtn = $("btn-reset-performance-baseline");
  if (baselineBtn && !baselineBtn.dataset.bound) {
    baselineBtn.dataset.bound = "1";
    baselineBtn.addEventListener("click", () => beginGlobalPerformanceBaselineReset());
  }

  const filterMap = [
    ["watchdog-filter-severity", "severity"],
    ["watchdog-filter-type", "watchdogType"],
    ["watchdog-filter-bot", "botId"],
    ["watchdog-filter-symbol", "symbol"],
  ];
  for (const [elementId, key] of filterMap) {
    const element = $(elementId);
    if (!element || element.dataset.bound) continue;
    element.dataset.bound = "1";
    element.addEventListener("change", () => {
      watchdogHubState.filters[key] = String(element.value || "");
      renderWatchdogHub();
    });
  }

  const activeOnlyToggle = $("watchdog-filter-active-only");
  if (activeOnlyToggle && !activeOnlyToggle.dataset.bound) {
    activeOnlyToggle.dataset.bound = "1";
    activeOnlyToggle.addEventListener("change", () => {
      watchdogHubState.filters.activeOnly = Boolean(activeOnlyToggle.checked);
      renderWatchdogHub();
    });
  }

  const activeContainer = $("watchdog-active-issues");
  if (activeContainer && !activeContainer.dataset.bound) {
    activeContainer.dataset.bound = "1";
    activeContainer.addEventListener("click", (event) => {
      const button = event.target.closest("[data-watchdog-select]");
      if (!button) return;
      watchdogHubState.selectedKey = String(button.dataset.watchdogKey || "");
      watchdogHubState.selectedKind = String(button.dataset.watchdogKind || "active");
      renderWatchdogHub();
    });
  }

  const cardsContainer = $("watchdog-cards-grid");
  if (cardsContainer && !cardsContainer.dataset.bound) {
    cardsContainer.dataset.bound = "1";
    cardsContainer.addEventListener("click", (event) => {
      const button = event.target.closest("[data-watchdog-card]");
      if (!button) return;
      const watchdogType = String(button.dataset.watchdogCard || "");
      const select = $("watchdog-filter-type");
      watchdogHubState.filters.watchdogType = watchdogType;
      if (select) select.value = watchdogType;
      renderWatchdogHub();
    });
  }

  const timelineContainer = $("watchdog-recent-timeline");
  if (timelineContainer && !timelineContainer.dataset.bound) {
    timelineContainer.dataset.bound = "1";
    timelineContainer.addEventListener("click", (event) => {
      const button = event.target.closest("[data-watchdog-select]");
      if (!button) return;
      watchdogHubState.selectedKey = String(button.dataset.watchdogKey || "");
      watchdogHubState.selectedKind = String(button.dataset.watchdogKind || "recent");
      renderWatchdogHub();
    });
  }
}

function getFilteredWatchdogHubData() {
  const payload = watchdogHubState.data || {};
  const filters = watchdogHubState.filters || {};
  const severity = String(filters.severity || "").trim().toUpperCase();
  const watchdogType = String(filters.watchdogType || "").trim();
  const botId = String(filters.botId || "").trim();
  const symbol = String(filters.symbol || "").trim().toUpperCase();
  const activeOnly = Boolean(filters.activeOnly);
  const activeKeys = new Set((payload.active_issues || []).map((item) => item.active_key));

  const matches = (item, isRecent = false) => {
    if (severity && String(item?.severity || "").trim().toUpperCase() !== severity) return false;
    if (watchdogType && String(item?.watchdog_type || "").trim() !== watchdogType) return false;
    if (botId && String(item?.bot_id || "").trim() !== botId) return false;
    if (symbol && String(item?.symbol || "").trim().toUpperCase() !== symbol) return false;
    if (activeOnly && isRecent && !activeKeys.has(String(item?.event_key || item?.active_key || ""))) return false;
    return true;
  };

  const activeIssues = (payload.active_issues || []).filter((item) => matches(item));
  const recentEvents = (payload.recent_events || []).filter((item) => matches(item, true));
  const watchdogCards = (payload.watchdog_cards || []).filter((card) => {
    if (watchdogType && String(card.watchdog_type || "").trim() !== watchdogType) return false;
    return true;
  });
  return { activeIssues, recentEvents, watchdogCards };
}











function renderWatchdogDetail(filtered) {
  const container = $("watchdog-detail-body");
  if (!container) return;
  const activeIssues = filtered.activeIssues || [];
  const recentEvents = filtered.recentEvents || [];
  let selected = null;
  if (watchdogHubState.selectedKey) {
    selected = activeIssues.find((item) => item.active_key === watchdogHubState.selectedKey)
      || recentEvents.find((item) => item.event_key === watchdogHubState.selectedKey);
  }
  if (!selected) {
    selected = activeIssues[0] || recentEvents[0] || null;
  }
  if (!selected) {
    container.innerHTML = `Select an active issue, watchdog card, or recent event to inspect its evidence.`;
    return;
  }
  watchdogHubState.selectedKey = String(selected.active_key || selected.event_key || "");
  const severity = getWatchdogSeverityMeta(selected.severity);
  const isActive = Boolean(selected.is_active);
  const truthTag = renderWatchdogExchangeTruthTag(selected);
  container.innerHTML = `
    <div class="space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${severity.chip}">${severity.label}</span>
        <span class="inline-flex items-center rounded-full border ${isActive ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100" : "border-slate-700 bg-slate-900/80 text-slate-300"} px-2 py-1 text-[11px] font-semibold">${isActive ? "ACTIVE NOW" : "RECENT / HISTORICAL"}</span>
        ${truthTag}
        <span class="text-sm font-semibold text-white">${escapeHtml(selected.watchdog_label || formatWatchdogLabel(selected.watchdog_type))}</span>
      </div>
      <div class="text-sm text-slate-100">${escapeHtml(formatWatchdogLabel(selected.reason))}</div>
      <div class="text-xs text-slate-400">${escapeHtml(selected.bot_id || "No bot")} · ${escapeHtml(selected.symbol || "No symbol")} · first seen ${escapeHtml(formatTimeAgo(new Date(selected.first_seen || selected.timestamp || Date.now())))} · last seen ${escapeHtml(formatTimeAgo(new Date(selected.last_seen || selected.timestamp || Date.now())))}</div>
      <div class="flex flex-wrap gap-2">${renderWatchdogMetricChips(selected.compact_metrics, 8)}</div>
      <div class="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-xs text-slate-300">
        <div><span class="text-slate-500">Actionable state:</span> ${escapeHtml(formatWatchdogLabel(selected.actionable_state || "review_recent_window"))}</div>
        <div class="mt-1"><span class="text-slate-500">Suggested action:</span> ${escapeHtml(selected.suggested_action || "Review the recent evidence before changing strategy settings.")}</div>
        <div class="mt-1"><span class="text-slate-500">Source context:</span> ${escapeHtml(formatWatchdogMetricValue(selected.source_context || {}))}</div>
      </div>
    </div>
  `;
}


function applyWatchdogHubData(data) {
  watchdogHubState.data = data || {
    active_issues: [],
    recent_events: [],
    opportunity_funnel: {
      updated_at: null,
      snapshot: {
        watch: 0,
        armed: 0,
        trigger_ready: 0,
        late: 0,
        bot_count: 0,
        included_statuses: [],
      },
      follow_through: {
        window_sec: 0,
        executed: 0,
        blocked: 0,
        opportunities: 0,
        trigger_to_execute_rate: null,
      },
      blocked_reasons: [],
      repeat_failures: [],
      structural_untradeable: [],
    },
    watchdog_cards: [],
    available_filters: {
      severities: ["CRITICAL", "ERROR", "WARN", "INFO"],
      watchdog_types: [],
      bots: [],
      symbols: [],
    },
    overview: {
      total_active_issues: 0,
      active_counts: { critical: 0, high: 0, medium: 0, low: 0 },
      affected_bots_count: 0,
      affected_symbols_count: 0,
      top_blocker_category: null,
      top_watchdog_category: null,
      most_noisy_watchdog: null,
    },
    runtime_integrity: null,
    insights: [],
    updated_at: null,
    performance_baseline: null,
  };
  renderWatchdogHub();
}






function getTriageRuntimeBot(botId) {
  return (window._lastBots || []).find((bot) => String(bot?.id || "") === String(botId || "")) || null;
}


function beginBotTriageStaticAction(botId, actionType) {
  const item = (botTriageState?.data?.items || []).find((row) => String(row?.bot_id || "") === String(botId || ""));
  if (!item) return;
  const runtimeStatus = String(item?.source_signals?.runtime_status || "").trim().toLowerCase();
  const baseConfig = {
    botId,
    actionType,
    title: "Confirm Action",
    lines: [],
    confirmLabel: "Confirm",
    confirmTone: "default",
  };
  if (actionType === "pause") {
    baseConfig.title = "Pause Bot";
    baseConfig.lines = [
      "This uses the standard pause flow.",
      "It pauses the bot and preserves reduce-only exits.",
    ];
    baseConfig.confirmLabel = runtimeStatus === "running" ? "Pause Bot" : "Confirm";
    baseConfig.confirmTone = "danger";
  } else if (actionType === "pause_cancel_pending") {
    baseConfig.title = "Pause + Cancel Pending";
    baseConfig.lines = [
      "This uses the safe pause flow and cancels pending opening orders only.",
      "Reduce-only exits are preserved.",
    ];
    baseConfig.confirmLabel = "Pause + Cancel Pending";
    baseConfig.confirmTone = "danger";
  } else if (actionType === "dismiss") {
    baseConfig.title = "Dismiss Recommendation";
    baseConfig.lines = [
      `Hide this ${String(item.verdict || "").toUpperCase()} recommendation until the verdict changes.`,
    ];
    baseConfig.confirmLabel = "Dismiss";
  } else if (actionType === "snooze") {
    baseConfig.title = "Snooze Recommendation";
    baseConfig.lines = [
      "Hide this recommendation for 1 hour.",
    ];
    baseConfig.confirmLabel = "Snooze 1h";
  } else {
    return;
  }
  botTriageState.confirmation = baseConfig;
  renderBotTriage();
}

async function beginBotTriagePreset(botId, preset) {
  try {
    const response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/apply-preset`, {
      method: "POST",
      body: JSON.stringify({ preset, preview: true }),
    });
    const preview = response?.preview || {};
    botTriageState.confirmation = {
      botId,
      actionType: `preset:${preset}`,
      preset,
      title: preview.title || "Confirm Preset",
      lines: Array.isArray(preview.summary_lines) ? preview.summary_lines : [],
      confirmLabel: preset === "reduce_risk" ? "Apply Safe Preset" : "Enable Session Timer Preset",
      confirmTone: preset === "reduce_risk" ? "accent" : "default",
    };
    renderBotTriage();
  } catch (error) {
    showToast(`Unable to load preset preview: ${error.message}`, "error");
  }
}

function cancelBotTriageAction() {
  if (botTriageState.actionInFlight) return;
  botTriageState.confirmation = null;
  renderBotTriage();
}

function buildBotTriageActionButtons(item) {
  const botId = String(item?.bot_id || "").trim();
  if (!botId) return "";
  const encodedBotId = JSON.stringify(botId);
  const encodedSymbol = JSON.stringify(String(item?.symbol || ""));
  const verdict = String(item?.verdict || "").trim().toUpperCase();
  const runtimeStatus = String(item?.source_signals?.runtime_status || "").trim().toLowerCase();
  const buttons = [];
  if (verdict === "PAUSE" && runtimeStatus === "running") {
    buttons.push(`<button type="button" onclick='beginBotTriageStaticAction(${encodedBotId}, "pause")' class="${getBotTriageActionButtonClass("danger")}">Pause Bot</button>`);
    buttons.push(`<button type="button" onclick='beginBotTriageStaticAction(${encodedBotId}, "pause_cancel_pending")' class="${getBotTriageActionButtonClass()}">Pause + Cancel Pending</button>`);
  } else if (verdict === "REDUCE") {
    buttons.push(`<button type="button" onclick='beginBotTriagePreset(${encodedBotId}, "reduce_risk")' class="${getBotTriageActionButtonClass("accent")}">Apply Safe Preset</button>`);
    buttons.push(`<button type="button" onclick='beginBotTriagePreset(${encodedBotId}, "sleep_session")' class="${getBotTriageActionButtonClass()}">Enable Session Timer Preset</button>`);
    buttons.push(`<button type="button" onclick='editBot(${encodedBotId})' class="${getBotTriageActionButtonClass()}">Open Settings</button>`);
  } else if (verdict === "REVIEW") {
    buttons.push(`<button type="button" onclick='editBot(${encodedBotId})' class="${getBotTriageActionButtonClass("accent")}">Open Settings</button>`);
    buttons.push(`<button type="button" onclick='openBotTriageDiagnostics(${encodedBotId}, ${encodedSymbol})' class="${getBotTriageActionButtonClass()}">Open Diagnostics</button>`);
  } else {
    buttons.push(`<button type="button" onclick='beginBotTriageStaticAction(${encodedBotId}, "dismiss")' class="${getBotTriageActionButtonClass()}">Dismiss</button>`);
    buttons.push(`<button type="button" onclick='beginBotTriageStaticAction(${encodedBotId}, "snooze")' class="${getBotTriageActionButtonClass()}">Snooze</button>`);
  }
  return buttons.join("");
}



function applyBotTriageData(data) {
  botTriageState.data = data || { summary_counts: {}, items: [], generated_at: null, suppressed_count: 0 };
  if (botTriageState.confirmation) {
    const botStillVisible = ((botTriageState.data || {}).items || []).some(
      (item) => String(item?.bot_id || "") === String(botTriageState.confirmation?.botId || "")
    );
    if (!botStillVisible) {
      botTriageState.confirmation = null;
      botTriageState.actionInFlight = false;
    }
  }
  renderBotTriage();
}

async function refreshBotTriage() {
  const data = await fetchJSON("/bot-triage");
  applyBotTriageData(data);
  return data;
}






function cancelBotConfigAdvisorApply() {
  if (botConfigAdvisorState.actionInFlight) return;
  botConfigAdvisorState.confirmation = null;
  renderBotConfigAdvisor();
}



function applyBotConfigAdvisorData(data) {
  botConfigAdvisorState.data = data || { summary_counts: {}, items: [], generated_at: null };
  if (botConfigAdvisorState.confirmation) {
    const botStillVisible = ((botConfigAdvisorState.data || {}).items || []).some(
      (item) => String(item?.bot_id || "") === String(botConfigAdvisorState.confirmation?.botId || "")
    );
    const botStillSupportsApply = ((botConfigAdvisorState.data || {}).items || []).some(
      (item) => String(item?.bot_id || "") === String(botConfigAdvisorState.confirmation?.botId || "") && Boolean(item?.supports_apply)
    );
    if (!botStillVisible || !botStillSupportsApply) {
      botConfigAdvisorState.confirmation = null;
      botConfigAdvisorState.actionInFlight = false;
    }
  }
  renderBotConfigAdvisor();
}

async function refreshBotConfigAdvisor() {
  const data = await fetchJSON("/bot-config-advisor");
  applyBotConfigAdvisorData(data);
  return data;
}

async function refreshWatchdogHub() {
  const data = await fetchJSON("/watchdog-center");
  applyWatchdogHubData(data);
  return data;
}


// =============================================================================
// Bot list filter
// =============================================================================
let activeBotFilter = "running";

function filterBotList(cat) {
  activeBotFilter = cat;
  // Toggle active chip style
  document.querySelectorAll(".bot-filter-chip").forEach(btn => {
    btn.classList.toggle("bot-filter-chip--active", btn.getAttribute("data-filter") === cat);
  });
  applyActiveBotFilters();
}

let activeBotSearchQuery = "";

function filterBotListBySearch(query) {
  activeBotSearchQuery = String(query || "").trim().toUpperCase();
  applyActiveBotFilters();
}

function clearActiveBotSearch() {
  const searchInput = $("active-bots-search");
  if (searchInput) searchInput.value = "";
  filterBotListBySearch("");
}

function focusActiveBotsWorkingNow() {
  filterBotList("running");
}

function applyActiveBotFilters() {
  const container = $("active-bots-list");
  if (!container) return;
  container.querySelectorAll("[data-ready-cat]").forEach(card => {
    // Keep rows visible during pending lifecycle actions to prevent flicker
    const botId = card.getAttribute("data-bot-id");
    if (botId && pendingBotActions[botId]) {
      card.style.display = "";
      return;
    }
    const matchFilter = doesActiveBotMatchFilterState(
      card.getAttribute("data-status"),
      card.getAttribute("data-ready-cat"),
      activeBotFilter,
      botId
    );
    const matchSearch = !activeBotSearchQuery ||
      (card.getAttribute("data-symbol") || "").toUpperCase().includes(activeBotSearchQuery) ||
      (card.getAttribute("data-bot-id") || "").toUpperCase().includes(activeBotSearchQuery);
    card.style.display = activeBotSearchQuery
      ? (matchSearch ? "" : "none")
      : ((matchFilter && matchSearch) ? "" : "none");
  });
}

// =============================================================================
// Backtest UI
// =============================================================================
async function runBacktest(symbol) {
  const btn = $(`btn-backtest-${symbol}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin inline-block mr-1">↻</span> Testing...`;
  }

  // Find the bot for this symbol to get its configuration
  const bot = window._lastBots?.find(b => b.symbol === symbol) || {};
  const gridCount = getConfiguredGridCount(bot);
  const leverage = bot.leverage || 5;
  const investment = bot.investment || 1000;

  try {
    const result = await fetchJSON("/backtest", {
      method: "POST",
      body: JSON.stringify({
        symbol: symbol,
        days: 7,
        capital: investment,
        grid_count: gridCount,
        leverage: leverage,
        investment: investment
      })
    });

    if (result.success) {
      showBacktestModal(result.result);
    } else {
      alert("Backtest failed: " + (result.error || "Unknown error"));
    }
  } catch (e) {
    alert("Backtest error: " + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `🔬 Backtest`;
    }
  }
}


const _emergReadyHistory = (() => {
  try {
    // Clear stale ready history on every page load.
    // Entries will be re-populated ONLY by fresh runtime data.
    localStorage.removeItem("emergReadyHistory");
  } catch {}
  return [];
})();

function _saveEmergReadyHistory() {
  // Only persist currently-ready entries — never save stale signals to localStorage
  try { localStorage.setItem("emergReadyHistory", JSON.stringify(_emergReadyHistory.filter(e => e.still_ready).slice(0, 20))); } catch {}
}

// ── Ready-to-trade mode filters (persisted in localStorage) ──
const READY_MODE_FILTER_DEFS = [
  { key: "long",     label: "Long",
    on:  "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
    cnt: "text-emerald-200" },
  { key: "short",    label: "Short",
    on:  "border-red-500/40 bg-red-500/15 text-red-300",
    cnt: "text-red-200" },
  { key: "neutral_classic_bybit", label: "Classic",
    on:  "border-cyan-500/40 bg-cyan-500/15 text-cyan-300",
    cnt: "text-cyan-200" },
  { key: "neutral",  label: "Dyn Neutral",
    on:  "border-blue-500/40 bg-blue-500/15 text-blue-300",
    cnt: "text-blue-200" },
  { key: "scalp_pnl", label: "Scalp",
    on:  "border-amber-500/40 bg-amber-500/15 text-amber-300",
    cnt: "text-amber-200" },
];
const READY_FILTER_OFF = "border-slate-700 bg-slate-800/50 text-slate-500";

const _readyModeFilters = (() => {
  try {
    const raw = localStorage.getItem("readyModeFilters");
    if (raw) return JSON.parse(raw);
  } catch {}
  const defaults = {};
  READY_MODE_FILTER_DEFS.forEach(d => { defaults[d.key] = true; });
  return defaults;
})();

function _saveReadyModeFilters() {
  try { localStorage.setItem("readyModeFilters", JSON.stringify(_readyModeFilters)); } catch {}
}

function toggleReadyModeFilter(mode) {
  _readyModeFilters[mode] = !_readyModeFilters[mode];
  _saveReadyModeFilters();
  _renderReadyModeFilters();
  const el = $("emergency-ready-list");
  const display = _emergReadyHistory.filter(e => e.still_ready).slice(0, 8);
  _renderReadyList(display, el);
  _updateReadyNavbar();
}

function _getReadyModeCounts() {
  const counts = {};
  READY_MODE_FILTER_DEFS.forEach(d => { counts[d.key] = 0; });
  _emergReadyHistory.forEach(entry => {
    if (!entry.still_ready) return;
    const m = entry.bot_mode || "";
    if (counts[m] !== undefined) counts[m]++;
  });
  return counts;
}


function _passesReadyModeFilter(entry) {
  const mode = entry.bot_mode || "";
  if (!READY_MODE_FILTER_DEFS.some(d => d.key === mode)) return true;
  return _readyModeFilters[mode] !== false;
}

function _fmtReadyPrice(p) {
  if (!p || !Number.isFinite(p)) return "";
  if (p >= 100) return p.toFixed(2);
  if (p >= 1) return p.toFixed(3);
  if (p >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}

function buildReadyTradeSymbolContext(bots) {
  const context = new Map();
  (bots || []).forEach((bot) => {
    const symbol = String(bot?.symbol || "").trim().toUpperCase();
    if (!symbol) return;
    const botId = String(bot?.id || "").trim();
    const status = String(bot?.status || "").trim().toLowerCase();
    let item = context.get(symbol);
    if (!item) {
      item = { activeIds: new Set() };
      context.set(symbol, item);
    }
    if (botId && ["running", "paused", "recovering", "flash_crash_paused"].includes(status)) {
      item.activeIds.add(botId);
    }
  });
  return context;
}




function updateEmergencyReadyHistory(readyBots, symbolContext = null) {
  const el = $("emergency-ready-list");
  const now = new Date();
  const readyKeys = new Set(readyBots.map((bot) => {
    const botId = String(bot?.id || "").trim();
    return botId ? `bot:${botId}` : `symbol:${String(bot?.symbol || "").trim().toUpperCase()}`;
  }));

  // Mark existing entries as not ready if they dropped off
  for (const entry of _emergReadyHistory) {
    const entryKey = entry.bot_id
      ? `bot:${String(entry.bot_id).trim()}`
      : `symbol:${String(entry.symbol || "").trim().toUpperCase()}`;
    if (!readyKeys.has(entryKey)) entry.still_ready = false;
  }

  // Add new ready bots or re-activate existing ones
  for (const bot of readyBots) {
    const botId = String(bot?.id || "").trim();
    const symbol = String(bot?.symbol || "").trim();
    const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
    const existing = _emergReadyHistory.find((entry) => {
      if (botId && String(entry?.bot_id || "").trim() === botId) return true;
      return !entry?.bot_id && String(entry?.symbol || "").trim().toUpperCase() === symbol.toUpperCase();
    });
    const setup = getSetupReadiness(bot);
    let dir = normalizeMarketStateHint(setup.direction || bot?.price_action_direction || bot?.mode);
    if (dir === "neutral" && _prevReadyBotDirections[botId]) dir = _prevReadyBotDirections[botId];
    if (dir !== "neutral") _prevReadyBotDirections[botId] = dir;
    const score = pickFiniteReadinessScore(setup.score);
    const price = parseFloat(bot?.mark_price) || parseFloat(bot?.market_data_price) || parseFloat(bot?.exchange_mark_price) || parseFloat(bot?.current_price) || 0;
    const botMode = normalizeBotModeValue(bot?.configured_mode || bot?.mode || "neutral");
    if (existing) {
      if (!existing.still_ready) {
        existing.readyAt = now;   // update time when coin comes back
      }
      existing.still_ready = true;
      existing.direction = dir;
      if (Number.isFinite(score)) existing.score = score;
      existing.bot_id = botId || existing.bot_id || "";
      existing.bot_status = String(bot?.status || "").trim().toLowerCase();
      existing.bot_mode = botMode;
      existing.source_label = sourceMeta?.label || "";
      existing.source_detail = sourceMeta?.detail || "";
      if (price > 0) existing.entry_price = price;  // always refresh entry price while ready
    } else {
      _emergReadyHistory.unshift({
        symbol,
        bot_id: botId,
        bot_status: String(bot?.status || "").trim().toLowerCase(),
        bot_mode: botMode,
        direction: dir,
        score: Number.isFinite(score) ? score : null,
        readyAt: now,
        still_ready: true,
        entry_price: price || null,
        source_label: sourceMeta?.label || "",
        source_detail: sourceMeta?.detail || "",
      });
    }
  }

  // Sort: active (still_ready) first, then by readyAt descending within each group
  _emergReadyHistory.sort((a, b) => {
    if (a.still_ready !== b.still_ready) return b.still_ready ? 1 : -1;
    return b.readyAt - a.readyAt;
  });
  if (_emergReadyHistory.length > 20) _emergReadyHistory.length = 20;
  _saveEmergReadyHistory();

  // Only display actively-ready entries — never show stale/expired signals
  const display = _emergReadyHistory.filter(e => e.still_ready).slice(0, 8);
  _renderReadyList(display, el);



  // Update mode filter chips and navbar
  _renderReadyModeFilters();
  _updateReadyNavbar();
}

// ── Navbar ready-to-trade notification ──

function _updateReadyNavbar() {
  const activeEntries = _emergReadyHistory.filter(e => e.still_ready);
  const filteredActive = activeEntries.filter(e => _passesReadyModeFilter(e));
  const count = filteredActive.length;
  const badge = $("ready-notif-count");
  const dropdownCount = $("ready-dropdown-count");
  const dropdownList = $("ready-dropdown-list");

  if (badge) {
    badge.textContent = String(count);
    if (count > 0) {
      badge.className = "ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full bg-red-500 text-white ready-notif-flash";
    } else {
      badge.className = "ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full bg-slate-900 text-slate-400 border border-slate-600";
    }
  }
  if (dropdownCount) dropdownCount.textContent = count ? `${count} active` : "0";

  if (dropdownList) {
    const top5 = filteredActive.slice(0, 5);
    if (!top5.length) {
      dropdownList.innerHTML = '<span class="text-xs text-slate-600 block py-2 text-center">No setups ready</span>';
      return;
    }
    dropdownList.innerHTML = top5.map(entry => {
      const dirLabel = entry.direction === "long" ? "LONG" : entry.direction === "short" ? "SHORT" : "NEUTRAL";
      const dirClass = entry.direction === "long" ? "text-emerald-400" : entry.direction === "short" ? "text-red-400" : "text-cyan-400";
      const priceStr = _fmtReadyPrice(entry.entry_price);
      const time = entry.readyAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return `<div class="flex items-center justify-between py-1.5 px-1 rounded hover:bg-slate-800/60 transition">
        <span class="flex items-center gap-1.5 min-w-0">
          <span class="emerg-ready-beacon-sm"></span>
          <span class="font-semibold text-white text-xs">${escapeHtml(entry.symbol)}</span>
          ${_readyModeBadge(entry.bot_mode)}
          ${priceStr ? `<span class="text-[10px] text-amber-300">@${priceStr}</span>` : ""}
        </span>
        <span class="flex items-center gap-1.5">
          <span class="${dirClass} font-bold text-[10px]">${dirLabel}</span>
          ${Number.isFinite(entry.score) ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-900/40 text-emerald-300 font-semibold">${entry.score.toFixed(1)}</span>` : ""}
          <span class="text-[9px] text-slate-500">${time}</span>
        </span>
      </div>`;
    }).join("");
  }
}

function toggleReadyDropdown() {
  const dd = $("ready-dropdown");
  if (!dd) return;
  dd.classList.toggle("hidden");
}

// Close dropdown when clicking outside
document.addEventListener("click", function(e) {
  const dd = $("ready-dropdown");
  const btn = $("btnReadyNotif");
  if (dd && btn && !btn.contains(e.target) && !dd.contains(e.target)) {
    dd.classList.add("hidden");
  }
});

let _prevReadyBotIds = new Set();
let _prevReadyBotDirections = {};

function updateRunningBotsStatus(bots) {
  const container = $("running-bots-list");
  if (!container) return;

  const runningBots = bots.filter(b => b.status === "running");

  if (runningBots.length === 0) {
    setElementHtmlIfChanged(container, '<span class="text-xs text-slate-600">No bots running</span>');
    return;
  }

  const runningMarkup = runningBots.map(bot => {
    const mode = (bot.mode || "neutral").toLowerCase();
    const symbol = bot.symbol;
    const rangeMode = bot.range_mode || "fixed";
    const scalp = bot.scalp_analysis;

    // Determine MARKET STATE (not bot mode)
    let marketState = normalizeMarketStateHint(bot.direction_change_guard_state);  // neutral, long, short
    let stateSource = "";

    if (marketState !== "neutral") {
      stateSource = bot.direction_change_guard_source || "guard";
    }

    // 1. Check scalp_analysis for market condition
    if (marketState === "neutral" && scalp && Object.keys(scalp).length > 0) {
      const scalpMomentum = normalizeMarketStateHint(scalp.momentum);
      marketState = scalpMomentum;
      if (scalpMomentum !== "neutral") {
        stateSource = "momentum";
      } else {
        stateSource = scalp.condition || "analysis";
      }
    }

    // 2. Prefer structured trend_direction from backend (avoid parsing freeform text)
    const trendDirection = normalizeMarketStateHint(bot.trend_direction);
    if (trendDirection === "long") {
      marketState = "long";
      stateSource = "trend";
    } else if (trendDirection === "short") {
      marketState = "short";
      stateSource = "trend";
    }

    // 3. Fallback: For non-scalp bots without analysis, use bot mode as market state
    if (marketState === "neutral" && !stateSource) {
      if (mode === "long") {
        marketState = "long";
        stateSource = "bot_mode";
      } else if (mode === "short") {
        marketState = "short";
        stateSource = "bot_mode";
      }
    }

    // 3. Position info (removed from display — too noisy)

    // Market state colors
    let stateClass = "bg-blue-500";
    let stateIcon = "⚖";
    let stateLabel = "NEUTRAL";

    if (marketState === "long") {
      stateClass = "bg-emerald-500";
      stateIcon = "▲";
      stateLabel = "LONG";
    } else if (marketState === "short") {
      stateClass = "bg-red-500";
      stateIcon = "▼";
      stateLabel = "SHORT";
    }

    // Bot mode label
    let modeShort = mode;
    if (mode === "scalp_pnl") modeShort = "scalp";
    else if (mode === "scalp_market") modeShort = "mkt";

    // Range mode
    const rangeBadge = rangeMode === "dynamic" ? "dynamic" : rangeMode === "trailing" ? "trailing" : "fixed";

    // Timer - show how long bot has been running
    const elapsed = formatElapsed(bot.started_at);
    const runningEarned = formatPnL(bot.session_total_pnl || 0);
    const runningEarnedPerHour = formatPnL(bot.session_profit_per_hour || 0);
    const elapsedAndEarned = elapsed
      ? `<span class="text-xs font-medium text-cyan-300">${elapsed}</span><span class="text-xs text-slate-500">,</span><span class="text-xs font-semibold ${runningEarned.class}">${runningEarned.text}</span>${bot.session_profit_per_hour !== null && bot.session_profit_per_hour !== undefined ? `<span class="text-xs text-slate-500">,</span><span class="text-xs font-semibold ${runningEarnedPerHour.class}">${runningEarnedPerHour.text}/h</span>` : ""}`
      : `<span class="text-xs font-semibold ${runningEarned.class}">${runningEarned.text}</span>`;

    // Readiness score badge (same style as emergency card)
    const readyScore = pickFiniteReadinessScore(getSetupReadiness(bot).score);
    const readyScoreBadge = Number.isFinite(readyScore)
      ? `<span class="text-[9px] px-1.5 py-0.5 rounded border border-emerald-700/40 bg-emerald-900/30 text-emerald-300 font-semibold">${readyScore.toFixed(1)}</span>`
      : "";

    // Build display - show everything as text
    return `<div class="flex flex-col gap-1 p-2.5 rounded bg-slate-800 border border-slate-700 min-w-[152px]">
      <div class="flex items-center justify-between">
        <span class="font-bold text-white text-lg leading-none">${symbol}</span>
        <span class="text-xs font-medium text-slate-300">${modeShort}</span>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ${stateClass} text-white">
          ${stateIcon} ${stateLabel}
        </span>
        ${readyScoreBadge}
        <span class="text-xs font-medium text-slate-400">${rangeBadge}</span>
        ${elapsedAndEarned}
      </div>
      <div class="flex flex-wrap gap-0.5 mt-0.5">
        ${trailingSlBadge(bot)}
        ${upnlSlBadges(bot)}
      </div>
      ${scalp ? `<div class="text-[10px] text-slate-500">${scalp.condition} | ${scalp.volatility} vol</div>` : ''}
    </div>`;
  }).join("");
  setElementHtmlIfChanged(container, runningMarkup);
  // Mirror into mobile container under Open Exposure
  const mobileContainer = $("running-bots-list-mobile");
  if (mobileContainer) setElementHtmlIfChanged(mobileContainer, container.innerHTML);
}

function updateAssetsRecentPnl(logs) {
  const tbody = $("assets-recent-pnl");
  if (!tbody) return;
  if (!logs || logs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="py-2 text-center text-slate-600">No trades yet</td></tr>';
    return;
  }
  const recent = logs.slice().reverse().slice(0, 10);
  tbody.innerHTML = recent.map((log, i) => {
    const pnl = formatPnL(log.realized_pnl);
    const bal = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : '-';
    const opacity = [1, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55][i] || 0.55;
    const mode = log.bot_mode || log.side || '-';
    return `<tr style="opacity:${opacity}">
      <td class="py-0.5 pr-2 text-slate-400 whitespace-nowrap">${formatTime(log.time)}</td>
      <td class="py-0.5 pr-2 text-white font-medium">${log.symbol}</td>
      <td class="py-0.5 pr-2 text-right ${pnl.class} font-semibold">${pnl.text}</td>
      <td class="py-0.5 pr-2 text-right text-slate-300">${bal}</td>
      <td class="py-0.5 text-right text-slate-300 font-medium">${mode}</td>
    </tr>`;
  }).join("");
}

async function refreshPnl() {
  const cacheBust = `_ts=${Date.now()}`;
  const data = await fetchJSON(`/pnl/log?${cacheBust}`, { cache: "no-store" });
  const logs = data.logs || [];
  const today = data.today || {};
  registerNewPnlEvents(logs, today);

  const currentIds = new Set(logs.map(log => log.id));
  if (previousValues.pnlLogIds.size > 0) {
    for (const log of logs) {
      if (!previousValues.pnlLogIds.has(log.id)) {
        const pnlValue = parseFloat(log.realized_pnl || 0);
        if (pnlValue > 0) playProfitSound();
        else if (pnlValue < 0) playLossSound();
      }
    }
  }
  previousValues.pnlLogIds = currentIds;

  const todayNet = formatPnL(today.net);
  const pnlTodayNetEl = $("pnl-today-net");
  if (pnlTodayNetEl) {
    pnlTodayNetEl.textContent = todayNet.text;
    pnlTodayNetEl.className = `font-medium ${todayNet.class}`;
  }
  const pnlTodayWinsEl = $("pnl-today-wins");
  if (pnlTodayWinsEl) pnlTodayWinsEl.textContent = today.wins || 0;
  const pnlTodayLossesEl = $("pnl-today-losses");
  if (pnlTodayLossesEl) pnlTodayLossesEl.textContent = today.losses || 0;
  updateValueWithFlash("summary-today-net", parseFloat(today.net || 0), formatPnL, "todayNet");
  if ($("summary-today-wins")) $("summary-today-wins").textContent = today.wins || 0;
  if ($("summary-today-losses")) $("summary-today-losses").textContent = today.losses || 0;
  lastPnlRefreshAt = Date.now();

  // Update all-time Closed PnL stats (fetch from stats endpoint)
  try {
    const allStats = await fetchJSON(`/pnl/stats?period=all&${cacheBust}`, { cache: "no-store" });
    const closedNetEl = document.getElementById('closed-pnl-net');
    const closedWrEl = document.getElementById('closed-pnl-winrate');
    const closedPfEl = document.getElementById('closed-pnl-pf');
    const closedProfitEl = document.getElementById('closed-pnl-profit');
    const closedLossEl = document.getElementById('closed-pnl-loss');

    if (closedNetEl) {
      closedNetEl.textContent = `$${allStats.net_pnl.toFixed(2)}`;
      closedNetEl.className = 'font-medium ' + (allStats.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400');
    }
    if (closedWrEl) closedWrEl.textContent = `${allStats.win_rate}%`;
    if (closedPfEl) closedPfEl.textContent = allStats.profit_factor === '∞' ? '∞' : allStats.profit_factor;
    if (closedProfitEl) closedProfitEl.textContent = allStats.total_profit.toFixed(2);
    if (closedLossEl) closedLossEl.textContent = allStats.total_loss.toFixed(2);
  } catch (err) {
    console.debug('Failed to fetch closed PnL stats:', err);
  }

  // Update recent closed PnL in Assets card
  updateAssetsRecentPnl(logs);

  const tbody = $("pnl-body");
  if (!tbody) {
    // Realized Flow section removed; still update operator watch
    renderMobilePnlData([]);
    updateOperatorWatch();
    return;
  }
  if (logs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="pnl-empty-state">
          <span class="pnl-empty-state__icon">◎</span>
          <strong>No closed PnL records</strong>
          Realized outcomes will populate here automatically after trades close.
        </td>
      </tr>
    `;
    renderMobilePnlData([]);
    return;
  }

  const recentLogs = logs.slice().reverse().slice(0, 50);
  tbody.innerHTML = recentLogs.map(log => {
    const pnl = formatPnL(log.realized_pnl);
    const balance = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : '-';
    // Calculate uptime: time from bot_started_at to trade time
    const uptime = formatDuration(log.bot_started_at, log.time);
    return `
      <tr class="table-row">
        <td class="px-4 py-3 text-xs text-slate-400">${formatTime(log.time)}</td>
        <td class="px-4 py-3 font-medium text-white">${log.symbol}</td>
        <td class="px-4 py-3"><span class="position-meta-pill">${log.side}</span></td>
        <td class="px-4 py-3 text-right ${pnl.class} font-semibold">${pnl.text}</td>
        <td class="px-4 py-3 text-center text-cyan-300 text-xs font-medium">${uptime}</td>
        <td class="px-4 py-3 text-right text-slate-300">${balance}</td>
      </tr>
    `;
  }).join("");
  renderMobilePnlData(recentLogs);
  updateOperatorWatch();
}

// ============================================================
// Recent Scanned Coins (persists 24 hours in localStorage)
// ============================================================

// const RECENT_SCANS_KEY = 'recentScannedCoins';  // Defined in app_v5.js
// const RECENT_SCANS_MAX_AGE_MS = 24 * 60 * 60 * 1000;  // Defined in app_v5.js

// ============================================================
// Innovation Zone Coins
// ============================================================




/**
 * Get recent scanned coins from localStorage, filtering out expired entries.
 */
function getRecentScans() {
  try {
    const stored = localStorage.getItem(RECENT_SCANS_KEY);
    if (!stored) return [];

    const scans = JSON.parse(stored);
    const now = Date.now();

    // Filter out entries older than 24 hours
    const valid = scans.filter(s => (now - s.timestamp) < RECENT_SCANS_MAX_AGE_MS);

    // If we filtered some out, save the cleaned list
    if (valid.length !== scans.length) {
      localStorage.setItem(RECENT_SCANS_KEY, JSON.stringify(valid));
    }

    return valid;
  } catch (e) {
    console.error('Error reading recent scans:', e);
    return [];
  }
}

// Sync recent scans from server on load (cross-device persistence)
async function _syncRecentScansFromServer() {
  try {
    const serverScans = await fetchJSON("/recent-scans");
    if (!Array.isArray(serverScans) || !serverScans.length) return;
    const localScans = getRecentScans();
    // Merge: server entries not in local get added
    const localSymbols = new Set(localScans.map(s => s.symbol));
    let merged = [...localScans];
    for (const s of serverScans) {
      if (!localSymbols.has(s.symbol)) merged.push(s);
    }
    merged.sort((a, b) => b.timestamp - a.timestamp);
    merged = merged.slice(0, 20);
    localStorage.setItem(RECENT_SCANS_KEY, JSON.stringify(merged));
    renderRecentScans();
  } catch {}
}

function _pushRecentScansToServer(scans) {
  try {
    fetchJSON("/recent-scans", {
      method: "POST",
      body: JSON.stringify(scans),
    }).catch(() => {});
  } catch {}
}

/**
 * Add symbols to recent scans list.
 */
function addRecentScans(symbols) {
  try {
    const scans = getRecentScans();
    const now = Date.now();

    // Parse symbols (could be comma-separated)
    const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(s => s);

    for (const symbol of symbolList) {
      // Remove existing entry for this symbol (we'll re-add with new timestamp)
      const idx = scans.findIndex(s => s.symbol === symbol);
      if (idx !== -1) {
        scans.splice(idx, 1);
      }

      // Add at the beginning
      scans.unshift({ symbol, timestamp: now });
    }

    // Keep only last 20 unique symbols
    const trimmed = scans.slice(0, 20);
    localStorage.setItem(RECENT_SCANS_KEY, JSON.stringify(trimmed));
    _pushRecentScansToServer(trimmed);

    // Update UI
    renderRecentScans();
  } catch (e) {
    console.error('Error saving recent scans:', e);
  }
}

/**
 * Render recent scans as clickable chips.
 */
function getScrollBehavior() {
  return prefersReducedMotion() ? "auto" : "smooth";
}

function getDashboardScrollOffset() {
  const nav = document.querySelector("nav");
  return (nav?.offsetHeight || 0) + 12;
}

function scrollToElementTop(element) {
  if (!element) return;
  const top = window.scrollY + element.getBoundingClientRect().top - getDashboardScrollOffset();
  window.scrollTo({
    top: Math.max(0, top),
    behavior: getScrollBehavior(),
  });
}

function updateFloatingScrollButton(force = false) {
  const button = $("floating-scroll-button");
  const scannerSection = $("neutral-scanner-section");
  const label = $("floating-scroll-label");
  const subtitle = $("floating-scroll-subtitle");
  const icon = $("floating-scroll-icon");
  if (!button || !scannerSection || !label || !subtitle || !icon) return;

  const rect = scannerSection.getBoundingClientRect();
  let nextTarget = floatingScrollButtonState.target || "scanner";
  if (window.scrollY < 60) {
    nextTarget = "scanner";
  } else if (nextTarget !== "top" && rect.top <= window.innerHeight * 0.38) {
    nextTarget = "top";
  } else if (nextTarget === "top" && rect.top > window.innerHeight * 0.56) {
    nextTarget = "scanner";
  }

  if (!force && nextTarget === floatingScrollButtonState.target) return;
  floatingScrollButtonState.target = nextTarget;
  button.dataset.target = nextTarget;

  if (nextTarget === "top") {
    button.setAttribute("aria-label", "Scroll back to the top of the dashboard");
    label.textContent = "Top";
    subtitle.textContent = "Back to dashboard top";
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 19V5m0 0-6 6m6-6 6 6" />';
  } else {
    button.setAttribute("aria-label", "Scroll to the Neutral Scanner");
    label.textContent = "Scanner";
    subtitle.textContent = "Jump to Neutral Scanner";
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M12 5v14m0 0 6-6m-6 6-6-6" />';
  }
}

function handleFloatingScrollButtonClick() {
  const scannerSection = $("neutral-scanner-section");
  if (floatingScrollButtonState.target === "top") {
    window.scrollTo({ top: 0, behavior: getScrollBehavior() });
    return;
  }
  scrollToElementTop(scannerSection);
}

function initActiveBotsJumpButton() {
  const button = $("floating-active-bots-button");
  const activeBotsSection = $("active-bots-table-section");
  if (!button || !activeBotsSection) return;

  button.addEventListener("click", () => {
    scrollToElementTop(activeBotsSection);
  });
}

function initFloatingScrollButton() {
  const button = $("floating-scroll-button");
  if (!button) return;

  button.addEventListener("click", handleFloatingScrollButtonClick);

  const requestUpdate = () => {
    if (floatingScrollButtonState.ticking) return;
    floatingScrollButtonState.ticking = true;
    window.requestAnimationFrame(() => {
      floatingScrollButtonState.ticking = false;
      updateFloatingScrollButton();
    });
  };

  window.addEventListener("scroll", requestUpdate, { passive: true });
  window.addEventListener("resize", requestUpdate);
  updateFloatingScrollButton(true);
}

function scanSymbol(symbol, shouldScroll = true) {
  const input = $('scanner-symbols');
  const scannerSection = $('neutral-scanner-section');

  if (input) {
    input.value = symbol;
    if (typeof input.focus === "function") {
      input.focus({ preventScroll: true });
    }
    if (typeof input.select === "function") {
      input.select();
    }
  }

  if (shouldScroll && scannerSection) {
    scrollToElementTop(scannerSection);
  }

  window.setTimeout(() => {
    scanNeutral();
  }, shouldScroll && scannerSection && !prefersReducedMotion() ? 120 : 0);
}



/**
 * Clear all recent scans.
 */
function clearRecentScans() {
  localStorage.removeItem(RECENT_SCANS_KEY);
  renderRecentScans();
}



function hydrateSharedBotConfigFields(
  getEl,
  bot,
  {
    booleanFields = SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
    auditContext = "main",
    tickSizeRaw = "",
  } = {},
) {
  const normalizedMode = normalizeBotModeValue(bot.mode || "neutral");
  const autoPilotUniverseMode = String(bot.auto_pilot_universe_mode || "default_safe").trim() || "default_safe";
  const configuredGridCount = getConfiguredGridCount(bot);

  if (getEl("bot-id")) getEl("bot-id").value = bot.id || "";
  if (getEl("bot-settings-version")) {
    getEl("bot-settings-version").value = bot.settings_version != null ? String(bot.settings_version) : "";
  }
  if (getEl("bot-symbol")) getEl("bot-symbol").value = bot.symbol || "";
  if (getEl("bot-lower")) {
    getEl("bot-lower").value = formatPriceForBotFormDisplay(bot.lower_price, tickSizeRaw);
    getEl("bot-lower").step = tickSizeRaw || "any";
    getEl("bot-lower").placeholder = tickSizeRaw || "0.00";
  }
  if (getEl("bot-upper")) {
    getEl("bot-upper").value = formatPriceForBotFormDisplay(bot.upper_price, tickSizeRaw);
    getEl("bot-upper").step = tickSizeRaw || "any";
    getEl("bot-upper").placeholder = tickSizeRaw || "0.00";
  }
  if (getEl("bot-grid-distribution")) getEl("bot-grid-distribution").value = bot.grid_distribution || "clustered";
  if (getEl("bot-grids")) getEl("bot-grids").value = configuredGridCount;
  if (getEl("bot-investment")) getEl("bot-investment").value = formatUsdtInputValue(bot.investment);
  if (getEl("bot-leverage")) getEl("bot-leverage").value = bot.leverage || 3;
  if (getEl("bot-mode")) getEl("bot-mode").value = normalizedMode;
  if (getEl("bot-mode-policy")) {
    getEl("bot-mode-policy").value = normalizeModePolicyValue(bot.mode_policy, bot);
  }
  if (getEl("bot-profile")) getEl("bot-profile").value = bot.profile || "normal";
  if (getEl("bot-auto-stop")) getEl("bot-auto-stop").value = bot.auto_stop || "";
  if (getEl("bot-balance-target")) getEl("bot-balance-target").value = bot.auto_stop_target_usdt || "";
  if (getEl("bot-auto-pilot-universe-mode")) getEl("bot-auto-pilot-universe-mode").value = autoPilotUniverseMode;

  const trailingActiv = getEl("bot-trailing-sl-activation");
  if (trailingActiv) {
    trailingActiv.value = bot.trailing_sl_activation_pct != null ? (bot.trailing_sl_activation_pct * 100).toFixed(2) : "";
  }
  const trailingDist = getEl("bot-trailing-sl-distance");
  if (trailingDist) {
    trailingDist.value = bot.trailing_sl_distance_pct != null ? (bot.trailing_sl_distance_pct * 100).toFixed(2) : "";
  }

  const rangeModeSelect = getEl("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.value = bot.range_mode || "fixed";
  }

  const tpInput = getEl("bot-tp-pct");
  if (tpInput) {
    const tp = bot.tp_pct;
    if (typeof tp === "number" && !isNaN(tp) && tp > 0 && tp < 1) {
      tpInput.value = (tp * 100).toFixed(2);
    } else {
      tpInput.value = "";
    }
  }

  const volGateThresh = getEl("bot-volatility-gate-threshold");
  if (volGateThresh) {
    volGateThresh.value = bot.neutral_volatility_gate_threshold_pct || 5.0;
  }

  const quickProfitTarget = getEl("bot-quick-profit-target");
  if (quickProfitTarget) {
    quickProfitTarget.value = bot.quick_profit_target != null ? String(bot.quick_profit_target) : "";
  }
  const quickProfitClosePct = getEl("bot-quick-profit-close-pct");
  if (quickProfitClosePct) {
    quickProfitClosePct.value = bot.quick_profit_close_pct != null ? String(bot.quick_profit_close_pct * 100) : "";
  }
  const quickProfitCooldown = getEl("bot-quick-profit-cooldown");
  if (quickProfitCooldown) {
    quickProfitCooldown.value = bot.quick_profit_cooldown != null ? String(bot.quick_profit_cooldown) : "";
  }

  const sessionTimerEnabled = getEl("bot-session-timer-enabled");
  if (sessionTimerEnabled) {
    sessionTimerEnabled.checked = !!bot.session_timer_enabled;
  }
  const sessionStartAt = getEl("bot-session-start-at");
  if (sessionStartAt) {
    sessionStartAt.value = formatDateTimeLocalInputValue(bot.session_start_at);
  }
  const sessionStopAt = getEl("bot-session-stop-at");
  if (sessionStopAt) {
    sessionStopAt.value = formatDateTimeLocalInputValue(bot.session_stop_at);
  }
  const sessionPreStop = getEl("bot-session-no-new-entries-before-stop-min");
  if (sessionPreStop) {
    sessionPreStop.value = bot.session_no_new_entries_before_stop_min != null
      ? String(bot.session_no_new_entries_before_stop_min)
      : "15";
  }
  const sessionEndMode = getEl("bot-session-end-mode");
  if (sessionEndMode) {
    sessionEndMode.value = bot.session_end_mode || "hard_stop";
  }
  const sessionGraceMin = getEl("bot-session-green-grace-min");
  if (sessionGraceMin) {
    sessionGraceMin.value = bot.session_green_grace_min != null
      ? String(bot.session_green_grace_min)
      : "5";
  }
  const sessionForceCloseCap = getEl("bot-session-force-close-max-loss-pct");
  if (sessionForceCloseCap) {
    sessionForceCloseCap.value = bot.session_force_close_max_loss_pct != null
      ? String(bot.session_force_close_max_loss_pct)
      : "";
  }
  const sessionCancelPending = getEl("bot-session-cancel-pending-orders-on-end");
  if (sessionCancelPending) {
    sessionCancelPending.checked = bot.session_cancel_pending_orders_on_end !== false;
  }
  const sessionReduceOnly = getEl("bot-session-reduce-only-on-end");
  if (sessionReduceOnly) {
    sessionReduceOnly.checked = !!bot.session_reduce_only_on_end;
  }

  applyBotConfigBooleanFields(getEl, bot, booleanFields);
  auditRenderedBotConfigBooleanFields(getEl, bot, booleanFields, auditContext);

  return {
    configuredGridCount,
    normalizedMode,
  };
}


















function updateAutoPilotUniverseModeHelp(scope = "main") {
  const modeSelect = getScopedElement(scope, "bot-auto-pilot-universe-mode");
  const helpText = getScopedElement(scope, "bot-auto-pilot-universe-help");
  if (!modeSelect || !helpText) return;

  const mode = String(modeSelect.value || "default_safe").trim().toLowerCase();
  if (mode === "aggressive_full") {
    helpText.textContent = "High-risk mode: broader symbol coverage, relaxed novelty/new-listing filters, and wider volatility limits.";
    helpText.className = "text-[11px] text-amber-300 mt-2";
    return;
  }

  helpText.textContent = "Keeps the current production-safe Auto-Pilot universe and filters.";
  helpText.className = "text-[11px] text-slate-400 mt-2";
}

function updateAutoPilotVisibility(scope = "main") {
  const autoPilotCheckbox = getScopedElement(scope, "bot-auto-pilot");
  if (!autoPilotCheckbox) return;

  const isAuto = autoPilotCheckbox.checked;
  const autopilotInfo = getScopedElement(scope, "autopilot-info");
  if (autopilotInfo) autopilotInfo.classList.toggle("hidden", !isAuto);
  const universeModeSelect = getScopedElement(scope, "bot-auto-pilot-universe-mode");
  if (universeModeSelect) {
    universeModeSelect.disabled = !isAuto;
    universeModeSelect.style.opacity = isAuto ? "1" : "0.6";
  }
  updateAutoPilotUniverseModeHelp(scope);

  // Only lock INPUT fields during Auto-Pilot (not buttons!)
  const lockFields = [
    "bot-symbol", "bot-lower", "bot-upper", "bot-mode", "bot-profile",
    "bot-range-mode", "bot-grid-distribution", "bot-grids", "bot-auto-direction",
    "bot-breakout-confirmed-entry"
  ];

  lockFields.forEach(id => {
    const el = getScopedElement(scope, id);
    if (el) {
      el.disabled = isAuto;
      el.style.opacity = isAuto ? "0.4" : "1";
    }
  });

  // Dim labels for locked fields (but NOT button containers)
  lockFields.forEach(id => {
    const el = getScopedElement(scope, id);
    if (el) {
      const label = el.closest('div')?.querySelector('label');
      if (label) label.style.opacity = isAuto ? "0.4" : "1";
    }
  });

  updateModeScopedBotOptions(scope);
}

function updateSessionTimerVisibility(scope = "main") {
  const enabled = !!getScopedElement(scope, "bot-session-timer-enabled")?.checked;
  const fields = getScopedElement(scope, "bot-session-timer-fields");
  const graceRow = getScopedElement(scope, "bot-session-green-grace-row");
  const endMode = String(getScopedElement(scope, "bot-session-end-mode")?.value || "hard_stop").trim().toLowerCase();

  if (fields) {
    fields.classList.toggle("opacity-60", !enabled);
  }

  [
    "bot-session-start-at",
    "bot-session-stop-at",
    "bot-session-no-new-entries-before-stop-min",
    "bot-session-end-mode",
    "bot-session-green-grace-min",
    "bot-session-force-close-max-loss-pct",
    "bot-session-cancel-pending-orders-on-end",
    "bot-session-reduce-only-on-end",
  ].forEach((id) => {
    const el = getScopedElement(scope, id);
    if (!el) return;
    el.disabled = !enabled;
  });

  if (graceRow) {
    graceRow.classList.toggle("hidden", !enabled || endMode !== "green_grace_then_stop");
  }
}






function roundUpToTwoDecimals(value) {
  if (!isFinite(value) || value <= 0) return 0;
  return Math.ceil(value * 100) / 100;
}

function roundUpLeverageRequirement(value) {
  if (!isFinite(value) || value <= 1) return 1;
  return Math.ceil(value - 1e-9);
}

function calculateRequiredGrossInvestment(requiredNotional, leverage, reserveUsePct, reservePct, reserveUsdFixed) {
  if (!isFinite(requiredNotional) || requiredNotional <= 0 || !isFinite(leverage) || leverage <= 0) {
    return 0;
  }
  if (reserveUsePct) {
    const usableRatio = 1 - Math.max(0, Math.min(0.95, reservePct || 0));
    if (usableRatio <= 0) return Infinity;
    return requiredNotional / (leverage * usableRatio);
  }
  return (requiredNotional / leverage) + Math.max(0, reserveUsdFixed || 0);
}

function decimalsFromStep(stepRaw) {
  const raw = String(stepRaw || "").trim();
  if (!raw) return null;
  if (raw.toLowerCase().includes("e-")) {
    const exp = parseInt(raw.split("e-")[1], 10);
    return Number.isFinite(exp) ? exp : null;
  }
  if (!raw.includes(".")) return 0;
  return raw.split(".")[1].replace(/0+$/, "").length || 0;
}





function applyPriceInputPrecision(spec, { reformatExisting = false } = {}) {
  const lowerInput = $("bot-lower");
  const upperInput = $("bot-upper");
  if (!lowerInput || !upperInput || !spec) return;

  const tickSizeRaw = spec.tick_size_raw || spec.tick_size || "";
  if (!tickSizeRaw) return;

  lowerInput.step = tickSizeRaw;
  upperInput.step = tickSizeRaw;
  lowerInput.placeholder = tickSizeRaw;
  upperInput.placeholder = tickSizeRaw;

  if (!reformatExisting) return;
  if (document.activeElement === lowerInput || document.activeElement === upperInput) return;

  const lowerValue = parseFloat(lowerInput.value);
  const upperValue = parseFloat(upperInput.value);
  if (!isFinite(lowerValue) || !isFinite(upperValue)) return;

  botFormSuppressRangeTracking = true;
  lowerInput.value = formatPriceForBybitInput(lowerValue, tickSizeRaw);
  upperInput.value = formatPriceForBybitInput(upperValue, tickSizeRaw);
  botFormSuppressRangeTracking = false;
}


function applyAutoInvestmentFromBalance({ force = false } = {}) {
  const investmentInput = $("bot-investment");
  if (!investmentInput) return false;
  if (!force && botFormAutoInvestmentManualOverride) {
    return false;
  }

  const balance = getBotFormTradingBalance();
  if (!(balance > 0)) return false;

  const currentValue = parseFloat(investmentInput.value) || 0;
  if (Math.abs(currentValue - balance) < 0.005) return false;

  botFormSuppressSizingTracking = true;
  investmentInput.value = formatUsdtInputValue(balance);
  botFormSuppressSizingTracking = false;
  return true;
}

async function updateRiskInfo() {
  const updateSeq = ++botFormRiskUpdateSeq;
  applyAutoInvestmentFromBalance();

  const requestedSymbol = $("bot-symbol").value.trim().toUpperCase();
  const investmentInput = $("bot-investment");
  const leverageInput = $("bot-leverage");
  const gridsElement = $("bot-grids");
  let info = [];

  // Fetch min order value for symbol (for min investment calculation)
  let minOrderValue = 5.1; // Default fallback
  let safeMinOrderValue = minOrderValue * 1.1;
  let symbolMaxLeverage = parseFloat(leverageInput?.max) || 100;
  let reservePct = 0.15;
  let reserveUsdFixed = 1.5;
  let reserveUsePct = true;
  let currentSymbolSpec = null;
  if (requestedSymbol && requestedSymbol.length > 3 && isTradeableDashboardSymbol(requestedSymbol)) {
    try {
      const priceData = await fetchJSON(`/price?symbol=${encodeURIComponent(requestedSymbol)}`);
      if (updateSeq !== botFormRiskUpdateSeq) return;
      if (($("bot-symbol")?.value || "").trim().toUpperCase() !== requestedSymbol) return;
      currentSymbolSpec = priceData || null;
      window._botFormSymbolSpecs[requestedSymbol] = priceData || {};
      if (priceData.min_order_value) {
        minOrderValue = priceData.min_order_value;
      }
      if (priceData.safe_min_order_value) {
        safeMinOrderValue = priceData.safe_min_order_value;
      } else {
        safeMinOrderValue = minOrderValue * 1.1;
      }
      if (priceData.max_leverage) {
        symbolMaxLeverage = parseFloat(priceData.max_leverage) || symbolMaxLeverage;
      }
      if (typeof priceData.auto_margin_reserve_pct === "number") {
        reservePct = priceData.auto_margin_reserve_pct;
      }
      if (typeof priceData.auto_margin_reserve_usdt === "number") {
        reserveUsdFixed = priceData.auto_margin_reserve_usdt;
      }
      if (typeof priceData.auto_margin_reserve_use_pct === "boolean") {
        reserveUsePct = priceData.auto_margin_reserve_use_pct;
      }
      applyPriceInputPrecision(priceData, { reformatExisting: true });
    } catch (e) {
      // Ignore - symbol might not exist yet
    }
  }
  if (updateSeq !== botFormRiskUpdateSeq) return;

  const symbol = $("bot-symbol").value.trim().toUpperCase();
  const investment = parseFloat(investmentInput?.value) || 0;
  let leverage = parseFloat(leverageInput?.value) || 1;
  const lower = parseFloat($("bot-lower").value) || 0;
  const upper = parseFloat($("bot-upper").value) || 0;
  const gridsInput = parseInt(gridsElement?.value) || 10;

  if (leverageInput && symbolMaxLeverage > 0) {
    leverageInput.max = String(symbolMaxLeverage);
  }

  const stepPct = 0.0037;
  let rangeBasedGrids = Math.max(3, gridsInput || 10);
  if (lower > 0 && upper > lower) {
    rangeBasedGrids = Math.max(
      3,
      Math.min(500, Math.floor(Math.log(upper / lower) / Math.log(1 + stepPct)) + 1)
    );
  }

  const reserveUsd = reserveUsePct
    ? investment * Math.max(0, Math.min(0.95, reservePct))
    : Math.max(0, reserveUsdFixed);
  const usableInvestment = Math.max(0, investment - reserveUsd);
  const requestedGridCount = Math.max(3, gridsInput || rangeBasedGrids || 10);
  const maxLeverage = symbolMaxLeverage > 0 ? symbolMaxLeverage : (parseFloat(leverageInput?.max) || 100);
  const minLevNeededForRequestedGridsRaw = usableInvestment > 0
    ? roundUpToTwoDecimals((safeMinOrderValue * requestedGridCount) / usableInvestment)
    : null;
  const minLevNeededForRequestedGrids = minLevNeededForRequestedGridsRaw != null
    ? roundUpLeverageRequirement(minLevNeededForRequestedGridsRaw)
    : null;

  if (leverageInput && leverage > maxLeverage) {
    botFormSuppressSizingTracking = true;
    leverageInput.value = formatLeverageInputValue(maxLeverage);
    botFormSuppressSizingTracking = false;
    leverage = maxLeverage;
  }

  if (!botFormAutoLeverageManualOverride && leverageInput && usableInvestment > 0) {
    const requiredAutoLeverage = Math.min(
      maxLeverage,
      Math.max(1, minLevNeededForRequestedGrids || 1)
    );
    const autoLeverage = Math.max(leverage, requiredAutoLeverage);
    if (Math.abs(autoLeverage - leverage) > 0.0001) {
      botFormSuppressSizingTracking = true;
      leverageInput.value = formatLeverageInputValue(autoLeverage);
      botFormSuppressSizingTracking = false;
      leverage = autoLeverage;
    }
  }

  const maxAffordableGridsAtCurrentLev = usableInvestment > 0 && leverage > 0
    ? Math.floor((usableInvestment * leverage) / safeMinOrderValue)
    : 0;
  const maxAffordableGridsAtMaxLev = usableInvestment > 0
    ? Math.floor((usableInvestment * maxLeverage) / safeMinOrderValue)
    : 0;

  let autoGridCount = rangeBasedGrids;
  if (maxAffordableGridsAtCurrentLev > 0) {
    autoGridCount = Math.min(autoGridCount, maxAffordableGridsAtCurrentLev);
  }
  autoGridCount = Math.max(3, Math.min(500, autoGridCount));

  if (!gridCountManuallyEdited && gridsElement) {
    gridsElement.value = autoGridCount;
  }

  const effectiveGridCount = parseInt(gridsElement?.value) || autoGridCount;
  const minLevNeededForChosenGridsRaw = usableInvestment > 0
    ? roundUpToTwoDecimals((safeMinOrderValue * effectiveGridCount) / usableInvestment)
    : null;
  const minLevNeededForChosenGrids = minLevNeededForChosenGridsRaw != null
    ? roundUpLeverageRequirement(minLevNeededForChosenGridsRaw)
    : null;

  // Update min investment / leverage display
  const minInvestDisplay = $("min-investment-display");
  const gridSpaceDisplay = $("grid-space-display");
  if (minInvestDisplay && leverage > 0) {
    const requiredNotional = safeMinOrderValue * effectiveGridCount;
    const minInvestment = Math.ceil(
      calculateRequiredGrossInvestment(
        requiredNotional,
        leverage,
        reserveUsePct,
        reservePct,
        reserveUsdFixed
      )
    );
    const isBelowMinInvest = investment > 0 && investment < minInvestment;
    const isBelowMinLev = minLevNeededForChosenGrids && minLevNeededForChosenGrids > leverage;
    const impossibleAtMaxLev = maxAffordableGridsAtMaxLev > 0 && maxAffordableGridsAtMaxLev < 3;

    let baseText = `Bal: $${investment.toFixed(2)} • Usable: $${usableInvestment.toFixed(2)} after $${reserveUsd.toFixed(2)} reserve • Lev auto ≥ ${minLevNeededForChosenGrids ? String(minLevNeededForChosenGrids) : "1"}x/${maxLeverage.toFixed(2)}x max • Grids ${effectiveGridCount}`;
    if (maxAffordableGridsAtCurrentLev > 0 && autoGridCount < rangeBasedGrids) {
      baseText += ` (range wanted ${rangeBasedGrids})`;
    }
    if (impossibleAtMaxLev) {
      minInvestDisplay.innerHTML = `<span class="text-red-400">${baseText} • Too small for 3 grids even at ${maxLeverage}x</span>`;
    } else if (isBelowMinInvest || isBelowMinLev) {
      minInvestDisplay.innerHTML = `<span class="text-red-400">${baseText}</span>`;
    } else {
      minInvestDisplay.innerHTML = `<span class="text-slate-500">${baseText}</span>`;
    }
  }

  if (usableInvestment > 0 && leverage > 0) {
    const notional = usableInvestment * leverage;
    info.push(`Usable notional: $${notional.toFixed(2)} (reserve $${reserveUsd.toFixed(2)})`);
  }

  if (lower > 0 && upper > lower) {
    const range = ((upper - lower) / lower * 100).toFixed(2);
    info.push(`Range: ${range}%`);

    info.push(`Est. grids: ${rangeBasedGrids}${gridCountManuallyEdited ? ` (using ${effectiveGridCount})` : ''}`);
    if (gridSpaceDisplay && effectiveGridCount > 1) {
      const space = (upper - lower) / (effectiveGridCount - 1);
      const pct = (space / lower) * 100;
      gridSpaceDisplay.textContent = `Grid step: ${space.toFixed(6)} (${pct.toFixed(2)}%)`;
    }

    if (investment > 0 && leverage > 0 && effectiveGridCount > 0) {
      const notional = investment * leverage;
      const valuePerGrid = notional / effectiveGridCount;
      info.push(`$${valuePerGrid.toFixed(2)}/grid`);
    }
  } else if (gridSpaceDisplay) {
    gridSpaceDisplay.textContent = "";
  }

  $("bot-risk-info").innerHTML = info.length > 0 ? info.join(" • ") : "";

  // Also update TP USDT display
  updateTpUsdt();
  renderBotPresetSummary();
}

function updateTpUsdt() {
  const investment = parseFloat($("bot-investment").value) || 0;
  const tpPct = parseFloat($("bot-tp-pct").value) || 0;
  const display = $("tp-usdt-display");

  if (!display) return;

  if (investment > 0 && tpPct > 0) {
    const tpUsdt = investment * (tpPct / 100);
    display.textContent = `= $${tpUsdt.toFixed(2)} USDT profit`;
  } else {
    display.textContent = "";
  }
}





function buildBotPayloadFromInputs(getEl = $) {
  const mode = getSelectedBotMode(getEl);
  const rangeModeSelect = getEl("bot-range-mode");
  const rangeMode = rangeModeSelect ? getSelectedRangeMode(getEl) : "fixed";
  const autoDirectionSupported = AUTO_DIRECTION_SUPPORTED_MODES.has(mode);
  const breakoutConfirmedSupported = BREAKOUT_CONFIRMED_SUPPORTED_MODES.has(mode);
  const trailingSupported = TRAILING_SL_SUPPORTED_MODES.has(mode);
  const quickProfitSupported = isQuickProfitSupported(mode, rangeMode);
  const volatilityGateSupported = VOLATILITY_GATE_SUPPORTED_MODES.has(mode);
  const autoPilotEnabled = !!getEl("bot-auto-pilot")?.checked;
  const autoNeutralModeEnabled = readBotConfigBooleanField(getEl, "auto_neutral_mode_enabled");

  const tpInput = getEl("bot-tp-pct");
  let tpPctFraction = null;
  if (tpInput && tpInput.value.trim() !== "") {
    const raw = Number(tpInput.value.trim());
    if (!Number.isNaN(raw) && raw > 0) {
      tpPctFraction = raw / 100.0;
    }
  }

  const autoPilotUniverseMode = getEl("bot-auto-pilot-universe-mode")
    ? getEl("bot-auto-pilot-universe-mode").value
    : "default_safe";
  const sessionTimerEnabledEl = getEl("bot-session-timer-enabled");
  const includeSessionTimerFields = !!sessionTimerEnabledEl;
  const activePreset = !getEl("bot-id")
    ? (botPresetState.appliedPreset || getBotPresetById(botPresetState.selectedPreset))
    : null;
  const activePresetId = String(activePreset?.preset_id || "").trim().toLowerCase();
  const presetMetadata = activePresetId
    ? {
        _creation_preset_name: activePresetId,
        _creation_preset_source: String(botPresetState.source || "manual"),
        _creation_preset_recommended: String(botPresetState.autoRecommendedPreset || ""),
        _creation_preset_fields: (activePreset?.key_fields || []).map((item) => String(item?.field || "")).filter(Boolean),
      }
    : {};

  return {
    id: getEl("bot-id") ? getEl("bot-id").value : undefined,
    settings_version: parseOptionalIntInput("bot-settings-version", getEl),
    symbol: autoPilotEnabled ? "Auto-Pilot" : String(getEl("bot-symbol")?.value || "").trim().toUpperCase(),
    lower_price: getEl("bot-lower") ? (parseFloat(getEl("bot-lower").value) || 0) : 0,
    upper_price: getEl("bot-upper") ? (parseFloat(getEl("bot-upper").value) || 0) : 0,
    investment: getEl("bot-investment") ? (parseFloat(getEl("bot-investment").value) || 0) : 0,
    leverage: getEl("bot-leverage") ? (parseFloat(getEl("bot-leverage").value) || 3) : 3,
    mode,
    mode_policy: normalizeModePolicyValue(getEl("bot-mode-policy")?.value, {
      auto_pilot: autoPilotEnabled,
      auto_direction: autoDirectionSupported ? readBotConfigBooleanField(getEl, "auto_direction") : false,
      auto_neutral_mode_enabled: autoNeutralModeEnabled,
    }),
    profile: getEl("bot-profile") ? (getEl("bot-profile").value || "normal") : "normal",
    range_mode: rangeMode,
    grid_distribution: getEl("bot-grid-distribution") ? getEl("bot-grid-distribution").value : "clustered",
    auto_direction: autoDirectionSupported ? readBotConfigBooleanField(getEl, "auto_direction") : false,
    auto_stop: getEl("bot-auto-stop") && getEl("bot-auto-stop").value ? parseFloat(getEl("bot-auto-stop").value) : null,
    auto_stop_target_usdt: getEl("bot-balance-target") && getEl("bot-balance-target").value ? parseFloat(getEl("bot-balance-target").value) : 0,
    tp_pct: tpPctFraction,
    grid_count: getEl("bot-grids") ? (parseInt(getEl("bot-grids").value, 10) || 10) : 10,
    trailing_sl_enabled: trailingSupported ? readBotConfigBooleanField(getEl, "trailing_sl_enabled") : false,
    trailing_sl_activation_pct: trailingSupported ? parseOptionalFloatInput("bot-trailing-sl-activation", (value) => value / 100.0, getEl) : null,
    trailing_sl_distance_pct: trailingSupported ? parseOptionalFloatInput("bot-trailing-sl-distance", (value) => value / 100.0, getEl) : null,
    quick_profit_enabled: quickProfitSupported ? readBotConfigBooleanField(getEl, "quick_profit_enabled") : false,
    quick_profit_target: parseOptionalFloatInput("bot-quick-profit-target", null, getEl),
    quick_profit_close_pct: parseOptionalFloatInput("bot-quick-profit-close-pct", (value) => value / 100.0, getEl),
    quick_profit_cooldown: parseOptionalIntInput("bot-quick-profit-cooldown", getEl),
    neutral_volatility_gate_enabled: volatilityGateSupported ? readBotConfigBooleanField(getEl, "neutral_volatility_gate_enabled") : false,
    neutral_volatility_gate_threshold_pct: volatilityGateSupported ? (parseOptionalFloatInput("bot-volatility-gate-threshold", null, getEl) ?? 5.0) : 5.0,
    auto_pilot: readBotConfigBooleanField(getEl, "auto_pilot"),
    auto_pilot_universe_mode: autoPilotUniverseMode || "default_safe",
    recovery_enabled: readBotConfigBooleanField(getEl, "recovery_enabled"),
    entry_gate_enabled: readBotConfigBooleanField(getEl, "entry_gate_enabled"),
    btc_correlation_filter_enabled: readBotConfigBooleanField(getEl, "btc_correlation_filter_enabled"),
    auto_stop_loss_enabled: readBotConfigBooleanField(getEl, "auto_stop_loss_enabled"),
    auto_take_profit_enabled: readBotConfigBooleanField(getEl, "auto_take_profit_enabled"),
    trend_protection_enabled: readBotConfigBooleanField(getEl, "trend_protection_enabled"),
    danger_zone_enabled: readBotConfigBooleanField(getEl, "danger_zone_enabled"),
    auto_neutral_mode_enabled: autoNeutralModeEnabled,
    breakout_confirmed_entry: breakoutConfirmedSupported
      ? readBotConfigBooleanField(getEl, "breakout_confirmed_entry")
      : false,
    ...(includeSessionTimerFields ? {
      session_timer_enabled: !!sessionTimerEnabledEl.checked,
      session_start_at: parseOptionalDateTimeInput("bot-session-start-at", getEl),
      session_stop_at: parseOptionalDateTimeInput("bot-session-stop-at", getEl),
      session_no_new_entries_before_stop_min: parseOptionalIntInput(
        "bot-session-no-new-entries-before-stop-min",
        getEl,
      ) ?? 15,
      session_end_mode: String(getEl("bot-session-end-mode")?.value || "hard_stop").trim().toLowerCase(),
      session_green_grace_min: parseOptionalIntInput("bot-session-green-grace-min", getEl) ?? 5,
      session_force_close_max_loss_pct: parseOptionalFloatInput(
        "bot-session-force-close-max-loss-pct",
        null,
        getEl,
      ),
      session_cancel_pending_orders_on_end: !!getEl("bot-session-cancel-pending-orders-on-end")?.checked,
      session_reduce_only_on_end: !!getEl("bot-session-reduce-only-on-end")?.checked,
    } : {}),
    ...presetMetadata,
  };
}

async function startBotFromSave(botId) {
  if (!botId) {
    throw new Error("Saved bot id missing");
  }

  pendingBotActions[botId] = "start";
  try {
    await fetchJSON("/bots/start", {
      method: "POST",
      body: JSON.stringify({ id: botId }),
    });
    focusActiveBotsWorkingNow();
    await Promise.allSettled([refreshBots(), refreshSummary(), refreshPositions()]);
    scheduleBotsRefreshFollowUp(900);
  } catch (error) {
    delete pendingBotActions[botId];
    throw error;
  }
}

function saveBotAndStart() {
  return saveBot({ startAfterSave: true });
}

async function saveBot(options = {}) {
  const startAfterSave = Boolean(options?.startAfterSave);
  await updateRiskInfo();
  const botData = buildBotPayloadFromInputs();

  if (!botData.symbol && !botData.auto_pilot) { alert("Symbol is required"); return; }
  if (!botData.auto_pilot && (!botData.lower_price || !botData.upper_price || botData.lower_price >= botData.upper_price)) {
    const autoApplied = await requestAiRange({ force: true, silent: false });
    if (autoApplied) {
      botData.lower_price = $("bot-lower") ? parseFloat($("bot-lower").value) : 0;
      botData.upper_price = $("bot-upper") ? parseFloat($("bot-upper").value) : 0;
    }
  }
  if (!botData.auto_pilot && (!botData.lower_price || !botData.upper_price || botData.lower_price >= botData.upper_price)) {
    alert("Invalid price range"); return;
  }

  const saveButtons = [
    {
      button: $("btn-save-bot"),
      loadingHtml: `<span class="animate-spin inline-block mr-1">↻</span> Saving…`,
      active: !startAfterSave,
    },
    {
      button: $("btn-save-start-bot"),
      loadingHtml: `<span class="animate-spin inline-block mr-1">↻</span> Saving & Starting…`,
      active: startAfterSave,
    },
  ].filter(({ button }) => button);
  const saveButtonOriginals = saveButtons.map(({ button }) => ({ button, html: button.innerHTML }));
  for (const { button, loadingHtml, active } of saveButtons) {
    button.disabled = true;
    button.classList.add("opacity-70", "cursor-not-allowed");
    if (active) button.innerHTML = loadingHtml;
  }

  try {
    const isEdit = !!botData.id;
    const savedSymbol = botData.symbol || 'Auto-Pilot';
    const savedBotId = botData.id;
    const resp = await fetchJSON("/bots", {
      method: "POST",
      headers: { "X-Bot-Config-Path": "main" },
      body: JSON.stringify(botData),
    });
    resetBotForm();
    // Suppress SSE-driven bot refreshes for 2s after save to prevent
    // stale cached data from overwriting the save result.
    window._forceNextBotsApply = true;
    window._suppressSseBotsUntil = Date.now() + 2000;
    await Promise.allSettled([refreshBots(), refreshSummary()]);
    scheduleBotsRefreshFollowUp();
    reportBotConfigSaveAudit(botData, resp, [
      ...SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
      ...MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS,
    ], "main");
    await reportPostSaveConfigRuntimeTruth(botData, resp, [
      ...SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
      ...MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS,
    ], "main");

    const targetBotId = resp?.bot?.id || savedBotId;
    if (startAfterSave) {
      try {
        await startBotFromSave(targetBotId);
        showToast(isEdit ? `✅ ${savedSymbol} bot updated and started!` : `✅ ${savedSymbol} bot created and started!`, "success");
      } catch (startError) {
        showToast(
          isEdit
            ? `❌ ${savedSymbol} bot updated, but start failed: ${startError.message}`
            : `❌ ${savedSymbol} bot created, but start failed: ${startError.message}`,
          "error",
        );
      }
    } else {
      showToast(isEdit ? `✅ ${savedSymbol} bot updated!` : `✅ ${savedSymbol} bot created!`, "success");
    }
    scrollToBotRow(targetBotId, savedSymbol);
  } catch (error) {
    if (error.status === 409 && error?.data?.error === "settings_version_conflict") {
      // Auto-retry with current settings_version (up to 3 attempts)
      for (let retryAttempt = 0; retryAttempt < 3; retryAttempt++) {
        const currentVersion = error?.data?.current_settings_version;
        if (currentVersion == null || !botData.id) break;
        try {
          botData.settings_version = currentVersion;
          const retryResp = await fetchJSON("/bots", {
            method: "POST",
            headers: { "X-Bot-Config-Path": "main" },
            body: JSON.stringify(botData),
          });
          window._forceNextBotsApply = true;
          await Promise.allSettled([refreshBots(), refreshSummary()]);
          scheduleBotsRefreshFollowUp();
          const targetId = retryResp?.bot?.id || botData.id;
          showToast(`✅ ${botData.symbol || "Bot"} updated!`, "success");
          scrollToBotRow(targetId, botData.symbol);
          return;
        } catch (retryErr) {
          if (retryErr.status === 409 && retryErr?.data?.error === "settings_version_conflict") {
            error = retryErr;
            continue;
          }
          showToast(`❌ Failed to save bot: ${retryErr.message}`, "error");
          return;
        }
      }
      showToast("Config changed in another editor or window. Reopen the bot settings and try again.", "error");
      await Promise.allSettled([refreshBots(), refreshSummary()]);
      return;
    }
    if (error?.data?.validation_type === "exchange_order_sizing" && error?.data?.sizing_validation) {
      showToast(`❌ Save blocked: ${formatBotPresetSizingWarningText({
        ...error.data.sizing_validation,
        viable: false,
        blockedReasons: Array.isArray(error.data.sizing_validation.blocked_reasons)
          ? error.data.sizing_validation.blocked_reasons
          : [],
      }) || error.message}`, "error");
      return;
    }
    showToast(`❌ Failed to save bot: ${error.message}`, "error");
  } finally {
    for (const { button, html } of saveButtonOriginals) {
      button.disabled = false;
      button.classList.remove("opacity-70", "cursor-not-allowed");
      button.innerHTML = html;
    }
  }
}

function scheduleBotsRefreshFollowUp(delay = 1200) {
  window.setTimeout(async () => {
    try {
      window._forceNextBotsApply = true;
      await refreshBots();
    } catch (error) {
      console.debug("Delayed bot refresh failed:", error);
    }
  }, delay);
}

/**
 * Scroll to a bot row in the Active Bots table and highlight it in purple.
 * Uses retry logic in case the table hasn't re-rendered yet.
 */
function scrollToBotRow(targetBotId, savedSymbol) {
  const maxAttempts = 6;
  const attemptDelay = 500;

  // Keep current filter — don't switch away from user's active view

  const tryScroll = (attempt) => {
    let botId = targetBotId;
    if (!botId && savedSymbol) {
      // Fallback: find by symbol in cached bots (pick newest)
      const matching = (window._lastBots || []).filter((b) => b.symbol === savedSymbol);
      if (matching.length === 1) {
        botId = matching[0].id;
      } else if (matching.length > 1) {
        matching.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
        botId = matching[0].id;
      }
    }

    if (!botId) {
      if (attempt < maxAttempts) {
        setTimeout(() => tryScroll(attempt + 1), attemptDelay);
      } else {
        console.warn(`Could not determine bot id for scroll (${savedSymbol || "unknown symbol"})`);
      }
      return;
    }

    const row = document.getElementById(`bot-row-${botId}`);
    if (row) {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("bot-row-highlight");
      setTimeout(() => {
        row.classList.remove("bot-row-highlight");
      }, 4500);
    } else if (attempt < maxAttempts) {
      setTimeout(() => tryScroll(attempt + 1), attemptDelay);
    } else {
      console.warn(`Could not find row element for bot id ${botId}`);
    }
  };

  // Wait for table re-render after save, then retry with longer intervals
  setTimeout(() => tryScroll(1), 800);
}

async function editBotWithFeedback(botId, btn) {
  if (btn) {
    btn.disabled = true;
    btn.classList.add("btn-click-animate");
    btn.innerHTML = `<span class="animate-spin inline-block">↻</span><span>Loading…</span>`;
  }
  try {
    await editBot(botId);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("btn-click-animate");
      btn.innerHTML = `<span>✏</span><span>Edit</span>`;
    }
  }
}

async function showQuickEditWithFeedback(botId, btn) {
  if (btn) {
    btn.disabled = true;
    btn.classList.add("btn-click-animate");
    btn.innerHTML = `<span class="animate-spin inline-block">↻</span><span>Loading…</span>`;
  }
  try {
    await showQuickEdit(botId);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("btn-click-animate");
      btn.innerHTML = `<span>⚙</span><span>Config</span>`;
    }
  }
}

async function editBot(botOrId) {
  const bot = await resolveEditorBotConfig(botOrId, {
    canonicalErrorLog: "Main bot form canonical fetch failed:",
    runtimeRefreshErrorLog: "Main bot form refresh failed:",
  });
  if (!bot) {
    const requestedBotId = typeof botOrId === "string" ? botOrId : (botOrId?.id || "unknown");
    console.error("Bot not found:", requestedBotId);
    showToast("Unable to load bot configuration", "error");
    return;
  }
  fillBotForm(bot);
  $("bot-form").scrollIntoView({ behavior: "smooth" });
}

async function useScanResult(result) {
  const range = result.suggested_range || {};
  // Use recommended values from scanner
  const recMode = result.recommended_mode || "neutral";
  const recRangeMode = result.recommended_range_mode || "fixed";
  const recProfile = result.recommended_profile || "normal";

  // Reset grid manual edit flag so grids auto-calculate from range
  gridCountManuallyEdited = false;

  fillBotForm({
    symbol: result.symbol,
    lower_price: range.lower,
    upper_price: range.upper,
    mode: recMode,
    profile: recProfile,
    range_mode: recRangeMode,
    leverage: 3,
    auto_direction: false,
  });

  await requestAiRange({ force: true, silent: true });

  // Show recommendation reasoning in console
  if (result.mode_reasoning) {
    console.log(`[Scanner] ${result.symbol}: ${result.mode_reasoning}`);
  }

  $("bot-form").scrollIntoView({ behavior: "smooth" });
}

async function botAction(action, botId, event, silent = false) {
  if (action === "start") {
    const recentlyStoppedAt = Number(recentlyStoppedBots[botId] || 0);
    if (recentlyStoppedAt && (Date.now() - recentlyStoppedAt) < STOP_TO_START_GUARD_MS) {
      if (!silent) {
        const sec = Math.max(
          1,
          Math.ceil((STOP_TO_START_GUARD_MS - (Date.now() - recentlyStoppedAt)) / 1000)
        );
        showToast(`Start blocked for ${sec}s after stop`, "error");
      }
      return;
    }
  }

  // Add to pending actions to prevent UI flicker during refresh
  if (["start", "stop", "pause", "resume"].includes(action)) {
    pendingBotActions[botId] = action;
  }

  // Add click animation to button
  const btn = event?.target?.closest('button');
  let originalHtml = null;
  if (event && event.target) {
    if (btn) {
      btn.classList.add('btn-click-animate');
      setTimeout(() => btn.classList.remove('btn-click-animate'), 200);
    }
  }

  // Keep the clicked button busy until the lifecycle refresh settles.
  if (["start", "stop", "pause", "resume"].includes(action) && btn) {
    originalHtml = btn.innerHTML;
    btn.disabled = true;
    const labels = {
      start: "Starting...",
      stop: "Stopping...",
      pause: "Pausing...",
      resume: "Resuming..."
    };
    btn.innerHTML = `<span class="animate-spin inline-block mr-1">↻</span> ${labels[action] || "Processing..."}`;
  }

  if (action === "delete" && !silent && !confirm("Are you sure you want to delete this bot?")) {
    delete pendingBotActions[botId];
    return;
  }

  if (action === "start") {
    focusActiveBotsWorkingNow();
  }

  // Stop cancels all orders and closes positions via emergency_stop.
  const apiPath = action === "stop" ? "stop"
    : action === "reduce_only" ? "reduce-only"
    : action;
  const apiBody = action === "reduce_only"
    ? { id: botId, reduce_only: true, auto_stop_paused: true }
    : { id: botId };
  const apiCall = fetchJSON(`/bots/${apiPath}`, {
    method: "POST",
    body: JSON.stringify(apiBody),
  });

  // Fire and handle result in background — UI is already updated via pendingBotActions
  apiCall.then(async () => {
    if (action === "stop") {
      recentlyStoppedBots[botId] = Date.now();
      setTimeout(() => { delete recentlyStoppedBots[botId]; }, STOP_TO_START_GUARD_MS + 1000);
    }
    // Refresh to pick up confirmed state
    window._forceNextBotsApply = true;
    try {
      const tasks = [refreshBots()];
      if (action !== "delete") tasks.push(refreshPositions(), refreshSummary());
      if (action === "stop") tasks.push(refreshPnl());
      await Promise.allSettled(tasks);
    } catch (_) {}
    // Follow-up refresh for exchange/runner lag
    setTimeout(async () => {
      try {
        await Promise.allSettled([refreshBots(), refreshPositions(), refreshSummary()]);
      } catch (_) {}
      delete pendingBotActions[botId];
      if (btn && btn.isConnected && originalHtml !== null) {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
      }
    }, action === "stop" ? 1200 : 900);
  }).catch((error) => {
    delete pendingBotActions[botId];
    if (btn && btn.isConnected && originalHtml !== null) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
    if (!silent) {
      showToast(`${action} failed: ${error.message}`, "error");
    } else {
      console.error(`Action ${action} failed for ${botId}: ${error.message}`);
    }
    // Force refresh to restore true state
    window._forceNextBotsApply = true;
    refreshBots().catch(() => {});
  });
}

async function removeAllBots() {
  // Get current bots count from cached data (more reliable than DOM)
  const botCount = (window._lastBots || []).length;

  if (botCount === 0) {
    alert("No bots to remove.");
    return;
  }

  if (!confirm(`⚠️ Are you sure you want to remove ALL ${botCount} bot(s)?\n\nThis will stop and delete every bot. This action cannot be undone.`)) {
    return;
  }

  // Double confirmation for safety
  if (!confirm(`🚨 FINAL WARNING: This will permanently delete ${botCount} bot(s).\n\nClick OK to proceed.`)) {
    return;
  }

  try {
    const response = await fetchJSON("/bots/delete-all", { method: "POST" });
    alert(`✅ Removed ${response.deleted_count || botCount} bot(s)`);
    window._forceNextBotsApply = true;
    await refreshBots();
    await refreshPositions();
    await refreshSummary();
  } catch (error) {
    alert(`❌ Failed to remove bots: ${error.message}`);
  }
}

async function closePosition(symbol, side, size, botId = null, btn = null) {
  let originalHtml = null;
  if (btn) {
    originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin inline-block mr-1">↻</span>';
  }
  try {
    await fetchJSON("/close-position", { method: "POST", body: JSON.stringify({ symbol, side, size, bot_id: botId }) });
    await refreshPositions();
    await refreshSummary();
    showToast(`✅ Closed ${side} ${symbol}`, "success");
  } catch (error) {
    showToast(`❌ Close failed for ${symbol}: ${error.message}`, "error");
    console.error(`Close position error for ${symbol}:`, error);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml !== null ? originalHtml : "⚡";
    }
  }
}

async function closePositionSilent(symbol, side, size, botId = null) {
  try {
    await fetchJSON("/close-position", { method: "POST", body: JSON.stringify({ symbol, side, size, bot_id: botId }) });
    await refreshPositions();
    await refreshSummary();
    console.log(`Auto-closed ${side} position for ${symbol}`);
  } catch (error) {
    console.error(`Failed to auto-close position for ${symbol}: ${error.message}`);
  }
}

async function emergencyStop() {
  const btn = $("btn-emergency-stop");
  const originalText = btn.innerHTML;
  btn.innerHTML = '<span class="text-2xl">⏳</span> STOPPING... <span class="text-2xl">⏳</span>';
  btn.disabled = true;

  // C4: Show immediate feedback — mark all running bots as pending stop
  (window._lastBots || []).forEach(b => {
    if (b && b.id && ["running","paused","recovering"].includes(b.status)) {
      pendingBotActions[b.id] = "stop";
    }
  });
  appendActivityEvent({
    key: `emergency-stop:${Date.now()}`,
    category: "emergency stop",
    tone: "danger",
    icon: "🚨",
    message: "Emergency stop requested. Flatten and cancel flow started.",
    toast: true,
    notify: true,
  });
  if (soundEnabled) {
    playTone(800, 0.3, 'square', 0.3);
  }
  // Force immediate UI update with pending badges
  window._forceNextBotsApply = true;
  refreshBots().catch(() => {});

  // Fire API call — don't block UI
  fetchJSON("/emergency-stop", { method: "POST" }).then(async () => {
    window._forceNextBotsApply = true;
    await refreshAll();
    // Follow-up refresh
    setTimeout(async () => {
      await refreshAll();
      Object.keys(pendingBotActions).forEach(k => delete pendingBotActions[k]);
    }, 2000);
  }).catch((error) => {
    console.error("Emergency stop error:", error);
    showToast("Emergency stop failed: " + error.message, "error");
  }).finally(() => {
    btn.innerHTML = originalText;
    btn.disabled = false;
  });
}

async function setTakeProfit(symbol) {
  const input = $(`tp-input-${symbol}`);
  if (!input) { alert("Take profit input not found"); return; }
  const tpValue = parseFloat(input.value);
  if (!tpValue || tpValue <= 0) { alert("Please enter a valid take profit price"); return; }
  try {
    await fetchJSON("/set-take-profit", { method: "POST", body: JSON.stringify({ symbol, take_profit: tpValue }) });
    await refreshPositions();
    alert(`✅ Take profit set to ${tpValue} for ${symbol}`);
  } catch (error) {
    alert(`❌ Failed to set take profit: ${error.message}`);
  }
}

async function setStopLoss(symbol) {
  const input = $(`sl-input-${symbol}`);
  if (!input) { alert("Stop loss input not found"); return; }
  const slValue = parseFloat(input.value);
  if (!slValue || slValue <= 0) { alert("Please enter a valid stop loss price"); return; }
  try {
    await fetchJSON("/set-stop-loss", { method: "POST", body: JSON.stringify({ symbol, stop_loss: slValue }) });
    await refreshPositions();
    alert(`✅ Stop loss set to ${slValue} for ${symbol}`);
  } catch (error) {
    alert(`❌ Failed to set stop loss: ${error.message}`);
  }
}

async function setBalanceTarget(botId, symbol) {
  const input = $(`target-input-${symbol}`);
  if (!input) { alert("Balance target input not found"); return; }
  const targetValue = input.value.trim() === '' ? 0 : parseFloat(input.value);
  if (isNaN(targetValue) || targetValue < 0) { alert("Please enter a valid balance target"); return; }
  try {
    await fetchJSON(`/bots/${botId}/quick-update`, {
      method: "POST",
      body: JSON.stringify({ auto_stop_target_usdt: targetValue })
    });
    await Promise.all([refreshPositions(), refreshBots()]);
    if (targetValue > 0) {
      console.log(`✅ Balance target set to $${targetValue} for ${symbol}`);
    } else {
      console.log(`✅ Balance target disabled for ${symbol}`);
    }
  } catch (error) {
    alert(`❌ Failed to set balance target: ${error.message}`);
  }
}

async function toggleAiGuard(botId, symbol, apply) {
  try {
    await fetchJSON(`/bots/${botId}/quick-update`, {
      method: "POST",
      body: JSON.stringify({ ai_advisor_apply: apply })
    });
    await refreshBots();
    console.log(`AI guard ${apply ? "enabled" : "disabled"} for ${symbol}`);
  } catch (error) {
    alert(`❌ Failed to toggle AI guard: ${error.message}`);
  }
}

function updateScalpPnlInfoVisibility(scope = "main") {
  const modeSelect = getScopedElement(scope, "bot-mode");
  const scalpPnlInfo = getScopedElement(scope, "scalp-pnl-info");
  const scalpMarketInfo = getScopedElement(scope, "scalp-market-info");
  const rangeModeSelect = getScopedElement(scope, "bot-range-mode");

  if (modeSelect) {
    const mode = modeSelect.value;
    const isScalpPnl = mode === "scalp_pnl";
    const isScalpMarket = mode === "scalp_market";
    const isNeutralClassic = mode === "neutral_classic_bybit";

    // Show/hide info panels
    if (scalpPnlInfo) {
      scalpPnlInfo.classList.toggle("hidden", !isScalpPnl);
    }
    if (scalpMarketInfo) {
      scalpMarketInfo.classList.toggle("hidden", !isScalpMarket);
    }

    // Force dynamic range mode for scalp modes, fixed for neutral classic
    if ((isScalpPnl || isScalpMarket) && rangeModeSelect) {
      rangeModeSelect.value = "dynamic";
      rangeModeSelect.disabled = true;
    } else if (isNeutralClassic && rangeModeSelect) {
      // Allow selecting range mode for classic neutral (fixed or trailing)
      rangeModeSelect.disabled = false;
    } else if (rangeModeSelect) {
      rangeModeSelect.disabled = false;
    }
  }

  updateModeScopedBotOptions(scope);
}

function initEventListeners() {
  $("btn-save-bot").addEventListener("click", saveBot);
  $("btn-save-start-bot").addEventListener("click", saveBotAndStart);
  $("btn-reset-bot").addEventListener("click", resetBotForm);
  $("btn-scan-neutral").addEventListener("click", scanNeutral);
  $("bot-symbol").addEventListener("input", () => {
    botFormAutoRangeContextKey = getBotFormAutoRangeContext();
    botFormAutoRangeManualOverride = false;
    if (!isEditingExistingBotForm()) {
      botFormAutoInvestmentManualOverride = false;
    }
    botFormAutoLeverageManualOverride = false;
    updateRiskInfo();
    autoFillRangeAndGrids();
  });
  $("bot-investment").addEventListener("input", () => {
    if (!botFormSuppressSizingTracking) {
      botFormAutoInvestmentManualOverride = true;
    }
    updateRiskInfo();
  });
  $("bot-leverage").addEventListener("input", () => {
    if (!botFormSuppressSizingTracking) {
      botFormAutoLeverageManualOverride = true;
    }
    updateRiskInfo();
  });
  $("bot-lower").addEventListener("input", () => {
    if (!botFormSuppressRangeTracking) {
      botFormAutoRangeManualOverride = true;
      botFormAutoRangeContextKey = getBotFormAutoRangeContext();
    }
    botFormAutoLeverageManualOverride = false;
    updateRiskInfo();
  });
  $("bot-upper").addEventListener("input", () => {
    if (!botFormSuppressRangeTracking) {
      botFormAutoRangeManualOverride = true;
      botFormAutoRangeContextKey = getBotFormAutoRangeContext();
    }
    botFormAutoLeverageManualOverride = false;
    updateRiskInfo();
  });
  $("bot-grids").addEventListener("input", () => {
    gridCountManuallyEdited = true;
    botFormAutoLeverageManualOverride = false;
    updateRiskInfo();
  });
  const presetSelect = $("bot-preset-select");
  if (presetSelect) {
    presetSelect.addEventListener("change", (event) => {
      applySelectedBotPreset(event.target.value, { source: "manual" });
    });
  }
  const autoPresetButton = $("bot-preset-auto-recommend");
  if (autoPresetButton) {
    autoPresetButton.addEventListener("click", autoRecommendBotPreset);
  }
  const saveCustomPresetButton = $("btn-save-custom-preset");
  if (saveCustomPresetButton) {
    saveCustomPresetButton.addEventListener("click", saveCurrentBotAsCustomPreset);
  }
  const deleteCustomPresetButton = $("bot-preset-delete-selected");
  if (deleteCustomPresetButton) {
    deleteCustomPresetButton.addEventListener("click", deleteSelectedCustomBotPreset);
  }
  const renameCustomPresetButton = $("bot-preset-rename-selected");
  if (renameCustomPresetButton) {
    renameCustomPresetButton.addEventListener("click", renameSelectedCustomBotPreset);
  }
  $("bot-tp-pct").addEventListener("input", updateTpUsdt);
  $("scanner-symbols").addEventListener("keypress", (e) => { if (e.key === "Enter") scanNeutral(); });

  // Show/hide scalp PnL info panel based on mode selection
  const modeSelect = $("bot-mode");
  if (modeSelect) {
    modeSelect.addEventListener("change", () => {
      updateScalpPnlInfoVisibility();
      renderModeSemanticsPanel("main", mainBotFormContext);
      botFormAutoRangeContextKey = getBotFormAutoRangeContext();
      botFormAutoRangeManualOverride = false;
      if (!isEditingExistingBotForm()) {
        botFormAutoInvestmentManualOverride = false;
      }
      botFormAutoLeverageManualOverride = false;
      updateRiskInfo();
      autoFillRangeAndGrids();
    });
  }

  const rangeModeSelect = $("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.addEventListener("change", () => {
      updateScalpPnlInfoVisibility();
      renderModeSemanticsPanel("main", mainBotFormContext);
      botFormAutoRangeContextKey = getBotFormAutoRangeContext();
      botFormAutoRangeManualOverride = false;
      botFormAutoLeverageManualOverride = false;
      updateRiskInfo();
      autoFillRangeAndGrids();
    });
  }
  const modePolicySelect = $("bot-mode-policy");
  if (modePolicySelect) {
    modePolicySelect.addEventListener("change", () => {
      renderModeSemanticsPanel("main", mainBotFormContext);
    });
  }

  const autoPilotToggle = $("bot-auto-pilot");
  if (autoPilotToggle) {
    autoPilotToggle.addEventListener("change", () => {
      updateAutoPilotVisibility();
      renderModeSemanticsPanel("main", mainBotFormContext);
    });
    updateAutoPilotVisibility(); // Set initial state
  }
  const autoPilotUniverseMode = $("bot-auto-pilot-universe-mode");
  if (autoPilotUniverseMode) {
    autoPilotUniverseMode.addEventListener("change", updateAutoPilotUniverseModeHelp);
    updateAutoPilotUniverseModeHelp();
  }

  const sessionTimerToggle = $("bot-session-timer-enabled");
  if (sessionTimerToggle) {
    sessionTimerToggle.addEventListener("change", () => updateSessionTimerVisibility());
  }
  const sessionEndMode = $("bot-session-end-mode");
  if (sessionEndMode) {
    sessionEndMode.addEventListener("change", () => updateSessionTimerVisibility());
  }
  updateSessionTimerVisibility();

  ["bot-trailing-sl", "bot-quick-profit-enabled", "bot-volatility-gate-enabled"].forEach((id) => {
    const el = $(id);
    if (el) {
      el.addEventListener("change", updateModeScopedBotOptions);
    }
  });
  ["bot-auto-direction", "bot-auto-neutral-mode-enabled"].forEach((id) => {
    const el = $(id);
    if (el) {
      el.addEventListener("change", () => renderModeSemanticsPanel("main", mainBotFormContext));
    }
  });

  updateScalpPnlInfoVisibility();
  renderModeSemanticsPanel("main", mainBotFormContext);
  renderPresetContext("main", mainBotFormContext);
  renderQuickFormLimitations();
  loadBotPresetCatalog().catch((error) => {
    console.debug("Bot preset catalog failed:", error);
  });

  // Initialize select-all-on-click for text inputs
  initSelectAllOnClick();

  // Initialize recent scans display
  renderRecentScans();

  const profitRainThreshold = $("profit-rain-threshold");
  if (profitRainThreshold) {
    profitRainThreshold.addEventListener("change", (event) => {
      updateProfitRainThreshold(event.target.value);
    });
  }

}

/**
 * Initialize select-all-on-click behavior for text and number inputs.
 * Inputs with class 'select-all-on-click' or all inputs in the bot form will select all text on click.
 */
let _selectAllInitialized = false;
function initSelectAllOnClick() {
  if (_selectAllInitialized) return;
  _selectAllInitialized = true;
  const inputs = document.querySelectorAll(
    'input[type="text"], input[type="number"], input.select-all-on-click, #bot-form input'
  );

  inputs.forEach(input => {
    input.addEventListener('click', function (e) {
      // Only select all if input is not already focused (first click)
      // This allows users to position cursor on subsequent clicks
      if (document.activeElement !== this) {
        this.select();
      }
    });

    // Also select all on focus (for tab navigation)
    input.addEventListener('focus', function (e) {
      // Small delay to ensure the focus is complete
      setTimeout(() => this.select(), 0);
    });
  });
}

let _liveTimerInterval = null;
function startLiveTimer() {
  if (_liveTimerInterval) clearInterval(_liveTimerInterval);
  _liveTimerInterval = setInterval(() => {
    const el = $("last-update-time");
    if (el && lastUpdateTime) el.textContent = formatTimeAgo(lastUpdateTime);
    syncDashboardTitle();
  }, 1000);
}

// ============================================================
// Bot Status/Log Modal Functions
// ============================================================

// Track current modal tab and auto-refresh interval
// let botModalCurrentTab = 'log';  // Defined in app_v5.js
// let botModalRefreshInterval = null;  // Defined in app_v5.js

/**
 * Open the bot status/log modal and load initial data.
 */

// ============================================================
// Bot Detail Modal Functions
// ============================================================

// let botDetailRefreshInterval = null;  // Defined in app_v5.js

function renderBotDetailModeReadinessMatrix(matrix, botId = "") {
  const container = $("botDetailModeMatrix");
  if (!container) return;
  const items = Array.isArray(matrix?.items) ? matrix.items : [];
  if (!items.length) {
    container.innerHTML = `<div class="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-3 text-xs text-slate-500">No readiness comparison available.</div>`;
    return;
  }
  container.innerHTML = items.map((item) => {
    const status = String(item?.status || "watch").trim().toLowerCase();
    const isConfiguredMode = Boolean(item?.is_configured_mode);
    const statusClass = status === "trigger_ready"
      ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"
      : status === "armed"
        ? "border-cyan-400/25 bg-cyan-500/10 text-cyan-100"
        : status === "late"
          ? "border-orange-400/25 bg-orange-500/10 text-orange-100"
      : status === "blocked"
        ? "border-red-400/25 bg-red-500/10 text-red-100"
        : "border-amber-400/25 bg-amber-500/10 text-amber-100";
    const surfaceClass = isConfiguredMode
      ? "border-slate-700 bg-slate-900/70"
      : "border-slate-800 bg-slate-950/60";
    const markers = [
      isConfiguredMode ? "Current Mode" : "If Switched",
      item?.is_runtime_view ? "Runtime View" : "",
      item?.is_scanner_suggestion ? "Scanner" : "",
    ].filter(Boolean).join(" • ");
    const scoreText = Number.isFinite(Number(item?.score)) ? `Score ${Number(item.score).toFixed(1)}` : "";
    const freshness = getReadinessFreshnessMeta({}, {
      sourceKind: item?.readiness_source_kind,
      previewState: item?.preview_state,
      ageSec: item?.age_sec,
    });
    const reasonText = String(item?.reason_text || humanizeReason(item?.reason || status)).trim();
    const detailText = truncateText(String(item?.detail || "").trim(), 120);
    const reviewButton = botId && !item?.is_configured_mode && ["trigger_ready", "armed"].includes(status)
      ? `<button type="button" onclick="reviewSuggestedMode('${botId}', '${String(item?.mode || "")}', '${String(item?.range_mode || "")}')" class="rounded-lg border border-cyan-400/25 bg-cyan-500/10 px-2 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-500/20 transition">Review Mode</button>`
      : "";
    return `
      <div class="rounded-xl border px-3 py-3 ${surfaceClass}">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div class="text-sm font-medium text-white">${escapeHtml(String(item?.label || formatBotModeLabel(item?.mode || "")))}</div>
            <div class="mt-1 text-[11px] text-slate-400">${escapeHtml([markers, scoreText, freshness.label].filter(Boolean).join(" • "))}</div>
          </div>
          <div class="flex flex-col items-end gap-2">
            <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusClass}">${escapeHtml(formatReadinessStageLabel(status).toUpperCase())}</span>
            ${reviewButton}
          </div>
        </div>
        <div class="mt-2 text-xs text-slate-300">${escapeHtml(reasonText)}</div>
        ${detailText ? `<div class="mt-1 text-[11px] text-slate-500">${escapeHtml(detailText)}</div>` : ""}
      </div>
    `;
  }).join("");
}

async function fetchBotDetailPayload(botId) {
  const normalizedBotId = String(botId || "").trim();
  if (!normalizedBotId) {
    const error = new Error("Missing bot id");
    error.status = 400;
    throw error;
  }

  try {
    return await fetchJSON(`/bots/${encodeURIComponent(normalizedBotId)}/details`, {
      suppress404Log: true,
    });
  } catch (error) {
    if (error?.status !== 404) throw error;
    await refreshBots().catch(() => null);
    return await fetchJSON(`/bots/${encodeURIComponent(normalizedBotId)}/details`, {
      suppress404Log: true,
    });
  }
}

/**
 * Open the bot detail modal and load bot details including trade history.
 * @param {string} botId - The bot ID to show details for
 */
async function openBotDetailModal(botId) {
  window.currentDetailBotId = botId;
  const modal = $("botDetailModal");
  if (!modal) return;

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden"; // Prevent background scrolling

  // Show loading state
  $("botDetailSymbol").textContent = "Loading...";
  $("botDetailNetPnl").textContent = "...";
  if ($("botDetailBaselineMeta")) $("botDetailBaselineMeta").textContent = "Loading baseline...";
  $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-500">Loading...</td></tr>`;

  try {
    const data = await fetchBotDetailPayload(botId);
    const bot = data.bot;

    if (!bot) {
      $("botDetailSymbol").textContent = "Bot not found";
      return;
    }

    // Update header
    $("botDetailSymbol").textContent = bot.symbol;

    // Start auto-refresh for details
    if (botDetailRefreshInterval) clearInterval(botDetailRefreshInterval);
    botDetailRefreshInterval = setInterval(() => {
      refreshBotDetailLogs();
    }, 5000);

    $("botDetailStatus").textContent = bot.status === "recovering" ? "🔄 recovering" : bot.status;
    $("botDetailStatus").className = `px-2 py-0.5 text-xs font-medium rounded-full ${bot.status === "running" ? "bg-emerald-500/20 text-emerald-400" :
      bot.status === "paused" ? "bg-amber-500/20 text-amber-400" :
        bot.status === "flash_crash_paused" ? "bg-orange-500/20 text-orange-300" :
          bot.status === "recovering" ? "bg-blue-500/20 text-blue-400" :
            bot.status === "stopped" ? "bg-slate-500/20 text-slate-400" :
              "bg-red-500/20 text-red-400"
      }`;

    // Update summary cards
    const performanceSummary = bot.performance_summary || bot.bot_pnl || {};
    const netPnl = performanceSummary.net_pnl || 0;
    const netPnlFormatted = formatPnL(netPnl);
    $("botDetailNetPnl").textContent = netPnlFormatted.text;
    $("botDetailNetPnl").className = `text-xl font-bold ${netPnlFormatted.class}`;
    $("botDetailWinRate").textContent = `${performanceSummary.trade_count || 0} trades, ${performanceSummary.win_rate || 0}% win`;

    const profitFormatted = formatPnL(performanceSummary.total_profit || 0);
    $("botDetailProfit").textContent = profitFormatted.text;

    $("botDetailLoss").textContent = `-$${formatNumber(performanceSummary.total_loss || 0, 2)}`;

    const botPnlFormatted = formatPnL(bot.total_pnl || 0);
    $("botDetailBotPnl").textContent = botPnlFormatted.text;
    $("botDetailBotPnl").className = `text-xl font-bold ${botPnlFormatted.class}`;
    if ($("botDetailBaselineMeta")) {
      $("botDetailBaselineMeta").textContent = formatPerformanceBaselineSummary(
        bot.performance_baseline || null,
        { prefix: "Baseline" }
      );
    }
    const resetBotBaselineBtn = $("btn-reset-bot-baseline");
    if (resetBotBaselineBtn) {
      resetBotBaselineBtn.onclick = () => beginBotPerformanceBaselineReset(bot.id, bot.symbol);
      setPerformanceBaselineButtonState(
        resetBotBaselineBtn,
        Boolean(botBaselineResetInFlight),
        "Resetting Bot Baseline...",
        "Reset Bot Baseline"
      );
    }

    // Update configuration
    $("botDetailConfiguredMode").textContent = `${formatBotModeLabel(getConfiguredModeForUi(bot))} / ${formatRangeModeLabel(getConfiguredRangeModeForUi(bot))}`;
    $("botDetailRuntimeMode").textContent = `${formatBotModeLabel(getEffectiveRuntimeModeForUi(bot))} / ${formatRangeModeLabel(getEffectiveRuntimeRangeModeForUi(bot))}`;
    $("botDetailModePolicy").textContent = formatModePolicyLabel(bot.mode_policy);
    $("botDetailProfile").textContent = bot.profile || "normal";
    $("botDetailInvest").textContent = `$${formatNumber(bot.investment, 0)}`;
    $("botDetailLeverage").textContent = `${bot.leverage || 1}x`;
    $("botDetailGrids").textContent = getConfiguredGridCount(bot) || "-";
    $("botDetailRange").textContent = `${formatNumber(bot.lower_price, 2)} - ${formatNumber(bot.upper_price, 2)}`;
    $("botDetailTp").textContent = bot.tp_pct ? `${(bot.tp_pct * 100).toFixed(1)}%` : "-";
    $("botDetailAutoStop").textContent = bot.auto_stop || "-";
    const botDetailTruthBody = $("botDetailTruthBody");
    if (botDetailTruthBody) {
      botDetailTruthBody.innerHTML = renderBotDetailExchangeTruth(bot);
    }
    const botDetailProfitProtectionBody = $("botDetailProfitProtectionBody");
    if (botDetailProfitProtectionBody) {
      botDetailProfitProtectionBody.innerHTML = renderBotDetailProfitProtection(bot);
    }
    renderBotDetailModeReadinessMatrix(bot.mode_readiness_matrix, bot.id);

    // Update Auto-Direction Signals Section
    const signalsSection = $("botDetailSignalsSection");
    const signalsGrid = $("botDetailSignalsGrid");
    const signalsSummary = $("botDetailSignalsSummary");
    const directionScoreEl = $("botDetailDirectionScore");
    const directionModeEl = $("botDetailDirectionMode");

    // Only show if auto_direction is enabled
    if (bot.auto_direction && signalsSection) {
      signalsSection.classList.remove("hidden");

      // Get direction score and determine mode
      const dirScore = bot.direction_score || 0;
      const dirSignals = bot.direction_signals || "";

      // Update total score with color
      if (directionScoreEl) {
        directionScoreEl.textContent = dirScore > 0 ? `+${dirScore.toFixed(0)}` : dirScore.toFixed(0);
        directionScoreEl.className = `px-2 py-0.5 text-sm font-bold rounded ${dirScore > 30 ? "bg-emerald-600 text-white" :
          dirScore > 0 ? "bg-emerald-500/30 text-emerald-400" :
            dirScore < -30 ? "bg-red-600 text-white" :
              dirScore < 0 ? "bg-red-500/30 text-red-400" :
                "bg-slate-700 text-white"
          }`;
      }

      // Update mode badge
      if (directionModeEl) {
        let modeText = "NEUTRAL";
        let modeClass = "bg-slate-600 text-slate-300";
        if (dirScore >= 35) {
          modeText = "LONG";
          modeClass = "bg-emerald-500/30 text-emerald-400";
        } else if (dirScore <= -35) {
          modeText = "SHORT";
          modeClass = "bg-red-500/30 text-red-400";
        }
        directionModeEl.textContent = modeText;
        directionModeEl.className = `px-2 py-0.5 text-xs rounded-full ${modeClass}`;
      }

      // Build signals grid
      const signalConfigs = [
        { key: "rsi_signal", label: "RSI", score: "rsi_score", icon: "📈" },
        { key: "adx_signal", label: "ADX", score: "adx_score", icon: "📉" },
        { key: "macd_signal", label: "MACD", score: "macd_score", icon: "〰️" },
        { key: "ema_signal", label: "EMA", score: "ema_score", icon: "📊" },
        { key: "funding_signal", label: "Funding", score: "funding_score", icon: "💰" },
        { key: "volume_profile_signal", label: "Vol Profile", score: "volume_profile_score", icon: "📦" },
        { key: "oi_signal", label: "Open Int", score: "oi_score", icon: "🔓" },
        { key: "orderbook_signal", label: "Order Book", score: "orderbook_score", icon: "📚", extra: "orderbook_imbalance" },
        { key: "liquidation_signal", label: "Liquidation", score: "liquidation_score", icon: "💧" },
        { key: "session_signal", label: "Session", score: "session_modifier", icon: "🌍", extraLabel: "session_name" },
        { key: "mean_reversion_signal", label: "Mean Rev", score: "mean_reversion_score", icon: "📊", extra: "mean_reversion_deviation" },
        { key: "btc_guard_status", label: "BTC Guard", score: null, icon: "🛡️" },
      ];

      let signalsHtml = "";
      let activeSignals = 0;

      signalConfigs.forEach(cfg => {
        const signal = bot[cfg.key];
        const score = cfg.score ? bot[cfg.score] : null;

        // Skip if no signal data
        if (!signal && score === null) return;

        activeSignals++;

        // Determine signal color
        let signalClass = "bg-slate-700/50 text-slate-400";
        let scoreClass = "text-slate-500";

        if (signal) {
          const sigLower = signal.toLowerCase();
          if (sigLower.includes("bullish") || sigLower.includes("long") || signal === "FAVORABLE" || signal === "ok") {
            signalClass = "bg-emerald-500/20 text-emerald-400";
            scoreClass = "text-emerald-400";
          } else if (sigLower.includes("bearish") || sigLower.includes("short") || signal === "UNFAVORABLE" || signal === "paused") {
            signalClass = "bg-red-500/20 text-red-400";
            scoreClass = "text-red-400";
          }
        } else if (score !== null) {
          if (score > 0) {
            signalClass = "bg-emerald-500/20 text-emerald-400";
            scoreClass = "text-emerald-400";
          } else if (score < 0) {
            signalClass = "bg-red-500/20 text-red-400";
            scoreClass = "text-red-400";
          }
        }

        // Extra info (like imbalance %)
        let extraInfo = "";
        if (cfg.extra && bot[cfg.extra] !== undefined) {
          const val = bot[cfg.extra];
          if (typeof val === "number") {
            extraInfo = ` (${val.toFixed(1)}%)`;
          }
        }
        if (cfg.extraLabel && bot[cfg.extraLabel]) {
          extraInfo = ` (${bot[cfg.extraLabel]})`;
        }

        signalsHtml += `
          <div class="${signalClass} rounded-lg p-1.5 text-xs">
            <div class="flex items-center justify-between mb-0.5">
              <span class="font-medium">${cfg.icon} ${cfg.label}</span>
              ${score !== null ? `<span class="${scoreClass} font-mono">${score > 0 ? '+' : ''}${typeof score === 'number' ? score.toFixed(0) : score}</span>` : ''}
            </div>
            <div class="text-xs opacity-80 truncate overflow-hidden text-ellipsis">${signal || '-'}${extraInfo}</div>
          </div>
        `;
      });

      if (signalsGrid) {
        if (activeSignals > 0) {
          signalsGrid.innerHTML = signalsHtml;
        } else {
          signalsGrid.innerHTML = `<div class="col-span-full text-center text-slate-500 py-4">No signal data available yet. Wait for next cycle.</div>`;
        }
      }

      // Summary text
      if (signalsSummary) {
        if (dirSignals) {
          signalsSummary.innerHTML = `<span class="text-slate-400">Active signals:</span> ${dirSignals}`;
        } else {
          signalsSummary.innerHTML = `<span class="text-slate-400">Signals update every ~10 seconds when bot is running</span>`;
        }
      }
    } else if (signalsSection) {
      signalsSection.classList.add("hidden");
    }

    // Update trade history
    $("botDetailHistorySymbol").textContent = bot.symbol;
    const trades = bot.trade_history || [];

    if (trades.length === 0) {
      $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-500">No bot-only trades recorded yet</td></tr>`;
    } else {
      $("botDetailTradesBody").innerHTML = trades.map(trade => {
        const tradePnl = formatPnL(trade.realized_pnl);
        return `
          <tr class="hover:bg-slate-700/30">
            <td class="px-3 py-2 text-slate-400">${formatTime(trade.time)}</td>
            <td class="px-3 py-2">${trade.side}</td>
            <td class="px-3 py-2 text-right ${tradePnl.class}">${tradePnl.text}</td>
            <td class="px-3 py-2 text-slate-500">${trade.bot_id ? trade.bot_id.slice(0, 8) + "..." : "-"}</td>
          </tr>
        `;
      }).join("");
    }

    // Update footer timestamps
    $("botDetailFirstTrade").textContent = `Symbol-wide first raw trade: ${bot.symbol_first_trade_at ? formatTime(bot.symbol_first_trade_at) : "-"}`;
    $("botDetailLastTrade").textContent = `Symbol-wide last raw trade: ${bot.symbol_last_trade_at ? formatTime(bot.symbol_last_trade_at) : "-"}`;
    refreshBotDetailLogs();

  } catch (error) {
    const notFound = error?.status === 404;
    $("botDetailSymbol").textContent = notFound ? "Bot unavailable" : "Error";
    if ($("botDetailBaselineMeta")) $("botDetailBaselineMeta").textContent = "Unable to load baseline metadata";
    $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center ${notFound ? "text-amber-300" : "text-red-400"}">${notFound ? "Bot no longer exists or the dashboard list was stale. The bot list was refreshed." : `Failed to load: ${error.message}`}</td></tr>`;
    if (notFound) {
      showToast("Bot detail was stale. The dashboard list was refreshed.", "warning");
    }
  }
}

/**
 * Close the bot detail modal.
 */

// ============================================================
// All Closed PnL Modal Functions
// ============================================================

// let allPnlCurrentPage = 1;  // Defined in app_v5.js
// let allPnlTotalPages = 1;  // Defined in app_v5.js

let allPnlAutoRefreshEnabled = true;
let allPnlLastUpdatedAt = null;
let allPnlLastUpdatedTimerId = null;
let allPnlKnownRowIds = new Map(); // id -> { hash, tr, card }
let allPnlIsRefreshing = false;

const ALL_PNL_MODE_COLORS = {
  neutral: "bg-slate-500/20 text-slate-300",
  neutral_classic_bybit: "bg-slate-500/20 text-slate-300",
  long: "bg-emerald-500/20 text-emerald-400",
  short: "bg-red-500/20 text-red-400",
  scalp_pnl: "bg-amber-500/20 text-amber-400",
  scalp_market: "bg-purple-500/20 text-purple-400",
};
const ALL_PNL_RANGE_COLORS = {
  fixed: "bg-blue-500/20 text-blue-400",
  dynamic: "bg-cyan-500/20 text-cyan-400",
  trailing: "bg-orange-500/20 text-orange-400",
};

function allPnlRowHash(log) {
  return `${log.id}|${log.realized_pnl}|${log.balance_after}|${log.bot_id}`;
}


function allPnlBuildRowHTML(log) {
  const pnl = formatPnL(log.realized_pnl);
  const balance = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : "-";
  const investment = log.bot_investment ? `$${formatNumber(log.bot_investment, 0)}` : "-";
  const leverage = log.bot_leverage ? `${log.bot_leverage}x` : "-";
  const mode = log.bot_mode || "-";
  const rangeMode = log.bot_range_mode || "-";
  const botIdShort = log.bot_id ? log.bot_id.slice(0, 8) : "-";
  const modeClass = ALL_PNL_MODE_COLORS[mode] || "bg-slate-700 text-slate-400";
  const rangeClass = ALL_PNL_RANGE_COLORS[rangeMode] || "bg-slate-700 text-slate-400";
  const pnlVal = parseFloat(log.realized_pnl || 0);
  const pnlBgClass = pnlVal > 0 ? "allpnl-pnl-cell--profit" : pnlVal < 0 ? "allpnl-pnl-cell--loss" : "";

  return `<td class="px-3 py-2 text-slate-400 whitespace-nowrap text-[11px]">${allPnlFormatCompactTime(log.time)}</td>
    <td class="px-3 py-2 font-semibold text-white">${escapeHtml(log.symbol || "-")}</td>
    <td class="px-3 py-2 text-slate-300">${escapeHtml(log.side || "-")}</td>
    <td class="px-3 py-2 text-right font-semibold ${pnl.class} ${pnlBgClass} rounded-sm">${pnl.text}</td>
    <td class="px-3 py-2 text-right text-slate-400">${balance}</td>
    <td class="px-3 py-2 text-right text-slate-400">${investment}</td>
    <td class="px-3 py-2 text-center text-slate-400">${leverage}</td>
    <td class="px-3 py-2 text-center"><span class="px-1.5 py-0.5 ${modeClass} rounded text-[10px]">${escapeHtml(mode)}</span></td>
    <td class="px-3 py-2 text-center"><span class="px-1.5 py-0.5 ${rangeClass} rounded text-[10px]">${escapeHtml(rangeMode)}</span></td>
    <td class="px-3 py-2 text-slate-500 font-mono text-[10px]" title="${escapeHtml(log.bot_id || "N/A")}">${escapeHtml(botIdShort)}</td>`;
}

function clearAllPnlFilters() {
  $("allPnlStartDate").value = "";
  $("allPnlEndDate").value = "";
  $("allPnlSymbolFilter").value = "";
  allPnlCurrentPage = 1;
  refreshAllPnlModal(true);
}

/**
 * Change page for pagination.
 */
function allPnlChangePage(delta) {
  const newPage = allPnlCurrentPage + delta;
  if (newPage >= 1 && newPage <= allPnlTotalPages) {
    allPnlCurrentPage = newPage;
    refreshAllPnlModal(true);
  }
}

function startAllPnlAutoRefresh() {
  stopAllPnlAutoRefresh();
  if (!allPnlAutoRefreshEnabled) return;
  allPnlModalRefreshInterval = window.setInterval(() => {
    const modalEl = $("allPnlModal");
    if (!modalEl || modalEl.classList.contains("hidden")) {
      stopAllPnlAutoRefresh();
      return;
    }
    refreshAllPnlModal(false);
  }, 10000);
  const dot = $("allPnlLiveDot");
  if (dot) dot.classList.remove("allpnl-live-dot--paused");
}

function stopAllPnlAutoRefresh() {
  if (allPnlModalRefreshInterval) {
    clearInterval(allPnlModalRefreshInterval);
    allPnlModalRefreshInterval = null;
  }
}

function toggleAllPnlAutoRefresh() {
  const checkbox = $("allPnlAutoRefresh");
  allPnlAutoRefreshEnabled = checkbox ? checkbox.checked : true;
  const dot = $("allPnlLiveDot");
  if (allPnlAutoRefreshEnabled) {
    startAllPnlAutoRefresh();
    if (dot) dot.classList.remove("allpnl-live-dot--paused");
  } else {
    stopAllPnlAutoRefresh();
    if (dot) dot.classList.add("allpnl-live-dot--paused");
  }
}

function updateAllPnlLastUpdatedText() {
  const el = $("allPnlLastUpdated");
  if (!el || !allPnlLastUpdatedAt) return;
  el.textContent = `Updated ${formatTimeAgo(allPnlLastUpdatedAt)}`;
}

/**
 * Refresh the All PnL modal data with incremental updates.
 * @param {boolean} forceFullRebuild - true to rebuild entire table (page change, filter, first open)
 */
async function refreshAllPnlModal(forceFullRebuild = false) {
  if (allPnlIsRefreshing) return;
  allPnlIsRefreshing = true;

  const tbody = $("allPnlTableBody");
  const cardsBody = $("allPnlCardsBody");

  if (forceFullRebuild || allPnlKnownRowIds.size === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="px-3 py-8 text-center text-slate-500">Loading...</td></tr>`;
    cardsBody.innerHTML = `<div class="px-3 py-8 text-center text-slate-500 text-sm">Loading...</div>`;
    allPnlKnownRowIds.clear();
  }

  const scrollContainer = $("allPnlBody");
  const savedScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;

  try {
    const params = new URLSearchParams();
    params.set("page", allPnlCurrentPage);

    const startDate = $("allPnlStartDate").value;
    const endDate = $("allPnlEndDate").value;
    const symbol = $("allPnlSymbolFilter").value.trim().toUpperCase();

    // When searching by symbol without date filters, fetch all records for that coin
    if (symbol && !startDate && !endDate) {
      params.set("per_page", 5000);
    } else {
      params.set("per_page", 100);
    }

    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    if (symbol) params.set("symbol", symbol);

    const data = await fetchJSON(`/pnl/all?${params.toString()}`);
    const logs = data.logs || [];
    const summary = data.summary || {};
    const pagination = data.pagination || {};

    // Update summary stats
    const totalPnlFormatted = formatPnL(summary.total_pnl);
    const totalPnlEl = $("allPnlTotalPnl");
    totalPnlEl.textContent = totalPnlFormatted.text;
    totalPnlEl.className = `metric-box__value ${totalPnlFormatted.class}`;

    $("allPnlTotalTrades").textContent = summary.total_trades || 0;
    $("allPnlWins").textContent = summary.wins || 0;
    $("allPnlLosses").textContent = summary.losses || 0;
    $("allPnlWinRate").textContent = `${summary.win_rate || 0}%`;
    $("allPnlRecordCount").textContent = `${pagination.total_records || 0} records`;

    // Update pagination
    allPnlTotalPages = pagination.total_pages || 1;
    $("allPnlPageInfo").textContent = `Page ${pagination.page} of ${allPnlTotalPages}`;
    $("allPnlPrevPage").disabled = pagination.page <= 1;
    $("allPnlNextPage").disabled = pagination.page >= allPnlTotalPages;

    // Update live indicator
    allPnlLastUpdatedAt = new Date();
    updateAllPnlLastUpdatedText();

    // Empty result
    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="px-3 py-8 text-center text-slate-500">No closed PnL records found</td></tr>`;
      cardsBody.innerHTML = `<div class="px-3 py-8 text-center text-slate-500 text-sm">No closed PnL records found</div>`;
      allPnlKnownRowIds.clear();
      return;
    }

    const incomingIds = new Set(logs.map(l => l.id));

    if (forceFullRebuild || allPnlKnownRowIds.size === 0) {
      // ---- FULL REBUILD ----
      allPnlKnownRowIds.clear();

      const fragment = document.createDocumentFragment();
      const cardFragment = document.createDocumentFragment();

      logs.forEach(log => {
        const tr = document.createElement("tr");
        tr.dataset.id = log.id;
        tr.className = "hover:bg-slate-700/30 transition-colors";
        tr.innerHTML = allPnlBuildRowHTML(log);
        fragment.appendChild(tr);

        const card = document.createElement("article");
        card.dataset.id = log.id;
        card.className = "allpnl-card";
        card.innerHTML = allPnlBuildCardHTML(log);
        cardFragment.appendChild(card);

        allPnlKnownRowIds.set(log.id, { hash: allPnlRowHash(log), tr, card });
      });

      tbody.innerHTML = "";
      tbody.appendChild(fragment);
      cardsBody.innerHTML = "";
      cardsBody.appendChild(cardFragment);

    } else {
      // ---- INCREMENTAL PATCH ----

      // Remove rows no longer in response
      for (const [id, entry] of allPnlKnownRowIds) {
        if (!incomingIds.has(id)) {
          if (entry.tr && entry.tr.parentNode) entry.tr.remove();
          if (entry.card && entry.card.parentNode) entry.card.remove();
          allPnlKnownRowIds.delete(id);
        }
      }

      // Walk incoming logs and insert/update as needed
      let prevTr = null;
      let prevCard = null;

      for (let i = 0; i < logs.length; i++) {
        const log = logs[i];
        const hash = allPnlRowHash(log);
        const existing = allPnlKnownRowIds.get(log.id);

        if (!existing) {
          // NEW ROW
          const tr = document.createElement("tr");
          tr.dataset.id = log.id;
          tr.className = "hover:bg-slate-700/30 transition-colors allpnl-row--new";
          tr.innerHTML = allPnlBuildRowHTML(log);

          const card = document.createElement("article");
          card.dataset.id = log.id;
          card.className = "allpnl-card allpnl-row--new";
          card.innerHTML = allPnlBuildCardHTML(log);

          if (prevTr && prevTr.nextSibling) {
            tbody.insertBefore(tr, prevTr.nextSibling);
          } else if (!prevTr) {
            tbody.insertBefore(tr, tbody.firstChild);
          } else {
            tbody.appendChild(tr);
          }

          if (prevCard && prevCard.nextSibling) {
            cardsBody.insertBefore(card, prevCard.nextSibling);
          } else if (!prevCard) {
            cardsBody.insertBefore(card, cardsBody.firstChild);
          } else {
            cardsBody.appendChild(card);
          }

          allPnlKnownRowIds.set(log.id, { hash, tr, card });
          prevTr = tr;
          prevCard = card;

          setTimeout(() => {
            tr.classList.remove("allpnl-row--new");
            card.classList.remove("allpnl-row--new");
          }, 1600);

        } else if (existing.hash !== hash) {
          // CHANGED ROW
          existing.tr.innerHTML = allPnlBuildRowHTML(log);
          if (existing.card) existing.card.innerHTML = allPnlBuildCardHTML(log);
          existing.hash = hash;
          prevTr = existing.tr;
          prevCard = existing.card;

        } else {
          // UNCHANGED
          prevTr = existing.tr;
          prevCard = existing.card;
        }
      }

      // Restore scroll position
      if (scrollContainer) {
        scrollContainer.scrollTop = savedScrollTop;
      }
    }

  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="10" class="px-3 py-8 text-center text-red-400">Failed to load: ${error.message}</td></tr>`;
    cardsBody.innerHTML = `<div class="px-3 py-8 text-center text-red-400 text-sm">Failed to load: ${error.message}</div>`;
  } finally {
    allPnlIsRefreshing = false;
  }
}

/**
 * Switch between Status and Log tabs in the modal.
 * @param {string} tab - Tab name: 'status' or 'log'
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Log category definitions for filtering and classification.
 * Match functions run against the raw log line for reliable detection.
 */
const LOG_CATEGORIES = [
  { id: 'all',      label: 'All',          match: null },
  { id: 'errors',   label: 'Errors',       match: line => /\[ERROR\]|❌|Traceback|Exception/.test(line) },
  { id: 'warnings', label: 'Warnings',     match: line => /\[WARNING\]|⚠️/.test(line) },
  { id: 'orders',   label: 'Orders',       match: line => /Placing orders|Placed \d+ new orders|levels need orders|order placed|cancel.*order|Trailing (?:LONG|SHORT)/i.test(line) },
  { id: 'risk',     label: 'Risk/Safety',  match: line => /Opening guard|NEUTRAL_GATE blocked|Strong trend detected|Breakout guard|risk.?stop|flatten|Inventory cap|Max loss|margin warning|liquidat/i.test(line) },
  { id: 'strategy', label: 'Strategy',     match: line => /SETUP_QUALITY|Regime=|direction_score|ATR-adaptive|Smart grid:|Grid distribution=|ENTRY_GATE|Trend reversal check/.test(line) },
  { id: 'cycles',   label: 'Cycles',       match: line => /Running bot cycle|🤖 Running|Cycle completed|✓ Cycle|Bot started|Bot stopped/.test(line) },
  { id: 'api',      label: 'API',          match: line => /Bybit API|retCode=|leverage not modified/.test(line) },
];

/** Important severity set — used by the "Important" quick filter. */
const LOG_IMPORTANT_SEVERITIES = new Set(['error', 'warning', 'bot-start', 'bot-stop', 'profit', 'highlight']);
const LOG_IMPORTANT_CATEGORIES = new Set(['errors', 'warnings', 'orders', 'risk']);

let activeLogFilters = new Set(['all']);
let parsedLogLines = [];
let logFilterChipsInitialized = false;
let logAutoScroll = true;
let logPaused = false;
let logSearchTerm = '';
let logImportantOnly = false;
let _logSearchDebounceTimer = null;

const LOG_RE_TIMESTAMP = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s*/;
const LOG_RE_LEVEL = /\[(INFO|WARNING|ERROR|DEBUG|CRITICAL)\]\s*/;
const LOG_RE_SYMBOL = /\[([A-Z0-9]+(?:USDT|USD|USDC))(?::[\da-f]+)?\]\s*/;

/**
 * Parse a raw log line into structured parts.
 */
function parseLogLine(raw) {
  let rest = raw;
  let timestamp = '';
  let level = '';
  let symbol = '';

  const tsMatch = rest.match(LOG_RE_TIMESTAMP);
  if (tsMatch) { timestamp = tsMatch[1]; rest = rest.slice(tsMatch[0].length); }

  const lvlMatch = rest.match(LOG_RE_LEVEL);
  if (lvlMatch) { level = lvlMatch[1]; rest = rest.slice(lvlMatch[0].length); }

  const symMatch = rest.match(LOG_RE_SYMBOL);
  if (symMatch) { symbol = symMatch[1]; rest = rest.slice(symMatch[0].length); }

  // Determine category — first matching rule wins
  let category = '';
  for (const cat of LOG_CATEGORIES) {
    if (cat.match && cat.match(raw)) { category = cat.id; break; }
  }

  // Determine severity for row styling
  let severity = 'info';
  if (level === 'ERROR' || /❌|Traceback|Exception/.test(raw)) severity = 'error';
  else if (level === 'WARNING' || /⚠️/.test(raw)) severity = 'warning';
  else if (/Bot started|✅ Bot started|▶️ Bot started/.test(raw)) severity = 'bot-start';
  else if (/Bot stopped|🛑 Bot stopped|⏹️ Bot stopped/.test(raw)) severity = 'bot-stop';
  else if (/Running bot cycle|🤖 Running|Cycle completed|✓ Cycle/.test(raw)) severity = 'cycle';
  else if (/realized_pnl.*\+/.test(raw)) severity = 'profit';
  else if (/Opening guard|NEUTRAL_GATE blocked|Strong trend detected|Placing orders|Placed \d+ new orders|ENTRY_GATE/.test(raw)) severity = 'highlight';

  return { raw, timestamp, level, symbol, message: rest.trim(), category, severity };
}

/**
 * Initialize log filter chips inside #logFilterBar.
 */
function initLogFilterChips() {
  const bar = document.getElementById('logFilterBar');
  if (!bar || logFilterChipsInitialized) return;
  logFilterChipsInitialized = true;

  bar.innerHTML = LOG_CATEGORIES.map(cat =>
    `<button class="log-filter-chip${cat.id === 'all' ? ' log-filter-chip--active' : ''}" data-category="${cat.id}" onclick="toggleLogFilter('${cat.id}')">` +
    `${escapeHtml(cat.label)}` +
    (cat.match ? `<span class="log-filter-chip__count" data-count-for="${cat.id}">0</span>` : '') +
    `</button>`
  ).join('');

  // Wire up search input
  const searchInput = document.getElementById('logSearchInput');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(_logSearchDebounceTimer);
      _logSearchDebounceTimer = setTimeout(() => {
        logSearchTerm = searchInput.value.trim().toLowerCase();
        renderFilteredLogView();
      }, 180);
    });
  }
}

/**
 * Toggle a log filter chip on/off.
 */
function toggleLogFilter(categoryId) {
  // Deactivate important-only if user manually picks categories
  if (logImportantOnly) {
    logImportantOnly = false;
    const btn = document.getElementById('logImportantToggle');
    if (btn) btn.classList.remove('log-toggle-btn--important');
  }

  if (categoryId === 'all') {
    activeLogFilters.clear();
    activeLogFilters.add('all');
  } else {
    activeLogFilters.delete('all');
    if (activeLogFilters.has(categoryId)) {
      activeLogFilters.delete(categoryId);
    } else {
      activeLogFilters.add(categoryId);
    }
    if (activeLogFilters.size === 0) activeLogFilters.add('all');
  }

  syncFilterChipStates();
  renderFilteredLogView();
}

/**
 * Sync visual active state on all filter chips from activeLogFilters set.
 */
function syncFilterChipStates() {
  const bar = document.getElementById('logFilterBar');
  if (bar) {
    bar.querySelectorAll('.log-filter-chip').forEach(chip => {
      const id = chip.getAttribute('data-category');
      chip.classList.toggle('log-filter-chip--active', activeLogFilters.has(id));
    });
  }
}

/**
 * Toggle "Important only" quick filter.
 */
function toggleImportantOnly() {
  logImportantOnly = !logImportantOnly;
  const btn = document.getElementById('logImportantToggle');
  if (btn) btn.classList.toggle('log-toggle-btn--important', logImportantOnly);

  if (logImportantOnly) {
    activeLogFilters.clear();
    LOG_IMPORTANT_CATEGORIES.forEach(c => activeLogFilters.add(c));
  } else {
    activeLogFilters.clear();
    activeLogFilters.add('all');
  }
  syncFilterChipStates();
  renderFilteredLogView();
}

/**
 * Toggle auto-scroll to bottom on new log content.
 */
function toggleLogAutoScroll() {
  logAutoScroll = !logAutoScroll;
  const btn = document.getElementById('logAutoScrollToggle');
  if (btn) btn.classList.toggle('log-toggle-btn--on', logAutoScroll);
  if (logAutoScroll) {
    const box = document.getElementById('botLogBox');
    if (box) box.scrollTop = box.scrollHeight;
  }
}

/**
 * Toggle pause/resume of live log updates.
 */
function toggleLogPause() {
  logPaused = !logPaused;
  const btn = document.getElementById('logPauseToggle');
  if (btn) {
    btn.classList.toggle('log-toggle-btn--warn', logPaused);
    btn.innerHTML = logPaused ? '\u23F5\uFE0F Resume' : '\u23F8\uFE0F Pause';
  }
}

/**
 * Copy all currently visible log lines to clipboard.
 */
function copyVisibleLogs() {
  const box = document.getElementById('botLogBox');
  if (!box) return;
  const rows = box.querySelectorAll('.log-row:not(.log-row--search-hidden)');
  const text = Array.from(rows).map(r => r.textContent.trim()).join('\n');
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const toast = document.getElementById('logCopyToast');
    if (toast) {
      toast.classList.add('log-copy-toast--visible');
      setTimeout(() => toast.classList.remove('log-copy-toast--visible'), 1400);
    }
  }).catch(() => {});
}

/**
 * Update filter chip count badges from parsedLogLines.
 */
function updateFilterCounts() {
  const counts = {};
  for (const cat of LOG_CATEGORIES) {
    if (cat.match) counts[cat.id] = 0;
  }
  for (const l of parsedLogLines) {
    if (l.category && counts[l.category] !== undefined) counts[l.category]++;
  }
  for (const id in counts) {
    const badge = document.querySelector(`[data-count-for="${id}"]`);
    if (badge) badge.textContent = counts[id];
  }
}

/**
 * Highlight search term in an already-escaped HTML string.
 */
function highlightSearchTerm(escapedHtml, term) {
  if (!term) return escapedHtml;
  // Escape regex special chars in the search term, then build case-insensitive regex
  const safeterm = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`(${safeterm})`, 'gi');
  return escapedHtml.replace(re, '<mark>$1</mark>');
}

/**
 * Render filtered log view from cached parsedLogLines into #botLogBox.
 */
let runnerStatusPollInterval = null;
let runnerServiceActionInFlight = false;
let pendingServiceAction = null;
const RUNNER_SERVICE_API_MODE_KEY = "dashboard_runner_service_api_mode";
let runnerServiceApiMode = loadRunnerServiceApiMode();

function isHttp404(error) {
  return /404/.test(String(error?.message || ""));
}

function loadRunnerServiceApiMode() {
  try {
    return localStorage.getItem(RUNNER_SERVICE_API_MODE_KEY) === "modern" ? "modern" : "unknown";
  } catch (error) {
    return "unknown";
  }
}

function setRunnerServiceApiMode(mode) {
  runnerServiceApiMode = mode === "modern" ? "modern" : mode === "legacy" ? "legacy" : "unknown";
  try {
    if (runnerServiceApiMode === "modern") {
      localStorage.setItem(RUNNER_SERVICE_API_MODE_KEY, "modern");
    } else {
      localStorage.removeItem(RUNNER_SERVICE_API_MODE_KEY);
    }
  } catch (error) {
    // Ignore storage failures; the in-memory mode still avoids repeated probes.
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeLegacyRunnerStatusPayload(legacy) {
  const runner = legacy.runner || {};
  return {
    runner_active: runner.active === true,
    runner_pid: runner.pid || null,
    detected_via: runner.detected_via || "bot_status",
    stop_flag_exists: false,
    _legacy: true,
  };
}

async function fetchLegacyRunnerStatusPayload() {
  const legacy = await fetchJSON("/bot/status");
  return normalizeLegacyRunnerStatusPayload(legacy);
}

async function fetchRunnerStatusPayload() {
  // Poll the legacy status route by default; only use /services once this browser
  // has already confirmed that the newer service API exists.
  if (runnerServiceApiMode !== "modern") {
    return fetchLegacyRunnerStatusPayload();
  }

  try {
    const data = await fetchJSON("/services/status", { suppress404Log: true });
    setRunnerServiceApiMode("modern");
    return data;
  } catch (error) {
    if (!isHttp404(error)) {
      throw error;
    }

    setRunnerServiceApiMode("legacy");
    return fetchLegacyRunnerStatusPayload();
  }
}

async function waitForRunnerState(active, timeoutMs = 15000, pollMs = 1000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const status = await fetchRunnerStatusPayload().catch(() => null);
    if (status && status.runner_active === active) {
      return status;
    }
    await delay(pollMs);
  }

  return null;
}

async function restartRunnerLegacyFlow() {
  await fetchJSON("/runner/stop", { method: "POST" });

  const stoppedStatus = await waitForRunnerState(false, 20000, 1000);
  if (!stoppedStatus) {
    throw new Error("Runner did not stop within 20s");
  }

  let lastError = null;
  const startDeadline = Date.now() + 15000;
  while (Date.now() < startDeadline) {
    try {
      const startData = await fetchJSON("/runner/start", { method: "POST" });
      return {
        ...startData,
        _legacy: true,
      };
    } catch (error) {
      lastError = error;
      if (!/409/.test(String(error?.message || ""))) {
        throw error;
      }
      await delay(1000);
    }
  }

  throw lastError || new Error("Runner restart timed out");
}

async function performLegacyRunnerServiceAction(action) {
  if (action === "restart") {
    return restartRunnerLegacyFlow();
  }

  if (action === "stop") {
    return fetchJSON("/runner/stop", { method: "POST" });
  }

  throw new Error(`Unsupported runner action: ${action}`);
}

async function performRunnerServiceAction(action) {
  let path = null;
  if (action === "restart") {
    path = "/services/restart";
  } else if (action === "stop") {
    path = "/services/stop";
  } else {
    throw new Error(`Unsupported runner action: ${action}`);
  }

  if (runnerServiceApiMode === "legacy") {
    return performLegacyRunnerServiceAction(action);
  }

  try {
    const data = await fetchJSON(path, { method: "POST", suppress404Log: true });
    setRunnerServiceApiMode("modern");
    return data;
  } catch (error) {
    if (!isHttp404(error)) {
      throw error;
    }

    setRunnerServiceApiMode("legacy");
    return performLegacyRunnerServiceAction(action);
  }
}

function getRunnerActionButtons(action) {
  return Array.from(document.querySelectorAll(`[data-runner-action="${action}"]`));
}

function rememberRunnerButtonDefaults(button) {
  if (!button) return;
  if (!button.dataset.defaultHtml) button.dataset.defaultHtml = button.innerHTML;
  if (!button.dataset.defaultClass) button.dataset.defaultClass = button.className;
}

function setRunnerActionButtonState(action, html, disabled) {
  getRunnerActionButtons(action).forEach((button) => {
    rememberRunnerButtonDefaults(button);
    button.innerHTML = html;
    button.disabled = disabled;
    button.classList.toggle("opacity-60", disabled);
  });
}

function restoreRunnerActionButtons(action) {
  getRunnerActionButtons(action).forEach((button) => {
    rememberRunnerButtonDefaults(button);
    button.innerHTML = button.dataset.defaultHtml;
    button.className = button.dataset.defaultClass;
    button.disabled = false;
    button.classList.remove("opacity-60");
  });
}


function syncRunnerButtonsForStatus(isActive, isStopping) {
  const startBtn = $("btnStartRunner");
  if (startBtn) {
    const shouldDisableStart = isActive || isStopping;
    startBtn.disabled = shouldDisableStart;
    startBtn.classList.toggle("opacity-50", shouldDisableStart);
    startBtn.title = isStopping
      ? "Runner is stopping"
      : isActive
        ? "Runner is already running"
        : "Click to start the runner";
  }

  if (runnerServiceActionInFlight) {
    return;
  }

  getRunnerActionButtons("stop").forEach((button) => {
    rememberRunnerButtonDefaults(button);
    const shouldDisable = !isActive || isStopping;
    button.disabled = shouldDisable;
    button.classList.toggle("opacity-50", shouldDisable);
    button.title = shouldDisable
      ? "Runner is not currently active"
      : "Stop the runner process";
  });

  getRunnerActionButtons("restart").forEach((button) => {
    rememberRunnerButtonDefaults(button);
    button.disabled = false;
    button.classList.remove("opacity-50");
    button.title = isActive
      ? "Restart the runner process"
      : "Start the runner process";
  });
}

async function updateRunnerStatus() {
  const badge = $("runnerStatusBadge");
  const dot = $("runnerStatusDot");
  const text = $("runnerStatusText");
  const startBtn = $("btnStartRunner");

  if (!badge && !dot && !text && !startBtn) return null;

  try {
    const data = await fetchRunnerStatusPayload();
    const isActive = data.runner_active === true;
    const isStopping = isActive && data.stop_flag_exists === true;
    const pid = data.runner_pid;
    const pidSuffix = pid ? ` (PID ${pid})` : "";

    if (isStopping) {
      setRunnerStatusDisplay({
        badgeText: "● Stopping...",
        badgeClass: "px-2 py-0.5 text-xs font-medium rounded-full bg-amber-500/20 text-amber-400",
        dotClass: "inline-block w-2.5 h-2.5 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.55)]",
        dotTitle: `Runner stopping${pidSuffix}`,
        textValue: "Runner: Stopping",
        textClass: "hidden md:inline text-[11px] font-mono text-amber-300",
      });
    } else if (isActive) {
      setRunnerStatusDisplay({
        badgeText: "● Running",
        badgeClass: "px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/20 text-emerald-400",
        dotClass: "inline-block w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.55)]",
        dotTitle: `Runner active${pidSuffix}`,
        textValue: pid ? `Runner: Active #${pid}` : "Runner: Active",
        textClass: "hidden md:inline text-[11px] font-mono text-emerald-300",
      });
    } else {
      setRunnerStatusDisplay({
        badgeText: "○ Stopped",
        badgeClass: "px-2 py-0.5 text-xs font-medium rounded-full bg-red-500/20 text-red-400",
        dotClass: "inline-block w-2.5 h-2.5 rounded-full bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.45)]",
        dotTitle: "Runner stopped",
        textValue: "Runner: Stopped",
        textClass: "hidden md:inline text-[11px] font-mono text-red-300",
      });
    }
    syncRunnerButtonsForStatus(isActive, isStopping);
    return data;
  } catch (e) {
    setRunnerStatusDisplay({
      badgeText: "? Unknown",
      badgeClass: "px-2 py-0.5 text-xs font-medium rounded-full bg-slate-700 text-slate-400",
      dotClass: "inline-block w-2.5 h-2.5 rounded-full bg-slate-500 shadow-[0_0_8px_rgba(100,116,139,0.4)]",
      dotTitle: "Runner status unknown",
      textValue: "Runner: Unknown",
      textClass: "hidden md:inline text-[11px] font-mono text-slate-400",
    });
    syncRunnerButtonsForStatus(false, false);
    return null;
  }
}

/**
 * Start the runner.py process via API.
 */
async function startRunner() {
  const btn = $("btnStartRunner");
  const badge = $("runnerStatusBadge");

  if (!btn) return;

  // Disable button and show loading state
  const originalText = btn.innerHTML;
  btn.innerHTML = '<span class="mr-1">⏳</span> Starting...';
  btn.disabled = true;

  try {
    const data = await fetchJSON("/runner/start", { method: "POST" });

    if (data.success) {
      // Show success
      btn.innerHTML = '<span class="mr-1">✓</span> Starting...';
      btn.className = "px-3 py-1 text-xs bg-emerald-700 text-white font-medium rounded transition flex items-center";

      if (badge) {
        badge.textContent = "● Starting...";
        badge.className = "px-2 py-0.5 text-xs font-medium rounded-full bg-amber-500/20 text-amber-400";
      }

      // Wait a moment then refresh log to see new output
      setTimeout(() => {
        loadBotLog();
        btn.innerHTML = originalText;
        btn.disabled = false;
        btn.className = "px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded transition flex items-center";
        updateRunnerStatus();
      }, 3000);
      showToast(data.message || "Runner started", "success");
    } else {
      showToast(`Failed to start runner: ${data.message || "Unknown error"}`, "error");
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  } catch (e) {
    showToast(`Error starting runner: ${e.message}`, "error");
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

/**
 * Open the shared confirmation modal for service actions.
 */


function confirmRestartServices() {
  openServiceActionModal({
    action: "restart",
    path: "/services/restart",
    eyebrow: "Service Restart",
    title: "Restart Runner",
    message: "This will stop active bot cycles, then start a fresh runner process. Open positions will remain open.",
    warning: "Use restart after changing Python or config so the runner picks up the latest code.",
    confirmLabel: "Restart Runner",
    loadingLabel: "Restarting...",
    buttonBusyHtml: '<span class="mr-1">⏳</span> Restarting...',
    buttonSuccessHtml: '<span class="mr-1">✓</span> Restarted',
    confirmButtonClass: "inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-500",
    successToast: (data) => data?.new_pid ? `Runner restarted (PID ${data.new_pid})` : "Runner restarted",
  });
}

function confirmStopServices() {
  openServiceActionModal({
    action: "stop",
    path: "/services/stop",
    eyebrow: "Service Stop",
    title: "Stop Runner",
    message: "This will stop the runner. Bots will stop processing cycles until you restart it.",
    warning: "Open positions remain on the exchange but will be unmanaged while the runner is stopped.",
    confirmLabel: "Stop Runner",
    loadingLabel: "Stopping...",
    buttonBusyHtml: '<span class="mr-1">⏳</span> Stopping...',
    buttonSuccessHtml: '<span class="mr-1">✓</span> Stopped',
    confirmButtonClass: "inline-flex items-center gap-2 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-600",
    successToast: () => "Runner stopped",
  });
}

async function executeServiceAction() {
  if (!pendingServiceAction || runnerServiceActionInFlight) {
    return;
  }

  const action = pendingServiceAction;
  const confirmBtn = $("serviceActionConfirm");
  const confirmText = $("serviceActionConfirmText");
  const confirmSpinner = $("serviceActionConfirmSpinner");
  const cancelBtn = $("serviceActionCancel");

  runnerServiceActionInFlight = true;
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.classList.add("opacity-60");
  }
  if (cancelBtn) cancelBtn.disabled = true;
  if (confirmText) confirmText.textContent = action.loadingLabel;
  if (confirmSpinner) confirmSpinner.classList.remove("hidden");
  setRunnerActionButtonState(action.action, action.buttonBusyHtml, true);

  try {
    const data = await performRunnerServiceAction(action.action);
    if (!data.success) {
      throw new Error(data.error || data.message || "Unknown service error");
    }

    setRunnerActionButtonState(action.action, action.buttonSuccessHtml, true);
    closeServiceActionModal(true);
    showToast(action.successToast(data), "success");
    updateRunnerStatus();
    setTimeout(updateRunnerStatus, 1500);
    setTimeout(updateRunnerStatus, 4000);
    setTimeout(loadBotLog, 1200);
    setTimeout(() => {
      restoreRunnerActionButtons(action.action);
      updateRunnerStatus();
    }, 2500);
  } catch (error) {
    restoreRunnerActionButtons(action.action);
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.classList.remove("opacity-60");
    }
    if (cancelBtn) cancelBtn.disabled = false;
    if (confirmText) confirmText.textContent = action.confirmLabel;
    if (confirmSpinner) confirmSpinner.classList.add("hidden");
    showToast(`${action.title} failed: ${error.message}`, "error");
    updateRunnerStatus();
  } finally {
    runnerServiceActionInFlight = false;
  }
}

/**
 * Initialize bot modal event listeners.
 */

// ============================================================
// Price Predictions
// ============================================================

async function refreshPredictions() {
  try {
    const loadingEl = $("predictions-loading");
    if (loadingEl) loadingEl.classList.remove("hidden");

    const data = await fetchJSON("/predictions");
    const predictions = data.predictions || [];

    if (loadingEl) loadingEl.classList.add("hidden");

    const emptyEl = $("predictions-empty");
    const gridEl = $("predictions-grid");

    if (!gridEl) return;

    if (predictions.length === 0) {
      if (emptyEl) emptyEl.classList.remove("hidden");
      gridEl.classList.remove("predictions-card-grid--compact");
      gridEl.classList.add("hidden");
      return;
    }

    if (emptyEl) emptyEl.classList.add("hidden");
    gridEl.classList.remove("hidden");
    gridEl.classList.toggle("predictions-card-grid--compact", predictions.length <= 2);

    // Build prediction cards
    gridEl.innerHTML = predictions.map(pred => {
      const directionColors = {
        "STRONG_LONG": "bg-emerald-600 text-white",
        "LONG": "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30",
        "NEUTRAL": "bg-slate-600/20 text-slate-400 border border-slate-500/30",
        "SHORT": "bg-red-500/20 text-red-400 border border-red-500/30",
        "STRONG_SHORT": "bg-red-600 text-white",
        "ERROR": "bg-gray-600 text-gray-400",
      };

      const directionIcons = {
        "STRONG_LONG": "🚀",
        "LONG": "📈",
        "NEUTRAL": "➖",
        "SHORT": "📉",
        "STRONG_SHORT": "💥",
        "ERROR": "⚠️",
      };

      const dirColor = directionColors[pred.direction] || directionColors["NEUTRAL"];
      const dirIcon = directionIcons[pred.direction] || "❓";

      // Format signals
      const signalsHtml = (pred.signals || []).slice(0, 4).map(s => {
        const sigColor = s.direction === "bullish" ? "text-emerald-400" :
          s.direction === "bearish" ? "text-red-400" : "text-slate-400";
        const sigIcon = s.direction === "bullish" ? "↑" : s.direction === "bearish" ? "↓" : "•";
        return `<span class="${sigColor} text-[10px]" title="${s.description}">${sigIcon} ${s.name}</span>`;
      }).join(" ");

      // Format patterns
      const patternsHtml = (pred.patterns || []).slice(0, 2).map(p =>
        `<span class="px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded text-[10px]">${p}</span>`
      ).join(" ");

      // S/R levels
      let srHtml = "";
      if (pred.sr_levels) {
        if (pred.sr_levels.support) {
          srHtml += `<span class="text-emerald-400 text-[10px]">S: ${formatPrice(pred.sr_levels.support)}</span> `;
        }
        if (pred.sr_levels.resistance) {
          srHtml += `<span class="text-red-400 text-[10px]">R: ${formatPrice(pred.sr_levels.resistance)}</span>`;
        }
      }

      // MTF alignment badge
      const mtfColor = pred.mtf_alignment?.includes("BULLISH") ? "text-emerald-400" :
        pred.mtf_alignment?.includes("BEARISH") ? "text-red-400" : "text-slate-500";

      // Build auto-direction signals section
      let autoSignalsHtml = "";
      if (pred.auto_direction && pred.direction_score !== null && pred.direction_score !== undefined) {
        const dirScore = pred.direction_score || 0;
        const scoreColor = dirScore > 30 ? "text-emerald-400" : dirScore < -30 ? "text-red-400" : "text-slate-400";
        const scoreBg = dirScore > 30 ? "bg-emerald-500/20" : dirScore < -30 ? "bg-red-500/20" : "bg-slate-700/50";

        // Determine direction based on score
        let autoDir = "NEUTRAL";
        let autoDirIcon = "➖";
        if (dirScore >= 35) { autoDir = "LONG"; autoDirIcon = "📈"; }
        else if (dirScore <= -35) { autoDir = "SHORT"; autoDirIcon = "📉"; }

        // Helper to get color based on score
        const getScoreColor = (score) => score > 0 ? "text-emerald-400" : score < 0 ? "text-red-400" : "text-slate-400";
        const formatScore = (score) => score != null ? (score > 0 ? `+${score.toFixed(0)}` : score.toFixed(0)) : '0';
        const sesColor = pred.session_signal === "FAVORABLE" ? "text-emerald-400" : pred.session_signal === "UNFAVORABLE" ? "text-red-400" : "text-slate-400";

        // Helper to get signal state label
        const getFundingState = (score) => {
          if (score >= 10) return "shorts crowded";
          if (score <= -10) return "longs crowded";
          return "neutral";
        };
        const getOBState = (score) => {
          if (score >= 10) return "buyers strong";
          if (score <= -10) return "sellers strong";
          return "balanced";
        };
        const getOIState = (score) => {
          if (score >= 10) return "new longs";
          if (score <= -10) return "new shorts";
          return "stable";
        };
        const getLiqState = (score) => {
          if (score >= 5) return "near short liq";
          if (score <= -5) return "near long liq";
          return "safe zone";
        };
        const getMRState = (score) => {
          if (score >= 10) return "oversold bounce";
          if (score <= -10) return "overbought drop";
          return "at mean";
        };
        const getSessionState = (name, signal) => {
          if (signal === "FAVORABLE") return "high activity";
          if (signal === "UNFAVORABLE") return "low activity";
          return "normal";
        };
        const getWhaleState = (score, bidWalls, askWalls) => {
          if (score >= 10) return "bid walls";
          if (score <= -10) return "ask walls";
          if (bidWalls > 0 || askWalls > 0) return "walls found";
          return "no walls";
        };

        // Dynamic descriptions based on current state
        const getFundingDesc = (score) => {
          if (score >= 10) return "Shorts paying longs heavily → bearish sentiment extreme → expect reversal UP";
          if (score <= -10) return "Longs paying shorts heavily → bullish sentiment extreme → expect reversal DOWN";
          return "Funding balanced, no extreme sentiment detected";
        };
        const getOBDesc = (score) => {
          if (score >= 10) return "Heavy buy orders stacked → strong demand → price likely to push UP";
          if (score <= -10) return "Heavy sell orders stacked → strong supply → price likely to push DOWN";
          return "Bid/ask depth balanced, no clear directional pressure";
        };
        const getOIDesc = (score) => {
          if (score >= 10) return "New money entering longs + price rising → strong confirmed uptrend";
          if (score <= -10) return "New money entering shorts + price falling → strong confirmed downtrend";
          return "No significant new positions, existing trend may be weakening";
        };
        const getLiqDesc = (score) => {
          if (score >= 5) return "Price near short liquidation zone → shorts may get squeezed → bullish";
          if (score <= -5) return "Price near long liquidation zone → longs may get cascaded → bearish";
          return "Price away from major liquidation clusters, safer zone";
        };
        const getMRDesc = (score) => {
          if (score >= 10) return "Price far BELOW moving averages + oversold RSI → expect bounce UP";
          if (score <= -10) return "Price far ABOVE moving averages + overbought RSI → expect pullback DOWN";
          return "Price near equilibrium with EMAs, no extreme deviation";
        };
        const getSessionDesc = (name, signal) => {
          if (name === "Asian") return "Asian session: Low volatility, range-bound, good for grid trading";
          if (name === "European") return "European session: Moderate volatility, trending moves begin";
          if (name === "US") return "US session: High volatility, big directional moves expected";
          if (name === "EU/US Overlap") return "EU/US overlap: Peak volatility, breakouts and reversals common";
          if (name === "Late") return "Late session: Low liquidity, consolidation before Asia";
          return "Market session active";
        };
        const getWhaleDesc = (score, bidWalls, askWalls, reason) => {
          if (score >= 10) return `Large bid walls detected nearby → strong support → bullish. ${reason || ''}`;
          if (score <= -10) return `Large ask walls detected nearby → strong resistance → bearish. ${reason || ''}`;
          if (bidWalls > 0 && askWalls > 0) return `Mixed walls: ${bidWalls} bid, ${askWalls} ask walls nearby`;
          if (bidWalls > 0) return `${bidWalls} bid wall(s) detected → potential support`;
          if (askWalls > 0) return `${askWalls} ask wall(s) detected → potential resistance`;
          return "No large orders (whale walls) detected near current price";
        };

        // Build signals grid - horizontal layout
        autoSignalsHtml = `
          <div class="mt-2 pt-2 border-t border-slate-700">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs text-slate-400 font-medium">Auto-Direction</span>
              <span class="px-2 py-0.5 rounded text-xs font-bold ${scoreBg} ${scoreColor}">
                ${autoDirIcon} ${autoDir} ${dirScore > 0 ? '+' : ''}${dirScore.toFixed(0)}
              </span>
            </div>
            <div class="grid grid-cols-4 gap-1.5 text-xs">
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getFundingDesc(pred.funding_score || 0)}">
                <div class="text-slate-400 mb-0.5">💰 Fund</div>
                <div class="${getScoreColor(pred.funding_score || 0)} font-semibold">${formatScore(pred.funding_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getFundingState(pred.funding_score || 0)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getOBDesc(pred.orderbook_score || 0)}">
                <div class="text-slate-400 mb-0.5">📚 OB</div>
                <div class="${getScoreColor(pred.orderbook_score || 0)} font-semibold">${formatScore(pred.orderbook_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getOBState(pred.orderbook_score || 0)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getOIDesc(pred.oi_score || 0)}">
                <div class="text-slate-400 mb-0.5">🔓 OI</div>
                <div class="${getScoreColor(pred.oi_score || 0)} font-semibold">${formatScore(pred.oi_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getOIState(pred.oi_score || 0)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getLiqDesc(pred.liquidation_score || 0)}">
                <div class="text-slate-400 mb-0.5">💧 Liq</div>
                <div class="${getScoreColor(pred.liquidation_score || 0)} font-semibold">${formatScore(pred.liquidation_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getLiqState(pred.liquidation_score || 0)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getSessionDesc(pred.session_name, pred.session_signal)}">
                <div class="text-slate-400 mb-0.5">🌍 Sess</div>
                <div class="${sesColor} font-semibold">${pred.session_name || 'N/A'}</div>
                <div class="text-[10px] text-slate-500 truncate">${getSessionState(pred.session_name, pred.session_signal)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getMRDesc(pred.mean_reversion_score || 0)}">
                <div class="text-slate-400 mb-0.5">📊 MR</div>
                <div class="${getScoreColor(pred.mean_reversion_score || 0)} font-semibold">${formatScore(pred.mean_reversion_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getMRState(pred.mean_reversion_score || 0)}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center" title="${getWhaleDesc(pred.whale_score || 0, pred.whale_bid_walls || 0, pred.whale_ask_walls || 0, pred.whale_reason)}">
                <div class="text-slate-400 mb-0.5">🐋 Whale</div>
                <div class="${getScoreColor(pred.whale_score || 0)} font-semibold">${formatScore(pred.whale_score)}</div>
                <div class="text-[10px] text-slate-500 truncate">${getWhaleState(pred.whale_score || 0, pred.whale_bid_walls || 0, pred.whale_ask_walls || 0)}</div>
              </div>
            </div>
          </div>
        `;
      }

      // AI Advisor section
      let aiAdvisorHtml = "";
      if (pred.ai_advisor_enabled) {
        const decision = pred.ai_decision || {};
        const regime = decision.regime || "N/A";
        const confidence = decision.confidence != null ? (decision.confidence * 100).toFixed(0) : "?";
        const action = decision.action || "N/A";
        const tradeAllowed = pred.ai_trade_allowed;
        const reasons = decision.reasons || [];
        const error = pred.ai_error;

        // Colors based on action/state
        const actionColor = action === "PAUSE" ? "text-red-400" :
          action === "ALLOW" ? "text-emerald-400" : "text-slate-400";
        const regimeColor = regime === "UP" ? "text-emerald-400" :
          regime === "DOWN" ? "text-red-400" : "text-amber-400";
        const tradeBadge = tradeAllowed === false
          ? '<span class="px-1.5 py-0.5 rounded text-[10px] bg-red-500/20 text-red-400">BLOCKED</span>'
          : tradeAllowed === true
            ? '<span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400">ALLOWED</span>'
            : '';

        const reasonsText = reasons.slice(0, 2).join(" | ") || "No reasons";

        aiAdvisorHtml = `
          <div class="mt-2 pt-2 border-t border-slate-700">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-xs text-slate-400 font-medium">AI Advisor</span>
              ${tradeBadge}
            </div>
            <div class="grid grid-cols-3 gap-1.5 text-xs">
              <div class="bg-slate-900/50 rounded p-1.5 text-center">
                <div class="text-slate-400 mb-0.5">Regime</div>
                <div class="${regimeColor} font-semibold">${regime}</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center">
                <div class="text-slate-400 mb-0.5">Conf</div>
                <div class="text-white font-semibold">${confidence}%</div>
              </div>
              <div class="bg-slate-900/50 rounded p-1.5 text-center">
                <div class="text-slate-400 mb-0.5">Action</div>
                <div class="${actionColor} font-semibold">${action}</div>
              </div>
            </div>
            ${error ? `<div class="mt-1 text-[10px] text-amber-400 truncate" title="${error}">⚠ ${error}</div>` : ""}
            ${!error && reasons.length ? `<div class="mt-1 text-[10px] text-slate-500 truncate" title="${reasons.join(' | ')}">${reasonsText}</div>` : ""}
          </div>
        `;
      }

      return `
        <div class="prediction-card-terminal">
          <div class="flex items-center justify-between mb-2 gap-2">
            <span class="font-semibold text-white text-sm truncate min-w-0" title="${pred.symbol}">${pred.symbol}</span>
            <span class="px-2 py-0.5 rounded text-xs font-medium ${dirColor}">
              ${dirIcon} ${pred.direction}
            </span>
          </div>

          <div class="flex items-center gap-2 mb-2">
            <div class="flex-1 bg-slate-700 rounded-full h-2">
              <div class="h-2 rounded-full ${pred.confidence >= 50 ? 'bg-emerald-500' : 'bg-amber-500'}"
                   style="width: ${Math.min(100, pred.confidence)}%"></div>
            </div>
            <span class="text-xs text-slate-400">${pred.confidence}%</span>
          </div>

          <div class="text-xs text-slate-500 mb-1">Score: ${pred.score?.toFixed(1) || 0}</div>

          ${signalsHtml ? `<div class="prediction-card-terminal__signals">${signalsHtml}</div>` : ""}

          ${patternsHtml ? `<div class="flex flex-wrap gap-1 mb-2">${patternsHtml}</div>` : ""}

          ${srHtml ? `<div class="mb-1">${srHtml}</div>` : ""}

          <div class="prediction-card-terminal__meta">
            <div class="prediction-card-terminal__meta-box">
              <div class="prediction-card-terminal__meta-label">Structure</div>
              <div class="prediction-card-terminal__meta-value text-slate-200">${pred.trend_structure || "?"}</div>
            </div>
            <div class="prediction-card-terminal__meta-box">
              <div class="prediction-card-terminal__meta-label">MTF</div>
              <div class="prediction-card-terminal__meta-value ${mtfColor}">${pred.mtf_alignment || "?"}</div>
            </div>
          </div>

          ${pred.divergence ? `<div class="mt-1 text-[10px] text-amber-400">⚡ ${pred.divergence}</div>` : ""}

          ${autoSignalsHtml}
          ${aiAdvisorHtml}
        </div>
      `;
    }).join("");

  } catch (error) {
    console.error("Failed to refresh predictions:", error);
    const loadingEl = $("predictions-loading");
    if (loadingEl) loadingEl.classList.add("hidden");
  }
}


const BOT_CONFIG_BOOLEAN_DEFAULTS = Object.freeze({
  auto_direction: false,
  breakout_confirmed_entry: false,
  auto_pilot: false,
  trailing_sl_enabled: true,
  quick_profit_enabled: false,  // OFF by default — ATR partial TP + profit lock handle exits
  neutral_volatility_gate_enabled: true,
  recovery_enabled: true,
  entry_gate_enabled: false,  // OFF by default — too strict for most users
  btc_correlation_filter_enabled: true,
  auto_stop_loss_enabled: true,
  auto_take_profit_enabled: true,
  trend_protection_enabled: true,
  danger_zone_enabled: true,
  auto_neutral_mode_enabled: false,  // OFF by default — causes unexpected mode switching
});

const BOT_CONFIG_BOOLEAN_INPUT_IDS = Object.freeze({
  auto_direction: "bot-auto-direction",
  breakout_confirmed_entry: "bot-breakout-confirmed-entry",
  auto_pilot: "bot-auto-pilot",
  trailing_sl_enabled: "bot-trailing-sl",
  quick_profit_enabled: "bot-quick-profit-enabled",
  neutral_volatility_gate_enabled: "bot-volatility-gate-enabled",
  recovery_enabled: "bot-recovery-enabled",
  entry_gate_enabled: "bot-entry-gate-enabled",
  btc_correlation_filter_enabled: "bot-btc-corr-filter",
  auto_stop_loss_enabled: "bot-auto-stoploss-enabled",
  auto_take_profit_enabled: "bot-auto-takeprofit-enabled",
  trend_protection_enabled: "bot-trend-protection-enabled",
  danger_zone_enabled: "bot-danger-zone-enabled",
  auto_neutral_mode_enabled: "bot-auto-neutral-mode-enabled",
});

const SHARED_BOT_CONFIG_BOOLEAN_FIELDS = Object.freeze([
  "auto_direction",
  "breakout_confirmed_entry",
  "auto_pilot",
  "trailing_sl_enabled",
  "quick_profit_enabled",
  "neutral_volatility_gate_enabled",
  "recovery_enabled",
  "entry_gate_enabled",
  "btc_correlation_filter_enabled",
  "auto_neutral_mode_enabled",
]);

const MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS = Object.freeze([
  "auto_stop_loss_enabled",
  "auto_take_profit_enabled",
  "trend_protection_enabled",
  "danger_zone_enabled",
]);



function readBotConfigBooleanField(getEl, field) {
  const inputId = BOT_CONFIG_BOOLEAN_INPUT_IDS[field];
  const el = inputId ? getEl(inputId) : null;
  return el ? !!el.checked : getBotConfigBooleanFallback(field);
}

function applyBotConfigBooleanFields(getEl, bot, fields) {
  (fields || []).forEach((field) => {
    const inputId = BOT_CONFIG_BOOLEAN_INPUT_IDS[field];
    const el = inputId ? getEl(inputId) : null;
    if (el) {
      el.checked = getBotConfigBooleanValue(bot, field);
    }
  });
}


function auditSavedBotConfigBooleanRoundTrip(payload, savedBot, fields, context = "main") {
  const mismatches = [];
  const missing = [];
  (fields || []).forEach((field) => {
    if (!Object.prototype.hasOwnProperty.call(payload || {}, field)) return;
    if (!savedBot || !Object.prototype.hasOwnProperty.call(savedBot, field)) {
      missing.push(field);
      return;
    }
    const submitted = !!payload[field];
    const persisted = !!savedBot[field];
    if (submitted !== persisted) {
      mismatches.push({ field, submitted, persisted });
    }
  });
  const audit = {
    context,
    bot_id: savedBot?.id || payload?.id || null,
    mismatches,
    missing,
    checked_at: new Date().toISOString(),
  };
  window.__lastBotConfigSaveAudit = audit;
  if (missing.length || mismatches.length) {
    console.warn(`[bot-config:${context}] save round-trip mismatch`, audit);
  }
  return audit;
}

async function reportConfigIntegrityRuntimeIssue(payload) {
  try {
    await fetchJSON("/config-integrity/report", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
  } catch (error) {
    console.debug("Config integrity runtime report failed:", error);
  }
}

function collectBotConfigBooleanValues(source, fields) {
  const values = {};
  (fields || []).forEach((field) => {
    if (!Object.prototype.hasOwnProperty.call(source || {}, field)) return;
    values[field] = !!source[field];
  });
  return values;
}

async function reportPostSaveConfigRuntimeTruth(payload, response, fields, context = "main") {
  const savedBot = response?.bot || null;
  const audit = response?.config_integrity_audit || null;
  const botId = savedBot?.id || payload?.id || null;
  if (!botId) return null;
  const runtimeBot = (window._lastBots || []).find((item) => item.id === botId);
  if (!runtimeBot) return null;

  const requestedValues = collectBotConfigBooleanValues(payload, fields);
  const responseValues = collectBotConfigBooleanValues(savedBot, Object.keys(requestedValues));
  const runtimeValues = collectBotConfigBooleanValues(runtimeBot, Object.keys(requestedValues));
  const mismatches = [];

  Object.keys(requestedValues).forEach((field) => {
    if (!Object.prototype.hasOwnProperty.call(runtimeValues, field)) {
      mismatches.push({
        field,
        requested: requestedValues[field],
        runtime: null,
        response: Object.prototype.hasOwnProperty.call(responseValues, field) ? responseValues[field] : null,
      });
      return;
    }
    const expected = Object.prototype.hasOwnProperty.call(responseValues, field)
      ? responseValues[field]
      : requestedValues[field];
    if (runtimeValues[field] !== expected) {
      mismatches.push({
        field,
        requested: requestedValues[field],
        response: expected,
        runtime: runtimeValues[field],
      });
    }
  });

  if (!mismatches.length) return null;

  const eventType = audit?.persisted_matches_intent ? "stale_render_after_save" : "config_runtime_mismatch";
  const runtimeAudit = {
    event_type: eventType,
    ui_path: context,
    bot_id: botId,
    symbol: runtimeBot?.symbol || savedBot?.symbol || payload?.symbol || null,
    fields: mismatches.map((item) => item.field),
    requested_values: requestedValues,
    response_values: responseValues,
    persisted_values: audit?.persisted_values || {},
    runtime_values: runtimeValues,
    details: {
      mismatches,
      persisted_matches_intent: audit?.persisted_matches_intent,
      response_matches_intent: audit?.response_matches_intent,
    },
  };
  await reportConfigIntegrityRuntimeIssue(runtimeAudit);
  console.warn(`[bot-config:${context}] post-save runtime mismatch`, runtimeAudit);
  return runtimeAudit;
}

function reportBotConfigSaveAudit(payload, response, fields, context = "main") {
  const savedBot = response?.bot || null;
  const audit = response?.config_integrity_audit
    || response?.config_boolean_audit
    || auditSavedBotConfigBooleanRoundTrip(payload, savedBot, fields, context);
  window.__lastBotConfigSaveAudit = audit;
  const missingFields = audit?.missing
    || audit?.missing_expected_fields
    || audit?.missing_in_persisted
    || [];
  if (Array.isArray(missingFields) && missingFields.length) {
    showToast(`⚠ Config save missing boolean fields: ${missingFields.join(", ")}`, "warning");
    return audit;
  }
  const mismatchFields = audit?.mismatches
    || audit?.persisted_mismatches
    || audit?.normalized_fields
    || [];
  if (Array.isArray(mismatchFields) && mismatchFields.length) {
    const labels = mismatchFields
      .map((item) => typeof item === "string" ? item : item.field)
      .filter(Boolean);
    if (labels.length) {
      showToast(`ℹ Server normalized settings: ${labels.join(", ")}`, "info");
    }
  }
  return audit;
}


// ============================================================
// ============================================================
// Main Initialization
// ============================================================

window.addEventListener("load", () => {
  // Navbar live clock (12-hour format)
  (function initNavbarClock() {
    const el = $("navbar-clock");
    if (!el) return;
    function tick() {
      const d = new Date();
      let hr = d.getHours();
      const ampm = hr >= 12 ? "PM" : "AM";
      hr = hr % 12 || 12;
      const mm = String(d.getMinutes()).padStart(2, "0");
      const ss = String(d.getSeconds()).padStart(2, "0");
      el.textContent = `${hr}:${mm}:${ss} ${ampm}`;
    }
    tick();
    setInterval(tick, 1000);
  })();

  initEventListeners();
  initQuickEditEventListeners();
  _renderReadyModeFilters();
  _syncRecentScansFromServer();
  initBotModalListeners();
  initWatchdogHubControls();
  ensureDashboardUiPrefs();
  updateDashboardPreferenceButtons();
  updateOperatorWatch();

  // Set default checkbox states on page load
  (function initDefaultCheckboxes() {
    const vg = document.getElementById("bot-volatility-gate-enabled");
    if (vg && !vg.dataset.loaded) { vg.checked = true; vg.dataset.loaded = "1"; }
    const qp = document.getElementById("bot-quick-profit-enabled");
    if (qp && !qp.dataset.loaded) { qp.checked = true; qp.dataset.loaded = "1"; }
    const tsl = document.getElementById("bot-trailing-sl");
    if (tsl && !tsl.dataset.loaded) { tsl.checked = true; tsl.dataset.loaded = "1"; }
  })();
  initSelectAllOnClick();
  initActiveBotsJumpButton();
  initFloatingScrollButton();
  restoreSoundPreference();
  initAutoStopPreference();
  refreshAll();
  updateRunnerStatus();
  if (runnerStatusPollInterval) clearInterval(runnerStatusPollInterval);
  runnerStatusPollInterval = setInterval(updateRunnerStatus, 10000);
  startLiveTimer();
  configureLivePolling(false);
  connectLiveFeed();

  // Flash crash polling (was module-level, moved here for DOM safety)
  setTimeout(checkFlashCrashStatus, 1000);
  setInterval(checkFlashCrashStatus, 10000);

  // Trade stats polling (was module-level, moved here for DOM safety)
  setTimeout(() => loadTradeStats('all'), 500);
  setInterval(() => loadTradeStats(currentStatsPeriod), 30000);
});

// Initialize auto-stop on direction change preference
async function initAutoStopPreference() {
  const checkbox = $("auto-stop-direction");
  const alertDiv = $("direction-change-alert");
  if (!checkbox) return;

  const syncStatusNote = (enabled) => {
    if (!alertDiv) return;
    if (!enabled) {
      alertDiv.classList.add("hidden");
      alertDiv.textContent = "";
      return;
    }
    alertDiv.className = "text-[9px] font-semibold text-amber-400 px-1.5 py-0.5 rounded border border-amber-400/30 bg-amber-500/10";
    alertDiv.textContent = "Guard active";
    alertDiv.classList.remove("hidden");
  };

  checkbox.disabled = true;
  let enabled = localStorage.getItem("autoStopOnDirectionChange") === "true";
  try {
    const settings = await fetchJSON("/runtime-settings");
    enabled = Boolean(settings.auto_stop_on_direction_change);
  } catch (error) {
    console.warn("Falling back to local auto-stop preference:", error);
  }
  checkbox.checked = enabled;
  checkbox.disabled = false;
  localStorage.setItem("autoStopOnDirectionChange", String(enabled));
  syncStatusNote(enabled);

  checkbox.addEventListener("change", async () => {
    const nextValue = checkbox.checked;
    checkbox.disabled = true;
    try {
      const settings = await fetchJSON("/runtime-settings", {
        method: "POST",
        body: JSON.stringify({
          auto_stop_on_direction_change: nextValue,
        }),
      });
      const persisted = Boolean(settings.auto_stop_on_direction_change);
      checkbox.checked = persisted;
      localStorage.setItem("autoStopOnDirectionChange", String(persisted));
      syncStatusNote(persisted);
      showToast(
        persisted
          ? "Server-side direction-change auto-stop enabled"
          : "Server-side direction-change auto-stop disabled",
        persisted ? "success" : "info",
      );
    } catch (error) {
      checkbox.checked = !nextValue;
      syncStatusNote(checkbox.checked);
      showToast(`Failed to update direction-change auto-stop: ${error.message}`, "error");
    } finally {
      checkbox.disabled = false;
    }
  });
}

// ============================================================
// Flash Crash Protection Banner (Smart Feature #12)
// ============================================================

async function checkFlashCrashStatus() {
  try {
    const data = await fetchJSON("/flash-crash-status");
    const banner = $("flash-crash-banner");
    const details = $("flash-crash-details");
    const timeEl = $("flash-crash-time");

    if (!banner) return;

    if (data.active) {
      // Show the banner
      banner.classList.remove("hidden");

      // Update details
      const triggerDetails = data.trigger_details || {};
      const symbol = triggerDetails.symbol || "BTC";
      const changePct = triggerDetails.price_change_pct || 0;
      const direction = triggerDetails.direction || "down";
      const pausedCount = (data.paused_bots || []).length;

      details.textContent = `${symbol} moved ${(Math.abs(changePct) * 100).toFixed(1)}% ${direction} - ${pausedCount} bot(s) paused`;

      // Update time since trigger
      if (data.triggered_at) {
        const triggeredDate = new Date(data.triggered_at);
        const now = new Date();
        const diffMs = now - triggeredDate;
        const diffMins = Math.floor(diffMs / 60000);
        const diffSecs = Math.floor((diffMs % 60000) / 1000);
        timeEl.textContent = `Active for ${diffMins}m ${diffSecs}s`;
      }

      // Play alert sound if this is first time seeing active
      if (soundEnabled && !banner.dataset.alerted) {
        playTone(200, 0.5, 'square', 0.3);
        setTimeout(() => playTone(150, 0.5, 'square', 0.3), 200);
        banner.dataset.alerted = "true";
      }
    } else {
      // Hide the banner
      banner.classList.add("hidden");
      banner.dataset.alerted = "";  // Reset for next time
    }
  } catch (error) {
    console.debug("Flash crash status check failed:", error);
  }
}

// Note: Flash crash polling is started inside window.load to ensure DOM is ready

// =============================================================================
// Quick Config Modal
// =============================================================================


function openQuickEditPanelWithBot(bot) {
  const panel = $("quick-edit-panel");
  const backdrop = $("quick-edit-backdrop");
  if (!panel || !backdrop) return;
  populateQuickEditForm(bot);
  panel.classList.remove("hidden");
  panel.classList.add("flex");
  backdrop.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  window.setTimeout(() => {
    getScopedElement("quick", "bot-symbol")?.focus({ preventScroll: true });
  }, 20);
}

async function fetchCanonicalBotConfig(botId) {
  if (!botId) return null;
  const resp = await fetchJSON(`/bots/${encodeURIComponent(botId)}`);
  return resp?.bot || null;
}

function getCachedBotConfig(botId) {
  if (!botId) return null;
  return window._lastBots?.find((item) => item.id === botId) || null;
}

function buildFallbackEditorBotFromSettings(botId, settings) {
  if (!botId || !settings) return null;
  return {
    id: botId,
    symbol: "",
    mode: "neutral",
    profile: "normal",
    range_mode: "fixed",
    grid_distribution: "clustered",
    grid_count: 10,
    leverage: 3,
    investment: 0,
    auto_stop: settings.auto_stop || null,
    auto_stop_target_usdt: settings.auto_stop_target_usdt || 0,
    tp_pct: settings.tp_pct || null,
    trailing_sl_enabled: settings.trailing_sl_enabled !== undefined ? !!settings.trailing_sl_enabled : getBotConfigBooleanFallback("trailing_sl_enabled"),
    quick_profit_enabled: settings.quick_profit_enabled !== undefined ? !!settings.quick_profit_enabled : getBotConfigBooleanFallback("quick_profit_enabled"),
    neutral_volatility_gate_enabled: settings.neutral_volatility_gate_enabled !== undefined ? !!settings.neutral_volatility_gate_enabled : getBotConfigBooleanFallback("neutral_volatility_gate_enabled"),
    recovery_enabled: settings.recovery_enabled !== undefined ? !!settings.recovery_enabled : getBotConfigBooleanFallback("recovery_enabled"),
    entry_gate_enabled: settings.entry_gate_enabled !== undefined ? !!settings.entry_gate_enabled : getBotConfigBooleanFallback("entry_gate_enabled"),
    auto_direction: settings.auto_direction !== undefined ? !!settings.auto_direction : getBotConfigBooleanFallback("auto_direction"),
    breakout_confirmed_entry: settings.breakout_confirmed_entry !== undefined ? !!settings.breakout_confirmed_entry : getBotConfigBooleanFallback("breakout_confirmed_entry"),
    auto_pilot: settings.auto_pilot !== undefined ? !!settings.auto_pilot : getBotConfigBooleanFallback("auto_pilot"),
  };
}

async function resolveEditorBotConfig(
  botOrId,
  {
    settings = null,
    allowSettingsFallback = false,
    canonicalErrorLog = "Editor canonical fetch failed:",
    runtimeRefreshErrorLog = "Editor runtime refresh failed:",
  } = {},
) {
  const requestedBotId = typeof botOrId === "string"
    ? botOrId
    : (botOrId?.id || "");
  let bot = null;

  if (requestedBotId) {
    try {
      bot = await fetchCanonicalBotConfig(requestedBotId);
    } catch (error) {
      console.debug(canonicalErrorLog, error);
    }
  }

  if (!bot) {
    bot = typeof botOrId === "string"
      ? getCachedBotConfig(botOrId)
      : botOrId;
  }

  if (!bot && requestedBotId) {
    try {
      await refreshBots();
      bot = getCachedBotConfig(requestedBotId);
    } catch (error) {
      console.debug(runtimeRefreshErrorLog, error);
    }
  }

  if (!bot && allowSettingsFallback) {
    bot = buildFallbackEditorBotFromSettings(requestedBotId, settings);
  }

  return bot;
}

async function showQuickEdit(botOrId, settings) {
  const bot = await resolveEditorBotConfig(botOrId, {
    settings,
    allowSettingsFallback: typeof botOrId === "string",
    canonicalErrorLog: "Quick config canonical fetch failed:",
    runtimeRefreshErrorLog: "Quick config refresh failed:",
  });

  if (!bot) {
    showToast("Unable to load bot configuration", "error");
    return;
  }

  openQuickEditPanelWithBot(bot);
}

async function reviewSuggestedMode(botOrId, suggestedMode, suggestedRangeMode) {
  const bot = await resolveEditorBotConfig(botOrId, {
    canonicalErrorLog: "Suggested mode canonical fetch failed:",
    runtimeRefreshErrorLog: "Suggested mode runtime refresh failed:",
  });
  if (!bot) {
    showToast("Unable to load bot configuration", "error");
    return;
  }
  const normalizedMode = normalizeBotModeValue(suggestedMode || bot.mode || "neutral");
  const normalizedRangeMode = String(
    suggestedRangeMode
    || (normalizedMode === "neutral_classic_bybit" ? "fixed" : bot.range_mode || bot.configured_range_mode || "dynamic")
  ).trim().toLowerCase() || "fixed";
  const reviewedBot = {
    ...bot,
    mode: normalizedMode,
    configured_mode: normalizedMode,
    range_mode: normalizedRangeMode,
    configured_range_mode: normalizedRangeMode,
  };
  openQuickEditPanelWithBot(reviewedBot);
  showToast(`Reviewing ${formatBotModeLabel(normalizedMode)} suggestion in Quick Config`, "info");
}

function hideQuickEdit() {
  const panel = $("quick-edit-panel");
  const backdrop = $("quick-edit-backdrop");
  quickEditState.bot = null;
  if (panel) {
    panel.classList.add("hidden");
    panel.classList.remove("flex");
  }
  if (backdrop) backdrop.classList.add("hidden");
  document.body.style.overflow = "";
}

async function openQuickEditFullForm() {
  if (!quickEditState.botId) return;
  hideQuickEdit();
  await editBot(quickEditState.botId);
}

function saveQuickEditAndStart() {
  return saveQuickEdit({ startAfterSave: true });
}

async function saveQuickEdit(options = {}) {
  const startAfterSave = Boolean(options?.startAfterSave);
  if (window.__quickEditSaving) return;
  window.__quickEditSaving = true;

  const getEl = createScopedGetter("quick");
  const saveButtons = [
    {
      button: $("quick-edit-save-btn"),
      loadingHtml: `<span class="animate-spin inline-block mr-1">↻</span> Saving…`,
      active: !startAfterSave,
    },
    {
      button: $("quick-edit-save-start-btn"),
      loadingHtml: `<span class="animate-spin inline-block mr-1">↻</span> Saving & Starting…`,
      active: startAfterSave,
    },
  ].filter(({ button }) => button);
  const saveButtonOriginals = saveButtons.map(({ button }) => ({ button, html: button.innerHTML }));
  for (const { button, loadingHtml, active } of saveButtons) {
    button.disabled = true;
    button.classList.add("opacity-70", "cursor-not-allowed");
    if (active) button.innerHTML = loadingHtml;
  }

  try {
    const botData = buildBotPayloadFromInputs(getEl);
    if (!botData.symbol && !botData.auto_pilot) {
      throw new Error("Symbol is required");
    }
    if (!botData.auto_pilot && (!botData.lower_price || !botData.upper_price || botData.lower_price >= botData.upper_price)) {
      throw new Error("Invalid price range");
    }

    const isEdit = !!botData.id;
    const savedSymbol = botData.symbol || "Auto-Pilot";
    const savedBotId = botData.id;
    const resp = await fetchJSON("/bots", {
      method: "POST",
      headers: { "X-Bot-Config-Path": "quick" },
      body: JSON.stringify(botData),
    });

    hideQuickEdit();
    window._forceNextBotsApply = true;
    await Promise.allSettled([refreshBots(), refreshPositions()]);
    scheduleBotsRefreshFollowUp();
    reportBotConfigSaveAudit(botData, resp, SHARED_BOT_CONFIG_BOOLEAN_FIELDS, "quick");
    await reportPostSaveConfigRuntimeTruth(
      botData,
      resp,
      SHARED_BOT_CONFIG_BOOLEAN_FIELDS,
      "quick",
    );
    const targetBotId = resp?.bot?.id || savedBotId;
    if (startAfterSave) {
      try {
        await startBotFromSave(targetBotId);
        showToast(isEdit ? `✅ ${savedSymbol} bot updated and started!` : `✅ ${savedSymbol} bot created and started!`, "success");
      } catch (startError) {
        showToast(
          isEdit
            ? `❌ ${savedSymbol} bot updated, but start failed: ${startError.message}`
            : `❌ ${savedSymbol} bot created, but start failed: ${startError.message}`,
          "error",
        );
      }
    } else {
      showToast(isEdit ? `✅ ${savedSymbol} bot updated!` : `✅ ${savedSymbol} bot created!`, "success");
    }
    scrollToBotRow(targetBotId, savedSymbol);
  } catch (err) {
    if (err.status === 409 && err?.data?.error === "settings_version_conflict") {
      // Auto-retry with current settings_version (up to 3 attempts)
      for (let retryAttempt = 0; retryAttempt < 3; retryAttempt++) {
        const currentVersion = err?.data?.current_settings_version;
        if (currentVersion == null || !botData.id) break;
        try {
          botData.settings_version = currentVersion;
          const retryResp = await fetchJSON("/bots", {
            method: "POST",
            headers: { "X-Bot-Config-Path": "quick" },
            body: JSON.stringify(botData),
          });
          hideQuickEdit();
          window._forceNextBotsApply = true;
          await Promise.allSettled([refreshBots(), refreshPositions()]);
          scheduleBotsRefreshFollowUp();
          const targetId = retryResp?.bot?.id || botData.id;
          showToast(`✅ ${savedSymbol} bot updated!`, "success");
          scrollToBotRow(targetId, savedSymbol);
          return;
        } catch (retryErr) {
          if (retryErr.status === 409 && retryErr?.data?.error === "settings_version_conflict") {
            err = retryErr;
            continue;
          }
          showToast(`❌ Failed to save bot: ${retryErr.message || retryErr}`, "error");
          return;
        }
      }
      showToast("Config changed in another editor or window. Reopen Quick Config before saving again.", "error");
      await Promise.allSettled([refreshBots(), refreshPositions()]);
      hideQuickEdit();
      return;
    }
    showToast(`❌ Failed to save bot: ${err.message || err}`, "error");
  } finally {
    for (const { button, html } of saveButtonOriginals) {
      button.disabled = false;
      button.classList.remove("opacity-70", "cursor-not-allowed");
      button.innerHTML = html;
    }
    window.__quickEditSaving = false;
  }
}

function initQuickEditEventListeners() {
  const quickMode = getScopedElement("quick", "bot-mode");
  const quickRangeMode = getScopedElement("quick", "bot-range-mode");
  const quickAutoPilot = getScopedElement("quick", "bot-auto-pilot");
  const quickUniverse = getScopedElement("quick", "bot-auto-pilot-universe-mode");
  const fullBtn = $("quick-edit-open-full-btn");

  if (quickMode) {
    quickMode.addEventListener("change", () => {
      updateScalpPnlInfoVisibility("quick");
      renderModeSemanticsPanel("quick", quickEditState.bot);
    });
  }

  if (quickRangeMode) {
    quickRangeMode.addEventListener("change", () => {
      updateScalpPnlInfoVisibility("quick");
      renderModeSemanticsPanel("quick", quickEditState.bot);
    });
  }

  if (quickAutoPilot) {
    quickAutoPilot.addEventListener("change", () => {
      updateAutoPilotVisibility("quick");
      renderModeSemanticsPanel("quick", quickEditState.bot);
    });
  }

  const quickModePolicy = getScopedElement("quick", "bot-mode-policy");
  if (quickModePolicy) {
    quickModePolicy.addEventListener("change", () => {
      renderModeSemanticsPanel("quick", quickEditState.bot);
    });
  }

  if (quickUniverse) {
    quickUniverse.addEventListener("change", () => {
      updateAutoPilotUniverseModeHelp("quick");
    });
  }

  ["bot-trailing-sl", "bot-quick-profit-enabled", "bot-volatility-gate-enabled"].forEach((id) => {
    const el = getScopedElement("quick", id);
    if (el) {
      el.addEventListener("change", () => updateModeScopedBotOptions("quick"));
    }
  });
  ["bot-auto-direction", "bot-auto-neutral-mode-enabled"].forEach((id) => {
    const el = getScopedElement("quick", id);
    if (el) {
      el.addEventListener("change", () => renderModeSemanticsPanel("quick", quickEditState.bot));
    }
  });

  if (fullBtn) {
    fullBtn.addEventListener("click", openQuickEditFullForm);
  }
}

// Note: Quick edit Escape key is handled by the unified Escape handler above

// =============================================================================
// Profitable Trades Statistics (Bybit-style)
// =============================================================================

// let currentStatsPeriod = 'all';  // Defined in app_v5.js

async function loadTradeStats(period = 'all') {
  currentStatsPeriod = period;

  // Update button styles
  document.querySelectorAll('.stats-period-btn').forEach(btn => {
    btn.classList.remove('bg-emerald-600', 'text-white');
    btn.classList.add('bg-slate-700', 'text-slate-400');
  });
  const activeBtn = document.getElementById(`stats-btn-${period}`);
  if (activeBtn) {
    activeBtn.classList.remove('bg-slate-700', 'text-slate-400');
    activeBtn.classList.add('bg-emerald-600', 'text-white');
  }

  try {
    const data = await fetchJSON(`/pnl/stats?period=${period}`);
    updateTradeStatsDisplay(data);
  } catch (err) {
    console.error('Failed to load trade stats:', err);
  }
}


// =============================================================================
// AI Range Suggestion (Bot form)
// =============================================================================

async function requestAiRange(options = {}) {
  const { force = false, silent = true } = options;
  const symbolInput = $("bot-symbol");
  const modeInput = $("bot-mode");
  const lowerInput = $("bot-lower");
  const upperInput = $("bot-upper");
  const autoPilot = $("bot-auto-pilot");

  if (!symbolInput || !lowerInput || !upperInput) return false;
  if (autoPilot && autoPilot.checked) return false;

  const symbol = (symbolInput.value || "").trim().toUpperCase();
  const mode = (modeInput && modeInput.value ? modeInput.value : "neutral").trim().toLowerCase();
  const rangeMode = ($("bot-range-mode")?.value || "fixed").trim().toLowerCase();
  if (!symbol || symbol.length < 4 || !isTradeableDashboardSymbol(symbol)) return false;
  if (!force && botFormAutoRangeManualOverride) return false;
  const preserveGridCountManual =
    options.preserveGridCountManual !== undefined
      ? !!options.preserveGridCountManual
      : (isEditingExistingBotForm() && gridCountManuallyEdited);

  const contextKey = getBotFormAutoRangeContext();
  const requestSeq = ++botFormAutoRangeRequestSeq;

  try {
    const query = new URLSearchParams({ mode, range_mode: rangeMode });
    const resp = await fetchJSON(`/ai-range/${encodeURIComponent(symbol)}?${query.toString()}`);
    if (!resp.success) {
      throw new Error(resp.error || "AI failed");
    }
    if (requestSeq !== botFormAutoRangeRequestSeq) return false;
    if (getBotFormAutoRangeContext() !== contextKey) return false;
    if (!force && botFormAutoRangeManualOverride) return false;
    if (!resp.lower || !resp.upper || resp.lower >= resp.upper) {
      throw new Error("Invalid AI range");
    }

    return applyAutoRangeToForm(resp.lower, resp.upper, resp.price, {
      preserveGridCountManual,
    });
  } catch (err) {
    console.error("AI range error", err);
    if (!silent) {
      showToast(`❌ Auto range failed: ${err.message || err}`, "error");
    }
    return false;
  }
}

/**
 * Refresh logs in Bot Detail Modal
 */
async function refreshBotDetailLogs() {
  if (!window.currentDetailBotId) return;
  const box = $("botDetailLogsBox");
  if (!box) return;

  try {
    const data = await fetchJSON(`/bots/${window.currentDetailBotId}/logs?limit=100&_ts=${Date.now()}`);

    // Check if we already have some logs vs loading for the first time
    const isFirstLoad = box.textContent === "Loading logs..." || box.textContent === "" || box.textContent.includes("No logs found");

    if (data.logs && Array.isArray(data.logs) && data.logs.length > 0) {
      box.textContent = data.logs.join("\n");
    } else {
      box.textContent = "No logs found for this bot/symbol.";
    }

    // Scroll to bottom (sticky behavior: only scroll if already near bottom OR force for first load)
    const isAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;
    if (isAtBottom || isFirstLoad) {
      setTimeout(() => {
        box.scrollTop = box.scrollHeight;
      }, 50);
    }
  } catch (err) {
    box.textContent = "Error loading logs: " + (err.message || err);
  }
}

/**
 * runBacktestFromForm - Run backtest using current form values (no save required)
 */
async function runBacktestFromForm() {
  // Gather form values
  const symbol = document.getElementById("bot-symbol")?.value?.trim() || "";
  const lowerPrice = parseFloat(document.getElementById("bot-lower")?.value || 0);
  const upperPrice = parseFloat(document.getElementById("bot-upper")?.value || 0);
  const gridCount = parseInt(document.getElementById("bot-grids")?.value || 10, 10);
  const investment = parseFloat(document.getElementById("bot-investment")?.value || 100);
  const leverage = parseFloat(document.getElementById("bot-leverage")?.value || 5);
  const mode = document.getElementById("bot-mode")?.value || "neutral";
  const rangeMode = document.getElementById("bot-range-mode")?.value || "fixed";

  if (!symbol) {
    alert("Please enter a symbol first");
    return;
  }
  if (lowerPrice >= upperPrice) {
    alert("Lower price must be less than upper price");
    return;
  }

  // Show loading
  const btn = document.getElementById("btn-backtest-form");
  const originalText = btn?.textContent || "Backtest";
  if (btn) btn.textContent = "Running...";

  try {
    const data = await fetchJSON("/backtest", {
      method: "POST",
      body: JSON.stringify({
        symbol,
        lower_price: lowerPrice,
        upper_price: upperPrice,
        grid_count: gridCount,
        investment,
        leverage,
        mode,
        range_mode: rangeMode,
      }),
    });

    if (data.error) {
      alert("Backtest error: " + data.error);
      return;
    }

    // Display results in a modal
    showBacktestResultsModal(data);

  } catch (err) {
    alert("Backtest failed: " + (err.message || err));
  } finally {
    if (btn) btn.textContent = originalText;
  }
}
