"""Shared OHLCV schema definitions."""

from __future__ import annotations

import unicodedata
from typing import Literal

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"]
TIMEFRAME_TO_PANDAS_FREQ = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "3h": "3h",
    "4h": "4h",
    "1d": "1D",
}
TIMEFRAME_TO_MILLISECONDS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "3h": 10_800_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def normalize_timeframe(timeframe: str) -> str:
    """Normalize CLI timeframe text by removing invisible formatting characters."""

    normalized = unicodedata.normalize("NFKC", timeframe).strip()
    return "".join(char for char in normalized if unicodedata.category(char) != "Cf")


def timeframe_to_pandas_freq(timeframe: str) -> str:
    """Convert an exchange timeframe to a pandas frequency string."""

    timeframe = normalize_timeframe(timeframe)
    if timeframe not in TIMEFRAME_TO_PANDAS_FREQ:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return TIMEFRAME_TO_PANDAS_FREQ[timeframe]


def timeframe_to_milliseconds(timeframe: str) -> int:
    """Convert a timeframe string into milliseconds."""

    timeframe = normalize_timeframe(timeframe)
    if timeframe not in TIMEFRAME_TO_MILLISECONDS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return TIMEFRAME_TO_MILLISECONDS[timeframe]
