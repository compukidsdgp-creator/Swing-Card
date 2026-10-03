"""Standalone HTML exports: 21-day dashboard and positive-news/sentiment page."""
from __future__ import annotations

import html as H
from datetime import datetime

import pandas as pd

from . import charts
from .news import sentiment_summary
from .tracker import HOLD

TIMELINE_CSS = """
.tl{display:grid;grid-template-columns:repeat(22,1fr);gap:4px;margin-top:10px}
.tl div{height:34px;border-radius:6px;background:var(--wash);border:1px solid var(--line);font-size:10.5px;
display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--sub)}
.tl .done{background:#dbe4ff;border-color:#b4c3ff;color:#1e3a8a}.tl .cur{background:var(--amber);color:#fff;
border-color:var(--amber);font-weight:700}.tl .ex{border:2px solid var(--red)}
@media(prefers-color-scheme:dark){.tl .done{background:#1e2a55;border-color:#2f4bd8;color:#c7d2fe}}
"""

CSS = """
:root{--bg:#f5f7fb;--card:#fff;--ink:#0f172a;--sub:#64748b;--line:#e2e8f0;--navy:#0B1F3A;--blue:#2F4BD8;
--green:#1F9D63;--red:#D64545;--amber:#C9860A;--wash:#f8fafc}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--sub:#8b949e;--line:#30363d;
--wash:#1c2128}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 Inter,"Segoe UI",Roboto,system-ui,sans-serif}
header{background:linear-gradient(120deg,#0B1F3A,#1E3A66 60%,#2F4BD8);color:#fff;padding:26px 32px}
header h1{margin:0;font-size:24px;letter-spacing:.2px}header p{margin:4px 0 0;color:#c9d3e6;font-size:13px}
.wrap{max-width:1320px;margin:0 auto;padding:22px 24px 40px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;
background:rgba(255,255,255,.15);color:#fff;margin-right:6px}
.grid{display:grid;gap:14px}.k6{grid-template-columns:repeat(6,1fr)}.c2{grid-template-columns:1fr 1fr}
@media(max-width:1000px){.k6{grid-template-columns:repeat(3,1fr)}.c2{grid-template-columns:1fr}}
@media(max-width:560px){.k6{grid-template-columns:repeat(2,1fr)}.wrap{padding:16px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
box-shadow:0 1px 2px rgba(15,23,42,.04)}
.kpi .l{font-size:11px;font-weight:700;letter-spacing:.6px;color:var(--sub);text-transform:uppercase}
.kpi .v{font-size:22px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .n{font-size:11.5px;color:var(--sub)}
.pos{color:var(--green)}.neg{color:var(--red)}
h2{font-size:16px;margin:26px 0 10px;color:var(--ink)}
.tl{display:grid;grid-template-columns:repeat(22,1fr);gap:4px;margin-top:10px}
.tl div{height:34px;border-radius:6px;background:var(--wash);border:1px solid var(--line);font-size:10.5px;
display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--sub)}
.tl .done{background:#dbe4ff;border-color:#b4c3ff;color:#1e3a8a}.tl .cur{background:var(--amber);color:#fff;
border-color:var(--amber);font-weight:700}.tl .ex{border:2px solid var(--red)}
@media(prefers-color-scheme:dark){.tl .done{background:#1e2a55;border-color:#2f4bd8;color:#c7d2fe}}
.bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden}.bar i{display:block;height:100%;
background:linear-gradient(90deg,#2F4BD8,#0E7C86)}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{background:var(--navy);color:#fff;font-weight:600;padding:8px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}
tr:nth-child(even) td{background:var(--wash)}.scroll{overflow-x:auto}
footer{color:var(--sub);font-size:12px;margin-top:28px;text-align:center}
.news{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.item{border-left:4px solid var(--green)}.item a{color:var(--ink);text-decoration:none;font-weight:600}
.item a:hover{color:var(--blue)}.meta{font-size:12px;color:var(--sub);margin-top:6px;display:flex;gap:10px;flex-wrap:wrap}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;background:#e8f7ef;color:#137a4b;font-size:11.5px;font-weight:700}
.sym{background:#e0e7ff;color:#1e3a8a}
@media(prefers-color-scheme:dark){.chip{background:#12351f;color:#7ee2a8}.sym{background:#1e2a55;color:#c7d2fe}}
.warn{background:#fff7e6;border:1px solid #f5d38a;color:#7a5200;padding:10px 14px;border-radius:10px;margin-top:12px}
"""


def _sign(v, pct=True, money=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "<span>—</span>"
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    if money:
        txt = f"{'+' if v > 0 else '−' if v < 0 else ''}₹{abs(v):,.0f}"
    else:
        txt = f"{v:+.2f}%" if pct else f"{v:+.2f}"
    return f'<span class="{cls}">{txt}</span>'


def _avg(v):
    return "—" if v is None else f"{v:+.2f}"


def _kpi(label, value_html, note=""):
    return f'<div class="card kpi"><div class="l">{label}</div><div class="v">{value_html}</div><div class="n">{note}</div></div>'


def _fig_html(fig, first=False):
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if first else False,
                       config={"displaylogo": False, "responsive": True})


