"""Feature registry for Bitcoin quantitative research."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureSpec:
    """Metadata for a generated feature."""

    name: str
    category: str
    description: str


class FeatureBuilder:
    """Generate a broad, documented OHLCV feature set."""

    def __init__(self) -> None:
        self.specs: list[FeatureSpec] = []

    def build(self, data: pd.DataFrame) -> pd.DataFrame:
        """Create trend, momentum, volatility, volume, structure, and statistical features."""

        frame = data.copy().sort_values("timestamp")
        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        volume = frame["volume"]
        features = pd.DataFrame(index=frame.index)

        for window in [5, 10, 20, 50, 100, 200]:
            features[f"sma_{window}"] = close.rolling(window).mean()
            features[f"ema_{window}"] = close.ewm(span=window, adjust=False).mean()
            features[f"close_sma_ratio_{window}"] = close / features[f"sma_{window}"] - 1
            self._add_specs(window)

        features["macd"] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        features["macd_signal"] = features["macd"].ewm(span=9, adjust=False).mean()
        features["macd_hist"] = features["macd"] - features["macd_signal"]
        features["rsi_14"] = _rsi(close, 14)
        for window in [5, 10, 20, 50]:
            features[f"roc_{window}"] = close.pct_change(window)
            features[f"realized_vol_{window}"] = close.pct_change().rolling(window).std() * np.sqrt(window)
            features[f"zscore_{window}"] = (close - close.rolling(window).mean()) / close.rolling(window).std()
            features[f"skew_{window}"] = close.pct_change().rolling(window).skew()
            features[f"kurt_{window}"] = close.pct_change().rolling(window).kurt()

        true_range = _true_range(high, low, close)
        features["atr_14"] = true_range.rolling(14).mean()
        middle = close.rolling(20).mean()
        band_std = close.rolling(20).std()
        features["bb_width_20"] = (4 * band_std) / middle
        features["bb_percent_b_20"] = (close - (middle - 2 * band_std)) / (4 * band_std)
        features["stoch_14"] = (close - low.rolling(14).min()) / (high.rolling(14).max() - low.rolling(14).min())
        features["obv"] = (np.sign(close.diff()).fillna(0) * volume).cumsum()
        money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        features["cmf_20"] = (money_flow_multiplier * volume).rolling(20).sum() / volume.rolling(20).sum()
        typical_price = (high + low + close) / 3
        vwap = (typical_price * volume).rolling(20).sum() / volume.rolling(20).sum()
        features["vwap_distance_20"] = close / vwap - 1
        features["distance_from_ath"] = close / close.cummax() - 1
        features["swing_high_20"] = (high == high.rolling(20, center=True).max()).astype(int)
        features["swing_low_20"] = (low == low.rolling(20, center=True).min()).astype(int)
        features["local_trend_strength_20"] = close.diff(20) / true_range.rolling(20).sum()
        features["adx_14"] = _adx(high, low, close, 14)
        return pd.concat([frame, features.replace([np.inf, -np.inf], np.nan)], axis=1)

    def _add_specs(self, window: int) -> None:
        """Register repeated trend feature metadata."""

        self.specs.extend(
            [
                FeatureSpec(f"sma_{window}", "trend", f"Simple moving average over {window} bars"),
                FeatureSpec(f"ema_{window}", "trend", f"Exponential moving average over {window} bars"),
                FeatureSpec(
                    f"close_sma_ratio_{window}",
                    "trend",
                    f"Relative distance between close and {window}-bar SMA",
                ),
            ]
        )


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = -delta.clip(upper=0).rolling(window).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    previous_close = close.shift(1)
    return pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = _true_range(high, low, close)
    plus_di = 100 * plus_dm.rolling(window).mean() / tr.rolling(window).mean()
    minus_di = 100 * minus_dm.rolling(window).mean() / tr.rolling(window).mean()
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window).mean()

