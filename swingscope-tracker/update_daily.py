"""Daily updater — run after the NSE close (GitHub Actions or cron).

    python update_daily.py                 # update every active batch from Yahoo Finance
    python update_daily.py --news          # also refresh news & sentiment
    python update_daily.py --batch 2026-09-28
    python update_daily.py --html path/to/swingscope.html   # register a new batch first
    python update_daily.py --batch 2026-09-28 --notes my_notes.txt   # attach your research write-up
    python update_daily.py --news --telegram                 # day-end run: update + send to Telegram
    python update_daily.py --telegram --force-send           # resend today's report
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from core.news import collect_news
from core.parser import parse_swingscope_html
from core.research import auto_research, fetch_fundamentals, parse_notes
from core import telegram
from core.service import rebuild_outputs, update_from_yahoo
from core.tracker import HOLD, compute, list_batches, load_state, new_state, save_state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", help="Only this batch id")
    ap.add_argument("--html", help="Register a new SwingScope HTML before updating")
    ap.add_argument("--news", action="store_true", help="Refresh news & sentiment too")
    ap.add_argument("--news-days", type=int, default=7)
    ap.add_argument("--notes", help="Attach a research-notes text file (Stock by stock format) to the batch")
    ap.add_argument("--telegram", action="store_true", help="Send summary + Excel/HTML to the Telegram bot")
    ap.add_argument("--force-send", action="store_true",
                    help="Send even if there is no new session today or it was already sent")
    ap.add_argument("--include-complete", action="store_true", help="Also touch batches past Day 21")
    a = ap.parse_args()

    if a.html:
        raw = Path(a.html).read_text(encoding="utf-8")
        b = parse_swingscope_html(raw)
        if load_state(b["batch_id"]) is None:
            rebuild_outputs(new_state(b, raw))
            print(f"Registered batch {b['batch_id']}")
        a.batch = a.batch or b["batch_id"]

    ids = [a.batch] if a.batch else list_batches()
    if not ids:
        print("No batches found in data/batches — upload an HTML in the app or pass --html.")
        return 0

    for bid in ids:
        state = load_state(bid)
        if state is None or bid.endswith("-DEMO"):
            continue
        before = compute(state)["kpi"]["day"]
        if before >= HOLD and not a.include_complete:
            print(f"[{bid}] complete (Day {before}) — skipped")
            continue
        n, errs = update_from_yahoo(state)
        syms = [s["symbol"] for s in state["batch"]["stocks"]]
        if a.notes:
            txt = Path(a.notes).read_text(encoding="utf-8")
            state["research"], state["research_notes"] = parse_notes(txt, state["batch"]), txt
        if a.news:
            if not state.get("fundamentals"):
                state["fundamentals"] = {s_: fetch_fundamentals(s_) for s_ in syms}
            state["news"] = collect_news(syms, state.get("names"), a.news_days)
        if (state.get("research") or {"method": "auto"}).get("method") == "auto" and state.get("news"):
            state["research"] = auto_research(state, compute(state))
        res, paths = rebuild_outputs(state)
        k = res["kpi"]
        print(f"[{bid}] +{n} prices · Day {before} → {k['day']} · gross {k['gross_ret']:+.2f}% "
              f"· P&L ₹{k['gross_pnl']:,.0f} · files: {paths['xlsx'].name}")
        for e in errs[:10]:
            print(f"   ! {e}")

        if a.telegram:
            ship(state, res, paths, a.force_send)
    return 0


def ship(state: dict, res: dict, paths: dict, force: bool) -> None:
    """Send the day-end report once per new trading session."""
    bid, k = state["batch"]["batch_id"], res["kpi"]
    if not telegram.enabled():
        print(f"[{bid}] Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipped")
        return
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    already = state.get("telegram_sent") == k["last_session"]
    fresh = k["last_session"] == today
    if not force and (already or not fresh):
        why = "already sent for this session" if already else f"no new session today (last {k['last_session']})"
        print(f"[{bid}] Telegram: {why} — skipped (use --force-send to override)")
        return
    stamp = f"D{k['day']:02d}_{k['last_session']}"
    files = [paths["xlsx"], paths["dashboard"], paths["research"]]
    try:
        for line in telegram.send_report(state, res, files, stamp=stamp):
            print(f"[{bid}] Telegram: {line}")
        state["telegram_sent"] = k["last_session"]
        save_state(state)
    except Exception as ex:
        print(f"[{bid}] Telegram ERROR: {ex}")


if __name__ == "__main__":
    sys.exit(main())
