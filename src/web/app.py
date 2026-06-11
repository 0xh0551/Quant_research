"""FastAPI web server for the Quant Research Platform dashboard — v1.1."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import subprocess
import sys
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

from src.analysis import cross_exchange as _cx
from src.analysis import forward_test as _fwd
from src.analysis.statistics import bootstrap_metric_ci
from src.backtesting.engine import BacktestConfig, VectorizedBacktester
from src.data.downloader import CCXTFallbackDownloader, DataIngestionPipeline, DownloadRequest
from src.ml import model_eval as _ml_eval
from src.portfolio import construction as _pf
from src.portfolio import sizing as _sizing
from src.rl.recommend import recommend_rl_coins
from src.tracking.experiments import log_run, recent_runs
from src.validation.monitor import quality_report
from src.data.nobitex import NobitexDataIngestionPipeline, NobitexDownloadRequest
from src.data.storage import ParquetDataStore
from src.logging_config import setup_logging, tail_log
from src.strategies.rules import (
    STRATEGY_PARAM_GRIDS,
    STRATEGY_PARAM_SPECS,
    build_strategy_signals,
    build_strategy_signals_with_params,
)
from src.web.jobs import JobStatus, job_manager

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "processed"
WEB_DIR = ROOT / "web"
LOG_DIR = ROOT / "logs"
OUTPUTS_DIR = ROOT / "outputs"

setup_logging(level="INFO", log_dir=LOG_DIR)
logger = logging.getLogger(__name__)

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
FUTURES_MARKET_TYPES = {"futures", "perp", "perpetual", "um", "cm"}

ALL_STRATEGIES = [
    "ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion",
    "donchian_breakout", "atr_breakout", "macd_cross", "stochastic_mr",
    "ichimoku", "supertrend", "vwap_deviation", "cmf_trend",
    "hammer_pattern", "engulfing", "ml_signal",
]

STRATEGY_LABELS = {
    "ema_trend": "EMA Trend",
    "rsi_mean_reversion": "RSI Mean Reversion",
    "bollinger_mean_reversion": "Bollinger Bands",
    "donchian_breakout": "Donchian Breakout",
    "atr_breakout": "ATR Breakout",
    "macd_cross": "MACD Cross",
    "stochastic_mr": "Stochastic MR",
    "ichimoku": "Ichimoku Cloud",
    "supertrend": "SuperTrend",
    "vwap_deviation": "VWAP Deviation",
    "cmf_trend": "CMF Trend",
    "hammer_pattern": "Hammer Pattern",
    "engulfing": "Engulfing Pattern",
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

app = FastAPI(title="Quant Research Platform", version="1.1.0")
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


class LabRunRequest(BaseModel):
    filename: str
    strategy: str
    params: dict[str, Any] = {}


class LabOptRequest(BaseModel):
    filename: str
    strategy: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "dashboard.html")


def _load_app_config() -> dict[str, Any]:
    """User-facing app settings (e.g. install-time default language)."""
    cfg_path = ROOT / "configs" / "app.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@app.get("/api/config")
def get_app_config() -> dict[str, Any]:
    cfg = _load_app_config()
    return {"default_language": cfg.get("default_language", "fa")}


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


# ── Edges (walk-forward validated edges) ───────────────────────────────────────

@app.get("/edges")
def edges_page() -> FileResponse:
    # Edges is now a section of the single-page dashboard; the SPA detects the
    # /edges suffix on boot and opens that section (keeps old links working).
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/api/edges")
def get_edges() -> dict[str, Any]:
    """Latest scan report + history + candidate count for the Edges dashboard."""
    report_path = OUTPUTS_DIR / "wf_report.json"
    manifest_path = OUTPUTS_DIR / "wf_candidates.json"
    history_path = OUTPUTS_DIR / "wf_history.jsonl"

    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    history: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines()[-60:]:
            line = line.strip()
            if line:
                try:
                    history.append(json.loads(line))
                except Exception:
                    pass

    return {
        "report": report,
        "history": history,
        "n_candidates": len(manifest.get("candidates", [])),
        "manifest_generated_at": manifest.get("generated_at"),
    }


@app.post("/api/edges/refresh")
def refresh_edges(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Run the walk-forward scan as a background job (same weekly script)."""
    job_id = job_manager.create("edges")
    background_tasks.add_task(_run_edge_refresh, job_id)
    return {"job_id": job_id}


