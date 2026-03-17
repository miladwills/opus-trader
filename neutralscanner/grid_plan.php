<?php
// grid_plan.php – صفحة تخطيط للجريد بوت لعملة مفردة
// يعرض اقتراحات للرينج وعدد الجريدز والخطوة بناءً على بيانات العملة ويفسح المجال للمستخدم لتعديل الإعدادات

date_default_timezone_set('Africa/Cairo');

// -------- Helpers --------

function http_get_json($url) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_SSL_VERIFYPEER => false,
    ]);
    $res = curl_exec($ch);
    if ($res === false) {
        curl_close($ch);
        return null;
    }
    curl_close($ch);
    $data = json_decode($res, true);
    return $data;
}

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
    if ($len <= $period + 1) return null;
    $trs = [];
    for ($i = 1; $i < $len; $i++) {
        $high      = $highs[$i];
        $low       = $lows[$i];
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
    $std = sqrt($sumSq / $period);
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

function format_num($n, $dec = 5) {
    if ($n === null) return '-';
    return rtrim(rtrim(number_format((float)$n, $dec, '.', ''), '0'), '.');
}

// -------- Fetch metrics for symbol --------
function get_symbol_metrics($symbol, $interval15 = '15', $interval60 = '60', $limit = 200) {
    // Fetch kline 15m
    $klineUrl15 = sprintf(
        'https://api.bybit.com/v5/market/kline?category=linear&symbol=%s&interval=%s&limit=%d',
        urlencode($symbol), $interval15, $limit
    );
    $data15 = http_get_json($klineUrl15);
    if (!$data15 || ($data15['retCode'] ?? -1) !== 0) return null;
    $list15 = $data15['result']['list'] ?? [];
    if (!is_array($list15) || count($list15) < 22) return null;
    $list15 = array_reverse($list15);
    $highs15 = $lows15 = $closes15 = [];
    foreach ($list15 as $row) {
        $highs15[]  = (float)$row[2];
        $lows15[]   = (float)$row[3];
        $closes15[] = (float)$row[4];
    }
    $lastClose15 = end($closes15);
    // indicators 15m
    $rsi15  = calc_rsi($closes15, 14);
    $atr15  = calc_atr($highs15, $lows15, $closes15, 14);
    $atrPct15 = ($atr15 !== null && $lastClose15 > 0) ? ($atr15 / $lastClose15) * 100.0 : null;
    list($bbU15, $bbL15, $bbM15, $bbw15, $pos15) = calc_bb_bands($closes15, 20, 2.0);
    $adx15 = calc_adx($highs15, $lows15, $closes15, 14);
    // Fetch kline 1h
    $klineUrl60 = sprintf(
        'https://api.bybit.com/v5/market/kline?category=linear&symbol=%s&interval=%s&limit=%d',
        urlencode($symbol), $interval60, $limit
    );
    $data60 = http_get_json($klineUrl60);
    $rsi60 = $adx60 = $bbw60 = $atrPct60 = null;
    if ($data60 && ($data60['retCode'] ?? -1) === 0) {
        $list60 = $data60['result']['list'] ?? [];
        if (is_array($list60) && count($list60) >= 22) {
            $list60 = array_reverse($list60);
            $highs60 = $lows60 = $closes60 = [];
            foreach ($list60 as $row) {
                $highs60[]  = (float)$row[2];
                $lows60[]   = (float)$row[3];
                $closes60[] = (float)$row[4];
            }
            $lastClose60 = end($closes60);
            $rsi60  = calc_rsi($closes60, 14);
            $atr60  = calc_atr($highs60, $lows60, $closes60, 14);
            $atrPct60 = ($atr60 !== null && $lastClose60 > 0) ? ($atr60 / $lastClose60) * 100.0 : null;
            list($bbU60, $bbL60, $bbM60, $bbw60, $pos60) = calc_bb_bands($closes60, 20, 2.0);
            $adx60 = calc_adx($highs60, $lows60, $closes60, 14);
        }
    }
    // volume
    $volume24 = null;
    $tickerUrl = sprintf(
        'https://api.bybit.com/v5/market/tickers?category=linear&symbol=%s',
        urlencode($symbol)
    );
    $tickerData = http_get_json($tickerUrl);
    if ($tickerData && ($tickerData['retCode'] ?? -1) === 0) {
        $tickerRow = $tickerData['result']['list'][0] ?? null;
        if ($tickerRow) {
            $volume24 = (float)$tickerRow['volume24h'];
        }
    }
    return [
        'symbol'    => $symbol,
        'price'     => $lastClose15,
        'adx15'     => $adx15,
        'adx1h'     => $adx60,
        'rsi15'     => $rsi15,
        'rsi1h'     => $rsi60,
        'bbw15'     => $bbw15,
        'bbw1h'     => $bbw60,
        'atrPct15'  => $atrPct15,
        'atrPct1h'  => $atrPct60,
        'volume24'  => $volume24,
    ];
}

// ------- Main --------

$symbol = isset($_GET['symbol']) ? trim($_GET['symbol']) : '';
if ($symbol === '') {
    echo '<h2>لم يتم تمرير رمز العملة.</h2>';
    exit;
}

// اجلب بيانات العملة
$metrics = get_symbol_metrics($symbol);
if (!$metrics) {
    echo '<h2>تعذر جلب بيانات العملة أو البيانات غير كافية.</h2>';
    exit;
}

// اجلب بيانات البيتكوين لتحديد حالته
$btcMetrics = get_symbol_metrics('BTCUSDT');
$btcNeutral = false;
if ($btcMetrics) {
    // شرط بسيط: ADX15 بين 15 و 30، RSI15 بين 35 و 65، BBW15 بين 3 و 8
    $score = 0;
    if ($btcMetrics['adx15'] !== null && $btcMetrics['adx15'] >= 16 && $btcMetrics['adx15'] <= 28) $score++;
    if ($btcMetrics['rsi15'] !== null && $btcMetrics['rsi15'] >= 38 && $btcMetrics['rsi15'] <= 62) $score++;
    if ($btcMetrics['bbw15'] !== null && $btcMetrics['bbw15'] >= 3.5 && $btcMetrics['bbw15'] <= 8.0) $score++;
    $btcNeutral = $score >= 2;
}

// نطاقات الكى (حساسية الرينج) لكل مستوى مخاطرة
$riskScales = [
    'conservative' => 1.5,
    'normal'       => 2.0,
    'aggressive'   => 2.5,
];
// اقتراح عدد الجريدز لكل مستوى مخاطرة
$riskGrids = [
    'conservative' => 12,
    'normal'       => 16,
    'aggressive'   => 22,
];

?><!doctype html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="utf-8">
    <title>إعدادات جريد بوت – <?= htmlspecialchars($symbol, ENT_QUOTES, 'UTF-8') ?></title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            background: #050509;
            color: #f5f5f5;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            direction: rtl;
        }
        h1 {
            margin: 0 0 8px;
            font-size: 24px;
        }
        .section {
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 14px;
        }
        label {
            display: block;
            margin-bottom: 4px;
            font-size: 12px;
            color: #9ca3af;
        }
        input, select {
            width: 100%;
            padding: 6px 8px;
            margin-bottom: 8px;
            border-radius: 4px;
            border: 1px solid #334155;
            background: #020617;
            color: #f5f5f5;
        }
        .result-card {
            background: #020617;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 8px;
            font-size: 13px;
        }
        .warning {
            background: #7f1d1d;
            color: #fecaca;
            padding: 8px 10px;
            border-radius: 6px;
            margin-bottom: 12px;
            font-size: 12px;
        }
        .small {
            font-size: 12px;
            color: #94a3b8;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        button.compute-btn {
            background: #10b981;
            color: #022c22;
            border: none;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }
        button.compute-btn:hover {
            background: #34d399;
        }
    </style>
