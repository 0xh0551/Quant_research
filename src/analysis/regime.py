"""Market regime classification."""

from __future__ import annotations

import pandas as pd


def classify_regimes(data: pd.DataFrame, volatility_window: int = 30, trend_window: int = 100) -> pd.Series:
    """Classify candles into volatility/trend regimes."""

    returns = data["close"].pct_change()
    vol = returns.rolling(volatility_window).std()
    trend = data["close"] / data["close"].rolling(trend_window).mean() - 1
    high_vol = vol > vol.rolling(trend_window).median()
    bull = trend > 0
    labels = []
    for hv, is_bull in zip(high_vol.fillna(False), bull.fillna(False), strict=False):
        labels.append("high_vol_bull" if hv and is_bull else "high_vol_bear" if hv else "low_vol_bull" if is_bull else "low_vol_bear")
    return pd.Series(labels, index=data.index, name="regime")
