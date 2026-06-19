#!/usr/bin/env python3
"""Walk-forward validation for Popeye's μ/α regressor (leakage-free, cost-aware).

چرا این فایل: بات زنده روی هر بازآموزش train IC≈+0.96 / eval IC منفی می‌داد
(overfit شدید: ~۵۰۰ ویژگی روی ~۹۵۰ ردیف). این harness همان هدفِ μ و همان خانوادهٔ
ویژگی‌های PopeyeML را روی دادهٔ واقعیِ Gate بازسازی می‌کند و با walk-forwardِ
purge+embargo (López de Prado، از src/ml/cv.py) صادقانه می‌سنجد:

  ▸ آیا μ خارج‌از‌نمونه (OOS) قابل‌پیش‌بینی است؟  → IC پیرسون/اسپیرمن هر fold
  ▸ آیا بعدِ هزینه پول درمی‌آورد؟  → Sharpe خالصِ یک استراتژیِ z-gate روی μ̂ـِ OOS

هدفِ μ دقیقاً مطابق PopeyeML.set_freqai_targets:
  بازده آتیِ افق h  →  بازار-خنثی (حذفِ بتای trailing نسبت‌به‌BTC)  →  مقیاس‌شده با
  نوسانِ افق (کمیتِ شبه-شارپ)، clip ±4.

استفاده:
  .venv/bin/python scripts/popeye_wf.py --pair ETH --tf 1h --features reduced
  .venv/bin/python scripts/popeye_wf.py --pair ETH,HYPE,WLD,ZEC --features full --train-min 1080
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.cv import purged_walk_forward_splits  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


# ── داده ──────────────────────────────────────────────────────────────────────

def load_ohlcv(base: str, tf: str, venue: str = "gate") -> pd.DataFrame:
    f = PROCESSED / f"{venue}_futures_{base}USDT_{tf}.parquet"
    if not f.exists():
        raise FileNotFoundError(f)
    df = pd.read_parquet(f)
    df = df.rename(columns={"timestamp": "date"}).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


# ── ویژگی‌ها (همان خانوادهٔ PopeyeML) ──────────────────────────────────────────

def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / (dn + 1e-12)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _adx(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean() + 1e-12
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-12)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def build_features(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """mode='reduced' → ~14 ویژگیِ هسته‌ای؛ mode='full' → بازتولیدِ انفجارِ FreqAI
    (دوره‌های متعدد × shifted candles) برای نشان‌دادنِ overfit."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    feats = pd.DataFrame(index=df.index)

    # هستهٔ مشترک
    feats["ret_1"] = c.pct_change()
    feats["ret_3"] = c.pct_change(3)
    feats["ret_8"] = c.pct_change(8)
    feats["rsi_14"] = _rsi(c, 14)
    feats["adx_14"] = _adx(df, 14)
    feats["atr_pct"] = _atr(df, 14) / (c + 1e-9)
    feats["hl_pct"] = (h - l) / (c + 1e-9)
    feats["body_pct"] = (c - df["open"]).abs() / (c + 1e-9)
    feats["vol_ma_ratio"] = v / (v.rolling(20).mean() + 1e-9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    feats["ema_gap"] = (ema12 - ema50) / (ema50 + 1e-9)
    feats["ema_dist_20"] = (c - c.ewm(span=20, adjust=False).mean()) / (c + 1e-9)
    bbmid = c.rolling(20).mean()
    bbstd = c.rolling(20).std()
    feats["bb_pct_20"] = (c - (bbmid - 2 * bbstd)) / (4 * bbstd + 1e-9)
    feats["bb_width_20"] = (4 * bbstd) / (c + 1e-9)
    feats["roc_10"] = c.pct_change(10)

    if mode == "reduced":
        return feats

    # full: دوره‌های متعدد + shifted candles → انفجارِ بُعد (مثل FreqAI زنده)
    for p in (10, 20, 50):
        feats[f"rsi_{p}"] = _rsi(c, p)
        feats[f"adx_{p}"] = _adx(df, p)
        feats[f"roc_{p}"] = c.pct_change(p)
        feats[f"ema_dist_{p}"] = (c - c.ewm(span=p, adjust=False).mean()) / (c + 1e-9)
        m = c.rolling(p).mean()
        s = c.rolling(p).std()
        feats[f"bb_pct_{p}"] = (c - (m - 2 * s)) / (4 * s + 1e-9)
        feats[f"cci_{p}"] = (c - m) / (0.015 * (c - m).abs().rolling(p).mean() + 1e-9)
    base_cols = list(feats.columns)
    for sh in (1, 2):
        for col in base_cols:
            feats[f"{col}_t-{sh}"] = feats[col].shift(sh)
    return feats


# ── هدفِ μ/α (دقیقاً مطابق PopeyeML.set_freqai_targets) ─────────────────────────

def build_mu_target(df: pd.DataFrame, btc: pd.DataFrame, h: int) -> pd.Series:
    eps = 1e-9
    close = df["close"]
    r1 = close.pct_change()
    r_fwd = close.shift(-h) / close - 1.0

    # هم‌ترازیِ BTC با تاریخِ جفت
    bs = btc[["date", "close"]].drop_duplicates("date").set_index("date")["close"]
    aligned = bs.reindex(df["date"].values)
    br1 = pd.Series(aligned.pct_change().values, index=df.index)

    if br1.notna().sum() > 50:
        br_fwd = (1.0 + br1).shift(-1).rolling(h).apply(np.prod, raw=True) - 1.0
        w = max(50, 4 * h)
        cov = r1.rolling(w).cov(br1)
        var = br1.rolling(w).var()
        beta = (cov / (var + eps)).clip(-3.0, 3.0).fillna(0.0)
        r_alpha = r_fwd - beta * br_fwd.fillna(0.0)
    else:
        r_alpha = r_fwd

    vol_h = r1.rolling(h).std() * math.sqrt(h)
    mu = (r_alpha / (vol_h + eps)).clip(-4.0, 4.0)
    return mu


# ── متریک‌ها ──────────────────────────────────────────────────────────────────

def _ic(pred: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    """(pearson, spearman) IC؛ NaN-safe."""
    m = np.isfinite(pred) & np.isfinite(actual)
    if m.sum() < 10:
        return float("nan"), float("nan")
    p, a = pred[m], actual[m]
    pear = np.corrcoef(p, a)[0, 1] if p.std() > 0 and a.std() > 0 else float("nan")
    pr = pd.Series(p).rank().values
    ar = pd.Series(a).rank().values
    spear = np.corrcoef(pr, ar)[0, 1] if pr.std() > 0 and ar.std() > 0 else float("nan")
    return float(pear), float(spear)


# ── walk-forward ──────────────────────────────────────────────────────────────

def run_wf(base: str, tf: str, mode: str, *, train_min: int, n_splits: int,
           depth: int, horizon: int, z_thr: float, cost: float,
           n_estimators: int, lr: float, min_child: int) -> dict:
    from xgboost import XGBRegressor

    df = load_ohlcv(base, tf)
    btc = load_ohlcv("BTC", tf)
    feats = build_features(df, mode)
    mu = build_mu_target(df, btc, horizon)

    # ردیف‌های معتبر برای آموزش: ویژگی کامل + لیبلِ آینده موجود (h کندلِ آخر حذف)
    X = feats.copy()
    y = mu.copy()
    valid = X.notna().all(axis=1) & y.notna()
    # آخرین h ردیف لیبلِ آینده ندارند
    valid.iloc[-horizon:] = False

    idx_all = np.where(valid.values)[0]
    if len(idx_all) < train_min + n_splits * 50:
        return {"base": base, "error": f"insufficient rows ({len(idx_all)})"}

    Xv = X.values
    yv = y.values
    # forward 1-bar alpha-return برای تستِ اقتصادی (واقعیِ بعدِ سیگنال)
    fwd1 = (df["close"].shift(-1) / df["close"] - 1.0).values

    # t1 = پایانِ پنجرهٔ لیبل (i+h) برای purge
    t1 = np.minimum(np.arange(len(df)) + horizon, len(df) - 1)

    splits = purged_walk_forward_splits(len(df), t1=t1, n_splits=n_splits, embargo_pct=0.01)

    close = df["close"].values
    fold_rows = []
    oos_pred, oos_actual = [], []
    oos_idx, oos_z = [], []          # برای بک‌تستِ غیرهم‌پوشان
    for k, (tr_idx, te_idx) in enumerate(splits):
        tr = tr_idx[np.isin(tr_idx, idx_all)]
        te = te_idx[np.isin(te_idx, idx_all)]
        if len(tr) < train_min or len(te) < 30:
            continue
        model = XGBRegressor(
            objective="reg:pseudohubererror", n_estimators=n_estimators,
            learning_rate=lr, max_depth=depth, min_child_weight=min_child,
            subsample=0.8, colsample_bytree=0.7, reg_lambda=2.0, reg_alpha=0.5,
            gamma=0.1, tree_method="hist", n_jobs=-1, verbosity=0)
        model.fit(Xv[tr], yv[tr])
        ptr = model.predict(Xv[tr])
        pte = model.predict(Xv[te])
        ic_tr = _ic(ptr, yv[tr])
        ic_te = _ic(pte, yv[te])

        # z-gate روی μ̂ـِ OOS (z با آمارِ همان fold؛ هدف ~۱std است)
        mu_mean, mu_std = pte.mean(), pte.std() + 1e-9
        z = (pte - mu_mean) / mu_std

        fold_rows.append({
            "fold": k, "n_tr": len(tr), "n_te": len(te),
            "ic_tr_p": ic_tr[0], "ic_te_p": ic_te[0], "ic_te_s": ic_te[1],
        })
        oos_pred.append(pte); oos_actual.append(yv[te])
        oos_idx.append(te); oos_z.append(z)

    if not fold_rows:
        return {"base": base, "error": "no usable folds"}

    fr = pd.DataFrame(fold_rows)
    allpred = np.concatenate(oos_pred); allact = np.concatenate(oos_actual)
    ic_all = _ic(allpred, allact)

    # تستِ اقتصادی: نگه‌داریِ غیرهم‌پوشانِ h کندلی، کارمزدِ رفت‌وبرگشت یک‌بار/ترید.
    # بازده روی افقِ واقعیِ سیگنال (h کندل)، نه ۱-کندلی.
    bt = (pd.DataFrame({"idx": np.concatenate(oos_idx), "z": np.concatenate(oos_z)})
          .sort_values("idx").reset_index(drop=True))
    rets = []
    next_free = -1
    for _, row in bt.iterrows():
        i = int(row["idx"]); zz = row["z"]
        if i < next_free or abs(zz) < z_thr or i + horizon >= len(close):
            continue
        side = 1.0 if zz > 0 else -1.0
        r = side * (close[i + horizon] / close[i] - 1.0) - cost
        rets.append(r)
        next_free = i + horizon
    rets = np.asarray(rets)
    n_tr = len(rets)
    # هر ترید h کندل طول می‌کشد → تریدِ مستقل در سال ≈ bars_per_year/h
    bars_yr = {"1h": 8760, "4h": 2190, "15m": 35040}.get(tf, 8760)
    ann = math.sqrt(bars_yr / horizon)
    sh_net = float(rets.mean() / (rets.std() + 1e-12) * ann) if n_tr > 20 else float("nan")
    hit = float((rets > 0).mean()) if n_tr else float("nan")
    avg_ret = float(rets.mean()) if n_tr else float("nan")

    return {
        "base": base, "tf": tf, "mode": mode, "n_feats": feats.shape[1],
        "folds": len(fr),
        "ic_te_p_mean": round(float(fr["ic_te_p"].mean()), 3),
        "ic_te_s_mean": round(float(fr["ic_te_s"].mean()), 3),
        "ic_tr_p_mean": round(float(fr["ic_tr_p"].mean()), 3),
        "pct_folds_pos": round(float((fr["ic_te_p"] > 0).mean()), 2),
        "ic_pooled_p": round(ic_all[0], 3),
        "net_sharpe": round(sh_net, 2),
        "hit_rate": round(hit, 3),
        "avg_ret": round(avg_ret, 4),
        "n_trades": n_tr,
        "_fr": fr,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="ETH", help="کاما-جدا: ETH,HYPE,WLD,ZEC")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--features", choices=["reduced", "full"], default="reduced")
    ap.add_argument("--train-min", type=int, default=1080,
                    help="حداقل ردیفِ آموزش هر fold (live=45d≈1080 @1h)")
    ap.add_argument("--n-splits", type=int, default=8)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--z-thr", type=float, default=1.4)
    ap.add_argument("--cost", type=float, default=0.0018)
    ap.add_argument("--n-estimators", type=int, default=400)
    ap.add_argument("--lr", type=float, default=0.03)
    ap.add_argument("--min-child", type=int, default=8)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    bases = [b.strip().upper() for b in args.pair.split(",") if b.strip()]
    rows = []
    for b in bases:
        try:
            r = run_wf(b, args.tf, args.features, train_min=args.train_min,
                       n_splits=args.n_splits, depth=args.depth, horizon=args.horizon,
                       z_thr=args.z_thr, cost=args.cost, n_estimators=args.n_estimators,
                       lr=args.lr, min_child=args.min_child)
        except Exception as exc:
            r = {"base": b, "error": repr(exc)}
        if "error" in r:
            print(f"[{b}] ERROR: {r['error']}")
            continue
        if args.verbose:
            print(f"\n[{b}] per-fold:\n{r.pop('_fr').to_string(index=False)}")
        else:
            r.pop("_fr", None)
        rows.append(r)

    if rows:
        cols = ["base", "n_feats", "folds", "ic_tr_p_mean", "ic_te_p_mean",
                "ic_te_s_mean", "pct_folds_pos", "ic_pooled_p", "net_sharpe",
                "hit_rate", "avg_ret", "n_trades"]
        out = pd.DataFrame(rows)[cols]
        print(f"\n=== Popeye WF — tf={args.tf} features={args.features} "
              f"train_min={args.train_min} depth={args.depth} h={args.horizon} ===")
        print(out.to_string(index=False))
        print(f"\nMEAN OOS IC (pearson): {out['ic_te_p_mean'].mean():+.3f}  | "
              f"mean net Sharpe: {out['net_sharpe'].mean():.2f}  | "
              f"mean %folds+: {out['pct_folds_pos'].mean():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
