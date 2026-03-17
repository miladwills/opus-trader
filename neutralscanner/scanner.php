<?php
/**
 * Neutral Scanner Pro - Data Endpoint
 * Handles API calls, caching, indicator calculations, and data processing
 */

// Load configuration
$config = require __DIR__ . '/config.php';

// Set timezone
date_default_timezone_set($config['timezone']);

// ============================================================================
// HELPERS: Symbols Storage
// ============================================================================

function save_symbols($file, $symbols) {
    $symbols = array_values(array_unique(array_map('strtoupper', $symbols)));
    $dir = dirname($file);
    if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
        return false;
    }

    $encoded = json_encode($symbols, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    if ($encoded === false) {
        return false;
    }

    return @file_put_contents($file, $encoded, LOCK_EX) !== false;
}

function load_symbols($file, $defaults) {
    if (file_exists($file)) {
        $json = file_get_contents($file);
        $symbols = json_decode($json, true);
        if (is_array($symbols) && count($symbols)) {
            return array_values(array_unique(array_map('strtoupper', $symbols)));
        }
    }
    save_symbols($file, $defaults);
    return $defaults;
}

function sanitize_symbol($symbol) {
    $symbol = strtoupper(trim($symbol));
    $symbol = preg_replace('/[^A-Z0-9]/', '', $symbol);
    if (strlen($symbol) > 20) {
        $symbol = substr($symbol, 0, 20);
    }
    return $symbol;
}

// ============================================================================
// HELPERS: HTTP with Disk Caching
// ============================================================================

function ensure_cache_dir($cacheDir) {
    if (!is_dir($cacheDir)) {
        mkdir($cacheDir, 0755, true);
    }
}

function http_get_json_cached($url, $cacheDir, $ttlSeconds, $apiConfig) {
    ensure_cache_dir($cacheDir);

    $urlHash = sha1($url);
    $cacheFile = $cacheDir . '/' . $urlHash . '.json';
    $metaFile = $cacheDir . '/' . $urlHash . '.meta';

    // Check if cache is fresh
    if (file_exists($metaFile) && file_exists($cacheFile)) {
        $meta = json_decode(file_get_contents($metaFile), true);
        if (isset($meta['timestamp']) && (time() - $meta['timestamp']) < $ttlSeconds) {
            $cached = json_decode(file_get_contents($cacheFile), true);
            if ($cached !== null) {
                return ['data' => $cached, 'cached' => true, 'stale' => false];
            }
        }
    }

    // Fetch fresh data
    $result = null;

    if (function_exists('curl_init')) {
        // cURL method
        $sslVerify = $apiConfig['ssl_verify'] ?? true;
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => $apiConfig['curl_connect_timeout'],
            CURLOPT_TIMEOUT => $apiConfig['curl_total_timeout'],
            CURLOPT_SSL_VERIFYPEER => $sslVerify,
            CURLOPT_SSL_VERIFYHOST => $sslVerify ? 2 : 0,
            CURLOPT_USERAGENT => $apiConfig['user_agent'],
        ]);
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($response !== false && $httpCode === 200) {
            $result = json_decode($response, true);
        }
    } else {
        // file_get_contents fallback
        $sslVerify = $apiConfig['ssl_verify'] ?? true;
        $context = stream_context_create([
            'http' => [
                'timeout' => $apiConfig['curl_total_timeout'],
                'user_agent' => $apiConfig['user_agent'],
            ],
            'ssl' => [
                'verify_peer' => $sslVerify,
                'verify_peer_name' => $sslVerify,
            ],
        ]);
        $response = @file_get_contents($url, false, $context);
        if ($response !== false) {
            $result = json_decode($response, true);
        }
    }

    // If fetch succeeded, update cache
    if ($result !== null) {
        file_put_contents($cacheFile, json_encode($result));
        file_put_contents($metaFile, json_encode(['timestamp' => time(), 'url' => $url]));
        return ['data' => $result, 'cached' => false, 'stale' => false];
    }

    // If fetch failed but stale cache exists, return it with warning
    if (file_exists($cacheFile)) {
        $cached = json_decode(file_get_contents($cacheFile), true);
        if ($cached !== null) {
            return ['data' => $cached, 'cached' => true, 'stale' => true];
        }
    }

    return null;
}

function symbol_without_quote($symbol, $quote = 'USDT') {
    $symbol = strtoupper((string)$symbol);
    $quote = strtoupper((string)$quote);
    if ($quote !== '' && substr($symbol, -strlen($quote)) === $quote) {
        return substr($symbol, 0, -strlen($quote));
    }
    return $symbol;
}

function normalize_symbol_alias($symbol) {
    $base = symbol_without_quote(sanitize_symbol($symbol));
    return preg_replace('/^\d+/', '', $base);
}

function fetch_linear_instruments_catalog($config) {
    $cacheDir = $config['cache_dir'];
    $ttl = (int)($config['instrument_catalog_cache_ttl_seconds'] ?? 900);
    $apiConfig = $config['api'];
    $instruments = [];
    $cursor = null;
    $seenCursors = [];

    for ($page = 0; $page < 8; $page++) {
        $url = sprintf(
            '%s/instruments-info?category=linear&limit=1000%s',
            $apiConfig['base_url'],
            $cursor ? '&cursor=' . urlencode($cursor) : ''
        );

        $result = http_get_json_cached($url, $cacheDir, $ttl, $apiConfig);
        if (!$result || !isset($result['data'])) {
            break;
        }

        $data = $result['data'];
        if (($data['retCode'] ?? -1) !== 0) {
            break;
        }

        $list = $data['result']['list'] ?? [];
        if (!is_array($list) || !$list) {
            break;
        }

        foreach ($list as $item) {
            $symbol = strtoupper((string)($item['symbol'] ?? ''));
            $quoteCoin = strtoupper((string)($item['quoteCoin'] ?? ''));
            $status = strtoupper((string)($item['status'] ?? ''));
            if ($symbol === '' || $quoteCoin !== 'USDT') {
                continue;
            }
            if ($status !== '' && $status !== 'TRADING') {
                continue;
            }

            $baseCoin = strtoupper((string)($item['baseCoin'] ?? symbol_without_quote($symbol)));
            $instruments[$symbol] = [
                'symbol' => $symbol,
                'base_coin' => $baseCoin,
                'quote_coin' => $quoteCoin,
                'status' => $status,
            ];
        }

        $nextCursor = trim((string)($data['result']['nextPageCursor'] ?? ''));
        if ($nextCursor === '' || isset($seenCursors[$nextCursor])) {
            break;
        }

        $seenCursors[$nextCursor] = true;
        $cursor = $nextCursor;
    }

    return $instruments;
}

