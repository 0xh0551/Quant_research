# Exchange Data & Multi-Exchange Research

The data layer supports OHLCV ingestion from any exchange while storing all data in an identical normalised schema. Exchange-prefixed filenames keep datasets unambiguous: `binance_BTCUSDT_1h.parquet`, `nobitex_BTCIRT_1d.parquet`, `bybit_ETHUSDT_4h.parquet`.

## Supported Sources

### Binance

- **Preferred path:** Monthly ZIP archives from `https://data.binance.vision/data/spot/monthly/klines/{symbol}/{timeframe}/`
- **Fallback:** CCXT paginated API for months without an archive (current and near-current months)
- **Speed:** Bulk download is ~10× faster than API paging for long historical periods
- **Coverage:** Spot OHLCV from exchange launch (2017) through present

### CCXT (111 exchanges)

Any exchange supported by the [CCXT](https://github.com/ccxt/ccxt) library can be used. Common options:

| Exchange | Notable pairs |
|---|---|
| Bybit | BTC, ETH, SOL/USDT |
| OKX | BTC, ETH, DOGE/USDT |
| KuCoin | Long tail of altcoins |
| Gate.io | Wide altcoin coverage |
| Kraken | EUR pairs, institutional |
| Bitfinex | BTC/USD, deep history |

CCXT uses paginated `fetchOHLCV` with a configurable `limit` (default 1000 bars). Rate limiting is managed automatically by CCXT's `enableRateLimit` flag.

### Nobitex

Nobitex is an Iranian spot exchange. OHLCV data is available from the public TradingView UDF endpoint — no API key required.

**Endpoint:**
```
GET https://apiv2.nobitex.ir/market/udf/history
    ?symbol=BTCUSDT
    &resolution=60
    &from=<unix_timestamp>
    &to=<unix_timestamp>
```

**Response format:**
```json
{
  "s": "ok",
  "t": [1672531200, ...],   ← open timestamps (Unix seconds)
  "o": [16600.0, ...],
  "h": [16650.0, ...],
  "l": [16550.0, ...],
  "c": [16620.0, ...],
  "v": [123.4, ...]
}
```

**Timeframe mapping:**

| Internal | Nobitex `resolution` | Available since |
|---|---|---|
| `1m` | `1` | ~2022-03-21 (Persian year 1401) |
| `5m` | `5` | ~2022-03-21 |
| `15m` | `15` | ~2022-03-21 |
| `30m` | `30` | ~2022-03-21 |
| `1h` | `60` | Earlier |
| `2h` | `120` | Earlier |
| `3h` | `180` | Earlier |
| `4h` | `240` | Earlier |
| `1d` | `D` | Exchange launch |

**Common Nobitex symbols:** `BTCUSDT`, `ETHUSDT`, `BTCIRT`, `ETHIRT`, `BNBUSDT`, `ADAUSDT`, `DOTUSDT`, `LTCUSDT`, `XRPUSDT`, `SOLUSDT`

Note: IRT (Iranian Toman) pairs price the asset directly in Toman. These pairs have very different price scales and cannot be directly compared with USDT pairs without currency conversion.

## Web Dashboard: Symbol Discovery

When a user selects an exchange in the Download section, the dashboard calls `/api/symbols/{exchange}`. For Nobitex, a hardcoded list of common symbols is returned immediately. For CCXT exchanges, the exchange's `load_markets()` is called and the result is cached in memory for the session. Only USDT, BTC, ETH, and BNB quote assets are included; perpetual and futures markets are excluded.

## CLI Commands

```bash
# Download single timeframe from Nobitex
uv run quant-research download-exchange \
    --exchange nobitex --symbol BTCUSDT --timeframe 1h --start 2023-01-01

# Download all timeframes
uv run quant-research download-exchange-all \
    --exchange nobitex --symbol BTCIRT --timeframes 1h,4h,1d --start 2022-03-21

# Check data coverage
uv run quant-research data-status --exchange nobitex --symbol BTCUSDT

# Compare datasets from different exchanges
uv run quant-research compare-datasets \
    data/processed/binance_BTCUSDT_1d.parquet \
    data/processed/nobitex_BTCUSDT_1d.parquet

# Run all strategies on all local datasets, generate unified HTML dashboard
uv run quant-research research-all \
    --data-dir data/processed \
    --output reports/global_research/index.html
```

## Cross-Exchange Analysis

The `compare-datasets` command generates:
- **Coverage table** — date range, row count, and timeframe for each dataset
- **Close-return correlation matrix** — useful for identifying pairs that move together vs diverge (e.g. BTCUSDT on Binance vs Nobitex should be near 1.0; IRT pairs add FX noise)
- **Return distribution statistics** — mean, std, skewness, kurtosis, VaR, CVaR per dataset

## Unified Research Dashboard (static)

`research-all` runs every strategy on every Parquet file found in the data directory and writes a single standalone HTML file. This is the static equivalent of the web dashboard's Report section, useful for sharing results or archiving a research snapshot.

The HTML includes: strategy ranking tables, equity curves, drawdown charts, monthly return heatmaps, parameter stability analysis, and dataset coverage statistics.
