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
            follower_ret = rets[cols[j]] if best_lag > 0 else rets[cols[i]]
            # rough expected move captured by mirroring the leader for `lag`
            # bars on the follower venue: |corr| * follower's bar-vol * sqrt(lag)
            vol_per_bar_pct = float(follower_ret.std()) * 100.0
            gap_pct = abs(best_corr) * vol_per_bar_pct * (abs(best_lag) ** 0.5)
            out.append({
                "a": cols[i], "b": cols[j], "best_lag": best_lag,
                "corr": round(best_corr, 3), "leader": leader,
                "gap_pct": round(gap_pct, 4),
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
                dev = float(spread.iloc[-1] - spread.mean())
                z = float(dev / (spread.std() + 1e-12))
                # % of capital the spread has to travel to revert to its mean,
                # expressed against the leg's own price so it's comparable to
                # the dislocation/basis numbers below.
                gap_pct = abs(dev) / float(y.iloc[-1]) * 100.0
            except Exception:
                continue
            out.append({
                "a": cols[i], "b": cols[j], "pvalue": round(float(pval), 4),
                "hedge_ratio": round(beta, 4), "spread_z": round(z, 2),
                "gap_pct": round(gap_pct, 4),
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
                "spot": a, "derivative": b, "kind": "perp_vs_spot",
                "basis_now_pct": round(float(spread.iloc[-1]), 4),
                "basis_mean_pct": round(float(spread.mean()), 4),
                "basis_std_pct": round(float(spread.std()), 4),
            })
    # No spot leg available (e.g. only futures venues downloaded): report the
    # cross-venue price dislocation HONESTLY as such — it is not a funding/carry
    # basis, so it must not be labelled perp-vs-spot.
    if not out:
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                spread = (prices[cols[j]] - prices[cols[i]]) / prices[cols[i]] * 100.0
                out.append({
                    "spot": cols[i], "derivative": cols[j], "kind": "cross_venue",
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


def _confidence(score: float, kind: str) -> str:
    """Map a raw score onto a human confidence tier (deliberately conservative —
    these are correlational signals, not guarantees)."""
    if kind == "stat_arb":
        return "high" if score >= 8 else "medium" if score >= 3 else "low"
    if kind == "lead_lag":
        return "high" if score >= 1.5 else "medium" if score >= 0.8 else "low"
    return "high" if score >= 5 else "medium" if score >= 2 else "low"  # dislocation


def _with_pnl_estimate(best: dict, capital: float = 1000.0) -> dict:
    """Attach a gross, pre-fee/funding/slippage PnL estimate for a market-
    neutral position sized at `capital` total notional (split across both legs).
    This is the % gap captured *if and when* the spread fully reverts — not a
    guarantee, and ignores fees, funding, slippage and the chance it never
    converges (or diverges further first)."""
    gap_pct = best.get("gap_pct", 0.0)
    best["est_pnl_usd"] = round(capital * gap_pct / 100.0, 2)
    best["confidence"] = _confidence(best["score"], best["type"])
    return best


def _opportunity_score(report: dict) -> dict:
    """Distil one symbol/tf report into a ranked, actionable opportunity.

    Picks the single best edge across the three families and emits a concrete
    trade construction so the section is no longer a dead-end read-out:
      • stat-arb : cointegrated pair with the largest |z| (mean-reversion entry)
      • lead-lag : strongest leader with a non-zero lag (latency follow)
      • dislocation: widest cross-venue basis vs its own std (convergence)
    """
    best: dict | None = None

    coint = [c for c in report.get("cointegration", []) if c.get("cointegrated")]
    if coint:
        c = max(coint, key=lambda d: abs(d.get("spread_z", 0)))
        z = c.get("spread_z", 0)
        if abs(z) >= 1.5:
            side = "short_spread" if z > 0 else "long_spread"
            best = {"type": "stat_arb", "score": round(abs(z), 2),
                    "pair": f"{c['a']} ↔ {c['b']}", "z": z, "pvalue": c["pvalue"],
                    "hedge_ratio": c["hedge_ratio"], "gap_pct": c.get("gap_pct", 0.0),
                    "action": f"{side}: {c['b']} − {c['hedge_ratio']}·{c['a']} (z={z:+.2f}, "
                              f"expect mean-reversion)"}

    for ll in report.get("lead_lag", []):
        if ll.get("best_lag", 0) != 0 and abs(ll.get("corr", 0)) >= 0.6:
            s = round(abs(ll["corr"]) * min(abs(ll["best_lag"]), 5), 2)
            if best is None or s > best["score"]:
                best = {"type": "lead_lag", "score": s, "pair": f"{ll['a']} ↔ {ll['b']}",
                        "leader": ll["leader"], "lag": ll["best_lag"], "corr": ll["corr"],
                        "gap_pct": ll.get("gap_pct", 0.0),
                        "action": f"follow {ll['leader']} (leads by {abs(ll['best_lag'])} bar, "
                                  f"corr={ll['corr']:.2f})"}
            break

    for b in report.get("basis", []):
        std = b.get("basis_std_pct", 0) or 0
        dev = abs(b.get("basis_now_pct", 0) - b.get("basis_mean_pct", 0))
        if std > 0 and dev / std >= 2.0:
            s = round(dev / std, 2)
            if best is None or s > best["score"]:
                best = {"type": "dislocation", "score": s,
                        "pair": f"{b['spot']} ↔ {b['derivative']}", "kind": b.get("kind"),
                        "now": b["basis_now_pct"], "mean": b["basis_mean_pct"],
                        "gap_pct": round(dev, 4),
                        "action": f"{b.get('kind','spread')} {dev/std:.1f}σ from mean "
                                  f"(now {b['basis_now_pct']:.2f}% vs {b['basis_mean_pct']:.2f}%)"}
            break

    return _with_pnl_estimate(best) if best else {}


def scan_all(processed_dir: Path, timeframe: str | None = None,
             max_bars: int = 4000) -> dict:
    """Auto-scan every symbol available on ≥2 venues and rank the best edges.

    This is the missing piece the Cross-Exchange section needed: instead of only
    answering for one hand-picked symbol, it surveys the whole multi-venue store
    and returns a leaderboard of concrete, ranked opportunities.
    """
    catalog = list_symbols(processed_dir)
    opps: list[dict] = []
    for sym, tfs in catalog.items():
        for tf in tfs:
            if timeframe and tf != timeframe:
                continue
            report = analyze_symbol(processed_dir, sym, tf, max_bars)
            if report.get("insufficient"):
                continue
            opp = _opportunity_score(report)
            if not opp:
                continue
            opp.update(symbol=sym, timeframe=tf, venues=report["venues"],
                       n_bars=report["n_bars"])
            opps.append(opp)
    opps.sort(key=lambda o: o.get("score", 0), reverse=True)
    return {"timeframe": timeframe, "n_scanned": len(opps),
            "opportunities": opps[:30]}


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
