"""Glue: update prices, rebuild outputs, persist — used by the app and the daily CLI."""
from __future__ import annotations

from pathlib import Path

from .excel_builder import build_workbook
from .prices import (NSENotPublished, fetch_nse_bhavcopy, fetch_yahoo, learn_holiday,
                     unlearn_holidays,
                     project_sessions)
from .reports import dashboard_html
from .research_report import research_html
from .tracker import HOLD, add_corp_actions, batch_dir, compute, detect_corp_actions, merge_prices, save_state


def output_paths(batch_id: str) -> dict[str, Path]:
    d = batch_dir(batch_id)
    return {"xlsx": d / f"SwingScope_{batch_id}_tracker.xlsx",
            "dashboard": d / f"SwingScope_{batch_id}_dashboard.html",
            "research": d / f"SwingScope_{batch_id}_research_sentiment.html",
            "state": d / "state.json"}


def rebuild_outputs(state: dict, min_news_score: float = 0.2) -> tuple[dict, dict[str, Path]]:
    """Recompute analytics, write Excel + HTML files and state.json. Returns (results, paths)."""
    res = compute(state)
    paths = output_paths(state["batch"]["batch_id"])
    save_state(state)
    paths["xlsx"].write_bytes(build_workbook(state, res))
    paths["dashboard"].write_text(dashboard_html(state, res), encoding="utf-8")
    paths["research"].write_text(research_html(state, res, min_news_score), encoding="utf-8")
    return res, paths


def update_prices(state: dict, use_nse: bool = True, today: str | None = None) -> dict:
    """Refresh prices from every source and handle corporate actions.

    1. Yahoo Finance (all sessions since the signal; raw prices + split/bonus/dividend events)
    2. NSE bhavcopy archives (official closes) for any session still missing from NSE — fills
       gaps when Yahoo is late or rate-limited, and replaces Yahoo values with the official print
    3. Detection of unreported bonuses/splits from overnight price gaps
    Also learns market holidays (weekdays for which NSE published no bhavcopy).
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    b = state["batch"]
    syms = [s["symbol"] for s in b["stocks"]]
    today = today or datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    out = {"yahoo": 0, "nse": 0, "errors": [], "notes": [], "new_actions": []}

    # 1 — Yahoo
    df, errors, events = fetch_yahoo(syms, b["signal_date"])
    if not df.empty:
        out["yahoo"] = merge_prices(state, df, "yahoo")
    if df.empty and len(errors) > 3:
        errors = ["Yahoo Finance returned no data (blocked, rate-limited, or not updated yet)."]
    out["errors"] += errors
    out["new_actions"] += add_corp_actions(state, events)

    # 2 — NSE bhavcopy for sessions not yet confirmed by NSE (or manual entry)
    if use_nse:
        import requests
        sess = requests.Session()
        candidates = [d for d in project_sessions(b["signal_date"], HOLD + 5) if d <= today]
        blocked = False
        for d in candidates:
            if blocked:
                break
            done = all((state["prices"].get(x, {}).get(d) or {}).get("src") in ("bhavcopy", "manual") for x in syms)
            if done:
                continue
            try:
                nse = fetch_nse_bhavcopy(d, syms, sess=sess)
                out["nse"] += merge_prices(state, nse, "bhavcopy")
            except NSENotPublished:
                have_any = any(state["prices"].get(x, {}).get(d) for x in syms)
                if d < today and not have_any:
                    if learn_holiday(d, "no NSE bhavcopy and no prices"):
                        out["notes"].append(f"Learned market holiday {d}")
                elif d == today:
                    out["notes"].append("NSE bhavcopy for today not published yet")
            except Exception as e:
                blocked = True
                out["notes"].append(f"NSE archives unreachable ({type(e).__name__}) - using Yahoo only this run")

    seen = {d for x in syms for d in state["prices"].get(x, {})}
    for d in unlearn_holidays(seen):
        out["notes"].append(f"Removed {d} from learned holidays (prices found)")

    # 3 — unreported bonus/split detection
    out["new_actions"] += detect_corp_actions(state)
    return out


def update_from_yahoo(state: dict) -> tuple[int, list[str]]:
    """Backward-compatible wrapper used by the Streamlit app."""
    r = update_prices(state)
    msgs = r["errors"] + r["notes"] + [
        f"Corporate action: {e['symbol']} ratio {e.get('ratio')} ex {e['ex_date']} ({e['status']})"
        for e in r["new_actions"] if e.get("kind") == "split"]
    return r["yahoo"] + r["nse"], msgs


def is_complete(state: dict) -> bool:
    return compute(state)["kpi"]["day"] >= HOLD
