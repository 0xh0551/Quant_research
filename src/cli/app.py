"""Typer CLI for the Bitcoin Quantitative Research Platform."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import typer
from rich.console import Console

from src.analysis import combine_strategy_returns, run_monte_carlo
from src.backtesting import BacktestConfig, VectorizedBacktester
from src.data.downloader import DataIngestionPipeline, DownloadRequest
from src.data.storage import ParquetDataStore
from src.factors import FactorResearcher
from src.features import FeatureBuilder
from src.ml import TimeSeriesMLResearcher, future_return_target
from src.strategies import build_strategy_signals
from src.validation import DataValidator
from src.visualization import save_drawdown_chart, save_equity_curve

app = typer.Typer(help="Bitcoin quantitative research pipeline")
console = Console()
BASE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
STRATEGIES = ["ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion", "donchian_breakout", "atr_breakout"]


@app.command()
def demo(rows: int = 1500) -> None:
    """Generate deterministic sample data and all core sample reports."""

    root = Path.cwd()
    data = sample_ohlcv(rows)
    processed_path = ParquetDataStore(root / "data/processed").write(data, "BTCUSDT", "1h")

    validator = DataValidator("1h")
    validator.write_markdown(validator.validate(data), root / "reports/data_quality/BTCUSDT_1h.md")

    enriched = FeatureBuilder().build(data)
    research_path = root / "data/research/BTCUSDT_1h_features.parquet"
    research_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(research_path, index=False)

    feature_columns = [column for column in enriched.columns if column not in BASE_COLUMNS]
    researcher = FactorResearcher([1, 6, 24])
    factor_result = researcher.evaluate(enriched, feature_columns[:50])
    researcher.write_report(factor_result, root / "reports/factor_research/BTCUSDT_1h.md")

    backtester = VectorizedBacktester(BacktestConfig(periods_per_year=24 * 365))
    strategy_returns: dict[str, pd.Series] = {}
    for strategy in STRATEGIES:
        result = backtester.run(data, build_strategy_signals(data, strategy))
        strategy_returns[strategy] = result.returns
        backtester.write_report(result, root / f"reports/backtests/{strategy}.md")
        save_equity_curve(result.equity, root / f"outputs/figures/{strategy}_equity.png", f"{strategy} Equity")
        save_drawdown_chart(result.equity, root / f"outputs/figures/{strategy}_drawdown.png", f"{strategy} Drawdown")

    portfolio_returns = combine_strategy_returns(pd.DataFrame(strategy_returns))
    portfolio_equity = 10_000 * (1 + portfolio_returns).cumprod()
    save_equity_curve(portfolio_equity, root / "outputs/figures/portfolio_equity.png", "Equal Weight Portfolio")
    _write_portfolio_report(portfolio_returns, root / "reports/portfolio/equal_weight.md")

    mc = run_monte_carlo(strategy_returns["ema_trend"], simulations=1000)
    _write_monte_carlo_report(mc.confidence_intervals, root / "reports/monte_carlo/ema_trend.md")

    ml_result = TimeSeriesMLResearcher(test_fraction=0.25).train_random_forest(enriched, feature_columns[:20], future_return_target(enriched, 24))
    _write_ml_report(ml_result.metrics, root / "reports/ml/random_forest_returns.md")

    console.print(f"[green]Demo complete[/green]: {processed_path}")
    console.print("Reports written under reports/ and charts under outputs/figures/.")


@app.command()
def download(symbol: str = "BTCUSDT", timeframe: str = "1h", start: date = date(2020, 1, 1), output: Path = Path("data/processed")) -> None:
    """Download Binance Spot candles to Parquet."""

    path = DataIngestionPipeline(ParquetDataStore(output)).run(DownloadRequest(symbol, timeframe, start))
    console.print(f"[green]Wrote[/green] {path}")


@app.command()
def validate(path: Path, timeframe: str = "1h") -> None:
    """Validate a Parquet OHLCV dataset and write a Markdown report."""

    data = pd.read_parquet(path)
    report_path = Path("reports/data_quality") / f"{path.stem}.md"
    validator = DataValidator(timeframe)
    validator.write_markdown(validator.validate(data), report_path)
    console.print(f"[green]Report[/green] {report_path}")


@app.command()
def factors(path: Path, horizon: int = 24) -> None:
    """Run feature generation and factor research for a dataset."""

    data = pd.read_parquet(path)
    enriched = FeatureBuilder().build(data)
    feature_columns = [column for column in enriched.columns if column not in BASE_COLUMNS]
    researcher = FactorResearcher([horizon])
    report_path = Path("reports/factor_research") / f"{path.stem}.md"
    researcher.write_report(researcher.evaluate(enriched, feature_columns), report_path)
    console.print(f"[green]Report[/green] {report_path}")


@app.command()
def backtest(path: Path, strategy: str = "ema_trend") -> None:
    """Backtest one named strategy."""

    data = pd.read_parquet(path)
    backtester = VectorizedBacktester()
    result = backtester.run(data, build_strategy_signals(data, strategy))
    report_path = Path("reports/backtests") / f"{strategy}.md"
    backtester.write_report(result, report_path)
    save_equity_curve(result.equity, Path("outputs/figures") / f"{strategy}_equity.png")
    console.print(f"[green]Report[/green] {report_path}")


def sample_ohlcv(rows: int = 1500) -> pd.DataFrame:
    """Create deterministic synthetic BTC-like OHLCV for tests and demo reports."""

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


def _write_monte_carlo_report(intervals: dict[str, float], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Monte Carlo Robustness Report", "", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {key} | {value:.6f} |" for key, value in intervals.items())
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_ml_report(metrics: dict[str, float], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Machine Learning Research Report", "", "Model: Random Forest return forecasting baseline.", "", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {key} | {value:.6f} |" for key, value in metrics.items())
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _write_portfolio_report(returns: pd.Series, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    lines = ["# Portfolio Research Report", "", f"- Mean return: `{returns.mean():.8f}`", f"- Volatility: `{returns.std():.8f}`", f"- Max drawdown: `{drawdown.min():.6f}`"]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
