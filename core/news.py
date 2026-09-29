"""News collection + sentiment scoring (VADER with a finance lexicon boost)."""
from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
except Exception:  # pragma: no cover
    _VADER = None

# Market-specific words VADER underweights or misses entirely.
FIN_LEXICON = {
    "upgrade": 2.2, "upgrades": 2.2, "upgraded": 2.2, "downgrades": -2.2, "outperform": 2.0, "overweight": 1.5, "buy": 1.2, "accumulate": 1.2,
    "beats": 2.0, "beat": 1.6, "record": 1.5, "surge": 2.2, "surges": 2.2, "soar": 2.4, "soars": 2.4,
    "rally": 2.0, "rallies": 2.0, "jumps": 2.0, "jump": 1.8, "gains": 1.6, "gain": 1.4, "climbs": 1.6,
    "order": 1.0, "orders": 1.0, "win": 1.8, "wins": 1.8, "bags": 1.8, "bagged": 1.8, "secures": 1.8,
    "contract": 0.8, "expansion": 1.5, "approval": 1.8, "approves": 1.6, "profit": 1.4, "growth": 1.5,
    "robust": 1.8, "strong": 1.6, "bullish": 2.4, "breakout": 1.8, "high": 0.8, "dividend": 1.2,
    "bonus": 1.2, "buyback": 1.5, "target": 0.6, "multibagger": 2.0, "upside": 1.8, "rerating": 1.6,
    "downgrade": -2.2, "downgraded": -2.2, "underperform": -2.0, "sell": -1.4, "miss": -1.8, "misses": -1.8,
    "plunge": -2.5, "plunges": -2.5, "slump": -2.2, "slumps": -2.2, "falls": -1.6, "fall": -1.4,
    "tumbles": -2.2, "crash": -2.8, "loss": -1.8, "losses": -1.8, "decline": -1.6, "declines": -1.6,
    "weak": -1.6, "bearish": -2.4, "fraud": -3.0, "probe": -1.8, "penalty": -1.8, "raid": -2.0,
    "resigns": -1.4, "pledge": -1.2, "slips": -1.4, "slip": -1.4, "share": 0.0, "shares": 0.0, "stock": 0.0, "stocks": 0.0,
    "focus": 0.0, "sinks": -2.0, "sheds": -1.6, "tanks": -2.2, "cuts": -1.2, "hit": -0.6, "hits": -0.6, "drags": -1.4, "sebi": -0.3, "lower": -0.8,
}
if _VADER:
    _VADER.lexicon.update(FIN_LEXICON)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def score(text: str) -> float:
    if _VADER:
        return float(_VADER.polarity_scores(text)["compound"])
    # tiny fallback if vaderSentiment isn't installed
    words = re.findall(r"[a-z]+", text.lower())
    s = sum(FIN_LEXICON.get(w, 0) for w in words)
    return max(-1.0, min(1.0, s / 4))


def label(s: float, pos: float = 0.2, neg: float = -0.2) -> str:
    return "Positive" if s >= pos else ("Negative" if s <= neg else "Neutral")


def _google_news(query: str, days: int) -> list[dict]:
    q = urllib.parse.quote(f"{query} when:{days}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
        blk = m.group(1)
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", blk, re.S) or [None, ""])[1]  # noqa: E731
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", g("title"))).strip()
        src = html.unescape(g("source")).strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        pub = g("pubDate")
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except Exception:
            dt = None
        items.append({"title": title, "link": html.unescape(g("link")).strip(), "source": src,
                      "published_dt": dt})
    return items


def _yahoo_news(symbol: str) -> list[dict]:
    try:
        import yfinance as yf
        out = []
        for n in (yf.Ticker(f"{symbol}.NS").news or [])[:15]:
            c = n.get("content", n)
            title = c.get("title", "")
            link = (c.get("canonicalUrl") or {}).get("url") or c.get("link", "")
            src = (c.get("provider") or {}).get("displayName") or c.get("publisher", "Yahoo")
            ts = c.get("pubDate") or c.get("providerPublishTime")
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float)) else \
                    datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                dt = None
            if title:
                out.append({"title": title, "link": link, "source": src, "published_dt": dt,
                            "summary": c.get("summary", "")})
        return out
    except Exception:
        return []


