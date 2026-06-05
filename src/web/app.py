"""FastAPI web server for the Quant Research Platform dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import ccxt as _ccxt
import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.backtesting.engine import BacktestConfig, VectorizedBacktester
from src.data.downloader import CCXTFallbackDownloader, DataIngestionPipeline, DownloadRequest
from src.data.nobitex import NobitexDataIngestionPipeline, NobitexDownloadRequest
from src.data.storage import ParquetDataStore
from src.logging_config import setup_logging, tail_log
from src.strategies.rules import build_strategy_signals
from src.web.jobs import JobStatus, job_manager

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "processed"
WEB_DIR = ROOT / "web"
LOG_DIR = ROOT / "logs"

setup_logging(level="INFO", log_dir=LOG_DIR)
logger = logging.getLogger(__name__)

# All supported exchanges (CCXT + nobitex) — computed once at startup
_ALL_KNOWN_EXCHANGES: frozenset[str] = frozenset(_ccxt.exchanges) | {"nobitex"}

NOBITEX_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BTCIRT", "ETHIRT", "BNBUSDT", "ADAUSDT",
    "DOTUSDT", "LTCUSDT", "XRPUSDT", "SOLUSDT", "MATICUSDT", "DOGEUSDT",
    "LINKUSDT", "UNIUSDT", "AVAXUSDT", "ATOMUSDT", "TRXUSDT", "SHIBUSDT",
    "DAIUSDT", "USDTIRT",
]

NOBITEX_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"]
CCXT_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
KNOWN_TF_SET = {"1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"}

ALL_STRATEGIES = [
    "ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion",
    "donchian_breakout", "atr_breakout", "macd_cross", "stochastic_mr",
    "ml_signal",
]

STRATEGY_LABELS = {
    "ema_trend": "EMA Trend",
    "rsi_mean_reversion": "RSI Mean Reversion",
    "bollinger_mean_reversion": "Bollinger Bands",
    "donchian_breakout": "Donchian Breakout",
    "atr_breakout": "ATR Breakout",
    "macd_cross": "MACD Cross",
    "stochastic_mr": "Stochastic MR",
    "ml_signal": "ML Signal (GBM)",
}

PERIODS_PER_YEAR = {
    "1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "2h": 4380, "3h": 2920, "4h": 2190, "1d": 365,
}

BARS_30D = {
    "1m": 43200, "5m": 8640, "15m": 2880, "30m": 1440,
    "1h": 720, "2h": 360, "3h": 240, "4h": 180, "1d": 30,
}

_symbol_cache: dict[str, list[str]] = {}
_symbol_cache_lock = threading.Lock()

app = FastAPI(title="Quant Research Platform")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.middleware("http")
async def _log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - t0) * 1000
    if not request.url.path.startswith("/api/jobs/") or "events" not in request.url.path:
        logger.info("%s %s → %s  (%.0f ms)", request.method, request.url.path, response.status_code, elapsed)
    return response


# ── Models ────────────────────────────────────────────────────────────────────

class DownloadRequestBody(BaseModel):
    exchange: str
    symbol: str
    timeframes: list[str]
    start: str
    end: str | None = None
    market_type: str = "spot"


class ResearchRequest(BaseModel):
    datasets: list[dict[str, str]]
    strategies: list[str]
    start: str | None = None
    end: str | None = None
    return_type: str = "simple"
    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0


class DetailedInsightRequest(BaseModel):
    filename: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/api/exchanges")
def list_exchanges() -> dict[str, Any]:
    return {"exchanges": ["nobitex", *sorted(_ccxt.exchanges)]}


@app.get("/api/symbols/{exchange}")
def get_symbols(exchange: str) -> dict[str, Any]:
    if exchange == "nobitex":
        return {"symbols": NOBITEX_SYMBOLS, "timeframes": NOBITEX_TIMEFRAMES}

    with _symbol_cache_lock:
        if exchange in _symbol_cache:
            return {"symbols": _symbol_cache[exchange], "timeframes": CCXT_TIMEFRAMES}

    try:
        ex_class = getattr(_ccxt, exchange, None)
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
            info = _parse_dataset_id(path)
            ts = df["timestamp"] if "timestamp" in df.columns else pd.Series(dtype="datetime64[ns]")
            items.append({
                "file": path.name,
                "exchange": info["exchange"],
                "symbol": info["symbol"],
                "timeframe": info["timeframe"],
                "market_type": info["market_type"],
                "rows": len(df),
                "start": str(ts.min())[:10] if len(ts) else "",
                "end": str(ts.max())[:10] if len(ts) else "",
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
        except Exception:
            pass
    return {"items": items, "total": len(items)}


@app.delete("/api/inventory/{filename}")
def delete_dataset(filename: str) -> dict[str, str]:
    path = DATA_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if path.suffix != ".parquet":
        raise HTTPException(status_code=400, detail="Only .parquet files can be deleted")
    path.unlink()
    return {"status": "deleted", "file": filename}


@app.post("/api/download")
def start_download(req: DownloadRequestBody, background_tasks: BackgroundTasks) -> dict[str, str]:
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
    async def generator() -> AsyncGenerator[str, None]:
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


@app.get("/api/logs")
def get_logs(n: int = 200, level: str = "all") -> dict[str, Any]:
    """Return the last N log lines, optionally filtered by level."""
    lines = tail_log(LOG_DIR, "app.log", lines=n)
    if level != "all":
        lvl = level.upper()
        lines = [ln for ln in lines if f"  {lvl}  " in ln or f"  {lvl} " in ln]
    return {"lines": [ln.rstrip("\n") for ln in lines], "total": len(lines)}


@app.get("/api/logs/errors")
def get_error_logs(n: int = 100) -> dict[str, Any]:
    lines = tail_log(LOG_DIR, "errors.log", lines=n)
    return {"lines": [ln.rstrip("\n") for ln in lines], "total": len(lines)}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": job_manager.list_recent(30)}


@app.get("/api/insights")
def get_insights() -> dict[str, Any]:
    """Quick overview of all datasets — used to populate the dataset selector."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        try:
            info = _parse_dataset_id(path)
            df = pd.read_parquet(path)
            items.append({
                "file": path.name,
                "exchange": info["exchange"],
                "symbol": info["symbol"],
                "timeframe": info["timeframe"],
                "rows": len(df),
                "start": str(df["timestamp"].min())[:10] if len(df) else "",
                "end": str(df["timestamp"].max())[:10] if len(df) else "",
            })
        except Exception:
            pass
    return {"datasets": items}


