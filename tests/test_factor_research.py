from __future__ import annotations

from src.factors import FactorResearcher
from src.features import FeatureBuilder


def test_factor_research_outputs_ranking(sample_ohlcv):
    enriched = FeatureBuilder().build(sample_ohlcv)
    features = ["ema_20", "rsi_14", "distance_from_ath"]
    result = FactorResearcher([1]).evaluate(enriched, features)
    assert not result.ranking.empty
    assert {"feature", "rank_ic"}.issubset(result.ranking.columns)
