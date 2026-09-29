"""Research brief HTML: stock-by-stock views, ranked shortlist, call scorecard and positive news."""
from __future__ import annotations

import html as H
from datetime import datetime

import plotly.graph_objects as go

from .news import sentiment_summary
from .research import VIEW_STYLE, scorecard

TONE_COLOR = {"strong-bull": "#0f7a4a", "bull": "#1f9d63", "mod-bull": "#5cc08a", "spec": "#d99a1e",
              "neutral": "#94a3b8", "mod-bear": "#e07b7b", "bear": "#d64545"}

CSS = """
:root{--bg:#f4f6fa;--card:#fff;--ink:#0f172a;--sub:#5b6474;--faint:#94a3b8;--line:#e3e8ef;--wash:#f8fafc;
--navy:#0B1F3A;--blue:#2F4BD8;--green:#1F9D63;--red:#D64545;--amber:#C9860A}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--sub:#9aa4b2;--faint:#6b7480;
--line:#2b313a;--wash:#1b2129}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,"Segoe UI",Roboto,system-ui,sans-serif}
a{color:inherit}
header{background:radial-gradient(1200px 300px at 90% -40%,#3b5bff55,transparent),linear-gradient(120deg,#08162b,#13305a 55%,#2440c4);
color:#fff;padding:28px 0 26px}
.wrap{max-width:1280px;margin:0 auto;padding:0 24px}
header h1{margin:6px 0 4px;font-size:26px;letter-spacing:.2px}
header .eyebrow{font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:#9fb4ff;font-weight:700}
header p{margin:0;color:#c9d3e6;font-size:13px}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.hb{background:rgba(255,255,255,.14);color:#fff;margin:10px 6px 0 0}
main{padding:22px 0 40px}
.grid{display:grid;gap:14px}.g4{grid-template-columns:1.2fr 1fr 1fr 1fr}.g2{grid-template-columns:1fr 1fr}
@media(max-width:1000px){.g4{grid-template-columns:1fr 1fr}.g2{grid-template-columns:1fr}}
@media(max-width:560px){.g4{grid-template-columns:1fr}.wrap{padding:0 14px}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;
box-shadow:0 1px 2px rgba(15,23,42,.04)}
.lbl{font-size:11px;font-weight:700;letter-spacing:.7px;color:var(--sub);text-transform:uppercase}
.big{font-size:26px;font-weight:750;font-variant-numeric:tabular-nums;margin-top:2px}
.note{font-size:12px;color:var(--sub)}
h2{font-size:17px;margin:30px 0 12px;display:flex;align-items:center;gap:10px}
h2 .count{font-size:12px;color:var(--sub);font-weight:600}
.dist{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:10px 0 8px;background:var(--line)}
.dist i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:12px;color:var(--sub)}
.legend b{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:var(--sub);font-weight:700;text-align:left;
padding:10px 10px;border-bottom:2px solid var(--line);white-space:nowrap}
td{padding:11px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
tr:hover td{background:var(--wash)}
.num{text-align:right}.rank{font-weight:800;color:var(--sub);width:34px}
.sym{font-weight:750}.nm{display:block;font-size:11.5px;color:var(--sub);font-weight:500}
.meter{width:90px;height:8px;border-radius:4px;background:var(--line);position:relative;overflow:hidden}
.meter i{position:absolute;top:0;bottom:0}
.meter:after{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--faint)}
.pos{color:var(--green)}.neg{color:var(--red)}
.scroll{overflow-x:auto}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media(max-width:900px){.cards{grid-template-columns:1fr}}
.sc{border-top:4px solid var(--tone);padding:0;overflow:hidden}
.sc-h{display:flex;gap:12px;align-items:flex-start;padding:16px 18px 10px}
.sc-rank{flex:0 0 34px;height:34px;border-radius:10px;background:var(--tone);color:#fff;font-weight:800;
display:flex;align-items:center;justify-content:center;font-size:15px}
.sc-t{flex:1;min-width:0}.sc-t h3{margin:0;font-size:16px}.sc-t .tk{font-size:12px;color:var(--sub);font-weight:600}
.sc-spark{flex:0 0 130px;text-align:right}
.sc-spark svg{width:130px;height:40px}.sc-spark small{display:block;font-size:10px;color:var(--faint)}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 18px 12px}
.chip{font-size:11.5px;padding:3px 8px;border-radius:7px;background:var(--wash);border:1px solid var(--line);
color:var(--sub);font-variant-numeric:tabular-nums}.chip b{color:var(--ink)}
.sc-b{padding:4px 18px 14px}
.grp{margin-top:8px}.grp .gt{font-size:11px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;margin:6px 0 4px}
.pt{display:flex;gap:9px;padding:5px 0;align-items:flex-start}
.pt .ic{flex:0 0 18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;
font-size:11px;font-weight:900;color:#fff;margin-top:1px}
.pt .tx{flex:1}
.src{display:inline-block;margin-left:6px;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:999px;
background:#e8edff;color:#2f4bd8;text-decoration:none;vertical-align:1px;white-space:nowrap}
.src:hover{background:#2f4bd8;color:#fff}
@media(prefers-color-scheme:dark){.src{background:#1e2a55;color:#b8c6ff}}
.why{margin:10px 18px 0;padding:10px 12px;border-radius:10px;background:var(--wash);font-size:13px}
.why b{color:var(--sub);font-size:11px;letter-spacing:.6px;text-transform:uppercase;margin-right:6px}
.hl{border-top:1px dashed var(--line);margin-top:12px;padding:10px 18px 14px}
.hl .gt{font-size:11px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;color:var(--sub);margin-bottom:4px}
.hl a{display:block;text-decoration:none;font-size:13px;padding:4px 0}.hl a:hover{color:var(--blue)}
.hl a span{font-size:11px;color:var(--green);font-weight:700;margin-right:6px}
.verdict{font-weight:700;font-size:12px}
.feed{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.fi{border-left:4px solid var(--green);padding:12px 14px}.fi a{text-decoration:none;font-weight:600}
.fi a:hover{color:var(--blue)}.fi .m{font-size:11.5px;color:var(--sub);margin-top:6px}
.warn{background:#fff7e6;border:1px solid #f5d38a;color:#7a5200;padding:10px 14px;border-radius:10px;margin-bottom:12px}
footer{color:var(--sub);font-size:12px;text-align:center;padding:10px 0 30px}
@media print{header{-webkit-print-color-adjust:exact;print-color-adjust:exact}.card{break-inside:avoid}}
"""