@app.post("/api/insights/detailed")
def get_detailed_insights(req: DetailedInsightRequest) -> dict[str, Any]:
    """Deep rolling-window analysis for a single dataset."""
    path = DATA_DIR / req.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
    if len(df) < 50:
        raise HTTPException(status_code=422, detail="Insufficient data (need ≥ 50 bars)")

    info = _parse_dataset_id(path)
    tf = info["timeframe"]
    ppy = PERIODS_PER_YEAR.get(tf, 365)
    config = BacktestConfig(periods_per_year=ppy)
    backtester = VectorizedBacktester(config)

    # Full-period results
    bh_result = backtester.run(df, pd.Series(1.0, index=df.index))
    full_metrics: dict[str, Any] = {}
    full_equities: dict[str, list] = {}
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(df, strat)
            res = backtester.run(df, sigs)
            full_metrics[strat] = res.metrics
            full_equities[strat] = _downsample(res.equity.tolist(), 800)
        except Exception:
            full_metrics[strat] = {}

    # Rolling-window best-strategy analysis
    window = max(20, BARS_30D.get(tf, 30))
    n = len(df)
    strategy_windows: list[dict[str, Any]] = []
    oracle_pos = pd.Series(0.0, index=df.index)
    wf_pos = pd.Series(0.0, index=df.index)
    prev_best = "ema_trend"

    win_start = 0
    while win_start < n - window:
        win_end = min(win_start + window, n)
        win_df = df.iloc[win_start:win_end].reset_index(drop=True)
        best_strat, best_sharpe = _best_strategy_in_window(win_df, config)

        # Oracle: look-ahead best strategy for this window
        try:
            oracle_sigs = build_strategy_signals(df, best_strat)
            oracle_pos.iloc[win_start:win_end] = oracle_sigs.iloc[win_start:win_end].values
        except Exception:
            pass

        # Walk-forward: previous window's best strategy applied to current window
        try:
            wf_sigs = build_strategy_signals(df, prev_best)
            wf_pos.iloc[win_start:win_end] = wf_sigs.iloc[win_start:win_end].values
        except Exception:
            pass

        strategy_windows.append({
            "start_idx": win_start,
            "end_idx": win_end - 1,
            "start": str(df["timestamp"].iloc[win_start])[:10],
            "end": str(df["timestamp"].iloc[win_end - 1])[:10],
            "best_strategy": best_strat,
            "best_label": STRATEGY_LABELS.get(best_strat, best_strat),
            "best_sharpe": round(best_sharpe, 3),
        })
        prev_best = best_strat
        win_start += window

    oracle_result = backtester.run(df, oracle_pos)
    wf_result = backtester.run(df, wf_pos)

    timestamps = _downsample(df["timestamp"].dt.strftime("%Y-%m-%d %H:%M").tolist(), 800)

    # Recent insight
    cutoff = df["timestamp"].max() - pd.Timedelta(days=90)
    recent = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    if len(recent) < 30:
        recent = df.tail(200).reset_index(drop=True)
    recent_scores = {}
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(recent, strat)
            res = backtester.run(recent, sigs)
            recent_scores[strat] = round(res.metrics.get("sharpe", 0.0), 3)
        except Exception:
            recent_scores[strat] = 0.0

    best_now = max(recent_scores, key=recent_scores.get)  # type: ignore[arg-type]
    current_regime = _current_regime(recent)
    recommendation = _build_recommendation(
        best_now, current_regime, strategy_windows, recent_scores
    )

    return {
        "info": info,
        "rows": n,
        "start": str(df["timestamp"].min())[:10],
        "end": str(df["timestamp"].max())[:10],
        "buy_hold_metrics": bh_result.metrics,
        "strategy_metrics": full_metrics,
        "oracle_metrics": oracle_result.metrics,
        "wf_metrics": wf_result.metrics,
        "buy_hold_equity": _downsample(bh_result.equity.tolist(), 800),
        "oracle_equity": _downsample(oracle_result.equity.tolist(), 800),
        "wf_equity": _downsample(wf_result.equity.tolist(), 800),
        "strategy_equities": full_equities,
        "timestamps": timestamps,
        "strategy_windows": strategy_windows,
        "current_regime": current_regime,
        "momentum": _price_momentum(df),
        "recent_scores": recent_scores,
        "best_now": best_now,
        "best_now_label": STRATEGY_LABELS.get(best_now, best_now),
        "recommendation": recommendation,
    }


