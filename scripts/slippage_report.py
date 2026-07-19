#!/usr/bin/env python3
"""Execution-quality report for the noches bots.

Reads each bot's freqtrade sqlite (read-only), computes slippage / taker-mix /
fill-latency / non-fill rate, writes a machine-readable JSON the dashboard can
mount, and prints a human summary.

    .venv/bin/python scripts/slippage_report.py            # 45d window
    .venv/bin/python scripts/slippage_report.py --days 30
    .venv/bin/python scripts/slippage_report.py --quiet    # JSON only

Cron (mirror the hl_flow_scan line, but this is cheap/read-only so daily is plenty):
    15 6 * * * cd /home/h0551user/Quant_research && .venv/bin/python scripts/slippage_report.py --quiet >> logs/slippage.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # load-bearing: run from repo root without install

from src.execution.slippage import fleet_report  # noqa: E402

OUT = ROOT / "outputs" / "execution_report.json"


def _fmt(x, suffix="", nd=2):
    return "n/a" if x is None else f"{x:,.{nd}f}{suffix}"


def print_summary(rep: dict) -> None:
    f = rep["fleet"]
    print(f"\n=== Execution quality — last {rep['window_days']}d ===")
    print(
        f"Fleet gross PnL: {_fmt(f['gross_pnl_quote'])}  |  "
        f"slippage drag: {_fmt(f['roundtrip_slip_cost_quote'])} "
        f"({_fmt(f['slip_pct_of_gross'], '%', 1)} of gross)  |  "
        f"annualized drag: {_fmt(f['annualized_slip_drag_quote'])}"
    )
    print(f"Notional traded: {_fmt(f['notional_traded_quote'])}\n")
    print("  slip$ = order-level realised slippage cost (taker+maker); cxl% = limit non-fill rate\n")
    hdr = f"{'bot':8} {'trades':>6} {'gross':>10} {'slip$':>8} {'%gross':>7} {'tkr_bps':>7} {'tkr$':>8} {'lat_p50':>7} {'cxl%':>6}"
    print(hdr)
    print("-" * len(hdr))
    for b, d in rep["bots"].items():
        if d.get("n_trades", 0) == 0:
            print(f"{b:8} {'0':>6}   (no closed trades in window)")
            continue
        o = d.get("orders", {})
        cxl = o.get("limit_cancel_rate")
        print(
            f"{b:8} {d['n_trades']:>6} {_fmt(d.get('gross_pnl_quote')):>10} "
            f"{_fmt(d.get('slip_cost_quote')):>8} {_fmt(d.get('slip_pct_of_gross'),'',1):>7} "
            f"{_fmt(o.get('taker_slip_bps_wavg')):>7} {_fmt(o.get('taker_slip_cost_quote')):>8} "
            f"{_fmt(o.get('market_fill_latency_p50_s'),'s',1):>7} "
            f"{_fmt(None if cxl is None else cxl*100,'',1):>6}"
        )
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=45.0)
    ap.add_argument("--quiet", action="store_true", help="write JSON only, no stdout table")
    args = ap.parse_args()

    rep = fleet_report(since_days=args.days)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2))
    if not args.quiet:
        print_summary(rep)
        print(f"[written] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
