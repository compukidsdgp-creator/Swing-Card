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


COMMON_RATIOS = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0)


def applicable_actions(state: dict, last_session: str | None = None) -> dict[str, list[dict]]:
    """Split/bonus events that fall inside the hold (after the signal close, up to the latest session)."""
    sig = state["batch"]["signal_date"]
    out: dict[str, list[dict]] = {}
    for ev in state.get("corp_actions", []):
        if ev.get("kind") != "split" or ev.get("status") == "rejected" or not ev.get("ratio"):
            continue
        if ev["ex_date"] <= sig or (last_session and ev["ex_date"] > last_session):
            continue
        out.setdefault(ev["symbol"], []).append(ev)
    return out


def add_corp_actions(state: dict, events: list[dict]) -> list[dict]:
    """Merge events (from Yahoo, the detector or the user). Returns the ones that are new."""
    have = state.setdefault("corp_actions", [])
    new = []
    for ev in events:
        ev = dict(ev)
        ev.setdefault("status", "confirmed")
        ev.setdefault("added", datetime.now().strftime("%Y-%m-%d %H:%M"))
        dup = None
        for h in have:
            if h["symbol"] != ev["symbol"] or h["kind"] != ev["kind"]:
                continue
            gap = abs((datetime.strptime(h["ex_date"], "%Y-%m-%d") - datetime.strptime(ev["ex_date"], "%Y-%m-%d")).days)
            if h["ex_date"] == ev["ex_date"] or (ev["kind"] == "split" and gap <= 4):
                dup = h
                break
        if dup is None:
            have.append(ev)
            new.append(ev)
        elif dup.get("status") == "suspected" and ev.get("status") == "confirmed":
            dup.update({k: v for k, v in ev.items() if k != "added"})  # confirmation replaces a guess
    have.sort(key=lambda e: (e["ex_date"], e["symbol"]))
    return new


def detect_corp_actions(state: dict) -> list[dict]:
    """Flag overnight drops that match a bonus/split ratio (e.g. −50% = 1:1 bonus) that no source reported.
    NSE price bands make a genuine one-day fall of 33%+ very unlikely, so these are applied as 'suspected'."""
    b = state["batch"]
    found = []
    for s in b["stocks"]:
        sym = s["symbol"]
        series = [(b["signal_date"], s["last_close"])] + sorted(
            (d, c["close"]) for d, c in state["prices"].get(sym, {}).items() if d > b["signal_date"])
        for (d0, c0), (d1, c1) in zip(series, series[1:]):
            if not c0 or not c1 or c1 / c0 > 0.7:
                continue
            ratio = c0 / c1
            best = min(COMMON_RATIOS, key=lambda r: abs(ratio / r - 1))
            if abs(ratio / best - 1) <= 0.04:
                found.append({"symbol": sym, "ex_date": d1, "kind": "split", "ratio": best,
                              "source": "detected", "status": "suspected",
                              "note": f"close fell {c0:,.2f} → {c1:,.2f} overnight ({(c1 / c0 - 1) * 100:.0f}%)"})
    return add_corp_actions(state, found)


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

    # ---- corporate actions (splits / bonuses) applied during the hold ----
    # Prices are stored raw. Every price before an ex-date is divided by the ratio and the
    # quantity is multiplied, so returns and P&L stay continuous across a bonus or split.
    last_real = dates[-1]
    entry_date = dates[1] if len(dates) > 1 else None
    acts = applicable_actions(state, last_real)

    def factor(sym: str, d: str) -> float:
        f = 1.0
        for ev in acts.get(sym, []):
            if ev["ex_date"] > d:
                f *= ev["ratio"]
        return f

    # ---- close matrix (symbols x Day0..Day21), NaN where not yet available ----
    day_cols = [f"Day {i}" for i in range(HOLD + 1)]
    closes = pd.DataFrame(np.nan, index=syms, columns=day_cols)
    srcs = pd.DataFrame("", index=syms, columns=day_cols)
    for s in stocks:
        sym = s["symbol"]
        closes.loc[sym, "Day 0"] = s["last_close"] / factor(sym, b["signal_date"])
        srcs.loc[sym, "Day 0"] = "signal"
        for i, d in enumerate(dates[1:], start=1):
            cell = state["prices"].get(sym, {}).get(d)
            if cell:
                closes.loc[sym, f"Day {i}"] = cell["close"] / factor(sym, d)
                srcs.loc[sym, f"Day {i}"] = cell["src"]
    # forward-fill gaps inside the elapsed window only (e.g., one missing print)
    elapsed = day_cols[: cur_day + 1]
    closes[elapsed] = closes[elapsed].ffill(axis=1)

    # ---- entry price: override > Day-1 open > Day-0 close (all adjusted) ----
    entry, entry_src = {}, {}
    qty_mult = {}
    for s in stocks:
        sym = s["symbol"]
        ov = state.get("entry_override", {}).get(sym)
        d1 = state["prices"].get(sym, {}).get(dates[1]) if len(dates) > 1 else None
        f_entry = factor(sym, entry_date) if entry_date else factor(sym, b["signal_date"])
        if ov:
            entry[sym], entry_src[sym] = float(ov) / f_entry, "manual fill"
        elif d1 and d1.get("open"):
            entry[sym], entry_src[sym] = d1["open"] / f_entry, "Day-1 open"
        else:
            entry[sym], entry_src[sym] = s["last_close"] / factor(sym, b["signal_date"]), "Day-0 close (provisional)"
        qty_mult[sym] = f_entry
        if f_entry != 1.0:
            entry_src[sym] += f" · adj ×{f_entry:g}"

    qty = pd.Series({s["symbol"]: s["qty"] * qty_mult[s["symbol"]] for s in stocks})
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
            "#": s["rank"], "Symbol": sym, "Qty": qty[sym],
            "Signal close": closes.loc[sym, "Day 0"], "Entry": entry[sym], "Entry basis": entry_src[sym],
            "Invested": qty[sym] * entry[sym],
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
    last_d = dates[-1]
    kpi["coverage"] = (sum(1 for x in syms if state["prices"].get(x, {}).get(last_d)) if cur_day >= 1 else len(syms))
    kpi["n_stocks"] = len(syms)
    kpi["missing_today"] = [x for x in syms if cur_day >= 1 and not state["prices"].get(x, {}).get(last_d)]
    kpi["actions"] = [ev for evs in acts.values() for ev in evs]
    kpi["dividends"] = [ev for ev in state.get("corp_actions", []) if ev.get("kind") == "dividend"
                        and b["signal_date"] < ev["ex_date"] <= last_d]
    if kpi["nifty_ret"] is not None:
        kpi["alpha"] = kpi["gross_ret"] - kpi["nifty_ret"]
    else:
        kpi["alpha"] = None

    return {
        "kpi": kpi, "dates": dates, "all_dates": all_dates, "closes": closes, "sources": srcs,
        "ret_matrix": ret_matrix, "portfolio": port, "table": table, "entry": entry_s, "qty": qty,
    }
