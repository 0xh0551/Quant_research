"""Portfolio construction across selected edges.

Treating each edge independently and full-sizing all of them ignores that they
share risk (correlated symbols, same regime exposure). These allocators are
correlation-aware:

  • equal_weight / inverse_vol — baselines.
  • risk_parity — equalize each asset's risk contribution.
  • hrp — Hierarchical Risk Parity (López de Prado 2016): cluster by correlation,
    quasi-diagonalize, then recursively bisect the variance. More robust than
    mean-variance because it never inverts the (noisy) covariance matrix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def _cov_corr(returns: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    cov = returns.cov()
    corr_np = returns.corr().fillna(0.0).to_numpy().copy()
    np.fill_diagonal(corr_np, 1.0)
    return cov, corr_np


def equal_weight(returns: pd.DataFrame) -> dict[str, float]:
    cols = list(returns.columns)
    w = 1.0 / len(cols)
    return dict.fromkeys(cols, w)


def inverse_vol(returns: pd.DataFrame) -> dict[str, float]:
    vol = returns.std().replace(0, np.nan)
    inv = (1.0 / vol).fillna(0.0)
    if inv.sum() == 0:
        return equal_weight(returns)
    w = inv / inv.sum()
    return {c: float(w[c]) for c in returns.columns}


def risk_parity(returns: pd.DataFrame, iters: int = 250, lr: float = 0.01) -> dict[str, float]:
    """Equal risk contribution via simple multiplicative gradient updates."""
    cov = returns.cov().to_numpy()
    n = cov.shape[0]
    if n == 1:
        return {returns.columns[0]: 1.0}
    w = np.ones(n) / n
    for _ in range(iters):
        mrc = cov @ w                       # marginal risk contribution
        rc = w * mrc                        # risk contribution
        target = rc.mean()
        w *= (1 + lr * (target - rc) / (np.abs(rc) + 1e-12))
        w = np.clip(w, 1e-6, None)
        w /= w.sum()
    return {c: float(w[i]) for i, c in enumerate(returns.columns)}


def _quasi_diag(link: np.ndarray) -> list[int]:
    link = link.astype(int)
    n = link[-1, 3]
    items = [link[-1, 0], link[-1, 1]]
    while max(items) >= n:
        new = []
        for it in items:
            if it >= n:
                row = link[it - n]
                new.extend([int(row[0]), int(row[1])])
            else:
                new.append(int(it))
        items = new
    return items


def hrp(returns: pd.DataFrame) -> dict[str, float]:
    """Hierarchical Risk Parity weights."""
    cols = list(returns.columns)
    if len(cols) == 1:
        return {cols[0]: 1.0}
    cov, corr_np = _cov_corr(returns)
    dist = np.sqrt(np.clip((1.0 - corr_np) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    try:
        link = linkage(squareform(dist, checks=False), method="single")
    except Exception:
        return inverse_vol(returns)
    order = _quasi_diag(link)
    cov_np = cov.to_numpy()

    def cluster_var(idx: list[int]) -> float:
        sub = cov_np[np.ix_(idx, idx)]
        iv = 1.0 / np.diag(sub)
        iv /= iv.sum()
        return float(iv @ sub @ iv)

    w = pd.Series(1.0, index=order)
    clusters = [order]
    while clusters:
        clusters = [c[j:k] for c in clusters for j, k in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0, v1 = cluster_var(c0), cluster_var(c1)
            alpha = 1.0 - v0 / (v0 + v1) if (v0 + v1) > 0 else 0.5
            w[c0] *= alpha
            w[c1] *= 1.0 - alpha
    return {cols[i]: float(w[i]) for i in order}


def build_portfolio(returns: pd.DataFrame, method: str = "hrp") -> dict:
    """Return weights + the resulting portfolio's risk profile."""
    returns = returns.dropna(how="all", axis=1).fillna(0.0)
    if returns.shape[1] == 0:
        return {"method": method, "weights": {}, "metrics": {}}
    fn = {"hrp": hrp, "risk_parity": risk_parity, "inverse_vol": inverse_vol,
          "equal_weight": equal_weight}.get(method, hrp)
    weights = fn(returns)
    w = np.array([weights[c] for c in returns.columns])
    port_ret = returns.to_numpy() @ w
    cov = returns.cov().to_numpy()
    port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    # diversification ratio = weighted avg vol / portfolio vol
    avg_vol = float(w @ returns.std().to_numpy())
    return {
        "method": method,
        "weights": {c: round(weights[c], 4) for c in returns.columns},
        "metrics": {
            "portfolio_vol_per_bar": round(port_vol, 6),
            "mean_return_per_bar": round(float(port_ret.mean()), 6),
            "diversification_ratio": round(avg_vol / port_vol, 3) if port_vol > 0 else 0.0,
            "n_assets": int(returns.shape[1]),
            "avg_pairwise_corr": round(float(returns.corr().values[np.triu_indices(returns.shape[1], 1)].mean()), 3) if returns.shape[1] > 1 else 0.0,
        },
    }
