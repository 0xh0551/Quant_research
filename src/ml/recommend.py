"""Recommend which coins are best suited to a supervised-ML trading bot.

Mirror of the dashboard's ML-fitness heuristic (`_compute_ml_rl_fitness` in
src/web/app.py) packaged for pipeline use: ML shines where the series is
*predictable* — autocorrelation, Hurst away from 0.5, stable volatility — and
there are enough samples. Scores processed parquet datasets and ranks symbols.

Kept self-contained (no import from src.web.app) so cron scripts don't pull
FastAPI / module-level dashboard state.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.cross_exchange import parse_stem

DEFAULT_VENUES = ("bybit", "gate", "gateio", "gate_io", "okx")


def estimate_hurst(returns: np.ndarray) -> float:
    """R/S-based Hurst exponent, clipped to [0.1, 0.9]; 0.5 on failure."""
    try:
        lags = [l for l in [2, 4, 8, 16, 32, 64] if l < len(returns) // 4]
        if len(lags) < 2:
            return 0.5
        rs_values = []
        for lag in lags:
            sub = returns[: lag * (len(returns) // lag)]
            if len(sub) < lag:
                continue
            chunks = sub.reshape(-1, lag)
            rs_list = []
            for chunk in chunks:
                std = chunk.std()
                if std < 1e-12:
                    continue
                cum = np.cumsum(chunk - chunk.mean())
                rs_list.append((cum.max() - cum.min()) / std)
            if rs_list:
                rs_values.append(np.mean(rs_list))
        if len(rs_values) < 2:
            return 0.5
        log_lags = np.log(lags[: len(rs_values)])
        log_rs = np.log(rs_values)
        hurst = float(np.polyfit(log_lags, log_rs, 1)[0])
        return float(np.clip(hurst, 0.1, 0.9))
    except Exception:
        return 0.5


def ml_fitness(df: pd.DataFrame) -> dict:
    """ML-suitability score + components for one OHLCV dataset (0-100)."""
    close = df["close"]
    returns = close.pct_change().dropna()
    n = len(returns)
    if n < 500:
        return {"ml_score": 0, "n": n, "reason": "insufficient_data"}

    autocorr_1 = float(returns.autocorr(lag=1)) if n > 5 else 0.0
    hurst = estimate_hurst(returns.values)

    roll_std = returns.rolling(max(20, n // 10)).std().dropna()
    cv_std = float(roll_std.std() / (roll_std.mean() + 1e-9)) if len(roll_std) > 2 else 1.0
    stationarity = float(1.0 / (1.0 + cv_std))

    sample = min(n / 1000.0, 1.0)
    autocorr_score = float(min(abs(autocorr_1) * 5.0, 1.0))
    hurst_score = float(min(abs(hurst - 0.5) * 4.0, 1.0))

    score = int((
        sample * 0.25 +
        autocorr_score * 0.25 +
        stationarity * 0.25 +
        hurst_score * 0.25
    ) * 100)
    return {
        "ml_score": max(0, min(100, score)),
        "n": n,
        "autocorr_1": round(autocorr_1, 4),
        "hurst": round(hurst, 3),
        "stationarity": round(stationarity, 3),
    }


def recommend_ml_coins(
    processed_dir: Path, *, venues: tuple[str, ...] = DEFAULT_VENUES,
    timeframe: str = "15m", futures_only: bool = True, top_n: int = 10,
) -> dict:
    """Rank datasets on the requested venues by ML-suitability.

    Duplicate symbols across venues are collapsed to their best score (the
    structure stats are venue-agnostic enough to act as a proxy when the
    trading venue itself has no downloaded data, e.g. OKX).
    """
    venues_l = {v.lower() for v in venues}
    best: dict[str, dict] = {}
    for path in sorted(Path(processed_dir).glob("*.parquet")):
        info = parse_stem(path.stem)
        if info["timeframe"] != timeframe:
            continue
        if info["exchange"].lower() not in venues_l:
            continue
        if futures_only and info["market"] not in {"futures", "perp", "perpetual", "um", "cm"}:
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        fit = ml_fitness(df)
        if fit.get("ml_score", 0) <= 0:
            continue
        row = {"exchange": info["exchange"], "symbol": info["symbol"],
               "market": info["market"], **fit}
        cur = best.get(info["symbol"])
        if cur is None or row["ml_score"] > cur["ml_score"]:
            best[info["symbol"]] = row
    rows = sorted(best.values(), key=lambda r: r["ml_score"], reverse=True)
    return {
        "timeframe": timeframe,
        "venues": sorted(venues_l),
        "n_evaluated": len(rows),
        "recommendations": rows[:top_n],
    }
