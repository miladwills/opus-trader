/**
 * Neutral Scanner Pro - Multi-Sort Manager
 * Supports up to 8 sorting levels with all table columns
 */

// Column definitions for sorting
const SORT_COLUMNS = [
    { key: 'symbol', label: 'Symbol', type: 'string' },
    { key: 'state', label: 'State', type: 'state' },
    { key: 'recommendation', label: 'Recommendation', type: 'string' },
    { key: 'price', label: 'Price', type: 'number' },
    { key: 'vol24h', label: '24h Volume', type: 'number' },
    { key: 'adx15', label: 'ADX 15m', type: 'number' },
    { key: 'adx1h', label: 'ADX 1h', type: 'number' },
    { key: 'rsi15', label: 'RSI 15m', type: 'number' },
    { key: 'rsi1h', label: 'RSI 1h', type: 'number' },
    { key: 'bbw15', label: 'BBW% 15m', type: 'number' },
    { key: 'bbw1h', label: 'BBW% 1h', type: 'number' },
    { key: 'atrPct15', label: 'ATR% 15m', type: 'number' },
    { key: 'atrPct1h', label: 'ATR% 1h', type: 'number' },
    { key: 'speed_pct', label: 'Speed %', type: 'number' },
    { key: 'dir_code', label: 'Direction', type: 'string' },
    { key: 'btc_corr', label: 'BTC Corr', type: 'number' },
    { key: 'btc_beta', label: 'BTC Beta', type: 'number' },
    { key: 'btc_impact', label: 'BTC Impact', type: 'impact' },
    { key: 'neutral', label: 'Neutral Status', type: 'boolean' },
];

// State priority order (for sorting)
const STATE_ORDER = {
    'NEUTRAL': 0,
    'TREND_UP': 1,
    'TREND_DOWN': 2,
    'TRANSITION': 3,
    'VOLATILE': 4
};

// Impact priority order
const IMPACT_ORDER = {
    'High': 0,
    'Medium': 1,
    'Low': 2,
    'Weak': 3,
    'Unknown': 4
};

/**
 * MultiSortManager class
 * Manages multi-level sorting with localStorage persistence
 */
class MultiSortManager {
    constructor(maxLevels = 8) {
        this.maxLevels = maxLevels;
        this.levels = [];
        this.storageKey = 'scanner_sort_config';
        this.containerId = 'sortLevels';
        this.loadFromStorage();
    }

    /**
     * Load sort configuration from localStorage
     */
    loadFromStorage() {
        try {
            const saved = localStorage.getItem(this.storageKey);
            if (saved) {
                this.levels = JSON.parse(saved);
                // Validate loaded data
                if (!Array.isArray(this.levels)) {
                    this.levels = [];
                }
            }
        } catch (e) {
            console.error('Failed to load sort config:', e);
            this.levels = [];
        }
    }

