"""Unified multi-dataset research dashboard generation."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from src.backtesting import BacktestConfig, VectorizedBacktester
from src.strategies import build_strategy_signals
from src.strategies.rules import (
    ATRBreakoutConfig,
    BollingerMeanReversionConfig,
    DonchianBreakoutConfig,
    EMATrendConfig,
    RSIMeanReversionConfig,
    atr_breakout,
    bollinger_mean_reversion,
    donchian_breakout,
    ema_trend,
    rsi_mean_reversion,
)

KNOWN_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"}
HIGHER_IS_BETTER_METRICS = [
    "sharpe",
    "sortino",
    "calmar",
    "cagr",
    "total_return",
    "profit_factor",
    "win_rate",
    "trades_count",
    "avg_trade",
    "median_trade",
    "excess_cagr_vs_buy_hold",
    "test_cagr",
]
LOWER_IS_BETTER_METRICS = ["max_drawdown_abs"]
WALK_FORWARD_TRAIN_START = pd.Timestamp("2020-01-01", tz="UTC")
WALK_FORWARD_TRAIN_END = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
WALK_FORWARD_TEST_START = pd.Timestamp("2025-01-01", tz="UTC")
WALK_FORWARD_TEST_END = pd.Timestamp("2026-12-31 23:59:59", tz="UTC")


@dataclass(frozen=True)
class DashboardResult:
    """Generated dashboard artifact paths."""

    html_path: Path
    metrics_path: Path
    dataset_stats_path: Path
    parameter_stability_path: Path


@dataclass(frozen=True)
class StrategyVariant:
    """One nearby parameter variant for stability checks."""

    label: str
    params: str
    signal_builder: Callable[[pd.DataFrame], pd.Series]


def build_global_research_dashboard(
    data_dir: Path,
    output_path: Path,
    strategies: list[str],
    pattern: str = "*.parquet",
) -> DashboardResult:
    """Run all strategies on every local dataset and render one HTML dashboard."""

    dataset_paths = sorted(data_dir.glob(pattern))
    if not dataset_paths:
        raise ValueError(f"No Parquet datasets found in {data_dir} with pattern {pattern}")

    metric_rows: list[dict[str, float | str]] = []
    dataset_rows: list[dict[str, float | str | int]] = []
    equity_curves: dict[str, dict[str, pd.Series]] = {}
    drawdown_curves: dict[str, dict[str, pd.Series]] = {}
    market_returns: dict[str, pd.Series] = {}
    data_by_dataset: dict[str, pd.DataFrame] = {}
    config_by_dataset: dict[str, BacktestConfig] = {}

    for path in dataset_paths:
        data = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        data_by_dataset[parse_dataset_id(path)["dataset"]] = data
        dataset = parse_dataset_id(path)
        dataset_id = dataset["dataset"]
        timeframe = dataset["timeframe"]
        returns = data["close"].pct_change().dropna().rename(dataset_id)
        market_returns[dataset_id] = returns.reset_index(drop=True)
        dataset_rows.append(_dataset_stats(path, data, returns, dataset))

        config = BacktestConfig(periods_per_year=_periods_per_year(timeframe))
        config_by_dataset[dataset_id] = config
        backtester = VectorizedBacktester(config)
        buy_hold = backtester.run(data, pd.Series(1.0, index=data.index))
        buy_hold_metrics = _buy_hold_comparison_metrics(buy_hold)
        equity_curves[dataset_id] = {}
        drawdown_curves[dataset_id] = {}
        for strategy in strategies:
            signals = build_strategy_signals(data, strategy)
            result = backtester.run(data, signals)
            equity = (result.equity / result.equity.iloc[0]).reset_index(drop=True)
            drawdown = (result.equity / result.equity.cummax() - 1).reset_index(drop=True)
            equity_curves[dataset_id][strategy] = equity
            drawdown_curves[dataset_id][strategy] = drawdown
            metric_rows.append(
                {
                    "dataset": dataset_id,
                    "exchange": dataset["exchange"],
                    "symbol": dataset["symbol"],
                    "timeframe": timeframe,
                    "strategy": strategy,
                    "strategy_params": _default_strategy_params(strategy),
                    "position_mode": "long_only_spot",
                    "fee_bps": config.fee_bps,
                    "slippage_bps": config.slippage_bps,
                    "spread_bps": config.spread_bps,
                    "execution_delay": config.execution_delay,
                    **result.metrics,
                    **_trade_stats(result.returns, result.position),
                    **_exposure_stats(result.position),
                    **buy_hold_metrics,
                    **_relative_to_buy_hold(result.metrics, buy_hold.metrics),
                    **_walk_forward_metrics(data, signals, config),
                }
            )

    metrics = _add_strategy_scores(pd.DataFrame(metric_rows)).sort_values(
        ["performance_score", "sharpe", "cagr"],
        ascending=False,
    )
    stability = _parameter_stability(data_by_dataset, metrics.head(20), config_by_dataset)
    dataset_stats = pd.DataFrame(dataset_rows).sort_values(["exchange", "symbol", "timeframe"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path = output_path.with_name("strategy_metrics.csv")
    dataset_stats_path = output_path.with_name("dataset_stats.csv")
    parameter_stability_path = output_path.with_name("parameter_stability.csv")
    metrics.to_csv(metrics_path, index=False)
    dataset_stats.to_csv(dataset_stats_path, index=False)
    stability.to_csv(parameter_stability_path, index=False)

    html_text = _render_dashboard(
        metrics=metrics,
        dataset_stats=dataset_stats,
        stability=stability,
        market_returns=market_returns,
        equity_curves=equity_curves,
        drawdown_curves=drawdown_curves,
    )
    output_path.write_text(html_text, encoding="utf-8")
    return DashboardResult(output_path, metrics_path, dataset_stats_path, parameter_stability_path)


def parse_dataset_id(path: Path) -> dict[str, str]:
    """Infer exchange, symbol, timeframe, and stable dataset id from a Parquet filename."""

    parts = path.stem.split("_")
    timeframe = parts[-1] if parts and parts[-1] in KNOWN_TIMEFRAMES else "unknown"
    known_exchanges = {"binance", "nobitex"}
    if parts and parts[0].lower() in known_exchanges and len(parts) >= 3:
        exchange = parts[0].lower()
        symbol = "_".join(parts[1:-1])
    else:
        exchange = "binance"
        symbol = "_".join(parts[:-1]) if len(parts) > 1 else path.stem
    return {
        "dataset": f"{exchange}_{symbol}_{timeframe}",
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
    }


def _add_strategy_scores(metrics: pd.DataFrame) -> pd.DataFrame:
    """Add an intuitive 0-100 score so tables and charts can show best runs in green."""

    scored = metrics.copy()
    if scored.empty:
        scored["performance_score"] = pd.Series(dtype=float)
        scored["performance_rank"] = pd.Series(dtype=int)
        return scored

    scored["max_drawdown_abs"] = scored["max_drawdown"].abs()
    score_parts: list[pd.Series] = []
    for metric in HIGHER_IS_BETTER_METRICS:
        if metric in scored:
            score_parts.append(_percentile_score(scored[metric], higher_is_better=True))
    for metric in LOWER_IS_BETTER_METRICS:
        if metric in scored:
            score_parts.append(_percentile_score(scored[metric], higher_is_better=False))

    if score_parts:
        scored["performance_score"] = pd.concat(score_parts, axis=1).mean(axis=1) * 100
    else:
        scored["performance_score"] = 50.0
    scored["performance_rank"] = scored["performance_score"].rank(ascending=False, method="min").astype(int)
    return scored.drop(columns=["max_drawdown_abs"])


def _percentile_score(values: pd.Series, higher_is_better: bool) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if clean.notna().sum() <= 1:
        return pd.Series(0.5, index=values.index)
    ranks = clean.rank(pct=True, ascending=higher_is_better)
    return ranks.fillna(0.5)


def _dataset_stats(
    path: Path,
    data: pd.DataFrame,
    returns: pd.Series,
    dataset: dict[str, str],
) -> dict[str, float | str | int]:
    timestamps = pd.to_datetime(data["timestamp"], utc=True)
    clean_returns = returns.dropna()
    var_5 = float(clean_returns.quantile(0.05)) if not clean_returns.empty else 0.0
    tail = clean_returns[clean_returns <= var_5]
    cvar_5 = float(tail.mean()) if not tail.empty else 0.0
    return {
        "dataset": dataset["dataset"],
        "exchange": dataset["exchange"],
        "symbol": dataset["symbol"],
        "timeframe": dataset["timeframe"],
        "path": str(path),
        "rows": len(data),
        "start": str(timestamps.min()),
        "end": str(timestamps.max()),
        "mean_return": float(clean_returns.mean()),
        "volatility": float(clean_returns.std()),
        "skewness": float(clean_returns.skew()),
        "kurtosis": float(clean_returns.kurt()),
        "min_return": float(clean_returns.min()),
        "max_return": float(clean_returns.max()),
        "var_5": var_5,
        "cvar_5": cvar_5,
    }


def _trade_stats(returns: pd.Series, position: pd.Series) -> dict[str, float]:
    trade_returns: list[float] = []
    in_trade = False
    cumulative = 1.0
    previous_position = 0.0
    for offset, current_position in enumerate(position.fillna(0.0)):
        current_position = float(current_position)
        row_return = float(returns.iloc[offset]) if offset < len(returns) else 0.0
        if not in_trade and current_position > 0:
            in_trade = True
            cumulative = 1.0
        if in_trade:
            cumulative *= 1 + row_return
        if in_trade and previous_position > 0 and current_position <= 0:
            trade_returns.append(cumulative - 1)
            in_trade = False
            cumulative = 1.0
        previous_position = current_position
    if in_trade:
        trade_returns.append(cumulative - 1)

    if not trade_returns:
        return {"trades_count": 0.0, "avg_trade": 0.0, "median_trade": 0.0}
    trade_series = pd.Series(trade_returns)
    return {
        "trades_count": float(len(trade_returns)),
        "avg_trade": float(trade_series.mean()),
        "median_trade": float(trade_series.median()),
    }


def _exposure_stats(position: pd.Series) -> dict[str, float]:
    clean = position.fillna(0.0)
    return {"exposure": float((clean > 0).mean()) if len(clean) else 0.0}


def _buy_hold_comparison_metrics(result) -> dict[str, float]:
    return {
        "buy_hold_total_return": result.metrics["total_return"],
        "buy_hold_cagr": result.metrics["cagr"],
        "buy_hold_sharpe": result.metrics["sharpe"],
        "buy_hold_max_drawdown": result.metrics["max_drawdown"],
    }


def _relative_to_buy_hold(metrics: dict[str, float], buy_hold_metrics: dict[str, float]) -> dict[str, float]:
    return {
        "excess_total_return_vs_buy_hold": metrics["total_return"] - buy_hold_metrics["total_return"],
        "excess_cagr_vs_buy_hold": metrics["cagr"] - buy_hold_metrics["cagr"],
        "excess_sharpe_vs_buy_hold": metrics["sharpe"] - buy_hold_metrics["sharpe"],
    }


def _walk_forward_metrics(data: pd.DataFrame, signals: pd.Series, config: BacktestConfig) -> dict[str, float]:
    timestamps = pd.to_datetime(data["timestamp"], utc=True)
    train_mask = (timestamps >= WALK_FORWARD_TRAIN_START) & (timestamps <= WALK_FORWARD_TRAIN_END)
    test_mask = (timestamps >= WALK_FORWARD_TEST_START) & (timestamps <= WALK_FORWARD_TEST_END)
    train_data = data.loc[train_mask].reset_index(drop=True)
    test_data = data.loc[test_mask].reset_index(drop=True)
    train_signals = signals.loc[train_mask].reset_index(drop=True)
    test_signals = signals.loc[test_mask].reset_index(drop=True)
    train = _segment_backtest(train_data, train_signals, config)
    test = _segment_backtest(test_data, test_signals, config)
    return {
        "train_total_return": train["total_return"],
        "train_cagr": train["cagr"],
        "train_sharpe": train["sharpe"],
        "train_max_drawdown": train["max_drawdown"],
        "train_trades_count": train["trades_count"],
        "train_exposure": train["exposure"],
        "test_total_return": test["total_return"],
        "test_cagr": test["cagr"],
        "test_sharpe": test["sharpe"],
        "test_max_drawdown": test["max_drawdown"],
        "test_trades_count": test["trades_count"],
        "test_exposure": test["exposure"],
        "test_minus_train_cagr": test["cagr"] - train["cagr"],
        "test_minus_train_sharpe": test["sharpe"] - train["sharpe"],
    }


def _segment_backtest(data: pd.DataFrame, signals: pd.Series, config: BacktestConfig) -> dict[str, float]:
    if len(data) < 3:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "trades_count": 0.0,
            "exposure": 0.0,
        }
    result = VectorizedBacktester(config).run(data, signals)
    return {
        "total_return": result.metrics["total_return"],
        "cagr": result.metrics["cagr"],
        "sharpe": result.metrics["sharpe"],
        "max_drawdown": result.metrics["max_drawdown"],
        **_trade_stats(result.returns, result.position),
        **_exposure_stats(result.position),
    }


def _default_strategy_params(strategy: str) -> str:
    defaults = {
        "ema_trend": EMATrendConfig(),
        "rsi_mean_reversion": RSIMeanReversionConfig(),
        "bollinger_mean_reversion": BollingerMeanReversionConfig(),
        "donchian_breakout": DonchianBreakoutConfig(),
        "atr_breakout": ATRBreakoutConfig(),
    }
    config = defaults.get(strategy)
    return _format_params(asdict(config)) if config else "default"


def _parameter_stability(
    data_by_dataset: dict[str, pd.DataFrame],
    top_metrics: pd.DataFrame,
    config_by_dataset: dict[str, BacktestConfig],
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for _, metric in top_metrics.iterrows():
        dataset = str(metric["dataset"])
        strategy = str(metric["strategy"])
        data = data_by_dataset.get(dataset)
        config = config_by_dataset.get(dataset)
        if data is None or config is None:
            continue
        backtester = VectorizedBacktester(config)
        for variant in _strategy_variants(strategy):
            result = backtester.run(data, variant.signal_builder(data))
            rows.append(
                {
                    "dataset": dataset,
                    "strategy": strategy,
                    "variant": variant.label,
                    "params": variant.params,
                    "total_return": result.metrics["total_return"],
                    "cagr": result.metrics["cagr"],
                    "sharpe": result.metrics["sharpe"],
                    "max_drawdown": result.metrics["max_drawdown"],
                    **_trade_stats(result.returns, result.position),
                    **_exposure_stats(result.position),
                }
            )
    return pd.DataFrame(rows)


def _strategy_variants(strategy: str) -> list[StrategyVariant]:
    if strategy == "ema_trend":
        configs = [EMATrendConfig(18, 90), EMATrendConfig(20, 100), EMATrendConfig(22, 110)]
        return [
            StrategyVariant(f"ema_{config.fast}_{config.slow}", _format_params(asdict(config)), lambda data, config=config: ema_trend(data, config))
            for config in configs
        ]
    if strategy == "rsi_mean_reversion":
        configs = [RSIMeanReversionConfig(12, 30, 50), RSIMeanReversionConfig(14, 30, 50), RSIMeanReversionConfig(16, 30, 50)]
        return [
            StrategyVariant(f"rsi_{config.window}", _format_params(asdict(config)), lambda data, config=config: rsi_mean_reversion(data, config))
            for config in configs
        ]
    if strategy == "bollinger_mean_reversion":
        configs = [
            BollingerMeanReversionConfig(18, -2.0, 0.0),
            BollingerMeanReversionConfig(20, -2.0, 0.0),
            BollingerMeanReversionConfig(22, -2.0, 0.0),
        ]
        return [
            StrategyVariant(f"bollinger_{config.window}", _format_params(asdict(config)), lambda data, config=config: bollinger_mean_reversion(data, config))
            for config in configs
        ]
    if strategy == "donchian_breakout":
        configs = [DonchianBreakoutConfig(50), DonchianBreakoutConfig(55), DonchianBreakoutConfig(60)]
        return [
            StrategyVariant(f"donchian_{config.window}", _format_params(asdict(config)), lambda data, config=config: donchian_breakout(data, config))
            for config in configs
        ]
    if strategy == "atr_breakout":
        configs = [
            ATRBreakoutConfig(18, 1.4),
            ATRBreakoutConfig(20, 1.5),
            ATRBreakoutConfig(22, 1.6),
        ]
        return [
            StrategyVariant(f"atr_{config.window}_{config.atr_multiple}", _format_params(asdict(config)), lambda data, config=config: atr_breakout(data, config))
            for config in configs
        ]
    return []


def _format_params(params: dict[str, float | int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in params.items())


def _stability_summary(stability: pd.DataFrame) -> pd.DataFrame:
    if stability.empty:
        return stability
    summary = stability.groupby(["dataset", "strategy"], as_index=False).agg(
        variants_count=("variant", "count"),
        cagr_min=("cagr", "min"),
        cagr_median=("cagr", "median"),
        cagr_max=("cagr", "max"),
        cagr_std=("cagr", "std"),
        sharpe_min=("sharpe", "min"),
        sharpe_median=("sharpe", "median"),
        sharpe_max=("sharpe", "max"),
        sharpe_std=("sharpe", "std"),
        trades_count_min=("trades_count", "min"),
        trades_count_median=("trades_count", "median"),
        trades_count_max=("trades_count", "max"),
    )
    summary["cagr_range"] = summary["cagr_max"] - summary["cagr_min"]
    summary["sharpe_range"] = summary["sharpe_max"] - summary["sharpe_min"]
    return summary.sort_values(["cagr_range", "sharpe_range"], ascending=False)


def _render_dashboard(
    metrics: pd.DataFrame,
    dataset_stats: pd.DataFrame,
    stability: pd.DataFrame,
    market_returns: dict[str, pd.Series],
    equity_curves: dict[str, dict[str, pd.Series]],
    drawdown_curves: dict[str, dict[str, pd.Series]],
) -> str:
    stability_summary = _stability_summary(stability)
    figure_divs: list[str] = []
    include_plotly = True
    for figure in _build_figures(metrics, dataset_stats, stability_summary, market_returns, equity_curves, drawdown_curves):
        figure_divs.append(
            pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs="cdn" if include_plotly else False,
                config={"displaylogo": False, "responsive": True},
            )
        )
        include_plotly = False

    dataset_table = dataset_stats.to_html(index=False, classes="table", float_format=lambda value: f"{value:.6f}")
    top_table = _strategy_metrics_table(metrics.head(20))
    full_metrics_table = _strategy_metrics_table(metrics)
    stability_table = _plain_table(stability_summary.head(50))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Global Quant Research Dashboard</title>
  <style>
    body {{ font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #172026; background: #f6f7f9; }}
    header {{ background: #101820; color: #fff; padding: 28px 40px; }}
    main {{ padding: 28px 40px 56px; }}
    h1, h2 {{ margin: 0 0 14px; }}
    section {{ background: #fff; border: 1px solid #e3e7eb; border-radius: 8px; padding: 22px; margin-bottom: 22px; box-shadow: 0 1px 2px rgba(16, 24, 32, 0.04); }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    .table th, .table td {{ border-bottom: 1px solid #e6e9ed; padding: 8px 10px; text-align: right; }}
    .table th:first-child, .table td:first-child {{ text-align: left; }}
    .table th {{ background: #f0f3f6; position: sticky; top: 0; }}
    .metric-table tbody tr {{ background: var(--score-bg); }}
    .metric-table tbody tr:hover {{ filter: saturate(1.08); }}
    .metric-table .score-cell {{ font-weight: 700; border-left: 4px solid var(--score-accent); }}
    .table-wrap {{ overflow: auto; max-height: 560px; border: 1px solid #e6e9ed; border-radius: 6px; }}
    .note {{ color: #52616f; max-width: 1040px; line-height: 1.6; }}
    .assumption {{ display: inline-block; margin: 0 12px 10px 0; padding: 6px 8px; border: 1px solid #d8dee5; border-radius: 6px; background: #f8fafb; font-size: 13px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} main, header {{ padding-left: 18px; padding-right: 18px; }} }}
  </style>
</head>
<body>
<header>
  <h1>Global Quant Research Dashboard</h1>
  <p class="note">Unified cross-exchange and cross-timeframe research view generated from every local Parquet dataset.</p>
</header>
<main>
  <section>
    <h2>Execution Assumptions</h2>
    <span class="assumption">Position Mode: Long Only Spot</span>
    <span class="assumption">Default Fee: 10 bps per turnover</span>
    <span class="assumption">Default Slippage: 2 bps per turnover</span>
    <span class="assumption">Spread: 0 bps unless configured</span>
    <span class="assumption">Execution Delay: 1 bar</span>
    <p class="note">Short exposure is not allowed in this backtester. Positions are clipped to 0..1, which matches spot-only assumptions for Nobitex. Fee, slippage, spread, and delay are also exported per strategy row.</p>
  </section>
  <section>
    <h2>Dataset Coverage And Return Statistics</h2>
    <p class="note">Includes mean return, volatility, skewness, kurtosis, 5% VaR, and 5% CVaR for each dataset.</p>
    <div class="table-wrap">{dataset_table}</div>
  </section>
  <section>
    <h2>Top Strategy Runs</h2>
    <p class="note">Rows are colored by composite score. Trades Count, Avg Trade, Median Trade, Exposure, Buy & Hold comparison, and 2020-2024 / 2025-2026 walk-forward metrics are included.</p>
    <div class="table-wrap">{top_table}</div>
  </section>
  <section>
    <h2>Parameter Stability Analysis</h2>
    <p class="note">Nearby parameter variants are tested for the top 20 strategy runs. Wide CAGR or Sharpe ranges indicate higher curve-fit risk.</p>
    <div class="table-wrap">{stability_table}</div>
  </section>
  <section>
    <h2>Charts</h2>
    {''.join(f'<div>{div}</div>' for div in figure_divs)}
  </section>
  <section>
    <h2>Full Strategy Metrics</h2>
    <div class="table-wrap">{full_metrics_table}</div>
  </section>
</main>
</body>
</html>"""