function build_symbol_catalog_index($config) {
    $instruments = fetch_linear_instruments_catalog($config);
    if (!$instruments) {
        return null;
    }

    $aliasMap = [];
    foreach ($instruments as $symbol => $instrument) {
        $aliases = array_filter([
            $symbol,
            sanitize_symbol($instrument['base_coin'] . 'USDT'),
            sanitize_symbol(normalize_symbol_alias($instrument['base_coin']) . 'USDT'),
            sanitize_symbol(normalize_symbol_alias($symbol) . 'USDT'),
        ]);

        foreach ($aliases as $alias) {
            $aliasMap[$alias] = $aliasMap[$alias] ?? [];
            $aliasMap[$alias][] = $symbol;
        }
    }

    foreach (($config['symbol_aliases'] ?? []) as $legacy => $replacementBase) {
        $legacyAlias = sanitize_symbol($legacy . 'USDT');
        $replacementBase = strtoupper((string)$replacementBase);
        foreach ($instruments as $symbol => $instrument) {
            $baseCoin = strtoupper((string)($instrument['base_coin'] ?? ''));
            $normalizedBase = normalize_symbol_alias($baseCoin);
            if ($baseCoin === $replacementBase || $normalizedBase === $replacementBase) {
                $aliasMap[$legacyAlias] = $aliasMap[$legacyAlias] ?? [];
                $aliasMap[$legacyAlias][] = $symbol;
            }
        }
    }

    foreach ($aliasMap as $alias => $matches) {
        $aliasMap[$alias] = array_values(array_unique(array_map('strtoupper', $matches)));
    }

    return [
        'by_symbol' => $instruments,
        'by_alias' => $aliasMap,
    ];
}

function score_symbol_match($candidate, $resolvedSymbol, $catalogIndex) {
    $candidate = sanitize_symbol($candidate);
    $candidateBase = symbol_without_quote($candidate);
    $normalizedCandidate = normalize_symbol_alias($candidateBase);
    $info = $catalogIndex['by_symbol'][$resolvedSymbol] ?? [];
    $baseCoin = strtoupper((string)($info['base_coin'] ?? symbol_without_quote($resolvedSymbol)));
    $normalizedBase = normalize_symbol_alias($baseCoin);

    $score = 0;
    if ($resolvedSymbol === $candidate) {
        $score += 1000;
    }
    if ($baseCoin === $candidateBase) {
        $score += 250;
    }
    if ($normalizedBase === $normalizedCandidate) {
        $score += 150;
    }
    if (substr($resolvedSymbol, -strlen($candidate)) === $candidate) {
        $score += 25;
    }
    if (!preg_match('/^\d+/', symbol_without_quote($resolvedSymbol))) {
        $score += 5;
    }
    return $score;
}

function resolve_symbol_candidate($symbol, $catalogIndex) {
    $candidate = sanitize_symbol($symbol);
    if ($candidate === '') {
        return null;
    }
    if (substr($candidate, -4) !== 'USDT') {
        $candidate .= 'USDT';
    }

    if (!$catalogIndex) {
        return $candidate;
    }

    if (isset($catalogIndex['by_symbol'][$candidate])) {
        return $candidate;
    }

    $matches = $catalogIndex['by_alias'][$candidate] ?? [];
    if (!$matches) {
        return null;
    }

    usort($matches, function ($left, $right) use ($candidate, $catalogIndex) {
        return score_symbol_match($candidate, $right, $catalogIndex) <=> score_symbol_match($candidate, $left, $catalogIndex);
    });

    return $matches[0] ?? null;
}

function reconcile_saved_symbols($symbols, $catalogIndex, $config) {
    if (!$catalogIndex) {
        return ['symbols' => $symbols, 'replacements' => []];
    }

    $resolvedSymbols = [];
    $replacements = [];

    foreach ($symbols as $symbol) {
        $resolved = resolve_symbol_candidate($symbol, $catalogIndex);
        if ($resolved && $resolved !== $symbol) {
            $replacements[$symbol] = $resolved;
        }
        $resolvedSymbols[] = $resolved ?: $symbol;
    }

    $resolvedSymbols = array_values(array_unique(array_map('strtoupper', $resolvedSymbols)));

    if ($replacements) {
        save_symbols($config['symbols_file'], $resolvedSymbols);
    }

    return [
        'symbols' => $resolvedSymbols,
        'replacements' => $replacements,
    ];
}

function persist_last_response($payload, $config) {
    try {
        $lastResponseFile = $config['cache_dir'] . '/last_response.json';
        @file_put_contents($lastResponseFile, json_encode($payload), LOCK_EX);
    } catch (Throwable $e) {
    }
}

function load_last_response($config) {
    $lastResponseFile = $config['cache_dir'] . '/last_response.json';
    if (!file_exists($lastResponseFile)) {
        return null;
    }

    $payload = json_decode((string)@file_get_contents($lastResponseFile), true);
    return is_array($payload) ? $payload : null;
}

function is_symbol_list_newer_than_cached_payload($config) {
    $symbolsFile = $config['symbols_file'] ?? null;
    if (!$symbolsFile || !file_exists($symbolsFile)) {
        return false;
    }

    $lastResponseFile = ($config['cache_dir'] ?? __DIR__ . '/cache') . '/last_response.json';
    if (!file_exists($lastResponseFile)) {
        return true;
    }

    $symbolsMtime = @filemtime($symbolsFile);
    $payloadMtime = @filemtime($lastResponseFile);
    if ($symbolsMtime === false || $payloadMtime === false) {
        return false;
    }

    return $symbolsMtime > $payloadMtime;
}

function get_seed_max_age_ms($config, $payload = null) {
    $configured = (int)($config['seed_max_age_seconds'] ?? 20) * 1000;
    $payloadAge = is_array($payload) ? (int)($payload['seed_max_age_ms'] ?? 0) : 0;
    return max($configured, $payloadAge);
}

function is_snapshot_fresh($payload, $config) {
    if (!is_array($payload)) {
        return false;
    }

    $generatedAtMs = (int)($payload['generated_at_epoch_ms'] ?? 0);
    if ($generatedAtMs <= 0) {
        return false;
    }

    $maxAgeMs = get_seed_max_age_ms($config, $payload);
    if ($maxAgeMs <= 0) {
        return false;
    }

    return ((int)round(microtime(true) * 1000) - $generatedAtMs) <= $maxAgeMs;
}

function decorate_payload_for_delivery($payload, $config, $servedFromSnapshot = true, $refreshInProgress = false) {
    if (!is_array($payload)) {
        return null;
    }

    $decorated = $payload;
    $decorated['ok'] = true;
    $decorated['seed_max_age_ms'] = get_seed_max_age_ms($config, $payload);
    $decorated['served_from_snapshot'] = $servedFromSnapshot;
    $decorated['snapshot_stale'] = !$servedFromSnapshot ? false : !is_snapshot_fresh($payload, $config);
    $decorated['refresh_in_progress'] = $refreshInProgress;
    $decorated['served_at_epoch_ms'] = (int)round(microtime(true) * 1000);
    $decorated['served_at_iso'] = gmdate('c');
    return $decorated;
}

