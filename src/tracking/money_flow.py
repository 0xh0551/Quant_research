"""Money-flow detection: which coins capital is rotating into/out of right now.

Computed purely from OHLCV (`timestamp, open, high, low, close, volume` —
the only columns guaranteed for every processed symbol, see
`src/data/schema.py`). Taker-buy/funding/open-interest data exists elsewhere
in the codebase (`src/data/funding.py`) but isn't wired into the per-symbol
processed parquet pipeline, so building on it here would mean a second data
ingestion project before this signal could ever fire — deferred to a future
version.

Three classic, OHLCV-only proxies for buying/selling pressure, combined:
  - CMF (Chaikin Money Flow): where in the bar's range each close landed,
    weighted by volume — sustained CMF > 0 means buyers are in control.
  - RVOL (relative volume): current volume vs its own rolling average —
    unusual activity is the signature of capital actually moving.
  - OBV slope: direction of cumulative volume-signed flow — confirms CMF
    isn't just one noisy bar.

Mirrors `src/ml/recommend.py` (`ml_fitness` / `recommend_ml_coins`) and
`src/tracking/selection_feedback.py` (`feedback_multiplier` / `apply_feedback`)
in shape, so it plugs into `scripts/rotate_bot_pairs.py` the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.analysis.cross_exchange import parse_stem

DEFAULT_VENUES = ("bybit", "gate", "gateio", "gate_io", "okx")


def _chaikin_money_flow(df: pd.DataFrame, lookback: int) -> float:
    high, low, close, vol = df["high"], df["low"], df["close"], df["volume"]
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfv = (mfm * vol).tail(lookback)
    vol_sum = vol.tail(lookback).sum()
    if vol_sum <= 0 or mfv.dropna().empty:
        return 0.0
    return float(mfv.sum() / vol_sum)


def _relative_volume(df: pd.DataFrame, lookback: int) -> float:
    vol = df["volume"]
    baseline = vol.iloc[-(lookback + 1):-1].mean()
    if not baseline or baseline <= 0:
        return 1.0
    return float(vol.iloc[-1] / baseline)


def _obv_slope(df: pd.DataFrame, lookback: int) -> float:
    direction = np.sign(df["close"].diff()).fillna(0.0)
    obv = (direction * df["volume"]).cumsum().tail(lookback)
    if len(obv) < 2:
        return 0.0
    x = np.arange(len(obv))
    slope = float(np.polyfit(x, obv.values, 1)[0])
    scale = df["volume"].tail(lookback).mean() or 1.0
    return float(np.clip(slope / scale, -1.0, 1.0))


def money_flow_metrics(df: pd.DataFrame, lookback: int = 20) -> dict:
    """{cmf, rvol, obv_slope, n} from OHLCV only. Empty-safe."""
    n = len(df)
    if n < lookback * 5:
        return {"n": n, "reason": "insufficient_data"}
    return {
        "n": n,
        "cmf": round(_chaikin_money_flow(df, lookback), 4),
        "rvol": round(_relative_volume(df, lookback), 3),
        "obv_slope": round(_obv_slope(df, lookback), 4),
    }


def money_flow_score(df: pd.DataFrame, lookback: int = 20) -> dict:
    """Money-flow score + direction for one OHLCV dataset (0-100)."""
    m = money_flow_metrics(df, lookback)
    if "reason" in m:
        return {"money_flow_score": 0, **m}

    cmf, rvol, obv_slope = m["cmf"], m["rvol"], m["obv_slope"]
    pressure = float(np.clip(cmf, -1.0, 1.0))
    confirm = float(np.clip(obv_slope, -1.0, 1.0))
    surge = float(np.clip((rvol - 1.0) / 2.0, 0.0, 1.0))  # rvol>=3x → fully saturated

    signed = (pressure * 0.5 + confirm * 0.3) / 0.8  # in [-1, 1]
    score = round((abs(signed) * 0.7 + surge * 0.3) * 100)
    score = max(0, min(100, score))

    if score < 20 or abs(signed) < 0.1:
        direction = "neutral"
    else:
        direction = "inflow" if signed > 0 else "outflow"

    return {"money_flow_score": score, "direction": direction, **m}


def recommend_money_flow_coins(
    processed_dir: Path, *, venues: tuple[str, ...] = DEFAULT_VENUES,
    timeframe: str = "15m", futures_only: bool = True, top_n: int = 10,
    lookback: int = 20,
) -> dict:
    """Rank datasets on the requested venues by money-flow direction.

    Returns both `top_inflow` and `top_outflow` — unlike ml/rl fitness this
    signal is two-sided, both directions are actionable (long inflow / short
    outflow, or simply avoid rotating *into* an outflow coin).
    """
    venues_l = {v.lower() for v in venues}
    best: dict[str, dict] = {}
    for path in sorted(Path(processed_dir).glob("*.parquet")):
        info = parse_stem(path.stem)
        if info["timeframe"] != timeframe:
            continue
        if info["exchange"].lower() not in venues_l:
            continue
        if futures_only and info["market"] not in {"futures", "perp", "perpetual", "um", "cm"}:
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        fit = money_flow_score(df, lookback=lookback)
        if fit.get("money_flow_score", 0) <= 0:
            continue
        row = {"exchange": info["exchange"], "symbol": info["symbol"],
               "market": info["market"], **fit}
        cur = best.get(info["symbol"])
        if cur is None or row["money_flow_score"] > cur["money_flow_score"]:
            best[info["symbol"]] = row
    rows = list(best.values())
    inflow = sorted((r for r in rows if r.get("direction") == "inflow"),
                     key=lambda r: r["money_flow_score"], reverse=True)
    outflow = sorted((r for r in rows if r.get("direction") == "outflow"),
                      key=lambda r: r["money_flow_score"], reverse=True)
    return {
        "timeframe": timeframe,
        "venues": sorted(venues_l),
        "n_evaluated": len(rows),
        "top_inflow": inflow[:top_n],
        "top_outflow": outflow[:top_n],
    }


def money_flow_multiplier(row: dict | None, *, max_adj: float = 0.15,
                           min_score: int = 35) -> float:
    """Bounded score multiplier from a money-flow row (±15%, weaker cap than
    realized-PnL feedback's ±25% since this is exploratory, not realized PnL).

    Below `min_score` or `direction == "neutral"` → 1.0 (no opinion).
    """
    if not row:
        return 1.0
    score = float(row.get("money_flow_score", 0))
    direction = row.get("direction", "neutral")
    if direction == "neutral" or score < min_score:
        return 1.0
    sign = 1.0 if direction == "inflow" else -1.0
    adj = sign * max_adj * min(score / 100.0, 1.0)
    return round(1.0 + adj, 4)


def apply_money_flow(
    table: dict[str, dict], mf: dict, quote: str = "USDT", **kw: Any,
) -> dict[str, dict]:
    """Adjust each base's score in-place by its money-flow multiplier.

    `mf` is the dict returned by `recommend_money_flow_coins` (top_inflow +
    top_outflow rows, keyed by full symbol e.g. "BTCUSDT"). Mirrors
    `selection_feedback.apply_feedback`'s in-place-adjust + audit-trail shape.
    """
    by_base = {}
    for row in (*mf.get("top_inflow", []), *mf.get("top_outflow", [])):
        sym = row["symbol"]
        if sym.endswith(quote):
            by_base[sym[: -len(quote)]] = row

    audit: dict[str, dict] = {}
    for base, v in table.items():
        mult = money_flow_multiplier(by_base.get(base), **kw)
        if mult == 1.0:
            continue
        old = v.get("score", 0)
        new = int(max(0, min(100, round(old * mult))))
        if new == old:
            continue
        v["score"] = new
        audit[base] = {"old": old, "new": new, "mult": mult,
                        "money_flow": by_base.get(base)}
    return audit
