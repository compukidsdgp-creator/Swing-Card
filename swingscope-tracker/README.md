# SwingScope 21-Day Batch Tracker

A Streamlit app that takes a **SwingScope momentum-batch HTML** and tracks its 10 stocks from **Day 0 (signal close) to Day 21 (exit)**. It keeps a formatted Excel tracker and a 21-day dashboard up to date, and adds a separate news and sentiment page.

## What it does

| Tab | What you get |
|---|---|
| **① Upload** | Upload the SwingScope HTML. The app reads the order ticket (symbol, ISIN, qty, last close, 12-1/6-1/3-1, volatility, liquidity, signal rank, data quality), the signal and exit dates, capital, costs and market regime. There's also a demo mode that uses simulated prices. |
| **② Daily update** | You can add closes three ways. **A** is Yahoo Finance, fetched with one click. **B** is an NSE bhavcopy upload (old `cm…bhav.csv` or the new UDiFF format, CSV or ZIP). **C** is manual entry, with an editable grid for corrections. You can also enter your broker's actual fill prices. |
| **③ Dashboard** | A 22-cell timeline with today's position, KPI tiles with sparklines, portfolio return vs Nifty 50 with the remaining sessions shaded, return by stock, a P&L waterfall, a stock × day heatmap, each stock's path, drawdown and daily change. |
| **④ Research & sentiment** | A **stock-by-stock research brief**: a view for each stock (strongest → bearish), a conviction meter, catalysts, risks and context with source links, and a ranked **swing-trade shortlist**. The brief can come from three places: **paste your own notes** (the "Stock by stock" format), **auto-generate** it from price data, P/E and news themes, or have **Claude with web search** write it (needs `ANTHROPIC_API_KEY`). The page adds a batch-mood gauge, a view-distribution bar, a **"call check"** on each stock (is the view playing out since entry?), a top-3 vs bottom-3 spread, a conviction-vs-outcome chart, the 12-month sparkline from the SwingScope HTML and then the live 21-day path, plus the positive-headline feed (Google News + Yahoo, scored with VADER plus a finance lexicon). Everything is exported as one HTML page. |
| **⑤ Downloads** | The Excel tracker on any day, the dashboard HTML, the positive-news HTML and a JSON backup. |

### Excel workbook

* **Dashboard**: KPI tiles, a progress bar, a stock league table and charts.
* **Daily Closes**: a Day 0 → Day 21 grid. The latest session is highlighted, and future sessions show projected dates. Last close, return, P&L and trend are live formulas.
* **Returns %**: close ÷ entry − 1, with a red → green colour scale. Every cell is a formula.
* **P&L**: qty × (close − entry) for each day, plus totals.
* **Portfolio Path**: value, P&L, return, daily %, drawdown and Nifty %, with a chart.
* **Batch Info**: everything parsed from the HTML, plus the backtest evidence.
* **Research**: the ranked shortlist (view, conviction, why, return since entry, call check), then every catalyst, risk and context point with its source link.
* **News & Sentiment**: headlines with scores and links.
* **_state** (hidden): the full tracker state. Upload the workbook through **Restore from a tracker Excel** to continue where you left off.

### Conventions

* **Day 0** is the signal-day close from the HTML.
* **Entry** is the Day-1 open. If that isn't available yet, the Day-0 close is used and marked provisional. A manual fill price overrides both.
* **Day N** is the N-th real NSE trading session after the signal. A session counts once at least half the basket has a close for that date.
* Future dates are projected with the NSE holiday list in `core/prices.py`. Update that list each year.
* **Net P&L** deducts the batch's estimated round-trip cost (0.6% in the HTML). **Nifty 50** is measured from the Day-0 close.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on GitHub + Streamlit Community Cloud

1. Push this folder to a new GitHub repo.
2. On share.streamlit.io, choose **New app**, pick the repo and set the main file to `app.py`.
3. **Daily auto-update:** `.github/workflows/daily_update.yml` runs `update_daily.py --news --telegram` Monday–Friday at 18:05 IST. It fetches closes and commits the refreshed `data/batches/<id>/` files (state, Excel, dashboard HTML, news HTML). The app redeploys from the repo, so it always shows the latest day. You can also start the workflow by hand from the **Actions** tab.
4. **Optional, closes the loop:** add `GITHUB_TOKEN`, `GITHUB_REPO` and `GITHUB_BRANCH` in the app's **Secrets** (see `.streamlit/secrets.toml.example`). Batches you upload and manual edits you make in the app are then committed to the repo, so the scheduled job picks them up too.

