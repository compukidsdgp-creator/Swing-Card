"""Live layer for the 24x7 dashboard: market status, intraday quotes, latest state from GitHub."""
from __future__ import annotations

import json
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .prices import BENCHMARK_SYMBOL, BENCHMARK_YF, is_trading_day, project_sessions

IST = ZoneInfo("Asia/Kolkata")
OPEN, CLOSE = dtime(9, 15), dtime(15, 30)


# --------------------------------------------------------------------------- #
# Market clock
# --------------------------------------------------------------------------- #
def market_status(now: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    day = now.strftime("%Y-%m-%d")
    trading = is_trading_day(day)
    t = now.time()
    if trading and OPEN <= t < CLOSE:
        state, label = "open", "Market open"
    elif trading and dtime(9, 0) <= t < OPEN:
        state, label = "preopen", "Pre-open"
    elif trading and t >= CLOSE:
        state, label = "closed_today", "Closed for the day"
    else:
        state, label = "closed", "Market closed" + ("" if trading else " (holiday/weekend)" if now.weekday() < 5
                                                    else " (weekend)")
    nxt = day if (trading and t < OPEN) else project_sessions(day, 1)[0]
    return {"now": now, "today": day, "trading_day": trading, "state": state, "label": label,
            "is_open": state == "open", "next_session": nxt}


# --------------------------------------------------------------------------- #
# Intraday quotes (Yahoo, ~1-15 min delayed for NSE)
# --------------------------------------------------------------------------- #
def fetch_live_quotes(symbols: list[str]) -> tuple[dict, str | None]:
    """Latest traded price per symbol for today. Returns ({sym: {"price", "time"}}, error)."""
    try:
        import yfinance as yf
    except ImportError:
        return {}, "yfinance not installed"
    tickers = {f"{s}.NS": s for s in symbols}
    tickers[BENCHMARK_YF] = BENCHMARK_SYMBOL
    out = {}
    try:
        raw = yf.download(list(tickers), period="1d", interval="1m", progress=False, group_by="ticker",
                          threads=True, auto_adjust=False)
        for yt, sym in tickers.items():
            try:
                sub = raw[yt] if isinstance(raw.columns, pd.MultiIndex) else raw
                s = sub["Close"].dropna()
                if not s.empty:
                    ts = pd.Timestamp(s.index[-1])
                    ts = ts.tz_convert(IST) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(IST)
                    out[sym] = {"price": float(s.iloc[-1]), "time": ts.strftime("%H:%M")}
            except Exception:
                continue
    except Exception as e:
        err = f"intraday download failed: {type(e).__name__}"
    else:
        err = None
    # fallback for anything missing
    for yt, sym in tickers.items():
        if sym in out:
            continue
        try:
            import yfinance as yf
            p = yf.Ticker(yt).fast_info.get("last_price")
            if p:
                out[sym] = {"price": float(p), "time": "last"}
        except Exception:
            pass
    if not out and err is None:
        err = "no intraday prices returned"
    return out, err


def live_table(state: dict, res: dict, quotes: dict) -> tuple[pd.DataFrame, dict]:
    """Combine end-of-day analytics with live quotes."""
    t = res["table"].set_index("Symbol")
    last_eod = res["closes"].iloc[:, res["kpi"]["day"]]
    rows = []
    for sym in t.index:
        q = quotes.get(sym)
        live = q["price"] if q else float(last_eod[sym])
        qty, entry, eod = float(t.loc[sym, "Qty"]), float(t.loc[sym, "Entry"]), float(last_eod[sym])
        view = ""
        research = state.get("research") or {}
        if sym in research.get("stocks", {}):
            st = research["stocks"][sym]
            view = st.get("short_view") or st.get("view", "")
        rows.append({"Symbol": sym, "Qty": qty, "Entry": entry, "Last EOD": eod, "Live": live,
                     "As of": q["time"] if q else "EOD",
                     "Today %": (live / eod - 1) * 100, "Since entry %": (live / entry - 1) * 100,
                     "Live P&L": qty * (live - entry), "Today ₹": qty * (live - eod), "View": view})
    df = pd.DataFrame(rows).sort_values("Since entry %", ascending=False).reset_index(drop=True)
    invested = float((df["Qty"] * df["Entry"]).sum())
    value = float((df["Qty"] * df["Live"]).sum())
    eod_value = float((df["Qty"] * df["Last EOD"]).sum())
    n = quotes.get(BENCHMARK_SYMBOL)
    nb = state["prices"].get(BENCHMARK_SYMBOL, {})
    n_eod = (nb.get(res["kpi"]["last_session"]) or {}).get("close")
    n_d0 = (nb.get(state["batch"]["signal_date"]) or {}).get("close")
    nifty_today = (n["price"] / n_eod - 1) * 100 if (n and n_eod) else None
    nifty_since = (n["price"] / n_d0 - 1) * 100 if (n and n_d0) else res["kpi"].get("nifty_ret")
    summ = {"invested": invested, "value": value, "pnl": value - invested,
            "ret": (value / invested - 1) * 100 if invested else 0.0,
            "today_pnl": value - eod_value, "today_pct": (value / eod_value - 1) * 100 if eod_value else 0.0,
            "winners": int((df["Since entry %"] > 0).sum()), "losers": int((df["Since entry %"] < 0).sum()),
            "covered": sum(1 for s in df["Symbol"] if s in quotes),
            "nifty_today": nifty_today, "nifty_since": nifty_since}
    summ["alpha"] = summ["ret"] - nifty_since if nifty_since is not None else None
    return df, summ


# --------------------------------------------------------------------------- #
# Latest data straight from the GitHub repo (the Action commits it every evening)
# --------------------------------------------------------------------------- #
def _headers(token: str | None) -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_remote_batches(repo: str, branch: str = "main", token: str | None = None) -> list[str]:
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/data/batches", params={"ref": branch},
                     headers=_headers(token), timeout=15)
    r.raise_for_status()
    return sorted([x["name"] for x in r.json() if x.get("type") == "dir" and not x["name"].endswith("-DEMO")],
                  reverse=True)


def load_remote_state(repo: str, batch_id: str, branch: str = "main", token: str | None = None) -> dict:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/data/batches/{batch_id}/state.json"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=20)
    r.raise_for_status()
    return json.loads(r.text)
