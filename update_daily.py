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
from core.prices import holiday_years_covered, is_trading_day, refresh_nse_holidays
from core.service import rebuild_outputs, update_prices
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
    ap.add_argument("--final-attempt", action="store_true",
                    help="Last run of the evening: send even if some closes are still missing, "
                         "and alert if no data arrived on a trading day")
    ap.add_argument("--no-nse", action="store_true", help="Skip the NSE bhavcopy download")
    ap.add_argument("--include-complete", action="store_true", help="Also touch batches past Day 21")
    a = ap.parse_args()

    if a.html:
        raw = Path(a.html).read_text(encoding="utf-8")
        b = parse_swingscope_html(raw)
        if load_state(b["batch_id"]) is None:
            rebuild_outputs(new_state(b, raw))
            print(f"Registered batch {b['batch_id']}")
        a.batch = a.batch or b["batch_id"]

    print(f"[calendar] {refresh_nse_holidays()}")
    nxt = datetime.now(ZoneInfo("Asia/Kolkata")).year + 1
    if datetime.now(ZoneInfo("Asia/Kolkata")).month == 12 and nxt not in holiday_years_covered():
        print(f"[calendar] ! {nxt} holiday list not available yet - exit dates for {nxt} assume weekdays only")
    process_inbox()

    ids = [a.batch] if a.batch else list_batches()
    if not ids:
        print("No batches found in data/batches — upload an HTML in the app or pass --html.")
        return 0

    failed = False
    for bid in ids:
        state = load_state(bid)
        if state is None or bid.endswith("-DEMO"):
            continue
        before = compute(state)["kpi"]["day"]
        if before >= HOLD and not a.include_complete:
            print(f"[{bid}] complete (Day {before}) — skipped")
            continue
        upd = update_prices(state, use_nse=not a.no_nse)
        n, errs = upd["yahoo"] + upd["nse"], upd["errors"]
        for note in upd["notes"]:
            print(f"[{bid}] {note}")
        for ev in upd["new_actions"]:
            if ev["kind"] == "split":
                print(f"[{bid}] CORPORATE ACTION {ev['symbol']}: ratio {ev['ratio']} ex {ev['ex_date']} "
                      f"({ev['status']}, {ev['source']}) - prices and qty adjusted")
                state.setdefault("pending_alerts", []).append(ev)
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
        print(f"[{bid}] +{upd['yahoo']} Yahoo / +{upd['nse']} NSE prices · coverage {k['coverage']}/{k['n_stocks']}")
        print(f"[{bid}] Day {before} → {k['day']} · gross {k['gross_ret']:+.2f}% "
              f"· P&L ₹{k['gross_pnl']:,.0f} · files: {paths['xlsx'].name}")
        for e in errs[:10]:
            print(f"   ! {e}")

        if a.telegram and not ship(state, res, paths, a.force_send, a.final_attempt):
            failed = True
    if failed:
        print("::error::Telegram delivery failed - see the lines above")
    return 1 if failed else 0


INBOX = Path(__file__).resolve().parent / "inbox"


def process_inbox() -> list[str]:
    """Register every SwingScope HTML dropped into inbox/ (plus optional research notes .txt).

    inbox/anything.html               -> new batch (batch id = date in the HTML title)
    inbox/<same name>.txt  or  inbox/research_notes_<batch id>.txt   -> your research notes
    Processed files are moved to inbox/processed/.
    """
    if not INBOX.exists():
        return []
    done = INBOX / "processed"
    new_ids = []
    for html_f in sorted(INBOX.glob("*.htm*")):
        try:
            raw = html_f.read_text(encoding="utf-8", errors="ignore")
            b = parse_swingscope_html(raw)
        except Exception as ex:
            print(f"[inbox] {html_f.name}: not a SwingScope batch HTML ({ex}) - left in inbox")
            continue
        bid = b["batch_id"]
        if load_state(bid) is None:
            state = new_state(b, raw)
            print(f"[inbox] Registered new batch {bid} from {html_f.name} ({len(b['stocks'])} stocks)")
        else:
            state = load_state(bid)
            print(f"[inbox] Batch {bid} already exists - kept its price history")
        for notes in (html_f.with_suffix(".txt"), INBOX / f"research_notes_{bid}.txt"):
            if notes.exists():
                txt = notes.read_text(encoding="utf-8", errors="ignore")
                state["research"], state["research_notes"] = parse_notes(txt, b), txt
                print(f"[inbox] Attached research notes {notes.name}")
                done.mkdir(exist_ok=True)
                notes.rename(done / notes.name)
                break
        rebuild_outputs(state)
        done.mkdir(exist_ok=True)
        html_f.rename(done / html_f.name)
        new_ids.append(bid)
    # notes uploaded later for an existing batch: inbox/research_notes_<id>.txt
    for notes in sorted(INBOX.glob("research_notes_*.txt")):
        bid = notes.stem.replace("research_notes_", "")
        state = load_state(bid)
        if state is None:
            print(f"[inbox] {notes.name}: no batch {bid} yet - left in inbox")
            continue
        txt = notes.read_text(encoding="utf-8", errors="ignore")
        state["research"], state["research_notes"] = parse_notes(txt, state["batch"]), txt
        rebuild_outputs(state)
        done.mkdir(exist_ok=True)
        notes.rename(done / notes.name)
        print(f"[inbox] Updated research notes for batch {bid}")
    return new_ids


def ship(state: dict, res: dict, paths: dict, force: bool, final: bool = False) -> bool:
    """Send the day-end report once per trading session. Returns False only on a real failure.

    * 18:05 run: sends only when every stock has today's close.
    * 20:15 run (--final-attempt): sends even if a few closes are missing (flagged in the message),
      and alerts you if a trading day produced no data at all.
    """
    bid, k = state["batch"]["batch_id"], res["kpi"]
    if not telegram.enabled():
        print(f"[{bid}] Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - add them as repository secrets")
        return False
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    already = state.get("telegram_sent") == k["last_session"]
    fresh = k["last_session"] == today
    complete = k["coverage"] >= k["n_stocks"]
    try:
        if not force:
            if already:
                print(f"[{bid}] Telegram: already sent for {k['last_session']} - skipped")
                return True
            if not fresh:
                if final and is_trading_day(today) and k["day"] < 21 and state.get("telegram_alert") != today:
                    telegram.send_text(
                        f"⚠️ <b>SwingScope {bid}</b>: no closing prices for today ({today}) from Yahoo or NSE "
                        f"by 20:15 IST. Tracker is still at Day {k['day']} ({k['last_session']}). "
                        f"It will catch up automatically on the next run.")
                    state["telegram_alert"] = today
                    save_state(state)
                    print(f"[{bid}] Telegram: no data today - alert sent")
                else:
                    print(f"[{bid}] Telegram: no new session today (last {k['last_session']}) - skipped")
                return True
            if not complete and not final:
                print(f"[{bid}] Telegram: only {k['coverage']}/{k['n_stocks']} closes for today "
                      f"(missing {', '.join(k['missing_today'])}) - waiting for the 20:15 retry")
                return True
        stamp = f"D{k['day']:02d}_{k['last_session']}"
        files = [paths["xlsx"], paths["dashboard"], paths["research"]]
        for line in telegram.send_report(state, res, files, stamp=stamp):
            print(f"[{bid}] Telegram: {line}")
        state["telegram_sent"] = k["last_session"]
        state["pending_alerts"] = []
        save_state(state)
        return True
    except Exception as ex:
        print(f"[{bid}] Telegram ERROR: {ex}")
        return False


if __name__ == "__main__":
    sys.exit(main())
