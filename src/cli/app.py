"""Typer CLI for the Bitcoin Quantitative Research Platform."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import typer
from rich.console import Console

from src.analysis import combine_strategy_returns, run_monte_carlo
from src.backtesting import BacktestConfig, BacktestResult, VectorizedBacktester
from src.data.downloader import DataIngestionPipeline, DownloadRequest
from src.data.nobitex import NobitexDataIngestionPipeline, NobitexDownloadRequest
from src.data.storage import ParquetDataStore
from src.factors import FactorResearcher
from src.factors.research import FactorResearchResult
from src.features import FeatureBuilder
from src.ml import TimeSeriesMLResearcher, future_return_target
from src.strategies import build_strategy_signals
from src.validation import DataQualityReport, DataValidator
from src.visualization import save_drawdown_chart, save_equity_curve

app = typer.Typer(help="Bitcoin quantitative research pipeline")
console = Console()
BASE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
STRATEGIES = [
    "ema_trend",
    "rsi_mean_reversion",
    "bollinger_mean_reversion",
    "donchian_breakout",
    "atr_breakout",
]


@app.command()
def demo(rows: int = 1500) -> None:
    """Generate an offline synthetic sample and clearly marked demo reports."""

    root = Path.cwd()
    data = sample_ohlcv(rows)
    processed_path = ParquetDataStore(root / "data/processed").write(data, "BTCUSDT", "1h")
    run_research_pipeline(
        data=data,
        symbol="BTCUSDT",
        timeframe="1h",
        source_name="Synthetic offline sample",
        source_note="Demo-only synthetic data. Do not interpret these values as Bitcoin findings.",
        root=root,
    )
    console.print(f"[green]Demo complete[/green]: {processed_path}")
    console.print("Reports written under reports/ and charts under outputs/figures/.")


@app.command()
def research(
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    start: str = "2020-01-01",
    refresh: bool = False,
    path: Path | None = None,
) -> None:
    """Run the full research pipeline on real Binance Spot data."""

    root = Path.cwd()
    store = ParquetDataStore(root / "data/processed")
    dataset_path = path or store.path_for(symbol, timeframe)
    if refresh and dataset_path.exists():
        dataset_path.unlink()
    if refresh or not dataset_path.exists():
        start_date = date.fromisoformat(start)
        _print_download_plan(symbol, timeframe, start, dataset_path)
        request = DownloadRequest(symbol=symbol, timeframe=timeframe, start=start_date)
        dataset_path = DataIngestionPipeline(store).run(request)
    data = pd.read_parquet(dataset_path)
    _print_dataset_coverage(dataset_path, data)
    run_research_pipeline(
        data=data,
        symbol=symbol,
        timeframe=timeframe,
        source_name="Binance Spot real market data",
        source_note=f"Source file: `{dataset_path}`. Start requested: `{start}`. Generated from real OHLCV candles.",
        root=root,
    )
    console.print(f"[green]Research complete[/green]: {dataset_path}")
    console.print("Polished real-data reports written under reports/ and outputs/figures/.")


@app.command()
def download(
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    start: str = "2020-01-01",
    output: Path = Path("data/processed"),
    refresh: bool = False,
) -> None:
    """Download one Binance Spot timeframe to Parquet and print coverage."""

    start_date = date.fromisoformat(start)
    store = ParquetDataStore(output)
    path = store.path_for(symbol, timeframe)
    if refresh and path.exists():
        path.unlink()
    _print_download_plan(symbol, timeframe, start, path)
    request = DownloadRequest(symbol, timeframe, start_date)
    path = DataIngestionPipeline(store).run(request)
    data = pd.read_parquet(path)
    _print_dataset_coverage(path, data)


@app.command("download-all")
def download_all(
    symbol: str = "BTCUSDT",
    timeframes: str = "1m,5m,1h,1d",
    start: str = "2020-01-01",
    output: Path = Path("data/processed"),
    refresh: bool = False,
) -> None:
    """Download all requested Binance timeframes for one symbol."""

    download_exchange_all("binance", symbol, timeframes, start, output, refresh)


@app.command("download-exchange")
def download_exchange(
    exchange: str = "binance",
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    start: str = "2020-01-01",
    output: Path = Path("data/processed"),
    refresh: bool = False,
) -> None:
    """Download one timeframe from a supported exchange and print coverage."""

    exchange_key = exchange.lower()
    start_date = date.fromisoformat(start)
    store = ParquetDataStore(output)
    path = _exchange_dataset_path(output, exchange_key, symbol, timeframe)
    if refresh and path.exists():
        path.unlink()
    _print_download_plan(f"{exchange_key}:{symbol}", timeframe, start, path)
    if exchange_key == "binance":
        binance_request = DownloadRequest(symbol, timeframe, start_date)
        downloaded_path = DataIngestionPipeline(store).run(binance_request)
        if downloaded_path != path:
            downloaded_path.replace(path)
    elif exchange_key == "nobitex":
        nobitex_request = NobitexDownloadRequest(symbol, timeframe, start_date)
        path = NobitexDataIngestionPipeline(store).run(nobitex_request)
        expected_path = _exchange_dataset_path(output, exchange_key, symbol, timeframe)
        if path != expected_path:
            path.replace(expected_path)
            path = expected_path
    else:
        raise typer.BadParameter(f"Unsupported exchange: {exchange}")
    data = pd.read_parquet(path)
    _print_dataset_coverage(path, data)


@app.command("download-exchange-all")
def download_exchange_all(
    exchange: str = "binance",
    symbol: str = "BTCUSDT",
    timeframes: str = "1m,5m,1h,1d",
    start: str = "2020-01-01",
    output: Path = Path("data/processed"),
    refresh: bool = False,
) -> None:
    """Download all requested timeframes from one exchange for one symbol."""

    requested_timeframes = [item.strip() for item in timeframes.split(",") if item.strip()]
    for timeframe in requested_timeframes:
        console.rule(f"{exchange.lower()} {symbol} {timeframe}")
        download_exchange(exchange, symbol, timeframe, start, output, refresh)


@app.command("research-exchange")
def research_exchange(
    exchange: str = "binance",
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    start: str = "2020-01-01",
    refresh: bool = False,
) -> None:
    """Run the polished research pipeline for one exchange dataset."""

    root = Path.cwd()
    path = _exchange_dataset_path(root / "data/processed", exchange.lower(), symbol, timeframe)
    if refresh or not path.exists():
        download_exchange(exchange, symbol, timeframe, start, root / "data/processed", refresh)
    data = pd.read_parquet(path)
    _print_dataset_coverage(path, data)
    run_research_pipeline(
        data=data,
        symbol=f"{exchange.lower()}:{symbol}",
        timeframe=timeframe,
        source_name=f"{exchange.title()} real market data",
        source_note=f"Source file: `{path}`. Start requested: `{start}`.",
        root=root,
    )
    console.print(f"[green]Research complete[/green]: {path}")


@app.command("data-status")
def data_status(
    symbol: str | None = None,
    exchange: str | None = None,
    data_dir: Path = Path("data/processed"),
) -> None:
    """Show local Parquet coverage for downloaded exchange/timeframe datasets."""

    pattern = "*.parquet"
    if exchange and symbol:
        pattern = f"{exchange.lower()}_{symbol}_*.parquet"
    elif symbol:
        pattern = f"*{symbol}_*.parquet"
    elif exchange:
        pattern = f"{exchange.lower()}_*.parquet"
    paths = sorted(data_dir.glob(pattern))
    if not paths:
        console.print(f"[yellow]No local datasets found[/yellow] in {data_dir} for pattern {pattern}")
        raise typer.Exit(code=0)
    for path in paths:
        data = pd.read_parquet(path, columns=["timestamp"])
        _print_dataset_coverage(path, data)


@app.command("compare-datasets")
def compare_datasets(
    paths: list[Path],
    output: Path = Path("reports/cross_exchange/dataset_comparison.md"),
) -> None:
    """Compare coverage and return correlations across exchange/timeframe Parquet files."""

    rows: list[dict[str, str | int]] = []
    returns: dict[str, pd.Series] = {}
    for path in paths:
        data = pd.read_parquet(path)
        timestamps = pd.to_datetime(data["timestamp"], utc=True)
        rows.append({
            "dataset": path.stem,
            "rows": len(data),
            "start": str(timestamps.min()),
            "end": str(timestamps.max()),
        })
        series = data.set_index(timestamps)["close"].pct_change().rename(path.stem)
        returns[path.stem] = series
    coverage = pd.DataFrame(rows)
    correlation = pd.DataFrame(returns).corr().round(4)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cross-Exchange / Timeframe Dataset Comparison",
        "",
        "## Coverage",
        "",
        coverage.to_markdown(index=False),
        "",
        "## Close Return Correlation",
        "",
        correlation.to_markdown(),
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Comparison report[/green] {output}")


@app.command()
def validate(path: Path, timeframe: str = "1h") -> None:
    """Validate a Parquet OHLCV dataset and write a Markdown report."""

    data = pd.read_parquet(path)
    report = DataValidator(timeframe).validate(data)
    report_path = Path("reports/data_quality") / f"{path.stem}.md"
    _write_data_quality_report(report, report_path, "User supplied Parquet dataset", f"Source file: `{path}`")
    console.print(f"[green]Report[/green] {report_path}")


@app.command()
def factors(path: Path, horizon: int = 24) -> None:
    """Run feature generation and factor research for a dataset."""

    data = pd.read_parquet(path)
    enriched = FeatureBuilder().build(data)
    feature_columns = [column for column in enriched.columns if column not in BASE_COLUMNS]
    researcher = FactorResearcher([horizon])
    report_path = Path("reports/factor_research") / f"{path.stem}.md"
    _write_factor_report(
        researcher.evaluate(enriched, feature_columns),
        report_path,
        "User supplied Parquet dataset",
        f"Source file: `{path}`",
    )
    console.print(f"[green]Report[/green] {report_path}")


@app.command()
def backtest(path: Path, strategy: str = "ema_trend") -> None:
    """Backtest one named strategy."""

    data = pd.read_parquet(path)
    backtester = VectorizedBacktester(BacktestConfig(periods_per_year=_periods_per_year("1h")))
    result = backtester.run(data, build_strategy_signals(data, strategy))
    equity_path = Path("outputs/figures") / f"{strategy}_equity.png"
    drawdown_path = Path("outputs/figures") / f"{strategy}_drawdown.png"
    save_equity_curve(result.equity, equity_path)
    save_drawdown_chart(result.equity, drawdown_path)
    report_path = Path("reports/backtests") / f"{strategy}.md"
    _write_strategy_report(result, report_path, strategy, "User supplied Parquet dataset", equity_path, drawdown_path)
    console.print(f"[green]Report[/green] {report_path}")


def _artifact_prefix(symbol: str, timeframe: str) -> str:
    safe_symbol = symbol.lower().replace(":", "_").replace("/", "_")
    return f"{safe_symbol}_{timeframe}"


def _exchange_dataset_path(data_dir: Path, exchange: str, symbol: str, timeframe: str) -> Path:
    return data_dir / f"{exchange}_{symbol}_{timeframe}.parquet"


def _print_download_plan(symbol: str, timeframe: str, start: str, path: Path) -> None:
    console.print(
        f"[cyan]Downloading[/cyan] symbol={symbol} timeframe={timeframe} "
        f"requested_start={start} output={path}"
    )


def _print_dataset_coverage(path: Path, data: pd.DataFrame) -> None:
    timestamps = pd.to_datetime(data["timestamp"], utc=True)
    console.print(
        f"[green]Dataset coverage[/green] path={path} rows={len(data):,} "
        f"start={timestamps.min()} end={timestamps.max()}"
    )


def run_research_pipeline(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
    source_name: str,
    source_note: str,
    root: Path,
) -> None:
    """Generate polished research artifacts for one OHLCV dataset."""

    data = data.sort_values("timestamp").reset_index(drop=True)
    metadata = _dataset_metadata(data, symbol, timeframe, source_name, source_note)
    artifact_prefix = _artifact_prefix(symbol, timeframe)
    validator = DataValidator(timeframe)
    _write_data_quality_report(
        validator.validate(data),
        root / f"reports/data_quality/{artifact_prefix}.md",
        source_name,
        source_note,
    )

    enriched = FeatureBuilder().build(data)
    research_path = root / f"data/research/{artifact_prefix}_features.parquet"
    research_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(research_path, index=False)

    feature_columns = [column for column in enriched.columns if column not in BASE_COLUMNS]
    researcher = FactorResearcher([1, 6, 24])
    factor_result = researcher.evaluate(enriched, feature_columns[:50])
    _write_factor_report(
        factor_result,
        root / f"reports/factor_research/{artifact_prefix}.md",
        source_name,
        source_note,
    )

    backtester = VectorizedBacktester(BacktestConfig(periods_per_year=_periods_per_year(timeframe)))
    strategy_returns: dict[str, pd.Series] = {}
    strategy_rows: list[dict[str, float | str]] = []
    for strategy in STRATEGIES:
        result = backtester.run(data, build_strategy_signals(data, strategy))
        strategy_returns[strategy] = result.returns
        strategy_rows.append({"strategy": strategy, **result.metrics})
        equity_path = root / f"outputs/figures/{artifact_prefix}_{strategy}_equity.png"
        drawdown_path = root / f"outputs/figures/{artifact_prefix}_{strategy}_drawdown.png"
        save_equity_curve(result.equity, equity_path, f"{strategy} Equity")
        save_drawdown_chart(result.equity, drawdown_path, f"{strategy} Drawdown")
        _write_strategy_report(
            result,
            root / f"reports/backtests/{artifact_prefix}_{strategy}.md",
            strategy,
            source_name,
            equity_path,
            drawdown_path,
        )

    comparison = pd.DataFrame(strategy_rows).sort_values("sharpe", ascending=False)
    _write_strategy_comparison(
        comparison,
        root / f"reports/backtests/{artifact_prefix}_strategy_comparison.md",
        metadata,
    )

    returns_frame = pd.DataFrame(strategy_returns)
    portfolio_returns = combine_strategy_returns(returns_frame)
    portfolio_equity = 10_000 * (1 + portfolio_returns).cumprod()
    portfolio_equity_path = root / f"outputs/figures/{artifact_prefix}_portfolio_equity.png"
    save_equity_curve(portfolio_equity, portfolio_equity_path, "Equal Weight Portfolio")
    _write_portfolio_report(
        portfolio_returns,
        returns_frame,
        portfolio_equity_path,
        root / f"reports/portfolio/{artifact_prefix}_equal_weight.md",
        metadata,
    )

    mc = run_monte_carlo(strategy_returns["ema_trend"], simulations=1000)
    _write_monte_carlo_report(
        mc.confidence_intervals,
        root / f"reports/monte_carlo/{artifact_prefix}_ema_trend.md",
        metadata,
    )

    ml_result = TimeSeriesMLResearcher(test_fraction=0.25).train_random_forest(
        enriched,
        feature_columns[:20],
        future_return_target(enriched, 24),
    )
    _write_ml_report(ml_result.metrics, root / f"reports/ml/{artifact_prefix}_random_forest_returns.md", metadata)


def sample_ohlcv(rows: int = 1500) -> pd.DataFrame:
    """Create deterministic synthetic BTC-like OHLCV for tests and offline demo reports."""

    rng = np.random.default_rng(42)
    timestamps = pd.date_range("2020-01-01", periods=rows, freq="1h", tz="UTC")
    returns = rng.normal(0.0002, 0.02, size=rows)
    close = 10_000 * pd.Series(1 + returns).cumprod().to_numpy()
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, rows))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, rows))
    volume = rng.lognormal(mean=8, sigma=0.4, size=rows)
    return pd.DataFrame({"timestamp": timestamps, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _dataset_metadata(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
    source_name: str,
    source_note: str,
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_name": source_name,
        "source_note": source_note,
        "rows": str(len(data)),
        "start": str(pd.to_datetime(data["timestamp"]).min()),
        "end": str(pd.to_datetime(data["timestamp"]).max()),
    }


def _metadata_lines(metadata: dict[str, str]) -> list[str]:
    return [
        "## Dataset",
        "",
        f"- Symbol: `{metadata['symbol']}`",
        f"- Timeframe: `{metadata['timeframe']}`",
        f"- Source: **{metadata['source_name']}**",
        f"- Rows: `{metadata['rows']}`",
        f"- Start: `{metadata['start']}`",
        f"- End: `{metadata['end']}`",
        f"- Note: {metadata['source_note']}",
        "",
    ]


def _write_data_quality_report(
    report: DataQualityReport,
    output_path: Path,
    source_name: str,
    source_note: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data Quality Report",
        "",
        "## Dataset",
        "",
        f"- Source: **{source_name}**",
        f"- Note: {source_note}",
        f"- Rows: `{report.rows}`",
        f"- Start: `{report.start}`",
        f"- End: `{report.end}`",
        f"- Passed: `{report.passed}`",
        "",
        "## Checks",
        "",
        "| Check | Severity | Count | Details |",
        "|---|---:|---:|---|",
    ]
    for issue in report.issues:
        lines.append(f"| {issue.name} | {issue.severity} | {issue.count} | {issue.details} |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_factor_report(
    result: FactorResearchResult,
    output_path: Path,
    source_name: str,
    source_note: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    top = result.ranking.head(25)
    lines = [
        "# Factor Research Report",
        "",
        "## Dataset",
        "",
        f"- Source: **{source_name}**",
        f"- Note: {source_note}",
        "",
        "## Top Predictive Features",
        "",
        top.to_markdown(index=False) if not top.empty else "No valid factor rows.",
        "",
        "## Methodology",
        "",
        "Features are compared against forward returns across multiple horizons. Rank IC is the primary ranking metric; conditional return spread is used as a monotonicity diagnostic.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_strategy_report(
    result: BacktestResult,
    output_path: Path,
    strategy: str,
    source_name: str,
    equity_path: Path,
    drawdown_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Backtest Report: {strategy}",
        "",
        f"- Source: **{source_name}**",
        f"- Equity chart: [{equity_path.name}](../../outputs/figures/{equity_path.name})",
        f"- Drawdown chart: [{drawdown_path.name}](../../outputs/figures/{drawdown_path.name})",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in result.metrics.items():
        lines.append(f"| {key} | {value:.6f} |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_strategy_comparison(
    comparison: pd.DataFrame,
    output_path: Path,
    metadata: dict[str, str],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Strategy Comparison", "", *_metadata_lines(metadata), "## Ranking", "", comparison.to_markdown(index=False)]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    comparison.to_csv(output_path.with_suffix(".csv"), index=False)
    return output_path


def _write_monte_carlo_report(
    intervals: dict[str, float],
    output_path: Path,
    metadata: dict[str, str],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Monte Carlo Robustness Report", "", *_metadata_lines(metadata), "## Confidence Intervals", "", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {key} | {value:.6f} |" for key, value in intervals.items())
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_ml_report(metrics: dict[str, float], output_path: Path, metadata: dict[str, str]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Machine Learning Research Report",
        "",
        *_metadata_lines(metadata),
        "## Model",
        "",
        "Random Forest return forecasting baseline with chronological train/test split.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value:.6f} |" for key, value in metrics.items())
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_portfolio_report(
    returns: pd.Series,
    strategy_returns: pd.DataFrame,
    equity_path: Path,
    output_path: Path,
    metadata: dict[str, str],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    correlation = strategy_returns.corr().round(3)
    weights = pd.Series(1 / len(strategy_returns.columns), index=strategy_returns.columns, name="weight")
    lines = [
        "# Portfolio Research Report",
        "",
        *_metadata_lines(metadata),
        f"- Equity chart: [{equity_path.name}](../../outputs/figures/{equity_path.name})",
        f"- Mean return: `{returns.mean():.8f}`",
        f"- Volatility: `{returns.std():.8f}`",
        f"- Max drawdown: `{drawdown.min():.6f}`",
        "",
        "## Equal Weights",
        "",
        weights.to_frame().to_markdown(),
        "",
        "## Strategy Return Correlation",
        "",
        correlation.to_markdown(),
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _periods_per_year(timeframe: str) -> int:
    mapping = {"1m": 525_600, "5m": 105_120, "1h": 8_760, "1d": 365}
    return mapping.get(timeframe, 365)
