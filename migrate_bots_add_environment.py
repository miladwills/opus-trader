#!/usr/bin/env python3
"""
Migration script to add trading_env and paper_trading fields to existing bots.

This script:
1. Reads existing bots from storage/bots.json
2. Adds trading_env="testnet" to bots missing the field
3. Adds paper_trading=True to bots missing the field
4. Saves the updated bots back to storage

Usage:
    python migrate_bots_add_environment.py [--dry-run]

Options:
    --dry-run: Show what would be changed without actually changing anything
"""

import json
import sys
import os
from pathlib import Path

# Default bot storage path
BOT_STORAGE_PATH = Path("storage/bots.json")


def migrate_bots(dry_run=False):
    """
    Add trading_env and paper_trading fields to existing bots.

    Args:
        dry_run: If True, show changes without saving

    Returns:
        Number of bots updated
    """
    if not BOT_STORAGE_PATH.exists():
        print(f"❌ Bot storage file not found: {BOT_STORAGE_PATH}")
        print(f"   Create it or check your working directory")
        return 0

    # Read existing bots
    with open(BOT_STORAGE_PATH, "r", encoding="utf-8") as f:
        bots = json.load(f)

    if not isinstance(bots, list):
        print(f"❌ Invalid bots.json format (expected list, got {type(bots).__name__})")
        return 0

    print(f"📖 Found {len(bots)} bot(s) in {BOT_STORAGE_PATH}")
    print()

    updated_count = 0

    for i, bot in enumerate(bots):
        bot_id = bot.get("id", f"unknown_{i}")
        symbol = bot.get("symbol", "UNKNOWN")
        status = bot.get("status", "unknown")
        changes = []

        # Add trading_env if missing
        if "trading_env" not in bot or not bot["trading_env"]:
            bot["trading_env"] = "testnet"
            changes.append("trading_env=testnet")
            updated_count += 1

        # Add paper_trading if missing
        if "paper_trading" not in bot:
            bot["paper_trading"] = True
            changes.append("paper_trading=True")
            updated_count += 1

        # Log changes
        if changes:
            print(f"🔄 Bot {bot_id} ({symbol}, {status})")
            print(f"   Adding: {', '.join(changes)}")
            print()

    if updated_count == 0:
        print("✅ All bots already have trading_env and paper_trading fields")
        print("   No migration needed!")
        return 0

    # Show summary
    print("-" * 60)
    print(f"Summary: {updated_count} field(s) to be added across {len(bots)} bot(s)")
    print()

    # Save changes
    if dry_run:
        print("🔍 DRY RUN MODE - No changes saved")
        print("   Remove --dry-run flag to apply changes")
    else:
        # Create backup
        backup_path = BOT_STORAGE_PATH.with_suffix(".json.backup")
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(bots, f, indent=2, ensure_ascii=False)
        print(f"💾 Created backup: {backup_path}")

        # Save updated bots
        with open(BOT_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(bots, f, indent=2, ensure_ascii=False)
        print(f"✅ Saved updated bots to: {BOT_STORAGE_PATH}")
        print()
        print("🎉 Migration complete!")
        print()
        print("All bots now have:")
        print("  - trading_env = 'testnet' (safe default)")
        print("  - paper_trading = True (safe default)")

    return updated_count


def main():
    """Main entry point."""
    # Check for --dry-run flag
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("🔍 Running in DRY RUN mode")
        print()

    print("=" * 60)
    print("Bybit Environment Migration Script")
    print("=" * 60)
    print()

    # Run migration
    updated = migrate_bots(dry_run=dry_run)

    # Exit
    if updated > 0 and not dry_run:
        print()
        print("Next steps:")
        print("1. Verify bots in dashboard")
        print("2. Check that all bots show 'ENV: TESTNET'")
        print("3. Manually switch bots to mainnet if needed (after testing!)")
        return 0
    elif updated > 0 and dry_run:
        print()
        print("Run without --dry-run to apply these changes")
        return 0
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