KIND = {"catalyst": ("Catalysts", "#1f9d63", "✓"), "risk": ("Risks", "#d64545", "!"),
        "context": ("Context", "#94a3b8", "•")}


def _e(x) -> str:
    return H.escape(str(x if x is not None else ""))


def _newsfmt(ns) -> str:
    if not ns or ns.get("avg_score") is None:
        return "—"
    v = ns["avg_score"]
    return f'<span class="{"pos" if v > 0.1 else "neg" if v < -0.1 else ""}">{v:+.2f}</span>'


def view_pill(view: str, tone: str) -> str:
    bg, fg = VIEW_STYLE.get(tone, VIEW_STYLE["neutral"])
    return f'<span class="pill" style="background:{bg};color:{fg}">{_e(view)}</span>'


def meter(score: float) -> str:
    c = TONE_COLOR[{True: "bull", False: "bear"}[score >= 0]] if score else "#94a3b8"
    w = abs(score) / 2 * 50
    left = 50 if score >= 0 else 50 - w
    return f'<div class="meter" title="Conviction {score:+.2f} of ±2"><i style="left:{left}%;width:{w}%;background:{c}"></i></div>'


def gauge_svg(avg: float) -> str:
    """Semicircle gauge from -2 (bearish) to +2 (bullish)."""
    import math
    segs = [("#d64545", -2, -1.2), ("#e98b8b", -1.2, -0.4), ("#cbd5e1", -0.4, 0.4), ("#7fcfa3", 0.4, 1.2),
            ("#1f9d63", 1.2, 2)]
    cx, cy, r = 110, 104, 84

    def pt(v, rr=r):
        a = math.pi * (1 - (v + 2) / 4)
        return cx + rr * math.cos(a), cy - rr * math.sin(a)
    arcs = []
    for col, a, b in segs:
        x1, y1 = pt(a)
        x2, y2 = pt(b)
        arcs.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}" stroke="{col}" '
                    f'stroke-width="18" fill="none"/>')
    nx, ny = pt(max(-2, min(2, avg)), r - 20)
    mood = ("Bullish" if avg >= 0.75 else "Leaning bullish" if avg >= 0.25 else "Mixed" if avg > -0.25
            else "Leaning bearish" if avg > -0.75 else "Bearish")
    return (f'<svg viewBox="0 0 220 128" width="100%" style="max-width:260px;display:block;margin:auto">{"".join(arcs)}'
            f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="6" fill="currentColor"/>'
            f'<text x="18" y="124" font-size="10" fill="#94a3b8">Bearish</text>'
            f'<text x="202" y="124" font-size="10" fill="#94a3b8" text-anchor="end">Bullish</text></svg>'
            f'<div style="text-align:center;margin-top:-4px"><div class="big" style="font-size:20px">{mood}</div>'
            f'<div class="note">average conviction {avg:+.2f} (−2 … +2)</div></div>')


