from __future__ import annotations

from src.data.schema import normalize_timeframe, timeframe_to_milliseconds


def test_normalize_timeframe_removes_invisible_formatting_characters():
    assert normalize_timeframe("‍1h") == "1h"
    assert timeframe_to_milliseconds("‍1h") == 3_600_000
