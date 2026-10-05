"""📡 Live dashboard — read-only, always on.

* Market hours: live (delayed) prices for the batch, live P&L, today's move, auto-refresh every minute.
* Any time: the full 21-day performance dashboard and the research & sentiment report, combined.
* Data: the latest state the GitHub Action committed (read straight from the repo), or local files.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from core import live
from core.excel_builder import build_workbook
from core.reports import TIMELINE_CSS, dashboard_html, timeline_html
from core.research_report import research_html
from core.tracker import HOLD, compute, list_batches, load_state


# --------------------------------------------------------------------------- #
# config + data loading
# --------------------------------------------------------------------------- #
def secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


REPO = secret("LIVE_REPO") or secret("GITHUB_REPO")
BRANCH = secret("GITHUB_BRANCH", "main")
TOKEN = secret("GITHUB_TOKEN")


@st.cache_data(ttl=300, show_spinner=False)
def get_batches(repo, branch, token) -> tuple[list[str], str]:
    if repo:
        try:
            return live.list_remote_batches(repo, branch, token), f"GitHub · {repo}"
        except Exception:
            pass
    return [b for b in list_batches() if not b.endswith("-DEMO")], "local files"


@st.cache_data(ttl=300, show_spinner=False)
def get_state(repo, branch, token, batch_id) -> dict | None:
    if repo:
        try:
            return live.load_remote_state(repo, batch_id, branch, token)
        except Exception:
            pass
    return load_state(batch_id)


@st.cache_data(ttl=55, show_spinner=False)
def get_quotes(symbols: tuple[str, ...]):
    return live.fetch_live_quotes(list(symbols))


@st.cache_data(ttl=300, show_spinner=False)
def get_reports(state_json: str):
    import json
    stt = json.loads(state_json)
    r = compute(stt)
    return dashboard_html(stt, r), research_html(stt, r), build_workbook(stt, r)


def embed(html: str, height: int):
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height, scrolling=True)


def inr(v, sign=True):
    if v is None or pd.isna(v):
        return "—"
    s = f"₹{abs(v):,.0f}"
    return (("+" if v > 0 else "-" if v < 0 else "") + s) if sign else s


_MP = set(__import__("inspect").signature(st.metric).parameters)


def metric(col, label, value, delta=None, neutral=False):
    kw = {}
    if delta is not None:
        kw["delta"] = delta
        if neutral:
            kw["delta_color"] = "off"
            if "delta_arrow" in _MP:
                kw["delta_arrow"] = "off"
    col.metric(label, value, **kw)


def pct(v):
    return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"


st.markdown("""
<style>
.block-container{padding-top:1rem;max-width:1440px}
.hero{background:radial-gradient(900px 260px at 92% -60%,#3b5bff66,transparent),linear-gradient(120deg,#08162b,#13305a 55%,#2440c4);
color:#fff;border-radius:16px;padding:18px 24px;margin-bottom:12px}
.hero h1{font-size:23px;margin:0;color:#fff}.hero p{margin:6px 0 0;color:#c9d3e6;font-size:13px}
.pill{display:inline-block;padding:3px 11px;border-radius:999px;font-size:12px;font-weight:700;margin:8px 6px 0 0;
background:rgba(255,255,255,.14);color:#fff}
.pill.open{background:#1f9d63}.pill.pre{background:#c9860a}.pill.closed{background:rgba(255,255,255,.14)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#7CFFB2;margin-right:6px;
animation:pulse 1.4s infinite}@keyframes pulse{0%{opacity:1}50%{opacity:.25}100%{opacity:1}}
div[data-testid="stMetric"]{background:var(--secondary-background-color);border-radius:12px;padding:10px 14px;
border-top:3px solid #2F4BD8}
div[data-testid="stMetricValue"]{font-size:1.4rem}
:root{--wash:#f8fafc;--line:#e2e8f0;--sub:#64748b;--amber:#C9860A;--red:#D64545}
@media(max-width:700px){.tl{grid-template-columns:repeat(22,40px)!important;overflow-x:auto;padding-bottom:4px}}
""" + TIMELINE_CSS + "</style>", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# batch selection
# --------------------------------------------------------------------------- #
batches, source = get_batches(REPO, BRANCH, TOKEN)
if not batches:
    st.info("No batch yet. Add one in **🛠 Manage & update** or drop a SwingScope HTML into the repo's `inbox/`.")
    st.stop()

states = {b: get_state(REPO, BRANCH, TOKEN, b) for b in batches[:6]}
states = {b: s for b, s in states.items() if s}
active = [b for b, s in states.items() if compute(s)["kpi"]["day"] < HOLD]
with st.sidebar:
    st.markdown("#### 📡 Live dashboard")
    options = list(states)
    default = options.index(active[0]) if active else 0
    bid = st.selectbox("Batch", options, index=default,
                       format_func=lambda b: f"{b}  ·  {'active' if b in active else 'completed'}")
    if st.button("🔄 Reload latest data", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"Data source: {source}. Refreshes every 5 min; live prices every 60 s in market hours.")

state = states[bid]
res = compute(state)
k = res["kpi"]
mkt = live.market_status()
b = state["batch"]

pill_cls = {"open": "open", "preopen": "pre"}.get(mkt["state"], "closed")
dot = '<span class="dot"></span>' if mkt["is_open"] else ""
st.markdown(
    f"""<div class="hero"><h1>SwingScope batch {bid} · Day {k['day']} of {HOLD}</h1>
    <p>{k['phase']} · last official close {k['last_session']} · exit ~{k['exit_date']} ·
    regime {b.get('regime') or '—'} · data updated {state.get('last_updated') or '—'}</p>
    <span class="pill {pill_cls}">{dot}{mkt['label']}</span>
    <span class="pill">{mkt['now']:%a %d %b · %H:%M} IST</span>
    <span class="pill">Next session {mkt['next_session']}</span></div>""",
    unsafe_allow_html=True)
st.markdown(timeline_html(res), unsafe_allow_html=True)
st.write("")

# --------------------------------------------------------------------------- #
# live block (auto-refreshing fragment)
# --------------------------------------------------------------------------- #
show_live = (k["day"] < HOLD and mkt["trading_day"] and mkt["state"] in ("open", "closed_today")
             and k["last_session"] < mkt["today"])
refresh = 60 if mkt["is_open"] else None


@st.fragment(run_every=refresh)
def live_block():
    m = live.market_status()
    if show_live:
        syms = tuple(s["symbol"] for s in b["stocks"])
        quotes, err = get_quotes(syms)
        df, sm = live.live_table(state, res, quotes)
        if sm["covered"] == 0:
            st.markdown(f"##### 🟠 Live prices unavailable right now — showing official closes of "
                        f"{k['last_session']} · retrying every minute")
        else:
            head = "Live" if m["is_open"] else "Today's close (provisional, before the official update)"
            st.markdown(f"##### {'🟢' if m['is_open'] else '🕕'} {head} — {sm['covered']}/{len(syms)} quotes · "
                        f"{m['now']:%H:%M:%S} IST")
        c = st.columns(6)
        metric(c[0], "Live value", inr(sm["value"], False), f"{inr(sm['today_pnl'])} today")
        metric(c[1], "P&L since entry", inr(sm["pnl"]), pct(sm["ret"]))
        metric(c[2], "Today", pct(sm["today_pct"]), inr(sm["today_pnl"]))
        metric(c[3], "Nifty 50 today", pct(sm["nifty_today"]), f"since signal {pct(sm['nifty_since'])}",
                    neutral=True)
        metric(c[4], "Alpha vs Nifty", pct(sm["alpha"]), "since entry", neutral=True)
        metric(c[5], "Winners / losers", f"{sm['winners']} / {sm['losers']}", f"of {len(df)}", neutral=True)
        left, right = st.columns([3, 2])
        with left:
            st.dataframe(
                df.style.format({"Qty": "{:.0f}", "Entry": "{:,.2f}", "Last EOD": "{:,.2f}", "Live": "{:,.2f}",
                                 "Today %": "{:+.2f}%", "Since entry %": "{:+.2f}%", "Live P&L": "₹{:,.0f}",
                                 "Today ₹": "₹{:,.0f}"})
                .map(lambda v: "color:#1F9D63;font-weight:600" if isinstance(v, (int, float)) and v > 0 else
                     ("color:#D64545;font-weight:600" if isinstance(v, (int, float)) and v < 0 else ""),
                     subset=["Today %", "Since entry %", "Live P&L", "Today ₹"]),
                hide_index=True, width="stretch", height=410)
        with right:
            d = df.sort_values("Since entry %")
            fig = go.Figure()
            fig.add_bar(y=d["Symbol"], x=d["Since entry %"], orientation="h", name="Since entry",
                        marker_color=["#1F9D63" if v >= 0 else "#D64545" for v in d["Since entry %"]],
                        text=[f"{v:+.1f}%" for v in d["Since entry %"]], textposition="outside", cliponaxis=False)
            fig.add_scatter(y=d["Symbol"], x=d["Today %"], mode="markers", name="Today",
                            marker=dict(symbol="diamond", size=10, color="#C9860A"))
            fig.update_layout(height=410, margin=dict(l=10, r=30, t=30, b=20), paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.08, x=0),
                              title=dict(text="Return since entry (bar) · today (◆)", font=dict(size=13)))
            fig.update_xaxes(ticksuffix="%", gridcolor="rgba(148,163,184,.2)")
            st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
        note = "Prices from Yahoo Finance, delayed ~1–15 min. "
        if m["is_open"]:
            note += "Auto-refreshes every 60 s. "
        note += "Official closes replace these after 18:05 IST."
        if err:
            note += f"  ⚠️ {err}"
        st.caption(note)
    else:
        why = ("Batch complete — final figures." if k["day"] >= HOLD else
               f"{m['label']} — showing official closes of {k['last_session']}.")
        st.markdown(f"##### 🕘 {why}")
        c = st.columns(6)
        metric(c[0], "Value", inr(k["value"], False), pct(k["today_chg"]) + " last session"
                    if k["today_chg"] is not None else None)
        metric(c[1], "Gross P&L", inr(k["gross_pnl"]), pct(k["gross_ret"]))
        metric(c[2], "Net P&L (est.)", inr(k["net_pnl"]), pct(k["net_ret"]))
        metric(c[3], "Nifty 50", pct(k["nifty_ret"]), "same window", neutral=True)
        metric(c[4], "Alpha vs Nifty", pct(k["alpha"]), neutral=True)
        metric(c[5], "Winners / losers", f"{k['winners']} / {k['losers']}",
                    f"best {k['best'][0]} {pct(float(k['best'][1]))}", neutral=True)
        if mkt["trading_day"] and mkt["state"] == "preopen":
            st.caption("Pre-open: live prices start at 09:15 IST.")


live_block()

# --------------------------------------------------------------------------- #
# the two reports, combined
# --------------------------------------------------------------------------- #
dash, research, xlsx = get_reports(__import__("json").dumps(state, default=str))
t1, t2, t3 = st.tabs(["📊 21-day performance", "🧭 Research & sentiment", "⬇️ Files"])
with t1:
    embed(dash, 4300)
with t2:
    embed(research, 7200)
with t3:
    stamp = f"D{k['day']:02d}_{k['last_session']}"
    c1, c2, c3 = st.columns(3)
    c1.download_button("📗 Excel tracker", xlsx, file_name=f"SwingScope_{bid}_{stamp}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    c2.download_button("📊 Dashboard HTML", dash.encode("utf-8"), file_name=f"SwingScope_{bid}_{stamp}_dashboard.html",
                       mime="text/html", width="stretch")
    c3.download_button("🧭 Research HTML", research.encode("utf-8"),
                       file_name=f"SwingScope_{bid}_{stamp}_research.html", mime="text/html", width="stretch")
    st.caption("Same files the Telegram report carries, rebuilt from the latest data.")
