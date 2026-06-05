# Strategy Research

The platform ships five parameterised strategy families, all implemented as long/flat signal generators. Each strategy is designed as a research baseline — a starting point for parameter optimisation, regime filtering, and walk-forward validation rather than a production trading system.

## Strategy Interface

All strategies follow a common interface:

```python
def build_strategy_signals(data: pd.DataFrame, strategy: str) -> pd.Series:
    ...
```

Input: OHLCV DataFrame with a `close`, `high`, `low`, `volume` column.
Output: `pd.Series` of `{0.0, 1.0}` values — 1.0 = long, 0.0 = flat.

Each strategy can also be called directly with a custom config dataclass:

```python
from src.strategies.rules import ema_trend, EMATrendConfig

config = EMATrendConfig(fast=10, slow=50)
signals = ema_trend(data, config)
```

## Strategy Definitions

### 1. EMA Trend (`ema_trend`)

**Hypothesis:** Prices that are above their slow exponential moving average tend to continue rising.

**Config:**
```python
@dataclass(frozen=True)
class EMATrendConfig:
    fast: int = 20    # Short-term EMA span
    slow: int = 100   # Long-term EMA span
```

**Signal logic:**
```
fast_ema[t] = EWM(close, span=fast)
slow_ema[t] = EWM(close, span=slow)

signal[t] = 1.0  if fast_ema[t] > slow_ema[t]
            0.0  otherwise
```

**Characteristics:** Low trade frequency (few crossings), long holding periods, naturally captures large trending moves, tends to underperform in choppy or ranging markets.

---

### 2. RSI Mean Reversion (`rsi_mean_reversion`)

**Hypothesis:** Extreme short-term oversold conditions tend to reverse.

**Config:**
```python
@dataclass(frozen=True)
class RSIMeanReversionConfig:
    window: int = 14     # RSI lookback period
    entry: float = 30.0  # Enter long when RSI falls below this
    exit: float = 50.0   # Exit when RSI recovers above this
```

**Signal logic:**
```
rsi[t] = RSI(close, window)

if rsi[t] < entry:  active = True   (oversold → enter)
if rsi[t] > exit:   active = False  (reverted → exit)

signal[t] = 1.0 if active else 0.0
```

The state machine is stateful: once active, it stays long until the exit threshold is crossed.

**Characteristics:** Performs well in ranging markets with mean-reverting price action. Loses money in sustained downtrends where RSI remains depressed for long periods.

---

### 3. Bollinger Band Mean Reversion (`bollinger_mean_reversion`)

**Hypothesis:** Prices that deviate far from their rolling mean tend to revert.

**Config:**
```python
@dataclass(frozen=True)
class BollingerMeanReversionConfig:
    window: int = 20      # Rolling mean and std lookback
    z_entry: float = -2.0 # Enter when z-score drops below this
    z_exit: float = 0.0   # Exit when z-score returns above this
```

**Signal logic:**
```
mean[t]   = rolling_mean(close, window)
std[t]    = rolling_std(close, window)
zscore[t] = (close[t] - mean[t]) / std[t]

if zscore[t] < z_entry:  active = True   (price below −2σ → enter)
if zscore[t] > z_exit:   active = False  (price returns to mean → exit)

signal[t] = 1.0 if active else 0.0
```

**Characteristics:** Similar to RSI mean reversion but normalises entry by recent volatility, making the signal adaptive. More frequent entries than RSI in low-volatility regimes.

---

### 4. Donchian Breakout (`donchian_breakout`)

**Hypothesis:** A breakout above the highest price of the last N periods signals a new upward trend.

**Config:**
```python
@dataclass(frozen=True)
class DonchianBreakoutConfig:
    window: int = 55   # Lookback period for channel (Turtle Trading default)
```

**Signal logic:**
```
upper_channel[t] = max(high[t-window : t-1])
lower_channel[t] = min(low[t-window : t-1])

if close[t] > upper_channel[t]:  active = True   (breakout → enter)
if close[t] < lower_channel[t]:  active = False  (breakdown → exit)

signal[t] = 1.0 if active else 0.0
```

The `shift(1)` on channel boundaries prevents look-ahead: the channel is computed from bars that closed *before* bar t.

**Characteristics:** Classic trend-following. The 55-period default comes from the original Turtle Trading rules. Works well in strongly trending markets; generates whipsaws in ranging conditions.

---

### 5. ATR Breakout (`atr_breakout`)

**Hypothesis:** A close above the moving average plus a volatility-adjusted threshold signals a trend breakout.

**Config:**
```python
@dataclass(frozen=True)
class ATRBreakoutConfig:
    window: int = 20            # MA and ATR lookback
    atr_multiple: float = 1.5   # ATR multiplier for the entry threshold
```

**Signal logic:**
```
true_range[t] = max(high[t]-low[t], |high[t]-close[t-1]|, |low[t]-close[t-1]|)
atr[t]        = rolling_mean(true_range, window)
ma[t]         = rolling_mean(close, window)

if close[t] > ma[t] + atr_multiple × atr[t]:  active = True   (vol-adjusted breakout)
if close[t] < ma[t]:                           active = False  (price falls back)

signal[t] = 1.0 if active else 0.0
```

**Characteristics:** Unlike Donchian, the threshold adapts to current volatility. During high-volatility periods the bar needs to exceed a larger margin; in quiet periods a smaller move is sufficient. This filters out some false breakouts.

---

## Regime Sensitivity

Historical backtests across Binance BTCUSDT data show consistent regime sensitivity:

| Regime | Best performing family | Reason |
|---|---|---|
| **Strong uptrend** | EMA Trend, Donchian, ATR Breakout | Trend-following strategies ride extended moves |
| **Ranging / sideways** | RSI MR, Bollinger MR | Mean-reversion profits from oscillations |
| **Sharp reversal / oversold** | RSI MR | Captures V-shaped recoveries |
| **High volatility trend** | ATR Breakout | Volatility-adaptive threshold avoids noise |

The Insights section automatically detects the current regime (from EMA20/EMA50 crossover and return autocorrelation) and recommends the strategy with the best Sharpe on the most recent 90 days.

## Parameter Stability

The global report (`analysis/global_report.py`) runs each strategy with small parameter variations around the default (e.g. EMA Trend with fast=18/20/22, slow=90/100/110) to assess whether performance is robust or highly sensitive to exact parameter choice. High variance across nearby parameters is a red flag for curve fitting.

## Adding a New Strategy

1. Add a config dataclass and a signal function to `src/strategies/rules.py`.
2. Register the string name in the `mapping` dict inside `build_strategy_signals`.
3. Add the label to `STRATEGY_LABELS` in `src/web/app.py` and in `web/dashboard.html`.

No other changes are required — the backtesting engine, web dashboard, and report generator are all driven by the string name.