def spark_svg(points: str, color: str) -> str:
    if not points:
        return ""
    last = points.strip().split()[-1].split(",")
    return (f'<svg viewBox="0 0 112 34" preserveAspectRatio="none"><polyline points="{_e(points)}" fill="none" '
            f'stroke="{color}" stroke-width="1.4" stroke-linejoin="round"/>'
            f'<circle cx="{last[0]}" cy="{last[1]}" r="2.2" fill="{color}"/></svg>')


def path_svg(values: list[float], color: str) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{2 + i * 108 / (n - 1):.1f},{32 - (v - lo) / rng * 30:.1f}" for i, v in enumerate(vals))
    return spark_svg(pts, color)


def fig_conviction(brief: dict, batch: dict, res: dict | None) -> go.Figure:
    live = res is not None and res["kpi"]["day"] >= 1
    tbl = res["table"].set_index("Symbol") if res is not None else None
    xs, ys, txt, cols, sizes, hov = [], [], [], [], [], []
    by = {s["symbol"]: s for s in batch["stocks"]}
    for sym in brief["shortlist"]:
        st = brief["stocks"].get(sym)
        if not st or sym not in by:
            continue
        s = by[sym]
        xs.append(st["view_score"])
        y = float(tbl.loc[sym, "Return %"]) if live else (s.get("from_12m_high") or 0)
        ys.append(y)
        txt.append(sym)
        cols.append(TONE_COLOR[st["tone"]])
        sizes.append(12 + (s.get("traded_daily_cr") or 50) ** 0.5 * 1.2)
        hov.append(f"<b>{sym}</b><br>{st['view']}<br>{'Return since entry' if live else 'From 12m high'}: {y:+.2f}%")
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="markers+text", text=txt, textposition="top center",
                               marker=dict(size=sizes, color=cols, line=dict(color="#fff", width=1.5), opacity=.9),
                               hovertext=hov, hoverinfo="text", textfont=dict(size=11)))
    fig.add_vline(x=0, line=dict(color="#94a3b8", dash="dot"))
    fig.add_hline(y=0, line=dict(color="#94a3b8", dash="dot"))
    if live:
        for x, y, t in ((1.9, 1, "Bullish call, working"), (-1.9, 1, "Bearish call, but rising"),
                        (1.9, -1, "Bullish call, not yet working"), (-1.9, -1, "Bearish call, confirmed")):
            fig.add_annotation(x=x, y=y, yref="y", text=t, showarrow=False, font=dict(size=10, color="#94a3b8"),
                               xanchor="right" if x > 0 else "left", yanchor="bottom" if y > 0 else "top",
                               yshift=0)
    title = ("Does the view match the outcome? Conviction vs return since entry" if live
             else "Conviction vs distance from 12-month high (bubble = liquidity)")
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=14)), height=420, margin=dict(l=50, r=20, t=50, b=45),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
                      font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#64748b"))
    fig.update_xaxes(range=[-2.3, 2.3], title="Research conviction (−2 bearish … +2 bullish)", gridcolor="rgba(148,163,184,.15)",
                     zeroline=False)
    fig.update_yaxes(ticksuffix="%", title="Return since entry" if live else "From 12-month high",
                     gridcolor="rgba(148,163,184,.15)", zeroline=False)
    return fig