function now_epoch_ms() {
    return (int)round(microtime(true) * 1000);
}

function get_payload_refresh_lock_timeout_ms($config) {
    return max(30000, (int)($config['payload_refresh_lock_timeout_seconds'] ?? 180) * 1000);
}

function decode_refresh_lock_state($raw) {
    $state = json_decode((string)$raw, true);
    return is_array($state) ? $state : null;
}

function is_pid_alive($pid) {
    $pid = (int)$pid;
    if ($pid <= 0) {
        return null;
    }

    if (is_dir('/proc/' . $pid)) {
        return true;
    }

    if (!function_exists('posix_kill')) {
        return false;
    }

    if (@posix_kill($pid, 0)) {
        return true;
    }

    if (function_exists('posix_get_last_error')) {
        $errno = @posix_get_last_error();
        if ($errno === 1) {
            return true;
        }
    }

    return false;
}

function can_refresh_lock_state_expire($state, $config) {
    if (!is_array($state) || empty($state['owner_token'])) {
        return true;
    }

    $nowMs = now_epoch_ms();
    $startedAtMs = (int)($state['started_at_epoch_ms'] ?? 0);
    $expiresAtMs = (int)($state['expires_at_epoch_ms'] ?? 0);
    $lockTimeoutMs = get_payload_refresh_lock_timeout_ms($config);
    $pidAlive = is_pid_alive($state['pid'] ?? 0);

    if ($pidAlive === false) {
        return true;
    }

    if ($expiresAtMs > 0 && $nowMs > $expiresAtMs) {
        return true;
    }

    if ($startedAtMs > 0 && $nowMs > ($startedAtMs + $lockTimeoutMs)) {
        return true;
    }

    return false;
}

function open_payload_refresh_lock($config) {
    ensure_cache_dir($config['cache_dir']);
    $lockPath = $config['cache_dir'] . '/payload_refresh.lock';
    $handle = @fopen($lockPath, 'c+');
    if ($handle === false) {
        return null;
    }

    if (!@flock($handle, LOCK_EX)) {
        @fclose($handle);
        return null;
    }

    $state = null;
    $contents = @stream_get_contents($handle);
    if ($contents !== false && $contents !== '') {
        $state = decode_refresh_lock_state($contents);
    }

    if ($state && !can_refresh_lock_state_expire($state, $config)) {
        @flock($handle, LOCK_UN);
        @fclose($handle);
        return null;
    }

    $nowMs = now_epoch_ms();
    $lockState = [
        'owner_token' => bin2hex(random_bytes(16)),
        'pid' => (int)getmypid(),
        'started_at_epoch_ms' => $nowMs,
        'expires_at_epoch_ms' => $nowMs + get_payload_refresh_lock_timeout_ms($config),
    ];

    @rewind($handle);
    @ftruncate($handle, 0);
    @fwrite($handle, json_encode($lockState));
    @fflush($handle);
    @flock($handle, LOCK_UN);
    @fclose($handle);

    return [
        'path' => $lockPath,
        'owner_token' => $lockState['owner_token'],
    ];
}

function close_payload_refresh_lock($lockHandle) {
    if (!is_array($lockHandle) || empty($lockHandle['path']) || empty($lockHandle['owner_token'])) {
        return;
    }

    $handle = @fopen($lockHandle['path'], 'c+');
    if ($handle === false) {
        return;
    }

    if (!@flock($handle, LOCK_EX)) {
        @fclose($handle);
        return;
    }

    $state = decode_refresh_lock_state((string)@stream_get_contents($handle));
    if (($state['owner_token'] ?? null) === $lockHandle['owner_token']) {
        @rewind($handle);
        @ftruncate($handle, 0);
        @fflush($handle);
    }

    @flock($handle, LOCK_UN);
    @fclose($handle);
}

function get_data_payload_response($symbols, $config, $forceRefresh = false) {
    $cachedPayload = load_last_response($config);
    $symbolsChanged = is_symbol_list_newer_than_cached_payload($config);

    if ($cachedPayload && !$forceRefresh && !$symbolsChanged) {
        return decorate_payload_for_delivery($cachedPayload, $config, true, false);
    }

    $lockHandle = open_payload_refresh_lock($config);
    if ($lockHandle === null) {
        if ($cachedPayload) {
            return decorate_payload_for_delivery($cachedPayload, $config, true, true);
        }

        return [
            'ok' => false,
            'message' => 'Scanner refresh already in progress.',
        ];
    }

    try {
        if (!$forceRefresh && !is_symbol_list_newer_than_cached_payload($config)) {
            $latestPayload = load_last_response($config);
            if ($latestPayload) {
                return decorate_payload_for_delivery($latestPayload, $config, true, false);
            }
        }

        $payload = build_data_payload($symbols, $config);
        return decorate_payload_for_delivery($payload, $config, false, false);
    } catch (Throwable $e) {
        if ($cachedPayload) {
            $fallback = decorate_payload_for_delivery($cachedPayload, $config, true, true);
            $fallback['message'] = 'Refresh failed, showing the latest cached snapshot.';
            return $fallback;
        }

        return [
            'ok' => false,
            'message' => 'Failed to build scanner payload.',
        ];
    } finally {
        close_payload_refresh_lock($lockHandle);
    }
}

// ============================================================================
// HELPERS: Technical Analysis (Preserved from original)
// ============================================================================

function calc_rsi(array $closes, int $period = 14) {
    $len = count($closes);
    if ($len <= $period) return null;

    $gains = [];
    $losses = [];
    for ($i = 1; $i < $len; $i++) {
        $diff = $closes[$i] - $closes[$i-1];
        $gains[]  = $diff > 0 ? $diff : 0;
        $losses[] = $diff < 0 ? -$diff : 0;
    }

    $avgGain = array_sum(array_slice($gains, 0, $period)) / $period;
    $avgLoss = array_sum(array_slice($losses, 0, $period)) / $period;

    if ($avgLoss == 0) return 100.0;

    for ($i = $period; $i < count($gains); $i++) {
        $avgGain = (($avgGain * ($period - 1)) + $gains[$i]) / $period;
        $avgLoss = (($avgLoss * ($period - 1)) + $losses[$i]) / $period;
    }

    if ($avgLoss == 0) return 100.0;
    $rs = $avgGain / $avgLoss;
    return 100 - (100 / (1 + $rs));
}

function calc_atr(array $highs, array $lows, array $closes, int $period = 14) {
    $len = count($closes);
    if ($len <= $period) return null;

    $trs = [];
    for ($i = 1; $i < $len; $i++) {
        $high = $highs[$i];
        $low  = $lows[$i];
        $prevClose = $closes[$i-1];
        $tr = max(
            $high - $low,
            abs($high - $prevClose),
            abs($low  - $prevClose)
        );
        $trs[] = $tr;
    }

    $atr = array_sum(array_slice($trs, 0, $period)) / $period;
    for ($i = $period; $i < count($trs); $i++) {
        $atr = (($atr * ($period - 1)) + $trs[$i]) / $period;
    }
    return $atr;
}

