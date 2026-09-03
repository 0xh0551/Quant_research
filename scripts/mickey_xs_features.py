#!/usr/bin/env python3
"""mickey_xs_features.py — گروه‌های فاکتورِ مقطعی (mode='xs') برای MickeyXSMN.

هر تابع «فاکتورِ خامِ per-asset» می‌سازد (کاملاً علّی/causal)؛ نرمال‌سازیِ مقطعی
(z-score per timestamp) در مرحلهٔ پنلِ popeye_xs انجام می‌شود، نه این‌جا.

گروه‌ها (هر کدام جداگانه قابلِ حذف برای ablation):
  mom   : مومنتومِ 7d و 30d با یک روز skip؛ بازگشتِ کوتاه‌مدتِ 1d/3d
  resid : مومنتومِ باقی‌مانده (بتا-تعدیل‌شده نسبت به BTC، بتای رولینگِ 30d) + خودِ بتا
  fund  : سطحِ فاندینگ، تغییرِ 24h، z نسبت به 30dِ خودش + پرچمِ دسترسی
  oi    : تغییرِ OI ی 24h، OI/حجم + پرچمِ دسترسی (Bybit فقط ۲۰۰ ساعتِ آخر را می‌دهد)
  vol   : وولِ محقق 30d، نسبتِ وولِ 1d/30d، شوکِ حجم (24h / میانگینِ 20d)، ATR%
  dist  : فاصله تا سقف/کفِ 30d
  ta    : هستهٔ کوچکِ TA (rsi_14, adx_14)

هم‌ترازیِ داده‌های جانبی (بدونِ نگاهِ به آینده): timestampِ کندل = زمانِ بازِ کندل؛
ویژگی‌های ردیفِ i در زمانِ بستنِ کندل (date+1h) محاسبه می‌شوند. فاندینگ/OI را با
as-of روی «timestamp ≤ date» (زمانِ باز) هم‌تراز می‌کنیم — یک ساعت محافظه‌کارانه‌تر
از حدِ لازم، تا تسویهٔ فاندینگِ دقیقاً روی مرزِ ساعت هرگز به‌عنوانِ «دانسته» نیاید.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from popeye_wf import _adx, _atr, _rsi  # noqa: E402

XS_GROUPS: tuple[str, ...] = ("mom", "resid", "fund", "oi", "vol", "dist", "ta")
FUND_DIRS = (ROOT / "data" / "funding_hist", ROOT / "data" / "funding")
OI_DIR = ROOT / "data" / "funding"
LIQUID_JSON = ROOT / "outputs" / "bybit_liquid_bases.json"
PROCESSED = ROOT / "data" / "processed"
# نمادهایی که در یک سبدِ مقطعیِ کریپتو معنا ندارند (فلز/سهامِ توکنی/مرجعِ بازار)
LIQUID_EXCLUDE = {"BTC", "PAXG", "XAUT", "XAG", "XAU", "USDC", "USDE"}
EPS = 1e-9
DAY = 24
FUND_FRESH_H = 9        # فاندینگ ۸ ساعته؛ کهنه‌تر از ۹h = «در دسترس نیست»
OI_FFILL_H = 3


def parse_groups(spec: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if spec is None or spec == "" or spec == "all":
        return XS_GROUPS
    items = spec if isinstance(spec, (list, tuple)) else [s.strip() for s in str(spec).split(",")]
    out = []
    for g in items:
        g = g.strip().lower()
        if not g:
            continue
        if g not in XS_GROUPS:
            raise ValueError(f"unknown xs group {g!r}; valid: {XS_GROUPS}")
        if g not in out:
            out.append(g)
    return tuple(out)


def is_flag_col(col: str) -> bool:
    """ستون‌های پرچمِ ۰/۱ که نباید z-score مقطعی بخورند."""
    return col.endswith("_avail")


def xs_norm_cols(feat_cols: list[str]) -> list[str]:
    return [c for c in feat_cols if not is_flag_col(c)]


# ── لودرهای دادهٔ جانبی ────────────────────────────────────────────────────────

def load_funding(base: str, venue: str = "bybit") -> pd.Series | None:
    """سری فاندینگ (index=timestamp UTC). data/funding_hist (بک‌فیل) + data/funding (کرون)."""
    parts = []
    for d in FUND_DIRS:
        f = d / f"{venue}_{base}USDT_funding.parquet"
        if f.exists():
            try:
                parts.append(pd.read_parquet(f)[["timestamp", "funding_rate"]])
            except Exception:
                continue
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    s = df.set_index("timestamp")["funding_rate"].astype(float)
    return s if len(s) else None


def load_oi(base: str, venue: str = "bybit") -> pd.Series | None:
    f = OI_DIR / f"{venue}_{base}USDT_oi_1h.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)[["timestamp", "open_interest"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    s = df.set_index("timestamp")["open_interest"].astype(float)
    return s if len(s) else None


def load_aux(base: str, venue: str = "bybit") -> dict:
    return {"funding": load_funding(base, venue), "oi": load_oi(base, venue)}


def align_asof(series: pd.Series | None, dates: pd.Series) -> pd.Series:
    """آخرین مقدارِ دانسته تا زمانِ بازِ کندل (timestamp ≤ date). NaN اگر هیچ."""
    idx = pd.RangeIndex(len(dates))
    if series is None or len(series) == 0:
        return pd.Series(np.nan, index=idx, dtype=float)
    # واحدهای زمانی ممکن است us (کندل) و ns (فاندینگ) باشند → هر دو به ns
    d_idx = pd.DatetimeIndex(pd.to_datetime(dates.values, utc=True)).as_unit("ns")
    s_idx = pd.DatetimeIndex(pd.to_datetime(series.index, utc=True)).as_unit("ns")
    left = pd.DataFrame({"date": d_idx, "_i": idx})
    right = pd.DataFrame({"date": s_idx, "val": series.values.astype(float),
                          "src_ts": s_idx}).sort_values("date")
    m = pd.merge_asof(left.sort_values("date"), right, on="date", direction="backward")
    m = m.sort_values("_i")
    out = pd.Series(m["val"].values, index=idx, dtype=float)
    out.attrs["src_ts"] = pd.Series(m["src_ts"].values, index=idx)
    return out


def _btc_r1(btc: pd.DataFrame | None, dates: pd.Series, index) -> pd.Series | None:
    if btc is None:
        return None
    bs = btc[["date", "close"]].drop_duplicates("date").set_index("date")["close"]
    bs.index = pd.DatetimeIndex(pd.to_datetime(bs.index, utc=True)).as_unit("ns")
    aligned = bs.reindex(pd.DatetimeIndex(pd.to_datetime(dates.values, utc=True)).as_unit("ns"))
    return pd.Series(aligned.pct_change().values, index=index)


def rolling_beta(r1: pd.Series, br1: pd.Series, w: int = 30 * DAY) -> pd.Series:
    cov = r1.rolling(w, min_periods=w // 2).cov(br1)
    var = br1.rolling(w, min_periods=w // 2).var()
    return (cov / (var + EPS)).clip(-3.0, 3.0)


# ── فاکتورها ───────────────────────────────────────────────────────────────────

def build_xs_features(df: pd.DataFrame, groups=None, *, btc: pd.DataFrame | None = None,
                      funding: pd.Series | None = None, oi: pd.Series | None = None,
                      ) -> pd.DataFrame:
    """فاکتورهای خامِ per-asset برای پنلِ مقطعی. همهٔ پنجره‌ها فقط گذشته را می‌بینند."""
    groups = parse_groups(groups)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    dates = df["date"] if "date" in df.columns else df["timestamp"]
    r1 = c.pct_change()
    feats = pd.DataFrame(index=df.index)

    if "mom" in groups:
        feats["mom_7d"] = c.shift(DAY) / (c.shift(DAY + 7 * DAY) + EPS) - 1.0
        feats["mom_30d"] = c.shift(DAY) / (c.shift(DAY + 30 * DAY) + EPS) - 1.0
        feats["rev_1d"] = c / (c.shift(DAY) + EPS) - 1.0
        feats["rev_3d"] = c / (c.shift(3 * DAY) + EPS) - 1.0

    if "resid" in groups:
        if btc is None:
            raise ValueError("xs group 'resid' needs btc OHLCV")
        br1 = _btc_r1(btc, dates, df.index)
        beta = rolling_beta(r1, br1)
        # بتای دانسته تا کندلِ قبل × بازدهِ BTC ی همین کندل → باقی‌ماندهٔ ساعتی
        resid = (r1 - beta.shift(1).fillna(0.0) * br1.fillna(0.0))
        feats["beta_30d"] = beta
        feats["resid_mom_7d"] = resid.rolling(7 * DAY).sum().shift(DAY)
        feats["resid_mom_30d"] = resid.rolling(30 * DAY).sum().shift(DAY)

    if "fund" in groups:
        f = align_asof(funding, dates)
        src = f.attrs.get("src_ts")
        if src is not None:
            d_idx = pd.DatetimeIndex(pd.to_datetime(dates.values, utc=True))
            s_idx = pd.DatetimeIndex(pd.to_datetime(src.values, utc=True))
            age_h = pd.Series(np.asarray((d_idx - s_idx) / pd.Timedelta(hours=1), dtype=float),
                              index=df.index)
        else:
            age_h = pd.Series(np.inf, index=df.index)
        avail = (f.notna() & (age_h <= FUND_FRESH_H)).astype(float)
        f = f.where(avail > 0)
        # سطح (annualised-ish بدونِ مقیاس: ×۳ در روز)، تغییرِ ۲۴h، z نسبت به ۳۰dِ خودش
        f_ff = f.ffill(limit=FUND_FRESH_H)
        feats["fund_level"] = f_ff.fillna(0.0)
        feats["fund_chg_24h"] = (f_ff - f_ff.shift(DAY)).fillna(0.0)
        mu30 = f_ff.rolling(30 * DAY, min_periods=10 * DAY).mean()
        sd30 = f_ff.rolling(30 * DAY, min_periods=10 * DAY).std()
        feats["fund_z_30d"] = ((f_ff - mu30) / (sd30 + 1e-6)).clip(-5, 5).fillna(0.0)
        feats["fund_avail"] = avail

    if "oi" in groups:
        o = align_asof(oi, dates).ffill(limit=OI_FFILL_H)
        o_prev = o.shift(DAY)
        avail = (o.notna() & o_prev.notna()).astype(float)
        feats["oi_chg_24h"] = (o / (o_prev + EPS) - 1.0).where(avail > 0).clip(-2, 2).fillna(0.0)
        dv24 = (v * c).rolling(DAY).sum()
        feats["oi_vol_ratio"] = np.log1p((o * c) / (dv24 + EPS)).where(o.notna()).fillna(0.0)
        feats["oi_avail"] = avail

    if "vol" in groups:
        rv30 = r1.rolling(30 * DAY, min_periods=15 * DAY).std()
        feats["rvol_30d"] = rv30
        feats["rvol_ratio_1d_30d"] = r1.rolling(DAY).std() / (rv30 + EPS)
        dv = v * c
        feats["vol_shock"] = dv.rolling(DAY).sum() / (dv.rolling(20 * DAY, min_periods=10 * DAY).mean() * DAY + EPS)
        feats["atr_pct"] = _atr(df, 14) / (c + EPS)

    if "dist" in groups:
        feats["dist_hi_30d"] = c / (h.rolling(30 * DAY, min_periods=15 * DAY).max() + EPS) - 1.0
        feats["dist_lo_30d"] = c / (l.rolling(30 * DAY, min_periods=15 * DAY).min() + EPS) - 1.0

    if "ta" in groups:
        feats["rsi_14"] = _rsi(c, 14)
        feats["adx_14"] = _adx(df, 14)

    return feats.replace([np.inf, -np.inf], np.nan)


# ── جهانِ نقد ───────────────────────────────────────────────────────────────────

def liquid_universe(n: int = 70, *, tf: str = "1h", venue: str = "bybit",
                    min_bars: int = 8760, max_stale_days: int = 3,
                    must_include: list[str] | None = None) -> list[str]:
    """top-n بر حسبِ حجمِ ۲۴h (outputs/bybit_liquid_bases.json) که ≥۱۲ ماه دیتای 1h دارند و
    هنوز لیست‌اند. فلز/سهامِ توکنی/BTC حذف. must_include (وایت‌لیستِ فعلی) همیشه هست."""
    vols = json.loads(LIQUID_JSON.read_text(encoding="utf-8")).get("vols", {}) if LIQUID_JSON.exists() else {}
    rows = []
    for f in sorted(PROCESSED.glob(f"{venue}_futures_*USDT_{tf}.parquet")):
        m = re.search(rf"{venue}_futures_(.+?)USDT_{tf}\.parquet$", f.name)
        if not m:
            continue
        b = m.group(1)
        if b in LIQUID_EXCLUDE:
            continue
        ts = pd.read_parquet(f, columns=["timestamp"])["timestamp"]
        if len(ts) < min_bars:
            continue
        rows.append((b, len(ts), pd.Timestamp(ts.max()), float(vols.get(b, 0.0))))
    if not rows:
        return list(must_include or [])
    d = pd.DataFrame(rows, columns=["base", "n", "end", "vol"])
    mx = d["end"].max()
    d = d[d["end"] >= mx - pd.Timedelta(days=max_stale_days)].sort_values("vol", ascending=False)
    out = d["base"].head(n).tolist()
    for b in (must_include or []):
        if b not in out and b in set(d["base"]):
            out.append(b)
    return out
