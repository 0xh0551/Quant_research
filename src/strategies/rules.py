"""Research strategy definitions with parameterized configurations.

Long/flat by default (allow_short=False).
When allow_short=True (futures mode), strategies return -1/0/+1 signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.library import _rsi, _true_range


# ── Config dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EMATrendConfig:
    fast: int = 20
    slow: int = 100


@dataclass(frozen=True)
class RSIMeanReversionConfig:
    window: int = 14
    entry: float = 30
    exit: float = 50
    short_entry: float = 70   # enter short when RSI above this


@dataclass(frozen=True)
class BollingerMeanReversionConfig:
    window: int = 20
    z_entry: float = -2.0
    z_exit: float = 0.0


@dataclass(frozen=True)
class DonchianBreakoutConfig:
    window: int = 55


@dataclass(frozen=True)
class ATRBreakoutConfig:
    window: int = 20
    atr_multiple: float = 1.5


@dataclass(frozen=True)
class MACDCrossConfig:
    fast: int = 12
    slow: int = 26
    signal: int = 9


@dataclass(frozen=True)
class StochasticMRConfig:
    k_window: int = 14
    d_window: int = 3
    oversold: float = 20.0
    overbought: float = 80.0


@dataclass(frozen=True)
class IchimokuConfig:
    tenkan: int = 9
    kijun: int = 26
    senkou_b: int = 52


@dataclass(frozen=True)
class SuperTrendConfig:
    period: int = 10
    multiplier: float = 3.0


@dataclass(frozen=True)
class VWAPDeviationConfig:
    window: int = 20
    threshold: float = 2.0   # deviation % to trigger signal


@dataclass(frozen=True)
class CMFTrendConfig:
    window: int = 20
    threshold: float = 0.05


@dataclass(frozen=True)
class HammerPatternConfig:
    shadow_ratio: float = 2.0   # lower shadow must be N × body


@dataclass(frozen=True)
class EngulfingConfig:
    body_ratio: float = 1.2   # engulfing body must be N × prior body


@dataclass(frozen=True)
class MLSignalConfig:
    train_frac: float = 0.65
    n_estimators: int = 100
    max_depth: int = 3
    threshold: float = 0.001


# ── Default config map (used by Lab optimizer) ────────────────────────────────

STRATEGY_DEFAULT_CONFIGS: dict[str, object] = {
    "ema_trend": EMATrendConfig(),
    "rsi_mean_reversion": RSIMeanReversionConfig(),
    "bollinger_mean_reversion": BollingerMeanReversionConfig(),
    "donchian_breakout": DonchianBreakoutConfig(),
    "atr_breakout": ATRBreakoutConfig(),
    "macd_cross": MACDCrossConfig(),
    "stochastic_mr": StochasticMRConfig(),
    "ichimoku": IchimokuConfig(),
    "supertrend": SuperTrendConfig(),
    "vwap_deviation": VWAPDeviationConfig(),
    "cmf_trend": CMFTrendConfig(),
    "hammer_pattern": HammerPatternConfig(),
    "engulfing": EngulfingConfig(),
    "ml_signal": MLSignalConfig(),
}

# Parameter grid for Lab optimizer
STRATEGY_PARAM_GRIDS: dict[str, dict[str, list]] = {
    "ema_trend": {"fast": [10, 20, 30], "slow": [50, 100, 200]},
    "rsi_mean_reversion": {"window": [7, 14, 21], "entry": [20, 25, 30], "exit": [50, 55, 60]},
    "bollinger_mean_reversion": {"window": [10, 20, 30], "z_entry": [-1.5, -2.0, -2.5], "z_exit": [-0.5, 0.0, 0.5]},
    "donchian_breakout": {"window": [20, 35, 55]},
    "atr_breakout": {"window": [10, 20, 30], "atr_multiple": [1.0, 1.5, 2.0]},
    "macd_cross": {"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [7, 9, 13]},
    "stochastic_mr": {"k_window": [9, 14, 21], "oversold": [15, 20, 25], "overbought": [75, 80, 85]},
    "ichimoku": {"tenkan": [7, 9, 12], "kijun": [22, 26, 30]},
    "supertrend": {"period": [7, 10, 14], "multiplier": [2.0, 3.0, 4.0]},
    "vwap_deviation": {"window": [14, 20, 30], "threshold": [1.0, 2.0, 3.0]},
    "cmf_trend": {"window": [10, 20, 30], "threshold": [0.03, 0.05, 0.1]},
    "hammer_pattern": {"shadow_ratio": [1.5, 2.0, 2.5]},
    "engulfing": {"body_ratio": [1.0, 1.2, 1.5]},
}

# Lab UI param spec
STRATEGY_PARAM_SPECS: dict[str, list[dict]] = {
    "ema_trend": [
        {"key": "fast", "label": "Fast EMA", "type": "int", "min": 5, "max": 50, "default": 20},
        {"key": "slow", "label": "Slow EMA", "type": "int", "min": 20, "max": 300, "default": 100},
    ],
    "rsi_mean_reversion": [
        {"key": "window", "label": "RSI Period", "type": "int", "min": 5, "max": 30, "default": 14},
        {"key": "entry", "label": "Oversold Level", "type": "float", "min": 10.0, "max": 40.0, "default": 30.0},
        {"key": "exit", "label": "Exit Level", "type": "float", "min": 40.0, "max": 70.0, "default": 50.0},
        {"key": "short_entry", "label": "Overbought Level (Short)", "type": "float", "min": 60.0, "max": 90.0, "default": 70.0},
    ],
    "bollinger_mean_reversion": [
        {"key": "window", "label": "BB Period", "type": "int", "min": 10, "max": 50, "default": 20},
        {"key": "z_entry", "label": "Entry Z-Score", "type": "float", "min": -3.5, "max": -1.0, "default": -2.0},
        {"key": "z_exit", "label": "Exit Z-Score", "type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
    ],
    "donchian_breakout": [
        {"key": "window", "label": "Channel Period", "type": "int", "min": 10, "max": 100, "default": 55},
    ],
    "atr_breakout": [
        {"key": "window", "label": "ATR Period", "type": "int", "min": 5, "max": 50, "default": 20},
        {"key": "atr_multiple", "label": "ATR Multiple", "type": "float", "min": 0.5, "max": 4.0, "default": 1.5},
    ],
    "macd_cross": [
        {"key": "fast", "label": "Fast Period", "type": "int", "min": 5, "max": 20, "default": 12},
        {"key": "slow", "label": "Slow Period", "type": "int", "min": 15, "max": 50, "default": 26},
        {"key": "signal", "label": "Signal Period", "type": "int", "min": 3, "max": 15, "default": 9},
    ],
    "stochastic_mr": [
        {"key": "k_window", "label": "%K Period", "type": "int", "min": 5, "max": 30, "default": 14},
        {"key": "d_window", "label": "%D Period", "type": "int", "min": 2, "max": 10, "default": 3},
        {"key": "oversold", "label": "Oversold Level", "type": "float", "min": 10.0, "max": 35.0, "default": 20.0},
        {"key": "overbought", "label": "Overbought Level", "type": "float", "min": 65.0, "max": 90.0, "default": 80.0},
    ],
    "ichimoku": [
        {"key": "tenkan", "label": "Tenkan-sen Period", "type": "int", "min": 5, "max": 20, "default": 9},
        {"key": "kijun", "label": "Kijun-sen Period", "type": "int", "min": 15, "max": 50, "default": 26},
        {"key": "senkou_b", "label": "Senkou Span B", "type": "int", "min": 30, "max": 100, "default": 52},
    ],
    "supertrend": [
        {"key": "period", "label": "ATR Period", "type": "int", "min": 5, "max": 30, "default": 10},
        {"key": "multiplier", "label": "ATR Multiplier", "type": "float", "min": 1.0, "max": 6.0, "default": 3.0},
    ],
    "vwap_deviation": [
        {"key": "window", "label": "VWAP Period", "type": "int", "min": 5, "max": 50, "default": 20},
        {"key": "threshold", "label": "Deviation % Threshold", "type": "float", "min": 0.5, "max": 5.0, "default": 2.0},
    ],
    "cmf_trend": [
        {"key": "window", "label": "CMF Period", "type": "int", "min": 5, "max": 40, "default": 20},
        {"key": "threshold", "label": "Signal Threshold", "type": "float", "min": 0.01, "max": 0.3, "default": 0.05},
    ],
    "hammer_pattern": [
        {"key": "shadow_ratio", "label": "Shadow/Body Ratio", "type": "float", "min": 1.0, "max": 4.0, "default": 2.0},
    ],
    "engulfing": [
        {"key": "body_ratio", "label": "Body Engulf Ratio", "type": "float", "min": 1.0, "max": 2.5, "default": 1.2},
    ],
    "ml_signal": [
        {"key": "n_estimators", "label": "Trees", "type": "int", "min": 50, "max": 300, "default": 100},
        {"key": "max_depth", "label": "Max Depth", "type": "int", "min": 2, "max": 7, "default": 3},
    ],
}


# ── Dispatch ──────────────────────────────────────────────────────────────────

def build_strategy_signals(
    data: pd.DataFrame,
    strategy: str,
    allow_short: bool = False,
) -> pd.Series:
    """Dispatch named strategy → position series.

    Returns values in [0, 1] (long-only) or [-1, 0, 1] when allow_short=True.
    """
    mapping = {
        "ema_trend": lambda: ema_trend(data, EMATrendConfig(), allow_short),
        "rsi_mean_reversion": lambda: rsi_mean_reversion(data, RSIMeanReversionConfig(), allow_short),
        "bollinger_mean_reversion": lambda: bollinger_mean_reversion(data, BollingerMeanReversionConfig(), allow_short),
        "donchian_breakout": lambda: donchian_breakout(data, DonchianBreakoutConfig(), allow_short),
        "atr_breakout": lambda: atr_breakout(data, ATRBreakoutConfig(), allow_short),
        "macd_cross": lambda: macd_cross(data, MACDCrossConfig(), allow_short),
        "stochastic_mr": lambda: stochastic_mr(data, StochasticMRConfig(), allow_short),
        "ichimoku": lambda: ichimoku(data, IchimokuConfig(), allow_short),
        "supertrend": lambda: supertrend(data, SuperTrendConfig(), allow_short),
        "vwap_deviation": lambda: vwap_deviation(data, VWAPDeviationConfig(), allow_short),
        "cmf_trend": lambda: cmf_trend(data, CMFTrendConfig(), allow_short),
        "hammer_pattern": lambda: hammer_pattern(data, HammerPatternConfig(), allow_short),
        "engulfing": lambda: engulfing(data, EngulfingConfig(), allow_short),
        "ml_signal": lambda: ml_signal(data, MLSignalConfig(), allow_short),
    }
    if strategy not in mapping:
        raise ValueError(f"Unknown strategy: {strategy}")
    return mapping[strategy]()


def build_strategy_signals_with_params(
    data: pd.DataFrame,
    strategy: str,
    params: dict,
    allow_short: bool = False,
) -> pd.Series:
    """Build signals using a custom params dict (used by Lab)."""
    cfg_class_map = {
        "ema_trend": EMATrendConfig,
        "rsi_mean_reversion": RSIMeanReversionConfig,
        "bollinger_mean_reversion": BollingerMeanReversionConfig,
        "donchian_breakout": DonchianBreakoutConfig,
        "atr_breakout": ATRBreakoutConfig,
        "macd_cross": MACDCrossConfig,
        "stochastic_mr": StochasticMRConfig,
        "ichimoku": IchimokuConfig,
        "supertrend": SuperTrendConfig,
        "vwap_deviation": VWAPDeviationConfig,
        "cmf_trend": CMFTrendConfig,
        "hammer_pattern": HammerPatternConfig,
        "engulfing": EngulfingConfig,
        "ml_signal": MLSignalConfig,
    }
    strat_func_map = {
        "ema_trend": ema_trend,
        "rsi_mean_reversion": rsi_mean_reversion,
        "bollinger_mean_reversion": bollinger_mean_reversion,
        "donchian_breakout": donchian_breakout,
        "atr_breakout": atr_breakout,
        "macd_cross": macd_cross,
        "stochastic_mr": stochastic_mr,
        "ichimoku": ichimoku,
        "supertrend": supertrend,
        "vwap_deviation": vwap_deviation,
        "cmf_trend": cmf_trend,
        "hammer_pattern": hammer_pattern,
        "engulfing": engulfing,
        "ml_signal": ml_signal,
    }
    if strategy not in cfg_class_map:
        raise ValueError(f"Unknown strategy: {strategy}")
    # Cast params to correct types using the field types of the dataclass
    import dataclasses
    cfg_cls = cfg_class_map[strategy]
    field_types = {f.name: f.type for f in dataclasses.fields(cfg_cls)}
    cast_params = {}
    for k, v in params.items():
        if k in field_types:
            t = field_types[k]
            try:
                cast_params[k] = int(v) if t == "int" else float(v)
            except (TypeError, ValueError):
                cast_params[k] = v
    config = cfg_cls(**cast_params)
    return strat_func_map[strategy](data, config, allow_short)


# ── Strategy implementations ──────────────────────────────────────────────────

def ema_trend(data: pd.DataFrame, config: EMATrendConfig, allow_short: bool = False) -> pd.Series:
    """Long when fast EMA > slow EMA; short when below (futures)."""
    fast = data["close"].ewm(span=config.fast, adjust=False).mean()
    slow = data["close"].ewm(span=config.slow, adjust=False).mean()
    long_sig = fast > slow
    if allow_short:
        return long_sig.astype(float) * 2 - 1  # +1 or -1
    return long_sig.astype(float)


def rsi_mean_reversion(data: pd.DataFrame, config: RSIMeanReversionConfig, allow_short: bool = False) -> pd.Series:
    """Long on RSI oversold, short on overbought (futures)."""
    rsi = _rsi(data["close"], config.window)
    position = pd.Series(0.0, index=data.index)
    state = 0  # 0=flat, 1=long, -1=short
    for idx, value in rsi.items():
        if value < config.entry:
            state = 1
        elif allow_short and value > config.short_entry:
            state = -1
        elif value > config.exit and state == 1:
            state = 0 if not allow_short else -1
        elif value < config.entry and state == -1:
            state = 0
        position.loc[idx] = float(state)
    if not allow_short:
        position = position.clip(lower=0.0)
    return position


def bollinger_mean_reversion(data: pd.DataFrame, config: BollingerMeanReversionConfig, allow_short: bool = False) -> pd.Series:
    """Long below lower z-band, short above upper z-band (futures)."""
    mean = data["close"].rolling(config.window).mean()
    std = data["close"].rolling(config.window).std()
    zscore = (data["close"] - mean) / std.clip(lower=1e-9)
    if allow_short:
        upper_entry = -config.z_entry  # mirror: e.g. +2.0
        long_entry = zscore < config.z_entry
        short_entry = zscore > upper_entry
        long_exit = zscore > config.z_exit
        short_exit = zscore < -config.z_exit
        return _stateful_signal(long_entry, long_exit, short_entry, short_exit)
    return _stateful_long_signal(zscore < config.z_entry, zscore > config.z_exit)


def donchian_breakout(data: pd.DataFrame, config: DonchianBreakoutConfig, allow_short: bool = False) -> pd.Series:
    """Long on upper channel breakout, short on lower breakdown (futures)."""
    hi_max = data["high"].rolling(config.window).max().shift(1)
    lo_min = data["low"].rolling(config.window).min().shift(1)
    upper_break = data["close"] > hi_max
    lower_break = data["close"] < lo_min
    upper_exit = data["close"] < lo_min
    lower_exit = data["close"] > hi_max
    if allow_short:
        return _stateful_signal(upper_break, upper_exit, lower_break, lower_exit)
    return _stateful_long_signal(upper_break, upper_exit)


def atr_breakout(data: pd.DataFrame, config: ATRBreakoutConfig, allow_short: bool = False) -> pd.Series:
    """Long above MA+ATR band, short below MA-ATR band (futures)."""
    atr = _true_range(data["high"], data["low"], data["close"]).rolling(config.window).mean()
    mean = data["close"].rolling(config.window).mean()
    long_entry = data["close"] > mean + config.atr_multiple * atr
    short_entry = data["close"] < mean - config.atr_multiple * atr
    if allow_short:
        return _stateful_signal(long_entry, ~long_entry & (data["close"] < mean), short_entry, ~short_entry & (data["close"] > mean))
    return _stateful_long_signal(long_entry, data["close"] < mean)


def macd_cross(data: pd.DataFrame, config: MACDCrossConfig, allow_short: bool = False) -> pd.Series:
    """Long when MACD crosses above signal; short when below (futures)."""
    fast_ema = data["close"].ewm(span=config.fast, adjust=False).mean()
    slow_ema = data["close"].ewm(span=config.slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=config.signal, adjust=False).mean()
    long_sig = macd_line > signal_line
    if allow_short:
        return long_sig.astype(float) * 2 - 1
    return _stateful_long_signal(macd_line > signal_line, macd_line < signal_line)


def stochastic_mr(data: pd.DataFrame, config: StochasticMRConfig, allow_short: bool = False) -> pd.Series:
    """Long on oversold %D, short on overbought (futures)."""
    low_min = data["low"].rolling(config.k_window).min()
    high_max = data["high"].rolling(config.k_window).max()
    k = 100 * (data["close"] - low_min) / (high_max - low_min + 1e-9)
    d = k.rolling(config.d_window).mean()
    if allow_short:
        return _stateful_signal(
            d < config.oversold, d > (config.oversold + config.overbought) / 2,
            d > config.overbought, d < (config.oversold + config.overbought) / 2,
        )
    return _stateful_long_signal(d < config.oversold, d > config.overbought)


def ichimoku(data: pd.DataFrame, config: IchimokuConfig, allow_short: bool = False) -> pd.Series:
    """Ichimoku Cloud: long above cloud, short below cloud (futures)."""
    high, low, close = data["high"], data["low"], data["close"]
    tenkan = (high.rolling(config.tenkan).max() + low.rolling(config.tenkan).min()) / 2
    kijun = (high.rolling(config.kijun).max() + low.rolling(config.kijun).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(config.kijun)
    senkou_b = ((high.rolling(config.senkou_b).max() + low.rolling(config.senkou_b).min()) / 2).shift(config.kijun)
    cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)

    long_entry = (close > cloud_top) & (tenkan > kijun)
    short_entry = (close < cloud_bot) & (tenkan < kijun)
    long_exit = close < cloud_bot
    short_exit = close > cloud_top

    if allow_short:
        return _stateful_signal(long_entry, long_exit, short_entry, short_exit)
    return _stateful_long_signal(long_entry, long_exit)


def supertrend(data: pd.DataFrame, config: SuperTrendConfig, allow_short: bool = False) -> pd.Series:
    """SuperTrend indicator: long above line, short below (futures)."""
    high, low, close = data["high"], data["low"], data["close"]
    atr = _true_range(high, low, close).rolling(config.period).mean()
    mid = (high + low) / 2
    basic_upper = mid + config.multiplier * atr
    basic_lower = mid - config.multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    trend = pd.Series(1, index=data.index, dtype=float)

    for i in range(1, len(data)):
        bu_prev = final_upper.iloc[i - 1]
        bl_prev = final_lower.iloc[i - 1]
        c_prev = close.iloc[i - 1]
        c_cur = close.iloc[i]

        fu = basic_upper.iloc[i]
        fl = basic_lower.iloc[i]
        final_upper.iloc[i] = fu if fu < bu_prev or c_prev > bu_prev else bu_prev
        final_lower.iloc[i] = fl if fl > bl_prev or c_prev < bl_prev else bl_prev

        if trend.iloc[i - 1] == -1 and c_cur > final_upper.iloc[i - 1]:
            trend.iloc[i] = 1.0
        elif trend.iloc[i - 1] == 1 and c_cur < final_lower.iloc[i - 1]:
            trend.iloc[i] = -1.0
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    if allow_short:
        return trend
    return (trend > 0).astype(float)


def vwap_deviation(data: pd.DataFrame, config: VWAPDeviationConfig, allow_short: bool = False) -> pd.Series:
    """Mean-reversion around rolling VWAP; short when price far above (futures)."""
    typical = (data["high"] + data["low"] + data["close"]) / 3
    vol = data["volume"].clip(lower=1e-9)
    vwap = (typical * vol).rolling(config.window).sum() / vol.rolling(config.window).sum()
    deviation = (data["close"] - vwap) / vwap.clip(lower=1e-9) * 100.0

    long_entry = deviation < -config.threshold
    short_entry = deviation > config.threshold
    long_exit = deviation > 0
    short_exit = deviation < 0

    if allow_short:
        return _stateful_signal(long_entry, long_exit, short_entry, short_exit)
    return _stateful_long_signal(long_entry, long_exit)


def cmf_trend(data: pd.DataFrame, config: CMFTrendConfig, allow_short: bool = False) -> pd.Series:
    """Chaikin Money Flow: long on positive CMF, short on negative (futures)."""
    hl_range = (data["high"] - data["low"]).clip(lower=1e-9)
    mfm = ((data["close"] - data["low"]) - (data["high"] - data["close"])) / hl_range
    mfv = mfm * data["volume"]
    cmf_val = mfv.rolling(config.window).sum() / data["volume"].rolling(config.window).sum()

    long_entry = cmf_val > config.threshold
    short_entry = cmf_val < -config.threshold
    long_exit = cmf_val < 0
    short_exit = cmf_val > 0

    if allow_short:
        return _stateful_signal(long_entry, long_exit, short_entry, short_exit)
    return _stateful_long_signal(long_entry, long_exit)


def hammer_pattern(data: pd.DataFrame, config: HammerPatternConfig, allow_short: bool = False) -> pd.Series:
    """Hammer (bullish) and Shooting Star (bearish) candlestick patterns."""
    o = data["open"]
    c = data["close"]
    h = data["high"]
    lo = data["low"]

    body = (c - o).abs().clip(lower=1e-9)
    body_top = pd.concat([o, c], axis=1).max(axis=1)
    body_bot = pd.concat([o, c], axis=1).min(axis=1)
    upper_shadow = h - body_top
    lower_shadow = body_bot - lo

    hammer = (lower_shadow >= config.shadow_ratio * body) & (upper_shadow < body)
    shooting_star = (upper_shadow >= config.shadow_ratio * body) & (lower_shadow < body)

    if allow_short:
        return _stateful_signal(hammer, shooting_star, shooting_star, hammer)
    return _stateful_long_signal(hammer, shooting_star)


def engulfing(data: pd.DataFrame, config: EngulfingConfig, allow_short: bool = False) -> pd.Series:
    """Bullish/Bearish engulfing candlestick pattern."""
    o = data["open"]
    c = data["close"]

    prev_body = (c.shift(1) - o.shift(1)).abs().clip(lower=1e-9)
    cur_body = (c - o).abs()
    prev_bull = c.shift(1) > o.shift(1)
    prev_bear = c.shift(1) < o.shift(1)
    cur_bull = c > o
    cur_bear = c < o

    bull_engulf = cur_bull & prev_bear & (cur_body > config.body_ratio * prev_body)
    bear_engulf = cur_bear & prev_bull & (cur_body > config.body_ratio * prev_body)

    if allow_short:
        return _stateful_signal(bull_engulf, bear_engulf, bear_engulf, bull_engulf)
    return _stateful_long_signal(bull_engulf, bear_engulf)


def ml_signal(data: pd.DataFrame, config: MLSignalConfig, allow_short: bool = False) -> pd.Series:
    """GradientBoosting classifier on RSI/MACD/Bollinger/ATR features."""
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

    fwd_ret = close.pct_change(1).shift(-1).fillna(0.0)
    if allow_short:
        # 3-class: -1 down, 0 flat, +1 up
        labels = np.where(fwd_ret > config.threshold, 1, np.where(fwd_ret < -config.threshold, -1, 0))
    else:
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
    if not allow_short:
        signals = signals.clip(lower=0.0)
    return signals


# ── Signal helpers ────────────────────────────────────────────────────────────

def _stateful_long_signal(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    """Hold long position between entry and exit events."""
    position = pd.Series(0.0, index=entry.index)
    active = False
    for idx in entry.index:
        if bool(entry.loc[idx]):
            active = True
        elif bool(exit_signal.loc[idx]):
            active = False
        position.loc[idx] = float(active)
    return position


def _stateful_signal(
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series,
    short_exit: pd.Series,
) -> pd.Series:
    """Stateful long/short/flat position. Long=+1, Short=-1, Flat=0."""
    position = pd.Series(0.0, index=long_entry.index)
    state = 0  # 0=flat, 1=long, -1=short
    for idx in long_entry.index:
        if bool(long_entry.loc[idx]):
            state = 1
        elif bool(short_entry.loc[idx]):
            state = -1
        elif state == 1 and bool(long_exit.loc[idx]):
            state = -1
        elif state == -1 and bool(short_exit.loc[idx]):
            state = 1
        position.loc[idx] = float(state)
    return position
