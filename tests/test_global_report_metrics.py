from __future__ import annotations

import pandas as pd

from src.analysis.global_report import _exposure_stats, _trade_stats
from src.backtesting import BacktestConfig, VectorizedBacktester


def test_trade_stats_count_average_and_median_completed_and_open_trades():
    returns = pd.Series([0.0, 0.10, 0.05, -0.02, 0.03])
    position = pd.Series([0.0, 1.0, 1.0, 0.0, 1.0])

    stats = _trade_stats(returns, position)

    assert stats["trades_count"] == 2.0
    assert round(stats["avg_trade"], 6) == round(((1.10 * 1.05 * 0.98 - 1) + 0.03) / 2, 6)
    assert round(stats["median_trade"], 6) == round(((1.10 * 1.05 * 0.98 - 1) + 0.03) / 2, 6)


def test_exposure_uses_fraction_of_time_in_market():
    assert _exposure_stats(pd.Series([0.0, 1.0, 1.0, 0.0]))["exposure"] == 0.5


def test_backtester_spread_bps_adds_to_turnover_costs(sample_ohlcv):
    target = pd.Series(1.0, index=sample_ohlcv.index)
    no_spread = VectorizedBacktester(BacktestConfig(spread_bps=0)).run(sample_ohlcv, target)
    with_spread = VectorizedBacktester(BacktestConfig(spread_bps=5)).run(sample_ohlcv, target)

    assert with_spread.equity.iloc[-1] < no_spread.equity.iloc[-1]