</head>
<body>
    <h1>إعدادات الجريد: <?= htmlspecialchars($symbol, ENT_QUOTES, 'UTF-8') ?></h1>
    <?php if (!$btcNeutral): ?>
        <div class="warning">⚠️ تنبيه: البيتكوين خارج نطاق النيوترال، قد تكون هناك حركة عنيفة. يفضَّل تقليل حجم الصفقات أو الانتظار.</div>
    <?php endif; ?>
    <div class="section">
        <h2 style="font-size:18px;margin:0 0 6px;">بيانات المؤشرات الحالية</h2>
        <div class="grid">
            <div>
                <strong>السعر الحالي:</strong> <?= format_num($metrics['price'], 5) ?>
            </div>
            <div>
                <strong>حجم التداول 24h:</strong> <?= $metrics['volume24'] !== null ? number_format($metrics['volume24'], 0, '.', ',') : '-' ?>
            </div>
            <div>
                <strong>ADX 15m:</strong> <?= format_num($metrics['adx15'], 2) ?>
            </div>
            <div>
                <strong>ADX 1h:</strong> <?= format_num($metrics['adx1h'], 2) ?>
            </div>
            <div>
                <strong>RSI 15m:</strong> <?= format_num($metrics['rsi15'], 2) ?>
            </div>
            <div>
                <strong>RSI 1h:</strong> <?= format_num($metrics['rsi1h'], 2) ?>
            </div>
            <div>
                <strong>BBW% 15m:</strong> <?= format_num($metrics['bbw15'], 2) ?>
            </div>
            <div>
                <strong>BBW% 1h:</strong> <?= format_num($metrics['bbw1h'], 2) ?>
            </div>
            <div>
                <strong>ATR% 15m:</strong> <?= format_num($metrics['atrPct15'], 2) ?>
            </div>
            <div>
                <strong>ATR% 1h:</strong> <?= format_num($metrics['atrPct1h'], 2) ?>
            </div>
        </div>
    </div>
    <div class="section">
        <h2 style="font-size:18px;margin:0 0 6px;">إدخال الإعدادات</h2>
        <label for="capital">رأس المال (USDT)</label>
        <input type="number" id="capital" value="100" step="0.01" min="10">
        <label for="leverage">الرافعة المالية (x)</label>
        <input type="number" id="leverage" value="5" step="1" min="1" max="20">
        <label for="risk">الملف الشخصي للمخاطرة</label>
        <select id="risk">
            <option value="conservative">محافظ</option>
            <option value="normal" selected>متوسط</option>
            <option value="aggressive">هجومي</option>
        </select>
        <label for="mode">وضع الرينج</label>
        <select id="mode">
            <option value="neutral" selected>متوازن (50/50)</option>
            <option value="up">محب للصعود (40% تحت / 60% فوق)</option>
            <option value="down">محب للهبوط (60% تحت / 40% فوق)</option>
        </select>
        <button class="compute-btn" onclick="computeGrid()">احسب الخطة</button>
    </div>
    <div class="section">
        <h2 style="font-size:18px;margin:0 0 6px;">النتائج المقترحة</h2>
        <div id="results">
            <p class="small">أدخل إعداداتك ثم اضغط "احسب الخطة".</p>
        </div>
    </div>

