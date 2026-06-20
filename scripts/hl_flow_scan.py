#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hl_flow_scan — آشکارسازِ «جریانِ پول» روی صرافیِ Hyperliquid (فقط دیتای خودِ HL).

ایده: سرمایهٔ عمده هر لحظه از روی بعضی توکن‌ها خارج و به بعضی دیگر وارد می‌شود.
این جریان را با دیتای **بومیِ HL** اندازه می‌گیریم و توکن‌های مقصدِ پول را long،
مبدأ پول را short می‌کنیم (رتبه‌بندیِ مقطعی).

چرا دیتای HL کافی است (probe شده):
  ▸ OHLCV: تا ۵۰۰۰ کندلِ اخیر (1h ≈ ۲۰۸ روز) — قیمت/حجم/اسیلاتورهای جریانِ پول.
  ▸ metaAndAssetCtxs: برای هر کوین **Open Interest + funding + حجمِ دلاریِ روز** —
    قلبِ جریانِ سرمایه. ولی HL تاریخچهٔ OI نمی‌دهد → هر ساعت snapshot می‌گیریم تا
    سری‌زمانیِ OI را خودمان بسازیم (همان دانلودِ ساعتی‌ای که کاربر گفت).

امضای جریانِ پول (مقطعی، z-score روی کلِ universe):
  جهت = مومنتومِ قیمت (ret_L)؛ تأیید/تقویت با:
    • رشدِ OI (سرمایهٔ تازهٔ متعهدشده)  ← هستهٔ «money flow»
    • چرخشِ حجمِ دلاری (توجهِ سرمایه)
    • CMF (فشارِ خرید/فروشِ درون‌کندلی)
  OI↑ همراهِ قیمت↑ = انباشتِ long → long ؛ OI↑ همراهِ قیمت↓ = ساختِ short → short.
  funding اکستریم = ازدحام (جریمهٔ کوچک، ضدِ دنبال‌کردنِ پوزیشنِ شلوغ).

خروجی: noches/user_data/hl_flow_signal.json (مانیفستی که استراتژیِ WalleFlow می‌خواند).
اجرا: هر ساعت از طریقِ refresh_candidates.sh (step: hl_flow_scan). فقط-snapshot هم می‌شود.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import ccxt

ROOT = Path(__file__).resolve().parents[1]
FLOW_DIR = ROOT / "data" / "hl_flow"
SNAP_PATH = FLOW_DIR / "snapshots.parquet"
OHLCV_DIR = FLOW_DIR / "ohlcv"
SIGNAL_OUT = Path("/home/h0551user/noches/user_data/hl_flow_signal.json")

# ── پارامترهای universe و سیگنال ─────────────────────────────────────────────
MIN_OI_USD = 10_000_000.0     # کفِ Open Interest دلاری (نقدشوندگیِ واقعی)
MIN_DAY_VOL = 2_000_000.0     # کفِ حجمِ دلاریِ روز
MAX_UNIVERSE = 40             # حداکثر تعداد کوین (top by OI)
TIMEFRAME = "1h"
LOOKBACK = 24                 # افقِ سیگنال (ساعت) برای ret/Δ-OI/حجم
HOLD_BAND = 6                 # هیسترزیس: پوزیشن تا وقتی در top/bottom-(k+band) بماند نگه داشته می‌شود
SNAP_RETAIN_DAYS = 45         # نگه‌داریِ snapshotهای OI (بستنِ رشدِ حافظه)

# وزنِ مؤلفه‌ها (جریانِ سرمایه محور است؛ وقتی تاریخچهٔ OI نباشد، گرِیسفول fallback)
W_MOM = 1.0       # مومنتومِ قیمت (جهت)
W_OI  = 1.2       # رشدِ OI در جهتِ حرکت (هستهٔ money-flow؛ نیازمندِ snapshotِ انباشته)
W_VOL = 0.7       # چرخشِ حجمِ دلاری در جهتِ حرکت
W_CMF = 0.6       # فشارِ درون‌کندلی
W_FUND = 0.3      # جریمهٔ ازدحامِ funding


def hl() -> ccxt.hyperliquid:
    return ccxt.hyperliquid({"enableRateLimit": True})


