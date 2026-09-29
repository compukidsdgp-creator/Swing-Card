"""Price sources: Yahoo Finance, NSE bhavcopy (auto-download or upload), manual entry; NSE calendar.

All sources return a tidy DataFrame: columns [date, symbol, open, close]
with `date` as 'YYYY-MM-DD' strings.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# NSE trading calendar
# --------------------------------------------------------------------------- #
# Built-in list (fallback). The live list is refreshed from NSE into
# data/nse_holidays.json, and weekdays on which NSE published no bhavcopy are
# learned automatically. Real session dates always come from price data; the
# calendar is only used to project future sessions and the exit date.
BUILTIN_HOLIDAYS = {
    # 2026
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
    "2026-12-25",
}
HOLIDAY_FILE = Path(__file__).resolve().parent.parent / "data" / "nse_holidays.json"
NSE_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36", "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}


def _read_holiday_file() -> dict:
    try:
        return json.loads(HOLIDAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"nse": {}, "learned": {}, "updated": None}


def load_holidays() -> set[str]:
    data = _read_holiday_file()
    hol = set(BUILTIN_HOLIDAYS)
    hol |= set(data.get("nse", {}).keys())
    hol |= set(data.get("learned", {}).keys())
    return hol


def holiday_years_covered() -> set[int]:
    data = _read_holiday_file()
    years = {int(d[:4]) for d in BUILTIN_HOLIDAYS} | {int(d[:4]) for d in data.get("nse", {})}
    return years


def learn_holiday(day: str, reason: str) -> bool:
    """Record a weekday on which the market was closed (no NSE bhavcopy published)."""
    data = _read_holiday_file()
    if day in data.get("nse", {}) or day in data.get("learned", {}) or day in BUILTIN_HOLIDAYS:
        return False
    data.setdefault("learned", {})[day] = reason
    HOLIDAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLIDAY_FILE.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return True


def unlearn_holidays(days_with_prices: set[str]) -> list[str]:
    """Remove learned holidays for which prices turned up later (e.g. NSE archive was just late)."""
    data = _read_holiday_file()
    wrong = [d for d in data.get("learned", {}) if d in days_with_prices]
    if wrong:
        for d in wrong:
            data["learned"].pop(d, None)
        HOLIDAY_FILE.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return wrong


def refresh_nse_holidays(force: bool = False) -> str:
    """Download the official NSE equity (CM) trading-holiday list. Safe to call daily:
    it only hits NSE when the cached list is older than 7 days or doesn't cover next year."""
    data = _read_holiday_file()
    today = date.today()
    fresh = data.get("updated") and (today - datetime.strptime(data["updated"], "%Y-%m-%d").date()).days < 7
    if fresh and not force:
        return "holiday list up to date"
    try:
        sess = requests.Session()
        sess.headers.update(NSE_UA)
        sess.get("https://www.nseindia.com/", timeout=15)
        r = sess.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=15,
                     headers={"Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"})
        r.raise_for_status()
        rows = r.json().get("CM", [])
        got = {}
        for row in rows:
            d = datetime.strptime(row["tradingDate"], "%d-%b-%Y").strftime("%Y-%m-%d")
            got[d] = row.get("description", "").strip()
        if not got:
            raise ValueError("empty list")
        data.setdefault("nse", {}).update(got)
        data["updated"] = today.strftime("%Y-%m-%d")
        HOLIDAY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HOLIDAY_FILE.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return f"NSE holiday list refreshed ({len(got)} dates)"
    except Exception as e:
        return f"NSE holiday list not refreshed ({type(e).__name__}); using cached/built-in list"


BENCHMARK_SYMBOL = "NIFTY50"
BENCHMARK_YF = "^NSEI"


def project_sessions(start: str, n: int, holidays: set[str] | None = None) -> list[str]:
    """Return the next `n` NSE trading dates strictly after `start`."""
    hol = holidays if holidays is not None else load_holidays()
    d = datetime.strptime(start, "%Y-%m-%d").date()
    out = []
    while len(out) < n:
        d += timedelta(days=1)
        s = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and s not in hol:
            out.append(s)
    return out


def is_trading_day(day: str) -> bool:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return d.weekday() < 5 and day not in load_holidays()


