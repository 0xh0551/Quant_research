"""Factor research metrics for single-asset time-series features."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr


@dataclass(frozen=True)
class FactorResearchResult:
    """Container for factor ranking and diagnostics."""

    ranking: pd.DataFrame
    decay: pd.DataFrame
    correlation: pd.DataFrame


class FactorResearcher:
    """Evaluate predictive relationships between features and future returns."""

    def __init__(self, horizons: list[int] | None = None, quantiles: int = 5) -> None:
        self.horizons = horizons or [1, 3, 6, 12, 24]
        self.quantiles = quantiles

    def evaluate(self, data: pd.DataFrame, feature_columns: list[str]) -> FactorResearchResult:
        """Calculate IC, rank IC, conditional returns, stability, decay, and correlation."""

        rows: list[dict[str, float | str | int]] = []
        decay_rows: list[dict[str, float | str | int]] = []
        frame = data.copy()
        for horizon in self.horizons:
            target = frame["close"].pct_change(horizon).shift(-horizon)
            for feature in feature_columns:
                pair = pd.concat([frame[feature], target], axis=1).dropna()
                if pair.empty or pair.iloc[:, 0].nunique() < 2:
                    continue
                ic = pair.iloc[:, 0].corr(pair.iloc[:, 1])
                rank_ic = spearmanr(pair.iloc[:, 0], pair.iloc[:, 1]).statistic
                buckets = pd.qcut(pair.iloc[:, 0].rank(method="first"), self.quantiles, labels=False)
                conditional = pair.groupby(buckets).mean(numeric_only=True).iloc[:, 1]
                rows.append({
                    "feature": feature,
                    "horizon": horizon,
                    "ic": float(ic),
                    "rank_ic": float(rank_ic),
                    "conditional_spread": float(conditional.iloc[-1] - conditional.iloc[0]),
                    "observations": len(pair),
                })
                decay_rows.append({"feature": feature, "horizon": horizon, "rank_ic": float(rank_ic)})
        ranking = pd.DataFrame(rows)
        if not ranking.empty:
            ranking = ranking.sort_values("rank_ic", key=lambda s: s.abs(), ascending=False)
        return FactorResearchResult(ranking=ranking, decay=pd.DataFrame(decay_rows), correlation=frame[feature_columns].corr())

    def write_report(self, result: FactorResearchResult, output_path: Path) -> Path:
        """Write a Markdown factor research report."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        top = result.ranking.head(25)
        lines = [
            "# Factor Research Report",
            "",
            "## Top Predictive Features",
            "",
            top.to_markdown(index=False) if not top.empty else "No valid factor rows.",
            "",
            "## Methodology",
            "",
            "Features are compared against forward returns across multiple horizons. Rank IC is the primary ranking metric; conditional return spread is used as a monotonicity diagnostic.",
        ]
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path
