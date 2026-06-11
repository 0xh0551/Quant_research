"""Position sizing — volatility targeting and fractional Kelly.

The scan tells you *what* to trade; sizing tells you *how much*. Two staples:

  • Volatility targeting — lever each strategy so its realized vol matches a
    target (e.g. 15%/yr), capping leverage. Equalizes risk contribution over time.
  • Fractional Kelly — bet a fraction of the growth-optimal Kelly leverage
    (full Kelly is too aggressive once estimation error is considered).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def vol_target_leverage(
    returns: pd.Series, target_vol_annual: float = 0.15,
    bars_per_year: int = 365, max_leverage: float = 3.0,
) -> float:
    """Constant leverage so the stream's annualized vol hits the target."""
    sd = float(np.asarray(returns, dtype=float).std(ddof=1))
    if sd <= 0:
        return 0.0
    realized_vol = sd * np.sqrt(bars_per_year)
    return float(min(target_vol_annual / realized_vol, max_leverage))


def vol_target_position(
    returns: pd.Series, target_vol_annual: float = 0.15,
    bars_per_year: int = 365, lookback: int = 60, max_leverage: float = 3.0,
) -> pd.Series:
    """Time-varying leverage from a rolling vol estimate (lagged to avoid leak)."""
    r = pd.Series(returns).astype(float)
    roll_vol = r.rolling(lookback, min_periods=max(5, lookback // 3)).std() * np.sqrt(bars_per_year)
    lev = (target_vol_annual / roll_vol).clip(upper=max_leverage).shift(1)
    return lev.fillna(0.0)


def fractional_kelly(
    returns: pd.Series, fraction: float = 0.5, bars_per_year: int = 365,
    max_leverage: float = 3.0,
) -> dict[str, float]:
    """Growth-optimal leverage f* = μ/σ² (per-bar), scaled by `fraction`."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 20:
        return {"full_kelly": 0.0, "fractional_kelly": 0.0, "fraction": fraction}
    mu, var = r.mean(), r.var(ddof=1)
    full = float(mu / var) if var > 0 else 0.0
    frac = float(np.clip(full * fraction, -max_leverage, max_leverage))
    return {
        "full_kelly": round(full, 4),
        "fractional_kelly": round(frac, 4),
        "fraction": fraction,
        "ann_growth_estimate": round(float(mu * frac * bars_per_year), 4),
    }
