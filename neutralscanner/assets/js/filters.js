/**
 * Neutral Scanner Pro - Filter Manager
 * Multi-rule filter builder with localStorage persistence
 */

// Filter column definitions (same as sort columns plus additional filter-friendly columns)
const FILTER_COLUMNS = [
    { key: 'symbol', label: 'Symbol', type: 'string' },
    { key: 'state', label: 'State', type: 'enum', values: ['NEUTRAL', 'TREND_UP', 'TREND_DOWN', 'TRANSITION', 'VOLATILE'] },
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
    { key: 'dir_code', label: 'Direction', type: 'enum', values: ['flat_range', 'neutral_up', 'neutral_down', 'unclear', 'unknown'] },
    { key: 'btc_corr', label: 'BTC Corr', type: 'number' },
    { key: 'btc_beta', label: 'BTC Beta', type: 'number' },
    { key: 'btc_impact', label: 'BTC Impact', type: 'enum', values: ['High', 'Medium', 'Low', 'Weak', 'Unknown'] },
    { key: 'neutral', label: 'Is Neutral', type: 'boolean' },
];

// Filter operators
const FILTER_OPERATORS = {
    '=': { label: 'Equals', types: ['string', 'number', 'enum', 'boolean'] },
    '!=': { label: 'Not Equals', types: ['string', 'number', 'enum', 'boolean'] },
    '>': { label: 'Greater Than', types: ['number'] },
    '>=': { label: 'Greater Or Equal', types: ['number'] },
    '<': { label: 'Less Than', types: ['number'] },
    '<=': { label: 'Less Or Equal', types: ['number'] },
    'contains': { label: 'Contains', types: ['string'] },
    'between': { label: 'Between', types: ['number'] },
};

/**
 * FilterManager class
 * Manages multi-rule filters with localStorage persistence
 */
class FilterManager {
    constructor() {
        this.rules = [];
        this.combineMode = 'AND'; // 'AND' or 'OR'
        this.storageKey = 'scanner_filter_config';
        this.containerId = 'filterRules';
        this.loadFromStorage();
    }

    /**
     * Load filter configuration from localStorage
     */
    loadFromStorage() {
        try {
            const saved = localStorage.getItem(this.storageKey);
            if (saved) {
                const parsed = JSON.parse(saved);
                this.rules = parsed.rules || [];
                this.combineMode = parsed.combineMode || 'AND';

                // Validate loaded data
                if (!Array.isArray(this.rules)) {
                    this.rules = [];
                }
            }
        } catch (e) {
            console.error('Failed to load filter config:', e);
            this.rules = [];
        }
    }

