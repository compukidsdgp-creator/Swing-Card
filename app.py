"""SwingScope 21-Day Batch Tracker — Streamlit app.

Run:  streamlit run app.py
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import charts, github_sync, telegram
from core.excel_builder import build_workbook, state_from_workbook
from core.news import collect_news, demo_news, sentiment_summary
from core.parser import parse_swingscope_html
from core.prices import BENCHMARK_SYMBOL, parse_bhavcopy, project_sessions, synthetic_prices
from core.reports import TIMELINE_CSS, dashboard_html, timeline_html
from core.research import ai_research, auto_research, fetch_fundamentals, parse_notes, view_score
from core.research_report import research_html
from core.service import output_paths, rebuild_outputs, update_from_yahoo
from core.tracker import HOLD, compute, list_batches, load_state, merge_prices, new_state, save_state

st.set_page_config(page_title="SwingScope 21-Day Tracker", page_icon="📈", layout="wide")

st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1400px}
.hero{background:linear-gradient(120deg,#0B1F3A,#1E3A66 60%,#2F4BD8);color:#fff;border-radius:14px;
padding:18px 24px;margin-bottom:14px}
.hero h1{font-size:24px;margin:0;color:#fff}.hero p{margin:4px 0 0;color:#c9d3e6;font-size:13px}
div[data-testid="stMetric"]{background:var(--secondary-background-color);border-radius:12px;padding:10px 14px;
border-top:3px solid #2F4BD8}
div[data-testid="stMetricValue"]{font-size:1.45rem}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def current_state() -> dict | None:
    return st.session_state.get("state")


def set_state(state: dict):
    st.session_state["state"] = state
    st.session_state["batch_id"] = state["batch"]["batch_id"]


def persist(state: dict, msg: str = "", push: bool = False):
    res, paths = rebuild_outputs(state, st.session_state.get("min_score", 0.2))
    set_state(state)
    if push and github_sync.enabled(st.secrets):
        bid = state["batch"]["batch_id"]
        files = {f"data/batches/{bid}/{p.name}": p for p in paths.values() if p.exists()}
        if (paths["state"].parent / "source.html").exists():
            files[f"data/batches/{bid}/source.html"] = paths["state"].parent / "source.html"
        out = github_sync.push_files(st.secrets, files, f"SwingScope {bid}: {msg or 'update'}")
        st.toast("GitHub: " + ", ".join(out))
    return res


def embed_html(html: str, height: int):
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:  # older Streamlit
        components.html(html, height=height, scrolling=True)


_METRIC_PARAMS = set(inspect.signature(st.metric).parameters)


def metric(col, label, value, delta=None, neutral=False, spark=None, help=None):
    kw = {"help": help}
    if delta is not None:
        kw["delta"] = delta
        if neutral:
            kw["delta_color"] = "off"
            if "delta_arrow" in _METRIC_PARAMS:
                kw["delta_arrow"] = "off"
    if spark is not None and "chart_data" in _METRIC_PARAMS and len(spark) > 1:
        kw["chart_data"] = list(spark)
        kw["chart_type"] = "area"
    col.metric(label, value, **kw)


def flash(kind: str, msg: str):
    st.session_state.setdefault("flash", []).append((kind, msg))


def fmt_inr(v, sign=False):
    if v is None or pd.isna(v):
        return "—"
    s = f"₹{abs(v):,.0f}"
    return ("+" if v > 0 else "−" if v < 0 else "") + s if sign else ("−" + s if v < 0 else s)


def fmt_pct(v):
    return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"


# --------------------------------------------------------------------------- #
# sidebar — batch management
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("📁 Batch")
    batches = list_batches()
    if batches:
        cur_id = st.session_state.get("batch_id")
        idx = batches.index(cur_id) if cur_id in batches else 0
        pick = st.selectbox("Saved batches", batches, index=idx,
                            format_func=lambda b: f"Batch {b}")
        if st.session_state.get("batch_id") != pick or current_state() is None:
            s = load_state(pick)
            if s:
                set_state(s)
    else:
        st.info("No saved batch yet — upload your SwingScope HTML in **① Upload**.")

    with st.expander("♻️ Restore from a tracker Excel"):
        st.caption("Streamlit Cloud forgets files on restart. Upload any tracker .xlsx this app produced "
                   "to continue exactly where you left off.")
        xl = st.file_uploader("Tracker workbook", type=["xlsx"], key="restore_xl")
        if xl and st.button("Restore batch", width="stretch"):
            try:
                s = state_from_workbook(xl.getvalue())
                persist(s, "restored from Excel")
                flash("success", f"Restored batch {s['batch']['batch_id']}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.caption("GitHub sync: " + ("✅ configured" if github_sync.enabled(st.secrets) else
                                  "off (add GITHUB_TOKEN / GITHUB_REPO to secrets)"))
    st.caption("Telegram: " + ("✅ configured" if telegram.enabled(st.secrets) else
                                "off (add TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"))
    st.caption(f"Today: {date.today():%a %d %b %Y}")


state = current_state()
res = compute(state) if state else None

if state:
    k = res["kpi"]
    b = state["batch"]
    st.markdown(
        f"""<div class="hero"><h1>SwingScope Momentum Batch {b['batch_id']} — 21-Day Tracker</h1>
        <p>Day <b>{k['day']}</b> of {HOLD} · {k['phase']} · last session {k['last_session']} ·
        exit ~{k['exit_date']} · regime {b.get('regime') or '—'} · updated {k['last_updated'] or '—'}</p></div>""",
        unsafe_allow_html=True)
else:
    st.markdown("""<div class="hero"><h1>SwingScope 21-Day Batch Tracker</h1>
    <p>Upload a SwingScope batch HTML to start tracking its 10 stocks from Day 0 to Day 21.</p></div>""",
                unsafe_allow_html=True)

for kind, msg in st.session_state.pop("flash", []):
    getattr(st, kind)(msg)

tab_up, tab_upd, tab_dash, tab_news, tab_dl = st.tabs(
    ["① Upload", "② Daily update", "③ Dashboard", "④ Research & sentiment", "⑤ Downloads"])

# =========================================================================== #
# ① UPLOAD
# =========================================================================== #
with tab_up:
    st.subheader("Upload SwingScope batch HTML")
    up = st.file_uploader("SwingScope momentum batch (.html)", type=["html", "htm"])
    if up:
        raw = up.getvalue().decode("utf-8", errors="ignore")
        try:
            parsed = parse_swingscope_html(raw)
        except Exception as e:
            st.error(f"Could not read this HTML: {e}")
            parsed = None
        if parsed:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Signal (Day 0)", parsed["signal_date"])
            c2.metric("Exit (HTML est.)", parsed.get("exit_date_est") or "—")
            c3.metric("Capital committed", fmt_inr(parsed["capital"]))
            c4.metric("Market regime", parsed.get("regime") or "—")
            df = pd.DataFrame(parsed["stocks"])[["rank", "symbol", "isin", "qty", "last_close", "amount",
                                                 "ret_12_1", "ret_6_1", "ret_3_1", "volatility",
                                                 "traded_daily_cr", "signal_rank", "data_quality", "watch"]]
            df.columns = ["#", "Symbol", "ISIN", "Qty", "Last close", "Amount", "12-1 %", "6-1 %", "3-1 %",
                          "Vol %", "Traded ₹cr", "Signal rank", "DQ", "Watch"]
            st.dataframe(df, hide_index=True, width="stretch")
            exists = parsed["batch_id"] in list_batches()
            if exists:
                st.warning(f"Batch {parsed['batch_id']} already exists. Creating it again resets its price history.")
            colA, colB = st.columns([1, 3])
            if colA.button("✅ Create tracker for this batch", type="primary", width="stretch"):
                s = new_state(parsed, raw)
                with st.spinner("Looking up company names for news search…"):
                    s["fundamentals"] = {x["symbol"]: fetch_fundamentals(x["symbol"]) for x in parsed["stocks"]}
                    s["names"] = {k_: (v_.get("name") or k_) for k_, v_ in s["fundamentals"].items()}
                persist(s, "new batch", push=True)
                flash("success", f"Tracker created for batch {parsed['batch_id']}. Go to **② Daily update**.")
                st.rerun()

    with st.expander("🧪 No HTML handy? Load the demo batch with simulated prices"):
        st.caption("Uses the bundled sample HTML and random-walk prices, only to preview the dashboard.")
        n_demo = st.slider("Simulated sessions", 1, HOLD, 8)
        if st.button("Load demo"):
            raw = (Path(__file__).parent / "samples" / "swingscope_batch_2026-09-28.html").read_text(encoding="utf-8")
            p = parse_swingscope_html(raw)
            p["batch_id"] = p["batch_id"] + "-DEMO"
            s = new_state(p, raw)
            merge_prices(s, synthetic_prices(p, n_demo), "manual")
            s["news"] = demo_news([x["symbol"] for x in p["stocks"]])
            notes = Path(__file__).parent / "samples" / "research_notes_2026-09-28.txt"
            if notes.exists():
                s["research"] = parse_notes(notes.read_text(encoding="utf-8"), p)
            persist(s, "demo")
            st.rerun()

# =========================================================================== #
# ② DAILY UPDATE
# =========================================================================== #
with tab_upd:
    if not state:
        st.info("Create or restore a batch first.")
    else:
        b = state["batch"]
        syms = [x["symbol"] for x in b["stocks"]]
        k = res["kpi"]
        st.progress(k["progress"], text=f"Day {k['day']} of {HOLD} — {k['phase']}")
        if k["stale"]:
            st.warning(f"Latest session stored is **{k['last_session']}**. Fetch today's closes after 3:30 pm IST.")

        partial = {}
        for s_ in syms:
            for d in state["prices"].get(s_, {}):
                if d > b["signal_date"] and d not in res["dates"]:
                    partial[d] = partial.get(d, 0) + 1
        if partial:
            st.info("Partial sessions (not counted until at least half the basket has a close): " +
                    ", ".join(f"{d} ({n}/{len(syms)} stocks)" for d, n in sorted(partial.items())))

        st.markdown("#### A. Automatic — Yahoo Finance + NSE bhavcopy")
        ca, cb = st.columns([1, 2])
        if ca.button("🔄 Fetch latest closes", type="primary", width="stretch"):
            with st.spinner("Downloading closes from Yahoo Finance and NSE archives…"):
                n, errs = update_from_yahoo(state)
            persist(state, f"Yahoo update ({n} prices)", push=True)
            if n:
                flash("success", f"Stored {n} price points. Now at Day {compute(state)['kpi']['day']}.")
            if errs:
                flash("info", "Notes from this update:\n\n- " + "\n- ".join(errs[:12]))
            st.rerun()
        cb.caption("Pulls daily open/close for all 10 stocks plus Nifty 50 from Yahoo, then confirms each session "
                   "with NSE's official bhavcopy (fills anything Yahoo missed). Detects bonuses/splits. "
                   "Day-1 **open** becomes the entry price. Manual values are never overwritten.")

        st.markdown("#### B. NSE bhavcopy upload (most reliable)")
        bh = st.file_uploader("CM bhavcopy CSV/ZIP (old `cmDDMMMYYYYbhav.csv` or new UDiFF `BhavCopy_NSE_CM_…csv`)",
                              type=["csv", "zip"], accept_multiple_files=True, key="bhav")
        if bh and st.button("Import bhavcopy file(s)"):
            total = 0
            for f in bh:
                try:
                    df = parse_bhavcopy(f.getvalue(), f.name, syms)
                    total += merge_prices(state, df, "bhavcopy")
                    flash("success", f"✅ {f.name}: {df['date'].iloc[0]} — {len(df)} stocks")
                except Exception as e:
                    flash("error", f"{f.name}: {e}")
            persist(state, f"bhavcopy import ({total})", push=True)
            st.rerun()

        st.markdown("#### C. Manual entry / corrections")
        nxt_dates = project_sessions(res["dates"][-1], 1)
        with st.form("add_day"):
            c1, c2 = st.columns([1, 3])
            d_new = c1.date_input("Session date", value=datetime.strptime(nxt_dates[0], "%Y-%m-%d").date())
            c2.caption("Enter closes (and optionally Day-1 opens) for a session. Leave blank to skip a stock.")
            base = pd.DataFrame({"Symbol": syms + [BENCHMARK_SYMBOL],
                                 "Open": [None] * (len(syms) + 1), "Close": [None] * (len(syms) + 1)})
            ed = st.data_editor(base, hide_index=True, width="stretch", disabled=["Symbol"],
                                column_config={"Open": st.column_config.NumberColumn(format="%.2f"),
                                               "Close": st.column_config.NumberColumn(format="%.2f")})
            if st.form_submit_button("💾 Save session"):
                ed = ed.dropna(subset=["Close"])
                if ed.empty:
                    st.warning("No closes entered.")
                else:
                    df = pd.DataFrame({"date": d_new.strftime("%Y-%m-%d"), "symbol": ed["Symbol"],
                                       "open": ed["Open"], "close": ed["Close"]})
                    n = merge_prices(state, df, "manual")
                    persist(state, f"manual {d_new}", push=True)
                    flash("success", f"Saved {n} closes for {d_new}.")
                    st.rerun()

        st.markdown("##### Edit stored closes")
        dates = res["dates"][1:]
        if dates:
            grid = pd.DataFrame(index=syms, columns=dates, dtype=float)
            for s_ in syms:
                for d in dates:
                    c = state["prices"].get(s_, {}).get(d)
                    grid.loc[s_, d] = c["close"] if c else None
            grid.columns = [f"D{i + 1} {d}" for i, d in enumerate(dates)]
            eg = st.data_editor(grid, width="stretch", key="grid_edit")
            if st.button("💾 Save edits to closes"):
                changed = 0
                for i, d in enumerate(dates):
                    col = f"D{i + 1} {d}"
                    for s_ in syms:
                        v = eg.loc[s_, col]
                        old = grid.loc[s_, col]
                        if pd.notna(v) and (pd.isna(old) or abs(float(v) - float(old)) > 1e-9):
                            cell = state["prices"].setdefault(s_, {}).setdefault(d, {"open": None})
                            cell.update({"close": float(v), "src": "manual"})
                            changed += 1
                persist(state, f"edited {changed} closes", push=True)
                flash("success", f"Updated {changed} values.")
                st.rerun()
        else:
            st.caption("No sessions after Day 0 yet.")

        st.markdown("##### Actual fill prices (optional)")
        st.caption("If your broker filled at a different price than the Day-1 open, enter it here. It overrides the entry.")
        ent = pd.DataFrame({"Symbol": syms,
                            "Entry used": [float(res["entry"][s_]) for s_ in syms],
                            "Basis": [res["table"].set_index("Symbol").loc[s_, "Entry basis"] for s_ in syms],
                            "Your fill": [state.get("entry_override", {}).get(s_) for s_ in syms]})
        ent_ed = st.data_editor(ent, hide_index=True, disabled=["Symbol", "Entry used", "Basis"],
                                width="stretch", key="fill_edit",
                                column_config={"Your fill": st.column_config.NumberColumn(format="%.2f")})
        if st.button("💾 Save fill prices"):
            state["entry_override"] = {sy: float(v) for sy, v in zip(ent_ed["Symbol"], ent_ed["Your fill"]) if pd.notna(v)}
            persist(state, "fill prices", push=True)
            st.rerun()

        with st.expander("Data sources per cell"):
            st.dataframe(res["sources"].iloc[:, : k["day"] + 1], width="stretch")

        st.markdown("##### Corporate actions (bonus / split / dividend)")
        st.caption("Found automatically from Yahoo, or flagged when a close drops overnight by a bonus/split ratio. "
                   "A split/bonus divides every earlier price by the ratio and multiplies the quantity, so the "
                   "return stays continuous. Set a wrong one to *rejected*; add any that were missed.")
        cas = state.get("corp_actions") or []
        cadf = pd.DataFrame(cas if cas else [], columns=["symbol", "ex_date", "kind", "ratio", "amount", "status",
                                                         "source", "note"])
        caed = st.data_editor(
            cadf, num_rows="dynamic", hide_index=True, width="stretch", key="ca_ed",
            column_config={
                "symbol": st.column_config.SelectboxColumn("Symbol", options=syms, required=True),
                "ex_date": st.column_config.TextColumn("Ex-date (YYYY-MM-DD)", required=True),
                "kind": st.column_config.SelectboxColumn("Type", options=["split", "dividend"], required=True),
                "ratio": st.column_config.NumberColumn("Ratio (1:1 bonus = 2)", format="%.3f"),
                "amount": st.column_config.NumberColumn("Dividend ₹/share", format="%.2f"),
                "status": st.column_config.SelectboxColumn("Status", options=["confirmed", "suspected", "rejected"]),
                "source": st.column_config.TextColumn("Source", disabled=True),
                "note": st.column_config.TextColumn("Note")})
        if st.button("💾 Save corporate actions"):
            rows = []
            for r in caed.to_dict("records"):
                if not r.get("symbol") or not r.get("ex_date"):
                    continue
                r = {k_: v_ for k_, v_ in r.items() if not (isinstance(v_, float) and pd.isna(v_)) and v_ is not None}
                r.setdefault("kind", "split")
                r.setdefault("status", "confirmed")
                r.setdefault("source", "manual")
                rows.append(r)
            state["corp_actions"] = sorted(rows, key=lambda e: (e["ex_date"], e["symbol"]))
            persist(state, "corporate actions", push=True)
            st.rerun()

# =========================================================================== #
# ③ DASHBOARD
# =========================================================================== #
with tab_dash:
    if not state:
        st.info("Create or restore a batch first.")
    else:
        k = res["kpi"]
        t = res["table"]
        st.markdown(f"<style>:root{{--wash:#f8fafc;--line:#e2e8f0;--sub:#64748b;--amber:#C9860A;--red:#D64545}}"
                    f"{TIMELINE_CSS}</style>", unsafe_allow_html=True)
        st.markdown(f"**Progress — {k['progress']:.0%} · {k['days_left']} sessions left · "
                    f"status as of {k['today']}**")
        st.markdown(timeline_html(res), unsafe_allow_html=True)
        st.write("")
        port = res["portfolio"]
        m = st.columns(6)
        metric(m[0], "Current day", f"{k['day']} / {HOLD}", k["phase"], neutral=True)
        metric(m[1], "Invested", fmt_inr(k["invested"]), "Qty × entry", neutral=True)
        metric(m[2], "Market value", fmt_inr(k["value"]),
               (fmt_pct(k["today_chg"]) + " today") if k["today_chg"] is not None else None,
               spark=port["Value"].iloc[1:].round(0) if k["day"] >= 2 else None)
        metric(m[3], "Gross P&L", fmt_inr(k["gross_pnl"], True), fmt_pct(k["gross_ret"]),
               spark=port["P&L"].round(0) if k["day"] >= 2 else None)
        metric(m[4], "Net P&L (est.)", fmt_inr(k["net_pnl"], True), fmt_pct(k["net_ret"]),
               help=f"After estimated round-trip costs of {fmt_inr(k['est_costs'])}")
        metric(m[5], "Alpha vs Nifty", fmt_pct(k["alpha"]), f"Nifty {fmt_pct(k['nifty_ret'])}", neutral=True)
        m = st.columns(6)
        metric(m[0], "Winners / losers", f"{k['winners']} / {k['losers']}", f"of {len(t)} stocks", neutral=True)
        metric(m[1], "Best stock", k["best"][0], fmt_pct(float(k["best"][1])))
        metric(m[2], "Worst stock", k["worst"][0], fmt_pct(float(k["worst"][1])))
        metric(m[3], "Max drawdown", fmt_pct(k["max_dd"]), "peak → trough", neutral=True)
        metric(m[4], "Best / worst day", fmt_pct(k["best_day"]), f"worst {fmt_pct(k['worst_day'])}", neutral=True)
        metric(m[5], "Exit date (proj.)", k["exit_date"] or "—", f"{k['days_left']} sessions left", neutral=True)

        if k["day"] == 20:
            st.warning("⏰ **Exit reminder** — tomorrow is Day 21. Place sell orders for all 10 stocks.")
        elif k["day"] >= HOLD:
            st.success("🏁 Day 21 reached — the batch is complete. Final numbers below.")

        cfg = {"displaylogo": False}
        st.plotly_chart(charts.fig_equity(res), width="stretch", config=cfg)
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.fig_stock_bars(res), width="stretch", config=cfg)
        c2.plotly_chart(charts.fig_contribution(res), width="stretch", config=cfg)

        st.markdown("#### Stock league table")
        show = t.sort_values("Return %", ascending=False)[
            ["Symbol", "Qty", "Entry", "Last close", "Day chg %", "Return %", "P&L", "Max gain %", "Max loss %",
             "Weight %", "Contribution %", "Entry basis"]]
        st.dataframe(
            show.style.format({"Entry": "{:,.2f}", "Last close": "{:,.2f}", "Day chg %": "{:+.2f}%",
                               "Return %": "{:+.2f}%", "P&L": "₹{:,.0f}", "Max gain %": "{:+.2f}%",
                               "Max loss %": "{:+.2f}%", "Weight %": "{:.1f}%", "Contribution %": "{:+.2f}%"})
            .map(lambda v: "color:#1F9D63;font-weight:600" if isinstance(v, (int, float)) and v > 0 else
                 ("color:#D64545;font-weight:600" if isinstance(v, (int, float)) and v < 0 else ""),
                 subset=["Day chg %", "Return %", "P&L", "Contribution %"]),
            hide_index=True, width="stretch")

        st.plotly_chart(charts.fig_heatmap(res), width="stretch", config=cfg)
        st.plotly_chart(charts.fig_paths(res), width="stretch", config=cfg)
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts.fig_drawdown(res), width="stretch", config=cfg)
        c2.plotly_chart(charts.fig_daily(res), width="stretch", config=cfg)

        with st.expander("Daily closes grid (Day 0 → today)"):
            cl = res["closes"].iloc[:, : k["day"] + 1].copy()
            cl.columns = [f"{c}\n{d[5:]}" for c, d in zip(cl.columns, res["dates"])]
            st.dataframe(cl.style.format("{:,.2f}"), width="stretch")
        with st.expander("Portfolio path table"):
            st.dataframe(res["portfolio"].style.format({"Value": "₹{:,.0f}", "P&L": "₹{:,.0f}",
                                                         "Return %": "{:+.2f}%", "Daily %": "{:+.2f}%",
                                                         "Drawdown %": "{:.2f}%", "Nifty %": "{:+.2f}%"},
                                                        na_rep="—"), hide_index=True, width="stretch")

# =========================================================================== #
# ④ RESEARCH & SENTIMENT
# =========================================================================== #
with tab_news:
    if not state:
        st.info("Create or restore a batch first.")
    else:
        b = state["batch"]
        syms = [x["symbol"] for x in b["stocks"]]
        brief = state.get("research")
        min_score = st.session_state.get("min_score", 0.2)

        # ---------- 1. build the stock-by-stock brief ----------
        st.markdown("#### 1 · Stock-by-stock brief")
        ai_key = None
        try:
            ai_key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            pass
        src_opts = ["📝 Paste my research notes", "⚙️ Auto-generate (price data + news)", "🤖 Claude + web search"]
        cur_method = {"notes": 0, "auto": 1, "ai": 2}.get((brief or {}).get("method"), 0)
        how = st.radio("Source of the views", src_opts, index=cur_method, horizontal=True, label_visibility="collapsed")

        if how == src_opts[0]:
            st.caption("Paste notes in the *Stock by stock* format: a heading line per stock such as "
                       "`1. Laurus Labs (LAURUSLABS): strongest, bullish`, then one sentence per line with the source "
                       "name alone on the next line, and optionally a `Rank / Stock / View / Why` shortlist table.")
            sample = ""
            sp = Path(__file__).parent / "samples" / f"research_notes_{b['batch_id']}.txt"
            if sp.exists():
                sample = sp.read_text(encoding="utf-8")
            txt = st.text_area("Research notes", value=state.get("research_notes") or sample, height=260)
            if st.button("✅ Apply notes", type="primary"):
                try:
                    nb = parse_notes(txt, b)
                    if not nb["stocks"]:
                        st.error("No stock headings found. Expected lines like `1. Name (SYMBOL): view`.")
                    else:
                        state["research"], state["research_notes"] = nb, txt
                        persist(state, "research notes", push=True)
                        flash("success", f"Loaded research for {len(nb['stocks'])} stocks"
                              + (f" · missing: {', '.join(nb['missing'])}" if nb["missing"] else ""))
                        st.rerun()
                except Exception as e:
                    st.error(f"Could not parse the notes: {e}")
        elif how == src_opts[1]:
            st.caption("Builds views from the batch's momentum, distance from high, volatility, liquidity, P/E "
                       "(Yahoo) and the themes in fetched headlines (results, guidance, orders, broker calls, "
                       "fundraises, index inclusion…). Fetch news first for richer cards.")
            c1, c2 = st.columns(2)
            if c1.button("⚙️ Generate brief", type="primary", width="stretch"):
                with st.spinner("Fetching P/E and sector for each stock…"):
                    fund = state.get("fundamentals") or {}
                    for s_ in syms:
                        if not fund.get(s_):
                            fund[s_] = fetch_fundamentals(s_)
                    state["fundamentals"] = fund
                state["research"] = auto_research(state, res)
                persist(state, "auto research", push=True)
                st.rerun()
            c2.caption("Tip: run it again after each news refresh — the auto brief also reads the live return "
                       "since entry.")
        else:
            if not ai_key:
                st.warning("Add `ANTHROPIC_API_KEY` to the app's secrets to enable this. Claude will search the web "
                           "for each stock and write the brief in the same format as your notes, with source links.")
            else:
                c1, c2 = st.columns([1, 2])
                try:
                    model = st.secrets.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
                except Exception:
                    model = "claude-sonnet-4-5"
                c2.caption(f"Model: `{model}` · about 1–3 minutes and ~25 web searches per run.")
                if c1.button("🤖 Research with Claude", type="primary", width="stretch"):
                    with st.spinner("Claude is researching all 10 stocks…"):
                        try:
                            state["research"] = ai_research(state, ai_key, model)
                            persist(state, "AI research", push=True)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

        if brief:
            with st.expander("✏️ Adjust views, ranking and shortlist reasons"):
                ed = pd.DataFrame([{"Rank": i + 1, "Symbol": sy, "View": brief["stocks"][sy]["view"],
                                    "Why": brief["stocks"][sy]["why"]}
                                   for i, sy in enumerate(brief["shortlist"]) if sy in brief["stocks"]])
                ed2 = st.data_editor(ed, hide_index=True, width="stretch", disabled=["Symbol"], key="brief_ed",
                                     column_config={"Rank": st.column_config.NumberColumn(min_value=1, step=1),
                                                    "Why": st.column_config.TextColumn(width="large")})
                if st.button("💾 Save changes"):
                    for r in ed2.itertuples(index=False):
                        stk = brief["stocks"][r.Symbol]
                        stk["view"], stk["why"] = r.View, r.Why
                        stk.pop("short_view", None)
                        stk["view_score"], stk["tone"] = view_score(r.View)
                    brief["shortlist"] = list(ed2.sort_values("Rank")["Symbol"])
                    state["research"] = brief
                    persist(state, "edited views", push=True)
                    st.rerun()

        # ---------- 2. news ----------
        st.markdown("#### 2 · Headlines & sentiment")
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        days = c1.slider("Look-back (days)", 1, 30, 7)
        min_score = c2.slider("Positive threshold", 0.05, 0.8, min_score, 0.05)
        st.session_state["min_score"] = min_score
        inc_mkt = c3.checkbox("Include broad-market news", True)
        with st.expander("Company names used in news search"):
            names = state.get("names") or {s_: s_ for s_ in syms}
            ned = st.data_editor(pd.DataFrame({"Symbol": syms, "Search name": [names.get(s_, s_) for s_ in syms]}),
                                 hide_index=True, disabled=["Symbol"], width="stretch", key="names_ed")
            if st.button("Save names"):
                state["names"] = dict(zip(ned["Symbol"], ned["Search name"]))
                save_state(state)
                st.rerun()
        if c4.button("📰 Fetch news & score", type="primary", width="stretch"):
            bar = st.progress(0.0, text="Starting…")
            state["news"] = collect_news(syms, state.get("names"), days, inc_mkt,
                                         progress=lambda p, t: bar.progress(min(p, 1.0), text=t))
            if (state.get("research") or {}).get("method") == "auto":
                state["research"] = auto_research(state, res)
            persist(state, "news refresh", push=True)
            st.rerun()

        news = state.get("news")
        if news:
            for e in news.get("errors", [])[:4]:
                st.caption(f"⚠️ {e}")
            items = pd.DataFrame(news["items"])
            m = st.columns(5)
            m[0].metric("Headlines", len(items))
            if not items.empty:
                m[1].metric("Positive", int((items["score"] >= min_score).sum()))
                m[2].metric("Negative", int((items["label"] == "Negative").sum()))
                m[3].metric("Average score", f"{items['score'].mean():+.2f}")
            m[4].metric("Fetched", news["fetched"][5:], help=news["fetched"])
            with st.expander("Headline table & sentiment mix"):
                summ = pd.DataFrame(sentiment_summary(news, syms))
                st.plotly_chart(charts.fig_sentiment(summ.to_dict("records")), width="stretch")
                if not items.empty:
                    pos = items[items["score"] >= min_score].sort_values(["symbol", "score"], ascending=[True, False])
                    st.dataframe(pos[["symbol", "published", "title", "source", "score", "link"]],
                                 column_config={"link": st.column_config.LinkColumn("Link", display_text="open ↗"),
                                                "score": st.column_config.ProgressColumn("Score", min_value=0,
                                                                                         max_value=1, format="%.2f"),
                                                "title": st.column_config.TextColumn("Headline", width="large")},
                                 hide_index=True, width="stretch", height=400)
        else:
            st.caption("No headlines yet — **Fetch news & score** adds a positive-news feed and news tone to every card.")

        # ---------- 3. the report ----------
        st.markdown("#### 3 · Research & sentiment report")
        rhtml = research_html(state, res, min_score)
        st.download_button("⬇️ Download research & sentiment HTML", rhtml.encode("utf-8"), type="primary",
                           file_name=f"SwingScope_{b['batch_id']}_research_sentiment.html", mime="text/html")
        if not brief:
            st.caption("Showing an auto-generated preview — pick a source above to make it yours.")
        embed_html(rhtml, 1400)

# =========================================================================== #
# ⑤ DOWNLOADS
# =========================================================================== #
with tab_dl:
    if not state:
        st.info("Create or restore a batch first.")
    else:
        b = state["batch"]
        k = res["kpi"]
        stamp = f"D{k['day']:02d}_{k['last_session']}"
        st.subheader(f"Downloads — Day {k['day']} ({k['last_session']})")
        xbytes = build_workbook(state, res)
        dhtml = dashboard_html(state, res)
        c1, c2, c3, c4 = st.columns(4)
        c1.download_button("📗 Excel tracker (.xlsx)", xbytes, type="primary", width="stretch",
                           file_name=f"SwingScope_{b['batch_id']}_{stamp}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c2.download_button("📊 Dashboard (.html)", dhtml.encode("utf-8"), width="stretch",
                           file_name=f"SwingScope_{b['batch_id']}_{stamp}_dashboard.html", mime="text/html")
        c3.download_button("🧭 Research & sentiment (.html)",
                           research_html(state, res, st.session_state.get("min_score", 0.2)).encode(),
                           width="stretch", file_name=f"SwingScope_{b['batch_id']}_{stamp}_research.html",
                           mime="text/html")
        c4.download_button("🧾 State backup (.json)", json.dumps(state, default=str).encode(),
                           width="stretch", file_name=f"SwingScope_{b['batch_id']}_state.json",
                           mime="application/json")
        st.caption("The Excel contains: Dashboard · Daily Closes (Day 0–21) · Returns % · P&L · Portfolio Path · "
                   "Batch Info · Research · News & Sentiment · a hidden state sheet so you can restore from it later.")
        st.markdown("#### 📨 Send to Telegram")
        if not telegram.enabled(st.secrets):
            st.info("Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to the app's secrets to send from here. "
                    "The scheduled day-end send (18:05 IST) uses the same two values as GitHub Actions secrets — "
                    "see the README.")
        else:
            tc1, tc2, tc3 = st.columns([1, 1, 2])
            if tc1.button("📤 Send today's report", type="primary", width="stretch"):
                with st.spinner("Sending to Telegram…"):
                    try:
                        _, paths = rebuild_outputs(state, st.session_state.get("min_score", 0.2))
                        log = telegram.send_report(state, res, [paths["xlsx"], paths["dashboard"], paths["research"]],
                                                   secrets=st.secrets, stamp=stamp)
                        state["telegram_sent"] = k["last_session"]
                        save_state(state)
                        st.success(" · ".join(log))
                    except Exception as e:
                        st.error(str(e))
            if tc2.button("🔔 Send test message", width="stretch"):
                try:
                    telegram.send_text("✅ SwingScope tracker: Telegram connection works.", secrets=st.secrets)
                    st.success("Test message sent.")
                except Exception as e:
                    st.error(str(e))
            tc3.caption(f"Last scheduled send: session {state.get('telegram_sent') or '—'}")
        with st.expander("Preview the Telegram summary text"):
            st.code(telegram.summary_message(state, res), language="html")
        with st.expander("Preview dashboard HTML", expanded=False):
            embed_html(dhtml, 1000)
        st.caption(f"Files are also saved on the server in `{output_paths(b['batch_id'])['xlsx'].parent}`.")
