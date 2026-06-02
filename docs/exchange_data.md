# Multi-Exchange Data And Unified Research

The data layer supports exchange-specific OHLCV ingestion while preserving a shared normalized schema: `timestamp`, `open`, `high`, `low`, `close`, and `volume`. Exchange-aware datasets are stored with an exchange prefix, for example `binance_BTCUSDT_1h.parquet` and `nobitex_BTCIRT_1d.parquet`.

## Nobitex

Nobitex public market OHLC data is downloaded from the official UDF history endpoint documented in the Nobitex API docs repository and documentation site.

- Base URL: `https://apiv2.nobitex.ir`
- Endpoint: `GET /market/udf/history`
- Required parameters: `symbol`, `resolution`, `to`
- Optional parameters used by this project: `from`, `page`
- Response arrays: `t`, `o`, `h`, `l`, `c`, `v`
- Maximum candles per request: 500

Supported project timeframe mappings:

| Project timeframe | Nobitex resolution |
|---|---:|
| `1m` | `1` |
| `5m` | `5` |
| `1h` | `60` |
| `1d` | `D` |

Nobitex documentation notes that minute candles are available from the beginning of Persian year 1401, roughly 2022-03-21 Gregorian. For earlier minute-level requests, expect `no_data` or partial coverage. Daily candles may align to the exchange/local-market daily boundary rather than midnight UTC.

## Commands

```bash
quant-research download-exchange --exchange nobitex --symbol BTCIRT --timeframe 1d --start 2024-01-01 --refresh
quant-research download-exchange-all --exchange nobitex --symbol BTCIRT --timeframes 1m,5m,1h,1d --start 2022-03-21 --refresh
quant-research data-status --exchange nobitex --symbol BTCIRT
quant-research research-exchange --exchange nobitex --symbol BTCIRT --timeframe 1d --start 2024-01-01
```

## Cross-Exchange Comparison

Use `compare-datasets` to create a coverage table and close-return correlation matrix across arbitrary local Parquet datasets.

```bash
quant-research compare-datasets data/processed/binance_BTCUSDT_1d.parquet data/processed/nobitex_BTCIRT_1d.parquet
```

## Unified Research Dashboard

Use `research-all` after downloading one or more exchange datasets. The command scans local Parquet files, runs every strategy on every dataset, calculates cross-dataset metrics, and writes a single HTML dashboard plus CSV exports.

```bash
quant-research research-all --data-dir data/processed --output reports/global_research/index.html
```

The dashboard includes dataset coverage, return distribution statistics, skewness, kurtosis, VaR/CVaR, strategy ranking tables, Sharpe and drawdown heatmaps, risk/return scatter plots, equity curves, drawdown curves, and return histograms with normal-curve overlays.