Streamlit Cloud's disk is temporary. If you don't use GitHub sync, download the Excel regularly and restore from it when needed.

## Day-end delivery to Telegram (after 6 PM IST)

Every weekday at **18:05 IST**, the GitHub Action updates the closes and sends your Telegram bot:

1. **A summary message:** Day X/21 with a progress bar, P&L (gross and net), value, today's change, Nifty and alpha, winners and losers, max drawdown, the top 3 leaders and laggards, today's biggest movers, how many research calls are on track, the shortlist top 3 and up to 3 positive headlines. On Day 20 it becomes an **"EXIT TOMORROW"** reminder, and on Day 21 a **"batch complete"** report.
2. **An album of 3 files:** the Excel tracker, the dashboard HTML and the research & sentiment HTML, named with the day and date (for example `…_tracker_D08_2026-10-09.xlsx`).

The report is sent **once per trading session**. On NSE holidays (no new close) and on reruns, nothing is sent.

### Setup (5 minutes)

1. In Telegram open **@BotFather** → `/newbot` → copy the **token**.
2. Open your new bot and send it any message (or add the bot to a group or channel).
3. Get your chat id:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC... python -m core.telegram --whoami
   ```
4. In GitHub → repo **Settings → Secrets and variables → Actions**, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (comma-separate several chats).
5. Test it: **Actions → Daily SwingScope update + Telegram → Run workflow** with *force_send* ticked.

Optional: add the same two values to the Streamlit app's Secrets to get **Send today's report** and **Send test message** buttons in the ⑤ Downloads tab.

To change the time, edit the `cron` line in `.github/workflows/daily_update.yml` (it's in UTC: `35 12 * * 1-5` = 18:05 IST).

## Command line

```bash
python update_daily.py                                   # update all active batches
python update_daily.py --news                            # + news & sentiment
python update_daily.py --html path/to/batch.html         # register a new batch, then update
python update_daily.py --batch 2026-09-28
python update_daily.py --batch 2026-09-28 --notes my_notes.txt   # attach your research write-up
python update_daily.py --news --telegram                 # the day-end job: update + send to Telegram
python update_daily.py --telegram --force-send           # resend today's report
python -m core.telegram --test                           # send a test message
```

### Research notes format

```
1. Laurus Labs (LAURUSLABS): strongest, bullish
FY26 profit after tax was ₹740 crore vs ₹380 crore the year before.
torusdigital                      <- source name on its own line, bound to the line above
P/E is high, so it can still pull back.
anandrathi

Swing-trade shortlist (21-session hold)
Rank	Stock	View	Why
1	LAURUSLABS	Bullish	Relative strength near highs, lowest volatility
```

Each sentence is classified automatically as a catalyst, risk or context point. Recognised views: strongest/bullish, bullish (high risk), moderately bullish, speculative / neutral to bullish, neutral, neutral to bearish, bearish. You can adjust any view, rank or reason in the app.

## Project layout

```
app.py                  Streamlit UI
update_daily.py         CLI / GitHub Actions entry point
core/parser.py          SwingScope HTML → batch dict
core/prices.py          Yahoo, bhavcopy, NSE calendar
core/tracker.py         state + all 21-day analytics
core/excel_builder.py   formatted workbook (openpyxl)
core/charts.py          Plotly figures (shared by app & HTML)
core/reports.py         dashboard HTML + positive-news HTML
core/news.py            news fetch + sentiment
core/research.py        research brief: notes parser, auto rules, Claude + web search, call check
core/research_report.py research & sentiment HTML
core/github_sync.py     optional push to repo
core/telegram.py        day-end summary + file delivery to a Telegram bot
data/batches/<id>/      state.json, source.html, xlsx, html outputs
```

This is a research tracking tool, not investment advice.
