"""Per-trade PnL attribution — where each dollar of edge actually went.

A bot's net PnL mixes five very different stories: the alpha the strategy
intended, what entry/exit slippage gave back, what fees took, what funding
paid or charged, and how much of the favorable excursion the exit logic
actually captured. Post-mortems that look only at net PnL can't tell a decay
of alpha from a decay of execution. This module reads every closed trade from
the configured freqtrade DBs (read-only) and decomposes, in quote currency:

    intended_pnl   side × (close_req − open_req) × amount   (the decision)
    entry_slip     adverse fill vs requested on entry        (execution)
    exit_slip      adverse fill vs requested on exit         (execution)
    fees           fee_open_cost + fee_close_cost            (venue)
    funding        freqtrade's signed funding_fees           (carry)
    net            close_profit_abs                          (ground truth)
    residual       net − (intended − slips − fees + funding) (unmodeled)

plus an **exit-efficiency** lens against local candles: the trade's maximum
favorable excursion (MFE) and the share of it the realized exit captured —
the number that showed disciplined TP/SL beats hoping (MFE-capture ≈ 0 was
this fleet's single biggest finding).

CLI:  python -m src.analysis.attribution [days]  → outputs/attribution_report.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src import local_config

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_PATH = ROOT / "outputs" / "attribution_report.json"

DEFAULT_WINDOW_DAYS = 45.0
MFE_TIMEFRAME = "15m"       # candle grid used for excursion measurement


# ── trade loading (read-only, fail-safe) ────────────────────────────────────

def _connect_ro(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return None


def load_closed_trades(db_path: Path, since_days: float | None) -> pd.DataFrame:
    con = _connect_ro(db_path)
    if con is None:
        return pd.DataFrame()
    where = "is_open=0 AND close_date IS NOT NULL"
    params: tuple = ()
    if since_days is not None:
        cutoff = (pd.Timestamp.utcnow().tz_localize(None)
                  - pd.Timedelta(days=since_days)).strftime("%Y-%m-%d %H:%M:%S")
        where += " AND close_date >= ?"
        params = (cutoff,)
    try:
        df = pd.read_sql_query(
            "SELECT id, pair, is_short, leverage, amount, stake_amount, "
            "open_rate, open_rate_requested, close_rate, close_rate_requested, "
            "fee_open_cost, fee_close_cost, fee_open, fee_close, open_trade_value, "
            "funding_fees, close_profit_abs, exit_reason, open_date, close_date "
            f"FROM trades WHERE {where}", con, params=params,
        )
    except Exception:
        df = pd.DataFrame()
    if not df.empty:
        # فیکس 2026-08-08: برای تریدهای چندفیلی (DCA)، open_rate_requestedِ تک-سفارشی
        # در برابر VWAPِ کلِ ترید «اسلیپیج/intended» را با میانگین‌گیریِ DCA قاطی
        # می‌کرد (Bender: entry_slip منفیِ ناممکن روی سفارش‌های limit). VWAPِ
        # قیمت‌های درخواستیِ همه‌ی سفارش‌های فیل‌شده‌ی همان سمت، مرجعِ درست است.
        try:
            orders = pd.read_sql_query(
                "SELECT ft_trade_id AS id, ft_order_side AS o_side, "
                "SUM(COALESCE(price, average) * filled) / SUM(filled) AS req_vwap "
                "FROM orders WHERE filled > 0 GROUP BY ft_trade_id, ft_order_side",
                con,
            )
            ent = df["is_short"].fillna(0).astype(int).map({0: "buy", 1: "sell"})
            for leg, col in (("entry", "open_rate_requested"),
                             ("exit", "close_rate_requested")):
                side = ent if leg == "entry" else ent.map({"buy": "sell", "sell": "buy"})
                m = orders.merge(
                    pd.DataFrame({"id": df["id"], "o_side": side}), on=["id", "o_side"])
                vw = df["id"].map(m.set_index("id")["req_vwap"])
                df[col] = vw.where(vw.notna() & (vw > 0), df[col])
        except Exception:
            pass
    con.close()
    if df.empty:
        return df
    for c in ("open_date", "close_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce", utc=True)
    return df


# ── the decomposition ───────────────────────────────────────────────────────

def decompose_trade(row: pd.Series) -> dict[str, float]:
    side = -1.0 if int(row.get("is_short") or 0) else 1.0
    amount = float(row.get("amount") or 0.0)
    open_rate = float(row.get("open_rate") or 0.0)
    close_rate = float(row.get("close_rate") or 0.0)
    open_req = float(row.get("open_rate_requested") or open_rate) or open_rate
    close_req = float(row.get("close_rate_requested") or close_rate) or close_rate

    intended = side * (close_req - open_req) * amount
    # adverse slippage in quote currency (positive = cost)
    entry_slip = side * (open_rate - open_req) * amount
    exit_slip = side * (close_req - close_rate) * amount

    fee_open = row.get("fee_open_cost")
    fee_close = row.get("fee_close_cost")
    if pd.isna(fee_open) or fee_open is None:
        fee_open = float(row.get("fee_open") or 0.0) * float(row.get("open_trade_value") or 0.0)
    if pd.isna(fee_close) or fee_close is None:
        fee_close = float(row.get("fee_close") or 0.0) * close_rate * amount
    fees = float(fee_open or 0.0) + float(fee_close or 0.0)

    funding = float(row.get("funding_fees") or 0.0)   # freqtrade: signed, adds to profit
    net = float(row.get("close_profit_abs") or 0.0)
    modeled = intended - entry_slip - exit_slip - fees + funding
    return {
        "intended": intended, "entry_slip": entry_slip, "exit_slip": exit_slip,
        "fees": fees, "funding": funding, "net": net,
        "residual": net - modeled,
    }


# ── MFE / exit efficiency against local candles ─────────────────────────────

_candle_cache: dict[str, pd.DataFrame | None] = {}


def _candles_for(base: str) -> pd.DataFrame | None:
    if base in _candle_cache:
        return _candle_cache[base]
    # 2026-08-08: هایپرلیکویید با کوتِ USDC ذخیره می‌شود — بدونِ آن، MFE جفت‌های
    # HL-only بی‌صدا اندازه‌گیری نمی‌شد.
    matches = sorted([p for q in ("USDT", "USDC")
                      for p in PROCESSED_DIR.glob(f"*_{base}{q}_{MFE_TIMEFRAME}.parquet")],
                     key=lambda p: p.stat().st_mtime, reverse=True)
    df = None
    if matches:
        try:
            df = pd.read_parquet(matches[0], columns=["timestamp", "high", "low"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.set_index("timestamp").sort_index()
        except Exception:
            df = None
    _candle_cache[base] = df
    return df


def excursions(row: pd.Series) -> dict[str, float | None]:
    """MFE/MAE (as % of entry) and the exit's capture of MFE."""
    base = str(row["pair"]).split("/")[0]
    candles = _candles_for(base)
    if candles is None or pd.isna(row["open_date"]) or pd.isna(row["close_date"]):
        return {"mfe_pct": None, "mae_pct": None, "capture": None}
    win = candles[(candles.index >= row["open_date"]) & (candles.index <= row["close_date"])]
    if win.empty:
        return {"mfe_pct": None, "mae_pct": None, "capture": None}
    side = -1.0 if int(row.get("is_short") or 0) else 1.0
    open_rate = float(row.get("open_rate") or 0.0)
    if open_rate <= 0:
        return {"mfe_pct": None, "mae_pct": None, "capture": None}
    if side > 0:
        mfe = float(win["high"].max() / open_rate - 1.0)
        mae = float(win["low"].min() / open_rate - 1.0)
    else:
        mfe = float(1.0 - win["low"].min() / open_rate)
        mae = float(1.0 - win["high"].max() / open_rate)
    realized = side * (float(row.get("close_rate") or 0.0) / open_rate - 1.0)
    capture = realized / mfe if mfe > 1e-6 else None
    return {
        "mfe_pct": round(mfe * 100, 3),
        "mae_pct": round(mae * 100, 3),
        "capture": round(capture, 3) if capture is not None else None,
    }