# --------------------------------------------------------------------------- #
# Yahoo Finance
# --------------------------------------------------------------------------- #
EMPTY = ["date", "symbol", "open", "close"]


def fetch_yahoo(symbols: list[str], start: str, end: str | None = None,
                include_benchmark: bool = True) -> tuple[pd.DataFrame, list[str], list[dict]]:
    """Download daily OHLC for NSE symbols via yfinance.

    Returns (tidy_df, errors, events).
    * Prices are returned RAW (as traded that day): Yahoo back-adjusts history for
      splits/bonuses, so we undo that — the tracker applies its own, consistent adjustment.
    * events: [{"symbol", "ex_date", "kind": "split"|"dividend", "ratio"|"amount", "source": "yahoo"}]
    Never raises for network problems.
    """
    errors: list[str] = []
    events: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(columns=EMPTY), ["yfinance not installed"], []

    start_dt = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    end_dt = end or (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    tickers = {f"{s}.NS": s for s in symbols}
    if include_benchmark:
        tickers[BENCHMARK_YF] = BENCHMARK_SYMBOL

    frames = []
    try:
        raw = yf.download(list(tickers), start=start_dt, end=end_dt, interval="1d", actions=True,
                          auto_adjust=False, progress=False, group_by="ticker", threads=True)
    except Exception as e:  # network / API failure
        return pd.DataFrame(columns=EMPTY), [f"Yahoo download failed: {e}"], []

    for yt, sym in tickers.items():
        try:
            sub = raw[yt] if isinstance(raw.columns, pd.MultiIndex) else raw
            sub = sub.dropna(subset=["Close"], how="all")
            if sub.empty:
                errors.append(f"{sym}: no data from Yahoo")
                continue
            idx = pd.to_datetime(sub.index).strftime("%Y-%m-%d")
            splits = sub["Stock Splits"].fillna(0) if "Stock Splits" in sub else pd.Series(0, index=sub.index)
            divs = sub["Dividends"].fillna(0) if "Dividends" in sub else pd.Series(0, index=sub.index)
            split_list = [(d, float(r)) for d, r in zip(idx, splits.values) if r and float(r) not in (0.0, 1.0)]
            for d, r in split_list:
                events.append({"symbol": sym, "ex_date": d, "kind": "split", "ratio": r, "source": "yahoo"})
            for d, a in zip(idx, divs.values):
                if a and float(a) > 0:
                    events.append({"symbol": sym, "ex_date": d, "kind": "dividend", "amount": float(a),
                                   "source": "yahoo"})
            # undo Yahoo's back-adjustment: raw = adjusted x product(ratios with ex_date > d)
            factor = [1.0] * len(idx)
            for i, d in enumerate(idx):
                for ed, r in split_list:
                    if ed > d:
                        factor[i] *= r
            df = pd.DataFrame({
                "date": idx, "symbol": sym,
                "open": (sub["Open"].astype(float).values * factor).round(2),
                "close": (sub["Close"].astype(float).values * factor).round(2),
            })
            frames.append(df)
        except Exception as e:
            errors.append(f"{sym}: {e}")

    if not frames:
        return pd.DataFrame(columns=EMPTY), errors or ["No data returned"], events
    return pd.concat(frames, ignore_index=True), errors, events


# --------------------------------------------------------------------------- #
# NSE archives: daily bhavcopy + index closes (official, unadjusted)
# --------------------------------------------------------------------------- #
class NSENotPublished(Exception):
    """NSE has no file for that date (holiday, or not published yet)."""


def _nse_get(url: str, sess: requests.Session) -> bytes:
    r = sess.get(url, timeout=25)
    if r.status_code == 404:
        raise NSENotPublished(url)
    r.raise_for_status()
    if len(r.content) < 200:
        raise NSENotPublished(url)
    return r.content


def fetch_nse_bhavcopy(day: str, symbols: list[str], include_benchmark: bool = True,
                       sess: requests.Session | None = None) -> pd.DataFrame:
    """Official NSE close/open for `symbols` on `day` (YYYY-MM-DD).
    Raises NSENotPublished when NSE has no file for that date."""
    sess = sess or requests.Session()
    sess.headers.update(NSE_UA)
    d = datetime.strptime(day, "%Y-%m-%d")
    urls = [
        (f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip", "x.zip"),
        (f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv", "x.csv"),
    ]
    last: Exception | None = None
    df = None
    for url, name in urls:
        try:
            df = parse_bhavcopy(_nse_get(url, sess), name, symbols)
            break
        except NSENotPublished as e:
            last = e
        except Exception as e:
            last = e
    if df is None:
        if isinstance(last, NSENotPublished):
            raise last
        raise RuntimeError(f"NSE bhavcopy {day}: {last}")
    if include_benchmark:
        try:
            raw = _nse_get(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv", sess)
            idx = pd.read_csv(io.BytesIO(raw))
            idx.columns = [c.strip() for c in idx.columns]
            row = idx[idx["Index Name"].astype(str).str.strip().str.upper() == "NIFTY 50"]
            if not row.empty:
                df = pd.concat([df, pd.DataFrame([{
                    "date": day, "symbol": BENCHMARK_SYMBOL,
                    "open": pd.to_numeric(row["Open Index Value"], errors="coerce").iloc[0],
                    "close": pd.to_numeric(row["Closing Index Value"], errors="coerce").iloc[0]}])],
                    ignore_index=True)
        except Exception:
            pass
    return df


# --------------------------------------------------------------------------- #
# NSE bhavcopy (old CM format and new UDiFF format)
# --------------------------------------------------------------------------- #
def parse_bhavcopy(file_bytes: bytes, filename: str, symbols: list[str]) -> pd.DataFrame:
    """Extract open/close for `symbols` (EQ/BE series) from an NSE bhavcopy CSV or ZIP."""
    name = filename.lower()
    if name.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            inner = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            file_bytes = z.read(inner)
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = [c.strip() for c in df.columns]
    cols = {c.upper(): c for c in df.columns}

    if "TCKRSYMB" in cols:  # UDiFF (2024+)
        sym_c, ser_c, open_c, close_c = cols["TCKRSYMB"], cols.get("SCTYSRS"), cols["OPNPRIC"], cols["CLSPRIC"]
        date_c = cols.get("TRADDT") or cols.get("BIZDT")
    elif "SYMBOL" in cols:  # classic cm..bhav.csv / sec_bhavdata_full
        sym_c, ser_c = cols["SYMBOL"], cols.get("SERIES")
        open_c = cols.get("OPEN") or cols.get("OPEN_PRICE")
        close_c = cols.get("CLOSE") or cols.get("CLOSE_PRICE")
        date_c = cols.get("TIMESTAMP") or cols.get("DATE1")
    else:
        raise ValueError("Unrecognised bhavcopy format (need SYMBOL/CLOSE or TckrSymb/ClsPric columns).")

    d = df.copy()
    d[sym_c] = d[sym_c].astype(str).str.strip()
    if ser_c:
        d[ser_c] = d[ser_c].astype(str).str.strip()
        d = d[d[ser_c].isin(["EQ", "BE", "BZ", "SM", "ST"])]
    d = d[d[sym_c].isin(symbols)]
    if d.empty:
        raise ValueError("None of the batch symbols were found in this bhavcopy.")
    raw_d = d[date_c].astype(str).str.strip().iloc[0]
    iso = len(raw_d) >= 10 and raw_d[4] == "-"
    trade_date = pd.to_datetime(raw_d, dayfirst=not iso).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": trade_date,
        "symbol": d[sym_c].values,
        "open": pd.to_numeric(d[open_c], errors="coerce").values,
        "close": pd.to_numeric(d[close_c], errors="coerce").values,
    })


def synthetic_prices(batch: dict, n_days: int, seed: int = 7) -> pd.DataFrame:
    """Demo/test data: random-walk closes for the first n_days sessions."""
    import numpy as np
    rng = np.random.default_rng(seed)
    sessions = project_sessions(batch["signal_date"], n_days)
    rows = []
    for s in batch["stocks"] + [{"symbol": BENCHMARK_SYMBOL, "last_close": 24500.0, "volatility": 14}]:
        px = s["last_close"]
        daily_vol = (s.get("volatility") or 40) / 100 / (252 ** 0.5)
        for d in sessions:
            o = px * (1 + rng.normal(0, daily_vol / 3))
            px = o * (1 + rng.normal(0.0012, daily_vol))
            rows.append({"date": d, "symbol": s["symbol"], "open": round(o, 2), "close": round(px, 2)})
    return pd.DataFrame(rows)
