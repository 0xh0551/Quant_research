"""Lightweight, dependency-free experiment tracking (+ optional MLflow).

Reproducibility needs three things recorded for every run: parameters, metrics,
and the *exact inputs* (random seed + a content hash of the dataset). This logs
all three to an append-only JSONL ledger (`outputs/experiments.jsonl`) and, if
MLflow happens to be installed, mirrors the run there too. No server required.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_LEDGER = Path("outputs/experiments.jsonl")


def set_global_seed(seed: int = 42) -> int:
    """Seed Python / NumPy / PYTHONHASHSEED for reproducible runs."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    return seed


def dataset_fingerprint(path: str | Path) -> str:
    """Stable content hash of a dataset file (first 16 hex of SHA-256)."""
    p = Path(path)
    if not p.exists():
        return "missing"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def log_run(
    name: str, params: dict[str, Any], metrics: dict[str, Any], *,
    seed: int | None = None, dataset: str | Path | None = None,
    tags: dict[str, Any] | None = None, ledger: Path = DEFAULT_LEDGER,
) -> dict[str, Any]:
    """Append one run to the JSONL ledger; mirror to MLflow if available."""
    record = {
        "ts": time.time(),
        "name": name,
        "params": params,
        "metrics": metrics,
        "seed": seed,
        "dataset_fingerprint": dataset_fingerprint(dataset) if dataset else None,
        "tags": tags or {},
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    try:  # optional mirror
        import mlflow
        with mlflow.start_run(run_name=name):
            mlflow.log_params({**params, "seed": seed})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))})
            if record["dataset_fingerprint"]:
                mlflow.set_tag("dataset_fingerprint", record["dataset_fingerprint"])
    except Exception:
        pass
    return record


def recent_runs(limit: int = 50, ledger: Path = DEFAULT_LEDGER) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    lines = ledger.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        ln = ln.strip()
        if ln:
            with contextlib.suppress(Exception):
                out.append(json.loads(ln))
    return list(reversed(out))
