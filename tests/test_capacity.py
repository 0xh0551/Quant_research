from __future__ import annotations

import math

import pytest
from src.execution import capacity


def test_calibrate_k_uses_worst_side():
    book = {
        "buy_sweep_bps_500": 2.0, "sell_sweep_bps_500": 1.0,
        "buy_sweep_bps_2000": 4.0, "sell_sweep_bps_2000": 6.0,
    }
    k = capacity.calibrate_k(book)
    expected = (2.0 / math.sqrt(500) + 6.0 / math.sqrt(2000)) / 2.0
    assert k == pytest.approx(expected)


def test_calibrate_k_none_without_data():
    assert capacity.calibrate_k({}) is None


def test_impact_bps_regimes():
    # book regime only
    assert capacity.impact_bps(400, k_l2=0.5, adv=None) == pytest.approx(10.0)
    # participation regime only: 0.1 * sqrt(1e4/1e8) * 1e4 = 10
    assert capacity.impact_bps(10_000, k_l2=None, adv=1e8) == pytest.approx(10.0)
    # neither → infinite (unknown means unsafe, not free)
    assert capacity.impact_bps(1000, None, None) == float("inf")
    # both → the max binds
    both = capacity.impact_bps(10_000, k_l2=0.5, adv=1e8)
    assert both == pytest.approx(0.5 * math.sqrt(10_000))


def test_capacity_curve_finds_zero_crossing():
    # edge 50bps RT, fees 10bps, k=0.5 → net = 40 − 2*0.5*√N = 0 at N = 1600
    out = capacity.capacity_curve(50.0, 10.0, k_l2=0.5, adv=None)
    assert out["capacity_notional"] == pytest.approx(1600, rel=0.15)
    # half-edge point: impact_rt = 20 → √N = 20 → N = 400 (≈ capacity/4)
    assert out["half_edge_notional"] == pytest.approx(400, rel=0.2)
    assert all("net_edge_bps" in p for p in out["curve"])


def test_capacity_zero_when_edge_below_fees():
    out = capacity.capacity_curve(5.0, 11.0, k_l2=0.1, adv=1e8)
    assert out["capacity_notional"] == 0.0
    assert out["half_edge_notional"] == 0.0
