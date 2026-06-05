"""FastAPI web server for the Quant Research Platform dashboard."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.backtesting.engine import BacktestConfig, VectorizedBacktester, calculate_metrics
from src.data.downloader import CCXTFallbackDownloader, DataIngestionPipeline, DownloadRequest
from src.data.nobitex import NobitexDataIngestionPipeline, NobitexDownloadRequest
from src.data.storage import ParquetDataStore
from src.strategies.rules import build_strategy_signals
from src.web.jobs import JobStatus, job_manager

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "processed"
WEB_DIR = ROOT / "web"

NOBITEX_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BTCIRT", "ETHIRT", "BNBUSDT", "ADAUSDT",
    "DOTUSDT", "LTCUSDT", "XRPUSDT", "SOLUSDT", "MATICUSDT", "DOGEUSDT",
    "LINKUSDT", "UNIUSDT", "AVAXUSDT", "ATOMUSDT", "TRXUSDT", "SHIBUSDT",
    "DAIUSDT", "USDTIRT",
]

NOBITEX_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"]
CCXT_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
ALL_STRATEGIES = ["ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion", "donchian_breakout", "atr_breakout"]

STRATEGY_LABELS = {
    "ema_trend": "EMA Trend",
    "rsi_mean_reversion": "RSI Mean Reversion",
    "bollinger_mean_reversion": "Bollinger Bands",
    "donchian_breakout": "Donchian Breakout",
    "atr_breakout": "ATR Breakout",
}

PERIODS_PER_YEAR = {
    "1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "2h": 4380, "3h": 2920, "4h": 2190, "1d": 365,
}

_symbol_cache: dict[str, list[str]] = {}
_symbol_cache_lock = threading.Lock()

app = FastAPI(title="Quant Research Platform")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ── Models ────────────────────────────────────────────────────────────────────

class DownloadRequest_(BaseModel):
    exchange: str
    symbol: str
    timeframes: list[str]
    start: str
    end: str | None = None


class ResearchRequest(BaseModel):
    datasets: list[dict[str, str]]
    strategies: list[str]
    start: str | None = None
    end: str | None = None
    return_type: str = "simple"
    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/api/exchanges")
def list_exchanges() -> dict[str, Any]:
    import ccxt
    exchanges = ["nobitex"] + sorted(ccxt.exchanges)
    return {"exchanges": exchanges}


@app.get("/api/symbols/{exchange}")
def get_symbols(exchange: str) -> dict[str, Any]:
    if exchange == "nobitex":
        return {"symbols": NOBITEX_SYMBOLS, "timeframes": NOBITEX_TIMEFRAMES}

    with _symbol_cache_lock:
        if exchange in _symbol_cache:
            return {"symbols": _symbol_cache[exchange], "timeframes": CCXT_TIMEFRAMES}

    try:
        import ccxt
        ex_class = getattr(ccxt, exchange, None)
        if ex_class is None:
            raise HTTPException(status_code=404, detail=f"Exchange '{exchange}' not found")
        ex = ex_class({"enableRateLimit": True})
        markets = ex.load_markets()
        symbols = sorted({
            k.replace("/", "")
            for k in markets
            if any(k.endswith(f"/{q}") for q in ("USDT", "BTC", "ETH", "BNB"))
            and ":" not in k
        })
        with _symbol_cache_lock:
            _symbol_cache[exchange] = symbols
        return {"symbols": symbols, "timeframes": CCXT_TIMEFRAMES}
    except HTTPException:
        raise
    except Exception as exc:
        return {"symbols": [], "timeframes": CCXT_TIMEFRAMES, "error": str(exc)}


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("*.parquet"))
    items = []
    for path in files:
        try:
            df = pd.read_parquet(path)
            parts = path.stem.split("_")
            timeframe = parts[-1] if parts else "?"
            known_exchanges = {"binance", "nobitex", "bybit", "okx", "kucoin", "gateio"}
            if parts and parts[0].lower() in known_exchanges:
                exchange = parts[0].lower()
                symbol = "_".join(parts[1:-1])
            else:
                exchange = "unknown"
                symbol = "_".join(parts[:-1])
            ts = df["timestamp"] if "timestamp" in df.columns else pd.Series(dtype="datetime64[ns]")
            items.append({
                "file": path.name,
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": len(df),
                "start": str(ts.min())[:10] if len(ts) else "",
                "end": str(ts.max())[:10] if len(ts) else "",
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
        except Exception:
            pass
    return {"items": items, "total": len(items)}


@app.post("/api/download")
def start_download(req: DownloadRequest_, background_tasks: BackgroundTasks) -> dict[str, str]:
    job_id = job_manager.create("download")
    background_tasks.add_task(_run_download, job_id, req)
    return {"job_id": job_id}


@app.post("/api/research")
def start_research(req: ResearchRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    job_id = job_manager.create("research")
    background_tasks.add_task(_run_research, job_id, req)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def generator():
        for _ in range(300):
            data = job_manager.get_dict(job_id)
            if data is None:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            yield f"data: {json.dumps(data)}\n\n"
            if data["status"] in ("done", "error"):
                return
            await asyncio.sleep(0.6)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/result")
def get_job_result(job_id: str) -> dict[str, Any]:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.result or {}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": job_manager.list_recent(30)}


@app.get("/api/insights")
def get_insights() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("*.parquet"))
    if not files:
        return {"insights": []}
    results = []
    for path in files:
        try:
            result = _compute_insight(path)
            if result:
                results.append(result)
        except Exception:
            pass
    results.sort(key=lambda x: x["best_sharpe"], reverse=True)
    return {"insights": results}


# ── Exchange-prefixed store (names files as {exchange}_{symbol}_{tf}.parquet) ──

class _ExchangePrefixedStore(ParquetDataStore):
    def __init__(self, root: Path, exchange: str) -> None:
        super().__init__(root)
        self._exchange = exchange

    def path_for(self, symbol: str, timeframe: str) -> Path:
        return self.root / f"{self._exchange}_{symbol}_{timeframe}.parquet"


# ── Background tasks ──────────────────────────────────────────────────────────

def _run_download(job_id: str, req: DownloadRequest_) -> None:
    job_manager.update(job_id, status=JobStatus.RUNNING, message="شروع دانلود...")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        store = ParquetDataStore(DATA_DIR)
        total = len(req.timeframes)
        start_date = date.fromisoformat(req.start)
        end_date = date.fromisoformat(req.end) if req.end else None

        for i, tf in enumerate(req.timeframes):
            job_manager.update(
                job_id,
                progress=round(i / total * 100, 1),
                message=f"دانلود {req.symbol} {tf} از {req.exchange}...",
            )
            # Use exchange-prefixed store so files are named {exchange}_{symbol}_{tf}.parquet
            exch_store = _ExchangePrefixedStore(DATA_DIR, req.exchange)
            if req.exchange == "nobitex":
                dl = NobitexDataIngestionPipeline(exch_store)
                dl.run(NobitexDownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date
                ))
            elif req.exchange == "binance":
                from src.data.downloader import BinanceBulkDownloader
                pipeline = DataIngestionPipeline(
                    exch_store,
                    bulk_downloader=BinanceBulkDownloader(),
                    fallback_downloader=CCXTFallbackDownloader("binance"),
                )
                pipeline.run(DownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date
                ))
            else:
                pipeline = DataIngestionPipeline(
                    exch_store,
                    fallback_downloader=CCXTFallbackDownloader(req.exchange),
                )
                pipeline.run(DownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date
                ))

        job_manager.update(
            job_id,
            status=JobStatus.DONE,
            progress=100.0,
            message=f"دانلود {req.symbol} کامل شد ({total} تایم‌فریم)",
        )
    except Exception as exc:
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc), message=f"خطا: {exc}")


def _run_research(job_id: str, req: ResearchRequest) -> None:
    job_manager.update(job_id, status=JobStatus.RUNNING, message="شروع بک‌تست...")
    try:
        store = ParquetDataStore(DATA_DIR)
        total = len(req.datasets) * len(req.strategies)
        step = 0
        all_results: list[dict[str, Any]] = []

        for ds in req.datasets:
            exchange = ds.get("exchange", "")
            symbol = ds.get("symbol", "")
            tf = ds.get("timeframe", "")
            df = store.read(symbol, tf) if not exchange else pd.read_parquet(
                DATA_DIR / f"{exchange}_{symbol}_{tf}.parquet"
            )
            if df.empty:
                step += len(req.strategies)
                continue

            if req.start:
                df = df[df["timestamp"] >= pd.Timestamp(req.start, tz="UTC")]
            if req.end:
                df = df[df["timestamp"] <= pd.Timestamp(req.end, tz="UTC")]
            df = df.reset_index(drop=True)
            if len(df) < 50:
                step += len(req.strategies)
                continue

            ppy = PERIODS_PER_YEAR.get(tf, 365)
            config = BacktestConfig(
                initial_capital=req.initial_capital,
                fee_bps=req.fee_bps,
                slippage_bps=req.slippage_bps,
                periods_per_year=ppy,
            )
            backtester = VectorizedBacktester(config)
            bh_result = backtester.run(df, pd.Series(1.0, index=df.index))
            timestamps = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M").tolist()
            price = _downsample(df["close"].tolist(), 1000)
            price_ts = _downsample(timestamps, 1000)
            bh_equity = _downsample(bh_result.equity.tolist(), 1000)

            dataset_entry: dict[str, Any] = {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": tf,
                "dataset_id": f"{exchange}_{symbol}_{tf}",
                "rows": len(df),
                "start": str(df["timestamp"].min())[:10],
                "end": str(df["timestamp"].max())[:10],
                "price": price,
                "timestamps": price_ts,
                "buy_hold_equity": bh_equity,
                "buy_hold_metrics": bh_result.metrics,
                "strategies": [],
                "regime_bands": _detect_regimes(df),
                "monthly_returns": _monthly_heatmap(bh_result.returns, df["timestamp"]),
            }

            for strategy in req.strategies:
                step += 1
                job_manager.update(
                    job_id,
                    progress=round(step / total * 90, 1),
                    message=f"بک‌تست {STRATEGY_LABELS.get(strategy, strategy)} روی {symbol} {tf}...",
                )
                try:
                    signals = build_strategy_signals(df, strategy)
                    result = backtester.run(df, signals)
                    log_returns = np.log1p(result.returns)
                    equity_ds = _downsample(result.equity.tolist(), 1000)
                    dd_ds = _downsample((result.equity / result.equity.cummax() - 1).tolist(), 1000)
                    dataset_entry["strategies"].append({
                        "name": strategy,
                        "label": STRATEGY_LABELS.get(strategy, strategy),
                        "metrics": result.metrics,
                        "log_metrics": _log_metrics(log_returns, ppy),
                        "equity": equity_ds,
                        "drawdown": dd_ds,
                    })
                except Exception as exc:
                    dataset_entry["strategies"].append({"name": strategy, "error": str(exc)})

            all_results.append(dataset_entry)

        job_manager.update(
            job_id,
            status=JobStatus.DONE,
            progress=100.0,
            message=f"ریسرچ کامل شد — {len(all_results)} دیتاست، {len(req.strategies)} استراتژی",
            result={"datasets": all_results},
        )
    except Exception as exc:
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc), message=f"خطا: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _downsample(data: list, max_pts: int) -> list:
    if len(data) <= max_pts:
        return data
    step = len(data) / max_pts
    return [data[int(i * step)] for i in range(max_pts)]


def _log_metrics(log_returns: pd.Series, ppy: int) -> dict[str, float]:
    if log_returns.empty:
        return {}
    total_log = float(log_returns.sum())
    vol = float(log_returns.std() * np.sqrt(ppy))
    mean_ann = float(log_returns.mean() * ppy)
    sharpe = mean_ann / vol if vol else 0.0
    return {"total_log_return": total_log, "annualized_log_return": mean_ann, "log_sharpe": sharpe}


def _detect_regimes(df: pd.DataFrame) -> list[dict[str, Any]]:
    if len(df) < 50:
        return []
    close = df["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ts = df["timestamp"]
    bands = []
    current_regime = None
    band_start = None

    for i in range(len(df)):
        regime = "up" if ema20.iloc[i] > ema50.iloc[i] else "down"
        if regime != current_regime:
            if current_regime is not None:
                bands.append({
                    "regime": current_regime,
                    "start": str(ts.iloc[band_start])[:10],
                    "end": str(ts.iloc[i - 1])[:10],
                    "start_idx": band_start,
                    "end_idx": i - 1,
                })
            current_regime = regime
            band_start = i

    if current_regime is not None and band_start is not None:
        bands.append({
            "regime": current_regime,
            "start": str(ts.iloc[band_start])[:10],
            "end": str(ts.iloc[-1])[:10],
            "start_idx": band_start,
            "end_idx": len(df) - 1,
        })
    return bands


def _monthly_heatmap(returns: pd.Series, timestamps: pd.Series) -> list[dict[str, Any]]:
    try:
        df = pd.DataFrame({"r": returns.values, "ts": timestamps.values})
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["year"] = df["ts"].dt.year
        df["month"] = df["ts"].dt.month
        monthly = df.groupby(["year", "month"])["r"].apply(
            lambda x: float((1 + x).prod() - 1)
        ).reset_index()
        return monthly.rename(columns={"r": "return"}).to_dict(orient="records")
    except Exception:
        return []


def _compute_insight(path: Path) -> dict[str, Any] | None:
    parts = path.stem.split("_")
    timeframe = parts[-1] if parts else "?"
    known_exchanges = {"binance", "nobitex", "bybit", "okx", "kucoin"}
    if parts and parts[0].lower() in known_exchanges:
        exchange = parts[0].lower()
        symbol = "_".join(parts[1:-1])
    else:
        exchange = "unknown"
        symbol = "_".join(parts[:-1])

    df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
    if len(df) < 100:
        return None

    cutoff = df["timestamp"].max() - pd.Timedelta(days=90)
    recent = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    if len(recent) < 30:
        recent = df.tail(200).reset_index(drop=True)

    ppy = PERIODS_PER_YEAR.get(timeframe, 365)
    config = BacktestConfig(periods_per_year=ppy)
    backtester = VectorizedBacktester(config)

    scores: dict[str, float] = {}
    for strat in ALL_STRATEGIES:
        try:
            signals = build_strategy_signals(recent, strat)
            result = backtester.run(recent, signals)
            scores[strat] = result.metrics.get("sharpe", 0.0)
        except Exception:
            scores[strat] = 0.0

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    regime = _current_regime(recent)
    momentum = _price_momentum(recent)

    return {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "dataset_id": f"{exchange}_{symbol}_{timeframe}",
        "file": path.name,
        "rows": len(df),
        "last_date": str(df["timestamp"].max())[:10],
        "regime": regime,
        "momentum": momentum,
        "best_strategy": best,
        "best_label": STRATEGY_LABELS.get(best, best),
        "best_sharpe": round(scores[best], 3),
        "strategy_scores": {k: round(v, 3) for k, v in scores.items()},
    }


def _current_regime(df: pd.DataFrame) -> str:
    close = df["close"]
    if len(close) < 50:
        return "unknown"
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    returns = close.pct_change().dropna()
    autocorr = float(returns.autocorr(lag=1)) if len(returns) > 5 else 0.0
    if ema20.iloc[-1] > ema50.iloc[-1] and autocorr > 0.02:
        return "trending_up"
    elif ema20.iloc[-1] < ema50.iloc[-1] and autocorr > 0.02:
        return "trending_down"
    elif autocorr < -0.03:
        return "mean_reverting"
    return "ranging"


def _price_momentum(df: pd.DataFrame) -> float:
    close = df["close"]
    if len(close) < 20:
        return 0.0
    return float((close.iloc[-1] / close.iloc[-20] - 1) * 100)
