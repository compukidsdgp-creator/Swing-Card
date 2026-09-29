"""Plotly figures shared by the Streamlit dashboard and the exported HTML."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .tracker import HOLD

BLUE = "#2F4BD8"
TEAL = "#0E7C86"
GREEN = "#1F9D63"
RED = "#D64545"
GREY = "#9AA2AD"
AMBER = "#C9860A"
NAVY = "#0B1F3A"
FONT = dict(family="Inter, Segoe UI, Roboto, sans-serif", size=12, color="#1f2937")


def _inr(v):
    return f"{'−' if v < 0 else '+'}₹{abs(v):,.0f}"


def _layout(fig, title, h=380):
    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(size=15, color=NAVY)),
        height=h, margin=dict(l=50, r=20, t=50, b=40), font=FONT,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, linecolor="#d1d5db")
    fig.update_yaxes(gridcolor="#eef0f3", zerolinecolor="#cbd5e1")
    return fig


def fig_equity(res: dict) -> go.Figure:
    port, k = res["portfolio"], res["kpi"]
    cur = k["day"]
    fig = go.Figure()
    fig.add_vrect(x0=cur, x1=HOLD, fillcolor="#f1f5f9", line_width=0, layer="below",
                  annotation_text="remaining sessions", annotation_position="top left",
                  annotation_font=dict(size=10, color=GREY))
    fig.add_trace(go.Scatter(x=port["Day"], y=port["Return %"], mode="lines+markers", name="Portfolio (gross)",
                             line=dict(color=BLUE, width=3), marker=dict(size=6),
                             customdata=port["Date"], hovertemplate="%{customdata}: %{y:+.2f}%<extra></extra>",
                             fill="tozeroy", fillcolor="rgba(47,75,216,0.07)"))
    if port["Nifty %"].notna().any():
        fig.add_trace(go.Scatter(x=port["Day"], y=port["Nifty %"], mode="lines", name="Nifty 50",
                                 line=dict(color=GREY, width=2, dash="dash"),
                                 hovertemplate="Nifty: %{y:+.2f}%<extra></extra>"))
    be = res["kpi"]["est_costs"] / res["kpi"]["invested"] * 100
    fig.add_hline(y=be, line=dict(color=AMBER, width=1, dash="dot"),
                  annotation_text=f"break-even after costs (+{be:.2f}%)", annotation_position="bottom right",
                  annotation_font=dict(size=10, color=AMBER))
    fig.add_vline(x=cur, line=dict(color=AMBER, width=2))
    fig.update_xaxes(range=[-0.3, HOLD + 0.3], dtick=1, title="Session day")
    fig.update_yaxes(ticksuffix="%", title="Return vs entry")
    return _layout(fig, f"Portfolio return — Day {cur} of {HOLD}", 400)


def fig_stock_bars(res: dict) -> go.Figure:
    t = res["table"].sort_values("Return %")
    colors = [GREEN if v >= 0 else RED for v in t["Return %"]]
    fig = go.Figure(go.Bar(x=t["Return %"], y=t["Symbol"], orientation="h", marker_color=colors,
                           text=[f"{v:+.2f}%" for v in t["Return %"]], textposition="outside", cliponaxis=False,
                           customdata=np.stack([t["P&L"], t["Last close"]], axis=1),
                           hovertemplate="<b>%{y}</b><br>Return %{x:+.2f}%<br>P&L ₹%{customdata[0]:,.0f}"
                                         "<br>Close ₹%{customdata[1]:,.2f}<extra></extra>"))
    lo, hi = float(t["Return %"].min()), float(t["Return %"].max())
    pad = max(2.0, (hi - lo) * 0.18)
    fig.update_xaxes(ticksuffix="%", range=[min(lo, 0) - pad, max(hi, 0) + pad])
    fig = _layout(fig, "Return by stock (vs entry)", 400)
    fig.update_layout(hovermode="closest")
    return fig


def fig_heatmap(res: dict) -> go.Figure:
    k = res["kpi"]
    m = res["ret_matrix"].iloc[:, 1: k["day"] + 1] if k["day"] >= 1 else res["ret_matrix"].iloc[:, :1]
    dates = res["dates"][1: k["day"] + 1] if k["day"] >= 1 else res["dates"][:1]
    x = [f"D{i + 1}<br>{d[5:]}" for i, d in enumerate(dates)]
    lim = max(5, float(np.nanmax(np.abs(m.values))) if m.size and not np.all(np.isnan(m.values)) else 5)
    fig = go.Figure(go.Heatmap(z=m.values, x=x, y=m.index, colorscale=[[0, RED], [0.5, "#ffffff"], [1, GREEN]],
                               zmin=-lim, zmax=lim, text=np.vectorize(lambda v: "" if np.isnan(v) else f"{v:+.1f}")(m.values),
                               texttemplate="%{text}", textfont=dict(size=10),
                               hovertemplate="%{y} %{x}: %{z:+.2f}%<extra></extra>",
                               colorbar=dict(ticksuffix="%", thickness=10)))
    fig.update_yaxes(autorange="reversed")
    fig = _layout(fig, "Cumulative return heatmap (stock × session)", 420)
    fig.update_layout(hovermode="closest")
    return fig


def fig_paths(res: dict) -> go.Figure:
    k = res["kpi"]
    m = res["ret_matrix"].iloc[:, : k["day"] + 1].copy()
    m["Day 0"] = (res["closes"]["Day 0"] / res["entry"] - 1) * 100
    fig = go.Figure()
    palette = ["#2F4BD8", "#0E7C86", "#C9860A", "#8B5CF6", "#DB2777", "#059669", "#EA580C", "#0284C7",
               "#65A30D", "#B91C1C"]
    for i, sym in enumerate(m.index):
        fig.add_trace(go.Scatter(x=list(range(m.shape[1])), y=m.loc[sym].values, mode="lines", name=sym,
                                 line=dict(width=2, color=palette[i % len(palette)]),
                                 hovertemplate=f"{sym}: %{{y:+.2f}}%<extra></extra>"))
    fig.add_hline(y=0, line=dict(color="#94a3b8", width=1))
    fig.update_xaxes(range=[0, HOLD], dtick=1, title="Session day")
    fig.update_yaxes(ticksuffix="%")
    fig = _layout(fig, "Individual stock paths (vs entry)", 420)
    fig.update_layout(legend=dict(orientation="v", x=1.02, y=1, xanchor="left", yanchor="top"))
    return fig


def fig_contribution(res: dict) -> go.Figure:
    t = res["table"].sort_values("P&L", ascending=False)
    fig = go.Figure(go.Waterfall(
        x=list(t["Symbol"]) + ["Portfolio"], y=list(t["P&L"]) + [0],
        measure=["relative"] * len(t) + ["total"],
        increasing=dict(marker=dict(color=GREEN)), decreasing=dict(marker=dict(color=RED)),
        totals=dict(marker=dict(color=BLUE)),
        text=[_inr(v) for v in t["P&L"]] + [_inr(t["P&L"].sum())], textposition="outside", cliponaxis=False,
        connector=dict(line=dict(color="#cbd5e1"))))
    fig.update_yaxes(tickprefix="₹")
    fig = _layout(fig, "P&L contribution (₹)", 400)
    fig.update_layout(hovermode="closest")
    return fig


def fig_drawdown(res: dict) -> go.Figure:
    p = res["portfolio"]
    fig = go.Figure(go.Scatter(x=p["Day"], y=p["Drawdown %"], fill="tozeroy", mode="lines",
                               line=dict(color=RED, width=2), fillcolor="rgba(214,69,69,0.15)",
                               hovertemplate="Day %{x}: %{y:.2f}%<extra></extra>"))
    fig.update_xaxes(range=[0, HOLD], dtick=1, title="Session day")
    fig.update_yaxes(ticksuffix="%")
    return _layout(fig, "Portfolio drawdown from peak", 300)


def fig_daily(res: dict) -> go.Figure:
    p = res["portfolio"].dropna(subset=["Daily %"])
    fig = go.Figure(go.Bar(x=p["Day"], y=p["Daily %"], marker_color=[GREEN if v >= 0 else RED for v in p["Daily %"]],
                           customdata=p["Date"], hovertemplate="%{customdata}: %{y:+.2f}%<extra></extra>"))
    fig.update_xaxes(range=[0.5, HOLD + 0.5], dtick=1, title="Session day")
    fig.update_yaxes(ticksuffix="%")
    return _layout(fig, "Daily portfolio change", 300)


def fig_sentiment(summary: list[dict]) -> go.Figure:
    df = pd.DataFrame(summary)
    fig = go.Figure()
    for col, color in (("positive", GREEN), ("neutral", "#cbd5e1"), ("negative", RED)):
        fig.add_trace(go.Bar(y=df["symbol"], x=df[col], name=col.title(), orientation="h", marker_color=color))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed")
    fig = _layout(fig, "Headline sentiment mix by stock", 420)
    fig.update_layout(hovermode="closest")
    return fig


ALL = [fig_equity, fig_stock_bars, fig_contribution, fig_heatmap, fig_paths, fig_drawdown, fig_daily]
