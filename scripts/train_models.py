import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config.settings import ALL_ASSETS, MODEL_HORIZON, MODEL_SAVE_DIR
from utils.logger import get_logger
from models.trainer import train_all_models, evaluate_model_health

logger = get_logger("train_models")
FORCE  = "--retrain" in sys.argv


def main():
    print("\n" + "="*70)
    print("  ZAERYN — Phase 3 Model Training")
    print(f"  Horizon:       {MODEL_HORIZON} candles ({MODEL_HORIZON}h ahead)")
    print(f"  Assets:        {len(ALL_ASSETS)}")
    print(f"  Force retrain: {FORCE}")
    print("="*70 + "\n")

    os.makedirs(MODEL_SAVE_DIR, exist_ok=True)

    results = train_all_models(
        assets=ALL_ASSETS,
        horizon=MODEL_HORIZON,
        days_back=730,
        force_retrain=FORCE,
    )

    # -- Metrics table ---------------------------------------------------------
    W = 95
    print("\n" + "="*W)
    print(f"  {'Asset':<12}  {'Vol MAE':>9}  {'Vol R²':>8}  {'Acc':>7}  "
          f"{'F1':>7}  {'AUC':>7}  Status")
    print("  " + "-"*(W-2))

    for asset in ALL_ASSETS:
        r     = results.get(asset, {})
        vol   = r.get("volatility", {})
        trend = r.get("trend", {})

        if vol.get("skipped") and trend.get("skipped"):
            status = "⚠  SKIPPED — insufficient data"
        elif vol.get("failed") or trend.get("failed"):
            status = "✗ FAILED — check logs"
        elif vol.get("loaded_from_disk"):
            status = "✓ loaded from disk"
        else:
            status = "✓ trained"

        mae_s = f"{vol['mae']:.4f}"         if "mae"      in vol   else "   N/A"
        r2_s  = f"{vol['r2']:.4f}"          if "r2"       in vol   else "   N/A"
        acc_s = f"{trend['accuracy']:.4f}"  if "accuracy" in trend else "  N/A"
        f1_s  = f"{trend['f1']:.4f}"        if "f1"       in trend else "  N/A"
        auc_s = f"{trend['auc']:.4f}"       if "auc"      in trend else "  N/A"

        print(f"  {asset:<12}  {mae_s:>9}  {r2_s:>8}  {acc_s:>7}  "
              f"{f1_s:>7}  {auc_s:>7}  {status}")

    print("="*W + "\n")

    # -- Live prediction health check ------------------------------------------
    print("Live prediction check (most recent candle in DB):\n")
    print(f"  {'Asset':<12}  {'Pred Vol':>10}  {'Direction':<12}  {'Confidence':>11}")
    print("  " + "-"*55)

    for asset in ALL_ASSETS:
        h     = evaluate_model_health(asset)
        vol   = h.get("volatility_prediction")
        trend = h.get("trend") or {}

        vol_s  = f"{vol:.4f}" if vol is not None else "        N/A"
        dir_s  = trend.get("direction", "N/A")
        conf_s = f"{trend['confidence']:.4f}" if "confidence" in trend else "        N/A"

        print(f"  {asset:<12}  {vol_s:>10}  {dir_s:<12}  {conf_s:>11}")

    # -- Final summary ---------------------------------------------------------
    trained = sum(
        1 for r in results.values()
        if "mae" in r.get("volatility", {})
        or r.get("volatility", {}).get("loaded_from_disk")
    )

    print(f"\n{'='*70}")
    if trained == len(ALL_ASSETS):
        print(f"  ✓ All {trained}/{len(ALL_ASSETS)} assets have models")
        print(f"  Commit: git add . && git commit -m 'v0.3.0-ml-models'")
    else:
        skipped = len(ALL_ASSETS) - trained
        print(f"  ⚠  {trained}/{len(ALL_ASSETS)} trained | {skipped} skipped")
        print(f"  Skipped assets need more history — run fetch_history.py")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
