"""Financial labeling — triple-barrier method and meta-labeling.

The default `ml_signal` labels a bar by the sign of the *next* bar's return vs a
fixed threshold. That ignores volatility scaling and, worse, produces heavily
overlapping labels that leak across the train/test boundary. The triple-barrier
method (López de Prado, *Advances in Financial Machine Learning*) fixes both:

  • each observation is labeled by which of three barriers is touched first —
    a volatility-scaled profit-take, a volatility-scaled stop-loss, or a
    vertical (time) barrier;
  • it returns each label's *end time* (`t1`), which the purged CV needs to drop
    train samples whose outcome window overlaps the test set.

Meta-labeling then trains a secondary model to decide whether to *act* on the
primary model's side (and how big), which lifts precision and enables bet sizing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ewma_volatility(close: pd.Series, span: int = 50) -> pd.Series:
    """EWMA of per-bar returns — used to scale the barriers per regime."""
    returns = close.pct_change()
    return returns.ewm(span=span, adjust=False).std().bfill().fillna(0.0)


def triple_barrier_labels(
    close: pd.Series,
    *,
    vol: pd.Series | None = None,
    pt_mult: float = 1.5,
    sl_mult: float = 1.5,
    max_hold: int = 20,
    vol_span: int = 50,
) -> pd.DataFrame:
    """Label each bar by the first barrier touched within `max_hold` bars.

    Returns a DataFrame indexed like `close` with columns:
      label   ∈ {-1, 0, +1}   (stop / time-barrier / profit)
      ret     realized return to the touch
      t1      integer index of the touch (for purging)
    """
    close = close.reset_index(drop=True)
    n = len(close)
    if vol is None:
        vol = ewma_volatility(close, vol_span)
    vol = vol.reset_index(drop=True).to_numpy()
    px = close.to_numpy()

    labels = np.zeros(n, dtype=int)
    rets = np.zeros(n, dtype=float)
    t1 = np.arange(n, dtype=int)

    for i in range(n):
        v = vol[i]
        if not np.isfinite(v) or v <= 0:
            continue
        upper = px[i] * (1.0 + pt_mult * v)
        lower = px[i] * (1.0 - sl_mult * v)
        end = min(i + max_hold, n - 1)
        touched = end
        lab = 0
        for j in range(i + 1, end + 1):
            if px[j] >= upper:
                touched, lab = j, 1
                break
            if px[j] <= lower:
                touched, lab = j, -1
                break
        labels[i] = lab
        t1[i] = touched
        rets[i] = px[touched] / px[i] - 1.0

    return pd.DataFrame({"label": labels, "ret": rets, "t1": t1})


def meta_labels(primary_side: np.ndarray, realized_ret: np.ndarray) -> np.ndarray:
    """Meta-label: 1 if acting on the primary side was profitable, else 0.

    `primary_side` ∈ {-1,0,+1} is the primary model's call; `realized_ret` is the
    forward return to the label's touch. The secondary model learns *whether to
    take* the primary bet (precision/recall trade-off + bet sizing).
    """
    side = np.asarray(primary_side, dtype=float)
    ret = np.asarray(realized_ret, dtype=float)
    return ((side * ret) > 0).astype(int)
