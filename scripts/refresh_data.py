#!/usr/bin/env python3
"""رفرشِ افزایشیِ دیتای موجود تا اسکنِ لبه‌ها روی کندل‌های تازه اجرا شود.

چهار فاز دارد:
  1. کشفِ داینامیک: top 100 جفتِ Gate.io futures را بر اساسِ حجم ۲۴ساعته می‌گیرد و
     هر سه تایم‌فریمِ اصلی (4h/1h/15m) را bootstrap می‌کند (اگر پارکت وجود نداشت).
  2. عمیق‌سازی: فایل‌هایی که کمتر از MIN_SCAN_BARS کندل دارند (و اسکن نادیده‌شان
     می‌گیرد) تا جای ممکن به عقب گسترش می‌یابند تا وارد walk-forward شوند.
  3. رفرشِ افزایشی: برای هر parquetِ موجود در data/processed، فقط کندل‌های بعد از
     آخرین timestamp را از همان صرافی می‌گیرد و merge می‌کند. چیزی پاک نمی‌شود.
  4. خلاصهٔ پوشش: outputs/data_coverage.json برای داشبوردهای مانیتورینگ.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.downloader import (  # noqa: E402
    CCXTFallbackDownloader, DownloadRequest, timeframe_to_milliseconds,
)

PROCESSED = ROOT / "data" / "processed"
COVERAGE_PATH = ROOT / "outputs" / "data_coverage.json"
BUFFER_DAYS = 5

GATE_TOP_N = 100
HL_TOP_N = 30          # top Hyperliquid perps by volume (excluding synthetics)
DISCOVER_TIMEFRAMES = ["4h", "1h", "15m"]
BOOTSTRAP_DAYS = 730

# اسکنِ wf (scan_processed_dir) فایل‌های کوتاه‌تر از این را نادیده می‌گیرد؛
# عمیق‌سازی تلاش می‌کند فایل‌ها را تا این حد برساند.
MIN_SCAN_BARS = 6000

# صرافی‌هایی که از ccxt قابل‌رفرش نیستند (دیتای موجودشان دست‌نخورده می‌ماند)
SKIP_EXCHANGES = {
    "nobitex": "not a ccxt source",
    "okx": "okx fetch_ohlcv broken in ccxt 4.5.56",
}

# محدودیتِ نگاه به عقبِ هر صرافی (بر حسب تعداد کندل). Gate برای کندل‌های قدیمی‌تر
# از ~10000 نقطه خطای INVALID_PARAM_VALUE می‌دهد؛ کمی حاشیه می‌گیریم.
MAX_LOOKBACK_BARS = {"gate": 9900}

# عمیق‌سازی حداکثر تا این تاریخ به عقب می‌رود (برای صرافی‌های بدون محدودیت)
DEEPEN_FLOOR = date(2019, 1, 1)


def _clamp_start(ccxt_id: str, tf: str, start: date) -> date:
    """شروعِ دانلود را به پنجرهٔ مجازِ صرافی محدود می‌کند."""
    max_bars = MAX_LOOKBACK_BARS.get(ccxt_id)
    if not max_bars:
        return start
    step_ms = timeframe_to_milliseconds(tf)
    earliest = datetime.now(UTC) - timedelta(milliseconds=step_ms * max_bars)
    return max(start, earliest.date() + timedelta(days=1))

# جفت‌های ضروری که حتی اگر discovery شکست بخورد باید داشته باشیم
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
    # Hyperliquid: دیتای اصلی والی — USDC perps
    ("hyperliquid", "futures", "BTCUSDC", "4h"),
    ("hyperliquid", "futures", "BTCUSDC", "1h"),
    ("hyperliquid", "futures", "BTCUSDC", "15m"),
    ("hyperliquid", "futures", "ETHUSDC", "4h"),
    ("hyperliquid", "futures", "ETHUSDC", "15m"),
    ("hyperliquid", "futures", "SOLUSDC", "4h"),
    ("hyperliquid", "futures", "SOLUSDC", "15m"),
    ("hyperliquid", "futures", "XRPUSDC", "4h"),
]


def discover_gate_futures_pairs(n: int = GATE_TOP_N) -> list[tuple[str, str, str, str]]:
    """Top N Gate.io USDT-settled futures pairs by 24h quote volume → bootstrap list.

    برای هر ارز، صرافی دوم (bybit) هم اضافه می‌شود تا گیتِ «سازگاری بین‌صرافی»
    (apply_robustness) شواهد مستقل داشته باشد؛ ارزی که فقط یک صرافی دارد عملاً
    هرگز نمی‌تواند تأیید بین‌صرافی بگیرد.
    """
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
                result.append(("bybit", "futures", clean, tf))  # صرافی دوم برای cross-venue
        print(f"  discovered {len(ranked[:n])} pairs × {len(DISCOVER_TIMEFRAMES)} timeframes × 2 venues = {len(result)} datasets")
        return result
    except Exception as exc:
        print(f"  WARN  Gate discovery failed ({exc}); falling back to static pairs")
        return []


def discover_hyperliquid_pairs(n: int = HL_TOP_N) -> list[tuple[str, str, str, str]]:
    """Top N Hyperliquid USDC perps by 24h volume → bootstrap list (Wall_E venue).

    سینتتیک‌ها (XYZ-SP500، XYZ-CL و مانند آن) و ارزهای مشکوک (base حاوی '-' یا '/')
    فیلتر می‌شوند تا فقط جفت‌های کریپتوی واقعی اضافه شوند.
    """
    try:
        exchange = ccxt.hyperliquid({"enableRateLimit": True})
        tickers = exchange.fetch_tickers()
        ranked = sorted(
            [
                (sym, float(t.get("quoteVolume") or 0))
                for sym, t in tickers.items()
                if sym.endswith(":USDC") and (t.get("quoteVolume") or 0) > 0
            ],
            key=lambda x: -x[1],
        )
        result = []
        for sym, _ in ranked:
            base = sym.split("/")[0]
            # حذف سینتتیک‌های بازار سهام/کالا: XYZ- prefix یا '-' در نام
            if "-" in base or "/" in base:
                continue
            # 'BTC/USDC:USDC' → 'BTCUSDC'
            clean = sym.split(":")[0].replace("/", "")
            for tf in DISCOVER_TIMEFRAMES:
                result.append(("hyperliquid", "futures", clean, tf))
            if len({r[2] for r in result}) >= n:
                break
        print(f"  hyperliquid discovered {len({r[2] for r in result})} pairs × {len(DISCOVER_TIMEFRAMES)} timeframes = {len(result)} datasets")
        return result
    except Exception as exc:
        print(f"  WARN  Hyperliquid discovery failed ({exc}); falling back to static pairs")
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
    start = _clamp_start(ccxt_id, tf, date.today() - timedelta(days=BOOTSTRAP_DAYS))
    dl = CCXTFallbackDownloader(ccxt_id, market_type)
    new = dl.fetch(DownloadRequest(symbol=symbol, timeframe=tf,
                                   start=start, end=date.today()))
    if new is None or new.empty:
        return f"WARN  {path.name}: no data returned"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    new.to_parquet(path, index=False)
    return f"bootstrap {path.name}  {len(new)} bars"


def deepen_one(path: Path) -> str:
    """گسترشِ تاریخچه به عقب برای فایل‌های کوتاه‌تر از MIN_SCAN_BARS."""
    ccxt_id, market_type, symbol, tf = _parse(path.stem)
    if ccxt_id in SKIP_EXCHANGES:
        return f"skip {path.name} ({ccxt_id} — {SKIP_EXCHANGES[ccxt_id]})"

    old = pd.read_parquet(path)
    if "timestamp" not in old.columns or old.empty:
        return f"skip {path.name} (no timestamp/empty)"
    if len(old) >= MIN_SCAN_BARS:
        return f"ok   {path.name} (deep enough: {len(old)} bars)"

    first_ts = pd.to_datetime(old["timestamp"]).min()
    earliest = _clamp_start(ccxt_id, tf, DEEPEN_FLOOR)
    if earliest >= (first_ts.date() - timedelta(days=1)):
        return f"skip {path.name} (exchange window exhausted @ {first_ts:%Y-%m-%d})"

    dl = CCXTFallbackDownloader(ccxt_id, market_type)
    new = dl.fetch(DownloadRequest(symbol=symbol, timeframe=tf,
                                   start=earliest, end=first_ts.date()))
    if new is None or new.empty:
        return f"ok   {path.name} (no older candles available)"

    merged = (pd.concat([new, old], ignore_index=True)
                .drop_duplicates(subset="timestamp", keep="last")
                .sort_values("timestamp")
                .reset_index(drop=True))
    added = len(merged) - len(old)
    if added <= 0:
        return f"ok   {path.name} (nothing to prepend)"
    merged.to_parquet(path, index=False)
    return f"deepen {path.name}  +{added} bars → {len(merged)} (from {merged['timestamp'].min():%Y-%m-%d})"


def refresh_one(path: Path) -> str:
    ccxt_id, market_type, symbol, tf = _parse(path.stem)
    if ccxt_id in SKIP_EXCHANGES:
        return f"skip {path.name} ({ccxt_id} — {SKIP_EXCHANGES[ccxt_id]})"

    old = pd.read_parquet(path)
    if "timestamp" not in old.columns or old.empty:
        return f"skip {path.name} (no timestamp/empty)"
    last_ts = pd.to_datetime(old["timestamp"]).max()
    start = (last_ts - pd.Timedelta(days=BUFFER_DAYS)).date()
    if start >= date.today():
        return f"ok   {path.name} (already current @ {last_ts:%Y-%m-%d})"

    dl = CCXTFallbackDownloader(ccxt_id, market_type)
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


def write_coverage(files: list[Path]) -> str:
    """خلاصهٔ پوشش دیتا برای داشبوردها (hnarimani / QR web)."""
    rows = []
    for path in files:
        try:
            ts = pd.read_parquet(path, columns=["timestamp"])["timestamp"]
            ccxt_id, market_type, symbol, tf = _parse(path.stem)
            bars = int(len(ts))
            rows.append({
                "dataset": path.stem,
                "exchange": f"{ccxt_id}_{market_type}" if market_type != "spot" else ccxt_id,
                "ccxt_id": ccxt_id,
                "symbol": symbol,
                "timeframe": tf,
                "bars": bars,
                "first": str(pd.to_datetime(ts.min()).date()) if bars else None,
                "last": str(pd.to_datetime(ts.max()).date()) if bars else None,
                "scannable": bars >= MIN_SCAN_BARS,
                "refreshable": ccxt_id not in SKIP_EXCHANGES,
                "size_mb": round(path.stat().st_size / 1e6, 2),
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"dataset": path.stem, "error": str(exc)})

    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_PATH.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "min_scan_bars": MIN_SCAN_BARS,
        "n_datasets": len(rows),
        "n_scannable": sum(1 for r in rows if r.get("scannable")),
        "datasets": rows,
    }, ensure_ascii=False), encoding="utf-8")
    return f"coverage -> {COVERAGE_PATH}"


def main() -> int:
    # فاز ۱: کشفِ داینامیک + bootstrap (Gate + Hyperliquid)
    print("discovering Gate.io top futures pairs…")
    dynamic = discover_gate_futures_pairs()
    print("discovering Hyperliquid top USDC perps…")
    dynamic += discover_hyperliquid_pairs()
    all_bootstrap = list(dict.fromkeys(dynamic + FALLBACK_PAIRS))  # dedup, preserve order
    print(f"bootstrapping {len(all_bootstrap)} datasets (skips existing)…")
    for args in all_bootstrap:
        try:
            print("  " + bootstrap_one(*args))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL bootstrap {args}: {exc}")

    # فاز ۲: عمیق‌سازی فایل‌های کوتاه (تا وارد اسکن walk-forward شوند)
    files = sorted(PROCESSED.glob("*.parquet"))
    print(f"deepening short datasets (<{MIN_SCAN_BARS} bars)…")
    for path in files:
        try:
            msg = deepen_one(path)
            if not msg.startswith("ok   "):
                print("  " + msg)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL deepen {path.name}: {exc}")

    # فاز ۳: رفرشِ افزایشیِ پارکت‌های موجود
    files = sorted(PROCESSED.glob("*.parquet"))
    print(f"refreshing {len(files)} datasets…")
    for path in files:
        try:
            print("  " + refresh_one(path))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {path.name}: {exc}")

    # فاز ۴: خلاصهٔ پوشش
    try:
        print(write_coverage(files))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL coverage: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
