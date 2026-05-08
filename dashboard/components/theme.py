COLORS = {
    "bg_void":         "#000000",
    "bg_deep":         "#0A0A0A",
    "bg_surface":      "#111111",
    "bg_hover":        "#1A1A1A",
    "text_primary":    "#F5F5F5",
    "text_secondary":  "#888888",
    "text_muted":      "#444444",
    "accent_primary":  "#FF2D00",
    "accent_warm":     "#FF5500",
    "accent_glow":     "#FF3D00",
    "accent_dim":      "#8B1500",
    "positive":        "#E8E8E8",
    "negative":        "#FF2D00",
    "neutral":         "#555555",
    "border_default":  "#1E1E1E",
    "border_active":   "#FF2D00",
    "border_subtle":   "#161616",
}

PLOTLY_BASE = {
    "paper_bgcolor": "#000000",
    "plot_bgcolor":  "#000000",
    "font":          {"color": "#888888", "family": "Space Mono"},
    "xaxis": {
        "gridcolor":     "#161616",
        "linecolor":     "#1E1E1E",
        "tickfont":      {"color": "#555555", "size": 10, "family": "Space Mono"},
        "zerolinecolor": "#1E1E1E",
    },
    "yaxis": {
        "gridcolor":     "#161616",
        "linecolor":     "#1E1E1E",
        "tickfont":      {"color": "#555555", "size": 10, "family": "Space Mono"},
        "zerolinecolor": "#1E1E1E",
    },
    "legend": {
        "bgcolor":     "rgba(10,10,10,0.9)",
        "bordercolor": "#1E1E1E",
        "borderwidth": 1,
        "font":        {"color": "#888888", "size": 11, "family": "Space Mono"},
    },
    "hoverlabel": {
        "bgcolor":     "#000000",
        "bordercolor": "#FF3D00",
        "font":        {"color": "#F5F5F5", "family": "Space Mono", "size": 11},
    },
    "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
}


GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@300;400;500;600&family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;500&display=swap');

/* -- Reset & Base ---------------------------------------------------------- */
html, body, [class*="css"], .stApp {
    background-color: #000000 !important;
    color: #F5F5F5;
    font-family: 'Inter', sans-serif;
}

#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding: 2rem 2.5rem !important;
    max-width: 1400px;
}

/* -- Sidebar — always visible, never collapsible -------------------------- */
[data-testid="stSidebar"],
section[data-testid="stSidebar"],
[data-testid="stSidebar"][aria-expanded="false"],
section[data-testid="stSidebar"][aria-expanded="false"] {
    background: #000000 !important;
    border-right: 1px solid #1E1E1E;
    min-width: 240px !important;
    max-width: 240px !important;
    width: 240px !important;
    transform: none !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
}
[data-testid="stSidebar"] > div {
    padding: 0 !important;
}
/* Hide Streamlit's auto-generated page nav and all collapse toggles */
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarNavCollapseButton"],
button[aria-label="Close sidebar"],
button[aria-label="Open sidebar"],
.css-1outpf7, .css-17eq0hr {
    display: none !important;
}

/* -- Metrics --------------------------------------------------------------- */
[data-testid="stMetric"] {
    background: #0A0A0A;
    border: 1px solid #1E1E1E;
    border-top: 2px solid #FF2D00;
    padding: 1.25rem 1.5rem;
    transition: border-color 0.2s ease;
}
[data-testid="stMetric"]:hover {
    border-top-color: #FF5500;
}
[data-testid="stMetricLabel"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 0.65rem !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #555555 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Bebas Neue', sans-serif !important;
    font-size: 2.4rem !important;
    font-weight: 400;
    color: #F5F5F5 !important;
    letter-spacing: 0.04em;
}
[data-testid="stMetricDelta"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 0.72rem !important;
}

/* -- Dataframe ------------------------------------------------------------- */
[data-testid="stDataFrame"] {
    background: #0A0A0A;
    border: 1px solid #1E1E1E;
}

/* -- Selectbox ------------------------------------------------------------- */
[data-testid="stSelectbox"] > div > div {
    background: #0A0A0A;
    border: 1px solid #1E1E1E;
    border-radius: 0 !important;
    color: #F5F5F5;
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
}

/* -- Tabs ------------------------------------------------------------------ */
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    border-bottom: 1px solid #1E1E1E;
    gap: 0;
    padding: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    color: #444444;
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 0.6rem 1.5rem;
    border-radius: 0 !important;
}
.stTabs [aria-selected="true"] {
    color: #F5F5F5 !important;
    border-bottom: 2px solid #FF2D00 !important;
    background: transparent !important;
}

