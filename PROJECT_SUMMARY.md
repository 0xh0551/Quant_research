# Project Summary

## What This Is

The Quant Research Platform is an end-to-end quantitative research environment for cryptocurrency markets. It combines a production-grade Python library for data acquisition, feature engineering, strategy research, and backtesting with a browser-based interactive dashboard for daily research workflow.

## Architecture

Three layers communicate through well-defined interfaces:

1. **Data store** — Parquet files in `data/processed/` named `{exchange}_{symbol}_{timeframe}.parquet`
2. **Python library** — `src/` modules for data acquisition, validation, features, strategies, backtesting, analysis, ML
3. **Web dashboard** — FastAPI backend (`src/web/app.py`) serving a single-page HTML UI (`web/dashboard.html`)

Background jobs (downloads and backtests) run in threads and report progress to the browser via Server-Sent Events.

## Data Coverage

| Exchange | Method | Auth required |
|---|---|---|
| Binance | Monthly bulk ZIPs + CCXT fallback | No |
| Nobitex | Public UDF history endpoint | No |
| 110+ other CCXT exchanges | CCXT paginated OHLCV | No (public data) |

Supported timeframes: `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `3h`, `4h`, `1d`

## Strategy Baselines

| Name | Family | Key parameter |
|---|---|---|
| EMA Trend | Trend following | Fast/slow EMA spans (20/100) |
| RSI Mean Reversion | Counter-trend | Entry at RSI < 30, exit > 50 |
| Bollinger Mean Reversion | Counter-trend | Enter below −2σ, exit at mean |
| Donchian Breakout | Trend following | 55-period channel (Turtle Trading) |
| ATR Breakout | Trend following | MA + 1.5× ATR(20) threshold |

## Backtesting Model

Vectorised long/flat simulator. Costs: 10 bps fee + 2 bps slippage (one-way, charged on turnover). One-bar execution delay. Metrics: Sharpe, Sortino, Calmar, CAGR, Max Drawdown, Profit Factor, Win Rate.

## What Is Not Modelled

This is a research platform, not a live trading system. The following are **not** modelled:

- Order book depth or market impact at scale
- Partial fills or order rejection
- Exchange downtime or API errors
- Funding rates, borrow costs, or taxes
- Intra-bar price movement
- Multi-asset portfolio rebalancing constraints

All strategy results are **in-sample** unless explicitly produced by the walk-forward module. Past backtest performance does not predict future live trading results.

## Reproducibility

Given the same Parquet input files, every backtest, report, and insights computation is fully deterministic. The `quant-research demo` command generates synthetic BTC-like data so the full pipeline can be exercised without any network access.

## Development Status

The platform is production-ready for personal and institutional research use. The web dashboard (`make web`) provides a complete self-serve research environment. The Python library can also be used programmatically or via the CLI for automated pipelines.

**Ready:** data acquisition, validation, feature library, strategy backtesting, walk-forward, Monte Carlo, web dashboard, insights engine.
**Planned:** Bayesian parameter optimisation, HMM regime detection, GitHub Actions CI for scheduled data refresh and report publishing.
