#!/usr/bin/env python3
"""رفرشِ افزایشیِ دیتای موجود تا اسکنِ لبه‌ها روی کندل‌های تازه اجرا شود.

دو فاز دارد:
  1. کشفِ داینامیک: top 100 جفتِ Gate.io futures را بر اساسِ حجم ۲۴ساعته می‌گیرد و
     هر سه تایم‌فریمِ اصلی (4h/1h/15m) را bootstrap می‌کند (اگر پارکت وجود نداشت).
  2. رفرشِ افزایشی: برای هر parquetِ موجود در data/processed، فقط کندل‌های بعد از
     آخرین timestamp را از همان صرافی می‌گیرد و merge می‌کند. چیزی پاک نمی‌شود.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.downloader import CCXTFallbackDownloader, DownloadRequest  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
BUFFER_DAYS = 5

GATE_TOP_N = 100
DISCOVER_TIMEFRAMES = ["4h", "1h", "15m"]
BOOTSTRAP_DAYS = 730

# جفت‌های ضروری که حتی اگر Gate discovery شکست بخورد باید داشته باشیم
FALLBACK_PAIRS: list[tuple[str, str, str, str]] = [
    ("gate", "futures", "BTCUSDT", "4h"),
    ("gate", "futures", "BTCUSDT", "1h"),
    ("gate", "futures", "BTCUSDT", "15m"),
    ("gate", "futures", "ETHUSDT", "4h"),
    ("gate", "futures", "SOLUSDT", "4h"),
    ("gate", "futures", "XRPUSDT", "4h"),
    ("gate", "futures", "DOGEUSDT", "4h"),
    ("gate", "futures", "DOGEUSDT", "1h"),
    ("gate", "futures", "DOGEUSDT", "15m"),
    ("bybit", "futures", "BTCUSDT", "4h"),
    ("bybit", "futures", "ETHUSDT", "4h"),
    ("bybit", "futures", "SOLUSDT", "4h"),
]


def discover_gate_futures_pairs(n: int = GATE_TOP_N) -> list[tuple[str, str, str, str]]:
    """Top N Gate.io USDT-settled futures pairs by 24h quote volume → bootstrap list."""
    try:
        exchange = ccxt.gate({"options": {"defaultType": "swap"}})
        tickers = exchange.fetch_tickers()
        ranked = sorted(
            [
                (sym, float(t.get("quoteVolume") or 0))
                for sym, t in tickers.items()
                if sym.endswith(":USDT") and (t.get("quoteVolume") or 0) > 0
            ],
            key=lambda x: -x[1],
        )
        result = []
        for sym, _ in ranked[:n]:
            # 'BTC/USDT:USDT' → 'BTCUSDT'
            clean = sym.split(":")[0].replace("/", "")
            for tf in DISCOVER_TIMEFRAMES:
                result.append(("gate", "futures", clean, tf))
        print(f"  discovered {len(ranked[:n])} Gate pairs × {len(DISCOVER_TIMEFRAMES)} timeframes = {len(result)} datasets")
        return result
    except Exception as exc:
        print(f"  WARN  Gate discovery failed ({exc}); falling back to static pairs")
        return []


def _parse(stem: str) -> tuple[str, str, str, str]:
    """'bybit_futures_BTCUSDT_15m' → (ccxt_id, market_type, symbol, timeframe)."""
    parts = stem.split("_")
    tf, symbol = parts[-1], parts[-2]
    prefix = parts[:-2]
    ccxt_id = prefix[0] if prefix else "binance"
    market_type = prefix[1] if len(prefix) > 1 else "spot"
    return ccxt_id, market_type, symbol, tf


def _stem(ccxt_id: str, market_type: str, symbol: str, tf: str) -> str:
    return f"{ccxt_id}_{market_type}_{symbol}_{tf}"


def bootstrap_one(ccxt_id: str, market_type: str, symbol: str, tf: str) -> str:
    path = PROCESSED / f"{_stem(ccxt_id, market_type, symbol, tf)}.parquet"
    if path.exists():
        return f"exists {path.name} (skip bootstrap)"
    start = (date.today() - timedelta(days=BOOTSTRAP_DAYS)).isoformat()
    dl = CCXTFallbackDownloader(ccxt_id)
    new = dl.fetch(DownloadRequest(symbol=symbol, timeframe=tf,
                                   start=date.fromisoformat(start), end=date.today()))
    if new is None or new.empty:
        return f"WARN  {path.name}: no data returned"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    new.to_parquet(path, index=False)
    return f"bootstrap {path.name}  {len(new)} bars"


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
    # فاز ۱: کشفِ داینامیک + bootstrap
    print("discovering Gate.io top futures pairs…")
    dynamic = discover_gate_futures_pairs()
    all_bootstrap = list(dict.fromkeys(dynamic + FALLBACK_PAIRS))  # dedup, preserve order
    print(f"bootstrapping {len(all_bootstrap)} datasets (skips existing)…")
    for args in all_bootstrap:
        try:
            print("  " + bootstrap_one(*args))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL bootstrap {args}: {exc}")

    # فاز ۲: رفرشِ افزایشیِ پارکت‌های موجود
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
