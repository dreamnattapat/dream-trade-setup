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
     target = resistance, stop = support minus 1×ATR(14).
   - **Near 52-Week Low**: price within 8% of its 52-week low, off the low for a few days
     (not making fresh lows right now) and not in a sharp ongoing plunge. Entry = just
     above the 52-week low, target = the local high since the bottom, stop = 5% below
     the 52-week low.
   - **Uptrend Pullback**: a confirmed uptrend (rising 50-day average, tested as support
     at least twice) that has pulled back 5–25% off its recent high without breaking that
     trend. Entry = the rising 50-day average, target = the recent high, stop = pullback
     low minus 1×ATR(14). This is the "buy the dip in a mover" case (e.g. NBIS) that the
     other two detectors miss, since they're both mean-reversion strategies.
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
