/**
 * Neutral Scanner Pro - Main Application
 * Handles data fetching, rendering, and user interactions
 */

// Global state
let lastRows = [];
let watchList = [];
let previousNeutral = {};
let previousBtcRisk = null;
let refreshInterval = 8000; // Default, will be updated from server
let refreshTimer = null;
let fetchInFlight = null;
let symbolSearchQuery = '';
let pendingFocusSymbol = null;
let focusResetTimer = null;
const CACHE_KEY = 'scanner_cache_v1';
const DEFAULT_TITLE = document.title;

// DOM Elements
const tableBody = document.getElementById('tableBody');
const lastUpdateEl = document.getElementById('lastUpdate');
const btcPriceEl = document.getElementById('btcPrice');
const btcRiskBadgeEl = document.getElementById('btcRiskBadge');
const btcChange1hEl = document.getElementById('btcChange1h');
const btcChange4hEl = document.getElementById('btcChange4h');
const btcAdxEl = document.getElementById('btcAdx');
const btcSpeedEl = document.getElementById('btcSpeed');
const btcTopCorrEl = document.getElementById('btcTopCorr');
const btcWeakCorrEl = document.getElementById('btcWeakCorr');
const skippedSymbolsEl = document.getElementById('skippedSymbols');
const symbolSearchEl = document.getElementById('symbolSearch');
const clearSymbolSearchBtn = document.getElementById('clearSymbolSearch');
const tableStatusEl = document.getElementById('tableStatus');
const pageNoticeEl = document.getElementById('pageNotice');

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize the application
 */
async function initApp() {
    // Load watch list from localStorage
    loadWatchList();

    // Initialize i18n
    await window.i18n.init();

    // Initialize sort manager
    window.multiSortManager.init();

    // Initialize filter manager
    window.filterManager.init();

    // Initialize preset manager (Sort + Filter named presets)
    if (window.presetManager && typeof window.presetManager.init === 'function') {
        window.presetManager.init();
    }

    // Render cached data immediately (if available) before fetching fresh data
    applyCachedData();

    // Setup event listeners
    setupEventListeners();

    // Fetch initial data
    await fetchData();

    // Start auto-refresh
    startAutoRefresh();
}

