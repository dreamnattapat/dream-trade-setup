"""Turn a detected Setup into a STRONG BUY..STRONG SELL rating.

The composite score blends three plain, inspectable ingredients:
  - reward:risk ratio        (45%) - is the trade worth taking at all
  - proximity to entry price (35%) - is *now* a good time to act on it
  - setup quality            (20%) - how well-formed is the range/base

Ratings answer "how good is this as a NEW swing-trade entry right now",
not "is this a good company" or "should you hold if you already own it".
"""

from .screener import Setup

RATING_THRESHOLDS = [
    (80, "STRONG BUY"),
    (60, "BUY"),
    (40, "HOLD"),
    (20, "SELL"),
]
DEFAULT_RATING = "STRONG SELL"

RR_FLOOR, RR_CEIL = 1.0, 8.0  # reward:risk mapped to 0..100 across this range
MAX_QUALITY_TOUCHES = 6
MAX_BASING_DAYS = 30


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _rr_score(rr: float) -> float:
    return _clamp((rr - RR_FLOOR) / (RR_CEIL - RR_FLOOR) * 100)


def _entry_proximity_score(setup: Setup) -> float:
    """Peaks at the entry price; decays to 0 at the stop (breakdown risk) and at the target (already ran)."""
    price, entry, target, stop = setup.current_price, setup.entry, setup.target, setup.stop
    if price <= stop or price >= target:
        return 0.0
    if price <= entry:
        return _clamp(100 * (price - stop) / (entry - stop))
    return _clamp(100 * (target - price) / (target - entry))


def _quality_score(setup: Setup) -> float:
    if setup.setup_type == "Sideways Range":
        return _clamp(setup.touches / MAX_QUALITY_TOUCHES * 100)
    days = setup.days_since_low or 0
    return _clamp(days / MAX_BASING_DAYS * 100)


def score_setup(setup: Setup) -> float:
    composite = (
        0.30 * _rr_score(setup.reward_risk)
        + 0.50 * _entry_proximity_score(setup)
        + 0.20 * _quality_score(setup)
    )
    return round(composite, 1)


def rate(score: float) -> str:
    for threshold, label in RATING_THRESHOLDS:
        if score >= threshold:
            return label
    return DEFAULT_RATING


AT_ENTRY_PCT = 1.0  # price at or within 1% above entry counts as "hit"
NEAR_ENTRY_PCT = 5.0  # within 5% above entry is close enough to watch closely

ENTRY_STATUS_ORDER = ["At Entry", "Near Entry", "Waiting for Pullback"]


def entry_status(setup: Setup) -> str:
    """Is *today's* price actually at the entry level, or still waiting for a pullback?

    This is deliberately separate from the overall rating: a setup can be an excellent
    STRONG BUY candidate on quality/R:R while still trading well above its entry price.
    """
    pct_above = (setup.current_price - setup.entry) / setup.entry * 100
    if pct_above <= AT_ENTRY_PCT:
        return "At Entry"
    if pct_above <= NEAR_ENTRY_PCT:
        return "Near Entry"
    return "Waiting for Pullback"
