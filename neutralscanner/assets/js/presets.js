/**
 * Neutral Scanner Pro - Preset Manager
 * Saves/loads named presets for BOTH Multi-Level Sort + Filter Builder.
 *
 * Preset includes:
 * - multiSortManager.levels
 * - filterManager.rules
 * - filterManager.combineMode
 *
 * Storage: localStorage
 */

(function () {
    const STORAGE_KEY = 'scanner_presets_v1';

    function safeName(input) {
        const name = (input || '').toString().trim();
        // Keep it simple: allow letters/numbers/spaces/_- only; collapse spaces.
        // Use unicode property escapes when available (modern browsers), otherwise fallback to ASCII.
        let cleaned = name.replace(/\s+/g, ' ');
        try {
            cleaned = cleaned.replace(/[^\p{L}\p{N}\s_\-]/gu, '');
        } catch (e) {
            cleaned = cleaned.replace(/[^A-Za-z0-9\s_\-]/g, '');
        }
        return cleaned.slice(0, 32);
    }

    function loadPresets() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            console.error('Failed to load presets:', e);
            return [];
        }
    }

    function savePresets(presets) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(presets || []));
        } catch (e) {
            console.error('Failed to save presets:', e);
        }
    }

    class PresetManager {
        constructor() {
            this.presets = loadPresets();
            this.activePreset = null;

            this.nameInputId = 'presetName';
            this.saveBtnId = 'savePreset';
            this.buttonsContainerId = 'presetButtons';
        }

        async init() {
            await this.ensurePresetSeeds();
            this.presets = loadPresets();
            this.render();
            this.bind();
        }

        async ensurePresetSeeds() {
            const current = loadPresets();
            const map = new Map(current.map(p => [p.name, p]));

            const defaultAll = {
                name: 'Default - All Coins',
                sortLevels: [{ col: 'symbol', dir: 'asc' }],
                filterRules: [],
                combineMode: 'AND',
            };

            const blankCustom = {
                name: 'Blank - Custom',
                sortLevels: [],
                filterRules: [],
                combineMode: 'AND',
            };

            map.set(defaultAll.name, defaultAll);
            map.set(blankCustom.name, blankCustom);

            try {
                const res = await fetch('./presets/presets_all.json?v=20260314c');
                if (res.ok) {
                    const incoming = await res.json();
                    if (Array.isArray(incoming)) {
                        incoming.forEach(p => {
                            if (p && p.name) map.set(p.name, p);
                        });
                    }
                }
            } catch (e) {
                console.warn('Failed to load presets_all.json', e);
            }

            const next = [...map.values()];
            if (JSON.stringify(next) !== JSON.stringify(current)) {
                savePresets(next);
            }
        }

        bind() {
            const saveBtn = document.getElementById(this.saveBtnId);
            const nameInput = document.getElementById(this.nameInputId);
            if (saveBtn) {
                saveBtn.addEventListener('click', () => {
                    const name = safeName(nameInput ? nameInput.value : '');
                    this.saveCurrentAs(name);
                });
            }
            if (nameInput) {
                nameInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        const name = safeName(nameInput.value);
                        this.saveCurrentAs(name);
                    }
                });
            }
        }

        getCurrentSnapshot() {
            const sortLevels = Array.isArray(window.multiSortManager?.levels)
                ? window.multiSortManager.levels
                : [];

            const filterRules = Array.isArray(window.filterManager?.rules)
                ? window.filterManager.rules
                : [];

            const combineMode = (window.filterManager?.combineMode === 'OR') ? 'OR' : 'AND';

            // Deep clone to avoid accidental mutations
            return {
                sortLevels: JSON.parse(JSON.stringify(sortLevels)),
                filterRules: JSON.parse(JSON.stringify(filterRules)),
                combineMode,
            };
        }

        saveCurrentAs(name) {
            const t = (k, fb) => (window.i18n?.t ? window.i18n.t(k, fb) : fb);

            if (!name) {
                alert(t('presets.nameRequired', 'Please enter a preset name.'));
                return;
            }

            const existingIdx = this.presets.findIndex(p => (p.name || '').toLowerCase() === name.toLowerCase());
            if (existingIdx >= 0) {
                const ok = confirm(t('presets.confirmOverwrite', 'Preset already exists. Overwrite it?'));
                if (!ok) return;
            }

            const snap = this.getCurrentSnapshot();
            const now = new Date().toISOString();
            const preset = {
                name,
                ...snap,
                updatedAt: now,
                createdAt: existingIdx >= 0 ? (this.presets[existingIdx].createdAt || now) : now,
            };

            if (existingIdx >= 0) {
                this.presets[existingIdx] = preset;
            } else {
                this.presets.push(preset);
                // Keep newest at top
                this.presets.sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
            }

            savePresets(this.presets);
            this.activePreset = name;
            this.render();
        }

        applyPresetByName(name) {
            const preset = this.presets.find(p => p.name === name);
            if (!preset) return;

            // Apply sort
            if (window.multiSortManager) {
                window.multiSortManager.levels = Array.isArray(preset.sortLevels) ? preset.sortLevels : [];
                window.multiSortManager.saveToStorage?.();
                window.multiSortManager.renderUI?.();
                // trigger re-render
                try { document.dispatchEvent(new Event('sort:changed')); } catch (e) {}
            }

            // Apply filters
            if (window.filterManager) {
                window.filterManager.rules = Array.isArray(preset.filterRules) ? preset.filterRules : [];
                window.filterManager.combineMode = (preset.combineMode === 'OR') ? 'OR' : 'AND';
                window.filterManager.saveToStorage?.();
                window.filterManager.renderUI?.();
                const combineSelect = document.getElementById('filterCombineMode');
                if (combineSelect) combineSelect.value = window.filterManager.combineMode;
            }

            this.activePreset = name;
            this.render();

            // Re-render table if app exposes rows
            try {
                if (typeof window.renderTable === 'function' && Array.isArray(window.lastRows)) {
                    window.renderTable(window.lastRows);
                }
            } catch (e) {}

            // Fallback: app.js calls renderTable in response to sort changes, but filters need it too
            try {
                document.dispatchEvent(new Event('preset:applied'));
            } catch (e) {}

            // Mark hot coins after table is rendered (small delay to ensure DOM is ready)
            setTimeout(() => {
                this.markHotCoinsInTable();
            }, 50);
        
            // Smooth-scroll to the main table so the user sees the result immediately
            try {
                const table = document.getElementById('mainTable');
                const container = table ? table.closest('.table-container') : null;
                const target = container || table;

                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });

                    // If the table still ends up too low in the viewport (common when the table is short),
                    // nudge scroll so the table header sits near the top.
                    setTimeout(() => {
                        try {
                            const rect = (table || target).getBoundingClientRect();
                            const desiredTop = 24; // px from top of viewport
                            if (rect.top > desiredTop + 8) {
                                window.scrollBy({ top: rect.top - desiredTop, left: 0, behavior: 'smooth' });
                            }
                        } catch (e) {}
                    }, 250);
                }
            } catch (e) {}

        }

        deletePreset(name) {
            const t = (k, fb) => (window.i18n?.t ? window.i18n.t(k, fb) : fb);
            const ok = confirm(t('presets.confirmDelete', 'Delete this preset?'));
            if (!ok) return;

            this.presets = this.presets.filter(p => p.name !== name);
            if (this.activePreset === name) this.activePreset = null;
            savePresets(this.presets);
            this.render();
        }

        computePresetCount(preset) {
            try {
                const rows = Array.isArray(window.lastRows) ? window.lastRows : null;
                if (!rows || !rows.length) return null;

                const rules = Array.isArray(preset.filterRules) ? preset.filterRules : [];
                const combineMode = (preset.combineMode === 'OR') ? 'OR' : 'AND';

                // If no filters, all rows are available
                if (!rules.length) return rows.length;

                const evaluator = window.filterManager?.evaluateRule?.bind(window.filterManager);
                if (!evaluator) return null;

                let count = 0;
                for (const row of rows) {
                    const results = rules.map(rule => evaluator(row, rule));
                    const matches = (combineMode === 'AND')
                        ? results.every(Boolean)
                        : results.some(Boolean);
                    if (matches) count += 1;
                }
                return count;
            } catch (e) {
                console.error('Failed to compute preset count', e);
                return null;
            }
        }

        // ====================================================================
        // HOT COINS SCORING SYSTEM
        // Identifies safe, profitable coins that are starting to heat up
        // ====================================================================

        /**
         * Calculate safety score for a coin (0-1)
         * Lower volatility and balanced indicators = higher score
         */
        calcSafetyScore(row) {
            let score = 0;
            let factors = 0;

            // BBW15 - lower is safer (target: < 20%)
            if (row.bbw15 !== null && row.bbw15 !== undefined) {
                const bbwScore = Math.max(0, 1 - (row.bbw15 / 25));
                score += bbwScore;
                factors++;
            }

            // ATR% 15 - lower is safer (target: < 2.5%)
            if (row.atrPct15 !== null && row.atrPct15 !== undefined) {
                const atrScore = Math.max(0, 1 - (row.atrPct15 / 3.5));
                score += atrScore;
                factors++;
            }

            // RSI15 - closer to 50 is safer
            if (row.rsi15 !== null && row.rsi15 !== undefined) {
                const rsiDist = Math.abs(row.rsi15 - 50);
                const rsiScore = Math.max(0, 1 - (rsiDist / 35));
                score += rsiScore;
                factors++;
            }

            // BTC Impact - lower impact is safer
            if (row.btc_impact) {
                const impactScores = { 'Weak': 1.0, 'Low': 0.8, 'Medium': 0.5, 'High': 0.2, 'Unknown': 0.5 };
                score += impactScores[row.btc_impact] || 0.5;
                factors++;
            }

            return factors > 0 ? score / factors : 0;
        }

        /**
         * Calculate profitability score for a coin (0-1)
         * Good volume and moderate volatility for profit potential
         */
        calcProfitScore(row) {
            let score = 0;
            let factors = 0;

            // Volume - higher is better (target: > 50M for max score)
            if (row.vol24h !== null && row.vol24h !== undefined) {
                const volScore = Math.min(1, row.vol24h / 80000000);
                score += volScore;
                factors++;
            }

            // ATR% 15 - moderate is best for profit (sweet spot: 0.5-2.0%)
            if (row.atrPct15 !== null && row.atrPct15 !== undefined) {
                const atr = row.atrPct15;
                let atrScore;
                if (atr < 0.3) {
                    atrScore = atr / 0.3 * 0.5; // Too low, scale up to 0.5
                } else if (atr <= 2.0) {
                    atrScore = 0.5 + ((atr - 0.3) / 1.7) * 0.5; // Sweet spot, 0.5-1.0
                } else {
                    atrScore = Math.max(0, 1 - ((atr - 2.0) / 2.0)); // Too high, scale down
                }
                score += atrScore;
                factors++;
            }

            // BBW15 - moderate is best (sweet spot: 5-18%)
            if (row.bbw15 !== null && row.bbw15 !== undefined) {
                const bbw = row.bbw15;
                let bbwScore;
                if (bbw < 3) {
                    bbwScore = bbw / 3 * 0.4; // Too tight
                } else if (bbw <= 18) {
                    bbwScore = 0.4 + ((bbw - 3) / 15) * 0.6; // Good range
                } else {
                    bbwScore = Math.max(0, 1 - ((bbw - 18) / 15)); // Too wide
                }
                score += bbwScore;
                factors++;
            }

            return factors > 0 ? score / factors : 0;
        }

        /**
         * Calculate "heating up" score for a coin (0-1)
         * Early signs of movement - not too cold, not too hot
         */
        calcHeatingScore(row) {
            let score = 0;
            let factors = 0;

            // Speed - sweet spot is 15-35% (starting to move but not already fast)
            if (row.speed_pct !== null && row.speed_pct !== undefined) {
                const speed = row.speed_pct;
                let speedScore;
                if (speed < 10) {
                    speedScore = speed / 10 * 0.3; // Too cold
                } else if (speed <= 35) {
                    // Peak score at 20-25%
                    const optimal = 22;
                    const dist = Math.abs(speed - optimal);
                    speedScore = 0.6 + (1 - dist / 15) * 0.4;
                } else if (speed <= 50) {
                    speedScore = 0.6 - ((speed - 35) / 15) * 0.4; // Getting hot
                } else {
                    speedScore = Math.max(0, 0.2 - ((speed - 50) / 50) * 0.2); // Too hot (late entry)
                }
                score += Math.max(0, Math.min(1, speedScore));
                factors++;
            }

            // Direction code - slight bias is good (not flat, not unclear)
            if (row.dir_code) {
                const dirScores = {
                    'flat_range': 0.5,      // Stable but no momentum yet
                    'neutral_up': 0.9,      // Starting to move up - great!
                    'neutral_down': 0.9,    // Starting to move down - great!
                    'unclear': 0.3,         // Choppy
                    'unknown': 0.2
                };
                score += dirScores[row.dir_code] || 0.3;
                factors++;
            }

            // RSI15 - moving away from center (40-45 or 55-60 is heating up)
            if (row.rsi15 !== null && row.rsi15 !== undefined) {
                const rsi = row.rsi15;
                let rsiScore;
                if (rsi >= 45 && rsi <= 55) {
                    rsiScore = 0.4; // Dead center - not heating yet
                } else if ((rsi >= 40 && rsi < 45) || (rsi > 55 && rsi <= 60)) {
                    rsiScore = 0.9; // Sweet spot - starting to move!
                } else if ((rsi >= 35 && rsi < 40) || (rsi > 60 && rsi <= 65)) {
                    rsiScore = 0.6; // Moving but might be getting late
                } else {
                    rsiScore = 0.2; // Extreme - too late
                }
                score += rsiScore;
                factors++;
            }

            // BBW expansion hint - moderate BBW suggests bands are opening
            if (row.bbw15 !== null && row.bbw15 !== undefined) {
                const bbw = row.bbw15;
                let bbwScore;
                if (bbw >= 8 && bbw <= 18) {
                    bbwScore = 0.8; // Bands expanding nicely
                } else if (bbw >= 5 && bbw < 8) {
                    bbwScore = 0.5; // Still tight
                } else if (bbw > 18 && bbw <= 25) {
                    bbwScore = 0.4; // Already wide
                } else {
                    bbwScore = 0.2; // Extreme
                }
                score += bbwScore;
                factors++;
            }

            return factors > 0 ? score / factors : 0;
        }

        /**
         * Calculate composite score for a coin
         * Returns object with individual scores and combined score
         */
        calculateCoinScore(row) {
            const safety = this.calcSafetyScore(row);
            const profit = this.calcProfitScore(row);
            const heating = this.calcHeatingScore(row);

            // Equal weights: 33% each
            const combined = (safety + profit + heating) / 3;

            return {
                symbol: row.symbol,
                safety: Math.round(safety * 100),
                profit: Math.round(profit * 100),
                heating: Math.round(heating * 100),
                combined: Math.round(combined * 100),
                row: row
            };
        }

        /**
         * Find hot coins from the given rows
         * Returns top 3 coins that pass all thresholds
         */
        calculateHotCoins(rows) {
            if (!Array.isArray(rows) || rows.length === 0) return [];

            const scores = rows.map(row => this.calculateCoinScore(row));

            // Filter coins that pass minimum thresholds for all three criteria
            const qualified = scores.filter(s => 
                s.safety >= 45 &&   // At least 45% safety score
                s.profit >= 35 &&   // At least 35% profit potential
                s.heating >= 50     // At least 50% heating score (the key differentiator)
            );

            // Sort by heating score (primary), then combined score (secondary)
            qualified.sort((a, b) => {
                if (b.heating !== a.heating) return b.heating - a.heating;
                return b.combined - a.combined;
            });

            // Return ALL qualifying coins (no limit)
            return qualified;
        }

        /**
         * Get current hot coins based on active preset's filtered rows
         */
        getHotCoinsForActivePreset() {
            if (!this.activePreset) return [];

            const preset = this.presets.find(p => p.name === this.activePreset);
            if (!preset) return [];

            const rows = Array.isArray(window.lastRows) ? window.lastRows : [];
            if (!rows.length) return [];

            // Apply preset's filters to get matching rows
            const evaluator = window.filterManager?.evaluateRule?.bind(window.filterManager);
            if (!evaluator) return this.calculateHotCoins(rows);

            const rules = Array.isArray(preset.filterRules) ? preset.filterRules : [];
            const combineMode = (preset.combineMode === 'OR') ? 'OR' : 'AND';

            let filteredRows = rows;
            if (rules.length > 0) {
                filteredRows = rows.filter(row => {
                    const results = rules.map(rule => evaluator(row, rule));
                    return (combineMode === 'AND')
                        ? results.every(Boolean)
                        : results.some(Boolean);
                });
            }

            return this.calculateHotCoins(filteredRows);
        }

        /**
         * Mark hot coins in the table with highlighting
         */
        markHotCoinsInTable() {
            const hotCoins = this.getHotCoinsForActivePreset();
            
            // Store for external access
            this.currentHotCoins = hotCoins;
            
            // Store hot coin symbols globally for renderTable() to sort them to top
            window.hotCoinSymbols = hotCoins.map(c => c.symbol);
            window.hotCoinScores = hotCoins;

            // Clear existing hot coin classes
            document.querySelectorAll('.hot-coin-row').forEach(row => {
                row.classList.remove('hot-coin-row', 'hot-rank-1', 'hot-rank-2', 'hot-rank-3', 'hot-rank-other');
            });

            // Clear existing tooltips
            document.querySelectorAll('.hot-coin-tooltip').forEach(el => {
                el.classList.remove('hot-coin-tooltip');
                el.removeAttribute('data-tooltip');
            });

            // Clear fire indicators
            document.querySelectorAll('.hot-coin-indicator').forEach(el => {
                el.classList.remove('hot-coin-indicator');
            });

            if (!hotCoins.length) {
                window.hotCoinSymbols = [];
                window.hotCoinScores = [];
                return;
            }

            // Apply classes to matching rows
            hotCoins.forEach((coin, index) => {
                const row = document.querySelector(`tr[data-symbol="${coin.symbol}"]`);
                if (!row) return;

                // Determine rank class: Gold (1), Silver (2), Bronze (3), Amber (4+)
                let rankClass;
                if (index === 0) {
                    rankClass = 'hot-rank-1';       // Gold
                } else if (index === 1) {
                    rankClass = 'hot-rank-2';       // Silver
                } else if (index === 2) {
                    rankClass = 'hot-rank-3';       // Bronze
                } else {
                    rankClass = 'hot-rank-other';   // Amber for all others
                }

                // Add hot coin row class with appropriate rank
                row.classList.add('hot-coin-row', rankClass);

                // Add fire indicator to first cell (row number)
                const firstCell = row.querySelector('td:first-child');
                if (firstCell) {
                    firstCell.classList.add('hot-coin-indicator');
                }

                // Add tooltip to symbol cell
                const symbolCell = row.querySelector('td:nth-child(3)');
                if (symbolCell) {
                    symbolCell.classList.add('hot-coin-tooltip');
                    const tooltip = `Safe: ${coin.safety}% | Profit: ${coin.profit}% | Heat: ${coin.heating}%`;
                    symbolCell.setAttribute('data-tooltip', tooltip);
                }
            });
        }

        render() {
            const container = document.getElementById(this.buttonsContainerId);
            if (!container) return;

            if (!this.presets.length) {
                container.innerHTML = '<div class="preset-empty" data-i18n="presets.none">No saved presets yet.</div>';
                if (window.i18n?.applyTranslations) window.i18n.applyTranslations();
                return;
            }

            container.innerHTML = this.presets.map(p => {
                const active = (p.name === this.activePreset) ? ' active' : '';
                const count = this.computePresetCount(p);
                
                // Determine color class based on count value
                let countClass = '';
                if (count !== null) {
                    if (count === 0) {
                        countClass = 'count-zero';
                    } else if (count <= 3) {
                        countClass = 'count-low';
                    } else if (count <= 10) {
                        countClass = 'count-medium';
                    } else {
                        countClass = 'count-high';
                    }
                }
                
                const countBadge = (count === null)
                    ? ''
                    : `<span class="preset-count ${countClass}" title="Coins available">${count}</span>`;
                return `
                    <div class="preset-chip${active}">
                        <button class="preset-btn" data-name="${escapeHtml(p.name)}">
                            <span class="preset-label">${escapeHtml(p.name)}</span>
                            ${countBadge}
                        </button>
                        <button class="preset-del" data-name="${escapeHtml(p.name)}" title="${escapeHtml(p.name)}">×</button>
                    </div>
                `;
            }).join('');

            // Bind events
            container.querySelectorAll('.preset-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const name = e.currentTarget.dataset.name;
                    this.applyPresetByName(name);
                });
            });
            container.querySelectorAll('.preset-del').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const name = e.currentTarget.dataset.name;
                    this.deletePreset(name);
                });
            });

            if (window.i18n?.applyTranslations) window.i18n.applyTranslations();
        }
    }

    function escapeHtml(str) {
        return (str || '').toString()
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    window.presetManager = new PresetManager();
})();