function loadCachedData() {
    try {
        const raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (e) {
        return null;
    }
}

function saveCachedData(data) {
    try {
        if (isUsablePayload(data)) {
            localStorage.setItem(CACHE_KEY, JSON.stringify(data));
        }
    } catch (e) {}
}

function isUsablePayload(data) {
    if (!data || !data.ok || !Array.isArray(data.rows)) {
        return false;
    }

    const generatedAtMs = Number(data.generated_at_epoch_ms || 0);
    const seedMaxAgeMs = Number(data.seed_max_age_ms || 0);
    if (!generatedAtMs || !seedMaxAgeMs) {
        return true;
    }

    return (Date.now() - generatedAtMs) <= seedMaxAgeMs;
}

function getPayloadGeneratedAtMs(data) {
    return Number(data?.generated_at_epoch_ms || 0);
}

function getPayloadRank(data) {
    if (!data || !data.ok || !Array.isArray(data.rows)) {
        return -1;
    }

    return isUsablePayload(data) ? 2 : 1;
}

function selectBestPayload(...candidates) {
    const valid = candidates.filter(candidate => getPayloadRank(candidate) >= 0);
    if (!valid.length) {
        return null;
    }

    valid.sort((left, right) => {
        const rankDiff = getPayloadRank(right) - getPayloadRank(left);
        if (rankDiff !== 0) {
            return rankDiff;
        }
        return getPayloadGeneratedAtMs(right) - getPayloadGeneratedAtMs(left);
    });

    return valid[0] || null;
}

function applyCachedData() {
    const seed = (window.__INITIAL_DATA__ && typeof window.__INITIAL_DATA__ === 'object')
        ? window.__INITIAL_DATA__
        : null;
    const cached = loadCachedData();
    const data = selectBestPayload(seed, cached);
    if (!data) return;
    applyDataPayload(data, true);
    if (isUsablePayload(seed)) {
        saveCachedData(seed);
    }
}

function applyDataPayload(data, isCached) {
    if (!data || !data.ok) return;

    if (data.refresh_interval_ms) {
        refreshInterval = data.refresh_interval_ms;
    }

    if (data.btc) {
        updateBtcRiskBar(data.btc);
    }

    if (data.btc_top_corr) {
        updateBtcCorrelations(data.btc_top_corr, data.btc_weak_corr);
    }

    if (!isCached && Array.isArray(data.rows)) {
        checkNeutralTransitions(data.rows);
    }

    lastRows = Array.isArray(data.rows) ? data.rows : [];
    window.lastRows = lastRows;

    if (window.presetManager?.render) {
        window.presetManager.render();
    }

    if (window.presetManager?.activePreset && window.presetManager?.getHotCoinsForActivePreset) {
        const hotCoins = window.presetManager.getHotCoinsForActivePreset();
        window.hotCoinSymbols = hotCoins.map(c => c.symbol);
        window.hotCoinScores = hotCoins;
        window.presetManager.currentHotCoins = hotCoins;
    } else {
        window.hotCoinSymbols = [];
        window.hotCoinScores = [];
        window.hotCoinSeparatorIndex = 0;
    }

    // Update page title: show top ready coin or revert to default
    updatePageTitle();

    renderTable(lastRows);

    if (window.presetManager?.markHotCoinsInTable && window.presetManager?.activePreset) {
        setTimeout(() => {
            window.presetManager.markHotCoinsInTable();
        }, 50);
    }

    if (lastUpdateEl && data.server_time) {
        lastUpdateEl.textContent = data.server_time;
    }

    if (data.skipped_symbols && data.skipped_symbols.length > 0) {
        showSkippedSymbols(data.skipped_symbols);
    } else {
        hideSkippedSymbols();
    }
}

/**
 * Update page title with top ready coin or revert to default
 */
function updatePageTitle() {
    const scores = window.hotCoinScores;
    if (Array.isArray(scores) && scores.length > 0) {
        const top = scores[0];
        document.title = `${top.symbol} ${top.combined}% — Ready`;
    } else {
        document.title = DEFAULT_TITLE;
    }
}

/**
 * Load watch list from localStorage
 */
function loadWatchList() {
    try {
        const saved = localStorage.getItem('neutral_watchlist');
        if (saved) {
            watchList = JSON.parse(saved) || [];
        }
    } catch (e) {
        watchList = [];
    }
}

/**
 * Save watch list to localStorage
 */
function saveWatchList() {
    try {
        localStorage.setItem('neutral_watchlist', JSON.stringify(watchList));
    } catch (e) {}
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Add symbol form
    const addSymbolForm = document.getElementById('add-symbol-form');
    if (addSymbolForm) {
        addSymbolForm.addEventListener('submit', handleAddSymbol);
    }

    // Apply sort button
    const applySortBtn = document.getElementById('applySort');
    if (applySortBtn) {
        applySortBtn.addEventListener('click', () => {
            renderTable(lastRows);
        });
    }

    // Apply filters button
    const applyFiltersBtn = document.getElementById('applyFilters');
    if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener('click', () => {
            renderTable(lastRows);
        });
    }

    // Table body click delegation (for alert and delete buttons)
    if (tableBody) {
        tableBody.addEventListener('click', handleTableClick);
    }

    // i18n change event
    document.addEventListener('i18n:changed', () => {
        renderTable(lastRows);
    });

    // Auto-apply sorting changes immediately (fixes cases where user changes sort levels but forgets to click Apply)
    document.addEventListener('sort:changed', () => {
        renderTable(lastRows);
    });

    // When a preset is applied, re-render (filters + sort)
    document.addEventListener('preset:applied', () => {
        renderTable(lastRows);
    });

    if (symbolSearchEl) {
        symbolSearchEl.addEventListener('input', (e) => {
            setSymbolSearch(e.target.value);
            clearPageNotice();
        });
    }

    if (clearSymbolSearchBtn) {
        clearSymbolSearchBtn.addEventListener('click', () => {
            setSymbolSearch('');
            clearPageNotice();
        });
    }

    if (pageNoticeEl) {
        pageNoticeEl.addEventListener('click', handlePageNoticeClick);
    }
}