function calc_bb_bands(array $closes, int $period = 20, float $mult = 2.0) {
    $len = count($closes);
    if ($len < $period) {
        return [null, null, null, null, null];
    }

    $slice = array_slice($closes, $len - $period, $period);
    $mean  = array_sum($slice) / $period;

    $sumSq = 0;
    foreach ($slice as $c) {
        $sumSq += ($c - $mean) ** 2;
    }
    $variance = $sumSq / $period;
    $std      = sqrt($variance);

    $upper = $mean + $mult * $std;
    $lower = $mean - $mult * $std;

    if ($mean == 0 || $upper == $lower) {
        return [null, null, null, null, null];
    }

    $bbw = (($upper - $lower) / $mean) * 100;
    $lastClose = end($closes);
    $pos = ($lastClose - $lower) / ($upper - $lower);

    return [$upper, $lower, $mean, $bbw, $pos];
}

function calculate_adx(array $klines, int $period = 14): ?float {
    $n = count($klines);
    if ($n <= $period + 2) {
        return null;
    }

    $trs      = [];
    $plusDM   = [];
    $minusDM  = [];

    for ($i = 1; $i < $n; $i++) {
        $high      = (float)$klines[$i]['high'];
        $low       = (float)$klines[$i]['low'];
        $prevHigh  = (float)$klines[$i-1]['high'];
        $prevLow   = (float)$klines[$i-1]['low'];
        $prevClose = (float)$klines[$i-1]['close'];

        $upMove   = $high - $prevHigh;
        $downMove = $prevLow - $low;

        $plusDM[]  = ($upMove > $downMove && $upMove > 0) ? $upMove   : 0.0;
        $minusDM[] = ($downMove > $upMove && $downMove > 0) ? $downMove : 0.0;

        $tr = max(
            $high - $low,
            abs($high - $prevClose),
            abs($low  - $prevClose)
        );
        $trs[] = $tr;
    }

    $m = count($trs);
    if ($m <= $period) {
        return null;
    }

    $trSmooth    = array_sum(array_slice($trs, 0, $period));
    $plusSmooth  = array_sum(array_slice($plusDM, 0, $period));
    $minusSmooth = array_sum(array_slice($minusDM, 0, $period));

    $dx = [];

    for ($i = $period; $i < $m; $i++) {
        $trSmooth    = $trSmooth    - ($trSmooth    / $period) + $trs[$i];
        $plusSmooth  = $plusSmooth  - ($plusSmooth  / $period) + $plusDM[$i];
        $minusSmooth = $minusSmooth - ($minusSmooth / $period) + $minusDM[$i];

        if ($trSmooth == 0) {
            $dx[] = 0.0;
            continue;
        }

        $plusDI  = 100.0 * ($plusSmooth  / $trSmooth);
        $minusDI = 100.0 * ($minusSmooth / $trSmooth);

        $den = $plusDI + $minusDI;
        if ($den == 0) {
            $dx[] = 0.0;
            continue;
        }

        $dx[] = 100.0 * abs($plusDI - $minusDI) / $den;
    }

    if (count($dx) < $period) {
        return null;
    }

    $adx = array_sum(array_slice($dx, 0, $period)) / $period;

    for ($i = $period; $i < count($dx); $i++) {
        $adx = (($adx * ($period - 1)) + $dx[$i]) / $period;
    }

    return round($adx, 2);
}

function calc_adx(array $highs, array $lows, array $closes, int $period = 14) {
    $len = count($closes);
    if ($len <= $period + 2) return null;

    $klines = [];
    for ($i = 0; $i < $len; $i++) {
        $klines[] = [
            'high'  => (float)$highs[$i],
            'low'   => (float)$lows[$i],
            'close' => (float)$closes[$i],
        ];
    }

    return calculate_adx($klines, $period);
}

// ============================================================================
// HELPERS: Neutral Logic (Preserved from original)
// ============================================================================

function is_neutral_15m($adx, $rsi, $bbw, $atrPct, $thresholds) {
    if ($adx === null) return false;

    if ($adx < $thresholds['adx_15m_neutral_min'] || $adx > $thresholds['adx_15m_neutral_max']) return false;
    if ($rsi !== null && ($rsi < $thresholds['rsi_neutral_low'] || $rsi > $thresholds['rsi_neutral_high'])) return false;
    if ($bbw !== null && $bbw > $thresholds['bbw_neutral_max']) return false;
    if ($atrPct !== null && $atrPct > $thresholds['atr_pct_neutral_max']) return false;

    return true;
}

function is_trend_1h($adx, $thresholds) {
    if ($adx === null) return false;
    return $adx >= $thresholds['adx_1h_trend_min'];
}

function neutral_score($adx, $rsi, $bbw) {
    if ($adx === null || $rsi === null || $bbw === null) return 0;
    $s1 = max(0, 1 - abs($adx - 20) / 20);
    $s2 = max(0, 1 - abs($rsi - 50) / 30);
    $s3 = max(0, 1 - abs($bbw - 8) / 15);
    return $s1 + $s2 + $s3;
}

function classify_direction($changePct, $rsi, $pos, $dirConfig) {
    if ($changePct === null || $rsi === null || $pos === null) {
        return ['code' => 'unknown', 'label' => 'Unclear'];
    }

    $absChange = abs($changePct);

    // Flat range
    if ($absChange < $dirConfig['flat_range_change_max'] &&
        $rsi >= $dirConfig['flat_range_rsi_min'] &&
        $rsi <= $dirConfig['flat_range_rsi_max'] &&
        $pos >= $dirConfig['flat_range_pos_min'] &&
        $pos <= $dirConfig['flat_range_pos_max']) {
        return ['code' => 'flat_range', 'label' => 'Ranging'];
    }

    // Neutral up
    if ($changePct > $dirConfig['neutral_up_change_min'] &&
        $changePct < $dirConfig['neutral_up_change_max'] &&
        $rsi >= 50 && $pos >= 0.45) {
        return ['code' => 'neutral_up', 'label' => 'Neutral Up'];
    }

    // Neutral down
    if ($changePct < $dirConfig['neutral_down_change_max'] &&
        $changePct > $dirConfig['neutral_down_change_min'] &&
        $rsi <= 50 && $pos <= 0.55) {
        return ['code' => 'neutral_down', 'label' => 'Neutral Down'];
    }

    return ['code' => 'unclear', 'label' => 'Unclear'];
}

