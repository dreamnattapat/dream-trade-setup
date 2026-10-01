"""Historical price data fetching via yfinance, with on-disk caches."""

import os
import datetime as dt
import pandas as pd
import yfinance as yf

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prices")
INTRADAY_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "intraday")
HISTORY_PERIOD = "13mo"  # covers a full 52-week window plus buffer for rolling indicators
BATCH_SIZE = 50


def _cache_path(ticker: str, period: str) -> str:
    today = dt.date.today().isoformat()
    sub = "" if period == HISTORY_PERIOD else period  # keep the default cache where it always was
    return os.path.join(CACHE_DIR, today, sub, f"{ticker}.parquet")


def _load_cached(ticker: str, period: str) -> pd.DataFrame | None:
    path = _cache_path(ticker, period)
    if os.path.exists(path):
        return pd.read_parquet(path)
    return None


def _save_cache(ticker: str, period: str, df: pd.DataFrame) -> None:
    path = _cache_path(ticker, period)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path)


def fetch_history(
    tickers: list[str], force_refresh: bool = False, period: str = HISTORY_PERIOD
) -> dict[str, pd.DataFrame]:
    """Return {ticker: daily OHLCV DataFrame}, using today's on-disk cache when available."""
    result: dict[str, pd.DataFrame] = {}
    to_fetch = []

    if not force_refresh:
        for t in tickers:
            cached = _load_cached(t, period)
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
            period=period,
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        if raw.empty:
            continue

        for t in batch:
            try:
                df = raw[t]
            except KeyError:
                continue
            df = df.dropna(how="all")
            if df.empty or len(df) < 30:
                continue
            _save_cache(t, period, df)
            result[t] = df

    return result


def fetch_intraday(ticker: str, date: str) -> pd.DataFrame | None:
    """Hourly bars for one ticker on one day (Yahoo keeps ~2 years of hourly history).

    Only used to settle the rare day where a daily bar touched both a stop and a target,
    so it's fetched on demand and cached permanently - a finished day never changes.
    """
    path = os.path.join(INTRADAY_CACHE_DIR, f"{ticker}_{date}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)

    day = dt.date.fromisoformat(date)
    try:
        bars = yf.download(
            ticker, start=day, end=day + dt.timedelta(days=1), interval="60m",
            progress=False, auto_adjust=True, multi_level_index=False,
        )
    except Exception:
        return None
    bars = bars.dropna(how="all")
    if bars.empty:
        return None
    if day < dt.date.today():
        os.makedirs(INTRADAY_CACHE_DIR, exist_ok=True)
        bars.to_parquet(path)
    return bars
