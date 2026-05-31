"""Binance data acquisition with bulk downloads and CCXT fallback."""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO

import pandas as pd

from src.data.schema import OHLCV_COLUMNS, timeframe_to_milliseconds
from src.data.storage import ParquetDataStore, normalize_ohlcv

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadRequest:
    """Parameters for a market data download."""

    symbol: str
    timeframe: str
    start: date
    end: date | None = None


class BinanceBulkDownloader:
    """Download public Binance monthly klines from data.binance.vision."""

    base_url = "https://data.binance.vision/data/spot/monthly/klines"

    def monthly_url(self, symbol: str, timeframe: str, year: int, month: int) -> str:
        """Build the monthly bulk zip URL for a symbol/timeframe."""

        month_text = f"{month:02d}"
        filename = f"{symbol}-{timeframe}-{year}-{month_text}.zip"
        return f"{self.base_url}/{symbol}/{timeframe}/{filename}"

    def download_month(self, symbol: str, timeframe: str, year: int, month: int) -> pd.DataFrame:
        """Download and parse one Binance monthly kline archive."""

        url = self.monthly_url(symbol, timeframe, year, month)
        LOGGER.info("Downloading Binance bulk data: %s", url)
        import requests

        response = requests.get(url, timeout=60)
        if response.status_code == 404:
            raise FileNotFoundError(url)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            csv_name = archive.namelist()[0]
            with archive.open(csv_name) as csv_file:
                return self._parse_bulk_csv(csv_file)

    def _parse_bulk_csv(self, csv_file: IO[bytes]) -> pd.DataFrame:
        """Parse Binance bulk CSV format into normalized OHLCV data."""

        columns = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "ignore",
        ]
        frame = pd.read_csv(csv_file, names=columns)
        frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        return normalize_ohlcv(frame.rename(columns={"timestamp": "timestamp"}))


class CCXTFallbackDownloader:
    """Fetch OHLCV candles through CCXT when bulk files are unavailable."""

    def __init__(self, exchange_id: str = "binance") -> None:
        import ccxt

        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})

    def fetch(self, request: DownloadRequest, limit: int = 1000) -> pd.DataFrame:
        """Fetch candles from CCXT using paginated requests."""

        since = int(datetime.combine(request.start, datetime.min.time(), UTC).timestamp() * 1000)
        end_date = request.end or datetime.now(UTC).date()
        end_ms = int(datetime.combine(end_date, datetime.min.time(), UTC).timestamp() * 1000)
        step = timeframe_to_milliseconds(request.timeframe)
        rows: list[list[float]] = []
        symbol = request.symbol.replace("USDT", "/USDT")
        while since < end_ms:
            batch = self.exchange.fetch_ohlcv(symbol, request.timeframe, since=since, limit=limit)
            if not batch:
                break
            rows.extend(batch)
            since = int(batch[-1][0]) + step
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return normalize_ohlcv(frame)


class DataIngestionPipeline:
    """Coordinate incremental data acquisition and Parquet persistence."""

    def __init__(
        self,
        store: ParquetDataStore,
        bulk_downloader: BinanceBulkDownloader | None = None,
        fallback_downloader: CCXTFallbackDownloader | None = None,
    ) -> None:
        self.store = store
        self.bulk_downloader = bulk_downloader or BinanceBulkDownloader()
        self.fallback_downloader = fallback_downloader

    def run(self, request: DownloadRequest) -> Path:
        """Download data and merge it into the configured Parquet store."""

        frames: list[pd.DataFrame] = []
        end = request.end or datetime.now(UTC).date()
        for year, month in _month_range(request.start, end):
            try:
                frames.append(self.bulk_downloader.download_month(request.symbol, request.timeframe, year, month))
            except FileNotFoundError:
                LOGGER.warning("Bulk file unavailable for %s-%02d; using fallback later", year, month)
        if not frames:
            if self.fallback_downloader is None:
                self.fallback_downloader = CCXTFallbackDownloader()
            frames.append(self.fallback_downloader.fetch(request))
        data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OHLCV_COLUMNS)
        return self.store.merge_incremental(data, request.symbol, request.timeframe)


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    """Return inclusive year/month pairs for a date range."""

    cursor = date(start.year, start.month, 1)
    final = date(end.year, end.month, 1)
    months: list[tuple[int, int]] = []
    while cursor <= final:
        months.append((cursor.year, cursor.month))
        next_month = cursor.month + 1
        next_year = cursor.year + (next_month == 13)
        cursor = date(next_year, 1 if next_month == 13 else next_month, 1)
    return months