    /**
     * Save sort configuration to localStorage
     */
    saveToStorage() {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(this.levels));
        } catch (e) {
            console.error('Failed to save sort config:', e);
        }
    }

    notifyChange() {
        try {
            document.dispatchEvent(new Event('sort:changed'));
        } catch (e) {
            // ignore
        }
    }

    /**
     * Add a new sort level
     */
    addLevel(column = 'neutral', direction = 'desc') {
        if (this.levels.length < this.maxLevels) {
            this.levels.push({ col: column, dir: direction });
            this.saveToStorage();
            this.renderUI();
            this.notifyChange();
            return true;
        }
        return false;
    }

    /**
     * Remove a sort level by index
     */
    removeLevel(index) {
        if (index >= 0 && index < this.levels.length) {
            this.levels.splice(index, 1);
            this.saveToStorage();
            this.renderUI();
            this.notifyChange();
        }
    }

    /**
     * Update a sort level
     */
    updateLevel(index, column, direction) {
        if (index >= 0 && index < this.levels.length) {
            this.levels[index] = { col: column, dir: direction };
            this.saveToStorage();
            this.notifyChange();
        }
    }

    /**
     * Reset all sort levels
     */
    reset() {
        this.levels = [];
        this.saveToStorage();
        this.renderUI();
        this.notifyChange();
    }

    /**
     * Get sort value from a row for comparison
     */
    getSortValue(row, key) {
        const colDef = SORT_COLUMNS.find(c => c.key === key);
        if (!colDef) return { isNull: true, v: 0 };

        const val = row[key];
        const isMissing = (val === null || val === undefined || val === '');
        if (isMissing) {
            // Always push missing values to the bottom, regardless of sort direction.
            return { isNull: true, v: 0 };
        }

        switch (colDef.type) {
            case 'number': {
                const num = Number(val);
                return { isNull: isNaN(num), v: isNaN(num) ? 0 : num };
            }

            case 'string':
                return { isNull: false, v: (val || '').toString().toLowerCase() };

            case 'boolean':
                return { isNull: false, v: val ? 1 : 0 };

            case 'state':
                return { isNull: false, v: STATE_ORDER[val] ?? 99 };

            case 'impact':
                return { isNull: false, v: IMPACT_ORDER[val] ?? 99 };

            default:
                return { isNull: false, v: val };
        }
    }

    /**
     * Apply multi-level sort to an array of rows
     */
    applySort(rows) {
        if (!this.levels.length || !Array.isArray(rows)) {
            return rows;
        }

        const sorted = [...rows];
        sorted.sort((a, b) => {
            for (const level of this.levels) {
                const av = this.getSortValue(a, level.col);
                const bv = this.getSortValue(b, level.col);

                // Missing values always go to bottom
                if (av.isNull !== bv.isNull) {
                    return av.isNull ? 1 : -1;
                }

                // Handle different comparison types
                let comparison = 0;
                const aVal = av.v;
                const bVal = bv.v;
                if (typeof aVal === 'string' && typeof bVal === 'string') {
                    comparison = aVal.localeCompare(bVal);
                } else {
                    if (aVal < bVal) comparison = -1;
                    else if (aVal > bVal) comparison = 1;
                }

                if (comparison !== 0) {
                    return level.dir === 'asc' ? comparison : -comparison;
                }
            }
            // Deterministic tie-breaker (fixes "sorting not consistent" across refreshes)
            return (a.symbol || '').localeCompare(b.symbol || '');
        });

        return sorted;
    }

    /**
     * Render sort levels UI
     */
    renderUI() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        if (this.levels.length === 0) {
            container.innerHTML = '<div class="sort-level"><span style="color: var(--text-muted);">No sort levels defined. Click "Add Level" to start.</span></div>';
            return;
        }

        let html = '';
        this.levels.forEach((level, index) => {
            html += `
                <div class="sort-level" data-index="${index}">
                    <span class="sort-level-number">${index + 1}</span>
                    <select class="sort-col-select" data-index="${index}">
                        ${this.renderColumnOptions(level.col)}
                    </select>
                    <select class="sort-dir-select" data-index="${index}">
                        <option value="desc" ${level.dir === 'desc' ? 'selected' : ''} data-i18n="sort.desc">Descending</option>
                        <option value="asc" ${level.dir === 'asc' ? 'selected' : ''} data-i18n="sort.asc">Ascending</option>
                    </select>
                    <button class="remove-btn" data-index="${index}">X</button>
                </div>
            `;
        });

        container.innerHTML = html;
        this.bindUIEvents();

        // Trigger i18n update if available
        if (typeof window.i18n !== 'undefined' && window.i18n.applyTranslations) {
            window.i18n.applyTranslations();
        }
    }

    /**
     * Render column options for select
     */
    renderColumnOptions(selectedKey) {
        return SORT_COLUMNS.map(col =>
            `<option value="${col.key}" ${col.key === selectedKey ? 'selected' : ''}>${col.label}</option>`
        ).join('');
    }

    /**
     * Bind UI events for sort level controls
     */
    bindUIEvents() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        // Column select change
        container.querySelectorAll('.sort-col-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const dirSelect = container.querySelector(`.sort-dir-select[data-index="${index}"]`);
                this.updateLevel(index, e.target.value, dirSelect?.value || 'desc');
            });
        });

        // Direction select change
        container.querySelectorAll('.sort-dir-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const colSelect = container.querySelector(`.sort-col-select[data-index="${index}"]`);
                this.updateLevel(index, colSelect?.value || 'symbol', e.target.value);
            });
        });

        // Remove button click
        container.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.dataset.index);
                this.removeLevel(index);
            });
        });
    }

    /**
     * Initialize the manager and set up global events
     */
    init() {
        this.renderUI();

        // Add Level button
        const addBtn = document.getElementById('addSortLevel');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                if (!this.addLevel()) {
                    alert(`Maximum ${this.maxLevels} sort levels allowed.`);
                }
            });
        }

        // Reset button
        const resetBtn = document.getElementById('resetSort');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                this.reset();
            });
        }
    }
}

// Create global instance
window.multiSortManager = new MultiSortManager(8);