def _run_edge_refresh(job_id: str) -> None:
    _log = logging.getLogger("quant.edges")
    job_manager.update(job_id, status=JobStatus.RUNNING,
                       message="Walk-forward scan started", message_code="job_edge_start")
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "refresh_candidates.py")],
            capture_output=True, text=True, timeout=1800, cwd=str(ROOT),
        )
        report_path = OUTPUTS_DIR / "wf_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        if proc.returncode != 0:
            _log.error("edge refresh failed: %s", proc.stderr[-1000:])
            job_manager.update(job_id, status=JobStatus.ERROR,
                               error=(proc.stderr or proc.stdout)[-2000:],
                               message="Scan failed", message_code="job_edge_error")
            return
        n_passed = report.get("n_passed", 0)
        n_alerts = len(report.get("alerts", []))
        job_manager.update(
            job_id, status=JobStatus.DONE, progress=100.0,
            message=f"Scan complete — {n_passed} valid edges, {n_alerts} alerts",
            message_code="job_edge_done", message_params={"passed": n_passed, "alerts": n_alerts},
            result=report,
        )
    except Exception as exc:
        _log.exception("edge refresh crashed")
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc),
                           message=f"Error: {exc}", message_code="job_error",
                           message_params={"error": str(exc)})


@app.get("/api/insights")
def get_insights() -> dict[str, Any]:
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
                "market_type": info["market_type"],
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
    allow_short = info["market_type"] in FUTURES_MARKET_TYPES
    config = BacktestConfig(periods_per_year=ppy, allow_short=allow_short)
    backtester = VectorizedBacktester(config)

    # Buy & Hold baseline
    bh_pos = pd.Series(1.0, index=df.index)
    bh_result = backtester.run(df, bh_pos)

    # Full-period results for all strategies
    full_metrics: dict[str, Any] = {}
    full_equities: dict[str, list] = {}
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(df, strat, allow_short=allow_short)
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
        best_strat, best_sharpe = _best_strategy_in_window(win_df, config, allow_short)

        try:
            oracle_sigs = build_strategy_signals(df, best_strat, allow_short=allow_short)
            oracle_pos.iloc[win_start:win_end] = oracle_sigs.iloc[win_start:win_end].values
        except Exception:
            pass

        try:
            wf_sigs = build_strategy_signals(df, prev_best, allow_short=allow_short)
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
    price_ds = _downsample(df["close"].tolist(), 800)

    # Recent 90-day scores
    cutoff = df["timestamp"].max() - pd.Timedelta(days=90)
    recent = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    if len(recent) < 30:
        recent = df.tail(200).reset_index(drop=True)
    recent_scores = {}
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(recent, strat, allow_short=allow_short)
            res = backtester.run(recent, sigs)
            recent_scores[strat] = round(res.metrics.get("sharpe", 0.0), 3)
        except Exception:
            recent_scores[strat] = 0.0

    best_now = max(recent_scores, key=recent_scores.get)  # type: ignore[arg-type]
    current_regime = _current_regime(recent)
    recommendation = _build_recommendation(best_now, current_regime, strategy_windows, recent_scores)

    # ML/RL fitness
    ml_rl_fitness = _compute_ml_rl_fitness(df, ppy)

    return {
        "info": info,
        "allow_short": allow_short,
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
        "price": price_ds,
        "strategy_windows": strategy_windows,
        "current_regime": current_regime,
        "momentum": _price_momentum(df),
        "recent_scores": recent_scores,
        "best_now": best_now,
        "best_now_label": STRATEGY_LABELS.get(best_now, best_now),
        "recommendation": recommendation,
        "ml_rl_fitness": ml_rl_fitness,
    }


