"""Tests for the walk-forward scan and funding-aware backtest engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestConfig, VectorizedBacktester
from src.analysis.wf_scan import scan_dataset, write_manifest, _parse_dataset


def _trend_data(n: int = 12000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # روند ملایم + نویز تا استراتژی‌های روندی سیگنال تولید کنند
    drift = np.linspace(0, 0.6, n)
    noise = rng.normal(0, 0.01, n).cumsum()
    close = 100 * np.exp(drift / n * np.arange(n) * 0 + drift + noise)
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    ts = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": close, "high": high,
                         "low": low, "close": close, "volume": 1.0})


def test_parse_dataset():
    assert _parse_dataset("bybit_futures_BTCUSDT_15m") == ("bybit_futures", "BTCUSDT", "15m")
    assert _parse_dataset("nobitex_BTCUSDT_4h") == ("nobitex", "BTCUSDT", "4h")


def test_funding_reduces_returns_for_held_position():
    df = _trend_data(2000)
    target = pd.Series(1.0, index=df.index)  # always long
    base = VectorizedBacktester(BacktestConfig(apply_funding=False)).run(df, target)
    fund = VectorizedBacktester(BacktestConfig(
        apply_funding=True, funding_rate_8h=0.001, hours_per_bar=4.0)).run(df, target)
    # funding مثبت → long باید بازده کمتری بگیرد
    assert fund.equity.iloc[-1] < base.equity.iloc[-1]


def test_scan_runs_and_flags_passed():
    df = _trend_data(12000)
    results = scan_dataset(df, "synthetic_futures_BTCUSDT_4h",
                           strategies=["ema_trend", "donchian_breakout"],
                           train_size=3000, test_size=1000)
    assert results, "scan should produce results"
    # هر نتیجه فیلدهای کلیدی را دارد
    r = results[0]
    assert r.symbol == "BTCUSDT" and r.timeframe == "4h"
    assert isinstance(r.passed, bool)
    assert r.n_splits >= 1


def test_write_manifest(tmp_path):
    df = _trend_data(12000)
    results = scan_dataset(df, "synthetic_futures_BTCUSDT_4h",
                           strategies=["ema_trend"], train_size=3000, test_size=1000)
    out = write_manifest(results, tmp_path / "wf.json")
    assert out.exists()
    import json
    m = json.loads(out.read_text())
    assert m["version"] == 1
    assert "candidates" in m
    assert m["n_passed"] == len(m["candidates"])
