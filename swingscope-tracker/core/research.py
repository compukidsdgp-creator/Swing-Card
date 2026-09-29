"""Stock-by-stock research brief: views, catalysts, risks, sources and a ranked shortlist.

A brief can come from three places:
  1. parse_notes()   – your own write-up pasted as text (the "Stock by stock" format)
  2. auto_research() – rule-based, built from the batch's signal metrics, fundamentals and fetched news
  3. ai_research()   – Claude with web search (needs ANTHROPIC_API_KEY)

Every brief uses the same schema:
{
  "method": "notes" | "auto" | "ai",
  "generated": "YYYY-MM-DD HH:MM",
  "title": str,
  "stocks": {SYM: {"symbol", "name", "view", "view_score", "tone", "summary", "why",
                   "points": [{"text", "kind": catalyst|risk|context, "source", "url"}]}},
  "shortlist": [SYM, ...]            # ranked best → worst
}
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime

import requests

# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
VIEW_STYLE = {  # tone -> (bg, fg)
    "strong-bull": ("#0f7a4a", "#ffffff"),
    "bull": ("#1f9d63", "#ffffff"),
    "mod-bull": ("#d7f2e3", "#0f5132"),
    "spec": ("#fdecc8", "#7a4a00"),
    "neutral": ("#e5e7eb", "#374151"),
    "mod-bear": ("#fde2e2", "#9b1c1c"),
    "bear": ("#d64545", "#ffffff"),
}


def view_score(view: str) -> tuple[float, str]:
    """Map free-text view to a score in [-2, 2] and a tone key."""
    v = (view or "").lower()
    if "strongest" in v or "strong buy" in v or "very bullish" in v:
        return 2.0, "strong-bull"
    if "neutral to bearish" in v or "mildly bearish" in v or "moderately bearish" in v:
        return -1.0, "mod-bear"
    if "bearish" in v or "avoid" in v or "sell" in v:
        return -2.0, "bear"
    if "speculative" in v or "neutral to bullish" in v:
        return 0.5, "spec"
    if "moderately bullish" in v or "mildly bullish" in v:
        return 1.0, "mod-bull"
    if "bullish" in v and ("risk" in v or "pullback" in v):
        return 1.25, "bull"
    if "bullish" in v or "buy" in v:
        return 1.5, "bull"
    if "neutral" in v or "hold" in v:
        return 0.0, "neutral"
    return 0.0, "neutral"


def tone_for_score(s: float) -> str:
    return ("strong-bull" if s >= 1.75 else "bull" if s >= 1.1 else "mod-bull" if s >= 0.75 else
            "spec" if s >= 0.35 else "neutral" if s > -0.6 else "mod-bear" if s > -1.5 else "bear")


def label_for_score(s: float) -> str:
    return {"strong-bull": "Strongest, bullish", "bull": "Bullish", "mod-bull": "Moderately bullish",
            "spec": "Neutral to bullish", "neutral": "Neutral", "mod-bear": "Neutral to bearish",
            "bear": "Bearish"}[tone_for_score(s)]


# --------------------------------------------------------------------------- #
# Point classification + sources
# --------------------------------------------------------------------------- #
_POS = {"rose": 1, "grew": 1, "growth": 1, "jumped": 1.5, "raised": 1, "raise its": 1, "doubled": 1.5,
        "added to": 1, "approval": 1, "target": 0.8, "outperform": 1.5, "upgrade": 1.5, "profit of": 1,
        "lifting": 0.8, "stake": 0.5, "commissioned": 1, "tailwind": 1, "uptrend": 1, "shallow pullback": 1,
        "near highs": 1.2, "near its high": 1.2, "relative strength": 1.2, "defensive": 0.8, "order": 0.7,
        "expansion": 0.8, "capacity": 0.6, "narrowed": 1, "record": 1, "beat": 1, "intact": 0.6,
        "lowest of": 0.8, "better than": 0.6, "moderate": 0.3, "only": 0.2, "bounced": 0.5, "holding": 0.5, "initiated": 0.8, "wins": 1}
_NEG = {"stretched": 1.2, "p/e": 0.6, "fragile": 1.5, "thin": 1, "dilut": 1.5, "negative": 1.2, "fell": 1,
        "slipped": 1.2, "compress": 1.5, "fading": 1.5, "downtrend": 2, "bearish": 1.5, "avoid": 2,
        "lower sequentially": 1.5, "lower": 0.6, "risk": 1, "pull back": 0.8, "expensive": 1.2,
        "highest of": 0.8, "slid": 0.8, "no clear": 1, "sideways": 0.8, "weakest": 2, "momentum-only": 1,
        "fundrais": 0.8, "raising funds": 0.8, "qip": 1, "falling market": 0.8, "gap risk": 1,
        "below the peak": 1, "off that high": 0.6, "loss": 0.3, "decline": 1, "downgrade": 1.5, "sensitive": 0.6}

SOURCE_DOMAINS = {
    "5paisa": "5paisa.com", "fyers": "fyers.in", "sahi": "sahi.com", "share": "sharemarketindia",
    "indmoney": "indmoney.com", "freepressjournal": "freepressjournal.in", "hdfcsky": "hdfcsky.com",
    "angelone": "angelone.in", "anandrathi": "anandrathi.com", "bajajfinserv": "bajajfinserv.in",
    "torusdigital": "torusdigital.com", "moneycontrol": "moneycontrol.com", "economictimes": "economictimes.com",
    "et": "economictimes.com", "livemint": "livemint.com", "mint": "livemint.com",
    "business-standard": "business-standard.com", "businessstandard": "business-standard.com",
    "screener": "screener.in", "trendlyne": "trendlyne.com", "tickertape": "tickertape.in",
    "nse": "nseindia.com", "bse": "bseindia.com", "zerodha": "zerodha.com", "groww": "groww.in",
    "reuters": "reuters.com", "cnbctv18": "cnbctv18.com", "financialexpress": "financialexpress.com",
    "thehindubusinessline": "thehindubusinessline.com", "businessline": "thehindubusinessline.com",
}


def _num(x: str) -> float:
    return float(x.replace(",", ""))


def classify(text: str) -> str:
    t = text.lower().replace("risk-off", "").replace("−", "-")
    p = sum(w for k, w in _POS.items() if k in t)
    n = sum(w for k, w in _NEG.items() if k in t)
    # "₹740 crore vs ₹380 crore" style comparisons (current vs prior)
    m = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr)?\s+vs\.?\s+₹?\s*([\d,]+(?:\.\d+)?)", t)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        p += 1.0 if a > b * 1.05 else 0
        n += 1.0 if a < b * 0.95 else 0
    if re.search(r"return is -\d", t) or "below its high" in t:
        n += 0.8
    if p - n >= 0.6:
        return "catalyst"
    if n - p >= 0.6:
        return "risk"
    return "context"


def source_url(source: str, symbol: str, name: str = "") -> str:
    """Best link we can build from a bare source tag: a site-restricted search for the stock."""
    if not source:
        return ""
    if source.startswith("http"):
        return source
    dom = SOURCE_DOMAINS.get(source.lower().strip(), f"{source.lower().strip()}")
    q = f"{name or symbol} site:{dom}" if "." in dom else f"{name or symbol} {source}"
    return "https://www.google.com/search?q=" + urllib.parse.quote(q)


def _sentences(par: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z₹0-9])", par.strip())
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------- #
# 1. Parse pasted notes
# --------------------------------------------------------------------------- #
HEAD_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*\(([A-Z0-9&\-_.]+)\)\s*[:\-–—]\s*(.+?)\s*$")


def parse_notes(text: str, batch: dict | None = None) -> dict:
    syms_in_batch = {s["symbol"] for s in (batch or {}).get("stocks", [])}
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    stocks: dict[str, dict] = {}
    order: list[str] = []
    cur = None
    buf: list[str] = []
    shortlist_rows: list[list[str]] = []
    in_short = False

    def flush_para(src: str = ""):
        nonlocal buf
        if cur is None or not buf:
            buf = []
            return
        par = " ".join(x.strip() for x in buf if x.strip())
        for sent in _sentences(par):
            cur["points"].append({"text": sent, "kind": classify(sent), "source": src,
                                  "url": source_url(src, cur["symbol"], cur["name"])})
        buf = []

    for ln in lines:
        s = ln.strip()
        if not s:
            flush_para()
            continue
        if re.match(r"(?i)^(swing[- ]trade )?shortlist", s) or re.match(r"(?i)^rank\s*[\t|,]", s):
            flush_para()
            in_short = True
            continue
        if in_short:
            cells = [c.strip() for c in re.split(r"\t+|\s*\|\s*|\s{2,}", s) if c.strip()]
            if len(cells) >= 3 and cells[0].isdigit():
                shortlist_rows.append(cells)
            continue
        m = HEAD_RE.match(s)
        if m:
            flush_para()
            _, name, sym, view = m.groups()
            sc, tone = view_score(view)
            cur = {"symbol": sym, "name": name, "view": view.strip().rstrip(".").capitalize(),
                   "view_score": sc, "tone": tone, "summary": "", "why": "", "points": []}
            stocks[sym] = cur
            order.append(sym)
            continue
        # a bare source tag: single token, lowercase-ish, no spaces, short
        if (re.fullmatch(r"[A-Za-z0-9][\w.\-]{1,30}", s) and re.search(r"[a-z]", s)
                and s.lower() == s and not s[-1] in ".:"):
            flush_para(s)
            continue
        if s.lower().startswith("stock by stock"):
            continue
        flush_para()  # previous line had no source tag
        buf.append(s)
    flush_para()

    shortlist = []
    for row in shortlist_rows:
        sym = row[1].upper()
        if sym not in stocks:  # allow names in the table
            hit = [k for k, v in stocks.items() if v["name"].lower() == row[1].lower()]
            sym = hit[0] if hit else sym
        shortlist.append(sym)
        if sym in stocks:
            view = row[2] if len(row) > 2 else stocks[sym]["view"]
            why = " ".join(row[3:]) if len(row) > 3 else ""
            st = stocks[sym]
            st["why"] = why
            st["short_view"] = view
            # table view refines score only if the heading didn't carry more detail
            sc2, tone2 = view_score(view + " " + st["view"])
            if abs(sc2) > 0 and st["view_score"] == 0:
                st["view_score"], st["tone"] = sc2, tone2

    if not shortlist:
        shortlist = sorted(order, key=lambda k: -stocks[k]["view_score"])
    for sym, st in stocks.items():
        cats = [p for p in st["points"] if p["kind"] == "catalyst"]
        risks = [p for p in st["points"] if p["kind"] == "risk"]
        if not st["why"]:
            st["why"] = "; ".join(x["text"].split(",")[0].rstrip(".") for x in (cats[:1] + risks[:1]))
        st["summary"] = st["points"][0]["text"] if st["points"] else ""
    missing = sorted(syms_in_batch - set(stocks)) if syms_in_batch else []
    return {"method": "notes", "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title": "Stock by stock", "stocks": stocks, "shortlist": shortlist, "missing": missing}


# --------------------------------------------------------------------------- #
# 2. Rule-based auto brief
# --------------------------------------------------------------------------- #
THEMES = [
    ("Results", r"\b(q[1-4]|quarter|results?|profit|pat|revenue|ebitda|earnings|margin)\b"),
    ("Guidance", r"\bguidance|outlook|targets? (fy|revenue)"),
    ("Order win", r"\border(s)?\b|contract|bags|wins|secures|l1 bidder"),
    ("Broker call", r"\btarget price|price target|upgrade|downgrade|outperform|overweight|initiat|buy rating|brokerage"),
    ("Fundraise", r"\bqip\b|fund ?rais|preferential|rights issue|ofs\b|block deal|stake sale"),
    ("Index", r"\bmsci|ftse|sensex inclusion|nifty inclusion|index\b"),
    ("Stake/Promoter", r"\bpromoter|stake|acquisition|acquire|merger"),
    ("Capacity", r"\bcapacity|plant|expansion|capex|commission"),
    ("Regulatory", r"\bsebi|usfda|fda|approval|pli|license|licence|probe|penalty"),
]


def fetch_fundamentals(symbol: str) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info or {}
        return {"name": info.get("shortName") or info.get("longName") or symbol,
                "pe": info.get("trailingPE"), "fwd_pe": info.get("forwardPE"), "sector": info.get("sector"),
                "industry": info.get("industry"), "mcap_cr": (info.get("marketCap") or 0) / 1e7 or None,
                "pb": info.get("priceToBook"), "rev_growth": info.get("revenueGrowth"),
                "earn_growth": info.get("earningsGrowth")}
    except Exception:
        return {}


def auto_research(state: dict, res: dict | None = None) -> dict:
    b = state["batch"]
    stocks = b["stocks"]
    names = state.get("names") or {}
    fund = state.get("fundamentals") or {}
    news = (state.get("news") or {}).get("items", [])
    vols = [s.get("volatility") or 0 for s in stocks]
    liq = [s.get("traded_daily_cr") or 0 for s in stocks]
    out = {}
    for s in stocks:
        sym = s["symbol"]
        f = fund.get(sym, {})
        name = f.get("name") or names.get(sym) or sym
        pts, score = [], 0.0
        fh = s.get("from_12m_high")
        if fh is not None:
            if fh > -5:
                pts.append(("Close is only {:.1f}% below its 12-month high — relative strength near highs.".format(-fh), "catalyst", "near highs")); score += 1.0
            elif fh > -12:
                pts.append((f"{-fh:.1f}% below its 12-month high: a shallow pullback inside the uptrend.", "catalyst", "shallow pullback")); score += 0.5
            elif fh > -20:
                pts.append((f"{-fh:.1f}% below its 12-month high — consolidating after a big run.", "context", "consolidating"))
            else:
                pts.append((f"{-fh:.1f}% below its 12-month high — a deep drawdown; the trend is weakening.", "risk", "deep drawdown")); score -= 1.2
        r61, r31 = s.get("ret_6_1"), s.get("ret_3_1")
        if r61 is not None:
            if r61 < 0:
                pts.append((f"6-1 month return is {r61:+.1f}%: medium-term momentum is fading.", "risk", "fading 6-1 momentum")); score -= 0.8
            elif r61 > 80:
                pts.append((f"6-1 month return {r61:+.0f}% — very strong medium-term momentum.", "catalyst", "very strong 6-1")); score += 0.5
        if r31 is not None and r31 < -8:
            pts.append((f"3-1 month return {r31:+.1f}% — the recent leg is negative.", "risk", "negative recent leg")); score -= 0.4
        elif r31 is not None and r31 > 25:
            pts.append((f"3-1 month return {r31:+.1f}% — recent momentum is accelerating.", "catalyst", "accelerating momentum")); score += 0.3
        v = s.get("volatility")
        if v is not None:
            if v == min(vols):
                pts.append((f"Lowest volatility of the batch ({v:.0f}%).", "catalyst", "lowest volatility")); score += 0.5
            elif v == max(vols):
                pts.append((f"Highest volatility of the batch ({v:.0f}%) — expect big swings.", "risk", "highest volatility")); score -= 0.5
            elif v >= 55:
                pts.append((f"High volatility ({v:.0f}%).", "risk", "high volatility")); score -= 0.2
        l = s.get("traded_daily_cr")
        if l is not None and l < 60:
            pts.append((f"Thin liquidity (₹{l:.0f} cr/day) — gap risk in a falling market.", "risk", "thin liquidity")); score -= 0.3
        elif l is not None and l == max(liq):
            pts.append((f"Most liquid name in the batch (₹{l:.0f} cr/day).", "context", "most liquid"))
        pe = f.get("pe")
        if pe:
            if pe > 90:
                pts.append((f"Valuation is stretched (P/E ≈ {pe:.0f}).", "risk", "stretched valuation")); score -= 0.5
            elif pe > 50:
                pts.append((f"Premium valuation (P/E ≈ {pe:.0f}).", "context", "premium valuation"))
        if f.get("earn_growth") and f["earn_growth"] > 0.5:
            pts.append((f"Earnings growth ≈ {f['earn_growth'] * 100:.0f}% YoY (latest quarter).", "catalyst", "strong earnings growth")); score += 0.4
        # news
        mine = [n for n in news if n["symbol"] == sym]
        themes, used = {}, set()
        for n in sorted(mine, key=lambda x: -abs(x["score"])):
            if n["title"] in used:
                continue
            for th, rx in THEMES:
                if re.search(rx, n["title"], re.I) and th not in themes:
                    themes[th] = n
                    used.add(n["title"])
                    break
        for th, n in list(themes.items())[:4]:
            kind = "catalyst" if n["score"] >= 0.2 else ("risk" if n["score"] <= -0.2 else "context")
            if th == "Fundraise":
                kind = "risk"
            pts.append((f"[{th}] {n['title']}", kind, th.lower(), n.get("source") or "news", n.get("link", "")))
        if mine:
            avg = sum(n["score"] for n in mine) / len(mine)
            score += max(-0.8, min(0.8, avg * 1.2))
        # live tracking
        if res is not None and res["kpi"]["day"] >= 1:
            row = res["table"].set_index("Symbol").loc[sym]
            pts.append((f"Since entry: {row['Return %']:+.2f}% (Day {res['kpi']['day']}).",
                        "catalyst" if row["Return %"] > 0 else "risk", ""))
        points, tag_c, tag_r = [], [], []
        for p in pts:
            text, kind, tag = p[0], p[1], p[2]
            src = p[3] if len(p) > 3 else "SwingScope data"
            url = p[4] if len(p) > 4 else ""
            points.append({"text": text, "kind": kind, "source": src, "url": url})
            if tag:
                if kind == "catalyst":
                    tag_c.append(tag)
                elif kind == "risk":
                    tag_r.append(tag)
        score = max(-2.0, min(2.0, score))
        why = ", ".join(tag_c[:2] + tag_r[:2])
        why = why[:1].upper() + why[1:] if why else "No strong signal either way"
        out[sym] = {"symbol": sym, "name": name, "view": label_for_score(score), "view_score": round(score, 2),
                    "tone": tone_for_score(score), "summary": points[0]["text"] if points else "",
                    "why": why, "points": points}
    shortlist = sorted(out, key=lambda k: (-out[k]["view_score"], -(next(
        (s.get("ret_12_1") or 0) for s in stocks if s["symbol"] == k))))
    return {"method": "auto", "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title": "Stock by stock (auto-generated)", "stocks": out, "shortlist": shortlist, "missing": []}


# --------------------------------------------------------------------------- #
# 3. Claude + web search
# --------------------------------------------------------------------------- #
AI_PROMPT = """You are an equity research analyst for Indian (NSE) swing trades.
A momentum model selected the 10 stocks below on {signal_date} for a 21-session hold
(buy at next open, no stop, no target). Market regime: {regime}.

