"""Data quality checks and Markdown report generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.data.schema import timeframe_to_pandas_freq


@dataclass(frozen=True)
class ValidationIssue:
    """A single data quality issue."""

    name: str
    severity: str
    count: int
    details: str


@dataclass(frozen=True)
class DataQualityReport:
    """Structured data quality report."""

    rows: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    issues: list[ValidationIssue]

    @property
    def passed(self) -> bool:
        """Return True when no error severity issues are present."""

        return not any(issue.severity == "error" and issue.count > 0 for issue in self.issues)


class DataValidator:
    """Validate OHLCV data for continuity and malformed candles."""

    def __init__(self, timeframe: str) -> None:
        self.timeframe = timeframe
        self.freq = timeframe_to_pandas_freq(timeframe)

    def validate(self, data: pd.DataFrame) -> DataQualityReport:
        """Run all validation checks against an OHLCV DataFrame."""

        frame = data.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.sort_values("timestamp")
        issues = [
            self._duplicates(frame),
            self._missing_candles(frame),
            self._malformed_rows(frame),
            self._outliers(frame),
        ]
        start = frame["timestamp"].min() if not frame.empty else None
        end = frame["timestamp"].max() if not frame.empty else None
        return DataQualityReport(rows=len(frame), start=start, end=end, issues=issues)

    def write_markdown(self, report: DataQualityReport, output_path: Path) -> Path:
        """Write a professional Markdown data quality report."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Data Quality Report",
            "",
            f"- Rows: `{report.rows}`",
            f"- Start: `{report.start}`",
            f"- End: `{report.end}`",
            f"- Passed: `{report.passed}`",
            "",
            "| Check | Severity | Count | Details |",
            "|---|---:|---:|---|",
        ]
        for issue in report.issues:
            lines.append(f"| {issue.name} | {issue.severity} | {issue.count} | {issue.details} |")
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path

    def _duplicates(self, frame: pd.DataFrame) -> ValidationIssue:
        count = int(frame["timestamp"].duplicated().sum())
        return ValidationIssue("duplicate_candles", "error", count, "Duplicate timestamps")

    def _missing_candles(self, frame: pd.DataFrame) -> ValidationIssue:
        if frame.empty:
            return ValidationIssue("missing_candles", "error", 0, "Dataset is empty")
        expected = pd.date_range(frame["timestamp"].min(), frame["timestamp"].max(), freq=self.freq, tz="UTC")
        missing = expected.difference(pd.DatetimeIndex(frame["timestamp"]))
        return ValidationIssue("missing_candles", "warning", len(missing), "Expected timestamp continuity")

    def _malformed_rows(self, frame: pd.DataFrame) -> ValidationIssue:
        numeric = ["open", "high", "low", "close", "volume"]
        invalid_price = (frame[numeric].isna().any(axis=1)) | (frame[numeric] < 0).any(axis=1)
        invalid_ohlc = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (
            frame["low"] > frame[["open", "close", "high"]].min(axis=1)
        )
        count = int((invalid_price | invalid_ohlc).sum())
        return ValidationIssue("malformed_rows", "error", count, "Negative, missing, or inconsistent OHLCV rows")

    def _outliers(self, frame: pd.DataFrame) -> ValidationIssue:
        returns = frame["close"].pct_change()
        rolling_std = returns.rolling(96, min_periods=20).std()
        zscore = (returns - returns.rolling(96, min_periods=20).mean()).abs() / rolling_std
        count = int((zscore > 8).sum())
        return ValidationIssue("extreme_outliers", "warning", count, "Absolute rolling z-score above 8")