def timeline_html(res: dict) -> str:
    k = res["kpi"]
    cells = []
    for d in range(HOLD + 1):
        date = res["all_dates"][d] if d < len(res["all_dates"]) else ""
        cls = "cur" if d == k["day"] else ("done" if d < k["day"] else "")
        if d == HOLD:
            cls += " ex"
        lab = "Sig" if d == 0 else ("Buy" if d == 1 else ("Sell" if d == HOLD else f"D{d}"))
        cells.append(f'<div class="{cls}" title="Day {d} · {date}"><b>{lab}</b><span>{date[5:]}</span></div>')
    return f'<div class="tl">{"".join(cells)}</div>'


def dashboard_html(state: dict, res: dict) -> str:
    b, k = state["batch"], res["kpi"]
    t = res["table"].sort_values("Return %", ascending=False)
    kpis = [
        _kpi("Status", f"Day {k['day']}/{HOLD}", H.escape(k["phase"])),
        _kpi("Invested", f"₹{k['invested']:,.0f}", "Qty × entry"),
        _kpi("Market value", f"₹{k['value']:,.0f}", f"as of {k['last_session']}"),
        _kpi("Gross P&L", _sign(k["gross_pnl"], money=True), _sign(k["gross_ret"])),
        _kpi("Net P&L (est.)", _sign(k["net_pnl"], money=True), f"after ₹{k['est_costs']:,.0f} costs"),
        _kpi("vs Nifty 50", _sign(k["alpha"]), f"Nifty {_sign(k['nifty_ret'])}"),
        _kpi("Today", _sign(k["today_chg"]), "portfolio daily change"),
        _kpi("Winners / Losers", f"{k['winners']} / {k['losers']}", f"of {len(t)} stocks"),
        _kpi("Best stock", H.escape(str(k["best"][0])), _sign(float(k["best"][1]))),
        _kpi("Worst stock", H.escape(str(k["worst"][0])), _sign(float(k["worst"][1]))),
        _kpi("Max drawdown", _sign(k["max_dd"]), "peak to trough"),
        _kpi("Sessions left", str(k["days_left"]), f"exit ~{k['exit_date']}"),
    ]
    rows = "".join(
        f"<tr><td><b>{r['Symbol']}</b></td><td>{r['Qty']}</td><td>{r['Entry']:,.2f}</td><td>{r['Last close']:,.2f}</td>"
        f"<td>{_sign(r['Day chg %'])}</td><td>{_sign(r['Return %'])}</td><td>{_sign(r['P&L'], money=True)}</td>"
        f"<td>{_sign(r['Max gain %'])}</td><td>{_sign(r['Max loss %'])}</td><td>{r['Weight %']:.1f}%</td>"
        f"<td>{_sign(r['Contribution %'])}</td><td style='color:var(--sub)'>{H.escape(r['Entry basis'])}</td></tr>"
        for _, r in t.iterrows())
    closes = res["closes"].iloc[:, : k["day"] + 1]
    ch = "".join(f"<th>D{i}<br><small>{res['dates'][i][5:]}</small></th>" for i in range(closes.shape[1]))
    cr = "".join(
        f"<tr><td><b>{sym}</b></td>" + "".join(f"<td>{v:,.2f}</td>" if pd.notna(v) else "<td>—</td>" for v in closes.loc[sym])
        + "</tr>" for sym in closes.index)
    figs = [charts.fig_equity(res), charts.fig_stock_bars(res), charts.fig_contribution(res),
            charts.fig_heatmap(res), charts.fig_paths(res), charts.fig_drawdown(res), charts.fig_daily(res)]
    stale = (f'<div class="warn">Latest session in the tracker is {k["last_session"]}; '
             f'today is {k["today"]}. The daily update (18:05 IST) has not picked up the latest session yet.</div>') if k["stale"] else ""
    pct = k["progress"] * 100
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SwingScope {b['batch_id']} — 21-Day Dashboard</title>
<style>{CSS}</style></head><body>
<header><h1>SwingScope Momentum Batch {b['batch_id']}</h1>
<p><span class="badge">Day {k['day']} of {HOLD}</span><span class="badge">{H.escape(k['phase'])}</span>
<span class="badge">Regime: {H.escape(b.get('regime') or '—')}</span>
Signal {b['signal_date']} · Exit ~{k['exit_date']} · Report generated {datetime.now():%d %b %Y, %H:%M}</p></header>
<div class="wrap">
<div class="card"><div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px">
<b>21-session progress</b><span>{pct:.0f}% · {k['days_left']} sessions left</span></div>
<div class="bar"><i style="width:{pct:.1f}%"></i></div>{timeline_html(res)}</div>{stale}
<h2>Key metrics</h2><div class="grid k6">{''.join(kpis)}</div>
<h2>Performance</h2><div class="card">{_fig_html(figs[0], first=True)}</div>
<div class="grid c2" style="margin-top:14px"><div class="card">{_fig_html(figs[1])}</div><div class="card">{_fig_html(figs[2])}</div></div>
<h2>Stock league table</h2><div class="card scroll"><table><thead><tr><th>Symbol</th><th>Qty</th><th>Entry ₹</th>
<th>Last ₹</th><th>Day chg</th><th>Return</th><th>P&amp;L</th><th>Max gain</th><th>Max loss</th><th>Weight</th>
<th>Contrib.</th><th>Entry basis</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Path analysis</h2><div class="card">{_fig_html(figs[3])}</div>
<div class="card" style="margin-top:14px">{_fig_html(figs[4])}</div>
<div class="grid c2" style="margin-top:14px"><div class="card">{_fig_html(figs[5])}</div><div class="card">{_fig_html(figs[6])}</div></div>
<h2>Daily closes</h2><div class="card scroll"><table><thead><tr><th>Symbol</th>{ch}</tr></thead><tbody>{cr}</tbody></table></div>
<footer>Entry = Day-1 open unless a manual fill was entered. Returns are gross; net P&amp;L deducts the batch's estimated
{b.get('cost_pct')}% round-trip cost. Nifty 50 is measured from the Day-0 close. Research tracking only — not investment advice.</footer>
</div></body></html>"""


def news_html(state: dict, min_score: float = 0.2) -> str:
    b = state["batch"]
    news = state.get("news") or {"items": [], "fetched": "—"}
    syms = [s["symbol"] for s in b["stocks"]]
    positives = sorted([i for i in news["items"] if i["score"] >= min_score],
                       key=lambda x: (-x["score"], x["published"]))
    summ = sentiment_summary(news, syms)
    fig = charts.fig_sentiment(summ) if news["items"] else None
    srows = "".join(
        f"<tr><td><b>{r['symbol']}</b></td><td>{r['articles']}</td><td class='pos'>{r['positive']}</td>"
        f"<td>{r['neutral']}</td><td class='neg'>{r['negative']}</td>"
        f"<td>{_avg(r['avg_score'])}</td><td>{r['mood']}</td></tr>" for r in summ)
    cards = []
    for sym in ["MARKET"] + syms:
        grp = [i for i in positives if i["symbol"] == sym]
        if not grp:
            continue
        name = "Broad market" if sym == "MARKET" else sym
        cards.append(f'<h3 style="margin:18px 0 8px;font-size:14px">{H.escape(name)} '
                     f'<span class="chip">{len(grp)} positive</span></h3><div class="news">')
        for it in grp:
            cards.append(
                f'<div class="card item"><a href="{H.escape(it["link"])}" target="_blank" rel="noopener">{H.escape(it["title"])}</a>'
                f'<div class="meta"><span class="chip">+{it["score"]:.2f}</span><span>{H.escape(it.get("source", ""))}</span>'
                f'<span>{it.get("published", "")}</span></div></div>')
        cards.append("</div>")
    total = len(news["items"])
    pos_n = sum(i["label"] == "Positive" for i in news["items"])
    neg_n = sum(i["label"] == "Negative" for i in news["items"])
    avg = sum(i["score"] for i in news["items"]) / total if total else 0
    warn = "".join(f'<div class="warn">{H.escape(e)}</div>' for e in news.get("errors", [])[:5])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SwingScope {b['batch_id']} — Positive News</title>
<style>{CSS}</style></head><body>
<header><h1>Positive News &amp; Sentiment</h1><p>Batch {b['batch_id']} · {len(syms)} stocks + broad market ·
last {news.get('days', 7)} days · fetched {news.get('fetched')}</p></header><div class="wrap">{warn}
<div class="grid k6">{_kpi('Headlines scanned', str(total))}{_kpi('Positive', f'<span class="pos">{pos_n}</span>')}
{_kpi('Negative', f'<span class="neg">{neg_n}</span>')}{_kpi('Neutral', str(total - pos_n - neg_n))}
{_kpi('Average score', _sign(avg, pct=False), '−1 bearish … +1 bullish')}{_kpi('Shown below', str(len(positives)), f'score ≥ {min_score:+.2f}')}</div>
<h2>Sentiment by stock</h2><div class="grid c2"><div class="card">{_fig_html(fig, first=True) if fig else 'No news yet.'}</div>
<div class="card scroll"><table><thead><tr><th>Symbol</th><th>Articles</th><th>Pos</th><th>Neu</th><th>Neg</th>
<th>Avg</th><th>Mood</th></tr></thead><tbody>{srows}</tbody></table></div></div>
<h2>Positive headlines ({len(positives)})</h2>{''.join(cards) or '<p>No positive headlines in this window.</p>'}
<footer>Sentiment = VADER compound score on the headline, with a finance-specific lexicon (upgrade, order win, beats,
surge …). Headlines come from Google News RSS and Yahoo Finance. Automated scoring can misread context — read the article.</footer>
</div></body></html>"""
