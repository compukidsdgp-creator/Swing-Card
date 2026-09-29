"""Glue: update prices, rebuild outputs, persist — used by the app and the daily CLI."""
from __future__ import annotations

from pathlib import Path

from .excel_builder import build_workbook
from .prices import fetch_yahoo
from .reports import dashboard_html
from .research_report import research_html
from .tracker import HOLD, batch_dir, compute, merge_prices, save_state


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


def update_from_yahoo(state: dict) -> tuple[int, list[str]]:
    b = state["batch"]
    syms = [s["symbol"] for s in b["stocks"]]
    df, errors = fetch_yahoo(syms, b["signal_date"])
    n = merge_prices(state, df, "yahoo") if not df.empty else 0
    if df.empty and len(errors) > 3:
        errors = ["Yahoo Finance returned no data (network blocked, rate-limited, or market not yet updated)."]
    return n, errors


def is_complete(state: dict) -> bool:
    return compute(state)["kpi"]["day"] >= HOLD
