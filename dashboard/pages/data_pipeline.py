import streamlit as st
import pandas as pd
from dashboard.components.theme import (
    page_title, section_label, stat_block, chart_container,
    chart_container_close, COLORS, tag,
)
from dashboard.components.charts import candlestick_chart
from dashboard.data_loader import db_stats, candles
from config.settings import ALL_ASSETS, ASSET_SOURCE


def render():
    st.markdown(page_title(
        "DATA PIPELINE",
        "ETL — extract from Coinbase Exchange API + Birdeye API (Solana DEX) · "
        "transform + validate · load to SQLite"
    ), unsafe_allow_html=True)

    stats = db_stats()
    total = sum(v.get("1h", {}).get("count", 0) for v in stats.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(stat_block(f"{total:,}", "Total Candles"),       unsafe_allow_html=True)
    c2.markdown(stat_block("10",         "Assets Tracked"),      unsafe_allow_html=True)
    c3.markdown(stat_block("5",          "Coinbase Assets"),     unsafe_allow_html=True)
    c4.markdown(stat_block("5",          "Solana DEX Tokens"),   unsafe_allow_html=True)

    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

    # -- Asset inventory -------------------------------------------------------
    st.markdown(section_label("ASSET INVENTORY"), unsafe_allow_html=True)
    rows = []
    for asset in ALL_ASSETS:
        info  = stats.get(asset, {}).get("1h", {})
        count = info.get("count", 0)
        rows.append({
            "ASSET":   asset,
            "SOURCE":  ASSET_SOURCE.get(asset, "coinbase").upper(),
            "CANDLES": count,
            "FROM":    info.get("oldest", "—")[:10] if info.get("oldest") else "—",
            "TO":      info.get("newest", "—")[:10] if info.get("newest") else "—",
            "DAYS":    f"~{count // 24}d" if count else "—",
            "READY":   "✓" if count >= 300 else "✗",
        })
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"CANDLES": st.column_config.NumberColumn(format="%d")},
    )

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # -- Chart explorer --------------------------------------------------------
    st.markdown(section_label("PRICE HISTORY EXPLORER"), unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        asset_sel = st.selectbox(
            "ASSET",
            [a for a in ALL_ASSETS
             if stats.get(a, {}).get("1h", {}).get("count", 0) > 100],
        )
    with col2:
        days = st.select_slider("WINDOW", [7, 30, 60, 90, 180, 365], value=90)

    df = candles(asset_sel, days)
    if not df.empty:
        st.markdown(chart_container(), unsafe_allow_html=True)
        fig = candlestick_chart(df, asset_sel, show_sma=True, height=480)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(chart_container_close(), unsafe_allow_html=True)

        latest = df.iloc[-1]
        pct    = (float(latest["close"]) / float(df.iloc[0]["close"]) - 1) * 100
        vol    = float(df["close"].pct_change().std() * (8760 ** 0.5) * 100)

        c = st.columns(5)
        c[0].markdown(stat_block(f"${float(latest['close']):,.2f}", "Current Price"),    unsafe_allow_html=True)
        c[1].markdown(stat_block(f"{pct:+.2f}%",                    "Period Return"),    unsafe_allow_html=True)
        c[2].markdown(stat_block(f"{vol:.1f}%",                     "Ann. Volatility"),  unsafe_allow_html=True)
        c[3].markdown(stat_block(f"${float(df['high'].max()):,.2f}", "Period High"),      unsafe_allow_html=True)
        c[4].markdown(stat_block(f"${float(df['low'].min()):,.2f}",  "Period Low"),       unsafe_allow_html=True)

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    # -- ETL stages ------------------------------------------------------------
    st.markdown(section_label("PIPELINE STAGES"), unsafe_allow_html=True)
    st.markdown(f"""
    <div style="display:grid; grid-template-columns:repeat(3,1fr);
                gap:1px; background:#1E1E1E; border:1px solid #1E1E1E;">
        {"".join([
            f'''<div style="background:#000; padding:1.5rem;">
                <div style="font-family:'Bebas Neue',sans-serif; font-size:2rem;
                            color:#FF2D00; margin-bottom:0.25rem;
                            text-shadow:0 0 20px rgba(255,61,0,0.27);">{num}</div>
                <div style="font-family:'Bebas Neue',sans-serif; font-size:1.2rem;
                            letter-spacing:0.08em; color:#F5F5F5;
                            margin-bottom:0.75rem;">{title}</div>
                <div style="font-family:'Space Mono',monospace; font-size:0.7rem;
                            color:#444; line-height:1.9; text-transform:uppercase;
                            letter-spacing:0.05em;">{body}</div>
            </div>'''
            for num, title, body in [
                ("01", "EXTRACT",
                 "Coinbase Exchange API<br>Birdeye API (Solana DEX)<br>"
                 "Chunked requests · 1.1s rate limit<br>Exponential backoff retry (3x)"),
                ("02", "TRANSFORM",
                 "clean_ohlcv() — dedupe, sort, ffill<br>"
                 "detect_anomalies() — flag >20% jumps<br>"
                 "normalize_price_data() — returns, log ret<br>"
                 "Validate high >= low, prices > 0"),
                ("03", "LOAD",
                 "SQLite — zaeryn.db<br>"
                 "UNIQUE(asset, granularity, timestamp)<br>"
                 "INSERT OR REPLACE upsert pattern<br>"
                 "Index on (asset, gran, timestamp)"),
            ]
        ])}
    </div>
    """, unsafe_allow_html=True)
