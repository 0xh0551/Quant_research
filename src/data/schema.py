"""Shared OHLCV schema definitions."""

from __future__ import annotations

from typing import Literal

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
Timeframe = Literal["1m", "5m", "1h", "1d"]


def timeframe_to_pandas_freq(timeframe: str) -> str:
    """Convert an exchange timeframe to a pandas frequency string."""

    mapping = {"1m": "1min", "5m": "5min", "1h": "1h", "1d": "1D"}
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def timeframe_to_milliseconds(timeframe: str) -> int:
    """Convert a timeframe string into milliseconds."""

    mapping = {"1m": 60_000, "5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]

