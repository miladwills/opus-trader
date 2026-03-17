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
  const watchCount = normalizedStatuses.filter((status) => ["watch", "wait", "caution", "armed", "late"].includes(status)).length;
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
    setElementHtmlIfChanged(watchEl, `Watch/Armed <strong>${watchCount}</strong>`);
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
        if (typeof _prevReadyBotDirections === "undefined") window._prevReadyBotDirections = {};
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
    const entryPrice = histEntry?.entry_price || parseFloat(bot?.mark_price) || parseFloat(bot?.market_data_price) || parseFloat(bot?.current_price) || 0;
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
            <div class="ready-trade-setup-card__metric-label">Entry Price</div>
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

