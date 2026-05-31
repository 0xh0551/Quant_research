"""Walk-forward validation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardSplit:
    """Integer-location train/test split."""

    train_start: int
    train_end: int
    test_start: int
    test_end: int


def rolling_walk_forward_splits(n_rows: int, train_size: int, test_size: int, step_size: int | None = None) -> list[WalkForwardSplit]:
    """Create rolling walk-forward splits without lookahead leakage."""

    step = step_size or test_size
    splits: list[WalkForwardSplit] = []
    train_start = 0
    while train_start + train_size + test_size <= n_rows:
        train_end = train_start + train_size
        test_start = train_end
        test_end = test_start + test_size
        splits.append(WalkForwardSplit(train_start, train_end, test_start, test_end))
        train_start += step
    return splits
