// AUDIO functions — extracted from app_lf.js
// 29 functions, 546 lines

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

function unlockAudio() {
  if (audioUnlocked) return;
  if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();

  // Just try to resume - if it works, great. If blocked, we'll try again next click.
  if (audioContext.state === 'suspended') {
    audioContext.resume().then(() => {
      audioUnlocked = true;
      console.log('AudioContext resumed successfully');
      // Remove the listeners once unlocked
      document.removeEventListener('click', unlockAudio);
      document.removeEventListener('keydown', unlockAudio);
      document.removeEventListener('touchstart', unlockAudio);
    }).catch(e => {
      // Ignore errors - likely still blocked
    });
  } else if (audioContext.state === 'running') {
    audioUnlocked = true;
  }
}

// Add global listeners to unlock audio on first interaction
document.addEventListener('click', unlockAudio);
document.addEventListener('keydown', unlockAudio);
document.addEventListener('touchstart', unlockAudio);

function initAudio() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  // Try to resume, but suppress error if it fails (browser will block it until gesture)
  if (audioContext.state === 'suspended') {
    audioContext.resume().catch(() => { });
  }
  return audioContext;
}

function playTone(frequency, duration, type = 'sine', volume = 0.3) {
  try {
    if (!audioContext) return;
    const ctx = audioContext;
    if (ctx.state === 'suspended') ctx.resume().catch(() => { });

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
    if (ctx.state === 'suspended') ctx.resume().catch(() => { });
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
    if (ctx.state === 'suspended') ctx.resume().catch(() => { });
    // Satisfying "cha-ching" celebration — clearly distinct from ready ping
    const notes = [523.25, 659.25, 783.99, 1046.50];
    notes.forEach((freq, i) => {
      setTimeout(() => {
        playTone(freq, 0.2, 'sine', 0.22);
        playTone(freq * 2, 0.15, 'sine', 0.12);
      }, i * 70);
    });
    // Cha-ching finish
    setTimeout(() => {
      playTone(1567.98, 0.08, 'square', 0.18);
      playTone(2093.0, 0.06, 'sine', 0.1);
    }, 300);
    setTimeout(() => {
      playTone(2093.0, 0.12, 'square', 0.2);
      playTone(2637.0, 0.08, 'sine', 0.08);
    }, 420);
  } catch (e) { }
  // Trigger celebration animation
  triggerProfitCelebration();
}

function triggerProfitCelebration() {
  try {
    // Confetti burst
    const colors = ['#10b981', '#34d399', '#6ee7b7', '#fbbf24', '#f59e0b'];
    const container = document.body;
    for (let i = 0; i < 20; i++) {
      const piece = document.createElement('div');
      piece.className = 'confetti-piece';
      piece.style.left = `${Math.random() * 100}vw`;
      piece.style.setProperty('--confetti-x', `${(Math.random() - 0.5) * 200}px`);
      piece.style.background = colors[Math.floor(Math.random() * colors.length)];
      piece.style.animationDelay = `${Math.random() * 400}ms`;
      container.appendChild(piece);
      setTimeout(() => piece.remove(), 2000);
    }
    // Floating money symbols
    const symbols = ['💰', '💵', '🤑', '📈', '✨'];
    for (let i = 0; i < 6; i++) {
      const sym = document.createElement('div');
      sym.className = 'profit-rain-symbol';
      sym.textContent = symbols[Math.floor(Math.random() * symbols.length)];
      sym.style.left = `${15 + Math.random() * 70}vw`;
      sym.style.setProperty('--profit-drift-x', `${(Math.random() - 0.5) * 100}px`);
      sym.style.setProperty('--profit-rotate', `${Math.random() * 360}deg`);
      sym.style.setProperty('--profit-duration', `${1800 + Math.random() * 800}ms`);
      sym.style.animationDelay = `${Math.random() * 300}ms`;
      container.appendChild(sym);
      setTimeout(() => sym.remove(), 3000);
    }
    // Flash the summary PnL green
    const todayNet = document.getElementById('summary-today-net');
    if (todayNet) {
      todayNet.style.transition = 'transform 0.3s, text-shadow 0.3s';
      todayNet.style.transform = 'scale(1.3)';
      todayNet.style.textShadow = '0 0 12px rgba(16, 185, 129, 0.8)';
      setTimeout(() => {
        todayNet.style.transform = '';
        todayNet.style.textShadow = '';
      }, 1500);
    }
  } catch (e) { }
}

function playLossSound() {
  if (!soundEnabled) return;
  try {
    const ctx = initAudio();
    if (ctx.state === 'suspended') ctx.resume().catch(() => { });
    const notes = [392.00, 349.23, 293.66];
    notes.forEach((freq, i) => {
      setTimeout(() => playTone(freq, 0.25, 'triangle', 0.25), i * 150);
    });
  } catch (e) { }
}

