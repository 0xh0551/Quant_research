"""Cross-exchange edge detection — the alpha the platform's name promises.

Operating on the multi-exchange Parquet store, this finds structural edges that
only exist *between* venues/instruments:

  • lead_lag        — which venue's returns lead another's (cross-correlation
                      argmax over small lags); a lead is exploitable latency alpha.
  • cointegration   — Engle-Granger test + hedge ratio for mean-reverting
                      spreads (stat-arb pairs across venues/symbols).
  • basis           — perp-vs-spot (or cross-venue) price gap; with funding this
                      is the classic cash-and-carry / funding-harvest edge.
  • liquidity       — comparative dollar volume, so you trade where you can fill.

Everything returns plain dicts for the dashboard's Cross-Exchange section.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_TF_TOKENS = {"1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "1d"}
_MARKET_TOKENS = {"futures", "perp", "perpetual", "spot", "um", "cm"}


def parse_stem(stem: str) -> dict[str, str]:
    """'bybit_futures_BTCUSDT_15m' → {exchange, market, symbol, timeframe}."""
    parts = stem.split("_")
    timeframe = parts[-1] if parts[-1] in _TF_TOKENS else "?"
    core = parts[:-1] if timeframe != "?" else parts
    exchange = core[0] if core else "unknown"
    rest = core[1:]
    market = "spot"
    if rest and rest[0].lower() in _MARKET_TOKENS:
        market = rest[0].lower()
        rest = rest[1:]
    symbol = "_".join(rest)
    return {"exchange": exchange, "market": market, "symbol": symbol, "timeframe": timeframe}


def _load_aligned(
    processed_dir: Path, symbol: str, timeframe: str, max_bars: int = 4000,
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Aligned close-price frame across every (exchange, market) for one symbol/tf."""
    series: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    vol: dict[str, pd.Series] = {}
    for path in sorted(Path(processed_dir).glob("*.parquet")):
        info = parse_stem(path.stem)
        if info["symbol"] != symbol or info["timeframe"] != timeframe:
            continue
        df = pd.read_parquet(path)
        if "timestamp" not in df.columns or len(df) < 200:
            continue
        df = df.sort_values("timestamp").tail(max_bars)
        key = f"{info['exchange']}:{info['market']}"
        s = df.set_index("timestamp")["close"]
        series[key] = s
        meta[key] = {**info, "rows": len(df)}
        if "volume" in df.columns:
            vol[key] = df.set_index("timestamp")["close"] * df.set_index("timestamp")["volume"]
    if not series:
        return pd.DataFrame(), {}
    prices = pd.DataFrame(series).dropna(how="all").ffill().dropna()
    for key in meta:
        if key in vol:
            v = vol[key].reindex(prices.index)
            meta[key]["dollar_volume"] = round(float(v.mean()), 2) if len(v) else 0.0
    return prices, meta


def lead_lag(prices: pd.DataFrame, max_lag: int = 5) -> list[dict]:
    """Cross-correlation lead-lag for each venue pair (positive lag → col A leads B)."""
    rets = prices.pct_change().dropna()
    cols = list(rets.columns)
    out: list[dict] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = rets[cols[i]], rets[cols[j]]
            best_lag, best_corr = 0, 0.0
            for lag in range(-max_lag, max_lag + 1):
                c = a.corr(b.shift(-lag))
                if pd.notna(c) and abs(c) > abs(best_corr):
                    best_corr, best_lag = float(c), lag
            leader = cols[i] if best_lag > 0 else (cols[j] if best_lag < 0 else "—")
            out.append({
                "a": cols[i], "b": cols[j], "best_lag": best_lag,
                "corr": round(best_corr, 3), "leader": leader,
            })
    return sorted(out, key=lambda x: abs(x["best_lag"]) * abs(x["corr"]), reverse=True)


