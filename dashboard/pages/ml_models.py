import os

import joblib
import pandas as pd
import streamlit as st

from config.settings import ALL_ASSETS, FEATURE_COLUMNS
from dashboard.components.charts import feature_importance, model_performance_bars
from dashboard.components.theme import (
    chart_container,
    chart_container_close,
    page_title,
    section_label,
    stat_block,
)
from dashboard.data_loader import feature_importances, model_health_all
from models.trend import TrendClassifier
from models.volatility import VolatilityPredictor


def render():
    st.markdown(
        page_title(
            "ML MODELS",
            "XGBoost volatility predictor + Random Forest trend classifier · "
            "29 engineered features · 2-year training · recency-weighted",
        ),
        unsafe_allow_html=True,
    )

    health = model_health_all()
    trained = [a for a in ALL_ASSETS if health.get(a, {}).get("models_exist")]

    # Compute live stats from loaded models
    _r2_vals = [
        joblib.load(VolatilityPredictor.model_path(a)).get("r2")
        for a in ALL_ASSETS
        if os.path.exists(VolatilityPredictor.model_path(a))
    ]
    _r2_vals = [v for v in _r2_vals if v is not None]
    best_r2 = f"{max(_r2_vals):.2f}" if _r2_vals else "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(stat_block(f"{len(trained)}/10", "Models Active"), unsafe_allow_html=True)
    c2.markdown(stat_block(str(len(FEATURE_COLUMNS)), "Features"), unsafe_allow_html=True)
    c3.markdown(stat_block(best_r2, "Best R²", accent=True), unsafe_allow_html=True)
    c4.markdown(stat_block("2 YRS", "Training Data"), unsafe_allow_html=True)

    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

    # -- Metrics table ---------------------------------------------------------
    st.markdown(section_label("TRAINING METRICS"), unsafe_allow_html=True)
    rows = []
    for asset in ALL_ASSETS:
        vp = VolatilityPredictor.model_path(asset)
        tp = TrendClassifier.model_path(asset)
        if os.path.exists(vp) and os.path.exists(tp):
            try:
                vd = joblib.load(vp)
                td = joblib.load(tp)
                rows.append(
                    {
                        "ASSET": asset,
                        "VOL MAE": round(vd.get("mae", 0), 4) if vd.get("mae") is not None else "—",
                        "VOL R²": round(vd.get("r2", 0), 4) if vd.get("r2") is not None else "—",
                        "TREND AUC": round(td.get("auc", 0), 4)
                        if td.get("auc") is not None
                        else "—",
                        "TREND F1": round(td.get("f1", 0), 4) if td.get("f1") is not None else "—",
                        "TRAIN ROWS": vd.get("train_rows", "—"),
                        "STATUS": "ACTIVE",
                    }
                )
            except Exception:
                rows.append({"ASSET": asset, "STATUS": "ERROR"})
        else:
            rows.append({"ASSET": asset, "STATUS": "NO MODEL"})

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # -- Performance chart -----------------------------------------------------
    active_rows = [r for r in rows if "VOL R²" in r and isinstance(r.get("VOL R²"), float)]
    if active_rows:
        st.markdown(section_label("PERFORMANCE BY ASSET"), unsafe_allow_html=True)
        st.markdown(chart_container(), unsafe_allow_html=True)
        fig = model_performance_bars(
            [r["ASSET"] for r in active_rows],
            [r["VOL R²"] for r in active_rows],
            [r["TREND AUC"] if isinstance(r.get("TREND AUC"), float) else 0.0 for r in active_rows],
            height=360,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(chart_container_close(), unsafe_allow_html=True)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    # -- Feature importance + live predictions ---------------------------------
    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown(section_label("FEATURE IMPORTANCE"), unsafe_allow_html=True)
        asset_sel = st.selectbox("SELECT ASSET", trained or ALL_ASSETS[:1])
        imps = feature_importances(asset_sel)
        if imps:
            st.markdown(chart_container(), unsafe_allow_html=True)
            fig2 = feature_importance(list(imps.keys()), list(imps.values()), height=440)
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
            st.markdown(chart_container_close(), unsafe_allow_html=True)
        else:
            st.info("Feature importance not available for this asset.")

    with col2:
        st.markdown(section_label("LIVE PREDICTIONS"), unsafe_allow_html=True)
        if trained:
            st.markdown(
                f"""
            <div style="border:1px solid #1E1E1E; border-top:2px solid #FF2D00;">
                {
                    "".join(
                        [
                            f'''<div style="padding:0.9rem 1.1rem; border-bottom:1px solid #161616;
                            display:flex; justify-content:space-between; align-items:center;">
                        <div style="font-family:'Bebas Neue',sans-serif; font-size:1.1rem;
                                    letter-spacing:0.08em; color:#F5F5F5;">{asset}</div>
                        <div style="text-align:right;">
                            <div style="font-family:'Space Mono',monospace; font-size:0.7rem; color:#555;">
                                VOL <span style="color:#FF3D00;">
                                {
                                f"{health.get(asset, {}).get('volatility_prediction', 0):.3f}"
                                if health.get(asset, {}).get("models_exist")
                                else "—"
                            }</span>
                            </div>
                            <div style="font-family:'Space Mono',monospace; font-size:0.7rem;
                                        color:{
                                "#F5F5F5"
                                if (health.get(asset, {}).get("trend") or {}).get("direction")
                                == "UP"
                                else "#FF2D00"
                                if (health.get(asset, {}).get("trend") or {}).get("direction")
                                == "DOWN"
                                else "#444"
                            };">
                                {(health.get(asset, {}).get("trend") or {}).get("direction", "—")}
                                ({
                                (health.get(asset, {}).get("trend") or {}).get(
                                    "confidence", 0
                                ):.2f})
                            </div>
                        </div>
                    </div>'''
                            for asset in trained
                        ]
                    )
                }
            </div>
            """,
                unsafe_allow_html=True,
            )
        else:
            st.info("No trained models found.")

        # Feature categories
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        st.markdown(section_label("FEATURE CATEGORIES"), unsafe_allow_html=True)
        st.markdown(
            f"""
        <div style="border:1px solid #1E1E1E;">
            {
                "".join(
                    [
                        f'''<div style="padding:0.75rem 1rem; border-bottom:1px solid #161616;
                        display:flex; justify-content:space-between;">
                    <div style="font-family:'Space Mono',monospace; font-size:0.65rem;
                                color:#888; text-transform:uppercase;">{cat}</div>
                    <div style="font-family:'Space Mono',monospace; font-size:0.65rem;
                                color:#FF3D00;">{count}</div>
                </div>'''
                        for cat, count in [
                            ("Trend", "7 features"),
                            ("Momentum", "4 features"),
                            ("Volatility", "5 features"),
                            ("Volume", "4 features"),
                            ("Time / Regime", "9 features"),
                            ("TOTAL", f"{len(FEATURE_COLUMNS)} features"),
                        ]
                    ]
                )
            }
        </div>
        """,
            unsafe_allow_html=True,
        )