function calc_speed_pct($atrPct15, $bbw15, $adx15, $shortChangePct, $longChangePct) {
    $atrScore = ($atrPct15 !== null) ? min($atrPct15 / 1.2, 4.0) : 0.0;
    $bbwScore = ($bbw15 !== null) ? min($bbw15 / 10.0, 3.0) : 0.0;
    $adxScore = ($adx15 !== null) ? min(max(($adx15 - 10.0) / 8.0, 0.0), 3.0) : 0.0;

    $shapeAbs = 0.0;
    if ($shortChangePct !== null) {
        $shapeAbs = max($shapeAbs, abs($shortChangePct));
    }
    if ($longChangePct !== null) {
        $shapeAbs = max($shapeAbs, abs($longChangePct));
    }
    $shapeScore = min($shapeAbs / 0.8, 3.5);

    $speedScore = $atrScore + $bbwScore + $adxScore + $shapeScore;
    $maxScore = 13.5;
    $pct = $maxScore > 0 ? ($speedScore / $maxScore) * 100.0 : 0.0;
    $pct = max(0.0, min($pct, 100.0));
    return (int)round($pct);
}

// ============================================================================
// STATE DETECTION AND RECOMMENDATIONS
// ============================================================================

function detect_state($indicators, $thresholds) {
    $adx15 = $indicators['adx15'];
    $adx1h = $indicators['adx1h'];
    $rsi15 = $indicators['rsi15'];
    $rsi1h = $indicators['rsi1h'];
    $bbw15 = $indicators['bbw15'];
    $atrPct15 = $indicators['atrPct15'];
    $speedPct = $indicators['speed_pct'];

    // Check for VOLATILE first
    $volatileBbw = $thresholds['bbw_neutral_max'] * $thresholds['volatile_bbw_mult'];
    $volatileAtr = $thresholds['atr_pct_neutral_max'] * $thresholds['volatile_atr_mult'];

    if (($bbw15 !== null && $bbw15 > $volatileBbw) ||
        ($atrPct15 !== null && $atrPct15 > $volatileAtr) ||
        $speedPct > $thresholds['volatile_speed_pct']) {
        return 'VOLATILE';
    }

    // Check NEUTRAL conditions
    $isNeutral15m = is_neutral_15m($adx15, $rsi15, $bbw15, $atrPct15, $thresholds);
    $isTrend1h = is_trend_1h($adx1h, $thresholds);

    if ($isNeutral15m && !$isTrend1h) {
        return 'NEUTRAL';
    }

    // Check TREND_UP
    if ($adx1h !== null && $adx1h >= $thresholds['adx_1h_trend_min'] && $rsi1h !== null && $rsi1h > 55) {
        return 'TREND_UP';
    }

    // Check TREND_DOWN
    if ($adx1h !== null && $adx1h >= $thresholds['adx_1h_trend_min'] && $rsi1h !== null && $rsi1h < 45) {
        return 'TREND_DOWN';
    }

    // Default to TRANSITION
    return 'TRANSITION';
}

function get_recommendation($state, $speedPct, $bbw15, $atrPct15) {
    $isLowVolatility = ($bbw15 !== null && $bbw15 < 15) && ($atrPct15 !== null && $atrPct15 < 2.0);
    $isLowSpeed = ($speedPct < 30);
    $isHighSpeed = ($speedPct > 50);

    switch ($state) {
        case 'NEUTRAL':
            if ($isLowVolatility && $isLowSpeed) {
                return 'Neutral/Fixed';
            }
            return 'Neutral/Trailing';

        case 'TREND_UP':
            if ($isHighSpeed) {
                return 'Long/Trailing';
            }
            return 'Long/Fixed';

        case 'TREND_DOWN':
            if ($isHighSpeed) {
                return 'Short/Trailing';
            }
            return 'Short/Fixed';

        case 'VOLATILE':
            return 'Volatile/Avoid';

        default: // TRANSITION
            return 'Transition/Wait';
    }
}

// ============================================================================
// BTC CORRELATION AND RISK
// ============================================================================

function calc_btc_correlation($symbolCloses, $btcCloses, $window = 96) {
    // Use the most recent window (not the oldest bars)
    $len = min(count($symbolCloses), count($btcCloses), $window + 1);
    if ($len < 20) return ['corr' => null, 'beta' => null];

    $symbolCloses = array_slice($symbolCloses, -$len);
    $btcCloses = array_slice($btcCloses, -$len);

    $symbolReturns = [];
    $btcReturns = [];

    for ($i = 1; $i < $len; $i++) {
        if ($symbolCloses[$i-1] > 0 && $btcCloses[$i-1] > 0) {
            $symbolReturns[] = ($symbolCloses[$i] - $symbolCloses[$i-1]) / $symbolCloses[$i-1];
            $btcReturns[] = ($btcCloses[$i] - $btcCloses[$i-1]) / $btcCloses[$i-1];
        }
    }

    if (count($symbolReturns) < 10) return ['corr' => null, 'beta' => null];

    // Calculate means
    $meanSymbol = array_sum($symbolReturns) / count($symbolReturns);
    $meanBtc = array_sum($btcReturns) / count($btcReturns);

    // Calculate covariance and variances
    $covariance = 0;
    $varSymbol = 0;
    $varBtc = 0;

    for ($i = 0; $i < count($symbolReturns); $i++) {
        $diffSymbol = $symbolReturns[$i] - $meanSymbol;
        $diffBtc = $btcReturns[$i] - $meanBtc;
        $covariance += $diffSymbol * $diffBtc;
        $varSymbol += $diffSymbol ** 2;
        $varBtc += $diffBtc ** 2;
    }

    $n = count($symbolReturns);
    $covariance /= $n;
    $varSymbol /= $n;
    $varBtc /= $n;

    // Pearson correlation
    $corr = null;
    if ($varSymbol > 0 && $varBtc > 0) {
        $corr = $covariance / (sqrt($varSymbol) * sqrt($varBtc));
    }

    // Beta
    $beta = null;
    if ($varBtc > 0) {
        $beta = $covariance / $varBtc;
    }

    return ['corr' => $corr, 'beta' => $beta];
}

function get_btc_impact_label($corr, $impactThresholds) {
    if ($corr === null) return 'Unknown';
    $absCorr = abs($corr);

    if ($absCorr >= $impactThresholds['corr_high']) return 'High';
    if ($absCorr >= $impactThresholds['corr_med']) return 'Medium';
    if ($absCorr >= $impactThresholds['corr_low']) return 'Low';
    return 'Weak';
}

function calc_btc_risk_level($btcData, $btcRiskThresholds) {
    $abs1h = abs($btcData['change_1h_pct'] ?? 0);
    $abs4h = abs($btcData['change_4h_pct'] ?? 0);
    $speed = $btcData['speed_pct'] ?? 0;

    // HIGH if any threshold exceeded
    if ($abs1h >= $btcRiskThresholds['high_abs_change_1h_pct'] ||
        $abs4h >= $btcRiskThresholds['high_abs_change_4h_pct'] ||
        $speed >= $btcRiskThresholds['high_speed_pct'] * 100) {
        return 'HIGH';
    }

    // MED if approaching thresholds
    if ($abs1h >= $btcRiskThresholds['high_abs_change_1h_pct'] * 0.6 ||
        $abs4h >= $btcRiskThresholds['high_abs_change_4h_pct'] * 0.6 ||
        $speed >= $btcRiskThresholds['high_speed_pct'] * 60) {
        return 'MED';
    }

    // LOW if moderate activity
    if ($abs1h >= 0.3 || $abs4h >= 0.6 || $speed >= 25) {
        return 'LOW';
    }

    return 'CALM';
}

