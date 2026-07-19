#!/usr/bin/env python3
"""L2 order-book microstructure collector for the noches venues.

Mirrors the hl_flow_scan.py pattern: ccxt public fetch -> feature rows -> append
to a rolling Parquet with retention -> atomic latest-snapshot JSON for the
dashboard/bots. Public order-book endpoints need no API keys.

Pairs come from Quant_research/outputs/pair_assignments.json (the live deployed
whitelist per bot); pass --pairs to override.

    .venv/bin/python scripts/ob_collect.py                 # all rotated venues/pairs
    .venv/bin/python scripts/ob_collect.py --venue bybit --pairs BTC/USDT:USDT,SOL/USDT:USDT
    .venv/bin/python scripts/ob_collect.py --once --dry    # fetch + print, no write

Cron (intraday, like hl_flow_scan — book state is fast-moving):
    */5 * * * * cd /home/h0551user/Quant_research && .venv/bin/python scripts/ob_collect.py >> logs/ob_collect.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.execution.orderbook import book_features, make_exchange  # noqa: E402

OUT = ROOT / "outputs"
USER_DATA = Path("/home/h0551user/noches/user_data")
# primary store lives in user_data (bind-mounted into every bot container, so
# strategies can join book features at the same absolute path); QR keeps a dir
# symlink-free copy path for research use via the same file.
MS_DIR = USER_DATA / "microstructure"
SNAP_PARQUET = MS_DIR / "book_snapshots.parquet"
LEGACY_PARQUET = ROOT / "data" / "microstructure" / "book_snapshots.parquet"
LATEST_JSON = OUT / "microstructure_latest.json"
RETAIN_DAYS = 14

# bot -> (venue, config) — venue for ccxt, config for the live pair_whitelist
BOT_CFG = {
    "Bender": ("bybit", USER_DATA / "bender_config.json"),
    "Gadget": ("bybit", USER_DATA / "gadget_config.json"),
    "Mickey": ("bybit", USER_DATA / "mickey_config.json"),
    "Klaymen": ("okx", USER_DATA / "klaymen_config.json"),
    "Popeye": ("gate", USER_DATA / "popeye_config.json"),
    "Wall_E": ("hyperliquid", USER_DATA / "walle_config.json"),
}
_WL_RE = re.compile(r'"pair_whitelist"\s*:\s*\[(.*?)\]', re.DOTALL)


def _pairs_from_assignments() -> dict[str, list[str]]:
    """venue -> [pairs]: union of every bot's LIVE pair_whitelist (parsed straight
    from each config, JSONC-tolerant) plus pair_assignments.json. This covers
    Mickey/Wall_E too, which are outside the rotation file."""
    venue_pairs: dict[str, set[str]] = {}
    # 1) live whitelists from bot configs
    for _bot, (venue, cfg) in BOT_CFG.items():
        try:
            m = _WL_RE.search(cfg.read_text())
            if not m:
                continue
            for pair in re.findall(r'"([^"]+)"', m.group(1)):
                venue_pairs.setdefault(venue, set()).add(pair)
        except Exception:
            continue
    # 2) rotation assignments (may include not-yet-applied candidates)
    pa = OUT / "pair_assignments.json"
    if pa.exists():
        try:
            data = json.loads(pa.read_text())
            for _label, spec in (data.get("bots") or {}).items():
                venue = spec.get("exchange")
                if not venue:
                    continue
                for pair in (spec.get("pairs") or {}):
                    venue_pairs.setdefault(venue, set()).add(pair)
        except Exception:
            pass
    return {v: sorted(p) for v, p in venue_pairs.items()}


def collect(venue_pairs: dict[str, list[str]], now_iso: str) -> list[dict]:
    rows: list[dict] = []
    for venue, pairs in venue_pairs.items():
        if not pairs:
            continue
        try:
            ex = make_exchange(venue)
            ex.load_markets()
        except Exception as e:
            print(f"[{venue}] exchange init failed: {e}")
            continue
        for sym in pairs:
            try:
                book = ex.fetch_l2_order_book(sym, 25)
                feat = book_features(book, sym, venue)
                feat["ts"] = now_iso
                rows.append(feat)
            except Exception as e:
                print(f"[{venue}] {sym} book fetch failed: {e}")
    return rows


def _append_rolling(rows: list[dict], now: pd.Timestamp) -> None:
    MS_DIR.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([r for r in rows if r.get("ok")])
    if new.empty:
        return
    if SNAP_PARQUET.exists():
        try:
            old = pd.read_parquet(SNAP_PARQUET)
            cutoff = (now - pd.Timedelta(days=RETAIN_DAYS)).isoformat()
            old = old[old["ts"] >= cutoff]
            new = pd.concat([old, new], ignore_index=True)
        except Exception:
            pass
    new.to_parquet(SNAP_PARQUET, index=False)


def _write_latest(rows: list[dict], now_iso: str) -> None:
    latest = {
        r["symbol"]: {k: r.get(k) for k in (
            "venue", "spread_bps", "imbalance_n", "microprice_skew_bps",
            "buy_sweep_bps_500", "sell_sweep_bps_500", "buy_sweep_bps_2000", "sell_sweep_bps_2000",
        )}
        for r in rows if r.get("ok")
    }
    payload = {"generated_at": now_iso, "n_symbols": len(latest), "books": latest}
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = LATEST_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(LATEST_JSON)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue")
    ap.add_argument("--pairs", help="comma-separated (requires --venue)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true", help="print, do not write parquet/json")
    args = ap.parse_args()

    now = pd.Timestamp.utcnow().tz_localize(None)
    now_iso = now.isoformat() + "Z"

    if args.venue and args.pairs:
        venue_pairs = {args.venue: [p.strip() for p in args.pairs.split(",") if p.strip()]}
    else:
        venue_pairs = _pairs_from_assignments()
        if args.venue:
            venue_pairs = {args.venue: venue_pairs.get(args.venue, [])}
    if not any(venue_pairs.values()):
        print("no pairs (pair_assignments.json empty? pass --venue/--pairs)")
        return 1

    rows = collect(venue_pairs, now_iso)
    ok = [r for r in rows if r.get("ok")]
    print(f"[{now_iso}] fetched {len(ok)}/{len(rows)} books across {len(venue_pairs)} venue(s)")
    for r in ok[:12]:
        print(f"  {r['venue']:11} {r['symbol']:16} spread={r['spread_bps']}bps "
              f"imb={r['imbalance_n']:+.3f} buy500={r.get('buy_sweep_bps_500')} "
              f"sell2k={r.get('sell_sweep_bps_2000')}")
    if not args.dry:
        _append_rolling(rows, now)
        _write_latest(rows, now_iso)
        print(f"[written] {SNAP_PARQUET.name} (+{len(ok)} rows), {LATEST_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
