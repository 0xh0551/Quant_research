"""Purged + embargoed cross-validation for overlapping financial labels.

Plain k-fold leaks: when label i's outcome window (t1) overlaps a test fold, a
train sample carries information about the test period. PurgedKFold drops those
overlapping train samples and additionally *embargoes* a fraction of bars right
after each test fold (serial correlation bleeds forward too). Reference:
López de Prado, *Advances in Financial Machine Learning*, ch. 7.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


class PurgedKFold:
    """K-fold over time with purging of overlapping labels and an embargo.

    Parameters
    ----------
    n_splits : number of folds.
    t1       : array of label end-indices (one per sample); label i is "active"
               over [i, t1[i]].
    embargo_pct : fraction of the dataset embargoed after each test fold.
    """

    def __init__(self, n_splits: int = 5, t1: np.ndarray | None = None, embargo_pct: float = 0.01):
        self.n_splits = n_splits
        self.t1 = None if t1 is None else np.asarray(t1, dtype=int)
        self.embargo_pct = embargo_pct

    def split(self, X) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        n = len(X)
        idx = np.arange(n)
        t1 = self.t1 if self.t1 is not None else idx
        embargo = int(n * self.embargo_pct)
        fold_bounds = [(b[0], b[-1] + 1) for b in np.array_split(idx, self.n_splits)]

        for start, stop in fold_bounds:
            test_idx = idx[start:stop]
            test_min, test_max = start, stop - 1
            # train = everything whose label window does NOT overlap the test span,
            # minus an embargo after the test fold.
            train_mask = np.ones(n, dtype=bool)
            train_mask[start:stop] = False
            # purge: drop train samples whose [i, t1[i]] overlaps [test_min, test_max]
            overlap = (idx <= test_max) & (t1 >= test_min)
            train_mask &= ~overlap
            # embargo: drop a band right after the test fold
            if embargo > 0:
                emb_end = min(stop + embargo, n)
                train_mask[stop:emb_end] = False
            train_idx = idx[train_mask]
            if train_idx.size and test_idx.size:
                yield train_idx, test_idx

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits


def purged_walk_forward_splits(
    n: int, t1: np.ndarray | None = None, n_splits: int = 5, embargo_pct: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window walk-forward with purge+embargo (train always precedes test)."""
    idx = np.arange(n)
    t1 = idx if t1 is None else np.asarray(t1, dtype=int)
    embargo = int(n * embargo_pct)
    fold_bounds = [(b[0], b[-1] + 1) for b in np.array_split(idx, n_splits + 1)]
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for start, stop in fold_bounds[1:]:
        test_idx = idx[start:stop]
        # train = all bars strictly before the test fold whose label ends before it
        cutoff = start - embargo
        train_idx = idx[(idx < cutoff) & (t1 < start)]
        if train_idx.size and test_idx.size:
            splits.append((train_idx, test_idx))
    return splits