def cointegration(prices: pd.DataFrame, pvalue_max: float = 0.05) -> list[dict]:
    """Engle-Granger cointegration + OLS hedge ratio for each venue pair."""
    try:
        from statsmodels.tsa.stattools import coint
    except Exception:
        return []
    cols = list(prices.columns)
    out: list[dict] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            x, y = prices[cols[i]], prices[cols[j]]
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    _, pval, _ = coint(x, y)
                beta = float(np.polyfit(x, y, 1)[0])
                spread = y - beta * x
                z = float((spread.iloc[-1] - spread.mean()) / (spread.std() + 1e-12))
            except Exception:
                continue
            out.append({
                "a": cols[i], "b": cols[j], "pvalue": round(float(pval), 4),
                "hedge_ratio": round(beta, 4), "spread_z": round(z, 2),
                "cointegrated": bool(pval < pvalue_max),
            })
    return sorted(out, key=lambda d: d["pvalue"])


def basis(prices: pd.DataFrame, meta: dict[str, dict]) -> list[dict]:
    """Perp-vs-spot (and cross-venue) price basis = (B − A)/A, in %."""
    cols = list(prices.columns)
    out: list[dict] = []
    for i in range(len(cols)):
        for j in range(len(cols)):
            if i == j:
                continue
            a, b = cols[i], cols[j]
            ma, mb = meta.get(a, {}), meta.get(b, {})
            # prefer spot(a) vs derivative(b)
            if not (ma.get("market") == "spot" and mb.get("market") in {"futures", "perp", "perpetual", "um", "cm"}):
                continue
            spread = (prices[b] - prices[a]) / prices[a] * 100.0
            out.append({
                "spot": a, "derivative": b,
                "basis_now_pct": round(float(spread.iloc[-1]), 4),
                "basis_mean_pct": round(float(spread.mean()), 4),
                "basis_std_pct": round(float(spread.std()), 4),
            })
    # also cross-venue spot/spot dislocations
    if not out:
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                spread = (prices[cols[j]] - prices[cols[i]]) / prices[cols[i]] * 100.0
                out.append({
                    "spot": cols[i], "derivative": cols[j],
                    "basis_now_pct": round(float(spread.iloc[-1]), 4),
                    "basis_mean_pct": round(float(spread.mean()), 4),
                    "basis_std_pct": round(float(spread.std()), 4),
                })
    return out


def analyze_symbol(processed_dir: Path, symbol: str, timeframe: str, max_bars: int = 4000) -> dict:
    """Full cross-exchange report for one symbol/timeframe."""
    prices, meta = _load_aligned(processed_dir, symbol, timeframe, max_bars)
    if prices.shape[1] < 2:
        return {"symbol": symbol, "timeframe": timeframe, "venues": list(meta.keys()),
                "n_venues": prices.shape[1], "insufficient": True}
    liquidity = sorted(
        ({"venue": k, "dollar_volume": v.get("dollar_volume", 0.0)} for k, v in meta.items()),
        key=lambda d: d["dollar_volume"], reverse=True,
    )
    return {
        "symbol": symbol, "timeframe": timeframe,
        "venues": list(prices.columns), "n_venues": int(prices.shape[1]),
        "n_bars": int(prices.shape[0]),
        "lead_lag": lead_lag(prices)[:10],
        "cointegration": cointegration(prices)[:10],
        "basis": basis(prices, meta)[:10],
        "liquidity": liquidity,
        "insufficient": False,
    }


def list_symbols(processed_dir: Path) -> dict[str, dict]:
    """Symbols available on ≥2 venues per timeframe (cross-exchange candidates)."""
    catalog: dict[tuple[str, str], set[str]] = {}
    for path in sorted(Path(processed_dir).glob("*.parquet")):
        info = parse_stem(path.stem)
        if info["timeframe"] == "?":
            continue
        catalog.setdefault((info["symbol"], info["timeframe"]), set()).add(f"{info['exchange']}:{info['market']}")
    out: dict[str, dict] = {}
    for (sym, tf), venues in catalog.items():
        if len(venues) >= 2:
            out.setdefault(sym, {})[tf] = sorted(venues)
    return out
