import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import SOLANA_TOKENS
from data.cleaner import clean_ohlcv, detect_anomalies, normalize_price_data, validate_ohlcv
from data.dex_fetcher import fetch_all_dex_prices, fetch_token_info
from data.gecko_fetcher import fetch_dex_candles
from data.storage import get_db_stats, init_db, upsert_candles
from utils.logger import get_logger

logger = get_logger("init_dex_data")


def main():
    print("\n" + "=" * 65)
    print("  ZAERYN - Phase 1.5 DEX Data Pipeline Validation")
    print("=" * 65 + "\n")

    print("[ 1 / 5 ] Initializing database...")
    conn = init_db()
    print("          OK Database ready\n")

    print("[ 2 / 5 ] Fetching live DEX prices from DexScreener...\n")
    prices = fetch_all_dex_prices()

    if not prices:
        print("  ERROR: No DEX prices returned - check internet connection")
        sys.exit(1)

    print(f"\n  Got prices for {len(prices)}/{len(SOLANA_TOKENS)} tokens\n")

    print("[ 3 / 5 ] Fetching token metadata...\n")
    for symbol in SOLANA_TOKENS:
        info = fetch_token_info(symbol)
        if info:
            status = "WARN" if info["below_threshold"] else "OK  "
            print(
                f"  {status} {symbol:<8} "
                f"${info['price_usd']:.6f}  "
                f"liq=${info['liquidity_usd']:>12,.0f}  "
                f"vol24h=${info['volume_24h']:>12,.0f}  "
                f"DEX: {info['dex']}"
            )
        else:
            print(f"  FAIL {symbol:<8} - failed to fetch")

    print("\n[ 4 / 5 ] Fetching 7 days of 1h OHLCV candles for all tokens...")
    print("          (Multiple API calls - may take 30-60 seconds)\n")

    success_count = 0
    for symbol in SOLANA_TOKENS:
        print(f"  {symbol}...")
        try:
            df = fetch_dex_candles(symbol, granularity="1h", days_back=7)

            if df.empty:
                print("    FAIL No data returned\n")
                continue

            cleaned = clean_ohlcv(df)
            is_valid, errors = validate_ohlcv(cleaned)

            if not is_valid:
                print(f"    FAIL Validation failed: {errors}\n")
                continue

            cleaned = detect_anomalies(cleaned)
            cleaned = normalize_price_data(cleaned)

            written = upsert_candles(symbol, "1h", cleaned, conn)
            anomaly_count = cleaned["is_anomaly"].sum()

            print(
                f"    OK  {len(cleaned)} candles  |  {anomaly_count} anomalies  |  {written} rows stored\n"
            )
            success_count += 1

        except Exception as e:
            print(f"    FAIL Error: {e}\n")

    print(f"[ 5 / 5 ] Database summary ({success_count}/{len(SOLANA_TOKENS)} DEX tokens stored):\n")
    stats = get_db_stats(conn)

    dex_stats = {a: s for a, s in stats.items() if a in SOLANA_TOKENS}

    if not dex_stats:
        print("  No DEX data in database")
        sys.exit(1)

    print(f"  {'Token':<10} {'Gran':<8} {'Candles':>8}  {'From':<18}  {'To'}")
    print("  " + "-" * 65)
    for asset in sorted(dex_stats.keys()):
        for gran, info in sorted(dex_stats[asset].items()):
            print(
                f"  {asset:<10} {gran:<8} {info['count']:>8}  {info['oldest']:<18}  {info['newest']}"
            )

    conn.close()

    print()
    print("=" * 65)
    if success_count == len(SOLANA_TOKENS):
        print("  OK All DEX tokens loaded successfully!")
    else:
        print(f"  WARN {success_count}/{len(SOLANA_TOKENS)} tokens loaded - check logs above")
    print("  Ready to commit: git add . && git commit -m 'v0.1.5-dex-integration'")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
