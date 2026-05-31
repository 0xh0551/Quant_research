"""Multi-strategy portfolio research."""

from __future__ import annotations

import pandas as pd


def combine_strategy_returns(strategy_returns: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.Series:
    """Combine strategy return streams into a weighted portfolio."""

    if strategy_returns.empty:
        raise ValueError("strategy_returns cannot be empty")
    if weights is None:
        return strategy_returns.mean(axis=1).rename("portfolio_return")
    weight_series = pd.Series(weights).reindex(strategy_returns.columns).fillna(0.0)
    if weight_series.sum() == 0:
        raise ValueError("weights must contain at least one positive allocation")
    return strategy_returns.mul(weight_series / weight_series.sum(), axis=1).sum(axis=1).rename("portfolio_return")
