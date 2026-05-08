"""
Train models ONLY for DEX tokens (BONK, WIF, PYTH, RAY) on 730 days.
Do NOT retrain Coinbase assets or JUP.
"""
from dotenv import load_dotenv
load_dotenv()

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.trainer import train_all_models

DEX_ASSETS = ["BONK", "WIF", "PYTH", "RAY"]
DAYS_BACK  = 730

print(f"Training DEX models: {DEX_ASSETS} | days_back={DAYS_BACK}")
print("=" * 60)

results = train_all_models(
    assets=DEX_ASSETS,
    days_back=DAYS_BACK,
    force_retrain=True,
)

print("\n" + "=" * 60)
print(f"{'ASSET':<10} {'VOL MAE':>10} {'VOL R²':>10} {'TREND AUC':>12} {'TREND F1':>10} {'ROWS':>8}")
print("-" * 60)
for asset in DEX_ASSETS:
    r   = results.get(asset, {})
    vol = r.get("volatility", {})
    trn = r.get("trend", {})
    if vol.get("skipped") or vol.get("failed"):
        status = vol.get("reason") or vol.get("error") or "FAILED"
        print(f"{asset:<10} {status}")
        continue
    mae = f"{vol.get('mae', 0):.4f}" if vol.get("mae") is not None else "—"
    r2  = f"{vol.get('r2',  0):.4f}" if vol.get("r2")  is not None else "—"
    auc = f"{trn.get('auc', 0):.4f}" if trn.get("auc") is not None else "—"
    f1  = f"{trn.get('f1',  0):.4f}" if trn.get("f1")  is not None else "—"
    rows = vol.get("train_rows", "—")
    print(f"{asset:<10} {mae:>10} {r2:>10} {auc:>12} {f1:>10} {rows:>8}")
print("=" * 60)
print("Done. BONK/WIF/PYTH/RAY models saved to models/saved/")
