from __future__ import annotations

import pandas as pd
import pytest
from src.data import altdata


def test_term_structure_annualizes_dated_futures():
    now = pd.Timestamp.now(tz="UTC")
    expiry = now + pd.Timedelta(days=91)
    tenor = expiry.strftime("%y%m%d")
    premium = pd.DataFrame([
        {"symbol": "BTCUSDT", "mark": 100_000.0, "index": 100_000.0,
         "premium_bps": 0.0, "funding_rate": 0.0001, "next_funding_ts": 0},
        {"symbol": f"BTCUSDT_{tenor}", "mark": 102_500.0, "index": 100_000.0,
         "premium_bps": 250.0, "funding_rate": 0.0, "next_funding_ts": 0},
        {"symbol": "ETHUSDT", "mark": 4000.0, "index": 4000.0,
         "premium_bps": 0.0, "funding_rate": 0.0, "next_funding_ts": 0},
    ])
    term = altdata.term_structure(premium, "BTCUSDT")
    assert term[0]["tenor"] == "perp"
    # perp carry = funding annualized: 0.0001 × 3 × 365 = 10.95%
    assert term[0]["basis_ann_pct"] == pytest.approx(10.95, abs=0.01)
    dated = term[1]
    # 2.5% over ~91d → ~10% annualized
    assert dated["basis_ann_pct"] == pytest.approx(2.5 * 365 / 91, rel=0.05)
    # ETH row must not leak into the BTC structure
    assert all(not x.get("tenor", "").startswith("ETH") for x in term)


def test_append_parquet_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(altdata, "ALTDATA_DIR", tmp_path)
    ts = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    df1 = pd.DataFrame({"timestamp": ts, "dvol": [50.0, 51.0, 52.0]})
    altdata._append_parquet(df1, "dvol_T")
    # overlapping refresh: last two points repeat with revised values + one new
    ts2 = pd.date_range("2026-01-01 01:00", periods=3, freq="1h", tz="UTC")
    df2 = pd.DataFrame({"timestamp": ts2, "dvol": [51.5, 52.5, 53.0]})
    altdata._append_parquet(df2, "dvol_T")
    merged = pd.read_parquet(tmp_path / "dvol_T.parquet")
    assert len(merged) == 4                       # deduped on timestamp
    assert merged["dvol"].iloc[-1] == 53.0
    assert merged["dvol"].iloc[1] == 51.5         # keep="last" wins


def test_regime_hints():
    ts = pd.date_range("2026-01-01", periods=200, freq="1h", tz="UTC")
    dvol_high = pd.DataFrame({"timestamp": ts, "dvol": list(range(200))})
    ls_long = pd.DataFrame({"timestamp": ts[:5], "ls_ratio": [1, 1, 1, 1, 3.5]})
    term_back = [{"tenor": "perp", "basis_ann_pct": 5.0},
                 {"tenor": "260327", "basis_ann_pct": -2.0}]
    hints = altdata._regime_hints(dvol_high, ls_long, term_back)
    assert "dvol_high" in hints
    assert "crowd_long" in hints
    assert "backwardation" in hints

    dvol_low = pd.DataFrame({"timestamp": ts, "dvol": list(range(200, 0, -1))})
    hints2 = altdata._regime_hints(dvol_low, pd.DataFrame(), [])
    assert hints2 == ["dvol_low"]