// ============================================================================
// FETCH AND PROCESS DATA
// ============================================================================

function fetch_kline_data($symbol, $interval, $limit, $cacheDir, $ttl, $apiConfig, $useClosedOnly = false) {
    $url = sprintf(
        '%s/kline?category=linear&symbol=%s&interval=%s&limit=%d',
        $apiConfig['base_url'],
        urlencode($symbol),
        $interval,
        $limit
    );

    $result = http_get_json_cached($url, $cacheDir, $ttl, $apiConfig);
    if (!$result || !isset($result['data'])) return null;

    $data = $result['data'];
    if (($data['retCode'] ?? -1) !== 0) return null;

    $list = $data['result']['list'] ?? [];
    if (!is_array($list) || count($list) < 22) return null;

    $chronological = array_reverse($list);
    if ($useClosedOnly) {
        $chronological = trim_incomplete_last_candle($chronological, interval_to_minutes($interval));
    }
    return [
        'list' => $chronological,
        'cached' => $result['cached'],
        'stale' => $result['stale']
    ];
}

function interval_to_minutes($interval) {
    $m = (int)$interval;
    return $m > 0 ? $m : 0;
}

/**
 * Exclude the last candle if it is still forming.
 * This makes indicator values closer to what Bybit/TV show (closed candles).
 */
function trim_incomplete_last_candle(array $chronological, int $intervalMinutes) {
    if (count($chronological) < 3 || $intervalMinutes <= 0) {
        return $chronological;
    }

    $last = $chronological[count($chronological) - 1];
    if (!is_array($last) || !isset($last[0])) {
        return $chronological;
    }

    $startMs = (int)$last[0];
    $intervalMs = $intervalMinutes * 60 * 1000;
    $nowMs = (int)round(microtime(true) * 1000);

    // If candle is not complete (with small safety buffer), drop it.
    if ($nowMs < ($startMs + $intervalMs - 5000)) {
        array_pop($chronological);
    }

    return $chronological;
}

function fetch_ticker_data($symbol, $cacheDir, $ttl, $apiConfig) {
    $url = sprintf(
        '%s/tickers?category=linear&symbol=%s',
        $apiConfig['base_url'],
        urlencode($symbol)
    );

    $result = http_get_json_cached($url, $cacheDir, $ttl, $apiConfig);
    if (!$result || !isset($result['data'])) return null;

    $data = $result['data'];
    if (($data['retCode'] ?? -1) !== 0) return null;

    return $data['result']['list'][0] ?? null;
}

function process_symbol($symbol, $btcCloses, $config) {
    $cacheDir = $config['cache_dir'];
    $ttl = $config['api_cache_ttl_seconds'];
    $apiConfig = $config['api'];
    $periods = $config['periods'];
    $thresholds = $config['thresholds'];
    $dirConfig = $config['direction'];
    $btcImpact = $config['btc_impact'];
    $corrWindow = $config['correlation_window_15m_bars'];

    $useClosedOnly = !empty($config['use_closed_candles_only']);

    // Fetch 15m klines
    $kline15 = fetch_kline_data($symbol, '15', $config['kline_limit'], $cacheDir, $ttl, $apiConfig, $useClosedOnly);
    if (!$kline15) return null;

    $list15 = $kline15['list'];
    $highs15 = [];
    $lows15 = [];
    $closes15 = [];

    foreach ($list15 as $row) {
        $highs15[] = (float)$row[2];
        $lows15[] = (float)$row[3];
        $closes15[] = (float)$row[4];
    }

    $lastClose15 = end($closes15);

    // Fetch 1h klines
    $m1h = ['adx' => null, 'rsi' => null, 'bbw' => null, 'atrPct' => null];
    $kline1h = fetch_kline_data($symbol, '60', $config['kline_limit'], $cacheDir, $ttl, $apiConfig, $useClosedOnly);

    if ($kline1h) {
        $list1h = $kline1h['list'];
        $highs1h = [];
        $lows1h = [];
        $closes1h = [];

        foreach ($list1h as $row) {
            $highs1h[] = (float)$row[2];
            $lows1h[] = (float)$row[3];
            $closes1h[] = (float)$row[4];
        }

        $lastClose1h = end($closes1h);
        $rsi1h = calc_rsi($closes1h, $periods['rsi']);
        $atr1h = calc_atr($highs1h, $lows1h, $closes1h, $periods['atr']);
        list(, , , $bbw1h, ) = calc_bb_bands($closes1h, $periods['bb'], $periods['bb_mult']);
        $adx1h = calc_adx($highs1h, $lows1h, $closes1h, $periods['adx']);
        $atrPct1h = ($atr1h !== null && $lastClose1h > 0) ? ($atr1h / $lastClose1h) * 100 : null;

        $m1h = [
            'adx' => $adx1h,
            'rsi' => $rsi1h,
            'bbw' => $bbw1h,
            'atrPct' => $atrPct1h,
        ];
    }

    // Fetch ticker for volume
    $tickerData = fetch_ticker_data($symbol, $cacheDir, $ttl, $apiConfig);
    $volume24 = null;
    $displayPrice = $lastClose15;
    if ($tickerData) {
        // Display price selection (helps match Bybit UI values)
        $priceSource = $config['price_source'] ?? 'ticker_last';
        if ($priceSource === 'ticker_mark' && isset($tickerData['markPrice'])) {
            $displayPrice = (float)$tickerData['markPrice'];
        } elseif ($priceSource === 'ticker_last' && isset($tickerData['lastPrice'])) {
            $displayPrice = (float)$tickerData['lastPrice'];
        }

        if (isset($tickerData['turnover24h'])) {
            $volume24 = (float)$tickerData['turnover24h'];
        } elseif (isset($tickerData['volume24h'])) {
            $lastPrice = isset($tickerData['lastPrice']) ? (float)$tickerData['lastPrice'] : $lastClose15;
            if ($lastPrice > 0) {
                $volume24 = (float)$tickerData['volume24h'] * $lastPrice;
            }
        }
    }

    // Calculate 15m indicators
    $rsi15 = calc_rsi($closes15, $periods['rsi']);
    $atr15 = calc_atr($highs15, $lows15, $closes15, $periods['atr']);
    list(, , , $bbw15, $pos15) = calc_bb_bands($closes15, $periods['bb'], $periods['bb_mult']);
    $adx15 = calc_adx($highs15, $lows15, $closes15, $periods['adx']);
    $atrPct15 = ($atr15 !== null && $lastClose15 > 0) ? ($atr15 / $lastClose15) * 100 : null;

    // Calculate change percentages
    $changePct15 = null;
    $lookbackBars = 24;
    $len15 = count($closes15);
    if ($len15 > $lookbackBars) {
        $oldClose = $closes15[$len15 - 1 - $lookbackBars];
        if ($oldClose > 0) {
            $changePct15 = (($lastClose15 - $oldClose) / $oldClose) * 100.0;
        }
    }

    $changePctShort = null;
    $shortBars = 6;
    if ($len15 > $shortBars) {
        $oldShortClose = $closes15[$len15 - 1 - $shortBars];
        if ($oldShortClose > 0) {
            $changePctShort = (($lastClose15 - $oldShortClose) / $oldShortClose) * 100.0;
        }
    }

    // Direction and speed
    $dirInfo = classify_direction($changePct15, $rsi15, $pos15, $dirConfig);
    $speedPct = calc_speed_pct($atrPct15, $bbw15, $adx15, $changePctShort, $changePct15);

    // Neutral status
    $neutral15 = is_neutral_15m($adx15, $rsi15, $bbw15, $atrPct15, $thresholds);
    $trend1h = is_trend_1h($m1h['adx'], $thresholds);
    $neutral = $neutral15 && !$trend1h;

    // State and recommendation
    $indicators = [
        'adx15' => $adx15,
        'adx1h' => $m1h['adx'],
        'rsi15' => $rsi15,
        'rsi1h' => $m1h['rsi'],
        'bbw15' => $bbw15,
        'atrPct15' => $atrPct15,
        'speed_pct' => $speedPct,
    ];

    $state = detect_state($indicators, $thresholds);
    $recommendation = get_recommendation($state, $speedPct, $bbw15, $atrPct15);

    // BTC correlation (if not BTC itself)
    $btcCorr = null;
    $btcBeta = null;
    $btcImpactLabel = 'Unknown';

    if ($symbol !== 'BTCUSDT' && !empty($btcCloses)) {
        $corrData = calc_btc_correlation($closes15, $btcCloses, $corrWindow);
        $btcCorr = $corrData['corr'];
        $btcBeta = $corrData['beta'];
        $btcImpactLabel = get_btc_impact_label($btcCorr, $btcImpact);
    }

    return [
        'symbol' => $symbol,
        'price' => $displayPrice,
        'adx15' => $adx15,
        'adx1h' => $m1h['adx'],
        'rsi15' => $rsi15,
        'rsi1h' => $m1h['rsi'],
        'bbw15' => $bbw15,
        'bbw1h' => $m1h['bbw'],
        'atrPct15' => $atrPct15,
        'atrPct1h' => $m1h['atrPct'],
        'vol24h' => $volume24,
        'speed_pct' => $speedPct,
        'neutral' => $neutral,
        'neutral15' => $neutral15,
        'trend1h' => $trend1h,
        'state' => $state,
        'recommendation' => $recommendation,
        'dir_code' => $dirInfo['code'],
        'dir_label' => $dirInfo['label'],
        'btc_corr' => $btcCorr !== null ? round($btcCorr, 3) : null,
        'btc_beta' => $btcBeta !== null ? round($btcBeta, 3) : null,
        'btc_impact' => $btcImpactLabel,
    ];
}

