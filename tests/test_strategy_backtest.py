from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from src.backtesting import VectorizedBacktester
from src.strategies import build_strategy_signals
from src.strategies.rules import _stateful_long_signal, _stateful_signal


def test_strategy_backtest_produces_metrics(sample_ohlcv):
    signals = build_strategy_signals(sample_ohlcv, "ema_trend")
    result = VectorizedBacktester().run(sample_ohlcv, signals)
    assert len(result.equity) == len(sample_ohlcv)
    assert "sharpe" in result.metrics
    assert result.position.between(0, 1).all()


# ── Vectorized position state machines (2026-08-15) ───────────────────────────
# The loop-with-`.loc[idx] = ...` versions were the single largest source of
# pandas overhead in the nightly scan (~515k setitem calls per dataset). They
# were replaced by an ffill (long-only) and a numpy loop (long/short). Both must
# stay bit-identical to the original semantics, which these references encode.

def _long_reference(entry, exit_signal):
    position = pd.Series(0.0, index=entry.index)
    active = False
    for idx in entry.index:
        if bool(entry.loc[idx]):
            active = True
        elif bool(exit_signal.loc[idx]):
            active = False
        position.loc[idx] = float(active)
    return position


def _long_short_reference(long_entry, long_exit, short_entry, short_exit):
    position = pd.Series(0.0, index=long_entry.index)
    state = 0
    for idx in long_entry.index:
        if bool(long_entry.loc[idx]):
            state = 1
        elif bool(short_entry.loc[idx]):
            state = -1
        elif (state == 1 and bool(long_exit.loc[idx])) or (state == -1 and bool(short_exit.loc[idx])):
            state = 0
        position.loc[idx] = float(state)
    return position


@pytest.mark.parametrize("p", [0.0, 0.03, 0.25, 0.7, 1.0])
def test_stateful_signals_match_loop_reference(p):
    rng = np.random.default_rng(int(p * 100) + 1)
    n = 250
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    a, b, c, d = (pd.Series(rng.random(n) < p, index=idx) for _ in range(4))

    np.testing.assert_array_equal(
        _stateful_long_signal(a, b).to_numpy(), _long_reference(a, b).to_numpy())
    np.testing.assert_array_equal(
        _stateful_signal(a, b, c, d).to_numpy(),
        _long_short_reference(a, b, c, d).to_numpy())


def test_stateful_signal_exit_returns_to_flat_not_opposite():
    """Guards the 'never flat' bug the long/short state machine was written for."""
    idx = pd.date_range("2024-01-01", periods=5, freq="h")
    f = pd.Series([False] * 5, index=idx)
    long_entry = pd.Series([True, False, False, False, False], index=idx)
    long_exit = pd.Series([False, False, True, False, False], index=idx)
    pos = _stateful_signal(long_entry, long_exit, f, f)
    assert list(pos) == [1.0, 1.0, 0.0, 0.0, 0.0]
