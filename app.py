import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import paper_page
from src import data, indicators, paper, rating, screener, universe

st.set_page_config(page_title="DreamTradeSetup", page_icon="📈", layout="wide")

WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "watchlist.txt")
DEFAULT_SECTORS = [
    "Information Technology", "Energy", "Financials", "Health Care", "Industrials", "Materials",
]


def load_watchlist() -> str:
    if not os.path.exists(WATCHLIST_PATH):
        return ""
    with open(WATCHLIST_PATH) as f:
        tickers = [line.strip().upper() for line in f if line.strip()]
    return ", ".join(tickers)


def save_watchlist(tickers: tuple[str, ...]) -> None:
    with open(WATCHLIST_PATH, "w") as f:
        f.write("\n".join(tickers) + "\n" if tickers else "")

RATING_COLORS = {
    "STRONG BUY": "#0f9d58",
    "BUY": "#34a853",
    "HOLD": "#f9ab00",
    "SELL": "#ea4335",
    "STRONG SELL": "#b31412",
    "FILTERED OUT": "#9aa0a6",
}
RATING_ORDER = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]


@st.cache_data(show_spinner=False)
def load_universe():
    return universe.get_universe()


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def lookup_custom_tickers(tickers: tuple[str, ...]) -> pd.DataFrame:
    return universe.get_custom_tickers(list(tickers))