def research_html(state: dict, res: dict | None = None, min_score: float = 0.2) -> str:
    b = state["batch"]
    brief = state.get("research")
    news = state.get("news") or {"items": []}
    fund = state.get("fundamentals") or {}
    by = {s["symbol"]: s for s in b["stocks"]}
    live = res is not None and res["kpi"]["day"] >= 1
    k = res["kpi"] if res is not None else None

    if not brief:
        from .research import auto_research
        brief = auto_research(state, res)

    sc_rows = scorecard(brief, res)
    stocks = brief["stocks"]
    scores = [stocks[s]["view_score"] for s in brief["shortlist"] if s in stocks]
    avg = sum(scores) / len(scores) if scores else 0.0
    order_t = ["strong-bull", "bull", "mod-bull", "spec", "neutral", "mod-bear", "bear"]
    names_t = {"strong-bull": "Strongest", "bull": "Bullish", "mod-bull": "Mod. bullish", "spec": "Speculative",
               "neutral": "Neutral", "mod-bear": "Neutral–bearish", "bear": "Bearish"}
    counts = {t: sum(1 for s in stocks.values() if s["tone"] == t) for t in order_t}
    tot = max(1, sum(counts.values()))
    dist = "".join(f'<i style="width:{counts[t] / tot * 100:.1f}%;background:{TONE_COLOR[t]}" title="{names_t[t]}: {counts[t]}"></i>'
                   for t in order_t if counts[t])
    legend = "".join(f'<span><b style="background:{TONE_COLOR[t]}"></b>{names_t[t]} {counts[t]}</span>'
                     for t in order_t if counts[t])
    bulls = sum(1 for s in scores if s >= 0.75)
    bears = sum(1 for s in scores if s <= -0.6)

    # call scorecard summary
    judged = [r for r in sc_rows if r["verdict"] and ("On track" in r["verdict"] or "Off track" in r["verdict"])]
    on = sum("On track" in r["verdict"] for r in judged)
    top3 = [r["ret"] for r in sc_rows[:3] if r["ret"] is not None]
    bot3 = [r["ret"] for r in sc_rows[-3:] if r["ret"] is not None]
    spread = (sum(top3) / len(top3) - sum(bot3) / len(bot3)) if (top3 and bot3) else None

    items = news.get("items", [])
    n_pos = sum(1 for i in items if i["score"] >= min_score)
    avg_news = sum(i["score"] for i in items) / len(items) if items else None
    news_by = {r["symbol"]: r for r in sentiment_summary(news, list(by))} if items else {}

    kpi3 = (f'<div class="card"><div class="lbl">Calls on track</div><div class="big">{on}/{len(judged)}</div>'
            f'<div class="note">Day {k["day"]} · directional calls only</div></div>' if live else
            f'<div class="card"><div class="lbl">Bullish / bearish calls</div><div class="big">{bulls} / {bears}</div>'
            f'<div class="note">of {len(scores)} stocks</div></div>')
    kpi4 = (f'<div class="card"><div class="lbl">Top-3 minus bottom-3</div><div class="big {"pos" if (spread or 0) >= 0 else "neg"}">'
            f'{spread:+.2f}%</div><div class="note">does the ranking add value?</div></div>' if spread is not None else
            f'<div class="card"><div class="lbl">News tone</div><div class="big">{"—" if avg_news is None else f"{avg_news:+.2f}"}</div>'
            f'<div class="note">{len(items)} headlines · {n_pos} positive</div></div>')

    # ---- shortlist table ----
    trs = []
    for r in sc_rows:
        s = by.get(r["symbol"], {})
        ns = news_by.get(r["symbol"])
        ret = "—" if r["ret"] is None else f'<span class="{"pos" if r["ret"] >= 0 else "neg"}">{r["ret"]:+.2f}%</span>'
        vcol = ("#1f9d63" if r["verdict"] and ("On track" in r["verdict"] or "Beat" in r["verdict"]) else
                "#d64545" if r["verdict"] and ("Off" in r["verdict"] or "Lagging" in r["verdict"]) else "#94a3b8")
        trs.append(
            f'<tr><td class="rank">{r["rank"]}</td><td><span class="sym">{_e(r["symbol"])}</span>'
            f'<span class="nm">{_e(r["name"])}</span></td><td>{view_pill(r["view"], r["tone"])}</td>'
            f'<td>{meter(r["score"])}</td><td style="min-width:220px">{_e(r["why"])}</td>'
            f'<td class="num">{s.get("from_12m_high", 0):+.1f}%</td><td class="num">{s.get("volatility", 0):.0f}%</td>'
            f'<td class="num">{s.get("ret_6_1", 0):+.1f}%</td>'
            f'<td class="num">{_newsfmt(ns)}</td>'
            f'<td class="num">{ret}</td><td><span class="verdict" style="color:{vcol}">{_e(r["verdict"] or "awaiting Day 1")}</span></td></tr>')
    table = ('<div class="card scroll"><table><thead><tr><th>#</th><th>Stock</th><th>View</th><th>Conviction</th>'
             '<th>Why</th><th class="num">From high</th><th class="num">Vol</th><th class="num">6-1</th>'
             '<th class="num">News</th><th class="num">Since entry</th><th>Call check</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table></div>')

    # ---- stock cards ----
    cards = []
    for rank, sym in enumerate(brief["shortlist"], start=1):
        st = stocks.get(sym)
        if not st:
            continue
        s = by.get(sym, {})
        f = fund.get(sym, {})
        tone_c = TONE_COLOR[st["tone"]]
        chips = [f'12-1 <b>{s.get("ret_12_1", 0):+.0f}%</b>', f'From high <b>{s.get("from_12m_high", 0):+.1f}%</b>',
                 f'Vol <b>{s.get("volatility", 0):.0f}%</b>', f'Traded <b>₹{s.get("traded_daily_cr", 0):.0f} cr/d</b>',
                 f'Rank <b>{s.get("signal_rank", "—")}</b>']
        if f.get("pe"):
            chips.append(f'P/E <b>{f["pe"]:.0f}</b>')
        if f.get("sector"):
            chips.append(_e(f["sector"]))
        spark_now = ""
        if live:
            row = res["table"].set_index("Symbol").loc[sym]
            cls = "pos" if row["Return %"] >= 0 else "neg"
            chips.insert(0, f'Since entry <b class="{cls}">{row["Return %"]:+.2f}%</b>')
            vals = [None if v != v else float(v) for v in res["closes"].loc[sym].iloc[: k["day"] + 1]]
            spark_now = path_svg(vals, "#2F4BD8")
        groups = []
        for kind in ("catalyst", "risk", "context"):
            pts = [p for p in st["points"] if p["kind"] == kind]
            if not pts:
                continue
            title, col, ic = KIND[kind]
            lis = []
            for p in pts:
                src = ""
                if p.get("source") and p.get("url"):
                    src = f'<a class="src" href="{_e(p["url"])}" target="_blank" rel="noopener">{_e(p["source"])} ↗</a>'
                elif p.get("source"):
                    src = f'<span class="src" style="background:var(--wash);color:var(--sub)">{_e(p["source"])}</span>'
                lis.append(f'<div class="pt"><span class="ic" style="background:{col}">{ic}</span>'
                           f'<span class="tx">{_e(p["text"])}{src}</span></div>')
            groups.append(f'<div class="grp"><div class="gt" style="color:{col}">{title}</div>{"".join(lis)}</div>')
        heads = sorted([i for i in items if i["symbol"] == sym and i["score"] >= min_score], key=lambda x: -x["score"])[:3]
        hl = ""
        if heads:
            hl = ('<div class="hl"><div class="gt">Latest positive headlines</div>' +
                  "".join(f'<a href="{_e(i["link"])}" target="_blank" rel="noopener"><span>+{i["score"]:.2f}</span>'
                          f'{_e(i["title"])} <small style="color:var(--faint)">· {_e(i.get("source", ""))}</small></a>'
                          for i in heads) + "</div>")
        spark12 = spark_svg(s.get("spark_12m", ""), "#94a3b8")
        spark_block = (f'<div class="sc-spark">{spark_now}<small>21-day path</small></div>' if spark_now else
                       f'<div class="sc-spark">{spark12}<small>12-month trend</small></div>' if spark12 else "")
        why = f'<div class="why"><b>Shortlist</b>{_e(st["why"])}</div>' if st.get("why") else ""
        cards.append(
            f'<div class="card sc" style="--tone:{tone_c}"><div class="sc-h"><div class="sc-rank">{rank}</div>'
            f'<div class="sc-t"><h3>{_e(st["name"])}</h3><div class="tk">{_e(sym)} · {_e(s.get("isin", ""))}</div>'
            f'<div style="margin-top:6px;display:flex;gap:8px;align-items:center">{view_pill(st["view"], st["tone"])}'
            f'{meter(st["view_score"])}</div></div>{spark_block}</div>'
            f'<div class="chips">{"".join(f"<span class=chip>{c}</span>" for c in chips)}</div>'
            f'<div class="sc-b">{"".join(groups)}</div>{why}{hl}<div style="height:12px"></div></div>')

    # ---- positive feed ----
    pos = sorted([i for i in items if i["score"] >= min_score], key=lambda x: (x["symbol"] != "MARKET", -x["score"]))
    feed = "".join(
        f'<div class="card fi"><a href="{_e(i["link"])}" target="_blank" rel="noopener">{_e(i["title"])}</a>'
        f'<div class="m"><span class="pill" style="background:#e0e7ff;color:#1e3a8a;padding:1px 8px">'
        f'{_e("Market" if i["symbol"] == "MARKET" else i["symbol"])}</span> '
        f'<span class="pos"><b>+{i["score"]:.2f}</b></span> · {_e(i.get("source", ""))} · {_e(i.get("published", ""))}</div></div>'
        for i in pos[:60])

    fig = fig_conviction(brief, b, res)
    chart = fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displaylogo": False, "responsive": True})
    method = {"notes": "Your research notes", "auto": "Auto-generated (rules + news)",
              "ai": "Claude + web search"}.get(brief.get("method"), "")
    warn = ""
    if brief.get("missing"):
        warn = f'<div class="warn">No research found for: {_e(", ".join(brief["missing"]))}</div>'
    for e in (news.get("errors") or [])[:3]:
        warn += f'<div class="warn">{_e(e)}</div>'
    live_txt = (f'Day {k["day"]} of 21 · last session {k["last_session"]} · portfolio {k["gross_ret"]:+.2f}%'
                if live else "Before entry — views are pre-trade")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SwingScope {b['batch_id']} — Research &amp; Sentiment</title><style>{CSS}</style></head><body>
