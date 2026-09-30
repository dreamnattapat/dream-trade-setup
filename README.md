# DreamTradeSetup

A rule-based swing-trade setup finder for US (S&P 500) stocks. Pick a sector, run a scan,
and get a ranked list of stocks currently sitting in a tradeable technical setup — with
entry, target, and stop-loss levels computed for you.

No sign-in, no LLM calls per stock, no paid data — everything runs locally against free
Yahoo Finance data.

## How it works

1. **Universe** — S&P 500 constituents with GICS sector, scraped from Wikipedia and cached.
2. **Screen** — for every ticker, two purely mechanical detectors run against ~13 months
   of daily price history:
   - **Sideways Range**: flat trend over the last 6 months, trading inside a
     support/resistance channel that's been tested at least 3 times. Entry = support,
     target = resistance, stop = support minus 1×ATR(14).
   - **Near 52-Week Low**: price within 8% of its 52-week low, off the low for a few days
     (not making fresh lows right now) and not in a sharp ongoing plunge. Entry = just
     above the 52-week low, target = the local high since the bottom, stop = 5% below
     the 52-week low.
3. **Rate** — each setup gets a 0–100 composite score from reward:risk, how close the
   current price is to the ideal entry right now, and how well-formed the setup is. The
   score maps to STRONG BUY / BUY / HOLD / SELL / STRONG SELL. All thresholds live in
   [`src/rating.py`](src/rating.py) — nothing is a black box.
4. **Dashboard** — filter by sector, see the ranked table, click a row for a candlestick
   chart with entry/target/stop drawn on it, and size your position with the built-in
   risk calculator.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate
streamlit run app.py
```

Opens at http://localhost:8501. Click **Run scan** in the sidebar (first run per day takes
~20-30s to download price data for all 503 tickers; it's cached under `data/` after that).

## Notes / limitations

- This is a mechanical technical screener, not investment advice — it does not look at
  fundamentals, news, or earnings risk. Always do your own diligence before trading.
- Universe is fixed to the current S&P 500 list; no small/micro caps.
- Price data cache is per calendar day; use "Force refresh" in the sidebar to bypass it.
