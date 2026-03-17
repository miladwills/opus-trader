#!/usr/bin/env python3
"""
Quick script to verify environment configuration is correct.
Run this before starting the app to ensure testnet/mainnet is set up properly.
"""

import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

print("=" * 70)
print("ENVIRONMENT CONFIGURATION CHECK")
print("=" * 70)

# Check BYBIT_ACTIVE_ENV
active_env = os.getenv("BYBIT_ACTIVE_ENV", "").lower()
print(f"\n1. BYBIT_ACTIVE_ENV: {active_env if active_env else '❌ NOT SET (will default to testnet)'}")

if active_env == "testnet":
    print("   ✅ Set to TESTNET (safe)")
elif active_env == "mainnet":
    print("   ⚠️  Set to MAINNET (REAL MONEY!)")
else:
    print("   ⚠️  Not set or invalid - will default to testnet")

# Check DEFAULT_TRADING_ENV
default_env = os.getenv("DEFAULT_TRADING_ENV", "testnet").lower()
print(f"\n2. DEFAULT_TRADING_ENV: {default_env}")
if default_env == "testnet":
    print("   ✅ New bots will default to testnet")
else:
    print("   ⚠️  New bots will default to mainnet")

# Check testnet credentials
testnet_key = os.getenv("BYBIT_TESTNET_API_KEY", "")
testnet_secret = os.getenv("BYBIT_TESTNET_API_SECRET", "")

print(f"\n3. TESTNET Credentials:")
if testnet_key and testnet_secret:
    print(f"   ✅ API Key: {testnet_key[:10]}... (length: {len(testnet_key)})")
    print(f"   ✅ API Secret: {testnet_secret[:10]}... (length: {len(testnet_secret)})")
    print(f"   ✅ Base URL: {os.getenv('BYBIT_TESTNET_BASE_URL', 'https://api-testnet.bybit.com')}")
else:
    print("   ❌ NOT SET - testnet won't work!")

# Check mainnet credentials
mainnet_key = os.getenv("BYBIT_MAINNET_API_KEY", "")
mainnet_secret = os.getenv("BYBIT_MAINNET_API_SECRET", "")

print(f"\n4. MAINNET Credentials:")
if mainnet_key and mainnet_secret:
    print(f"   ⚠️  API Key: {mainnet_key[:10]}... (length: {len(mainnet_key)})")
    print(f"   ⚠️  API Secret: {mainnet_secret[:10]}... (length: {len(mainnet_secret)})")
    print(f"   ⚠️  Base URL: {os.getenv('BYBIT_MAINNET_BASE_URL', 'https://api.bybit.com')}")
    print("   ⚠️  REAL MONEY CREDENTIALS ARE SET!")
else:
    print("   ℹ️  Not set (mainnet won't work)")

# Determine which will be used
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if active_env == "testnet" and testnet_key:
    print("✅ Backend will use: TESTNET (safe)")
    print("✅ Balance shown: Testnet fake money")
    print("✅ New bots: Created on testnet")
elif active_env == "mainnet" and mainnet_key:
    print("🔴 Backend will use: MAINNET (REAL MONEY!)")
    print("🔴 Balance shown: Real account balance")
    print("🔴 New bots: Created on mainnet")
elif not active_env and testnet_key:
    print("✅ Backend will use: TESTNET (safe, by default)")
    print("✅ Balance shown: Testnet fake money")
    print("✅ New bots: Created on testnet")
elif not active_env and mainnet_key:
    print("⚠️  Backend will use: MAINNET (only mainnet configured)")
    print("⚠️  Balance shown: Real account balance")
    print("⚠️  This might be unintended!")
else:
    print("❌ ERROR: No valid credentials found!")

print("\n" + "=" * 70)
print("RECOMMENDATIONS")
print("=" * 70)

if active_env != "testnet":
    print("⚠️  Consider setting BYBIT_ACTIVE_ENV=testnet for safety")

if not testnet_key or not testnet_secret:
    print("⚠️  Set up testnet credentials for safe testing")

if default_env != "testnet":
    print("⚠️  Consider setting DEFAULT_TRADING_ENV=testnet")

print("\n✅ To use testnet:")
print("   1. Set BYBIT_ACTIVE_ENV=testnet in .env")
print("   2. Make sure testnet credentials are filled in")
print("   3. Restart the app")

print("\n🔴 To use mainnet:")
print("   1. Set BYBIT_ACTIVE_ENV=mainnet in .env")
print("   2. Make sure mainnet credentials are filled in")
print("   3. Restart the app")
print("   4. ⚠️  VERIFY you see MAINNET indicator in dashboard!")

print("\n" + "=" * 70)
