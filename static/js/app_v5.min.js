/**
 * Bybit Control Center - Frontend Application
 * Plain JavaScript client with LIVE real-time updates
 */

const API_BASE = "/api";

// Track previous values for change detection
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

// Audio context for sound effects
let audioContext = null;
let soundEnabled = false;

// Track if grid count was manually edited (don't auto-override)
let gridCountManuallyEdited = false;

// Track bots that are currently performing an action to prevent UI flicker
let pendingBotActions = {};

// Global account balances for transfer modal
window._currentUnifiedBalance = 0;
window._currentFundingBalance = 0;

// Toast notification system
function showToast(message, type = "info") {
  // Create or get toast container
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.style.cssText = "position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;";
    document.body.appendChild(container);
  }

  // Create toast element
  const toast = document.createElement("div");
  const bgColor = type === "success" ? "#10b981" : type === "error" ? "#ef4444" : "#3b82f6";
  toast.style.cssText = `
    background:${bgColor};color:#fff;padding:12px 20px;border-radius:8px;
    box-shadow:0 4px 12px rgba(0,0,0,0.3);font-size:14px;font-weight:500;
    transform:translateX(120%);transition:transform 0.3s ease;max-width:350px;
  `;
  toast.textContent = message;
  container.appendChild(toast);

  // Animate in
  setTimeout(() => toast.style.transform = "translateX(0)", 10);

  // Auto-remove after 4 seconds
  setTimeout(() => {
    toast.style.transform = "translateX(120%)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Toggle sound on/off
function toggleSound() {
  soundEnabled = !soundEnabled;

  const icon = $("sound-icon");
  const label = $("sound-label");
  const btn = $("sound-toggle");

  if (soundEnabled) {
    initAudio();
    icon.textContent = "🔊";
    label.textContent = "Sound On";
    btn.className = "px-2 py-1 text-xs font-medium rounded bg-emerald-600 text-white hover:bg-emerald-500 transition flex items-center";
    playTone(880, 0.1, 'sine', 0.2);
    setTimeout(() => playTone(1100, 0.1, 'sine', 0.2), 100);
  } else {
    icon.textContent = "🔇";
    label.textContent = "Sound Off";
    btn.className = "px-2 py-1 text-xs font-medium rounded bg-slate-700 text-slate-400 hover:bg-slate-600 transition flex items-center";
  }
  localStorage.setItem('soundEnabled', soundEnabled);
}

// Logout function - clears credentials and redirects to login
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

function initAudio() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioContext.state === 'suspended') {
    audioContext.resume();
  }
  return audioContext;
}

function playTone(frequency, duration, type = 'sine', volume = 0.3) {
  try {
    if (!audioContext) return;
    const ctx = audioContext;
    if (ctx.state === 'suspended') ctx.resume();

    const oscillator = ctx.createOscillator();
    const gainNode = ctx.createGain();

    oscillator.connect(gainNode);
    gainNode.connect(ctx.destination);

    oscillator.frequency.value = frequency;
    oscillator.type = type;

    gainNode.gain.setValueAtTime(volume, ctx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + duration);

    oscillator.start(ctx.currentTime);
    oscillator.stop(ctx.currentTime + duration);
  } catch (e) {
    console.log('Audio not available:', e);
  }
}

function playPositionOpenSound() {
  if (!soundEnabled) return;
  try {
    const ctx = initAudio();
    if (ctx.state === 'suspended') ctx.resume();
    const notes = [523.25, 659.25, 783.99];
    notes.forEach((freq, i) => {
      setTimeout(() => playTone(freq, 0.15, 'sine', 0.25), i * 100);
    });
  } catch (e) { }
}

function playProfitSound() {
  if (!soundEnabled) return;
  try {
    const ctx = initAudio();
    if (ctx.state === 'suspended') ctx.resume();
    const notes = [523.25, 659.25, 783.99, 1046.50];
    notes.forEach((freq, i) => {
      setTimeout(() => {
        playTone(freq, 0.2, 'sine', 0.2);
        playTone(freq * 2, 0.15, 'sine', 0.1);
      }, i * 80);
    });
    setTimeout(() => {
      playTone(1318.51, 0.1, 'square', 0.15);
      setTimeout(() => playTone(1567.98, 0.15, 'square', 0.15), 50);
    }, 350);
  } catch (e) { }
}

function playLossSound() {
  if (!soundEnabled) return;
  try {
    const ctx = initAudio();
    if (ctx.state === 'suspended') ctx.resume();
    const notes = [392.00, 349.23, 293.66];
    notes.forEach((freq, i) => {
      setTimeout(() => playTone(freq, 0.25, 'triangle', 0.25), i * 150);
    });
  } catch (e) { }
}

function restoreSoundPreference() {
  const saved = localStorage.getItem('soundEnabled');
  // Default to ON if no preference saved, or if explicitly 'true'
  if (saved === null || saved === 'true') {
    soundEnabled = true;
    // Audio context will be initialized on first user interaction (browser requirement)
    // The unlockAudio() listeners handle this
  } else {
    // User explicitly turned sound off
    soundEnabled = false;
    const icon = $("sound-icon");
    const label = $("sound-label");
    const btn = $("sound-toggle");
    if (icon && label && btn) {
      icon.textContent = "🔇";
      label.textContent = "Sound Off";
      btn.className = "px-2 py-1 text-xs font-medium rounded bg-slate-700 text-slate-400 hover:bg-slate-600 transition flex items-center";
    }
  }
}

let lastUpdateTime = null;

function $(id) { return document.getElementById(id); }

async function fetchJSON(path, options = {}) {
  try {
    const response = await fetch(API_BASE + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`API Error (${path}):`, error);
    throw error;
  }
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

/**
 * Update the page title with current unrealized PnL.
 * Shows: "Bybit Control: +$0.12" or "Bybit Control: -$0.05"
 */
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

  document.title = `${pnlText} - Bybit Bot`;
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

function statusBadge(status) {
  const badges = {
    running: "bg-emerald-500/20 text-emerald-400",
    paused: "bg-amber-500/20 text-amber-400",
    recovering: "bg-blue-500/20 text-blue-400",
    stopped: "bg-slate-500/20 text-slate-400",
    error: "bg-red-500/20 text-red-400",
    risk_stopped: "bg-red-500/20 text-red-400",
    out_of_range: "bg-purple-500/20 text-purple-400",
    tp_hit: "bg-cyan-500/20 text-cyan-400",
  };
  const cls = badges[status] || badges.stopped;
  const displayStatus = status === "recovering" ? "🔄 recovering" : status;
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls}">${displayStatus}</span>`;
}

// =============================================================================
// UPnL Stop-Loss Badges (NEW - Part 10)
// =============================================================================
function upnlSlBadges(bot) {
  if (!bot.upnl_stoploss_enabled) return "";

  let badges = [];

  // HARD triggered (risk_stopped status with UPnL SL reason)
  if (bot.status === "risk_stopped" && bot.upnl_stoploss_reason) {
    badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-600/30 text-red-400" title="${bot.upnl_stoploss_reason}">🛑 HARD SL</span>`);
  }
  // SOFT triggered (blocking orders but still running)
  else if (bot.upnl_stoploss_active) {
    badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-orange-600/30 text-orange-400" title="Soft SL active - opening orders blocked">⚠️ SOFT SL</span>`);
  }

  // Cooldown badge with countdown
  if (bot.upnl_stoploss_in_cooldown && bot.upnl_stoploss_cooldown_until) {
    const cooldownEnd = new Date(bot.upnl_stoploss_cooldown_until);
    const now = new Date();
    const remainingSec = Math.max(0, Math.floor((cooldownEnd - now) / 1000));
    const mins = Math.floor(remainingSec / 60);
    const secs = remainingSec % 60;
    const timeStr = mins > 0 ? `${mins}m${secs}s` : `${secs}s`;
    badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-600/30 text-blue-400" title="Cooldown until ${cooldownEnd.toLocaleTimeString()}">⏳ ${timeStr}</span>`);
  }

  // Show trigger count if > 0
  if (bot.upnl_stoploss_trigger_count > 0 && !bot.upnl_stoploss_active && !bot.upnl_stoploss_in_cooldown) {
    badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-600/30 text-slate-400" title="Times UPnL SL triggered">🛡️×${bot.upnl_stoploss_trigger_count}</span>`);
  }

  // Show effective thresholds on hover (always visible small indicator)
  if (bot.upnl_stoploss_enabled && badges.length === 0) {
    const soft = bot.effective_upnl_soft || "-12";
    const hard = bot.effective_upnl_hard || "-18";
    badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700/50 text-slate-500" title="UPnL SL enabled: Soft ${soft}% / Hard ${hard}%">🛡️</span>`);
  }

  return badges.length > 0 ? `<div class="flex flex-wrap gap-0.5 mt-0.5 justify-center">${badges.join("")}</div>` : "";
}

/**
 * Trailing Stop-Loss Badge (Smart Feature #14)
 */
function trailingSlBadge(bot) {
  if (!bot.trailing_sl_enabled || !bot.trailing_sl_price) return "";

  const slPrice = parseFloat(bot.trailing_sl_price);
  const currentPrice = parseFloat(bot.current_price) || 0;

  if (!slPrice || !currentPrice) return "";

  const distPct = Math.abs(slPrice - currentPrice) / currentPrice * 100;
  const activated = bot.trailing_sl_activated;

  // Use cyan for activated trailing SL (it's locking in profit)
  const colorClass = activated ? "bg-cyan-600/30 text-cyan-400" : "bg-slate-700/50 text-slate-500";
  const icon = activated ? "📈" : "⏱️";
  const label = activated ? `TRAIL $${slPrice.toFixed(4)}` : "TRAILING";

  return `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${colorClass}" title="Trailing SL active at $${slPrice.toFixed(4)} (${distPct.toFixed(2)}% away)">${icon} ${label}</span>`;
}

// AI Advisor removed - function kept for compatibility
function aiGuardBadge(bot) {
  return "";
}

function entryGateBadge(bot) {
  // Only show for long/short modes when gate is blocked
  if (!bot.entry_gate_blocked) return "";
  if (bot.mode !== "long" && bot.mode !== "short") return "";

  const reason = bot.entry_gate_reason || "Bad entry conditions";
  const blockedUntil = bot.entry_gate_blocked_until || 0;
  const now = Date.now() / 1000;
  const timeRemaining = Math.max(0, Math.round(blockedUntil - now));

  const tooltip = `${reason}. Rechecking in ${timeRemaining}s`;

  return `
    <div class="mt-0.5" title="${tooltip}">
      <span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-600/30 text-amber-300">
        ENTRY GATE
      </span>
      <span class="ml-1 text-[9px] text-amber-400 truncate max-w-[100px]" title="${reason}">
        ${reason.substring(0, 25)}${reason.length > 25 ? '...' : ''}
      </span>
    </div>
  `;
}

function dangerZoneBadge(bot) {
  const level = (bot.danger_level || "none").toLowerCase();
  const score = bot.danger_score || 0;
  if (!level || level === "none" || score <= 0) return "";

  let cls = "bg-amber-600/30 text-amber-400";
  if (level === "high" || level === "extreme") {
    cls = "bg-red-600/30 text-red-400";
  } else if (level === "medium") {
    cls = "bg-orange-600/30 text-orange-400";
  } else if (level === "low") {
    cls = "bg-yellow-600/30 text-yellow-400";
  }

  const warnings = Array.isArray(bot.danger_warnings) ? bot.danger_warnings.join("; ") : "";
  const title = warnings ? `Danger ${level} (${score}/100) - ${warnings}` : `Danger ${level} (${score}/100)`;
  return `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${cls}" title="${title}">⚠ DZ</span>`;
}

function profileBadge(profile, autoDirection) {
  let badgeClass = "bg-slate-500/20 text-slate-400";
  let label = profile || "normal";
  if (profile === "scalp") {
    badgeClass = "bg-orange-500/20 text-orange-400";
    label = "⚡scalp";
  }
  let autoIndicator = autoDirection ? '<span class="ml-1 text-purple-400" title="Auto Direction enabled">🔄</span>' : "";
  return `<span class="px-2 py-1 rounded text-xs font-medium ${badgeClass}">${label}</span>${autoIndicator}`;
}

function modeBadge(mode, scalpAnalysis, bot) {
  let badgeClass = "bg-slate-500/20 text-slate-400";
  let label = mode || "neutral";
  let extra = "";

  if (mode === "dynamic") {
    badgeClass = "bg-orange-500/20 text-orange-400";
    label = "🔥 Dynamic";
    extra = `<div class="text-[10px] text-orange-400 mt-0.5">Ultra-Trend</div>`;
  } else if (mode === "neutral_classic_bybit") {
    badgeClass = "bg-slate-500/20 text-slate-300";
    label = "Neutral Classic";
  } else if (mode === "scalp_pnl") {
    badgeClass = "bg-amber-500/20 text-amber-400";
    label = "💰 Scalp PnL";

    // Show scalp analysis if available
    if (scalpAnalysis) {
      const condition = scalpAnalysis.condition || "unknown";
      const momentum = scalpAnalysis.momentum || "neutral";
      const target = scalpAnalysis.profit_target || 0.30;
      const isChoppy = scalpAnalysis.is_choppy;

      let conditionIcon = "⚡";
      if (condition === "trending_up") conditionIcon = "📈";
      else if (condition === "trending_down") conditionIcon = "📉";
      else if (condition === "choppy" || isChoppy) conditionIcon = "🌊";
      else if (condition === "calm") conditionIcon = "😌";

      extra = `<div class="text-[10px] text-slate-400 mt-0.5">${conditionIcon} $${target.toFixed(2)} target</div>`;
    }
  } else if (mode === "scalp_market") {
    badgeClass = "bg-cyan-500/20 text-cyan-400";
    label = "⚡ Scalp Mkt";

    // Show signal score and status if available
    if (bot) {
      const signalScore = bot.scalp_signal_score;
      const scalpStatus = bot.scalp_status;
      if (signalScore !== undefined && signalScore !== null) {
        const signalIcon = signalScore > 0 ? "📈" : signalScore < 0 ? "📉" : "➖";
        extra = `<div class="text-[10px] text-slate-400 mt-0.5">${signalIcon} ${signalScore > 0 ? '+' : ''}${signalScore}</div>`;
      }
      if (scalpStatus) {
        extra += `<div class="text-[10px] text-slate-500 mt-0.5 truncate max-w-[120px]" title="${scalpStatus}">${scalpStatus}</div>`;
      }
    }
  } else if (mode === "long") {
    badgeClass = "bg-emerald-500/20 text-emerald-400";
  } else if (mode === "short") {
    badgeClass = "bg-red-500/20 text-red-400";
  }

  return `<span class="px-2 py-1 rounded text-xs font-medium ${badgeClass}">${label}</span>${extra}`;
}

function rangeModeBadge(rangeMode, widthPct) {
  const badges = {
    fixed: "bg-slate-500/20 text-slate-400",
    dynamic: "bg-blue-500/20 text-blue-400",
    trailing: "bg-purple-500/20 text-purple-400",
  };
  const mode = (rangeMode || "fixed").toLowerCase();
  const cls = badges[mode] || badges.fixed;
  let widthText = "";
  if (widthPct && !isNaN(widthPct)) {
    widthText = `<div class="text-xs text-slate-500 mt-0.5">${(widthPct * 100).toFixed(1)}%</div>`;
  }
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls}">${mode}</span>${widthText}`;
}

function regimeBadge(regime) {
  const badges = {
    choppy: "bg-emerald-500/20 text-emerald-400",
    trending: "bg-blue-500/20 text-blue-400",
    too_strong: "bg-red-500/20 text-red-400",
    illiquid: "bg-slate-500/20 text-slate-400",
  };
  const cls = badges[regime] || badges.trending;
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls}">${regime}</span>`;
}

function trendBadge(trend) {
  const badges = {
    uptrend: "bg-emerald-500/20 text-emerald-400",
    downtrend: "bg-red-500/20 text-red-400",
    neutral: "bg-slate-500/20 text-slate-400",
  };
  const icons = {
    uptrend: "↑",
    downtrend: "↓",
    neutral: "→",
  };
  const cls = badges[trend] || badges.neutral;
  const icon = icons[trend] || icons.neutral;
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls}">${icon} ${trend}</span>`;
}

