#!/usr/bin/env python3
"""Mickey «سایه» (تصمیم مالک ۲۰۲۶-۰۹-۰۳): آزمونِ زنده‌ی سیگنالِ انبساطِ نوسان (گروه vol،
افق ۱۲۰h، k=16، باند ۳۰، یونیورسِ نقدِ ۷۰تایی) به‌صورت دفترِ کاغذی، بدونِ دست زدن به باتِ
زنده‌ی Mickey. هر ساعت (--tick): امتیازِ مقطعی → اگر ≥120h از آخرین بازآرایی گذشته، دفترِ
قبلی با قیمتِ بسته‌شدنِ آخر تسویه و دفترِ جدید (±1/k با هیسترزیسِ باند) باز می‌شود؛ وگرنه
فقط mark-to-market. هزینه = گردش × COST_ONEWAY (همان فرضِ آموزش). خروجی: state.json،
periods.jsonl، equity.jsonl، status.json در outputs/mickey_shadow/. مدل از همان پوشه
(mickey_xs_train.py --out-dir …). صفر ریسکِ زنده؛ کارنامه‌ی OOS برای تصمیمِ استقرار."""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import joblib, numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from popeye_wf import build_features            # noqa: E402
from mickey_xs_features import xs_norm_cols     # noqa: E402
SH = ROOT / "outputs" / "mickey_shadow"
MODEL, GATE = SH / "mickey_xs_model.joblib", SH / "mickey_xs_gate.json"
STATE, PERIODS, EQ, STATUS = SH / "state.json", SH / "periods.jsonl", SH / "equity.jsonl", SH / "status.json"
TF, N_CANDLES = "1h", 1000
K, BAND, H = 16, 30, 120
COST_ONEWAY = 0.0003                     # نصفِ COST=0.0006 رفت‌وبرگشت (همان فرضِ WF)
MODEL_MAX_AGE_H = 24 * 9                 # آموزشِ هفتگی + حاشیه

def _load(p, d): 
    try: return json.loads(p.read_text())
    except Exception: return d
def _atomic(p: Path, obj) -> None:
    t = p.with_suffix(p.suffix + ".tmp"); t.write_text(json.dumps(obj, ensure_ascii=False, indent=1)); t.replace(p)

def scores(now: datetime):
    bundle = joblib.load(MODEL); model, feat_cols, meta = bundle["model"], bundle["feat_cols"], bundle["meta"]
    age_h = (now - datetime.fromisoformat(meta["trained_at"])).total_seconds() / 3600
    if age_h > MODEL_MAX_AGE_H:
        raise RuntimeError(f"model stale ({age_h:.0f}h)")
    gate = _load(GATE, {}); bases = gate.get("universe") or []
    if len(bases) < 20:
        raise RuntimeError("universe missing in gate json")
    groups = meta.get("groups")
    import ccxt
    ex = ccxt.bybit({"options": {"defaultType": "swap"}}); ex.load_markets()
    cur_hour = pd.Timestamp(now).floor("1h")
    def fetch(pair):
        o = ex.fetch_ohlcv(pair, timeframe=TF, limit=N_CANDLES)
        if not o or len(o) < 800: return None
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[df["date"] < cur_hour].reset_index(drop=True)
    btc = fetch("BTC/USDT:USDT")
    rows, px, excluded = {}, {}, []
    for b in bases:
        pair = f"{b}/USDT:USDT"
        try:
            df = fetch(pair)
            if df is None: excluded.append(b); continue
            feats = build_features(df, "xs", groups=groups, btc=btc, funding=None, oi=None)
            last = feats.iloc[-1]
            v = last.reindex(feat_cols).to_numpy(dtype=float)
            if not np.isfinite(v).all(): excluded.append(b); continue
            rows[pair] = v; px[pair] = float(df["close"].iloc[-1])
            time.sleep(0.1)
        except Exception as exc:  # noqa: BLE001
            excluded.append(f"{b}:{str(exc)[:40]}")
    if len(rows) < 2 * K + 4:
        raise RuntimeError(f"too few pairs ({len(rows)}); excluded={excluded[:8]}")
    pairs = list(rows); X = np.array([rows[p] for p in pairs], dtype=float)
    zmask = np.array([c in set(xs_norm_cols(feat_cols)) for c in feat_cols])
    Xz = np.where(zmask, (X - X.mean(0)) / (X.std(0) + 1e-9), X)
    pred = np.asarray(model.predict(Xz), dtype=float)
    pz = (pred - pred.mean()) / (pred.std() + 1e-9)
    return {p: float(pz[i]) for i, p in enumerate(pairs)}, px, {"trained_at": meta["trained_at"], "n": len(pairs), "excluded": excluded, "candle": cur_hour.isoformat()}

