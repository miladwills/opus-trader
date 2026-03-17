import time

from services.neutral_scanner_service import NeutralScannerService


def test_resolve_scan_symbols_skips_placeholder_and_maps_dead_aliases():
    service = NeutralScannerService.__new__(NeutralScannerService)
    service._symbol_catalog_cache = {
        "fetched_at": time.time(),
        "actual_symbols": {"BTCUSDT", "1000PEPEUSDT", "1000SHIBUSDT"},
        "alias_map": {
            "PEPEUSDT": "1000PEPEUSDT",
            "SHIBUSDT": "1000SHIBUSDT",
        },
    }

    resolved = NeutralScannerService._resolve_scan_symbols(
        service,
        [
            "Auto-Pilot",
            "pepeusdt",
            "1000PEPEUSDT",
            "BTCUSDT",
            "SHIBUSDT",
            "UNKNOWNUSDT",
        ],
    )

    assert resolved == ["1000PEPEUSDT", "BTCUSDT", "1000SHIBUSDT"]
