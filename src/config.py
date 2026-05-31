"""Typed project configuration models."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class MarketConfig(BaseModel):
    """Market data configuration for a single symbol and timeframe."""

    symbol: str = "BTCUSDT"
    exchange: str = "binance"
    market_type: str = "spot"
    timeframe: str = "1h"
    start: date = date(2020, 1, 1)
    end: date | None = None


class ProjectPaths(BaseModel):
    """Filesystem layout used by the research platform."""

    root: Path = Field(default_factory=lambda: Path.cwd())
    raw: Path = Path("data/raw")
    processed: Path = Path("data/processed")
    research: Path = Path("data/research")
    reports: Path = Path("reports")
    outputs: Path = Path("outputs")

    def resolve(self, path: Path) -> Path:
        """Resolve a project-relative path."""

        return path if path.is_absolute() else self.root / path