<script>
function computeGrid() {
    const price    = <?= json_encode($metrics['price']) ?>;
    const atr1hPct = <?= json_encode($metrics['atrPct1h']) ?>;
    if (!price || !atr1hPct) {
        document.getElementById('results').innerHTML = '<p>بيانات غير كافية للحساب.</p>';
        return;
    }
    const capital  = parseFloat(document.getElementById('capital').value) || 0;
    const leverage = parseFloat(document.getElementById('leverage').value) || 1;
    const risk     = document.getElementById('risk').value;
    const mode     = document.getElementById('mode').value;

    // حساسية الرينج وفقًا للمخاطرة
    const kMap   = {conservative: 1.5, normal: 2.0, aggressive: 2.5};
    const gridMap= {conservative: 12, normal: 16, aggressive: 22};
    const k      = kMap[risk] || 2.0;
    let grids  = gridMap[risk] || 16;

    // تقدير نسبة الرينج من ATR 1h
    const rangePct = atr1hPct * k;
    const rangeAbs = price * (rangePct / 100.0);
    let lower, upper;
    if (mode === 'up') {
        lower = price - rangeAbs * 0.4;
        upper = price + rangeAbs * 0.6;
    } else if (mode === 'down') {
        lower = price - rangeAbs * 0.6;
        upper = price + rangeAbs * 0.4;
    } else {
        lower = price - rangeAbs / 2.0;
        upper = price + rangeAbs / 2.0;
    }
    // خطوة الجريد كنسبة مئوية
    const minStepPct = 0.15; // حافظ على مسافة كافية بين الجريدز لمنع أرباح تساوي صفر
    const spanAbs = upper - lower;
    let gridsUsed = grids;
    let stepPct = spanAbs / (gridsUsed - 1) / price * 100.0;
    if (stepPct < minStepPct) {
        gridsUsed = Math.max(6, Math.round(spanAbs / (price * (minStepPct / 100))) + 1);
        gridsUsed = Math.min(gridsUsed, 28); // سقف لتجنب كثرة الأوامر
        stepPct = spanAbs / (gridsUsed - 1) / price * 100.0;
    }
    // نعتبر 20% احتياطي غير مستخدم
    const reserve  = 0.2;
    const activeCapital = capital * (1 - reserve);
    const capitalPerGrid  = activeCapital / gridsUsed;
    const positionPerGrid = capitalPerGrid * leverage;
    const profitPerGrid   = positionPerGrid * (stepPct / 100.0);
    const estDailyGrids   = Math.min(30, Math.max(4, Math.round(atr1hPct / stepPct * 12))); // تقدير عشوائي لعدد الشبكات يوميًا
    const estDailyProfit  = profitPerGrid * estDailyGrids;
    const warnings = [];
    if (stepPct < minStepPct + 0.001) {
        warnings.push(`تم توسيع المسافة بين الجريدز لتكون ${stepPct.toFixed(3)}٪ باستخدام ${gridsUsed} شبكة لتجنب أرباح صفرية.`);
    }
    if (profitPerGrid < 0.01) {
        warnings.push('الربح لكل جريد أقل من 0.01 USDT — جرّب تقليل عدد الجريدز، أو زيادة رأس المال/الرافعة.');
    }
    // عرض النتائج
    document.getElementById('results').innerHTML = `
        <div class="result-card">
            <strong>نطاق التداول:</strong> من <code>${lower.toFixed(5)}</code> إلى <code>${upper.toFixed(5)}</code><br>
            <strong>عدد الجريدز المقترح:</strong> ${gridsUsed} شبكة<br>
            <strong>نسبة الخطوة لكل جريد:</strong> ${stepPct.toFixed(3)}٪<br>
            <strong>رأس المال المتاح لكل جريد:</strong> ${capitalPerGrid.toFixed(4)} USDT<br>
            <strong>حجم الصفقة لكل جريد (بعد الرافعة):</strong> ${positionPerGrid.toFixed(4)} USDT<br>
            <strong>الربح لكل جريد (تقريبًا):</strong> ${profitPerGrid.toFixed(4)} USDT<br>
            <strong>تقدير عدد الجريدز يوميًا:</strong> ${estDailyGrids} عملية<br>
            <strong>تقدير الربح اليومي:</strong> ${estDailyProfit.toFixed(4)} USDT
        </div>
        ${warnings.length ? `<div class="warning">${warnings.join('<br>')}</div>` : ''}
        <div class="result-card">
            <strong>نص للتنفيذ:</strong><br>
            <code>Lower: ${lower.toFixed(5)}, Upper: ${upper.toFixed(5)}, Grids: ${gridsUsed}, Leverage: ${leverage}, Capital: ${capital}</code>
        </div>
    `;
}
</script>
</body>
</html>