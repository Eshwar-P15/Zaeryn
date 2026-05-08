import os
import sys
import json
import glob as _glob

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import ALL_ASSETS, BACKTEST_REPORTS_DIR, MODEL_SAVE_DIR
from data.storage import init_db, load_candles, get_db_stats, load_price_snapshots


@st.cache_data(ttl=300)
def db_stats() -> dict:
    conn = init_db()
    s    = get_db_stats(conn)
    conn.close()
    return s


@st.cache_data(ttl=300)
def candles(asset: str, days: int = 90) -> pd.DataFrame:
    conn = init_db()
    df   = load_candles(asset, "1h", days_back=days, conn=conn)
    conn.close()
    return df


@st.cache_data(ttl=1800)
def model_health_all() -> dict:
    from models.trainer import evaluate_model_health
    return {a: evaluate_model_health(a) for a in ALL_ASSETS}


@st.cache_data(ttl=300)
def sentiment_all() -> dict:
    """Load latest cached sentiment, ignoring TTL expiry so stale data still shows."""
    from pathlib import Path
    from config.settings import CACHE_DIR
    result = {}
    for a in ALL_ASSETS:
        safe = a.replace("-", "_").replace("/", "_")
        path = Path(CACHE_DIR) / f"sentiment_{safe}.json"
        if path.exists():
            try:
                import json as _json
                with open(path) as f:
                    entry = _json.load(f)
                data = entry.get("data", entry)
                if data:
                    result[a] = data
            except Exception:
                pass
    return result


@st.cache_data(ttl=300)
def fear_greed() -> dict:
    from sentiment.fear_greed import fetch_fear_greed
    try:
        return fetch_fear_greed()
    except Exception:
        return {"value": 50, "label": "Neutral", "normalized": 0.0}


@st.cache_data(ttl=3600)
def backtest_reports() -> list:
    reports = []
    pattern = os.path.join(BACKTEST_REPORTS_DIR, "*.json")
    for fp in sorted(_glob.glob(pattern)):
        try:
            with open(fp) as f:
                reports.append(json.load(f))
        except Exception:
            continue
    return reports


@st.cache_data(ttl=3600)
def strategy_comparison() -> pd.DataFrame:
    seen = {}
    for r in backtest_reports():
        m = r.get("metadata", {})
        if not m:
            continue
        key = (m.get("strategy", ""), m.get("asset", ""))
        seen[key] = {
            "Strategy":      m.get("strategy", ""),
            "Asset":         m.get("asset", ""),
            "Return %":      m.get("total_return_pct", 0),
            "Ann Return %":  m.get("annualized_return_pct", 0),
            "Sharpe":        m.get("sharpe_ratio", 0),
            "Sortino":       m.get("sortino_ratio", 0),
            "Max DD %":      m.get("max_drawdown_pct", 0),
            "Win Rate %":    m.get("win_rate_pct", 0),
            "Trades":        m.get("total_trades", 0),
            "Profit Factor": m.get("profit_factor", 0),
            "W/L Ratio":     m.get("win_loss_ratio", 1.5),
        }
    if not seen:
        return pd.DataFrame()
    return (
        pd.DataFrame(list(seen.values()))
        .sort_values("Sharpe", ascending=False)
        .reset_index(drop=True)
    )


@st.cache_data(ttl=3600)
def equity_curves_for(asset: str) -> dict:
    curves = {}
    for r in backtest_reports():
        m, res = r.get("metadata", {}), r.get("result", {})
        if m.get("asset") == asset:
            eq = res.get("equity_curve", [])
            ts = res.get("timestamps", [])
            if eq and ts:
                strat = m.get("strategy", "")
                curves[strat] = {"equity": eq, "timestamps": ts}
    return curves


@st.cache_data(ttl=3600)
def feature_importances(asset: str) -> dict:
    import joblib
    from models.volatility import VolatilityPredictor
    path = VolatilityPredictor.model_path(asset)
    if not os.path.exists(path):
        return {}
    try:
        return joblib.load(path).get("feature_importances", {})
    except Exception:
        return {}
