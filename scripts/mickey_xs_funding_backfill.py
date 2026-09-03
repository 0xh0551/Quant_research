#!/usr/bin/env python3
"""mickey_xs_funding_backfill.py — بک‌فیلِ تاریخچهٔ کاملِ فاندینگِ bybit برای جهانِ Mickey-XS.

چرا (۲۰۲۶-۰۹-۰۳): data/funding/ (کرونِ refresh_funding.py) فقط ~۱۰۰ روزِ آخر را دارد
(limit=500 بدون since) → پوششِ فاندینگ روی WF ی ۲۶ ماهه <۱۰٪. Bybit با since صفحه‌بندی
می‌کند (۲۰۰ ردیف/درخواست ≈ ۶۷ روز)، پس کلِ تاریخچه در ~۱۰ درخواست/نماد می‌آید.
خروجی در data/funding_hist/ (جدا از فایل‌های کرون؛ لودرِ xs هر دو را ادغام می‌کند).
OI: Bybit فقط ۲۰۰ ساعتِ آخر را می‌دهد (since نادیده گرفته می‌شود) → بک‌فیل ندارد.

استفاده: uv run python scripts/mickey_xs_funding_backfill.py --bases ADA,ETH,...
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "funding_hist"


def backfill(ex, base: str, start: pd.Timestamp, quiet: bool) -> int:
    sym = f"{base}/USDT:USDT"
    path = OUT / f"bybit_{base}USDT_funding.parquet"
    since = int(start.timestamp() * 1000)
    if path.exists():
        old = pd.read_parquet(path)
        since = int(pd.Timestamp(old["timestamp"].max()).timestamp() * 1000) + 1
    else:
        old = pd.DataFrame(columns=["timestamp", "funding_rate"])
    rows: list[dict] = []
    now_ms = int(time.time() * 1000)
    window_ms = 200 * 8 * 3600 * 1000     # Bybit: since→since+limit×8h (پنجرهٔ زمانی، نه شمارشی)
    for _ in range(400):
        if since >= now_ms:
            break
        try:
            batch = ex.fetch_funding_rate_history(sym, since=since, limit=200)
        except Exception as exc:  # نمادِ بدونِ بازار/شبکه — رد شو
            if not quiet:
                print(f"  {base}: {exc}", file=sys.stderr)
            break
        if batch:
            rows.extend({"timestamp": r["timestamp"], "funding_rate": float(r["fundingRate"])}
                        for r in batch if r.get("fundingRate") is not None)
            last = batch[-1]["timestamp"]
            since = max(last + 1, since + 1)
        else:
            # پنجرهٔ خالی (قبل از لیست‌شدنِ نماد) → پنجره را جلو ببر
            since += window_ms
        time.sleep(0.15)
    if not rows:
        return len(old)
    new = pd.DataFrame(rows)
    new["timestamp"] = pd.to_datetime(new["timestamp"], unit="ms", utc=True)
    df = (pd.concat([old, new], ignore_index=True)
          .drop_duplicates("timestamp", keep="last").sort_values("timestamp")
          .reset_index(drop=True))
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    return len(df)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bases", required=True, help="comma-separated bases")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    import ccxt
    ex = ccxt.bybit({"options": {"defaultType": "swap"}})
    ex.load_markets()
    OUT.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.start, tz="UTC")
    for b in [x.strip().upper() for x in args.bases.split(",") if x.strip()]:
        n = backfill(ex, b, start, args.quiet)
        if not args.quiet:
            print(f"{b}: {n} rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
