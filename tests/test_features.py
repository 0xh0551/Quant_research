from __future__ import annotations

from src.features import FeatureBuilder


def test_feature_builder_generates_large_feature_set(sample_ohlcv):
    enriched = FeatureBuilder().build(sample_ohlcv)
    generated = [c for c in enriched.columns if c not in sample_ohlcv.columns]
    assert len(generated) >= 45
    assert "rsi_14" in enriched.columns
    assert "distance_from_ath" in enriched.columns
