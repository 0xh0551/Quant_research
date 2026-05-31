"""Parquet storage layer for reproducible research datasets."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.schema import OHLCV_COLUMNS


class ParquetDataStore:
    """Read, write, and incrementally merge OHLCV Parquet datasets."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, symbol: str, timeframe: str) -> Path:
        """Return the canonical Parquet path for a symbol/timeframe pair."""

        return self.root / f"{symbol}_{timeframe}.parquet"

    def read(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Read a dataset or return an empty OHLCV frame."""

        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        return pd.read_parquet(path)

    def write(self, data: pd.DataFrame, symbol: str, timeframe: str) -> Path:
        """Write a normalized OHLCV dataset to Parquet."""

        normalized = normalize_ohlcv(data)
        path = self.path_for(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_parquet(path, index=False)
        return path

    def merge_incremental(self, new_data: pd.DataFrame, symbol: str, timeframe: str) -> Path:
        """Merge new candles with existing data, removing duplicate timestamps."""

        existing = self.read(symbol, timeframe)
        merged = pd.concat([existing, new_data], ignore_index=True)
        return self.write(merged, symbol, timeframe)


def normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """Return a timestamp-sorted, de-duplicated OHLCV frame."""

    missing = set(OHLCV_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    frame = data.loc[:, OHLCV_COLUMNS].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    numeric_columns = ["open", "high", "low", "close", "volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=OHLCV_COLUMNS)
    frame = frame.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    return frame.reset_index(drop=True)

