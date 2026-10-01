import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import paper, screener

STRATEGY_COLOR = "#2a78d6"
SPY_COLOR = "#eb6834"


def _money(x: float) -> str:
    return f"-฿{abs(x):,.2f}" if x < 0 else f"฿{x:,.2f}"


# Streamlit has no baht number format, so baht columns say "(฿)" in the header and use a
# localized number (correct minus sign, thousands separators). Stock prices stay in US$.
BAHT = st.column_config.NumberColumn(format="localized")
USD = st.column_config.NumberColumn(format="dollar")


def _run_cycle(force_refresh: bool = False) -> None:
    with st.spinner("Updating paper positions and checking today's signals..."):
        ledger, prices = paper.run_cycle(force_refresh=force_refresh)
    st.session_state.paper_ledger = ledger
    st.session_state.paper_prices = prices


def _vs_sp500(stats: dict) -> None:
    strat, index = stats["return_on_peak_capital"], stats["spy_buy_hold_pct"]
    if strat is None or index is None:
        return
    gap = strat - index
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Strategy return", f"{strat:+.1f}%",
                  help="Total P&L ÷ the peak capital needed to follow every signal.")
        c2.metric("S&P 500 buy & hold", f"{index:+.1f}%",
                  help="The same capital put into SPY on the first trade day and simply held, converted "
                       "to baht. Harder to beat than the per-trade comparison below, because this money "
                       "is never sitting idle.")
        even = round(gap, 1) == 0
        times = f"{strat / index:.1f}× the index return" if index > 0 and strat > 0 and not even else None
        label = "Even with the S&P 500" if even else ("Beat the S&P 500 by" if gap > 0 else "Behind the S&P 500 by")
        c3.metric(label, f"{abs(gap):.1f} pts", delta=times, delta_color="normal" if gap > 0 else "inverse",
                  delta_arrow="up" if gap > 0 else "down",
                  help="Strategy return minus S&P 500 return, in percentage points.")
        days = (pd.Timestamp(stats["period_end"]) - pd.Timestamp(stats["period_start"])).days
        note = " · too early to judge - this needs weeks of trades" if days < 30 else ""
        st.caption(f"{stats['period_start']} to {stats['period_end']} ({days} days), in baht including USD/THB moves{note}")


def _kpis(stats: dict) -> None:
    edge = stats["total_pnl"] - stats["spy_pnl"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total P&L", _money(stats["total_pnl"]), delta=f"{_money(edge)} vs SPY",
              delta_color="normal" if round(edge, 2) else "off",
              help="Realized + unrealized, in baht. The delta is how far ahead (or behind) of putting the same baht into SPY on the same dates.")
    c2.metric("Win rate", f"{stats['win_rate']:.0f}%" if stats["win_rate"] is not None else "–",
              help="Share of closed trades that made money.")
    c3.metric("Open / closed trades", f"{stats['open_trades']} / {stats['closed_trades']}")
    c4.metric("Profit factor", f"{stats['profit_factor']:.2f}" if stats["profit_factor"] is not None else "–",
              help="Gross wins ÷ gross losses. Above 1.0 makes money; 1.5+ is solid.")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Same baht in SPY", _money(stats["spy_pnl"]),
              help="What the same baht per trade would have made sitting in SPY over each trade's exact dates "
                   "(including the same USD/THB conversion).")
    c6.metric("Avg R multiple", f"{stats['avg_r']:+.2f}R" if stats["avg_r"] is not None else "–",
              help="Average closed-trade result measured in units of the risk taken (entry − stop). +1R = made what you risked.")
    c7.metric("Max drawdown", _money(-stats["max_drawdown"]) if stats["max_drawdown"] else _money(0),
              help="Biggest peak-to-trough drop in cumulative P&L.")
    c8.metric("Peak capital needed", _money(stats["peak_capital"]),
              delta=f"{stats['return_on_peak_capital']:+.1f}% return on it" if stats["return_on_peak_capital"] is not None else None,
              delta_color="normal" if round(stats["return_on_peak_capital"] or 0, 1) else "off",
              help="The most positions open on any one day × the per-trade size - the cash you'd actually need "
                   "to follow every signal. The delta is total P&L as a % of that.")
    hold = f"{stats['avg_hold_days']:.0f} days avg hold · " if stats["avg_hold_days"] is not None else ""
    st.caption(f"{_money(paper.POSITION_SIZE_THB)} per trade · {hold}{_money(stats['realized_pnl'])} realized · "
               f"{_money(stats['unrealized_pnl'])} unrealized · up to {stats['peak_positions']} positions at once · "
               "includes USD/THB exchange-rate moves")


