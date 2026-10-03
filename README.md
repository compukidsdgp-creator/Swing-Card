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

### Data reliability

* **Two price sources.** Yahoo Finance first, then NSE's official bhavcopy (and index closes) for every session not yet confirmed by NSE. The NSE print wins when both exist, which fills gaps when Yahoo is late or rate-limited.
* **Two evening runs.** 18:05 IST sends the report only when all 10 closes are in. 20:15 IST fills any gaps and sends if 18:05 couldn't; if a trading day produced no data at all, it sends a short alert instead. You never get the same day twice.
* **Bonuses and splits.** Prices are stored raw (as traded). Split/bonus events come from Yahoo, or are flagged when a close falls overnight by a bonus ratio (−50% ≈ 1:1 bonus, −33% ≈ 1:2, …). Every earlier price is divided by the ratio and the quantity multiplied, so a bonus never shows up as a fake crash. The Telegram message flags each event, and "suspected" ones should be verified. You can review, reject or add events in the app (② Daily update → Corporate actions). Dividends are recorded but not added to P&L.
* **Holiday calendar.** The official NSE holiday list is refreshed weekly into `data/nse_holidays.json`. Weekdays for which NSE published no bhavcopy are learned automatically (and unlearned if prices turn up later). If next year's list isn't out yet in December, exit dates for that year assume weekdays only, and the log says so.

### Conventions

* **Day 0** is the signal-day close from the HTML.
* **Entry** is the Day-1 open. If that isn't available yet, the Day-0 close is used and marked provisional. A manual fill price overrides both.
* **Day N** is the N-th real NSE trading session after the signal. A session counts once at least half the basket has a close for that date.
* Future dates are projected with the NSE holiday calendar (auto-refreshed, see above).
* **Net P&L** deducts the batch's estimated round-trip cost (0.6% in the HTML). **Nifty 50** is measured from the Day-0 close.

## 📡 Live dashboard (24x7)

`app.py` now opens on a read-only **Live dashboard**. The previous app is kept as **🛠 Manage & update** in the sidebar.

* **During market hours (09:15–15:30 IST):** live prices for your 10 stocks and the Nifty (Yahoo, delayed ~1–15 min), refreshed every 60 s. You get live value, P&L since entry, today's move in ₹ and %, Nifty today and alpha. Each stock row shows your research view next to it.
* **15:30 to 18:05:** today's provisional closes, until the official update lands.
* **Any other time:** the latest official closes.
* **Underneath:** the full **21-day performance** report and the **Research & sentiment** report as two tabs, with Excel/HTML downloads.
* **Data source:** the dashboard reads the latest data straight from your GitHub repo, so it's current as soon as the evening run commits. In Streamlit Cloud → App settings → Secrets, add:
  ```toml
  LIVE_REPO = "your-username/your-repo"
  # optional, avoids GitHub's anonymous rate limit on shared servers (read-only token is enough)
  GITHUB_TOKEN = "github_pat_..."
  ```
  Without `LIVE_REPO` it uses the files deployed with the app. Streamlit Cloud redeploys on each push, so those catch up too.
* **Free Streamlit Cloud:** apps go to sleep after a period with no visitors. Opening the link wakes the app in under a minute, and the data is always the latest when it wakes.

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

## Starting the next batch (every 21 days)

Upload the new SwingScope HTML into the **`inbox/`** folder of the repo (GitHub → `inbox` → **Add file → Upload files** → Commit).
You don't need the app or a computer for this.

* The Action starts right away. It registers the batch under `data/batches/<date>/`, builds the Excel and HTML files, and moves the upload to `inbox/processed/`.
* If you upload on the signal day (after the close), the **Day-0 "buy at next open"** message arrives in Telegram within a few minutes.
* From the next evening it is tracked at 18:05 IST until Day 21. Finished batches stop on their own, and overlapping batches are tracked side by side.
* **Research notes (optional):** upload a `.txt` with the **same name** as the HTML, or named `research_notes_<batch date>.txt`. You can add or replace notes later with that second name.

You can also still upload a new batch in the Streamlit app (tab ①). If you use the app on Streamlit Cloud, set `GITHUB_TOKEN`/`GITHUB_REPO` so the batch is saved to the repo.

## Day-end delivery to Telegram (after 6 PM IST)

Every weekday at **18:05 IST** (retry at **20:15 IST**), the GitHub Action updates the closes and sends your Telegram bot:

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

### Exact timing with cron-job.org (recommended)

GitHub's built-in schedule is best-effort and can start runs hours late. For on-time reports, let a free external scheduler start the workflow:

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate. Repository access: **only this repo**. Permissions: **Actions: Read and write**. Copy the token.
2. Create a free account at **cron-job.org** → *Create cronjob*:
   * URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily_update.yml/dispatches`
   * Schedule: custom, Mon–Fri **18:05**, time zone **Asia/Kolkata**
   * Advanced → Request method **POST**, headers
     `Authorization: Bearer <token>` · `Accept: application/vnd.github+json` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json`
   * Request body: `{"ref":"main","inputs":{"news":"true","final_attempt":"false"}}`
3. Clone that job for **20:15** with body `{"ref":"main","inputs":{"news":"true","final_attempt":"true"}}`.
4. Use *Test run*: the response should be **204**, and a "Manually run" workflow appears in Actions.

The GitHub schedule stays on as a backup. Duplicate runs are harmless because each session is sent only once.

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