// ============================================================================
// DATA FETCHING
// ============================================================================

/**
 * Fetch data from scanner.php
 */
async function fetchData() {
    if (fetchInFlight) {
        return fetchInFlight;
    }

    fetchInFlight = (async () => {
        const controller = new AbortController();
        const timeoutMs = Math.max(5000, Math.min(refreshInterval - 500, 15000));
        const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

        try {
            const res = await fetch('./scanner.php?action=data', {
                cache: 'no-store',
                signal: controller.signal,
            });
            const data = await res.json();

            if (!res.ok || !data || !data.ok) {
                if (!(data && data.message && data.message.includes("already in progress"))) {
                    console.error("Failed to fetch data:", data?.message || `HTTP ${res.status}`);
                }
                return null;
            }

            applyDataPayload(data, false);
            saveCachedData(data);
            return data;
        } catch (err) {
            console.error('fetchData error:', err);
            return null;
        } finally {
            window.clearTimeout(timeoutId);
            fetchInFlight = null;
        }
    })();

    return fetchInFlight;
}

/**
 * Start auto-refresh timer
 */
function startAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(fetchData, refreshInterval);
}

// ============================================================================
// BTC RISK BAR
// ============================================================================

/**
 * Update BTC risk bar
 */
function updateBtcRiskBar(btc) {
    // Price
    if (btcPriceEl && btc.price !== null) {
        btcPriceEl.textContent = formatNumber(btc.price, 2);
    }

    // Risk badge
    if (btcRiskBadgeEl && btc.risk_level) {
        btcRiskBadgeEl.textContent = window.i18n.translateRiskLevel(btc.risk_level);
        btcRiskBadgeEl.setAttribute('data-risk', btc.risk_level);

        // Check for risk transition to HIGH
        if (previousBtcRisk !== 'HIGH' && btc.risk_level === 'HIGH') {
            playHighRiskAlert();
        }
        previousBtcRisk = btc.risk_level;
    }

    // 1h change
    if (btcChange1hEl && btc.change_1h_pct !== null) {
        btcChange1hEl.textContent = formatPercent(btc.change_1h_pct);
        btcChange1hEl.className = 'btc-stat-value ' + (btc.change_1h_pct >= 0 ? 'positive' : 'negative');
    }

    // 4h change
    if (btcChange4hEl && btc.change_4h_pct !== null) {
        btcChange4hEl.textContent = formatPercent(btc.change_4h_pct);
        btcChange4hEl.className = 'btc-stat-value ' + (btc.change_4h_pct >= 0 ? 'positive' : 'negative');
    }

    // ADX
    if (btcAdxEl && btc.adx15 !== null) {
        btcAdxEl.textContent = formatNumber(btc.adx15, 1);
    }

    // Speed
    if (btcSpeedEl && btc.speed_pct !== null) {
        btcSpeedEl.textContent = btc.speed_pct + '%';
    }
}

/**
 * Update BTC correlation lists
 */
function updateBtcCorrelations(topCorr, weakCorr) {
    if (btcTopCorrEl && topCorr) {
        btcTopCorrEl.innerHTML = topCorr.map(item =>
            `<span class="btc-corr-item">${item.symbol} (${formatNumber(item.corr, 2)})</span>`
        ).join('');
    }

    if (btcWeakCorrEl && weakCorr) {
        btcWeakCorrEl.innerHTML = weakCorr.map(item =>
            `<span class="btc-corr-item">${item.symbol} (${formatNumber(item.corr, 2)})</span>`
        ).join('');
    }
}

