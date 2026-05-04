import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config.settings import ALL_ASSETS, MAX_POSITION_PCT
from utils.logger import get_logger
from data.storage import init_db, load_candles, get_db_stats
from risk.scorer import compute_risk_score, score_all_assets
from risk.position_sizer import full_position_plan
from risk.alerts import check_all_assets

logger = get_logger("risk_report")

PORTFOLIO_VALUE = 10_000.0


def main():
    print("\n" + "="*75)
    print("  ZAERYN — Phase 4 Risk Engine Validation")
    print("="*75 + "\n")

    conn  = init_db()
    stats = get_db_stats(conn)

    if not stats:
        print("ERROR: No data in DB — run scripts/fetch_history.py first")
        sys.exit(1)

    total_candles = sum(
        v.get("1h", {}).get("count", 0) for v in stats.values()
    )
    print(f"[ DB ] {total_candles:,} total candles across {len(stats)} assets\n")

    print("Computing risk scores for all assets...\n")
    results = score_all_assets(conn=conn)

    # Risk table
    print("="*80)
    print(f"  {'Asset':<12} {'Score':>6}  {'Label':<10}  {'Recommend':<8}  "
          f"{'ML':>4}  {'Vol Risk':>9}  {'Sent Risk':>10}  {'RSI':>6}")
    print("  " + "-"*77)

    for asset in ALL_ASSETS:
        r = results.get(asset)
        if r is None:
            print(f"  {asset:<12} {'ERROR':>6}")
            continue

        comps  = r.get("components", {})
        vol_r  = comps.get("volatility", {}).get("risk")
        sent_r = comps.get("sentiment",  {}).get("risk")
        rsi    = comps.get("price_momentum", {}).get("rsi")
        ml_ok  = "✓" if r.get("models_available") else "✗"

        vol_s  = f"{vol_r:.3f}"  if vol_r  is not None else "   N/A"
        sent_s = f"{sent_r:.3f}" if sent_r is not None else "    N/A"
        rsi_s  = f"{rsi:.1f}"   if rsi    is not None else "   N/A"

        print(
            f"  {asset:<12} {r['score']:>6.1f}  {r['label']:<10}  "
            f"{r['recommendation']:<8}  {ml_ok:>4}  {vol_s:>9}  "
            f"{sent_s:>10}  {rsi_s:>6}"
        )

    print("="*80 + "\n")

    # Position sizing table
    print(f"Position sizing (portfolio = ${PORTFOLIO_VALUE:,.0f}):\n")
    print(f"  {'Asset':<12} {'Pos %':>7}  {'Pos $':>10}  "
          f"{'Entry':>12}  {'Stop Loss':>12}  {'Take Profit':>12}")
    print("  " + "-"*75)

    for asset in ALL_ASSETS:
        r = results.get(asset)
        if r is None:
            continue

        candles = load_candles(asset, "1h", days_back=5, conn=conn)
        plan    = full_position_plan(asset, r, PORTFOLIO_VALUE, candles)
        pos     = plan["position"]

        pos_pct = f"{pos['position_pct']*100:.2f}%"
        pos_usd = f"${pos['position_usd']:.2f}"
        entry_s = f"${plan['entry_price']:.4f}" if plan['entry_price'] else "N/A"
        sl_s    = f"${plan['stop_loss']:.4f}"   if plan['stop_loss']   else "N/A"
        tp_s    = f"${plan['take_profit']:.4f}" if plan['take_profit'] else "N/A"

        print(
            f"  {asset:<12} {pos_pct:>7}  {pos_usd:>10}  "
            f"{entry_s:>12}  {sl_s:>12}  {tp_s:>12}"
        )
        print(f"    └─ {pos['rationale']}")

    print()

    # Alert check
    print("Alert check:\n")
    candles_map = {
        asset: load_candles(asset, "1h", days_back=5, conn=conn)
        for asset in ALL_ASSETS
    }
    all_alerts = check_all_assets(results, candles_map=candles_map)

    total_alerts = sum(len(v) for v in all_alerts.values())
    if total_alerts == 0:
        print("  ✓ No alerts triggered\n")
    else:
        print(f"  ⚠  {total_alerts} alerts triggered:\n")
        for asset, alerts in all_alerts.items():
            for alert in alerts:
                print(f"  {alert}")
        print()

    conn.close()

    print("="*75)
    print("  ✓ Phase 4 validation complete!")
    print("  Commit: git add . && git commit -m 'v0.4.0-risk-engine'")
    print("="*75 + "\n")


if __name__ == "__main__":
    main()
