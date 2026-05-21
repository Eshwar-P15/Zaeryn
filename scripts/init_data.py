# LEGACY (Phase 1 validation script). Superseded by scripts/fetch_history.py +
# scripts/fetch_birdeye_history.py. Retained for archival reference only — do
# not rely on it for new pipeline work.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import ACTIVE_ASSETS
from data.cleaner import clean_ohlcv, detect_anomalies, normalize_price_data, validate_ohlcv
from data.historical import fetch_all_assets
from data.storage import get_db_stats, init_db, load_candles, upsert_candles
from utils.logger import get_logger

logger = get_logger("init_data")


def main():
    print("\n" + "=" * 60)
    print("  ZAERYN - Phase 1 Data Pipeline Validation")
    print("=" * 60 + "\n")

    print("[ 1 / 5 ] Initializing database...")
    conn = init_db()
    print("          OK Database ready\n")

    print("[ 2 / 5 ] Fetching 7 days of 1h candles for all assets...")
    print("          (This makes multiple API calls - ~30 seconds)\n")
    raw_data = fetch_all_assets(granularity="1h", days_back=7)

    if not raw_data:
        print("ERROR: No data returned from API. Check internet connection.")
        sys.exit(1)

    print(f"\n          OK Got data for {len(raw_data)}/{len(ACTIVE_ASSETS)} assets\n")

    print("[ 3 / 5 ] Cleaning, validating, and storing each asset...\n")
    for asset, df in raw_data.items():
        print(f"  {asset}:")
        print(f"    Raw rows:  {len(df)}")

        cleaned = clean_ohlcv(df)
        print(f"    Cleaned:   {len(cleaned)} rows")

        is_valid, errors = validate_ohlcv(cleaned)
        if not is_valid:
            print(f"    VALIDATION FAILED: {errors}")
            continue
        print("    Validated: OK")

        cleaned = detect_anomalies(cleaned)
        anomaly_count = cleaned["is_anomaly"].sum()
        print(f"    Anomalies: {anomaly_count}")

        cleaned = normalize_price_data(cleaned)

        written = upsert_candles(asset, "1h", cleaned, conn)
        print(f"    Stored:    {written} rows OK\n")

    print("[ 4 / 5 ] Loading BTC-USD from database (sanity check)...\n")
    btc = load_candles("BTC-USD", "1h", days_back=7, conn=conn)

    if btc.empty:
        print("ERROR: BTC-USD loaded empty - storage may have failed")
        sys.exit(1)

    print("  First 5 rows of BTC-USD:")
    print(
        btc[["timestamp", "open", "high", "low", "close", "volume"]].head().to_string(index=False)
    )
    print()

    print("[ 5 / 5 ] Database summary:\n")
    stats = get_db_stats(conn)

    if not stats:
        print("  No data in database - something went wrong")
        sys.exit(1)

    print(f"  {'Asset':<12} {'Granularity':<14} {'Candles':>8}  {'From':<18}  {'To'}")
    print("  " + "-" * 70)
    for asset in sorted(stats.keys()):
        for gran, info in sorted(stats[asset].items()):
            print(
                f"  {asset:<12} {gran:<14} {info['count']:>8}  {info['oldest']:<18}  {info['newest']}"
            )

    print()
    conn.close()

    print("=" * 60)
    print("  OK Phase 1 validation complete!")
    print("  Ready to commit: git add . && git commit -m 'v0.1.0-data-pipeline'")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
