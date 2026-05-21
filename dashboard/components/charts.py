import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.theme import COLORS, PLOTLY_BASE


def _base_layout(height: int, title: str = "") -> dict:
    layout = {**PLOTLY_BASE, "height": height}
    if title:
        layout["title"] = {
            "text": title,
            "font": {"family": "Bebas Neue", "size": 20, "color": COLORS["text_primary"]},
            "x": 0.01,
            "xanchor": "left",
        }
    return layout


def candlestick_chart(
    df: pd.DataFrame, asset: str, show_sma: bool = True, height: int = 500
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=asset,
            increasing_line_color=COLORS["accent_warm"],
            decreasing_line_color="#333333",
            increasing_fillcolor="rgba(255,45,0,0.6)",
            decreasing_fillcolor="#222222",
            line={"width": 1},
        ),
        row=1,
        col=1,
    )

    if show_sma and len(df) >= 50:
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["close"].rolling(20).mean(),
                name="SMA 20",
                mode="lines",
                line={"color": COLORS["accent_glow"], "width": 1.5},
                opacity=0.7,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["close"].rolling(50).mean(),
                name="SMA 50",
                mode="lines",
                line={"color": "#555555", "width": 1.2, "dash": "dot"},
                opacity=0.6,
            ),
            row=1,
            col=1,
        )

    vol_colors = [
        COLORS["accent_primary"] if c >= o else "#222222"
        for c, o in zip(df["close"], df["open"], strict=False)
    ]
    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            marker_color=vol_colors,
            marker_opacity=0.7,
            showlegend=False,
            name="Volume",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(**_base_layout(height))
    fig.update_layout(xaxis_rangeslider_visible=False)
    fig.update_yaxes(
        gridcolor=COLORS["border_subtle"],
        linecolor=COLORS["border_default"],
    )
    return fig


def equity_curves(curves: dict, timestamps: list, height: int = 500) -> go.Figure:
    fig = go.Figure()

    STYLE_MAP = {
        "ZAERYN ML Composite": {
            "color": COLORS["accent_glow"],
            "width": 3,
            "dash": "solid",
            "opacity": 1.0,
            "fill": True,
        },
        "Buy & Hold": {
            "color": "#555555",
            "width": 1.5,
            "dash": "dot",
            "opacity": 0.7,
            "fill": False,
        },
        "MACD Cross": {
            "color": "#333333",
            "width": 1.5,
            "dash": "solid",
            "opacity": 0.8,
            "fill": False,
        },
        "RSI Mean Reversion": {
            "color": "#2A2A2A",
            "width": 1.5,
            "dash": "solid",
            "opacity": 0.8,
            "fill": False,
        },
        "Bollinger Band": {
            "color": "#252525",
            "width": 1.5,
            "dash": "solid",
            "opacity": 0.8,
            "fill": False,
        },
    }

    for name, values in curves.items():
        if not values:
            continue
        style = STYLE_MAP.get(
            name, {"color": "#333", "width": 1, "dash": "solid", "opacity": 0.6, "fill": False}
        )
        pct_vals = [(v / values[0] - 1) * 100 for v in values]

        fig.add_trace(
            go.Scatter(
                x=timestamps[: len(values)],
                y=pct_vals,
                name=name,
                mode="lines",
                line={
                    "color": style["color"],
                    "width": style["width"],
                    "dash": style["dash"],
                },
                opacity=style["opacity"],
                fill="tozeroy" if style["fill"] else None,
                fillcolor="rgba(255,61,0,0.06)" if style["fill"] else None,
                hovertemplate=f"<b>{name}</b><br>Return: %{{y:.2f}}%<extra></extra>",
            )
        )

    fig.update_layout(**_base_layout(height, "Equity Curve — $10,000 Starting Capital"))
    fig.update_layout(
        yaxis_title="Return (%)",
        yaxis_ticksuffix="%",
        legend={
            **PLOTLY_BASE["legend"],
            "orientation": "h",
            "y": 1.08,
            "x": 0,
        },
    )
    fig.add_hline(y=0, line_dash="dot", line_color=COLORS["border_default"], opacity=0.5)
    return fig


def sharpe_bar(strategies: list, sharpes: list, height: int = 380) -> go.Figure:
    colors = [
        COLORS["accent_primary"] if "ZAERYN" in s else "#222222" if v >= 0 else "#1A0000"
        for s, v in zip(strategies, sharpes, strict=False)
    ]

    fig = go.Figure(
        go.Bar(
            x=sharpes,
            y=strategies,
            orientation="h",
            marker={"color": colors, "opacity": 0.9, "line": {"color": "#000", "width": 0}},
            text=[f"{v:.3f}" for v in sharpes],
            textposition="outside",
            textfont={"family": "Space Mono", "size": 11, "color": COLORS["text_secondary"]},
            hovertemplate="<b>%{y}</b><br>Sharpe: %{x:.4f}<extra></extra>",
        )
    )

    fig.update_layout(**_base_layout(height, "Sharpe Ratio Comparison"))
    fig.add_vline(x=0, line_dash="dot", line_color=COLORS["border_default"], opacity=0.6)
    fig.update_layout(
        xaxis_title="Sharpe Ratio",
        yaxis={"categoryorder": "total ascending"},
    )
    return fig


