#!/usr/bin/env python3
"""Cross-venue funding-rate carry scanner (public data, no keys, no LLM).

For each base traded across the four supported venues (bybit/gate/okx/hyperliquid),
fetch the current funding rate, annualize per the venue's funding interval, and
rank the best short-high-funding / long-low-funding pairs. This is the
market-neutral "carry sleeve" opportunity: collect funding on the short leg,
hedge with the long leg — no directional bet. Gross numbers; fees/borrow and
convergence risk not deducted.

Writes outputs/funding_carry.json. Cron (free):
    25 */4 * * * cd $QR_ROOT && .venv/bin/python scripts/funding_carry_scan.py --quiet >> logs/funding_carry.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "outputs"

import ccxt  # noqa: E402
import pandas as pd  # noqa: E402

VENUES = {
    "bybit": (ccxt.bybit, 3),          # 8h -> 3/day
    "gateio": (ccxt.gateio, 3),
    "okx": (ccxt.okx, 3),
    "hyperliquid": (ccxt.hyperliquid, 24),  # 1h -> 24/day
}
BASES = ["BTC", "ETH", "SOL", "ADA", "BNB", "LINK", "ARB", "DOGE", "XRP", "SUI",
         "WLD", "AAVE", "FARTCOIN", "VIRTUAL", "TAO", "JTO", "AERO"]


def scan() -> dict:
    rates: dict[str, dict] = {}
    for vname, (klass, per_day) in VENUES.items():
        try:
            ex = klass({"enableRateLimit": True, "options": {"defaultType": "swap"}})
            ex.load_markets()
        except Exception as e:
            print(f"[{vname}] init failed: {e}")
            continue
        for base in BASES:
            for sym in (f"{base}/USDT:USDT", f"{base}/USDC:USDC"):
                if sym not in ex.markets:
                    continue
                try:
                    fr = ex.fetch_funding_rate(sym)
                    r = fr.get("fundingRate")
                    if r is None:
                        continue
                    itv = fr.get("interval") or ""
                    pd_ = {"1h": 24, "2h": 12, "4h": 6, "8h": 3}.get(itv, per_day)
                    rates.setdefault(base, {})[vname] = round(float(r) * pd_ * 365 * 100, 2)
                    break
                except Exception:
                    continue
    opps = []
    for base, d in rates.items():
        if len(d) < 2:
            continue
        hi = max(d, key=d.get)
        lo = min(d, key=d.get)
        opps.append({"base": base, "short_venue": hi, "short_ann_pct": d[hi],
                     "long_venue": lo, "long_ann_pct": d[lo],
                     "gross_spread_ann_pct": round(d[hi] - d[lo], 2)})
    opps.sort(key=lambda o: o["gross_spread_ann_pct"], reverse=True)
    return {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "note": "gross annualized funding spreads; fees + convergence risk NOT deducted",
        "rates_ann_pct": rates,
        "top_carry": opps[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    payload = scan()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "funding_carry.json").write_text(json.dumps(payload, indent=2))
    if not args.quiet:
        print("top carry (gross %/yr):")
        for o in payload["top_carry"][:6]:
            print(f"  {o['base']:10} short@{o['short_venue']:12} long@{o['long_venue']:12} ≈ {o['gross_spread_ann_pct']:6.1f}%/yr")
        print("[written] outputs/funding_carry.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
