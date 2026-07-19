#!/usr/bin/env python3
"""Go-live readiness scorecard — who has EARNED real capital?

All six noches bots run dry_run (paper, $1000 wallets). Before any bot gets real
money it must pass explicit gates on its own recent paper record. This computes,
per bot, over two windows (rolling 30d, and post-fix = since the 2026-07-11
overlay/drop-list/retrain deploy):

  net PnL, profit factor, win rate, trades, max drawdown (vs the $1k paper
  wallet), a naive daily Sharpe — plus the fitness→live calibration IC from the
  learning loop.

Gates (per bot, on the post-fix window once it has enough data, else 30d):
  trades >= 30, PF >= 1.2, net > 0, maxDD <= 15% of wallet
Verdict: READY / NOT-YET (+ failing gates). Writes outputs/golive_scorecard.json.

    .venv/bin/python scripts/golive_scorecard.py

Cron (nightly, after the learner):
    40 23 * * * cd /home/h0551user/Quant_research && .venv/bin/python scripts/golive_scorecard.py --quiet >> logs/golive.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "outputs"
USER_DATA = Path("/home/h0551user/noches/user_data")
BOTS = {"Bender": "bender.sqlite", "Gadget": "gadget.sqlite", "Klaymen": "klaymen.sqlite",
        "Popeye": "popeye.sqlite", "Mickey": "mickey.sqlite", "Wall_E": "walle.sqlite"}
PAPER_WALLET = 1000.0
FIX_DEPLOY_UTC = "2026-07-11 19:00:00"  # overlay + drop-list + retrain went live

GATES = {"min_trades": 30, "min_pf": 1.2, "min_net": 0.0, "max_dd_pct": 15.0}


def _trades(db: Path, since: str | None) -> pd.DataFrame:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        q = ("SELECT close_profit_abs, close_date FROM trades "
             "WHERE is_open=0 AND close_profit_abs IS NOT NULL")
        p: tuple = ()
        if since:
            q += " AND close_date >= ?"; p = (since,)
        df = pd.read_sql_query(q + " ORDER BY close_date", con, params=p)
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


def window_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0}
    pnl = df["close_profit_abs"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    equity = PAPER_WALLET + pnl.cumsum()
    dd = (equity.cummax() - equity).max()
    daily = pnl.groupby(pd.to_datetime(df["close_date"], errors="coerce").dt.date).sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if len(daily) > 3 and daily.std() > 0 else None
    return {
        "trades": int(len(pnl)),
        "net": round(float(pnl.sum()), 2),
        "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() != 0 else None,
        "win_rate": round(float((pnl > 0).mean()), 3),
        "max_dd_pct": round(float(dd / PAPER_WALLET * 100), 2),
        "sharpe_naive": round(sharpe, 2) if sharpe is not None else None,
        "monthly_pct_naive": round(float(pnl.sum()) / PAPER_WALLET * 100 / max(len(daily), 1) * 30, 2) if len(daily) else None,
    }


def gate_check(s: dict) -> tuple[bool, list[str]]:
    fails = []
    if s.get("trades", 0) < GATES["min_trades"]:
        fails.append(f"trades<{GATES['min_trades']}")
    if (s.get("pf") or 0) < GATES["min_pf"]:
        fails.append(f"PF<{GATES['min_pf']}")
    if (s.get("net") or -1) <= GATES["min_net"]:
        fails.append("net<=0")
    if (s.get("max_dd_pct") or 100) > GATES["max_dd_pct"]:
        fails.append(f"DD>{GATES['max_dd_pct']}%")
    return (not fails), fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cutoff_30 = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    ic_by_bot = {}
    try:
        cal = json.loads((OUT / "score_calibration.json").read_text())
        ic_by_bot = {b: v.get("mean_rank_ic") for b, v in cal.get("calibration", {}).get("per_bot", {}).items()}
    except Exception:
        pass

    bots_out = {}
    for bot, f in BOTS.items():
        db = USER_DATA / f
        w30 = window_stats(_trades(db, cutoff_30))
        wpf = window_stats(_trades(db, FIX_DEPLOY_UTC))
        # judge on post-fix once it has enough trades, else on 30d
        judged = wpf if wpf.get("trades", 0) >= GATES["min_trades"] else w30
        ready, fails = gate_check(judged)
        bots_out[bot] = {
            "mode": "PAPER (dry_run)",
            "last_30d": w30,
            "post_fix": wpf,
            "judged_on": "post_fix" if judged is wpf else "last_30d",
            "calibration_ic": ic_by_bot.get(bot),
            "ready_for_live": ready,
            "failing_gates": fails,
        }

    payload = {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "paper_wallet_usd": PAPER_WALLET,
        "fix_deploy_utc": FIX_DEPLOY_UTC,
        "gates": GATES,
        "bots": bots_out,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "golive_scorecard.json").write_text(json.dumps(payload, indent=2))

    if not args.quiet:
        print(f"\n=== GO-LIVE SCORECARD (paper wallets ${PAPER_WALLET:.0f}; gates: "
              f"{GATES['min_trades']}+ trades, PF>={GATES['min_pf']}, net>0, DD<={GATES['max_dd_pct']}%) ===\n")
        hdr = f"{'bot':8} {'win':>6} {'net30d':>8} {'PF':>5} {'wr%':>5} {'DD%':>6} {'shrp':>5} {'IC':>6} {'verdict'}"
        print(hdr); print("-" * len(hdr))
        for b, d in bots_out.items():
            s = d["last_30d"]
            ic = d["calibration_ic"]
            verdict = "✅ READY" if d["ready_for_live"] else "⏳ " + ",".join(d["failing_gates"])
            print(f"{b:8} {s.get('trades',0):>6} {s.get('net',0) or 0:>8} {s.get('pf') or 0:>5} "
                  f"{(s.get('win_rate') or 0)*100:>4.0f}% {s.get('max_dd_pct') or 0:>6} "
                  f"{s.get('sharpe_naive') if s.get('sharpe_naive') is not None else '—':>5} "
                  f"{ic if ic is not None else '—':>6} {verdict}")
        print("\n[written] outputs/golive_scorecard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
