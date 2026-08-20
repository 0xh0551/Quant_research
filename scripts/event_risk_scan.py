#!/usr/bin/env python3
"""Per-symbol event/risk overlay -> event_risk.json (bots scale stake by it).

    # deterministic only (free, fast — funding + vol + liquidity):
    .venv/bin/python scripts/event_risk_scan.py
    # add the Claude + web_search catalyst layer (unlocks/listings/forks):
    .venv/bin/python scripts/event_risk_scan.py --with-events
    # one venue/pairs, no write:
    .venv/bin/python scripts/event_risk_scan.py --venue bybit --pairs BTC/USDT:USDT,ADA/USDT:USDT --dry

Cron (hourly like hl_flow_scan; add --with-events on a slower cadence to cap LLM cost):
    7 * * * * cd $QR_ROOT && .venv/bin/python scripts/event_risk_scan.py >> logs/event_risk.log 2>&1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intelligence.event_risk import build  # noqa: E402

from scripts.ob_collect import _pairs_from_assignments  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue")
    ap.add_argument("--pairs", help="comma-separated (requires --venue)")
    ap.add_argument("--with-events", action="store_true", help="add Claude web_search catalyst layer")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if args.venue and args.pairs:
        venue_symbols = {args.venue: [p.strip() for p in args.pairs.split(",") if p.strip()]}
    else:
        venue_symbols = _pairs_from_assignments()
        if args.venue:
            venue_symbols = {args.venue: venue_symbols.get(args.venue, [])}
    if not any(venue_symbols.values()):
        print("no pairs (pair_assignments.json empty? pass --venue/--pairs)")
        return 1

    payload = build(venue_symbols, with_events=args.with_events, write=not args.dry)
    print(f"event_risk: {payload['n_symbols']} symbols, with_events={payload['with_events']}")
    ranked = sorted(payload["symbols"].items(), key=lambda kv: kv[1]["risk"], reverse=True)
    print(f"\n{'symbol':18} {'risk':>5}  factors(vol/fund/liq/evt)   reason")
    print("-" * 88)
    for sym, d in ranked[:15]:
        fa = d["factors"]
        print(f"{sym:18} {d['risk']:>5.3f}  "
              f"{fa['vol']:.2f}/{fa['funding']:.2f}/{fa['liquidity']:.2f}/{fa['event']:.2f}      {d['reason'][:44]}")
    if not args.dry:
        print("\n[written] outputs/event_risk.json (+ bot user_data copy if configured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