{table}

Use web search to find the latest (last ~90 days) facts for EACH stock: quarterly results, guidance,
order wins, broker target changes, fundraises/QIPs, index inclusions, promoter activity, valuation (P/E),
and anything that matters for the next 21 sessions. Combine with the price metrics above.

Return ONLY a JSON object (no prose before or after) with this exact shape:
{{"stocks": [{{"symbol": "TDPOWERSYS", "name": "TD Power Systems",
   "view": "bullish | bullish, high risk | moderately bullish | speculative, neutral to bullish | neutral | neutral to bearish | bearish | strongest, bullish",
   "points": [{{"text": "One factual sentence with numbers.", "kind": "catalyst|risk|context",
                "source": "short site name", "url": "https://..."}}],
   "why": "Max 12 words for the shortlist table"}}],
 "shortlist": ["SYMBOL ranked best first", "..."]}}
Rules: 3-5 points per stock, each point ONE sentence, cite a real URL you actually read for every
non-price fact, never invent numbers, rank all 10 in the shortlist."""


def ai_research(state: dict, api_key: str, model: str = "claude-sonnet-4-5", max_searches: int = 25,
                timeout: int = 600) -> dict:
    b = state["batch"]
    rows = ["symbol | qty | last close | 12-1 % | 6-1 % | 3-1 % | from 12m high % | vol % | traded ₹cr/day"]
    for s in b["stocks"]:
        rows.append(f"{s['symbol']} | {s['qty']} | {s['last_close']} | {s.get('ret_12_1')} | {s.get('ret_6_1')} | "
                    f"{s.get('ret_3_1')} | {s.get('from_12m_high')} | {s.get('volatility')} | {s.get('traded_daily_cr')}")
    prompt = AI_PROMPT.format(signal_date=b["signal_date"], regime=f"{b.get('regime')} ({b.get('regime_note')})",
                              table="\n".join(rows))
    body = {"model": model, "max_tokens": 16000,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}],
            "messages": [{"role": "user", "content": prompt}]}
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=timeout, json=body,
                      headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:400]}")
    text = "".join(blk.get("text", "") for blk in r.json().get("content", []) if blk.get("type") == "text")
    return ai_json_to_brief(text)


def ai_json_to_brief(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("The model did not return JSON.")
    data = json.loads(m.group(0))
    stocks = {}
    for s in data.get("stocks", []):
        sc, tone = view_score(s.get("view", ""))
        pts = [{"text": p.get("text", ""), "kind": p.get("kind") or classify(p.get("text", "")),
                "source": p.get("source", ""), "url": p.get("url", "")} for p in s.get("points", [])]
        stocks[s["symbol"]] = {"symbol": s["symbol"], "name": s.get("name", s["symbol"]),
                               "view": (s.get("view") or "Neutral").capitalize(), "view_score": sc, "tone": tone,
                               "summary": pts[0]["text"] if pts else "", "why": s.get("why", ""), "points": pts}
    shortlist = [x for x in data.get("shortlist", []) if x in stocks] or \
        sorted(stocks, key=lambda k: -stocks[k]["view_score"])
    return {"method": "ai", "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title": "Stock by stock (Claude + web search)", "stocks": stocks, "shortlist": shortlist, "missing": []}


# --------------------------------------------------------------------------- #
# Scorecard: how are the calls playing out?
# --------------------------------------------------------------------------- #
def scorecard(brief: dict, res: dict | None) -> list[dict]:
    rows = []
    tbl = res["table"].set_index("Symbol") if res is not None else None
    live = res is not None and res["kpi"]["day"] >= 1
    for rank, sym in enumerate(brief.get("shortlist", []), start=1):
        st = brief["stocks"].get(sym)
        if not st:
            continue
        ret = float(tbl.loc[sym, "Return %"]) if (live and sym in tbl.index) else None
        verdict = None
        if ret is not None:
            vs = st["view_score"]
            if vs >= 0.75:
                verdict = "✓ On track" if ret > 0 else "✗ Off track"
            elif vs <= -0.6:
                verdict = "✓ On track" if ret < 0 else "✗ Off track"
            else:
                verdict = "• Neutral call" if abs(ret) < 3 else ("↑ Beat call" if ret > 0 else "↓ Lagging")
        rows.append({"rank": rank, "symbol": sym, "name": st["name"], "view": st.get("short_view") or st["view"],
                     "tone": st["tone"], "score": st["view_score"], "why": st["why"], "ret": ret, "verdict": verdict})
    return rows
