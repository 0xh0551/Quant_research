from __future__ import annotations

import pandas as pd
import pytest

from src.analysis import stress


def _pos(side="long", lev=5.0, stake=100.0, notional=500.0, bot="A", pair="X/USDT:USDT"):
    return {"bot": bot, "pair": pair, "base": "X", "side": side, "leverage": lev,
            "stake_usd": stake, "notional_usd": notional}


def test_stress_position_linear_loss():
    st = stress.stress_position(_pos(), market_move=-0.05, beta=1.0,
                                slippage_mult=1.0, funding_rate_8h=0.0,
                                funding_days=0.0, outage_hours=0.0)
    assert st.pnl == pytest.approx(-25.0)      # -5% × $500
    assert not st.liquidated


def test_stress_position_liquidation_caps_loss_at_stake():
    # 5x long, −25% move → past the ~19.9% liq threshold → lose the stake, not 125
    st = stress.stress_position(_pos(lev=5.0), market_move=-0.25, beta=1.0,
                                slippage_mult=1.0, funding_rate_8h=0.0,
                                funding_days=0.0, outage_hours=0.0)
    assert st.liquidated
    assert st.pnl == pytest.approx(-100.0)
    assert st.exit_cost == 0.0                 # nothing left to exit


def test_short_profits_in_crash_pays_in_meltup():
    crash = stress.stress_position(_pos(side="short"), -0.10, 1.0, 1.0, 0.0, 0.0, 0.0)
    assert crash.pnl == pytest.approx(50.0)
    melt = stress.stress_position(_pos(side="short"), 0.10, 1.0, 1.0, 0.0, 0.0, 0.0)
    assert melt.pnl == pytest.approx(-50.0)


def test_beta_scales_the_move():
    st = stress.stress_position(_pos(), -0.10, beta=2.0, slippage_mult=1.0,
                                funding_rate_8h=0.0, funding_days=0.0, outage_hours=0.0)
    assert st.pnl == pytest.approx(-100.0)     # 2β × −10% × $500


def test_measure_window_move():
    idx = pd.date_range("2022-11-01", periods=15, freq="1D", tz="UTC")
    closes = pd.Series([100] * 6 + [95, 80, 75, 78, 80, 82, 84, 85, 86], index=idx, dtype=float)
    out = stress.measure_window_move(closes, "2022-11-05", "2022-11-12")
    assert out is not None
    assert out["move"] == pytest.approx(-0.25)  # 100 → 75 inside the window
    # window outside data → None
    assert stress.measure_window_move(closes, "2020-01-01", "2020-01-05") is None


def test_run_scenario_aggregates_and_verdict():
    fleet = {
        "positions": [_pos(bot="A"), _pos(bot="B", side="short", notional=200.0, stake=40.0)],
        "per_asset": [{"base": "X", "beta_btc": 1.0}],
        "fleet": {"equity_usd": 1000.0},
    }
    scn = stress.Scenario("t", "shock", market_move=-0.10, slippage_mult=1.0)
    out = stress.run_scenario(scn, fleet, btc=pd.Series(dtype=float))
    assert out["fleet_pnl_usd"] == pytest.approx(-50.0 + 20.0)
    assert set(out["per_bot"]) == {"A", "B"}
    assert out["verdict"] == "ok"
    assert out["equity_after"] < 1000.0        # exit costs subtracted
