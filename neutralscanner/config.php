<?php
/**
 * Neutral Scanner Pro - Configuration
 * All settings, thresholds, and defaults in one place
 */

return [
    // Default symbols list (USDT perpetuals)
    'symbols' => [
        'BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','TRXUSDT',
        'TONUSDT','AVAXUSDT','LINKUSDT','DOTUSDT','MATICUSDT','ATOMUSDT','LTCUSDT','BCHUSDT',
        'ETCUSDT','NEARUSDT','APTUSDT','ARBUSDT','OPUSDT','INJUSDT','SEIUSDT','SUIUSDT',
        'UNIUSDT','AAVEUSDT','MKRUSDT','FTMUSDT','RUNEUSDT','EGLDUSDT','FILUSDT','ICPUSDT',
        'XLMUSDT','HBARUSDT','IMXUSDT','GALAUSDT','SANDUSDT','MANAUSDT','AXSUSDT',
        'DYDXUSDT','WIFUSDT','PEPEUSDT','SHIBUSDT','FLOKIUSDT','BONKUSDT',
        'RNDRUSDT','RENDERUSDT','TIAUSDT','JTOUSDT','JUPUSDT','PYTHUSDT','STXUSDT',
        'ARUSDT','KASUSDT','THETAUSDT','EOSUSDT','IOTAUSDT'
    ],

    // File paths
    'symbols_file' => __DIR__ . '/neutral_symbols.json',
    'cache_dir' => __DIR__ . '/cache',

    // Cache settings
    'api_cache_ttl_seconds' => 120,
    'instrument_catalog_cache_ttl_seconds' => 900,
    'seed_max_age_seconds' => 90,
    'payload_refresh_lock_timeout_seconds' => 180,

    // Correlation settings
    'correlation_window_15m_bars' => 96,

    // UI refresh interval (milliseconds)
    'refresh_interval_ms' => 8000,

    // Price source shown in the UI
    // - 'ticker_last' : Bybit ticker lastPrice (closest to what you see in Bybit UI)
    // - 'ticker_mark' : Bybit ticker markPrice
    // - 'kline_close' : last 15m kline close (can lag / be candle-based)
    'price_source' => 'ticker_last',

    // Indicators are more consistent with Bybit/TV when calculated on closed candles only.
    // If true, the last (still-forming) candle is excluded from indicator calculations.
    'use_closed_candles_only' => true,

    // Indicator periods
    'periods' => [
        'adx' => 14,
        'rsi' => 14,
        'atr' => 14,
        'bb' => 20,
        'bb_mult' => 2.0,
    ],

    // Kline settings
    'kline_limit' => 200,

    // Indicator thresholds (preserved from original)
    'thresholds' => [
        // ADX thresholds
        'adx_15m_neutral_min' => 12,
        'adx_15m_neutral_max' => 30,
        'adx_1h_trend_min' => 25,

        // RSI thresholds
        'rsi_neutral_low' => 30,
        'rsi_neutral_high' => 70,

        // BBW threshold
        'bbw_neutral_max' => 25,

        // ATR threshold
        'atr_pct_neutral_max' => 3.0,

        // Speed threshold
        'speed_high_pct' => 1.2,

        // Volatile thresholds (multiplier of neutral max)
        'volatile_bbw_mult' => 1.5,  // BBW > 37.5% = volatile
        'volatile_atr_mult' => 1.5,  // ATR > 4.5% = volatile
        'volatile_speed_pct' => 70,  // Speed > 70% = volatile
    ],

    // BTC risk thresholds
    'btc_risk' => [
        'high_abs_change_1h_pct' => 1.2,
        'high_abs_change_4h_pct' => 2.5,
        'high_speed_pct' => 1.0,
    ],

    // BTC impact correlation thresholds
    'btc_impact' => [
        'corr_high' => 0.65,
        'corr_med' => 0.40,
        'corr_low' => 0.20,
    ],

    // API settings
    'api' => [
        'base_url' => 'https://api.bybit.com/v5/market',
        'curl_connect_timeout' => 3,
        'curl_total_timeout' => 6,
        'user_agent' => 'NeutralScannerPro/2.0',
        // Keep SSL verification enabled for safety. If your server is missing CA certificates,
        // you may set this to false (not recommended).
        'ssl_verify' => true,
    ],

    // Direction classification thresholds
    'direction' => [
        'flat_range_change_max' => 0.5,
        'flat_range_rsi_min' => 45,
        'flat_range_rsi_max' => 55,
        'flat_range_pos_min' => 0.35,
        'flat_range_pos_max' => 0.65,
        'neutral_up_change_min' => 0.5,
        'neutral_up_change_max' => 4.0,
        'neutral_down_change_min' => -4.0,
        'neutral_down_change_max' => -0.5,
    ],

    // Legacy aliases that should resolve to the current Bybit futures symbol.
    'symbol_aliases' => [
        'MATIC' => 'POL',
        'FTM' => 'S',
    ],

    // Timezone
    'timezone' => 'Africa/Cairo',
];