// ============================================================================
// TABLE RENDERING
// ============================================================================

/**
 * Render the main data table
 */
function renderTable(rows) {
    if (!tableBody) return;

    const allRows = Array.isArray(rows) ? rows : [];
    const filteredByRules = window.filterManager.applyFilters(allRows);
    const filteredBySearch = applySymbolSearch(filteredByRules);
    updateTableStatus(allRows, filteredByRules, filteredBySearch);

    // Apply sort
    let sorted = window.multiSortManager.applySort(filteredBySearch);

    if (sorted.length === 0) {
        const hiddenByFilters = Math.max(0, allRows.length - filteredByRules.length);
        const hiddenBySearch = Math.max(0, filteredByRules.length - filteredBySearch.length);
        const hasHiddenRows = allRows.length > 0 && (hiddenByFilters > 0 || hiddenBySearch > 0);
        tableBody.innerHTML = `
            <tr>
                <td colspan="21" class="loading-message" data-i18n="common.noData">
                    ${hasHiddenRows
                        ? buildHiddenRowsMessage(hiddenByFilters, hiddenBySearch)
                        : window.i18n.t('common.noData', 'No data available. Check your internet connection and Bybit symbols.')}
                </td>
            </tr>
        `;
        window.hotCoinSeparatorIndex = 0;
        return;
    }

    // =========================================================================
    // HOT COINS SORTING - Move hot coins to the top of the table
    // =========================================================================
    let hotCoinCount = 0;
    
    if (window.hotCoinSymbols?.length > 0 && window.presetManager?.activePreset) {
        const hotSet = new Set(window.hotCoinSymbols);
        const hotRows = [];
        const otherRows = [];
        
        // Partition rows into hot and non-hot
        sorted.forEach(row => {
            if (hotSet.has(row.symbol)) {
                hotRows.push(row);
            } else {
                otherRows.push(row);
            }
        });
        
        // Sort hot rows by their heating score order (maintain order from hotCoinSymbols)
        hotRows.sort((a, b) => {
            return window.hotCoinSymbols.indexOf(a.symbol) - window.hotCoinSymbols.indexOf(b.symbol);
        });
        
        // Combine: hot coins first, then regular coins
        sorted = [...hotRows, ...otherRows];
        hotCoinCount = hotRows.length;
    }
    
    // Store separator position for reference
    window.hotCoinSeparatorIndex = hotCoinCount;

    let html = '';
    let displayIndex = 1;
    
    sorted.forEach((row, idx) => {
        // Insert separator row after hot coins section
        if (idx === hotCoinCount && hotCoinCount > 0) {
            html += `
                <tr class="hot-coins-separator">
                    <td colspan="21"></td>
                </tr>
            `;
        }
        
        const rowClass = getRowClass(row.state);
        const symbol = row.symbol;
        const isWatched = watchList.includes(symbol);

        html += `
            <tr class="${rowClass}" data-symbol="${symbol}">
                <td>${displayIndex}</td>
                <td>
                    <button class="alert-btn${isWatched ? ' active' : ''}" data-symbol="${symbol}" data-action="toggle-watch">
                        ${isWatched ? '🔔' : '🔕'}
                    </button>
                </td>
                <td>
                    <a href="./grid_plan.php?symbol=${symbol}" target="_blank" class="symbol-link">${symbol}</a>
                </td>
                <td>${renderStateBadge(row.state)}</td>
                <td>${renderRecommendationBadge(row.recommendation)}</td>
                <td>${formatNumber(row.price, 5)}</td>
                <td>${formatNumber(row.adx15, 1)}</td>
                <td>${formatNumber(row.adx1h, 1)}</td>
                <td>${formatNumber(row.rsi15, 1)}</td>
                <td>${formatNumber(row.rsi1h, 1)}</td>
                <td>${formatNumber(row.bbw15, 2)}</td>
                <td>${formatNumber(row.bbw1h, 2)}</td>
                <td>${formatNumber(row.atrPct15, 2)}</td>
                <td>${formatNumber(row.atrPct1h, 2)}</td>
                <td class="vol">${formatVolume(row.vol24h)}</td>
                <td>${renderSpeedBar(row.speed_pct)}</td>
                <td>${window.i18n.translateDirection(row.dir_code) || row.dir_label}</td>
                <td>${formatNumber(row.btc_corr, 2)}</td>
                <td>${formatNumber(row.btc_beta, 2)}</td>
                <td>${renderImpactBadge(row.btc_impact)}</td>
                <td>
                    <button class="delete-btn" data-symbol="${symbol}" data-action="delete">X</button>
                </td>
            </tr>
        `;
        
        displayIndex++;
    });

    tableBody.innerHTML = html;
    focusPendingSymbolRow();
}

