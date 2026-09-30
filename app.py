import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import data, rating, screener, universe

st.set_page_config(page_title="DreamTradeSetup", page_icon="📈", layout="wide")

RATING_COLORS = {
    "STRONG BUY": "#0f9d58",
    "BUY": "#34a853",
    "HOLD": "#f9ab00",
    "SELL": "#ea4335",
    "STRONG SELL": "#b31412",
}
RATING_ORDER = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]


@st.cache_data(show_spinner=False)
def load_universe():
    return universe.get_universe()


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def run_scan(sectors: tuple[str, ...], force_refresh: bool) -> pd.DataFrame:
    uni = universe.get_tickers_for_sectors(list(sectors))
    price_data = data.fetch_history(uni["ticker"].tolist(), force_refresh=force_refresh)
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
                "Score": score,
                "Price": s.current_price,
                "Entry": s.entry,
                "Target": s.target,
                "Stop Loss": s.stop,
                "R:R": s.reward_risk,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["Ticker", "Company", "Sector", "Setup", "Rating", "Score", "Price", "Entry", "Target", "Stop Loss", "R:R"]
        )

    df = pd.DataFrame(rows)
    df["_rating_rank"] = df["Rating"].map({r: i for i, r in enumerate(RATING_ORDER)})
    df = df.sort_values(["_rating_rank", "Score"], ascending=[True, False]).drop(columns="_rating_rank")
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
        fig.add_hline(y=value, line_dash="dash", line_color=color, annotation_text=f"{label}: {value:.2f}")

    fig.update_layout(
        title=f"{ticker} — {row['Setup']}",
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def position_size_calculator():
    st.subheader("Position size calculator")
    account_size = st.number_input("Account size ($)", min_value=0.0, value=10000.0, step=500.0)
    risk_pct = st.slider("Risk per trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
    entry = st.number_input("Entry price", min_value=0.0, value=0.0, step=0.01)
    stop = st.number_input("Stop loss price", min_value=0.0, value=0.0, step=0.01)

    if entry > 0 and stop > 0 and entry > stop:
        risk_dollars = account_size * (risk_pct / 100)
        per_share_risk = entry - stop
        shares = int(risk_dollars // per_share_risk)
        st.metric("Risk amount", f"${risk_dollars:,.2f}")
        st.metric("Suggested shares", f"{shares:,}")
        st.metric("Position value", f"${shares * entry:,.2f}")
    else:
        st.caption("Enter an entry price above the stop loss to calculate size.")


def main():
    st.title("📈 DreamTradeSetup")
    st.caption("Rule-based swing-trade setup finder — sideways ranges and 52-week-low basing setups, ranked for you.")

    uni = load_universe()
    sectors = sorted(uni["sector"].unique().tolist())

    with st.sidebar:
        st.header("Filters")
        selected_sectors = st.multiselect("Industry / Sector", sectors, default=sectors)
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
        if not selected_sectors:
            st.warning("Select at least one sector in the sidebar.")
            return
        with st.spinner("Scanning stocks... this can take a minute for many sectors."):
            df = run_scan(tuple(selected_sectors), force_refresh)
            uni_filtered = universe.get_tickers_for_sectors(selected_sectors)
            st.session_state.price_cache = data.fetch_history(uni_filtered["ticker"].tolist(), force_refresh=force_refresh)
        st.session_state.results = df

    df = st.session_state.results
    if df is None or df.empty:
        st.info("No qualifying setups found yet. Click **Run scan** in the sidebar.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Setups found", len(df))
    col2.metric("Strong Buy / Buy", int(df["Rating"].isin(["STRONG BUY", "BUY"]).sum()))
    col3.metric("Sectors scanned", len(selected_sectors))

    st.subheader("Ranked setups")
    display_df = df.copy()

    def _style_rating(val):
        color = RATING_COLORS.get(val, "")
        return f"background-color: {color}; color: white; font-weight: 600;" if color else ""

    styled = display_df.style.map(_style_rating, subset=["Rating"]).format(
        {
            "Price": "${:.2f}",
            "Entry": "${:.2f}",
            "Target": "${:.2f}",
            "Stop Loss": "${:.2f}",
            "Score": "{:.1f}",
            "R:R": "{:.2f}",
        }
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
        m1, m2, m3, m4, m5 = st.columns(5)
        rating_color = RATING_COLORS.get(selected["Rating"], "#888")
        m1.markdown("Rating")
        m1.markdown(
            f"<span style='background-color:{rating_color}; color:white; padding:4px 10px; "
            f"border-radius:4px; font-weight:600; font-size:1.1rem;'>{selected['Rating']}</span>",
            unsafe_allow_html=True,
        )
        m2.metric("Entry", f"${selected['Entry']:.2f}")
        m3.metric("Target", f"${selected['Target']:.2f}")
        m4.metric("Stop Loss", f"${selected['Stop Loss']:.2f}")
        m5.metric("Reward:Risk", f"{selected['R:R']:.2f}")
        price_chart(selected["Ticker"], selected, st.session_state.price_cache)
    else:
        st.caption("Select a row above to see the price chart with entry/target/stop levels.")

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Export as CSV", csv, "dream_trade_setups.csv", "text/csv")


if __name__ == "__main__":
    main()
