"""Small technical-indicator helpers shared by the screener."""

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def linreg_slope_pct(series: pd.Series) -> float:
    """Slope of a linear fit through `series`, expressed as fraction of the mean price per day."""
    y = series.to_numpy(dtype=float)
    x = np.arange(len(y))
    if len(y) < 2 or np.mean(y) == 0:
        return 0.0
    slope, _ = np.polyfit(x, y, 1)
    return float(slope / np.mean(y))


def count_touches(series: pd.Series, level: float, tolerance_pct: float) -> int:
    """Count how many bars traded within `tolerance_pct` of `level`."""
    band = level * tolerance_pct
    return int(((series - level).abs() <= band).sum())