def _equity_chart(curve: pd.DataFrame, key: str) -> None:
    st.subheader("Cumulative P&L vs SPY (baht)")
    if len(curve) < 2:
        st.caption("The chart appears after the first full trading day of history.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.index, y=curve["strategy"], name="Strategy", mode="lines",
                             line=dict(color=STRATEGY_COLOR, width=2),
                             hovertemplate="฿%{y:,.2f}<extra>Strategy</extra>"))
    fig.add_trace(go.Scatter(x=curve.index, y=curve["spy"], name="Same baht in SPY", mode="lines",
                             line=dict(color=SPY_COLOR, width=2, dash="dash"),
                             hovertemplate="฿%{y:,.2f}<extra>Same baht in SPY</extra>"))
    fig.add_hline(y=0, line_width=1, line_color="rgba(128,128,128,0.5)")
    fig.update_layout(hovermode="x unified", height=360, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(tickformat=",.0f", ticksuffix=" ฿", title=None),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig, use_container_width=True, key=f"{key}_curve")


def _open_positions(ledger: pd.DataFrame, prices: dict) -> None:
    st.subheader("Open positions")
    mtm = paper.mark_to_market(ledger, prices)
    if mtm.empty:
        st.caption("No open positions.")
        return
    view = pd.DataFrame({
        "Ticker": mtm["ticker"], "Company": mtm["company"], "Setup": mtm["setup"], "Rating": mtm["rating"],
        "Entry date": mtm["entry_date"], "Entry": mtm["entry_price"], "Current": mtm["current_price"],
        "Target": mtm["target"], "Stop": mtm["stop"], "P&L (฿)": mtm["unrealized_pnl"].round(2),
        "P&L %": mtm["unrealized_pnl"] / (mtm["shares"] * mtm["entry_price"] * mtm["fx_entry"]) * 100,
        "Same baht in SPY (฿)": mtm["spy_unrealized_pnl"].round(2), "Days held": mtm["days_held"],
    })
    st.dataframe(view, hide_index=True, use_container_width=True, column_config={
        c: USD for c in ["Entry", "Current", "Target", "Stop"]
    } | {"P&L (฿)": BAHT, "Same baht in SPY (฿)": BAHT, "P&L %": st.column_config.NumberColumn(format="%+.1f%%")})


def _closed_trades(ledger: pd.DataFrame) -> None:
    st.subheader("Closed trades")
    closed = ledger[ledger["status"].isin([paper.WON, paper.LOST])].sort_values("exit_date", ascending=False)
    if closed.empty:
        st.caption("No closed trades yet - positions close when they hit their take-profit or stop-loss.")
        return
    view = pd.DataFrame({
        "Ticker": closed["ticker"], "Setup": closed["setup"], "Result": closed["status"],
        "Exit reason": closed["exit_reason"], "Entry date": closed["entry_date"], "Exit date": closed["exit_date"],
        "Entry": closed["entry_price"], "Exit": closed["exit_price"], "P&L (฿)": closed["pnl"],
        "P&L %": closed["pnl_pct"], "R": closed["r_multiple"], "Same baht in SPY (฿)": closed["spy_pnl"],
    })
    st.dataframe(view, hide_index=True, use_container_width=True, column_config={
        "Entry": USD, "Exit": USD, "P&L (฿)": BAHT, "Same baht in SPY (฿)": BAHT,
    } | {"P&L %": st.column_config.NumberColumn(format="%+.1f%%"), "R": st.column_config.NumberColumn(format="%+.2fR")})


