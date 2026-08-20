"""Tests for the statistical-rigor toolkit (PSR / DSR / bootstrap / PBO)."""

from __future__ import annotations

import numpy as np
import pytest
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


def _pbo_reference(returns_matrix, n_splits=16):
    """Pre-2026-08-15 implementation: rebuild every IS/OOS partition by slicing.

    The fast path precomputes per-block count/sum/sum-of-squares and derives each
    partition's mean/std from those, which is what makes the nightly scan ~2x
    cheaper overall. It must stay numerically identical to this reference.
    """
    import itertools
    import math

    from scipy import stats as _stats

    M = np.asarray(returns_matrix, dtype=float)
    T, _N = M.shape
    s = n_splits - (n_splits % 2)
    block_idx = np.array_split(np.arange(T), s)
    blocks = list(range(s))

    def sr(sub):
        mu = sub.mean(axis=0)
        sd = sub.std(axis=0, ddof=1)
        sd[sd == 0] = np.nan
        return mu / sd

    logits = []
    for is_combo in itertools.combinations(blocks, s // 2):
        is_set = set(is_combo)
        is_perf = sr(M[np.concatenate([block_idx[b] for b in blocks if b in is_set])])
        oos_perf = sr(M[np.concatenate([block_idx[b] for b in blocks if b not in is_set])])
        if not np.isfinite(is_perf).any():
            continue
        best = int(np.nanargmax(is_perf))
        valid = np.isfinite(oos_perf)
        if valid.sum() < 2:
            continue
        rank = _stats.rankdata(oos_perf[valid])[np.where(valid)[0] == best]
        if rank.size == 0:
            continue
        w = min(max(float(rank[0] / (valid.sum() + 1)), 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1.0 - w)))
    arr = np.array(logits)
    return {"pbo": float((arr <= 0).mean()), "median_logit": float(np.median(arr)),
            "n_combinations": int(arr.size)}


@pytest.mark.parametrize("shape,loc,scale", [
    ((900, 8), 2e-4, 6e-3),      # typical stitched OOS returns
    ((300, 4), 0.0, 1e-2),       # short series
    ((1200, 20), 1e-5, 3e-3),    # many configs, near-zero drift
])
def test_pbo_block_precompute_matches_slicing_reference(shape, loc, scale):
    rng = np.random.default_rng(5)
    M = rng.normal(loc, scale, shape)
    fast = probability_of_backtest_overfitting(M, n_splits=10)
    ref = _pbo_reference(M, n_splits=10)
    assert fast["n_combinations"] == ref["n_combinations"]
    assert fast["pbo"] == pytest.approx(ref["pbo"], abs=1e-12)
    assert fast["median_logit"] == pytest.approx(ref["median_logit"], abs=1e-9)


def test_pbo_handles_constant_column():
    """A zero-variance config must yield NaN sr, not blow up the partition math."""
    rng = np.random.default_rng(6)
    M = np.hstack([rng.normal(0, 5e-3, (600, 5)), np.zeros((600, 1))])
    fast = probability_of_backtest_overfitting(M, n_splits=10)
    ref = _pbo_reference(M, n_splits=10)
    assert fast["pbo"] == pytest.approx(ref["pbo"], abs=1e-12)
