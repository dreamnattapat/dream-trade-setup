"""Stock universe: S&P 500 + S&P 400 MidCap tickers with GICS sector/industry, cached locally.

Plus a lookup for arbitrary extra tickers (e.g. SOFI) that aren't in either index but
that a user wants force-included in a scan.
"""

import os
import io
import requests
import pandas as pd
import yfinance as yf

WIKI_URLS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
}
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "universe.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DreamTradeSetup/1.0)"}

COLUMNS = ["ticker", "company", "sector", "sub_industry"]


def _fetch_index_table(url: str) -> pd.DataFrame:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0][["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"]]
    df.columns = COLUMNS
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df


def _fetch_from_wikipedia() -> pd.DataFrame:
    frames = [_fetch_index_table(url) for url in WIKI_URLS.values()]
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)


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
    """Empty `sectors` means none of the base universe - not "all"."""
    df = get_universe()
    if not sectors:
        return df.iloc[0:0]
    return df[df["sector"].isin(sectors)].reset_index(drop=True)


def get_custom_tickers(tickers: list[str]) -> pd.DataFrame:
    """Look up sector/company for arbitrary extra tickers not in the base universe."""
    rows = []
    for raw in tickers:
        t = raw.strip().upper()
        if not t:
            continue
        try:
            info = yf.Ticker(t).info
            company = info.get("shortName") or info.get("longName") or t
            sector = info.get("sector") or "Other"
        except Exception:
            company, sector = t, "Other"
        rows.append({"ticker": t, "company": company, "sector": sector, "sub_industry": ""})
    return pd.DataFrame(rows, columns=COLUMNS)
