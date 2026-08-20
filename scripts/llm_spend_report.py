#!/usr/bin/env python3
"""Where did the LLM budget actually go?

Reads the per-call ledger (outputs/llm_calls.jsonl) and breaks spend down by caller,
model and day. The monthly total in outputs/llm_spend.json says how much is left; this
says which feature is eating it, which is the number you need before touching cadence
or tiers.

    python scripts/llm_spend_report.py                # this month, by call site
    python scripts/llm_spend_report.py --days 7       # last 7 days
    python scripts/llm_spend_report.py --by script    # group by entry-point script
    python scripts/llm_spend_report.py --daily        # add a per-day series
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "outputs" / "llm_calls.jsonl"
SPEND = ROOT / "outputs" / "llm_spend.json"


def _rows(days: float | None) -> list[dict]:
    if not LEDGER.exists():
        return []
    cutoff = None
    if days:
        cutoff = datetime.now(UTC) - timedelta(days=days)
    out = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if cutoff:
            try:
                if datetime.fromisoformat(r["ts"]) < cutoff:
                    continue
            except (KeyError, ValueError):
                continue
        out.append(r)
    return out


def _table(rows: list[dict], key: str) -> list[tuple]:
    agg: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "cost": 0.0, "in": 0, "out": 0, "think": 0, "skipped": 0})
    for r in rows:
        a = agg[str(r.get(key, "?"))]
        a["n"] += 1
        a["cost"] += float(r.get("cost_usd", 0.0) or 0.0)
        a["in"] += int(r.get("in", 0) or 0)
        a["out"] += int(r.get("out", 0) or 0)
        a["think"] += int(r.get("thinking", 0) or 0)
        if r.get("skipped"):
            a["skipped"] += 1
    return sorted(agg.items(), key=lambda kv: -kv[1]["cost"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=None, help="window in days (default: all)")
    ap.add_argument("--by", default="site", choices=["site", "script", "model", "tier", "mode"])
    ap.add_argument("--daily", action="store_true", help="also print a per-day series")
    args = ap.parse_args()

    rows = _rows(args.days)
    if not rows:
        print("no ledger rows yet — outputs/llm_calls.jsonl fills up as calls are made")
        return

    total = sum(float(r.get("cost_usd", 0.0) or 0.0) for r in rows)
    span = f"last {args.days:g}d" if args.days else "all time"
    print(f"\nLLM spend by {args.by} — {span}, {len(rows)} calls, ${total:.4f}\n")
    print(f"{args.by:44} {'calls':>6} {'$':>9} {'share':>7} {'in':>9} {'out':>8} {'think':>7}")
    print("-" * 96)
    for name, a in _table(rows, args.by):
        share = (a["cost"] / total * 100) if total else 0.0
        flag = f"  ({a['skipped']} skipped)" if a["skipped"] else ""
        print(f"{name[:44]:44} {a['n']:6d} {a['cost']:9.4f} {share:6.1f}% "
              f"{a['in']:9d} {a['out']:8d} {a['think']:7d}{flag}")

    if args.daily:
        per_day: dict[str, float] = defaultdict(float)
        for r in rows:
            per_day[str(r.get("ts", ""))[:10]] += float(r.get("cost_usd", 0.0) or 0.0)
        print("\nper day")
        print("-" * 24)
        for d in sorted(per_day):
            print(f"{d}  ${per_day[d]:.4f}")
        if len(per_day) > 1:
            avg = sum(per_day.values()) / len(per_day)
            print(f"\navg ${avg:.4f}/day -> ${avg * 30:.2f}/month at this rate")

    if SPEND.exists():
        try:
            book = json.loads(SPEND.read_text())
            mk = datetime.now(UTC).strftime("%Y-%m")
            print(f"\nmonth-to-date (authoritative counter): ${float(book.get(mk, 0.0)):.4f}")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    main()
