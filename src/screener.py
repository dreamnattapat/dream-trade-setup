"""Rule-based swing-trade setup detection.

Three setup types are detected, purely from price/volume history:

1. SIDEWAYS RANGE - the stock has been trading flat for ~6 months inside a
   support/resistance channel. Entry near support, target at the middle of the
   channel, stop below the channel's lowest low (where the range actually breaks).
2. NEAR 52-WEEK LOW - the stock has been pushed down to (or near) its
   52-week low and shows early signs of basing rather than still free-falling.
   Entry near current price, target at a recent local high, stop below the low.
3. UPTREND PULLBACK - the stock is in a confirmed uptrend (a rising 50-day
   average that price keeps bouncing off) and has pulled back 5-25% off its
   recent high without breaking that trend. Entry near the rising average,
   target back at the recent high, stop below the pullback low. This is the
   "buy the dip in a mover" case (e.g. NBIS) that the other two detectors miss,
   since they're both mean-reversion strategies and neither fires on a stock
   that's already trending strongly upward.

Every threshold below is a plain constant so the logic stays inspectable -
nothing here is a black box.
"""

from dataclasses import dataclass

import pandas as pd

from .indicators import annualized_volatility_pct, atr, count_touches, linreg_slope_pct

SIDEWAYS_WINDOW_DAYS = 126  # ~6 trading months
YEAR_WINDOW_DAYS = 252  # ~52 trading weeks

# Below this, a stock is a slow compounder (e.g. MSCI ~30%, SYK ~36%) that can form a
# technically valid range but won't realistically deliver a swing-sized move in weeks to
# months. Above it is where choppier, swing-friendly movers live (e.g. SOFI ~56%, PLTR ~65%).
MIN_ANNUALIZED_VOL_PCT = 40.0

SIDEWAYS_MAX_SLOPE = 0.0006  # max |slope| as fraction of price per day (~7.5%/6mo)
SIDEWAYS_MIN_RANGE_PCT = 0.08  # channel must be at least 8% wide to be worth trading
SIDEWAYS_MAX_RANGE_PCT = 0.70  # wider than this looks like a trend/volatility, not a range
SIDEWAYS_TOUCH_TOLERANCE = 0.03  # within 3% of support/resistance counts as a "touch"
SIDEWAYS_MIN_TOTAL_TOUCHES = 3  # combined support+resistance touches required
# Backtested over the past year (see the Paper Trading backtest): a stop 1 ATR under the
# 10th-percentile "support" got shaken out by ordinary noise in a median 4 days, and a target at
# the top of the range was rarely reached. A stop under the range's true floor plus a target at
# its midpoint took the setup from a 13% to a ~59% win rate, profitable in both halves of the year.
SIDEWAYS_TARGET_FRACTION = 0.5  # take profit this far from support toward resistance (0.5 = the middle)
SIDEWAYS_STOP_ATR_BUFFER = 0.5  # stop this many ATRs below the lowest low of the 6-month window

NEAR_LOW_MAX_PCT_ABOVE = 0.08  # "near" the 52w low = within 8% of it
NEAR_LOW_MIN_DAYS_SINCE_LOW = 4  # avoid stocks making fresh lows in the last few days
NEAR_LOW_MAX_RECENT_DROP = -0.08  # skip if last 10 trading days return is worse than -8% (still falling)
NEAR_LOW_STOP_BUFFER = 0.05  # stop placed 5% below the 52w low
NEAR_LOW_ENTRY_BUFFER = 0.02  # buy-zone placed 2% above the exact 52w low
NEAR_LOW_BOUNCE_WINDOW = 40  # look back this many days for a local-high bounce target

UPTREND_MIN_SLOPE = 0.0012  # min slope (fraction/day, ~15%/6mo) to call it a confirmed uptrend
UPTREND_SMA_PERIOD = 50  # the rising average used as dynamic support
UPTREND_SMA_RISING_LOOKBACK = 20  # SMA must be higher now than this many days ago
UPTREND_HIGH_LOOKBACK_DAYS = 60  # window for finding the peak of the current leg
UPTREND_MIN_PULLBACK_PCT = 0.05  # need at least a 5% dip off the high - a real discount
UPTREND_MAX_PULLBACK_PCT = 0.25  # more than 25% off the high risks the trend actually breaking
UPTREND_TOUCH_TOLERANCE = 0.03  # within 3% of the rising SMA counts as a "touch"
UPTREND_MIN_TOUCHES = 2  # the average must have already acted as support at least twice
UPTREND_STOP_ATR_MULT = 1.0  # stop = pullback low minus this many ATRs

