"""Beyond-OHLCV ingestion: perpetual funding rates and open interest.

Funding is the single most important non-price series for a perp-trading desk —
it is literally a cash flow on the position and the basis of cash-and-carry /
funding-harvest edges. Open interest reveals positioning. Both are pulled via
CCXT where the venue supports them and stored as Parquet next to OHLCV.

Designed to degrade gracefully: a venue/symbol that doesn't expose these simply
returns an empty frame with a reason, never raising into the request path.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _exchange(name: str):
    import ccxt
    klass = getattr(ccxt, name, None)
    if klass is None:
        raise ValueError(f"unknown exchange '{name}'")
    return klass({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def fetch_funding_history(
    exchange: str, symbol: str, limit: int = 500,
) -> pd.DataFrame:
    """Funding-rate history → DataFrame[timestamp, funding_rate]. Empty on failure."""
    try:
        ex = _exchange(exchange)
        if not ex.has.get("fetchFundingRateHistory"):
            return pd.DataFrame(columns=["timestamp", "funding_rate"])
        rows = ex.fetch_funding_rate_history(symbol, limit=limit)
        if not rows:
            return pd.DataFrame(columns=["timestamp", "funding_rate"])
        df = pd.DataFrame([
            {"timestamp": pd.to_datetime(r["timestamp"], unit="ms", utc=True),
             "funding_rate": float(r.get("fundingRate") or 0.0)}
            for r in rows if r.get("timestamp")
        ])
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as exc:  # network/auth/symbol issues → empty, logged
        logger.warning("funding fetch failed %s %s: %s", exchange, symbol, exc)
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


def fetch_open_interest_history(
    exchange: str, symbol: str, timeframe: str = "1h", limit: int = 500,
) -> pd.DataFrame:
    """Open-interest history → DataFrame[timestamp, open_interest]. Empty on failure."""
    try:
        ex = _exchange(exchange)
        if not ex.has.get("fetchOpenInterestHistory"):
            return pd.DataFrame(columns=["timestamp", "open_interest"])
        rows = ex.fetch_open_interest_history(symbol, timeframe, limit=limit)
        if not rows:
            return pd.DataFrame(columns=["timestamp", "open_interest"])
        df = pd.DataFrame([
            {"timestamp": pd.to_datetime(r["timestamp"], unit="ms", utc=True),
             "open_interest": float(r.get("openInterestValue") or r.get("openInterestAmount") or 0.0)}
            for r in rows if r.get("timestamp")
        ])
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as exc:
        logger.warning("OI fetch failed %s %s: %s", exchange, symbol, exc)
        return pd.DataFrame(columns=["timestamp", "open_interest"])


def annualized_funding(funding_df: pd.DataFrame, periods_per_day: int = 3) -> float:
    """Mean funding rate annualized (perps fund ~3×/day by default)."""
    if funding_df.empty:
        return 0.0
    return float(funding_df["funding_rate"].mean() * periods_per_day * 365)


def save_funding(df: pd.DataFrame, exchange: str, symbol: str, out_dir: Path) -> Path | None:
    if df.empty:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{exchange}_{symbol}_funding.parquet"
    df.to_parquet(path, index=False)
    return path