# ── Lab endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/lab/params/{strategy}")
def lab_get_params(strategy: str) -> dict[str, Any]:
    """Return parameter spec for the Lab UI."""
    if strategy not in STRATEGY_PARAM_SPECS:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")
    return {"strategy": strategy, "params": STRATEGY_PARAM_SPECS[strategy]}


@app.post("/api/lab/run")
def lab_run(req: LabRunRequest) -> dict[str, Any]:
    """Run a single strategy backtest with custom parameters (synchronous)."""
    path = DATA_DIR / req.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
    if len(df) < 50:
        raise HTTPException(status_code=422, detail="Insufficient data (need ≥ 50 bars)")

    info = _parse_dataset_id(path)
    tf = info["timeframe"]
    ppy = PERIODS_PER_YEAR.get(tf, 365)
    allow_short = info["market_type"] in FUTURES_MARKET_TYPES
    config = BacktestConfig(periods_per_year=ppy, allow_short=allow_short)
    backtester = VectorizedBacktester(config)

    try:
        signals = build_strategy_signals_with_params(df, req.strategy, req.params, allow_short=allow_short)
        result = backtester.run(df, signals)
        bh = backtester.run(df, pd.Series(1.0, index=df.index))
        ts_ds = _downsample(df["timestamp"].dt.strftime("%Y-%m-%d %H:%M").tolist(), 600)
        eq_ds = _downsample(result.equity.tolist(), 600)
        bh_eq_ds = _downsample(bh.equity.tolist(), 600)
        pos_ds = _downsample(result.position.tolist(), 600)
        return {
            "metrics": result.metrics,
            "bh_metrics": bh.metrics,
            "equity": eq_ds,
            "bh_equity": bh_eq_ds,
            "position": pos_ds,
            "timestamps": ts_ds,
            "allow_short": allow_short,
            "params": req.params,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/lab/optimize")
def lab_optimize(req: LabOptRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Grid search optimization — returns a job_id to poll."""
    job_id = job_manager.create("optimize")
    background_tasks.add_task(_run_optimize, job_id, req)
    return {"job_id": job_id}


# ── Cross-exchange edge suite (Tier 1) ──────────────────────────────────────────

@app.get("/api/cross-exchange/symbols")
def cross_exchange_symbols() -> dict[str, Any]:
    return {"symbols": _cx.list_symbols(DATA_DIR)}


@app.get("/api/cross-exchange")
def cross_exchange_analyze(symbol: str, timeframe: str) -> dict[str, Any]:
    return _cx.analyze_symbol(DATA_DIR, symbol, timeframe)


# ── Portfolio construction & sizing (Tier 2) ────────────────────────────────────

class PortfolioRequest(BaseModel):
    files: list[str]
    method: str = "hrp"          # hrp | risk_parity | inverse_vol | equal_weight
    lookback: int = 1500
    target_vol: float = 0.15


@app.post("/api/portfolio")
def build_portfolio(req: PortfolioRequest) -> dict[str, Any]:
    series: dict[str, pd.Series] = {}
    bars_year = 365
    for f in req.files:
        path = DATA_DIR / f
        if not path.exists():
            continue
        info = _parse_dataset_id(path)
        bars_year = PERIODS_PER_YEAR.get(info["timeframe"], bars_year)
        df = pd.read_parquet(path).sort_values("timestamp").tail(req.lookback)
        label = f"{info['symbol']}·{info['exchange']}"
        series[label] = df.set_index("timestamp")["close"].pct_change()
    if len(series) < 2:
        raise HTTPException(status_code=422, detail="Need ≥2 datasets for a portfolio")
    returns = pd.DataFrame(series).dropna()
    if returns.empty or returns.shape[1] < 2:
        raise HTTPException(status_code=422, detail="Datasets do not overlap in time")
    portfolio = _pf.build_portfolio(returns, req.method)
    sizing = {
        col: {
            "vol_target_leverage": round(_sizing.vol_target_leverage(returns[col], req.target_vol, bars_year), 3),
            "kelly": _sizing.fractional_kelly(returns[col], 0.5, bars_year),
        }
        for col in returns.columns
    }
    return {**portfolio, "sizing": sizing, "bars_per_year": bars_year,
            "n_bars": int(returns.shape[0])}


# ── ML evaluation (purged CV) & RL recommendation (Tier 3) ──────────────────────

class MLEvalRequest(BaseModel):
    filename: str
    optimize: bool = False


@app.post("/api/ml/evaluate")
def ml_evaluate(req: MLEvalRequest) -> dict[str, Any]:
    path = DATA_DIR / req.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
    res = _ml_eval.optimize_hyperparams(df) if req.optimize else _ml_eval.evaluate_dataset(df)
    out = {
        "filename": req.filename,
        "mean_auc": round(res.mean_auc, 4),
        "std_auc": round(res.std_auc, 4),
        "mean_accuracy": round(res.mean_accuracy, 4),
        "n_splits": res.n_splits,
        "n_samples": res.n_samples,
        "fold_auc": res.fold_auc,
        "best_params": res.best_params,
        "note": res.note,
        "verdict": ("predictable" if res.mean_auc >= 0.55
                    else "weak" if res.mean_auc >= 0.52 else "noise"),
    }
    log_run("ml_evaluate", {"filename": req.filename, "optimize": req.optimize},
            {"mean_auc": res.mean_auc, "mean_accuracy": res.mean_accuracy},
            seed=42, dataset=path)
    return out


@app.get("/api/rl/recommend")
def rl_recommend(timeframe: str = "15m", top_n: int = 12) -> dict[str, Any]:
    return recommend_rl_coins(DATA_DIR, timeframe=timeframe, top_n=top_n)


# ── Data quality + forward-test attribution + experiments (Tier 4) ──────────────

@app.get("/api/quality")
def data_quality() -> dict[str, Any]:
    return quality_report(DATA_DIR, max_files=300)


@app.get("/api/forward-test")
def forward_test() -> dict[str, Any]:
    report_path = OUTPUTS_DIR / "wf_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return _fwd.attribution(report)


@app.get("/api/experiments")
def experiments() -> dict[str, Any]:
    return {"runs": recent_runs(50)}


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
    _log.info("Download started  job=%s  exchange=%s  symbol=%s  market=%s  tfs=%s",
              job_id, req.exchange, req.symbol, req.market_type, req.timeframes)
    job_manager.update(job_id, status=JobStatus.RUNNING,
                       message="Starting download", message_code="job_dl_start")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        total = len(req.timeframes)
        start_date = date.fromisoformat(req.start)
        end_date = date.fromisoformat(req.end) if req.end else None

        for i, tf in enumerate(req.timeframes):
            msg = f"download {req.symbol} {tf} ({req.market_type}) from {req.exchange}"
            _log.info("  [%d/%d] %s", i + 1, total, msg)
            job_manager.update(
                job_id, progress=round(i / total * 100, 1), message=msg,
                message_code="job_dl_tf",
                message_params={"symbol": req.symbol, "tf": tf,
                                "market": req.market_type, "exchange": req.exchange},
            )
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
                pipeline.run(DownloadRequest(symbol=req.symbol, timeframe=tf, start=start_date, end=end_date))
            else:
                pipeline = DataIngestionPipeline(
                    store, fallback_downloader=CCXTFallbackDownloader(req.exchange),
                )
                pipeline.run(DownloadRequest(symbol=req.symbol, timeframe=tf, start=start_date, end=end_date))

        done_msg = f"Download of {req.symbol} complete ({total} timeframes)"
        _log.info("Download done  job=%s  %s", job_id, done_msg)
        job_manager.update(job_id, status=JobStatus.DONE, progress=100.0, message=done_msg,
                           message_code="job_dl_done",
                           message_params={"symbol": req.symbol, "n": total})
    except Exception as exc:
        _log.exception("Download failed  job=%s  error=%s", job_id, exc)
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc),
                           message=f"Error: {exc}", message_code="job_error",
                           message_params={"error": str(exc)})


def _run_research(job_id: str, req: ResearchRequest) -> None:
    _log = logging.getLogger("quant.research")
    _log.info("Research started  job=%s  datasets=%d  strategies=%s",
              job_id, len(req.datasets), req.strategies)
    job_manager.update(job_id, status=JobStatus.RUNNING,
                       message="Starting backtest", message_code="job_res_start")
    try:
        total = len(req.datasets) * len(req.strategies)
        step = 0
        all_results: list[dict[str, Any]] = []

        for ds in req.datasets:
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
            allow_short = info["market_type"] in FUTURES_MARKET_TYPES

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
                allow_short=allow_short,
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
                "market_type": info["market_type"],
                "dataset_id": f"{exchange}_{symbol}_{tf}",
                "allow_short": allow_short,
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
                short_tag = "  [Short/Long]" if allow_short else ""
                job_manager.update(
                    job_id,
                    progress=round(step / total * 90, 1),
                    message=f"backtest {STRATEGY_LABELS.get(strategy, strategy)} on {symbol} {tf}{short_tag}",
                    message_code="job_res_bt",
                    message_params={"strategy": STRATEGY_LABELS.get(strategy, strategy),
                                    "symbol": symbol, "tf": tf, "short": short_tag},
                )
                try:
                    signals = build_strategy_signals(df, strategy, allow_short=allow_short)
                    result = backtester.run(df, signals)
                    log_returns = np.log1p(result.returns)
                    equity_ds = _downsample(result.equity.tolist(), 1000)
                    dd_ds = _downsample((result.equity / result.equity.cummax() - 1).tolist(), 1000)
                    sharpe_ci = bootstrap_metric_ci(
                        result.returns.to_numpy(), ppy, n_boot=300)["sharpe"]
                    dataset_entry["strategies"].append({
                        "name": strategy,
                        "label": STRATEGY_LABELS.get(strategy, strategy),
                        "metrics": result.metrics,
                        "log_metrics": _log_metrics(log_returns, ppy),
                        "equity": equity_ds,
                        "drawdown": dd_ds,
                        "return_dist": _return_distribution(result.returns),
                        "sharpe_ci": {"low": round(sharpe_ci["low"], 2),
                                      "high": round(sharpe_ci["high"], 2)},
                    })
                except Exception as exc:
                    _log.warning("Strategy %s failed on %s: %s", strategy, symbol, exc)
                    dataset_entry["strategies"].append({"name": strategy, "error": str(exc)})

            all_results.append(dataset_entry)

        done_msg = f"Research complete — {len(all_results)} datasets, {len(req.strategies)} strategies"
        _log.info("Research done  job=%s  %s", job_id, done_msg)
        job_manager.update(job_id, status=JobStatus.DONE, progress=100.0, message=done_msg,
                           message_code="job_res_done",
                           message_params={"datasets": len(all_results), "strategies": len(req.strategies)},
                           result={"datasets": all_results})
    except Exception as exc:
        _log.exception("Research failed  job=%s  error=%s", job_id, exc)
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc),
                           message=f"Error: {exc}", message_code="job_error",
                           message_params={"error": str(exc)})


def _run_optimize(job_id: str, req: LabOptRequest) -> None:
    _log = logging.getLogger("quant.optimize")
    job_manager.update(job_id, status=JobStatus.RUNNING,
                       message="Starting optimization", message_code="job_opt_start")
    try:
        path = DATA_DIR / req.filename
        df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        info = _parse_dataset_id(path)
        tf = info["timeframe"]
        ppy = PERIODS_PER_YEAR.get(tf, 365)
        allow_short = info["market_type"] in FUTURES_MARKET_TYPES
        config = BacktestConfig(periods_per_year=ppy, allow_short=allow_short)
        backtester = VectorizedBacktester(config)

        grid = STRATEGY_PARAM_GRIDS.get(req.strategy, {})
        if not grid:
            all_params = [{}]
        else:
            keys = list(grid.keys())
            values = list(grid.values())
            all_params = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

        total = len(all_params)
        results: list[dict[str, Any]] = []

        for i, params in enumerate(all_params):
            job_manager.update(
                job_id,
                progress=round(i / total * 95, 1),
                message=f"combo {i+1}/{total}: {params}",
                message_code="job_opt_combo",
                message_params={"i": i + 1, "total": total, "params": str(params)},
            )
            try:
                sigs = build_strategy_signals_with_params(df, req.strategy, params, allow_short=allow_short)
                res = backtester.run(df, sigs)
                results.append({
                    "params": params,
                    "sharpe": round(res.metrics.get("sharpe", -999), 4),
                    "cagr": round(res.metrics.get("cagr", 0), 4),
                    "max_drawdown": round(res.metrics.get("max_drawdown", -1), 4),
                    "total_return": round(res.metrics.get("total_return", 0), 4),
                    "win_rate": round(res.metrics.get("win_rate", 0), 4),
                })
            except Exception:
                pass

        results.sort(key=lambda x: x["sharpe"], reverse=True)
        best = results[0] if results else {}
        best_sharpe = best.get("sharpe", 0)
        done_msg = f"Optimization complete — {len(results)} combos, best Sharpe: {best_sharpe:.3f}"
        job_manager.update(
            job_id, status=JobStatus.DONE, progress=100.0, message=done_msg,
            message_code="job_opt_done",
            message_params={"n": len(results), "sharpe": f"{best_sharpe:.3f}"},
            result={"best": best, "all_results": results[:50], "strategy": req.strategy},
        )
    except Exception as exc:
        _log.exception("Optimize failed  job=%s  error=%s", job_id, exc)
        job_manager.update(job_id, status=JobStatus.ERROR, error=str(exc),
                           message=f"Error: {exc}", message_code="job_error",
                           message_params={"error": str(exc)})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dataset_id(path: Path) -> dict[str, str]:
    parts = path.stem.split("_")
    if not parts:
        return {"exchange": "unknown", "symbol": path.stem, "timeframe": "?", "market_type": "spot"}

    timeframe = parts[-1] if parts[-1] in KNOWN_TF_SET else "unknown"
    core = parts[:-1]

    if core and core[0].lower() in _ALL_KNOWN_EXCHANGES:
        exchange = core[0].lower()
        rest = core[1:]
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
    win_df: pd.DataFrame, config: BacktestConfig, allow_short: bool = False,
) -> tuple[str, float]:
    backtester = VectorizedBacktester(config)
    best_name = "ema_trend"
    best_sharpe = -float("inf")
    for strat in ALL_STRATEGIES:
        try:
            sigs = build_strategy_signals(win_df, strat, allow_short=allow_short)
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
    try:
        r = returns.dropna()
        if len(r) < 10:
            return {}
        counts, edges = np.histogram(r, bins=bins)
        mid = ((edges[:-1] + edges[1:]) / 2 * 100).tolist()
        return {
            "x": mid, "y": counts.tolist(),
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


_TREND_STRATEGIES = frozenset({
    "ema_trend", "macd_cross", "atr_breakout", "donchian_breakout",
    "ichimoku", "supertrend", "cmf_trend",
})
_MR_STRATEGIES = frozenset({
    "rsi_mean_reversion", "bollinger_mean_reversion", "stochastic_mr",
    "vwap_deviation", "hammer_pattern", "engulfing",
})

_REGIME_FIT: dict[str, frozenset[str]] = {
    "trending_up": _TREND_STRATEGIES,
    "trending_down": _TREND_STRATEGIES,
    "ranging": _MR_STRATEGIES,
    "mean_reverting": _MR_STRATEGIES,
}

def _build_recommendation(
    best_now: str,
    regime: str,
    windows: list[dict[str, Any]],
    recent_scores: dict[str, float],
) -> dict[str, Any]:
    # Reasons are emitted as language-neutral {code, ...params}; the frontend
    # localizes them (and the embedded regime code) via its i18n layer.
    reasons: list[dict[str, Any]] = []
    last_wins = windows[-5:] if len(windows) >= 5 else windows
    win_count = sum(1 for w in last_wins if w["best_strategy"] == best_now)
    consistency = win_count / max(len(last_wins), 1)
    reasons.append({"code": "reason_window_wins", "n": win_count, "total": len(last_wins)})

    fit_strategies = _REGIME_FIT.get(regime, frozenset())
    regime_fit = best_now in fit_strategies
    reasons.append({"code": "reason_regime_fit" if regime_fit else "reason_regime_misfit",
                    "regime": regime})

    sorted_scores = sorted(recent_scores.items(), key=lambda x: x[1], reverse=True)
    best_sharpe = sorted_scores[0][1] if sorted_scores else 0.0
    runner_up_sharpe = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    margin = best_sharpe - runner_up_sharpe
    if margin > 0.3:
        reasons.append({"code": "reason_margin_strong", "margin": f"{margin:.2f}"})
    elif margin > 0.1:
        reasons.append({"code": "reason_margin_mild", "margin": f"{margin:.2f}"})
    else:
        reasons.append({"code": "reason_margin_weak"})

    margin_score = min(margin / 0.5, 1.0)
    confidence = int(consistency * 60 + (30 if regime_fit else 0) + margin_score * 10)

    alt_strat: str | None = None
    if not regime_fit and fit_strategies:
        alt_scores = {s: recent_scores.get(s, -999) for s in fit_strategies}
        alt_strat = max(alt_scores, key=alt_scores.get)  # type: ignore[arg-type]

    return {
        "strategy": best_now,
        "label": STRATEGY_LABELS.get(best_now, best_now),
        "confidence": confidence,
        "regime": regime,
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


def _estimate_hurst(returns: np.ndarray) -> float:
    """Simplified R/S Hurst exponent estimation."""
    try:
        lags = [l for l in [2, 4, 8, 16, 32, 64] if l < len(returns) // 4]
        if len(lags) < 2:
            return 0.5
        rs_values = []
        for lag in lags:
            sub = returns[: lag * (len(returns) // lag)]
            if len(sub) < lag:
                continue
            chunks = sub.reshape(-1, lag)
            rs_list = []
            for chunk in chunks:
                std = chunk.std()
                if std < 1e-12:
                    continue
                cum = np.cumsum(chunk - chunk.mean())
                rs_list.append((cum.max() - cum.min()) / std)
            if rs_list:
                rs_values.append(np.mean(rs_list))
        if len(rs_values) < 2:
            return 0.5
        log_lags = np.log(lags[: len(rs_values)])
        log_rs = np.log(rs_values)
        hurst = float(np.polyfit(log_lags, log_rs, 1)[0])
        return float(np.clip(hurst, 0.1, 0.9))
    except Exception:
        return 0.5


def _compute_ml_rl_fitness(df: pd.DataFrame, ppy: int) -> dict[str, Any]:
    """Score how suitable this dataset is for ML vs RL-based trading bots."""
    close = df["close"]
    returns = close.pct_change().dropna()
    n = len(returns)
    if n < 30:
        return {"ml_score": 0, "rl_score": 0, "recommendation": "",
                "hint": "Not enough data to assess", "hint_code": "mlrl_insufficient",
                "bot_hint_code": "mlrl_insufficient", "hint_params": {}, "details": {}}

    # Autocorrelation lag-1
    autocorr_1 = float(returns.autocorr(lag=1)) if n > 5 else 0.0

    # Hurst exponent
    hurst = _estimate_hurst(returns.values)

    # Information Coefficient (lagged correlation)
    lag_ret = returns.shift(1).dropna()
    fwd_ret = returns.iloc[1:].reset_index(drop=True)
    if len(lag_ret) == len(fwd_ret) and len(lag_ret) > 10:
        ic = float(lag_ret.reset_index(drop=True).corr(fwd_ret))
    else:
        ic = 0.0
    ic = 0.0 if np.isnan(ic) else ic

    # Stationarity proxy: coefficient of variation of rolling std
    roll_std = returns.rolling(max(20, n // 10)).std().dropna()
    cv_std = float(roll_std.std() / (roll_std.mean() + 1e-9)) if len(roll_std) > 2 else 1.0
    stationarity_score = float(1.0 / (1.0 + cv_std))

    # Sample adequacy
    sample_ml = min(n / 1000.0, 1.0)
    sample_rl = min(n / 5000.0, 1.0)

    # Regime diversity (number of ema crossovers)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    regime_changes = int(((ema20 > ema50).astype(int).diff().abs() > 0).sum())
    regime_diversity = float(min(regime_changes / max(n / 50.0, 1.0), 1.0))

    # Reward density: fraction of bars with moves > 1σ
    big_moves = float((returns.abs() > returns.std()).mean())

    # Volatility clustering (GARCH proxy)
    sq_ret = returns ** 2
    vol_autocorr = float(sq_ret.autocorr(lag=1)) if n > 5 else 0.0
    vol_autocorr = max(0.0, vol_autocorr)

    # Fat tails
    kurt = float(returns.kurtosis()) if n > 10 else 0.0
    return_diversity = float(min(max(kurt / 10.0, 0.0), 1.0))

    # === ML Score ===
    autocorr_score = float(min(abs(autocorr_1) * 5.0, 1.0))
    # Hurst closer to 0 or 1 = more predictable
    hurst_score = float(min(abs(hurst - 0.5) * 4.0, 1.0))
    ml_score = int((
        sample_ml * 0.25 +
        autocorr_score * 0.25 +
        stationarity_score * 0.25 +
        hurst_score * 0.25
    ) * 100)

    # === RL Score ===
    rl_score = int((
        sample_rl * 0.20 +
        regime_diversity * 0.30 +
        big_moves * 0.20 +
        vol_autocorr * 0.15 +
        return_diversity * 0.15
    ) * 100)

    ml_score = max(0, min(100, ml_score))
    rl_score = max(0, min(100, rl_score))

    # Recommendation — emit language-neutral hint codes + params; the frontend
    # localizes them. (Plain `hint`/`bot_hint` kept as an EN fallback only.)
    gap = ml_score - rl_score
    hint_params: dict[str, Any] = {
        "stationarity": f"{stationarity_score:.2f}", "ic": f"{ic:.3f}",
        "hurst": f"{hurst:.2f}", "regime_changes": regime_changes,
        "density": f"{big_moves * 100:.1f}", "vol": f"{vol_autocorr:.2f}",
        "ml": ml_score, "rl": rl_score,
    }
    if gap > 15:
        recommendation = "ml"
        hint_code, bot_hint_code = "mlrl_ml", "mlrl_ml_bot"
        hint = f"ML is a better fit — stationarity={stationarity_score:.2f}, IC={ic:.3f}, Hurst={hurst:.2f}"
        bot_hint = "Suggestion: an ML model (e.g. GBM/XGBoost) with technical features on this pair"
    elif gap < -15:
        recommendation = "rl"
        hint_code, bot_hint_code = "mlrl_rl", "mlrl_rl_bot"
        hint = f"RL is a better fit — regime diversity ({regime_changes}), density={big_moves:.1%}, vol-clustering={vol_autocorr:.2f}"
        bot_hint = "Suggestion: an RL bot (e.g. PPO/SAC) to learn regime switching on this pair"
    else:
        recommendation = "both"
        hint_code, bot_hint_code = "mlrl_both", "mlrl_both_bot"
        hint = f"Both ML and RL are usable (ML={ml_score}, RL={rl_score})"
        bot_hint = "You can experiment with both approaches"

    return {
        "ml_score": ml_score,
        "rl_score": rl_score,
        "recommendation": recommendation,
        "hint": hint,
        "bot_hint": bot_hint,
        "hint_code": hint_code,
        "bot_hint_code": bot_hint_code,
        "hint_params": hint_params,
        "details": {
            "autocorrelation": round(autocorr_1, 4),
            "hurst": round(hurst, 4),
            "ic": round(ic, 4),
            "stationarity": round(stationarity_score, 4),
            "regime_changes": regime_changes,
            "regime_diversity": round(regime_diversity, 4),
            "reward_density": round(big_moves, 4),
            "vol_clustering": round(vol_autocorr, 4),
            "kurtosis": round(kurt, 4),
            "sample_count": n,
        },
    }