function get_btc_data($config) {
    $cacheDir = $config['cache_dir'];
    $ttl = $config['api_cache_ttl_seconds'];
    $apiConfig = $config['api'];
    $periods = $config['periods'];

    // Fetch 15m klines for BTC
    $useClosedOnly = !empty($config['use_closed_candles_only']);
    $kline15 = fetch_kline_data('BTCUSDT', '15', $config['kline_limit'], $cacheDir, $ttl, $apiConfig, $useClosedOnly);
    if (!$kline15) return null;

    $list15 = $kline15['list'];
    $highs15 = [];
    $lows15 = [];
    $closes15 = [];

    foreach ($list15 as $row) {
        $highs15[] = (float)$row[2];
        $lows15[] = (float)$row[3];
        $closes15[] = (float)$row[4];
    }

    $lastClose = end($closes15);
    $displayPrice = $lastClose;
    $tickerData = fetch_ticker_data('BTCUSDT', $cacheDir, $ttl, $apiConfig);
    if ($tickerData) {
        $priceSource = $config['price_source'] ?? 'ticker_last';
        if ($priceSource === 'ticker_mark' && isset($tickerData['markPrice'])) {
            $displayPrice = (float)$tickerData['markPrice'];
        } elseif ($priceSource === 'ticker_last' && isset($tickerData['lastPrice'])) {
            $displayPrice = (float)$tickerData['lastPrice'];
        }
    }
    $len = count($closes15);

    // Calculate 1h and 4h changes
    $change1h = null;
    $change4h = null;

    $bars1h = 4; // 4 x 15m = 1h
    $bars4h = 16; // 16 x 15m = 4h

    if ($len > $bars1h) {
        $oldClose = $closes15[$len - 1 - $bars1h];
        if ($oldClose > 0) {
            $change1h = (($lastClose - $oldClose) / $oldClose) * 100.0;
        }
    }

    if ($len > $bars4h) {
        $oldClose = $closes15[$len - 1 - $bars4h];
        if ($oldClose > 0) {
            $change4h = (($lastClose - $oldClose) / $oldClose) * 100.0;
        }
    }

    // Calculate ADX and speed
    $adx15 = calc_adx($highs15, $lows15, $closes15, $periods['adx']);
    $atr15 = calc_atr($highs15, $lows15, $closes15, $periods['atr']);
    list(, , , $bbw15, ) = calc_bb_bands($closes15, $periods['bb'], $periods['bb_mult']);
    $atrPct15 = ($atr15 !== null && $lastClose > 0) ? ($atr15 / $lastClose) * 100 : null;

    $speedPct = calc_speed_pct($atrPct15, $bbw15, $adx15, $change1h, $change4h);

    // Risk level
    $btcData = [
        'price' => $displayPrice,
        'change_1h_pct' => $change1h !== null ? round($change1h, 2) : null,
        'change_4h_pct' => $change4h !== null ? round($change4h, 2) : null,
        'adx15' => $adx15,
        'speed_pct' => $speedPct,
    ];

    $btcData['risk_level'] = calc_btc_risk_level($btcData, $config['btc_risk']);
    $btcData['closes'] = $closes15; // For correlation calculations

    return $btcData;
}

// ============================================================================
// PAYLOAD BUILDERS
// ============================================================================

