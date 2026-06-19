"""Tests for OHLCV-only money-flow detection (CMF + RVOL + OBV slope)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.tracking.money_flow import (
    apply_money_flow,
    money_flow_metrics,
    money_flow_multiplier,
    money_flow_score,
)


def _ohlcv(n, drift, vol_surge_tail=40, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(drift + rng.normal(0, 0.05, n))
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close - drift
    volume = rng.uniform(80, 120, n)
    volume[-vol_surge_tail:] *= 3.0  # recent surge so the signal isn't drowned out
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_insufficient_data_is_safe():
    out = money_flow_score(_ohlcv(10, 0.1))
    assert out["money_flow_score"] == 0
    assert out["reason"] == "insufficient_data"


def test_uptrend_with_volume_surge_is_inflow():
    out = money_flow_score(_ohlcv(200, drift=0.3, seed=1))
    assert out["direction"] == "inflow"
    assert out["money_flow_score"] > 20


def test_downtrend_with_volume_surge_is_outflow():
    out = money_flow_score(_ohlcv(200, drift=-0.3, seed=2))
    assert out["direction"] == "outflow"
    assert out["money_flow_score"] > 20


def test_flat_random_is_neutral():
    out = money_flow_score(_ohlcv(200, drift=0.0, vol_surge_tail=0, seed=3))
    assert out["direction"] == "neutral"


def test_metrics_shape():
    m = money_flow_metrics(_ohlcv(200, drift=0.2, seed=4))
    assert set(m) >= {"n", "cmf", "rvol", "obv_slope"}


def test_multiplier_bounded_and_neutral_is_noop():
    assert money_flow_multiplier(None) == 1.0
    assert money_flow_multiplier({"money_flow_score": 10, "direction": "inflow"}) == 1.0
    boosted = money_flow_multiplier({"money_flow_score": 100, "direction": "inflow"})
    demoted = money_flow_multiplier({"money_flow_score": 100, "direction": "outflow"})
    assert 1.0 < boosted <= 1.15
    assert 0.85 <= demoted < 1.0


def test_apply_money_flow_adjusts_in_place_and_audits():
    table = {"BTC": {"score": 50}, "ETH": {"score": 50}, "SOL": {"score": 50}}
    mf = {
        "top_inflow": [{"symbol": "BTCUSDT", "exchange": "bybit", "money_flow_score": 90, "direction": "inflow"}],
        "top_outflow": [{"symbol": "ETHUSDT", "exchange": "bybit", "money_flow_score": 90, "direction": "outflow"}],
    }
    audit = apply_money_flow(table, mf, quote="USDT")
    assert table["BTC"]["score"] > 50
    assert table["ETH"]["score"] < 50
    assert table["SOL"]["score"] == 50
    assert set(audit) == {"BTC", "ETH"}