def fetch_ctxs(ex) -> pd.DataFrame:
    """snapshotِ زندهٔ همهٔ کوین‌ها: OI، funding، حجمِ روز، قیمتِ mark."""
    info = ex.publicPostInfo({"type": "metaAndAssetCtxs"})
    meta, ctxs = info[0], info[1]
    now = int(time.time())
    rows = []
    for u, c in zip(meta["universe"], ctxs):
        try:
            mark = float(c.get("markPx") or 0)
            oi = float(c.get("openInterest") or 0)
            rows.append({
                "ts": now, "coin": u["name"], "mark": mark,
                "oi_base": oi, "oi_usd": oi * mark,
                "funding": float(c.get("funding") or 0),
                "day_vol_usd": float(c.get("dayNtlVlm") or 0),
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


def append_snapshot(snap: pd.DataFrame) -> pd.DataFrame:
    """snapshot را به storeِ rolling اضافه و سری را برمی‌گرداند (با retain)."""
    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    if SNAP_PATH.exists():
        old = pd.read_parquet(SNAP_PATH)
        allrows = pd.concat([old, snap], ignore_index=True)
    else:
        allrows = snap
    cutoff = int(time.time()) - SNAP_RETAIN_DAYS * 86400
    allrows = allrows[allrows["ts"] >= cutoff].reset_index(drop=True)
    allrows.to_parquet(SNAP_PATH, index=False)
    return allrows


def oi_growth_from_store(store: pd.DataFrame, coin: str, hours: int) -> float | None:
    """رشدِ نسبیِ OI دلاری در lookback (از snapshotهای انباشته). None اگر تاریخچه کم باشد."""
    g = store[store["coin"] == coin].sort_values("ts")
    if len(g) < 2:
        return None
    now_ts = g["ts"].iloc[-1]
    past = g[g["ts"] <= now_ts - hours * 3600]
    if past.empty:
        return None
    oi_now = g["oi_usd"].iloc[-1]
    oi_past = past["oi_usd"].iloc[-1]
    if oi_past <= 0:
        return None
    return oi_now / oi_past - 1.0


def fetch_ohlcv(ex, symbol: str, limit: int = 300) -> pd.DataFrame | None:
    try:
        o = ex.fetch_ohlcv(symbol, TIMEFRAME, limit=limit)
        if not o:
            return None
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "vol"])
        return df
    except Exception:
        return None


def cmf(df: pd.DataFrame, window: int = 20) -> float:
    hl_range = (df["high"] - df["low"]).clip(lower=1e-9)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    mfv = mfm * df["vol"]
    denom = df["vol"].rolling(window).sum()
    c = (mfv.rolling(window).sum() / denom.clip(lower=1e-9)).iloc[-1]
    return float(c) if np.isfinite(c) else 0.0