# ── report builder ──────────────────────────────────────────────────────────

def attribute_bot(name: str, db_path: Path, since_days: float | None) -> dict[str, Any] | None:
    trades = load_closed_trades(db_path, since_days)
    if trades.empty:
        return {"bot": name, "n_trades": 0}
    comps = trades.apply(decompose_trade, axis=1, result_type="expand")
    exc = trades.apply(excursions, axis=1, result_type="expand")

    agg = {k: round(float(comps[k].sum()), 2)
           for k in ("intended", "entry_slip", "exit_slip", "fees", "funding", "net", "residual")}
    captures = exc["capture"].dropna()
    by_reason = []
    trades2 = pd.concat([trades[["exit_reason"]], comps], axis=1)
    for reason, grp in trades2.groupby(trades2["exit_reason"].fillna("unknown")):
        by_reason.append({
            "exit_reason": str(reason), "n": int(len(grp)),
            "net": round(float(grp["net"].sum()), 2),
            "intended": round(float(grp["intended"].sum()), 2),
        })
    by_reason.sort(key=lambda r: r["net"])
    return {
        "bot": name,
        "n_trades": int(len(trades)),
        "components": agg,
        "execution_drag": round(agg["entry_slip"] + agg["exit_slip"] + agg["fees"], 2),
        "mfe_capture_mean": round(float(captures.mean()), 3) if len(captures) else None,
        "mfe_capture_median": round(float(captures.median()), 3) if len(captures) else None,
        "n_capture_measured": int(len(captures)),
        "mfe_mean_pct": round(float(exc["mfe_pct"].dropna().mean()), 3)
            if exc["mfe_pct"].notna().any() else None,
        "mae_mean_pct": round(float(exc["mae_pct"].dropna().mean()), 3)
            if exc["mae_pct"].notna().any() else None,
        "by_exit_reason": by_reason,
    }


def build_report(since_days: float | None = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    bots = local_config.bot_databases()
    per_bot = []
    for name, db in sorted(bots.items()):
        result = attribute_bot(name, db, since_days)
        if result is not None:
            per_bot.append(result)
    totals: dict[str, float] = {}
    for b in per_bot:
        for k, v in (b.get("components") or {}).items():
            totals[k] = round(totals.get(k, 0.0) + v, 2)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": since_days,
        "totals": totals,
        "per_bot": per_bot,
    }


def write_report(path: Path = OUTPUT_PATH, since_days: float | None = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    report = build_report(since_days)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    days = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_WINDOW_DAYS
    report = write_report(since_days=days)
    print(f"attribution over {days:.0f}d — totals: {report['totals']}")
    for b in report["per_bot"]:
        if not b.get("n_trades"):
            print(f"  {b['bot']:<10} no closed trades")
            continue
        c = b["components"]
        print(f"  {b['bot']:<10} n={b['n_trades']:<4} intended={c['intended']:>9.2f}  "
              f"slip={c['entry_slip'] + c['exit_slip']:>7.2f}  fees={c['fees']:>7.2f}  "
              f"funding={c['funding']:>7.2f}  net={c['net']:>9.2f}  "
              f"capture={b['mfe_capture_mean']}")


if __name__ == "__main__":
    main()
