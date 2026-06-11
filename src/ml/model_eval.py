"""Validated ML evaluation — replaces the heuristic "ML fitness" with a real,
leakage-free, cross-validated score.

Pipeline: build technical features → triple-barrier labels (+ their t1) →
PurgedKFold CV of a gradient-boosting classifier → out-of-sample AUC/accuracy.
The mean OOS AUC is the honest "is there learnable structure here?" number.
Hyperparameters can be tuned with Optuna when installed (graceful fallback to a
small random search otherwise).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.library import _rsi, _true_range
from src.ml.cv import PurgedKFold
from src.ml.labeling import ewma_volatility, triple_barrier_labels


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Technical feature matrix (same family as the ml_signal strategy)."""
    close, high, low = df["close"], df["high"], df["low"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std().clip(lower=1e-9)
    atr = _true_range(high, low, close).rolling(14).mean()
    feats = pd.DataFrame({
        "rsi": _rsi(close, 14).fillna(50.0),
        "macd": ((ema12 - ema26) / close.clip(lower=1e-9)).fillna(0.0),
        "bb_pct": ((close - bb_mid) / bb_std).fillna(0.0),
        "atr": (atr / close.clip(lower=1e-9)).fillna(0.0),
        "ret5": close.pct_change(5).fillna(0.0),
        "ret20": close.pct_change(20).fillna(0.0),
        "vol": ewma_volatility(close, 50),
    }).fillna(0.0)
    return feats


@dataclass
class CVResult:
    mean_auc: float
    std_auc: float
    mean_accuracy: float
    n_splits: int
    n_samples: int
    fold_auc: list[float] = field(default_factory=list)
    best_params: dict | None = None
    note: str = ""


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Binary ROC-AUC via Mann-Whitney; robust to single-class folds (→0.5)."""
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.5
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, scores.size + 1)
    auc = (ranks[y_true == 1].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size)
    return float(auc)


def evaluate_dataset(
    df: pd.DataFrame, *, n_splits: int = 5, embargo_pct: float = 0.02,
    max_hold: int = 24, pt_mult: float = 1.5, sl_mult: float = 1.5,
    params: dict | None = None,
) -> CVResult:
    """Purged-CV evaluation of a GBM on triple-barrier (up vs not-up) labels."""
    try:
        from sklearn.ensemble import GradientBoostingClassifier
    except ImportError as e:  # pragma: no cover
        raise ImportError("scikit-learn required") from e

    df = df.reset_index(drop=True)
    if len(df) < 300:
        return CVResult(0.5, 0.0, 0.0, 0, len(df), note="insufficient_data")

    feats = build_features(df)
    bars = triple_barrier_labels(df["close"], max_hold=max_hold, pt_mult=pt_mult, sl_mult=sl_mult)
    y = (bars["label"].to_numpy() > 0).astype(int)      # profit-take touched first
    t1 = bars["t1"].to_numpy()
    X = feats.to_numpy()

    valid = np.isfinite(X).all(axis=1)
    X, y, t1 = X[valid], y[valid], t1[valid]
    if y.sum() < 10 or (len(y) - y.sum()) < 10:
        return CVResult(0.5, 0.0, 0.0, 0, len(y), note="degenerate_labels")

    params = params or {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.05}
    cv = PurgedKFold(n_splits=n_splits, t1=t1, embargo_pct=embargo_pct)
    aucs, accs = [], []
    for tr, te in cv.split(X):
        if y[tr].sum() == 0 or y[tr].sum() == len(tr):
            continue
        model = GradientBoostingClassifier(random_state=42, **params)
        model.fit(X[tr], y[tr])
        proba = model.predict_proba(X[te])[:, 1]
        aucs.append(_auc(y[te], proba))
        accs.append(float(((proba > 0.5).astype(int) == y[te]).mean()))

    if not aucs:
        return CVResult(0.5, 0.0, 0.0, 0, len(y), note="no_valid_folds")
    return CVResult(
        mean_auc=float(np.mean(aucs)), std_auc=float(np.std(aucs)),
        mean_accuracy=float(np.mean(accs)), n_splits=len(aucs), n_samples=len(y),
        fold_auc=[round(a, 4) for a in aucs], best_params=params,
    )


def optimize_hyperparams(df: pd.DataFrame, n_trials: int = 25, **eval_kwargs) -> CVResult:
    """Tune GBM hyperparameters maximizing purged-CV AUC.

    Uses Optuna (Bayesian TPE) when installed; otherwise a deterministic random
    search over the same space. Either way the search is honest — every trial is
    scored by leakage-free purged CV.
    """
    space_random = {
        "n_estimators": [80, 120, 200, 300],
        "max_depth": [2, 3, 4],
        "learning_rate": [0.02, 0.05, 0.1],
        "subsample": [0.7, 0.85, 1.0],
    }
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_categorical("n_estimators", space_random["n_estimators"]),
                "max_depth": trial.suggest_categorical("max_depth", space_random["max_depth"]),
                "learning_rate": trial.suggest_categorical("learning_rate", space_random["learning_rate"]),
                "subsample": trial.suggest_categorical("subsample", space_random["subsample"]),
            }
            return evaluate_dataset(df, params=params, **eval_kwargs).mean_auc

        study = optuna.create_study(direction="maximize",
                                    sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        best = evaluate_dataset(df, params=study.best_params, **eval_kwargs)
        best.note = f"optuna:{n_trials}"
        return best
    except ImportError:
        rng = np.random.default_rng(42)
        best: CVResult | None = None
        for _ in range(min(n_trials, 12)):
            params = {k: rng.choice(v).item() for k, v in space_random.items()}
            res = evaluate_dataset(df, params=params, **eval_kwargs)
            if best is None or res.mean_auc > best.mean_auc:
                best = res
        if best is not None:
            best.note = "random_search(optuna_unavailable)"
        return best or CVResult(0.5, 0.0, 0.0, 0, len(df))