def _setup_breakdown(ledger: pd.DataFrame) -> None:
    st.subheader("Which setup is earning?")
    table = paper.setup_breakdown(ledger)
    if table.empty:
        st.caption("Appears once trades start closing.")
        return
    st.dataframe(table, hide_index=True, use_container_width=True, column_config={
        "Win rate": st.column_config.NumberColumn(format="%.0f%%"),
        "P&L (฿)": BAHT,
        "Same baht in SPY (฿)": BAHT,
        "Avg R": st.column_config.NumberColumn(format="%+.2fR"),
        "Profit factor": st.column_config.NumberColumn(format="%.2f"),
    })


def _results(ledger: pd.DataFrame, prices: dict, key: str) -> None:
    stats = paper.summarize(ledger, prices)
    _vs_sp500(stats)
    _kpis(stats)
    st.divider()
    _equity_chart(paper.equity_curve(ledger, prices), key)
    _setup_breakdown(ledger)
    _open_positions(ledger, prices)
    _closed_trades(ledger)


def _live_tab() -> None:
    with st.expander("How the simulation trades"):
        st.markdown(
            f"- **Universe:** {', '.join(paper.PAPER_SECTORS)} only.\n"
            f"- **Buys** every {' / '.join(sorted(paper.PAPER_RATINGS, reverse=True))} setup whose Entry Status is "
            f"**{paper.PAPER_ENTRY_STATUS}**, at the latest price, ฿{paper.POSITION_SIZE_THB:,.0f} per trade (converted to US dollars at that day's "
            "USD/THB rate, and back to baht when it sells), one position per ticker.\n"
            "- **Sells** when a later daily bar hits the setup's take-profit or stop-loss. If a bar *opens* past either "
            "level (a gap), it fills at that open. If one day touches both, that day's hourly prices decide which came "
            "first; if hourly data can't settle it, it counts as a stop-out (the worse case).\n"
            "- **Uptrend Pullback** only buys while the S&P 500 is at or below its 50-day average - backtests showed "
            "pullbacks pay off when the whole market is dipping, and break even otherwise.\n"
            "- **Benchmark:** every trade is shadowed by the same baht in SPY over the same dates.\n"
            "- Positions update each time this page opens (it catches up on any days you missed), or run `make paper` "
            "from a terminal. New entries are only picked up on days a cycle runs."
        )

    col_a, col_b, _ = st.columns([1, 1, 3])
    if col_a.button("🔄 Update now", use_container_width=True) or "paper_ledger" not in st.session_state:
        _run_cycle()
    force = col_b.button("Force refresh prices", use_container_width=True)
    if force:
        _run_cycle(force_refresh=True)

    ledger = st.session_state.paper_ledger
    prices = st.session_state.paper_prices
    if ledger.empty:
        paused = "" if screener.uptrend_pullbacks_allowed(prices) else (
            " Uptrend Pullback signals are also paused while the S&P 500 is above its 50-day average.")
        st.info("No paper trades yet - nothing in the universe is a BUY/STRONG BUY at its entry price today."
                f"{paused} Check back after the next update.")
        return

    _results(ledger, prices, key="live")

    with st.expander("Reset paper portfolio"):
        st.caption("Deletes every simulated trade and starts over. This can't be undone.")
        confirm = st.checkbox("Yes, delete all paper trades")
        if st.button("Reset", disabled=not confirm):
            paper.reset_ledger()
            st.session_state.pop("paper_ledger", None)
            st.rerun()


