"""Unified multi-dataset research dashboard generation."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from src.backtesting import BacktestConfig, VectorizedBacktester
from src.strategies import build_strategy_signals


@dataclass(frozen=True)
class DashboardResult:
    """Generated dashboard artifact paths."""

    html_path: Path
    metrics_path: Path
    dataset_stats_path: Path


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

    for path in dataset_paths:
        data = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        dataset = parse_dataset_id(path)
        dataset_id = dataset["dataset"]
        timeframe = dataset["timeframe"]
        returns = data["close"].pct_change().dropna().rename(dataset_id)
        market_returns[dataset_id] = returns.reset_index(drop=True)
        dataset_rows.append(_dataset_stats(path, data, returns, dataset))

        backtester = VectorizedBacktester(BacktestConfig(periods_per_year=_periods_per_year(timeframe)))
        equity_curves[dataset_id] = {}
        drawdown_curves[dataset_id] = {}
        for strategy in strategies:
            result = backtester.run(data, build_strategy_signals(data, strategy))
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
                    **result.metrics,
                }
            )

    metrics = pd.DataFrame(metric_rows).sort_values(["sharpe", "cagr"], ascending=False)
    dataset_stats = pd.DataFrame(dataset_rows).sort_values(["exchange", "symbol", "timeframe"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path = output_path.with_name("strategy_metrics.csv")
    dataset_stats_path = output_path.with_name("dataset_stats.csv")
    metrics.to_csv(metrics_path, index=False)
    dataset_stats.to_csv(dataset_stats_path, index=False)

    html_text = _render_dashboard(
        metrics=metrics,
        dataset_stats=dataset_stats,
        market_returns=market_returns,
        equity_curves=equity_curves,
        drawdown_curves=drawdown_curves,
    )
    output_path.write_text(html_text, encoding="utf-8")
    return DashboardResult(output_path, metrics_path, dataset_stats_path)


def parse_dataset_id(path: Path) -> dict[str, str]:
    """Infer exchange, symbol, timeframe, and stable dataset id from a Parquet filename."""

    parts = path.stem.split("_")
    known_timeframes = {"1m", "5m", "1h", "1d"}
    timeframe = parts[-1] if parts and parts[-1] in known_timeframes else "unknown"
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


def _render_dashboard(
    metrics: pd.DataFrame,
    dataset_stats: pd.DataFrame,
    market_returns: dict[str, pd.Series],
    equity_curves: dict[str, dict[str, pd.Series]],
    drawdown_curves: dict[str, dict[str, pd.Series]],
) -> str:
    figure_divs: list[str] = []
    include_plotly = True
    for figure in _build_figures(metrics, dataset_stats, market_returns, equity_curves, drawdown_curves):
        figure_divs.append(
            pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs="cdn" if include_plotly else False,
                config={"displaylogo": False, "responsive": True},
            )
        )
        include_plotly = False

    top_rows = metrics.head(20)
    dataset_table = dataset_stats.to_html(index=False, classes="table", float_format=lambda value: f"{value:.6f}")
    top_table = top_rows.to_html(index=False, classes="table", float_format=lambda value: f"{value:.6f}")
    full_metrics_table = metrics.to_html(index=False, classes="table", float_format=lambda value: f"{value:.6f}")

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
    .table-wrap {{ overflow: auto; max-height: 520px; border: 1px solid #e6e9ed; border-radius: 6px; }}
    .note {{ color: #52616f; max-width: 980px; line-height: 1.6; }}
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
    <h2>Dataset Coverage And Return Statistics</h2>
    <p class="note">Includes mean return, volatility, skewness, kurtosis, 5% VaR, and 5% CVaR for each dataset.</p>
    <div class="table-wrap">{dataset_table}</div>
  </section>
  <section>
    <h2>Top Strategy Runs</h2>
    <div class="table-wrap">{top_table}</div>
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
    market_returns: dict[str, pd.Series],
    equity_curves: dict[str, dict[str, pd.Series]],
    drawdown_curves: dict[str, dict[str, pd.Series]],
) -> list[go.Figure]:
    figures = [
        _strategy_bar(metrics, "sharpe", "Strategy Sharpe By Dataset"),
        _strategy_bar(metrics, "total_return", "Strategy Total Return By Dataset"),
        _risk_return_scatter(metrics),
        _metric_heatmap(metrics, "sharpe", "Sharpe Heatmap"),
        _metric_heatmap(metrics, "max_drawdown", "Max Drawdown Heatmap"),
        _dataset_distribution_stats(dataset_stats),
    ]
    for dataset_id, returns in market_returns.items():
        figures.append(_distribution_figure(dataset_id, returns))
    for dataset_id, curves in equity_curves.items():
        figures.append(_curve_figure(dataset_id, curves, "Equity Curves", "Normalized Equity"))
    for dataset_id, curves in drawdown_curves.items():
        figures.append(_curve_figure(dataset_id, curves, "Drawdown Curves", "Drawdown"))
    return figures


def _strategy_bar(metrics: pd.DataFrame, metric: str, title: str) -> go.Figure:
    figure = go.Figure()
    for strategy, group in metrics.groupby("strategy"):
        figure.add_bar(name=str(strategy), x=group["dataset"], y=group[metric])
    figure.update_layout(title=title, barmode="group", xaxis_title="Dataset", yaxis_title=metric)
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
            marker={"size": 10, "color": group["sharpe"], "colorscale": "Viridis", "showscale": True},
        )
    figure.update_layout(title="Risk / Return Map", xaxis_title="Absolute Max Drawdown", yaxis_title="CAGR")
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
    mapping = {"1m": 525_600, "5m": 105_120, "1h": 8_760, "1d": 365}
    return mapping.get(timeframe, 365)
