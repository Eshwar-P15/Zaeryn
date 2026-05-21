# scripts/fetch_birdeye_history.py
# Backfills full OHLCV history for JUP, BONK, WIF, PYTH, RAY from Birdeye.
#
# Prerequisites:
#   1. BIRDEYE_API_KEY set in .env (get free key: https://bds.birdeye.so)
#   2. zaeryn.db exists
#
# Safe to re-run — upsert_candles() uses INSERT OR REPLACE, no duplicates.
# Runtime: ~5-10 minutes (rate limited to 1 req/sec on free tier).
#
# Run: python -X utf8 scripts/fetch_birdeye_history.py

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config.settings import BIRDEYE_API_KEY, BIRDEYE_HISTORY_DAYS, SOLANA_TOKENS
from data.birdeye_fetcher import fetch_birdeye_ohlcv
from data.cleaner import clean_ohlcv, detect_anomalies, normalize_price_data, validate_ohlcv
from data.storage import get_db_stats, init_db, upsert_candles
from utils.logger import get_logger

logger = get_logger("fetch_birdeye_history")
TOKENS = ["JUP", "BONK", "WIF", "PYTH", "RAY"]


def main():
    print("\n" + "=" * 65)
    print("  ZAERYN — Birdeye Solana Token History Backfill")
    print(f"  Tokens:  {', '.join(TOKENS)}")
    print(f"  Target:  {BIRDEYE_HISTORY_DAYS} days max per token")
    print("  Runtime: ~5-10 minutes")
    print("=" * 65 + "\n")

    if not BIRDEYE_API_KEY:
        print("ERROR: BIRDEYE_API_KEY not set in .env\n")
        print("  1. Go to: https://bds.birdeye.so/auth/sign-up")
        print("  2. Sign up with email (free, no credit card)")
        print("  3. Verify your email")
        print("  4. Dashboard → Security tab → Generate Key")
        print("  5. Add to .env:  BIRDEYE_API_KEY=your_key_here")
        print("  6. Re-run this script")
        sys.exit(1)

    print("  API key: loaded ✓\n")

    conn = init_db()
    stats_before = get_db_stats(conn)
    total_added = 0
    results = {}

    for i, token in enumerate(TOKENS, 1):
        mint = SOLANA_TOKENS.get(token)
        if not mint:
            print(f"  [{i}/{len(TOKENS)}] {token}: missing mint address — skipping\n")
            continue

        print(f"  [{i}/{len(TOKENS)}] {token}  ({mint[:8]}...)")
        t0 = time.time()

        try:
            raw = fetch_birdeye_ohlcv(
                mint_address=mint,
                symbol=token,
                granularity="1h",
                days_back=BIRDEYE_HISTORY_DAYS,
            )
        except RuntimeError as e:
            print(f"  ✗ FAILED — {e}\n")
            results[token] = "failed"
            continue

        if raw is None or raw.empty:
            print("  ✗ No data returned\n")
            results[token] = "no data"
            continue

        cleaned = clean_ohlcv(raw)
        is_valid, errors = validate_ohlcv(cleaned)

        if not is_valid:
            print(f"  ✗ Validation failed: {errors}\n")
            results[token] = f"invalid: {errors}"
            continue

        cleaned = detect_anomalies(cleaned)
        cleaned = normalize_price_data(cleaned)
        anomalies = int(cleaned["is_anomaly"].sum()) if "is_anomaly" in cleaned.columns else 0

        written = upsert_candles(token, "1h", cleaned, conn)
        total_added += written

        elapsed = round(time.time() - t0, 1)
        earliest = cleaned["timestamp"].min().strftime("%Y-%m-%d")
        latest = cleaned["timestamp"].max().strftime("%Y-%m-%d")

        print(
            f"  ✓ {written:,} candles | {earliest} → {latest} | "
            f"{anomalies} anomalies | {elapsed}s\n"
        )
        results[token] = written

    stats_after = get_db_stats(conn)
    conn.close()

    print("=" * 65)
    print(f"  {'TOKEN':<8}  {'BEFORE':>8}  {'AFTER':>8}  {'ADDED':>8}  STATUS")
    print("  " + "-" * 60)

    for token in TOKENS:
        before = stats_before.get(token, {}).get("1h", {}).get("count", 0)
        after = stats_after.get(token, {}).get("1h", {}).get("count", 0)
        added = after - before
        oldest = stats_after.get(token, {}).get("1h", {}).get("oldest", "")[:10]

        if after >= 5000:
            status = "✓ READY"
        elif after >= 1000:
            status = "△  LIMITED"
        else:
            status = "✗ INSUFFICIENT"

        print(f"  {token:<8}  {before:>8,}  {after:>8,}  {added:>+8,}  {status}  [{oldest}]")

    print("=" * 65)
    print(f"\n  Total candles added: {total_added:,}")

    ready = [t for t in TOKENS if stats_after.get(t, {}).get("1h", {}).get("count", 0) >= 1000]
    print(f"  Ready for training:  {ready}\n")

    print("  Next steps:")
    print("  python -X utf8 scripts/fetch_history.py       — top up Coinbase assets to 900 days")
    print("  python -X utf8 scripts/train_models.py --retrain")
    print("  python scripts/run_backtest.py")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
