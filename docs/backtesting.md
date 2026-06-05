# Backtesting Engine

The backtesting engine (`src/backtesting/engine.py`) is a vectorised long/flat simulator designed for rapid iteration over large datasets. It models realistic execution assumptions without requiring an event-driven loop.

## Design Decisions

**Vectorised, not event-driven.** All operations run as numpy array computations. This allows testing thousands of parameter combinations in seconds at the cost of not being able to model intra-bar execution or complex order types.

**Long/flat only.** The engine holds either 100% of capital in the asset or 0% (cash). No leverage, short selling, or partial position sizing. This is appropriate for the long-only crypto research scope.

**Execution delay.** The signal is computed at bar close and executed at the *next* bar open (modelled as the next bar's close with a one-bar shift). This prevents unrealistic same-bar execution.

**Costs on turnover.** Transaction costs are charged proportionally to position changes, not to total capital. Holding a position incurs no ongoing fee; only entries and exits cost money.

## Configuration

```python
@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0   # Starting portfolio value ($)
    fee_bps: float = 10.0               # Exchange fee (basis points, one-way)
    slippage_bps: float = 2.0           # Market impact (basis points, one-way)
    spread_bps: float = 0.0             # Bid-ask spread (basis points)
    execution_delay: int = 1            # Bars between signal and execution
    periods_per_year: int = 365         # Used for annualisation
```

`periods_per_year` should match the timeframe of the data:

| Timeframe | `periods_per_year` |
|---|---|
| `1m` | 525 600 |
| `5m` | 105 120 |
| `15m` | 35 040 |
| `30m` | 17 520 |
| `1h` | 8 760 |
| `2h` | 4 380 |
| `4h` | 2 190 |
| `1d` | 365 |

## Execution Logic

```
close_returns[t]  = close[t] / close[t-1] - 1

position[t]       = target[t - execution_delay]   (clipped to [0, 1])
turnover[t]       = |position[t] - position[t-1]|
costs[t]          = turnover[t] × (fee_bps + slippage_bps + spread_bps) / 10_000

strategy_return[t] = position[t-1] × close_returns[t] - costs[t]
equity[t]          = equity[t-1] × (1 + strategy_return[t])
```

The one-period lag on `position` in the return calculation reflects the fact that a position entered at close[t] earns the return from close[t] to close[t+1].

## Performance Metrics

| Metric | Formula | Notes |
|---|---|---|
| **Total Return** | `equity[-1] / equity[0] - 1` | Raw P&L |
| **CAGR** | `(1 + total_return)^(1/years) - 1` | Compound annual growth rate |
| **Sharpe Ratio** | `mean(r) × PPY / std(r) × √PPY` | Annualised; no risk-free rate subtracted |
| **Sortino Ratio** | `mean(r) × PPY / downside_std × √PPY` | Downside deviation uses only negative returns |
| **Calmar Ratio** | `CAGR / |max_drawdown|` | Lower drawdown and higher CAGR → higher Calmar |
| **Maximum Drawdown** | `min(equity / cummax(equity) - 1)` | Negative fraction; worst peak-to-trough decline |
| **Profit Factor** | `sum(positive returns) / |sum(negative returns)|` | > 1 means more gross profit than loss |
| **Win Rate** | `count(returns > 0) / count(returns)` | Fraction of bars with positive net return |

## Logarithmic Returns

The Research section offers a toggle between simple and log returns for display purposes. Log returns are computed as:

```
log_return[t] = log(1 + strategy_return[t])
```

The equity curve is identical in both modes (it uses compound growth of simple returns). Log returns are additive over time and Gaussian-distributed for longer horizons, making them more appropriate for statistical testing and regime analysis.

**Annualised log return:**
```
ann_log_return = mean(log_returns) × periods_per_year
```

**Log Sharpe:**
```
log_sharpe = mean(log_returns) × PPY / (std(log_returns) × √PPY)
```

## Buy & Hold Benchmark

Every research run also computes a buy-and-hold baseline: `target_position = 1.0` for the full period. This uses the same `BacktestConfig` (including fees charged on the initial entry). The benchmark Sharpe, CAGR, and maximum drawdown are displayed alongside strategy metrics in the Report section.

## Walk-Forward Validation

See [walk_forward.md](walk_forward.md) for out-of-sample validation methodology. The global research dashboard (`src/analysis/global_report.py`) uses a fixed split:

- **Training period:** 2020-01-01 → 2024-12-31
- **Test period:** 2025-01-01 → present

Walk-forward metrics are labelled `test_cagr`, `test_sharpe`, etc. in the metrics table to distinguish them from in-sample results.

## Example

```python
from src.backtesting.engine import BacktestConfig, VectorizedBacktester
from src.strategies.rules import build_strategy_signals
import pandas as pd

data = pd.read_parquet("data/processed/binance_BTCUSDT_1h.parquet")
config = BacktestConfig(initial_capital=10_000, fee_bps=10, periods_per_year=8760)
backtester = VectorizedBacktester(config)

signals = build_strategy_signals(data, "ema_trend")
result = backtester.run(data, signals)

print(result.metrics)
# {'total_return': 1.42, 'cagr': 0.38, 'sharpe': 1.21, ...}
```