def build_universe(sectors: list[str], extra_tickers: tuple[str, ...]) -> pd.DataFrame:
    uni = universe.get_tickers_for_sectors(sectors)
    if extra_tickers:
        custom = lookup_custom_tickers(extra_tickers)
        custom = custom[~custom["ticker"].isin(uni["ticker"])]
        uni = pd.concat([uni, custom], ignore_index=True)
    return uni


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def run_scan(sectors: tuple[str, ...], extra_tickers: tuple[str, ...], force_refresh: bool) -> pd.DataFrame:
    uni = build_universe(list(sectors), extra_tickers)
    price_data = data.fetch_history(uni["ticker"].tolist() + [screener.MARKET_TICKER], force_refresh=force_refresh)
    market_gap = screener.market_gap_pct(price_data)
    setups = screener.scan(uni, price_data)

    rows = []
    for s in setups:
        score = rating.score_setup(s)
        rows.append(
            {
                "Ticker": s.ticker,
                "Company": s.company,
                "Sector": s.sector,
                "Setup": s.setup_type,
                "Rating": rating.rate(score),
                "Entry Status": rating.entry_status(s),
                "Score": score,
                "Price": s.current_price,
                "Entry": s.entry,
                "Target": s.target,
                "Stop Loss": s.stop,
                "R:R": s.reward_risk,
                "Volatility": s.volatility_pct,
                "Reason": "",
            }
        )

    # Tickers explicitly requested always show up, even when no setup qualifies -
    # sector-wide scan results stay clean (only real setups), but "your" tickers don't vanish.
    matched = {s.ticker for s in setups}
    for t in extra_tickers:
        if t in matched:
            continue
        df_prices = price_data.get(t)
        if df_prices is None or df_prices.empty:
            continue
        info = uni[uni["ticker"] == t]
        company = info["company"].iloc[0] if not info.empty else t
        sector = info["sector"].iloc[0] if not info.empty else "-"
        rows.append(
            {
                "Ticker": t,
                "Company": company,
                "Sector": sector,
                "Setup": "-",
                "Rating": "FILTERED OUT",
                "Entry Status": "-",
                "Score": None,
                "Price": float(df_prices["Close"].iloc[-1]),
                "Entry": None,
                "Target": None,
                "Stop Loss": None,
                "R:R": None,
                "Volatility": indicators.annualized_volatility_pct(df_prices["Close"]),
                "Reason": screener.explain_no_setup(df_prices, market_gap),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["Ticker", "Company", "Sector", "Setup", "Rating", "Entry Status", "Score", "Price", "Entry", "Target", "Stop Loss", "R:R", "Volatility", "Reason"]
        )

    df = pd.DataFrame(rows)
    df["_rating_rank"] = df["Rating"].map({r: i for i, r in enumerate(RATING_ORDER)})
    df["_entry_rank"] = df["Entry Status"].map({s: i for i, s in enumerate(rating.ENTRY_STATUS_ORDER)})
    df = df.sort_values(["_rating_rank", "_entry_rank", "Score"], ascending=[True, True, False]).drop(
        columns=["_rating_rank", "_entry_rank"]
    )
    return df.reset_index(drop=True)


def price_chart(ticker: str, row: pd.Series, price_data: dict[str, pd.DataFrame]):
    df = price_data.get(ticker)
    if df is None:
        st.warning("No price history cached for this ticker in this session — re-run the scan.")
        return

    plot_df = df.tail(160)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=plot_df.index,
            open=plot_df["Open"],
            high=plot_df["High"],
            low=plot_df["Low"],
            close=plot_df["Close"],
            name=ticker,
        )
    )
    for label, value, color in [
        ("Entry", row["Entry"], "#34a853"),
        ("Target", row["Target"], "#4285f4"),
        ("Stop Loss", row["Stop Loss"], "#ea4335"),
    ]:
        if pd.isna(value):
            continue
        fig.add_hline(y=value, line_dash="dash", line_color=color, annotation_text=f"{label}: {value:.2f}")

    fig.update_layout(
        title=f"{ticker} — {row['Setup']}",
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(show_spinner=False, ttl=3600)
def usd_thb_rate() -> float | None:
    fx = data.fetch_history([paper.FX_TICKER]).get(paper.FX_TICKER)
    return float(fx["Close"].iloc[-1]) if fx is not None else None


def position_size_calculator():
    st.subheader("Position size calculator")
    account_size = st.number_input("Account size (฿)", min_value=0.0, value=300000.0, step=10000.0)
    risk_pct = st.slider("Risk per trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
    entry = st.number_input("Entry price (US$)", min_value=0.0, value=0.0, step=0.01)
    stop = st.number_input("Stop loss price (US$)", min_value=0.0, value=0.0, step=0.01)

    rate = usd_thb_rate()
    if not rate:
        st.caption("Couldn't load today's USD/THB rate - try again shortly.")
    elif entry > 0 and stop > 0 and entry > stop:
        risk_baht = account_size * (risk_pct / 100)
        per_share_risk_baht = (entry - stop) * rate
        shares = int(risk_baht // per_share_risk_baht)
        st.metric("Risk amount", f"฿{risk_baht:,.2f}")
        st.metric("Suggested shares", f"{shares:,}")
        st.metric("Position value", f"฿{shares * entry * rate:,.2f}", help=f"US${shares * entry:,.2f} at {rate:.2f} baht per dollar")
        st.caption(f"Using today's rate: {rate:.2f} baht per US dollar")
    else:
        st.caption("Enter an entry price above the stop loss to calculate size.")


def main():
    st.title("📈 DreamTradeSetup")
    st.caption("Rule-based swing-trade setup finder — sideways ranges, 52-week-low basing, and uptrend pullbacks, ranked for you.")

    uni = load_universe()
    sectors = sorted(uni["sector"].unique().tolist())

    with st.sidebar:
        st.header("Filters")
        default_sectors = [s for s in DEFAULT_SECTORS if s in sectors] or sectors
        selected_sectors = st.multiselect("Industry / Sector", sectors, default=default_sectors)
        extra_input = st.text_input(
            "Add specific tickers",
            value=load_watchlist(),
            placeholder="e.g. SOFI, PLTR",
            help="Force-include tickers that aren't in the S&P 500/400 universe, regardless of the sector filter above. Pre-filled from your saved watchlist.",
        )
        extra_tickers = tuple(sorted({t.strip().upper() for t in extra_input.split(",") if t.strip()}))
        if st.button("💾 Save as my watchlist", use_container_width=True):
            save_watchlist(extra_tickers)
            st.success(f"Saved {len(extra_tickers)} tickers to your watchlist.")
        force_refresh = st.checkbox("Force refresh price data", value=False, help="Bypass today's cache and re-download from Yahoo Finance.")
        run_clicked = st.button("🔍 Run scan", type="primary", use_container_width=True)
        st.divider()
        position_size_calculator()
        st.divider()
        st.caption(
            "⚠️ Not financial advice. This is a mechanical technical screener — "
            "always do your own research and manage risk before trading."
        )

    if "results" not in st.session_state:
        st.session_state.results = None
        st.session_state.price_cache = {}

    if run_clicked or st.session_state.results is None:
        if not selected_sectors and not extra_tickers:
            st.warning("Select at least one sector, or add a specific ticker, in the sidebar.")
            return
        with st.spinner("Scanning stocks... this can take a minute for many sectors."):
            df = run_scan(tuple(selected_sectors), extra_tickers, force_refresh)
            uni_filtered = build_universe(selected_sectors, extra_tickers)
            st.session_state.price_cache = data.fetch_history(uni_filtered["ticker"].tolist(), force_refresh=force_refresh)
        st.session_state.results = df

    df = st.session_state.results
    if df is None or df.empty:
        st.info("No qualifying setups found yet. Click **Run scan** in the sidebar.")
        return

    qualifying = df[df["Rating"] != "FILTERED OUT"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Setups found", len(qualifying))
    col2.metric("Strong Buy / Buy", int(qualifying["Rating"].isin(["STRONG BUY", "BUY"]).sum()))
    col3.metric("At Entry now", int((qualifying["Entry Status"] == "At Entry").sum()))
    col4.metric("Sectors scanned", len(selected_sectors))

    gap = screener.market_gap_pct(data.fetch_history([screener.MARKET_TICKER]))
    if gap is not None and gap > screener.UPTREND_MAX_MARKET_GAP_PCT:
        st.info(f"**Uptrend Pullback signals are paused.** The S&P 500 is {gap:.1f}% above its 50-day average. "
                "Backtests showed this setup only pays off when the whole market is dipping, so it switches back on "
                "when the S&P 500 drops to or below that average.", icon="⏸️")

    st.subheader("Ranked setups")
    display_df = df.copy()

    def _style_rating(val):
        color = RATING_COLORS.get(val, "")
        return f"background-color: {color}; color: white; font-weight: 600;" if color else ""

    ENTRY_STATUS_STYLES = {
        "At Entry": "color: #0f9d58; font-weight: 600;",
        "Near Entry": "color: #b8860b; font-weight: 600;",
        "Waiting for Pullback": "color: #888;",
    }

    def _style_entry_status(val):
        return ENTRY_STATUS_STYLES.get(val, "")

    styled = display_df.style.map(_style_rating, subset=["Rating"]).map(
        _style_entry_status, subset=["Entry Status"]
    ).format(
        {
            "Price": "${:.2f}",
            "Entry": "${:.2f}",
            "Target": "${:.2f}",
            "Stop Loss": "${:.2f}",
            "Score": "{:.1f}",
            "R:R": "{:.2f}",
            "Volatility": "{:.0f}%",
        },
        na_rep="–",
    )

    event = st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="results_table",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        selected = df.iloc[selected_rows[0]]
        st.divider()
        st.subheader(f"{selected['Ticker']} — {selected['Company']}")
        rating_color = RATING_COLORS.get(selected["Rating"], "#888")
        badges = f"<span style='background-color:{rating_color}; color:white; padding:4px 10px; border-radius:4px; font-weight:600; font-size:1.1rem;'>{selected['Rating']}</span>"
        if selected["Rating"] != "FILTERED OUT":
            badges += f"&nbsp;&nbsp;<span style='padding:4px 10px; border:1px solid #ccc; border-radius:4px; font-weight:600; font-size:1.1rem;'>{selected['Entry Status']}</span>"
        st.markdown(badges, unsafe_allow_html=True)
        if selected["Rating"] == "FILTERED OUT":
            st.write(f"**Current price:** ${selected['Price']:.2f}  |  **Volatility:** {selected['Volatility']:.0f}% annualized")
            st.write(f"**Why it's filtered out:** {selected['Reason']}")
        else:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Entry", f"${selected['Entry']:.2f}")
            m2.metric("Target", f"${selected['Target']:.2f}")
            m3.metric("Stop Loss", f"${selected['Stop Loss']:.2f}")
            m4.metric("Reward:Risk", f"{selected['R:R']:.2f}")
            m5.metric("Volatility", f"{selected['Volatility']:.0f}%")
        price_chart(selected["Ticker"], selected, st.session_state.price_cache)
    else:
        st.caption("Select a row above to see the price chart with entry/target/stop levels.")

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Export as CSV", csv, "dream_trade_setups.csv", "text/csv")


st.navigation([
    st.Page(main, title="Scanner", icon="📈", default=True),
    st.Page(paper_page.render, title="Paper Trading", icon="🧪", url_path="paper"),
]).run()
