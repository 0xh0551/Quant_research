"""Monte Carlo robustness analysis."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MonteCarloResult:
    """Monte Carlo terminal wealth and drawdown distributions."""

    terminal_return: pd.Series
    max_drawdown: pd.Series
    confidence_intervals: dict[str, float]


def run_monte_carlo(returns: pd.Series, simulations: int = 1000, seed: int = 42) -> MonteCarloResult:
    """Bootstrap strategy returns to estimate robustness distributions."""

    rng = np.random.default_rng(seed)
    clean = returns.dropna().to_numpy()
    if clean.size == 0:
        raise ValueError("returns must contain at least one observation")
    terminal: list[float] = []
    drawdowns: list[float] = []
    for _ in range(simulations):
        sampled = rng.choice(clean, size=clean.size, replace=True)
        equity = pd.Series((1 + sampled).cumprod())
        terminal.append(float(equity.iloc[-1] - 1))
        drawdowns.append(float((equity / equity.cummax() - 1).min()))
    terminal_series = pd.Series(terminal, name="terminal_return")
    drawdown_series = pd.Series(drawdowns, name="max_drawdown")
    return MonteCarloResult(terminal_series, drawdown_series, {
        "terminal_return_p05": float(terminal_series.quantile(0.05)),
        "terminal_return_p50": float(terminal_series.quantile(0.50)),
        "terminal_return_p95": float(terminal_series.quantile(0.95)),
        "max_drawdown_p05": float(drawdown_series.quantile(0.05)),
        "max_drawdown_p50": float(drawdown_series.quantile(0.50)),
    })