# ── Exchange-prefixed store ────────────────────────────────────────────────────

class _ExchangePrefixedStore(ParquetDataStore):
    def __init__(self, root: Path, exchange: str, market_type: str = "spot") -> None:
        super().__init__(root)
        self._exchange = exchange
        self._market_type = market_type

    def path_for(self, symbol: str, timeframe: str) -> Path:
        if self._market_type == "spot":
            return self.root / f"{self._exchange}_{symbol}_{timeframe}.parquet"
        return self.root / f"{self._exchange}_{self._market_type}_{symbol}_{timeframe}.parquet"


# ── Background tasks ──────────────────────────────────────────────────────────

def _run_download(job_id: str, req: DownloadRequestBody) -> None:
    _log = logging.getLogger("quant.download")
    _log.info(
        "Download started  job=%s  exchange=%s  symbol=%s  market=%s  tfs=%s",
        job_id, req.exchange, req.symbol, req.market_type, req.timeframes,
    )
    job_manager.update(job_id, status=JobStatus.RUNNING, message="شروع دانلود...")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        total = len(req.timeframes)
        start_date = date.fromisoformat(req.start)
        end_date = date.fromisoformat(req.end) if req.end else None

        for i, tf in enumerate(req.timeframes):
            msg = f"دانلود {req.symbol} {tf} ({req.market_type}) از {req.exchange}..."
            _log.info("  [%d/%d] %s", i + 1, total, msg)
            job_manager.update(job_id, progress=round(i / total * 100, 1), message=msg)
            store = _ExchangePrefixedStore(DATA_DIR, req.exchange, req.market_type)
            if req.exchange == "nobitex":
                dl = NobitexDataIngestionPipeline(store)
                dl.run(NobitexDownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date,
                ))
            elif req.exchange == "binance":
                from src.data.downloader import BinanceBulkDownloader
                pipeline = DataIngestionPipeline(
                    store,
                    bulk_downloader=BinanceBulkDownloader(market_type=req.market_type),
                    fallback_downloader=CCXTFallbackDownloader("binance"),
                )
                pipeline.run(DownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date,
                ))
            else:
                pipeline = DataIngestionPipeline(
                    store,
                    fallback_downloader=CCXTFallbackDownloader(req.exchange),
                )
                pipeline.run(DownloadRequest(
                    symbol=req.symbol, timeframe=tf, start=start_date, end=end_date,
                ))

        done_msg = f"دانلود {req.symbol} کامل شد ({total} تایم‌فریم)"
        _log.info("Download done  job=%s  %s", job_id, done_msg)
        job_manager.update(job_id, status=JobStatus.DONE, progress=100.0, message=done_msg)
    except Exception as exc:
        _log.exception("Download failed  job=%s  error=%s", job_id, exc)
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc), message=f"خطا: {exc}")


