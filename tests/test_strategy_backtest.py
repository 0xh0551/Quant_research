from __future__ import annotations

from src.backtesting import VectorizedBacktester
from src.strategies import build_strategy_signals


def test_strategy_backtest_produces_metrics(sample_ohlcv):
    signals = build_strategy_signals(sample_ohlcv, "ema_trend")
    result = VectorizedBacktester().run(sample_ohlcv, signals)
    assert len(result.equity) == len(sample_ohlcv)
    assert "sharpe" in result.metrics
    assert result.position.between(0, 1).all()
