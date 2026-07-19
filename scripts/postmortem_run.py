#!/usr/bin/env python3
"""Claude trade post-mortems for the noches bots.

    # interactive / small (sync, Haiku per-trade, Sonnet synthesis):
    .venv/bin/python scripts/postmortem_run.py --bot Popeye --n 6 --synth-tier smart

    # nightly full run over losers via Batch API (50% cheaper):
    .venv/bin/python scripts/postmortem_run.py --bot Popeye --n 40 --mode batch
    # ... then when batch_status == ended:
    .venv/bin/python scripts/postmortem_run.py --bot Popeye --collect <batch_id>

Requires pair_priors.json (run learn_outcomes.py first) for the edge-prior evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intelligence.postmortem import analyze, collect  # noqa: E402
from src.llm.client import get_llm  # noqa: E402


def _print(out: dict) -> None:
    if "note" in out and "synthesis" not in out:
        print(f"{out['bot']}: {out['note']}")
        return
    print(f"\n=== Post-mortem: {out['bot']} ({out['n_analyzed']} worst losers) ===")
    print("cause counts:", out["cause_counts"])
    print("loss by cause ($):", out["loss_by_cause_quote"])
    s = out["synthesis"]
    print(f"\nHEADLINE: {s.get('headline')}")
    for i, f in enumerate(s.get("systemic_fixes", []), 1):
        print(f"  {i}. [{f['addresses_cause']}] {f['fix']}\n     ↳ {f['rationale']}")
    print("\nper-trade:")
    for t in out["trades"][:8]:
        v = t["verdict"]
        print(f"  {t['pair']:16} {t['close_profit_abs']:+8.2f}  exit_slip={t['exit_slip_bps']}bps  "
              f"[{v.get('primary_cause')}] {v.get('suggested_fix','')[:70]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--days", type=float, default=45.0)
    ap.add_argument("--mode", choices=["sync", "batch"], default="sync")
    ap.add_argument("--per-trade-tier", default="cheap")
    ap.add_argument("--synth-tier", default="reasoning")
    ap.add_argument("--collect", help="batch_id to finish a prior batch run")
    args = ap.parse_args()

    if args.collect:
        out = collect(args.bot, args.collect, since_days=args.days, n_worst=args.n, synth_tier=args.synth_tier)
        _print(out)
        return 0

    out = analyze(args.bot, n_worst=args.n, since_days=args.days, mode=args.mode,
                  per_trade_tier=args.per_trade_tier, synth_tier=args.synth_tier)
    if out.get("mode") == "batch":
        print(f"submitted batch {out['batch_id']} ({out['n_submitted']} trades). "
              f"Poll then: --collect {out['batch_id']}")
        return 0
    _print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
