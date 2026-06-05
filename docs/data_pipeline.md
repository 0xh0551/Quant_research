# Data Pipeline

The data layer handles acquisition from multiple exchanges, normalisation to a canonical OHLCV schema, incremental Parquet storage, and quality validation. All acquired data is stored identically regardless of source exchange.

## Storage Convention

All datasets are stored in `data/processed/` as Parquet files using the naming convention:

```
{exchange}_{symbol}_{timeframe}.parquet
```

| Field | Examples |
|---|---|
| `exchange` | `binance`, `nobitex`, `bybit`, `okx` |
| `symbol` | `BTCUSDT`, `ETHUSDT`, `BTCIRT` |
| `timeframe` | `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `3h`, `4h`, `1d` |

### OHLCV Schema

Every Parquet file has exactly six columns:

| Column | Type | Description |
|---|---|---|
| `timestamp` | `datetime64[ns, UTC]` | Bar open time, timezone-aware UTC |
| `open` | `float64` | Bar open price |
| `high` | `float64` | Bar high price |
| `low` | `float64` | Bar low price |
| `close` | `float64` | Bar close price |
| `volume` | `float64` | Base asset volume traded in the bar |

Data is sorted ascending by `timestamp`, deduplicated (last record wins on conflicts), and validated before writing.

## Acquisition Sources

### Binance (preferred path)

Binance provides free monthly archive ZIPs at `https://data.binance.vision/data/spot/monthly/klines/{symbol}/{timeframe}/`. The `BinanceBulkDownloader` fetches and parses these archives directly — much faster than paging through the REST API for historical data.

**Fallback:** For months where no bulk archive exists (current or very recent month), `CCXTFallbackDownloader` takes over and fetches the gap via paginated CCXT OHLCV calls.

**Pipeline flow:**

```
For each month in [start, end]:
    try:
        download monthly ZIP from data.binance.vision
        parse CSV inside ZIP
    except 404:
        record month as missing
        → fallback to CCXT for this month
concat all DataFrames → normalize → merge_incremental
```

### CCXT Exchanges (111 supported)

`CCXTFallbackDownloader` wraps any exchange available in the CCXT library. It paginates through OHLCV history using a configurable `limit` (default 1000 bars per request) and advances the `since` cursor until the requested end date is reached. Rate limiting is handled by CCXT's built-in `enableRateLimit` flag.

Supported quote assets for symbol discovery: `USDT`, `BTC`, `ETH`, `BNB`. Derivative (perpetual/futures) markets are excluded from the symbol list.

### Nobitex

Nobitex is an Iranian cryptocurrency exchange that provides a public TradingView UDF history endpoint:

```
GET https://apiv2.nobitex.ir/market/udf/history
    ?symbol=BTCUSDT
    &resolution=60       ← timeframe in minutes (or "D" for daily)
    &from=1672531200     ← Unix timestamp
    &to=1675123200
```

No authentication is required. The downloader chunks the requested range into batches of 500 candles and adds a 50 ms sleep between requests to be polite to the server.

**Timeframe mapping:**

| Internal | Nobitex resolution |
|---|---|
| `1m` | `1` |
| `5m` | `5` |
| `15m` | `15` |
| `30m` | `30` |
| `1h` | `60` |
| `2h` | `120` |
| `3h` | `180` |
| `4h` | `240` |
| `1d` | `D` |

## Incremental Updates

`ParquetDataStore.merge_incremental()` reads the existing Parquet file, concatenates the new data, deduplicates on `timestamp` (keeping the latest record for any conflict), and writes back. This means:

- Re-running a download never creates duplicates.
- Downloading a short recent window to catch up on a large historical dataset is efficient.
- Corrupt or partial files can be repaired by re-downloading the affected range.

## Normalisation (`normalize_ohlcv`)

Applied to every DataFrame before writing:

1. Cast `timestamp` to `datetime64[ns, UTC]`
2. Cast OHLCV columns to `float64`, coercing non-numeric values to `NaN`
3. Drop rows with any `NaN` in the six required columns
4. Drop duplicate `timestamp` values (keep last)
5. Sort ascending by `timestamp`
6. Reset integer index

## Validation

`src/validation/quality.py` can be run on any Parquet file:

```bash
uv run quant-research validate data/processed/binance_BTCUSDT_1h.parquet --timeframe 1h
```

Checks performed:

| Check | Description |
|---|---|
| Expected bar count | Compares actual rows to theoretical count for the timeframe and date range |
| Gap detection | Identifies consecutive timestamp jumps larger than 2× the expected interval |
| Duplicate timestamps | Flags any repeated timestamp values |
| OHLCV consistency | Verifies high ≥ open, close, low and low ≤ open, close, high |
| Zero-volume bars | Reports bars with zero or negative volume |
| Price outliers | Flags bars where close deviates more than 5 standard deviations from a rolling window |

## Web API

The web dashboard exposes these data-related endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/exchanges` | GET | List of all CCXT exchange IDs plus `nobitex` |
| `/api/symbols/{exchange}` | GET | Available trading pairs for an exchange (cached per session) |
| `/api/inventory` | GET | All Parquet files in `data/processed/` with metadata |
| `/api/download` | POST | Start a background download job; returns `job_id` |
| `/api/jobs/{id}/events` | GET | SSE stream of job progress (status, progress %, message) |
