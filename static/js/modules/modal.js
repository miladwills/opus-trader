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

