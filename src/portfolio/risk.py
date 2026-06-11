"""Risk overlays — drawdown control, regime gating, capacity/impact.

These sit on top of a sized strategy and cut exposure when conditions warrant:

  • drawdown_control — de-lever as the equity curve falls below its peak,
    re-lever as it recovers (a soft equity-curve stop).
  • regime_gate — only allow positions when a regime flag is "on".
  • capacity_estimate — how much capital a strategy can run before its own
    trading moves the market past the alpha (square-root impact model).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def drawdown_control(
    returns: pd.Series, max_drawdown: float = 0.20, floor: float = 0.2,
) -> pd.Series:
    """Leverage multiplier in [floor, 1] that shrinks as drawdown approaches the
    limit. Applied to next-bar position (uses only past equity → no lookahead)."""
    r = pd.Series(returns).astype(float).fillna(0.0)
    equity = (1.0 + r).cumprod()
    dd = equity / equity.cummax() - 1.0
    scale = (1.0 - (dd.abs() / max_drawdown)).clip(lower=floor, upper=1.0)
    return scale.shift(1).fillna(1.0)


def apply_drawdown_control(returns: pd.Series, **kw) -> pd.Series:
    """Return the de-levered return stream under drawdown control."""
    scale = drawdown_control(returns, **kw)
    return pd.Series(returns).astype(float).fillna(0.0) * scale


def regime_gate(position: pd.Series, regime_on: pd.Series) -> pd.Series:
    """Zero out positions when the (lagged) regime flag is off."""
    gate = pd.Series(regime_on).astype(bool).shift(1).fillna(False)
    return pd.Series(position).where(gate, 0.0)


def capacity_estimate(
    avg_daily_volume_usd: float, target_participation: float = 0.05,
    expected_edge_bps: float = 20.0, impact_coef: float = 0.1,
) -> dict[str, float]:
    """Square-root market-impact capacity: the capital at which impact (in bps)
    eats the expected per-trade edge.

    impact_bps ≈ impact_coef * sqrt(participation) * 1e4, with participation =
    order_notional / ADV. Solve for the notional where impact == edge.
    """
    if avg_daily_volume_usd <= 0 or expected_edge_bps <= 0:
        return {"max_notional_usd": 0.0, "participation_at_edge": 0.0}
    # participation where impact_bps == edge:  p* = (edge / (impact_coef*1e4))**2
    p_star = (expected_edge_bps / (impact_coef * 1e4)) ** 2
    p = min(p_star, target_participation)
    max_notional = p * avg_daily_volume_usd
    impact_bps = impact_coef * np.sqrt(p) * 1e4
    return {
        "max_notional_usd": round(float(max_notional), 2),
        "participation": round(float(p), 5),
        "impact_bps_at_capacity": round(float(impact_bps), 2),
        "edge_bps": expected_edge_bps,
    }
