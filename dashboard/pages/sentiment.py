import plotly.graph_objects as go
import streamlit as st

from dashboard.components.charts import sentiment_bars
from dashboard.components.theme import (
    COLORS,
    chart_container,
    chart_container_close,
    page_title,
    section_label,
    stat_block,
)
from dashboard.data_loader import fear_greed, sentiment_all


def render():
    st.markdown(
        page_title(
            "SENTIMENT ENGINE",
            "Multi-source composite signal — NewsAPI · DexScreener buy/sell ratio · "
            "Helius on-chain whale data · Crypto Fear & Greed Index",
        ),
        unsafe_allow_html=True,
    )

    sd = sentiment_all()
    fg = fear_greed()
    fgv = fg.get("value", 50)

    # -- Top stats -------------------------------------------------------------
    avg_score = (sum(v.get("score", 0) for v in sd.values()) / len(sd)) if sd else 0
    bullish = sum(1 for v in sd.values() if v.get("score", 0) > 0.1) if sd else 0
    bearish = sum(1 for v in sd.values() if v.get("score", 0) < -0.1) if sd else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(stat_block(str(fgv), "Fear & Greed", accent=fgv < 35), unsafe_allow_html=True)
    c2.markdown(stat_block(f"{avg_score:+.3f}", "Market Sentiment"), unsafe_allow_html=True)
    c3.markdown(stat_block(str(bullish), "Bullish Assets"), unsafe_allow_html=True)
    c4.markdown(
        stat_block(str(bearish), "Bearish Assets", accent=bearish > 5), unsafe_allow_html=True
    )

    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

    # -- Sentiment bars --------------------------------------------------------
    if sd:
        st.markdown(section_label("COMPOSITE SENTIMENT — ALL ASSETS"), unsafe_allow_html=True)
        st.markdown(chart_container(), unsafe_allow_html=True)
        assets = list(sd.keys())
        scores = [sd[a].get("score", 0) for a in assets]
        fig = sentiment_bars(assets, scores, height=300)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(chart_container_close(), unsafe_allow_html=True)
    else:
        st.info("Sentiment cache empty. Run `python -m sentiment.scorer` to populate.")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    # -- Asset detail ----------------------------------------------------------
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown(section_label("COMPONENT BREAKDOWN"), unsafe_allow_html=True)
        if sd:
            asset_sel = st.selectbox("ASSET", list(sd.keys()))
            data = sd.get(asset_sel, {})
            comps = data.get("components", {})
            if comps:
                names = list(comps.keys())
                cscores = [comps[c].get("score", 0) for c in names]
                colors = [
                    COLORS["accent_primary"] if s < -0.1 else "#F5F5F5" if s > 0.1 else "#333"
                    for s in cscores
                ]
                fig2 = go.Figure(
                    go.Bar(
                        x=names,
                        y=cscores,
                        marker_color=colors,
                        marker_opacity=0.85,
                        text=[f"{s:+.3f}" for s in cscores],
                        textposition="outside",
                        textfont={"family": "Space Mono", "size": 10, "color": "#555"},
                    )
                )
                fig2.update_layout(
                    paper_bgcolor="#000",
                    plot_bgcolor="#000",
                    font={"color": "#555", "family": "Space Mono"},
                    height=320,
                    margin={"l": 40, "r": 20, "t": 20, "b": 40},
                    xaxis={"gridcolor": "#161616", "linecolor": "#1E1E1E"},
                    yaxis={"gridcolor": "#161616", "linecolor": "#1E1E1E"},
                )
                fig2.add_hline(y=0, line_dash="dot", line_color="#333", opacity=0.6)
                st.markdown(chart_container(), unsafe_allow_html=True)
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
                st.markdown(chart_container_close(), unsafe_allow_html=True)
            else:
                st.info(f"No component breakdown available for {asset_sel}.")
        else:
            st.info("No sentiment data loaded.")

    with col2:
        st.markdown(section_label("DATA SOURCES"), unsafe_allow_html=True)
        st.markdown(
            f"""
        <div style="border:1px solid #1E1E1E; border-top:2px solid #FF2D00;">
            {
                "".join(
                    [
                        f'''<div style="padding:1.1rem 1.25rem; border-bottom:1px solid #161616;
                        display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-family:'Space Grotesk',sans-serif; font-size:0.9rem;
                                    color:#F5F5F5; font-weight:500;">{source}</div>
                        <div style="font-family:'Space Mono',monospace; font-size:0.65rem;
                                    color:#444; margin-top:0.2rem;">{desc}</div>
                    </div>
                    <div style="font-family:'Bebas Neue',sans-serif; font-size:1.3rem;
                                color:{"#FF3D00" if active else "#333"};">
                        {weight}
                    </div>
                </div>'''
                        for source, desc, weight, active in [
                            ("NEWSAPI", "textblob nlp · crypto headlines", "25%", True),
                            ("DEX BUY/SELL", "dexscreener transaction flow", "30%", True),
                            ("HELIUS ON-CHAIN", "whale concentration · rpc calls", "25%", True),
                            ("FEAR & GREED", "alternative.me index · daily", "15%", True),
                            ("TWITTER/X", "twikit scraper · pending credentials", "0%", False),
                        ]
                    ]
                )
            }
        </div>
        """,
            unsafe_allow_html=True,
        )
