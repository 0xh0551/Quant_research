# Architecture

The system is organized as a reproducible pipeline: acquisition, storage, validation, feature generation, factor research, strategy research, backtesting, robustness analysis, ML research, and publication reports.

## Design Principles

- Reproducible from raw data.
- Research logic belongs in modules, not only notebooks.
- Reports are generated artifacts with clear methodology.
- Time-series experiments preserve chronological order.
- Outputs are suitable for public portfolio review.

## Implementation Status

The current version contains a runnable professional scaffold with deterministic demo data, validation, feature generation, factor ranking, strategy baselines, backtesting, Monte Carlo analysis, ML baseline research, and portfolio aggregation. Full empirical conclusions should be regenerated after downloading complete BTCUSDT history.
