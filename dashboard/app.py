import os
import sys

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.components.theme import GLOBAL_CSS

st.set_page_config(
    page_title="ZAERYN",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# -- Sidebar ------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<div style="padding:2rem 1.5rem 1.25rem;border-bottom:1px solid #1E1E1E;">'
        "<div style=\"font-family:'Bebas Neue',sans-serif;font-size:2.6rem;font-weight:400;"
        "letter-spacing:0.15em;color:#F5F5F5;line-height:1;"
        'text-shadow:0 0 40px rgba(255,61,0,0.4),0 0 80px rgba(255,45,0,0.2);">ZAERYN</div>'
        "<div style=\"font-family:'Space Mono',monospace;font-size:0.55rem;color:#2A2A2A;"
        'letter-spacing:0.22em;text-transform:uppercase;margin-top:0.35rem;">'
        "Intelligence System</div></div>",
        unsafe_allow_html=True,
    )

    selected = st.radio(
        label="",
        options=["OVERVIEW", "PIPELINE", "SENTIMENT", "ML MODELS", "BACKTESTING"],
        label_visibility="collapsed",
    )

    from config.settings import ALL_ASSETS as _ALL_ASSETS
    from config.settings import MODEL_HORIZON as _HORIZON
    from dashboard.data_loader import db_stats, model_health_all

    _stats = db_stats()
    _total_candles = sum(v.get("1h", {}).get("count", 0) for v in _stats.values())
    _health = model_health_all()
    _models_ready = sum(1 for a in _ALL_ASSETS if _health.get(a, {}).get("models_exist"))

    st.markdown(
        '<div style="margin-top:2.5rem;padding:1rem 1.5rem;border-top:1px solid #1E1E1E;">'
        "<div style=\"font-family:'Space Mono',monospace;font-size:0.58rem;color:#2A2A2A;"
        f'line-height:2.2;text-transform:uppercase;letter-spacing:0.06em;">'
        f'<div>CANDLES <span style="color:#FF3D00;float:right;">{_total_candles:,}</span></div>'
        f'<div>ASSETS <span style="color:#FF3D00;float:right;">{len(_ALL_ASSETS)}</span></div>'
        f'<div>MODELS <span style="color:#FF3D00;float:right;">{_models_ready}/{len(_ALL_ASSETS)}</span></div>'
        f'<div>HORIZON <span style="color:#FF3D00;float:right;">{_HORIZON}H</span></div>'
        "</div></div>",
        unsafe_allow_html=True,
    )

# -- Force sidebar open (counters browser-cached collapsed state) -------------
components.html(
    """
<script>
(function() {
    function openSidebar() {
        var btn = window.parent.document.querySelector('[data-testid="collapsedControl"] button');
        if (btn) { btn.click(); return; }
        var sb = window.parent.document.querySelector('section[data-testid="stSidebar"]');
        if (sb && sb.getAttribute('aria-expanded') === 'false') {
            var toggle = sb.querySelector('button');
            if (toggle) toggle.click();
        }
    }
    setTimeout(openSidebar, 300);
})();
</script>
""",
    height=0,
)

# -- Page transition flash ----------------------------------------------------
st.markdown('<div class="page-overlay"></div>', unsafe_allow_html=True)

# -- Route --------------------------------------------------------------------
if selected == "OVERVIEW":
    from dashboard.pages.overview import render

    render()
elif selected == "PIPELINE":
    from dashboard.pages.data_pipeline import render

    render()
elif selected == "SENTIMENT":
    from dashboard.pages.sentiment import render

    render()
elif selected == "ML MODELS":
    from dashboard.pages.ml_models import render

    render()
elif selected == "BACKTESTING":
    from dashboard.pages.backtesting import render

    render()