PERIOD_LABELS = {
    "recent": "Past year",
    "prior": "Year before (rules never saw it)",
}


def _both_years(saved: dict) -> None:
    rows = []
    for period, label in PERIOD_LABELS.items():
        if saved[period] is None:
            continue
        ledger, prices, _ = saved[period]
        stats = paper.summarize(ledger, prices)
        strat, index = stats["return_on_peak_capital"], stats["spy_buy_hold_pct"]
        rows.append({
            "Year": label, "From": stats["period_start"], "To": stats["period_end"],
            "Closed trades": stats["closed_trades"], "Win rate": stats["win_rate"],
            "Strategy": strat, "S&P 500 buy & hold": index,
            "vs S&P 500 (pts)": strat - index if strat is not None and index is not None else None,
        })
    if not rows:
        return
    st.subheader("Both years at a glance")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={
        "Win rate": st.column_config.NumberColumn(format="%.0f%%"),
        "Strategy": st.column_config.NumberColumn(format="%+.1f%%"),
        "S&P 500 buy & hold": st.column_config.NumberColumn(format="%+.1f%%"),
        "vs S&P 500 (pts)": st.column_config.NumberColumn(format="%+.1f"),
    })
    st.caption("The rules were tuned while looking at the past year, so it flatters them. The year before is the "
               "honest test - if the strategy only wins the year it was tuned on, the edge isn't proven.")


def _backtest_tab() -> None:
    st.markdown(
        f"Replays the **exact same rules** as the live portfolio over a past year (~{paper.BACKTEST_DAYS} trading days). "
        "Each replayed day only sees prices up to that day - the same 13-month window a live scan gets - so no "
        "future data leaks into a decision."
    )
    st.warning(
        "**Read this before trusting the numbers.** A backtest flatters a strategy in ways a live test can't: "
        "it uses *today's* Information Technology list, so stocks that crashed out of the index are missing "
        "(survivorship bias), and the screener's rules were tuned while looking at the past year. Use it to compare "
        "setups and spot what clearly doesn't work - the live tab is the real proof.",
        icon="⚠️",
    )

    saved = {period: paper.load_backtest(period) for period in PERIOD_LABELS}
    missing = [p for p, v in saved.items() if v is None]
    if missing and st.button("⏪ Run backtests (about 20 seconds per year)", type="primary"):
        for period in missing:
            bar = st.progress(0.0, text=f"{PERIOD_LABELS[period]}: replaying...")
            paper.run_backtest(period, progress=lambda frac, day, bar=bar, period=period: bar.progress(
                frac, text=f"{PERIOD_LABELS[period]}: replaying {day.date()}..."))
            bar.empty()
            saved[period] = paper.load_backtest(period)

    _both_years(saved)
    if all(v is None for v in saved.values()):
        st.info("No backtests yet - click **Run backtests**.")
        return

    st.divider()
    available = [p for p in PERIOD_LABELS if saved[p] is not None]
    period = st.radio("Show details for", available, format_func=PERIOD_LABELS.get, horizontal=True)
    ledger, prices, ran_at = saved[period]
    col_a, col_b = st.columns([4, 1])
    col_a.caption(f"Last run {ran_at:%Y-%m-%d %H:%M}")
    if col_b.button("Re-run this year", use_container_width=True):
        bar = st.progress(0.0, text="Replaying...")
        paper.run_backtest(period, progress=lambda frac, day: bar.progress(frac, text=f"Replaying {day.date()}..."))
        bar.empty()
        st.rerun()
    _results(ledger, prices, key=f"backtest_{period}")


def render() -> None:
    st.title("🧪 Paper Trading")
    st.caption("The screener trades its own signals with simulated money, so you can see whether they actually "
               "work before putting real money behind them.")
    live, backtest = st.tabs(["📅 Live (from today forward)", "⏪ Backtest (2 years)"])
    with live:
        _live_tab()
    with backtest:
        _backtest_tab()
