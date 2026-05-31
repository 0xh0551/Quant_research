from __future__ import annotations

from src.validation import DataValidator


def test_validation_passes_clean_sample(sample_ohlcv):
    report = DataValidator("1h").validate(sample_ohlcv)
    assert report.rows == len(sample_ohlcv)
    assert report.passed