function recommendedModeBadge(mode, rangeMode) {
  const modeColors = {
    neutral: "bg-slate-500/20 text-slate-300",
    neutral_classic_bybit: "bg-slate-500/20 text-slate-300",
    long: "bg-emerald-500/20 text-emerald-400",
    short: "bg-red-500/20 text-red-400",
    scalp_pnl: "bg-amber-500/20 text-amber-400",
  };
  const modeIcons = {
    neutral: "⚖",
    neutral_classic_bybit: "⚖",
    long: "↗",
    short: "↘",
    scalp_pnl: "⚡",
  };
  const rangeModeShort = { fixed: "F", dynamic: "D", trailing: "T" };
  const cls = modeColors[mode] || modeColors.neutral;
  const icon = modeIcons[mode] || "";
  const rmShort = rangeModeShort[rangeMode] || "F";
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls}">${icon} ${mode}/${rmShort}</span>`;
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

function riskBadge(riskData) {
  const { level, score, factors } = riskData;
  const badges = {
    low: "bg-emerald-500/20 text-emerald-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    high: "bg-orange-500/20 text-orange-400",
    extreme: "bg-red-500/20 text-red-400",
  };
  const icons = {
    low: "●",
    medium: "▲",
    high: "◆",
    extreme: "★",
  };
  const cls = badges[level] || badges.medium;
  const icon = icons[level] || "●";
  const tooltip = factors.length > 0 ? `title="Score: ${score}\n${factors.join('\n')}"` : `title="Risk score: ${score}"`;
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls} cursor-help" ${tooltip}>${icon} ${level}</span>`;
}

