"""Time-series-safe machine learning research models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


@dataclass(frozen=True)
class MLResearchResult:
    """Machine learning evaluation result."""

    model_name: str
    metrics: dict[str, float]
    predictions: pd.Series


class TimeSeriesMLResearcher:
    """Train return or volatility forecasting models without shuffling observations."""

    def __init__(self, test_fraction: float = 0.25, random_state: int = 42) -> None:
        self.test_fraction = test_fraction
        self.random_state = random_state

    def train_random_forest(self, data: pd.DataFrame, feature_columns: list[str], target: pd.Series) -> MLResearchResult:
        """Train a Random Forest baseline on chronological train/test split."""

        frame = pd.concat([data[feature_columns], target.rename("target")], axis=1).dropna()
        split = int(len(frame) * (1 - self.test_fraction))
        train = frame.iloc[:split]
        test = frame.iloc[split:]
        model = RandomForestRegressor(n_estimators=200, max_depth=6, random_state=self.random_state, n_jobs=-1)
        model.fit(train[feature_columns], train["target"])
        predictions = pd.Series(model.predict(test[feature_columns]), index=test.index, name="prediction")
        return MLResearchResult("random_forest", {
            "mae": float(mean_absolute_error(test["target"], predictions)),
            "rmse": float(np.sqrt(mean_squared_error(test["target"], predictions))),
            "r2": float(r2_score(test["target"], predictions)),
        }, predictions)


def future_return_target(data: pd.DataFrame, horizon: int = 24) -> pd.Series:
    """Forward return target shifted to prevent lookahead during feature construction."""

    return data["close"].pct_change(horizon).shift(-horizon)


def volatility_target(data: pd.DataFrame, horizon: int = 24) -> pd.Series:
    """Future realized volatility target."""

    return data["close"].pct_change().rolling(horizon).std().shift(-horizon)
