"""تست‌های mode='xs' ی Mickey (2026-09-03): ستون‌های گروهی، علّی‌بودن، هم‌ترازیِ
فاندینگ/OI بدونِ نگاهِ به آینده، دست‌نخورده‌ماندنِ reduced، و معادل‌بودنِ apply_offset
با بریدنِ iloc[:-o] (پایهٔ گیتِ «میانه روی آفست‌ها»)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mickey_xs_features import (  # noqa: E402
    XS_GROUPS, build_xs_features, parse_groups, xs_norm_cols, align_asof,
)
from popeye_wf import build_features  # noqa: E402
import popeye_xs  # noqa: E402


def _ohlcv(n: int, seed: int, start="2025-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    open_ = np.roll(close, 1); open_[0] = close[0]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.004, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.004, n))
    vol = rng.lognormal(10, 0.3, n)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


@pytest.fixture()
def alt_btc():
    return _ohlcv(1500, 1), _ohlcv(1500, 2)


def _funding_for(df: pd.DataFrame) -> pd.Series:
    ts = pd.date_range(df["date"].iloc[0], df["date"].iloc[-1], freq="8h", tz="UTC")
    return pd.Series(np.linspace(-1e-4, 3e-4, len(ts)), index=ts)


def _oi_for(df: pd.DataFrame) -> pd.Series:
    ts = df["date"].iloc[200:]
    return pd.Series(1e6 + np.arange(len(ts)) * 1e3, index=pd.DatetimeIndex(ts))


def test_group_columns_and_flags(alt_btc):
    df, btc = alt_btc
    f = build_xs_features(df, "all", btc=btc, funding=_funding_for(df), oi=_oi_for(df))
    expect = {"mom_7d", "mom_30d", "rev_1d", "rev_3d", "beta_30d", "resid_mom_7d", "resid_mom_30d",
              "fund_level", "fund_chg_24h", "fund_z_30d", "fund_avail", "oi_chg_24h", "oi_vol_ratio",
              "oi_avail", "rvol_30d", "rvol_ratio_1d_30d", "vol_shock", "atr_pct",
              "dist_hi_30d", "dist_lo_30d", "rsi_14", "adx_14"}
    assert set(f.columns) == expect
    assert xs_norm_cols(list(f.columns)) == [c for c in f.columns if not c.endswith("_avail")]
    # پس از warm-up (31 روز) هیچ NaN ای نمی‌ماند
    assert f.iloc[800:].notna().all().all()
    # ablation: حذفِ یک گروه فقط ستون‌های همان گروه را می‌برد
    f2 = build_xs_features(df, "mom,vol", btc=btc)
    assert set(f2.columns) == {"mom_7d", "mom_30d", "rev_1d", "rev_3d",
                               "rvol_30d", "rvol_ratio_1d_30d", "vol_shock", "atr_pct"}
    assert parse_groups(None) == XS_GROUPS
    with pytest.raises(ValueError):
        parse_groups("mom,bogus")


def test_missing_aux_gives_zero_with_flag_off(alt_btc):
    df, btc = alt_btc
    f = build_xs_features(df, "fund,oi", btc=btc, funding=None, oi=None)
    assert (f["fund_avail"] == 0).all() and (f["oi_avail"] == 0).all()
    assert (f[["fund_level", "fund_chg_24h", "fund_z_30d", "oi_chg_24h", "oi_vol_ratio"]] == 0).all().all()


def test_features_are_causal(alt_btc):
    """بریدنِ آینده نباید ویژگی‌های گذشته را عوض کند (پنجره‌ها فقط گذشته را می‌بینند)."""
    df, btc = alt_btc
    fund, oi = _funding_for(df), _oi_for(df)
    full = build_xs_features(df, "all", btc=btc, funding=fund, oi=oi)
    cut = 1200
    part = build_xs_features(df.iloc[:cut].reset_index(drop=True), "all", btc=btc,
                             funding=fund, oi=oi)
    pd.testing.assert_frame_equal(full.iloc[:cut].reset_index(drop=True), part, check_dtype=False)
    # همین برای reduced (رفتارِ قبلی، دست‌نخورده)
    r_full = build_features(df, "reduced")
    r_part = build_features(df.iloc[:cut].reset_index(drop=True), "reduced")
    pd.testing.assert_frame_equal(r_full.iloc[:cut].reset_index(drop=True), r_part, check_dtype=False)
    assert list(r_full.columns) == ["ret_1", "ret_3", "ret_8", "rsi_14", "adx_14", "atr_pct", "hl_pct",
                                    "body_pct", "vol_ma_ratio", "ema_gap", "ema_dist_20",
                                    "bb_pct_20", "bb_width_20", "roc_10"]
    with pytest.raises(TypeError):
        build_features(df, "reduced", groups="mom")


def test_aux_alignment_no_lookahead(alt_btc):
    """مقدارِ فاندینگ/OI با timestamp=T فقط برای کندل‌های date ≥ T دیده می‌شود."""
    df, _ = alt_btc
    T = df["date"].iloc[500]
    s = pd.Series([0.0, 5.0], index=pd.DatetimeIndex([df["date"].iloc[100], T]))
    a = align_asof(s, df["date"])
    assert a.iloc[499] == 0.0 and a.iloc[500] == 5.0 and a.iloc[501] == 5.0
    assert np.isnan(a.iloc[99]) and a.iloc[100] == 0.0
    # فاندینگِ کهنه (>9h) → avail=0
    f = build_xs_features(df, "fund", funding=s)
    assert f["fund_avail"].iloc[500] == 1.0 and f["fund_avail"].iloc[520] == 0.0


def test_apply_offset_matches_iloc_truncation(alt_btc, monkeypatch):
    """گیتِ میانه-روی-آفست: apply_offset(panel, o) باید عیناً همان پنلِ ساخته‌شده از
    دیتای iloc[:-o] باشد (برای همهٔ هدف‌ها)."""
    alt, btc = alt_btc
    alt2 = _ohlcv(1500, 3)
    data = {"BTC": btc, "A": alt, "B": alt2}

    def _make(off):
        def _load(base, tf, venue="gate"):
            d = data[base].copy()
            return d.iloc[:-off] if off else d
        return _load

    for target in ("raw", "alpha", "beta_neutral", "rank"):
        monkeypatch.setattr(popeye_xs, "load_ohlcv", _make(0))
        full, cols = popeye_xs.build_panel(["A", "B"], "1h", "xs", 24, "x", target,
                                           groups="mom,resid,vol", keep_unlabeled=True)
        for off in (0, 48, 96):
            monkeypatch.setattr(popeye_xs, "load_ohlcv", _make(off))
            ref, _ = popeye_xs.build_panel(["A", "B"], "1h", "xs", 24, "x", target,
                                           groups="mom,resid,vol", keep_unlabeled=False)
            got = popeye_xs.apply_offset(full, off, 24)
            pd.testing.assert_frame_equal(
                got.drop(columns=["pos_from_end"]).reset_index(drop=True),
                ref.drop(columns=["pos_from_end"]).reset_index(drop=True), check_dtype=False)