def _build_figures(
    metrics: pd.DataFrame,
    dataset_stats: pd.DataFrame,
    stability_summary: pd.DataFrame,
    market_returns: dict[str, pd.Series],
    equity_curves: dict[str, dict[str, pd.Series]],
    drawdown_curves: dict[str, dict[str, pd.Series]],
) -> list[go.Figure]:
    figures = [
        _strategy_score_leaderboard(metrics),
        _strategy_score_heatmap(metrics),
        _strategy_bar(metrics, "trades_count", "Trades Count By Dataset"),
        _strategy_bar(metrics, "avg_trade", "Average Trade By Dataset"),
        _strategy_bar(metrics, "exposure", "Exposure By Dataset"),
        _strategy_bar(metrics, "excess_cagr_vs_buy_hold", "Excess CAGR Versus Buy & Hold"),
        _walk_forward_scatter(metrics),
        _strategy_bar(metrics, "performance_score", "Composite Performance Score By Dataset"),
        _risk_return_scatter(metrics),
        _metric_heatmap(metrics, "sharpe", "Sharpe Heatmap"),
        _metric_heatmap(metrics, "max_drawdown", "Max Drawdown Heatmap"),
        _metric_heatmap(metrics, "trades_count", "Trades Count Heatmap"),
        _metric_heatmap(metrics, "exposure", "Exposure Heatmap"),
        _metric_heatmap(metrics, "excess_cagr_vs_buy_hold", "Excess CAGR Vs Buy & Hold Heatmap"),
        _dataset_distribution_stats(dataset_stats),
    ]
    if not stability_summary.empty:
        figures.append(_parameter_stability_figure(stability_summary))
    for dataset_id, returns in market_returns.items():
        figures.append(_distribution_figure(dataset_id, returns))
    for dataset_id, curves in equity_curves.items():
        figures.append(_curve_figure(dataset_id, curves, "Equity Curves", "Normalized Equity"))
    for dataset_id, curves in drawdown_curves.items():
        figures.append(_curve_figure(dataset_id, curves, "Drawdown Curves", "Drawdown"))
    return figures