# Market-dip rule for Uptrend Pullback. Backtested over two years: pullbacks bought while the whole
# market was dipping (S&P 500 at or below its 50-day average) won ~74% of the time and made nearly
# all of this setup's profit; pullbacks while the market was fine broke even - a strong stock that
# drops 15-25% while everything else is calm usually has a company-specific problem. The rule was
# found on Oct 2025-Sep 2026 and then held up on Oct 2024-Sep 2025, which it had never seen
# (that year: -4,645 baht without it, +6,024 with it).
MARKET_TICKER = "SPY"
MARKET_SMA_DAYS = 50
UPTREND_MAX_MARKET_GAP_PCT = 0.0  # S&P 500 must be at most this % above its 50-day average


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
    volatility_pct: float = 0.0
    days_since_low: int | None = None


def _detect_sideways(ticker: str, company: str, sector: str, df: pd.DataFrame) -> Setup | None:
    window = df.tail(SIDEWAYS_WINDOW_DAYS)
    if len(window) < SIDEWAYS_WINDOW_DAYS * 0.8:
        return None

    volatility = annualized_volatility_pct(df["Close"])
    if volatility < MIN_ANNUALIZED_VOL_PCT:
        return None  # too slow-moving to be a swing trade, regardless of how clean the range is

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
    target = support + SIDEWAYS_TARGET_FRACTION * (resistance - support)
    stop = float(window["Low"].min()) - SIDEWAYS_STOP_ATR_BUFFER * atr14
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
        volatility_pct=round(volatility, 1),
    )


def _detect_near_52w_low(ticker: str, company: str, sector: str, df: pd.DataFrame) -> Setup | None:
    window = df.tail(YEAR_WINDOW_DAYS)
    if len(window) < YEAR_WINDOW_DAYS * 0.6:
        return None

    volatility = annualized_volatility_pct(df["Close"])
    if volatility < MIN_ANNUALIZED_VOL_PCT:
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
        volatility_pct=round(volatility, 1),
        days_since_low=days_since_low,
    )


def _detect_uptrend_pullback(ticker: str, company: str, sector: str, df: pd.DataFrame) -> Setup | None:
    window = df.tail(SIDEWAYS_WINDOW_DAYS)
    if len(window) < SIDEWAYS_WINDOW_DAYS * 0.8:
        return None

    volatility = annualized_volatility_pct(df["Close"])
    if volatility < MIN_ANNUALIZED_VOL_PCT:
        return None

    slope = linreg_slope_pct(window["Close"])
    if slope < UPTREND_MIN_SLOPE:
        return None  # not trending up strongly enough to be a confirmed uptrend

    sma = df["Close"].rolling(UPTREND_SMA_PERIOD).mean()
    if len(sma) < UPTREND_SMA_RISING_LOOKBACK + 1 or pd.isna(sma.iloc[-1]) or pd.isna(sma.iloc[-UPTREND_SMA_RISING_LOOKBACK]):
        return None
    if sma.iloc[-1] <= sma.iloc[-UPTREND_SMA_RISING_LOOKBACK]:
        return None  # the average itself isn't rising - trend not structurally confirmed

    leg_window = df.tail(UPTREND_HIGH_LOOKBACK_DAYS)
    high_idx = leg_window["High"].idxmax()
    recent_high = float(leg_window.loc[high_idx, "High"])
    current_price = float(df["Close"].iloc[-1])
    if recent_high <= 0:
        return None

    pullback_pct = (recent_high - current_price) / recent_high
    if not (UPTREND_MIN_PULLBACK_PCT <= pullback_pct <= UPTREND_MAX_PULLBACK_PCT):
        return None

    sma_window = sma.tail(SIDEWAYS_WINDOW_DAYS)
    close_window = df["Close"].tail(SIDEWAYS_WINDOW_DAYS)
    valid = sma_window.notna()
    touches = int((((close_window[valid] - sma_window[valid]).abs() / sma_window[valid]) <= UPTREND_TOUCH_TOLERANCE).sum())
    if touches < UPTREND_MIN_TOUCHES:
        return None

    atr14 = atr(df, 14).iloc[-1]
    if pd.isna(atr14) or atr14 <= 0:
        return None

    pullback_low = float(leg_window.loc[high_idx:, "Low"].min())
    entry = float(sma.iloc[-1])
    stop = pullback_low - atr14 * UPTREND_STOP_ATR_MULT
    target = recent_high
    if stop <= 0 or entry <= stop or target <= entry:
        return None

    reward_risk = (target - entry) / (entry - stop)
    if current_price <= stop:
        return None  # trend has already broken down

    return Setup(
        ticker=ticker,
        company=company,
        sector=sector,
        setup_type="Uptrend Pullback",
        current_price=current_price,
        entry=round(entry, 2),
        target=round(target, 2),
        stop=round(stop, 2),
        reward_risk=round(reward_risk, 2),
        touches=touches,
        volatility_pct=round(volatility, 1),
    )


