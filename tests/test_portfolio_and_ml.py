"""Tests for portfolio construction/sizing and ML rigor (labeling + purged CV)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.ml.cv import PurgedKFold, purged_walk_forward_splits
from src.ml.labeling import meta_labels, triple_barrier_labels
from src.portfolio import construction, risk, sizing


def _returns_frame(n=600, k=4, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 0.01, n)
    cols = {f"a{i}": 0.5 * base + rng.normal(0, 0.01, n) for i in range(k)}
    return pd.DataFrame(cols)


def test_weights_sum_to_one():
    R = _returns_frame()
    for method in ("hrp", "risk_parity", "inverse_vol", "equal_weight"):
        out = construction.build_portfolio(R, method)
        # weights are rounded to 4 dp for display, so allow a small tolerance
        assert abs(sum(out["weights"].values()) - 1.0) < 1e-3
        assert all(w >= -1e-9 for w in out["weights"].values())


def test_diversification_ratio_ge_one():
    out = construction.build_portfolio(_returns_frame(), "hrp")
    assert out["metrics"]["diversification_ratio"] >= 0.99


def test_vol_target_hits_target():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.02, 1000))
    lev = sizing.vol_target_leverage(r, target_vol_annual=0.15, bars_per_year=8760, max_leverage=10)
    realized = (r.std() * np.sqrt(8760)) * lev
    assert abs(realized - 0.15) < 1e-6 or lev == 10


def test_fractional_kelly_half_of_full():
    rng = np.random.default_rng(2)
    r = pd.Series(rng.normal(0.0008, 0.01, 1000))
    k = sizing.fractional_kelly(r, fraction=0.5, max_leverage=100)
    assert abs(k["fractional_kelly"] - 0.5 * k["full_kelly"]) < 1e-3  # 4-dp rounding


def test_drawdown_control_in_range():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(-0.001, 0.02, 500))
    scale = risk.drawdown_control(r, max_drawdown=0.2)
    assert scale.min() >= 0.2 - 1e-9 and scale.max() <= 1.0 + 1e-9


def test_triple_barrier_labels_and_t1():
    rng = np.random.default_rng(4)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 800)))
    tb = triple_barrier_labels(close, max_hold=20)
    assert set(tb["label"].unique()) <= {-1, 0, 1}
    assert (tb["t1"] >= tb.index).all()           # touch never before the event
    assert (tb["t1"] <= len(close) - 1).all()


def test_meta_labels_binary():
    side = np.array([1, -1, 1, 0])
    ret = np.array([0.01, 0.01, -0.01, 0.0])
    ml = meta_labels(side, ret)
    assert ml.tolist() == [1, 0, 0, 0]


def test_purged_kfold_no_overlap_with_test():
    n = 200
    t1 = np.arange(n) + 5  # each label ends 5 bars later
    cv = PurgedKFold(n_splits=5, t1=t1, embargo_pct=0.05)
    for tr, te in cv.split(np.zeros(n)):
        # no training index's label window overlaps the test span
        assert not (set(tr) & set(te))
        for i in tr:
            assert not (i <= te.max() and t1[i] >= te.min())


def test_walk_forward_train_precedes_test():
    splits = purged_walk_forward_splits(300, n_splits=4, embargo_pct=0.02)
    assert splits
    for tr, te in splits:
        assert tr.max() < te.min()