function build_data_payload($symbols, $config) {
    $catalogIndex = build_symbol_catalog_index($config);
    $reconciliation = reconcile_saved_symbols($symbols, $catalogIndex, $config);
    $symbols = $reconciliation['symbols'];

    // Get BTC data first (for correlation calculations)
    $btcData = get_btc_data($config);
    $btcCloses = $btcData ? $btcData['closes'] : [];

    $rows = [];
    $skippedSymbols = [];

    foreach ($symbols as $symbol) {
        $row = process_symbol($symbol, $btcCloses, $config);
        if ($row) {
            $rows[] = $row;
        } else {
            $skippedSymbols[] = $symbol;
        }
    }

    // Sort: Neutral first, then by volume, then by BBW
    usort($rows, function($a, $b) {
        $aNeutral = !empty($a['neutral']);
        $bNeutral = !empty($b['neutral']);

        if ($aNeutral !== $bNeutral) {
            return $aNeutral ? -1 : 1;
        }

        $aVol = $a['vol24h'] ?? 0;
        $bVol = $b['vol24h'] ?? 0;
        if ($aVol != $bVol) {
            return $bVol <=> $aVol;
        }

        $aBBW = $a['bbw15'] ?? PHP_FLOAT_MAX;
        $bBBW = $b['bbw15'] ?? PHP_FLOAT_MAX;
        if ($aBBW != $bBBW) {
            return $aBBW <=> $bBBW;
        }

        return strcmp($a['symbol'], $b['symbol']);
    });

    // Prepare BTC data for response (without closes)
    $btcResponse = null;
    if ($btcData) {
        $btcResponse = $btcData;
        unset($btcResponse['closes']);
    }

    // Find top/weakest correlations for BTC bar
    $correlations = [];
    foreach ($rows as $row) {
        if ($row['symbol'] !== 'BTCUSDT' && $row['btc_corr'] !== null) {
            $correlations[] = [
                'symbol' => $row['symbol'],
                'corr' => $row['btc_corr']
            ];
        }
    }
    usort($correlations, function($a, $b) {
        return abs($b['corr']) <=> abs($a['corr']);
    });

    $topCorr = array_slice($correlations, 0, 5);
    $weakCorr = array_slice(array_reverse($correlations), 0, 5);

    $payload = [
        'ok' => true,
        'server_time' => date('Y-m-d h:i:s A'),
        'btc' => $btcResponse,
        'btc_top_corr' => $topCorr,
        'btc_weak_corr' => $weakCorr,
        'rows' => $rows,
        'skipped_symbols' => $skippedSymbols,
        'total_symbols' => count($symbols),
        'refresh_interval_ms' => $config['refresh_interval_ms'],
        'seed_max_age_ms' => (int)($config['seed_max_age_seconds'] ?? 20) * 1000,
        'generated_at_epoch_ms' => (int)round(microtime(true) * 1000),
        'generated_at_iso' => gmdate('c'),
        'resolved_symbols' => $reconciliation['replacements'],
    ];

    persist_last_response($payload, $config);
    return $payload;
}

// ============================================================================
// MAIN ROUTER
// ============================================================================

if (!defined('NEUTRAL_SCANNER_LIBRARY_MODE')) {
    header('Content-Type: application/json; charset=utf-8');

    // Load symbols
    $symbols = load_symbols($config['symbols_file'], $config['symbols']);
    $requestMethod = $_SERVER['REQUEST_METHOD'] ?? 'GET';

    // Handle POST actions
    if ($requestMethod === 'POST' && isset($_POST['action'])) {
        $action = $_POST['action'];

        if ($action === 'add') {
            $rawSymbol = sanitize_symbol($_POST['symbol'] ?? '');

            if ($rawSymbol === '') {
                echo json_encode(['ok' => false, 'message' => 'Please enter a symbol.']);
                exit;
            }

            if (!preg_match('/^[A-Z0-9]+$/', $rawSymbol)) {
                echo json_encode(['ok' => false, 'message' => 'Symbol can only contain letters and numbers.']);
                exit;
            }

            $catalogIndex = build_symbol_catalog_index($config);
            $resolvedSymbol = resolve_symbol_candidate($rawSymbol, $catalogIndex);
            if ($catalogIndex && !$resolvedSymbol) {
                echo json_encode([
                    'ok' => false,
                    'message' => "No active Bybit USDT futures symbol matched {$rawSymbol}.",
                ]);
                exit;
            }

            $symbol = $resolvedSymbol ?: $rawSymbol;
            if (substr($symbol, -4) !== 'USDT') {
                $symbol .= 'USDT';
            }
            $requestedSymbol = substr($rawSymbol, -4) === 'USDT' ? $rawSymbol : $rawSymbol . 'USDT';

            if (!in_array($symbol, $symbols, true)) {
                $symbols[] = $symbol;
                if (!save_symbols($config['symbols_file'], $symbols)) {
                    echo json_encode([
                        'ok' => false,
                        'message' => 'Failed to save the scanner symbol list. Check write permissions for neutral_symbols.json.',
                    ]);
                    exit;
                }
                $message = $resolvedSymbol && $resolvedSymbol !== $requestedSymbol
                    ? "Added {$symbol} (resolved from {$rawSymbol})"
                    : "Added {$symbol}";
                echo json_encode(['ok' => true, 'message' => $message, 'symbol' => $symbol, 'symbols' => $symbols]);
            } else {
                echo json_encode(['ok' => true, 'message' => "{$symbol} already exists.", 'symbol' => $symbol, 'symbols' => $symbols]);
            }
            exit;
        }

        if ($action === 'delete') {
            $symbol = sanitize_symbol($_POST['symbol'] ?? '');

            $symbols = array_values(array_filter($symbols, function($s) use ($symbol) {
                return $s !== $symbol;
            }));
            if (!save_symbols($config['symbols_file'], $symbols)) {
                echo json_encode([
                    'ok' => false,
                    'message' => 'Failed to update the scanner symbol list. Check write permissions for neutral_symbols.json.',
                ]);
                exit;
            }
            echo json_encode(['ok' => true, 'message' => "Deleted $symbol", 'symbols' => $symbols]);
            exit;
        }

        if ($action === 'reset') {
            $symbols = $config['symbols'];
            if (!save_symbols($config['symbols_file'], $symbols)) {
                echo json_encode([
                    'ok' => false,
                    'message' => 'Failed to reset the scanner symbol list. Check write permissions for neutral_symbols.json.',
                ]);
                exit;
            }
            echo json_encode(['ok' => true, 'message' => 'Reset to default symbols.', 'symbols' => $symbols]);
            exit;
        }

        echo json_encode(['ok' => false, 'message' => 'Unknown action.']);
        exit;
    }

    // Handle GET actions
    $action = $_GET['action'] ?? 'data';

    if ($action === 'btc') {
        $btcData = get_btc_data($config);
        if ($btcData) {
            unset($btcData['closes']); // Don't send closes array to client
            echo json_encode([
                'ok' => true,
                'server_time' => date('Y-m-d h:i:s A'),
                'btc' => $btcData,
            ]);
        } else {
            echo json_encode(['ok' => false, 'message' => 'Failed to fetch BTC data.']);
        }
        exit;
    }

    if ($action === 'refresh') {
        echo json_encode(get_data_payload_response($symbols, $config, true));
        exit;
    }

    if ($action === 'data') {
        echo json_encode(get_data_payload_response($symbols, $config, false));
        exit;
    }

    echo json_encode(['ok' => false, 'message' => 'Unknown action.']);
}