def sentiment_bars(assets: list, scores: list, height: int = 260) -> go.Figure:
    colors = [
        COLORS["accent_primary"] if s < -0.1 else COLORS["text_primary"] if s > 0.1 else "#444444"
        for s in scores
    ]

    fig = go.Figure(
        go.Bar(
            x=assets,
            y=scores,
            marker_color=colors,
            marker_opacity=0.85,
            text=[f"{s:+.3f}" for s in scores],
            textposition="outside",
            textfont={"family": "Space Mono", "size": 10, "color": COLORS["text_secondary"]},
        )
    )

    fig.update_layout(**_base_layout(height, "Composite Sentiment by Asset"))
    fig.add_hline(y=0, line_dash="dot", line_color="#333333", opacity=0.6)
    fig.update_layout(yaxis_title="Score", bargap=0.35)
    return fig


def feature_importance(features: list, values: list, height: int = 440) -> go.Figure:
    pairs = sorted(zip(values, features, strict=False), reverse=True)[:15]
    vals, feats = zip(*pairs, strict=False) if pairs else ([], [])

    colors = [
        COLORS["accent_primary"] if i == 0 else COLORS["accent_dim"] if i < 3 else "#222222"
        for i in range(len(vals))
    ]

    fig = go.Figure(
        go.Bar(
            x=list(vals),
            y=list(feats),
            orientation="h",
            marker={"color": colors, "opacity": 0.9},
            text=[f"{v:.4f}" for v in vals],
            textposition="outside",
            textfont={"family": "Space Mono", "size": 9, "color": COLORS["text_muted"]},
        )
    )

    fig.update_layout(**_base_layout(height, "Feature Importance — Volatility Model"))
    fig.update_layout(
        xaxis_title="Importance",
        yaxis={"categoryorder": "total ascending"},
    )
    return fig


def model_performance_bars(assets: list, r2s: list, aucs: list, height: int = 360) -> go.Figure:
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Volatility R²",
            x=assets,
            y=r2s,
            marker_color=COLORS["accent_primary"],
            marker_opacity=0.9,
            text=[f"{v:.3f}" for v in r2s],
            textposition="outside",
            textfont={"family": "Space Mono", "size": 10, "color": COLORS["text_secondary"]},
        )
    )
    fig.add_trace(
        go.Bar(
            name="Trend AUC",
            x=assets,
            y=aucs,
            marker_color="#333333",
            marker_opacity=0.9,
            text=[f"{v:.3f}" for v in aucs],
            textposition="outside",
            textfont={"family": "Space Mono", "size": 10, "color": COLORS["text_secondary"]},
        )
    )

    fig.update_layout(**_base_layout(height, "Model Performance by Asset"))
    fig.update_layout(barmode="group", yaxis_title="Score", bargap=0.2)
    fig.add_hline(
        y=0.5,
        line_dash="dot",
        line_color="#333333",
        opacity=0.6,
        annotation_text="AUC baseline",
        annotation_font={"size": 9, "color": "#444"},
    )
    return fig


def scatter_risk_return(
    names: list, returns: list, sharpes: list, trades: list, height: int = 460
) -> go.Figure:
    fig = go.Figure()

    for name, ret, sharpe, tc in zip(names, returns, sharpes, trades, strict=False):
        is_z = "ZAERYN" in name
        color = COLORS["accent_glow"] if is_z else "#333333"
        size = max(14, min(36, tc * 1.4))
        symbol = "star" if is_z else "circle"

        fig.add_trace(
            go.Scatter(
                x=[sharpe],
                y=[ret],
                mode="markers+text",
                name=name,
                marker={
                    "size": size,
                    "color": color,
                    "opacity": 1.0 if is_z else 0.55,
                    "line": {
                        "color": "rgba(255,61,0,0.4)" if is_z else "#000",
                        "width": 2 if is_z else 1,
                    },
                    "symbol": symbol,
                },
                text=[name.split()[0]],
                textposition="top center",
                textfont={
                    "family": "Space Mono",
                    "size": 10 if is_z else 8,
                    "color": color,
                },
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    f"Sharpe: {sharpe:.3f}<br>"
                    f"Return: {ret:.2f}%<br>"
                    f"Trades: {tc}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **_base_layout(height, "Risk-Adjusted Performance: All Strategies"),
        xaxis_title="Sharpe Ratio",
        yaxis_title="Return (%)",
        showlegend=False,
    )
    fig.add_vline(x=0, line_dash="dot", line_color="#222", opacity=0.6)
    fig.add_hline(y=0, line_dash="dot", line_color="#222", opacity=0.6)
    return fig