function playReadyAlertSound() {
  // Gentle double-ping — clearly distinct from profit celebration
  if (!soundEnabled) return;
  try {
    const ctx = initAudio();
    if (ctx.state === "suspended") ctx.resume().catch(() => { });
    playTone(440, 0.12, "sine", 0.12);
    setTimeout(() => playTone(554, 0.12, "sine", 0.12), 120);
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

// let lastUpdateTime = null;  // Defined in app_v5.js

function $(id) { return document.getElementById(id); }

function sortBotsForDisplay(bots) {
  return (bots || [])
    .map((bot, index) => ({ bot, index }))
    .sort((a, b) => {
      const autoPilotDiff = Number(Boolean(b.bot?.auto_pilot)) - Number(Boolean(a.bot?.auto_pilot));
      if (autoPilotDiff !== 0) return autoPilotDiff;
      const aBucket = getActiveBotDisplayBucket(a.bot?.status, a.bot?._active_bots_ready_cat);
      const bBucket = getActiveBotDisplayBucket(b.bot?.status, b.bot?._active_bots_ready_cat);
      const aChangedAt = Number(a.bot?._active_bots_category_changed_at || 0);
      const bChangedAt = Number(b.bot?._active_bots_category_changed_at || 0);
      const aShouldSink = (aBucket === "watch" || aBucket === "blocked") && aChangedAt > 0;
      const bShouldSink = (bBucket === "watch" || bBucket === "blocked") && bChangedAt > 0;
      if (aShouldSink !== bShouldSink) return Number(aShouldSink) - Number(bShouldSink);
      if (aShouldSink && bShouldSink) {
        const sinkDiff = aChangedAt - bChangedAt;
        if (sinkDiff !== 0) return sinkDiff;
      }
      const categoryChangeDiff = bChangedAt - aChangedAt;
      if (categoryChangeDiff !== 0) return categoryChangeDiff;
      // Within stopped bots, sort by most recently run first
      const aStatus = String(a.bot?.status || "").toLowerCase();
      const bStatus = String(b.bot?.status || "").toLowerCase();
      if (aStatus === "stopped" && bStatus === "stopped") {
        const aRunAt = Date.parse(a.bot?.last_run_at || "") || 0;
        const bRunAt = Date.parse(b.bot?.last_run_at || "") || 0;
        if (aRunAt !== bRunAt) return bRunAt - aRunAt;
      }
      return a.index - b.index;
    })
    .map(({ bot }) => bot);
}

function toggleConfetti() {
  const prefs = ensureDashboardUiPrefs();
  prefs.confetti = !prefs.confetti;
  saveDashboardUiPrefs();
  showToast(`Confetti ${prefs.confetti ? "enabled" : "disabled"}`, "info");
}

function toggleProfitRain() {
  const prefs = ensureDashboardUiPrefs();
  if (prefersReducedMotion()) {
    showToast("Profit FX stays off while reduced motion is enabled", "info");
    updateDashboardPreferenceButtons();
    return;
  }
  prefs.profitRain = !prefs.profitRain;
  saveDashboardUiPrefs();
  showToast(`Profit FX ${prefs.profitRain ? "enabled" : "disabled"}`, "info");
}

function updateProfitRainThreshold(value) {
  const prefs = ensureDashboardUiPrefs();
  const parsed = Number(value);
  prefs.profitRainMinPnl = Number.isFinite(parsed) && parsed > 0 ? parsed : 3;
  saveDashboardUiPrefs();
}

function eventToneTagClass(tone) {
  const classes = {
    profit: "bg-emerald-500/15 text-emerald-300",
    loss: "bg-red-500/15 text-red-300",
    warning: "bg-amber-500/15 text-amber-300",
    danger: "bg-rose-500/15 text-rose-200",
    autopilot: "bg-cyan-500/15 text-cyan-200",
    info: "bg-slate-800 text-slate-300",
  };
  return classes[tone] || classes.info;
}

function getActiveBotDisplayBucket(status, readyCat) {
  return doesActiveBotMatchFilterState(status, readyCat, "running")
    ? "running"
    : String(readyCat || "other").trim().toLowerCase();
}

function getActiveBotRowDisplayStyle(bot) {
  // Always keep rows visible during pending lifecycle actions (pause/stop/start/resume)
  // to prevent jarring disappear-reappear flicker
  if (bot?.id && pendingBotActions[bot.id]) return "";
  const readyCat = String(bot?._active_bots_ready_cat || getBaseActiveBotReadyCategory(bot)).trim().toLowerCase();
  const matchFilter = doesActiveBotMatchFilterState(bot?.status, readyCat, activeBotFilter, bot?.id);
  const matchSearch = !activeBotSearchQuery ||
    String(bot?.symbol || "").toUpperCase().includes(activeBotSearchQuery) ||
    String(bot?.id || "").toUpperCase().includes(activeBotSearchQuery);
  const visible = activeBotSearchQuery ? matchSearch : (matchFilter && matchSearch);
  return visible ? "" : ' style="display: none;"';
}

function getActiveBotRowDisplayValue(bot) {
  // getActiveBotRowDisplayStyle returns "" when visible, or ' style="display: none;"' when hidden
  return getActiveBotRowDisplayStyle(bot) ? "none" : "";
}

function setElementDisplayIfChanged(element, displayValue) {
  if (!element || !element.style) return false;
  const nextDisplay = String(displayValue || "");
  if (String(element.style.display || "") === nextDisplay) return false;
  element.style.display = nextDisplay;
  return true;
}

function _scoreDisplay(bot) {
  const setup = getSetupReadiness(bot);
  const score = setup.score;
  if (score === null || score === undefined || !Number.isFinite(score)) return "-";
  return score.toFixed(0);
}

function _bandDisplay(bot) {
  const setup = getSetupReadiness(bot);
  const score = setup.score;
  if (score === null || score === undefined || !Number.isFinite(score)) return "";
  if (score >= 72) return "Strong";
  if (score >= 60) return "Good";
  if (score >= 50) return "Caution";
  return "Poor";
}

function maybeTriggerConfetti() {
  const prefs = ensureDashboardUiPrefs();
  if (!prefs.confetti || prefersReducedMotion()) return;

  const layer = $("celebration-layer");
  if (!layer) return;

  for (let index = 0; index < 18; index += 1) {
    const piece = document.createElement("span");
    piece.className = "confetti-piece";
    piece.style.left = `${48 + Math.random() * 14}%`;
    piece.style.background = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
    piece.style.setProperty("--confetti-x", `${(Math.random() - 0.5) * 240}px`);
    piece.style.animationDelay = `${Math.random() * 120}ms`;
    layer.appendChild(piece);
    window.setTimeout(() => piece.remove(), 1800);
  }
}

function maybeTriggerProfitRain(amount = 0) {
  const prefs = ensureDashboardUiPrefs();
  const numericAmount = Number(amount || 0);
  if (!prefs.profitRain || prefersReducedMotion()) return;
  if (!Number.isFinite(numericAmount) || numericAmount < Number(prefs.profitRainMinPnl || 3)) return;
  if ((Date.now() - dashboardFeedState.lastProfitRainAt) < PROFIT_RAIN_COOLDOWN_MS) return;

  const layer = $("profit-rain-layer");
  if (!layer) return;

  dashboardFeedState.lastProfitRainAt = Date.now();
  const burstCount = Math.max(8, Math.min(20, Math.round(8 + (numericAmount / 2.5))));
  const fragment = document.createDocumentFragment();

  for (let index = 0; index < burstCount; index += 1) {
    const piece = document.createElement("span");
    const size = 18 + Math.random() * 16;
    piece.className = "profit-rain-symbol";
    piece.textContent = "$";
    piece.style.left = `${8 + Math.random() * 84}%`;
    piece.style.setProperty("--profit-size", `${size.toFixed(1)}px`);
    piece.style.setProperty("--profit-drift-x", `${((Math.random() - 0.5) * 120).toFixed(1)}px`);
    piece.style.setProperty("--profit-rotate", `${((Math.random() - 0.5) * 50).toFixed(1)}deg`);
    piece.style.setProperty("--profit-duration", `${1800 + Math.random() * 700}ms`);
    piece.style.animationDelay = `${Math.random() * 220}ms`;
    fragment.appendChild(piece);
    window.setTimeout(() => piece.remove(), 2900);
  }

  layer.appendChild(fragment);
}

function showMilestoneBanner(text, tone = "profit") {
  const banner = $("milestone-banner");
  const textEl = $("milestone-banner-text");
  if (!banner || !textEl) return;

  textEl.textContent = text;
  banner.classList.remove("hidden");
  banner.classList.remove("border-red-500/30", "bg-red-500/10");

  if (tone === "loss" || tone === "danger") {
    banner.classList.add("border-red-500/30", "bg-red-500/10");
  }

  if (dashboardFeedState.milestoneTimeout) {
    clearTimeout(dashboardFeedState.milestoneTimeout);
  }

  dashboardFeedState.milestoneTimeout = window.setTimeout(() => {
    banner.classList.add("hidden");
    banner.classList.remove("border-red-500/30", "bg-red-500/10");
  }, 9000);
}

function maybeEmitDailyMilestone(todayNet) {
  const current = Number(todayNet || 0);
  if (dashboardFeedState.lastTodayNet === null) {
    dashboardFeedState.lastTodayNet = current;
    return;
  }

  const prev = dashboardFeedState.lastTodayNet;
  const positiveThresholds = [10, 25, 50, 100];
  const negativeThresholds = [-10, -25, -50, -100];

  positiveThresholds.forEach((threshold) => {
    const key = `daily:${threshold}`;
    if (prev < threshold && current >= threshold && dashboardFeedState.lastMilestoneKey !== key) {
      dashboardFeedState.lastMilestoneKey = key;
      appendActivityEvent({
        key,
        category: "profit",
        tone: "profit",
        icon: "🏁",
        message: `Daily realized PnL crossed +$${threshold.toFixed(0)}`,
        meta: "Daily Milestone",
        toast: true,
        notify: true,
        confetti: threshold >= 25,
        bannerText: `Daily realized PnL crossed +$${threshold.toFixed(0)}`,
      });
    }
  });

  negativeThresholds.forEach((threshold) => {
    const key = `daily:${threshold}`;
    if (prev > threshold && current <= threshold && dashboardFeedState.lastMilestoneKey !== key) {
      dashboardFeedState.lastMilestoneKey = key;
      appendActivityEvent({
        key,
        category: "loss",
        tone: "loss",
        icon: "⚠️",
        message: `Daily realized PnL crossed ${threshold.toFixed(0)}`,
        meta: "Daily Drawdown",
        toast: true,
        notify: true,
        bannerText: `Daily realized PnL crossed ${threshold.toFixed(0)}`,
      });
    }
  });

  dashboardFeedState.lastTodayNet = current;
}

function inferPriceDisplayDecimals(value) {
  const numeric = Math.abs(Number(value || 0));
  if (!isFinite(numeric) || numeric === 0) return 2;
  if (numeric >= 1000) return 2;
  if (numeric >= 100) return 2;
  if (numeric >= 1) return 3;
  if (numeric >= 0.1) return 4;
  if (numeric >= 0.01) return 5;
  return 8;
}

function formatPriceForBotFormDisplay(value, tickSizeRaw = "") {
  const numeric = Number(value);
  if (!isFinite(numeric)) return "";
  if (tickSizeRaw) return formatPriceForBybitInput(numeric, tickSizeRaw);
  return numeric.toFixed(inferPriceDisplayDecimals(numeric)).replace(/\.?0+$/, "");
}

function setRunnerStatusDisplay({
  badgeText,
  badgeClass,
  dotClass,
  dotTitle,
  textValue,
  textClass,
}) {
  const badge = $("runnerStatusBadge");
  const dot = $("runnerStatusDot");
  const text = $("runnerStatusText");

  if (badge) {
    badge.textContent = badgeText;
    badge.className = badgeClass;
  }
  if (dot) {
    dot.className = dotClass;
    dot.title = dotTitle;
  }
  if (text) {
    text.textContent = textValue;
    text.className = textClass;
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
    netPnlEl.textContent = `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}`;
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

// Note: Trade stats polling is started inside window.load to ensure DOM is ready

// BOT_CARD functions — extracted from app_lf.js
// 84 functions, 3230 lines
// Loaded before app_lf.js via <script> tag

function renderPresetContext(scope = "main", bot = null) {
  const heading = scope === "quick" ? $("quick-preset-context-title") : $("bot-preset-heading");
  const subtitle = scope === "quick" ? $("quick-preset-context-summary") : $("bot-preset-subtitle");
  const note = scope === "quick" ? $("quick-preset-context-note") : $("bot-preset-summary-reason");
  if (!heading || !subtitle || !note) return;

  const isExisting = !!(bot && bot.id);
  if (!isExisting && scope === "main") {
    heading.textContent = "New Bot Presets";
    subtitle.textContent = "Creation-time defaults only. Values stay editable before save.";
    return;
  }

  const context = getPresetContextBits(bot);
  heading.textContent = scope === "quick" ? context.title : "Preset Context";
  subtitle.textContent = context.summary;
  note.textContent = context.note;
}

function renderModeSemanticsPanel(scope = "main", bot = null) {
  const summaryEl = getScopedElement(scope, "bot-mode-runtime-summary");
  const comparisonEl = getScopedElement(scope, "bot-mode-runtime-comparison");
  if (!summaryEl || !comparisonEl) return;

  const context = buildModeSemanticsContextFromInputs(scope, bot);
  const configuredMode = formatBotModeLabel(getConfiguredModeForUi(context));
  const configuredRange = formatRangeModeLabel(getConfiguredRangeModeForUi(context));
  const effectiveMode = formatBotModeLabel(getEffectiveRuntimeModeForUi(context));
  const effectiveRange = formatRangeModeLabel(getEffectiveRuntimeRangeModeForUi(context));
  const modePolicy = formatModePolicyLabel(context?.mode_policy);
  const runtimeSource = String(context?.runtime_mode_source || "").trim();
  const differs = getConfiguredModeForUi(context) !== getEffectiveRuntimeModeForUi(context)
    || getConfiguredRangeModeForUi(context) !== getEffectiveRuntimeRangeModeForUi(context);

  summaryEl.textContent = `Configured ${configuredMode} / ${configuredRange} • Policy ${modePolicy}`;
  comparisonEl.textContent = differs
    ? `Runtime View: ${effectiveMode} / ${effectiveRange}${runtimeSource ? ` via ${humanizeReason(runtimeSource)}` : ""}. Runtime suggestion only; saved mode unchanged.`
    : "Runtime suggestion only; saved mode unchanged.";
}

function renderQuickFormLimitations() {
  const noteEl = $("quick-form-limitation-note");
  if (!noteEl) return;
  const omitted = getBotFormSurfaceOmittedFieldLabels("quick");
  noteEl.textContent = omitted.length
    ? `Quick config uses the canonical bot fields for high-frequency edits. Full form only: ${omitted.join(", ")}.`
    : "Quick config uses the live dashboard bot fields and saves through the same backend bot update path.";
}

function statusBadge(status) {
  const badges = {
    running: "bg-emerald-500/20 text-emerald-400",
    paused: "bg-amber-500/20 text-amber-400",
    flash_crash_paused: "bg-orange-500/20 text-orange-300",
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

function upnlSlBadges(bot) {
  if (!bot.upnl_stoploss_enabled) return "";

  // Single badge — show most critical state only: hard > soft > cooldown > idle
  if (bot.status === "risk_stopped" && bot.upnl_stoploss_reason) {
    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-600/30 text-red-400" title="${bot.upnl_stoploss_reason}">🛑 HARD SL</span>`;
  }
  if (bot.upnl_stoploss_active) {
    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-orange-600/30 text-orange-400" title="Soft SL active - opening orders blocked">⚠️ SOFT SL</span>`;
  }
  if (bot.upnl_stoploss_in_cooldown && bot.upnl_stoploss_cooldown_until) {
    const cooldownEnd = new Date(bot.upnl_stoploss_cooldown_until);
    const now = new Date();
    const remainingSec = Math.max(0, Math.floor((cooldownEnd - now) / 1000));
    const mins = Math.floor(remainingSec / 60);
    const secs = remainingSec % 60;
    const timeStr = mins > 0 ? `${mins}m${secs}s` : `${secs}s`;
    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-600/30 text-blue-400" title="Cooldown until ${cooldownEnd.toLocaleTimeString()}">⏳ ${timeStr}</span>`;
  }
  if (bot.upnl_stoploss_trigger_count > 0) {
    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-600/30 text-slate-400" title="Times UPnL SL triggered">🛡️×${bot.upnl_stoploss_trigger_count}</span>`;
  }

  const soft = bot.effective_upnl_soft || "-12";
  const hard = bot.effective_upnl_hard || "-18";
  return `<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700/50 text-slate-500" title="UPnL SL enabled: Soft ${soft}% / Hard ${hard}%">🛡️</span>`;
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

function scalpOpeningCapHint(bot) {
  const mode = (bot.mode || "").toLowerCase();
  if (mode !== "scalp_pnl" && mode !== "scalp_market") return "";

  const configuredGridCount = getConfiguredGridCount(bot);
  const effectiveCap = parseInt(bot.effective_opening_order_cap, 10) || 0;
  const entryOrdersOpen = parseInt(bot.entry_orders_open, 10) || 0;
  const reason = bot.effective_opening_order_cap_reason || "";

  if (!(configuredGridCount > 0) || !(effectiveCap > 0)) return "";
  if (effectiveCap >= configuredGridCount && entryOrdersOpen <= 0) return "";

  const reasonLabel = reason ? ` (${String(reason).replace(/_/g, " ")})` : "";
  return `<span class="text-[9px] sm:text-[10px] text-slate-500" title="Live scalp opening orders ${entryOrdersOpen}/${effectiveCap} out of configured ${configuredGridCount}${reasonLabel}">live ${entryOrdersOpen}/${effectiveCap}</span>`;
}

function scannerRecommendationHint(bot) {
  const recMode = String(bot?.scanner_recommended_mode || "").trim();
  if (!recMode) return "";

  const recRangeMode = String(bot?.scanner_recommended_range_mode || "").trim();
  const recProfile = String(bot?.scanner_recommended_profile || "").trim();
  const regime = String(bot?.scanner_recommendation_regime || "").trim();
  const trend = String(bot?.scanner_recommendation_trend || "").trim();
  const differs = Boolean(bot?.scanner_recommendation_differs);
  const recLabel = recRangeMode ? `${recMode}/${recRangeMode}` : recMode;
  const cls = differs ? "text-amber-300" : "text-slate-500";
  const prefix = differs ? "rec→" : "rec:";
  const titleParts = [
    `Neutral Scanner recommends ${recLabel}`,
    recProfile ? `profile ${recProfile}` : "",
    regime ? `regime ${regime}` : "",
    trend ? `trend ${trend}` : "",
  ].filter(Boolean);

  return `<div class="text-[9px] sm:text-[10px] ${cls} mt-0.5" title="${titleParts.join(" • ")}">${prefix} ${recLabel}</div>`;
}

function priceActionHint(bot) {
  const summary = String(bot?.price_action_summary || "").trim();
  if (!summary) return "";

  const direction = String(bot?.price_action_direction || "neutral").toLowerCase();
  const fitScoreRaw = Number(bot?.price_action_mode_fit_score);
  const fitScore = Number.isFinite(fitScoreRaw) ? fitScoreRaw : null;
  const fitSummary = String(bot?.price_action_mode_fit_summary || "").trim();
  const toneClass =
    direction === "bullish"
      ? "text-emerald-300"
      : direction === "bearish"
        ? "text-rose-300"
        : "text-slate-500";
  const prefix = fitScore === null
    ? "PA"
    : `PA ${fitScore >= 0 ? "+" : ""}${fitScore.toFixed(1)}`;
  const shortSummary = summary.length > 52 ? `${summary.slice(0, 49)}…` : summary;
  const title = [summary, fitSummary].filter(Boolean).join(" • ").replace(/"/g, "&quot;");

  return `<div class="text-[9px] sm:text-[10px] ${toneClass} mt-0.5" title="${title}">${prefix}: ${shortSummary}</div>`;
}

function autoPilotPickHint(bot) {
  if (!bot?.auto_pilot) return "";
  const summary = String(bot?.auto_pilot_last_pick_summary || "").trim();
  if (!summary) return "";

  const scoreRaw = Number(bot?.auto_pilot_last_pick_score);
  const score = Number.isFinite(scoreRaw) ? scoreRaw : null;
  const shortSummary = summary.length > 56 ? `${summary.slice(0, 53)}…` : summary;
  const title = `Last Auto-Pilot pick basis${score === null ? "" : ` (score ${score.toFixed(1)})`}: ${summary}`.replace(/"/g, "&quot;");
  const prefix = score === null ? "pick" : `pick ${score.toFixed(1)}`;

  return `<div class="text-[9px] sm:text-[10px] text-cyan-300 mt-0.5" title="${title}">${prefix}: ${shortSummary}</div>`;
}

function exchangeTruthBadge(bot) {
  const truth = getExchangeTruthState(bot);
  if (!truth.visible || truth.subtle) return "";
  const toneMap = {
    sky: "border-sky-400/30 bg-sky-500/10 text-sky-100",
    blue: "border-blue-400/30 bg-blue-500/10 text-blue-100",
    cyan: "border-cyan-400/30 bg-cyan-500/10 text-cyan-100",
    slate: "border-slate-700 bg-slate-800/70 text-slate-200",
  };
  const titleParts = [
    truth.label,
    truth.detail,
    truth.reconcileStatus ? `Status: ${humanizeReason(truth.reconcileStatus)}` : "",
    truth.mismatches.length ? `Mismatch: ${truth.mismatches.map((item) => humanizeReason(item)).join(", ")}` : "",
    truth.followUpStatus ? `Follow-up: ${humanizeReason(truth.followUpStatus)}` : "",
  ].filter(Boolean);
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium bot-badge--secondary ${toneMap[truth.tone] || toneMap.slate}" title="${escapeHtml(titleParts.join(" • "))}">${escapeHtml(truth.label)}</span>`;
}

function getProfitProtectionMeta(bot) {
  const advisory = bot?.profit_protection_advisory && typeof bot.profit_protection_advisory === "object"
    ? bot.profit_protection_advisory
    : {};
  const shadow = bot?.profit_protection_shadow && typeof bot.profit_protection_shadow === "object"
    ? bot.profit_protection_shadow
    : {};
  const mode = String(bot?.profit_protection_mode || advisory.mode || "").trim().toLowerCase();
  const decision = String(bot?.profit_protection_decision || advisory.decision || "").trim().toLowerCase();
  const reasonFamily = String(
    bot?.profit_protection_reason_family
    || advisory.reason_family
    || ""
  ).trim().toLowerCase();
  const blocked = Boolean(bot?.profit_protection_blocked ?? advisory.blocked);
  const blockedReason = String(
    bot?.profit_protection_blocked_reason
    || advisory.blocked_reason
    || ""
  ).trim().toLowerCase();
  const shadowStatus = String(
    bot?.profit_protection_shadow_status
    || advisory.shadow_status
    || shadow.status
    || ""
  ).trim().toLowerCase();
  const shadowResult = String(advisory.shadow_result || shadow.result || "").trim().toLowerCase();
  const decisionMap = {
    wait: { label: "Wait", shortLabel: "Protect Wait", tone: "slate" },
    watch_closely: { label: "Watch Closely", shortLabel: "Protect Watch", tone: "amber" },
    take_partial: { label: "Take Partial", shortLabel: "Protect Partial", tone: "emerald" },
    exit_now: { label: "Exit Now", shortLabel: "Protect Exit", tone: "rose" },
  };
  const meta = decisionMap[decision] || decisionMap.wait;
  if (!mode || mode === "off") {
    return {
      visible: false,
      mode,
      decision,
      shadowStatus,
      shadowResult,
      blocked,
      reasonFamily,
      label: "",
      shortLabel: "",
      tone: "slate",
    };
  }
  if (blocked) {
    return {
      visible: true,
      mode,
      decision,
      shadowStatus,
      shadowResult,
      blocked,
      blockedReason,
      reasonFamily,
      label: "Blocked",
      shortLabel: "Protect Blocked",
      tone: "amber",
    };
  }
  return {
    visible: true,
    mode,
    decision,
    shadowStatus,
    shadowResult,
    blocked,
    reasonFamily,
    label: meta.label,
    shortLabel: meta.shortLabel,
    tone: meta.tone,
  };
}

function profitProtectionBadge(bot) {
  const meta = getProfitProtectionMeta(bot);
  if (!meta.visible) return "";
  if (!meta.blocked && (!meta.decision || meta.decision === "wait") && meta.shadowStatus !== "triggered") {
    return "";
  }
  const toneMap = {
    slate: "border-slate-700 bg-slate-800/70 text-slate-200",
    amber: "border-amber-400/30 bg-amber-500/10 text-amber-100",
    emerald: "border-emerald-400/30 bg-emerald-500/10 text-emerald-100",
    rose: "border-rose-400/30 bg-rose-500/10 text-rose-100",
  };
  const subtitle = [
    meta.mode ? `Mode ${humanizeReason(meta.mode)}` : "",
    meta.blocked ? humanizeReason(meta.blockedReason || "blocked") : "",
    meta.shadowStatus === "triggered" ? "Shadow active" : "",
  ].filter(Boolean).join(" • ");
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium bot-badge--secondary ${toneMap[meta.tone] || toneMap.slate}" title="${escapeHtml(subtitle)}">${escapeHtml(meta.label)}</span>`;
}

function renderWatchdogExchangeTruthTag(item) {
  const runtimeBlocker = String(
    item?.reason
    || item?.compact_metrics?.runtime_blocker
    || item?.source_context?.last_skip_reason
    || ""
  ).trim().toLowerCase();
  if (!isExchangeTruthExecutionReason(runtimeBlocker)) return "";
  const labelMap = {
    exchange_truth_stale: "Truth Stale",
    reconciliation_diverged: "Truth Diverged",
    exchange_state_untrusted: "Follow-up Pending",
  };
  const toneMap = {
    exchange_truth_stale: "border-sky-400/25 bg-sky-500/10 text-sky-100",
    reconciliation_diverged: "border-blue-400/25 bg-blue-500/10 text-blue-100",
    exchange_state_untrusted: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100",
  };
  return `<span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${toneMap[runtimeBlocker] || toneMap.exchange_truth_stale}">${escapeHtml(labelMap[runtimeBlocker] || humanizeReason(runtimeBlocker))}</span>`;
}

function formatReadinessStageLabel(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "trigger_ready") return "Trigger Ready";
  if (normalized === "armed") return "Armed";
  if (normalized === "late") return "Late";
  if (normalized === "blocked") return "Blocked";
  return humanizeReason(normalized || "watch");
}

function getReadinessStageOrder(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "trigger_ready") return 3;
  if (normalized === "armed") return 2;
  if (normalized === "late") return 1;
  return 0;
}

function formatCompactAgeSeconds(ageSec) {
  const numericAge = Number(ageSec);
  if (!Number.isFinite(numericAge) || numericAge < 0) return "";
  if (numericAge < 1) return "<1s";
  if (numericAge < 60) return `${Math.round(numericAge)}s`;
  const minutes = numericAge / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${Math.round(minutes / 60)}h`;
}

function getReadinessFreshnessMeta(bot, override = null) {
  const sourceKind = String(
    override?.sourceKind
    || bot?.readiness_source_kind
    || bot?.analysis_ready_source
    || ""
  ).trim().toLowerCase();
  const previewState = String(
    override?.previewState
    || bot?.readiness_preview_state
    || ""
  ).trim().toLowerCase();
  const ageSecRaw = override?.ageSec;
  const ageSec = Number.isFinite(Number(ageSecRaw))
    ? Number(ageSecRaw)
    : (
      Number.isFinite(Number(bot?.readiness_source_age_sec)) ? Number(bot.readiness_source_age_sec)
        : (Number.isFinite(Number(bot?.setup_ready_age_sec)) ? Number(bot.setup_ready_age_sec)
          : (Number.isFinite(Number(bot?.analysis_ready_age_sec)) ? Number(bot.analysis_ready_age_sec) : null))
    );
  const fallbackUsed = Boolean(
    override?.fallbackUsed
    || bot?.readiness_fallback_used
    || bot?.setup_ready_fallback_used
    || bot?.analysis_ready_fallback_used
  );
  let sourceLabel = "Readiness";
  let tone = "slate";
  if (sourceKind === "runtime") {
    sourceLabel = "Runtime";
    tone = "emerald";
  } else if (sourceKind === "fresh_fallback") {
    sourceLabel = "Fresh fallback";
    tone = "cyan";
  } else if (sourceKind === "fresh_analysis") {
    sourceLabel = "Fresh analysis";
    tone = "cyan";
  } else if (sourceKind === "stopped_preview") {
    sourceLabel = "Stopped Preview";
    tone = previewState === "aging" ? "amber" : "slate";
  } else if (sourceKind === "stopped_preview_stale") {
    sourceLabel = "Stopped Preview";
    tone = "amber";
  } else if (sourceKind === "stopped_preview_unavailable") {
    sourceLabel = "Stopped Preview Off";
    tone = "slate";
  }
  const ageText = formatCompactAgeSeconds(ageSec);
  const label = [sourceLabel, ageText].filter(Boolean).join(" · ");
  const title = [
    sourceLabel,
    ageText ? `Age ${ageText}` : "",
    previewState ? `Preview ${humanizeReason(previewState)}` : "",
    fallbackUsed ? "Fallback used" : "",
  ].filter(Boolean).join(" • ");
  return {
    label,
    title,
    tone,
    sourceKind,
    previewState,
    ageSec,
    fallbackUsed,
  };
}

function readinessFreshnessBadge(bot) {
  const meta = getReadinessFreshnessMeta(bot);
  if (!meta.label) return "";
  const toneMap = {
    slate: "border-slate-700 bg-slate-800/70 text-slate-200",
    cyan: "border-cyan-400/30 bg-cyan-500/10 text-cyan-200",
    emerald: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
    amber: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  };
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium bot-badge--secondary ${toneMap[meta.tone] || toneMap.slate}" title="${escapeHtml(meta.title || meta.label)}">${escapeHtml(meta.label)}</span>`;
}

function runtimeStartLifecycleBadge(bot) {
  const lifecycle = String(bot?.runtime_start_lifecycle || "").trim().toLowerCase();
  if (lifecycle === "startup_stalled" || Boolean(bot?.startup_stalled)) {
    return `<span class="inline-flex items-center rounded-full border border-rose-400/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-medium text-rose-100" title="Start accepted but runner-owned runtime state did not become active within the expected window.">Start stalled</span>`;
  }
  if (lifecycle === "pending_runner_pickup" || Boolean(bot?.startup_pending)) {
    return `<span class="inline-flex items-center rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-100" title="Start accepted. Waiting for a fresh runner-owned runtime snapshot.">Start pending</span>`;
  }
  return "";
}

// Grace period map: once a bot enters the ready board, it stays for at least 60s
// even if the raw status flips back to watch. Prevents appear/disappear flicker.

function getLiveExecutionIntentMeta(bot) {
  const status = String(bot?.status || "").trim().toLowerCase();
  if (!["running", "paused", "recovering", "flash_crash_paused"].includes(status)) return null;

  let direction = "";
  let sourceLabel = "";
  if (Number(bot?.position_size || 0) > 0) {
    const side = String(bot?.position_side || "").trim().toLowerCase();
    if (side === "buy") {
      direction = "long";
      sourceLabel = "Open position";
    } else if (side === "sell") {
      direction = "short";
      sourceLabel = "Open position";
    }
  }

  if (!direction) {
    const runtimeMode = normalizeBotModeValue(getEffectiveRuntimeModeForUi(bot));
    if (runtimeMode === "long" || runtimeMode === "short") {
      direction = runtimeMode;
      sourceLabel = "Runtime mode";
    }
  }

  if (!direction) return null;

  const upperDirection = direction.toUpperCase();
  return {
    direction,
    label: `Live ${upperDirection}`,
    toneClass: direction === "long"
      ? "border-emerald-300/45 bg-emerald-500/16 text-emerald-50 shadow-[0_0_18px_rgba(16,185,129,0.16)]"
      : "border-rose-300/45 bg-rose-500/16 text-rose-50 shadow-[0_0_18px_rgba(244,63,94,0.16)]",
    title: `${sourceLabel} remains ${upperDirection}. Cross-mode readiness is advisory only until you switch modes.`,
  };
}

function renderLiveExecutionIntentBadge(bot) {
  const meta = getLiveExecutionIntentMeta(bot);
  if (!meta) return "";
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${meta.toneClass}" title="${escapeHtml(meta.title)}">${escapeHtml(meta.label)}</span>`;
}

function renderAlternativeModeSummary(bot) {
  const alt = getAlternativeModeReadiness(bot);
  const setup = getSetupReadiness(bot);
  if (!alt || isTriggerReadyStatus(setup.status)) return "";
  const configuredMode = formatBotModeLabel(getConfiguredModeForUi(bot));
  const configuredState = setup.reasonText || humanizeReason(setup.reason || setup.status || "watch");
  const liveIntent = getLiveExecutionIntentMeta(bot);
  const scoreText = Number.isFinite(alt.score) ? `Score ${alt.score.toFixed(1)}` : "";
  const altState = alt.reasonText || humanizeReason(alt.reason || alt.status);
  const executionText = alt.executionBlocked
    ? (alt.executionReasonText || humanizeReason(alt.executionReason || "opening_blocked"))
    : (isTriggerReadyStatus(alt.status) ? "Actionable if you switch" : "Developing if you switch");
  const stageText = formatReadinessStageLabel(alt.status);
  const title = [
    `Configured mode: ${configuredMode} • ${configuredState}`,
    `Alternative mode ${stageText.toLowerCase()}: ${alt.label} • ${altState}`,
    scoreText,
    executionText,
    alt.detail,
    alt.updatedAt ? `Updated: ${formatFeedClock(alt.updatedAt)}` : "",
    alt.sourceKind ? `Source: ${humanizeReason(alt.sourceKind)}` : "",
  ].filter(Boolean).join(" • ");
  return `
    <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
      ${liveIntent ? `<span class="inline-flex items-center rounded-full border px-2 py-0.5 font-semibold uppercase tracking-[0.16em] ${liveIntent.toneClass}" title="${escapeHtml(liveIntent.title)}">${escapeHtml(liveIntent.label)}</span>` : ""}
      <span class="inline-flex items-center rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 font-medium text-cyan-100" title="${escapeHtml(title)}">
        Cross-Mode Preview
      </span>
      <span class="text-slate-400">${escapeHtml(`If switched: ${alt.label} · ${stageText}`)}</span>
      <span class="text-slate-500">${escapeHtml(`Current ${configuredMode}: ${configuredState}`)}</span>
      <button type="button" onclick="reviewSuggestedMode('${bot.id}', '${alt.mode}', '${alt.rangeMode}')" class="rounded-lg border border-cyan-400/25 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-500/20 transition">
        Review Mode
      </button>
    </div>
  `;
}

function entryGateStatusBadge(bot) {
  const gate = getLiveGateStatus(bot);
  if (!gate.status) return "";
  const labelMap = {
    on: "🟢 Gate On",
    off_global: "⚪ Gate Off (Global)",
    off_bot: "⚪ Gate Off (Bot)",
  };
  const toneMap = {
    on: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
    off_global: "border-slate-500/30 bg-slate-500/10 text-slate-300",
    off_bot: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  };
  const titleParts = [
    gate.reasonText ? `Live gate: ${gate.reasonText}` : "",
    gate.detail ? `Detail: ${gate.detail}` : "",
    gate.updatedAt ? `Updated: ${formatFeedClock(gate.updatedAt)}` : "",
  ].filter(Boolean);
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium bot-badge--secondary ${toneMap[gate.status] || toneMap.off_bot}" title="${escapeHtml(titleParts.join(" • "))}">${escapeHtml(labelMap[gate.status] || "⚪ Gate")}</span>`;
}

function entryReadinessBadge(bot) {
  const analysis = getSetupReadiness(bot);
  const execution = getExecutionViability(bot);
  const status = analysis.status;
  if (!status) return "";

  const reason = analysis.reason;
  const reasonText = analysis.reasonText;
  const detail = analysis.detail;
  const source = analysis.source;
  const updatedAt = analysis.updatedAt;
  const actionState = (() => {
    if (hasAnalyticalSetupReady(bot) && execution.marginLimited) {
      return {
        label: "SETUP READY / MARGIN WARNING",
        next: "Setup is valid, but free account margin is tight right now.",
      };
    }
    if (isTriggerReadyStatus(status) && execution.blocked) {
      return {
        label: "TRIGGER READY / BLOCKED",
        next: "Trigger is valid, but a runtime opening blocker must clear before entry.",
      };
    }
    if (reason === "preview_disabled") {
      return { label: "PREVIEW OFF", next: "This is not a trading block. Use runtime state or enable live preview." };
    }
    if (reason === "entry_gate_disabled") {
      if (source === "entry_gate_disabled_global") {
        return { label: "GATE OFF (GLOBAL)", next: "Enable the global entry gate if you want readiness gating active." };
      }
      return { label: "GATE OFF (BOT)", next: "Enable Entry Gate (Safety) on this bot if you want readiness gating active." };
    }
    if (reason === "stale_snapshot") {
      return { label: "STALE", next: "Wait for a fresh runner snapshot before acting." };
    }
    if (reason === "pullback_watch") {
      const pbDepth = Number(bot._pullback_watch_pullback_depth_pct || 0).toFixed(1);
      return { label: `PULLBACK WATCH (${pbDepth}%)`, next: "HTF trend intact. Waiting for pullback to ease before re-entering." };
    }
    if (isTriggerReadyStatus(status)) {
      return { label: "ACTIONABLE NOW", next: "Executable now. Use the signal label to judge whether this is early or continuation." };
    }
    if (isArmedStatus(status)) {
      return { label: "ARMED / NEAR TRIGGER", next: "The setup is building toward a likely trigger, but it is not enter-now yet." };
    }
    if (isLateStatus(status)) {
      return { label: "LATE / DECAYED", next: "The setup is too extended to treat as a fresh trigger." };
    }
    if (status === "blocked") {
      return { label: "BLOCKED", next: "Do not enter until this blocker clears." };
    }
    return { label: "WAIT / WATCH", next: "Watch for the caution or blocker state to clear before entering." };
  })();

  const shortLabels = {
    trigger_ready: "✅ TRIGGER",
    armed: "🟦 ARMED",
    late: "🟠 LATE",
    setup_ready_blocked: "✅ TRIGGER / BLOCKED",
    early_entry: "✅ EARLY",
    good_continuation: "✅ GOOD CONT.",
    confirmed_breakout: "✅ BREAKOUT",
    continuation_entry: "🟦 ARMED · CONT.",
    late_continuation: "🟠 LATE CONT.",
    near_resistance: "⛔ BLOCKED · Near R",
    near_support: "⛔ BLOCKED · Near S",
    loss_budget_blocked: "⛔ BLOCKED · Budget",
    loss_budget_low: "👀 WAIT · Budget",
    position_cap_hit: "⛔ BLOCKED · Cap",
    insufficient_margin: "⛔ BLOCKED · Margin",
    qty_below_min: "⛔ BLOCKED · Min Qty",
    notional_below_min: "⛔ BLOCKED · Min Notional",
    stale_balance: "⚠️ STALE · Balance",
    breakout_invalidated: "⛔ BLOCKED · Invalidated",
    breakout_not_confirmed: "⛔ BLOCKED · Breakout",
    setup_quality_too_low: "⛔ BLOCKED · Weak Setup",
    low_setup_quality: "👀 WAIT · Weak Setup",
    watch_setup: "👀 WAIT · Setup",
    no_trade_zone: "⛔ BLOCKED · No-Trade",
    structure_weak: "👀 WAIT · Structure",
    waiting_for_confirmation: "👀 WAIT · Confirm",
    waiting_for_better_structure: "👀 WAIT · Structure",
    pullback_watch: "🔄 PB WATCH",
    trend_too_strong: "⛔ BLOCKED · Trend",
    awaiting_symbol_pick: "👀 WAIT · Pick",
    preview_limited: "⚠️ PREVIEW",
    preview_disabled: "⚠️ PREVIEW OFF",
    entry_gate_disabled: "⚪ GATE OFF",
    entry_gate_disabled_global: "⚪ GATE OFF (GLOBAL)",
    entry_gate_disabled_bot: "⚪ GATE OFF (BOT)",
    stale_snapshot: "⚠️ STALE",
    exchange_truth_stale: "Truth Stale",
    reconciliation_diverged: "Truth Diverged",
    exchange_state_untrusted: "Follow-up Pending",
  };
  const toneByStatus = {
    trigger_ready: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
    armed: "border-cyan-400/30 bg-cyan-500/10 text-cyan-100",
    late: "border-orange-400/30 bg-orange-500/10 text-orange-100",
    watch: "border-amber-400/30 bg-amber-500/10 text-amber-200",
    blocked: "border-red-400/30 bg-red-500/10 text-red-200",
    exchange_truth: "border-sky-400/30 bg-sky-500/10 text-sky-100",
  };

  let label = shortLabels[reason] || shortLabels[status] || `⚠️ ${reasonText || humanizeReason(reason || status)}`;
  if (hasAnalyticalSetupReady(bot) && execution.marginLimited) {
    label = isArmedStatus(status)
      ? "🟦 ARMED · Margin"
      : (isLateStatus(status) ? "🟠 LATE · Margin" : "✅ SETUP · Margin");
  }
  if (isTriggerReadyStatus(status) && execution.blocked) {
    const blockedText = shortLabels[execution.reason] || execution.reasonText || humanizeReason(execution.reason || "blocked");
    label = `✅ TRIGGER / ${blockedText}`;
  }
  if (hasAnalyticalSetupReady(bot) && execution.marginLimited) {
    label = isArmedStatus(status)
      ? "🟦 ARMED · Margin"
      : (isLateStatus(status) ? "🟠 LATE · Margin" : "✅ SETUP · Margin");
  }
  if (isArmedStatus(status)) {
    if (reason === "continuation_entry") {
      label = shortLabels.continuation_entry;
    } else if (reason === "waiting_for_confirmation") {
      label = "🟦 ARMED · Confirm";
    } else {
      label = shortLabels.armed;
    }
  }
  if (isLateStatus(status)) {
    label = reason === "late_continuation" ? shortLabels.late_continuation : shortLabels.late;
  }
  if (reason === "preview_limited" && source === "runtime_only") {
    label = shortLabels.preview_disabled;
  }
  if (reason === "entry_gate_disabled") {
    if (source === "entry_gate_disabled_global") {
      label = shortLabels.entry_gate_disabled_global;
    } else if (source === "entry_gate_disabled_bot") {
      label = shortLabels.entry_gate_disabled_bot;
    }
  }
  const titleParts = [
    `${actionState.label}: ${reasonText || humanizeReason(reason || status)}`,
    detail || "",
    isTriggerReadyStatus(status) && execution.blocked
      ? `Opening blocker: ${execution.reasonText || humanizeReason(execution.reason || "blocked")}`
      : "",
    isTriggerReadyStatus(status) && execution.blocked ? execution.detail : "",
    !execution.blocked && execution.staleData
      ? `Execution note: ${execution.diagnosticText || humanizeReason(execution.diagnosticReason || "stale_balance")}`
      : "",
    !execution.blocked && execution.staleData ? execution.diagnosticDetail : "",
    (analysis.next || actionState.next) || "",
    updatedAt ? `Updated: ${formatFeedClock(updatedAt)}` : "",
  ].filter(Boolean);
  const flashyClass = isTriggerReadyStatus(status) && !execution.blocked
    ? " entry-ready-badge--flashy border-emerald-300/70 shadow-[0_0_16px_rgba(16,185,129,0.28)]"
    : "";
  const toneClass = hasAnalyticalSetupReady(bot) && execution.marginLimited
    ? toneByStatus.watch
    : (isTriggerReadyStatus(status) && execution.blocked
    ? (isExchangeTruthExecutionReason(execution.reason) ? toneByStatus.exchange_truth : toneByStatus.blocked)
    : (toneByStatus[status] || toneByStatus.watch));

  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${toneClass}${flashyClass}" title="${escapeHtml(titleParts.join(" • "))}">${escapeHtml(label)}</span>`;
}

function autoPilotStatusBadge(bot) {
  if (!bot?.auto_pilot) return "";

  const title = `Current coin ${bot.symbol || "Auto-Pilot"} is under Auto-Pilot management.`;
  const toneClass = bot.status === "stopped"
    ? "bg-cyan-500/10 text-cyan-100 border-cyan-500/25"
    : "bg-cyan-400/20 text-cyan-50 border-cyan-300/70 shadow-[0_0_18px_rgba(34,211,238,0.32)]";

  return `<span class="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-black uppercase tracking-[0.18em] border ${toneClass}" title="${title}">🚀 AI PILOT</span>`;
}

function profileBadge(profile, autoDirection) {
  let badgeClass = "bg-slate-500/20 text-slate-400";
  let label = profile || "normal";
  if (profile === "scalp") {
    badgeClass = "bg-orange-500/20 text-orange-400";
    label = "⚡scalp";
  }
  let autoIndicator = autoDirection ? '<span class="ml-1 text-purple-400" title="Auto Direction enabled">🔄</span>' : "";
  return `<span class="px-2 py-1 rounded text-xs font-medium bot-badge--secondary ${badgeClass}">${label}</span>${autoIndicator}`;
}

function modeBadge(mode, scalpAnalysis, bot) {
  let badgeClass = "bg-slate-500/20 text-slate-400";
  let label = mode || "neutral";
  let titleParts = [];

  if (mode === "dynamic") {
    badgeClass = "bg-orange-500/20 text-orange-400";
    label = "🔥 Dynamic";
    titleParts.push("Ultra-Trend mode");
  } else if (mode === "neutral_classic_bybit") {
    badgeClass = "bg-slate-500/20 text-slate-300";
    label = "Neutral Classic";
  } else if (mode === "scalp_pnl") {
    badgeClass = "bg-amber-500/20 text-amber-400";
    label = "💰 Scalp PnL";

    if (scalpAnalysis) {
      const condition = scalpAnalysis.condition || "unknown";
      const target = bot.scalp_live_target || bot._scalp_adapted_target || scalpAnalysis.profit_target || 0.30;
      const liveNotional = bot.scalp_live_position_notional || 0;
      const isChoppy = scalpAnalysis.is_choppy;

      let conditionIcon = "⚡";
      if (condition === "trending_up") conditionIcon = "📈";
      else if (condition === "trending_down") conditionIcon = "📉";
      else if (condition === "choppy" || isChoppy) conditionIcon = "🌊";
      else if (condition === "calm") conditionIcon = "😌";

      label = `💰 Scalp PnL ${conditionIcon}$${target.toFixed(2)}`;
      titleParts.push(liveNotional > 0
        ? `Live scalp target scaled for $${Number(liveNotional).toFixed(2)} notional`
        : "Dynamic scalp profit target");
    }
  } else if (mode === "scalp_market") {
    badgeClass = "bg-cyan-500/20 text-cyan-400";
    label = "⚡ Scalp Mkt";

    if (bot) {
      const signalScore = bot.scalp_signal_score;
      const scalpStatus = bot.scalp_status;
      if (signalScore !== undefined && signalScore !== null) {
        const signalIcon = signalScore > 0 ? "📈" : signalScore < 0 ? "📉" : "➖";
        label = `⚡ Scalp Mkt ${signalIcon}${signalScore > 0 ? '+' : ''}${signalScore}`;
      }
      if (scalpStatus) titleParts.push(scalpStatus);
    }
  } else if (mode === "long") {
    badgeClass = "bg-emerald-500/20 text-emerald-400";
  } else if (mode === "short") {
    badgeClass = "bg-red-500/20 text-red-400";
  }

  // Fold runtime mode divergence into this badge (replaces separate runtimeModeViewBadge)
  if (bot) {
    const configuredMode = getConfiguredModeForUi(bot);
    const effectiveMode = getEffectiveRuntimeModeForUi(bot);
    const configuredRange = getConfiguredRangeModeForUi(bot);
    const effectiveRange = getEffectiveRuntimeRangeModeForUi(bot);
    if (configuredMode !== effectiveMode || configuredRange !== effectiveRange) {
      const runtimeSource = String(bot?.runtime_mode_source || "").trim();
      label += ` → ${formatBotModeLabel(effectiveMode)}`;
      titleParts.push(`Configured: ${formatBotModeLabel(configuredMode)} / ${formatRangeModeLabel(configuredRange)}`);
      titleParts.push(`Runtime: ${formatBotModeLabel(effectiveMode)} / ${formatRangeModeLabel(effectiveRange)}`);
      if (runtimeSource) titleParts.push(`Source: ${humanizeReason(runtimeSource)}`);
    }
  }

  const title = titleParts.length > 0 ? ` title="${escapeHtml(titleParts.join(" • "))}"` : "";
  return `<span class="px-2 py-1 rounded text-xs font-medium bot-badge--secondary ${badgeClass}"${title}>${label}</span>`;
}

function runtimeModeViewBadge(bot) {
  const configuredMode = getConfiguredModeForUi(bot);
  const effectiveMode = getEffectiveRuntimeModeForUi(bot);
  const configuredRange = getConfiguredRangeModeForUi(bot);
  const effectiveRange = getEffectiveRuntimeRangeModeForUi(bot);
  const runtimeSource = String(bot?.runtime_mode_source || "").trim();
  if (configuredMode === effectiveMode && configuredRange === effectiveRange) return "";
  const title = [
    `Configured Mode: ${formatBotModeLabel(configuredMode)} / ${formatRangeModeLabel(configuredRange)}`,
    `Runtime View: ${formatBotModeLabel(effectiveMode)} / ${formatRangeModeLabel(effectiveRange)}`,
    runtimeSource ? `Source: ${humanizeReason(runtimeSource)}` : "",
    "Runtime suggestion only; saved mode unchanged.",
  ].filter(Boolean).join(" • ");
  return `<span class="inline-flex items-center rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-medium text-cyan-100" title="${escapeHtml(title)}">Runtime View: ${escapeHtml(formatBotModeLabel(effectiveMode))}</span>`;
}

function rangeModeBadge(rangeMode, widthPct) {
  const badges = {
    fixed: "bg-slate-500/20 text-slate-400",
    dynamic: "bg-blue-500/20 text-blue-400",
    trailing: "bg-purple-500/20 text-purple-400",
  };
  const mode = (rangeMode || "fixed").toLowerCase();
  const cls = badges[mode] || badges.fixed;
  const widthTitle = (widthPct && !isNaN(widthPct)) ? ` title="Range width: ${(widthPct * 100).toFixed(1)}%"` : "";
  return `<span class="px-2 py-1 rounded text-xs font-medium bot-badge--secondary ${cls}"${widthTitle}>${mode}</span>`;
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

function updateOpenExposureMeta(totalPositionValue = null) {
  const openExposureValueEl = $("summary-open-exposure-value");
  if (openExposureValueEl) {
    const numericPositionValue = Number(totalPositionValue);
    openExposureValueEl.textContent = Number.isFinite(numericPositionValue) && numericPositionValue > 0
      ? `• ${formatNumber(numericPositionValue, 2)} USDT`
      : "";
  }

  const openExposureModeEl = $("summary-open-exposure-mode");
  if (openExposureModeEl) {
    const recommendationMode = String(liveOpenExposureRecommendation.mode || "").trim();
    const recommendationRangeMode = String(liveOpenExposureRecommendation.rangeMode || "").trim().toLowerCase() || "fixed";
    openExposureModeEl.innerHTML = recommendationMode
      ? recommendedModeBadge(recommendationMode.toLowerCase(), recommendationRangeMode)
      : "";
  }
}

function renderEmergencyRestartPanel(bots) {
  const panel = $("emergency-restart-panel");
  const list = $("emergency-restart-list");
  if (!panel || !list) return;

  if (!Array.isArray(bots) || !bots.length) {
    emergencyRestartBotId = "";
    panel.classList.add("hidden");
    list.innerHTML = "";
    return;
  }

  const runningBot = bots.find((bot) => bot.status === "running");
  if (runningBot) {
    emergencyRestartBotId = runningBot.id;
    panel.classList.add("hidden");
    list.innerHTML = "";
    return;
  }

  let selectedBot = bots.find((bot) => bot.id === emergencyRestartBotId);
  if (!selectedBot) {
    selectedBot = [...bots].sort((left, right) => {
      const leftTs = Math.max(
        Date.parse(left.last_run_at || "") || 0,
        Date.parse(left.control_updated_at || "") || 0,
        Date.parse(left.started_at || "") || 0,
      );
      const rightTs = Math.max(
        Date.parse(right.last_run_at || "") || 0,
        Date.parse(right.control_updated_at || "") || 0,
        Date.parse(right.started_at || "") || 0,
      );
      return rightTs - leftTs;
    })[0] || null;
    emergencyRestartBotId = selectedBot?.id || "";
  }

  if (!selectedBot) {
    panel.classList.add("hidden");
    list.innerHTML = "";
    return;
  }

  const activePendingAction = pendingBotActions[selectedBot.id];
  const recentlyStoppedAt = Number(recentlyStoppedBots[selectedBot.id] || 0);
  const canStart = !["running", "paused", "recovering", "flash_crash_paused"].includes(selectedBot.status);
  const stopGuardActive =
    selectedBot.status === "stopped" && (Date.now() - recentlyStoppedAt) < STOP_TO_START_GUARD_MS;
  const stopGuardSec = Math.max(
    1,
    Math.ceil((STOP_TO_START_GUARD_MS - (Date.now() - recentlyStoppedAt)) / 1000)
  );
  const buttonDisabled = !!activePendingAction || !canStart || stopGuardActive;
  const buttonLabel = activePendingAction === "start"
    ? "Starting..."
    : stopGuardActive
      ? `Wait ${stopGuardSec}s`
      : "Restart";
  const buttonClass = buttonDisabled
    ? "border border-slate-700 bg-slate-800 text-slate-400 cursor-not-allowed opacity-70"
    : "bg-emerald-600 text-white hover:bg-emerald-500";

  panel.classList.remove("hidden");
  list.innerHTML = `
    <div class="flex items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/65 px-3 py-3">
      <div class="min-w-0 truncate text-sm font-semibold text-white">${escapeHtml(selectedBot.symbol || "Auto-Pilot")}</div>
      <button
        onclick="botAction('start', '${selectedBot.id}', event)"
        ${buttonDisabled ? "disabled" : ""}
        class="min-w-[96px] rounded-xl px-3 py-2 text-xs font-semibold transition ${buttonClass}">
        ${escapeHtml(buttonLabel)}
      </button>
    </div>
  `;
}

function getActiveBotRenderIds(bots) {
  return (bots || []).map((bot) => String(bot?.id || "").trim());
}

function renderMobileBotsData(bots) {
  const container = $("active-bots-list");
  if (!container) return;

  if (!bots.length) {
    rememberActiveBotStructure([]);
    container.innerHTML = `
      <div class="ops-empty-state">
        <strong>No bots configured</strong>
        Add a bot from the workbench to populate the live operations board.
      </div>
    `;
    return;
  }

  container.innerHTML = bots.map((bot) => buildActiveBotRowMarkup(bot)).join("");
  rememberActiveBotStructure(bots);
}

function renderMobilePositionsData(positions) {
  const container = $("positions-board");
  if (!container) return;
  container.classList.toggle("positions-board--single", positions.length === 1);

  if (!positions.length) {
    setElementHtmlIfChanged(container, `
      <div class="positions-empty-state">
        <strong>No open positions</strong>
      </div>
    `);
    return;
  }

  setElementHtmlIfChanged(container, positions.map((pos) => {
    const isLong = pos.side === "Buy";
    const pnl = formatPnL(pos.unrealized_pnl || 0);
    const realized = formatPnL(pos.realized_pnl || 0);
    const valueText = `$${formatNumber(pos.position_value || 0, 2)}`;
    const leverageValue = Number(pos.leverage);
    const hasLeverage = Number.isFinite(leverageValue) && leverageValue > 0;
    const pctToLiqValue = Number(pos.pct_to_liq);
    const hasPctToLiq = Number.isFinite(pctToLiqValue);
    const pctToLiq = hasPctToLiq ? `${pctToLiqValue.toFixed(1)}%` : "-";
    const pctClass = hasPctToLiq && pctToLiqValue < 5
      ? "text-red-300"
      : hasPctToLiq && pctToLiqValue < 10
        ? "text-amber-300"
        : "text-emerald-300";
    const botId = pos.bot_id || "";
    const modeLabel = escapeHtml(String(pos.bot_mode || "-").toUpperCase());
    const rangeLabel = escapeHtml(String(pos.bot_range_mode || "-").toUpperCase());
    const liqTone = hasPctToLiq && pctToLiqValue < 5
      ? "border-red-400/35 bg-red-500/10"
      : hasPctToLiq && pctToLiqValue < 10
        ? "border-amber-400/35 bg-amber-500/10"
        : "border-emerald-400/30 bg-emerald-500/10";

    return `
      <article class="position-row-card">
        <div class="position-row-card__layout">
          <div>
            <div class="position-row-card__headline">
              <div class="text-base font-semibold text-white truncate max-w-[180px]" title="${escapeHtml(pos.symbol || "-")}">${escapeHtml(pos.symbol || "-")}</div>
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-[0.12em] ${isLong ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"}">
                ${isLong ? "Long" : "Short"}
              </span>
              <span class="position-meta-pill">${modeLabel}</span>
              <span class="position-meta-pill ${hasLeverage ? 'text-cyan-200 border-cyan-400/25 bg-cyan-500/10' : ''}">${hasLeverage ? `${formatNumber(leverageValue, 1)}x` : "-"}</span>
            </div>
            <div class="flex items-baseline gap-3 mt-1.5">
              <span class="text-lg font-semibold ${pnl.class}">${pnl.text}</span>
              <span class="text-[11px] text-slate-500">${realized.text}</span>
            </div>
          </div>

          <div class="position-row-card__metrics">
            <div class="position-row-card__metric ${liqTone}">
              <div class="position-row-card__metric-label">Risk</div>
              <div class="position-row-card__metric-value ${pctClass}">${pctToLiq}</div>
            </div>
            <div class="position-row-card__metric">
              <div class="position-row-card__metric-label">Entry</div>
              <div class="position-row-card__metric-value">${formatNumber(pos.entry_price || 0, 4)}</div>
            </div>
            <div class="position-row-card__metric">
              <div class="position-row-card__metric-label">Mark</div>
              <div class="position-row-card__metric-value">${formatNumber(pos.mark_price || 0, 4)}</div>
            </div>
            <div class="position-row-card__metric">
              <div class="position-row-card__metric-label">Value</div>
              <div class="position-row-card__metric-value">${valueText}</div>
            </div>
          </div>

          <div class="position-row-card__rail">
            <div class="position-row-card__actions">
              <div class="position-actions-stack">
                <button onclick="closePosition('${pos.symbol}', '${pos.side}', ${pos.size}, ${botId ? `'${botId}'` : 'null'}, this)"
                  class="position-action-btn close-btn">
                  Close
                </button>
                ${botId ? `
                  <button onclick='showQuickEdit("${botId}")'
                    class="position-action-btn config-btn">
                    Config
                  </button>
                ` : ""}
              </div>
            </div>
          </div>
        </div>
      </article>
    `;
  }).join(""));
}

function renderPositionsStatusMessage(message) {
  const safeMessage = escapeHtml(message || "Unable to load positions");
  const container = $("positions-board");
  if (container) {
    container.innerHTML = `<div class="positions-empty-state"><strong>${safeMessage}</strong></div>`;
  }
}

function renderMobilePnlData(logs) {
  const container = $("pnl-cards");
  if (!container) return;

  if (!logs.length) {
    container.innerHTML = `
      <div class="pnl-empty-state">
        <span class="pnl-empty-state__icon">◎</span>
        <strong>No closed trades yet</strong>
        Session closes and realized PnL will appear here automatically.
      </div>
    `;
    return;
  }

  container.innerHTML = logs.map((log) => {
    const pnl = formatPnL(log.realized_pnl || 0);
    const cardPulseClass = dashboardFeedState.lastPnlEventIds?.has(log.id || log.exec_id || `${log.time}:${log.symbol}`)
      ? (Number(log.realized_pnl || 0) >= 0 ? "profit-pulse" : "loss-pulse")
      : "";
    return `
      <article class="pnl-mobile-card ${cardPulseClass}">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-sm font-semibold text-white truncate max-w-[120px]" title="${escapeHtml(log.symbol || "-")}">${escapeHtml(log.symbol || "-")}</span>
              <span class="position-meta-pill">${escapeHtml(log.side || "-")}</span>
            </div>
            <div class="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400">
              <span class="pnl-toolbar-chip">${escapeHtml(formatTime(log.time))}</span>
            </div>
          </div>
          <div class="text-right">
            <div class="text-base font-semibold ${pnl.class}">${pnl.text}</div>
            <div class="mt-1 text-[11px] text-slate-500">${escapeHtml(log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : "-")}</div>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function renderActivityFeed() {
  const container = $("activity-feed-list");
  if (!container) return;

  if (!dashboardFeedState.events.length) {
    container.innerHTML = `
      <div class="activity-feed-item" data-tone="info">
        <div class="flex items-center justify-between gap-3">
          <span class="event-tag bg-slate-800 text-slate-300">Warmup</span>
          <span class="text-[11px] text-slate-500">Live</span>
        </div>
        <p class="mt-3 text-sm text-slate-300">Live updates will appear here.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = dashboardFeedState.events.map((item) => {
    const tags = [];
    if (item.symbol) {
      tags.push(buildMetricChip(item.symbol, "slate"));
    }
    if (item.meta) {
      tags.push(buildMetricChip(item.meta, item.tone === "danger" || item.tone === "loss" ? "rose" : item.tone === "warning" ? "amber" : item.tone === "profit" ? "emerald" : "cyan"));
    }

    return `
      <article class="activity-feed-item" data-tone="${escapeHtml(item.tone)}">
        <div class="flex items-center justify-between gap-3">
          <span class="event-tag ${eventToneTagClass(item.tone)}">${escapeHtml(item.icon)} ${escapeHtml(item.label)}</span>
          <div class="text-right">
            <div class="text-[11px] font-medium text-slate-300">${escapeHtml(formatFeedClock(item.ts))}</div>
            <div class="text-[10px] text-slate-500">${escapeHtml(formatFeedTimeAgo(item.ts))}</div>
          </div>
        </div>
        <p class="mt-3 text-sm font-medium text-slate-100">${escapeHtml(item.message)}</p>
        ${tags.length ? `<div class="mt-3 flex flex-wrap gap-2">${tags.join("")}</div>` : ""}
      </article>
    `;
  }).join("");
}

function updateStreakBadge() {
  const badge = $("streak-badge");
  if (!badge) return;

  if (dashboardFeedState.winStreak >= 2) {
    badge.textContent = `${dashboardFeedState.winStreak} wins in a row`;
    badge.className = "rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-[11px] font-bold text-emerald-300";
    badge.classList.remove("hidden");
    return;
  }

  if (dashboardFeedState.lossStreak >= 2) {
    badge.textContent = `${dashboardFeedState.lossStreak} losses in a row`;
    badge.className = "rounded-full border border-red-400/30 bg-red-500/10 px-3 py-1 text-[11px] font-bold text-red-200";
    badge.classList.remove("hidden");
    return;
  }

  badge.classList.add("hidden");
}

function getWatchdogSeverityMeta(severity) {
  const normalized = String(severity || "INFO").trim().toUpperCase();
  if (normalized === "CRITICAL") return { chip: "border-rose-400/30 bg-rose-500/15 text-rose-100", label: "CRITICAL" };
  if (normalized === "ERROR") return { chip: "border-red-400/30 bg-red-500/15 text-red-100", label: "HIGH" };
  if (normalized === "WARN") return { chip: "border-amber-400/30 bg-amber-500/15 text-amber-100", label: "MEDIUM" };
  return { chip: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100", label: "LOW" };
}

function renderWatchdogMetricChips(metrics, limit = 4) {
  const entries = Object.entries(metrics || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!entries.length) return `<span class="text-slate-500">No compact metrics</span>`;
  return entries.slice(0, limit).map(([key, value]) => `
    <span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-950/80 px-2 py-1 text-[11px] text-slate-200">
      <span class="mr-1 text-slate-500">${escapeHtml(formatWatchdogLabel(key))}</span>
      <strong class="font-medium text-slate-100">${escapeHtml(formatWatchdogMetricValue(value))}</strong>
    </span>
  `).join("");
}

function renderWatchdogBaselineSummary(meta) {
  const summaryEl = $("performance-baseline-summary");
  if (summaryEl) {
    summaryEl.textContent = formatPerformanceBaselineSummary(meta, { prefix: "Baseline" });
  }
  setPerformanceBaselineButtonState(
    $("btn-reset-performance-baseline"),
    Boolean(performanceBaselineResetInFlight),
    "Resetting Baseline...",
    "Reset Performance Baseline"
  );
}

function renderWatchdogHubSummary(filtered) {
  const overview = watchdogHubState.data?.overview || {};
  const activeIssues = filtered.activeIssues || [];
  const recentEvents = filtered.recentEvents || [];
  const severityCounts = { CRITICAL: 0, ERROR: 0, WARN: 0, INFO: 0 };
  const blockerCounts = {};
  const watchdogCounts = {};
  const bots = new Set();
  const symbols = new Set();

  activeIssues.forEach((item) => {
    const severity = String(item.severity || "INFO").trim().toUpperCase();
    severityCounts[severity] = (severityCounts[severity] || 0) + 1;
    if (item.bot_id) bots.add(item.bot_id);
    if (item.symbol) symbols.add(item.symbol);
    if (item.blocker_type) blockerCounts[item.blocker_type] = (blockerCounts[item.blocker_type] || 0) + 1;
    watchdogCounts[item.watchdog_type] = (watchdogCounts[item.watchdog_type] || 0) + 1;
  });

  const noisyCounts = {};
  recentEvents.forEach((item) => {
    noisyCounts[item.watchdog_type] = (noisyCounts[item.watchdog_type] || 0) + 1;
  });

  const topBlocker = Object.entries(blockerCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || overview.top_blocker_category;
  const noisy = Object.entries(noisyCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || overview.most_noisy_watchdog;

  $("watchdog-summary-active").textContent = String(activeIssues.length);
  $("watchdog-summary-critical-high").textContent = String((severityCounts.CRITICAL || 0) + (severityCounts.ERROR || 0));
  $("watchdog-summary-medium").textContent = String(severityCounts.WARN || 0);
  $("watchdog-summary-bots").textContent = String(bots.size || overview.affected_bots_count || 0);
  $("watchdog-summary-blocker").textContent = topBlocker ? formatWatchdogLabel(topBlocker) : "None";
  $("watchdog-summary-noisy").textContent = noisy ? formatWatchdogLabel(noisy) : "Quiet";
  $("watchdog-active-count-chip").textContent = `${activeIssues.length} active`;
  $("watchdog-timeline-count-chip").textContent = `${recentEvents.length} events`;
}

function renderRuntimeIntegrityPanel() {
  const payload = watchdogHubState.data?.runtime_integrity || window._lastRuntimeIntegrity || null;
  const statusEl = $("runtime-integrity-status");
  const badgesEl = $("runtime-integrity-badges");
  const sourceEl = $("runtime-integrity-source");
  const freshnessEl = $("runtime-integrity-freshness");
  const startupEl = $("runtime-integrity-startup");
  const recoveryEl = $("runtime-integrity-recovery");
  if (!statusEl || !badgesEl || !sourceEl || !freshnessEl || !startupEl || !recoveryEl) return;

  if (!payload || typeof payload !== "object") {
    statusEl.textContent = "Waiting for runtime state.";
    badgesEl.innerHTML = "";
    sourceEl.textContent = "Unknown";
    freshnessEl.textContent = "n/a";
    startupEl.textContent = "No pending starts";
    recoveryEl.textContent = "Not requested";
    return;
  }

  const statusText = payload.startup_stalled
    ? "Startup stalled"
    : payload.stale_guard_active
      ? "Holding last known good state"
      : payload.divergence_detected
        ? "Source divergence detected"
        : payload.startup_pending
          ? "Start pending runner pickup"
          : "Runtime state stable";
  statusEl.textContent = statusText;
  const badges = [];
  if (payload.stale_guard_active) {
    badges.push('<span class="lower-toolbar-chip border-amber-400/30 bg-amber-500/10 text-amber-100">Hold last good</span>');
  }
  if (payload.divergence_detected) {
    badges.push('<span class="lower-toolbar-chip border-rose-400/30 bg-rose-500/10 text-rose-100">Divergence</span>');
  }
  if (payload.startup_pending) {
    badges.push(`<span class="lower-toolbar-chip border-cyan-400/25 bg-cyan-500/10 text-cyan-100">Pending ${escapeHtml(String(payload.startup_pending_count || 0))}</span>`);
  }
  if (payload.startup_stalled) {
    badges.push(`<span class="lower-toolbar-chip border-rose-400/30 bg-rose-500/10 text-rose-100">Stalled ${escapeHtml(String(payload.startup_stalled_count || 0))}</span>`);
  }
  if (payload.resync_requested) {
    badges.push('<span class="lower-toolbar-chip border-indigo-400/25 bg-indigo-500/10 text-indigo-100">Resync requested</span>');
  }
  badgesEl.innerHTML = badges.join("");
  sourceEl.textContent = formatWatchdogLabel(String(payload.runtime_state_source || "unknown"));
  freshnessEl.textContent = `Runtime ${formatRuntimeIntegrityAge(payload.runtime_state_age_sec)} · Runner ${formatRuntimeIntegrityAge(payload.runner_heartbeat_age_sec)}`;
  startupEl.textContent = payload.startup_stalled
    ? `${Number(payload.startup_stalled_count || 0)} stalled`
    : payload.startup_pending
      ? `${Number(payload.startup_pending_count || 0)} pending`
      : "No pending starts";
  recoveryEl.textContent = payload.resync_requested
    ? (payload.stale_guard_reason || payload.dropped_reason || "Review runtime source drift")
    : "Not requested";
}

function renderOpportunityFunnelChips(containerId, items, fallbackText, formatter) {
  const container = $(containerId);
  if (!container) return;
  if (!(items || []).length) {
    container.innerHTML = `<span class="text-slate-500">${escapeHtml(fallbackText)}</span>`;
    return;
  }
  container.innerHTML = items.map((item) => formatter(item)).join("");
}

function renderOpportunityFunnel() {
  const payload = watchdogHubState.data?.opportunity_funnel || {};
  const snapshot = payload.snapshot || {};
  const followThrough = payload.follow_through || {};
  const watchEl = $("opportunity-funnel-watch");
  const armedEl = $("opportunity-funnel-armed");
  const triggerEl = $("opportunity-funnel-trigger-ready");
  const executedEl = $("opportunity-funnel-executed");
  const blockedEl = $("opportunity-funnel-blocked");
  const contextEl = $("opportunity-funnel-context");
  const rateEl = $("opportunity-funnel-rate");

  if (watchEl) watchEl.textContent = String(snapshot.watch || 0);
  if (armedEl) armedEl.textContent = String(snapshot.armed || 0);
  if (triggerEl) triggerEl.textContent = String(snapshot.trigger_ready || 0);
  if (executedEl) executedEl.textContent = String(followThrough.executed || 0);
  if (blockedEl) blockedEl.textContent = String(followThrough.blocked || 0);

  if (contextEl) {
    const lateCount = Number(snapshot.late || 0);
    const liveCount = Number(snapshot.bot_count || 0);
    const lateText = lateCount > 0 ? ` · Late ${lateCount}` : "";
    contextEl.textContent = `Live ${liveCount} · ${formatOpportunityFunnelWindow(followThrough.window_sec)} flow${lateText}`;
  }
  if (rateEl) {
    const conversion = followThrough.trigger_to_execute_rate;
    rateEl.textContent = Number.isFinite(Number(conversion))
      ? `T→E ${Number(conversion).toFixed(1)}%`
      : "T→E n/a";
  }

  renderOpportunityFunnelChips(
    "opportunity-funnel-blockers",
    payload.blocked_reasons || [],
    "No recent blockers",
    (item) => `
      <span class="inline-flex items-center rounded-full border border-amber-400/20 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-100">
        ${escapeHtml(item.label || item.key || "Other")} ${escapeHtml(String(item.count || 0))}
      </span>
    `,
  );
  renderOpportunityFunnelChips(
    "opportunity-funnel-repeat-failures",
    payload.repeat_failures || [],
    "No repeat failures",
    (item) => `
      <span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] font-medium text-slate-200">
        ${escapeHtml(item.label || "Unknown")} · ${escapeHtml(item.reason_label || item.reason || "Other")} ${escapeHtml(String(item.count || 0))}
      </span>
    `,
  );
  renderOpportunityFunnelChips(
    "opportunity-funnel-structural",
    payload.structural_untradeable || [],
    "No structural mismatches",
    (item) => `
      <span class="inline-flex items-center rounded-full border border-rose-400/20 bg-rose-500/10 px-2 py-1 text-[11px] font-medium text-rose-100">
        ${escapeHtml(item.label || "Unknown")} · ${escapeHtml(item.reason_label || item.reason || "Other")}
      </span>
    `,
  );
}

function renderWatchdogInsights(insights) {
  const container = $("watchdog-insights");
  if (!container) return;
  if (!(insights || []).length) {
    container.innerHTML = `<span class="lower-toolbar-chip text-slate-300">No outstanding summary insights.</span>`;
    return;
  }
  container.innerHTML = insights.map((item) => `
    <span class="lower-toolbar-chip border-slate-700 bg-slate-950/80 text-slate-200">${escapeHtml(item)}</span>
  `).join("");
}

function renderWatchdogActiveIssues(activeIssues) {
  const container = $("watchdog-active-issues");
  if (!container) return;
  if (!activeIssues.length) {
    container.innerHTML = `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
        No active watchdog issues in the selected scope.
      </div>
    `;
    return;
  }

  container.innerHTML = activeIssues.map((issue) => {
    const severity = getWatchdogSeverityMeta(issue.severity);
    const summary = summarizeWatchdogMetrics(issue.compact_metrics, 3);
    const truthTag = renderWatchdogExchangeTruthTag(issue);
    return `
      <button type="button"
        data-watchdog-select="1"
        data-watchdog-kind="active"
        data-watchdog-key="${escapeHtml(issue.active_key || "")}"
        class="block w-full rounded-xl border ${watchdogHubState.selectedKey === issue.active_key ? "border-amber-400/40 bg-amber-500/8" : "border-slate-800 bg-slate-950/55"} px-3 py-3 text-left transition hover:border-slate-700 hover:bg-slate-950/80">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${severity.chip}">${severity.label}</span>
              <span class="inline-flex items-center rounded-full border border-emerald-400/25 bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-100">ACTIVE</span>
              ${truthTag}
              <span class="text-sm font-semibold text-white">${escapeHtml(issue.watchdog_label || formatWatchdogLabel(issue.watchdog_type))}</span>
            </div>
            <div class="mt-2 text-sm text-slate-100">${escapeHtml(formatWatchdogLabel(issue.reason))}</div>
            <div class="mt-1 text-xs text-slate-400">${escapeHtml(issue.bot_id || "No bot")} · ${escapeHtml(issue.symbol || "No symbol")} · last seen ${escapeHtml(formatTimeAgo(new Date(issue.last_seen || Date.now())))}</div>
            <div class="mt-2 text-xs text-slate-300">${escapeHtml(summary || "No compact metrics captured.")}</div>
          </div>
          <div class="shrink-0 text-right text-[11px] text-slate-400">
            <div>${escapeHtml(String(issue.occurrence_count || 1))} hits</div>
            <div class="mt-1">${escapeHtml(formatWatchdogLabel(issue.actionable_state || "review_recent_window"))}</div>
          </div>
        </div>
      </button>
    `;
  }).join("");
}

function renderWatchdogCards(cards) {
  const container = $("watchdog-cards-grid");
  if (!container) return;
  if (!cards.length) {
    container.innerHTML = `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
        No watchdog cards match the selected filters.
      </div>
    `;
    return;
  }

  container.innerHTML = cards.map((card) => {
    const statusTone = card.current_status === "ACTIVE"
      ? "border-rose-400/20 bg-rose-500/8 text-rose-100"
      : card.current_status === "RECENT"
        ? "border-amber-400/20 bg-amber-500/8 text-amber-100"
        : "border-slate-700 bg-slate-950/70 text-slate-300";
    const trigger = card.most_recent_trigger || {};
    return `
      <button type="button"
        data-watchdog-card="${escapeHtml(card.watchdog_type || "")}"
        class="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-left transition hover:border-slate-700 hover:bg-slate-950/80">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-sm font-semibold text-white">${escapeHtml(card.label || formatWatchdogLabel(card.watchdog_type))}</div>
            <div class="mt-1 text-xs text-slate-400">${escapeHtml(card.explanation || "")}</div>
          </div>
          <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${statusTone}">${escapeHtml(card.current_status || "QUIET")}</span>
        </div>
        <div class="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div class="rounded-lg border border-slate-800 bg-slate-900/70 px-2 py-2 text-slate-300">Active<br><strong class="text-white">${escapeHtml(String(card.active_issue_count || 0))}</strong></div>
          <div class="rounded-lg border border-slate-800 bg-slate-900/70 px-2 py-2 text-slate-300">Bots<br><strong class="text-white">${escapeHtml(String(card.affected_bots_count || 0))}</strong></div>
          <div class="rounded-lg border border-slate-800 bg-slate-900/70 px-2 py-2 text-slate-300">Symbols<br><strong class="text-white">${escapeHtml(String(card.affected_symbols_count || 0))}</strong></div>
        </div>
        <div class="mt-3 text-[11px] text-slate-400">
          ${trigger.reason ? `${escapeHtml(formatWatchdogLabel(trigger.reason))} · ${escapeHtml(formatTimeAgo(new Date(trigger.timestamp || Date.now())))}` : "No recent trigger"}
        </div>
        <div class="mt-2 text-[11px] text-slate-500">
          ${escapeHtml(summarizeWatchdogConfig(card.config) || "Config visibility unavailable")}
        </div>
      </button>
    `;
  }).join("");
}

function renderWatchdogRecentTimeline(recentEvents, activeIssues) {
  const container = $("watchdog-recent-timeline");
  if (!container) return;
  const activeKeys = new Set((activeIssues || []).map((item) => item.active_key));
  if (!recentEvents.length) {
    container.innerHTML = `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
        No recent watchdog events in the selected window.
      </div>
    `;
    return;
  }

  container.innerHTML = recentEvents.map((event) => {
    const severity = getWatchdogSeverityMeta(event.severity);
    const isActive = activeKeys.has(String(event.event_key || ""));
    const truthTag = renderWatchdogExchangeTruthTag(event);
    return `
      <button type="button"
        data-watchdog-select="1"
        data-watchdog-kind="recent"
        data-watchdog-key="${escapeHtml(event.event_key || "")}"
        class="block w-full rounded-xl border ${watchdogHubState.selectedKey === event.event_key ? "border-cyan-400/40 bg-cyan-500/8" : "border-slate-800 bg-slate-950/55"} px-3 py-3 text-left transition hover:border-slate-700 hover:bg-slate-950/80">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${severity.chip}">${severity.label}</span>
              <span class="inline-flex items-center rounded-full border ${isActive ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100" : "border-slate-700 bg-slate-900/80 text-slate-300"} px-2 py-1 text-[11px] font-semibold">${isActive ? "ACTIVE" : "HISTORICAL"}</span>
              ${truthTag}
              <span class="text-sm font-semibold text-white">${escapeHtml(event.symbol || event.bot_id || "System")}</span>
            </div>
            <div class="mt-2 text-sm text-slate-100">${escapeHtml(formatWatchdogLabel(event.reason))}</div>
            <div class="mt-1 text-xs text-slate-400">${escapeHtml(event.watchdog_label || formatWatchdogLabel(event.watchdog_type))} · ${escapeHtml(event.bot_id || "No bot")} · ${escapeHtml(formatTimeAgo(new Date(event.timestamp || Date.now())))}</div>
          </div>
          <div class="shrink-0 text-right text-[11px] text-slate-400">
            ${escapeHtml(event.symbol || "")}
          </div>
        </div>
      </button>
    `;
  }).join("");
}

function renderWatchdogHub() {
  initWatchdogHubControls();
  const payload = watchdogHubState.data || {};
  const filtered = getFilteredWatchdogHubData();
  const availableFilters = payload.available_filters || {};
  populateWatchdogFilterOptions("watchdog-filter-severity", availableFilters.severities || [], "All severities");
  populateWatchdogFilterOptions("watchdog-filter-type", (availableFilters.watchdog_types || []).map((item) => String(item || "")), "All watchdogs");
  populateWatchdogFilterOptions("watchdog-filter-bot", availableFilters.bots || [], "All bots");
  populateWatchdogFilterOptions("watchdog-filter-symbol", availableFilters.symbols || [], "All symbols");
  const activeOnlyToggle = $("watchdog-filter-active-only");
  if (activeOnlyToggle) activeOnlyToggle.checked = Boolean(watchdogHubState.filters.activeOnly);
  const updatedLabel = $("watchdog-hub-last-updated");
  if (updatedLabel) {
    updatedLabel.textContent = `Last updated: ${payload.updated_at ? formatTimeAgo(new Date(payload.updated_at)) : "never"}`;
  }
  renderWatchdogBaselineSummary(payload.performance_baseline || null);
  renderWatchdogHubSummary(filtered);
  renderRuntimeIntegrityPanel();
  renderOpportunityFunnel();
  renderWatchdogInsights(payload.insights || []);
  renderWatchdogActiveIssues(filtered.activeIssues);
  renderWatchdogCards(filtered.watchdogCards);
  renderWatchdogRecentTimeline(filtered.recentEvents, filtered.activeIssues);
  renderWatchdogDetail(filtered);
}

function getBotTriageVerdictMeta(verdict) {
  const normalized = String(verdict || "").trim().toUpperCase();
  if (normalized === "PAUSE") return { chip: "border-rose-400/30 bg-rose-500/15 text-rose-100", label: "PAUSE" };
  if (normalized === "REDUCE") return { chip: "border-amber-400/30 bg-amber-500/15 text-amber-100", label: "REDUCE" };
  if (normalized === "REVIEW") return { chip: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100", label: "REVIEW" };
  return { chip: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100", label: "KEEP" };
}

function getBotTriageSeverityMeta(severity) {
  const normalized = String(severity || "").trim().toLowerCase();
  if (normalized === "high") return { chip: "border-rose-400/30 bg-rose-500/12 text-rose-100", label: "HIGH" };
  if (normalized === "medium") return { chip: "border-amber-400/30 bg-amber-500/12 text-amber-100", label: "MEDIUM" };
  return { chip: "border-slate-600 bg-slate-900/80 text-slate-200", label: "LOW" };
}

function renderBotTriageSourceSignals(sourceSignals) {
  const entries = Object.entries(sourceSignals || {}).filter(([, value]) => value !== null && value !== undefined && value !== "" && (!Array.isArray(value) || value.length));
  if (!entries.length) return "";
  return entries.slice(0, 4).map(([key, value]) => `${formatWatchdogLabel(key)} ${formatWatchdogMetricValue(value)}`).join(" · ");
}

function renderBotTriageConfirmation(item) {
  const confirmation = botTriageState.confirmation;
  if (!confirmation || String(confirmation.botId || "") !== String(item?.bot_id || "")) {
    return "";
  }
  const loading = Boolean(botTriageState.actionInFlight);
  const lines = Array.isArray(confirmation.lines) && confirmation.lines.length
    ? confirmation.lines
    : ["Confirm this triage action."];
  return `
    <div class="mt-3 rounded-xl border border-amber-400/20 bg-amber-500/8 px-3 py-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-amber-200/80">${escapeHtml(String(confirmation.title || "Confirm Action"))}</div>
      <div class="mt-2 space-y-1 text-sm text-amber-50">
        ${lines.map((line) => `<div>${escapeHtml(String(line || ""))}</div>`).join("")}
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <button type="button" onclick='executeBotTriageAction(${JSON.stringify(String(item?.bot_id || ""))})' class="${getBotTriageActionButtonClass(confirmation.confirmTone)}" ${loading ? "disabled" : ""}>
          ${loading ? "Applying..." : escapeHtml(String(confirmation.confirmLabel || "Confirm"))}
        </button>
        <button type="button" onclick="cancelBotTriageAction()" class="${getBotTriageActionButtonClass()}" ${loading ? "disabled" : ""}>Cancel</button>
      </div>
    </div>
  `;
}

async function openBotTriageDiagnostics(botId, symbol) {
  const filterBot = $("watchdog-filter-bot");
  const filterSymbol = $("watchdog-filter-symbol");
  watchdogHubState.filters.botId = String(botId || "");
  watchdogHubState.filters.symbol = String(symbol || "").trim().toUpperCase();
  if (filterBot) filterBot.value = watchdogHubState.filters.botId;
  if (filterSymbol) filterSymbol.value = watchdogHubState.filters.symbol;
  if (!watchdogHubState.data) {
    await refreshWatchdogHub();
  } else {
    renderWatchdogHub();
  }
  const target = $("watchdog-active-issues") || $("watchdog-center-hub");
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function executeBotTriageAction(botId) {
  const confirmation = botTriageState.confirmation;
  if (!confirmation || botTriageState.actionInFlight || String(confirmation.botId || "") !== String(botId || "")) {
    return;
  }
  const runtimeBot = getTriageRuntimeBot(botId) || {};
  const verdict = String(((botTriageState.data || {}).items || []).find((row) => String(row?.bot_id || "") === String(botId || ""))?.verdict || "").trim().toUpperCase();
  botTriageState.actionInFlight = true;
  renderBotTriage();
  try {
    let response = null;
    let successMessage = "Triage action applied";
    if (confirmation.actionType === "pause") {
      response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/pause-action`, {
        method: "POST",
        body: JSON.stringify({ cancel_pending: false }),
      });
      successMessage = "Bot paused";
    } else if (confirmation.actionType === "pause_cancel_pending") {
      response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/pause-action`, {
        method: "POST",
        body: JSON.stringify({ cancel_pending: true }),
      });
      successMessage = "Bot paused and pending entries cancelled";
    } else if (confirmation.actionType === "dismiss") {
      response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/dismiss`, {
        method: "POST",
        body: JSON.stringify({ verdict }),
      });
      successMessage = "Recommendation dismissed";
    } else if (confirmation.actionType === "snooze") {
      response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/snooze`, {
        method: "POST",
        body: JSON.stringify({ verdict, duration: "1h" }),
      });
      successMessage = "Recommendation snoozed for 1 hour";
    } else if (confirmation.actionType === "preset:reduce_risk" || confirmation.actionType === "preset:sleep_session") {
      response = await fetchJSON(`/bot-triage/${encodeURIComponent(botId)}/apply-preset`, {
        method: "POST",
        body: JSON.stringify({
          preset: confirmation.preset,
          settings_version: runtimeBot?.settings_version,
        }),
      });
      successMessage = confirmation.preset === "reduce_risk"
        ? "Safe preset applied"
        : "Session timer preset enabled";
    } else {
      return;
    }
    botTriageState.confirmation = null;
    showToast(successMessage, "success");
    const refreshTasks = [refreshBotTriage(), refreshBotConfigAdvisor(), refreshBots(), refreshSummary()];
    if (confirmation.actionType.startsWith("pause")) {
      refreshTasks.push(refreshPositions(), refreshWatchdogHub());
    } else if (confirmation.actionType.startsWith("preset:")) {
      refreshTasks.push(refreshWatchdogHub());
    }
    await Promise.allSettled(refreshTasks);
    return response;
  } catch (error) {
    if (error.status === 409 && error?.data?.error === "settings_version_conflict") {
      showToast("Bot settings changed in another editor or window. Refresh and try again.", "error");
      await Promise.allSettled([refreshBots(), refreshBotTriage(), refreshBotConfigAdvisor()]);
    } else {
      showToast(`Triage action failed: ${error.message}`, "error");
    }
  } finally {
    botTriageState.actionInFlight = false;
    renderBotTriage();
  }
}

function renderBotTriage() {
  const payload = botTriageState.data || { summary_counts: {}, items: [], generated_at: null, suppressed_count: 0 };
  const counts = payload.summary_counts || {};
  const items = Array.isArray(payload.items) ? payload.items : [];
  const listEl = $("bot-triage-list");
  const updatedEl = $("bot-triage-last-updated");
  if (updatedEl) {
    updatedEl.textContent = formatBotTriageUpdatedAt(payload.generated_at);
    updatedEl.title = payload?.stale_data && payload?.error ? String(payload.error) : "";
  }
  const pauseEl = $("bot-triage-summary-pause");
  const reduceEl = $("bot-triage-summary-reduce");
  const reviewEl = $("bot-triage-summary-review");
  const keepEl = $("bot-triage-summary-keep");
  if (pauseEl) pauseEl.textContent = String(counts.PAUSE || 0);
  if (reduceEl) reduceEl.textContent = String(counts.REDUCE || 0);
  if (reviewEl) reviewEl.textContent = String(counts.REVIEW || 0);
  if (keepEl) keepEl.textContent = String(counts.KEEP || 0);
  if (!listEl) return;

  if (!items.length) {
    listEl.innerHTML = `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
        ${payload?.stale_data ? "Triage data is limited by a stale runtime snapshot." : (Number(payload?.suppressed_count || 0) > 0 ? "All current triage items are dismissed or snoozed." : "No bot triage items available.")}
      </div>
    `;
    return;
  }

  const staleNote = payload?.stale_data
    ? `
      <div class="rounded-xl border border-amber-400/20 bg-amber-500/8 px-3 py-3 text-xs text-amber-100">
        Runtime snapshot is stale. Triage is conservative until a fresh runtime snapshot arrives.
      </div>
    `
    : "";
  const suppressedNote = Number(payload?.suppressed_count || 0) > 0
    ? `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3 text-xs text-slate-300">
        ${escapeHtml(String(payload.suppressed_count))} triage recommendation${Number(payload.suppressed_count) === 1 ? "" : "s"} hidden by dismiss/snooze.
      </div>
    `
    : "";

  listEl.innerHTML = staleNote + suppressedNote + items.map((item) => {
    const verdict = getBotTriageVerdictMeta(item.verdict);
    const severity = getBotTriageSeverityMeta(item.severity);
    const reasonItems = (item.reasons || []).slice(0, 3);
    const sourceSummary = renderBotTriageSourceSignals(item.source_signals);
    return `
      <article class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3">
        <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold text-white">${escapeHtml(String(item.symbol || "Unknown"))}</span>
              <span class="text-xs text-slate-400">${escapeHtml(formatBotTriageMode(item.mode))}</span>
              <span data-bot-triage-verdict="${escapeHtml(String(item.verdict || ""))}" class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${verdict.chip}">${verdict.label}</span>
              <span data-bot-triage-severity="${escapeHtml(String(item.severity || ""))}" class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${severity.chip}">${severity.label}</span>
            </div>
            <div class="mt-2 flex flex-wrap gap-2">
              ${reasonItems.map((reason) => `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-200">${escapeHtml(String(reason || ""))}</span>`).join("")}
            </div>
            <div class="mt-3 text-sm text-slate-100">${escapeHtml(String(item.suggested_action || ""))}</div>
            ${sourceSummary ? `<div class="mt-2 text-[11px] text-slate-500">${escapeHtml(sourceSummary)}</div>` : ""}
            ${renderBotTriageConfirmation(item)}
          </div>
          <div class="flex flex-wrap items-center gap-2">
            ${buildBotTriageActionButtons(item)}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function getBotConfigAdvisorVerdictMeta(verdict) {
  const normalized = String(verdict || "").trim().toUpperCase();
  if (normalized === "REDUCE_RISK") return { chip: "border-rose-400/30 bg-rose-500/12 text-rose-100", label: "REDUCE RISK" };
  if (normalized === "WIDEN_STRUCTURE") return { chip: "border-amber-400/30 bg-amber-500/12 text-amber-100", label: "WIDEN" };
  if (normalized === "REVIEW_MANUALLY") return { chip: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100", label: "REVIEW" };
  return { chip: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100", label: "KEEP CURRENT" };
}

function getBotConfigAdvisorConfidenceMeta(confidence) {
  const normalized = String(confidence || "").trim().toLowerCase();
  if (normalized === "high") return { chip: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100", label: "HIGH" };
  if (normalized === "medium") return { chip: "border-amber-400/30 bg-amber-500/12 text-amber-100", label: "MEDIUM" };
  return { chip: "border-slate-600 bg-slate-900/80 text-slate-200", label: "LOW" };
}

function getBotConfigAdvisorQueueMeta(state) {
  const normalized = String(state || "").trim().toLowerCase();
  if (normalized === "waiting_for_flat") return { chip: "border-amber-400/30 bg-amber-500/12 text-amber-100", label: "QUEUED UNTIL FLAT" };
  if (normalized === "blocked") return { chip: "border-rose-400/30 bg-rose-500/12 text-rose-100", label: "QUEUE BLOCKED" };
  if (normalized === "failed") return { chip: "border-rose-400/30 bg-rose-500/12 text-rose-100", label: "QUEUE FAILED" };
  if (normalized === "applying") return { chip: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100", label: "APPLYING" };
  return { chip: "border-slate-600 bg-slate-900/80 text-slate-200", label: formatWatchdogLabel(normalized || "queued") };
}

async function beginBotConfigAdvisorApply(botId) {
  if (botConfigAdvisorState.actionInFlight) return;
  try {
    const response = await fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/apply`, {
      method: "POST",
      body: JSON.stringify({ preview: true }),
    });
    botConfigAdvisorState.confirmation = {
      botId,
      preview: response?.preview || {},
    };
    renderBotConfigAdvisor();
  } catch (error) {
    showToast(`Unable to load advisor preview: ${error.message}`, "error");
  }
}

function renderBotConfigAdvisorConfirmation(item) {
  const confirmation = botConfigAdvisorState.confirmation;
  if (!confirmation || String(confirmation.botId || "") !== String(item?.bot_id || "")) {
    return "";
  }
  const preview = confirmation.preview || {};
  const applicable = Array.isArray(preview.applicable_changes) ? preview.applicable_changes : [];
  const advisory = Array.isArray(preview.advisory_only_changes) ? preview.advisory_only_changes : [];
  const loading = Boolean(botConfigAdvisorState.actionInFlight);
  const queueMode = Boolean(preview.requires_flat_state) && !Boolean(preview.is_flat_now);
  const confirmLabel = queueMode ? "Queue Until Flat" : "Apply Recommended Tune";
  const canConfirm = Boolean(preview.supports_apply);
  return `
    <div class="mt-3 rounded-xl border border-cyan-400/20 bg-cyan-500/8 px-3 py-3">
      <div class="text-[11px] uppercase tracking-[0.18em] text-cyan-200/80">${escapeHtml(String(preview.title || "Apply Recommended Tune"))}</div>
      <div class="mt-2 space-y-2 text-sm text-cyan-50">
        <div class="font-medium text-white">This will change:</div>
        ${applicable.length ? applicable.map((change) => `
          <div>${escapeHtml(String(change.label || change.field || ""))}: ${escapeHtml(formatBotConfigAdvisorValue(change.field, change.from))} <span class="text-cyan-200/70">-></span> ${escapeHtml(formatBotConfigAdvisorValue(change.field, change.to))}</div>
        `).join("") : '<div class="text-cyan-100/80">No concrete supported config fields are available to apply.</div>'}
        ${advisory.length ? `
          <div class="pt-2 font-medium text-white">Advisory only, not auto-applied:</div>
          ${advisory.map((change) => `
            <div>${escapeHtml(String(change.label || change.field || ""))}: ${escapeHtml(formatBotConfigAdvisorValue(change.field, change.from))} <span class="text-cyan-200/70">-></span> ${escapeHtml(formatBotConfigAdvisorValue(change.field, change.to))}</div>
          `).join("")}
        ` : ""}
        ${preview.requires_flat_state && !preview.is_flat_now ? '<div class="pt-2 text-amber-200">Bot must be flat before applying recommended tune.</div>' : ""}
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <button type="button" onclick='executeBotConfigAdvisorApply(${JSON.stringify(String(item?.bot_id || ""))})' class="${getBotTriageActionButtonClass("accent")}" ${(loading || !canConfirm) ? "disabled" : ""}>
          ${loading ? "Applying..." : escapeHtml(confirmLabel)}
        </button>
        <button type="button" onclick="cancelBotConfigAdvisorApply()" class="${getBotTriageActionButtonClass()}" ${loading ? "disabled" : ""}>Cancel</button>
      </div>
    </div>
  `;
}

async function executeBotConfigAdvisorApply(botId) {
  const confirmation = botConfigAdvisorState.confirmation;
  if (!confirmation || botConfigAdvisorState.actionInFlight || String(confirmation.botId || "") !== String(botId || "")) {
    return;
  }
  const preview = confirmation.preview || {};
  const runtimeBot = getTriageRuntimeBot(botId) || {};
  if (!preview.supports_apply) {
    showToast("This recommendation has no concrete supported fields to apply.", "error");
    return;
  }
  botConfigAdvisorState.actionInFlight = true;
  renderBotConfigAdvisor();
  try {
    if (preview.requires_flat_state && !preview.is_flat_now) {
      await fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/queue-apply`, {
        method: "POST",
      });
    } else {
      await fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/apply`, {
        method: "POST",
        body: JSON.stringify({
          settings_version: runtimeBot?.settings_version,
        }),
      });
    }
    botConfigAdvisorState.confirmation = null;
    showToast(preview.requires_flat_state && !preview.is_flat_now ? "Recommended tune queued until flat" : "Recommended tune applied", "success");
    await Promise.allSettled([
      refreshBotConfigAdvisor(),
      refreshBotTriage(),
      refreshBots(),
      refreshSummary(),
      refreshWatchdogHub(),
    ]);
  } catch (error) {
    if (error.status === 409 && error?.data?.blocked_reason === "requires_flat_state") {
      showToast("Bot must be flat before applying recommended tune.", "error");
      await Promise.allSettled([refreshBotConfigAdvisor(), refreshBots()]);
    } else if (error.status === 409 && error?.data?.blocked_reason === "already_flat_apply_now") {
      showToast("Bot is already flat. Apply the recommended tune directly instead of queueing it.", "error");
      await Promise.allSettled([refreshBotConfigAdvisor(), refreshBots()]);
    } else if (error.status === 409 && error?.data?.error === "settings_version_conflict") {
      showToast("Bot settings changed in another editor or window. Refresh and try again.", "error");
      await Promise.allSettled([refreshBotConfigAdvisor(), refreshBots()]);
    } else {
      showToast(`Advisor apply failed: ${error.message}`, "error");
    }
  } finally {
    botConfigAdvisorState.actionInFlight = false;
    renderBotConfigAdvisor();
  }
}

async function cancelBotConfigAdvisorQueue(botId) {
  if (botConfigAdvisorState.actionInFlight) return;
  botConfigAdvisorState.actionInFlight = true;
  renderBotConfigAdvisor();
  try {
    await fetchJSON(`/bot-config-advisor/${encodeURIComponent(botId)}/cancel-queued-apply`, {
      method: "POST",
    });
    showToast("Queued tune canceled", "success");
    await Promise.allSettled([refreshBotConfigAdvisor()]);
  } catch (error) {
    showToast(`Unable to cancel queued tune: ${error.message}`, "error");
  } finally {
    botConfigAdvisorState.actionInFlight = false;
    renderBotConfigAdvisor();
  }
}

function renderBotConfigAdvisor() {
  const payload = botConfigAdvisorState.data || { summary_counts: {}, items: [], generated_at: null };
  const counts = payload.summary_counts || {};
  const items = Array.isArray(payload.items) ? payload.items : [];
  const listEl = $("bot-config-advisor-list");
  const updatedEl = $("bot-config-advisor-last-updated");
  if (updatedEl) {
    updatedEl.textContent = formatBotTriageUpdatedAt(payload.generated_at);
    updatedEl.title = payload?.stale_data && payload?.error ? String(payload.error) : "";
  }
  const reduceEl = $("bot-config-advisor-summary-reduce");
  const widenEl = $("bot-config-advisor-summary-widen");
  const reviewEl = $("bot-config-advisor-summary-review");
  const keepEl = $("bot-config-advisor-summary-keep");
  if (reduceEl) reduceEl.textContent = String(counts.REDUCE_RISK || 0);
  if (widenEl) widenEl.textContent = String(counts.WIDEN_STRUCTURE || 0);
  if (reviewEl) reviewEl.textContent = String(counts.REVIEW_MANUALLY || 0);
  if (keepEl) keepEl.textContent = String(counts.KEEP_CURRENT || 0);
  if (!listEl) return;

  if (!items.length) {
    listEl.innerHTML = `
      <div class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
        ${payload?.stale_data ? "Advisor data is limited by a stale runtime snapshot." : "No config advisor items available."}
      </div>
    `;
    return;
  }

  const staleNote = payload?.stale_data
    ? `
      <div class="rounded-xl border border-amber-400/20 bg-amber-500/8 px-3 py-3 text-xs text-amber-100">
        Runtime snapshot is stale. Config advice is biased toward manual review until fresh diagnostics arrive.
      </div>
    `
    : "";
  listEl.innerHTML = staleNote + items.map((item) => {
    const verdict = getBotConfigAdvisorVerdictMeta(item.tuning_verdict);
    const confidence = getBotConfigAdvisorConfidenceMeta(item.confidence);
    const queuedApply = item?.queued_apply || null;
    const queueMeta = queuedApply ? getBotConfigAdvisorQueueMeta(queuedApply.state) : null;
    const reasonItems = (item.reasons || []).slice(0, 4);
    const diffRows = getBotConfigAdvisorDiffRows(item);
    const sourceSummary = renderBotTriageSourceSignals(item.source_signals);
    const suggestedPreset = String(item?.suggested_preset || "none").trim().toLowerCase();
    return `
      <article class="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3">
        <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold text-white">${escapeHtml(String(item.symbol || "Unknown"))}</span>
              <span class="text-xs text-slate-400">${escapeHtml(formatBotTriageMode(item.mode))}</span>
              <span data-bot-config-advisor-verdict="${escapeHtml(String(item.tuning_verdict || ""))}" class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${verdict.chip}">${verdict.label}</span>
              <span data-bot-config-advisor-confidence="${escapeHtml(String(item.confidence || ""))}" class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${confidence.chip}">${confidence.label}</span>
              ${queueMeta ? `<span data-bot-config-advisor-queue-state="${escapeHtml(String(queuedApply?.state || ""))}" class="inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${queueMeta.chip}">${queueMeta.label}</span>` : ""}
              ${suggestedPreset !== "none" ? `<span class="inline-flex items-center rounded-full border border-indigo-400/20 bg-indigo-500/10 px-2 py-1 text-[11px] font-semibold text-indigo-100">Preset: ${escapeHtml(formatWatchdogLabel(suggestedPreset))}</span>` : ""}
            </div>
            <div class="mt-2 flex flex-wrap gap-2">
              ${reasonItems.map((reason) => `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-200">${escapeHtml(String(reason || ""))}</span>`).join("")}
            </div>
            ${queuedApply ? `
              <div class="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
                <div>${escapeHtml(String(queuedApply?.state === "blocked" ? "Apply blocked by config drift or conflict." : queuedApply?.state === "failed" ? "Queued apply failed and needs review." : "Queued until flat."))}</div>
                ${Array.isArray(queuedApply?.queued_fields) && queuedApply.queued_fields.length ? `<div class="mt-1">Queued fields: ${escapeHtml(queuedApply.queued_fields.join(", "))}</div>` : ""}
                ${queuedApply?.blocked_reason ? `<div class="mt-1">Reason: ${escapeHtml(formatWatchdogLabel(String(queuedApply.blocked_reason || "")))}</div>` : ""}
              </div>
            ` : ""}
            <div class="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
              ${diffRows.map((row) => `
                <div class="rounded-lg border ${row.changed ? "border-cyan-400/20 bg-cyan-500/6" : "border-slate-800 bg-slate-900/50"} px-3 py-2">
                  <div class="text-[10px] uppercase tracking-[0.18em] text-slate-400">${escapeHtml(row.label)}</div>
                  <div class="mt-1 text-sm text-slate-100">${escapeHtml(row.current)} <span class="text-slate-500">-></span> ${escapeHtml(row.recommended)}</div>
                </div>
              `).join("")}
            </div>
            <div class="mt-3 text-sm text-slate-100">${escapeHtml(String(item.rationale || ""))}</div>
            ${sourceSummary ? `<div class="mt-2 text-[11px] text-slate-500">${escapeHtml(sourceSummary)}</div>` : ""}
            ${renderBotConfigAdvisorConfirmation(item)}
          </div>
          <div class="flex flex-wrap items-center gap-2">
            ${queuedApply ? `<button type="button" onclick='cancelBotConfigAdvisorQueue(${JSON.stringify(String(item?.bot_id || ""))})' class="${getBotTriageActionButtonClass()}">Cancel Queued Apply</button>` : (item?.can_apply_now ? `<button type="button" onclick='beginBotConfigAdvisorApply(${JSON.stringify(String(item?.bot_id || ""))})' class="${getBotTriageActionButtonClass("accent")}">Apply Recommended Tune</button>` : (item?.can_queue_until_flat ? `<button type="button" onclick='beginBotConfigAdvisorApply(${JSON.stringify(String(item?.bot_id || ""))})' class="${getBotTriageActionButtonClass("accent")}">Queue Until Flat</button>` : ""))}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function normalizeMarketStateHint(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["long", "up", "bullish", "rising", "strong_bullish", "buy"].includes(normalized)) {
    return "long";
  }
  if (["short", "down", "bearish", "falling", "strong_bearish", "sell"].includes(normalized)) {
    return "short";
  }
  return "neutral";
}

// Accumulating ready-to-trade history for emergency card (persisted in localStorage)

function _renderReadyModeFilters() {
  const container = $("ready-mode-filters");
  if (!container) return;
  const counts = _getReadyModeCounts();
  container.innerHTML = READY_MODE_FILTER_DEFS.map(def => {
    const active = _readyModeFilters[def.key] !== false;
    const count = counts[def.key] || 0;
    const cls = active ? def.on : READY_FILTER_OFF;
    const cntCls = count > 0 && active ? def.cnt : "text-slate-500";
    return `<button type="button" onclick="toggleReadyModeFilter('${def.key}')"
      class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[9px] font-semibold transition ${cls}"
      title="${active ? "Hide" : "Show"} ${def.label}">
      ${def.label}
      <span class="min-w-[14px] text-center ${cntCls}">${count}</span>
    </button>`;
  }).join("");
}

function getReadyTradeSourceMeta(bot, symbolContext = null) {
  const symbol = String(bot?.symbol || "").trim().toUpperCase();
  const botId = String(bot?.id || "").trim();
  const status = String(bot?.status || "").trim().toLowerCase();
  const activeIds = symbolContext instanceof Map ? symbolContext.get(symbol)?.activeIds : null;
  const otherActiveBot = Boolean(activeIds && Array.from(activeIds).some((id) => id && id !== botId));

  if (otherActiveBot) {
    return {
      label: "Other bot",
      detail: `Separate ${humanizeReason(status || "stopped")} bot on this symbol.`,
      toneClass: "border-slate-600/45 bg-slate-800/80 text-slate-200",
      emphasis: "separate",
    };
  }
  if (status === "stopped") {
    return {
      label: "Stopped bot",
      detail: "Ready setup belongs to a stopped bot.",
      toneClass: "border-slate-600/45 bg-slate-800/80 text-slate-200",
      emphasis: "stopped",
    };
  }
  if (["paused", "recovering", "flash_crash_paused"].includes(status)) {
    return {
      label: `${humanizeReason(status)} bot`,
      detail: `Ready setup belongs to a ${humanizeReason(status)} bot.`,
      toneClass: "border-amber-400/30 bg-amber-500/10 text-amber-100",
      emphasis: "standby",
    };
  }
  return null;
}

function renderReadyTradeSourceBadge(bot, symbolContext = null) {
  const meta = getReadyTradeSourceMeta(bot, symbolContext);
  if (!meta?.label) return "";
  return `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${meta.toneClass}" title="${escapeHtml(meta.detail || meta.label)}">${escapeHtml(meta.label)}</span>`;
}

function _renderReadyList(entries, targetEl) {
  if (!targetEl) return;
  const filtered = entries.filter(e => _passesReadyModeFilter(e));
  if (!filtered.length) {
    setElementHtmlIfChanged(targetEl, '<span class="text-slate-500">No setups ready</span>');
    return;
  }
  setElementHtmlIfChanged(targetEl, filtered.map(entry => {
    const alive = entry.still_ready;
    const dirLabel = entry.direction === "long" ? "LONG" : entry.direction === "short" ? "SHORT" : "NEUTRAL";
    const time = entry.readyAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const dirKey = entry.direction === "long" ? "long" : entry.direction === "short" ? "short" : "neutral";
    const priceStr = _fmtReadyPrice(entry.entry_price);

    if (alive) {
      const dirClass = dirKey === "long" ? "text-emerald-400" : dirKey === "short" ? "text-red-400" : "text-cyan-400";
      return `<div class="flex items-center justify-between py-1 emerg-ready-row--active emerg-ready-row--${dirKey}">
        <span class="flex items-center gap-2">
          <span class="emerg-ready-beacon-sm"></span>
          <span class="text-[10px] text-slate-400">${time}</span>
          <span class="font-semibold text-white">${escapeHtml(entry.symbol)}</span>
          ${_readyModeBadge(entry.bot_mode)}
          ${entry.source_label ? `<span class="inline-flex items-center rounded-full border border-slate-600/45 bg-slate-800/80 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-200" title="${escapeHtml(entry.source_detail || entry.source_label)}">${escapeHtml(entry.source_label)}</span>` : ""}
          ${priceStr ? `<span class="text-[10px] text-amber-300 font-medium">@${priceStr}</span>` : ""}
        </span>
        <span class="flex items-center gap-2">
          <span class="${dirClass} font-bold text-[10px]">${dirLabel}</span>
          ${entry.score ? `<span class="text-[9px] px-1.5 py-0.5 rounded border border-emerald-700/40 bg-emerald-900/30 text-emerald-300 font-semibold">${entry.score.toFixed(1)}</span>` : ""}
        </span>
      </div>`;
    } else {
      const dirClass = dirKey === "long" ? "text-emerald-600" : dirKey === "short" ? "text-rose-500" : "text-cyan-600";
      return `<div class="flex items-center justify-between py-1 emerg-ready-row--inactive emerg-ready-row--${dirKey} bg-slate-800/60 rounded">
        <span class="flex items-center gap-2">
          <span class="text-[10px] text-slate-400">${time}</span>
          <span class="font-medium text-slate-300">${escapeHtml(entry.symbol)}</span>
          ${_readyModeBadge(entry.bot_mode)}
          ${entry.source_label ? `<span class="inline-flex items-center rounded-full border border-slate-700/50 bg-slate-900/70 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-300" title="${escapeHtml(entry.source_detail || entry.source_label)}">${escapeHtml(entry.source_label)}</span>` : ""}
          ${priceStr ? `<span class="text-[10px] text-amber-400/60 font-medium">@${priceStr}</span>` : ""}
        </span>
        <span class="flex items-center gap-2">
          <span class="${dirClass} font-semibold text-[10px]">${dirLabel}</span>
          ${entry.score ? `<span class="text-[9px] px-1.5 py-0.5 rounded border border-slate-600/40 bg-slate-800/50 text-slate-400 font-medium">${entry.score.toFixed(1)}</span>` : ""}
        </span>
      </div>`;
    }
  }).join(""));
}

function _readyModeBadge(mode) {
  const m = {
    long:   { l: "L",  cls: "bg-emerald-500/20 text-emerald-300" },
    short:  { l: "S",  cls: "bg-red-500/20 text-red-300" },
    neutral_classic_bybit: { l: "NC", cls: "bg-cyan-500/20 text-cyan-300" },
    neutral: { l: "DN", cls: "bg-blue-500/20 text-blue-300" },
    scalp_pnl: { l: "SP", cls: "bg-amber-500/20 text-amber-300" },
    scalp_market: { l: "SM", cls: "bg-amber-500/20 text-amber-300" },
  }[mode];
  if (!m) return "";
  return `<span class="text-[8px] font-bold px-1 py-0.5 rounded ${m.cls}">${m.l}</span>`;
}

function renderReadyTradeBoard(bots) {
  // Always compute readyBots and update emergency card, even if board DOM elements are missing
  const symbolContext = buildReadyTradeSymbolContext(bots);
  const readyBots = (bots || [])
    .filter((bot) => isActionableReadyBot(bot))
    .sort((left, right) => {
      const leftScore = Number(getSetupReadiness(left).score || 0);
      const rightScore = Number(getSetupReadiness(right).score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  updateEmergencyReadyHistory(readyBots, symbolContext);

  const targets = [
    {
      container: $("ready-trade-board"),
      countEl: $("ready-trade-count"),
      watchEl: $("ready-trade-watch-count"),
      blockedEl: $("ready-trade-blocked-count"),
      limitedEl: $("ready-trade-limited-count"),
    },
    { container: $("ready-trade-board-mobile"), countEl: $("ready-trade-count-mobile") },
  ].filter(({ container, countEl }) => container && countEl);
  if (!targets.length) return;

  const normalizedStatuses = (bots || []).map((bot) =>
    String(getSetupReadiness(bot).status || "").trim().toLowerCase()
  );
  const watchCount = normalizedStatuses.filter((status) => ["watch", "wait", "caution"].includes(status)).length;
  const blockedSetupCount = normalizedStatuses.filter((status) => status === "blocked").length;
  const limitedCount = normalizedStatuses.filter((status) => ["preview_disabled", "stale", "stale_snapshot", "preview_limited"].includes(status)).length;
  const armedBots = (bots || [])
    .filter((bot) => isArmedStatus(getSetupReadiness(bot).status))
    .sort((left, right) => {
      const leftScore = Number(getSetupReadiness(left).score || 0);
      const rightScore = Number(getSetupReadiness(right).score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  const lateBots = (bots || [])
    .filter((bot) => isLateStatus(getSetupReadiness(bot).status))
    .sort((left, right) => {
      const leftScore = Number(getSetupReadiness(left).score || 0);
      const rightScore = Number(getSetupReadiness(right).score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  const marginWarningBots = (bots || [])
    .filter((bot) => isSetupReadyMarginLimited(bot))
    .sort((left, right) => {
      const leftScore = Number(getSetupReadiness(left).score || left?.setup_ready_score || 0);
      const rightScore = Number(getSetupReadiness(right).score || right?.setup_ready_score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  const blockedReadyBots = (bots || [])
    .filter((bot) => isSetupReadyButBlocked(bot))
    .sort((left, right) => {
      const leftScore = Number(getSetupReadiness(left).score || 0);
      const rightScore = Number(getSetupReadiness(right).score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  const blockedCount = blockedSetupCount + blockedReadyBots.length;
  const alternativeModeBots = (bots || [])
    .filter((bot) => hasAlternativeModeReady(bot))
    .sort((left, right) => {
      const leftAlt = getAlternativeModeReadiness(left);
      const rightAlt = getAlternativeModeReadiness(right);
      const leftStage = getReadinessStageOrder(leftAlt?.status);
      const rightStage = getReadinessStageOrder(rightAlt?.status);
      if (rightStage !== leftStage) return rightStage - leftStage;
      const leftScore = Number(leftAlt?.score || 0);
      const rightScore = Number(rightAlt?.score || 0);
      if (Number.isFinite(rightScore) && Number.isFinite(leftScore) && rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return String(left?.symbol || "").localeCompare(String(right?.symbol || ""));
    });
  targets.forEach(({ countEl, watchEl, blockedEl, limitedEl }) => {
    setElementTextIfChanged(countEl, readyBots.length === 1 ? "1 actionable now" : `${readyBots.length} actionable now`);
    countEl.classList.toggle("ready-trade-count--active", readyBots.length > 0);
    setElementHtmlIfChanged(watchEl, `Watch <strong>${watchCount}</strong>`);
    setElementHtmlIfChanged(blockedEl, `Blocked <strong>${blockedCount}</strong>`);
    setElementHtmlIfChanged(limitedEl, `Preview/Stale <strong>${limitedCount}</strong>`);
  });

  const blockedReadyMarkup = blockedReadyBots.length ? `
    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">Setup Ready / Opening Blocked</p>
        <span class="text-[11px] text-slate-400">${blockedReadyBots.length}</span>
      </div>
      ${blockedReadyBots.map((bot) => {
        const setup = getSetupReadiness(bot);
        const execution = getExecutionViability(bot);
        const freshness = getReadinessFreshnessMeta(bot);
        const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
        const score = Number(setup.score);
        let direction = normalizeMarketStateHint(setup.direction || bot?.price_action_direction || bot?.mode);
        if (direction === "neutral" && _prevReadyBotDirections[bot.id]) direction = _prevReadyBotDirections[bot.id];
        if (direction !== "neutral") _prevReadyBotDirections[bot.id] = direction;
        const setupText = String(setup.reasonText || "Ready setup").trim();
        const setupDetail = String(setup.detail || "Setup is analytically ready.").trim();
        const blockedText = String(execution.reasonText || "Opening blocked").trim();
        const blockedDetail = String(execution.detail || "Opening is temporarily blocked.").trim();
        const updatedText = setup.updatedAt ? formatFeedClock(setup.updatedAt) : "Live";
        const detailText = sourceMeta?.detail ? `${sourceMeta.detail} ${setupDetail} ${blockedDetail}`.trim() : `${setupDetail} ${blockedDetail}`.trim();
        const title = [setupText, blockedText, detailText].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
        const cardToneClass = sourceMeta
          ? "ready-trade-card--neutral"
          : direction === "long"
          ? "ready-trade-card--long"
          : direction === "short"
            ? "ready-trade-card--short"
            : "ready-trade-card--neutral";
        return `
          <article class="ready-trade-card ready-trade-setup-card ${cardToneClass}">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-amber-200 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                    ${escapeHtml(bot.symbol)}
                  </button>
                  <span class="inline-flex items-center rounded-full border border-amber-300/35 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100">
                    Ready setup
                  </span>
                  ${renderReadyTradeSourceBadge(bot, symbolContext)}
                  <span class="inline-flex items-center rounded-full border border-red-300/35 bg-red-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-red-100">
                    ${escapeHtml(blockedText)}
                  </span>
                </div>
                <p class="mt-2 text-sm font-medium text-amber-100">${escapeHtml(setupText)}</p>
                <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(detailText, 120))}</p>
                ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
              </div>
              <div class="text-right shrink-0">
                <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">${Number.isFinite(score) ? escapeHtml(`Score ${score.toFixed(0)}`) : "Blocked"}</div>
                <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";
  const marginWarningMarkup = marginWarningBots.length ? `
    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">Setup Ready / Margin Warning</p>
        <span class="text-[11px] text-slate-400">${marginWarningBots.length}</span>
      </div>
      ${marginWarningBots.map((bot) => {
        const setup = getSetupReadiness(bot);
        const execution = getExecutionViability(bot);
        const freshness = getReadinessFreshnessMeta(bot);
        const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
        const score = Number(setup.score || bot?.setup_ready_score);
        let direction = normalizeMarketStateHint(setup.direction || bot?.price_action_direction || bot?.mode);
        if (direction === "neutral" && _prevReadyBotDirections[bot.id]) direction = _prevReadyBotDirections[bot.id];
        if (direction !== "neutral") _prevReadyBotDirections[bot.id] = direction;
        const stageText = formatReadinessStageLabel(setup.status || "trigger_ready");
        const setupText = String(setup.reasonText || "Setup ready").trim();
        const setupDetail = String(setup.detail || "Setup is analytically ready.").trim();
        const warningDetail = String(execution.detail || "Free account margin is tight right now.").trim();
        const updatedText = setup.updatedAt ? formatFeedClock(setup.updatedAt) : "Live";
        const detailText = sourceMeta?.detail ? `${sourceMeta.detail} ${setupDetail} ${warningDetail}`.trim() : `${setupDetail} ${warningDetail}`.trim();
        const title = [setupText, "Margin Warning", detailText].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
        const cardToneClass = sourceMeta
          ? "ready-trade-card--neutral"
          : direction === "long"
          ? "ready-trade-card--long"
          : direction === "short"
            ? "ready-trade-card--short"
            : "ready-trade-card--neutral";
        return `
          <article class="ready-trade-card ready-trade-setup-card ${cardToneClass}">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-amber-200 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                    ${escapeHtml(bot.symbol)}
                  </button>
                  <span class="inline-flex items-center rounded-full border border-amber-300/35 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100">
                    Setup Ready
                  </span>
                  ${renderReadyTradeSourceBadge(bot, symbolContext)}
                  <span class="inline-flex items-center rounded-full border border-amber-300/35 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100">
                    Margin Warning
                  </span>
                  ${setup.status && !isTriggerReadyStatus(setup.status) ? `<span class="inline-flex items-center rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-100">${escapeHtml(stageText)}</span>` : ""}
                </div>
                <p class="mt-2 text-sm font-medium text-amber-100">${escapeHtml(setupText)}</p>
                <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(detailText, 120))}</p>
                ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
              </div>
              <div class="text-right shrink-0">
                <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">${Number.isFinite(score) ? escapeHtml(`Score ${score.toFixed(0)}`) : "Margin"}</div>
                <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";
  const armedMarkup = armedBots.length ? `
    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">Armed / Near Trigger</p>
        <span class="text-[11px] text-slate-400">${armedBots.length}</span>
      </div>
      ${armedBots.map((bot) => {
        const setup = getSetupReadiness(bot);
        const freshness = getReadinessFreshnessMeta(bot);
        const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
        const score = Number(setup.score);
        const updatedText = setup.updatedAt ? formatFeedClock(setup.updatedAt) : "Live";
        const detailText = sourceMeta?.detail ? `${sourceMeta.detail} ${String(setup.detail || "Developing setup near trigger.").trim()}`.trim() : String(setup.detail || "Developing setup near trigger.").trim();
        const title = [setup.reasonText || "Armed setup", detailText].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
        return `
          <article class="ready-trade-card ready-trade-setup-card ready-trade-card--neutral">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-cyan-200 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                    ${escapeHtml(bot.symbol)}
                  </button>
                  ${renderReadyTradeSourceBadge(bot, symbolContext)}
                  <span class="inline-flex items-center rounded-full border border-cyan-300/35 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-100">
                    Armed
                  </span>
                </div>
                <p class="mt-2 text-sm font-medium text-cyan-100">${escapeHtml(String(setup.reasonText || "Developing setup").trim())}</p>
                <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(detailText, 120))}</p>
                ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
              </div>
              <div class="text-right shrink-0">
                <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">${Number.isFinite(score) ? escapeHtml(`Score ${score.toFixed(0)}`) : "Armed"}</div>
                <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";
  const lateMarkup = lateBots.length ? `
    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-orange-300">Late / Decayed</p>
        <span class="text-[11px] text-slate-400">${lateBots.length}</span>
      </div>
      ${lateBots.map((bot) => {
        const setup = getSetupReadiness(bot);
        const freshness = getReadinessFreshnessMeta(bot);
        const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
        const score = Number(setup.score);
        const updatedText = setup.updatedAt ? formatFeedClock(setup.updatedAt) : "Live";
        const detailText = sourceMeta?.detail ? `${sourceMeta.detail} ${String(setup.detail || "The move is too extended to treat as a fresh trigger.").trim()}`.trim() : String(setup.detail || "The move is too extended to treat as a fresh trigger.").trim();
        const title = [setup.reasonText || "Late setup", detailText].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
        return `
          <article class="ready-trade-card ready-trade-setup-card ready-trade-card--neutral">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-orange-200 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                    ${escapeHtml(bot.symbol)}
                  </button>
                  ${renderReadyTradeSourceBadge(bot, symbolContext)}
                  <span class="inline-flex items-center rounded-full border border-orange-300/35 bg-orange-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-orange-100">
                    Late
                  </span>
                </div>
                <p class="mt-2 text-sm font-medium text-orange-100">${escapeHtml(String(setup.reasonText || "Late / decayed").trim())}</p>
                <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(detailText, 120))}</p>
                ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
              </div>
              <div class="text-right shrink-0">
                <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-orange-300">${Number.isFinite(score) ? escapeHtml(`Score ${score.toFixed(0)}`) : "Late"}</div>
                <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";
  const alternativeModeMarkup = alternativeModeBots.length ? `
    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">Cross-Mode Preview</p>
        <span class="text-[11px] text-slate-400">${alternativeModeBots.length}</span>
      </div>
      ${alternativeModeBots.map((bot) => {
        const setup = getSetupReadiness(bot);
        const alt = getAlternativeModeReadiness(bot);
        const liveIntent = getLiveExecutionIntentMeta(bot);
        const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
        const freshness = getReadinessFreshnessMeta({}, {
          sourceKind: alt?.sourceKind,
          previewState: alt?.previewState,
          ageSec: alt?.ageSec,
        });
        const score = Number(alt?.score);
        const scoreText = Number.isFinite(score) ? `Score ${score.toFixed(0)}` : formatReadinessStageLabel(alt?.status);
        const configuredText = String(setup.reasonText || humanizeReason(setup.reason || setup.status || "watch")).trim();
        const alternativeText = String(alt?.reasonText || humanizeReason(alt?.reason || alt?.status || "watch")).trim();
        const executionText = alt?.executionBlocked
          ? String(alt?.executionReasonText || humanizeReason(alt?.executionReason || "opening_blocked")).trim()
          : (isTriggerReadyStatus(alt?.status) ? "Actionable if you switch" : "Developing if you switch");
        const updatedText = alt?.updatedAt ? formatFeedClock(alt.updatedAt) : "Live";
        const stageText = formatReadinessStageLabel(alt?.status);
        const summaryText = `${liveIntent?.label || `Current ${formatBotModeLabel(getConfiguredModeForUi(bot))}`}. If switched: ${alt?.label || formatBotModeLabel(alt?.mode || "")} ${stageText}. ${executionText}`.trim();
        const title = [
          `Configured mode: ${formatBotModeLabel(getConfiguredModeForUi(bot))} • ${configuredText}`,
          `Alternative mode ${stageText.toLowerCase()}: ${alt?.label || formatBotModeLabel(alt?.mode || "")} • ${alternativeText}`,
          executionText,
          sourceMeta?.detail || "",
          alt?.detail || "",
        ].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
        return `
          <article class="ready-trade-card ready-trade-setup-card ready-trade-card--neutral">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-cyan-200 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                    ${escapeHtml(bot.symbol)}
                  </button>
                  ${liveIntent ? `<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${liveIntent.toneClass}" title="${escapeHtml(liveIntent.title)}">${escapeHtml(liveIntent.label)}</span>` : ""}
                  ${renderReadyTradeSourceBadge(bot, symbolContext)}
                  <span class="inline-flex items-center rounded-full border border-cyan-300/35 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-100">
                    Cross-Mode Preview
                  </span>
                </div>
                <p class="mt-2 text-sm font-medium text-cyan-100">${escapeHtml(alt?.label || formatBotModeLabel(alt?.mode || ""))}</p>
                <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(summaryText, 120))}</p>
                ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
              </div>
              <div class="text-right shrink-0">
                <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">${escapeHtml(scoreText)}</div>
                <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
                <button type="button" onclick="reviewSuggestedMode('${bot.id}', '${alt?.mode || ""}', '${alt?.rangeMode || ""}')" class="mt-2 rounded-xl border border-cyan-400/25 bg-cyan-500/10 px-3 py-2 text-[11px] font-semibold text-cyan-100 hover:bg-cyan-500/20 transition">
                  Review Mode
                </button>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";

  if (!readyBots.length) {
    const emptyMarkup = `
      <div class="ready-trade-empty-state">
        <span class="ready-trade-empty-state__icon">◎</span>
        <strong>No actionable directional setups right now</strong>
      </div>
    ${marginWarningMarkup}
    ${armedMarkup}
    ${lateMarkup}
    ${blockedReadyMarkup}
    ${alternativeModeMarkup}`;
    targets.forEach(({ container }) => {
      setElementHtmlIfChanged(container, emptyMarkup);
    });
    return;
  }

  const readyMarkup = readyBots.map((bot) => {
    const setup = getSetupReadiness(bot);
    const freshness = getReadinessFreshnessMeta(bot);
    const sourceMeta = getReadyTradeSourceMeta(bot, symbolContext);
    const score = Number(setup.score);
    let direction = normalizeMarketStateHint(setup.direction || bot?.price_action_direction || bot?.mode);
    if (direction === "neutral" && _prevReadyBotDirections[bot.id]) direction = _prevReadyBotDirections[bot.id];
    if (direction !== "neutral") _prevReadyBotDirections[bot.id] = direction;
    const reasonText = String(setup.reasonText || "Enter now").trim();
    const detail = String(setup.detail || "Entry conditions favorable").trim();
    const updatedAt = String(setup.updatedAt || "").trim();
    const histEntry = _emergReadyHistory.find((entry) => {
      if (!entry?.still_ready) return false;
      const entryBotId = String(entry?.bot_id || "").trim();
      const botId = String(bot?.id || "").trim();
      if (entryBotId && botId) return entryBotId === botId;
      return String(entry?.symbol || "").trim().toUpperCase() === String(bot?.symbol || "").trim().toUpperCase();
    });
    const entryPrice = histEntry?.entry_price || parseFloat(bot?.market_data_price) || parseFloat(bot?.current_price) || parseFloat(bot?.exchange_mark_price) || 0;
    const entryPriceStr = _fmtReadyPrice(entryPrice);
    const directionClass = direction === "long"
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
      : direction === "short"
        ? "border-rose-400/30 bg-rose-500/10 text-rose-200"
        : "border-cyan-400/30 bg-cyan-500/10 text-cyan-200";
    const cardToneClass = sourceMeta
      ? "ready-trade-card--neutral"
      : direction === "long"
      ? "ready-trade-card--long"
      : direction === "short"
        ? "ready-trade-card--short"
        : "ready-trade-card--neutral";
    const scoreText = Number.isFinite(score) ? `Score ${score.toFixed(0)}` : "Ready";
    const updatedText = updatedAt ? formatFeedClock(updatedAt) : "Live";
    const detailText = sourceMeta?.detail ? `${sourceMeta.detail} ${detail}`.trim() : detail;
    const title = [reasonText, detailText].filter(Boolean).join(" • ").replace(/"/g, "&quot;");
    const isLiveExecution = String(bot?.status || "").trim().toLowerCase() === "running" && !sourceMeta;

    const isNewlyReady = !_prevReadyBotIds.has(bot.id);
    return `
      <article class="ready-trade-card${isLiveExecution ? " ready-trade-card--flashy" : ""}${isNewlyReady ? " ready-new-flash" : ""} ready-trade-setup-card ${cardToneClass}">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              ${isLiveExecution ? '<span class="ready-trade-card__beacon" aria-hidden="true"></span>' : ""}
              <button onclick="openBotDetailModal('${bot.id}')" class="text-left text-base font-semibold text-white hover:text-emerald-300 transition truncate max-w-[160px]" title="${escapeHtml(bot.symbol)}">
                ${escapeHtml(bot.symbol)}
              </button>
              <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${directionClass}">
                ${escapeHtml(direction === "neutral" ? "READY" : direction)}
              </span>
              ${renderReadyTradeSourceBadge(bot, symbolContext)}
              <span class="inline-flex items-center rounded-full border ${isLiveExecution ? "border-emerald-300/45 bg-emerald-500/15 text-emerald-50 shadow-[0_0_16px_rgba(16,185,129,0.18)]" : "border-slate-600/45 bg-slate-800/70 text-slate-200"} px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.18em]">
                ${escapeHtml(isLiveExecution ? "Actionable" : "Setup Ready")}
              </span>
            </div>
            <p class="mt-2 text-sm font-medium text-emerald-100">${escapeHtml(reasonText)}</p>
            <p class="mt-1 text-xs text-slate-300" title="${title}">${escapeHtml(truncateText(detailText, 120))}</p>
            ${freshness.label ? `<p class="mt-1 text-[11px] text-slate-500">${escapeHtml(freshness.label)}</p>` : ""}
          </div>
          <div class="text-right shrink-0">
            <div class="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-300">${escapeHtml(scoreText)}</div>
            <div class="mt-1 text-[11px] text-slate-400">${escapeHtml(updatedText)}</div>
          </div>
        </div>
        <div class="ready-trade-setup-card__metrics">
          <div class="ready-trade-setup-card__metric">
            <div class="ready-trade-setup-card__metric-label">Direction</div>
            <div class="ready-trade-setup-card__metric-value">${escapeHtml(direction === "neutral" ? "Neutral bias" : direction.toUpperCase())}</div>
          </div>
          ${entryPriceStr ? `<div class="ready-trade-setup-card__metric">
            <div class="ready-trade-setup-card__metric-label">Price @ Ready</div>
            <div class="ready-trade-setup-card__metric-value text-amber-300">$${escapeHtml(entryPriceStr)}</div>
          </div>` : ""}
          <div class="ready-trade-setup-card__metric">
            <div class="ready-trade-setup-card__metric-label">Updated</div>
            <div class="ready-trade-setup-card__metric-value">${escapeHtml(updatedText)}</div>
          </div>
        </div>
      </article>
    `;
  }).join("");

  targets.forEach(({ container }) => {
    setElementHtmlIfChanged(container, `${readyMarkup}${marginWarningMarkup}${armedMarkup}${lateMarkup}${blockedReadyMarkup}${alternativeModeMarkup}`);
  });
  // Track ready bot IDs for next render — new ones get the flash class
  _prevReadyBotIds = new Set(readyBots.map(b => b.id));
}

// ── Market Heat Map ──
let _heatMapData = [];

let _refreshHeatMapPromise = null;
async function refreshHeatMap() {
  if (_refreshHeatMapPromise) return _refreshHeatMapPromise;
  _refreshHeatMapPromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/neutral-scan");
      _heatMapData = (data.results || []).sort((a, b) =>
        (b.volume_24h_usdt || 0) - (a.volume_24h_usdt || 0)
      );
      renderHeatMap();
    } catch (e) { console.error("Heat map refresh failed:", e); }
    finally { _refreshHeatMapPromise = null; }
  })();
  return _refreshHeatMapPromise;
}

function renderHeatMap() {
  const container = $("symbol-heat-map");
  if (!container) return;
  if (!_heatMapData.length) {
    setElementHtmlIfChanged(container, '<div class="text-center text-slate-500 text-xs py-4">No data</div>');
    return;
  }
  const html = '<div class="heatmap-grid">' + _heatMapData.map(r => {
    const score = Number(r.neutral_score || 0);
    const mode = r.recommended_mode || "neutral";
    const trend = r.trend || "neutral";
    const vol = r.volume_24h_usdt || 0;
    const fr = r.funding_rate || 0;
    let bg, textCls;
    if (score >= 75) { bg = "rgba(16,185,129,0.25)"; textCls = "text-emerald-300"; }
    else if (score >= 60) { bg = "rgba(6,182,212,0.20)"; textCls = "text-cyan-300"; }
    else if (score >= 45) { bg = "rgba(245,158,11,0.20)"; textCls = "text-amber-300"; }
    else { bg = "rgba(100,116,139,0.15)"; textCls = "text-slate-400"; }
    const arrow = trend === "uptrend" ? "\u2191" : trend === "downtrend" ? "\u2193" : "\u2192";
    const arrowCls = trend === "uptrend" ? "text-emerald-400" : trend === "downtrend" ? "text-red-400" : "text-slate-500";
    const modeLetter = {long:"L",short:"S",neutral:"N",neutral_classic_bybit:"NC",scalp_pnl:"SP"}[mode] || "N";
    const modeCls = {long:"text-emerald-400",short:"text-red-400"}[mode] || "text-cyan-400";
    const safeResult = JSON.stringify(r).replace(/'/g, "&#39;");
    const title = `${r.symbol}  Score: ${score.toFixed(0)} | Mode: ${mode}  ADX: ${(r.adx||0).toFixed(0)} | ATR: ${((r.atr_pct||0)*100).toFixed(2)}%  Vol: $${formatVolume(vol)} | FR: ${(fr*100).toFixed(4)}%  Trend: ${trend} | Regime: ${r.regime || "-"}`;
    return `<div class="heatmap-cell" style="background:${bg}" title="${escapeHtml(title)}" onclick='useScanResult(JSON.parse(this.dataset.r))' data-r='${safeResult}'>
      <div class="heatmap-cell__symbol">${escapeHtml(r.symbol.replace("USDT",""))}</div>
      <div class="heatmap-cell__score ${textCls}">${score.toFixed(0)}</div>
      <div class="heatmap-cell__meta"><span class="${arrowCls}">${arrow}</span> <span class="${modeCls}">${modeLetter}</span></div>
    </div>`;
  }).join("") + '</div>';
  setElementHtmlIfChanged(container, html);
  const updEl = $("heatmap-updated");
  if (updEl) updEl.textContent = new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
}

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
      <button type="button" onclick="scanSymbol('${s.symbol}', false)" 
        class="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded transition flex items-center gap-1"
        title="Scanned ${ageText} ago - click to scan again">
        <span>${s.symbol}</span>
        <span class="text-slate-500 text-[10px]">${ageText}</span>
      </button>
    `;
  }).join('');
}



/**
 * Scan a specific symbol and optionally scroll to the scanner.
 */

function smartScoreBadge(score, pumpRisk, details) {
  if (score === undefined || score === null) return `<span class="text-slate-500">-</span>`;
  let color = "text-slate-400";
  if (score >= 80) color = "text-emerald-400 font-bold";
  else if (score >= 60) color = "text-emerald-500";
  else if (score >= 31) color = "text-amber-400";
  else if (score <= 30) color = "text-red-400";

  let riskBadge = "";
  if (pumpRisk === true) {
    riskBadge = `<span class="text-[9px] bg-red-900/50 text-red-300 px-1 rounded ml-1" title="High Pump Risk">⚠️</span>`;
  }

  const tooltip = (details || []).join("&#10;").replace(/"/g, "&quot;");

  return `<span class="${color} cursor-help border-b border-dotted border-slate-500" title="${tooltip}">${score.toFixed(1)}</span>${riskBadge}`;
}

function renderEntryZoneCard(result) {
  const card = $("entry-zone-card");
  if (!card) return;

  const ez = result.entry_zone;
  if (!ez) {
    card.classList.add("hidden");
    return;
  }

  // Verdict styling
  const verdictStyles = {
    GOOD: { bg: "bg-emerald-500/15", border: "border-emerald-500/40", text: "text-emerald-400", icon: "🟢", glow: "shadow-emerald-500/10" },
    CAUTION: { bg: "bg-amber-500/15", border: "border-amber-500/40", text: "text-amber-400", icon: "🟡", glow: "shadow-amber-500/10" },
    AVOID: { bg: "bg-red-500/15", border: "border-red-500/40", text: "text-red-400", icon: "🔴", glow: "shadow-red-500/10" },
  };
  const vs = verdictStyles[ez.verdict] || verdictStyles.CAUTION;

  // Risk meter
  const riskPct = Math.max(5, Math.min(100, ez.score));
  const riskColor = ez.risk_level === "LOW" ? "bg-emerald-500" : ez.risk_level === "MEDIUM" ? "bg-amber-500" : "bg-red-500";

  // Mode display name
  const modeNames = {
    neutral: "Neutral Dynamic",
    neutral_classic_bybit: "Neutral Classic",
    long: "Long",
    short: "Short",
    scalp_pnl: "Scalp PnL",
    scalp_market: "Scalp Market",
    dynamic: "Dynamic",
  };
  const ss = ez.suggested_settings || {};
  const modeName = modeNames[ss.mode] || ss.mode || "-";

  // Build reasons HTML
  const reasonsHtml = (ez.reasons || []).map(r => {
    const isPositive = r.includes("✅");
    const color = isPositive ? "text-emerald-400" : "text-slate-300";
    return `<li class="${color} text-xs leading-relaxed">${r}</li>`;
  }).join("");

  // Build warnings HTML
  const warningsHtml = (ez.warnings || []).map(w => {
    const isRed = w.includes("🔴");
    const color = isRed ? "text-red-400" : "text-amber-400";
    return `<li class="${color} text-xs leading-relaxed">${w}</li>`;
  }).join("");

  // Funding & 24h change display
  const fr = result.funding_rate;
  const frStr = fr != null ? `${(fr * 100).toFixed(4)}%` : "-";
  const pc = result.price_change_24h_pct;
  const pcStr = pc != null ? `${(pc * 100).toFixed(2)}%` : "-";
  const pcColor = pc != null ? (pc >= 0 ? "text-emerald-400" : "text-red-400") : "text-slate-400";

  card.innerHTML = `
    <div class="${vs.bg} ${vs.border} border rounded-xl p-4 shadow-lg ${vs.glow}" style="animation: fadeIn 0.3s ease-out">
      <!-- Header -->
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="text-lg">${vs.icon}</span>
          <h3 class="text-sm font-bold text-white">Entry Zone Analysis</h3>
          <span class="text-xs ${vs.text} font-bold">${result.symbol}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="px-2.5 py-1 rounded-full text-xs font-bold ${vs.text} ${vs.bg} border ${vs.border}">
            ${ez.verdict}
          </span>
          <span class="text-xs text-slate-500">Score: ${ez.score}/100</span>
        </div>
      </div>

      <!-- Risk Meter -->
      <div class="mb-3">
        <div class="flex items-center justify-between text-[10px] text-slate-500 mb-1">
          <span>Risk Level</span>
          <span class="font-medium ${vs.text}">${ez.risk_level}</span>
        </div>
        <div class="h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div class="h-full ${riskColor} rounded-full transition-all duration-500" style="width: ${riskPct}%"></div>
        </div>
      </div>

      <!-- Two Column Layout -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <!-- Left: Analysis -->
        <div>
          ${reasonsHtml ? `
          <div class="mb-2">
            <h4 class="text-[10px] uppercase text-slate-500 font-medium mb-1">Analysis</h4>
            <ul class="space-y-0.5 pl-0 list-none">${reasonsHtml}</ul>
          </div>` : ""}
          ${warningsHtml ? `
          <div>
            <h4 class="text-[10px] uppercase text-slate-500 font-medium mb-1">Warnings</h4>
            <ul class="space-y-0.5 pl-0 list-none">${warningsHtml}</ul>
          </div>` : ""}
        </div>

        <!-- Right: Suggested Settings -->
        <div class="bg-slate-800/60 rounded-lg p-3">
          <h4 class="text-[10px] uppercase text-slate-500 font-medium mb-2">Suggested Settings</h4>
          <div class="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <div><span class="text-slate-500">Mode:</span> <span class="text-white font-medium">${modeName}</span></div>
            <div><span class="text-slate-500">Range:</span> <span class="text-white font-medium">${ss.range_mode || "-"}</span></div>
            <div><span class="text-slate-500">Leverage:</span> <span class="text-white font-medium">${ss.leverage || "-"}x</span></div>
            <div><span class="text-slate-500">Profile:</span> <span class="text-white font-medium">${ss.profile || "-"}</span></div>
            <div><span class="text-slate-500">Grids:</span> <span class="text-white font-medium">${ss.grid_levels || "-"}</span></div>
            <div><span class="text-slate-500">Funding:</span> <span class="text-white font-medium">${frStr}</span></div>
            <div><span class="text-slate-500">24h Chg:</span> <span class="font-medium ${pcColor}">${pcStr}</span></div>
            <div><span class="text-slate-500">Best for:</span> <span class="text-white font-medium">${ez.best_for || "-"}</span></div>
          </div>
          <div class="mt-2 pt-2 border-t border-slate-700">
            <p class="text-[10px] text-slate-500 italic">${result.mode_reasoning || ""}</p>
          </div>
        </div>
      </div>
    </div>
  `;
  card.classList.remove("hidden");
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
  tbody.innerHTML = `
    <div class="scanner-empty-state">
      <strong>Scanning...</strong>
      Pulling the latest neutral scanner snapshot.
    </div>
  `;

  try {
    const data = await fetchJSON(url);
    const results = data.results || [];
    if (results.length === 0) {
      tbody.innerHTML = `
        <div class="scanner-empty-state">
          <strong>No results found</strong>
          Try a different symbol set or broaden the scan universe.
        </div>
      `;
      return;
    }
    tbody.innerHTML = results.map(r => {
      const range = r.suggested_range || {};
      const rangeStr = `${formatNumber(range.lower, 2)} - ${formatNumber(range.upper, 2)}`;
      const recMode = r.recommended_mode || "neutral";
      const recRangeMode = r.recommended_range_mode || "fixed";
      const riskData = calculateRisk(r);
      return `
        <article class="scanner-result-row">
          <div class="scanner-result-row__layout">
            <div>
              <div class="scanner-result-row__headline">
                <span class="font-semibold text-white truncate max-w-[160px]" title="${escapeHtml(r.symbol || "-")}">${escapeHtml(r.symbol || "-")}</span>
                ${regimeBadge(r.regime)}
                ${recommendedModeBadge(recMode, recRangeMode)}
              </div>
              <div class="scanner-result-row__meta mt-2">
                Trend ${escapeHtml(String(r.trend || "neutral"))} • Speed ${escapeHtml(String(r.speed || "-"))} • Range ${escapeHtml(rangeStr)}
              </div>
            </div>

            <div class="scanner-result-row__grid">
              <div class="scanner-result-box">
                <div class="scanner-result-box__label">Risk</div>
                <div class="scanner-result-box__value">${riskBadge(riskData)} ${smartScoreBadge(r.smart_score, r.smart_pump_risk, r.smart_details)}</div>
                <div class="scanner-result-box__hint">ADX ${formatNumber(r.adx, 1)}</div>
              </div>
              <div class="scanner-result-box">
                <div class="scanner-result-box__label">Volatility</div>
                <div class="scanner-result-box__value">ATR ${formatPercent(r.atr_pct)} • BBW ${formatPercent(r.bbw_pct)}</div>
                <div class="scanner-result-box__hint">Vol ${formatVolume(r.volume_24h_usdt)}</div>
              </div>
              <div class="scanner-result-box">
                <div class="scanner-result-box__label">Flow</div>
                <div class="scanner-result-box__value">${trendBadge(r.trend || 'neutral')} <span class="text-xs text-slate-300">${escapeHtml(String(r.speed || "-"))}</span></div>
                <div class="scanner-result-box__hint">Velocity ${formatVelocity(r.price_velocity, r.velocity_display)} • BTC ${escapeHtml(String(r.btc_correlation ?? "-"))}</div>
              </div>
            </div>

            <div class="scanner-result-row__actions">
            <button type="button" onclick='useScanResult(${JSON.stringify(r)})' class="scanner-use-btn">Use</button>
            </div>
          </div>
        </article>
      `;
    }).join("");

    // Show entry zone card for single-symbol scans
    const entryCard = $("entry-zone-card");
    if (entryCard) {
      const isSingleSymbol = results.length === 1;
      if (isSingleSymbol && results[0].entry_zone) {
        renderEntryZoneCard(results[0]);
      } else {
        entryCard.classList.add("hidden");
      }
    }
  } catch (error) {
    tbody.innerHTML = `
      <div class="scanner-empty-state">
        <strong>Scan failed</strong>
        ${escapeHtml(error.message)}
      </div>
    `;
    const entryCard = $("entry-zone-card");
    if (entryCard) entryCard.classList.add("hidden");
  }
}

function getBotPresetConfidenceMeta(confidence) {
  const normalized = String(confidence || "").trim().toLowerCase();
  if (normalized === "high") return { chip: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100", label: "HIGH" };
  if (normalized === "medium") return { chip: "border-amber-400/30 bg-amber-500/12 text-amber-100", label: "MEDIUM" };
  return { chip: "border-slate-700 bg-slate-900/80 text-slate-200", label: "LOW" };
}

function renderBotPresetSummary() {
  updateBotPresetSectionVisibility();
  const section = $("bot-preset-section");
  if (!section || section.classList.contains("hidden")) return;

  const nameEl = $("bot-preset-summary-name");
  const confidenceEl = $("bot-preset-summary-confidence");
  const metaEl = $("bot-preset-summary-meta");
  const reasonEl = $("bot-preset-summary-reason");
  const reasonsEl = $("bot-preset-summary-reasons");
  const signalsEl = $("bot-preset-summary-signals");
  const fieldsEl = $("bot-preset-summary-fields");
  const alternativesEl = $("bot-preset-summary-alternatives");
  if (isEditingExistingBotForm() && mainBotFormContext) {
    const context = getPresetContextBits(mainBotFormContext);
    renderPresetContext("main", mainBotFormContext);
    if (nameEl) nameEl.textContent = context.title;
    if (confidenceEl) {
      confidenceEl.className = "inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] font-semibold text-slate-200";
      confidenceEl.textContent = "READ ONLY";
    }
    if (metaEl) metaEl.textContent = context.summary;
    if (reasonEl) reasonEl.textContent = context.note;
    if (reasonsEl) reasonsEl.innerHTML = "";
    if (signalsEl) signalsEl.innerHTML = "";
    if (fieldsEl) fieldsEl.innerHTML = "";
    if (alternativesEl) alternativesEl.innerHTML = "";
    renderBotPresetSizingWarning();
    return;
  }
  const preset = botPresetState.appliedPreset || getBotPresetById(botPresetState.selectedPreset) || getBotPresetById("manual_blank");
  if (!preset) return;

  if ($("bot-preset-select")) {
    $("bot-preset-select").value = String(preset?.preset_id || "manual_blank");
  }
  if (nameEl) nameEl.textContent = String(preset?.name || "Manual Blank");
  if (confidenceEl) {
    const confidence = getBotPresetConfidenceMeta(botPresetState.confidence || "low");
    confidenceEl.className = `inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${confidence.chip}`;
    confidenceEl.textContent = confidence.label;
  }
  if (metaEl) {
    const metaBits = [];
    const presetType = String(preset?.preset_type || "built_in").trim().toLowerCase();
    metaBits.push(presetType === "custom" ? "Custom preset" : "Built-in preset");
    if (preset?.symbol_hint) metaBits.push(`symbol ${String(preset.symbol_hint)}`);
    if (preset?.mode_hint) metaBits.push(`mode ${String(preset.mode_hint)}`);
    if (preset?.session_oriented) metaBits.push("session-oriented");
    if (preset?.session_time_safety?.requires_time_selection) metaBits.push("fresh time required");
    if (preset?.updated_at) metaBits.push(`updated ${formatTime(preset.updated_at)}`);
    if (preset?.source_bot_id) metaBits.push(`source bot ${String(preset.source_bot_id)}`);
    metaEl.textContent = metaBits.join(" • ");
  }
  const sourcePrefix = botPresetState.source === "auto" ? "Auto recommendation applied. " : "Preset applied. ";
  if (reasonEl) {
    if (botPresetState.autoReason) {
      reasonEl.textContent = `${sourcePrefix}${botPresetState.autoReason}`;
    } else if (preset?.session_time_safety?.requires_time_selection) {
      reasonEl.textContent = "Preset applied. Session timer stays enabled, but you must pick fresh start/stop times before save.";
    } else if (preset?.session_time_safety?.duration_min) {
      reasonEl.textContent = `Preset applied. Session timer refreshed to a new ${preset.session_time_safety.duration_min} minute window from now.`;
    } else {
      reasonEl.textContent = "Preset-applied values remain editable before save.";
    }
  }
  if (reasonsEl) {
    const reasons = (botPresetState.autoReasons?.length ? botPresetState.autoReasons : (preset?.reasons || [])).slice(0, 4);
    reasonsEl.innerHTML = reasons.map((reason) => (
      `<span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-200">${escapeHtml(String(reason || ""))}</span>`
    )).join("");
  }
  if (signalsEl) {
    const matchedSignals = Array.isArray(botPresetState.matchedSignals) ? botPresetState.matchedSignals.slice(0, 5) : [];
    signalsEl.innerHTML = matchedSignals.map((signal) => (
      `<span class="inline-flex items-center rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2 py-1 text-[11px] text-cyan-100">${escapeHtml(formatWatchdogLabel(String(signal || "")))}</span>`
    )).join("");
  }
  if (fieldsEl) {
    const keyFields = Array.isArray(preset?.key_fields) ? preset.key_fields : [];
    fieldsEl.innerHTML = keyFields.map((item) => `
      <div class="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
        <div class="text-[10px] uppercase tracking-[0.16em] text-slate-500">${escapeHtml(String(item?.label || item?.field || ""))}</div>
        <div class="mt-1 text-sm font-medium text-white">${escapeHtml(getBotPresetFieldValueForSummary(item?.field, item?.value))}</div>
      </div>
    `).join("");
  }
  if (alternativesEl) {
    const alternatives = Array.isArray(botPresetState.alternativePresets) ? botPresetState.alternativePresets.slice(0, 2) : [];
    alternativesEl.innerHTML = alternatives.length
      ? `Alternatives: ${alternatives.map((item) => `${escapeHtml(String(item?.name || item?.preset_id || ""))} (${escapeHtml(String(item?.reason || ""))})`).join(" • ")}`
      : "";
  }
  renderBotPresetSizingWarning();
}

function renderBotPresetSizingWarning() {
  const warningEl = $("bot-preset-sizing-warning");
  if (!warningEl) return;
  const viability = getBotPresetSizingViability();
  const warningText = formatBotPresetSizingWarningText(viability);
  if (!warningText) {
    warningEl.textContent = "";
    warningEl.classList.add("hidden");
    return;
  }
  warningEl.textContent = warningText;
  warningEl.classList.remove("hidden");
}

function renderSessionTimerRuntimeSummary(bot = {}, scope = "main") {
  const stateEl = getScopedElement(scope, "bot-session-runtime-state");
  const startsEl = getScopedElement(scope, "bot-session-runtime-starts");
  const endsEl = getScopedElement(scope, "bot-session-runtime-ends");
  const noNewEl = getScopedElement(scope, "bot-session-runtime-no-new");
  const endModeEl = getScopedElement(scope, "bot-session-runtime-end-mode");
  const graceEl = getScopedElement(scope, "bot-session-runtime-grace");
  if (!stateEl || !startsEl || !endsEl || !noNewEl || !endModeEl || !graceEl) return;

  const enabled = !!bot.session_timer_enabled;
  stateEl.textContent = enabled ? humanizeReason(bot.session_timer_state || "inactive") : "Inactive";
  startsEl.textContent = enabled ? formatTime(bot.session_start_at) : "-";
  endsEl.textContent = enabled ? formatTime(bot.session_stop_at) : "-";
  endModeEl.textContent = enabled ? humanizeReason(bot.session_end_mode || "hard_stop") : "-";

  let noNewText = "Inactive";
  if (enabled && bot.session_timer_no_new_entries_active) {
    noNewText = "Active";
  } else if (enabled && Number.isFinite(Number(bot.session_timer_pre_stop_in_sec)) && Number(bot.session_timer_pre_stop_in_sec) > 0) {
    noNewText = `In ${formatCountdownSeconds(bot.session_timer_pre_stop_in_sec)}`;
  }
  noNewEl.textContent = noNewText;

  let graceText = "-";
  if (enabled && bot.session_timer_complete) {
    graceText = bot.session_timer_completed_at
      ? `Done ${formatTime(bot.session_timer_completed_at)}`
      : "Complete";
  } else if (enabled && bot.session_timer_grace_active) {
    graceText = Number.isFinite(Number(bot.session_timer_grace_remaining_sec))
      ? `${formatCountdownSeconds(bot.session_timer_grace_remaining_sec)} left`
      : "Active";
  }
  graceEl.textContent = graceText;
}

function allPnlBuildCardHTML(log) {
  const pnl = formatPnL(log.realized_pnl);
  const balance = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : "-";
  const mode = log.bot_mode || "-";
  const rangeMode = log.bot_range_mode || "-";
  const modeClass = ALL_PNL_MODE_COLORS[mode] || "bg-slate-700 text-slate-400";
  const rangeClass = ALL_PNL_RANGE_COLORS[rangeMode] || "bg-slate-700 text-slate-400";
  const investment = log.bot_investment ? `$${formatNumber(log.bot_investment, 0)}` : "-";
  const leverage = log.bot_leverage ? `${log.bot_leverage}x` : "-";
  const botIdShort = log.bot_id ? log.bot_id.slice(0, 8) : "-";

  return `<div class="allpnl-card__header">
      <div class="min-w-0">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-sm font-semibold text-white">${escapeHtml(log.symbol || "-")}</span>
          <span class="text-[10px] text-slate-400">${escapeHtml(log.side || "-")}</span>
          <span class="px-1.5 py-0.5 ${modeClass} rounded text-[10px]">${escapeHtml(mode)}</span>
          <span class="px-1.5 py-0.5 ${rangeClass} rounded text-[10px]">${escapeHtml(rangeMode)}</span>
        </div>
        <div class="text-[10px] text-slate-500 mt-0.5">${allPnlFormatCompactTime(log.time)}</div>
      </div>
      <div class="text-right">
        <div class="allpnl-card__pnl ${pnl.class}">${pnl.text}</div>
        <div class="text-[10px] text-slate-400 mt-0.5">Bal <span class="text-white font-medium">${balance}</span></div>
      </div>
    </div>
    <div class="allpnl-card__meta">
      <span class="text-[10px] text-slate-500">${investment} @ ${leverage}</span>
      <span class="text-[10px] text-slate-600">&middot;</span>
      <span class="text-[10px] text-slate-600 font-mono">${escapeHtml(botIdShort)}</span>
    </div>`;
}

/**
 * Open the All PnL modal and load data.
 */
async function openAllPnlModal() {
  const modal = $("allPnlModal");
  if (!modal) return;

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  allPnlCurrentPage = 1;
  allPnlKnownRowIds.clear();

  await refreshAllPnlModal(true);
  startAllPnlAutoRefresh();

  if (allPnlLastUpdatedTimerId) clearInterval(allPnlLastUpdatedTimerId);
  allPnlLastUpdatedTimerId = setInterval(updateAllPnlLastUpdatedText, 5000);
}

/**
 * Close the All PnL modal.
 */

function renderFilteredLogView() {
  const box = document.getElementById('botLogBox');
  if (!box) return;

  const showAll = activeLogFilters.has('all');
  let filtered = showAll
    ? parsedLogLines
    : parsedLogLines.filter(l => activeLogFilters.has(l.category));

  // Symbol filter: if any symbol chips are active, only show matching symbols
  if (activeSymbolFilters.size > 0) {
    filtered = filtered.filter(l => activeSymbolFilters.has(l.symbol));
  }

  // Important-only: also filter by severity
  if (logImportantOnly) {
    filtered = filtered.filter(l =>
      LOG_IMPORTANT_SEVERITIES.has(l.severity) || LOG_IMPORTANT_CATEGORIES.has(l.category)
    );
  }

  // Search filter
  const term = logSearchTerm;
  if (term) {
    filtered = filtered.filter(l => l.raw.toLowerCase().includes(term));
  }

  // Update search count
  const searchCount = document.getElementById('logSearchCount');
  if (searchCount) {
    searchCount.textContent = term ? `${filtered.length} match${filtered.length !== 1 ? 'es' : ''}` : '';
  }

  if (filtered.length === 0) {
    const toastEl = document.getElementById('logCopyToast');
    const toastHtml = toastEl ? toastEl.outerHTML : '';
    box.innerHTML = '<div class="log-row"><span class="log-row__message" style="color:#64748b">' +
      (parsedLogLines.length === 0 ? '(No log content)' :
       term ? `(No matches for "${escapeHtml(term)}")` :
       '(No matching log lines for selected filters)') +
      '</span></div>' + toastHtml;
    return;
  }

  const parts = [];
  for (let i = 0; i < filtered.length; i++) {
    const l = filtered[i];
    const rowClass = l.severity !== 'info' ? ` log-row--${l.severity}` : '';
    // Show time portion (HH:MM:SS,mmm) with full timestamp on hover
    let tsHtml = '';
    if (l.timestamp) {
      const timePart = l.timestamp.slice(11); // "HH:MM:SS,mmm"
      tsHtml = `<span class="log-row__timestamp" title="${escapeHtml(l.timestamp)}">${escapeHtml(timePart)}</span>`;
    }
    const lvlClass = l.level ? ` log-row__level--${l.level.toLowerCase()}` : '';
    const lvlHtml = l.level ? `<span class="log-row__level${lvlClass}">${escapeHtml(l.level)}</span>` : '';
    const symText = l.symbol ? escapeHtml(l.symbol) : '';
    const symHtml = l.symbol ? `<span class="log-row__symbol">${term ? highlightSearchTerm(symText, term) : symText}</span>` : '';
    const msgText = escapeHtml(l.message);
    const msgHtml = `<span class="log-row__message">${term ? highlightSearchTerm(msgText, term) : msgText}</span>`;
    parts.push(`<div class="log-row${rowClass}">${tsHtml}${lvlHtml}${symHtml}${msgHtml}</div>`);
  }

  // Preserve the copy toast element
  const toastEl = document.getElementById('logCopyToast');
  const toastHtml = toastEl ? toastEl.outerHTML : '<span id="logCopyToast" class="log-copy-toast">Copied</span>';
  box.innerHTML = parts.join('') + toastHtml;

  // Auto-scroll to bottom (respects toggle)
  if (logAutoScroll) {
    setTimeout(() => { box.scrollTop = box.scrollHeight; }, 30);
  }
}

/**
 * Parse log text, update filter counts, and render.
 */

function renderLogLines(text) {
  const lines = text.split('\n').filter(l => l.trim());
  parsedLogLines = lines.map(parseLogLine);
  initLogFilterChips();
  updateFilterCounts();
  renderFilteredLogView();
}

/**
 * Load bot log from /api/bot/log and display in the modal.
 */
async function loadBotLog() {
  // Skip fetch when paused (user is reading/searching)
  if (logPaused) return;

  const box = $("botLogBox");
  const lastUpdate = $("botModalLastUpdate");
  const linesSelect = $("logLinesSelect");
  const scopeSelect = $("logScopeSelect");

  if (!box) return;

  const numLines = linesSelect ? linesSelect.value : 100;
  const scope = scopeSelect ? scopeSelect.value : "all";

  try {
    const res = await fetch(`/api/bot/log?lines=${numLines}&scope=${encodeURIComponent(scope)}&_ts=${Date.now()}`, { cache: "no-store" });
    const text = await res.text();

    if (res.ok) {
      const content = text || "(No log content)";
      renderLogLines(content);
    } else {
      box.innerHTML = `<div class="log-row"><span class="log-row__message" style="color:#f87171">Error (${res.status}): ${escapeHtml(text)}</span></div>`;
    }

    // Update last update time
    if (lastUpdate) {
      lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    }

    // Also update runner status
    updateRunnerStatus();
  } catch (e) {
    if (box) box.innerHTML = `<div class="log-row"><span class="log-row__message" style="color:#f87171">Error loading log: ${escapeHtml(e.message)}</span></div>`;
  }
}

/**
 * Runner service controls.
 */

function auditRenderedBotConfigBooleanFields(getEl, bot, fields, context = "main") {
  const mismatches = [];
  (fields || []).forEach((field) => {
    const inputId = BOT_CONFIG_BOOLEAN_INPUT_IDS[field];
    const el = inputId ? getEl(inputId) : null;
    if (!el) return;
    const expected = getBotConfigBooleanValue(bot, field);
    if (!!el.checked !== expected) {
      mismatches.push({ field, expected, rendered: !!el.checked });
    }
  });
  const audit = {
    context,
    bot_id: bot?.id || null,
    mismatches,
    checked_at: new Date().toISOString(),
  };
  window.__lastBotConfigRenderAudit = audit;
  if (mismatches.length) {
    console.warn(`[bot-config:${context}] rendered boolean mismatch`, audit);
  }
  return audit;
}

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
  const initialEntrySupported = INITIAL_ENTRY_SUPPORTED_MODES.has(mode);
  setBotOptionRowState("bot-initial-entry-row", initialEntrySupported, [
    "bot-initial-entry",
    "bot-initial-entry-auto-trend",
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

  // BTC Corr Filter: default OFF for directional, ON for neutral/other
  const btcFilterEl = getEl("bot-btc-corr-filter");
  const isNewBot = !String(getEl("bot-id")?.value || "").trim();
  if (btcFilterEl && isNewBot) {
    btcFilterEl.checked = !["long", "short"].includes(mode);
  }

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
    liveFullRefreshInterval = setInterval(refreshAll, 30000);
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

// MODAL functions — extracted from app_lf.js
// 10 functions, 340 lines

function showBacktestModal(data) {
  // Create modal if not exists
  let modal = $("backtest-modal");
  if (!modal) {
    const modalHtml = `
  <div id="backtest-modal" class="fixed inset-0 bg-black/80 hidden items-center justify-center z-50 backdrop-blur-sm" onclick="if(event.target===this){this.classList.remove('flex');this.classList.add('hidden')}">
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

function openBotModal() {
  const modal = $("botModal");
  if (!modal) return;

  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden"; // Prevent background scrolling

  // Always open on Runner Log tab
  switchBotModalTab('log');

  // Clear any existing interval before creating new one (prevent leaks)
  if (botModalRefreshInterval) clearInterval(botModalRefreshInterval);
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

// Unified Escape key handler for all modals (priority order: topmost first)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    // 1. Quick Edit panel (smallest overlay, check first)
    const quickEdit = document.getElementById('quick-edit-panel');
    if (quickEdit && !quickEdit.classList.contains('hidden')) {
      hideQuickEdit();
      return;
    }
    // 2. All PnL modal (may be on top of other modals)
    const allPnlModal = $("allPnlModal");
    if (allPnlModal && !allPnlModal.classList.contains("hidden")) {
      closeAllPnlModal();
      return;
    }
    // 3. Bot Detail modal
    const detailModal = $("botDetailModal");
    if (detailModal && !detailModal.classList.contains("hidden")) {
      closeBotDetailModal();
      return;
    }
    // 4. Bot Status/Log modal
    const botModal = $("botModal");
    if (botModal && !botModal.classList.contains("hidden")) {
      closeBotModal();
      return;
    }
  }
});

function closeAllPnlModal() {
  const modal = $("allPnlModal");
  if (!modal) return;

  modal.classList.add("hidden");
  document.body.style.overflow = "";
  stopAllPnlAutoRefresh();
  allPnlKnownRowIds.clear();

  if (allPnlLastUpdatedTimerId) {
    clearInterval(allPnlLastUpdatedTimerId);
    allPnlLastUpdatedTimerId = null;
  }
}

/**
 * Clear filters and refresh.
 */

function switchBotModalTab(tab) {
  botModalCurrentTab = tab;

  const tabBtnStatus = $("tabBtnStatus");
  const tabBtnLog = $("tabBtnLog");
  const tabContentStatus = $("tabContentStatus");
  const tabContentLog = $("tabContentLog");

  // Toggle active tab pill
  tabBtnStatus.classList.toggle("bot-modal__tab--active", tab === 'status');
  tabBtnLog.classList.toggle("bot-modal__tab--active", tab === 'log');

  if (tab === 'status') {
    tabContentStatus.style.display = 'flex';
    tabContentLog.style.display = 'none';
    loadBotStatus();
  } else {
    tabContentLog.style.display = 'flex';
    tabContentStatus.style.display = 'none';
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
    const data = await fetchJSON("/bot/status");

    // Pretty print the JSON
    box.textContent = JSON.stringify(data, null, 2);
    box.className = "bg-slate-800/50 rounded-lg p-4 text-sm text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-[65vh]";

    // Update last update time
    if (lastUpdate) {
      lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
    }

    // Also update runner status badge (in case user switches to log tab)
    updateRunnerStatus();
  } catch (e) {
    box.textContent = `Error loading status: ${e.message}`;
    box.className = "bg-red-900/30 rounded-lg p-4 text-sm text-red-400 font-mono whitespace-pre-wrap overflow-auto max-h-[65vh]";
  }
}

/**
 * Escape HTML entities to prevent XSS when using innerHTML.
 */

function openServiceActionModal(config) {
  pendingServiceAction = config;
  const modal = $("serviceActionModal");
  const title = $("serviceActionTitle");
  const message = $("serviceActionMessage");
  const warning = $("serviceActionWarning");
  const confirmBtn = $("serviceActionConfirm");
  const confirmText = $("serviceActionConfirmText");
  const confirmSpinner = $("serviceActionConfirmSpinner");
  const cancelBtn = $("serviceActionCancel");
  const eyebrow = $("serviceActionEyebrow");

  if (!modal || !title || !message || !warning || !confirmBtn || !confirmText) {
    return;
  }

  title.textContent = config.title;
  message.textContent = config.message;
  warning.textContent = config.warning;
  confirmText.textContent = config.confirmLabel;
  confirmBtn.className = config.confirmButtonClass;
  confirmBtn.disabled = false;
  confirmSpinner.classList.add("hidden");
  if (cancelBtn) cancelBtn.disabled = false;
  if (eyebrow) eyebrow.textContent = config.eyebrow || "Service Control";
  modal.classList.remove("hidden");
}

function closeServiceActionModal(force = false) {
  if (runnerServiceActionInFlight && !force) {
    return;
  }
  const modal = $("serviceActionModal");
  if (modal) {
    modal.classList.add("hidden");
  }
  pendingServiceAction = null;
}

function initBotModalListeners() {
  // Button click opens modal
  const btnStatus = $("btnBotStatus");
  if (btnStatus) {
    btnStatus.addEventListener("click", openBotModal);
  }
  // Note: Escape key is handled by the unified handler above
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
const LIVE_FALLBACK_PNL_REFRESH_MS = 5000;
const LIVE_FALLBACK_FULL_REFRESH_MS = 15000;
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
const INITIAL_ENTRY_SUPPORTED_MODES = new Set(["long", "short"]);
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

const DASHBOARD_FETCH_TIMEOUT_MS = 10000;

async function fetchJSON(path, options = {}) {
  const { suppress404Log = false, timeout = 0, ...fetchOptions } = options;
  const controller = timeout > 0 ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeout) : null;
  try {
    const response = await fetch(API_BASE + path, {
      ...fetchOptions,
      cache: fetchOptions.cache || "no-store",
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
      ...(controller ? { signal: controller.signal } : {}),
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
    if (error?.name === "AbortError") {
      const te = new Error(`Timeout after ${timeout}ms: ${path}`);
      te.isTimeout = true;
      throw te;
    }
    if (!(suppress404Log && error?.status === 404)) {
      console.error(`API Error (${path}):`, error);
    }
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function fetchDashboardJSON(path, options = {}) {
  return fetchJSON(path, { timeout: DASHBOARD_FETCH_TIMEOUT_MS, ...options });
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
    score: Number.isFinite(Number(bot?.setup_timing_score)) ? Number(bot?.setup_timing_score) : (Number.isFinite(Number(bot?.setup_ready_score)) ? Number(bot?.setup_ready_score) : (Number.isFinite(Number(bot?.analysis_ready_score)) ? Number(bot?.analysis_ready_score) : (Number.isFinite(Number(bot?.entry_ready_score)) ? Number(bot?.entry_ready_score) : null))),
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

  // Directional reanchor state
  if (bot.directional_reanchor_pending) {
    chips.push(buildMetricChip("Reanchor Pending", "amber"));
  } else if (bot.directional_reanchor_last_result === "completed" && bot.directional_reanchor_last_completed_at) {
    chips.push(buildMetricChip("Reanchored", "emerald"));
  } else if (bot.directional_reanchor_last_result === "expired_position_still_open") {
    chips.push(buildMetricChip("Reanchor Expired", "rose"));
  }

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

  const hasPendingNonPauseResume = activePendingAction && activePendingAction !== "pause" && activePendingAction !== "resume";
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
  const primaryButtons = [
    hasPendingNonPauseResume
      ? `<button disabled class="${primaryClass} bot-action-btn--disabled"><span class="animate-spin inline-block">↻</span><span>${escapeHtml(humanizeReason(activePendingAction))}</span></button>`
      : canStart && !stopGuardActive
        ? `<button onclick="botAction('start', '${bot.id}', event)" class="${primaryClass} bot-action-btn--start"><span>▶</span><span>Start</span></button>`
        : "",
    stopGuardActive
      ? `<button disabled class="${primaryClass} bot-action-btn--disabled"><span>⏳</span><span>Wait ${stopGuardSec}s</span></button>`
      : "",
    bot.status !== "stopped"
      ? `<button onclick="botAction('stop', '${bot.id}', event)" class="${primaryClass} bot-action-btn--stop"><span>⏹</span><span>Stop</span></button>`
      : "",
  ].filter(Boolean).join("");

  const utilityRow = `<div class="bot-action-group--utility">${utilityButtons}</div>`;
  const primaryRow = primaryButtons ? `<div class="bot-action-primary">${primaryButtons}</div>` : "";
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
      const pbActive = Boolean(bot._pullback_watch_active);
      const pbDir = String(bot._pullback_watch_direction || "").toUpperCase();
      const pbDepthVal = Number(bot._pullback_watch_pullback_depth_pct || 0).toFixed(1);
      const pbSpan = pbActive ? `<span class="text-cyan-300 font-medium">PB ${pbDir} ${pbDepthVal}%</span>` : "";
      return `
        <span>${botIdShort}</span>
        <span>${escapeHtml(gridsText)}</span>
        <span class="${(bot.open_order_count || 0) > 0 ? 'text-cyan-300' : 'text-slate-500'}">${bot.open_order_count || 0} orders</span>
        ${ppSpan}
        ${pbSpan}
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
      const score = Number(setup.score || 0);
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
  const bridgeStatus = payload._bridge_status || {};
  if (payload.summary) {
    applySummaryData(bridgeStatus.summary_degraded
      ? { ...payload.summary, _degraded: true } : payload.summary);
  }
  if (payload.positions) {
    applyPositionsData(bridgeStatus.positions_degraded
      ? { ...payload.positions, _degraded: true } : payload.positions);
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
      ...(bridgeStatus.bots_degraded ? { _degraded: true } : {}),
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

  // SSE stale detection: if no data event within 15s of open, the stream
  // is stuck (server building slow payload). Fall back to polling.
  let _sseReceivedData = false;
  if (window._sseStaleTimer) clearTimeout(window._sseStaleTimer);
  window._sseStaleTimer = setTimeout(() => {
    if (!_sseReceivedData) {
      console.warn("SSE stream stale (no data in 15s), enabling fallback polling");
      configureLivePolling(false);
    }
    window._sseStaleTimer = null;
  }, 15000);

  // Ongoing heartbeat watchdog: if no SSE event arrives for 30s, mark stale
  // and enable fallback polling. Resets on every event via _resetSseWatchdog().
  if (window._sseWatchdogInterval) clearInterval(window._sseWatchdogInterval);
  window._sseLastActivity = Date.now();
  window._sseWatchdogInterval = setInterval(() => {
    const elapsed = Date.now() - (window._sseLastActivity || 0);
    if (elapsed > 30000) {
      console.warn(`SSE stream idle for ${Math.round(elapsed / 1000)}s, enabling fallback polling`);
      setLiveFeedConnected(false);
      configureLivePolling(false);
    }
  }, 10000);
  function _resetSseWatchdog() { window._sseLastActivity = Date.now(); }

  source.addEventListener("open", () => {
    setLiveFeedConnected(true);
    _resetSseWatchdog();
    updateLastRefreshTime();
  });

  source.addEventListener("error", () => {
    setLiveFeedConnected(false);
    configureLivePolling(false);
  });

  source.addEventListener("snapshot", (event) => {
    _sseReceivedData = true;
    _resetSseWatchdog();
    if (window._sseStaleTimer) { clearTimeout(window._sseStaleTimer); window._sseStaleTimer = null; }
    setLiveFeedConnected(true);
    configureLivePolling(true);
    const payload = parseLiveEventPayload(event);
    if (payload?.dashboard) {
      applyLiveDashboardUpdate(payload.dashboard);
      return;
    }
    updateLastRefreshTime();
    scheduleLiveFullRefresh(0);
  });

  source.addEventListener("dashboard", (event) => {
    _resetSseWatchdog();
    setLiveFeedConnected(true);
    configureLivePolling(true);
    const payload = parseLiveEventPayload(event);
    if (payload) {
      applyLiveDashboardUpdate(payload);
    }
  });

  source.addEventListener("heartbeat", () => {
    _resetSseWatchdog();
    setLiveFeedConnected(true);
    updateLastRefreshTime();
  });

  ["ticker", "position", "execution", "order", "health"].forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      _resetSseWatchdog();
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
        }, 150);
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
let _refreshAllRunning = false;
let _refreshAllRerunRequested = false;
async function refreshAll() {
  if (_refreshAllRunning) {
    _refreshAllRerunRequested = true;
    return;
  }
  _refreshAllRunning = true;
  try {
    // Critical lane: always, blocks until done
    await Promise.all([refreshSummary(), refreshPositions(), refreshBots(), refreshPnlCritical()]);
    setConnectionStatus(true);
    updateLastRefreshTime();
    // Secondary lane: every 3rd cycle, fire-and-forget (never blocks critical)
    _refreshAllCycle = (_refreshAllCycle + 1) % 3;
    if (_refreshAllCycle === 0) {
      refreshPnlFull().catch(() => {});
      refreshWatchdogHub().catch(() => {});
      refreshBotTriage().catch(() => {});
      refreshBotConfigAdvisor().catch(() => {});
      refreshPredictions().catch(() => {});
      refreshHeatMap().catch(() => {});
    }
  } catch (error) {
    console.error("Refresh error:", error);
    setConnectionStatus(false);
  } finally {
    _refreshAllRunning = false;
    if (_refreshAllRerunRequested) {
      _refreshAllRerunRequested = false;
      refreshAll();
    }
  }
}

let _refreshPnlQuickPromise = null;
async function refreshPnlQuick() {
  if (_refreshPnlQuickPromise) return _refreshPnlQuickPromise;
  _refreshPnlQuickPromise = (async () => {
    try {
      await refreshPnlCritical();
      setConnectionStatus(true);
      updateLastRefreshTime();
    } catch (error) {
      console.error("Quick refresh error:", error);
      setConnectionStatus(false);
    } finally { _refreshPnlQuickPromise = null; }
  })();
  return _refreshPnlQuickPromise;
}

function applySummaryData(data) {
  const isDegraded = Boolean(data?._degraded || data?.stale_data);
  if (isDegraded && window._lastSummaryData && !window._lastSummaryData._degraded) {
    return;
  }
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

let _refreshSummaryPromise = null;
let _refreshSummaryFreshPromise = null;
async function refreshSummary(fresh = false) {
  if (fresh) {
    if (_refreshSummaryFreshPromise) return _refreshSummaryFreshPromise;
    _refreshSummaryFreshPromise = (async () => {
      try {
        const data = await fetchDashboardJSON("/summary?fresh=1");
        applySummaryData(data);
      } finally { _refreshSummaryFreshPromise = null; }
    })();
    return _refreshSummaryFreshPromise;
  }
  if (_refreshSummaryPromise) return _refreshSummaryPromise;
  _refreshSummaryPromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/summary");
      applySummaryData(data);
    } finally { _refreshSummaryPromise = null; }
  })();
  return _refreshSummaryPromise;
}

function applyPositionsData(data) {
  const payload = Array.isArray(data) ? { positions: data } : (data || {});
  window._lastPositionsPayload = payload;
  const positions = Array.isArray(payload.positions) ? payload.positions : [];

  const isDegraded = Boolean(payload._degraded || payload.stale_data);
  if (isDegraded && positions.length === 0) {
    renderPositionsStatusMessage("Positions unavailable \u2014 retrying");
    return;
  }

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

let _refreshPositionsPromise = null;
let _refreshPositionsFreshPromise = null;
async function refreshPositions(fresh = false) {
  if (fresh) {
    if (_refreshPositionsFreshPromise) return _refreshPositionsFreshPromise;
    _refreshPositionsFreshPromise = (async () => {
      try {
        const data = await fetchDashboardJSON("/positions?fresh=1");
        applyPositionsData(data);
        return data;
      } catch (error) {
        const cachedPayload = window._lastPositionsPayload;
        if (cachedPayload && Array.isArray(cachedPayload.positions)) {
          applyPositionsData(cachedPayload);
        } else if (error?.isTimeout) {
          renderPositionsStatusMessage("Positions request timed out — retrying");
        } else {
          renderPositionsStatusMessage("Unable to load positions");
        }
        throw error;
      } finally { _refreshPositionsFreshPromise = null; }
    })();
    return _refreshPositionsFreshPromise;
  }
  if (_refreshPositionsPromise) return _refreshPositionsPromise;
  _refreshPositionsPromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/positions");
      applyPositionsData(data);
      return data;
    } catch (error) {
      const cachedPayload = window._lastPositionsPayload;
      if (cachedPayload && Array.isArray(cachedPayload.positions)) {
        applyPositionsData(cachedPayload);
      } else if (error?.isTimeout) {
        renderPositionsStatusMessage("Positions request timed out — retrying");
      } else {
        renderPositionsStatusMessage("Unable to load positions");
      }
      throw error;
    } finally { _refreshPositionsPromise = null; }
  })();
  return _refreshPositionsPromise;
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
  const blockedCount = readyCats.filter((cat) => cat === "blocked").length;
  const limitedCount = readyCats.filter((cat) => cat === "limited").length;
  // M1 audit: subtract armed/late from watch so totals are mutually exclusive
  const armedLateCount = sortedBots.filter(b => {
    const st = getSetupReadiness(b).status;
    return isArmedStatus(st) || isLateStatus(st);
  }).length;
  const rawWatchCount = readyCats.filter((cat) => cat === "watch").length;
  const watchCount = Math.max(rawWatchCount - armedLateCount, 0);
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
    const isDegraded = Boolean(payload?._degraded || runtimeSnapshotStale);
    renderReadyTradeBoard([]);
    if (isDegraded) {
      const container = $("active-bots-list");
      if (container) {
        setElementHtmlIfChanged(container,
          '<div class="ops-empty-state"><strong>Bots unavailable</strong> Waiting for runtime data.</div>'
        );
      }
      rememberActiveBotStructure([]);
    } else {
      renderMobileBotsData([]);
    }
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
      const data = await fetchDashboardJSON("/bots/runtime");
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

let _refreshBotTriagePromise = null;
async function refreshBotTriage() {
  if (_refreshBotTriagePromise) return _refreshBotTriagePromise;
  _refreshBotTriagePromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/bot-triage");
      applyBotTriageData(data);
      return data;
    } finally { _refreshBotTriagePromise = null; }
  })();
  return _refreshBotTriagePromise;
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

let _refreshBotConfigAdvisorPromise = null;
async function refreshBotConfigAdvisor() {
  if (_refreshBotConfigAdvisorPromise) return _refreshBotConfigAdvisorPromise;
  _refreshBotConfigAdvisorPromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/bot-config-advisor");
      applyBotConfigAdvisorData(data);
      return data;
    } finally { _refreshBotConfigAdvisorPromise = null; }
  })();
  return _refreshBotConfigAdvisorPromise;
}

let _refreshWatchdogHubPromise = null;
async function refreshWatchdogHub() {
  if (_refreshWatchdogHubPromise) return _refreshWatchdogHubPromise;
  _refreshWatchdogHubPromise = (async () => {
    try {
      const data = await fetchDashboardJSON("/watchdog-center");
      applyWatchdogHubData(data);
      return data;
    } finally { _refreshWatchdogHubPromise = null; }
  })();
  return _refreshWatchdogHubPromise;
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
    const score = Number(setup.score || 0);
    const price = parseFloat(bot?.market_data_price) || parseFloat(bot?.current_price) || parseFloat(bot?.exchange_mark_price) || 0;
    const botMode = normalizeBotModeValue(bot?.configured_mode || bot?.mode || "neutral");
    if (existing) {
      if (!existing.still_ready) {
        existing.readyAt = now;   // update time when coin comes back
        if (price > 0) existing.entry_price = price;  // capture fresh on re-entry
      }
      existing.still_ready = true;
      existing.direction = dir;
      if (score > 0) existing.score = score;
      existing.bot_id = botId || existing.bot_id || "";
      existing.bot_status = String(bot?.status || "").trim().toLowerCase();
      existing.bot_mode = botMode;
      existing.source_label = sourceMeta?.label || "";
      existing.source_detail = sourceMeta?.detail || "";
    } else {
      _emergReadyHistory.unshift({
        symbol,
        bot_id: botId,
        bot_status: String(bot?.status || "").trim().toLowerCase(),
        bot_mode: botMode,
        direction: dir,
        score,
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
          ${entry.score ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-900/40 text-emerald-300 font-semibold">${entry.score.toFixed(1)}</span>` : ""}
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
    const readyScore = Number(getSetupReadiness(bot).score || 0);
    const readyScoreBadge = readyScore
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

// --- PnL bootstrap: apply critical PnL from bootstrap payload ---
function applyBootstrapPnl(pnlData) {
  if (!pnlData) return;
  const logs = pnlData.logs || [];
  const today = pnlData.today || {};
  registerNewPnlEvents(logs, today);
  previousValues.pnlLogIds = new Set(logs.map(log => log.id));

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
  updateAssetsRecentPnl(logs);

  const tbody = $("pnl-body");
  if (!tbody) { renderMobilePnlData([]); updateOperatorWatch(); return; }
  if (logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="pnl-empty-state"><span class="pnl-empty-state__icon">◎</span><strong>No closed PnL records</strong> Realized outcomes will populate here automatically after trades close.</td></tr>`;
    renderMobilePnlData([]);
    return;
  }
  const recentLogs = logs.slice().reverse().slice(0, 50);
  tbody.innerHTML = recentLogs.map(log => {
    const pnl = formatPnL(log.realized_pnl);
    const balance = log.balance_after != null ? `$${parseFloat(log.balance_after).toFixed(2)}` : '-';
    const uptime = formatDuration(log.bot_started_at, log.time);
    return `<tr class="table-row"><td class="px-4 py-3 text-xs text-slate-400">${formatTime(log.time)}</td><td class="px-4 py-3 font-medium text-white">${log.symbol}</td><td class="px-4 py-3"><span class="position-meta-pill">${log.side}</span></td><td class="px-4 py-3 text-right ${pnl.class} font-semibold">${pnl.text}</td><td class="px-4 py-3 text-center text-cyan-300 text-xs font-medium">${uptime}</td><td class="px-4 py-3 text-right text-slate-300">${balance}</td></tr>`;
  }).join("");
  renderMobilePnlData(recentLogs);
  updateOperatorWatch();
}

// --- PnL: split into critical (today stats + logs) and full (all-time stats) ---
let _refreshPnlCriticalPromise = null;
async function refreshPnlCritical() {
  if (_refreshPnlCriticalPromise) return _refreshPnlCriticalPromise;
  _refreshPnlCriticalPromise = (async () => {
  try {
  const cacheBust = `_ts=${Date.now()}`;
  const data = await fetchDashboardJSON(`/pnl/log?${cacheBust}`, { cache: "no-store" });
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

  // Update recent closed PnL in Assets card
  updateAssetsRecentPnl(logs);

  const tbody = $("pnl-body");
  if (!tbody) {
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
  } finally { _refreshPnlCriticalPromise = null; }
  })();
  return _refreshPnlCriticalPromise;
}

let _refreshPnlFullPromise = null;
async function refreshPnlFull() {
  if (_refreshPnlFullPromise) return _refreshPnlFullPromise;
  _refreshPnlFullPromise = (async () => {
  try {
    const cacheBust = `_ts=${Date.now()}`;
    const allStats = await fetchDashboardJSON(`/pnl/stats?period=all&${cacheBust}`, { cache: "no-store" });
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
  finally { _refreshPnlFullPromise = null; }
  })();
  return _refreshPnlFullPromise;
}

// Convenience wrapper for callers that need both (e.g. All PnL modal refresh)
async function refreshPnl() {
  await refreshPnlCritical();
  refreshPnlFull().catch(() => {});
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
    initial_entry: INITIAL_ENTRY_SUPPORTED_MODES.has(mode) ? readBotConfigBooleanField(getEl, "initial_entry") : false,
    initial_entry_auto_trend: INITIAL_ENTRY_SUPPORTED_MODES.has(mode) ? readBotConfigBooleanField(getEl, "initial_entry_auto_trend") : false,
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

  // Disable button with loading state for feedback
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

  // C4: Optimistic UI — fire the API call without awaiting it.
  // The pendingBotActions badge already shows the transition state.
  // Restore button immediately so the UI feels instant.
  if (["start", "stop", "pause", "resume"].includes(action) && btn) {
    // Restore button after a short flash so the spinner is visible briefly
    setTimeout(() => {
      btn.disabled = false;
      if (originalHtml !== null) btn.innerHTML = originalHtml;
    }, 400);
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
    }, action === "stop" ? 1200 : 900);
  }).catch((error) => {
    delete pendingBotActions[botId];
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
let activeSymbolFilters = new Set();
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
  if (!bar) return;

  if (!logFilterChipsInitialized) {
    logFilterChipsInitialized = true;

    // Build category chips (static, one-time)
    const catHtml = LOG_CATEGORIES.map(cat =>
      `<button class="log-filter-chip${cat.id === 'all' ? ' log-filter-chip--active' : ''}" data-category="${cat.id}" onclick="toggleLogFilter('${cat.id}')">` +
      `${escapeHtml(cat.label)}` +
      (cat.match ? `<span class="log-filter-chip__count" data-count-for="${cat.id}">0</span>` : '') +
      `</button>`
    ).join('');
    bar.innerHTML = catHtml + '<span id="logSymbolChips"></span>';

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

  // Rebuild dynamic symbol chips from current parsed log lines
  updateSymbolChips();
}

function updateSymbolChips() {
  const container = document.getElementById('logSymbolChips');
  if (!container) return;

  const symbols = new Set();
  for (const l of parsedLogLines) {
    if (l.symbol) symbols.add(l.symbol);
  }
  if (symbols.size === 0) { container.innerHTML = ''; return; }

  const sorted = Array.from(symbols).sort();
  const chips = sorted.map(sym => {
    const active = activeSymbolFilters.has(sym) ? ' log-filter-chip--active' : '';
    const count = parsedLogLines.filter(l => l.symbol === sym).length;
    return `<button class="log-filter-chip log-filter-chip--symbol${active}" data-symbol="${escapeHtml(sym)}" onclick="toggleSymbolFilter('${escapeHtml(sym)}')">${escapeHtml(sym)}<span class="log-filter-chip__count">${count}</span></button>`;
  }).join('');
  container.innerHTML = '<span class="log-filter-chip__sep"></span>' + chips;
}

function toggleSymbolFilter(symbol) {
  if (activeSymbolFilters.has(symbol)) {
    activeSymbolFilters.delete(symbol);
  } else {
    activeSymbolFilters.add(symbol);
  }
  // Sync chip visual state
  const container = document.getElementById('logSymbolChips');
  if (container) {
    container.querySelectorAll('.log-filter-chip--symbol').forEach(chip => {
      const sym = chip.getAttribute('data-symbol');
      chip.classList.toggle('log-filter-chip--active', activeSymbolFilters.has(sym));
    });
  }
  renderFilteredLogView();
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
  const legacy = await fetchDashboardJSON("/bot/status");
  return normalizeLegacyRunnerStatusPayload(legacy);
}

async function fetchRunnerStatusPayload() {
  // Poll the legacy status route by default; only use /services once this browser
  // has already confirmed that the newer service API exists.
  if (runnerServiceApiMode !== "modern") {
    return fetchLegacyRunnerStatusPayload();
  }

  try {
    const data = await fetchDashboardJSON("/services/status", { suppress404Log: true });
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

let _updateRunnerStatusPromise = null;
async function updateRunnerStatus() {
  if (_updateRunnerStatusPromise) return _updateRunnerStatusPromise;
  _updateRunnerStatusPromise = (async () => {
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
  finally { _updateRunnerStatusPromise = null; }
  })();
  return _updateRunnerStatusPromise;
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

let _refreshPredictionsPromise = null;
async function refreshPredictions() {
  if (_refreshPredictionsPromise) return _refreshPredictionsPromise;
  _refreshPredictionsPromise = (async () => {
  try {
    const loadingEl = $("predictions-loading");
    if (loadingEl) loadingEl.classList.remove("hidden");

    const data = await fetchDashboardJSON("/predictions");
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
  finally { _refreshPredictionsPromise = null; }
  })();
  return _refreshPredictionsPromise;
}


const BOT_CONFIG_BOOLEAN_DEFAULTS = Object.freeze({
  auto_direction: false,
  breakout_confirmed_entry: false,
  auto_pilot: false,
  initial_entry: false,
  initial_entry_auto_trend: true,
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
  initial_entry: "bot-initial-entry",
  initial_entry_auto_trend: "bot-initial-entry-auto-trend",
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
  "initial_entry",
  "initial_entry_auto_trend",
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
  // H6 audit: trigger delayed re-fetch so dashboard picks up new control booleans
  if (typeof refreshAll === "function") {
    setTimeout(() => refreshAll(), 2000);
  }
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
  // --- Critical data: single bootstrap request ---
  (async function bootstrapDashboard() {
    let bootstrapOk = false;
    try {
      const data = await fetchDashboardJSON("/dashboard/bootstrap");
      const bridgeStatus = data._bridge_status || {};
      const anyDegraded = !bridgeStatus.healthy;

      if (data.summary) applySummaryData(
        bridgeStatus.summary_degraded ? { ...data.summary, _degraded: true } : data.summary
      );
      if (data.positions) applyPositionsData(
        bridgeStatus.positions_degraded ? { ...data.positions, _degraded: true } : data.positions
      );
      if (data.bots) applyBotsData({
        bots: data.bots, bots_meta: data.bots_meta,
        runtime_integrity: data.runtime_integrity,
        _state_source: "bootstrap",
        ...(bridgeStatus.bots_degraded ? { _degraded: true } : {}),
      });
      if (data.pnl) applyBootstrapPnl(data.pnl);
      if (!anyDegraded) setConnectionStatus(true);
      updateLastRefreshTime();
      bootstrapOk = true;
    } catch (e) {
      console.warn("Bootstrap failed, falling back:", e);
      await refreshAll();
    }

    // Start live feed — SSE becomes first live owner
    startLiveTimer();
    connectLiveFeed();

    if (bootstrapOk) {
      const bridgeHealthy = !!(window._lastSummaryData && !window._lastSummaryData._degraded);
      // Faster retry when degraded, normal safety refresh otherwise
      setTimeout(refreshAll, bridgeHealthy ? 8000 : 3000);
    }
  })();

  // --- Stagger secondary loads after bootstrap window ---
  setTimeout(updateRunnerStatus, 1500);
  setTimeout(() => loadTradeStats('all'), 3000);
  setTimeout(refreshHeatMap, 5000);
  setTimeout(checkFlashCrashStatus, 6000);
  setTimeout(refreshPnlFull, 4000);  // All-time stats deferred

  // --- Start ongoing polling intervals after stagger window ---
  setTimeout(() => {
    if (runnerStatusPollInterval) clearInterval(runnerStatusPollInterval);
    runnerStatusPollInterval = setInterval(updateRunnerStatus, 10000);
    _flashCrashPollInterval = setInterval(checkFlashCrashStatus, 10000);
    _tradeStatsPollInterval = setInterval(() => loadTradeStats(currentStatsPeriod), 30000);
  }, 7000);
});

// --- Tab visibility: fully pause/resume live machinery ---
let _flashCrashPollInterval = null;
let _tradeStatsPollInterval = null;

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    // Pause SSE
    if (liveEventSource) { liveEventSource.close(); liveEventSource = null; }
    // Pause polling intervals
    if (liveQuickRefreshInterval) { clearInterval(liveQuickRefreshInterval); liveQuickRefreshInterval = null; }
    if (liveFullRefreshInterval) { clearInterval(liveFullRefreshInterval); liveFullRefreshInterval = null; }
    if (runnerStatusPollInterval) { clearInterval(runnerStatusPollInterval); runnerStatusPollInterval = null; }
    if (_flashCrashPollInterval) { clearInterval(_flashCrashPollInterval); _flashCrashPollInterval = null; }
    if (_tradeStatsPollInterval) { clearInterval(_tradeStatsPollInterval); _tradeStatsPollInterval = null; }
    // Pause scheduled refresh timeouts
    if (liveQuickRefreshTimeout) { clearTimeout(liveQuickRefreshTimeout); liveQuickRefreshTimeout = null; }
    if (liveFullRefreshTimeout) { clearTimeout(liveFullRefreshTimeout); liveFullRefreshTimeout = null; }
    if (livePnlRefreshTimeout) { clearTimeout(livePnlRefreshTimeout); livePnlRefreshTimeout = null; }
    // Pause SSE watchdog/stale timers
    if (window._sseStaleTimer) { clearTimeout(window._sseStaleTimer); window._sseStaleTimer = null; }
    if (window._sseWatchdogInterval) { clearInterval(window._sseWatchdogInterval); window._sseWatchdogInterval = null; }
  } else {
    // Resume: reconnect SSE (which also sets up fallback polling)
    connectLiveFeed();
    refreshAll();
    // Restart secondary polling
    if (runnerStatusPollInterval) clearInterval(runnerStatusPollInterval);
    runnerStatusPollInterval = setInterval(updateRunnerStatus, 10000);
    _flashCrashPollInterval = setInterval(checkFlashCrashStatus, 10000);
    _tradeStatsPollInterval = setInterval(() => loadTradeStats(currentStatsPeriod), 30000);
  }
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

let _checkFlashCrashPromise = null;
async function checkFlashCrashStatus() {
  if (_checkFlashCrashPromise) return _checkFlashCrashPromise;
  _checkFlashCrashPromise = (async () => {
  try {
    const data = await fetchDashboardJSON("/flash-crash-status");
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
  finally { _checkFlashCrashPromise = null; }
  })();
  return _checkFlashCrashPromise;
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
    initial_entry: settings.initial_entry !== undefined ? !!settings.initial_entry : getBotConfigBooleanFallback("initial_entry"),
    initial_entry_auto_trend: settings.initial_entry_auto_trend !== undefined ? !!settings.initial_entry_auto_trend : getBotConfigBooleanFallback("initial_entry_auto_trend"),
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

let _loadTradeStatsPromise = null;
async function loadTradeStats(period = 'all') {
  if (_loadTradeStatsPromise) return _loadTradeStatsPromise;
  _loadTradeStatsPromise = (async () => {
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
    const data = await fetchDashboardJSON(`/pnl/stats?period=${period}`);
    updateTradeStatsDisplay(data);
  } catch (err) {
    console.error('Failed to load trade stats:', err);
  }
  finally { _loadTradeStatsPromise = null; }
  })();
  return _loadTradeStatsPromise;
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