def compute_signal(ex, store: pd.DataFrame, snap: pd.DataFrame, k: int) -> dict:
    # universe: نقدشونده‌ها بر اساس OI/حجم
    u = snap[(snap["oi_usd"] >= MIN_OI_USD) & (snap["day_vol_usd"] >= MIN_DAY_VOL)]
    u = u.sort_values("oi_usd", ascending=False).head(MAX_UNIVERSE).copy()
    feats = []
    oi_hist_cov = 0
    for _, r in u.iterrows():
        coin = r["coin"]
        symbol = f"{coin}/USDC:USDC"
        df = fetch_ohlcv(ex, symbol, limit=max(60, LOOKBACK + 40))
        if df is None or len(df) < LOOKBACK + 5:
            continue
        close = df["close"]
        ret_l = float(close.iloc[-1] / close.iloc[-1 - LOOKBACK] - 1.0)
        # چرخشِ حجمِ دلاری: حجمِ اخیر نسبت به میانگین
        dvol = (df["close"] * df["vol"])
        vol_mom = float(dvol.tail(LOOKBACK).mean() / (dvol.tail(LOOKBACK * 4).mean() + 1e-9) - 1.0)
        cmf_v = cmf(df, 20)
        oi_g = oi_growth_from_store(store, coin, LOOKBACK)
        if oi_g is not None:
            oi_hist_cov += 1
        feats.append({
            "coin": coin, "symbol": symbol, "ret_l": ret_l, "vol_mom": vol_mom,
            "cmf": cmf_v, "oi_growth": oi_g, "oi_usd": float(r["oi_usd"]),
            "funding": float(r["funding"]), "day_vol_usd": float(r["day_vol_usd"]),
        })
    if len(feats) < 2 * k:
        return {"error": f"universe too small ({len(feats)})", "n": len(feats)}

    F = pd.DataFrame(feats)

    def z(s):
        s = pd.to_numeric(s, errors="coerce")
        return ((s - s.mean()) / (s.std() + 1e-9)).fillna(0.0)

    sign_mom = np.sign(F["ret_l"]).replace(0, 1)
    # رشدِ OI فقط وقتی تاریخچه باشد؛ وگرنه ۰ (گرِیسفول)
    oi_g_filled = F["oi_growth"].astype(float).fillna(0.0)
    score = (
        W_MOM * z(F["ret_l"])
        + W_OI * z(oi_g_filled) * sign_mom               # OI در جهتِ حرکت = تأییدِ جریانِ سرمایه
        + W_VOL * z(F["vol_mom"]) * sign_mom              # حجم در جهتِ حرکت
        + W_CMF * z(F["cmf"])                             # فشارِ درون‌کندلی
        - W_FUND * z(F["funding"].abs())                 # جریمهٔ ازدحام
    )
    F["flow_score"] = score.values
    F = F.sort_values("flow_score", ascending=False).reset_index(drop=True)

    longs = F.head(k)
    shorts = F.tail(k).iloc[::-1]
    # هیسترزیس: باندِ نگه‌داری = top/bottom-(k+band)
    long_hold = F.head(k + HOLD_BAND)["coin"].tolist()
    short_hold = F.tail(k + HOLD_BAND)["coin"].tolist()
    oi_ready = oi_hist_cov >= max(2 * k, int(0.5 * len(F)))

    def pack(row, side):
        return {
            "coin": row["coin"], "symbol": row["symbol"], "side": side,
            "flow_score": round(float(row["flow_score"]), 4),
            "ret_l": round(row["ret_l"], 4),
            "oi_growth": (round(float(row["oi_growth"]), 4)
                          if row["oi_growth"] is not None and np.isfinite(row["oi_growth"]) else None),
            "vol_mom": round(row["vol_mom"], 4), "cmf": round(row["cmf"], 4),
            "oi_usd": int(row["oi_usd"]), "funding": round(row["funding"], 6),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": TIMEFRAME, "lookback": LOOKBACK, "k": k, "hold_band": HOLD_BAND,
        "universe": len(F),
        "oi_history_ready": oi_ready,
        "oi_history_coverage": f"{oi_hist_cov}/{len(F)}",
        "long_coins": longs["coin"].tolist(),
        "short_coins": shorts["coin"].tolist(),
        "long_hold": long_hold,
        "short_hold": short_hold,
        "longs": [pack(r, "long") for _, r in longs.iterrows()],
        "shorts": [pack(r, "short") for _, r in shorts.iterrows()],
        "ranking": [pack(r, "long" if i < len(F) / 2 else "short")
                    for i, (_, r) in enumerate(F.iterrows())],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5, help="تعداد long و short")
    ap.add_argument("--snapshot-only", action="store_true",
                    help="فقط OI snapshot بگیر (برای انباشتِ تاریخچه)")
    ap.add_argument("--print", dest="show", action="store_true")
    args = ap.parse_args()

    ex = hl()
    snap = fetch_ctxs(ex)
    store = append_snapshot(snap)
    n_snaps = store.groupby("coin").size().median() if len(store) else 0
    print(f"[hl_flow] snapshot: {len(snap)} coins | store rows={len(store)} "
          f"(~{int(n_snaps)} snaps/coin) | {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z")
    if args.snapshot_only:
        return 0

    sig = compute_signal(ex, store, snap, args.k)
    if "error" in sig:
        print(f"[hl_flow] {sig['error']}")
        return 1
    SIGNAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = SIGNAL_OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SIGNAL_OUT)
    print(f"[hl_flow] signal written → {SIGNAL_OUT.name} | universe={sig['universe']} "
          f"OI-history-ready={sig['oi_history_ready']} ({sig['oi_history_coverage']})")
    if args.show:
        print(f"\n  {'LONGS (capital flowing IN)':<34}{'SHORTS (capital flowing OUT)'}")
        for lo, sh in zip(sig["longs"], sig["shorts"]):
            print(f"  {lo['coin']:<6} score={lo['flow_score']:+.2f} ret={lo['ret_l']:+.1%} "
                  f"oi_g={lo['oi_growth']}    │ {sh['coin']:<6} score={sh['flow_score']:+.2f} "
                  f"ret={sh['ret_l']:+.1%} oi_g={sh['oi_growth']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