/**
 * Get row CSS class based on state
 */
function getRowClass(state) {
    const stateClasses = {
        'NEUTRAL': 'state-neutral',
        'TREND_UP': 'state-trend-up',
        'TREND_DOWN': 'state-trend-down',
        'TRANSITION': 'state-transition',
        'VOLATILE': 'state-volatile'
    };
    return stateClasses[state] || '';
}

/**
 * Render state badge
 */
function renderStateBadge(state) {
    const badgeClasses = {
        'NEUTRAL': 'neutral',
        'TREND_UP': 'trend-up',
        'TREND_DOWN': 'trend-down',
        'TRANSITION': 'transition',
        'VOLATILE': 'volatile'
    };
    const badgeClass = badgeClasses[state] || '';
    const label = window.i18n.translateState(state);
    return `<span class="state-badge ${badgeClass}">${label}</span>`;
}

/**
 * Render recommendation badge
 */
function renderRecommendationBadge(rec) {
    const badgeClasses = {
        'Neutral/Fixed': 'neutral-fixed',
        'Neutral/Trailing': 'neutral-trailing',
        'Long/Fixed': 'long-fixed',
        'Long/Trailing': 'long-trailing',
        'Short/Fixed': 'short-fixed',
        'Short/Trailing': 'short-trailing',
        'Volatile/Avoid': 'volatile-avoid',
        'Transition/Wait': 'transition-wait'
    };
    const badgeClass = badgeClasses[rec] || '';
    const label = window.i18n.translateRecommendation(rec);
    return `<span class="rec-badge ${badgeClass}">${label}</span>`;
}

/**
 * Render impact badge
 */
function renderImpactBadge(impact) {
    const badgeClasses = {
        'High': 'high',
        'Medium': 'medium',
        'Low': 'low',
        'Weak': 'weak',
        'Unknown': 'weak'
    };
    const badgeClass = badgeClasses[impact] || 'weak';
    const label = window.i18n.translateImpact(impact);
    return `<span class="impact-badge ${badgeClass}">${label}</span>`;
}

/**
 * Render speed bar
 */
function renderSpeedBar(value) {
    const pct = Math.max(0, Math.min(100, Math.round(value || 0)));
    return `
        <div class="speed-wrap">
            <div class="speed-bar">
                <div class="speed-fill" style="width: ${pct}%;"></div>
            </div>
            <span class="speed-text">${pct}%</span>
        </div>
    `;
}

// ============================================================================
// FORMATTING HELPERS
// ============================================================================

/**
 * Format number with decimals
 */
function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined) return '-';
    const num = Number(value);
    if (isNaN(num)) return '-';

    // Remove trailing zeros
    let str = num.toFixed(decimals);
    if (str.includes('.')) {
        str = str.replace(/\.?0+$/, '');
    }
    return str || '0';
}

/**
 * Format percent with sign
 */
function formatPercent(value) {
    if (value === null || value === undefined) return '-';
    const num = Number(value);
    if (isNaN(num)) return '-';
    const sign = num >= 0 ? '+' : '';
    return sign + num.toFixed(2) + '%';
}

/**
 * Format volume with thousands separator
 */
