from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def sample_ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = 300
    timestamps = pd.date_range("2020-01-01", periods=rows, freq="1h", tz="UTC")
    close = 10_000 * pd.Series(1 + rng.normal(0.0001, 0.01, rows)).cumprod().to_numpy()
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    volume = rng.lognormal(8, 0.25, rows)
    return pd.DataFrame({"timestamp": timestamps, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
