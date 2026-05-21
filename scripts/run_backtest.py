import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics
from backtest.reporter import compare_strategies, print_comparison_table, save_report
from backtest.strategies import (
    BollingerBandStrategy,
    MACDCrossStrategy,
    RSIMeanReversionStrategy,
    ZAERYNMLStrategy,
)
from config.settings import ALL_ASSETS, BACKTEST_DAYS, BACKTEST_REPORTS_DIR
from data.storage import get_db_stats, init_db
from utils.logger import get_logger

logger = get_logger("run_backtest")

target_asset = sys.argv[1] if len(sys.argv) > 1 else None
target_strategy = sys.argv[2] if len(sys.argv) > 2 else None


def build_strategies(asset: str) -> list:
    all_strats = {
        "MACD": MACDCrossStrategy(),
        "RSI": RSIMeanReversionStrategy(),
        "BB": BollingerBandStrategy(),
        "ZAERYN": ZAERYNMLStrategy(asset),
    }
    if target_strategy:
        key = target_strategy.upper()
        if key in all_strats:
            return [all_strats[key]]
        else:
            print(f"Unknown strategy '{target_strategy}'. Options: {list(all_strats.keys())}")
            sys.exit(1)
    return list(all_strats.values())


def main():
    print("\n" + "=" * 70)
    print("  ZAERYN — Phase 5 Backtesting")
    print(f"  Window:   {BACKTEST_DAYS} days")
    print(f"  Assets:   {target_asset or 'all'}")
    print(f"  Strategy: {target_strategy or 'all 4'}")
    print("=" * 70 + "\n")

    os.makedirs(BACKTEST_REPORTS_DIR, exist_ok=True)

    conn = init_db()
    stats = get_db_stats(conn)
    if not stats:
        print("ERROR: No candles in DB. Run scripts/fetch_history.py first.")
        sys.exit(1)

    total_candles = sum(v.get("1h", {}).get("count", 0) for v in stats.values())
    print(f"DB: {total_candles:,} total 1h candles across {len(stats)} assets\n")

    assets = [target_asset] if target_asset else ALL_ASSETS
    all_results = []

    for asset in assets:
        if asset not in stats:
            print(f"⚠  {asset}: no data in DB — skipping\n")
            continue

        candle_count = stats[asset].get("1h", {}).get("count", 0)
        if candle_count < 100:
            print(f"⚠  {asset}: only {candle_count} candles — skipping\n")
            continue

        print(f"{'─' * 60}")
        print(f"  Asset: {asset} ({candle_count:,} candles)")
        print(f"{'─' * 60}")

        strategies = build_strategies(asset)

        for strat in strategies:
            try:
                engine = BacktestEngine(strategy=strat)
                result = engine.run(asset, days_back=BACKTEST_DAYS, conn=conn)
                m = compute_metrics(result)

                print(
                    f"  {strat.name:<25} "
                    f"return={m['total_return_pct']:>+7.2f}%  "
                    f"trades={m['total_trades']:>4}  "
                    f"sharpe={m['sharpe_ratio']:>7.4f}  "
                    f"dd={m['max_drawdown_pct']:>6.2f}%  "
                    f"wr={m['win_rate_pct']:>5.1f}%"
                )

                if "warning" in m:
                    print(f"    ⚠  {m['warning'][:60]}")

                save_report(result, m)
                all_results.append((result, m))

            except Exception as e:
                print(f"  {strat.name:<25} ERROR: {e}")
                logger.exception(f"Backtest failed: {strat.name} on {asset}")

        print()

    conn.close()

    if len(all_results) > 1:
        print("\n" + "=" * 70)
        print("  Strategy Comparison (sorted by Sharpe ratio)")
        print("=" * 70 + "\n")

        comparison = compare_strategies(all_results)
        print_comparison_table(comparison)

        if not comparison.empty:
            best = comparison.iloc[0]
            print(f"\n  ✓ Best strategy: {best['Strategy']} on {best['Asset']}")
            print(
                f"    Sharpe={best['Sharpe']:.4f}  Return={best['Return %']:.2f}%  DD={best['Max DD %']:.2f}%"
            )

    zaeryn_results = [(r, m) for r, m in all_results if "ZAERYN" in m["strategy"]]
    if zaeryn_results:
        wl_ratios = [m["win_loss_ratio"] for _, m in zaeryn_results]
        avg_wl = sum(wl_ratios) / len(wl_ratios)
        print(f"\n  📊 ZAERYN ML avg win/loss ratio: {avg_wl:.3f}")
        print(f"  Recommendation: update KELLY_WIN_LOSS_RATIO = {avg_wl:.2f} in config/settings.py")

    print(f"\n  Reports saved to: {BACKTEST_REPORTS_DIR}/")
    print("  Commit: git add . && git commit -m 'v0.5.0-backtesting'")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
