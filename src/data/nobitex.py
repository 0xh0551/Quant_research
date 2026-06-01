"""Nobitex OHLCV data downloader."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd

from src.data.schema import OHLCV_COLUMNS, timeframe_to_milliseconds
from src.data.storage import ParquetDataStore, normalize_ohlcv

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NobitexDownloadRequest:
    """Parameters for Nobitex public OHLCV download."""

    symbol: str
    timeframe: str
    start: date
    end: date | None = None


class NobitexOHLCVDownloader:
    """Download public Nobitex OHLCV candles from the UDF history endpoint."""

    base_url = "https://apiv2.nobitex.ir/market/udf/history"
    max_candles_per_request = 500

    def fetch(self, request: NobitexDownloadRequest) -> pd.DataFrame:
        """Fetch OHLCV candles using bounded time chunks."""

        import requests

        resolution = nobitex_resolution(request.timeframe)
        step_seconds = timeframe_to_milliseconds(request.timeframe) // 1000
        chunk_seconds = step_seconds * self.max_candles_per_request
        start_ts = int(datetime.combine(request.start, datetime.min.time(), UTC).timestamp())
        end_date = request.end or datetime.now(UTC).date()
        end_ts = int(datetime.combine(end_date, datetime.max.time(), UTC).timestamp())
        cursor = start_ts
        frames: list[pd.DataFrame] = []

        while cursor < end_ts:
            chunk_to = min(cursor + chunk_seconds, end_ts)
            params: dict[str, str | int] = {
                "symbol": request.symbol,
                "resolution": resolution,
                "from": cursor,
                "to": chunk_to,
            }
            LOGGER.info("Downloading Nobitex %s %s from=%s to=%s", request.symbol, request.timeframe, cursor, chunk_to)
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("s")
            if status == "ok":
                frames.append(self._parse_payload(payload))
            elif status == "no_data":
                LOGGER.info("No Nobitex data for %s", params)
            else:
                message = payload.get("errmsg", payload)
                raise ValueError(f"Nobitex OHLCV request failed: {message}")
            cursor = chunk_to + step_seconds
            sleep(0.05)

        if not frames:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        return normalize_ohlcv(pd.concat(frames, ignore_index=True))

    def _parse_payload(self, payload: dict[str, Any]) -> pd.DataFrame:
        """Parse Nobitex UDF arrays into normalized OHLCV data."""

        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(payload["t"], unit="s", utc=True),
                "open": payload["o"],
                "high": payload["h"],
                "low": payload["l"],
                "close": payload["c"],
                "volume": payload["v"],
            }
        )
        return normalize_ohlcv(frame)


class NobitexDataIngestionPipeline:
    """Coordinate Nobitex OHLCV acquisition and Parquet persistence."""

    def __init__(self, store: ParquetDataStore, downloader: NobitexOHLCVDownloader | None = None) -> None:
        self.store = store
        self.downloader = downloader or NobitexOHLCVDownloader()

    def run(self, request: NobitexDownloadRequest) -> Path:
        """Download Nobitex candles and merge them into the configured Parquet store."""

        data = self.downloader.fetch(request)
        return self.store.merge_incremental(data, request.symbol, request.timeframe)


def nobitex_resolution(timeframe: str) -> str:
    """Map internal timeframes to Nobitex UDF resolutions."""

    mapping = {"1m": "1", "5m": "5", "1h": "60", "1d": "D"}
    if timeframe not in mapping:
        raise ValueError(f"Unsupported Nobitex timeframe: {timeframe}")
    return mapping[timeframe]