/* -- Horizontal rule ------------------------------------------------------- */
hr { border-color: #1E1E1E; margin: 2rem 0; }

/* -- Radio buttons (nav) --------------------------------------------------- */
[data-testid="stSidebar"] .stRadio > label {
    display: none;
}
[data-testid="stSidebar"] .stRadio > div {
    gap: 0 !important;
}
/* Option label: full-width click target */
[data-testid="stSidebar"] .stRadio > div > label {
    display: flex !important;
    align-items: center;
    padding: 0.8rem 1.5rem !important;
    cursor: pointer;
    border-bottom: 1px solid #0D0D0D;
    width: 100%;
    box-sizing: border-box;
    margin: 0 !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: #0A0A0A;
}
/* Hide the radio circle dot */
[data-testid="stSidebar"] .stRadio input[type="radio"] { display: none !important; }
[data-testid="stSidebar"] .stRadio > div > label > span:first-of-type { display: none !important; }
/* Nav text */
[data-testid="stSidebar"] .stRadio div[data-testid="stMarkdownContainer"] p {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.15rem;
    letter-spacing: 0.12em;
    color: #444444;
    transition: color 0.15s ease;
    margin: 0;
    line-height: 1;
}
/* Active nav item */
[data-testid="stSidebar"] .stRadio label:has(input:checked) {
    border-left: 3px solid #FF2D00 !important;
    padding-left: calc(1.5rem - 3px) !important;
    background: #080808;
}
[data-testid="stSidebar"] .stRadio label:has(input:checked) div[data-testid="stMarkdownContainer"] p {
    color: #F5F5F5 !important;
}

/* -- Plotly chart wrapper -------------------------------------------------- */
.js-plotly-plot .plotly { border-radius: 0 !important; }

/* -- Scrollbar ------------------------------------------------------------- */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #000; }
::-webkit-scrollbar-thumb { background: #1E1E1E; }
::-webkit-scrollbar-thumb:hover { background: #FF2D00; }

/* -- Page transition overlay ----------------------------------------------- */
.page-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 999;
    animation: flashOut 0.3s ease forwards;
    pointer-events: none;
}
@keyframes flashOut {
    0%   { opacity: 1; }
    100% { opacity: 0; }
}
</style>
"""


def page_title(text: str, subtitle: str = "") -> str:
    sub = (
        f'<p style="font-family:\'Space Mono\',monospace;font-size:0.75rem;color:#555555;'
        f'letter-spacing:0.1em;text-transform:uppercase;margin:0 0 2rem 0;'
        f'max-width:600px;line-height:1.6;">{subtitle}</p>'
        if subtitle else "<div style='margin-bottom:2rem'></div>"
    )
    return (
        f'<div style="margin-bottom:0.5rem;">'
        f'<h1 style="font-family:\'Bebas Neue\',sans-serif;font-size:5rem;font-weight:400;'
        f'letter-spacing:0.06em;color:#F5F5F5;margin:0 0 0.5rem 0;line-height:0.9;">{text}</h1>'
        f'{sub}</div>'
    )


def stat_block(value: str, label: str, accent: bool = False) -> str:
    val_color  = "#FF3D00" if accent else "#F5F5F5"
    glow       = "text-shadow:0 0 30px rgba(255,61,0,0.33);" if accent else ""
    border_top = "#FF2D00" if accent else "#1E1E1E"
    return (
        f'<div style="padding:1.5rem;background:#0A0A0A;border:1px solid #1E1E1E;'
        f'border-top:2px solid {border_top};">'
        f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:3.2rem;font-weight:400;'
        f'color:{val_color};letter-spacing:0.04em;line-height:1;{glow}">{value}</div>'
        f'<div style="font-family:\'Space Mono\',monospace;font-size:0.65rem;color:#444444;'
        f'text-transform:uppercase;letter-spacing:0.12em;margin-top:0.5rem;">{label}</div>'
        f'</div>'
    )


def chart_container(title: str = "", subtitle: str = "") -> str:
    title_html = ""
    if title:
        sub_html = (
            f'<div style="font-family:Space Mono,monospace;font-size:0.65rem;color:#444;'
            f'margin-top:0.25rem;letter-spacing:0.08em;text-transform:uppercase;">{subtitle}</div>'
            if subtitle else ""
        )
        title_html = (
            f'<div style="padding:1rem 1.25rem 0.75rem;border-bottom:1px solid #161616;">'
            f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:1.3rem;'
            f'letter-spacing:0.08em;color:#F5F5F5;">{title}</div>{sub_html}</div>'
        )
    return (
        f'<div style="background:#0A0A0A;border:1px solid #1E1E1E;'
        f'border-top:2px solid #FF2D00;margin-bottom:1.5rem;">{title_html}'
    )


def chart_container_close() -> str:
    return "</div>"


def section_label(text: str) -> str:
    return (
        f'<div style="font-family:\'Space Mono\',monospace;font-size:0.65rem;color:#FF3D00;'
        f'text-transform:uppercase;letter-spacing:0.2em;margin-bottom:1rem;'
        f'display:flex;align-items:center;gap:0.5rem;">'
        f'<span style="display:inline-block;width:20px;height:1px;background:#FF3D00;"></span>'
        f'{text}</div>'
    )


def tag(text: str, variant: str = "default") -> str:
    styles = {
        "default":  "background:#111;color:#888;border:1px solid #1E1E1E;",
        "active":   "background:rgba(139,21,0,0.13);color:#FF3D00;border:1px solid rgba(255,45,0,0.27);",
        "positive": "background:#1A1A1A;color:#E8E8E8;border:1px solid #333;",
    }
    s = styles.get(variant, styles["default"])
    return (
        f'<span style="{s}font-family:\'Space Mono\',monospace;font-size:0.65rem;'
        f'padding:0.2rem 0.5rem;letter-spacing:0.06em;text-transform:uppercase;'
        f'display:inline-block;margin:0.1rem;">{text}</span>'
    )
