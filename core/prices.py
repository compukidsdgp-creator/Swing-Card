"""Price sources: Yahoo Finance (auto), NSE bhavcopy upload, and manual entry.

All sources return a tidy DataFrame: columns [date, symbol, open, close]
with `date` as 'YYYY-MM-DD' strings.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pandas as pd

# NSE equity trading holidays (edit / extend yearly). Used ONLY to project
# future session dates; real session dates always come from actual price data.
NSE_HOLIDAYS = {
    # 2026
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
    "2026-12-25",
}

BENCHMARK_SYMBOL = "NIFTY50"
BENCHMARK_YF = "^NSEI"


def project_sessions(start: str, n: int, holidays: set[str] | None = None) -> list[str]:
    """Return the next `n` NSE trading dates strictly after `start`."""
    hol = holidays if holidays is not None else NSE_HOLIDAYS
    d = datetime.strptime(start, "%Y-%m-%d").date()
    out = []
    while len(out) < n:
        d += timedelta(days=1)
        s = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and s not in hol:
            out.append(s)
    return out


# --------------------------------------------------------------------------- #
# Yahoo Finance
# --------------------------------------------------------------------------- #
def fetch_yahoo(symbols: list[str], start: str, end: str | None = None,
                include_benchmark: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Download daily OHLC for NSE symbols via yfinance.

    Returns (tidy_df, errors). Never raises for network problems — errors are
    returned so the UI can fall back to bhavcopy / manual entry.
    """
    errors: list[str] = []
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(columns=["date", "symbol", "open", "close"]), ["yfinance not installed"]

    start_dt = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    end_dt = end or (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    tickers = {f"{s}.NS": s for s in symbols}
    if include_benchmark:
        tickers[BENCHMARK_YF] = BENCHMARK_SYMBOL

    frames = []
    try:
        raw = yf.download(list(tickers), start=start_dt, end=end_dt, interval="1d",
                          auto_adjust=False, progress=False, group_by="ticker", threads=True)
    except Exception as e:  # network / API failure
        return pd.DataFrame(columns=["date", "symbol", "open", "close"]), [f"Yahoo download failed: {e}"]

    for yt, sym in tickers.items():
        try:
            sub = raw[yt] if isinstance(raw.columns, pd.MultiIndex) else raw
            sub = sub[["Open", "Close"]].dropna(how="all")
            if sub.empty:
                errors.append(f"{sym}: no data from Yahoo")
                continue
            df = pd.DataFrame({
                "date": pd.to_datetime(sub.index).strftime("%Y-%m-%d"),
                "symbol": sym,
                "open": sub["Open"].astype(float).round(2).values,
                "close": sub["Close"].astype(float).round(2).values,
            })
            frames.append(df)
        except Exception as e:
            errors.append(f"{sym}: {e}")

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "open", "close"]), errors or ["No data returned"]
    return pd.concat(frames, ignore_index=True), errors


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