def _run_research(job_id: str, req: ResearchRequest) -> None:
    _log = logging.getLogger("quant.research")
    _log.info(
        "Research started  job=%s  datasets=%d  strategies=%s",
        job_id, len(req.datasets), req.strategies,
    )
    job_manager.update(job_id, status=JobStatus.RUNNING, message="شروع بک‌تست...")
    try:
        total = len(req.datasets) * len(req.strategies)
        step = 0
        all_results: list[dict[str, Any]] = []

        for ds in req.datasets:
            # Use filename directly when available (avoids any naming ambiguity)
            file_key = ds.get("file", "")
            if file_key:
                parquet_path = DATA_DIR / file_key
            else:
                exchange = ds.get("exchange", "")
                symbol = ds.get("symbol", "")
                tf_key = ds.get("timeframe", "")
                parquet_path = DATA_DIR / f"{exchange}_{symbol}_{tf_key}.parquet"

            if not parquet_path.exists():
                step += len(req.strategies)
                continue

            df = pd.read_parquet(parquet_path)
            info = _parse_dataset_id(parquet_path)
            exchange = info["exchange"]
            symbol = info["symbol"]
            tf = info["timeframe"]

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
            price_ts = _downsample(timestamps, 1000)
            bh_equity = _downsample(bh_result.equity.tolist(), 1000)

            dataset_entry: dict[str, Any] = {
                "file": parquet_path.name,
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": tf,
                "dataset_id": f"{exchange}_{symbol}_{tf}",
                "rows": len(df),
                "start": str(df["timestamp"].min())[:10],
                "end": str(df["timestamp"].max())[:10],
                "price": _downsample(df["close"].tolist(), 1000),
                "timestamps": price_ts,
                "buy_hold_equity": bh_equity,
                "buy_hold_metrics": bh_result.metrics,
                "strategies": [],
                "regime_bands": _detect_regimes(df),
                "monthly_returns": _monthly_heatmap(bh_result.returns, df["timestamp"]),
                "return_distribution": _return_distribution(bh_result.returns),
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
                        "return_dist": _return_distribution(result.returns),
                    })
                except Exception as exc:
                    _log.warning("Strategy %s failed on %s: %s", strategy, symbol, exc)
                    dataset_entry["strategies"].append({"name": strategy, "error": str(exc)})

            all_results.append(dataset_entry)

        done_msg = f"ریسرچ کامل شد — {len(all_results)} دیتاست، {len(req.strategies)} استراتژی"
        _log.info("Research done  job=%s  %s", job_id, done_msg)
        job_manager.update(job_id, status=JobStatus.DONE, progress=100.0, message=done_msg, result={"datasets": all_results})
    except Exception as exc:
        _log.exception("Research failed  job=%s  error=%s", job_id, exc)
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc), message=f"خطا: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dataset_id(path: Path) -> dict[str, str]:
    """Parse exchange/symbol/timeframe/market_type from a Parquet filename."""
    parts = path.stem.split("_")
    if not parts:
        return {"exchange": "unknown", "symbol": path.stem, "timeframe": "?", "market_type": "spot"}

    timeframe = parts[-1] if parts[-1] in KNOWN_TF_SET else "unknown"
    core = parts[:-1]  # everything before timeframe

    # Detect exchange prefix (first part matches any known exchange)
    if core and core[0].lower() in _ALL_KNOWN_EXCHANGES:
        exchange = core[0].lower()
        rest = core[1:]
        # Detect optional market_type token (futures/perp/spot)
        if rest and rest[0].lower() in ("futures", "perp", "perpetual", "spot", "um", "cm"):
            market_type = rest[0].lower()
            symbol = "_".join(rest[1:])
        else:
            market_type = "spot"
            symbol = "_".join(rest)
    else:
        exchange = "unknown"
        market_type = "spot"
        symbol = "_".join(core)

    return {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "market_type": market_type,
        "dataset_id": f"{exchange}_{symbol}_{timeframe}",
    }


def _best_strategy_in_window(
    win_df: pd.DataFrame, config: BacktestConfig
) -> tuple[str, float]:
    """Return (strategy_name, sharpe) for the best strategy in a window."""
    backtester = VectorizedBacktester(config)
    best_name = "ema_trend"
    best_sharpe = -float("inf")
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(win_df, strat)
            res = backtester.run(win_df, sigs)
            sharpe = res.metrics.get("sharpe", -float("inf"))
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_name = strat
        except Exception:
            pass
    return best_name, best_sharpe


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


