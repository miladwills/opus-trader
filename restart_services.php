#!/usr/bin/env php
<?php
// Simple CLI helper to restart Opus Trader services and Apache proxy.

if (php_sapi_name() !== 'cli') {
    fwrite(STDERR, "Run this script via CLI (php restart_services.php)\n");
    exit(1);
}

if (function_exists('posix_geteuid') && posix_geteuid() !== 0) {
    fwrite(STDERR, "Warning: run as root or with sudo so systemctl can restart services.\n");
}

$services = [
    'opus_trader.service',
    'opus_runner.service',
    'apache2.service',
];

function run_cmd(string $cmd): array {
    exec($cmd . ' 2>&1', $output, $code);
    return [$code, $output];
}

foreach ($services as $svc) {
    [$code, $out] = run_cmd("systemctl restart {$svc}");
    $status = $code === 0 ? 'OK' : 'FAIL';
    echo "[restart] {$svc}: {$status}\n";
    if ($code !== 0) {
        echo implode("\n", $out) . "\n";
    }
}

echo "\nStatus after restart:\n";
foreach ($services as $svc) {
    [$code, $out] = run_cmd("systemctl status --no-pager {$svc} --lines=3");
    echo "\n--- {$svc} ---\n";
    echo implode("\n", $out) . "\n";
}

exit(0);