function formatVolume(value) {
    if (value === null || value === undefined) return '-';
    const num = Number(value);
    if (isNaN(num)) return '-';
    return num.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function normalizeSymbolSearch(value) {
    return (value || '')
        .toString()
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, '')
        .slice(0, 20);
}

function setSymbolSearch(value, shouldRender = true) {
    symbolSearchQuery = normalizeSymbolSearch(value);
    if (symbolSearchEl && symbolSearchEl.value !== symbolSearchQuery) {
        symbolSearchEl.value = symbolSearchQuery;
    }
    if (shouldRender) {
        renderTable(lastRows);
    }
}

function applySymbolSearch(rows) {
    if (!Array.isArray(rows)) return [];
    if (!symbolSearchQuery) return rows;

    return rows.filter(row => {
        const symbol = (row?.symbol || '').toString().toUpperCase();
        return symbol.includes(symbolSearchQuery);
    });
}

function updateTableStatus(allRows, filteredByRules, visibleRows) {
    if (!tableStatusEl) return;

    const total = Array.isArray(allRows) ? allRows.length : 0;
    if (total === 0) {
        tableStatusEl.textContent = '';
        tableStatusEl.style.display = 'none';
        return;
    }

    const activeFilters = Array.isArray(window.filterManager?.rules) ? window.filterManager.rules.length : 0;
    const hiddenByFilters = Math.max(0, total - filteredByRules.length);
    const hiddenBySearch = Math.max(0, filteredByRules.length - visibleRows.length);
    const parts = [`Showing ${visibleRows.length} of ${total} coins`];

    if (activeFilters > 0) {
        parts.push(`${activeFilters} filter rule${activeFilters === 1 ? '' : 's'} active`);
    }
    if (hiddenByFilters > 0) {
        parts.push(`${hiddenByFilters} hidden by filters`);
    }
    if (hiddenBySearch > 0) {
        parts.push(`${hiddenBySearch} hidden by symbol search`);
    }
    if (symbolSearchQuery) {
        parts.push(`Search: ${symbolSearchQuery}`);
    }

    tableStatusEl.textContent = parts.join(' • ');
    tableStatusEl.style.display = 'block';
}

function buildHiddenRowsMessage(hiddenByFilters, hiddenBySearch) {
    const reasons = [];
    if (hiddenByFilters > 0) reasons.push('filters');
    if (hiddenBySearch > 0) reasons.push('symbol search');
    const reasonText = reasons.join(' and ');
    return `No rows match the current ${reasonText}. Reset filters or clear the symbol search to show hidden coins.`;
}

