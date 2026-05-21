# scripts/fetch_stock_forex_history.py
# Backfills 730 days of hourly OHLCV history for all stocks and forex assets
# via Yahoo Finance (yfinance).
#
# Prerequisites:
#   pip install yfinance>=0.2.40
#   zaeryn.db must exist (run any previous backfill or init_db first)
#
# Safe to re-run — upsert_candles() uses INSERT OR REPLACE, no duplicates.
# Runtime: ~1-2 minutes (no rate limiting needed for yfinance).
#
# Run: python -X utf8 scripts/fetch_stock_forex_history.py

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config.settings import STOCK_TICKERS, FOREX_TICKERS, YFINANCE_MAX_DAYS_1H
from utils.logger import get_logger
from data.yfinance_fetcher import fetch_yfinance_ohlcv
from data.cleaner import clean_ohlcv, validate_ohlcv, detect_anomalies, normalize_price_data
from data.storage import init_db, upsert_candles, get_db_stats

logger = get_logger("fetch_stock_forex_history")

ALL_SYMBOLS = STOCK_TICKERS + FOREX_TICKERS
GRANULARITY = "1h"
DAYS_BACK   = YFINANCE_MAX_DAYS_1H   # 730 days


def main():
    print("\n" + "=" * 65)
    print("  ZAERYN — yfinance Stock & Forex History Backfill")
    print(f"  Stocks: {', '.join(STOCK_TICKERS)}")
    print(f"  Forex:  {', '.join(FOREX_TICKERS)}")
    print(f"  Target: {DAYS_BACK} days per asset (1h candles)")
    print(f"  Total:  {len(ALL_SYMBOLS)} assets")
    print("=" * 65 + "\n")

    conn         = init_db()
    stats_before = get_db_stats(conn)
    total_added  = 0
    results      = {}

    for i, symbol in enumerate(ALL_SYMBOLS, 1):
        asset_type = "STOCK" if symbol in STOCK_TICKERS else "FOREX"
        print(f"  [{i:>2}/{len(ALL_SYMBOLS)}] {symbol:<10} ({asset_type})")
        t0 = time.time()

        raw = fetch_yfinance_ohlcv(symbol, granularity=GRANULARITY, days_back=DAYS_BACK)

        if raw is None or raw.empty:
            print(f"  ✗ No data returned\n")
            results[symbol] = "no data"
            continue

        # gap_fill=False: don't forward-fill overnight/weekend gaps in stock/forex data
        cleaned = clean_ohlcv(raw, gap_fill=False)

        # Drop any remaining NaN rows before validation (gap_fill=False leaves them)
        cleaned = cleaned.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

        if cleaned.empty:
            print(f"  ✗ Empty after cleaning\n")
            results[symbol] = "empty after clean"
            continue

        is_valid, errors = validate_ohlcv(cleaned)
        if not is_valid:
            print(f"  ✗ Validation failed: {errors}\n")
            results[symbol] = f"invalid: {errors}"
            continue

        cleaned   = detect_anomalies(cleaned)
        cleaned   = normalize_price_data(cleaned)
        anomalies = int(cleaned["is_anomaly"].sum()) if "is_anomaly" in cleaned.columns else 0

        written = upsert_candles(symbol, GRANULARITY, cleaned, conn)
        total_added += written

        elapsed  = round(time.time() - t0, 1)
        earliest = cleaned["timestamp"].min().strftime("%Y-%m-%d")
        latest   = cleaned["timestamp"].max().strftime("%Y-%m-%d")

        print(f"  ✓ {written:,} candles | {earliest} → {latest} | "
              f"{anomalies} anomalies | {elapsed}s\n")
        results[symbol] = written

    stats_after = get_db_stats(conn)
    conn.close()

    print("=" * 65)
    print(f"  {'SYMBOL':<12}  {'BEFORE':>8}  {'AFTER':>8}  {'ADDED':>8}  STATUS")
    print("  " + "-" * 58)

    for symbol in ALL_SYMBOLS:
        before = stats_before.get(symbol, {}).get(GRANULARITY, {}).get("count", 0)
        after  = stats_after.get(symbol,  {}).get(GRANULARITY, {}).get("count", 0)
        added  = after - before
        oldest = stats_after.get(symbol,  {}).get(GRANULARITY, {}).get("oldest", "")[:10]

        # Stocks trade ~6.5h/day × 5 days × 52 weeks ≈ 1690 candles/year
        # Forex trades ~24h/day × 5 days × 52 weeks ≈ 6240 candles/year
        min_threshold = 1000 if symbol in STOCK_TICKERS else 3000
        ready_threshold = min_threshold * 3

        if after >= ready_threshold:
            status = "✓ READY"
        elif after >= min_threshold:
            status = "△  LIMITED"
        else:
            status = "✗ INSUFFICIENT"

        print(f"  {symbol:<12}  {before:>8,}  {after:>8,}  {added:>+8,}  "
              f"{status}  [{oldest}]")

    print("=" * 65)
    print(f"\n  Total candles added: {total_added:,}")

    ready = [s for s in ALL_SYMBOLS
             if stats_after.get(s, {}).get(GRANULARITY, {}).get("count", 0) >= 1000]
    print(f"  Ready for training:  {ready}\n")

    print("  Next steps:")
    print("  python -X utf8 scripts/train_models.py --retrain   # retrain all 22 assets")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
