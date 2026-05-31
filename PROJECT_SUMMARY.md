# Project Summary

The Bitcoin Quantitative Research Platform is an end-to-end research repository for BTCUSDT on Binance Spot. It is designed as a professional portfolio project that demonstrates the engineering of a complete quant research workflow rather than a claim of live trading profitability.

## Architecture

The project is module-first. Data acquisition writes Parquet files, validation produces Markdown quality reports, feature engineering creates a broad technical and statistical feature matrix, factor research ranks predictive relationships, strategy modules generate parameterized exposures, and the backtester applies fees, slippage, execution delay, and performance metrics. Analysis modules cover walk-forward splits, Monte Carlo bootstrapping, regimes, and portfolio aggregation.

## Methodology

All targets are shifted forward, all ML splits are chronological, and strategy outputs are separated from execution assumptions. Reports are deterministic when run with the demo command and can be regenerated on full Binance data.

## Current Findings

The repository currently ships with synthetic BTC-like sample data generation so the full pipeline can run without network access. Real findings should be produced after running `quant-research download` for BTCUSDT timeframes from 2020-01-01 through the latest available Binance data.

## Limitations

This is a research platform, not a live trading system. It does not model order book liquidity, exchange downtime, taxes, borrow costs, funding, latency, or live execution failures. LightGBM and XGBoost are included as dependencies for expansion; the first runnable ML baseline uses Random Forest for a lightweight smoke path.

## Future Work

Add richer exchange microstructure data, HMM regimes, Bayesian parameter optimization, experiment tracking, CI workflows, and scheduled report publishing.