def _strategy_metrics_table(metrics: pd.DataFrame) -> str:
    columns = [
        "performance_rank",
        "performance_score",
        "dataset",
        "exchange",
        "symbol",
        "timeframe",
        "strategy",
        "strategy_params",
        "position_mode",
        "trades_count",
        "avg_trade",
        "median_trade",
        "exposure",
        "total_return",
        "cagr",
        "buy_hold_cagr",
        "excess_cagr_vs_buy_hold",
        "test_cagr",
        "test_sharpe",
        "test_trades_count",
        "train_cagr",
        "train_sharpe",
        "train_trades_count",
        "sharpe",
        "sortino",
        "calmar",
        "profit_factor",
        "win_rate",
        "max_drawdown",
        "fee_bps",
        "slippage_bps",
        "spread_bps",
        "execution_delay",
    ]
    available_columns = [column for column in columns if column in metrics.columns]
    header = "".join(f"<th>{html.escape(_column_label(column))}</th>" for column in available_columns)
    rows = []
    for _, row in metrics[available_columns].iterrows():
        score = float(row.get("performance_score", 50.0))
        row_style = f' style="--score-bg: {_score_background(score)}; --score-accent: {_score_accent(score)};"'
        cells = []
        for column in available_columns:
            class_name = ' class="score-cell"' if column == "performance_score" else ""
            cells.append(f"<td{class_name}>{_format_cell(row[column], column)}</td>")
        rows.append(f"<tr{row_style}>{''.join(cells)}</tr>")
    return f'<table class="table metric-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _plain_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<table class="table"><tbody><tr><td>No stability rows available.</td></tr></tbody></table>'
    return frame.to_html(index=False, classes="table", escape=True, float_format=lambda value: f"{value:.6f}")


