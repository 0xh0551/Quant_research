"""Statistical-rigor toolkit for strategy selection.

When a platform scans hundreds of strategy×symbol×timeframe×direction combos and
keeps the best Sharpe, the winner is contaminated by *selection bias*: the more
configurations you try, the higher the best in-sample Sharpe climbs purely by
luck. This module implements the standard defences (Bailey & López de Prado):

  • Probabilistic Sharpe Ratio (PSR) — confidence that the true Sharpe > a
    benchmark given track-record length, skew and kurtosis.
  • Deflated Sharpe Ratio (DSR) — PSR against a benchmark that is *raised* to
    account for the number of trials, so a Sharpe that merely looks good among
    many tries is correctly discounted.
  • Bootstrap confidence intervals — interval estimates (not point estimates)
    for Sharpe / CAGR / max-drawdown, via a moving-block bootstrap that respects
    autocorrelation.
  • CSCV / PBO — Probability of Backtest Overfitting: how often the
    in-sample-best configuration underperforms the median out-of-sample.

All functions are pure (numpy/scipy) and operate on per-bar return arrays.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329


# ── Sharpe building blocks ──────────────────────────────────────────────────

def _clean(returns: np.ndarray) -> np.ndarray:
    r = np.asarray(returns, dtype=float)
    return r[np.isfinite(r)]


def per_bar_sharpe(returns: np.ndarray) -> float:
    """Non-annualized Sharpe (mean/std of per-bar returns)."""
    r = _clean(returns)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else 0.0


def probabilistic_sharpe_ratio(
    observed_sr: float, n_obs: int, skew: float, kurtosis: float,
    benchmark_sr: float = 0.0,
) -> float:
    """P(true Sharpe > benchmark).  `observed_sr`/`benchmark_sr` are PER-BAR.

    `kurtosis` is the non-excess (Pearson) kurtosis (3.0 for a normal).
    Returns a probability in [0, 1].
    """
    if n_obs < 3:
        return 0.0
    denom = 1.0 - skew * observed_sr + ((kurtosis - 1.0) / 4.0) * observed_sr ** 2
    if denom <= 0:
        return float("nan")
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(stats.norm.cdf(z))


def _expected_max_sharpe(sr_std: float, n_trials: int) -> float:
    """Expected maximum of N independent Sharpe estimates (the deflation
    benchmark). Uses the false-strategy/extreme-value approximation."""
    if n_trials < 2 or sr_std <= 0:
        return 0.0
    n = float(n_trials)
    return sr_std * (
        (1.0 - EULER_MASCHERONI) * stats.norm.ppf(1.0 - 1.0 / n)
        + EULER_MASCHERONI * stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    )


def deflated_sharpe_ratio(
    observed_sr: float, n_obs: int, skew: float, kurtosis: float,
    n_trials: int, sr_variance: float,
) -> float:
    """Deflated Sharpe Ratio: PSR against a multiple-testing-adjusted benchmark.

    `observed_sr` per-bar; `sr_variance` is the variance of the per-bar Sharpe
    estimates *across the trials* (the breadth of what was searched).
    """
    sr_std = math.sqrt(max(sr_variance, 0.0))
    benchmark = _expected_max_sharpe(sr_std, max(n_trials, 1))
    return probabilistic_sharpe_ratio(observed_sr, n_obs, skew, kurtosis, benchmark)


def annualized_from_per_bar(per_bar_sr: float, bars_per_year: int) -> float:
    return per_bar_sr * math.sqrt(bars_per_year)


@dataclass
class SharpeStats:
    sharpe_ann: float
    sharpe_per_bar: float
    n_obs: int
    skew: float
    kurtosis: float
    psr: float            # P(true SR > 0)
    dsr: float            # deflated (multiple-testing aware); NaN if n_trials/var unknown


def sharpe_significance(
    returns: np.ndarray, bars_per_year: int,
    n_trials: int = 1, sr_variance: float | None = None,
) -> SharpeStats:
    """Full significance summary for one return stream."""
    r = _clean(returns)
    n = r.size
    sr_pb = per_bar_sharpe(r)
    sk = float(stats.skew(r)) if n > 2 else 0.0
    ku = float(stats.kurtosis(r, fisher=False)) if n > 3 else 3.0
    psr = probabilistic_sharpe_ratio(sr_pb, n, sk, ku, 0.0)
    if sr_variance is not None and n_trials > 1:
        dsr = deflated_sharpe_ratio(sr_pb, n, sk, ku, n_trials, sr_variance)
    else:
        dsr = float("nan")
    return SharpeStats(
        sharpe_ann=annualized_from_per_bar(sr_pb, bars_per_year),
        sharpe_per_bar=sr_pb, n_obs=n, skew=sk, kurtosis=ku, psr=psr, dsr=dsr,
    )


# ── bootstrap confidence intervals ──────────────────────────────────────────

def _moving_block_bootstrap(returns: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    n = returns.size
    if n == 0:
        return returns
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, max(n - block, 1), size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n] % n
    return returns[idx]


def bootstrap_metric_ci(
    returns: np.ndarray, bars_per_year: int,
    n_boot: int = 1000, alpha: float = 0.05, block: int | None = None, seed: int = 7,
) -> dict[str, dict[str, float]]:
    """Moving-block bootstrap CIs for annualized Sharpe, CAGR and max-drawdown."""
    r = _clean(returns)
    out = {k: {"point": 0.0, "low": 0.0, "high": 0.0} for k in ("sharpe", "cagr", "max_drawdown")}
    if r.size < 20:
        return out
    if block is None:
        block = max(2, int(round(r.size ** (1.0 / 3.0))))  # ~ n^(1/3) rule of thumb
    rng = np.random.default_rng(seed)

    def metrics(x: np.ndarray) -> tuple[float, float, float]:
        sd = x.std(ddof=1)
        sharpe = (x.mean() / sd) * math.sqrt(bars_per_year) if sd > 0 else 0.0
        eq = np.cumprod(1.0 + x)
        years = max(x.size / bars_per_year, 1.0 / bars_per_year)
        cagr = eq[-1] ** (1.0 / years) - 1.0 if eq[-1] > 0 else -1.0
        mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
        return sharpe, cagr, mdd

    point = metrics(r)
    samples = np.array([metrics(_moving_block_bootstrap(r, block, rng)) for _ in range(n_boot)])
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    for i, key in enumerate(("sharpe", "cagr", "max_drawdown")):
        col = samples[:, i]
        out[key] = {
            "point": float(point[i]),
            "low": float(np.percentile(col, lo)),
            "high": float(np.percentile(col, hi)),
        }
    return out


# ── CSCV / Probability of Backtest Overfitting ──────────────────────────────

def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray, n_splits: int = 16,
) -> dict[str, float]:
    """CSCV PBO (Bailey, Borwein, López de Prado, Zhu 2017).

    `returns_matrix`: shape (T, N) — T time observations × N configurations.
    Splits time into `n_splits` blocks, evaluates every balanced
    in-sample/out-of-sample partition, and measures how often the IS-best
    config lands below the OOS median (logit < 0).
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2 or M.shape[0] < n_splits:
        return {"pbo": float("nan"), "n_combinations": 0}
    T, N = M.shape
    s = n_splits - (n_splits % 2)  # must be even
    if s < 2:
        return {"pbo": float("nan"), "n_combinations": 0}
    block_idx = np.array_split(np.arange(T), s)
    blocks = list(range(s))

    def sr(sub: np.ndarray) -> np.ndarray:
        mu = sub.mean(axis=0)
        sd = sub.std(axis=0, ddof=1)
        sd[sd == 0] = np.nan
        return mu / sd

    logits: list[float] = []
    for is_combo in itertools.combinations(blocks, s // 2):
        is_set = set(is_combo)
        is_rows = np.concatenate([block_idx[b] for b in blocks if b in is_set])
        oos_rows = np.concatenate([block_idx[b] for b in blocks if b not in is_set])
        is_perf = sr(M[is_rows])
        oos_perf = sr(M[oos_rows])
        if not np.isfinite(is_perf).any():
            continue
        best = int(np.nanargmax(is_perf))
        # OOS rank (fraction) of the IS-best config
        valid = np.isfinite(oos_perf)
        if valid.sum() < 2:
            continue
        rank = (stats.rankdata(oos_perf[valid])[np.where(valid)[0] == best])
        if rank.size == 0:
            continue
        w = float(rank[0] / (valid.sum() + 1))
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1.0 - w)))

    if not logits:
        return {"pbo": float("nan"), "n_combinations": 0}
    arr = np.array(logits)
    return {
        "pbo": float((arr <= 0).mean()),
        "median_logit": float(np.median(arr)),
        "n_combinations": int(arr.size),
    }
