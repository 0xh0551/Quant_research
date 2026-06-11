"""Recommend which coins are best suited to an RL trading agent.

RL shines where there is *exploitable non-stationary structure* — frequent regime
switches, volatility clustering, fat tails and enough samples to learn from — and
where simple supervised prediction is weak (so a reactive policy beats a forecast).
This scores downloaded **15m futures** datasets on the requested venues (Bybit,
OKX, Gate) and ranks the best RL candidates.

Score (0–100): regime diversity, volatility clustering, reward density, sample
adequacy, and a bonus when one-step return autocorrelation is *low* (hard to
forecast → favour a policy over a predictor).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.analysis.cross_exchange import parse_stem

DEFAULT_VENUES = ("bybit", "okx", "gate", "gateio", "gate_io")


def rl_fitness(df: pd.DataFrame) -> dict:
    """RL-suitability score + components for one OHLCV dataset."""
    close = df["close"]
    returns = close.pct_change().dropna()
    n = len(returns)
    if n < 500:
        return {"rl_score": 0, "n": n, "reason": "insufficient_data"}

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    regime_changes = int(((ema20 > ema50).astype(int).diff().abs() > 0).sum())
    regime_diversity = float(min(regime_changes / max(n / 200.0, 1.0), 1.0))

    big_moves = float((returns.abs() > returns.std()).mean())          # reward density
    sq = returns ** 2
    vol_cluster = max(0.0, float(sq.autocorr(lag=1))) if n > 5 else 0.0
    autocorr1 = abs(float(returns.autocorr(lag=1))) if n > 5 else 0.0
    low_predictability = float(max(0.0, 1.0 - autocorr1 * 5.0))         # low AC → favour RL
    sample = min(n / 20000.0, 1.0)

    score = int((
        regime_diversity * 0.30 +
        vol_cluster * 0.20 +
        big_moves * 0.20 +
        low_predictability * 0.15 +
        sample * 0.15
    ) * 100)
    return {
        "rl_score": max(0, min(100, score)),
        "n": n,
        "regime_changes": regime_changes,
        "regime_diversity": round(regime_diversity, 3),
        "vol_clustering": round(vol_cluster, 3),
        "reward_density": round(big_moves, 3),
        "low_predictability": round(low_predictability, 3),
    }


def recommend_rl_coins(
    processed_dir: Path, *, venues: tuple[str, ...] = DEFAULT_VENUES,
    timeframe: str = "15m", futures_only: bool = True, top_n: int = 10,
) -> dict:
    """Rank 15m-futures datasets on the requested venues by RL-suitability."""
    venues_l = {v.lower() for v in venues}
    rows: list[dict] = []
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
        fit = rl_fitness(df)
        if fit.get("rl_score", 0) <= 0:
            continue
        rows.append({"exchange": info["exchange"], "symbol": info["symbol"],
                     "market": info["market"], **fit})
    rows.sort(key=lambda r: r["rl_score"], reverse=True)
    return {
        "timeframe": timeframe,
        "venues": sorted(venues_l),
        "n_evaluated": len(rows),
        "recommendations": rows[:top_n],
    }