def company_name(symbol: str) -> str:
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        return info.get("shortName") or info.get("longName") or symbol
    except Exception:
        return symbol


def collect_news(symbols: list[str], names: dict[str, str] | None = None, days: int = 7,
                 include_market: bool = True, progress=None) -> dict:
    """Fetch and score news for each symbol (+ broad Indian market). Returns a JSON-able dict."""
    names = names or {}
    since = datetime.now(timezone.utc) - timedelta(days=days)
    all_items, errors = [], []
    targets = [(s, f'"{names.get(s, s)}" share OR stock' if names.get(s, s) != s else f"{s} NSE share")
               for s in symbols]
    if include_market:
        targets.append(("MARKET", "Sensex Nifty stock market India"))

    for i, (sym, q) in enumerate(targets):
        if progress:
            progress(i / len(targets), f"News: {sym}")
        found = []
        try:
            found += _google_news(q, days)
        except Exception as e:
            errors.append(f"{sym} Google News: {e}")
        if sym != "MARKET":
            found += _yahoo_news(sym)
        seen = set()
        for it in found:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if not it["title"] or key in seen:
                continue
            if it["published_dt"] and it["published_dt"] < since:
                continue
            seen.add(key)
            s = score(it["title"] + ". " + it.get("summary", ""))
            all_items.append({
                "symbol": sym, "title": it["title"], "link": it["link"], "source": it.get("source", ""),
                "published": it["published_dt"].strftime("%Y-%m-%d %H:%M") if it["published_dt"] else "",
                "score": round(s, 3), "label": label(s),
            })
    all_items.sort(key=lambda x: (x["published"] or ""), reverse=True)
    if progress:
        progress(1.0, "News done")
    return {"fetched": datetime.now().strftime("%Y-%m-%d %H:%M"), "days": days,
            "items": all_items, "errors": errors}


def sentiment_summary(news: dict, symbols: list[str]) -> list[dict]:
    rows = []
    for sym in symbols + ["MARKET"]:
        its = [i for i in news.get("items", []) if i["symbol"] == sym]
        if not its:
            rows.append({"symbol": sym, "articles": 0, "positive": 0, "neutral": 0, "negative": 0,
                         "avg_score": None, "mood": "No news"})
            continue
        avg = sum(i["score"] for i in its) / len(its)
        pos = sum(i["label"] == "Positive" for i in its)
        neg = sum(i["label"] == "Negative" for i in its)
        rows.append({"symbol": sym, "articles": len(its), "positive": pos, "neutral": len(its) - pos - neg,
                     "negative": neg, "avg_score": round(avg, 3),
                     "mood": "Bullish" if avg >= 0.15 else ("Bearish" if avg <= -0.15 else "Mixed")})
    return rows


def demo_news(symbols: list[str]) -> dict:
    """Offline sample so the UI can be previewed without internet."""
    samples = [
        ("{s} bags ₹450 crore order from leading utility; shares surge 6%", 1),
        ("Brokerage upgrades {s} to Buy, sees 25% upside on strong order book", 1),
        ("{s} Q2 profit jumps 38% YoY, beats street estimates", 1),
        ("{s} shares slip 2% as markets remain weak", -1),
        ("{s} board to consider fund raising; stock in focus", 0),
    ]
    items = []
    now = datetime.now()
    for k, s in enumerate(symbols + ["MARKET"]):
        for j, (t, _) in enumerate(samples[: 2 + (k % 4)]):
            title = t.format(s=s if s != "MARKET" else "Nifty")
            sc = score(title)
            items.append({"symbol": s, "title": title, "link": "https://news.google.com/", "source": "Sample",
                          "published": (now - timedelta(hours=5 * k + j)).strftime("%Y-%m-%d %H:%M"),
                          "score": round(sc, 3), "label": label(sc)})
    return {"fetched": now.strftime("%Y-%m-%d %H:%M"), "days": 7, "items": items,
            "errors": ["DEMO DATA — not real news"]}
