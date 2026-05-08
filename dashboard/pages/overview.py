import streamlit as st
import pandas as pd
from dashboard.components.theme import (
    page_title, stat_block, section_label, COLORS,
    chart_container, chart_container_close,
)
from dashboard.components.charts import equity_curves, sharpe_bar, scatter_risk_return
from dashboard.data_loader import strategy_comparison, equity_curves_for, candles, db_stats
from config.settings import FEATURE_COLUMNS


def render():
    st.markdown(page_title(
        "ZAERYN",
        "AI-powered cryptocurrency trading — data pipeline / sentiment analysis / machine learning / backtesting"
    ), unsafe_allow_html=True)

    df = strategy_comparison()

    # -- Key finding banner (live values) -------------------------------------
    _btc_zaeryn = df[(df["Strategy"].str.contains("ZAERYN", na=False)) & (df["Asset"] == "BTC-USD")]
    _btc_macd   = df[(df["Strategy"] == "MACD Cross") & (df["Asset"] == "BTC-USD")]
    _kf_sharpe  = f"{_btc_zaeryn['Sharpe'].iloc[0]:.2f}" if not _btc_zaeryn.empty else "—"
    _kf_macd    = f"{_btc_macd['Sharpe'].iloc[0]:.2f}"   if not _btc_macd.empty   else "—"
    _kf_wr      = f"{_btc_zaeryn['Win Rate %'].iloc[0]:.0f}%" if not _btc_zaeryn.empty else "—"
    _kf_dd      = f"{_btc_zaeryn['Max DD %'].iloc[0]:.2f}%"   if not _btc_zaeryn.empty else "—"

    st.markdown(f"""
    <div style="background:linear-gradient(90deg,#0D0000 0%,#000 100%);border:1px solid #1E1E1E;border-left:4px solid #FF2D00;padding:1.25rem 1.75rem;margin-bottom:2rem;display:flex;align-items:center;gap:2rem;">
        <div style="font-family:'Space Mono',monospace;font-size:0.65rem;color:#FF3D00;text-transform:uppercase;letter-spacing:0.2em;white-space:nowrap;">KEY FINDING</div>
        <div style="font-family:'Space Grotesk',sans-serif;font-size:0.95rem;color:#888;line-height:1.5;flex:1;">
            ZAERYN ML Composite achieves a Sharpe ratio of
            <span style="color:#F5F5F5;font-weight:600;">{_kf_sharpe}</span>
            on BTC-USD vs
            <span style="color:#FF2D00;">{_kf_macd}</span> for MACD Cross —
            with <span style="color:#F5F5F5;">{_kf_wr} win rate</span>
            and <span style="color:#F5F5F5;">{_kf_dd} max drawdown</span>
            over the 90-day test window.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # -- Hero stats -----------------------------------------------------------
    zaeryn_df = df[df["Strategy"].str.contains("ZAERYN", na=False)] if not df.empty else pd.DataFrame()
    z_active  = zaeryn_df[zaeryn_df["Trades"] >= 5] if not zaeryn_df.empty else pd.DataFrame()

    z_sharpe   = f"{z_active['Sharpe'].mean():.2f}"      if not z_active.empty  else "—"
    z_winrate  = f"{zaeryn_df['Win Rate %'].max():.0f}%"  if not zaeryn_df.empty else "—"
    z_dd       = f"{z_active['Max DD %'].min():.2f}%"    if not z_active.empty  else "—"

    _stats         = db_stats()
    _total_candles = sum(v.get("1h", {}).get("count", 0) for v in _stats.values())

    st.markdown(section_label("PERFORMANCE SUMMARY"), unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(stat_block(z_sharpe,                "Avg Sharpe",       accent=True),  unsafe_allow_html=True)
    c2.markdown(stat_block(z_winrate,               "Best Win Rate",     accent=False), unsafe_allow_html=True)
    c3.markdown(stat_block(z_dd,                    "Min Drawdown",      accent=False), unsafe_allow_html=True)
    c4.markdown(stat_block(str(len(FEATURE_COLUMNS)), "Features",        accent=False), unsafe_allow_html=True)
    c5.markdown(stat_block(f"{_total_candles:,}",   "Candles Processed", accent=False), unsafe_allow_html=True)

    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

    # -- Equity curves --------------------------------------------------------
    st.markdown(section_label("EQUITY CURVE COMPARISON — BTC-USD"), unsafe_allow_html=True)
    st.markdown(chart_container("", "90 days · $10,000 starting capital · 4 strategies + buy & hold"), unsafe_allow_html=True)

    btc_curves = equity_curves_for("BTC-USD")
    if btc_curves:
        btc_c        = candles("BTC-USD", 90)
        curves_mapped = {k: v["equity"] for k, v in btc_curves.items()}
        if not btc_c.empty:
            init_p = float(btc_c["close"].iloc[0])
            n      = max(len(v) for v in curves_mapped.values())
            curves_mapped["Buy & Hold"] = [
                10000 * float(btc_c["close"].iloc[min(i, len(btc_c) - 1)]) / init_p
                for i in range(n)
            ]
        ts  = next(iter(btc_curves.values()))["timestamps"]
        fig = equity_curves(curves_mapped, ts, height=460)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.markdown("""
        <div style='padding:3rem;text-align:center;color:#333;
                    font-family:Space Mono,monospace;font-size:0.75rem;'>
            NO BACKTEST DATA — RUN python scripts/run_backtest.py
        </div>
        """, unsafe_allow_html=True)

    st.markdown(chart_container_close(), unsafe_allow_html=True)

    # -- Two column charts ----------------------------------------------------
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(section_label("SHARPE BY STRATEGY — BTC-USD"), unsafe_allow_html=True)
        st.markdown(chart_container(), unsafe_allow_html=True)
        if not df.empty:
            btc   = df[df["Asset"] == "BTC-USD"].copy()
            btc_c = candles("BTC-USD", 90)
            if not btc_c.empty:
                bah_ret = (float(btc_c["close"].iloc[-1]) /
                           float(btc_c["close"].iloc[0]) - 1) * 100
                btc = pd.concat([btc, pd.DataFrame([{
                    "Strategy": "Buy & Hold BTC",
                    "Sharpe":   bah_ret / 20,
                }])], ignore_index=True)
            fig2 = sharpe_bar(list(btc["Strategy"]), list(btc["Sharpe"]), height=380)
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        st.markdown(chart_container_close(), unsafe_allow_html=True)

    with col2:
        st.markdown(section_label("RISK vs RETURN — ALL STRATEGIES"), unsafe_allow_html=True)
        st.markdown(chart_container(), unsafe_allow_html=True)
        if not df.empty:
            valid = df[df["Trades"] >= 5]
            fig3  = scatter_risk_return(
                list(valid["Strategy"]),
                list(valid["Return %"]),
                list(valid["Sharpe"]),
                list(valid["Trades"]),
                height=380,
            )
            st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})
        st.markdown(chart_container_close(), unsafe_allow_html=True)

    # -- Architecture (live values) -------------------------------------------
    _best_r2    = "—"
    _best_sharpe = "—"
    try:
        import os, joblib
        from models.volatility import VolatilityPredictor
        from config.settings import ALL_ASSETS as _AA
        _r2s = [joblib.load(VolatilityPredictor.model_path(a)).get("r2")
                for a in _AA if os.path.exists(VolatilityPredictor.model_path(a))]
        _r2s = [v for v in _r2s if v is not None]
        if _r2s:
            _best_r2 = f"r²={max(_r2s):.2f}"
    except Exception:
        pass
    try:
        _zs = z_active["Sharpe"] if not z_active.empty else pd.Series(dtype=float)
        if not _zs.empty:
            _best_sharpe = f"sharpe {_zs.max():.1f}"
    except Exception:
        pass

    _candle_k = f"{_total_candles // 1000}k candles" if _total_candles else "—"

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.markdown(section_label("SYSTEM ARCHITECTURE"), unsafe_allow_html=True)
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:#1E1E1E;border:1px solid #1E1E1E;margin-bottom:2rem;">
        {"".join([
            f'<div style="background:#000;padding:1.5rem 1.25rem;"><div style="font-size:1.2rem;margin-bottom:0.75rem;opacity:0.6;">{icon}</div><div style="font-family:\'Bebas Neue\',sans-serif;font-size:1.1rem;letter-spacing:0.08em;color:#F5F5F5;margin-bottom:0.5rem;">{title}</div><div style="font-family:\'Space Mono\',monospace;font-size:0.65rem;color:#444;line-height:1.7;text-transform:uppercase;letter-spacing:0.06em;">{desc}</div></div>'
            for icon, title, desc in [
                ("⬡", "DATA PIPELINE",    f"10 assets<br>{_candle_k}<br>2 year history"),
                ("◈", "SENTIMENT ENGINE", "4 sources<br>news + dex<br>on-chain + f&g"),
                ("▲", "ML MODELS",        f"xgboost + rf<br>{_best_r2}<br>{len(FEATURE_COLUMNS)} features"),
                ("◎", "RISK ENGINE",      "5-component<br>kelly sizing<br>atr stops"),
                ("◣", "BACKTESTING",      f"walk-forward<br>4 strategies<br>{_best_sharpe}"),
            ]
        ])}
    </div>
    """, unsafe_allow_html=True)
