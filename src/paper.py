"""Forward paper-trading simulator: let the screener's signals trade themselves.

Each cycle (run whenever the app's Paper Trading page opens, or `make paper`):
  1. Walk every OPEN position through each new daily bar since it was opened and close it
     if the bar hit its stop or target.
  2. Scan the paper universe and open a position in every STRONG BUY / BUY setup whose
     Entry Status is "At Entry" - one position per ticker at a time.

Fill rules are deliberately conservative so results aren't flattered:
  - Entries fill at the latest finished day's close; a bar still forming mid-session is ignored.
  - A bar that opens beyond the stop or target (a gap) fills at that open, not at the level.
  - A bar whose range touches both the stop and the target is settled with that day's hourly
    bars (whichever level an hour reached first). If hourly data is unavailable, or a single
    hour touched both, it counts as a stop-out - the worse case.
  - The entry bar itself is never used for exits - only bars after it.

Money is in Thai baht. Every trade invests the same POSITION_SIZE_THB, converted to US dollars at
that day's USD/THB rate and back again on exit - exactly what a Thai investor buying US stocks
goes through - so exchange-rate moves are part of the P&L. Each trade is shadowed by the same
baht in SPY over the same dates (with the same conversion), so "did the signals beat just buying
the index?" has an apples-to-apples answer. Prices, stops and targets stay in US dollars.
"""

import datetime as dt
import os

import pandas as pd

from . import data, rating, screener, universe

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "paper_trades.csv")

PAPER_SECTORS = ["Information Technology"]
PAPER_RATINGS = {"STRONG BUY", "BUY"}
PAPER_ENTRY_STATUS = "At Entry"
POSITION_SIZE_THB = 10_000.0
BENCHMARK = "SPY"
FX_TICKER = "THB=X"  # Yahoo's USD/THB rate: baht per 1 US dollar
US_MARKET_TZ = "America/New_York"
BARS_FINAL_AFTER = dt.time(16, 30)  # Yahoo's daily bar settles shortly after the 4pm close

COLUMNS = [
    "id", "ticker", "company", "setup", "rating", "score",
    "entry_date", "entry_price", "target", "stop", "shares",
    "status", "exit_date", "exit_price", "exit_reason",
    "pnl", "pnl_pct", "r_multiple", "spy_entry", "spy_exit", "spy_pnl",
    "fx_entry", "fx_exit",  # baht per US dollar on the entry / exit day
]
TEXT_COLUMNS = ["ticker", "company", "setup", "rating", "entry_date", "status", "exit_date", "exit_reason"]
OPEN, WON, LOST = "OPEN", "WON", "LOST"


def _normalize(ledger: pd.DataFrame) -> pd.DataFrame:
    # An all-empty column (e.g. exit_date before anything has closed) would otherwise be
    # float NaN, and pandas refuses to write a date string into it.
    ledger = ledger.reindex(columns=COLUMNS)
    return ledger.astype({c: "object" for c in TEXT_COLUMNS})


