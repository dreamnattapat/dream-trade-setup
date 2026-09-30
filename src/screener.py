"""Rule-based swing-trade setup detection.

Two setup types are detected, purely from price/volume history:

1. SIDEWAYS RANGE - the stock has been trading flat for ~6 months inside a
   support/resistance channel. Entry near support, target near resistance,
   stop below support.
2. NEAR 52-WEEK LOW - the stock has been pushed down to (or near) its
   52-week low and shows early signs of basing rather than still free-falling.
   Entry near current price, target at a recent local high, stop below the low.

Every threshold below is a plain constant so the logic stays inspectable -
nothing here is a black box.
"""

from dataclasses import dataclass

import pandas as pd

from .indicators import atr, count_touches, linreg_slope_pct

SIDEWAYS_WINDOW_DAYS = 126  # ~6 trading months
YEAR_WINDOW_DAYS = 252  # ~52 trading weeks

SIDEWAYS_MAX_SLOPE = 0.0006  # max |slope| as fraction of price per day (~7.5%/6mo)
SIDEWAYS_MIN_RANGE_PCT = 0.08  # channel must be at least 8% wide to be worth trading
SIDEWAYS_MAX_RANGE_PCT = 0.70  # wider than this looks like a trend/volatility, not a range
SIDEWAYS_TOUCH_TOLERANCE = 0.03  # within 3% of support/resistance counts as a "touch"
SIDEWAYS_MIN_TOTAL_TOUCHES = 3  # combined support+resistance touches required

NEAR_LOW_MAX_PCT_ABOVE = 0.08  # "near" the 52w low = within 8% of it
NEAR_LOW_MIN_DAYS_SINCE_LOW = 4  # avoid stocks making fresh lows in the last few days
NEAR_LOW_MAX_RECENT_DROP = -0.08  # skip if last 10 trading days return is worse than -8% (still falling)
NEAR_LOW_STOP_BUFFER = 0.05  # stop placed 5% below the 52w low
NEAR_LOW_ENTRY_BUFFER = 0.02  # buy-zone placed 2% above the exact 52w low
NEAR_LOW_BOUNCE_WINDOW = 40  # look back this many days for a local-high bounce target


@dataclass
class Setup:
    ticker: str
    company: str
    sector: str
    setup_type: str  # "Sideways Range" or "Near 52-Week Low"
    current_price: float
    entry: float
    target: float
    stop: float
    reward_risk: float
    touches: int
    days_since_low: int | None = None


def _detect_sideways(ticker: str, company: str, sector: str, df: pd.DataFrame) -> Setup | None:
    window = df.tail(SIDEWAYS_WINDOW_DAYS)
    if len(window) < SIDEWAYS_WINDOW_DAYS * 0.8:
        return None

    slope = linreg_slope_pct(window["Close"])
    if abs(slope) > SIDEWAYS_MAX_SLOPE:
        return None

    support = float(window["Low"].quantile(0.10))
    resistance = float(window["High"].quantile(0.90))
    if support <= 0:
        return None

    range_pct = (resistance - support) / support
    if not (SIDEWAYS_MIN_RANGE_PCT <= range_pct <= SIDEWAYS_MAX_RANGE_PCT):
        return None

    touches = count_touches(window["Low"], support, SIDEWAYS_TOUCH_TOLERANCE) + count_touches(
        window["High"], resistance, SIDEWAYS_TOUCH_TOLERANCE
    )
    if touches < SIDEWAYS_MIN_TOTAL_TOUCHES:
        return None

    atr14 = atr(df, 14).iloc[-1]
    if pd.isna(atr14) or atr14 <= 0:
        return None

    entry = support
    target = resistance
    stop = support - atr14
    if stop <= 0 or entry <= stop:
        return None

    reward_risk = (target - entry) / (entry - stop)
    current_price = float(df["Close"].iloc[-1])
    if current_price <= stop:
        return None  # support has already broken down - setup is invalidated

    return Setup(
        ticker=ticker,
        company=company,
        sector=sector,
        setup_type="Sideways Range",
        current_price=current_price,
        entry=round(entry, 2),
        target=round(target, 2),
        stop=round(stop, 2),
        reward_risk=round(reward_risk, 2),
        touches=touches,
    )


def _detect_near_52w_low(ticker: str, company: str, sector: str, df: pd.DataFrame) -> Setup | None:
    window = df.tail(YEAR_WINDOW_DAYS)
    if len(window) < YEAR_WINDOW_DAYS * 0.6:
        return None

    low_52w = float(window["Low"].min())
    current_price = float(df["Close"].iloc[-1])
    if low_52w <= 0:
        return None

    pct_above_low = (current_price - low_52w) / low_52w
    if pct_above_low > NEAR_LOW_MAX_PCT_ABOVE:
        return None

    low_idx = window["Low"].idxmin()
    days_since_low = int((window.index[-1] - low_idx) / pd.Timedelta(days=1))
    trading_days_since_low = len(window.loc[low_idx:]) - 1
    if trading_days_since_low < NEAR_LOW_MIN_DAYS_SINCE_LOW:
        return None

    recent_return = float(df["Close"].iloc[-1] / df["Close"].iloc[-11] - 1) if len(df) > 11 else 0.0
    if recent_return < NEAR_LOW_MAX_RECENT_DROP:
        return None

    bounce_target = float(df["High"].tail(NEAR_LOW_BOUNCE_WINDOW).max())
    stop = low_52w * (1 - NEAR_LOW_STOP_BUFFER)
    entry = low_52w * (1 + NEAR_LOW_ENTRY_BUFFER)
    if bounce_target <= entry or entry <= stop:
        return None

    reward_risk = (bounce_target - entry) / (entry - stop)

    return Setup(
        ticker=ticker,
        company=company,
        sector=sector,
        setup_type="Near 52-Week Low",
        current_price=current_price,
        entry=round(entry, 2),
        target=round(bounce_target, 2),
        stop=round(stop, 2),
        reward_risk=round(reward_risk, 2),
        touches=0,
        days_since_low=days_since_low,
    )


def scan(universe: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> list[Setup]:
    """Run both detectors over every ticker with available price data."""
    setups: list[Setup] = []
    for _, row in universe.iterrows():
        ticker = row["ticker"]
        df = price_data.get(ticker)
        if df is None or df.empty:
            continue
        try:
            sideways = _detect_sideways(ticker, row["company"], row["sector"], df)
            if sideways:
                setups.append(sideways)
            near_low = _detect_near_52w_low(ticker, row["company"], row["sector"], df)
            if near_low:
                setups.append(near_low)
        except Exception:
            continue
    return setups
