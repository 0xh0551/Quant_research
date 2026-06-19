#!/usr/bin/env python3
"""Cross-sectional market-neutral WF test for the μ/α signal.

فرضیه (قانونِ بنیادی IR=IC·√breadth): همان IC ضعیف (~+0.04) اگر به‌جای ۵ جفتِ مجزا
روی کلِ universe رتبه‌بندی شود (long تاپ‌k، short پایین‌k) → breadth چند برابر،
بتا حذف، و یک دفترِ مارکت-نیوترالِ قابل‌لوریج. اینجا با همان دادهٔ Gate و همان
هدفِ μ (که ذاتاً وول-اسکیل و بین‌جفتی مقایسه‌پذیر است) می‌سنجیم آیا واقعاً بهتر است.

مدل: **pooled** (یک مدل روی دادهٔ همهٔ جفت‌ها) → دادهٔ ده‌ها برابر بیشتر = ضدِ overfit.
WFِ زمانی purged (embargo = افقِ لیبل). سبد هر h کندل rebalance (غیرهم‌پوشان).

استفاده:
  .venv/bin/python scripts/bot1_xs.py --tf 1h --k 4 --features reduced
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot1_wf import load_ohlcv, build_features, build_mu_target, _ic  # noqa: E402

DEFAULT_UNIVERSE = ["ADA", "AVAX", "BNB", "DOGE", "ENA", "ETH", "HYPE", "NEAR",
                    "PEPE", "SOL", "SUI", "UNI", "WLD", "XAUT", "XLM", "XRP", "ZEC"]


def build_panel(bases: list[str], tf: str, mode: str, horizon: int,
                venue: str = "gate") -> pd.DataFrame:
    """پنل long: یک ردیف به‌ازای (date, pair) با ویژگی‌ها + μ + بازدهِ آتیِ h-کندلی."""
    btc = load_ohlcv("BTC", tf, venue)
    frames = []
    feat_cols: list[str] | None = None
    for b in bases:
        try:
            df = load_ohlcv(b, tf, venue)
        except FileNotFoundError:
            continue
        feats = build_features(df, mode)
        mu = build_mu_target(df, btc, horizon)
        fwd_h = df["close"].shift(-horizon) / df["close"] - 1.0
        if feat_cols is None:
            feat_cols = list(feats.columns)
        part = feats.copy()
        part["date"] = df["date"].values
        part["pair"] = b
        part["mu"] = mu.values
        part["fwd_h"] = fwd_h.values
        frames.append(part)
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.dropna(subset=feat_cols + ["mu"]).reset_index(drop=True)
    return panel, feat_cols


def run_xs(bases: list[str], tf: str, mode: str, *, horizon: int, k: int,
          n_splits: int, depth: int, n_estimators: int, lr: float,
          min_child: int, cost: float, xs_norm: bool, hyst_band: int = 0,
          venue: str = "gate") -> dict:
    from xgboost import XGBRegressor

    panel, feat_cols = build_panel(bases, tf, mode, horizon, venue)
    dates = np.sort(panel["date"].unique())
    nd = len(dates)

    # WFِ زمانی: مرزها روی محورِ تاریخ (نه ردیف) → بدونِ نشتِ بین‌جفتی
    bounds = np.array_split(np.arange(nd), n_splits + 1)
    embargo_days = horizon  # کندل
    bars_yr = {"1h": 8760, "4h": 2190, "15m": 35040}.get(tf, 8760)

    # نرمال‌سازیِ مقطعی: هر ویژگی و هدف را به‌ازای هر تاریخ به z-score درون‌مقطعی ببر،
    # تا مدل «جذابیتِ نسبیِ» جفت‌ها را یاد بگیرد (هستهٔ یک مدلِ cross-sectional).
    if xs_norm:
        def _xsz(df, cols):
            g = df.groupby("date")[cols]
            return (df[cols] - g.transform("mean")) / (g.transform("std") + 1e-9)
        panel[feat_cols] = _xsz(panel, feat_cols).fillna(0.0)
        # هدفِ مقطعی: μ استانداردشده درونِ هر تاریخ (رتبه‌بندیِ نسبی)
        gm = panel.groupby("date")["mu"]
        panel["mu"] = ((panel["mu"] - gm.transform("mean"))
                       / (gm.transform("std") + 1e-9)).fillna(0.0)

    Xall = panel[feat_cols].to_numpy()
    yall = panel["mu"].to_numpy()
    date_arr = panel["date"].to_numpy()

    oos_pred = np.full(len(panel), np.nan)
    for i in range(1, n_splits + 1):
        te_dates = dates[bounds[i]]
        cutoff = te_dates[0]
        # embargo: ردیف‌های آموزش باید لیبلشان قبل از شروعِ تست تمام شده باشد
        emb_cut = dates[max(0, bounds[i][0] - embargo_days)]
        tr_mask = date_arr < emb_cut
        te_mask = np.isin(date_arr, te_dates)
        if tr_mask.sum() < 5000 or te_mask.sum() < 200:
            continue
        m = XGBRegressor(
            objective="reg:pseudohubererror", n_estimators=n_estimators,
            learning_rate=lr, max_depth=depth, min_child_weight=min_child,
            subsample=0.8, colsample_bytree=0.7, reg_lambda=2.0, reg_alpha=0.5,
            gamma=0.1, tree_method="hist", n_jobs=-1, verbosity=0)
        m.fit(Xall[tr_mask], yall[tr_mask])
        oos_pred[te_mask] = m.predict(Xall[te_mask])

    panel["pred"] = oos_pred
    oos = panel.dropna(subset=["pred"]).copy()

    # IC مقطعی: همبستگیِ pred↔mu درونِ هر تاریخ، میانگین‌گیری (IC استانداردِ XS)
    xs_ic = (oos.groupby("date").apply(
        lambda g: _ic(g["pred"].to_numpy(), g["mu"].to_numpy())[1]  # spearman
        if len(g) >= 5 else np.nan).dropna())
    ic_xs_mean = float(xs_ic.mean()) if len(xs_ic) else float("nan")

    # ── بک‌تستِ سبدِ مارکت-نیوترال با هزینهٔ مبتنی‌بر گردشِ واقعی + هیسترزیس ─────────
    # وزن +1/k برای k تاپ، -1/k برای k پایین. هزینه فقط روی Δوزن (یک‌طرفه=cost/2).
    # هیسترزیس: جفتِ مستقر تا وقتی در تاپ/پایینِ (k+band) بماند نگه داشته می‌شود
    # (کاهشِ گردش = کاهشِ هزینه؛ قفلِ سوددهیِ خالص).
    reb_dates = dates[::horizon]
    oneway = cost / 2.0
    band = hyst_band
    w_prev: dict = {}
    rets, gross_list, turnovers = [], [], []
    cur_long: set = set()
    cur_short: set = set()
    for d in reb_dates:
        g = oos[oos["date"] == d].dropna(subset=["fwd_h"])
        if len(g) < 2 * k:
            continue
        gs = g.sort_values("pred")
        pairs_sorted = gs["pair"].tolist()
        rank = {p: i for i, p in enumerate(pairs_sorted)}  # 0=بدترین pred ... n-1=بهترین
        n = len(pairs_sorted)
        top_band = set(pairs_sorted[-(k + band):]); bot_band = set(pairs_sorted[:k + band])
        # هیسترزیس درست: اول مستقرهایی که هنوز در باندند را نگه دار (تا سقفِ k، بهترین‌ها)،
        # بعد جاهای خالی را با تازه‌واردهای تاپ/پایین (که هنوز نگه‌داشته نشده‌اند) پر کن.
        keep_long = sorted([p for p in cur_long if p in top_band],
                           key=lambda p: rank[p], reverse=True)[:k]
        for p in reversed(pairs_sorted):           # بهترین pred اول
            if len(keep_long) >= k:
                break
            if p not in keep_long:
                keep_long.append(p)
        keep_short = sorted([p for p in cur_short if p in bot_band],
                            key=lambda p: rank[p])[:k]
        for p in pairs_sorted:                      # بدترین pred اول
            if len(keep_short) >= k:
                break
            if p not in keep_short and p not in keep_long:
                keep_short.append(p)
        new_long, new_short = set(keep_long[:k]), set(keep_short[:k])
        cur_long, cur_short = new_long, new_short

        w_new: dict = {}
        for p in new_long:
            w_new[p] = 1.0 / k
        for p in new_short:
            w_new[p] = -1.0 / k
        # گردش = Σ|Δw|
        allp = set(w_prev) | set(w_new)
        turnover = sum(abs(w_new.get(p, 0.0) - w_prev.get(p, 0.0)) for p in allp)
        fwd = dict(zip(g["pair"], g["fwd_h"]))
        gross_ret = sum(w * fwd.get(p, 0.0) for p, w in w_new.items())
        net_ret = gross_ret - turnover * oneway
        gross_list.append(gross_ret); rets.append(net_ret); turnovers.append(turnover)
        w_prev = w_new

    rets = np.asarray(rets); gross = np.asarray(gross_list)
    n_reb = len(rets)
    ann = math.sqrt(bars_yr / horizon)
    sh = float(rets.mean() / (rets.std() + 1e-12) * ann) if n_reb > 10 else float("nan")
    sh_gross = float(gross.mean() / (gross.std() + 1e-12) * ann) if n_reb > 10 else float("nan")
    cum = float(np.prod(1 + rets) - 1) if n_reb else float("nan")
    avg_turnover = round(float(np.mean(turnovers)), 3) if turnovers else None

    return {
        "universe": len(bases), "n_feats": len(feat_cols), "k": k,
        "xs_ic_spearman": round(ic_xs_mean, 4),
        "sharpe_gross": round(sh_gross, 2),
        "sharpe_net": round(sh, 2),
        "cum_net": round(cum, 3),
        "avg_period_ret": round(float(rets.mean()), 4) if n_reb else None,
        "avg_turnover": avg_turnover,
        "n_rebalances": n_reb,
        "hit_rate": round(float((rets > 0).mean()), 3) if n_reb else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--features", choices=["reduced", "full"], default="reduced")
    ap.add_argument("--k", type=int, default=4, help="تعداد long و تعداد short")
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--n-splits", type=int, default=8)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--n-estimators", type=int, default=400)
    ap.add_argument("--lr", type=float, default=0.03)
    ap.add_argument("--min-child", type=int, default=8)
    ap.add_argument("--cost", type=float, default=0.0018)
    ap.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE))
    ap.add_argument("--xs-norm", action="store_true")
    ap.add_argument("--hyst-band", type=int, default=0,
                    help="هیسترزیس: مستقر را تا وقتی در تاپ/پایینِ (k+band) است نگه دار")
    ap.add_argument("--venue", default="gate", help="gate | bybit | okx ...")
    args = ap.parse_args()

    bases = [b.strip().upper() for b in args.universe.split(",") if b.strip()]
    r = run_xs(bases, args.tf, args.features, horizon=args.horizon, k=args.k,
               n_splits=args.n_splits, depth=args.depth, n_estimators=args.n_estimators,
               lr=args.lr, min_child=args.min_child, cost=args.cost, xs_norm=args.xs_norm,
               hyst_band=args.hyst_band, venue=args.venue)
    print(f"\n=== Cross-sectional MN — tf={args.tf} feats={args.features} "
          f"universe={r['universe']} k={args.k} h={args.horizon} ===")
    for kk, vv in r.items():
        print(f"  {kk:18s}: {vv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