def load_ledger(path: str = LEDGER_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return _normalize(pd.DataFrame(columns=COLUMNS))
    return _normalize(pd.read_csv(path, dtype={c: "object" for c in TEXT_COLUMNS}))


def save_ledger(ledger: pd.DataFrame, path: str = LEDGER_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ledger[COLUMNS].to_csv(path, index=False)


def reset_ledger() -> None:
    if os.path.exists(LEDGER_PATH):
        os.remove(LEDGER_PATH)


def _bar_date(ts) -> str:
    return pd.Timestamp(ts).date().isoformat()


def _close_on_or_before(df: pd.DataFrame, date: str) -> float | None:
    upto = df[df.index <= pd.Timestamp(date)]
    return float(upto["Close"].iloc[-1]) if not upto.empty else None


def _fx_on(price_data: dict[str, pd.DataFrame], date: str) -> float | None:
    fx = price_data.get(FX_TICKER)
    return _close_on_or_before(fx, date) if fx is not None else None


def _resolve_both_touched(ticker: str, ts, daily_bar: pd.Series, stop: float, target: float) -> tuple[float, str]:
    """A daily bar touched both levels - use that day's hourly bars to see which came first."""
    hourly = data.fetch_intraday(ticker, _bar_date(ts))
    if hourly is not None and not hourly.empty and hourly["Close"].iloc[-1] > 0:
        # Daily bars are split/dividend-adjusted and hourly ones may not be; rescale so both
        # describe the same price scale the stop and target were computed on.
        scale = float(daily_bar["Close"]) / float(hourly["Close"].iloc[-1])
        for _, hour in hourly.iterrows():
            hit_stop = hour["Low"] * scale <= stop
            hit_target = hour["High"] * scale >= target
            if hit_stop and hit_target:
                break  # still ambiguous within a single hour
            if hit_stop:
                return stop, "Stop loss (hourly check)"
            if hit_target:
                return target, "Take profit (hourly check)"
    return stop, "Stop loss (both hit, assumed worse)"


def _update_open_trades(ledger: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ledger = _normalize(ledger)
    spy = price_data.get(BENCHMARK)
    for i, trade in ledger[ledger["status"] == OPEN].iterrows():
        df = price_data.get(trade["ticker"])
        if df is None or df.empty:
            continue
        bars = df[df.index > pd.Timestamp(trade["entry_date"])]
        stop, target = trade["stop"], trade["target"]

        for ts, bar in bars.iterrows():
            exit_price, reason = None, None
            if bar["Open"] <= stop:
                exit_price, reason = bar["Open"], "Stop (gapped through)"
            elif bar["Open"] >= target:
                exit_price, reason = bar["Open"], "Target (gapped through)"
            elif bar["Low"] <= stop and bar["High"] >= target:
                exit_price, reason = _resolve_both_touched(trade["ticker"], ts, bar, stop, target)
            elif bar["Low"] <= stop:
                exit_price, reason = stop, "Stop loss"
            elif bar["High"] >= target:
                exit_price, reason = target, "Take profit"
            if exit_price is None:
                continue

            exit_date = _bar_date(ts)
            fx_exit = _fx_on(price_data, exit_date) or trade["fx_entry"]
            cost_thb = trade["shares"] * trade["entry_price"] * trade["fx_entry"]
            pnl = trade["shares"] * exit_price * fx_exit - cost_thb
            spy_exit = _close_on_or_before(spy, exit_date) if spy is not None else None
            ledger.loc[i, "status"] = WON if pnl > 0 else LOST
            ledger.loc[i, "exit_date"] = exit_date
            ledger.loc[i, "exit_price"] = round(float(exit_price), 2)
            ledger.loc[i, "exit_reason"] = reason
            ledger.loc[i, "pnl"] = round(pnl, 2)
            ledger.loc[i, "pnl_pct"] = round(pnl / cost_thb * 100, 2)
            ledger.loc[i, "fx_exit"] = round(float(fx_exit), 4)
            ledger.loc[i, "r_multiple"] = round((exit_price - trade["entry_price"]) / (trade["entry_price"] - stop), 2)
            if spy_exit and pd.notna(trade["spy_entry"]):
                ledger.loc[i, "spy_exit"] = round(spy_exit, 2)
                spy_growth = (spy_exit * fx_exit) / (trade["spy_entry"] * trade["fx_entry"])
                ledger.loc[i, "spy_pnl"] = round(POSITION_SIZE_THB * (spy_growth - 1), 2)
            break
    return ledger


def _open_new_trades(ledger: pd.DataFrame, setups: list, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    spy = price_data.get(BENCHMARK)
    held = set(ledger.loc[ledger["status"] == OPEN, "ticker"])

    best_per_ticker = {}
    for s in setups:
        score = rating.score_setup(s)
        if rating.rate(score) not in PAPER_RATINGS or rating.entry_status(s) != PAPER_ENTRY_STATUS:
            continue
        if s.ticker not in best_per_ticker or score > best_per_ticker[s.ticker][1]:
            best_per_ticker[s.ticker] = (s, score)

    new_rows = []
    next_id = int(ledger["id"].max()) + 1 if not ledger.empty else 1
    for ticker, (s, score) in sorted(best_per_ticker.items()):
        if ticker in held:
            continue
        entry_date = _bar_date(price_data[ticker].index[-1])
        # Don't re-buy a ticker on the same bar it was just closed on.
        closed_today = ledger[(ledger["ticker"] == ticker) & (ledger["exit_date"] == entry_date)]
        if not closed_today.empty:
            continue
        spy_entry = _close_on_or_before(spy, entry_date) if spy is not None else None
        fx_entry = _fx_on(price_data, entry_date)
        if not fx_entry:
            continue  # can't size a baht position without the exchange rate
        new_rows.append({
            "id": next_id, "ticker": ticker, "company": s.company, "setup": s.setup_type,
            "rating": rating.rate(score), "score": score,
            "entry_date": entry_date, "entry_price": round(s.current_price, 2),
            "target": s.target, "stop": s.stop,
            "shares": round(POSITION_SIZE_THB / fx_entry / s.current_price, 4),
            "status": OPEN, "spy_entry": round(spy_entry, 2) if spy_entry else None,
            "fx_entry": round(fx_entry, 4),
        })
        next_id += 1

    if new_rows:
        ledger = pd.concat([ledger, pd.DataFrame(new_rows)], ignore_index=True)
    return _normalize(ledger)


def run_cycle(force_refresh: bool = False) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Advance open positions to today, then open new ones. Returns (ledger, price_data)."""
    ledger = load_ledger()
    uni = universe.get_tickers_for_sectors(PAPER_SECTORS)
    tickers = set(uni["ticker"]) | set(ledger.loc[ledger["status"] == OPEN, "ticker"]) | {BENCHMARK, FX_TICKER}
    price_data = data.fetch_history(sorted(tickers), force_refresh=force_refresh)
    if FX_TICKER not in price_data:
        raise RuntimeError("Couldn't download the USD/THB exchange rate from Yahoo Finance - try again shortly.")

    # Trade only on finished days; the returned price_data keeps today's live bar for display.
    settled = _completed_bars(price_data)
    ledger = _update_open_trades(ledger, settled)
    setups = screener.scan(uni, settled)
    ledger = _open_new_trades(ledger, setups, settled)
    save_ledger(ledger)
    return ledger, price_data


def _completed_bars(price_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Drop today's bar while the US session is still open (or just closed and not yet final).

    Otherwise opening the app mid-session would buy at an intraday price and judge stops and
    targets against a half-formed bar - unlike the backtest, which only ever sees full days.
    """
    now = pd.Timestamp.now(tz=US_MARKET_TZ)
    if now.time() >= BARS_FINAL_AFTER:
        return price_data
    today = pd.Timestamp(now.date())
    return {t: df[df.index < today] for t, df in price_data.items()}


def mark_to_market(ledger: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Open positions with today's price, unrealized baht P&L, and the same baht in SPY."""
    spy = price_data.get(BENCHMARK)
    spy_last = float(spy["Close"].iloc[-1]) if spy is not None else None
    fx = price_data.get(FX_TICKER)
    fx_last = float(fx["Close"].iloc[-1]) if fx is not None else None
    # "Today" is the latest price bar, so a backtest's open positions are aged to its last day.
    as_of = spy.index[-1].date() if spy is not None else dt.date.today()
    rows = []
    for _, t in ledger[ledger["status"] == OPEN].iterrows():
        df = price_data.get(t["ticker"])
        last = float(df["Close"].iloc[-1]) if df is not None else t["entry_price"]
        fx_now = fx_last or t["fx_entry"]
        spy_pnl = (POSITION_SIZE_THB * ((spy_last * fx_now) / (t["spy_entry"] * t["fx_entry"]) - 1)
                   if spy_last and pd.notna(t["spy_entry"]) else 0.0)
        rows.append({**t.to_dict(), "current_price": last,
                     "unrealized_pnl": t["shares"] * (last * fx_now - t["entry_price"] * t["fx_entry"]),
                     "spy_unrealized_pnl": spy_pnl,
                     "days_held": (as_of - dt.date.fromisoformat(t["entry_date"])).days})
    return pd.DataFrame(rows)


def equity_curve(ledger: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily cumulative baht P&L (realized + unrealized) for the strategy and the same baht in SPY."""
    spy = price_data.get(BENCHMARK)
    fx = price_data.get(FX_TICKER)
    if ledger.empty or spy is None or fx is None:
        return pd.DataFrame(columns=["strategy", "spy"])

    dates = spy.index[spy.index >= pd.Timestamp(ledger["entry_date"].min())]
    strategy = pd.Series(0.0, index=dates)
    bench = pd.Series(0.0, index=dates)
    spy_close = spy["Close"].reindex(dates).ffill()
    fx_close = fx["Close"].sort_index().reindex(dates, method="ffill")  # FX and US market holidays differ

    for _, t in ledger.iterrows():
        df = price_data.get(t["ticker"])
        if df is None:
            continue
        close = df["Close"].reindex(dates).ffill()
        entry = pd.Timestamp(t["entry_date"])
        exit_ = pd.Timestamp(t["exit_date"]) if t["status"] != OPEN else None
        active = (dates >= entry) & ((dates < exit_) if exit_ is not None else True)
        strategy[active] += (t["shares"] * (close * fx_close - t["entry_price"] * t["fx_entry"]))[active]
        if pd.notna(t["spy_entry"]):
            spy_growth = (spy_close * fx_close) / (t["spy_entry"] * t["fx_entry"])
            bench[active] += (POSITION_SIZE_THB * (spy_growth - 1))[active]
        if exit_ is not None:
            done = dates >= exit_
            strategy[done] += t["pnl"]
            bench[done] += t["spy_pnl"] if pd.notna(t["spy_pnl"]) else 0.0

    return pd.DataFrame({"strategy": strategy, "spy": bench})


def peak_open_positions(ledger: pd.DataFrame) -> int:
    """Most positions held on any single day - i.e. how much capital the strategy really needs at once."""
    if ledger.empty:
        return 0
    events = []
    for _, t in ledger.iterrows():
        events.append((t["entry_date"], 1))
        if t["status"] != OPEN:
            events.append((t["exit_date"], -1))
    # On a shared date, process exits before entries: a position closed that day frees its slot.
    events.sort(key=lambda e: (e[0], e[1]))
    held = peak = 0
    for _, delta in events:
        held += delta
        peak = max(peak, held)
    return peak


def setup_breakdown(ledger: pd.DataFrame) -> pd.DataFrame:
    """Closed-trade results per setup type, to show which of the three detectors is actually earning."""
    closed = ledger[ledger["status"].isin([WON, LOST])]
    rows = []
    for setup, grp in closed.groupby("setup"):
        losses = abs(float(grp.loc[grp["pnl"] <= 0, "pnl"].sum()))
        rows.append({
            "Setup": setup, "Closed trades": len(grp),
            "Win rate": (grp["pnl"] > 0).mean() * 100,
            "P&L (฿)": float(grp["pnl"].sum()), "Same baht in SPY (฿)": float(grp["spy_pnl"].fillna(0).sum()),
            "Avg R": float(grp["r_multiple"].mean()),
            "Profit factor": float(grp.loc[grp["pnl"] > 0, "pnl"].sum()) / losses if losses else None,
        })
    return pd.DataFrame(rows).sort_values("P&L (฿)", ascending=False) if rows else pd.DataFrame()


def _vs_buy_and_hold(ledger: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> dict:
    """S&P 500 (SPY) bought on the first trade day and simply held, in baht.

    This is the harder benchmark: the strategy's return is measured on the capital it needs at
    its busiest, and that same capital could instead have sat in the index the whole time.
    """
    spy, fx = price_data.get(BENCHMARK), price_data.get(FX_TICKER)
    if ledger.empty or spy is None or fx is None:
        return {"spy_buy_hold_pct": None, "period_start": None, "period_end": None}
    start = ledger["entry_date"].min()
    spy0, fx0 = _close_on_or_before(spy, start), _close_on_or_before(fx, start)
    spy1, fx1 = float(spy["Close"].iloc[-1]), float(fx["Close"].iloc[-1])
    pct = ((spy1 * fx1) / (spy0 * fx0) - 1) * 100 if spy0 and fx0 else None
    return {"spy_buy_hold_pct": pct, "period_start": start, "period_end": _bar_date(spy.index[-1])}


def summarize(ledger: pd.DataFrame, price_data: dict[str, pd.DataFrame]) -> dict:
    closed = ledger[ledger["status"].isin([WON, LOST])]
    open_mtm = mark_to_market(ledger, price_data)
    wins, losses = closed[closed["pnl"] > 0], closed[closed["pnl"] <= 0]

    realized = float(closed["pnl"].sum())
    unrealized = float(open_mtm["unrealized_pnl"].sum()) if not open_mtm.empty else 0.0
    spy_total = float(closed["spy_pnl"].fillna(0).sum()) + (
        float(open_mtm["spy_unrealized_pnl"].sum()) if not open_mtm.empty else 0.0
    )
    gross_loss = abs(float(losses["pnl"].sum()))

    curve = equity_curve(ledger, price_data)
    max_dd = float((curve["strategy"].cummax() - curve["strategy"]).max()) if not curve.empty else 0.0

    hold_days = [
        (dt.date.fromisoformat(r["exit_date"]) - dt.date.fromisoformat(r["entry_date"])).days
        for _, r in closed.iterrows()
    ]
    return {
        "total_trades": len(ledger),
        "open_trades": len(open_mtm),
        "closed_trades": len(closed),
        "win_rate": len(wins) / len(closed) * 100 if len(closed) else None,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "spy_pnl": spy_total,
        "profit_factor": float(wins["pnl"].sum()) / gross_loss if gross_loss else None,
        "avg_r": float(closed["r_multiple"].mean()) if len(closed) else None,
        "max_drawdown": max_dd,
        "avg_hold_days": sum(hold_days) / len(hold_days) if hold_days else None,
        "capital_deployed": len(ledger) * POSITION_SIZE_THB,
        "peak_positions": (peak := peak_open_positions(ledger)),
        "peak_capital": peak * POSITION_SIZE_THB,
        "return_on_peak_capital": (realized + unrealized) / (peak * POSITION_SIZE_THB) * 100 if peak else None,
        **_vs_buy_and_hold(ledger, price_data),
    }


BACKTEST_DAYS = 252  # ~1 year of trading days per replayed period
BACKTEST_HISTORY = "37mo"  # two replay years plus the 13 months of history each replayed scan needs
LIVE_LOOKBACK = pd.DateOffset(months=13)  # matches data.HISTORY_PERIOD, so a replayed scan sees what a live one would

# Which slice of the downloaded history each period replays, as trading-day offsets from today.
# "prior" matters most: the rules were tuned while looking at "recent", so only "prior" shows
# how they do on a year they never saw.
BACKTEST_PERIODS = {
    "recent": (-BACKTEST_DAYS, None),
    "prior": (-2 * BACKTEST_DAYS, -BACKTEST_DAYS),
}


def _backtest_path(period: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "data", f"backtest_trades_{period}.csv")


def run_backtest(period: str = "recent", progress=None) -> pd.DataFrame:
    """Replay the exact paper-trading rules over one past year (see BACKTEST_PERIODS).

    Each replayed day only sees the 13 months of prices that existed up to and including
    that day - the same window a live scan gets - so no future data leaks into a decision.
    Exits and entries then run in the same order as a live cycle.
    """
    uni = universe.get_tickers_for_sectors(PAPER_SECTORS)
    full = data.fetch_history(sorted(set(uni["ticker"]) | {BENCHMARK, FX_TICKER}), period=BACKTEST_HISTORY)
    start, end = BACKTEST_PERIODS[period]
    replay_dates = full[BENCHMARK].index[start:end]

    ledger = _normalize(pd.DataFrame(columns=COLUMNS))
    for n, day in enumerate(replay_dates):
        as_of = {}
        for ticker, df in full.items():
            window = df.loc[day - LIVE_LOOKBACK : day]
            if ticker == FX_TICKER or (not window.empty and window.index[-1] == day):  # skip tickers with no bar that day
                as_of[ticker] = window
        ledger = _update_open_trades(ledger, as_of)
        ledger = _open_new_trades(ledger, screener.scan(uni, as_of), as_of)
        if progress:
            progress((n + 1) / len(replay_dates), day)

    save_ledger(ledger, _backtest_path(period))
    return ledger


def load_backtest(period: str = "recent") -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dt.datetime] | None:
    """A saved backtest, with prices cut off at the end of its period (so positions still open
    then are marked at that day's prices, not today's), or None if it hasn't been run."""
    path = _backtest_path(period)
    if not os.path.exists(path):
        return None
    ledger = load_ledger(path)
    tickers = sorted(set(ledger["ticker"]) | {BENCHMARK, FX_TICKER})
    full = data.fetch_history(tickers, period=BACKTEST_HISTORY)
    start, end = BACKTEST_PERIODS[period]
    last_day = full[BENCHMARK].index[start:end][-1]
    prices = {t: df.loc[:last_day] for t, df in full.items()}
    return ledger, prices, dt.datetime.fromtimestamp(os.path.getmtime(path))


if __name__ == "__main__":
    # Always download fresh: the daily cache may hold a mid-session bar from earlier the same day.
    print(f"--- {dt.datetime.now():%Y-%m-%d %H:%M} ---")
    ledger, prices = run_cycle(force_refresh=True)
    stats = summarize(ledger, prices)
    print(f"Paper trades: {stats['total_trades']} ({stats['open_trades']} open, {stats['closed_trades']} closed)")
    print(f"Total P&L: {stats['total_pnl']:,.2f} baht  vs same baht in SPY: {stats['spy_pnl']:,.2f} baht")
    if stats["win_rate"] is not None:
        print(f"Win rate: {stats['win_rate']:.0f}%")