def _column_label(column: str) -> str:
    return column.replace("_", " ").title()


def _format_cell(value: object, column: str) -> str:
    if pd.isna(value):
        return ""
    if column in {"performance_rank", "trades_count", "train_trades_count", "test_trades_count", "execution_delay"}:
        return str(int(value))
    if isinstance(value, float | np.floating):
        return f"{float(value):.4f}"
    return html.escape(str(value))


def _score_background(score: float) -> str:
    normalized = min(100.0, max(0.0, score)) / 100.0
    hue = normalized * 128
    return f"hsl({hue:.1f} 70% 91%)"


def _score_accent(score: float) -> str:
    normalized = min(100.0, max(0.0, score)) / 100.0
    hue = normalized * 128
    return f"hsl({hue:.1f} 72% 36%)"


def _strategy_score_leaderboard(metrics: pd.DataFrame) -> go.Figure:
    top = metrics.sort_values("performance_score", ascending=False).head(25).copy()
    top["run"] = top["dataset"] + " / " + top["strategy"]
    figure = go.Figure(
        data=go.Bar(
            x=top["performance_score"],
            y=top["run"],
            orientation="h",
            marker={
                "color": top["performance_score"],
                "colorscale": "RdYlGn",
                "cmin": 0,
                "cmax": 100,
                "colorbar": {"title": "Score"},
            },
        )
    )
    figure.update_layout(
        title="Top Strategy Runs By Composite Performance Score",
        xaxis_title="Performance Score",
        yaxis_title="Strategy Run",
        yaxis={"autorange": "reversed"},
    )
    return figure