function btcCorrBadge(corr) {
  if (corr === null || corr === undefined) {
    return `<span class="text-slate-500">-</span>`;
  }

  let label, cls;
  const absCorr = Math.abs(corr);

  if (corr >= 0.7) {
    label = "High";
    cls = "bg-blue-500/20 text-blue-400";
  } else if (corr >= 0.4) {
    label = "Med";
    cls = "bg-slate-500/20 text-slate-300";
  } else if (corr >= 0.1) {
    label = "Low";
    cls = "bg-slate-500/20 text-slate-400";
  } else if (corr >= -0.1) {
    label = "None";
    cls = "bg-slate-600/20 text-slate-500";
  } else if (corr >= -0.4) {
    label = "Inv";
    cls = "bg-amber-500/20 text-amber-400";
  } else {
    label = "Neg";
    cls = "bg-red-500/20 text-red-400";
  }

  const tooltip = `title="BTC Correlation: ${corr.toFixed(2)}"`;
  return `<span class="px-2 py-1 rounded text-xs font-medium ${cls} cursor-help" ${tooltip}>${label}</span>`;
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
    el.className = el.className.replace(/text-\w+-\d+/g, '') + ' ' + formattedValue.class;
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

async function refreshAll() {
  try {
    await Promise.all([refreshSummary(), refreshPositions(), refreshBots(), refreshPnl(), refreshPredictions()]);
    setConnectionStatus(true);
    updateLastRefreshTime();
  } catch (error) {
    console.error("Refresh error:", error);
    setConnectionStatus(false);
  }
}

async function refreshPnlQuick() {
  try {
    await Promise.all([refreshSummary(), refreshPositions(), refreshBots(), refreshPnl()]);
    setConnectionStatus(true);
    updateLastRefreshTime();
  } catch (error) {
    console.error("Quick refresh error:", error);
    setConnectionStatus(false);
  }
}

async function refreshSummary() {
  const data = await fetchJSON("/summary");
  const account = data.account || {};

  updateValueWithFlash("summary-total-assets", parseFloat(account.equity || 0), (v) => formatNumber(v, 2), "totalAssets");
  $("summary-available-balance").textContent = formatNumber(account.available_balance, 2);

  // Update global balances for modal (ALWAYS update even if UI elements missing)
  window._currentUnifiedBalance = parseFloat(account.available_balance || 0);
  window._currentFundingBalance = parseFloat(account.funding_balance || 0);

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
  if (realizedEl) {
    realizedEl.textContent = realizedPnL.text;
    realizedEl.className = `text-sm font-medium ${realizedVal > 0 ? 'text-cyan-400' : realizedPnL.class}`;
  }
  previousValues.realizedPnl = realizedVal;

  const unrealizedVal = parseFloat(account.unrealized_pnl || 0);
  const unrealizedPnL = formatPnL(unrealizedVal);
  const unrealizedEl = $("summary-unrealized-pnl");
  if (previousValues.unrealizedPnl !== null && previousValues.unrealizedPnl !== unrealizedVal) {
    flashElement("summary-unrealized-pnl", unrealizedVal > previousValues.unrealizedPnl);
  }
  if (unrealizedEl) {
    unrealizedEl.textContent = unrealizedPnL.text;
    unrealizedEl.className = `text-sm font-medium ${unrealizedPnL.class}`;
  }
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
}

async function refreshPositions() {
  const data = await fetchJSON("/positions");
  const positions = data.positions || [];
  const tbody = $("positions-body");

  const currentCount = positions.length;
  if (previousValues.positionCount !== null && currentCount > previousValues.positionCount) {
    playPositionOpenSound();
  }
  previousValues.positionCount = currentCount;

  // Calculate position stats
  let longCount = 0, shortCount = 0;
  let totalPnl = 0, profitSum = 0, lossSum = 0;
  for (const pos of positions) {
    if (pos.side === "Buy") longCount++;
    else if (pos.side === "Sell") shortCount++;
    const pnl = parseFloat(pos.unrealized_pnl || 0);
    totalPnl += pnl;
    if (pnl > 0) profitSum += pnl;
    else if (pnl < 0) lossSum += Math.abs(pnl);
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
    const pnlText = totalPnl >= 0 ? `+$${totalPnl.toFixed(2)}` : `-$${Math.abs(totalPnl).toFixed(2)}`;
    totalPnlEl.textContent = pnlText;
    totalPnlEl.className = 'font-medium ' + (totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400');
  }
  if (profitSumEl) profitSumEl.textContent = profitSum.toFixed(2);
  if (lossSumEl) lossSumEl.textContent = lossSum.toFixed(2);

  // Update wallet balance display
  const walletBalance = data.wallet_balance || 0;
  const walletBalanceEl = document.getElementById('pos-wallet-balance');
  if (walletBalanceEl) {
    walletBalanceEl.textContent = `$${walletBalance.toFixed(2)}`;
  }

  // Update available balance display
  const availableBalance = data.available_balance || 0;
  const availableBalanceEl = document.getElementById('pos-available-balance');
  if (availableBalanceEl) {
    availableBalanceEl.textContent = `$${availableBalance.toFixed(2)}`;
  }

  if (positions.length === 0) {
    previousValues.positionPnls = {};
    tbody.innerHTML = `<tr><td colspan="12" class="px-4 py-8 text-center text-slate-500">No open positions</td></tr>`;
    return;
  }

  tbody.innerHTML = positions.map(pos => {
    const pnl = formatPnL(pos.unrealized_pnl);
    const sideClass = pos.side === "Buy" ? "text-emerald-400" : "text-red-400";
    const posKey = `${pos.symbol}_${pos.side}`;
    const newPnl = parseFloat(pos.unrealized_pnl || 0);
    previousValues.positionPnls[posKey] = newPnl;

    // % to Liquidation - color based on risk level
    let pctToLiqText = "-";
    let pctToLiqClass = "text-slate-400";
    if (pos.pct_to_liq !== null && pos.pct_to_liq !== undefined) {
      pctToLiqText = pos.pct_to_liq.toFixed(1) + "%";
      if (pos.pct_to_liq < 5) {
        pctToLiqClass = "text-red-500 font-bold"; // Very dangerous
      } else if (pos.pct_to_liq < 10) {
        pctToLiqClass = "text-amber-400 font-medium"; // Warning
      } else if (pos.pct_to_liq < 20) {
        pctToLiqClass = "text-yellow-400"; // Caution
      } else {
        pctToLiqClass = "text-emerald-400"; // Safe
      }
    }

    // Bot info columns
    const botMode = pos.bot_mode || '-';
    const botModeClass = botMode === 'long' ? 'text-emerald-400' : botMode === 'short' ? 'text-red-400' : botMode === 'dynamic' ? 'text-orange-400' : 'text-slate-400';
    const rangeMode = pos.bot_range_mode || '-';
    const rangeModeClass = rangeMode === 'dynamic' ? 'text-cyan-400' : rangeMode === 'trailing' ? 'text-purple-400' : 'text-slate-400';
    const targetVal = pos.auto_stop_target_usdt || 0;
    const botId = pos.bot_id || '';

    return `
      <tr class="table-row">
        <td class="px-3 py-3 font-medium text-white">${pos.symbol}</td>
        <td class="px-3 py-3 text-center ${botModeClass} text-[10px] uppercase font-medium">${botMode}</td>
        <td class="px-3 py-3 text-center ${rangeModeClass} text-[10px] uppercase font-medium">${rangeMode}</td>
        <td class="px-3 py-3 text-right">${formatNumber(pos.size, 4)}</td>
        <td class="px-3 py-3 text-right text-slate-400">$${formatNumber(pos.position_value, 2)}</td>
        <td class="px-3 py-3 text-right">${formatNumber(pos.entry_price, 4)}</td>
        <td class="px-3 py-3 text-right">${formatNumber(pos.mark_price, 4)}</td>
        <td class="px-3 py-3 text-right font-medium" title="${pos.leverage ? `${pos.position_value || '?'} / Account Equity = ${pos.leverage.toFixed(2)}x` : 'No leverage data'}">${pos.leverage ? pos.leverage.toFixed(1) + "x" : "-"}</td>
        <td class="px-3 py-3 text-right ${pctToLiqClass}">${pctToLiqText}</td>
        <td class="px-3 py-3 text-right ${pnl.class}" data-pnl-position="${pos.symbol}">${pnl.text}</td>
        <td class="px-3 py-3 text-right ${pos.realized_pnl > 0 ? 'text-cyan-400' : pos.realized_pnl < 0 ? 'text-red-400' : 'text-slate-400'}" title="Realized PnL for this position">${formatPnL(pos.realized_pnl || 0).text}</td>
        <td class="px-3 py-3 text-center">
          ${botId ? `
            <div class="flex items-center justify-center gap-1">
              <input type="number" step="0.1" min="0" id="target-input-${pos.symbol}" placeholder="${targetVal > 0 ? targetVal : 'Target'}" value="${targetVal > 0 ? targetVal : ''}"
                onfocus="this.select()"
                class="w-16 px-1 py-1 bg-slate-800 border border-slate-600 rounded text-white text-xs text-right focus:outline-none focus:ring-1 focus:ring-yellow-500" />
              <button onclick="setBalanceTarget('${botId}', '${pos.symbol}')" class="px-1.5 py-1 bg-yellow-600 hover:bg-yellow-500 text-white text-[10px] font-bold rounded transition" title="Set Balance Target">$</button>
            </div>
          ` : `<span class="text-slate-500">-</span>`}
        </td>
        <td class="px-3 py-3 text-center">
          <button onclick="closePosition('${pos.symbol}', '${pos.side}', ${pos.size})" class="px-2 py-1.5 bg-red-600 hover:bg-red-500 text-white text-xs font-bold rounded transition shadow-lg shadow-red-900/30">⚡</button>
        </td>
      </tr>
    `;
  }).join("");
}

async function refreshBots() {
  const data = await fetchJSON("/bots/runtime");
  const bots = data.bots || [];
  window._lastBots = bots;  // Cache for backtest lookup
  const tbody = $("bots-body");

  // Count running bots and toggle emergency button visibility
  const runningBotsCount = bots.filter(b => b.status === "running").length;
  const emergencySection = $("emergency-stop-section");
  if (emergencySection) {
    emergencySection.style.display = runningBotsCount > 0 ? "flex" : "none";
  }

  if (bots.length === 0) {
    tbody.innerHTML = `<tr><td colspan="13" class="px-4 py-8 text-center text-slate-500">No bots configured</td></tr>`;
    return;
  }

  tbody.innerHTML = bots.map(bot => {
    const pnl = formatPnL(bot.total_pnl);
    const bounds = `${formatNumber(bot.lower_price, 2)} - ${formatNumber(bot.upper_price, 2)}`;
    const profile = bot.profile || "normal";
    const autoDirection = bot.auto_direction || false;
    const rangeMode = bot.range_mode || "fixed";
    const widthPct = bot.last_range_width_pct;
    const scalpAnalysis = bot.scalp_analysis || null;
    const shortId = bot.id ? bot.id.slice(0, 8) : "-";

    const newPnl = parseFloat(bot.total_pnl || 0);
    previousValues.botPnls[bot.id] = newPnl;

    // TP% and PnL% display
    const tpPct = bot.tp_pct;
    const pnlPct = bot.pnl_pct;
    const tpStr = (typeof tpPct === "number" && !isNaN(tpPct) && tpPct > 0 && tpPct < 1) ? (tpPct * 100).toFixed(1) + "%" : (bot.mode === "scalp_pnl" ? "Dynamic" : "-");
    const pnlPctStr = (typeof pnlPct === "number" && !isNaN(pnlPct)) ? (pnlPct * 100).toFixed(2) + "%" : "0.00%";
    const pnlPctClass = pnlPct > 0 ? "text-emerald-400" : (pnlPct < 0 ? "text-red-400" : "text-slate-400");
    const runtimeText = formatRuntimeHours(bot.runtime_hours);
    const pph = bot.profit_per_hour || 0;
    const pphFmt = formatPnL(pph);
    const lifetimeRuntimeText = formatRuntimeHours(bot.lifetime_hours);
    const lifetimePphFmt = formatPnL(bot.lifetime_profit_per_hour || 0);
    const lifetimePnlFmt = formatPnL(bot.lifetime_pnl || bot.realized_pnl || 0);

    // Symbol cumulative PnL
    const symbolPnl = bot.symbol_pnl || {};
    const symbolNetPnl = formatPnL(symbolPnl.net_pnl || 0);
    const symbolTradeCount = symbolPnl.trade_count || 0;
    const symbolWinRate = symbolPnl.win_rate || 0;

    return `
      <tr class="table-row" id="bot-row-${bot.symbol || 'Auto-Pilot'}">
        <td class="px-3 py-3 text-xs text-slate-400 whitespace-nowrap">${shortId}</td>
        <td class="px-3 py-3 font-medium">
          <button onclick="openBotDetailModal('${bot.id}')" class="text-white hover:text-emerald-400 transition cursor-pointer underline decoration-dotted underline-offset-2" title="Click to see details & trade history">
            ${bot.symbol || '-'}
          </button>
        </td>
        <td class="px-3 py-3">${modeBadge(bot.mode, scalpAnalysis, bot)}</td>
        <td class="px-3 py-3 text-center">${rangeModeBadge(rangeMode, widthPct)}</td>
        <td class="px-3 py-3 text-center">${profileBadge(profile, autoDirection)}</td>
        <td class="px-3 py-3 text-xs">${bounds}</td>
        <td class="px-3 py-3 text-right">${bot.grid_count || "-"}</td>
        <td class="px-3 py-3 text-right">${bot.leverage || 3}x</td>
        <td class="px-3 py-3 text-right">${formatNumber(bot.investment, 0)}</td>
        <td class="px-3 py-3 text-center">
          ${statusBadge(bot.status)}
          ${upnlSlBadges(bot)}
          ${aiGuardBadge(bot)}
          ${entryGateBadge(bot)}
          ${dangerZoneBadge(bot)}
        </td>
        <td class="px-3 py-3 text-center text-xs">
          <span class="text-slate-400">${tpStr}</span>
          <span class="mx-1 text-slate-600">/</span>
          <span class="${pnlPctClass}">${pnlPctStr}</span>
        </td>
        <td class="px-3 py-3 text-right ${pnl.class}" data-bot-pnl="${bot.id}">
          <div class="flex flex-col items-end">
            <span class="font-medium">${pnl.text}</span>
            <span class="text-xs text-slate-500">R: ${formatPnL(bot.realized_pnl, 2).text}</span>
          </div>
        </td>
        <td class="px-3 py-3 text-center text-xs">
          <div class="flex flex-col items-center">
            <span class="text-slate-400">${runtimeText}</span>
            <span class="${pphFmt.class} font-medium">${pphFmt.text}/h</span>
            <span class="text-[10px] text-slate-500" title="Lifetime runtime and P&L">${lifetimeRuntimeText !== "-" ? `${lifetimeRuntimeText} • ${lifetimePphFmt.text}/h • ${lifetimePnlFmt.text}` : "-"
      }</span>
          </div>
        </td>
        <td class="px-3 py-3 text-right ${symbolNetPnl.class}" title="${symbolTradeCount} trades, ${symbolWinRate}% win rate">
          <div class="flex flex-col items-end">
            <span class="font-medium">${symbolNetPnl.text}</span>
            <span class="text-xs text-slate-500">${symbolTradeCount} trades</span>
          </div>
        </td>
        <td class="px-3 py-3 text-center">
          <div class="flex items-center justify-center gap-2">
            ${bot.status !== "running" && bot.status !== "recovering" ? `<button onclick="botAction('start', '${bot.id}', event)" title="Start" class="px-2 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded text-white transition text-xs">▶</button>` : ""}
            ${bot.status === "running" ? `<button onclick="botAction('pause', '${bot.id}', event)" title="Pause" class="px-2 py-1.5 bg-amber-500 hover:bg-amber-400 rounded text-black transition text-xs font-bold">⏸</button>` : ""}
            ${bot.status === "paused" ? `<button onclick="botAction('resume', '${bot.id}', event)" title="Resume" class="px-2 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-white transition text-xs">▶</button>` : ""}
            ${bot.status === "recovering" ? `<button onclick="botAction('resume', '${bot.id}', event)" title="Force Resume" class="px-2 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-white transition text-xs">▶ Resume</button>` : ""}
            <button onclick="editBotById('${bot.id}')" title="Edit" class="px-2 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 hover:text-white transition text-xs">✏️</button>
            <button onclick='showQuickEdit("${bot.id}", ${JSON.stringify({ tp_pct: bot.tp_pct, auto_stop: bot.auto_stop, auto_stop_target_usdt: bot.auto_stop_target_usdt })})' title="Quick Settings (TP% / Balance Target)" class="px-2 py-1.5 bg-purple-700 hover:bg-purple-600 rounded text-purple-200 hover:text-white transition text-xs">⚙️</button>
            ${bot.status !== "stopped" ? `<button onclick="botAction('stop', '${bot.id}', event)" title="Stop" class="px-2 py-1.5 bg-red-600 hover:bg-red-500 rounded text-white transition text-xs font-bold">⏹</button>` : ""}
            <button onclick="botAction('delete', '${bot.id}', event)" title="Delete" class="px-2 py-1.5 bg-slate-700 hover:bg-red-600 rounded text-slate-400 hover:text-white transition text-xs">🗑</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  // Update running bots status display
  updateRunningBotsStatus(bots);
  updateScalpGuardCard(bots);
}

function updateScalpGuardCard(bots) {
  const minEl = $("scalp-guard-min-profit");
  const statusEl = $("scalp-guard-status");
  if (!minEl || !statusEl) return;

  const scalpBots = (bots || []).filter(
    b => (b.mode || "").toLowerCase() === "scalp_pnl"
  );
  if (scalpBots.length === 0) {
    minEl.textContent = "$-";
    statusEl.textContent = "No scalp bots";
    statusEl.className = "text-sm font-medium text-slate-500";
    return;
  }

  const runningScalps = scalpBots.filter(b => b.status === "running");
  const bot = runningScalps[0] || scalpBots[0];

  const minProfit = bot.scalp_adaptive_min_profit;
  minEl.textContent =
    minProfit !== undefined && minProfit !== null
      ? `$${formatNumber(minProfit, 2)}`
      : "$-";

  let statusText = bot.status || "-";
  if (
    bot.last_warning &&
    String(bot.last_warning).toLowerCase().includes("scalp")
  ) {
    statusText = bot.last_warning;
  } else if (bot.scalp_analysis && bot.scalp_analysis.condition) {
    statusText = `Market: ${bot.scalp_analysis.condition}`;
  }

  statusEl.textContent = statusText;
  if (
    String(statusText).toLowerCase().includes("skip") ||
    String(statusText).toLowerCase().includes("cooldown")
  ) {
    statusEl.className = "text-sm font-medium text-amber-400";
  } else if (bot.status === "running") {
    statusEl.className = "text-sm font-medium text-emerald-400";
  } else {
    statusEl.className = "text-sm font-medium text-slate-400";
  }
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
  const gridCount = bot.grid_count || 10;
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

function showBacktestModal(data) {
  // Create modal if not exists
  let modal = $("backtest-modal");
  if (!modal) {
    const modalHtml = `
  <div id="backtest-modal" class="fixed inset-0 bg-black/80 hidden items-center justify-center z-50 backdrop-blur-sm">
      <div class="bg-slate-800 border border-slate-700 rounded-lg p-6 max-w-md w-full shadow-2xl">
          <h3 class="text-xl font-bold text-emerald-400 mb-4">Backtest Results</h3>
          <div id="backtest-content" class="space-y-3 text-sm"></div>
          <div class="mt-6 flex justify-end">
              <button onclick="$('backtest-modal').classList.add('hidden')" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-white">Close</button>
          </div>
      </div>
  </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modal = $("backtest-modal");
  }

  const content = $("backtest-content");
  const pnlClass = data.profit >= 0 ? "text-emerald-400" : "text-red-400";

  content.innerHTML = `
  <div class="flex justify-between border-b border-slate-700 pb-2">
      <span class="text-slate-400">Symbol</span>
      <span class="font-bold text-white">${data.symbol}</span>
  </div>
  <div class="flex justify-between border-b border-slate-700 pb-2">
      <span class="text-slate-400">Duration</span>
      <span class="text-white">${data.days} Days</span>
  </div>
  <div class="flex justify-between border-b border-slate-700 pb-2">
      <span class="text-slate-400">Profit</span>
      <span class="font-bold ${pnlClass}">$${data.profit.toFixed(2)} (${data.roi.toFixed(2)}%)</span>
  </div>
  <div class="flex justify-between border-b border-slate-700 pb-2">
      <span class="text-slate-400">Max Drawdown</span>
      <span class="text-red-400">${data.max_drawdown.toFixed(2)}%</span>
  </div>
  <div class="flex justify-between">
      <span class="text-slate-400">Final Equity</span>
      <span class="text-white">$${data.final_equity.toFixed(2)}</span>
  </div>
`;

  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function updateRunningBotsStatus(bots) {
  const container = $("running-bots-list");
  if (!container) return;

  const runningBots = bots.filter(b => b.status === "running");
  const autoStopEnabled = $("auto-stop-direction")?.checked || false;
  const alertDiv = $("direction-change-alert");

  if (runningBots.length === 0) {
    container.innerHTML = '<span class="text-xs text-slate-600">No bots running</span>';
    return;
  }

  container.innerHTML = runningBots.map(bot => {
    const mode = (bot.mode || "neutral").toLowerCase();
    const symbol = bot.symbol.replace("USDT", "");
    const rangeMode = bot.range_mode || "fixed";
    const scalp = bot.scalp_analysis;

    // Determine MARKET STATE (not bot mode)
    let marketState = "neutral";  // neutral, long, short
    let stateSource = "";

    // 1. Check scalp_analysis for market condition
    if (scalp && Object.keys(scalp).length > 0) {
      if (scalp.momentum === "up") {
        marketState = "long";
        stateSource = "momentum";
      } else if (scalp.momentum === "down") {
        marketState = "short";
        stateSource = "momentum";
      } else {
        marketState = "neutral";
        stateSource = scalp.condition || "analysis";
      }
    }

    // 2. Check trend_status for trend color
    const trendStatus = bot.trend_status || "";
    const trendMatch = trendStatus.match(/trend:\s*(\w+)/i);
    if (trendMatch) {
      const trend = trendMatch[1].toLowerCase();
      if (trend === "green") {
        marketState = "long";
        stateSource = "trend";
      } else if (trend === "red") {
        marketState = "short";
        stateSource = "trend";
      }
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

    // === AUTO-STOP ON DIRECTION CHANGE ===
    const prevState = previousValues.botMarketStates[bot.id];
    if (prevState && prevState !== marketState && autoStopEnabled) {
      // Direction changed! Trigger auto-stop
      console.log(`Direction change detected for ${bot.symbol}: ${prevState} → ${marketState}`);

      // Check if there's an open position to close
      const hasPosition = bot.position_side && bot.position_size > 0;
      const positionSide = bot.position_side;
      const positionSize = bot.position_size;
      const unrealizedPnl = parseFloat(bot.unrealized_pnl) || 0;
      const isPositionProfitable = unrealizedPnl > 0;

      // Only close position if profitable
      const shouldClosePosition = hasPosition && isPositionProfitable;

      // Show alert
      if (alertDiv) {
        const timestamp = new Date().toLocaleTimeString();
        let posMsg = "";
        if (hasPosition) {
          if (shouldClosePosition) {
            posMsg = ` Position closed (profit: $${unrealizedPnl.toFixed(2)})!`;
          } else {
            posMsg = ` Position kept open (PnL: $${unrealizedPnl.toFixed(2)})`;
          }
        }
        alertDiv.innerHTML = `🚨 <strong>${timestamp}</strong> - ${bot.symbol} direction changed: <strong>${prevState.toUpperCase()}</strong> → <strong>${marketState.toUpperCase()}</strong> - Bot stopped!${posMsg}`;
        alertDiv.classList.remove("hidden");

        // Auto-hide after 30 seconds
        setTimeout(() => alertDiv.classList.add("hidden"), 30000);
      }


      /* Helper to inject button into bot card - likely finding where bot cards are built */
      // Trigger stop
      botAction('stop', bot.id, null, true);  // silent=true

      // Close position only if profitable
      if (shouldClosePosition) {
        console.log(`Auto-closing profitable ${positionSide} position for ${bot.symbol}, size: ${positionSize}, PnL: $${unrealizedPnl}`);
        closePositionSilent(bot.symbol, positionSide, positionSize);
      } else if (hasPosition) {
        console.log(`Keeping ${positionSide} position for ${bot.symbol} open - PnL: $${unrealizedPnl} (not profitable)`);
      }

      // Play alert sound if enabled
      if (soundEnabled) {
        playTone(200, 0.3, 'square', 0.5);
        setTimeout(() => playTone(150, 0.3, 'square', 0.5), 300);
      }
    }
    // Update tracked state
    previousValues.botMarketStates[bot.id] = marketState;

    // 3. Check current position
    let positionInfo = "";
    if (bot.position_side && bot.position_size > 0) {
      const side = bot.position_side.toLowerCase();
      positionInfo = side === "buy" ? "LONG pos" : "SHORT pos";
    }

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

    // Build display - show everything as text
    return `<div class="flex flex-col gap-0.5 p-2 rounded bg-slate-800 border border-slate-700 min-w-[120px]">
      <div class="flex items-center justify-between">
        <span class="font-bold text-white text-xs">${symbol}</span>
        <span class="text-[9px] text-slate-400">${modeShort}</span>
      </div>
      <div class="flex items-center gap-1">
        <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${stateClass} text-white">
          ${stateIcon} ${stateLabel}
        </span>
        <span class="text-[9px] text-slate-500">${rangeBadge}</span>
        ${elapsed ? `<span class="text-[9px] text-cyan-400">${elapsed}</span>` : ''}
      </div>
      ${positionInfo ? `<div class="text-[9px] text-amber-400 font-bold">${positionInfo}</div>` : ''}
      <div class="flex flex-wrap gap-0.5 mt-0.5">
        ${trailingSlBadge(bot)}
        ${upnlSlBadges(bot)}
      </div>
      ${scalp ? `<div class="text-[9px] text-slate-500">${scalp.condition} | ${scalp.volatility} vol</div>` : ''}
    </div>`;
  }).join("");
}

async function refreshPnl() {
  const data = await fetchJSON("/pnl/log");
  const logs = data.logs || [];
  const today = data.today || {};

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
  $("pnl-today-net").textContent = todayNet.text;
  $("pnl-today-net").className = `font-medium ${todayNet.class}`;
  $("pnl-today-wins").textContent = today.wins || 0;
  $("pnl-today-losses").textContent = today.losses || 0;

  // Update all-time Closed PnL stats (fetch from stats endpoint)
  try {
    const allStats = await fetchJSON("/pnl/stats?period=all");
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

  const tbody = $("pnl-body");
  if (logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-500">No closed PnL records</td></tr>`;
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
        <td class="px-4 py-2 text-xs text-slate-400">${formatTime(log.time)}</td>
        <td class="px-4 py-2 font-medium">${log.symbol}</td>
        <td class="px-4 py-2">${log.side}</td>
        <td class="px-4 py-2 text-right ${pnl.class}">${pnl.text}</td>
        <td class="px-4 py-2 text-center text-cyan-400 text-xs">${uptime}</td>
        <td class="px-4 py-2 text-right text-slate-300">${balance}</td>
      </tr>
    `;
  }).join("");
}

// ============================================================
// Recent Scanned Coins (persists 24 hours in localStorage)
// ============================================================

const RECENT_SCANS_KEY = 'recentScannedCoins';
const RECENT_SCANS_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours

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

    // Update UI
    renderRecentScans();
  } catch (e) {
    console.error('Error saving recent scans:', e);
  }
}

/**
 * Render recent scans as clickable chips.
 */
function renderRecentScans() {
  const container = $('recent-scans-container');
  if (!container) return;

  const scans = getRecentScans();

  if (scans.length === 0) {
    container.innerHTML = '<span class="text-slate-500 text-xs">No recent scans</span>';
    return;
  }

  container.innerHTML = scans.map(s => {
    const ageMs = Date.now() - s.timestamp;
    const ageHours = Math.floor(ageMs / (60 * 60 * 1000));
    const ageText = ageHours < 1 ? 'now' : `${ageHours}h`;

    return `
      <button onclick="scanSymbol('${s.symbol}')" 
        class="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded transition flex items-center gap-1"
        title="Scanned ${ageText} ago - click to scan again">
        <span>${s.symbol}</span>
        <span class="text-slate-500 text-[10px]">${ageText}</span>
      </button>
    `;
  }).join('');
}



/**
 * Scan a specific symbol (used by recent scan chips).
 */
function scanSymbol(symbol) {
  const input = $('scanner-symbols');
  if (input) {
    input.value = symbol;
  }
  scanNeutral();
}



/**
 * Clear all recent scans.
 */
function clearRecentScans() {
  localStorage.removeItem(RECENT_SCANS_KEY);
  renderRecentScans();
}

async function scanNeutral() {
  const symbolsInput = $("scanner-symbols").value.trim();
  let url = "/neutral-scan";
  if (symbolsInput) url += `?symbols=${encodeURIComponent(symbolsInput)}`;

  // Save to recent scans
  if (symbolsInput) {
    addRecentScans(symbolsInput);
  }

  const tbody = $("scanner-body");
  tbody.innerHTML = `<tr><td colspan="14" class="px-4 py-8 text-center text-slate-500">Scanning...</td></tr>`;

  try {
    const data = await fetchJSON(url);
    const results = data.results || [];
    if (results.length === 0) {
      tbody.innerHTML = `<tr><td colspan="14" class="px-4 py-8 text-center text-slate-500">No results found</td></tr>`;
      return;
    }
    tbody.innerHTML = results.map(r => {
      const range = r.suggested_range || {};
      const rangeStr = `${formatNumber(range.lower, 2)} - ${formatNumber(range.upper, 2)}`;
      const recMode = r.recommended_mode || "neutral";
      const recRangeMode = r.recommended_range_mode || "fixed";
      const riskData = calculateRisk(r);
      return `
            <tr class="table-row">
              <td class="px-1 py-2 font-medium text-white w-16 break-words">${r.symbol}</td>
              <td class="px-1 py-2 text-center w-10">${riskBadge(riskData)}</td>
              <td class="px-1 py-2 text-right w-10">${formatNumber(r.adx, 1)}</td>
              <td class="px-1 py-2 text-right w-10">${formatPercent(r.atr_pct)}</td>
              <td class="px-1 py-2 text-right w-10">${formatPercent(r.bbw_pct)}</td>
              <td class="px-1 py-2 text-right w-12" title="24h Volume in USDT">${formatVolume(r.volume_24h_usdt)}</td>
              <td class="px-1 py-2 text-center w-10">${btcCorrBadge(r.btc_correlation)}</td>
              <td class="px-1 py-2 text-center w-14 break-words">${regimeBadge(r.regime)}</td>
              <td class="px-1 py-2 text-center w-12">${trendBadge(r.trend || 'neutral')}</td>
              <td class="px-1 py-2 text-center text-xs w-12">${r.speed}</td>
              <td class="px-1 py-2 text-center text-xs w-12">${formatVelocity(r.price_velocity, r.velocity_display)}</td>
              <td class="px-1 py-2 text-center w-20 break-words">${recommendedModeBadge(recMode, recRangeMode)}</td>
              <td class="px-1 py-2 text-xs w-24 break-words">${rangeStr}</td>
              <td class="px-1 py-2 text-center w-12">
                <button onclick='useScanResult(${JSON.stringify(r)})' class="px-2 py-1 bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-400 text-xs rounded transition">Use</button>
              </td>
            </tr>
          `;
    }).join("");
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="14" class="px-4 py-8 text-center text-red-400">Scan failed: ${error.message}</td></tr>`;
  }
}

function fillBotForm(bot) {
  $("bot-id").value = bot.id || "";
  $("bot-symbol").value = bot.symbol || "";
  $("bot-lower").value = bot.lower_price || "";
  $("bot-upper").value = bot.upper_price || "";
  $("bot-grids").value = bot.grid_count || 10;
  gridCountManuallyEdited = bot.grid_count > 0;  // Keep existing value if bot has grid_count
  $("bot-investment").value = bot.investment || 50;
  $("bot-leverage").value = bot.leverage || 3;
  $("bot-mode").value = bot.mode || "neutral";
  $("bot-profile").value = bot.profile || "normal";
  $("bot-auto-direction").checked = bot.auto_direction || false;
  $("bot-auto-stop").value = bot.auto_stop || "";
  $("bot-balance-target").value = bot.auto_stop_target_usdt || "";

  // Trailing SL settings (Smart Feature #14)
  const trailingSLCheckbox = $("bot-trailing-sl");
  if (trailingSLCheckbox) {
    trailingSLCheckbox.checked = bot.trailing_sl_enabled !== false;
  }
  const trailingActiv = $("bot-trailing-sl-activation");
  if (trailingActiv) {
    trailingActiv.value = bot.trailing_sl_activation_pct != null ? (bot.trailing_sl_activation_pct * 100).toFixed(2) : "";
  }
  const trailingDist = $("bot-trailing-sl-distance");
  if (trailingDist) {
    trailingDist.value = bot.trailing_sl_distance_pct != null ? (bot.trailing_sl_distance_pct * 100).toFixed(2) : "";
  }

  const recoveryToggle = $("bot-recovery-enabled");
  if (recoveryToggle) {
    recoveryToggle.checked = bot.recovery_enabled !== false;
  }

  const rangeModeSelect = $("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.value = bot.range_mode || "fixed";
    rangeModeSelect.disabled = bot.mode === "scalp_pnl";
  }

  // Fill TP% field (convert from fraction to percentage)
  const tpInput = $("bot-tp-pct");
  if (tpInput) {
    const tp = bot.tp_pct;
    if (typeof tp === "number" && !isNaN(tp) && tp > 0 && tp < 1) {
      tpInput.value = (tp * 100).toFixed(2);
    } else {
      tpInput.value = "";
    }
  }

  // Volatility Gate (Smart Feature #15)
  const volGateEnabled = $("bot-volatility-gate-enabled");
  if (volGateEnabled) {
    volGateEnabled.checked = !!bot.neutral_volatility_gate_enabled;
  }
  const volGateThresh = $("bot-volatility-gate-threshold");
  if (volGateThresh) {
    volGateThresh.value = bot.neutral_volatility_gate_threshold_pct || 5.0;
  }

  // Entry Gate (Safety Gate - Feature #19)
  const entryGateEnabled = $("bot-entry-gate-enabled");
  if (entryGateEnabled) {
    entryGateEnabled.checked = bot.entry_gate_enabled !== false;
  }

  const autoSL = $("bot-auto-stoploss-enabled");
  if (autoSL) {
    autoSL.checked = bot.auto_stop_loss_enabled !== false;
  }
  const autoTP = $("bot-auto-takeprofit-enabled");
  if (autoTP) {
    autoTP.checked = bot.auto_take_profit_enabled !== false;
  }
  const trendProt = $("bot-trend-protection-enabled");
  if (trendProt) {
    trendProt.checked = bot.trend_protection_enabled !== false;
  }
  const dangerZone = $("bot-danger-zone-enabled");
  if (dangerZone) {
    dangerZone.checked = bot.danger_zone_enabled !== false;
  }
  const autoNeutral = $("bot-auto-neutral-mode-enabled");
  if (autoNeutral) {
    autoNeutral.checked = bot.auto_neutral_mode_enabled !== false;
  }

  updateRiskInfo();
  updateScalpPnlInfoVisibility();
}

// Look up bot by ID from cached bots and fill the form
function editBotById(botId) {
  const bot = (window._lastBots || []).find(b => b.id === botId);
  if (bot) {
    fillBotForm(bot);
    $("bot-form").scrollIntoView({ behavior: "smooth" });
  } else {
    console.error("Bot not found in cache:", botId);
    alert("Bot not found. Please refresh the page and try again.");
  }
}

function resetBotForm() {
  $("bot-id").value = "";
  $("bot-symbol").value = "";
  $("bot-lower").value = "";
  $("bot-upper").value = "";
  $("bot-grids").value = 10;
  gridCountManuallyEdited = false;
  $("bot-investment").value = 50;
  $("bot-leverage").value = 3;
  $("bot-mode").value = "neutral";
  $("bot-profile").value = "normal";
  $("bot-auto-direction").checked = false;
  $("bot-auto-stop").value = "";
  $("bot-balance-target").value = "";

  // Trailing SL checkbox (Smart Feature #14) - reset to enabled by default
  const trailingSLCheckbox = $("bot-trailing-sl");
  if (trailingSLCheckbox) {
    trailingSLCheckbox.checked = true;  // Default to enabled
  }

  const rangeModeSelect = $("bot-range-mode");
  if (rangeModeSelect) {
    rangeModeSelect.value = "fixed";
    rangeModeSelect.disabled = false;
  }

  const tpInput = $("bot-tp-pct");
  if (tpInput) tpInput.value = "";

  $("bot-risk-info").innerHTML = "";

  // Reset Volatility Gate (Smart Feature #15)
  const volGateEnabled = $("bot-volatility-gate-enabled");
  if (volGateEnabled) volGateEnabled.checked = true;  // Default to enabled
  const volGateThresh = $("bot-volatility-gate-threshold");
  if (volGateThresh) volGateThresh.value = 5.0;

  const entryGateEnabled = $("bot-entry-gate-enabled");
  if (entryGateEnabled) entryGateEnabled.checked = true;
  const autoSL = $("bot-auto-stoploss-enabled");
  if (autoSL) autoSL.checked = true;
  const autoTP = $("bot-auto-takeprofit-enabled");
  if (autoTP) autoTP.checked = true;
  const trendProt = $("bot-trend-protection-enabled");
  if (trendProt) trendProt.checked = true;
  const dangerZone = $("bot-danger-zone-enabled");
  if (dangerZone) dangerZone.checked = true;
  const autoNeutral = $("bot-auto-neutral-mode-enabled");
  if (autoNeutral) autoNeutral.checked = true;

  updateTpUsdt();
  updateScalpPnlInfoVisibility();
}

async function updateRiskInfo() {
  const symbol = $("bot-symbol").value.trim().toUpperCase();
  const investment = parseFloat($("bot-investment").value) || 0;
  const leverage = parseFloat($("bot-leverage").value) || 1;
  const lower = parseFloat($("bot-lower").value) || 0;
  const upper = parseFloat($("bot-upper").value) || 0;
  const gridsInput = parseInt($("bot-grids").value) || 10;
  let info = [];

  // Fetch min order value for symbol (for min investment calculation)
  let minOrderValue = 5.1; // Default fallback
  if (symbol && symbol.length > 3) {
    try {
      const priceData = await fetchJSON(`/ price ? symbol = ${encodeURIComponent(symbol)} `);
      if (priceData.min_order_value) {
        minOrderValue = priceData.min_order_value;
      }
    } catch (e) {
      // Ignore - symbol might not exist yet
    }
  }

  // Update min investment / leverage display
  // Calculate actual grid levels based on range width and step (0.37%)
  const minInvestDisplay = $("min-investment-display");
  const gridSpaceDisplay = $("grid-space-display");
  if (minInvestDisplay && leverage > 0) {
    let estimatedLevels = gridsInput || 10;

    // If we have a valid range, estimate actual level count from range width
    if (lower > 0 && upper > lower) {
      const rangeWidthPct = (upper - lower) / lower;
      const stepPct = 0.0037; // GRID_STEP_PCT from backend
      estimatedLevels = Math.ceil(rangeWidthPct / stepPct) + 1;
    }

    const minInvestment = Math.ceil((minOrderValue * estimatedLevels) / leverage);
    const minLevNeeded = investment > 0 ? Math.ceil(((minOrderValue * estimatedLevels) / investment) * 100) / 100 : null;
    const isBelowMinInvest = investment > 0 && investment < minInvestment;
    const isBelowMinLev = minLevNeeded && minLevNeeded > leverage;

    const levHint = minLevNeeded ? ` • Lev ≥ ${minLevNeeded.toFixed(2)} x` : "";
    const baseText = `Min: $${minInvestment} (${estimatedLevels} levels${levHint})`;
    if (isBelowMinInvest || isBelowMinLev) {
      minInvestDisplay.innerHTML = `< span class="text-red-400" > ${baseText}</span > `;
    } else {
      minInvestDisplay.innerHTML = `< span class="text-slate-500" > ${baseText}</span > `;
    }
  }

  if (investment > 0 && leverage > 0) {
    const notional = investment * leverage;
    info.push(`Notional: $${notional.toFixed(2)} `);
  }

  if (lower > 0 && upper > lower) {
    const range = ((upper - lower) / lower * 100).toFixed(2);
    info.push(`Range: ${range}% `);
    const gridStep = 0.0037;
    const estimatedGrids = Math.floor(Math.log(upper / lower) / Math.log(1 + gridStep)) + 1;

    // Only auto-fill grid count if not manually edited
    if (!gridCountManuallyEdited) {
      $("bot-grids").value = estimatedGrids;
    }

    // Use the actual value in the field for calculations
    const grids = parseInt($("bot-grids").value) || estimatedGrids;
    info.push(`Est.grids: ${estimatedGrids}${gridCountManuallyEdited ? ` (using ${grids})` : ''} `);
    if (gridSpaceDisplay && grids > 1) {
      const space = (upper - lower) / (grids - 1);
      const pct = (space / lower) * 100;
      gridSpaceDisplay.textContent = `Grid step: ${space.toFixed(6)} (${pct.toFixed(2)}%)`;
    }

    if (investment > 0 && leverage > 0 && grids > 0) {
      const notional = investment * leverage;
      const valuePerGrid = notional / grids;
      info.push(`$${valuePerGrid.toFixed(2)}/grid`);
    }
  } else if (gridSpaceDisplay) {
    gridSpaceDisplay.textContent = "";
  }

  $("bot-risk-info").innerHTML = info.length > 0 ? info.join(" • ") : "";

  // Also update TP USDT display
  updateTpUsdt();
}

function updateTpUsdt() {
  const investment = parseFloat($("bot-investment").value) || 0;
  const leverage = parseFloat($("bot-leverage").value) || 1;
  const tpPct = parseFloat($("bot-tp-pct").value) || 0;
  const display = $("tp-usdt-display");

  if (!display) return;

  if (investment > 0 && leverage > 0 && tpPct > 0) {
    const tpUsdt = investment * leverage * (tpPct / 100);
    display.textContent = `= $${tpUsdt.toFixed(2)} USDT profit`;
  } else {
    display.textContent = "";
  }
}

function formatRuntimeHours(hours) {
  if (!hours || hours <= 0) return "-";
  const totalMinutes = Math.floor(hours * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  if (h < 24) return `${h}h ${m}m`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return `${d}d ${rh}h`;
}

// Auto-fill range and grids based on coin's ATR and volatility
let autoFillDebounceTimer = null;
async function autoFillRangeAndGrids() {
  const symbol = $("bot-symbol").value.trim().toUpperCase();
  if (!symbol || symbol.length < 4) return;

  // Debounce to avoid too many API calls
  clearTimeout(autoFillDebounceTimer);
  autoFillDebounceTimer = setTimeout(async () => {
    try {
      // Fetch scanner data for this symbol
      const data = await fetchJSON(`/neutral-scan?symbols=${encodeURIComponent(symbol)}`);
      const results = data.results || [];

      if (results.length === 0) return;

      const r = results[0];
      const range = r.suggested_range || {};

      // Only auto-fill if fields are empty or zero
      const lowerInput = $("bot-lower");
      const upperInput = $("bot-upper");
      const currentLower = parseFloat(lowerInput.value) || 0;
      const currentUpper = parseFloat(upperInput.value) || 0;

      if (currentLower === 0 && currentUpper === 0 && range.lower && range.upper) {
        // Round to appropriate decimal places based on price magnitude
        const decimals = range.lower < 1 ? 6 : range.lower < 100 ? 4 : 2;
        lowerInput.value = range.lower.toFixed(decimals);
        upperInput.value = range.upper.toFixed(decimals);

        // Reset grid manual edit flag so grids auto-calculate
        gridCountManuallyEdited = false;

        // Trigger risk info update to calculate grids
        updateRiskInfo();

        console.log(`Auto-filled range for ${symbol}: ${range.lower.toFixed(decimals)} - ${range.upper.toFixed(decimals)} (ATR: ${(r.atr_pct * 100).toFixed(2)}%)`);
      }
    } catch (e) {
      // Silently fail - symbol might not exist
      console.log(`Auto-fill failed for ${symbol}: ${e.message}`);
    }
  }, 500); // 500ms debounce
}

async function saveBot() {
  const rangeModeSelect = $("bot-range-mode");
  const rangeMode = rangeModeSelect ? rangeModeSelect.value : "fixed";

  // Get TP% from input (convert from percentage to fraction)
  const tpInput = $("bot-tp-pct");
  let tpPctFraction = null;
  if (tpInput && tpInput.value.trim() !== "") {
    const raw = Number(tpInput.value.trim());
    if (!isNaN(raw) && raw > 0) {
      tpPctFraction = raw / 100.0;
    }
  }

  // Get trailing SL checkbox value (Smart Feature #14)
  const trailingSLCheckbox = $("bot-trailing-sl");
  const trailingSLEnabled = trailingSLCheckbox ? trailingSLCheckbox.checked : true;

  const botData = {
    id: $("bot-id").value || undefined,
    symbol: $("bot-symbol").value.toUpperCase(),
    lower_price: parseFloat($("bot-lower").value),
    upper_price: parseFloat($("bot-upper").value),
    investment: parseFloat($("bot-investment").value),
    leverage: parseFloat($("bot-leverage").value),
    mode: $("bot-mode").value,
    profile: $("bot-profile").value || "normal",
    range_mode: rangeMode,
    auto_direction: $("bot-auto-direction").checked,
    auto_stop: $("bot-auto-stop").value ? parseFloat($("bot-auto-stop").value) : null,
    auto_stop_target_usdt: $("bot-balance-target").value ? parseFloat($("bot-balance-target").value) : 0,
    tp_pct: tpPctFraction,
    grid_count: parseInt($("bot-grids").value) || 10,
    trailing_sl_enabled: trailingSLEnabled,  // Smart Feature #14
    trailing_sl_activation_pct: $("bot-trailing-sl-activation") && $("bot-trailing-sl-activation").value ? parseFloat($("bot-trailing-sl-activation").value) / 100 : null,
    trailing_sl_distance_pct: $("bot-trailing-sl-distance") && $("bot-trailing-sl-distance").value ? parseFloat($("bot-trailing-sl-distance").value) / 100 : null,
    neutral_volatility_gate_enabled: $("bot-volatility-gate-enabled") ? $("bot-volatility-gate-enabled").checked : false,
    neutral_volatility_gate_threshold_pct: $("bot-volatility-gate-threshold") ? parseFloat($("bot-volatility-gate-threshold").value) : 5.0,
    recovery_enabled: $("bot-recovery-enabled") ? $("bot-recovery-enabled").checked : true,
    entry_gate_enabled: $("bot-entry-gate-enabled") ? $("bot-entry-gate-enabled").checked : true,
    auto_stop_loss_enabled: $("bot-auto-stoploss-enabled") ? $("bot-auto-stoploss-enabled").checked : true,
    auto_take_profit_enabled: $("bot-auto-takeprofit-enabled") ? $("bot-auto-takeprofit-enabled").checked : true,
    trend_protection_enabled: $("bot-trend-protection-enabled") ? $("bot-trend-protection-enabled").checked : true,
    danger_zone_enabled: $("bot-danger-zone-enabled") ? $("bot-danger-zone-enabled").checked : true,
    auto_neutral_mode_enabled: $("bot-auto-neutral-mode-enabled") ? $("bot-auto-neutral-mode-enabled").checked : true,
  };

  if (!botData.symbol) { alert("Symbol is required"); return; }
  if (!botData.lower_price || !botData.upper_price || botData.lower_price >= botData.upper_price) {
    alert("Invalid price range"); return;
  }

  try {
    const isEdit = !!botData.id;
    const savedSymbol = botData.symbol;
    const savedBotId = botData.id;
    const resp = await fetchJSON("/bots", { method: "POST", body: JSON.stringify(botData) });
    resetBotForm();
    await refreshBots();
    showToast(isEdit ? `✅ ${savedSymbol} bot updated!` : `✅ ${savedSymbol} bot created!`, "success");

    // Scroll to the bot row and highlight it in purple
    const targetBotId = resp?.bot?.id || savedBotId;
    if (typeof scrollToBotRow === "function") {
      scrollToBotRow(targetBotId, savedSymbol);
    } else {
      // Inline fallback with purple highlight
      setTimeout(() => {
        let botId = targetBotId;
        if (!botId && savedSymbol) {
          const matching = (window._lastBots || []).filter(b => b.symbol === savedSymbol);
          if (matching.length >= 1) {
            matching.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
            botId = matching[0].id;
          }
        }
        const row = botId ? document.getElementById(`bot-row-${botId}`) : null;
        if (row) {
          row.scrollIntoView({ behavior: "smooth", block: "center" });
          row.style.transition = "background-color 0.4s ease, box-shadow 0.4s ease";
          row.style.backgroundColor = "rgba(168, 85, 247, 0.18)";
          row.style.boxShadow = "0 0 15px rgba(168, 85, 247, 0.5)";
          setTimeout(() => {
            row.style.backgroundColor = "";
            row.style.boxShadow = "";
          }, 4000);
        }
      }, 500);
    }
  } catch (error) {
    showToast(`❌ Failed to save bot: ${error.message}`, "error");
  }
}

function editBot(bot) {
  fillBotForm(bot);
  $("bot-form").scrollIntoView({ behavior: "smooth" });
}

function useScanResult(result) {
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
    investment: 50,
    leverage: 3,
    auto_direction: false,
  });

  // Show recommendation reasoning in console
  if (result.mode_reasoning) {
    console.log(`[Scanner] ${result.symbol}: ${result.mode_reasoning}`);
  }

  $("bot-form").scrollIntoView({ behavior: "smooth" });
}

async function applyScalpPreset() {
  const symbol = $("bot-symbol").value.trim().toUpperCase();
  if (!symbol) { alert("Please enter a symbol first"); return; }

  try {
    const data = await fetchJSON(`/price?symbol=${encodeURIComponent(symbol)}`);
    if (!data || !data.last_price) { alert("Failed to fetch price for " + symbol); return; }

    const last = Number(data.last_price);
    if (!last || last <= 0) { alert("Invalid price received"); return; }

    const widthPct = 0.03;
    const half = last * widthPct / 2.0;
    const lower = last - half;
    const upper = last + half;

    $("bot-lower").value = lower.toFixed(6);
    $("bot-upper").value = upper.toFixed(6);
    $("bot-investment").value = 30;
    $("bot-leverage").value = 5;
    $("bot-mode").value = "neutral";
    const profileInput = $("bot-profile");
    if (profileInput) profileInput.value = "scalp";
    updateRiskInfo();
    alert(`⚡ Scalp preset applied for ${symbol}\nPrice: ${last.toFixed(4)}\nRange: ${lower.toFixed(4)} - ${upper.toFixed(4)}`);
  } catch (error) {
    alert(`Failed to apply scalp preset: ${error.message}`);
  }
}

async function botAction(action, botId, event, silent = false) {
  // Add click animation to button
  if (event && event.target) {
    const btn = event.target.closest('button');
    if (btn) {
      btn.classList.add('btn-click-animate');
      setTimeout(() => btn.classList.remove('btn-click-animate'), 200);
    }
  }

  if (action === "delete" && !silent && !confirm("Are you sure you want to delete this bot?")) return;
  try {
    await fetchJSON(`/bots/${action}`, { method: "POST", body: JSON.stringify({ id: botId }) });
    await refreshBots();

    // For stop action: auto-retry after 2 seconds to clear any delayed orders
    if (action === "stop") {
      console.log(`Bot ${botId}: Stop initiated${silent ? ' (auto-stop)' : ''}, will retry in 2s to clear delayed orders...`);
      setTimeout(async () => {
        try {
          await fetchJSON(`/bots/stop`, { method: "POST", body: JSON.stringify({ id: botId }) });
          await refreshBots();
          console.log(`Bot ${botId}: Stop retry completed`);
        } catch (e) {
          console.log(`Bot ${botId}: Stop retry - ${e.message}`);
        }
      }, 2000);
    }
  } catch (error) {
    if (!silent) {
      alert(`Action failed: ${error.message}`);
    } else {
      console.error(`Auto-stop failed for ${botId}: ${error.message}`);
    }
  }
}

async function removeAllBots() {
  // Get current bots count
  const tbody = $("bots-body");
  const rows = tbody ? tbody.querySelectorAll("tr:not(.no-bots-row)") : [];
  const botCount = rows.length;

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
    await refreshBots();
    await refreshPositions();
    await refreshSummary();
  } catch (error) {
    alert(`❌ Failed to remove bots: ${error.message}`);
  }
}

async function closePosition(symbol, side, size) {
  try {
    await fetchJSON("/close-position", { method: "POST", body: JSON.stringify({ symbol, side, size }) });
    await refreshPositions();
    await refreshSummary();
  } catch (error) {
    alert(`❌ Failed to close position: ${error.message}`);
  }
}

async function closePositionSilent(symbol, side, size) {
  try {
    await fetchJSON("/close-position", { method: "POST", body: JSON.stringify({ symbol, side, size }) });
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

  try {
    await fetchJSON("/emergency-stop", { method: "POST" });

    // Play alarm sound if sound is enabled
    if (soundEnabled) {
      playTone(800, 0.3, 'square', 0.3);
    }

    // Refresh everything
    await refreshAll();

  } catch (error) {
    console.error("Emergency stop error:", error);
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
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

function updateScalpPnlInfoVisibility() {
  const modeSelect = $("bot-mode");
  const scalpPnlInfo = $("scalp-pnl-info");
  const scalpMarketInfo = $("scalp-market-info");
  const rangeModeSelect = $("bot-range-mode");

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
}

function initEventListeners() {
  $("btn-save-bot").addEventListener("click", saveBot);
  $("btn-reset-bot").addEventListener("click", resetBotForm);
  $("btn-scalp-preset").addEventListener("click", (e) => { e.preventDefault(); applyScalpPreset(); });
  $("btn-scan-neutral").addEventListener("click", scanNeutral);
  $("bot-symbol").addEventListener("input", () => { updateRiskInfo(); autoFillRangeAndGrids(); });
  $("bot-investment").addEventListener("input", updateRiskInfo);
  $("bot-leverage").addEventListener("input", updateRiskInfo);
  $("bot-lower").addEventListener("input", updateRiskInfo);
  $("bot-upper").addEventListener("input", updateRiskInfo);
  $("bot-grids").addEventListener("input", () => { gridCountManuallyEdited = true; updateRiskInfo(); });
  $("bot-tp-pct").addEventListener("input", updateTpUsdt);
  $("scanner-symbols").addEventListener("keypress", (e) => { if (e.key === "Enter") scanNeutral(); });

  // Show/hide scalp PnL info panel based on mode selection
  const modeSelect = $("bot-mode");
  if (modeSelect) {
    modeSelect.addEventListener("change", updateScalpPnlInfoVisibility);
  }

  // Initialize select-all-on-click for text inputs
  initSelectAllOnClick();

  // Initialize recent scans display
  renderRecentScans();

}

/**
 * Initialize select-all-on-click behavior for text and number inputs.
 * Inputs with class 'select-all-on-click' or all inputs in the bot form will select all text on click.
 */
function initSelectAllOnClick() {
  // Select all inputs that should have this behavior
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

function startLiveTimer() {
  setInterval(() => {
    const el = $("last-update-time");
    if (el && lastUpdateTime) el.textContent = formatTimeAgo(lastUpdateTime);
  }, 1000);
}

// ============================================================
// Bot Status/Log Modal Functions
// ============================================================

// Track current modal tab and auto-refresh interval
let botModalCurrentTab = 'log';  // Default to Runner Log tab
let botModalRefreshInterval = null;

/**
 * Open the bot status/log modal and load initial data.
 */
function openBotModal() {
  const modal = $("botModal");
  if (!modal) return;

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden"; // Prevent background scrolling

  // Always open on Runner Log tab
  switchBotModalTab('log');

  // Start auto-refresh every 5 seconds while modal is open
  botModalRefreshInterval = setInterval(() => {
    if (botModalCurrentTab === 'status') {
      loadBotStatus();
    } else {
      loadBotLog();
    }
  }, 5000);
}

/**
 * Close the bot status/log modal.
 */
function closeBotModal() {
  const modal = $("botModal");
  if (!modal) return;

  modal.classList.add("hidden");
  document.body.style.overflow = ""; // Restore scrolling

  // Stop auto-refresh
  if (botModalRefreshInterval) {
    clearInterval(botModalRefreshInterval);
    botModalRefreshInterval = null;
  }
}

// ============================================================
// Bot Detail Modal Functions
// ============================================================

let botDetailRefreshInterval = null;

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
  $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-500">Loading...</td></tr>`;

  try {
    const data = await fetchJSON(`/bots/${botId}/details`);
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
      refreshGridVisualization();
    }, 5000);

    // Initial grid load
    refreshGridVisualization();

    $("botDetailStatus").textContent = bot.status === "recovering" ? "🔄 recovering" : bot.status;
    $("botDetailStatus").className = `px-2 py-0.5 text-xs font-medium rounded-full ${bot.status === "running" ? "bg-emerald-500/20 text-emerald-400" :
      bot.status === "paused" ? "bg-amber-500/20 text-amber-400" :
        bot.status === "recovering" ? "bg-blue-500/20 text-blue-400" :
          bot.status === "stopped" ? "bg-slate-500/20 text-slate-400" :
            "bg-red-500/20 text-red-400"
      }`;

    // Update summary cards
    const symbolPnl = bot.symbol_pnl || {};
    const netPnl = symbolPnl.net_pnl || 0;
    const netPnlFormatted = formatPnL(netPnl);
    $("botDetailNetPnl").textContent = netPnlFormatted.text;
    $("botDetailNetPnl").className = `text-xl font-bold ${netPnlFormatted.class}`;
    $("botDetailWinRate").textContent = `${symbolPnl.trade_count || 0} trades, ${symbolPnl.win_rate || 0}% win`;

    const profitFormatted = formatPnL(symbolPnl.total_profit || 0);
    $("botDetailProfit").textContent = profitFormatted.text;

    $("botDetailLoss").textContent = `-$${formatNumber(symbolPnl.total_loss || 0, 2)}`;

    const botPnlFormatted = formatPnL(bot.total_pnl || 0);
    $("botDetailBotPnl").textContent = botPnlFormatted.text;
    $("botDetailBotPnl").className = `text-xl font-bold ${botPnlFormatted.class}`;

    // Update configuration
    $("botDetailMode").textContent = bot.mode || "neutral";
    $("botDetailProfile").textContent = bot.profile || "normal";
    $("botDetailInvest").textContent = `$${formatNumber(bot.investment, 0)}`;
    $("botDetailLeverage").textContent = `${bot.leverage || 1}x`;
    $("botDetailGrids").textContent = bot.grid_count || "-";
    $("botDetailRange").textContent = `${formatNumber(bot.lower_price, 2)} - ${formatNumber(bot.upper_price, 2)}`;
    $("botDetailTp").textContent = bot.tp_pct ? `${(bot.tp_pct * 100).toFixed(1)}%` : "-";
    $("botDetailAutoStop").textContent = bot.auto_stop || "-";

    // Update Smart Features - Funding Rate
    const fundingRate = bot.funding_rate_pct;
    const fundingSignal = bot.funding_signal || "NEUTRAL";
    const fundingScore = bot.funding_score || 0;

    const fundingRateEl = $("botDetailFundingRate");
    const fundingSignalEl = $("botDetailFundingSignal");
    const fundingScoreEl = $("botDetailFundingScore");

    if (fundingRateEl) {
      if (typeof fundingRate === "number" && !isNaN(fundingRate)) {
        fundingRateEl.textContent = `${fundingRate >= 0 ? '+' : ''}${fundingRate.toFixed(4)}%`;
        fundingRateEl.className = fundingRate > 0.03 ? "text-sm font-mono text-red-400" :
          fundingRate < -0.03 ? "text-sm font-mono text-emerald-400" :
            "text-sm font-mono text-slate-300";
      } else {
        fundingRateEl.textContent = "-";
        fundingRateEl.className = "text-sm font-mono text-slate-300";
      }
    }

    if (fundingSignalEl) {
      fundingSignalEl.textContent = fundingSignal;
      const signalClasses = {
        "STRONG_BULLISH": "bg-emerald-500/30 text-emerald-400",
        "BULLISH": "bg-emerald-500/20 text-emerald-300",
        "NEUTRAL": "bg-slate-600 text-slate-300",
        "BEARISH": "bg-red-500/20 text-red-300",
        "STRONG_BEARISH": "bg-red-500/30 text-red-400"
      };
      fundingSignalEl.className = `px-2 py-0.5 text-xs rounded-full ${signalClasses[fundingSignal] || signalClasses.NEUTRAL}`;
    }

    if (fundingScoreEl) {
      fundingScoreEl.textContent = `Score: ${fundingScore > 0 ? '+' : ''}${fundingScore.toFixed(0)}`;
    }

    // Update Smart Features - Partial TP
    const partialTpState = bot.partial_tp_state || {};
    const levelsHit = partialTpState.levels_hit || [];
    const totalClosedPct = partialTpState.total_closed_pct || 0;
    const lastPartialLevel = bot.last_partial_tp_level || 0;
    const lastPartialProfit = bot.last_partial_tp_profit_pct || 0;

    const partialTpStatusEl = $("botDetailPartialTpStatus");
    const partialTpLevelEl = $("botDetailPartialTpLevel");
    const partialTpProfitEl = $("botDetailPartialTpProfit");
    const partialTpProgressEl = $("botDetailPartialTpProgress");

    if (partialTpStatusEl) {
      if (levelsHit.length > 0) {
        partialTpStatusEl.textContent = "Active";
        partialTpStatusEl.className = "px-2 py-0.5 text-xs rounded-full bg-emerald-500/30 text-emerald-400";
      } else if (bot.position_size > 0) {
        partialTpStatusEl.textContent = "Watching";
        partialTpStatusEl.className = "px-2 py-0.5 text-xs rounded-full bg-amber-500/20 text-amber-400";
      } else {
        partialTpStatusEl.textContent = "No Position";
        partialTpStatusEl.className = "px-2 py-0.5 text-xs rounded-full bg-slate-600 text-slate-300";
      }
    }

    if (partialTpLevelEl) {
      partialTpLevelEl.textContent = `Level: ${levelsHit.length}/3`;
    }

    if (partialTpProfitEl) {
      partialTpProfitEl.textContent = `Closed: ${(totalClosedPct * 100).toFixed(0)}%`;
    }

    // Show progress to next TP level
    if (partialTpProgressEl) {
      const tpLevels = [0.5, 1.0, 2.0]; // TP level thresholds in %
      if (levelsHit.length >= 3) {
        partialTpProgressEl.textContent = "All levels reached!";
        partialTpProgressEl.className = "text-xs text-emerald-400";
      } else if (bot.position_size > 0) {
        const nextLevel = tpLevels[levelsHit.length];
        const currentProfit = (bot.pnl_pct || 0) * 100;
        partialTpProgressEl.textContent = `Profit: ${currentProfit.toFixed(2)}% → Next: ${nextLevel}%`;
        partialTpProgressEl.className = currentProfit > 0 ? "text-xs text-emerald-400" : "text-xs text-slate-500";
      } else {
        partialTpProgressEl.textContent = "Waiting for position";
        partialTpProgressEl.className = "text-xs text-slate-500";
      }
    }

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
          <div class="${signalClass} rounded-lg p-2 text-xs">
            <div class="flex items-center justify-between mb-1">
              <span class="font-medium">${cfg.icon} ${cfg.label}</span>
              ${score !== null ? `<span class="${scoreClass} font-mono">${score > 0 ? '+' : ''}${typeof score === 'number' ? score.toFixed(0) : score}</span>` : ''}
            </div>
            <div class="text-xs opacity-80 truncate">${signal || '-'}${extraInfo}</div>
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
      $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-500">No trades recorded for this symbol</td></tr>`;
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
    $("botDetailFirstTrade").textContent = `First trade: ${bot.symbol_first_trade_at ? formatTime(bot.symbol_first_trade_at) : "-"}`;
    $("botDetailLastTrade").textContent = `Last trade: ${bot.symbol_last_trade_at ? formatTime(bot.symbol_last_trade_at) : "-"}`;
    refreshBotDetailLogs();

  } catch (error) {
    $("botDetailSymbol").textContent = "Error";
    $("botDetailTradesBody").innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-red-400">Failed to load: ${error.message}</td></tr>`;
  }
}

/**
 * Close the bot detail modal.
 */
function closeBotDetailModal() {
  const modal = $("botDetailModal");
  if (!modal) return;

  modal.classList.add("hidden");
  document.body.style.overflow = ""; // Restore scrolling

  if (botDetailRefreshInterval) {
    clearInterval(botDetailRefreshInterval);
    botDetailRefreshInterval = null;
  }
}

// Close modals on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    // Close Analytics modal first (z-60)
    const analyticsModal = $("analyticsModal");
    if (analyticsModal && !analyticsModal.classList.contains("hidden")) {
      closeAnalyticsModal();
      return;
    }
    // Close All PnL modal (check this one next since it may be on top)
    const allPnlModal = $("allPnlModal");
    if (allPnlModal && !allPnlModal.classList.contains("hidden")) {
      closeAllPnlModal();
      return;
    }
    // Then check Bot Detail modal
    const detailModal = $("botDetailModal");
    if (detailModal && !detailModal.classList.contains("hidden")) {
      closeBotDetailModal();
    }
  }
});

// ============================================================
// All Closed PnL Modal Functions
// ============================================================

let allPnlCurrentPage = 1;
let allPnlTotalPages = 1;

// --- Performance Analytics ---
let equityChart = null;
let dailyPnlChart = null;
let currentAnalyticsPeriod = 'all';

/**
 * Open the All PnL modal and load data.
 */
async function openAllPnlModal() {
  const modal = $("allPnlModal");
  if (!modal) return;

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  // Reset page
  allPnlCurrentPage = 1;

  // Load data
  await refreshAllPnlModal();
}

/**
 * Close the All PnL modal.
 */
function closeAllPnlModal() {
  const modal = $("allPnlModal");
  if (!modal) return;

  modal.classList.add("hidden");
  document.body.style.overflow = "";
}

/**
 * Clear filters and refresh.
 */
function clearAllPnlFilters() {
  $("allPnlStartDate").value = "";
  $("allPnlEndDate").value = "";
  $("allPnlSymbolFilter").value = "";
  allPnlCurrentPage = 1;
  refreshAllPnlModal();
}

/**
 * Change page for pagination.
 */
function allPnlChangePage(delta) {
  const newPage = allPnlCurrentPage + delta;
  if (newPage >= 1 && newPage <= allPnlTotalPages) {
    allPnlCurrentPage = newPage;
    refreshAllPnlModal();
  }
}

/**
 * Refresh the All PnL modal data.
 */
async function refreshAllPnlModal() {
  const tbody = $("allPnlTableBody");
  tbody.innerHTML = `<tr><td colspan="9" class="px-3 py-8 text-center text-slate-500">Loading...</td></tr>`;

  try {
    // Build query params
    const params = new URLSearchParams();
    params.set("page", allPnlCurrentPage);
    params.set("per_page", 100);

    const startDate = $("allPnlStartDate").value;
    const endDate = $("allPnlEndDate").value;
    const symbol = $("allPnlSymbolFilter").value.trim().toUpperCase();

    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    if (symbol) params.set("symbol", symbol);

    const data = await fetchJSON(`/pnl/all?${params.toString()}`);

    const logs = data.logs || [];
    const summary = data.summary || {};
    const pagination = data.pagination || {};

    // Update summary stats
    const totalPnlFormatted = formatPnL(summary.total_pnl);
    $("allPnlTotalPnl").textContent = totalPnlFormatted.text;
    $("allPnlTotalPnl").className = `ml-2 font-bold ${totalPnlFormatted.class}`;

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

    // Render table
    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="px-3 py-8 text-center text-slate-500">No closed PnL records found</td></tr>`;
      return;
    }

    // Color mappings for mode and range
    const modeColors = {
      neutral: "bg-slate-500/20 text-slate-300",
      neutral_classic_bybit: "bg-slate-500/20 text-slate-300",
      long: "bg-emerald-500/20 text-emerald-400",
      short: "bg-red-500/20 text-red-400",
      scalp_pnl: "bg-amber-500/20 text-amber-400",
      scalp_market: "bg-purple-500/20 text-purple-400",
    };
    const rangeColors = {
      fixed: "bg-blue-500/20 text-blue-400",
      dynamic: "bg-cyan-500/20 text-cyan-400",
      trailing: "bg-orange-500/20 text-orange-400",
    };

    tbody.innerHTML = logs.map(log => {
      const pnl = formatPnL(log.realized_pnl);
      const balance = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : '-';
      const investment = log.bot_investment ? `$${formatNumber(log.bot_investment, 0)}` : "-";
      const leverage = log.bot_leverage ? `${log.bot_leverage}x` : "-";
      const mode = log.bot_mode || "-";
      const rangeMode = log.bot_range_mode || "-";
      const botIdShort = log.bot_id ? log.bot_id.slice(0, 8) + "..." : "-";
      const modeClass = modeColors[mode] || "bg-slate-700 text-slate-400";
      const rangeClass = rangeColors[rangeMode] || "bg-slate-700 text-slate-400";

      return `
        <tr class="hover:bg-slate-700/30">
          <td class="px-3 py-2 text-slate-400 whitespace-nowrap">${formatTime(log.time)}</td>
          <td class="px-3 py-2 font-medium">${log.symbol || "-"}</td>
          <td class="px-3 py-2">${log.side || "-"}</td>
          <td class="px-3 py-2 text-right ${pnl.class}">${pnl.text}</td>
          <td class="px-3 py-2 text-right text-slate-300">${balance}</td>
          <td class="px-3 py-2 text-right text-slate-300">${investment}</td>
          <td class="px-3 py-2 text-center text-slate-300">${leverage}</td>
          <td class="px-3 py-2 text-center"><span class="px-1.5 py-0.5 ${modeClass} rounded text-xs">${mode}</span></td>
          <td class="px-3 py-2 text-center"><span class="px-1.5 py-0.5 ${rangeClass} rounded text-xs">${rangeMode}</span></td>
          <td class="px-3 py-2 text-slate-500 font-mono text-[10px]" title="${log.bot_id || 'N/A'}">${botIdShort}</td>
        </tr>
      `;
    }).join("");

  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="10" class="px-3 py-8 text-center text-red-400">Failed to load: ${error.message}</td></tr>`;
  }
}

/**
 * Open the Analytics modal and load current period data.
 */
async function openAnalyticsModal() {
  const modal = $("analyticsModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  await loadAnalytics(currentAnalyticsPeriod);
}

/**
 * Close the Analytics modal.
 */
function closeAnalyticsModal() {
  const modal = $("analyticsModal");
  if (!modal) return;
  modal.classList.add("hidden");
  document.body.style.overflow = "auto";
}

/**
 * Load and render performance analytics.
 * @param {string} period - 'today', '7d', '30d', or 'all'
 */
async function loadAnalytics(period) {
  currentAnalyticsPeriod = period;

  // Update button styles
  ['today', '7d', '30d', 'all'].forEach(p => {
    const btn = $(`analytics-${p}`);
    if (btn) {
      btn.className = p === period
        ? "px-3 py-1 text-xs font-medium rounded-md bg-emerald-600 text-white shadow-lg"
        : "px-3 py-1 text-xs font-medium rounded-md transition-all text-slate-400 hover:text-slate-200";
    }
  });

  // Get filter values
  const symbolFilter = ($("analytics-symbol-filter") || {}).value || "";
  const botFilter = ($("analytics-bot-filter") || {}).value || "";

  // Show loading, hide others
  const loadingEl = $("ana-loading");
  const errorEl = $("ana-error");
  const emptyEl = $("ana-empty");
  const contentEl = $("ana-content");
  if (loadingEl) loadingEl.classList.remove("hidden");
  if (errorEl) errorEl.classList.add("hidden");
  if (emptyEl) emptyEl.classList.add("hidden");
  if (contentEl) contentEl.classList.add("hidden");

  try {
    let url = `/pnl/analytics?period=${period}`;
    if (symbolFilter) url += `&symbol=${encodeURIComponent(symbolFilter)}`;
    if (botFilter) url += `&bot_id=${encodeURIComponent(botFilter)}`;

    const data = await fetchJSON(url);
    if (!data) return;

    if (loadingEl) loadingEl.classList.add("hidden");

    // Populate filter dropdowns
    populateAnalyticsFilters(data.available_filters, symbolFilter, botFilter);

    const m = data.metrics;

    if (m.total_trades === 0) {
      if (emptyEl) emptyEl.classList.remove("hidden");
      return;
    }

    if (contentEl) contentEl.classList.remove("hidden");

    // Row 1: Primary
    const netPnl = formatPnL(m.net_pnl);
    $("ana-net-pnl").textContent = netPnl.text;
    $("ana-net-pnl").className = `text-lg sm:text-2xl font-bold ${netPnl.class}`;

    $("ana-total-trades").textContent = m.total_trades;

    $("ana-win-rate").textContent = `${m.win_rate}%`;
    $("ana-win-rate").className = `text-lg sm:text-2xl font-bold ${m.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}`;

    const pfVal = m.profit_factor === "\u221e" ? 999 : parseFloat(m.profit_factor);
    $("ana-profit-factor").textContent = m.profit_factor === "\u221e" ? "\u221e" : formatNumber(m.profit_factor);
    $("ana-profit-factor").className = `text-lg sm:text-2xl font-bold ${pfVal >= 1 ? 'text-blue-400' : 'text-red-400'}`;

    // Row 2: Trade Quality
    $("ana-avg-win").textContent = `+$${formatNumber(m.avg_win)}`;
    $("ana-avg-loss").textContent = `-$${formatNumber(m.avg_loss)}`;

    const prDisplay = m.payoff_ratio === "\u221e" ? "\u221e" : `${formatNumber(m.payoff_ratio)}x`;
    $("ana-payoff-ratio").textContent = prDisplay;

    const expPnl = formatPnL(m.expectancy);
    $("ana-expectancy").textContent = expPnl.text;
    $("ana-expectancy").className = `text-lg sm:text-2xl font-bold ${expPnl.class}`;

    // Row 3: Risk & Records
    $("ana-mdd").textContent = `$${formatNumber(m.max_drawdown)}`;
    $("ana-mdd").className = `text-lg sm:text-2xl font-bold ${m.max_drawdown_pct > 20 ? 'text-red-400' : 'text-amber-400'}`;
    const mddPctEl = $("ana-mdd-pct");
    if (mddPctEl) mddPctEl.textContent = m.max_drawdown_pct > 0 ? `${formatNumber(m.max_drawdown_pct)}% of peak` : "";

    if (m.best_day && m.best_day.date) {
      const bd = formatPnL(m.best_day.value);
      $("ana-best-day").textContent = bd.text;
      $("ana-best-day").className = `text-lg sm:text-2xl font-bold ${bd.class}`;
      $("ana-best-day-date").textContent = m.best_day.date;
    } else {
      $("ana-best-day").textContent = "-";
      $("ana-best-day").className = "text-lg sm:text-2xl font-bold text-slate-500";
      $("ana-best-day-date").textContent = "";
    }

    if (m.worst_day && m.worst_day.date) {
      const wd = formatPnL(m.worst_day.value);
      $("ana-worst-day").textContent = wd.text;
      $("ana-worst-day").className = `text-lg sm:text-2xl font-bold ${wd.class}`;
      $("ana-worst-day-date").textContent = m.worst_day.date;
    } else {
      $("ana-worst-day").textContent = "-";
      $("ana-worst-day").className = "text-lg sm:text-2xl font-bold text-slate-500";
      $("ana-worst-day-date").textContent = "";
    }

    const streak = m.current_streak;
    const streakText = streak > 0 ? `${streak}W` : streak < 0 ? `${Math.abs(streak)}L` : "-";
    const streakClass = streak > 0 ? 'text-emerald-400' : streak < 0 ? 'text-red-400' : 'text-slate-400';
    $("ana-streak").textContent = streakText;
    $("ana-streak").className = `text-lg sm:text-2xl font-bold ${streakClass}`;

    // Diagnostic panel
    renderAnalyticsDiagnostic(m);

    // Charts
    renderEquityChart(data.equity_curve);
    renderDailyPnlChart(data.daily_pnl);

  } catch (error) {
    console.error("Failed to load analytics:", error);
    if (loadingEl) loadingEl.classList.add("hidden");
    if (errorEl) errorEl.classList.remove("hidden");
  }
}

/**
 * Populate the symbol and bot filter dropdowns from API response.
 */
function populateAnalyticsFilters(filters, currentSymbol, currentBot) {
  if (!filters) return;

  const symbolSel = $("analytics-symbol-filter");
  if (symbolSel && filters.symbols) {
    const opts = ['<option value="">All Symbols</option>'];
    for (const s of filters.symbols) {
      const sel = s === currentSymbol ? ' selected' : '';
      opts.push(`<option value="${s}"${sel}>${s.replace('USDT', '')}</option>`);
    }
    symbolSel.innerHTML = opts.join('');
  }

  const botSel = $("analytics-bot-filter");
  if (botSel && filters.bots) {
    const opts = ['<option value="">All Bots</option>'];
    for (const b of filters.bots) {
      const sel = b.id === currentBot ? ' selected' : '';
      const sym = (b.symbol || '?').replace('USDT', '');
      const mode = b.mode || '?';
      opts.push(`<option value="${b.id}"${sel}>${sym} (${mode})</option>`);
    }
    botSel.innerHTML = opts.join('');
  }
}

/**
 * Show contextual diagnostic warnings based on analytics metrics.
 */
function renderAnalyticsDiagnostic(m) {
  const diagEl = $("ana-diagnostic");
  const textEl = $("ana-diagnostic-text");
  if (!diagEl || !textEl) return;

  const messages = [];

  // Loss asymmetry: high win rate but negative expectancy
  if (m.win_rate > 55 && m.expectancy < 0 && m.avg_loss > 0 && m.avg_win > 0) {
    const ratio = (m.avg_loss / m.avg_win).toFixed(1);
    messages.push(
      `<b>Loss asymmetry detected:</b> Win rate is ${m.win_rate}% but expectancy is negative ($${formatNumber(m.expectancy)}). ` +
      `Your average loss ($${formatNumber(m.avg_loss)}) is ${ratio}x your average win ($${formatNumber(m.avg_win)}). ` +
      `Many small wins are being erased by fewer, larger losses.`
    );
  }

  // Negative expectancy without high win rate
  if (m.win_rate <= 55 && m.expectancy < 0 && m.total_trades >= 10) {
    messages.push(
      `<b>Negative expectancy:</b> Losing $${formatNumber(Math.abs(m.expectancy))} per trade on average. ` +
      `Review entry quality and risk-reward targets.`
    );
  }

  // Profit factor below 1
  if (m.profit_factor !== "\u221e" && parseFloat(m.profit_factor) > 0 && parseFloat(m.profit_factor) < 1.0 && m.total_trades >= 10) {
    messages.push(
      `<b>Profit factor below 1.0</b> (${m.profit_factor}): Total losses exceed total profits. ` +
      `Consider tighter stops or improved entry criteria.`
    );
  }

  // High drawdown
  if (m.max_drawdown_pct > 20) {
    messages.push(
      `<b>High drawdown:</b> Peak-to-trough decline reached ${formatNumber(m.max_drawdown_pct)}% of peak equity. ` +
      `Consider reducing position sizes or adding loss limits.`
    );
  }

  // Long loss streak
  if (m.longest_loss_streak >= 5) {
    messages.push(
      `<b>Extended loss streak:</b> ${m.longest_loss_streak} consecutive losses recorded. ` +
      `Check if market conditions shifted during that period.`
    );
  }

  if (messages.length > 0) {
    textEl.innerHTML = messages.map(msg => `<p>${msg}</p>`).join('');
    diagEl.classList.remove("hidden");
  } else {
    diagEl.classList.add("hidden");
  }
}

/**
 * Render the Equity Curve and Drawdown chart.
 */
function renderEquityChart(points) {
  const ctx = $("equityChart").getContext("2d");
  if (equityChart) equityChart.destroy();

  const labels = points.map(p => formatTime(p.time));
  const equityData = points.map(p => p.value);
  const drawdownData = points.map(p => -p.drawdown); // Negative for downward bars

  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Cumulative PnL',
          data: equityData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          fill: true,
          tension: 0.1,
          pointRadius: 0,
          borderWidth: 2,
          yAxisID: 'y'
        },
        {
          label: 'Drawdown',
          data: drawdownData,
          type: 'bar',
          backgroundColor: 'rgba(239, 68, 68, 0.2)',
          borderColor: 'rgba(239, 68, 68, 0.3)',
          borderWidth: 1,
          yAxisID: 'y1',
          barThickness: 'flex'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label: function (context) {
              let label = context.dataset.label || '';
              if (label) label += ': ';
              if (context.parsed.y !== null) {
                label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(context.parsed.y);
              }
              return label;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, color: '#64748b', font: { size: 10 } }
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          grid: { color: 'rgba(71, 85, 105, 0.2)' },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        y1: {
          type: 'linear',
          display: false, // Hidden but used for scaling the red bars
          position: 'right',
          beginAtZero: true,
          grid: { drawOnChartArea: false }
        }
      }
    }
  });
}

