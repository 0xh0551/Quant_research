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


def build_strategy_signals(data: pd.DataFrame, strategy: str) -> pd.Series:
    """Dispatch a named strategy into long/flat target exposure."""

    mapping = {
        "ema_trend": lambda: ema_trend(data, EMATrendConfig()),
        "rsi_mean_reversion": lambda: rsi_mean_reversion(data, RSIMeanReversionConfig()),
        "bollinger_mean_reversion": lambda: bollinger_mean_reversion(data, BollingerMeanReversionConfig()),
        "donchian_breakout": lambda: donchian_breakout(data, DonchianBreakoutConfig()),
        "atr_breakout": lambda: atr_breakout(data, ATRBreakoutConfig()),
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
