# DreamTradeSetup

A rule-based swing-trade setup finder for US stocks. Pick a sector (or type in specific
tickers), run a scan, and get a ranked list of stocks currently sitting in a tradeable
technical setup — with entry, target, and stop-loss levels computed for you.

No sign-in, no LLM calls per stock, no paid data — everything runs locally against free
Yahoo Finance data.

## How it works

1. **Universe** — S&P 500 + S&P 400 MidCap constituents with GICS sector, scraped from
   Wikipedia and cached. You can also force-include any specific ticker (e.g. one not in
   either index) via the "Add specific tickers" box.
2. **Screen** — for every ticker, three purely mechanical detectors run against ~13 months
   of daily price history. All three first require **annualized realized volatility ≥ 40%**
   ([`src/screener.py`](src/screener.py) `MIN_ANNUALIZED_VOL_PCT`) — below that, a stock is
   a slow compounder (e.g. MSCI ~30%, SYK ~36%) that can form a technically valid setup
   without ever delivering a swing-sized move in weeks rather than years:
   - **Sideways Range**: flat trend over the last 6 months, trading inside a
     support/resistance channel that's been tested at least 3 times. Entry = support,
     target = the middle of the channel, stop = half an ATR below the channel's lowest low.
     (The original rules - target at the top, stop 1 ATR under support - won only 13% of
     backtested trades; these won ~59%.)
   - **Near 52-Week Low**: price within 8% of its 52-week low, off the low for a few days
     (not making fresh lows right now) and not in a sharp ongoing plunge. Entry = just
     above the 52-week low, target = the local high since the bottom, stop = 5% below
     the 52-week low.
   - **Uptrend Pullback**: a confirmed uptrend (rising 50-day average, tested as support
     at least twice) that has pulled back 5–25% off its recent high without breaking that
     trend. Entry = the rising 50-day average, target = the recent high, stop = pullback
     low minus 1×ATR(14). This is the "buy the dip in a mover" case (e.g. NBIS) that the
     other two detectors miss, since they're both mean-reversion strategies. It only fires
     while the S&P 500 is at or below its 50-day average: backtests showed pullbacks bought
     during a market-wide dip won ~74% of the time, while pullbacks in a calm market broke
     even (the Scanner shows a banner while it's paused).
3. **Rate** — each setup gets a 0–100 composite score from reward:risk, how close the
   current price is to the ideal entry right now, how well-formed the setup is, and how
   volatile the stock is. The score maps to STRONG BUY / BUY / HOLD / SELL / STRONG SELL.
   A separate **Entry Status** (At Entry / Near Entry / Waiting for Pullback) tells you
   whether *today's* price has actually reached the entry level, independent of the
   overall rating. All thresholds live in [`src/rating.py`](src/rating.py) and
   [`src/screener.py`](src/screener.py) — nothing is a black box.
4. **Dashboard** — filter by sector or type specific tickers, see the ranked table, click a
   row for a candlestick chart with entry/target/stop drawn on it, and size your position
   with the built-in risk calculator. A ticker you explicitly typed in always shows up even
   when it doesn't qualify for any setup — marked **Filtered Out** with a plain-language
   reason instead of silently disappearing.

## Paper trading

The **Paper Trading** page (sidebar) forward-tests the screener's own signals with simulated
money before you trust them with real money. Each time the page opens (or you run
`make paper`), it:

1. Walks every open position through each new daily bar and closes it at its take-profit or
   stop-loss. Gaps fill at the open. If one day touches both levels, that day's hourly prices
   decide which came first (fetched only for those rare days); if hourly data can't settle it,
   it counts as a stop-out.
2. Buys every Information Technology STRONG BUY / BUY setup that is **At Entry**, ฿10,000 per
   trade, one position per ticker.

Money is in Thai baht: each trade converts baht to US dollars at that day's real USD/THB rate and
back again when it sells, so exchange-rate moves count in P&L, just as they would for a Thai
investor. Stock prices, stops and targets stay in US dollars.

Trades are only decided on finished trading days: if you open the page while the US market is
still trading, today's half-formed bar is ignored, so a paper fill is always a daily close, the
same as in the backtest.

The cycle only buys on days it runs, so missed days mean missed entries. `make schedule`
installs a macOS background job that runs it every day at 07:00 local time (after the US close in
Thailand). It doesn't need the app open; if the Mac is asleep at 07:00, it runs on wake, and if it was shut
down, it runs at the next login. Output
goes to `data/paper_schedule.log`, and `make unschedule` removes it.

Every trade is shadowed by the same baht in SPY over the same dates, so the summary cards
(P&L, win rate, profit factor, average R, max drawdown, hold time) answer "did this beat just
buying the index?" Trades are stored in `paper_trades.csv`. Settings live at the top of
[`src/paper.py`](src/paper.py).

The **Backtest** tab replays those exact rules over two separate years (~20 seconds each). Each
replayed day only sees the 13 months of prices that existed up to that day, so no future data
leaks in. The rules were tuned while looking at the past year, so the **year before** is the
honest test of whether the edge is real. It shows strategy return vs. buying and holding the
S&P 500 with the same capital, peak capital needed, and a per-setup breakdown. Even the honest
year is optimistic, since it uses today's sector list (survivorship bias). The live tab is the
real proof.

## Setup

```bash
make install
```

## Run

```bash
make run
```

Opens at http://localhost:8501. Click **Run scan** in the sidebar (first run per day takes
a minute or so to download price data for the ~900-ticker universe; it's cached under
`data/` after that). `make stop` kills it.

## Notes / limitations

- This is a mechanical technical screener, not investment advice — it does not look at
  fundamentals, news, or earnings risk. Always do your own diligence before trading.
- Base universe is fixed to the current S&P 500 + S&P 400 MidCap lists; use "Add specific
  tickers" for anything outside that (e.g. small caps).
- Price data cache is per calendar day; use "Force refresh" in the sidebar to bypass it.
- Realized volatility is a simple 90-day stdev-of-returns calculation, so a single large
  gap (e.g. an earnings surprise) can temporarily inflate it for an otherwise low-volatility
  stock.
