from __future__ import annotations

import pandas as pd
import pytest
from src.analysis.attribution import decompose_trade


def _row(**kw):
    base = {
        "is_short": 0, "amount": 10.0, "leverage": 3.0,
        "open_rate": 100.0, "open_rate_requested": 100.0,
        "close_rate": 105.0, "close_rate_requested": 105.0,
        "fee_open_cost": 0.5, "fee_close_cost": 0.6,
        "fee_open": 0.0005, "fee_close": 0.0005, "open_trade_value": 1000.0,
        "funding_fees": 0.0, "close_profit_abs": 48.9,
    }
    base.update(kw)
    return pd.Series(base)


def test_clean_long_all_alpha():
    # perfect fills → intended == price pnl, residual ≈ 0
    c = decompose_trade(_row())
    assert c["intended"] == pytest.approx(50.0)
    assert c["entry_slip"] == pytest.approx(0.0)
    assert c["exit_slip"] == pytest.approx(0.0)
    assert c["fees"] == pytest.approx(1.1)
    assert c["residual"] == pytest.approx(48.9 - (50.0 - 1.1))


def test_slippage_signs_long():
    # long: filled entry above request = cost; exit filled below request = cost
    c = decompose_trade(_row(open_rate=100.2, close_rate=104.7))
    assert c["entry_slip"] == pytest.approx(2.0)    # (100.2−100)×10
    assert c["exit_slip"] == pytest.approx(3.0)     # (105−104.7)×10
    assert c["intended"] == pytest.approx(50.0)     # decision unchanged


def test_slippage_signs_short():
    # short entry: sell filled BELOW request = cost; exit buy ABOVE request = cost
    c = decompose_trade(_row(
        is_short=1, open_rate=99.8, open_rate_requested=100.0,
        close_rate=95.3, close_rate_requested=95.0,
    ))
    assert c["intended"] == pytest.approx(50.0)     # (100−95)×10 short
    assert c["entry_slip"] == pytest.approx(2.0)
    assert c["exit_slip"] == pytest.approx(3.0)


def test_funding_flows_into_model():
    c = decompose_trade(_row(funding_fees=-1.5, close_profit_abs=47.4))
    assert c["funding"] == pytest.approx(-1.5)
    # modeled = 50 − 1.1 − 1.5 = 47.4 → residual 0
    assert c["residual"] == pytest.approx(0.0, abs=1e-9)


def test_fee_fallback_from_rates():
    c = decompose_trade(_row(fee_open_cost=None, fee_close_cost=None))
    # 0.0005×1000 + 0.0005×105×10 = 0.5 + 0.525
    assert c["fees"] == pytest.approx(1.025)