/**
 * Render the Daily PnL Histogram.
 */
function renderDailyPnlChart(days) {
  const ctx = $("dailyPnlChart").getContext("2d");
  if (dailyPnlChart) dailyPnlChart.destroy();

  const labels = days.map(d => d.date);
  const values = days.map(d => d.value);
  const colors = values.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.6)' : 'rgba(239, 68, 68, 0.6)');

  dailyPnlChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Daily PnL',
        data: values,
        backgroundColor: colors,
        borderColor: colors.map(c => c.replace('0.6', '0.8')),
        borderWidth: 1,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (context) {
              return `PnL: ${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(context.parsed.y)}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#64748b', font: { size: 10 } }
        },
        y: {
          grid: { color: 'rgba(71, 85, 105, 0.2)' },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        }
      }
    }
  });
}

/**
 * Switch between Status and Log tabs in the modal.
 * @param {string} tab - Tab name: 'status' or 'log'
 */
function switchBotModalTab(tab) {
  botModalCurrentTab = tab;

  const tabBtnStatus = $("tabBtnStatus");
  const tabBtnLog = $("tabBtnLog");
  const tabContentStatus = $("tabContentStatus");
  const tabContentLog = $("tabContentLog");

  if (tab === 'status') {
    // Activate status tab
    tabBtnStatus.className = "px-4 py-2 text-sm font-medium text-indigo-400 border-b-2 border-indigo-400 -mb-px transition";
    tabBtnLog.className = "px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent -mb-px transition";
    tabContentStatus.classList.remove("hidden");
    tabContentStatus.classList.add("block");
    tabContentLog.classList.remove("block");
    tabContentLog.classList.add("hidden");
    loadBotStatus();
  } else {
    // Activate log tab
    tabBtnLog.className = "px-4 py-2 text-sm font-medium text-indigo-400 border-b-2 border-indigo-400 -mb-px transition";
    tabBtnStatus.className = "px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent -mb-px transition";
    tabContentLog.classList.remove("hidden");
    tabContentLog.classList.add("block");
    tabContentStatus.classList.remove("block");
    tabContentStatus.classList.add("hidden");
    loadBotLog();
  }
}

/**
 * Load bot status from /api/bot/status and display in the modal.
 */
async function loadBotStatus() {
  const box = $("botStatusBox");
  const lastUpdate = $("botModalLastUpdate");

  if (!box) return;

  try {
    const res = await fetch("/api/bot/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Pretty print the JSON
    box.textContent = JSON.stringify(data, null, 2);
    box.className = "bg-slate-800/50 rounded-lg p-4 text-sm text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-[50vh]";

    // Update last update time
    if (lastUpdate) {
      lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    }

    // Also update runner status badge (in case user switches to log tab)
    updateRunnerStatus();
  } catch (e) {
    box.textContent = `Error loading status: ${e.message}`;
    box.className = "bg-red-900/30 rounded-lg p-4 text-sm text-red-400 font-mono whitespace-pre-wrap overflow-auto max-h-[50vh]";
  }
}

/**
 * Escape HTML entities to prevent XSS when using innerHTML.
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Highlight special log lines (bot started, errors, etc.)
 */
function highlightLogLines(text) {
  const lines = text.split('\n');
  return lines.map(line => {
    const escaped = escapeHtml(line);

    // Highlight "Bot started" lines with bright green background
    if (line.includes('Bot started') || line.includes('✅ Bot started') || line.includes('▶️ Bot started')) {
      return `<span class="bg-emerald-600/40 text-emerald-300 font-semibold block px-1 -mx-1 rounded">${escaped}</span>`;
    }
    // Highlight "Bot stopped" lines
    if (line.includes('Bot stopped') || line.includes('🛑 Bot stopped') || line.includes('⏹️ Bot stopped')) {
      return `<span class="bg-red-600/30 text-red-300 block px-1 -mx-1 rounded">${escaped}</span>`;
    }
    // Highlight error lines
    if (line.includes('[ERROR]') || line.includes('❌')) {
      return `<span class="text-red-400">${escaped}</span>`;
    }
    // Highlight warning lines
    if (line.includes('[WARNING]') || line.includes('⚠️')) {
      return `<span class="text-amber-400">${escaped}</span>`;
    }
    // Highlight cycle start lines
    if (line.includes('▶️ Running cycle') || line.includes('Running cycle for')) {
      return `<span class="text-cyan-400">${escaped}</span>`;
    }
    // Highlight profit/loss
    if (line.includes('realized_pnl') && line.includes('+')) {
      return `<span class="text-emerald-400">${escaped}</span>`;
    }

    return escaped;
  }).join('\n');
}

/**
 * Load bot log from /api/bot/log and display in the modal.
 */
async function loadBotLog() {
  const box = $("botLogBox");
  const lastUpdate = $("botModalLastUpdate");
  const linesSelect = $("logLinesSelect");

  if (!box) return;

  const numLines = linesSelect ? linesSelect.value : 100;

  try {
    const res = await fetch(`/api/bot/log?lines=${numLines}&_ts=${Date.now()}`, { cache: "no-store" });
    const text = await res.text();

    if (res.ok) {
      const content = text || "(No log content)";
      box.innerHTML = highlightLogLines(content);
      box.className = "bg-slate-950 rounded-lg p-4 text-xs text-green-400 font-mono whitespace-pre-wrap overflow-auto max-h-[50vh] leading-relaxed";

      // Auto-scroll to bottom to show latest logs (force with small delay to ensure rendering)
      setTimeout(() => {
        box.scrollTop = box.scrollHeight;
      }, 50);
    } else {
      box.textContent = `Error (${res.status}): ${text}`;
      box.className = "bg-red-900/30 rounded-lg p-4 text-xs text-red-400 font-mono whitespace-pre-wrap overflow-auto max-h-[50vh] leading-relaxed";
    }

    // Update last update time
    if (lastUpdate) {
      lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    }

    // Also update runner status
    updateRunnerStatus();
  } catch (e) {
    box.textContent = `Error loading log: ${e.message}`;
    box.className = "bg-red-900/30 rounded-lg p-4 text-xs text-red-400 font-mono whitespace-pre-wrap overflow-auto max-h-[50vh] leading-relaxed";
  }
}

/**
 * Update the runner status badge based on /api/bot/status response.
 */
async function updateRunnerStatus() {
  const badge = $("runnerStatusBadge");
  const startBtn = $("btnStartRunner");

  if (!badge) return;

  try {
    const res = await fetch("/api/bot/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const runner = data.runner || {};
    const isActive = runner.active === true;

    if (isActive) {
      badge.textContent = "● Running";
      badge.className = "px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/20 text-emerald-400";
      if (startBtn) {
        startBtn.classList.add("opacity-50");
        startBtn.title = "Runner is already running";
      }
    } else {
      badge.textContent = "○ Stopped";
      badge.className = "px-2 py-0.5 text-xs font-medium rounded-full bg-red-500/20 text-red-400";
      if (startBtn) {
        startBtn.classList.remove("opacity-50");
        startBtn.title = "Click to start the runner";
      }
    }
  } catch (e) {
    badge.textContent = "? Unknown";
    badge.className = "px-2 py-0.5 text-xs font-medium rounded-full bg-slate-700 text-slate-400";
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
    const res = await fetch("/api/runner/start", { method: "POST" });
    const data = await res.json();

    if (data.success) {
      // Show success
      btn.innerHTML = '<span class="mr-1">✓</span> Started!';
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
      }, 3000);
    } else {
      // Show error
      alert(`Failed to start runner: ${data.message}`);
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  } catch (e) {
    alert(`Error starting runner: ${e.message}`);
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

/**
 * Stop the runner.py process via API.
 */
async function stopRunner() {
  const btn = $("btnStopRunner");
  const badge = $("runnerStatusBadge");

  if (!btn) return;

  // Confirm before stopping
  if (!confirm("Are you sure you want to stop the runner? All running bots will pause.")) {
    return;
  }

  // Disable button and show loading state
  const originalText = btn.innerHTML;
  btn.innerHTML = '<span class="mr-1">⏳</span> Stopping...';
  btn.disabled = true;

  try {
    const res = await fetch("/api/runner/stop", { method: "POST" });
    const data = await res.json();

    if (data.success) {
      // Show success
      btn.innerHTML = '<span class="mr-1">✓</span> Stopping...';
      btn.className = "px-3 py-1 text-xs bg-amber-600 text-white font-medium rounded transition flex items-center";

      if (badge) {
        badge.textContent = "● Stopping...";
        badge.className = "px-2 py-0.5 text-xs font-medium rounded-full bg-amber-500/20 text-amber-400";
      }

      // Wait a moment then refresh log to see stop message
      setTimeout(() => {
        loadBotLog();
        btn.innerHTML = originalText;
        btn.disabled = false;
        btn.className = "px-3 py-1 text-xs bg-red-600 hover:bg-red-500 text-white font-medium rounded transition flex items-center";
        updateRunnerStatus();
      }, 3000);
    } else {
      // Show error
      alert(`Failed to stop runner: ${data.message}`);
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  } catch (e) {
    alert(`Error stopping runner: ${e.message}`);
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

/**
 * Initialize bot modal event listeners.
 */
function initBotModalListeners() {
  // Button click opens modal
  const btnStatus = $("btnBotStatus");
  if (btnStatus) {
    btnStatus.addEventListener("click", openBotModal);
  }

  // Escape key closes modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const modal = $("botModal");
      if (modal && !modal.classList.contains("hidden")) {
        closeBotModal();
      }
    }
  });
}

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
      gridEl.classList.add("hidden");
      return;
    }

    if (emptyEl) emptyEl.classList.add("hidden");
    gridEl.classList.remove("hidden");

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
        const formatScore = (score) => score > 0 ? `+${score.toFixed(0)}` : score?.toFixed(0) || '0';
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
        <div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div class="flex items-center justify-between mb-2">
            <span class="font-semibold text-white text-sm">${pred.symbol}</span>
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

          ${signalsHtml ? `<div class="flex flex-wrap gap-1 mb-2">${signalsHtml}</div>` : ""}

          ${patternsHtml ? `<div class="flex flex-wrap gap-1 mb-2">${patternsHtml}</div>` : ""}

          ${srHtml ? `<div class="mb-1">${srHtml}</div>` : ""}

          <div class="flex items-center justify-between text-[10px]">
            <span class="text-slate-500">Structure: ${pred.trend_structure || "?"}</span>
            <span class="${mtfColor}">MTF: ${pred.mtf_alignment || "?"}</span>
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

function formatPrice(price) {
  if (!price) return "?";
  if (price >= 1000) return price.toFixed(0);
  if (price >= 1) return price.toFixed(2);
  return price.toFixed(6);
}


// ============================================================
// ============================================================
// Main Initialization
// ============================================================

window.addEventListener("load", () => {
  if (window.__DASHBOARD_PRIMARY_SCRIPT__ === "app_lf") {
    return;
  }
  initEventListeners();
  initBotModalListeners();
  initSelectAllOnClick();
  restoreSoundPreference();
  initAutoStopPreference();
  refreshAll();
  startLiveTimer();
  setInterval(refreshPnlQuick, 3000);
  setInterval(refreshAll, 10000);

  // Keep title updated even when tab is not focused
  // Refresh immediately when tab becomes visible to show fresh data
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshPnlQuick();
    }
  });

  // Use Web Worker for background refresh to keep title accurate
  // This runs even when tab is not focused
  if (window.Worker) {
    const workerCode = `
      setInterval(() => {
        postMessage('tick');
      }, 3000);
    `;
    const blob = new Blob([workerCode], { type: 'application/javascript' });
    const worker = new Worker(URL.createObjectURL(blob));
    worker.onmessage = () => {
      // Trigger refresh on each tick from worker
      if (document.visibilityState === "hidden") {
        // Fetch summary data to update title even when tab is hidden
        fetch('/api/summary', { credentials: 'same-origin' })
          .then(r => r.json())
          .then(data => {
            const unrealized = parseFloat(data.account?.unrealized_pnl || 0);
            updatePageTitle(unrealized);
          })
          .catch(() => { });
      }
    };
  }
});

// Initialize auto-stop on direction change preference
function initAutoStopPreference() {
  const checkbox = $("auto-stop-direction");
  if (checkbox) {
    // Restore from localStorage
    const saved = localStorage.getItem("autoStopOnDirectionChange");
    checkbox.checked = saved === "true";

    // Save on change
    checkbox.addEventListener("change", () => {
      localStorage.setItem("autoStopOnDirectionChange", checkbox.checked);
      if (checkbox.checked) {
        // Clear previous states when enabling to prevent immediate triggers
        previousValues.botMarketStates = {};
      }
    });
  }
}

// ============================================================
// Flash Crash Protection Banner (Smart Feature #12)
// ============================================================

async function checkFlashCrashStatus() {
  try {
    const response = await fetch("/api/flash-crash-status");
    if (!response.ok) return;

    const data = await response.json();
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

if (window.__DASHBOARD_PRIMARY_SCRIPT__ !== "app_lf") {
  // Poll flash crash status every 10 seconds (same as refreshAll)
  setInterval(checkFlashCrashStatus, 10000);

  // Initial check on page load
  setTimeout(checkFlashCrashStatus, 1000);
}

// =============================================================================
// Quick Edit Functions for TP% and Auto Stop
// =============================================================================

function showQuickEdit(botId, settings) {
  const panel = document.getElementById('quick-edit-panel');
  const backdrop = document.getElementById('quick-edit-backdrop');

  document.getElementById('quick-edit-bot-id').value = botId;
  document.getElementById('quick-edit-tp').value =
    settings.tp_pct ? (settings.tp_pct * 100).toFixed(1) : '';
  document.getElementById('quick-edit-autostop').value =
    settings.auto_stop || '';
  document.getElementById('quick-edit-balance-target').value =
    settings.auto_stop_target_usdt || '';

  // Position in center of screen
  panel.style.top = '50%';
  panel.style.left = '50%';
  panel.style.transform = 'translate(-50%, -50%)';

  panel.classList.remove('hidden');
  backdrop.classList.remove('hidden');

  // Focus on first input
  document.getElementById('quick-edit-tp').focus();
}

function hideQuickEdit() {
  document.getElementById('quick-edit-panel').classList.add('hidden');
  document.getElementById('quick-edit-backdrop').classList.add('hidden');
}

async function saveQuickEdit() {
  const botId = document.getElementById('quick-edit-bot-id').value;
  const tpVal = document.getElementById('quick-edit-tp').value.trim();
  const asVal = document.getElementById('quick-edit-autostop').value.trim();
  const btVal = document.getElementById('quick-edit-balance-target').value.trim();

  const payload = {
    tp_pct: tpVal === '' ? null : parseFloat(tpVal) / 100,
    auto_stop: asVal === '' ? null : parseFloat(asVal),
    auto_stop_target_usdt: btVal === '' ? 0 : parseFloat(btVal)
  };

  try {
    const resp = await fetchJSON(`/bots/${botId}/quick-update`, {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    hideQuickEdit();

    // Show success feedback
    console.log(`Bot ${botId} quick-updated:`, payload);

    // Refresh bot list to show updated values
    refreshBots();

  } catch (err) {
    alert('Failed to update: ' + (err.message || err));
  }
}

// Close quick edit on Escape key
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    const panel = document.getElementById('quick-edit-panel');
    if (panel && !panel.classList.contains('hidden')) {
      hideQuickEdit();
    }
  }
});

// =============================================================================
// Profitable Trades Statistics (Bybit-style)
// =============================================================================

let currentStatsPeriod = 'all';

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

function updateTradeStatsDisplay(stats) {
  // Win Rate
  const winRateEl = document.getElementById('stats-win-rate');
  if (winRateEl) {
    winRateEl.textContent = `${stats.win_rate}%`;
    winRateEl.className = 'text-xl font-bold ' + (stats.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400');
  }

  // Wins / Losses
  const winsEl = document.getElementById('stats-wins');
  const lossesEl = document.getElementById('stats-losses');
  if (winsEl) winsEl.textContent = stats.wins;
  if (lossesEl) lossesEl.textContent = stats.losses;

  // Total Trades
  const totalTradesEl = document.getElementById('stats-total-trades');
  if (totalTradesEl) totalTradesEl.textContent = stats.total_trades;

  // Net PnL
  const netPnlEl = document.getElementById('stats-net-pnl');
  if (netPnlEl) {
    const netPnl = stats.net_pnl;
    netPnlEl.textContent = `$${netPnl >= 0 ? '' : ''}${netPnl.toFixed(2)}`;
    netPnlEl.className = 'text-xl font-bold ' + (netPnl >= 0 ? 'text-emerald-400' : 'text-red-400');
  }

  // Profit Factor
  const pfEl = document.getElementById('stats-profit-factor');
  if (pfEl) {
    pfEl.textContent = stats.profit_factor === '∞' ? '∞' : stats.profit_factor;
  }

  // Total Profit
  const totalProfitEl = document.getElementById('stats-total-profit');
  if (totalProfitEl) totalProfitEl.textContent = `$${stats.total_profit.toFixed(2)}`;

  // Total Loss
  const totalLossEl = document.getElementById('stats-total-loss');
  if (totalLossEl) totalLossEl.textContent = `-$${stats.total_loss.toFixed(2)}`;

  // Average Win/Loss
  const avgWinEl = document.getElementById('stats-avg-win');
  const avgLossEl = document.getElementById('stats-avg-loss');
  if (avgWinEl) avgWinEl.textContent = `$${stats.avg_win.toFixed(4)}`;
  if (avgLossEl) avgLossEl.textContent = `-$${stats.avg_loss.toFixed(4)}`;

  // Largest Win/Loss
  const largestWinEl = document.getElementById('stats-largest-win');
  const largestLossEl = document.getElementById('stats-largest-loss');
  if (largestWinEl) largestWinEl.textContent = `$${stats.largest_win.toFixed(4)}`;
  if (largestLossEl) largestLossEl.textContent = `-$${stats.largest_loss.toFixed(4)}`;

  // Win/Loss Bar
  const winBar = document.getElementById('stats-win-bar');
  const lossBar = document.getElementById('stats-loss-bar');
  if (winBar && lossBar) {
    const total = stats.wins + stats.losses;
    if (total > 0) {
      const winPct = (stats.wins / total) * 100;
      const lossPct = (stats.losses / total) * 100;
      winBar.style.width = `${winPct}%`;
      lossBar.style.width = `${lossPct}%`;
    } else {
      winBar.style.width = '50%';
      lossBar.style.width = '50%';
    }
  }
}

if (window.__DASHBOARD_PRIMARY_SCRIPT__ !== "app_lf") {
  // Load trade stats on page load and refresh periodically
  setTimeout(() => loadTradeStats('all'), 500);
  setInterval(() => loadTradeStats(currentStatsPeriod), 30000); // Refresh every 30 seconds
}

/**
 * Refresh logs in Bot Detail Modal
 */
async function refreshBotDetailLogs() {
  if (!window.currentDetailBotId) return;
  const box = $("botDetailLogsBox");
  if (!box) return;

  try {
    const res = await fetch(`/api/bots/${window.currentDetailBotId}/logs?limit=100&_ts=${Date.now()}`, { cache: "no-store" });
    const data = await res.json();

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

// Grid Visualization Chart instance
let gridVizChart = null;

/**
 * Refresh Grid Visualization in Bot Detail Modal
 */
async function refreshGridVisualization() {
  if (!window.currentDetailBotId) return;

  const loading = document.getElementById("gridVizLoading");
  const canvas = document.getElementById("gridVizCanvas");
  if (!canvas) return;

  if (loading) loading.style.display = "flex";

  try {
    const res = await fetch(`/api/bots/${window.currentDetailBotId}/grid`);
    const data = await res.json();

    if (!data.grid_levels || data.grid_levels.length === 0) {
      if (loading) loading.innerHTML = '<span class="text-slate-400">No grid data available</span>';
      return;
    }

    // Prepare chart data
    const gridLevels = data.grid_levels;
    const currentPrice = data.current_price || 0;
    const orders = data.orders || [];
    const position = data.position;

    // Create price labels (sorted high to low for display)
    const allPrices = [...gridLevels];
    if (currentPrice > 0) allPrices.push(currentPrice);
    if (position && position.entry_price > 0) allPrices.push(position.entry_price);

    // De-duplicate and sort
    const uniquePrices = Array.from(new Set(allPrices)).sort((a, b) => b - a);

    const labels = uniquePrices.map(p => p.toFixed(4));

    // Order matching logic: map order prices to the closest label in uniquePrices
    const buyOrderPrices = orders.filter(o => o.side === "Buy").map(o => o.price);
    const sellOrderPrices = orders.filter(o => o.side === "Sell").map(o => o.price);

    const gridData = uniquePrices.map(p => gridLevels.includes(p) ? 100 : 0);
    const buyData = uniquePrices.map(p => buyOrderPrices.some(op => Math.abs(op - p) < p * 0.00001) ? 100 : 0);
    const sellData = uniquePrices.map(p => sellOrderPrices.some(op => Math.abs(op - p) < p * 0.00001) ? 100 : 0);
    const currentData = uniquePrices.map(p => p === currentPrice ? 100 : 0);
    const entryData = position && position.entry_price > 0
      ? uniquePrices.map(p => p === position.entry_price ? 100 : 0)
      : uniquePrices.map(() => 0);

    if (gridVizChart) gridVizChart.destroy();

    const ctx = canvas.getContext("2d");
    gridVizChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          { label: "Price", data: currentData, backgroundColor: "rgba(251,191,36,1.0)", borderColor: "#fbbf24", borderWidth: 3, barThickness: 6 },
          { label: "Entry", data: entryData, backgroundColor: "rgba(34,211,238,1.0)", borderColor: "#22d3ee", borderWidth: 2, barThickness: 5 },
          { label: "Buy", data: buyData, backgroundColor: "rgba(16,185,129,1.0)", borderColor: "#10b981", borderWidth: 1, barThickness: 4 },
          { label: "Sell", data: sellData, backgroundColor: "rgba(239,68,68,1.0)", borderColor: "#ef4444", borderWidth: 1, barThickness: 4 },
          { label: "Grid", data: gridData, backgroundColor: "rgba(100,116,139,0.3)", borderColor: "rgba(100,116,139,0.4)", borderWidth: 1, barThickness: 2 },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => ctx.raw === 0 ? null : ctx.dataset.label } }
        },
        scales: {
          x: { display: false, max: 100 },
          y: {
            grid: { color: "rgba(100,116,139,0.1)" },
            ticks: {
              color: (c) => {
                const p = uniquePrices[c.index];
                if (p === currentPrice) return "#fbbf24";
                if (position && p === position.entry_price) return "#22d3ee";
                if (buyOrderPrices.includes(p)) return "#10b981";
                if (sellOrderPrices.includes(p)) return "#ef4444";
                return "#94a3b8";
              },
              font: (c) => {
                const p = uniquePrices[c.index];
                const isSpecial = p === currentPrice || (position && p === position.entry_price);
                return { size: isSpecial ? 11 : 9, weight: isSpecial ? "bold" : "normal" };
              }
            }
          }
        }
      }
    });

    if (loading) loading.style.display = "none";
  } catch (err) {
    console.error("Grid viz error:", err);
    if (loading) loading.innerHTML = `<span class="text-red-400">Error: ${err.message}</span>`;
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
  const gridCount = parseInt(document.getElementById("bot-grid-count")?.value || 10, 10);
  const investment = parseFloat(document.getElementById("bot-investment")?.value || 100);
  const leverage = parseFloat(document.getElementById("bot-leverage")?.value || 5);
  const mode = document.getElementById("bot-mode")?.value || "neutral_classic";
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
    const res = await fetch(`${API_BASE}/backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

    const data = await res.json();

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

function showBacktestResultsModal(data) {
  // Remove existing modal if any
  const existingModal = document.getElementById("backtest-results-modal");
  if (existingModal) existingModal.remove();

  const modal = document.createElement("div");
  modal.id = "backtest-results-modal";
  modal.className = "fixed inset-0 bg-black/70 flex items-center justify-center z-50";

  // Real simulation data
  const profit = data.profit?.toFixed(2) || "N/A";
  const roi = data.roi_pct?.toFixed(2) || "N/A";
  const maxDD = data.max_drawdown_pct?.toFixed(2) || "N/A";
  const trades = data.trades_count || "N/A";
  const finalEquity = data.final_equity?.toFixed(2) || "N/A";
  const daysSimulated = data.days_simulated || 3;
  const candlesUsed = data.candles_used || "N/A";
  const simTime = data.simulation_time_sec?.toFixed(1) || "N/A";
  const isRealSim = data.is_real_simulation === true;

  const modeLabel = data.mode?.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) || "Unknown";
  const rangeModeLabel = data.range_mode?.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) || "Fixed";

  const profitColor = parseFloat(profit) >= 0 ? "text-emerald-400" : "text-red-400";
  const roiColor = parseFloat(roi) >= 0 ? "text-emerald-400" : "text-red-400";

  modal.innerHTML = `
    <div class="bg-slate-800 rounded-xl border border-slate-700 p-6 max-w-md w-full mx-4">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold text-white">📊 Real Backtest Results</h3>
        <button onclick="document.getElementById('backtest-results-modal').remove()" 
          class="text-slate-400 hover:text-white text-xl">&times;</button>
      </div>
      
      ${isRealSim ? '<div class="bg-emerald-900/30 border border-emerald-700 rounded px-3 py-2 mb-4 text-xs text-emerald-300">✅ Real historical simulation (not estimate)</div>' : ''}
      
      <div class="space-y-3 text-sm">
        <div class="flex justify-between">
          <span class="text-slate-400">Symbol:</span>
          <span class="text-white font-medium">${data.symbol || "N/A"}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">Mode:</span>
          <span class="text-purple-400">${modeLabel}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">Range Mode:</span>
          <span class="text-blue-400">${rangeModeLabel}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-slate-400">Range:</span>
          <span class="text-white">${data.lower_price?.toFixed(6) || "N/A"} - ${data.upper_price?.toFixed(6) || "N/A"}</span>
        </div>
        
        <div class="border-t border-slate-700 pt-3">
          <div class="flex justify-between">
            <span class="text-slate-400">Days Simulated:</span>
            <span class="text-white">${daysSimulated} days (${candlesUsed} candles)</span>
          </div>
        </div>
        
        <div class="bg-slate-900/50 rounded-lg p-3 space-y-2">
          <div class="flex justify-between">
            <span class="text-slate-400">Final Equity:</span>
            <span class="text-white font-bold">$${finalEquity}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Profit/Loss:</span>
            <span class="${profitColor} font-bold">$${profit}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">ROI:</span>
            <span class="${roiColor} font-bold">${roi}%</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Max Drawdown:</span>
            <span class="text-orange-400">${maxDD}%</span>
          </div>
          <div class="flex justify-between">
            <span class="text-slate-400">Total Trades:</span>
            <span class="text-white">${trades}</span>
          </div>
        </div>
      </div>
      
      <div class="mt-4 pt-4 border-t border-slate-700 text-xs text-slate-500">
        Simulation time: ${simTime}s | Uses 15-min candles
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });
}


// =============================================================================
// ASSET TRANSFER MODAL LOGIC (User Story 1 & 2)
// =============================================================================

function openTransferModal() {
  const modal = $("transferModal");
  if (!modal) return;

  // Set default max based on source
  updateTransferMaxDisplay();

  modal.classList.remove("hidden");
}

function closeTransferModal() {
  const modal = $("transferModal");
  if (modal) modal.classList.add("hidden");

  // Reset form
  $("transfer-amount").value = "";
  resetTransferBtn();
}

function swapTransferDirection() {
  const fromSelect = $("transfer-from");
  const toSelect = $("transfer-to");
  const temp = fromSelect.value;
  fromSelect.value = toSelect.value;
  toSelect.value = temp;

  updateTransferMaxDisplay();
}

function updateTransferMaxDisplay() {
  const fromAccount = $("transfer-from").value;
  const maxEl = $("transfer-max-amount");
  if (!maxEl) return;

  const balance = fromAccount === "UNIFIED" ? (window._currentUnifiedBalance || 0) : (window._currentFundingBalance || 0);
  console.log(`[Transfer] From: ${fromAccount}, Balance: ${balance}, Global Unified: ${window._currentUnifiedBalance}, Global Funding: ${window._currentFundingBalance}`);
  maxEl.textContent = formatNumber(balance, 2);
}

function setMaxTransferAmount() {
  const fromAccount = $("transfer-from").value;
  const balance = fromAccount === "UNIFIED" ? (window._currentUnifiedBalance || 0) : (window._currentFundingBalance || 0);
  $("transfer-amount").value = balance.toFixed(2);
}

async function submitTransfer() {
  const amount = parseFloat($("transfer-amount").value);
  const coin = $("transfer-coin").value;
  const fromType = $("transfer-from").value;
  const toType = $("transfer-to").value;

  if (isNaN(amount) || amount <= 0) {
    showToast("Please enter a valid amount", "error");
    return;
  }

  // Start loading state
  setTransferLoading(true);

  try {
    const result = await fetchJSON("/transfer", {
      method: "POST",
      body: JSON.stringify({
        amount: amount,
        coin: coin,
        from_type: fromType,
        to_type: toType
      })
    });

    if (result.success) {
      showToast(`Successfully transferred ${amount} ${coin}`, "success");
      closeTransferModal();

      // Trigger balance refresh
      setTimeout(refreshSummary, 1000);
      setTimeout(refreshSummary, 3000); // Second refresh to ensure exchange reflects change
    } else {
      showToast(result.error || "Transfer failed", "error");
    }
  } catch (error) {
    showToast("Network error: " + error.message, "error");
  } finally {
    setTransferLoading(false);
  }
}

function setTransferLoading(isLoading) {
  const btn = $("btn-confirm-transfer");
  const text = $("transfer-btn-text");
  const spinner = $("transfer-spinner");

  if (!btn || !text || !spinner) return;

  btn.disabled = isLoading;
  if (isLoading) {
    text.textContent = "Processing...";
    spinner.classList.remove("hidden");
    btn.classList.add("opacity-75", "cursor-wait");
  } else {
    resetTransferBtn();
  }
}

function resetTransferBtn() {
  const btn = $("btn-confirm-transfer");
  const text = $("transfer-btn-text");
  const spinner = $("transfer-spinner");

  if (!btn || !text || !spinner) return;

  btn.disabled = false;
  text.textContent = "Confirm Transfer";
  spinner.classList.add("hidden");
  btn.classList.remove("opacity-75", "cursor-wait");
}

// Ensure max display updates when from account changes manually
document.addEventListener('DOMContentLoaded', () => {
  if (window.__DASHBOARD_PRIMARY_SCRIPT__ === "app_lf") {
    return;
  }
  const fromSelect = $("transfer-from");
  if (fromSelect) {
    fromSelect.addEventListener('change', updateTransferMaxDisplay);
  }
});
