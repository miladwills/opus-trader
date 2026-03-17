#!/usr/bin/env python3
from __future__ import annotations

import argparse

from services.legacy_stop_cleanup_maintenance_service import (
    DEFAULT_BOTS_PATH,
    cleanup_legacy_stop_cleanup_storage,
    format_legacy_stop_cleanup_report,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clean stale persisted stop-cleanup markers from legacy bots. "
            "This tool does not check the live exchange; stop app.py and runner.py "
            "first and confirm all symbols are flat before using --apply."
        )
    )
    parser.add_argument(
        "--bots-path",
        default=str(DEFAULT_BOTS_PATH),
        help="Path to the persisted bots JSON file.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing. This is the default mode.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup, write the cleaned bots file, and print a summary.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = cleanup_legacy_stop_cleanup_storage(
        args.bots_path,
        apply_changes=bool(args.apply),
    )
    print(format_legacy_stop_cleanup_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
