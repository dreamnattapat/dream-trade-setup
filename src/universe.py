"""Stock universe: S&P 500 tickers with GICS sector/industry, cached locally."""

import os
import io
import requests
import pandas as pd

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sp500.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DreamTradeSetup/1.0)"}


def _fetch_from_wikipedia() -> pd.DataFrame:
    resp = requests.get(WIKI_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0][["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"]]
    df.columns = ["ticker", "company", "sector", "sub_industry"]
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df


def get_universe(refresh: bool = False) -> pd.DataFrame:
    """Return DataFrame[ticker, company, sector, sub_industry], cached on disk."""
    if not refresh and os.path.exists(CACHE_PATH):
        return pd.read_csv(CACHE_PATH)

    df = _fetch_from_wikipedia()
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    df.to_csv(CACHE_PATH, index=False)
    return df


def get_sectors() -> list[str]:
    return sorted(get_universe()["sector"].unique().tolist())


def get_tickers_for_sectors(sectors: list[str]) -> pd.DataFrame:
    df = get_universe()
    if not sectors:
        return df
    return df[df["sector"].isin(sectors)].reset_index(drop=True)