def _return_distribution(returns: pd.Series, bins: int = 50) -> dict[str, Any]:
    """Histogram data for return distribution chart."""
    try:
        r = returns.dropna()
        if len(r) < 10:
            return {}
        counts, edges = np.histogram(r, bins=bins)
        mid = ((edges[:-1] + edges[1:]) / 2 * 100).tolist()
        return {
            "x": mid,
            "y": counts.tolist(),
            "mean": float(r.mean() * 100),
            "std": float(r.std() * 100),
            "skew": float(r.skew()),
            "kurt": float(r.kurtosis()),
        }
    except Exception:
        return {}


def _detect_regimes(df: pd.DataFrame) -> list[dict[str, Any]]:
    if len(df) < 50:
        return []
    close = df["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ts = df["timestamp"]
    bands: list[dict[str, Any]] = []
    current_regime = None
    band_start = 0

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

    if current_regime is not None:
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
        return list(monthly.rename(columns={"r": "return"}).to_dict(orient="records"))
    except Exception:
        return []


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


_TREND_STRATEGIES = frozenset({"ema_trend", "macd_cross", "atr_breakout", "donchian_breakout"})
_MR_STRATEGIES = frozenset({"rsi_mean_reversion", "bollinger_mean_reversion", "stochastic_mr"})

_REGIME_FIT: dict[str, frozenset[str]] = {
    "trending_up": _TREND_STRATEGIES,
    "trending_down": _TREND_STRATEGIES,
    "ranging": _MR_STRATEGIES,
    "mean_reverting": _MR_STRATEGIES,
}

_REGIME_FA: dict[str, str] = {
    "trending_up": "ترند صعودی",
    "trending_down": "ترند نزولی",
    "ranging": "رنجینگ",
    "mean_reverting": "میانگین‌گرا",
    "unknown": "نامشخص",
}


def _build_recommendation(
    best_now: str,
    regime: str,
    windows: list[dict[str, Any]],
    recent_scores: dict[str, float],
) -> dict[str, Any]:
    """Build an actionable next-day recommendation with confidence and reasoning."""
    reasons: list[str] = []

    # 1. Consistency: how many of the last 5 windows did best_now win?
    last_wins = windows[-5:] if len(windows) >= 5 else windows
    win_count = sum(1 for w in last_wins if w["best_strategy"] == best_now)
    consistency = win_count / max(len(last_wins), 1)
    reasons.append(f"{win_count} از {len(last_wins)} پنجره اخیر بهترین بود")

    # 2. Regime fit
    fit_strategies = _REGIME_FIT.get(regime, frozenset())
    regime_fit = best_now in fit_strategies
    regime_label = _REGIME_FA.get(regime, regime)
    if regime_fit:
        reasons.append(f"رژیم «{regime_label}» با این استراتژی همخوانی دارد")
    else:
        reasons.append(f"رژیم «{regime_label}» با این استراتژی همخوانی ضعیف دارد")

    # 3. Recent Sharpe vs runner-up
    sorted_scores = sorted(recent_scores.items(), key=lambda x: x[1], reverse=True)
    best_sharpe = sorted_scores[0][1] if sorted_scores else 0.0
    runner_up_sharpe = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    margin = best_sharpe - runner_up_sharpe
    if margin > 0.3:
        reasons.append(f"Sharpe فاصله {margin:.2f} از استراتژی دوم")
    elif margin > 0.1:
        reasons.append(f"Sharpe کمی بهتر از رقبا (فاصله {margin:.2f})")
    else:
        reasons.append("فاصله Sharpe با رقبا کم است — بازار در تغییر رژیم")

    # Confidence: consistency (60%) + regime fit (30%) + margin (10%)
    margin_score = min(margin / 0.5, 1.0)
    confidence = int(consistency * 60 + (30 if regime_fit else 0) + margin_score * 10)

    # Regime-based alternative if fit is poor
    alt_strat: str | None = None
    if not regime_fit and fit_strategies:
        alt_scores = {s: recent_scores.get(s, -999) for s in fit_strategies}
        alt_strat = max(alt_scores, key=alt_scores.get)  # type: ignore[arg-type]

    return {
        "strategy": best_now,
        "label": STRATEGY_LABELS.get(best_now, best_now),
        "confidence": confidence,
        "regime": regime,
        "regime_label": regime_label,
        "regime_fit": regime_fit,
        "reasons": reasons,
        "sharpe_score": round(best_sharpe, 3),
        "alt_strategy": alt_strat,
        "alt_label": STRATEGY_LABELS.get(alt_strat, alt_strat) if alt_strat else None,
    }


def _price_momentum(df: pd.DataFrame) -> float:
    close = df["close"]
    if len(close) < 20:
        return 0.0
    return float((close.iloc[-1] / close.iloc[-20] - 1) * 100)
