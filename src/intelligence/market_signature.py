"""Market-effect signature of a time window (ccxt public data, cached per process).

Numeric fingerprint of what the market did over [t0, t1): BTC/ETH/SOL return, range,
both-leg whipsaw, volume ratio vs the trailing week, realised-vol z-score, vol-regime
flip, alt breadth, BTC open-interest change, funding, and (optionally) CoinGecko
market-cap flows («where did the money go»).

Consumers: the news→direction gate (src/intelligence/news_direction.py) and its fast
check (scripts/direction_fast_check.py) read `live_signature()` for their price triggers.
History: extracted 2026-09-23 from the retired incident/embargo module when the owner
removed the embargo and the portfolio-level risk layer; the data helpers were kept
because the news gate depends on them.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MAJORS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
LIVE_WINDOW_H = 6            # the live detector looks at the last 6h

_OHLCV_CACHE: dict[tuple, pd.DataFrame] = {}   # (venue, symbol) -> widest frame fetched
_OI_CACHE: dict[str, list] = {}
_FUND_CACHE: dict[str, list] = {}


_EX_CACHE: dict[str, Any] = {}


def _ex(venue: str = "bybit") -> Any:
    """One ccxt instance per venue per process (load_markets is ~3s; 18 symbols x 3s
    was the whole cold-start cost)."""
    ex = _EX_CACHE.get(venue)
    if ex is None:
        from src.execution.orderbook import make_exchange
        ex = make_exchange(venue)
        _EX_CACHE[venue] = ex
    return ex


def _fetch_ohlcv_1h(symbol: str, since: pd.Timestamp, until: pd.Timestamp, venue: str) -> pd.DataFrame:
    rows, cur = [], int(since.timestamp() * 1000)
    end_ms = int(until.timestamp() * 1000)
    ex = _ex(venue)
    for _ in range(8):
        chunk = ex.fetch_ohlcv(symbol, "1h", since=cur, limit=1000)
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1][0]
        if last >= end_ms or len(chunk) < 2:
            break
        cur = last + 3600_000
    if not rows:
        return pd.DataFrame(columns=["ts", "o", "h", "l", "c", "v", "qv"])
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).drop_duplicates("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["qv"] = df["v"] * df["c"]
    return df


def _ohlcv_1h(symbol: str, since: pd.Timestamp, until: pd.Timestamp, venue: str = "bybit") -> pd.DataFrame:
    """1h OHLCV covering [since, until]. One wide fetch per symbol per process; later
    calls slice the cached frame (the counterfactual scan asks ~25 overlapping windows)."""
    key = (venue, symbol)
    cached = _OHLCV_CACHE.get(key)
    if cached is None or cached.empty or cached["ts"].iloc[0] > since or cached["ts"].iloc[-1] < until - pd.Timedelta(hours=2):
        # fetch generously wide so backward-walking scans (counterfactual/background)
        # don't refetch every hour: 3 extra weeks before, up to now after
        lo = (since if cached is None or cached.empty else min(since, cached["ts"].iloc[0])) - pd.Timedelta(days=21)
        hi = max(until, pd.Timestamp.now(tz=UTC))
        try:
            cached = _fetch_ohlcv_1h(symbol, lo, hi, venue)
        except Exception as exc:
            log.warning("ohlcv %s %s: %s", venue, symbol, exc)
            cached = pd.DataFrame(columns=["ts", "o", "h", "l", "c", "v", "qv"])
        _OHLCV_CACHE[key] = cached
    if cached.empty:
        return cached
    return cached[(cached["ts"] >= since) & (cached["ts"] <= until)].reset_index(drop=True)


def _paged_history(fetch: Any, symbol: str, since: pd.Timestamp, step_ms: int, key: str,
                   extra_args: tuple = ()) -> list[tuple[pd.Timestamp, float]]:
    """Walk a bybit history endpoint forward from `since` (each call caps at 200)."""
    pts: dict[pd.Timestamp, float] = {}
    cur = int(since.timestamp() * 1000)
    end = int(pd.Timestamp.now(tz=UTC).timestamp() * 1000)
    for _ in range(40):
        rows = fetch(symbol, *extra_args, since=cur, limit=200)
        if not rows:
            break
        for x in rows:
            v = x.get(key)
            if v is not None:
                pts[pd.to_datetime(x["timestamp"], unit="ms", utc=True)] = float(v)
        last = max(int(x["timestamp"]) for x in rows)
        if last <= cur or last >= end - step_ms:
            break
        cur = last + step_ms
    return sorted(pts.items())


_HIST_COVER: dict[str, pd.Timestamp] = {}   # cache key -> earliest ts we tried to cover


def _hist(kind: str, symbol: str, since: pd.Timestamp) -> list[tuple[pd.Timestamp, float]]:
    """OI ('oi') or funding ('fund') history for symbol covering `since`..now, fetched
    once per process (paged) and never refetched for the same coverage; a scan that
    walks 14 days back must not hit the API once per hour."""
    cache = _OI_CACHE if kind == "oi" else _FUND_CACHE
    ck = f"{kind}:{symbol}"
    covered = _HIST_COVER.get(ck)
    if covered is None or since < covered - pd.Timedelta(hours=1):
        want = min(since, pd.Timestamp.now(tz=UTC) - pd.Timedelta(days=21))
        try:
            ex = _ex("bybit")
            if kind == "oi":
                pts = _paged_history(ex.fetch_open_interest_history, symbol, want, 3600_000,
                                     "openInterestAmount", ("1h",))
            else:
                pts = _paged_history(ex.fetch_funding_rate_history, symbol, want, 8 * 3600_000,
                                     "fundingRate")
        except Exception as exc:
            log.warning("%s history %s: %s", kind, symbol, exc)
            pts = cache.get(symbol) or []
        cache[symbol] = pts
        _HIST_COVER[ck] = want
    return cache.get(symbol) or []


def _oi_change_pct(symbol: str, t0: pd.Timestamp, t1: pd.Timestamp) -> float | None:
    try:
        pts = _hist("oi", symbol, t0 - pd.Timedelta(hours=1))
        sel = [(ts, a) for ts, a in pts if t0 - pd.Timedelta(hours=1) <= ts <= t1]
        if len(sel) < 2:
            return None
        return round((sel[-1][1] / sel[0][1] - 1.0) * 100, 3)
    except Exception:
        return None


def _funding_mean_pct(symbol: str, t0: pd.Timestamp, t1: pd.Timestamp) -> float | None:
    try:
        pts = _hist("fund", symbol, t0 - pd.Timedelta(hours=8))
        vals = [v for ts, v in pts if t0 - pd.Timedelta(hours=8) <= ts <= t1]
        return round(float(np.mean(vals)) * 100, 4) if vals else None
    except Exception:
        return None


def _coingecko_flows(t0: pd.Timestamp, t1: pd.Timestamp) -> dict:
    """Where did the money go? Market-cap paths for BTC, ETH and the two big stables
    (hourly, CoinGecko public). Stable mcap up while BTC/ETH mcap down = capital parked
    in stables (risk-off inside crypto); everything down = capital left crypto."""
    out: dict[str, Any] = {}
    try:
        import requests
        days = max(2, math.ceil((pd.Timestamp.now(tz=UTC) - t0).total_seconds() / 86400) + 1)
        days = min(days, 30)
        paths = {}
        for cid in ("bitcoin", "ethereum", "tether", "usd-coin"):
            r = requests.get(f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",
                             params={"vs_currency": "usd", "days": days}, timeout=20)
            if r.status_code != 200:
                continue
            mc = r.json().get("market_caps") or []
            s = pd.Series({pd.to_datetime(a, unit="ms", utc=True): float(b) for a, b in mc}).sort_index()
            if len(s):
                paths[cid] = s

        def _at(s: pd.Series, ts: pd.Timestamp) -> float | None:
            sub = s[s.index <= ts]
            return float(sub.iloc[-1]) if len(sub) else None

        for cid, s in paths.items():
            a, b = _at(s, t0), _at(s, t1)
            if a and b:
                out[f"{cid}_mcap_chg_pct"] = round((b / a - 1.0) * 100, 3)
                out[f"{cid}_mcap_chg_usd_bn"] = round((b - a) / 1e9, 2)
        if "bitcoin" in paths and "ethereum" in paths and "tether" in paths:
            stables = sum(out.get(f"{c}_mcap_chg_usd_bn", 0.0) for c in ("tether", "usd-coin"))
            risk = out.get("bitcoin_mcap_chg_usd_bn", 0.0) + out.get("ethereum_mcap_chg_usd_bn", 0.0)
            out["stables_net_usd_bn"] = round(stables, 2)
            out["btc_eth_net_usd_bn"] = round(risk, 2)
            if risk < 0 and stables > 0:
                out["flow_read"] = "risk-off inside crypto: BTC/ETH cap down, stable supply up (parked in stables)"
            elif risk < 0 and stables <= 0:
                out["flow_read"] = "capital left crypto: BTC/ETH cap down and stables did not absorb it"
            elif risk > 0:
                out["flow_read"] = "net inflow into BTC/ETH over the window"
            else:
                out["flow_read"] = "flat"
    except Exception as exc:
        out["error"] = str(exc)[:120]
    return out


def _window_features(df: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> dict | None:
    """Per-symbol window features from a 1h frame that also covers the 7d before t0."""
    if df.empty:
        return None
    w = df[(df["ts"] >= t0) & (df["ts"] < t1)]
    pre7 = df[(df["ts"] >= t0 - pd.Timedelta(days=7)) & (df["ts"] < t0)]
    pre24 = df[(df["ts"] >= t0 - pd.Timedelta(hours=24)) & (df["ts"] < t0)]
    if len(w) < 2 or len(pre7) < 24:
        return None
    o = float(w["o"].iloc[0])
    c = float(w["c"].iloc[-1])
    hi, lo = float(w["h"].max()), float(w["l"].min())
    ret = (c / o - 1.0) * 100
    rng = (hi - lo) / o * 100
    # both-leg travel: max drawdown from running peak + max run-up from running trough
    closes = w["c"].astype(float).to_numpy()
    path = np.concatenate([[o], closes])
    peak = np.maximum.accumulate(path)
    dd = float(((path / peak) - 1.0).min()) * 100
    trough = np.minimum.accumulate(path)
    ru = float(((path / trough) - 1.0).max()) * 100
    whipsaw = max(0.0, abs(dd) + ru - abs(ret))
    # volumes
    v_w = float(w["qv"].mean())
    v_7 = float(pre7["qv"].mean()) or 1e-9
    v_24 = float(pre24["qv"].mean()) if len(pre24) else v_7
    vol_ratio = v_w / v_7
    pre_ratio = v_24 / v_7
    # realised vol z: window std of hourly returns vs rolling same-length windows over pre7
    r = np.log(df["c"].astype(float)).diff()
    n = max(len(w), 2)
    roll = r[(df["ts"] < t0)].rolling(n).std().dropna()
    roll = roll.iloc[-24 * 7:] if len(roll) > 24 * 7 else roll
    rv = float(np.log(w["c"].astype(float)).diff().std())
    rv_z = float((rv - roll.mean()) / roll.std()) if len(roll) > 10 and roll.std() > 0 else 0.0
    return {"ret_pct": round(ret, 3), "range_pct": round(rng, 3), "maxdd_pct": round(dd, 3),
            "maxru_pct": round(ru, 3), "whipsaw_pct": round(whipsaw, 3),
            "vol_ratio": round(vol_ratio, 3), "pre24_vol_ratio": round(pre_ratio, 3),
            "rv_z": round(rv_z, 2), "n_bars": len(w)}


def market_signature(t0: pd.Timestamp, t1: pd.Timestamp, bases: list[str] | None = None,
                     *, with_flows: bool = True) -> dict:
    """Numeric fingerprint of the market over [t0, t1)."""
    t0 = pd.Timestamp(t0).tz_convert(UTC) if pd.Timestamp(t0).tzinfo else pd.Timestamp(t0, tz=UTC)
    t1 = pd.Timestamp(t1).tz_convert(UTC) if pd.Timestamp(t1).tzinfo else pd.Timestamp(t1, tz=UTC)
    since = t0 - pd.Timedelta(days=8)
    majors = {}
    for sym in MAJORS:
        f = _window_features(_ohlcv_1h(sym, since, t1), t0, t1)
        if f:
            majors[sym.split("/")[0]] = f
    sig: dict[str, Any] = {"t0": t0.isoformat(), "t1": t1.isoformat(),
                           "hours": round((t1 - t0).total_seconds() / 3600, 2), "majors": majors}
    if majors:
        def _avg(k: str) -> float:
            return round(float(np.mean([m[k] for m in majors.values()])), 3)
        btc = majors.get("BTC") or next(iter(majors.values()))
        sig.update({
            "btc_ret_pct": btc["ret_pct"], "btc_range_pct": btc["range_pct"],
            "btc_maxdd_pct": btc["maxdd_pct"], "btc_maxru_pct": btc["maxru_pct"],
            "whipsaw_pct": _avg("whipsaw_pct"), "vol_ratio": _avg("vol_ratio"),
            "pre24_vol_ratio": _avg("pre24_vol_ratio"), "rv_z": _avg("rv_z"),
        })
        sig["vol_regime_flip"] = round(sig["vol_ratio"] / max(sig["pre24_vol_ratio"], 0.05), 3)
    # alts the fleet was in
    alts = {}
    for b in (bases or [])[:15]:
        if b in ("BTC", "ETH", "SOL", "USDT", "USDC"):
            continue
        f = _window_features(_ohlcv_1h(f"{b}/USDT:USDT", since, t1), t0, t1)
        if f:
            alts[b] = f
    if alts:
        rets = [a["ret_pct"] for a in alts.values()]
        sig["alts"] = alts
        sig["alt_median_ret_pct"] = round(float(np.median(rets)), 3)
        sig["alt_down_share"] = round(float(np.mean([r < -2.0 for r in rets])), 3)
        sig["alt_whipsaw_pct"] = round(float(np.median([a["whipsaw_pct"] for a in alts.values()])), 3)
        sig["alt_vol_ratio"] = round(float(np.median([a["vol_ratio"] for a in alts.values()])), 3)
    else:
        sig["alt_down_share"] = 0.0
    oi = _oi_change_pct("BTC/USDT:USDT", t0, t1)
    sig["btc_oi_change_pct"] = oi
    sig["oi_change_abs_pct"] = abs(oi) if oi is not None else 0.0
    sig["btc_funding_mean_pct"] = _funding_mean_pct("BTC/USDT:USDT", t0, t1)
    if with_flows:
        sig["flows"] = _coingecko_flows(t0, t1)
    return sig


def live_signature(bases: list[str] | None = None, hours: int = LIVE_WINDOW_H) -> dict:
    now = pd.Timestamp.now(tz=UTC).floor("h")
    return market_signature(now - pd.Timedelta(hours=hours), now, bases, with_flows=False)
