# Architecture

The platform is organised as a layered pipeline with a browser-based interface sitting on top of a Python library. Each layer has a single responsibility and communicates through well-defined data contracts (Parquet files, Pydantic models, typed function signatures).

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        Browser UI                            │
│          web/dashboard.html  (Vanilla JS + Plotly)           │
└──────────────────────────────┬───────────────────────────────┘
                               │  HTTP / SSE
┌──────────────────────────────▼───────────────────────────────┐
│                    FastAPI Web Layer                         │
│                     src/web/app.py                           │
│   /api/exchanges  /api/symbols  /api/inventory               │
│   /api/download   /api/research  /api/insights               │
│   /api/jobs/{id}/events  (Server-Sent Events)                │
│                     src/web/jobs.py                          │
│           In-memory job manager (threading)                  │
└──────────────────────────────┬───────────────────────────────┘
                               │  Python calls
┌──────────────────────────────▼───────────────────────────────┐
│                    Research Library                          │
│                                                              │
│  src/data/         src/strategies/     src/backtesting/      │
│  src/features/     src/factors/        src/analysis/         │
│  src/validation/   src/ml/             src/config.py         │
└──────────────────────────────┬───────────────────────────────┘
                               │  read/write
┌──────────────────────────────▼───────────────────────────────┐
│                    Parquet Data Store                        │
│          data/processed/{exchange}_{symbol}_{tf}.parquet     │
└──────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### `src/data/`

| Module | Responsibility |
|---|---|
| `downloader.py` | `BinanceBulkDownloader` fetches monthly archive ZIPs from `data.binance.vision`; `CCXTFallbackDownloader` wraps any CCXT exchange for paginated OHLCV; `DataIngestionPipeline` coordinates both with incremental merge |
| `nobitex.py` | `NobitexOHLCVDownloader` reads from the public UDF history endpoint; chunks requests to stay within the 500-candle-per-request limit |
| `storage.py` | `ParquetDataStore` handles read, write, and incremental merge with deduplication by timestamp |
| `schema.py` | Canonical column list (`timestamp`, `open`, `high`, `low`, `close`, `volume`), timeframe normalisation, millisecond conversion |

### `src/strategies/`

All strategies in `rules.py` accept a `pd.DataFrame` with OHLCV columns and return a `pd.Series` of long/flat binary signals (1.0 = long, 0.0 = flat). Parameters are encapsulated in frozen dataclasses to make parameter sweeps explicit. The `build_strategy_signals` dispatcher maps string names to factory calls.

### `src/backtesting/`

`VectorizedBacktester.run()` takes OHLCV data and a target position series. It applies a one-bar execution delay, computes round-trip transaction costs (fee + slippage + spread in basis points), and produces a `BacktestResult` with equity curve, returns, position series, and a metrics dictionary. All operations are vectorised over numpy arrays.

### `src/features/`

`library.py` contains 40+ feature functions grouped by category. Each function takes price/volume series and returns a named `pd.Series`. The library covers: trend (EMA, MACD, ADX), momentum (RSI, Stochastic, ROC), volatility (ATR, Bollinger width, realised vol), volume (OBV, VWAP, volume ratio), and statistical (z-score, autocorrelation, Hurst exponent approximation).

### `src/factors/`

Factor research pipeline: IC (correlation of factor rank with forward returns), rank IC, conditional return buckets, factor decay curve (IC over multiple horizons), factor-vs-factor correlation. Outputs Markdown reports to `reports/factor_research/`.

### `src/analysis/`

| Module | Description |
|---|---|
| `global_report.py` | Runs all strategies on every Parquet file in a directory; generates a unified multi-tab HTML dashboard with equity curves, drawdowns, metrics, parameter stability, and dataset statistics |
| `walk_forward.py` | Sliding-window out-of-sample validation with configurable train/test splits |
| `monte_carlo.py` | Bootstrap resampling of return series to estimate strategy robustness and worst-case drawdown distributions |
| `regime.py` | Market regime detection and regime-conditional performance breakdowns |
| `portfolio.py` | Cross-dataset correlation, portfolio-level Sharpe and drawdown aggregation |

### `src/ml/`

Time-series-safe research pipeline: features are constructed without look-ahead; all train/test splits are strictly chronological. Supports LightGBM and XGBoost for return classification and volatility regression. Models are evaluated on walk-forward out-of-sample windows, not a single hold-out.

### `src/web/`

| Module | Description |
|---|---|
| `app.py` | FastAPI application; all route handlers; background task launchers; `_ExchangePrefixedStore` ensures downloads are saved under `{exchange}_{symbol}_{tf}.parquet` convention |
| `jobs.py` | Thread-safe in-memory `JobManager`; jobs track `status`, `progress` (0–100), `message`, and `result`; Server-Sent Events stream job state to the browser every 600 ms |

### `src/validation/`

`quality.py` checks: completeness (expected bar count vs actual), duplicate timestamps, OHLCV consistency (high ≥ low, close within high/low), gap detection, zero-volume bars, and statistical outliers in price and volume. Reports saved as Markdown.

## Data Flow

```
Exchange API
     │
     ▼
Downloader (monthly bulk / CCXT / Nobitex)
     │  pd.DataFrame (OHLCV, UTC timestamps)
     ▼
normalize_ohlcv()        ← deduplicate, sort, cast types
     │
     ▼
ParquetDataStore.merge_incremental()
     │  Parquet file on disk
     ▼
VectorizedBacktester.run(data, signals)
     │  BacktestResult (equity, returns, position, metrics)
     ▼
FastAPI /api/research response  or  global_report HTML
```

## Design Principles

1. **Reproducibility** — given the same Parquet input, every backtest and report is deterministic.
2. **Incremental downloads** — data is never re-fetched if it already exists locally; only new candles are appended.
3. **No look-ahead bias** — all feature calculations, ML splits, and walk-forward windows are strictly causal.
4. **Module-first** — research logic lives in reusable Python modules, not inside notebooks.
5. **Separation of concerns** — data acquisition, feature engineering, strategy logic, and execution modelling are independent layers with no circular dependencies.
6. **Typed interfaces** — Pydantic models for configuration, dataclasses for results, typed function signatures throughout.

## Execution Model

The web server runs synchronously (FastAPI with `threading`-based background tasks). Downloads and backtests run in background threads; the browser polls via Server-Sent Events. This design keeps the dependency footprint minimal (no Redis, no Celery, no message broker) while supporting the concurrent use case of one user running research in a browser tab.

For multi-user or production deployment, the job manager can be replaced with any async task queue (e.g. ARQ, Celery) with minimal changes to `src/web/jobs.py`.