    /**
     * Save filter configuration to localStorage
     */
    saveToStorage() {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify({
                rules: this.rules,
                combineMode: this.combineMode,
            }));
        } catch (e) {
            console.error('Failed to save filter config:', e);
        }
    }

    /**
     * Add a new filter rule
     */
    addRule(column = 'state', operator = '=', value = '', value2 = '') {
        this.rules.push({ col: column, op: operator, val: value, val2: value2 });
        this.saveToStorage();
        this.renderUI();
    }

    /**
     * Remove a filter rule by index
     */
    removeRule(index) {
        if (index >= 0 && index < this.rules.length) {
            this.rules.splice(index, 1);
            this.saveToStorage();
            this.renderUI();
        }
    }

    /**
     * Update a filter rule
     */
    updateRule(index, column, operator, value, value2 = '') {
        if (index >= 0 && index < this.rules.length) {
            this.rules[index] = { col: column, op: operator, val: value, val2: value2 };
            this.saveToStorage();
        }
    }

    /**
     * Set combine mode (AND/OR)
     */
    setCombineMode(mode) {
        this.combineMode = mode;
        this.saveToStorage();
    }

    /**
     * Reset all filter rules
     */
    reset() {
        this.rules = [];
        this.combineMode = 'AND';
        this.saveToStorage();
        this.renderUI();

        // Update combine mode select
        const combineSelect = document.getElementById('filterCombineMode');
        if (combineSelect) {
            combineSelect.value = 'AND';
        }
    }

    /**
     * Get operators available for a column type
     */
    getOperatorsForColumn(columnKey) {
        const colDef = FILTER_COLUMNS.find(c => c.key === columnKey);
        if (!colDef) return Object.keys(FILTER_OPERATORS);

        return Object.entries(FILTER_OPERATORS)
            .filter(([_, op]) => op.types.includes(colDef.type))
            .map(([key, _]) => key);
    }

    /**
     * Evaluate a single filter rule against a row
     */
    evaluateRule(row, rule) {
        const colDef = FILTER_COLUMNS.find(c => c.key === rule.col);
        if (!colDef) return true;

        let val = row[rule.col];
        let target = rule.val;
        let target2 = rule.val2;

        // Type conversion
        if (colDef.type === 'number') {
            val = Number(val);
            target = Number(target);
            target2 = Number(target2);
            if (isNaN(val)) val = 0;
        } else if (colDef.type === 'boolean') {
            val = !!val;
            target = target === 'true' || target === true || target === '1';
        } else if (colDef.type === 'string' || colDef.type === 'enum') {
            val = (val || '').toString().toLowerCase();
            target = (target || '').toString().toLowerCase();
        }

        switch (rule.op) {
            case '=':
                return val === target;
            case '!=':
                return val !== target;
            case '>':
                return val > target;
            case '>=':
                return val >= target;
            case '<':
                return val < target;
            case '<=':
                return val <= target;
            case 'contains':
                return val.includes(target);
            case 'between':
                return val >= target && val <= target2;
            default:
                return true;
        }
    }

    /**
     * Apply filters to an array of rows
     */
    applyFilters(rows) {
        if (!this.rules.length || !Array.isArray(rows)) {
            return rows;
        }

        return rows.filter(row => {
            const results = this.rules.map(rule => this.evaluateRule(row, rule));

            if (this.combineMode === 'AND') {
                return results.every(r => r);
            } else {
                return results.some(r => r);
            }
        });
    }

    /**
     * Render filter rules UI
     */
    renderUI() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        if (this.rules.length === 0) {
            container.innerHTML = '<div class="filter-rule"><span style="color: var(--text-muted);">No filter rules defined. Click "Add Rule" to start.</span></div>';
            return;
        }

        let html = '';
        this.rules.forEach((rule, index) => {
            const colDef = FILTER_COLUMNS.find(c => c.key === rule.col);
            const availableOps = this.getOperatorsForColumn(rule.col);
            const showSecondValue = rule.op === 'between';

            html += `
                <div class="filter-rule" data-index="${index}">
                    <select class="filter-col-select" data-index="${index}">
                        ${this.renderColumnOptions(rule.col)}
                    </select>
                    <select class="filter-op-select" data-index="${index}">
                        ${this.renderOperatorOptions(availableOps, rule.op)}
                    </select>
                    ${this.renderValueInput(colDef, rule, index, showSecondValue)}
                    <button class="remove-btn" data-index="${index}">X</button>
                </div>
            `;
        });

        container.innerHTML = html;
        this.bindUIEvents();
    }

    /**
     * Render column options for select
     */
    renderColumnOptions(selectedKey) {
        return FILTER_COLUMNS.map(col =>
            `<option value="${col.key}" ${col.key === selectedKey ? 'selected' : ''}>${col.label}</option>`
        ).join('');
    }

    /**
     * Render operator options for select
     */
    renderOperatorOptions(availableOps, selectedOp) {
        return availableOps.map(op =>
            `<option value="${op}" ${op === selectedOp ? 'selected' : ''}>${FILTER_OPERATORS[op].label}</option>`
        ).join('');
    }

    /**
     * Render value input based on column type
     */
    renderValueInput(colDef, rule, index, showSecondValue) {
        if (!colDef) {
            return `<input type="text" class="filter-val-input" data-index="${index}" value="${rule.val || ''}">`;
        }

        if (colDef.type === 'enum' && colDef.values) {
            return `
                <select class="filter-val-input" data-index="${index}">
                    <option value="">-- Select --</option>
                    ${colDef.values.map(v =>
                        `<option value="${v}" ${v === rule.val ? 'selected' : ''}>${v}</option>`
                    ).join('')}
                </select>
            `;
        }

        if (colDef.type === 'boolean') {
            return `
                <select class="filter-val-input" data-index="${index}">
                    <option value="true" ${rule.val === 'true' || rule.val === true ? 'selected' : ''}>Yes</option>
                    <option value="false" ${rule.val === 'false' || rule.val === false ? 'selected' : ''}>No</option>
                </select>
            `;
        }

        if (colDef.type === 'number') {
            let html = `<input type="number" class="filter-val-input" data-index="${index}" value="${rule.val || ''}" step="any">`;
            if (showSecondValue) {
                html += `<span>to</span><input type="number" class="filter-val2-input" data-index="${index}" value="${rule.val2 || ''}" step="any">`;
            }
            return html;
        }

        return `<input type="text" class="filter-val-input" data-index="${index}" value="${rule.val || ''}">`;
    }

    /**
     * Bind UI events for filter rule controls
     */
    bindUIEvents() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        // Column select change
        container.querySelectorAll('.filter-col-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const rule = this.rules[index];
                if (rule) {
                    // Reset operator to first available for new column type
                    const availableOps = this.getOperatorsForColumn(e.target.value);
                    const newOp = availableOps.includes(rule.op) ? rule.op : availableOps[0];
                    this.updateRule(index, e.target.value, newOp, '', '');
                    this.renderUI();
                }
            });
        });

        // Operator select change
        container.querySelectorAll('.filter-op-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const rule = this.rules[index];
                if (rule) {
                    this.updateRule(index, rule.col, e.target.value, rule.val, rule.val2);
                    // Re-render if switching to/from 'between'
                    if (e.target.value === 'between' || rule.op === 'between') {
                        this.renderUI();
                    }
                }
            });
        });

        // Value input change
        container.querySelectorAll('.filter-val-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const rule = this.rules[index];
                if (rule) {
                    this.updateRule(index, rule.col, rule.op, e.target.value, rule.val2);
                }
            });
        });

        // Second value input change (for 'between')
        container.querySelectorAll('.filter-val2-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const rule = this.rules[index];
                if (rule) {
                    this.updateRule(index, rule.col, rule.op, rule.val, e.target.value);
                }
            });
        });

        // Remove button click
        container.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.dataset.index);
                this.removeRule(index);
            });
        });
    }

    /**
     * Initialize the manager and set up global events
     */
    init() {
        this.renderUI();

        // Update combine mode select to match stored value
        const combineSelect = document.getElementById('filterCombineMode');
        if (combineSelect) {
            combineSelect.value = this.combineMode;
            combineSelect.addEventListener('change', (e) => {
                this.setCombineMode(e.target.value);
            });
        }

        // Add Rule button
        const addBtn = document.getElementById('addFilterRule');
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                this.addRule();
            });
        }

        // Reset button
        const resetBtn = document.getElementById('resetFilters');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                this.reset();
            });
        }
    }
}

// Create global instance
window.filterManager = new FilterManager();
