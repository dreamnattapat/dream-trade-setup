---
name: run-dream-trade-setup
description: Launch and drive the DreamTradeSetup app — a Streamlit stock swing-trade screener. Use this whenever asked to run, start, test, or screenshot this app.
---

# Running DreamTradeSetup

Python + Streamlit app. The virtualenv already exists at `venv/`.

## First-time setup (only if `venv/` is missing)

```bash
make install
```

## Launch

```bash
make run
```

This calls `venv/bin/streamlit run app.py` directly — no need to `source venv/bin/activate`
first, since the venv's `streamlit` binary already points at the venv's Python.

Serves at http://localhost:8501. For a background launch + readiness check:

```bash
nohup venv/bin/streamlit run app.py --server.headless true --server.port 8501 > /tmp/streamlit.log 2>&1 &
disown
curl -sf http://localhost:8501 >/dev/null && echo UP || cat /tmp/streamlit.log
```

## Stop

```bash
make stop
# or: lsof -ti:8501 -sTCP:LISTEN | xargs -r kill
```

## Drive it (for verification / screenshots)

The app auto-runs a scan on first load (no button click needed) because
`st.session_state.results` starts `None`. Key elements to check:

- `text=Ranked setups` — the results table has rendered
- `[data-testid="stDataFrame"]` — the results grid; click a cell to select that row
  (checkbox appears, row highlights) and a candlestick chart + entry/target/stop lines
  render below it
- The app's main scrollable container is `section[data-testid="stMain"]` — Streamlit
  does NOT scroll `document.body`, so `window.scrollTo` won't reveal content below the
  fold. Scroll that container's `scrollTop` instead (or set it to `scrollHeight`).

No auth, no external services beyond Yahoo Finance (yfinance) and a one-time Wikipedia
scrape for the S&P 500 ticker list (both cached under `data/`).
