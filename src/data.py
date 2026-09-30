"""Historical price data fetching via yfinance, with a same-day disk cache."""

import os
import datetime as dt
import pandas as pd
import yfinance as yf

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prices")
HISTORY_PERIOD = "13mo"  # covers a full 52-week window plus buffer for rolling indicators
BATCH_SIZE = 50


def _cache_path(ticker: str) -> str:
    today = dt.date.today().isoformat()
    return os.path.join(CACHE_DIR, today, f"{ticker}.parquet")


def _load_cached(ticker: str) -> pd.DataFrame | None:
    path = _cache_path(ticker)
    if os.path.exists(path):
        return pd.read_parquet(path)
    return None


def _save_cache(ticker: str, df: pd.DataFrame) -> None:
    path = _cache_path(ticker)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path)


def fetch_history(tickers: list[str], force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Return {ticker: OHLCV DataFrame}, using today's on-disk cache when available."""
    result: dict[str, pd.DataFrame] = {}
    to_fetch = []

    if not force_refresh:
        for t in tickers:
            cached = _load_cached(t)
            if cached is not None and len(cached) > 0:
                result[t] = cached
            else:
                to_fetch.append(t)
    else:
        to_fetch = list(tickers)

    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i : i + BATCH_SIZE]
        raw = yf.download(
            batch,
            period=HISTORY_PERIOD,
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        if raw.empty:
            continue

        single_ticker = len(batch) == 1
        for t in batch:
            try:
                df = raw if single_ticker else raw[t]
            except KeyError:
                continue
            df = df.dropna(how="all")
            if df.empty or len(df) < 30:
                continue
            _save_cache(t, df)
            result[t] = df

    return result