def new_book(sc: dict, prev: dict) -> dict:
    """همان هیسترزیسِ wf_eval: مستقرها تا وقتی در باندِ k+band بمانند نگه داشته می‌شوند."""
    ps = sorted(sc, key=lambda p: sc[p]); n = len(ps); rank = {p: i for i, p in enumerate(ps)}
    top_band, bot_band = set(ps[-(K + BAND):]), set(ps[:K + BAND])
    cur_long = {p for p, w in prev.items() if w > 0}; cur_short = {p for p, w in prev.items() if w < 0}
    keep_long = sorted([p for p in cur_long if p in top_band], key=lambda p: rank[p], reverse=True)[:K]
    for p in reversed(ps):
        if len(keep_long) >= K: break
        if p not in keep_long: keep_long.append(p)
    keep_short = sorted([p for p in cur_short if p in bot_band and p not in keep_long], key=lambda p: rank[p])[:K]
    for p in ps:
        if len(keep_short) >= K: break
        if p not in keep_short and p not in keep_long: keep_short.append(p)
    book = {p: 1.0 / K for p in keep_long[:K]}; book.update({p: -1.0 / K for p in keep_short[:K]})
    return book

def tick(now: datetime) -> dict:
    sc, px, info = scores(now)
    st = _load(STATE, {"book": {}, "entry": {}, "last_rebalance": None, "realized_cum": 0.0, "n_periods": 0})
    book, entry = st["book"], st["entry"]
    mtm = sum(w * (px.get(p, entry[p]) / entry[p] - 1.0) for p, w in book.items()) if book else 0.0
    due = (st["last_rebalance"] is None) or ((now - datetime.fromisoformat(st["last_rebalance"])) >= timedelta(hours=H))
    rec = None
    if due:
        w_new = new_book(sc, book)
        turnover = sum(abs(w_new.get(p, 0.0) - book.get(p, 0.0)) for p in set(book) | set(w_new))
        if book:  # تسویه‌ی دوره‌ی قبل با قیمتِ فعلی
            gross = mtm; net = gross - st.get("open_cost", 0.0)
            rec = {"closed_at": now.isoformat(), "opened_at": st["last_rebalance"], "gross": round(gross, 5),
                   "net": round(net, 5), "turnover_at_open": st.get("open_turnover"), "n_long": sum(1 for w in book.values() if w > 0)}
            with PERIODS.open("a") as f: f.write(json.dumps(rec) + "\n")
            st["realized_cum"] = float(st.get("realized_cum", 0.0)) + net; st["n_periods"] = int(st.get("n_periods", 0)) + 1
        st.update({"book": w_new, "entry": {p: px[p] for p in w_new}, "last_rebalance": now.isoformat(),
                   "open_turnover": round(turnover, 4), "open_cost": turnover * COST_ONEWAY, "scores_at_open": {p: round(sc[p], 3) for p in w_new}})
        mtm = 0.0
    st["last_tick"] = now.isoformat(); st["model_trained_at"] = info["trained_at"]; st["n_universe"] = info["n"]
    _atomic(STATE, st)
    with EQ.open("a") as f:
        f.write(json.dumps({"ts": now.isoformat(), "realized_cum": round(st["realized_cum"], 5), "unrealized": round(mtm, 5),
                            "equity": round(st["realized_cum"] + mtm, 5), "n_periods": st["n_periods"], "rebalanced": bool(due)}) + "\n")
    # آمارِ تاکنون
    pr = [json.loads(l) for l in PERIODS.read_text().splitlines() if l.strip()] if PERIODS.exists() else []
    nets = np.array([r["net"] for r in pr], dtype=float)
    ann = np.sqrt(365 * 24 / H)
    status = {"updated_at": now.isoformat(), "config": {"features": "xs:vol", "horizon_h": H, "k": K, "band": BAND, "cost_oneway": COST_ONEWAY},
              "n_periods": int(len(nets)), "realized_cum": round(float(nets.sum()), 4) if len(nets) else 0.0,
              "sharpe_net_ann": round(float(nets.mean() / (nets.std() + 1e-12) * ann), 2) if len(nets) > 3 else None,
              "hit_rate": round(float((nets > 0).mean()), 2) if len(nets) else None,
              "unrealized": round(mtm, 4), "equity": round(float(nets.sum()) + mtm, 4),
              "last_rebalance": st["last_rebalance"], "rebalanced_now": bool(due), "n_universe": info["n"], "excluded": info["excluded"][:10],
              "book_long": sorted([p.split("/")[0] for p, w in st["book"].items() if w > 0]), "book_short": sorted([p.split("/")[0] for p, w in st["book"].items() if w < 0]),
              "model_trained_at": info["trained_at"], "last_period": rec}
    _atomic(STATUS, status)
    return status

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--tick", action="store_true"); ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(); now = datetime.now(timezone.utc).replace(microsecond=0)
    if a.tick:
        try:
            s = tick(now)
            print(f"[shadow] {now.isoformat()} reb={s['rebalanced_now']} n={s['n_universe']} periods={s['n_periods']} cum={s['realized_cum']} unreal={s['unrealized']} sharpe={s['sharpe_net_ann']} hit={s['hit_rate']}")
        except Exception as exc:  # noqa: BLE001
            print(f"[shadow] {now.isoformat()} FAILED: {exc}"); return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