function escapeHtml(value) {
    return (value || '')
        .toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showPageNotice(message, type = 'info', actions = []) {
    if (!pageNoticeEl || !message) return;

    const actionHtml = actions.map(action => `
        <button
            type="button"
            class="notice-action"
            data-action="${escapeHtml(action.action)}"
            data-symbol="${escapeHtml(action.symbol || '')}"
        >
            ${escapeHtml(action.label)}
        </button>
    `).join('');

    pageNoticeEl.innerHTML = `
        <div class="page-notice-card ${escapeHtml(type)}">
            <div class="page-notice-text">${escapeHtml(message)}</div>
            ${actionHtml ? `<div class="page-notice-actions">${actionHtml}</div>` : ''}
        </div>
    `;
    pageNoticeEl.classList.add('is-visible');
}

function clearPageNotice() {
    if (!pageNoticeEl) return;
    pageNoticeEl.innerHTML = '';
    pageNoticeEl.classList.remove('is-visible');
}

function findRowBySymbol(symbol, rows = lastRows) {
    const normalized = normalizeSymbolSearch(symbol);
    if (!normalized || !Array.isArray(rows)) return null;

    return rows.find(row => normalizeSymbolSearch(row?.symbol) === normalized) || null;
}

function queueSymbolFocus(symbol) {
    const normalized = normalizeSymbolSearch(symbol);
    if (!normalized) return;
    pendingFocusSymbol = normalized;
}

function focusPendingSymbolRow() {
    if (!pendingFocusSymbol || !tableBody) return;

    const row = tableBody.querySelector(`tr[data-symbol="${pendingFocusSymbol}"]`);
    if (!row) return;

    pendingFocusSymbol = null;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('row-focus');

    if (focusResetTimer) {
        clearTimeout(focusResetTimer);
    }

    focusResetTimer = setTimeout(() => {
        row.classList.remove('row-focus');
    }, 2400);
}

function showSymbolNotice(symbol, row, hiddenByFilters, hiddenBySearch) {
    const stateLabel = window.i18n.translateState(row.state);
    const recLabel = window.i18n.translateRecommendation(row.recommendation);
    const reasons = [];
    const actions = [];

    if (hiddenByFilters) {
        reasons.push('filters');
        actions.push({
            action: 'reset-filters-show',
            symbol,
            label: 'Reset filters + show symbol',
        });
    }

    if (hiddenBySearch) {
        reasons.push('symbol search');
        actions.push({
            action: 'show-symbol',
            symbol,
            label: 'Show symbol',
        });
    }

    const message = `${symbol} exists in live data (${stateLabel}, ${recLabel}), but it is hidden by the current ${reasons.join(' and ')}.`;
    showPageNotice(message, 'warning', actions);
}

function handlePageNoticeClick(e) {
    const button = e.target.closest('[data-action]');
    if (!button) return;

    const action = button.dataset.action || '';
    const symbol = button.dataset.symbol || '';

    if (action === 'show-symbol') {
        setSymbolSearch(symbol, false);
        queueSymbolFocus(symbol);
        clearPageNotice();
        renderTable(lastRows);
        return;
    }

    if (action === 'reset-filters-show') {
        window.filterManager?.reset?.();
        setSymbolSearch(symbol, false);
        queueSymbolFocus(symbol);
        clearPageNotice();
        renderTable(lastRows);
    }
}

function revealSymbol(symbol) {
    const normalized = normalizeSymbolSearch(symbol);
    if (!normalized) return;

    const allRows = Array.isArray(lastRows) ? lastRows : [];
    const row = findRowBySymbol(normalized, allRows);
    if (!row) {
        showPageNotice(`${normalized} is saved, but no live scanner row is available yet.`, 'warning');
        return;
    }

    const filteredByRules = window.filterManager.applyFilters(allRows);
    const visibleRows = applySymbolSearch(filteredByRules);
    const isVisibleAfterFilters = !!findRowBySymbol(normalized, filteredByRules);
    const isVisible = !!findRowBySymbol(normalized, visibleRows);

    if (isVisible) {
        clearPageNotice();
        queueSymbolFocus(normalized);
        renderTable(lastRows);
        return;
    }

    showSymbolNotice(normalized, row, !isVisibleAfterFilters, isVisibleAfterFilters && !isVisible);
}

// ============================================================================
// SKIPPED SYMBOLS
// ============================================================================

/**
 * Show skipped symbols
 */
function showSkippedSymbols(symbols) {
    if (skippedSymbolsEl) {
        skippedSymbolsEl.textContent = `Skipped symbols: ${symbols.join(', ')}`;
        skippedSymbolsEl.style.display = 'block';
    }
}

/**
 * Hide skipped symbols
 */
function hideSkippedSymbols() {
    if (skippedSymbolsEl) {
        skippedSymbolsEl.style.display = 'none';
    }
}

// ============================================================================
// USER INTERACTIONS
// ============================================================================

/**
 * Handle add symbol form submission
 */
async function handleAddSymbol(e) {
    e.preventDefault();

    const input = document.getElementById('newSymbol');
    if (!input) return;

    let symbol = input.value.trim().toUpperCase();
    if (!symbol) return;

    // Sanitize
    symbol = symbol.replace(/[^A-Z0-9]/g, '');
    if (symbol.length > 20) {
        symbol = symbol.substring(0, 20);
    }

    try {
        const formData = new FormData();
        formData.append('action', 'add');
        formData.append('symbol', symbol);

        const res = await fetch('./scanner.php', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        alert(data.message || 'Done');
        if (data.ok) {
            input.value = '';
            const addedSymbol = data.symbol || symbol;
            await fetchData();
            revealSymbol(addedSymbol);
        }
    } catch (err) {
        console.error('Add symbol error:', err);
        alert('Error adding symbol');
    }
}

/**
 * Handle table click events (delegation)
 */
function handleTableClick(e) {
    const target = e.target;

    // Toggle watch button
    if (target.classList.contains('alert-btn')) {
        const symbol = target.dataset.symbol;
        toggleWatch(symbol);
        return;
    }

    // Delete button
    if (target.classList.contains('delete-btn')) {
        const symbol = target.dataset.symbol;
        deleteSymbol(symbol);
        return;
    }
}

/**
 * Toggle watch list for a symbol
 */
function toggleWatch(symbol) {
    const idx = watchList.indexOf(symbol);
    if (idx === -1) {
        watchList.push(symbol);
    } else {
        watchList.splice(idx, 1);
    }
    saveWatchList();
    renderTable(lastRows);
}

/**
 * Delete a symbol
 */
async function deleteSymbol(symbol) {
    if (!confirm(`Delete ${symbol} from the list?`)) return;

    try {
        const formData = new FormData();
        formData.append('action', 'delete');
        formData.append('symbol', symbol);

        const res = await fetch('./scanner.php', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        alert(data.message || 'Done');
        if (data.ok) {
            fetchData(); // Refresh data
        }
    } catch (err) {
        console.error('Delete symbol error:', err);
        alert('Error deleting symbol');
    }
}

// ============================================================================
// ALERTS
// ============================================================================

/**
 * Check for neutral transitions and alert
 */
function checkNeutralTransitions(rows) {
    rows.forEach(row => {
        const sym = row.symbol;
        const nowNeutral = !!row.neutral;
        const prev = previousNeutral[sym];

        // Alert if watched symbol exits neutral
        if (watchList.includes(sym) && prev === true && nowNeutral === false) {
            playNeutralExitAlert();
        }

        previousNeutral[sym] = nowNeutral;
    });
}

/**
 * Audio context for alerts
 */
let audioCtx = null;

/**
 * Get or create audio context
 */
function getAudioContext() {
    if (!audioCtx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
            audioCtx = new AC();
        }
    }
    return audioCtx;
}

/**
 * Check if sound is enabled
 */
function isSoundEnabled() {
    const checkbox = document.getElementById('enableSound');
    return checkbox ? checkbox.checked : true;
}

/**
 * Play alert when symbol exits neutral
 */
function playNeutralExitAlert() {
    if (!isSoundEnabled()) return;

    const ctx = getAudioContext();
    if (!ctx) return;

    try {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = 'sine';
        osc.frequency.value = 880;
        osc.connect(gain);
        gain.connect(ctx.destination);

        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);

        osc.start();
        osc.stop(ctx.currentTime + 0.4);
    } catch (e) {
        console.error('Audio alert error:', e);
    }
}

/**
 * Play alert when BTC risk goes HIGH
 */
function playHighRiskAlert() {
    if (!isSoundEnabled()) return;

    const ctx = getAudioContext();
    if (!ctx) return;

    try {
        // Two-tone alert for HIGH risk
        const freqs = [880, 1100];
        freqs.forEach((freq, i) => {
            setTimeout(() => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();

                osc.type = 'sine';
                osc.frequency.value = freq;
                osc.connect(gain);
                gain.connect(ctx.destination);

                gain.gain.setValueAtTime(0.3, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);

                osc.start();
                osc.stop(ctx.currentTime + 0.3);
            }, i * 200);
        });
    } catch (e) {
        console.error('High risk alert error:', e);
    }
}

// ============================================================================
// STARTUP
// ============================================================================

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
