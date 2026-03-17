"""Tests for log pattern matching."""

import re
import pytest
from opus_platform_watchdog.classifiers.patterns import PATTERNS


@pytest.mark.parametrize("pattern", PATTERNS, ids=[p.key for p in PATTERNS])
def test_pattern_compiles(pattern):
    compiled = re.compile(pattern.regex, re.IGNORECASE)
    assert compiled is not None


LOG_SAMPLES = [
    ("Unhandled error in main loop: KeyError('some_key')", "unhandled_main_loop"),
    ("Cycle SLA breach #3 (12.5s > 10.0s)", "cycle_sla_breach"),
    ("Persisted bot error state after cycle exception", "bot_error_state"),
    ("[BTCUSDT] Order router action failed: place_order (timeout)", "order_router_failed"),
    ("MarginMonitor add-margin exception: insufficient balance", "margin_exception"),
    ("ORDER_ROUTER_TIMEOUT_RESOLVED symbol=ETHUSDT action=place outcome=filled", "order_router_timeout"),
    ("Dashboard snapshot timeout for summary after 3.0s", "snapshot_timeout"),
    ("Dashboard snapshot error for positions: ConnectionError", "snapshot_error"),
    ("Bot storage cache_lock timed out after 0.250s", "cache_lock_timeout"),
    ("Request timeout: POST /v5/order/create", "request_timeout"),
    ("recv_window error: timestamp ahead by 2000ms", "recv_window"),
    ("ping/pong timed out, reconnecting", "ws_disconnect"),
    ("WebSocket connection closed unexpectedly", "ws_disconnect"),
    ("stream reconnect attempt #3", "ws_disconnect"),
]


@pytest.mark.parametrize("line,expected_key", LOG_SAMPLES)
def test_pattern_matches_sample(line, expected_key):
    matched = False
    for pattern in PATTERNS:
        compiled = re.compile(pattern.regex, re.IGNORECASE)
        if compiled.search(line):
            assert pattern.key == expected_key, f"Line matched {pattern.key} instead of {expected_key}"
            matched = True
            break
    assert matched, f"No pattern matched line: {line}"


def test_no_pattern_matches_normal_log():
    normal_lines = [
        "2026-03-17 10:00:00 [INFO] Bot cycle completed for BTCUSDT",
        "2026-03-17 10:00:01 [INFO] Grid tick completed in 2.3s",
        "2026-03-17 10:00:02 [INFO] Account equity synced: 15000.00",
    ]
    for line in normal_lines:
        for pattern in PATTERNS:
            compiled = re.compile(pattern.regex, re.IGNORECASE)
            assert not compiled.search(line), f"Normal line matched {pattern.key}: {line}"