def explain_no_setup(df: pd.DataFrame, market_gap: float | None = None) -> str:
    """Plain-language reason a ticker matched no detector - for tickers a user explicitly asked about."""
    reasons = []

    if market_gap is not None and market_gap > UPTREND_MAX_MARKET_GAP_PCT and _detect_uptrend_pullback("", "", "", df):
        return (f"Uptrend Pullback setup, but paused: the S&P 500 is {market_gap:.1f}% above its 50-day average. "
                "This setup only works when the whole market is dipping")

    volatility = annualized_volatility_pct(df["Close"])
    if volatility < MIN_ANNUALIZED_VOL_PCT:
        reasons.append(
            f"too low volatility for a swing trade ({volatility:.0f}% annualized, need {MIN_ANNUALIZED_VOL_PCT:.0f}%+ "
            f"- likely a slow compounder rather than a swing candidate)"
        )

    window = df.tail(SIDEWAYS_WINDOW_DAYS)
    slope = None
    if len(window) >= SIDEWAYS_WINDOW_DAYS * 0.8:
        slope = linreg_slope_pct(window["Close"])
        drift_pct = slope * SIDEWAYS_WINDOW_DAYS * 100

        if slope >= UPTREND_MIN_SLOPE:
            leg_window = df.tail(UPTREND_HIGH_LOOKBACK_DAYS)
            high_idx = leg_window["High"].idxmax()
            recent_high = float(leg_window.loc[high_idx, "High"])
            current_price = float(df["Close"].iloc[-1])
            pullback_pct = (recent_high - current_price) / recent_high * 100 if recent_high > 0 else 0
            if pullback_pct < UPTREND_MIN_PULLBACK_PCT * 100:
                reasons.append(
                    f"in a strong uptrend (~{drift_pct:.0f}% over 6 months) but only {pullback_pct:.0f}% off its "
                    f"recent high - no real pullback yet to buy"
                )
            elif pullback_pct > UPTREND_MAX_PULLBACK_PCT * 100:
                reasons.append(
                    f"pulled back {pullback_pct:.0f}% off its high - deep enough that the uptrend may be "
                    f"breaking, not just a healthy dip"
                )
            else:
                reasons.append("in an uptrend with a real pullback, but the rising average isn't confirmed as support yet")
        elif slope < -SIDEWAYS_MAX_SLOPE:
            reasons.append(f"trending down (~{drift_pct:.0f}% drift over 6 months, not a stable range)")
        elif abs(slope) > SIDEWAYS_MAX_SLOPE:
            reasons.append(
                f"drifting ~{drift_pct:.0f}% over 6 months - not flat enough for a range setup, not strong "
                f"enough yet to count as a confirmed uptrend"
            )

    if slope is None or slope < UPTREND_MIN_SLOPE:
        year_window = df.tail(YEAR_WINDOW_DAYS)
        if len(year_window) >= YEAR_WINDOW_DAYS * 0.6:
            low_52w = float(year_window["Low"].min())
            current = float(df["Close"].iloc[-1])
            if low_52w > 0:
                pct_above = (current - low_52w) / low_52w * 100
                if pct_above > NEAR_LOW_MAX_PCT_ABOVE * 100:
                    reasons.append(f"{pct_above:.0f}% above its 52-week low")

    if not reasons:
        reasons.append("no qualifying setup detected right now")
    return "; ".join(reasons)


def market_gap_pct(price_data: dict[str, pd.DataFrame]) -> float | None:
    """How far (%) the S&P 500 sits above (+) or below (-) its 50-day average on the latest bar."""
    market = price_data.get(MARKET_TICKER)
    if market is None or len(market) < MARKET_SMA_DAYS:
        return None
    close = market["Close"]
    return float((close.iloc[-1] / close.tail(MARKET_SMA_DAYS).mean() - 1) * 100)


def uptrend_pullbacks_allowed(price_data: dict[str, pd.DataFrame]) -> bool:
    gap = market_gap_pct(price_data)
    return gap is not None and gap <= UPTREND_MAX_MARKET_GAP_PCT


def scan(universe: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> list[Setup]:
    """Run the detectors over every ticker with available price data.

    `price_data` must include MARKET_TICKER (SPY); without it Uptrend Pullback can't check the
    market-dip rule, so it doesn't fire.
    """
    setups: list[Setup] = []
    detectors = [_detect_sideways, _detect_near_52w_low]
    if uptrend_pullbacks_allowed(price_data):
        detectors.append(_detect_uptrend_pullback)
    for _, row in universe.iterrows():
        ticker = row["ticker"]
        df = price_data.get(ticker)
        if df is None or df.empty:
            continue
        for detector in detectors:
            try:
                setup = detector(ticker, row["company"], row["sector"], df)
            except Exception:
                continue
            if setup:
                setups.append(setup)
    return setups
