#!/usr/bin/env python3
"""رفرشِ افزایشیِ دیتای موجود تا اسکنِ لبه‌ها روی کندل‌های تازه اجرا شود.

برای هر parquetِ موجود در data/processed، فقط کندل‌های بعد از آخرین timestamp را
از همان صرافی (ccxt) می‌گیرد و merge می‌کند (dedup بر timestamp). چیزی پاک نمی‌شود؛
فقط دنباله‌ی هر سری تمدید می‌شود. best-effort است: خطای یک دیتاست بقیه را متوقف نمی‌کند.

اجرا (قبل از اسکن، در کرانِ روزانه): .venv/bin/python scripts/refresh_data.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.downloader import CCXTFallbackDownloader, DownloadRequest  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
BUFFER_DAYS = 5  # کمی هم‌پوشانی تا کندلِ ناقصِ آخر بازنویسی شود


def _parse(stem: str) -> tuple[str, str, str, str]:
    """'bybit_futures_BTCUSDT_15m' → (ccxt_id, market_type, symbol, timeframe)."""
    parts = stem.split("_")
    tf, symbol = parts[-1], parts[-2]
    prefix = parts[:-2]
    ccxt_id = prefix[0] if prefix else "binance"
    market_type = prefix[1] if len(prefix) > 1 else "spot"
    return ccxt_id, market_type, symbol, tf


def refresh_one(path: Path) -> str:
    ccxt_id, market_type, symbol, tf = _parse(path.stem)
    if ccxt_id == "nobitex":
        return f"skip {path.name} (nobitex — not a ccxt source)"

    old = pd.read_parquet(path)
    if "timestamp" not in old.columns or old.empty:
        return f"skip {path.name} (no timestamp/empty)"
    last_ts = pd.to_datetime(old["timestamp"]).max()
    start = (last_ts - pd.Timedelta(days=BUFFER_DAYS)).date()
    if start >= date.today():
        return f"ok   {path.name} (already current @ {last_ts:%Y-%m-%d})"

    dl = CCXTFallbackDownloader(ccxt_id)
    new = dl.fetch(DownloadRequest(symbol=symbol, timeframe=tf, start=start, end=date.today()))
    if new is None or new.empty:
        return f"ok   {path.name} (no new candles)"

    merged = (pd.concat([old, new], ignore_index=True)
                .drop_duplicates(subset="timestamp", keep="last")
                .sort_values("timestamp")
                .reset_index(drop=True))
    added = len(merged) - len(old)
    merged.to_parquet(path, index=False)
    return f"ok   {path.name}  +{added} bars → {len(merged)} (to {merged['timestamp'].max():%Y-%m-%d})"


def main() -> int:
    files = sorted(PROCESSED.glob("*.parquet"))
    print(f"refreshing {len(files)} datasets…")
    for path in files:
        try:
            print("  " + refresh_one(path))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {path.name}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
