#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backtest the cross-sectional money-flow signal on NATIVE Hyperliquid data
(208 days of 1h OHLCV that HL actually serves — no proxy).

Caveat: HL serves NO Open-Interest history, so this backtest validates only the
price/volume/CMF money-flow component (what's computable from OHLCV). The OI-flow
term — the purest capital measure — is validated live on paper as hourly snapshots
accumulate. This answers "test on the real exchange's data" as far as the data allows.

Long top-k inflow / short bottom-k outflow, dollar-neutral, hysteresis, net of HL fees.
"""
from __future__ import annotations
import math, time, sys
from pathlib import Path
import numpy as np, pandas as pd, ccxt

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "hl_flow" / "ohlcv"


def hl():
    return ccxt.hyperliquid({"enableRateLimit": True})


def liquid_universe(ex, min_oi=10e6, min_vol=2e6, cap=35):
    info = ex.publicPostInfo({"type": "metaAndAssetCtxs"})
    meta, ctxs = info[0], info[1]
    rows = []
    for u, c in zip(meta["universe"], ctxs):
        mark = float(c.get("markPx") or 0); oi = float(c.get("openInterest") or 0)
        vol = float(c.get("dayNtlVlm") or 0)
        if oi * mark >= min_oi and vol >= min_vol:
            rows.append((u["name"], oi * mark))
    rows.sort(key=lambda r: -r[1])
    return [r[0] for r in rows[:cap]]


def load_ohlcv(ex, coin, limit=5000):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{coin}_1h.parquet"
    if f.exists():
        return pd.read_parquet(f)
    try:
        o = ex.fetch_ohlcv(f"{coin}/USDC:USDC", "1h", limit=limit)
        if not o or len(o) < 200:
            return None
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "vol"])
        df.to_parquet(f, index=False)
        return df
    except Exception as e:
        print(f"  {coin}: dl err {repr(e)[:80]}")
        return None


def cmf_series(df, window=20):
    rng = (df["high"] - df["low"]).clip(lower=1e-9)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mfv = mfm * df["vol"]
    return mfv.rolling(window).sum() / df["vol"].rolling(window).sum().clip(lower=1e-9)


def build_panels(ex, coins, L):
    """wide matrices indexed by ts: flow_score components + 1-bar fwd return."""
    close, score = {}, {}
    for c in coins:
        df = load_ohlcv(ex, c)
        if df is None or len(df) < L + 60:
            continue
        df = df.drop_duplicates("ts").sort_values("ts")
        idx = pd.to_datetime(df["ts"], unit="ms", utc=True)
        cl = pd.Series(df["close"].values, index=idx)
        dvol = pd.Series((df["close"] * df["vol"]).values, index=idx)
        ret_l = cl / cl.shift(L) - 1.0
        vol_mom = dvol.rolling(L).mean() / dvol.rolling(L * 4).mean() - 1.0
        cmf = pd.Series(cmf_series(df, 20).values, index=idx)
        sign = np.sign(ret_l).replace(0, 1)
        # OHLCV-only money flow: price momentum confirmed by volume rotation + CMF
        score[c] = (_z_t(ret_l) + 0.7 * _z_t(vol_mom) * sign + 0.6 * _z_t(cmf))
        close[c] = cl
    S = pd.DataFrame(score).sort_index()
    C = pd.DataFrame(close).reindex(S.index)
    R = C.shift(-1) / C - 1.0
    dense = S.notna().sum(axis=1) >= max(8, int(0.6 * S.shape[1]))
    return S[dense], R[dense]


def _z_t(s):  # time-series z (per coin) just to stabilize; XS-z happens at decision
    return (s - s.rolling(200, min_periods=30).mean()) / (s.rolling(200, min_periods=30).std() + 1e-9)


def backtest(S, R, k, band, cost, every):
    cols = list(S.columns); Sv = S.to_numpy(); Rv = R.to_numpy()
    idx_of = {c: i for i, c in enumerate(cols)}
    cur_l, cur_s = set(), set(); w_prev = np.zeros(len(cols))
    rets, turns = [], []
    for t in range(len(S)):
        row = Sv[t]; fin = np.where(np.isfinite(row))[0]
        if len(fin) >= 2 * k and t % every == 0:
            vals = row[fin]; z = (vals - vals.mean()) / (vals.std() + 1e-9)
            order = fin[np.argsort(z)]; ranked = [cols[i] for i in order]
            rank = {p: r for r, p in enumerate(ranked)}
            topb = set(ranked[-(k + band):]); botb = set(ranked[:k + band])
            keep_l = sorted([p for p in cur_l if p in topb], key=lambda p: rank[p], reverse=True)[:k]
            for p in reversed(ranked):
                if len(keep_l) >= k: break
                if p not in keep_l: keep_l.append(p)
            keep_s = sorted([p for p in cur_s if p in botb], key=lambda p: rank[p])[:k]
            for p in ranked:
                if len(keep_s) >= k: break
                if p not in keep_s and p not in keep_l: keep_s.append(p)
            cur_l, cur_s = set(keep_l[:k]), set(keep_s[:k])
        w = np.zeros(len(cols))
        for p in cur_l: w[idx_of[p]] = 1.0 / k
        for p in cur_s: w[idx_of[p]] = -1.0 / k
        turn = np.abs(w - w_prev).sum()
        r1 = np.where(np.isfinite(Rv[t]), Rv[t], 0.0)
        rets.append(float((w * r1).sum()) - turn * cost / 2.0); turns.append(turn); w_prev = w
    rets = np.asarray(rets); n = len(rets); ann = math.sqrt(8760)
    sh = float(rets.mean() / (rets.std() + 1e-12) * ann) if n > 10 else float("nan")
    cum = float(np.prod(1 + rets) - 1)
    return {"sharpe": round(sh, 2), "cum": round(cum, 3),
            "dayturn": round(float(np.mean(turns)) * 24, 2),
            "hit": round(float((rets > 0).mean()), 3), "n": n}


def main():
    ex = hl()
    coins = liquid_universe(ex)
    print(f"HL liquid universe: {len(coins)} coins → {coins}")
    print("downloading 5000×1h candles each (cached)...")
    print(f"\n{'L':>3}{'k':>3}{'every':>6}{'cost':>6} |{'sharpe':>7}{'cum':>8}{'dayturn':>8}{'hit':>6}{'n':>6}")
    print("-" * 52)
    best = []
    for L in (12, 24, 48):
        S, R = build_panels(ex, coins, L)
        for k in (4, 5):
            for every in (6, 12):
                for cost, cn in [(0.0004, "mk"), (0.0010, "tk")]:
                    r = backtest(S, R, k, 8, cost, every)
                    tag = f"L={L} k={k} e={every} {cn}"
                    print(f"{L:>3}{k:>3}{every:>6}{cn:>6} |{r['sharpe']:>7}{r['cum']:>8}"
                          f"{r['dayturn']:>8}{r['hit']:>6}{r['n']:>6}")
                    if cn == "mk": best.append((r["sharpe"], tag, r))
        print()
    best.sort(reverse=True)
    print("=== TOP 5 (maker 4bps, on REAL HL data) ===")
    for sh, tag, r in best[:5]:
        print(f"  {tag}: Sharpe {sh}, cum {r['cum']*100:+.0f}%, dayturn {r['dayturn']}, hit {r['hit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
