"""Vectorized backtesting engine with realistic execution assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    """Execution and portfolio assumptions."""

    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    spread_bps: float = 0.0
    execution_delay: int = 1
    periods_per_year: int = 365
    allow_short: bool = False  # enables -1 (short) positions for futures
    # ── realistic cost model (optional) ──────────────────────────────────
    # Override fee_bps with an explicit taker fee (entries/exits cross the book).
    taker_fee_bps: float | None = None
    # "fixed"  → flat slippage_bps per unit turnover (default; backward-compatible)
    # "dynamic"→ slippage scales with recent bar-range volatility and inverse
    #            liquidity (volume), i.e. trading is costlier in fast/thin markets.
    slippage_model: str = "fixed"
    impact_coef: float = 0.15          # share of avg bar-range charged as impact
    max_slippage_bps: float = 60.0     # cap so the dynamic model can't explode
    # ── Perpetual funding (futures) ──────────────────────────────────────
    # Funding is paid/received on the held notional every ~8h. With a positive
    # rate longs pay shorts (the common regime). We approximate it per-bar so
    # short and long carry costs become realistically asymmetric — important
    # because the noches bots trade perpetual futures, mostly short.
    apply_funding: bool = False
    funding_rate_8h: float = 0.0001   # ≈ 0.01% per 8h (typical neutral funding)
    hours_per_bar: float = 24.0       # set per timeframe (e.g. 0.25 for 15m, 1 for 1h)


@dataclass(frozen=True)
class BacktestResult:
    """Backtest equity curve, returns, positions, and metrics."""

    equity: pd.Series
    returns: pd.Series
    position: pd.Series
    metrics: dict[str, float]


class VectorizedBacktester:
    """Long/flat vectorized backtester for research signal evaluation."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, data: pd.DataFrame, target_position: pd.Series) -> BacktestResult:
        """Run a backtest using delayed execution and transaction costs."""

        close_returns = data["close"].pct_change().fillna(0.0)
        clip_min = -1.0 if self.config.allow_short else 0.0
        position = target_position.shift(self.config.execution_delay).fillna(0.0).clip(clip_min, 1.0)
        turnover = position.diff().abs().fillna(position.abs())
        fee = self.config.taker_fee_bps if self.config.taker_fee_bps is not None else self.config.fee_bps
        if self.config.slippage_model == "dynamic":
            slip_bps = self._dynamic_slippage_bps(data)
        else:
            slip_bps = self.config.slippage_bps
        cost_bps = fee + slip_bps + self.config.spread_bps
        costs = turnover * (cost_bps / 10_000)
        held = position.shift(1).fillna(0.0)
        strategy_returns = held * close_returns - costs
        if self.config.apply_funding and self.config.funding_rate_8h:
            # per-bar funding on the held position; long (+) pays, short (−) receives
            funding_per_bar = self.config.funding_rate_8h * (self.config.hours_per_bar / 8.0)
            strategy_returns = strategy_returns - held * funding_per_bar
        equity = self.config.initial_capital * (1 + strategy_returns).cumprod()
        return BacktestResult(equity, strategy_returns, position, calculate_metrics(strategy_returns, equity, self.config.periods_per_year))

    def _dynamic_slippage_bps(self, data: pd.DataFrame) -> pd.Series:
        """Per-bar slippage that scales with recent volatility and inverse
        liquidity. In fast or thin markets, crossing the book costs more."""
        close = data["close"].clip(lower=1e-9)
        bar_range = ((data["high"] - data["low"]) / close).fillna(0.0)
        range_bps = bar_range.rolling(20, min_periods=1).mean() * 10_000
        if "volume" in data.columns:
            vol = data["volume"].clip(lower=1e-9)
            liq = (vol.rolling(50, min_periods=1).mean() / vol).clip(0.3, 4.0).fillna(1.0)
        else:
            liq = 1.0
        dyn = self.config.slippage_bps + self.config.impact_coef * range_bps * liq
        return dyn.clip(upper=self.config.max_slippage_bps)

    def write_report(self, result: BacktestResult, output_path: Path) -> Path:
        """Write a Markdown performance report."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Backtest Report", "", "| Metric | Value |", "|---|---:|"]
        for key, value in result.metrics.items():
            lines.append(f"| {key} | {value:.6f} |")
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path


def calculate_metrics(returns: pd.Series, equity: pd.Series, periods_per_year: int) -> dict[str, float]:
    """Calculate standard quant performance metrics."""

    if len(equity) < 2:
        metric_names = [
            "total_return",
            "cagr",
            "sharpe",
            "sortino",
            "calmar",
            "profit_factor",
            "win_rate",
            "max_drawdown",
        ]
        return dict.fromkeys(metric_names, 0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    years = max(len(returns) / periods_per_year, 1 / periods_per_year)
    cagr = (1 + total_return) ** (1 / years) - 1
    volatility = returns.std() * np.sqrt(periods_per_year)
    sharpe = returns.mean() * periods_per_year / volatility if volatility else 0.0
    downside = returns[returns < 0].std() * np.sqrt(periods_per_year)
    sortino = returns.mean() * periods_per_year / downside if downside else 0.0
    drawdown = equity / equity.cummax() - 1
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown else 0.0
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "profit_factor": profit_factor,
        "win_rate": float((returns > 0).mean()),
        "max_drawdown": max_drawdown,
    }
