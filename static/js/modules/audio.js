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

