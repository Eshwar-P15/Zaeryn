import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config.settings import ALL_ASSETS, ASSET_SOURCE
from utils.logger import get_logger
from data.historical import fetch_candles
from data.cleaner import clean_ohlcv, validate_ohlcv, detect_anomalies, normalize_price_data
from data.storage import init_db, upsert_candles, get_db_stats

logger = get_logger("fetch_history")

FETCH_DAYS = 180


def main():
    print("\n" + "="*65)
    print("  ZAERYN — Historical Data Fetch (Phase 3 Pre-requisite)")
    print(f"  Target: {FETCH_DAYS} days of 1h candles for {len(ALL_ASSETS)} assets")
    print("="*65 + "\n")

    conn    = init_db()
    success = 0
    skipped = 0

    for i, asset in enumerate(ALL_ASSETS, 1):
        source = ASSET_SOURCE.get(asset, "coinbase")
        print(f"[{i}/{len(ALL_ASSETS)}] {asset} ({source})...")

        try:
            df = fetch_candles(asset, granularity="1h", days_back=FETCH_DAYS)

            if df is None or df.empty:
                print(f"  ✗ No data returned — skipping\n")
                skipped += 1
                continue

            cleaned          = clean_ohlcv(df)
            is_valid, errors = validate_ohlcv(cleaned)

            if not is_valid:
                print(f"  ✗ Validation failed: {errors}\n")
                skipped += 1
                continue

            cleaned   = detect_anomalies(cleaned)
            cleaned   = normalize_price_data(cleaned)
            written   = upsert_candles(asset, "1h", cleaned, conn)
            anomalies = int(cleaned["is_anomaly"].sum())

            print(f"  ✓ {written} rows stored | {anomalies} anomalies flagged\n")
            success += 1

        except Exception as e:
            print(f"  ✗ Error: {e}\n")
            logger.exception(f"fetch_history failed for {asset}")
            skipped += 1

    print("="*65)
    print(f"  Done: {success}/{len(ALL_ASSETS)} assets fetched\n")

    stats = get_db_stats(conn)
    print(f"  {'Asset':<12} {'Gran':<6} {'Candles':>8}  {'From':<18}  {'To'}")
    print("  " + "-"*65)
    for asset in sorted(stats):
        for gran, info in stats[asset].items():
            flag = "✗  LOW" if info["count"] < 300 else "✓"
            print(
                f"  {flag} {asset:<10} {gran:<6} {info['count']:>8}  "
                f"{info['oldest']:<18}  {info['newest']}"
            )

    conn.close()
    print()
    if success == len(ALL_ASSETS):
        print("  ✓ All assets ready. Run: python scripts/train_models.py")
    else:
        print(f"  ⚠  {skipped} assets skipped. Check logs above.")
        print("  Assets with ✗ LOW candle count will be skipped during training.")
    print("="*65 + "\n")


if __name__ == "__main__":
    main()
