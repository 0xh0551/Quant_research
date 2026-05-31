from __future__ import annotations

from src.data.storage import ParquetDataStore


def test_parquet_store_round_trip(tmp_path, sample_ohlcv):
    store = ParquetDataStore(tmp_path)
    path = store.write(sample_ohlcv, "BTCUSDT", "1h")
    loaded = store.read("BTCUSDT", "1h")
    assert path.exists()
    assert len(loaded) == len(sample_ohlcv)
    assert loaded["timestamp"].is_monotonic_increasing
