"""Research strategy definitions with parameterized configurations."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.features.library import _rsi, _true_range


@dataclass(frozen=True)
class EMATrendConfig:
    """EMA trend-following configuration."""

    fast: int = 20
    slow: int = 100


@dataclass(frozen=True)
class RSIMeanReversionConfig:
    """RSI mean-reversion configuration."""

    window: int = 14
    entry: float = 30
    exit: float = 50


@dataclass(frozen=True)
class BollingerMeanReversionConfig:
    """Bollinger Band mean-reversion configuration."""

    window: int = 20
    z_entry: float = -2.0
    z_exit: float = 0.0


@dataclass(frozen=True)
class DonchianBreakoutConfig:
    """Donchian breakout configuration."""

    window: int = 55


@dataclass(frozen=True)
class ATRBreakoutConfig:
    """ATR breakout configuration."""

    window: int = 20
    atr_multiple: float = 1.5


@dataclass(frozen=True)
class MACDCrossConfig:
    """MACD crossover configuration."""

    fast: int = 12
    slow: int = 26
    signal: int = 9


@dataclass(frozen=True)
class StochasticMRConfig:
    """Stochastic mean-reversion configuration."""

    k_window: int = 14
    d_window: int = 3
    oversold: float = 20.0
    overbought: float = 80.0


@dataclass(frozen=True)
class MLSignalConfig:
    """Gradient Boosting binary classifier on technical features."""

    train_frac: float = 0.65
    n_estimators: int = 100
    max_depth: int = 3
    threshold: float = 0.001


def build_strategy_signals(data: pd.DataFrame, strategy: str) -> pd.Series:
    """Dispatch a named strategy into long/flat target exposure."""

    mapping = {
        "ema_trend": lambda: ema_trend(data, EMATrendConfig()),
        "rsi_mean_reversion": lambda: rsi_mean_reversion(data, RSIMeanReversionConfig()),
        "bollinger_mean_reversion": lambda: bollinger_mean_reversion(data, BollingerMeanReversionConfig()),
        "donchian_breakout": lambda: donchian_breakout(data, DonchianBreakoutConfig()),
        "atr_breakout": lambda: atr_breakout(data, ATRBreakoutConfig()),
        "macd_cross": lambda: macd_cross(data, MACDCrossConfig()),
        "stochastic_mr": lambda: stochastic_mr(data, StochasticMRConfig()),
        "ml_signal": lambda: ml_signal(data, MLSignalConfig()),
    }
    if strategy not in mapping:
        raise ValueError(f"Unknown strategy: {strategy}")
    return mapping[strategy]()


def ema_trend(data: pd.DataFrame, config: EMATrendConfig) -> pd.Series:
    """Long when fast EMA is above slow EMA."""

    fast = data["close"].ewm(span=config.fast, adjust=False).mean()
    slow = data["close"].ewm(span=config.slow, adjust=False).mean()
    return (fast > slow).astype(float)


def rsi_mean_reversion(data: pd.DataFrame, config: RSIMeanReversionConfig) -> pd.Series:
    """Enter when RSI is oversold and exit when it mean-reverts."""

    rsi = _rsi(data["close"], config.window)
    position = pd.Series(0.0, index=data.index)
    active = False
    for idx, value in rsi.items():
        if value < config.entry:
            active = True
        elif value > config.exit:
            active = False
        position.loc[idx] = float(active)
    return position


def bollinger_mean_reversion(data: pd.DataFrame, config: BollingerMeanReversionConfig) -> pd.Series:
    """Enter below lower z-score band and exit near the moving average."""

    mean = data["close"].rolling(config.window).mean()
    std = data["close"].rolling(config.window).std()
    zscore = (data["close"] - mean) / std
    return _stateful_long_signal(zscore < config.z_entry, zscore > config.z_exit)


def donchian_breakout(data: pd.DataFrame, config: DonchianBreakoutConfig) -> pd.Series:
    """Long on upside Donchian channel breakouts."""

    breakout = data["close"] > data["high"].rolling(config.window).max().shift(1)
    exit_signal = data["close"] < data["low"].rolling(config.window).min().shift(1)
    return _stateful_long_signal(breakout, exit_signal)


def atr_breakout(data: pd.DataFrame, config: ATRBreakoutConfig) -> pd.Series:
    """Long when close exceeds a moving average by an ATR threshold."""

    atr = _true_range(data["high"], data["low"], data["close"]).rolling(config.window).mean()
    mean = data["close"].rolling(config.window).mean()
    return _stateful_long_signal(data["close"] > mean + config.atr_multiple * atr, data["close"] < mean)


def macd_cross(data: pd.DataFrame, config: MACDCrossConfig) -> pd.Series:
    """Long when MACD line crosses above signal line."""

    fast_ema = data["close"].ewm(span=config.fast, adjust=False).mean()
    slow_ema = data["close"].ewm(span=config.slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=config.signal, adjust=False).mean()
    return _stateful_long_signal(macd_line > signal_line, macd_line < signal_line)


def stochastic_mr(data: pd.DataFrame, config: StochasticMRConfig) -> pd.Series:
    """Enter long when stochastic %K is oversold, exit when overbought."""

    low_min = data["low"].rolling(config.k_window).min()
    high_max = data["high"].rolling(config.k_window).max()
    k = 100 * (data["close"] - low_min) / (high_max - low_min + 1e-9)
    d = k.rolling(config.d_window).mean()
    return _stateful_long_signal(d < config.oversold, d > config.overbought)


def ml_signal(data: pd.DataFrame, config: MLSignalConfig) -> pd.Series:
    """GradientBoosting classifier on RSI/MACD/Bollinger/ATR features.

    Trains on the first `train_frac` of bars and predicts on the rest.
    The training period carries a flat (0) signal to avoid look-ahead bias.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
    except ImportError as e:
        raise ImportError("scikit-learn required: uv add scikit-learn") from e

    n = len(data)
    if n < 120:
        return pd.Series(0.0, index=data.index)

    close = data["close"]
    high = data["high"]
    low = data["low"]

    # --- features ---
    rsi = _rsi(close, 14).fillna(50.0)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_norm = ((ema12 - ema26) / close.clip(lower=1e-9)).fillna(0.0)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std().clip(lower=1e-9)
    bb_pct = ((close - bb_mid) / bb_std).fillna(0.0)
    atr = _true_range(high, low, close).rolling(14).mean()
    atr_norm = (atr / close.clip(lower=1e-9)).fillna(0.0)
    ret5 = close.pct_change(5).fillna(0.0)
    ret20 = close.pct_change(20).fillna(0.0)

    features = pd.DataFrame({
        "rsi": rsi, "macd": macd_norm, "bb_pct": bb_pct,
        "atr": atr_norm, "ret5": ret5, "ret20": ret20,
    }).fillna(0.0).values

    # target: next bar closes higher by > threshold
    fwd_ret = close.pct_change(1).shift(-1).fillna(0.0)
    labels = (fwd_ret > config.threshold).astype(int).values

    train_end = int(n * config.train_frac)
    model = GradientBoostingClassifier(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        random_state=42,
    )
    model.fit(features[:train_end], labels[:train_end])

    preds = model.predict(features[train_end:])
    signals = pd.Series(0.0, index=data.index)
    signals.iloc[train_end:] = preds.astype(float)
    return signals


def _stateful_long_signal(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    position = pd.Series(0.0, index=entry.index)
    active = False
    for idx in entry.index:
        if bool(entry.loc[idx]):
            active = True
        elif bool(exit_signal.loc[idx]):
            active = False
        position.loc[idx] = float(active)
    return position
