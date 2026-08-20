"""Order-level execution simulator — closing the backtest→live gap.

The vectorized engine assumes every intended position change fills instantly at
close ± a slippage haircut. Live trading doesn't work like that: maker orders
sit in the queue and often *never fill* (the hidden cost of maker strategies),
big orders eat through the book in slices, and perp funding is a real cash flow
that a flat per-bar approximation misrepresents. This module simulates those
mechanics bar-by-bar on OHLCV so a backtest can be run under the same execution
regime the live bot actually uses:

  • maker fills — a limit order at the decision close only fills when the next
    bars trade *through* it by ``queue_penetration_bps`` (being touched is not
    enough; the far side of the queue is ahead of you). Adverse selection is
    inherent: the fills you do get skew toward moves against you.
  • partial fills — per-bar fill volume is capped at ``participation_cap`` of
    bar volume, so a large order fills across bars (or doesn't finish).
  • patience + fallback — after ``patience_bars`` an unfilled remainder either
    crosses the spread as taker (fee + slippage) or is cancelled (the trade is
    simply missed, like a real missed entry).
  • funding — an actual funding-rate history (e.g. ``data/funding/*.parquet``)
    is accrued on the held position with correct sign: positive rate → longs
    pay, shorts receive.

`VectorizedBacktester.run` stays untouched for fast research scans; use
:func:`run_realistic` when execution realism matters (maker bots, sizing
studies, go-live decisions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestConfig, BacktestResult, calculate_metrics


@dataclass(frozen=True)
class ExecutionParams:
    """How orders reach the market."""

    style: str = "taker"                 # "taker" | "maker"
    maker_fee_bps: float = 1.0           # maker rebate venues → negative is allowed
    taker_fee_bps: float = 5.0
    taker_slippage_bps: float = 2.0
    # maker microstructure
    queue_penetration_bps: float = 1.0   # price must trade through the limit by this
    patience_bars: int = 3               # bars to wait before fallback/cancel
    taker_fallback: bool = True          # cross the spread when patience runs out
    # order sizing vs liquidity
    participation_cap: float = 0.05      # max share of a bar's volume one order may take
    order_notional_usd: float = 10_000.0 # assumed order size for participation math


@dataclass
class ExecutionStats:
    """What actually happened to the orders."""

    n_orders: int = 0
    n_maker_filled: int = 0              # fully filled passively
    n_partial: int = 0                   # took >1 bar to complete
    n_fallback: int = 0                  # finished as taker after patience
    n_missed: int = 0                    # cancelled unfilled — trade never happened
    intended_turnover: float = 0.0
    filled_turnover: float = 0.0
    fees_paid_bps_turnover: float = 0.0  # Σ |fill| × fee_bps (bps-weighted turnover)

    @property
    def fill_ratio(self) -> float:
        return self.filled_turnover / self.intended_turnover if self.intended_turnover else 1.0

    @property
    def maker_fill_rate(self) -> float:
        return self.n_maker_filled / self.n_orders if self.n_orders else 0.0

    @property
    def effective_cost_bps(self) -> float:
        return self.fees_paid_bps_turnover / self.filled_turnover if self.filled_turnover else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "exec_n_orders": float(self.n_orders),
            "exec_fill_ratio": round(float(self.fill_ratio), 4),
            "exec_maker_fill_rate": round(float(self.maker_fill_rate), 4),
            "exec_partial_rate": round(self.n_partial / self.n_orders, 4) if self.n_orders else 0.0,
            "exec_fallback_rate": round(self.n_fallback / self.n_orders, 4) if self.n_orders else 0.0,
            "exec_missed_rate": round(self.n_missed / self.n_orders, 4) if self.n_orders else 0.0,
            "exec_effective_cost_bps": round(float(self.effective_cost_bps), 3),
        }


@dataclass
class FillSimResult:
    position: pd.Series                  # position the market actually let us hold
    cost: pd.Series                      # per-bar transaction cost (return units)
    stats: ExecutionStats = field(default_factory=ExecutionStats)


def simulate_fills(
    data: pd.DataFrame, target_position: pd.Series, params: ExecutionParams,
) -> FillSimResult:
    """Bar-by-bar order simulation. ``target_position`` is the *desired*
    position decided at each bar's close (same convention as the engine:
    it acts from the next bar)."""
    n = len(data)
    close = data["close"].to_numpy(dtype=float)
    high = data["high"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    volume = (
        data["volume"].to_numpy(dtype=float)
        if "volume" in data.columns
        else np.full(n, np.inf)
    )
    target = np.asarray(target_position.reindex(data.index).ffill().fillna(0.0), dtype=float)

    pos = np.zeros(n)
    cost = np.zeros(n)
    stats = ExecutionStats()

    current = 0.0
    # open order state
    order_remaining = 0.0    # signed position units still to fill
    order_price = 0.0
    order_age = 0
    order_partial = False

    taker_cost = (params.taker_fee_bps + params.taker_slippage_bps) / 1e4
    maker_cost = params.maker_fee_bps / 1e4
    pen = params.queue_penetration_bps / 1e4

    def bar_capacity(i: int) -> float:
        """Max position units fillable this bar under the participation cap."""
        if not np.isfinite(volume[i]) or params.order_notional_usd <= 0:
            return np.inf
        bar_usd = volume[i] * close[i]
        return cast(float, params.participation_cap * bar_usd / params.order_notional_usd)

    for i in range(1, n):
        # 1) work any resting maker order against this bar
        if order_remaining != 0.0:
            side = np.sign(order_remaining)
            crossed = (
                low[i] <= order_price * (1 - pen)
                if side > 0
                else high[i] >= order_price * (1 + pen)
            )
            if crossed:
                fill = side * min(abs(order_remaining), bar_capacity(i))
                if fill != 0.0:
                    current += fill
                    cost[i] += abs(fill) * maker_cost
                    stats.filled_turnover += abs(fill)
                    stats.fees_paid_bps_turnover += abs(fill) * params.maker_fee_bps
                    order_remaining -= fill
                    if order_remaining != 0.0:
                        order_partial = True
            if order_remaining != 0.0:
                order_age += 1
                if order_age >= params.patience_bars:
                    if params.taker_fallback:
                        fill = order_remaining
                        current += fill
                        cost[i] += abs(fill) * taker_cost
                        stats.filled_turnover += abs(fill)
                        stats.fees_paid_bps_turnover += abs(fill) * (
                            params.taker_fee_bps + params.taker_slippage_bps
                        )
                        stats.n_fallback += 1
                    else:
                        stats.n_missed += 1
                    order_remaining = 0.0
            else:
                if order_partial:
                    stats.n_partial += 1
                else:
                    stats.n_maker_filled += 1

        # 2) a new decision at the previous close spawns an order
        #    (decision at close[i-1] → active from bar i, like execution_delay=1)
        desired = target[i - 1]
        if order_remaining == 0.0 and desired != current:
            delta = desired - current
            stats.n_orders += 1
            stats.intended_turnover += abs(delta)
            if params.style == "maker":
                order_remaining = delta
                order_price = close[i - 1]
                order_age = 0
                order_partial = False
                # try to work it immediately against this same bar
                side = np.sign(order_remaining)
                crossed = (
                    low[i] <= order_price * (1 - pen)
                    if side > 0
                    else high[i] >= order_price * (1 + pen)
                )
                if crossed:
                    fill = side * min(abs(order_remaining), bar_capacity(i))
                    if fill != 0.0:
                        current += fill
                        cost[i] += abs(fill) * maker_cost
                        stats.filled_turnover += abs(fill)
                        stats.fees_paid_bps_turnover += abs(fill) * params.maker_fee_bps
                        order_remaining -= fill
                        if order_remaining != 0.0:
                            order_partial = True
                if order_remaining == 0.0:
                    stats.n_maker_filled += 1
            else:
                # taker: fill now, but still respect per-bar participation
                fill = np.sign(delta) * min(abs(delta), bar_capacity(i))
                remainder = delta - fill
                current += fill
                cost[i] += abs(fill) * taker_cost
                stats.filled_turnover += abs(fill)
                stats.fees_paid_bps_turnover += abs(fill) * (
                    params.taker_fee_bps + params.taker_slippage_bps
                )
                if remainder != 0.0:
                    order_remaining = remainder    # finish over the next bars as taker
                    order_price = close[i]
                    order_age = 0
                    order_partial = True

        pos[i] = current

    return FillSimResult(
        position=pd.Series(pos, index=data.index),
        cost=pd.Series(cost, index=data.index),
        stats=stats,
    )


# ── funding from a real rate history ────────────────────────────────────────

def load_funding_series(
    exchange: str, symbol: str, funding_dir: Path | str = Path("data/funding"),
) -> pd.Series:
    """Funding-rate history saved by ``src.data.funding`` → Series indexed by ts."""
    path = Path(funding_dir) / f"{exchange}_{symbol}_funding.parquet"
    if not path.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_parquet(path)
        s = pd.Series(
            df["funding_rate"].astype(float).to_numpy(),
            index=pd.to_datetime(df["timestamp"], utc=True),
        )
        return s.sort_index()
    except Exception:
        return pd.Series(dtype=float)


def funding_pnl(
    index: pd.Index, held: pd.Series, funding_series: pd.Series, hours_per_bar: float,
) -> pd.Series:
    """Per-bar funding return on the held position from a real rate series.

    The prevailing 8h rate is forward-filled onto the bar grid and accrued
    pro-rata per bar. Positive rate: longs pay (−), shorts receive (+).
    """
    if funding_series.empty:
        return pd.Series(0.0, index=index)
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    rate = funding_series.reindex(
        funding_series.index.union(idx)
    ).ffill().reindex(idx).fillna(0.0)
    per_bar = rate.to_numpy() * (hours_per_bar / 8.0)
    return pd.Series(-held.to_numpy(dtype=float) * per_bar, index=index)


# ── the realistic runner ────────────────────────────────────────────────────

def run_realistic(
    data: pd.DataFrame,
    target_position: pd.Series,
    config: BacktestConfig | None = None,
    exec_params: ExecutionParams | None = None,
    funding_series: pd.Series | None = None,
) -> BacktestResult:
    """Backtest under simulated execution + (optionally) real funding.

    Returns a normal :class:`BacktestResult`; execution statistics are merged
    into ``result.metrics`` under ``exec_*`` keys so callers can gate on the
    backtest→live gap (fill ratio, missed-trade rate, effective cost).
    """
    cfg = config or BacktestConfig()
    params = exec_params or ExecutionParams()

    clip_min = -1.0 if cfg.allow_short else 0.0
    desired = target_position.reindex(data.index).fillna(0.0).clip(clip_min, 1.0)

    sim = simulate_fills(data, desired, params)
    close_returns = data["close"].pct_change().fillna(0.0)
    held = sim.position.shift(1).fillna(0.0)
    strategy_returns = held * close_returns - sim.cost

    if funding_series is not None and not funding_series.empty:
        strategy_returns = strategy_returns + funding_pnl(
            data.index, held, funding_series, cfg.hours_per_bar
        )
    elif cfg.apply_funding and cfg.funding_rate_8h:
        strategy_returns = strategy_returns - held * (
            cfg.funding_rate_8h * (cfg.hours_per_bar / 8.0)
        )

    equity = cfg.initial_capital * (1 + strategy_returns).cumprod()
    metrics = calculate_metrics(strategy_returns, equity, cfg.periods_per_year)
    metrics.update(sim.stats.as_dict())
    return BacktestResult(equity, strategy_returns, sim.position, metrics)
