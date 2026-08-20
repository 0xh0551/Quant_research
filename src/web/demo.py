"""Synthetic home-screen payload for public screenshots and demos.

The launcher renders live trading state: fleet equity, open positions, per-bot
PnL, the symbols behind current edges. That is fine on the operator's own
screen and wrong in a README on a public repository, so `QR_DEMO=1` swaps the
summary for this fixture instead.

It is deliberately the *same shape* as the real payload — a test asserts field
parity — so a screenshot taken here shows the real interface with invented
numbers, never a mock-up that has drifted from what the code does. Bot names and
figures are made up; the tickers are public instruments.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any


def enabled() -> bool:
    return os.getenv("QR_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def summary() -> dict[str, Any]:
    """A plausible, entirely invented snapshot in the live payload's shape."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "demo": True,
        "tiles": {
            "inventory": {
                "n_datasets": 2418, "n_symbols": 512, "total_gb": 1.18,
                "matrix": {
                    "venues": ["binance", "bybit", "okx", "gate", "hyperliquid"],
                    "timeframes": ["15m", "1h", "4h", "1d"],
                    "cells": [[412, 412, 412, 96], [366, 366, 366, 74],
                              [188, 171, 154, 41], [140, 122, 104, 28],
                              [96, 88, 71, 19]],
                },
            },
            "download": {
                "recency": [{"k": "<1h", "v": 118}, {"k": "<6h", "v": 402},
                            {"k": "<24h", "v": 1731}, {"k": "<7d", "v": 122},
                            {"k": "older", "v": 45}],
                "n_venues": 5, "newest_age_h": 0.4, "n_datasets": 2418,
            },
            "quality": {
                "scannable_pct": 71.4, "n_scannable": 1726, "n_datasets": 2418,
                "median_bars": 11240, "stale_gt_3d": 38,
            },
            "research": {
                "n_runs": 146, "n_symbols": 512,
                "first": "2018-06-01", "last": "2026-08-20",
                "median_span_days": 412, "max_span_days": 2982,
            },
            "insights": {
                "gauges": [{"k": "event_risk", "v": 0.28, "max": 1.0},
                           {"k": "dvol_pct", "v": 0.64, "max": 1.0},
                           {"k": "ls_skew", "v": 0.41, "max": 1.0}],
                "dvol_btc": 42.6, "ls_ratio_btc": 1.11, "n_event_symbols": 64,
            },
            "lab": {
                "strategies": ["ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion",
                               "donchian_breakout", "atr_breakout", "macd_cross",
                               "stochastic_mr", "ichimoku", "supertrend", "vwap_deviation",
                               "cmf_trend", "hammer_pattern", "engulfing", "ml_signal"],
                "n_strategies": 14, "n_params": 32,
            },
            "report": {
                "sharpes": [3.41, 3.18, 2.96, 2.74, 2.61, 2.48, 2.33, 2.21, 2.09, 1.97,
                            1.88, 1.79, 1.71, 1.62, 1.55, 1.47, 1.39, 1.31, 1.24, 1.16],
                "n_top": 20, "best_sharpe": 3.41, "best_return": 0.0784, "age_h": 6.2,
            },
            "edges": {
                "funnel": [{"k": "scanned", "v": 51820}, {"k": "passed", "v": 3164},
                           {"k": "robust", "v": 142}, {"k": "deployable", "v": 96}],
                "median_pbo": 0.31, "live_timeframe": "1h", "age_h": 6.2,
            },
            "trials": {
                "age_h": 6.2, "n_deflated_pass": 11, "n_unique": 51820, "pass_rate": 6.1,
                "strategies": [{"k": "vwap_deviation", "v": 14.2},
                               {"k": "bollinger_mean_reversion", "v": 11.8},
                               {"k": "ema_trend", "v": 9.4},
                               {"k": "macd_cross", "v": 7.1},
                               {"k": "stochastic_mr", "v": 5.6}],
            },
            "capacity": {
                "points": [{"v": 34000.0, "k": "ARBUSDT"}, {"v": 52000.0, "k": "OPUSDT"},
                           {"v": 78000.0, "k": "LINKUSDT"}, {"v": 96000.0, "k": "AVAXUSDT"},
                           {"v": 145000.0, "k": "DOTUSDT"}, {"v": 210000.0, "k": "ADAUSDT"},
                           {"v": 380000.0, "k": "SOLUSDT"}, {"v": 620000.0, "k": "XRPUSDT"},
                           {"v": 1250000.0, "k": "ETHUSDT"}, {"v": 3100000.0, "k": "BTCUSDT"}],
                "median_capacity": 145000.0, "min_capacity": 34000.0,
                "n_books": 58, "age_h": 3.1,
            },
            "crossex": {
                "carry": [{"base": "SOL", "short": 24.6, "short_venue": "bybit",
                           "long": -8.2, "long_venue": "okx", "spread": 32.8},
                          {"base": "ARB", "short": 18.1, "short_venue": "okx",
                           "long": -4.4, "long_venue": "gate", "spread": 22.5},
                          {"base": "LINK", "short": 12.7, "short_venue": "gate",
                           "long": 1.2, "long_venue": "binance", "spread": 11.5},
                          {"base": "BTC", "short": 9.4, "short_venue": "binance",
                           "long": 2.8, "long_venue": "hyperliquid", "spread": 6.6}],
                "best_spread": 32.8, "multi_venue_symbols": 341, "n_venues": 5,
                "carry_age_h": 0.6,
            },
            "fleet": {
                "gross_leverage": 1.42, "max_gross_leverage": 3.0, "equity_usd": 25000.0,
                "net_beta_delta_pct": 6.4, "n_positions": 12, "n_alerts": 0, "age_h": 0.3,
            },
            "portfolio": {
                "top": [{"base": "BTC", "pct": 26.4}, {"base": "ETH", "pct": 19.1},
                        {"base": "SOL", "pct": 14.8}, {"base": "LINK", "pct": 12.2},
                        {"base": "ARB", "pct": 10.6}, {"base": "OP", "pct": 9.3},
                        {"base": "AVAX", "pct": 7.6}],
                "gross_usd": 35400.0, "hhi": 0.17, "n_assets": 7, "age_h": 0.3,
            },
            "stress": {
                "ticks": [{"k": "outage_4h", "v": -4.8}, {"k": "gap_20", "v": -3.6},
                          {"k": "aug_2024", "v": -2.9}, {"k": "gap_10", "v": -1.8},
                          {"k": "apr_2025", "v": -1.1}, {"k": "funding_spike", "v": -0.4},
                          {"k": "melt_up_10", "v": 2.2}, {"k": "melt_up_20", "v": 4.1}],
                "worst_pct": -4.8, "worst_key": "outage_4h",
                "n_liquidations": 0, "n_scenarios": 10, "age_h": 9.4,
            },
            "attribution": {
                "steps": [{"k": "intended", "v": 1840.0}, {"k": "fees", "v": -412.0},
                          {"k": "entry", "v": -96.0}, {"k": "exit", "v": -148.0},
                          {"k": "funding", "v": -74.0}],
                "net": 1110.0, "window_days": 45.0, "age_h": 4.8,
            },
            "altdata": {
                "dvol_series": [38.2, 37.9, 38.6, 39.4, 39.1, 38.7, 40.2, 41.6, 42.8, 44.1,
                                43.6, 42.9, 41.8, 40.9, 41.4, 42.2, 43.8, 45.6, 44.9, 43.2,
                                42.1, 41.5, 40.8, 41.2, 42.6, 43.9, 45.1, 44.4, 43.1, 42.6],
                "dvol_btc": 42.6, "dvol_eth": 51.3,
                "liquidations_24h_usd": 128_400_000.0, "age_h": 0.5,
            },
            "pipeline": {
                "jobs": [{"k": "wf_scan", "status": "ok", "used": 0.62},
                         {"k": "pair_rotation", "status": "ok", "used": 0.48},
                         {"k": "altdata_refresh", "status": "ok", "used": 0.41},
                         {"k": "fleet_risk", "status": "ok", "used": 0.22},
                         {"k": "capacity", "status": "ok", "used": 0.18},
                         {"k": "attribution", "status": "ok", "used": 0.14},
                         {"k": "stress", "status": "ok", "used": 0.36},
                         {"k": "data_refresh", "status": "ok", "used": 0.09},
                         {"k": "funding_refresh", "status": "ok", "used": 0.27},
                         {"k": "scorecard", "status": "ok", "used": 0.31},
                         {"k": "heartbeat", "status": "ok", "used": 0.05}],
                "ok": 11, "late": 0, "missing": 0, "n_jobs": 11, "healthy": True,
                "run_state": "idle", "run_step": None, "age_h": 0.2,
            },
            "models": {
                "split": [{"k": "Alpha", "v": 6, "net": 412.0},
                          {"k": "Beta", "v": 5, "net": 188.0},
                          {"k": "Gamma", "v": 4, "net": -96.0}],
                "n_pairs": 15, "n_bots": 3, "n_dropped": 22, "age_h": 0.9,
            },
            "logs": {
                "hourly": [42, 38, 51, 44, 39, 61, 88, 74, 52, 47, 43, 56,
                           118, 96, 71, 58, 49, 44, 41, 53, 67, 59, 48, 44],
                "n_hours": 24, "n_errors": 0, "n_warnings": 2, "n_lines": 3200,
            },
        },
    }
