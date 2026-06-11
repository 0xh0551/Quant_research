"""Tests for the statistical-rigor toolkit (PSR / DSR / bootstrap / PBO)."""

from __future__ import annotations

import numpy as np
from src.analysis.statistics import (
    bootstrap_metric_ci,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_significance,
)


def test_psr_in_unit_interval_and_monotone():
    p_low = probabilistic_sharpe_ratio(0.02, 500, 0.0, 3.0)
    p_high = probabilistic_sharpe_ratio(0.10, 500, 0.0, 3.0)
    assert 0.0 <= p_low <= 1.0
    assert p_high > p_low  # higher observed Sharpe → higher confidence


def test_deflated_sharpe_discounts_more_trials():
    # same observed Sharpe, more trials → lower deflated confidence
    dsr_few = deflated_sharpe_ratio(0.08, 1000, 0.0, 3.0, n_trials=2, sr_variance=0.01)
    dsr_many = deflated_sharpe_ratio(0.08, 1000, 0.0, 3.0, n_trials=200, sr_variance=0.01)
    assert dsr_many < dsr_few


def test_sharpe_significance_genuine_signal():
    rng = np.random.default_rng(0)
    good = rng.normal(0.001, 0.01, 3000)
    sig = sharpe_significance(good, bars_per_year=35040, n_trials=20, sr_variance=0.0004)
    assert sig.sharpe_ann > 0
    assert sig.psr > 0.9
    assert np.isfinite(sig.dsr)


def test_bootstrap_ci_brackets_point():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0005, 0.01, 1500)
    ci = bootstrap_metric_ci(r, bars_per_year=8760, n_boot=300)
    assert ci["sharpe"]["low"] <= ci["sharpe"]["point"] <= ci["sharpe"]["high"]
    assert ci["max_drawdown"]["low"] <= ci["max_drawdown"]["high"]


def test_pbo_low_for_one_genuine_signal_amid_noise():
    rng = np.random.default_rng(2)
    good = rng.normal(0.001, 0.01, 2000)
    noise = np.column_stack([rng.normal(0, 0.01, 2000) for _ in range(15)])
    matrix = np.column_stack([good, noise])
    res = probability_of_backtest_overfitting(matrix, n_splits=10)
    assert 0.0 <= res["pbo"] <= 1.0
    assert res["pbo"] < 0.5  # the real edge should not look overfit
