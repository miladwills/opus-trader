<!doctype html>
<html lang="en" dir="ltr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title data-i18n="app.title">Neutral Futures Scanner Pro - Bybit</title>
    <link rel="stylesheet" href="./assets/css/style.css?v=20260314">
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="header-top">
                <h1 data-i18n="app.title">Neutral Futures Scanner Pro - Bybit</h1>
                <div class="header-controls">
                    <label class="sound-toggle">
                        <input type="checkbox" id="enableSound" checked>
                        <span data-i18n="common.soundAlert">Sound Alert</span>
                    </label>
                    <div class="lang-toggle">
                        <button class="lang-btn" data-lang="en">EN</button>
                        <button class="lang-btn" data-lang="ar">AR</button>
                    </div>
                </div>
            </div>
            <p class="subtitle" data-i18n="app.subtitle">
                Green row = Neutral (ranging on 15m, no trend on 1h). Red row = Trending (ADX 1h >= 25).
            </p>
            <div class="last-update">
                <span data-i18n="common.lastUpdate">Last Update</span>: <span id="lastUpdate">--</span>
            </div>
        </header>

        <!-- BTC Risk Bar -->
        <section class="btc-risk-bar" id="btcRiskBar">
            <div class="btc-risk-header">
                <span class="btc-icon">BTC</span>
                <span class="btc-price" id="btcPrice">--</span>
                <span class="btc-risk-badge" id="btcRiskBadge" data-risk="CALM">CALM</span>
            </div>
            <div class="btc-risk-stats">
                <div class="btc-stat">
                    <span class="btc-stat-label">1h</span>
                    <span class="btc-stat-value" id="btcChange1h">--</span>
                </div>
                <div class="btc-stat">
                    <span class="btc-stat-label">4h</span>
                    <span class="btc-stat-value" id="btcChange4h">--</span>
                </div>
                <div class="btc-stat">
                    <span class="btc-stat-label">ADX</span>
                    <span class="btc-stat-value" id="btcAdx">--</span>
                </div>
                <div class="btc-stat">
                    <span class="btc-stat-label" data-i18n="table.headers.speed">Speed</span>
                    <span class="btc-stat-value" id="btcSpeed">--</span>
                </div>
            </div>
            <div class="btc-corr-lists">
                <div class="btc-corr-group">
                    <span class="btc-corr-title" data-i18n="btc_risk.top_corr">Top Correlated</span>
                    <div class="btc-corr-items" id="btcTopCorr">--</div>
                </div>
                <div class="btc-corr-group">
                    <span class="btc-corr-title" data-i18n="btc_risk.weak_corr">Weakest Correlated</span>
                    <div class="btc-corr-items" id="btcWeakCorr">--</div>
                </div>
            </div>
        </section>

        <!-- Symbol Management -->
        <section class="symbol-management">
            <form id="add-symbol-form" class="symbol-form">
                <label for="newSymbol" data-i18n="common.addSymbol">Add Symbol</label>
                <input id="newSymbol" name="symbol" type="text" placeholder="e.g. ZKUSDT or DOGE" autocomplete="off" required maxlength="20">
                <button type="submit" data-i18n="common.add">Add</button>
            </form>
            <div class="symbol-search-row">
                <label for="symbolSearch">Find Symbol</label>
                <input id="symbolSearch" type="text" placeholder="Type a symbol like UAIUSDT" autocomplete="off" maxlength="20">
                <button type="button" class="btn btn-secondary" id="clearSymbolSearch">Clear</button>
            </div>
            <div class="table-status" id="tableStatus" aria-live="polite"></div>
            <div class="page-notice" id="pageNotice" aria-live="polite"></div>
            <div class="skipped-symbols" id="skippedSymbols"></div>
        </section>

<!-- Multi-Sort Panel -->
        <section class="panel multi-sort-panel">
            <div class="panel-header">
                <h3 data-i18n="sort.title">Multi-Level Sort</h3>
                <div class="panel-actions">
                    <button class="btn btn-secondary" id="addSortLevel" data-i18n="sort.addLevel">Add Level</button>
                    <button class="btn btn-primary" id="applySort" data-i18n="sort.apply">Apply Sort</button>
                    <button class="btn btn-danger" id="resetSort" data-i18n="sort.reset">Reset</button>
                </div>
            </div>
            <div class="sort-levels" id="sortLevels">
                <!-- Sort levels will be added dynamically -->
            </div>
        </section>

        <!-- Filter Panel -->
        <section class="panel filter-panel">
            <div class="panel-header">
                <h3 data-i18n="filter.title">Filter Builder</h3>
                <div class="panel-actions">
                    <select id="filterCombineMode" class="filter-combine-select">
                        <option value="AND" data-i18n="filter.and">AND</option>
                        <option value="OR" data-i18n="filter.or">OR</option>
                    </select>
                    <button class="btn btn-secondary" id="addFilterRule" data-i18n="filter.addRule">Add Rule</button>
                    <button class="btn btn-primary" id="applyFilters" data-i18n="filter.apply">Apply Filters</button>
                    <button class="btn btn-danger" id="resetFilters" data-i18n="filter.reset">Reset</button>
                </div>
            </div>
            <div class="filter-rules" id="filterRules">
                <!-- Filter rules will be added dynamically -->
            </div>
        </section>

