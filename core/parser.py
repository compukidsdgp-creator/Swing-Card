"""Parse a SwingScope momentum-batch HTML into a structured batch dict."""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup


def _num(text: str | None) -> float | None:
    """'₹1,39,903' -> 139903.0 ; '−14.0%' -> -14.0 ; '+177%' -> 177.0"""
    if text is None:
        return None
    t = str(text).replace("−", "-").replace("₹", "").replace(",", "").replace("%", "")
    t = t.replace("cr", "").strip()
    m = re.search(r"-?\+?\d+(\.\d+)?", t)
    if not m:
        return None
    return float(m.group(0).replace("+", ""))


def _date(text: str) -> str | None:
    m = re.search(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", text or "")
    if not m:
        return None
    return datetime.strptime(m.group(1), "%d %b %Y").strftime("%Y-%m-%d")


def parse_swingscope_html(html: str | bytes) -> dict:
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(" ", strip=True)

    title = soup.title.get_text(strip=True) if soup.title else ""
    batch_id = None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", title)
    if m:
        batch_id = m.group(1)

    # ---- timeline marks (signal / exit dates) ----
    signal_date, exit_date = None, None
    for mark in soup.select(".timeline .mark"):
        txt = mark.get_text(" ", strip=True)
        if txt.lower().startswith("signal"):
            signal_date = _date(txt)
        elif txt.lower().startswith("sell"):
            exit_date = _date(txt)
    if not signal_date:
        signal_date = _date(re.search(r"Signal after the close of (.{0,30})", full_text).group(1)) \
            if "Signal after the close of" in full_text else batch_id
    batch_id = batch_id or signal_date

    # ---- summary block ----
    summary = {}
    for div in soup.select("dl.summary > div"):
        dt, dd = div.find("dt"), div.find("dd")
        if dt and dd:
            note = dd.find(class_="note")
            note_txt = note.get_text(" ", strip=True) if note else ""
            if note:
                note.extract()
            summary[dt.get_text(" ", strip=True)] = {"value": dd.get_text(" ", strip=True), "note": note_txt}

    capital = _num(summary.get("Capital committed", {}).get("value"))
    costs = _num(summary.get("Estimated costs, buy and sell", {}).get("value"))
    cost_pct = _num(summary.get("Estimated costs, buy and sell", {}).get("note"))
    regime = summary.get("Market regime", {}).get("value", "")
    regime_note = summary.get("Market regime", {}).get("note", "")
    warnings = summary.get("Stocks with a warning", {}).get("value", "")

    universe = ""
    m = re.search(r"Universe:\s*([^\n]+?)(?:Buy|$)", full_text)
    if m:
        universe = m.group(1).strip()

    # ---- order ticket table ----
    stocks = []
    table = None
    for h2 in soup.find_all("h2"):
        if "order ticket" in h2.get_text(strip=True).lower():
            table = h2.find_next("table")
            break
    if table is None:
        table = soup.find("table")
    if table is None:
        raise ValueError("Could not find the order-ticket table in this HTML.")

    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        row = dict(zip(headers, tds))
        sym_td = row.get("Stock", tds[1])
        isin_el = sym_td.find(class_="isin")
        isin = isin_el.get_text(strip=True) if isin_el else ""
        sym_el = sym_td.find("b")
        symbol = sym_el.get_text(strip=True) if sym_el else sym_td.get_text(strip=True).replace(isin, "")
        g = lambda k: row[k].get_text(" ", strip=True) if k in row else None  # noqa: E731
        poly = tr.select_one("svg.spark polyline") or tr.select_one("svg polyline")
        spark = poly.get("points", "") if poly else ""
        stocks.append({
            "rank": int(_num(g("#")) or len(stocks) + 1),
            "symbol": symbol,
            "isin": isin,
            "qty": int(_num(g("Qty")) or 0),
            "last_close": _num(g("Last close")),
            "amount": _num(g("Amount")),
            "spark_12m": spark,
            "ret_12_1": _num(g("12-1")),
            "ret_6_1": _num(g("6-1")),
            "ret_3_1": _num(g("3-1")),
            "volatility": _num(g("Volatility")),
            "traded_daily_cr": _num(g("Traded daily")),
            "watch": g("Watch during the hold") or "",
        })

    # ---- per-stock sheet metrics (signal rank, from-high, data quality) ----
    for art in soup.select("article.sheet"):
        b = art.select_one(".sheet-head b")
        if not b:
            continue
        sym = b.get_text(strip=True)
        extra = {}
        for span in art.select(".metrics span"):
            label = span.contents[0].strip() if span.contents and isinstance(span.contents[0], str) else ""
            val = span.find("b").get_text(strip=True) if span.find("b") else ""
            extra[label] = val
        for s in stocks:
            if s["symbol"] == sym:
                s["from_12m_high"] = _num(extra.get("From 12-month high"))
                s["signal_rank"] = int(_num(extra.get("Signal rank")) or 0) or None
                s["data_quality"] = extra.get("Data quality", "")

    # ---- backtest evidence ----
    evidence = []
    for card in soup.select(".evidence > div, .cards > div, .evidence-grid > div"):
        txt = card.get_text(" | ", strip=True)
        if txt:
            evidence.append(txt)
    if not evidence:
        m = re.search(r"Evidence behind the rule(.*?)Research output", full_text, re.S)
        if m:
            evidence = [m.group(1).strip()[:1500]]

    if not stocks:
        raise ValueError("No stocks found in the order ticket.")

    return {
        "batch_id": batch_id,
        "title": title,
        "signal_date": signal_date,
        "exit_date_est": exit_date,
        "hold_sessions": 21,
        "universe": universe,
        "capital": capital or sum((s["amount"] or 0) for s in stocks),
        "est_costs": costs,
        "cost_pct": cost_pct if cost_pct is not None else 0.6,
        "regime": regime,
        "regime_note": regime_note,
        "warnings": warnings,
        "evidence": evidence,
        "stocks": stocks,
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(parse_swingscope_html(open(sys.argv[1], encoding="utf-8").read()), indent=2))
