from __future__ import annotations

import math

import numpy as np

from src.tracking.trial_ledger import TrialLedger


def _trial(dataset="ex_BTCUSDT_15m", strategy="ema_trend", direction="long",
           sr=0.02, n_obs=500, passed=False, **kw):
    return {"dataset": dataset, "strategy": strategy, "direction": direction,
            "sr_pb": sr, "n_obs": n_obs, "passed": passed,
            "exchange": "ex", "symbol": "BTCUSDT", "timeframe": "15m", **kw}


def test_retest_counts_once(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.db")
    assert ledger.record_trials("wf_scan", [_trial(sr=0.01)]) == 1
    # same hypothesis re-tested → no new unique, n_runs bumps, sr refreshes
    assert ledger.record_trials("wf_scan", [_trial(sr=0.03, passed=True)]) == 0
    s = ledger.family_stats("wf_scan")
    assert s["n_unique"] == 1
    assert s["n_runs_total"] == 2
    assert s["n_ever_passed"] == 1


def test_distinct_hypotheses_accumulate(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.db")
    rng = np.random.default_rng(1)
    trials = [
        _trial(dataset=f"ex_SYM{i}USDT_15m", strategy=s, direction=d, sr=float(rng.normal(0, 0.02)))
        for i in range(30) for s in ("ema_trend", "macd_cross") for d in ("long", "short")
    ]
    assert ledger.record_trials("wf_scan", trials) == 120
    s = ledger.family_stats("wf_scan")
    assert s["n_unique"] == 120
    assert s["sr_variance"] > 0


def test_cumulative_deflation_is_harsher(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.db")
    rng = np.random.default_rng(2)
    # small family → mild deflation
    ledger.record_trials("wf_scan", [
        _trial(dataset=f"a{i}", sr=float(rng.normal(0, 0.02))) for i in range(10)
    ])
    d_small = ledger.deflate("wf_scan", sr_pb=0.05, n_obs=500)
    # thousands more historical trials → the same candidate deflates harder
    ledger.record_trials("wf_scan", [
        _trial(dataset=f"b{i}", sr=float(rng.normal(0, 0.02))) for i in range(2000)
    ])
    d_big = ledger.deflate("wf_scan", sr_pb=0.05, n_obs=500)
    assert not math.isnan(d_small) and not math.isnan(d_big)
    assert d_big < d_small


def test_views(tmp_path):
    ledger = TrialLedger(tmp_path / "ledger.db")
    ledger.record_trials("wf_scan", [
        _trial(dataset="d1", strategy="ema_trend", passed=True),
        _trial(dataset="d2", strategy="ema_trend"),
        _trial(dataset="d3", strategy="macd_cross"),
    ])
    tl = ledger.timeline("wf_scan")
    assert tl and tl[-1]["cumulative"] == 3
    br = ledger.strategy_breakdown("wf_scan")
    ema = next(r for r in br if r["strategy"] == "ema_trend")
    assert ema["n_hypotheses"] == 2 and ema["n_ever_passed"] == 1
