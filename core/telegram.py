"""Ship the day-end summary + Excel/HTML files to a Telegram bot.

Setup (one time):
  1. In Telegram, talk to @BotFather -> /newbot -> copy the token.
  2. Send any message to your new bot (or add it to a group/channel).
  3. Find your chat id:   TELEGRAM_BOT_TOKEN=xxx python -m core.telegram --whoami
  4. Store TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub Actions secrets
     (and optionally in Streamlit secrets for the "Send now" button).

Env vars / secrets:
  TELEGRAM_BOT_TOKEN   123456:ABC...
  TELEGRAM_CHAT_ID     your numeric chat id (or -100... for a group/channel); comma-separate for several
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def config(secrets=None) -> tuple[str | None, list[str]]:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chats = os.environ.get("TELEGRAM_CHAT_ID")
    if secrets is not None:
        try:
            tok = tok or secrets.get("TELEGRAM_BOT_TOKEN")
            chats = chats or secrets.get("TELEGRAM_CHAT_ID")
        except Exception:
            pass
    ids = [c.strip() for c in str(chats or "").split(",") if c.strip()]
    return tok, ids


def enabled(secrets=None) -> bool:
    tok, ids = config(secrets)
    return bool(tok and ids)


def _call(token: str, method: str, timeout: int = 60, **kw) -> dict:
    r = requests.post(API.format(token=token, method=method), timeout=timeout, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"ok": False, "description": r.text[:300]}
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description', r.status_code)}")
    return data


# --------------------------------------------------------------------------- #
# Message
# --------------------------------------------------------------------------- #
def _pct(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _inr(v) -> str:
    if v is None:
        return "—"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}₹{abs(v):,.0f}"


def _dot(v) -> str:
    return "🟢" if (v or 0) > 0 else ("🔴" if (v or 0) < 0 else "⚪")


def summary_message(state: dict, res: dict) -> str:
    """HTML-formatted day-end summary (Telegram parse_mode=HTML, < 4096 chars)."""
    b, k = state["batch"], res["kpi"]
    e = html.escape
    t = res["table"].sort_values("Return %", ascending=False)
    bar_n = round(k["day"] / 21 * 14)
    bar = "▰" * bar_n + "▱" * (14 - bar_n)

    if k["day"] >= 21:
        head = f"🏁 <b>SwingScope {e(b['batch_id'])} — batch complete</b>"
    elif k["day"] == 20:
        head = f"⏰ <b>SwingScope {e(b['batch_id'])} — EXIT TOMORROW</b>"
    else:
        head = f"📈 <b>SwingScope {e(b['batch_id'])} — day-end update</b>"

    lines = [head,
             f"<b>Day {k['day']}/21</b> · {e(k['last_session'])} · {e(k['phase'])}",
             f"<code>{bar}</code> {k['days_left']} session{'s' if k['days_left'] != 1 else ''} left · exit ~{e(str(k['exit_date']))}",
             ""]
    if k["day"] >= 1 and k.get("coverage", k.get("n_stocks")) < k.get("n_stocks", 0):
        lines += [f"⚠️ Only {k['coverage']}/{k['n_stocks']} closes available today — "
                  f"missing {e(', '.join(k['missing_today']))} (last known price used).", ""]
    for ev in (state.get("pending_alerts") or []):
        tag = "suspected — please verify" if ev.get("status") == "suspected" else "confirmed"
        lines += [f"🔔 <b>Corporate action</b>: {e(ev['symbol'])} split/bonus ratio {ev['ratio']:g} "
                  f"(ex {e(ev['ex_date'])}, {tag}). Prices and quantity adjusted.", ""]
    if k["day"] >= 1:
        lines += [
            f"{_dot(k['gross_pnl'])} <b>P&amp;L {_inr(k['gross_pnl'])}</b> ({_pct(k['gross_ret'])})"
            f" · net {_inr(k['net_pnl'])}",
            f"💼 Value ₹{k['value']:,.0f} on ₹{k['invested']:,.0f} invested",
            f"📊 Today {_pct(k['today_chg'])} · Nifty {_pct(k['nifty_ret'])} · alpha {_pct(k['alpha'])}",
            f"🎯 Winners {k['winners']} / losers {k['losers']} · max drawdown {_pct(k['max_dd'])}",
            "",
            "<b>Leaders</b>",
        ]
        for _, r in t.head(3).iterrows():
            lines.append(f"{_dot(r['Return %'])} {e(r['Symbol'])} {_pct(r['Return %'])} ({_inr(r['P&L'])})")
        lines.append("<b>Laggards</b>")
        for _, r in t.tail(3).iloc[::-1].iterrows():
            lines.append(f"{_dot(r['Return %'])} {e(r['Symbol'])} {_pct(r['Return %'])} ({_inr(r['P&L'])})")
        movers = res["table"].dropna(subset=["Day chg %"]).sort_values("Day chg %")
        if k["day"] >= 2 and not movers.empty:
            up, dn = movers.iloc[-1], movers.iloc[0]
            lines += ["", f"⚡ Biggest move today: {e(up['Symbol'])} {_pct(up['Day chg %'])} · "
                          f"{e(dn['Symbol'])} {_pct(dn['Day chg %'])}"]
    else:
        lines += [f"Signal day — buy all {len(b['stocks'])} stocks at the next open.",
                  f"Capital ₹{(b.get('capital') or 0):,.0f} · regime {e(b.get('regime') or '—')}"]

    brief = state.get("research")
    if brief and brief.get("shortlist"):
        from .research import scorecard
        rows = scorecard(brief, res)
        judged = [r for r in rows if r["verdict"] and ("On track" in r["verdict"] or "Off track" in r["verdict"])]
        if judged:
            on = sum("On track" in r["verdict"] for r in judged)
            lines += ["", f"🧭 Research calls on track: <b>{on}/{len(judged)}</b>"]
        top = ", ".join(e(r["symbol"]) for r in rows[:3])
        lines.append(f"🏆 Shortlist top 3: {top}")

    news = state.get("news") or {}
    pos = sorted([i for i in news.get("items", []) if i["score"] >= 0.3 and i["symbol"] != "MARKET"],
                 key=lambda x: -x["score"])[:3]
    if pos:
        lines += ["", "<b>📰 Positive headlines</b>"]
        for i in pos:
            title = i["title"] if len(i["title"]) <= 110 else i["title"][:107] + "…"
            lines.append(f"• <a href=\"{e(i['link'])}\">{e(title)}</a> <i>({e(i['symbol'])})</i>")

    if k["day"] == 20:
        lines += ["", "⏰ <b>Place sell orders for all stocks for tomorrow (Day 21).</b>"]
    lines += ["", "<i>Files attached: Excel tracker · Dashboard · Research &amp; sentiment</i>"]
    msg = "\n".join(lines)
    return msg[:4000]


# --------------------------------------------------------------------------- #
# Send
# --------------------------------------------------------------------------- #
def send_report(state: dict, res: dict, files: list[Path], secrets=None, stamp: str = "") -> list[str]:
    """Send the summary message followed by the files (as one album when possible)."""
    tok, chats = config(secrets)
    if not (tok and chats):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured")
    msg = summary_message(state, res)
    files = [Path(f) for f in files if f and Path(f).exists()]
    log = []
    for chat in chats:
        _call(tok, "sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                                        "disable_web_page_preview": "true"})
        log.append(f"{chat}: summary sent")
        if not files:
            continue
        names = [_dated_name(f, stamp) for f in files]
        try:
            media, up = [], {}
            for i, (f, nm) in enumerate(zip(files, names)):
                key = f"file{i}"
                up[key] = (nm, f.read_bytes())
                item = {"type": "document", "media": f"attach://{key}"}
                if i == len(files) - 1:
                    item["caption"] = f"SwingScope {state['batch']['batch_id']} · Day {res['kpi']['day']}/21"
                media.append(item)
            if len(files) == 1:
                _call(tok, "sendDocument", timeout=120, data={"chat_id": chat, "caption": media[0].get("caption", "")},
                      files={"document": up["file0"]})
            else:
                _call(tok, "sendMediaGroup", timeout=180,
                      data={"chat_id": chat, "media": json.dumps(media)}, files=up)
            log.append(f"{chat}: {len(files)} files sent")
        except Exception as ex:  # album failed -> send one by one
            log.append(f"{chat}: album failed ({ex}); sending individually")
            for f, nm in zip(files, names):
                _call(tok, "sendDocument", timeout=120, data={"chat_id": chat},
                      files={"document": (nm, f.read_bytes())})
            log.append(f"{chat}: {len(files)} files sent")
    return log


def send_text(text: str, secrets=None) -> None:
    tok, chats = config(secrets)
    for chat in chats:
        _call(tok, "sendMessage", data={"chat_id": chat, "text": text, "parse_mode": "HTML"})


def _dated_name(f: Path, stamp: str) -> str:
    if not stamp:
        return f.name
    return f"{f.stem}_{stamp}{f.suffix}"


def whoami(token: str) -> None:
    me = _call(token, "getMe")["result"]
    print(f"Bot: @{me.get('username')} ({me.get('first_name')})")
    ups = _call(token, "getUpdates")["result"]
    seen = {}
    for u in ups:
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        c = m.get("chat") or {}
        if c:
            seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name")
    if not seen:
        print("No chats yet — send any message to the bot first, then run this again.")
    for cid, name in seen.items():
        print(f"TELEGRAM_CHAT_ID = {cid}    ({name})")


if __name__ == "__main__":
    if "--whoami" in sys.argv:
        t = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not t:
            sys.exit("Set TELEGRAM_BOT_TOKEN first.")
        whoami(t)
    elif "--test" in sys.argv:
        send_text("✅ SwingScope tracker: Telegram connection works.")
        print("Test message sent.")
    else:
        print(__doc__)
