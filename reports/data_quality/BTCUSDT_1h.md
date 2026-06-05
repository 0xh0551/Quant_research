# Data Quality Report

## Dataset

- Source: **User supplied Parquet dataset**
- Note: Source file: `data/processed/BTCUSDT_1h.parquet`
- Rows: `56201`
- Start: `2020-01-01 00:00:00+00:00`
- End: `2026-05-31 23:00:00+00:00`
- Passed: `True`

## Checks

| Check | Severity | Count | Details |
|---|---:|---:|---|
| duplicate_candles | error | 0 | Duplicate timestamps |
| missing_candles | warning | 31 | Expected timestamp continuity |
| malformed_rows | error | 0 | Negative, missing, or inconsistent OHLCV rows |
| extreme_outliers | warning | 3 | Absolute rolling z-score above 8 |
