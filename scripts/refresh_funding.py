"""Incremental funding-rate + open-interest history collector.

Fills the platform's biggest data gap: funding/OI exist only as on-demand
fetches, never as a stored per-bar history — so nothing downstream (feature
stores, RL training, carry research) can use them historically. This script
appends both series to Parquet on every run; venues cap how far back they
serve, so history accrues from the day collection starts. Run it early,
run it often.

Store layout (append-only, dedup by timestamp):
    data/funding/{exchange}_{BASE}USDT_funding.parquet   [timestamp, funding_rate]
    data/funding/{exchange}_{BASE}USDT_oi_1h.parquet     [timestamp, open_interest]

Symbol universe (first non-empty wins):
    --symbols BTC,ETH,...            explicit bases
    outputs/pair_assignments.json    bases currently assigned to live bots
    fallback: BTC, ETH, SOL

Cron (free):
    52 */2 * * * cd $QR_ROOT && .venv/bin/python scripts/refresh_funding.py --quiet >> logs/funding_history.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.funding import fetch_funding_history, fetch_open_interest_history  # noqa: E402

OUT_DIR = ROOT / "data" / "funding"
ASSIGNMENTS = ROOT / "outputs" / "pair_assignments.json"
DEFAULT_BASES = ["BTC", "ETH", "SOL"]
DEFAULT_VENUES = ["bybit"]


def _bases_from_assignments() -> list[str]:
    try:
        data = json.loads(ASSIGNMENTS.read_text())
    except (OSError, ValueError):
        return []
    bases: set[str] = set()
    for bot in (data.get("bots") or data or {}).values() if isinstance(data, dict) else []:
        for pair in (bot.get("pairs") or []) if isinstance(bot, dict) else []:
            base = str(pair).split("/")[0].split(":")[0]
            for q in ("USDT", "USDC", "USD"):
                if base.endswith(q) and len(base) > len(q):
                    base = base[: -len(q)]
            if base:
                bases.add(base)
    return sorted(bases)


def _merge_save(df: pd.DataFrame, path: Path, quiet: bool) -> int:
    if df.empty:
        return 0
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old, df], ignore_index=True)
    df = (
        df.drop_duplicates(subset="timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    if not quiet:
        print(f"  {path.name}: {len(df)} rows (through {df['timestamp'].iloc[-1]})")
    return len(df)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="", help="comma-separated bases (BTC,ETH,...)")
    ap.add_argument("--venues", default=",".join(DEFAULT_VENUES))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    bases = [b.strip().upper() for b in args.symbols.split(",") if b.strip()]
    if not bases:
        bases = _bases_from_assignments() or DEFAULT_BASES
    venues = [v.strip() for v in args.venues.split(",") if v.strip()]

    total = 0
    for venue in venues:
        for base in bases:
            market = f"{base}/USDT:USDT"
            stem = f"{venue}_{base}USDT"
            fr = fetch_funding_history(venue, market, limit=500)
            total += _merge_save(fr, OUT_DIR / f"{stem}_funding.parquet", args.quiet)
            oi = fetch_open_interest_history(venue, market, timeframe="1h", limit=500)
            total += _merge_save(oi, OUT_DIR / f"{stem}_oi_1h.parquet", args.quiet)
    if not args.quiet:
        print(f"[refresh_funding] {len(venues)} venue(s) x {len(bases)} base(s), {total} stored rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