def _strategy_score_heatmap(metrics: pd.DataFrame) -> go.Figure:
    return _metric_heatmap(metrics, "performance_score", "Composite Performance Score Heatmap")


def _strategy_bar(metrics: pd.DataFrame, metric: str, title: str) -> go.Figure:
    figure = go.Figure()
    for strategy, group in metrics.groupby("strategy"):
        figure.add_bar(name=str(strategy), x=group["dataset"], y=group[metric])
    figure.update_layout(title=title, barmode="group", xaxis_title="Dataset", yaxis_title=metric)
    return figure


def _walk_forward_scatter(metrics: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for strategy, group in metrics.groupby("strategy"):
        figure.add_scatter(
            name=str(strategy),
            x=group["train_cagr"],
            y=group["test_cagr"],
            mode="markers",
            text=group["dataset"],
            marker={"size": 11, "color": group["trades_count"], "colorscale": "Viridis", "showscale": True},
        )
    figure.add_shape(type="line", x0=-1, y0=-1, x1=1, y1=1, line={"dash": "dash", "color": "#7a8691"})
    figure.update_layout(title="Walk Forward CAGR: Train 2020-2024 Vs Test 2025-2026", xaxis_title="Train CAGR", yaxis_title="Test CAGR")
    return figure


def _risk_return_scatter(metrics: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for strategy, group in metrics.groupby("strategy"):
        figure.add_scatter(
            name=str(strategy),
            x=group["max_drawdown"].abs(),
            y=group["cagr"],
            mode="markers",
            text=group["dataset"],
            marker={
                "size": 11,
                "color": group["performance_score"],
                "colorscale": "RdYlGn",
                "cmin": 0,
                "cmax": 100,
                "showscale": True,
            },
        )
    figure.update_layout(title="Risk / Return Map Colored By Performance Score", xaxis_title="Absolute Max Drawdown", yaxis_title="CAGR")
    return figure


def _parameter_stability_figure(stability_summary: pd.DataFrame) -> go.Figure:
    top = stability_summary.head(25).copy()
    top["run"] = top["dataset"] + " / " + top["strategy"]
    figure = go.Figure(
        data=go.Bar(
            x=top["cagr_range"],
            y=top["run"],
            orientation="h",
            marker={"color": top["sharpe_range"], "colorscale": "Reds", "showscale": True},
        )
    )
    figure.update_layout(
        title="Parameter Stability Risk: Wider Ranges Mean More Fragile Results",
        xaxis_title="CAGR Range Across Nearby Parameter Variants",
        yaxis_title="Strategy Run",
        yaxis={"autorange": "reversed"},
    )
    return figure


def _metric_heatmap(metrics: pd.DataFrame, metric: str, title: str) -> go.Figure:
    pivot = metrics.pivot_table(index="strategy", columns="dataset", values=metric, aggfunc="mean")
    figure = go.Figure(data=go.Heatmap(z=pivot.to_numpy(), x=list(pivot.columns), y=list(pivot.index), colorscale="RdYlGn"))
    figure.update_layout(title=title, xaxis_title="Dataset", yaxis_title="Strategy")
    return figure


def _dataset_distribution_stats(dataset_stats: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    figure.add_bar(name="Skewness", x=dataset_stats["dataset"], y=dataset_stats["skewness"])
    figure.add_bar(name="Kurtosis", x=dataset_stats["dataset"], y=dataset_stats["kurtosis"])
    figure.update_layout(title="Dataset Distribution Shape", barmode="group", xaxis_title="Dataset", yaxis_title="Value")
    return figure


def _distribution_figure(dataset_id: str, returns: pd.Series) -> go.Figure:
    clean = returns.dropna()
    sampled = _sample_series(clean, 10_000)
    mean = float(clean.mean())
    std = float(clean.std())
    figure = go.Figure()
    figure.add_histogram(name="Returns", x=sampled, histnorm="probability density", nbinsx=80, opacity=0.72)
    if std > 0:
        x_values = np.linspace(float(clean.quantile(0.001)), float(clean.quantile(0.999)), 240)
        pdf = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_values - mean) / std) ** 2)
        figure.add_scatter(name="Normal fit", x=x_values, y=pdf, mode="lines")
    figure.update_layout(title=f"Return Distribution With Normal Curve: {html.escape(dataset_id)}", xaxis_title="Return", yaxis_title="Density")
    return figure


def _curve_figure(dataset_id: str, curves: dict[str, pd.Series], title: str, yaxis_title: str) -> go.Figure:
    figure = go.Figure()
    for strategy, curve in curves.items():
        sampled = _sample_series(curve, 5_000)
        figure.add_scatter(name=strategy, x=list(sampled.index), y=sampled, mode="lines")
    figure.update_layout(title=f"{title}: {html.escape(dataset_id)}", xaxis_title="Observation", yaxis_title=yaxis_title)
    return figure


def _sample_series(series: pd.Series, max_points: int) -> pd.Series:
    if len(series) <= max_points:
        return series.reset_index(drop=True)
    indices = np.linspace(0, len(series) - 1, max_points).astype(int)
    return series.iloc[indices]


def _periods_per_year(timeframe: str) -> int:
    mapping = {
        "1m": 525_600,
        "5m": 105_120,
        "15m": 35_040,
        "30m": 17_520,
        "1h": 8_760,
        "2h": 4_380,
        "3h": 2_920,
        "4h": 2_190,
        "1d": 365,
    }
    return mapping.get(timeframe, 365)