<!-- Presets Panel (Sort + Filter) -->
        <section class="panel presets-panel">
            <div class="panel-header">
                <h3 data-i18n="presets.title">Presets</h3>
                <div class="panel-actions presets-actions">
                    <input
                        id="presetName"
                        type="text"
                        maxlength="32"
                        data-i18n-placeholder="presets.namePlaceholder"
                        placeholder="Preset name (e.g., Neutral, Long Trend)"
                    >
                    <button class="btn btn-primary" id="savePreset" data-i18n="presets.save">Save Preset</button>
                </div>
            </div>
            <div class="preset-buttons" id="presetButtons"></div>
            <div class="preset-hint" data-i18n="presets.hint">
                Save current Multi-Level Sort + Filter settings as a named preset, then click a preset to apply it.
            </div>
        </section>



        <!-- Main Table -->
        <section class="table-container">
            <table id="mainTable">
                <thead>
                    <tr>
                        <th>#</th>
                        <th data-i18n="table.headers.alert">Alert</th>
                        <th data-i18n="table.headers.symbol">Symbol</th>
                        <th data-i18n="table.headers.state">State</th>
                        <th data-i18n="table.headers.recommendation">Rec.</th>
                        <th data-i18n="table.headers.price">Price</th>
                        <th data-i18n="table.headers.adx15">ADX 15m</th>
                        <th data-i18n="table.headers.adx1h">ADX 1h</th>
                        <th data-i18n="table.headers.rsi15">RSI 15m</th>
                        <th data-i18n="table.headers.rsi1h">RSI 1h</th>
                        <th data-i18n="table.headers.bbw15">BBW% 15m</th>
                        <th data-i18n="table.headers.bbw1h">BBW% 1h</th>
                        <th data-i18n="table.headers.atrPct15">ATR% 15m</th>
                        <th data-i18n="table.headers.atrPct1h">ATR% 1h</th>
                        <th data-i18n="table.headers.vol24h">24h Vol</th>
                        <th data-i18n="table.headers.speed">Speed %</th>
                        <th data-i18n="table.headers.direction">Direction</th>
                        <th data-i18n="table.headers.btcCorr">BTC Corr</th>
                        <th data-i18n="table.headers.btcBeta">BTC Beta</th>
                        <th data-i18n="table.headers.btcImpact">Impact</th>
                        <th data-i18n="table.headers.actions">Actions</th>
                    </tr>
                </thead>
                <tbody id="tableBody">
                    <tr>
                        <td colspan="21" class="loading-message" data-i18n="common.loading">Loading data...</td>
                    </tr>
                </tbody>
            </table>
        </section>

        <!-- Footer -->
        <footer class="footer">
            <p data-i18n="footer.thresholds">
                Neutral conditions: 15m: ADX 12-30, RSI 30-70, BBW% max ~25, ATR% max ~3%.
                1h: ADX >= 25 indicates trend (red row).
            </p>
        </footer>
    </div>

    <!-- Scripts -->
    <?php
        $lastResponseFile = __DIR__ . '/cache/last_response.json';
        $initialData = null;

        if (file_exists($lastResponseFile)) {
            $lastResponse = json_decode((string)file_get_contents($lastResponseFile), true);
            if (is_array($lastResponse)) {
                $initialData = $lastResponse;
            }
        }

        if (is_array($initialData)) {
            echo '<script>window.__INITIAL_DATA__='
                . json_encode($initialData, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
                . ';</script>';
        }
    ?>
    <script src="./assets/js/i18n.js?v=20260314"></script>
    <script src="./assets/js/multi-sort.js?v=20260314"></script>
    <script src="./assets/js/filters.js?v=20260314"></script>
    <script src="./assets/js/presets.js?v=20260314c"></script>
    <script src="./assets/js/app.js?v=20260314"></script>
</body>
</html>