<header><div class="wrap"><div class="eyebrow">SwingScope · research &amp; sentiment</div>
<h1>Stock by stock — batch {_e(b['batch_id'])}</h1>
<p>Signal {_e(b['signal_date'])} · 21-session hold · regime <b>{_e(b.get('regime') or '—')}</b> ({_e(b.get('regime_note') or '')})</p>
<span class="pill hb">{_e(method)}</span><span class="pill hb">Written {_e(brief.get('generated'))}</span>
<span class="pill hb">{_e(live_txt)}</span></div></header>
<main><div class="wrap">{warn}
<div class="grid g4">
<div class="card"><div class="lbl">Batch mood</div>{gauge_svg(avg)}</div>
<div class="card"><div class="lbl">View distribution</div><div class="big">{bulls} bullish</div>
<div class="dist">{dist}</div><div class="legend">{legend}</div></div>
{kpi3}{kpi4}</div>

<h2>Swing-trade shortlist <span class="count">21-session hold · ranked best → worst</span></h2>{table}

<div class="card" style="margin-top:14px">{chart}</div>

<h2>Stock by stock <span class="count">catalysts, risks and sources</span></h2>
<div class="cards">{''.join(cards)}</div>

<h2>Positive headlines <span class="count">{len(pos)} with score ≥ {min_score:+.2f} · fetched {_e(news.get('fetched', '—'))}</span></h2>
<div class="feed">{feed or '<div class="card">No news fetched yet — use “Fetch news &amp; score”.</div>'}</div>
</div></main>
<footer><div class="wrap">Views: {_e(method)}. Source chips open the cited site (or a site search when only the source name was given).
Headline sentiment = VADER + finance lexicon. “Call check” compares each directional view with the return since entry.
Research tracking only — not investment advice.</div></footer></body></html>"""
