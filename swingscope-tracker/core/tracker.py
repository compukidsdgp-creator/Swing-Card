"""Batch state (JSON on disk) + all 21-day analytics."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .prices import BENCHMARK_SYMBOL, project_sessions

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "batches"
HOLD = 21
SRC_PRIORITY = {"yahoo": 1, "bhavcopy": 2, "manual": 3}


# --------------------------------------------------------------------------- #
# State persistence
# --------------------------------------------------------------------------- #
def batch_dir(batch_id: str) -> Path:
    p = DATA_DIR / batch_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_state(batch: dict, source_html: str | None = None) -> dict:
    st = {"batch": batch, "prices": {}, "entry_override": {}, "news": None,
          "created": datetime.now().isoformat(timespec="seconds"), "last_updated": None}
    if source_html:
        (batch_dir(batch["batch_id"]) / "source.html").write_text(source_html, encoding="utf-8")
    return st


def save_state(state: dict) -> Path:
    p = batch_dir(state["batch"]["batch_id"]) / "state.json"
    p.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    return p


def load_state(batch_id: str) -> dict | None:
    p = DATA_DIR / batch_id / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def list_batches() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted([p.name for p in DATA_DIR.iterdir() if (p / "state.json").exists()], reverse=True)


def merge_prices(state: dict, df: pd.DataFrame, source: str) -> int:
    """Merge tidy [date,symbol,open,close] rows. Higher-priority sources win."""
    n = 0
    sig = state["batch"]["signal_date"]
    for r in df.itertuples(index=False):
        if pd.isna(r.close) or r.date < sig:
            continue
        cell = state["prices"].setdefault(r.symbol, {}).get(r.date)
        if cell and SRC_PRIORITY.get(cell.get("src"), 0) > SRC_PRIORITY[source]:
            continue
        state["prices"][r.symbol][r.date] = {
            "open": None if pd.isna(r.open) else float(r.open),
            "close": float(r.close), "src": source}
        n += 1
    state["last_updated"] = datetime.now().isoformat(timespec="seconds")
    return n


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
def session_dates(state: dict) -> list[str]:
    """Day 0 = signal date, then real trading sessions seen in the price data (max 21)."""
    b = state["batch"]
    sig = b["signal_date"]
    syms = [s["symbol"] for s in b["stocks"]]
    counts: dict[str, int] = {}
    for s in syms:
        for d in state["prices"].get(s, {}):
            if d > sig:
                counts[d] = counts.get(d, 0) + 1
    need = max(1, len(syms) // 2)  # a session counts once half the basket has a close
    real = sorted(d for d, c in counts.items() if c >= need)[:HOLD]
    return [sig] + real


def phase_for(day: int) -> str:
    if day == 0:
        return "Signal day — buy at next open"
    if day == 1:
        return "Entry day (bought at open)"
    if day < 20:
        return "Holding"
    if day == 20:
        return "Exit reminder — sell tomorrow"
    return "Exit day — batch complete"


def compute(state: dict, today: date | None = None) -> dict:
    b = state["batch"]
    stocks = b["stocks"]
    syms = [s["symbol"] for s in stocks]
    today = today or date.today()

    dates = session_dates(state)
    cur_day = len(dates) - 1
    projected = project_sessions(b["signal_date"], HOLD)
    all_dates = dates + projected[cur_day:]  # real so far + projected rest
    all_dates = all_dates[: HOLD + 1]
    exit_date = all_dates[HOLD] if len(all_dates) > HOLD else b.get("exit_date_est")

    # ---- close matrix (symbols x Day0..Day21), NaN where not yet available ----
    day_cols = [f"Day {i}" for i in range(HOLD + 1)]
    closes = pd.DataFrame(np.nan, index=syms, columns=day_cols)
    srcs = pd.DataFrame("", index=syms, columns=day_cols)
    for s in stocks:
        closes.loc[s["symbol"], "Day 0"] = s["last_close"]
        srcs.loc[s["symbol"], "Day 0"] = "signal"
        for i, d in enumerate(dates[1:], start=1):
            cell = state["prices"].get(s["symbol"], {}).get(d)
            if cell:
                closes.loc[s["symbol"], f"Day {i}"] = cell["close"]
                srcs.loc[s["symbol"], f"Day {i}"] = cell["src"]
    # forward-fill gaps inside the elapsed window only (e.g., one missing print)
    elapsed = day_cols[: cur_day + 1]
    closes[elapsed] = closes[elapsed].ffill(axis=1)

    # ---- entry price: override > Day-1 open > Day-0 close ----
    entry, entry_src = {}, {}
    for s in stocks:
        sym = s["symbol"]
        ov = state.get("entry_override", {}).get(sym)
        d1 = state["prices"].get(sym, {}).get(dates[1]) if len(dates) > 1 else None
        if ov:
            entry[sym], entry_src[sym] = float(ov), "manual fill"
        elif d1 and d1.get("open"):
            entry[sym], entry_src[sym] = d1["open"], "Day-1 open"
        else:
            entry[sym], entry_src[sym] = s["last_close"], "Day-0 close (provisional)"

    qty = pd.Series({s["symbol"]: s["qty"] for s in stocks})
    entry_s = pd.Series(entry)
    invested = float((qty * entry_s).sum())
    cost_pct = (b.get("cost_pct") or 0.6) / 100

    last_close = closes[elapsed].iloc[:, -1]
    ret_pct = (last_close / entry_s - 1) * 100
    pnl = qty * (last_close - entry_s)
    prev_close = closes[elapsed].iloc[:, -2] if cur_day >= 1 else last_close
    day_chg = (last_close / prev_close - 1) * 100

    # ---- portfolio path ----
    value = (closes[elapsed].mul(qty, axis=0)).sum(axis=0)
    port = pd.DataFrame({
        "Day": range(cur_day + 1),
        "Date": dates,
        "Value": value.values,
    })
    port["P&L"] = port["Value"] - invested
    port.loc[0, "P&L"] = 0.0  # not in the market yet on Day 0
    port["Return %"] = port["P&L"] / invested * 100
    port["Daily %"] = port["Value"].pct_change() * 100
    port.loc[:1, "Daily %"] = np.nan
    peak = port["Value"].where(port["Day"] >= 1).cummax()
    port["Drawdown %"] = (port["Value"] / peak - 1) * 100

    # ---- benchmark (Nifty 50) rebased to Day 0 close ----
    bench = state["prices"].get(BENCHMARK_SYMBOL, {})
    bvals = [bench.get(d, {}).get("close") for d in dates]
    if bvals and any(v is not None for v in bvals[1:]):
        bser = pd.Series(bvals, dtype=float).ffill().bfill()
        port["Nifty %"] = (bser / bser.iloc[0] - 1) * 100
    else:
        port["Nifty %"] = np.nan

    # ---- stock table ----
    rows = []
    for s in stocks:
        sym = s["symbol"]
        path = closes.loc[sym, elapsed]
        path_after_entry = path.iloc[1:] if cur_day >= 1 else path
        rows.append({
            "#": s["rank"], "Symbol": sym, "Qty": s["qty"],
            "Signal close": s["last_close"], "Entry": entry[sym], "Entry basis": entry_src[sym],
            "Invested": s["qty"] * entry[sym],
            "Last close": last_close[sym], "Day chg %": day_chg[sym],
            "Return %": ret_pct[sym], "P&L": pnl[sym],
            "High close": path_after_entry.max(), "Low close": path_after_entry.min(),
            "Max gain %": (path_after_entry.max() / entry[sym] - 1) * 100,
            "Max loss %": (path_after_entry.min() / entry[sym] - 1) * 100,
            "12-1 %": s.get("ret_12_1"), "Vol %": s.get("volatility"),
        })
    table = pd.DataFrame(rows)
    table["Weight %"] = table["Invested"] / invested * 100
    table["Contribution %"] = table["P&L"] / invested * 100

    ret_matrix = closes[elapsed].div(entry_s, axis=0).sub(1).mul(100)
    ret_matrix["Day 0"] = np.nan

    gross = float(pnl.sum())
    costs = invested * cost_pct
    net = gross - costs
    kpi = {
        "batch_id": b["batch_id"],
        "today": today.strftime("%Y-%m-%d"),
        "day": cur_day,
        "last_session": dates[-1],
        "phase": phase_for(cur_day),
        "days_left": HOLD - cur_day,
        "exit_date": exit_date,
        "progress": cur_day / HOLD,
        "invested": invested,
        "value": float(value.iloc[-1]) if cur_day >= 1 else invested,
        "gross_pnl": gross if cur_day >= 1 else 0.0,
        "gross_ret": gross / invested * 100 if cur_day >= 1 else 0.0,
        "est_costs": costs,
        "net_pnl": net if cur_day >= 1 else -costs,
        "net_ret": net / invested * 100 if cur_day >= 1 else -cost_pct * 100,
        "nifty_ret": float(port["Nifty %"].iloc[-1]) if port["Nifty %"].notna().any() else None,
        "winners": int((ret_pct > 0).sum()) if cur_day >= 1 else 0,
        "losers": int((ret_pct < 0).sum()) if cur_day >= 1 else 0,
        "best": table.loc[table["Return %"].idxmax(), ["Symbol", "Return %"]].tolist(),
        "worst": table.loc[table["Return %"].idxmin(), ["Symbol", "Return %"]].tolist(),
        "max_dd": float(port["Drawdown %"].min()) if port["Drawdown %"].notna().any() else 0.0,
        "best_day": float(port["Daily %"].max()) if port["Daily %"].notna().any() else None,
        "worst_day": float(port["Daily %"].min()) if port["Daily %"].notna().any() else None,
        "today_chg": float(port["Daily %"].iloc[-1]) if cur_day >= 2 else None,
        "last_updated": state.get("last_updated"),
        "stale": dates[-1] < today.strftime("%Y-%m-%d") and cur_day < HOLD,
    }
    if kpi["nifty_ret"] is not None:
        kpi["alpha"] = kpi["gross_ret"] - kpi["nifty_ret"]
    else:
        kpi["alpha"] = None

    return {
        "kpi": kpi, "dates": dates, "all_dates": all_dates, "closes": closes, "sources": srcs,
        "ret_matrix": ret_matrix, "portfolio": port, "table": table, "entry": entry_s, "qty": qty,
    }
