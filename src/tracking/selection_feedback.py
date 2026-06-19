"""Closed-loop selection feedback.

The nightly pair rotation picks coins purely from forward-looking fitness
(`recommend_rl_coins` / `recommend_ml_coins`). Nothing ever checked whether a
past pick actually *made money live*. This module closes that loop:

  1. `realized_performance` reads CLOSED trades from a bot's freqtrade sqlite and
     aggregates realized PnL / win-rate / trade-count per base symbol.
  2. `feedback_multiplier` turns that into a **bounded** score multiplier
     (default ±25%, and 1.0 — "no opinion" — below `min_trades`), so a coin that
     lost money live is demoted and a consistent winner is nudged up for the
     next round, without letting one lucky/unlucky streak dominate selection.
  3. `apply_feedback` applies it in-place to a rotation score table and returns
     an audit trail for the dashboards (selected score → realized result).

Everything is read-only against the bot DBs and fails safe (no DB / no closed
trades / error → empty dict → multiplier 1.0 → selection unchanged).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _base_of(pair: str) -> str:
    return pair.split("/")[0]


def realized_performance(db_path: str | Path, since_days: float = 30.0) -> dict[str, dict]:
    """{base: {trades, win_rate, avg_profit, total_profit_abs}} for CLOSED trades.

    `avg_profit` is the mean per-trade profit ratio (e.g. 0.01 = +1% per trade).
    Read-only; any failure returns {} so the caller leaves selection untouched.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT pair, close_profit, close_profit_abs FROM trades "
            "WHERE is_open=0 AND close_profit IS NOT NULL AND close_date >= ?",
            (cutoff,),
        ).fetchall()
        con.close()
    except Exception:
        return {}

    agg: dict[str, dict] = {}
    for pair, cp, cpa in rows:
        a = agg.setdefault(_base_of(pair), {"profits": [], "abs": 0.0})
        a["profits"].append(float(cp))
        a["abs"] += float(cpa or 0.0)

    out: dict[str, dict] = {}
    for base, a in agg.items():
        p = a["profits"]
        n = len(p)
        if not n:
            continue
        out[base] = {
            "trades": n,
            "win_rate": round(sum(1 for x in p if x > 0) / n, 3),
            "avg_profit": round(sum(p) / n, 5),
            "total_profit_abs": round(a["abs"], 2),
        }
    return out


def feedback_multiplier(
    perf: dict | None, *, min_trades: int = 5, max_adj: float = 0.25,
    full_scale_avg: float = 0.02,
) -> float:
    """Bounded score multiplier from realized per-trade profit.

    Below `min_trades` closed trades → 1.0 (not enough evidence to judge).
    Otherwise map mean per-trade profit through a gentle linear slope:
    `full_scale_avg` (default ±2%/trade) reaches the ±`max_adj` clamp.
    """
    if not perf or perf.get("trades", 0) < min_trades:
        return 1.0
    avg = float(perf.get("avg_profit", 0.0))
    adj = max(-max_adj, min(max_adj, (avg / full_scale_avg) * max_adj))
    return round(1.0 + adj, 4)


def apply_feedback(
    table: dict[str, dict], perf: dict[str, dict], **kw,
) -> dict[str, dict]:
    """Adjust each base's score in-place by its realized-performance multiplier.

    Returns an audit map {base: {old, new, mult, perf}} for logging / dashboards
    (only bases whose score actually changed are included).
    """
    audit: dict[str, dict] = {}
    for base, v in table.items():
        mult = feedback_multiplier(perf.get(base), **kw)
        if mult == 1.0:
            continue
        old = v.get("score", 0)
        new = int(max(0, min(100, round(old * mult))))
        if new == old:
            continue
        v["score"] = new
        audit[base] = {"old": old, "new": new, "mult": mult, "perf": perf.get(base)}
    return audit
