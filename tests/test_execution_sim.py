from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig
from src.backtesting.execution_sim import (
    ExecutionParams,
    funding_pnl,
    run_realistic,
    simulate_fills,
)


def _bars(closes, lows=None, highs=None, volume=1e9):
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    lows = np.asarray(lows, dtype=float) if lows is not None else closes * 0.999
    highs = np.asarray(highs, dtype=float) if highs is not None else closes * 1.001
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes,
         "volume": np.full(n, volume)},
        index=idx,
    )


def test_maker_fills_only_on_penetration():
    # limit placed at close[0]=100; bar1 low=100 only *touches* → no fill;
    # bar2 low=99.5 trades through → fill.
    data = _bars([100, 100.5, 100.2, 100.1], lows=[99.9, 100.0, 99.5, 100.0])
    target = pd.Series([1.0, 1.0, 1.0, 1.0], index=data.index)
    params = ExecutionParams(style="maker", queue_penetration_bps=5.0, patience_bars=10)
    sim = simulate_fills(data, target, params)
    assert sim.position.iloc[1] == 0.0          # touched, not penetrated
    assert sim.position.iloc[2] == 1.0          # filled through
    assert sim.stats.n_maker_filled == 1
    assert sim.stats.n_fallback == 0


def test_maker_patience_falls_back_to_taker():
    # price runs away upward → buy limit never penetrated → taker after patience
    data = _bars([100, 101, 102, 103, 104], lows=[99.8, 100.8, 101.8, 102.8, 103.8])
    target = pd.Series(1.0, index=data.index)
    params = ExecutionParams(style="maker", patience_bars=2, taker_fallback=True,
                             maker_fee_bps=1.0, taker_fee_bps=5.0, taker_slippage_bps=2.0)
    sim = simulate_fills(data, target, params)
    assert sim.stats.n_fallback == 1
    assert sim.position.iloc[-1] == 1.0
    # paid the taker rate, not the maker rate
    assert sim.stats.effective_cost_bps == pytest.approx(7.0)


def test_maker_no_fallback_misses_the_trade():
    data = _bars([100, 101, 102, 103, 104], lows=[99.8, 100.8, 101.8, 102.8, 103.8])
    target = pd.Series(1.0, index=data.index)
    params = ExecutionParams(style="maker", patience_bars=2, taker_fallback=False)
    sim = simulate_fills(data, target, params)
    assert sim.stats.n_missed == 1
    assert sim.position.iloc[-1] == 0.0
    assert sim.stats.fill_ratio == 0.0


def test_participation_cap_causes_partial_fills():
    # tiny bar volume vs order notional → fill spread over several bars
    data = _bars([100] * 6, lows=[98] * 6, volume=10.0)  # bar usd = 1000
    target = pd.Series(1.0, index=data.index)
    params = ExecutionParams(
        style="maker", patience_bars=100, participation_cap=0.05,
        order_notional_usd=100.0,  # capacity = 0.05*1000/100 = 0.5 pos units/bar
    )
    sim = simulate_fills(data, target, params)
    assert sim.position.iloc[1] == pytest.approx(0.5)
    assert sim.position.iloc[2] == pytest.approx(1.0)
    assert sim.stats.n_partial == 1


def test_funding_sign_convention():
    idx = pd.date_range("2026-01-01", periods=4, freq="8h", tz="UTC")
    held_long = pd.Series(1.0, index=idx)
    held_short = pd.Series(-1.0, index=idx)
    rates = pd.Series(0.0001, index=idx)  # positive funding
    f_long = funding_pnl(idx, held_long, rates, hours_per_bar=8.0)
    f_short = funding_pnl(idx, held_short, rates, hours_per_bar=8.0)
    assert (f_long < 0).all()      # longs pay
    assert (f_short > 0).all()     # shorts receive
    assert f_long.iloc[0] == pytest.approx(-0.0001)


def test_run_realistic_reports_exec_metrics():
    rng = np.random.default_rng(3)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.004, 400))
    data = _bars(closes, lows=closes * 0.997, highs=closes * 1.003)
    target = pd.Series((np.arange(400) // 50) % 2, index=data.index, dtype=float)
    res = run_realistic(
        data, target, BacktestConfig(hours_per_bar=1.0),
        ExecutionParams(style="maker", patience_bars=3),
    )
    for key in ("exec_fill_ratio", "exec_maker_fill_rate", "exec_missed_rate",
                "exec_effective_cost_bps"):
        assert key in res.metrics
    assert 0.0 <= res.metrics["exec_fill_ratio"] <= 1.0
    assert len(res.equity) == 400
