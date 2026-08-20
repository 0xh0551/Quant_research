#!/usr/bin/env python3
"""Close the QR learning loop: read the write-only outcome ledger and emit
persisted priors, fitness calibration, and a retrain/drop priority list.

    .venv/bin/python scripts/learn_outcomes.py
    .venv/bin/python scripts/learn_outcomes.py --half-life 21 --quiet

Cron (after the nightly rotation has appended the day's ledger rows):
    30 23 * * * cd $QR_ROOT && .venv/bin/python scripts/learn_outcomes.py --quiet >> logs/learn_outcomes.log 2>&1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # load-bearing: run from repo root without install

from src.tracking.outcome_learner import run  # noqa: E402


def print_summary(res: dict) -> None:
    m, cal = res["meta"], res["calibration"]
    print(f"\n=== QR learning loop — {m['ledger_rows']} ledger rows, bots {m['bots']} ===")
    pooled = cal.get("pooled", {})
    if pooled:
        print(
            f"Fitness->live calibration (pooled rank-IC): {pooled['mean_rank_ic']:+.3f} "
            f"over {pooled['n_bot_days']} bot-days, "
            f"{pooled['hit_rate_ic_positive']*100:.0f}% days positive"
        )
        print(f"  -> {pooled['verdict']}")
    print("  per-bot rank-IC:", {b: v["mean_rank_ic"] for b, v in cal.get("per_bot", {}).items()})

    prio = res["retrain_priority"]
    from collections import Counter
    print("\nAttribution actions:", dict(Counter(p["action"] for p in prio)))
    flagged = [p for p in prio if p["action"] in ("retrain", "drop")][:12]
    if flagged:
        print(f"\n{'bot':8} {'base':10} {'action':8} {'prio':>6} {'edge/trd':>9} {'score':>6} {'trades':>6} {'wr':>5}")
        print("-" * 66)
        for p in flagged:
            print(
                f"{p['bot']:8} {p['base']:10} {p['action']:8} {p['priority']:>6.3f} "
                f"{p['decayed_avg_profit']*100:>8.2f}% {p['latest_selected_score']:>6} "
                f"{p['latest_trades']:>6} {(p['latest_win_rate'] or 0)*100:>4.0f}%"
            )
    print("\n[written] outputs/{pair_priors,score_calibration,retrain_priority}.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--half-life", type=float, default=14.0, help="EWMA half-life in days for the prior")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    res = run(half_life_days=args.half_life, write=True)
    if not args.quiet:
        print_summary(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
