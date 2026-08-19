"""Incident learning: fleet loss cluster -> market-effect signature -> embargo rule.

The owner's ask (2026-08-17): the fleet lost heavily *together*; the strategist
should look back, find what happened (news), tie it to the bots' behaviour, measure
the market effect with our own data (volume leaving, OI, vol, whipsaw, where the money
went), classify the root cause, simulate how much would have been saved had an
embargo been in force, and LEARN — so that next time the *market effect* looks the
same (not the headline — the effect), new organic entries stop for a while and only
the activity-floor trades go through at maximum size reduction.

We learn from the market's fingerprint, never from the headline. A headline is one
event; the fingerprint (volume regime flip, both-side stop-out, OI purge, stable
inflow) recurs.

Pieces
------
  fleet_trades(since)              closed trades across all bots (freqtrade sqlite, ro)
  detect_incidents(trades)         fleet-wide loss clusters (z-score vs trailing + >=2 bots)
  market_signature(t0, t1)         numeric fingerprint of the market over a window
  bot_impact(trades, t0, t1)       who lost what, long-vs-short, leverage
  learn_rule(signature, impact)    per-incident thresholds + embargo strength/TTL
  counterfactual(...)              earliest hour the rule would have fired; $ saved
  explain_incident(...)            Claude + web_search: cause class, narrative, sources
  live_signature() / match_live()  hourly recurrence detector -> embargo payload

Statistical honesty (platform rule): a rule learned from n=1 incident is one data
point. It is applied (the owner wants action) but every embargo is logged and scored
after its TTL, and the memory carries `n_incidents` so nobody mistakes it for a law.

Read-only on bot DBs and market data. Writes ONLY under outputs/:
  incident_memory.json, embargo_state.json, embargo_log.jsonl
and (via event_risk.build) the `global.embargo` block of event_risk.json.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src import local_config

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
MEMORY = OUT / "incident_memory.json"
EMBARGO_STATE = OUT / "embargo_state.json"
EMBARGO_LOG = OUT / "embargo_log.jsonl"

UTC = timezone.utc
MAJORS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
LIVE_WINDOW_H = 6            # the recurrence detector looks at the last 6h
DETECT_BUCKET_H = 4          # incident detection bucket
DETECT_LOOKBACK_D = 30       # trailing distribution for the z-score
DETECT_Z = 2.5
DETECT_MIN_BOTS = 2          # fleet-wide = at least 2 bots losing
DETECT_MIN_LOSS_FRAC = 0.005 # and at least 0.5% of fleet equity in one bucket
MERGE_GAP_BUCKETS = 1        # buckets with a single quiet bucket between them merge
RULE_RELAX = 0.75            # live must reach 75% of the incident's feature level
RULE_MIN_HITS = 2            # on at least 2 key features
TTL_MIN_H, TTL_MAX_H = 6.0, 48.0
FLOOR_MULT_MIN = 0.10        # "maximum reduction" for floor trades never below 0.1
DEFAULT_WALLET = 1000.0

# key features and the direction that means "stress" (+1: bigger is worse)
# MIN_NOTABLE: an incident feature below this level is ordinary market noise and
# teaches nothing — it is left out of the learned rule (otherwise a threshold like
# alt_down_share>=0.06 would fire on any quiet afternoon).
MIN_NOTABLE = {"vol_ratio": 1.3, "rv_z": 1.0, "whipsaw_pct": 1.0, "btc_range_pct": 1.0,
               "alt_down_share": 0.3, "oi_change_abs_pct": 3.0, "vol_regime_flip": 2.0}
RELAX_LADDER = (0.95, 0.9, 0.85, 0.8, 0.75)   # calibrate_rule tries tight -> loose
MAX_FALSE_ALARM = 0.08                        # <= 8% of ordinary hours may match
# قانون مالک 2026-08-19: جهشِ قیمت به‌خودی‌خود فرصت است نه خطر — امبارگو فقط وقتی
# مجاز است که ناوگان واقعاً در حال خون‌ریزی باشد (اج‌ها کار نمی‌کنند). امضای بازار
# شرطِ لازم است، نه کافی؛ شرطِ دوم: ضررِ بسته‌شده‌ی ناوگان در پنجره‌ی اخیر.
ARM_WINDOW_H = 6             # bleeding lookback for arming
ARM_LOSS_FRAC = 0.004        # trailing fleet closed-PnL <= -0.4% of equity ...
ARM_MIN_BOTS = 2             # ... with >=2 bots negative in that window
KEY_FEATURES = {
    "vol_ratio": +1,        # window volume / trailing-7d hourly mean (majors)
    "rv_z": +1,             # realised vol z-score vs 7d rolling windows
    "whipsaw_pct": +1,      # both-leg travel beyond net move (majors avg)
    "btc_range_pct": +1,    # (high-low)/open over the window
    "alt_down_share": +1,   # share of fleet bases down >2% in window
    "oi_change_abs_pct": +1,# |OI change| BTC (purge or pile-in)
    "vol_regime_flip": +1,  # window vol_ratio / pre-24h vol_ratio (dead -> loud)
}


# --------------------------------------------------------------------------- #
# fleet trades
# --------------------------------------------------------------------------- #
def _bot_dbs() -> dict[str, Path]:
    dbs = local_config.bot_databases()
    if dbs:
        return dbs
    ud = local_config.user_data_dir()
    if ud is None:
        return {}
    names = {"Bender": "bender", "Gadget": "gadget", "Klaymen": "klaymen", "Popeye": "popeye",
             "Mickey": "mickey", "Wall_E": "walle", "Gort": "gort"}
    return {b: ud / f"{f}.sqlite" for b, f in names.items() if (ud / f"{f}.sqlite").exists()}


def fleet_equity() -> float:
    """Sum of the bots' dry_run_wallet (paper fleet) — the denominator for severity."""
    ud = local_config.user_data_dir()
    total, n = 0.0, 0
    if ud is not None:
        cfgs = {"Bender": "bender_config.json", "Gadget": "gadget_config.json",
                "Klaymen": "klaymen_config.json", "Popeye": "popeye_config.json",
                "Mickey": "mickey_config.json", "Wall_E": "walle_config.json",
                "Gort": "gort_config.json"}
        for bot in _bot_dbs():
            p = ud / cfgs.get(bot, "")
            try:
                w = float(json.loads(p.read_text()).get("dry_run_wallet", DEFAULT_WALLET))
            except Exception:
                w = DEFAULT_WALLET
            total += w
            n += 1
    return total if n else DEFAULT_WALLET * 7


def fleet_trades(since: datetime, until: datetime | None = None) -> pd.DataFrame:
    """Closed trades across bots. Columns: bot, pair, base, is_short, open_date,
    close_date, pnl, exit_reason, leverage, stake, enter_tag (tz-aware UTC)."""
    frames = []
    s = since.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    for bot, db in _bot_dbs().items():
        if not Path(db).exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            df = pd.read_sql_query(
                "SELECT pair, is_short, open_date, close_date, close_profit_abs AS pnl, "
                "exit_reason, leverage, stake_amount AS stake, enter_tag, "
                "open_rate, max_rate, min_rate "
                "FROM trades WHERE is_open=0 AND close_date IS NOT NULL AND close_date >= ?",
                con, params=(s,))
            con.close()
        except Exception as exc:
            log.warning("fleet_trades %s: %s", bot, exc)
            continue
        if df.empty:
            continue
        df["bot"] = bot
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["bot", "pair", "base", "is_short", "open_date", "close_date",
                                     "pnl", "exit_reason", "leverage", "stake", "enter_tag"])
    t = pd.concat(frames, ignore_index=True)
    for c in ("open_date", "close_date"):
        t[c] = pd.to_datetime(t[c], utc=True, errors="coerce")
    t["pnl"] = pd.to_numeric(t["pnl"], errors="coerce").fillna(0.0)
    t["is_short"] = t["is_short"].astype(bool)
    t["base"] = t["pair"].astype(str).str.split("/").str[0].str.upper()
    # MFE در فضای قیمت (برای شاهدِ whipsaw: بازنده‌هایی که اول در سود بودند)
    try:
        o = pd.to_numeric(t["open_rate"], errors="coerce")
        mx = pd.to_numeric(t["max_rate"], errors="coerce")
        mn = pd.to_numeric(t["min_rate"], errors="coerce")
        t["mfe"] = np.where(t["is_short"], 1 - mn / o, mx / o - 1)
        t["mfe"] = pd.to_numeric(t["mfe"], errors="coerce").clip(lower=0).fillna(0.0)
    except Exception:
        t["mfe"] = 0.0
    if until is not None:
        u = pd.Timestamp(until)
        u = u.tz_convert(UTC) if u.tzinfo else u.tz_localize(UTC)
        t = t[t["close_date"] <= u]
    return t.dropna(subset=["close_date"]).sort_values("close_date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# incident detection
# --------------------------------------------------------------------------- #
def detect_incidents(trades: pd.DataFrame, *, equity: float | None = None,
                     bucket_h: int = DETECT_BUCKET_H, z: float = DETECT_Z,
                     min_bots: int = DETECT_MIN_BOTS, min_loss_frac: float = DETECT_MIN_LOSS_FRAC,
                     recent_days: float | None = None) -> list[dict]:
    """Fleet-wide loss clusters. A bucket is an incident candidate when its closed
    PnL is < min(mu - z*sd of trailing buckets, -min_loss_frac*equity) AND >= min_bots
    lost money in it. Adjacent candidates (gap <= MERGE_GAP_BUCKETS) merge."""
    if trades.empty:
        return []
    eq = float(equity or fleet_equity())
    t = trades.copy()
    t["bucket"] = t["close_date"].dt.floor(f"{bucket_h}h")
    g = t.groupby("bucket")
    pnl = g["pnl"].sum()
    # trailing distribution: complete range of buckets (zeros for quiet buckets)
    idx = pd.date_range(pnl.index.min(), pnl.index.max(), freq=f"{bucket_h}h", tz=UTC)
    pnl = pnl.reindex(idx, fill_value=0.0)
    mu, sd = float(pnl.mean()), float(pnl.std(ddof=0) or 0.0)
    thr = min(mu - z * sd, -min_loss_frac * eq)
    per_bot_bucket = t.groupby(["bucket", "bot"])["pnl"].sum()
    losing_bots = (per_bot_bucket < 0).groupby(level=0).sum()
    cands = [b for b, v in pnl.items()
             if v < thr and int(losing_bots.get(b, 0)) >= min_bots]
    if recent_days:
        cutoff = pd.Timestamp.now(tz=UTC) - pd.Timedelta(days=recent_days)
        cands = [b for b in cands if b >= cutoff]
    if not cands:
        return []
    # merge
    step = pd.Timedelta(hours=bucket_h)
    groups: list[list[pd.Timestamp]] = [[cands[0]]]
    for b in cands[1:]:
        if (b - groups[-1][-1]) <= step * (MERGE_GAP_BUCKETS + 1):
            groups[-1].append(b)
        else:
            groups.append([b])
    out = []
    for grp in groups:
        t0, t1 = grp[0], grp[-1] + step
        w = t[(t["close_date"] >= t0) & (t["close_date"] < t1)]
        per_bot = w.groupby("bot")["pnl"].sum().round(2).to_dict()
        out.append({
            "id": t0.strftime("%Y%m%dT%H") + "Z",
            "start": t0.isoformat(),
            "end": t1.isoformat(),
            "hours": float((t1 - t0).total_seconds() / 3600),
            "fleet_pnl": round(float(w["pnl"].sum()), 2),
            "severity": round(float(-w["pnl"].sum()) / eq, 5),
            "n_trades": int(len(w)),
            "n_bots_losing": int(sum(1 for v in per_bot.values() if v < 0)),
            "per_bot": per_bot,
            "threshold": round(thr, 2),
            "baseline": {"mu": round(mu, 2), "sd": round(sd, 2), "buckets": int(len(pnl))},
        })
    return out


def bot_impact(trades: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> dict:
    w = trades[(trades["close_date"] >= t0) & (trades["close_date"] < t1)]
    if w.empty:
        return {"n_trades": 0}
    long_pnl = float(w.loc[~w["is_short"], "pnl"].sum())
    short_pnl = float(w.loc[w["is_short"], "pnl"].sum())
    worst = w.nsmallest(5, "pnl")
    lev = pd.to_numeric(w["leverage"], errors="coerce").fillna(1.0)
    losers = w[w["pnl"] < 0]
    in_profit_first = losers[losers.get("mfe", 0) >= 0.005] if "mfe" in w.columns else losers.iloc[0:0]
    return {
        "n_trades": int(len(w)),
        "fleet_pnl": round(float(w["pnl"].sum()), 2),
        "long_pnl": round(long_pnl, 2),
        "short_pnl": round(short_pnl, 2),
        "both_sides_lost": bool(long_pnl < 0 and short_pnl < 0),
        # شاهدِ whipsaw از آنالیتیکس (2026-08-19): چند درصدِ بازنده‌ها اول ≥0.5% در سود بودند؟
        "losers_in_profit_first_share": round(float(len(in_profit_first) / len(losers)), 3) if len(losers) else None,
        "losers_in_profit_first_usd": round(float(in_profit_first["pnl"].sum()), 2) if len(losers) else 0.0,
        "losers_median_mfe_pct": round(float(losers["mfe"].median() * 100), 3) if len(losers) and "mfe" in w.columns else None,
        "per_bot": w.groupby("bot")["pnl"].sum().round(2).to_dict(),
        "per_base": w.groupby("base")["pnl"].sum().round(2).sort_values().head(8).to_dict(),
        "exit_reasons": w.groupby("exit_reason")["pnl"].sum().round(2).to_dict(),
        "lev_weighted_avg": round(float((lev * w["pnl"].abs()).sum() / max(w["pnl"].abs().sum(), 1e-9)), 2),
        "floor_trades_pnl": round(float(w.loc[w["enter_tag"] == "activity_floor", "pnl"].sum()), 2),
        "worst": [{"bot": r.bot, "pair": r.pair, "side": "short" if r.is_short else "long",
                   "pnl": round(float(r.pnl), 2), "exit": r.exit_reason,
                   "lev": float(r.leverage or 1), "opened": r.open_date.isoformat(),
                   "closed": r.close_date.isoformat()} for r in worst.itertuples()],
        "bases": sorted(w["base"].unique().tolist()),
    }


def fleet_bleeding(trades: pd.DataFrame | None = None, at: pd.Timestamp | None = None,
                   *, window_h: int = ARM_WINDOW_H, equity: float | None = None) -> tuple[bool, dict]:
    """Is the fleet actually LOSING right now? (closed PnL over the trailing window.)

    Owner rule (2026-08-19): a price jump alone is opportunity, not danger — the
    embargo may only arm when the fingerprint matches AND this returns True
    (edges demonstrably not working). Uses closed trades only (honest, realised)."""
    at = pd.Timestamp(at) if at is not None else pd.Timestamp.now(tz=UTC)
    if at.tzinfo is None:
        at = at.tz_localize(UTC)
    t0 = at - pd.Timedelta(hours=window_h)
    if trades is None:
        trades = fleet_trades(t0.to_pydatetime() - timedelta(hours=1), at.to_pydatetime())
    w = trades[(trades["close_date"] >= t0) & (trades["close_date"] < at)]
    eq = float(equity or fleet_equity())
    pnl = float(w["pnl"].sum())
    n_neg = int((w.groupby("bot")["pnl"].sum() < 0).sum()) if len(w) else 0
    bleeding = (pnl <= -ARM_LOSS_FRAC * eq) and (n_neg >= ARM_MIN_BOTS)
    return bleeding, {"window_h": window_h, "pnl": round(pnl, 2), "n_trades": int(len(w)),
                      "bots_negative": n_neg, "threshold": round(-ARM_LOSS_FRAC * eq, 2)}


# --------------------------------------------------------------------------- #
# market data (ccxt public, fresh) — cached per process
# --------------------------------------------------------------------------- #
_OHLCV_CACHE: dict[tuple, pd.DataFrame] = {}   # (venue, symbol) -> widest frame fetched
_OI_CACHE: dict[str, list] = {}
_FUND_CACHE: dict[str, list] = {}


_EX_CACHE: dict[str, Any] = {}


def _ex(venue: str = "bybit"):
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


def _paged_history(fetch, symbol: str, since: pd.Timestamp, step_ms: int, key: str,
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
        days = max(2, int(math.ceil((pd.Timestamp.now(tz=UTC) - t0).total_seconds() / 86400)) + 1)
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
            "rv_z": round(rv_z, 2), "n_bars": int(len(w))}


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
        def _avg(k):
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


# --------------------------------------------------------------------------- #
# learning: rule + counterfactual
# --------------------------------------------------------------------------- #
def learn_rule(sig: dict, severity: float, hours: float, relax: float = RULE_RELAX) -> dict:
    """Thresholds this incident teaches, plus how hard/long to embargo on recurrence.

    strength: 0.3..1.0 from severity (fleet loss / equity; 1% loss = full strength).
    floor_mult: stake multiplier for the *activity-floor* trades under embargo
                ("maximum reduction"): 1 - 0.9*strength, never below FLOOR_MULT_MIN.
    ttl_h:      1.5x the incident's duration, clamped 6..48h.
    """
    thr = {}
    for k in KEY_FEATURES:
        v = sig.get(k)
        if v is None or not np.isfinite(v) or float(v) < MIN_NOTABLE.get(k, 0.0):
            continue
        thr[k] = round(float(v) * relax, 4)
    strength = float(np.clip(severity / 0.01, 0.3, 1.0))
    return {
        "thresholds": thr,
        "relax": relax,
        "min_hits": RULE_MIN_HITS,
        "strength": round(strength, 3),
        "floor_mult": round(max(FLOOR_MULT_MIN, 1.0 - 0.9 * strength), 3),
        "ttl_h": float(np.clip(1.5 * hours, TTL_MIN_H, TTL_MAX_H)),
    }


def rule_hits(rule: dict, sig: dict) -> tuple[int, list[str]]:
    hits = []
    for k, thr in (rule.get("thresholds") or {}).items():
        v = sig.get(k)
        if v is None:
            continue
        # a threshold that is itself ~0 carries no information — skip it
        if abs(thr) < 1e-6:
            continue
        if KEY_FEATURES.get(k, 1) > 0 and float(v) >= thr:
            hits.append(f"{k}={float(v):.2f}≥{thr:.2f}")
    return len(hits), hits


def counterfactual(trades: pd.DataFrame, rule: dict, t0: pd.Timestamp, t1: pd.Timestamp,
                   bases: list[str], *, scan_back_h: int = 12) -> dict:
    """Had this rule been live, when would it have fired and what would it have saved?

    Scans hour by hour from t0-scan_back_h to t1 with the same LIVE_WINDOW_H rolling
    signature the detector uses (majors + alts, no flows). The first hour with
    >= min_hits is the embargo start; embargo lasts ttl_h. Saved = -(PnL of ORGANIC
    trades opened during the embargo). Floor trades are kept (they'd still open, at
    floor_mult size -> their PnL is scaled by floor_mult). Foregone gains are reported
    honestly (positive organic PnL blocked counts against).
    """
    t0 = pd.Timestamp(t0); t1 = pd.Timestamp(t1)
    fired_at, hits_at, bleed_at = None, [], {}
    for h in range(-scan_back_h, int((t1 - t0).total_seconds() // 3600) + 1):
        end = t0 + pd.Timedelta(hours=h)
        bleeding, bstats = fleet_bleeding(trades, end)
        if not bleeding:      # قانون مالک: بدون خون‌ریزیِ واقعی، امضا هرچه باشد امبارگو نه
            continue
        sig = market_signature(end - pd.Timedelta(hours=LIVE_WINDOW_H), end, bases, with_flows=False)
        n, hits = rule_hits(rule, sig)
        if n >= int(rule.get("min_hits", RULE_MIN_HITS)):
            fired_at, hits_at, bleed_at = end, hits, bstats
            break
    if fired_at is None:
        return {"fired": False, "note": "fingerprint+bleeding never coincided before/within the "
                                       "window — no embargo, no saving"}
    e_end = fired_at + pd.Timedelta(hours=float(rule.get("ttl_h", TTL_MIN_H)))
    opened = trades[(trades["open_date"] >= fired_at) & (trades["open_date"] < e_end)]
    organic = opened[opened["enter_tag"] != "activity_floor"]
    floor = opened[opened["enter_tag"] == "activity_floor"]
    saved = -float(organic["pnl"].sum())
    fm = float(rule.get("floor_mult", 1.0))
    floor_saved = -float(floor["pnl"].sum()) * (1.0 - fm)
    lead_h = round((t0 - fired_at).total_seconds() / 3600, 1)
    return {
        "fired": True, "fired_at": fired_at.isoformat(), "embargo_until": e_end.isoformat(),
        "lead_hours_before_losses": lead_h, "hits": hits_at, "bleeding_at_fire": bleed_at,
        "organic_trades_blocked": int(len(organic)),
        "organic_blocked_pnl": round(float(organic["pnl"].sum()), 2),
        "organic_blocked_losers": round(float(organic.loc[organic["pnl"] < 0, "pnl"].sum()), 2),
        "organic_blocked_winners": round(float(organic.loc[organic["pnl"] > 0, "pnl"].sum()), 2),
        "floor_trades": int(len(floor)), "floor_pnl": round(float(floor["pnl"].sum()), 2),
        "saved_usd": round(saved + floor_saved, 2),
        "per_bot_saved": (-organic.groupby("bot")["pnl"].sum()).round(2).to_dict(),
    }


def background_match_rate(rule: dict, bases: list[str], end: pd.Timestamp, *, days: int = 14,
                          exclude: tuple | None = None, trades: pd.DataFrame | None = None) -> dict:
    """How often would the FULL trigger (fingerprint match AND fleet bleeding) fire on
    ORDINARY hours? Scans hourly over the trailing `days` (excluding the incident span).
    Also reports the fingerprint-only rate so the two gates stay separately visible."""
    end = pd.Timestamp(end).floor("h")
    n_hit, n_sig, n_tot, hit_hours = 0, 0, 0, []
    for h in range(days * 24):
        e = end - pd.Timedelta(hours=h)
        if exclude and exclude[0] <= e <= exclude[1]:
            continue
        sig = market_signature(e - pd.Timedelta(hours=LIVE_WINDOW_H), e, bases, with_flows=False)
        if not sig.get("majors"):
            continue
        n_tot += 1
        n, _ = rule_hits(rule, sig)
        if n < int(rule.get("min_hits", RULE_MIN_HITS)):
            continue
        n_sig += 1
        if trades is not None and not fleet_bleeding(trades, e)[0]:
            continue
        n_hit += 1
        hit_hours.append(e.isoformat())
    return {"days": days, "hours_scanned": n_tot, "hours_matched": n_hit,
            "rate": round(n_hit / n_tot, 4) if n_tot else None,
            "fingerprint_only_rate": round(n_sig / n_tot, 4) if n_tot else None,
            "sample_hits": hit_hours[:6]}


def calibrate_rule(sig: dict, severity: float, hours: float, trades: pd.DataFrame,
                   t0: pd.Timestamp, t1: pd.Timestamp, bases: list[str]) -> tuple[dict, dict, dict]:
    """Walk the relax ladder (tight -> loose). Every rung is scored on two honest
    numbers: what it would have SAVED on this incident (counterfactual) and how often
    it fires on ORDINARY hours (background false-alarm rate). Choose the rung with the
    largest saving among those with false-alarm <= MAX_FALSE_ALARM; ties -> tighter.
    Fallbacks (flagged in rule.calibration.status): loosest rung that fires at all,
    else the tightest rung. The whole ladder is kept in rule.ladder for the record."""
    exclude = (pd.Timestamp(t0) - pd.Timedelta(hours=12), pd.Timestamp(t1) + pd.Timedelta(hours=TTL_MAX_H))
    tried = []
    for relax in RELAX_LADDER:
        rule = learn_rule(sig, severity, hours, relax)
        if not rule["thresholds"]:
            break
        cf = counterfactual(trades, rule, t0, t1, bases)
        bg = background_match_rate(rule, bases, t0, exclude=exclude, trades=trades)
        tried.append((rule, cf, bg))
    if not tried:
        rule = learn_rule(sig, severity, hours)
        rule["calibration"] = {"status": "no_notable_features", "false_alarm_rate": None}
        return rule, {"fired": False, "note": "no notable feature to learn from"}, {}
    ladder = [{"relax": r["relax"], "fired": bool(c.get("fired")), "fired_at": c.get("fired_at"),
               "saved_usd": c.get("saved_usd"), "false_alarm_rate": g.get("rate")} for r, c, g in tried]
    ok = [(r, c, g) for r, c, g in tried
          if c.get("fired") and g.get("rate") is not None and g["rate"] <= MAX_FALSE_ALARM]
    if ok:
        rule, cf, bg = max(ok, key=lambda x: (float(x[1].get("saved_usd") or 0.0), x[0]["relax"]))
        status = "ok"
    else:
        fired = [t for t in tried if t[1].get("fired")]
        if fired:
            rule, cf, bg = fired[-1]
            status = "fires_but_noisy"
        else:
            rule, cf, bg = tried[0]
            status = "never_fires_early"
    rule["calibration"] = {"status": status, "false_alarm_rate": bg.get("rate"),
                           "max_false_alarm": MAX_FALSE_ALARM, "tried": len(tried)}
    rule["ladder"] = ladder
    return rule, cf, bg


# --------------------------------------------------------------------------- #
# Claude + web_search: root cause + money flow narrative
# --------------------------------------------------------------------------- #
CAUSE_CLASSES = ["macro_policy", "geopolitical", "regulatory_legal", "exchange_incident",
                 "liquidation_cascade", "token_specific", "low_liquidity_whipsaw",
                 "scheduled_data_release", "unknown"]

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "cause_class": {"type": "string", "enum": CAUSE_CLASSES},
        "cause_confidence": {"type": "number"},
        "headline": {"type": "string"},
        "what_happened": {"type": "string"},
        "link_to_bot_losses": {"type": "string"},
        "money_flow": {"type": "string"},
        "market_effect_tags": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
        "researched": {"type": "boolean"},
    },
    "required": ["cause_class", "cause_confidence", "headline", "what_happened",
                 "link_to_bot_losses", "money_flow", "market_effect_tags", "sources", "researched"],
    "additionalProperties": False,
}


def explain_incident(inc: dict, sig: dict, impact: dict, *, tier: str = "smart",
                     max_uses: int = 6) -> dict | None:
    """Ask Claude (with web_search) what happened and how it maps to the fingerprint.
    Returns the structured verdict or None (disabled / budget / failure). Never guesses:
    if it could not research, researched=false and cause_class=unknown."""
    try:
        from src.llm.client import WEB_SEARCH_USD, get_llm
    except Exception:
        return None
    llm = get_llm()
    if not llm.is_enabled():
        return None
    est = max_uses * WEB_SEARCH_USD + 0.15
    if not llm.budget_ok(est):
        log.warning("explain_incident skipped — monthly LLM budget (spent $%.2f)", llm.month_spend())
        return None
    slim_sig = {k: v for k, v in sig.items() if k not in ("majors", "alts")}
    prompt = (
        "You are the risk strategist of a 7-bot crypto perp-futures fleet (paper wallets). "
        f"Between {inc['start']} and {inc['end']} (UTC) the fleet lost ${-inc['fleet_pnl']:.0f} "
        f"across {inc['n_trades']} trades in {inc['n_bots_losing']} bots at once. "
        "Our own numeric fingerprint of the market over that window (majors = BTC/ETH/SOL 1h "
        "on Bybit; vol_ratio = window volume vs trailing-7d hourly mean; whipsaw = both-leg travel "
        "beyond the net move; flows = CoinGecko market-cap deltas of BTC/ETH vs USDT/USDC):\n"
        f"{json.dumps(slim_sig, ensure_ascii=False)}\n"
        f"Bot impact: {json.dumps(impact, ensure_ascii=False, default=str)}\n\n"
        "TASK: (1) Search the web for what happened in crypto/macro/geopolitics/exchanges in and "
        "just before that window (statements by policymakers, war/geopolitical news, ETF flows, "
        "exchange incidents, liquidation cascades, token-specific events, scheduled data). "
        "(2) Classify the ROOT CAUSE into exactly one cause_class. (3) Explain the LINK between the "
        "cause, the fingerprint and how the bots lost (e.g. longs stopped on the down-leg, then "
        "shorts stopped on the bounce = whipsaw). (4) money_flow: where did capital go — out of "
        "crypto, into stables, BTC vs alts — grounded in the flows numbers and anything you find "
        "(ETF/exchange flow reports). (5) market_effect_tags: 3-6 short tags describing the "
        "MARKET EFFECT (not the headline), e.g. 'dead-volume-then-spike', 'v-reversal', "
        "'oi-purge', 'alts-underperform', 'stable-inflow'. Cite sources as URLs or outlet+date. "
        "If you could not research, set researched=false, cause_class='unknown', confidence 0 — "
        "never guess."
    )
    try:
        client = llm._c()
        model = llm.model_for(tier)
        # step 1 — research (prose + citations). Asking for JSON here is brittle: the
        # model embeds <cite> tags inside strings. Prose in, structure out (step 2).
        resp = client.messages.create(
            model=model, max_tokens=4096,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
            messages=[{"role": "user", "content": prompt + "\n\nWrite your findings as a clear "
                       "report with these headed sections: CAUSE CLASS, HEADLINE, WHAT HAPPENED, "
                       "LINK TO BOT LOSSES, MONEY FLOW, MARKET EFFECT TAGS, SOURCES, RESEARCHED (yes/no)."}],
        )
        texts, urls = [], []
        n_search = 0
        for b in resp.content:
            bt = getattr(b, "type", "")
            if bt == "text":
                texts.append(getattr(b, "text", "") or "")
                for c in (getattr(b, "citations", None) or []):
                    u = getattr(c, "url", None)
                    if u:
                        urls.append(u)
            elif bt == "server_tool_use":
                n_search += 1
        prose = re.sub(r"</?cite[^>]*>", "", "\n".join(texts)).strip()
        try:
            llm.record_web_search(resp.usage, model, n_search)
        except Exception:
            pass
        if not prose:
            return None
        # step 2 — schema-validated extraction (cheap tier; the API enforces the shape)
        ext = llm.complete(
            "Convert this research report into the JSON schema. Keep the analyst's numbers "
            "and wording; cause_class must be one of the enum values; sources = URLs/outlets "
            "mentioned (add these citation URLs too: " + ", ".join(sorted(set(urls))[:12]) + "). "
            "researched=false ONLY if the report says it could not search.\n\nREPORT:\n" + prose[:12000],
            tier="cheap", json_schema=EXPLAIN_SCHEMA, max_tokens=2000, cache_system=False)
        data = ext.get("data") if isinstance(ext, dict) else None
        if not isinstance(data, dict):
            data = {"cause_class": "unknown", "cause_confidence": 0.0, "researched": bool(n_search),
                    "headline": "structured extraction failed — see prose", "what_happened": prose[:1500],
                    "link_to_bot_losses": "", "money_flow": "", "market_effect_tags": [], "sources": urls[:8]}
        data["sources"] = list(dict.fromkeys((data.get("sources") or []) + urls))[:12]
        data["model"] = model
        data["n_searches"] = n_search
        data["prose"] = prose[:6000]
        return data
    except Exception as exc:
        log.warning("explain_incident failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# memory + live matching + embargo state
# --------------------------------------------------------------------------- #
def load_memory() -> dict:
    try:
        return json.loads(MEMORY.read_text())
    except Exception:
        return {"incidents": [], "n_incidents": 0}


def save_memory(mem: dict) -> None:
    mem["updated_at"] = datetime.now(UTC).isoformat()
    mem["n_incidents"] = len(mem.get("incidents") or [])
    mem["general_rule"] = _general_rule(mem)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mem, indent=2, ensure_ascii=False, default=str))
    tmp.replace(MEMORY)


def _general_rule(mem: dict) -> dict | None:
    """Once >=3 incidents exist, a pooled rule (median thresholds, loss-weighted
    strength) generalises beyond any single fingerprint. Below that, per-incident rules
    are all we honestly have."""
    incs = [i for i in (mem.get("incidents") or []) if i.get("rule")]
    if len(incs) < 3:
        return None
    thr: dict[str, list[float]] = {}
    for i in incs:
        for k, v in (i["rule"].get("thresholds") or {}).items():
            thr.setdefault(k, []).append(float(v))
    w = np.array([abs(float(i.get("severity") or 0.0)) for i in incs]) + 1e-9
    strength = float(np.average([i["rule"]["strength"] for i in incs], weights=w))
    ttl = float(np.median([i["rule"]["ttl_h"] for i in incs]))
    return {"thresholds": {k: round(float(np.median(v)), 4) for k, v in thr.items()},
            "min_hits": RULE_MIN_HITS, "strength": round(strength, 3),
            "floor_mult": round(max(FLOOR_MULT_MIN, 1.0 - 0.9 * strength), 3),
            "ttl_h": float(np.clip(ttl, TTL_MIN_H, TTL_MAX_H)), "n": len(incs)}


def match_live(sig: dict, mem: dict | None = None) -> dict | None:
    """Compare the live fingerprint with every learned rule. Returns the strongest
    match {incident_id, strength, floor_mult, ttl_h, hits, ...} or None."""
    mem = mem or load_memory()
    best = None
    rules = [(i.get("id"), i.get("rule"), i.get("cause", {}).get("cause_class"))
             for i in (mem.get("incidents") or []) if i.get("rule")]
    if mem.get("general_rule"):
        rules.append(("general", mem["general_rule"], "pooled"))
    for rid, rule, cls in rules:
        n, hits = rule_hits(rule, sig)
        if n >= int(rule.get("min_hits", RULE_MIN_HITS)):
            score = n + float(rule.get("strength", 0.5))
            if best is None or score > best["_score"]:
                best = {"incident_id": rid, "cause_class": cls, "hits": hits, "n_hits": n,
                        "strength": rule["strength"], "floor_mult": rule["floor_mult"],
                        "ttl_h": rule["ttl_h"], "_score": score}
    if best:
        best.pop("_score", None)
    return best


def _load_state() -> dict:
    try:
        return json.loads(EMBARGO_STATE.read_text())
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = EMBARGO_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False))
    tmp.replace(EMBARGO_STATE)


def update_embargo(bases: list[str] | None = None, *, now: datetime | None = None) -> dict | None:
    """Hourly: refresh the live fingerprint, match, and return the `global.embargo`
    payload for event_risk.json (or None). ARMS ONLY WHEN THE FLEET IS BLEEDING
    (owner rule 2026-08-19): fingerprint match without realised fleet losses is an
    opportunity, not a danger. Persists state so an active embargo keeps its TTL even
    if the fingerprint fades the next hour; extends TTL on re-match (again only while
    bleeding)."""
    now = now or datetime.now(UTC)
    # کلید دستی مالک: outputs/embargo_override.json = {"suspend_until": "<iso>"} —
    # تا آن لحظه امبارگوی فعال لغو و match جدید بی‌اثر است (برای وقتی حکم ماشین اشتباه است)
    try:
        ov = json.loads((OUT / "embargo_override.json").read_text())
        su = datetime.fromisoformat(str(ov.get("suspend_until")))
        if su.tzinfo is None:
            su = su.replace(tzinfo=UTC)
        if now < su:
            st = _load_state()
            if st.get("active"):
                _log_embargo({**st["active"], "event": "suspended_by_owner", "at": now.isoformat()})
                st["active"] = None
                _save_state(st)
            return None
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("embargo_override unreadable (%s) — ignored", exc)
    mem = load_memory()
    if not (mem.get("incidents")):
        return None
    st = _load_state()
    active = st.get("active")
    if active:
        try:
            until = datetime.fromisoformat(active["until"])
        except Exception:
            until = now
        if until <= now:
            _log_embargo({**active, "event": "expired", "at": now.isoformat()})
            st["active"] = None
            active = None
    try:
        sig = live_signature(bases)
    except Exception as exc:
        log.warning("live_signature failed: %s", exc)
        sig = {}
    st["last_signature"] = {k: v for k, v in sig.items() if k not in ("majors", "alts")}
    st["last_checked"] = now.isoformat()
    m = match_live(sig, mem) if sig else None
    if m:
        # قانون مالک 2026-08-19: امضا کافی نیست — فقط با خون‌ریزیِ واقعیِ ناوگان مسلح شو.
        try:
            bleeding, bstats = fleet_bleeding(None, pd.Timestamp(now))
        except Exception as exc:
            log.warning("fleet_bleeding failed (%s) — treating as not bleeding", exc)
            bleeding, bstats = False, {}
        st["last_bleeding"] = bstats
        if not bleeding:
            m = None
    if m:
        m["bleeding"] = bstats
        until = now + timedelta(hours=float(m["ttl_h"]))
        if active:
            # extend, keep the stronger setting
            new_until = max(datetime.fromisoformat(active["until"]), until)
            active.update({"until": new_until.isoformat(), "last_match": now.isoformat(),
                           "strength": max(float(active.get("strength", 0)), float(m["strength"])),
                           "floor_mult": min(float(active.get("floor_mult", 1)), float(m["floor_mult"])),
                           "hits": m["hits"], "extensions": int(active.get("extensions", 0)) + 1})
        else:
            active = {"since": now.isoformat(), "until": until.isoformat(), "last_match": now.isoformat(),
                      "matched": m["incident_id"], "cause_class": m.get("cause_class"),
                      "strength": m["strength"], "floor_mult": m["floor_mult"], "ttl_h": m["ttl_h"],
                      "hits": m["hits"], "extensions": 0, "bleeding_at_start": m.get("bleeding"),
                      "signature_at_start": st["last_signature"]}
            _log_embargo({**active, "event": "start"})
        st["active"] = active
    _save_state(st)
    if not active:
        return None
    return {
        "active": True, "since": active["since"], "until": active["until"],
        "strength": active["strength"], "floor_mult": active["floor_mult"],
        "matched": active["matched"], "cause_class": active.get("cause_class"),
        "reason": f"embargo: market fingerprint matches incident {active['matched']} "
                  f"({', '.join(active.get('hits') or [])[:160]})",
    }


def _log_embargo(rec: dict) -> None:
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with EMBARGO_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def score_embargoes(trades: pd.DataFrame | None = None) -> list[dict]:
    """After TTL: did the stress materialise, and what did the fleet do meanwhile?
    Appends `scored` records; returns the new scores. Honest labels: we cannot know
    the PnL of trades that were never opened, so the verdict is about the MARKET
    (did the fingerprint keep/escalate) plus the realised PnL of what did trade."""
    if not EMBARGO_LOG.exists():
        return []
    recs = [json.loads(l) for l in EMBARGO_LOG.read_text().splitlines() if l.strip()]
    scored_since = {r.get("since") for r in recs if r.get("event") == "scored"}
    now = pd.Timestamp.now(tz=UTC)
    out = []
    for r in recs:
        if r.get("event") != "start" or r.get("since") in scored_since:
            continue
        # the effective end is the latest 'until' recorded for this since (extensions live in state)
        st = _load_state()
        act = st.get("active") or {}
        until = act["until"] if act.get("since") == r["since"] else r["until"]
        t0, t1 = pd.Timestamp(r["since"]), pd.Timestamp(until)
        if t1 > now:
            continue
        sig = market_signature(t0, t1, None, with_flows=False)
        rule = None
        mem = load_memory()
        for i in mem.get("incidents") or []:
            if i.get("id") == r.get("matched"):
                rule = i.get("rule")
        if r.get("matched") == "general":
            rule = mem.get("general_rule")
        n, hits = rule_hits(rule or {}, sig)
        tr = trades if trades is not None else fleet_trades(t0 - timedelta(days=1))
        during = tr[(tr["open_date"] >= t0) & (tr["open_date"] < t1)]
        rec = {"event": "scored", "since": r["since"], "until": until, "matched": r.get("matched"),
               "realised": {k: sig.get(k) for k in ("btc_ret_pct", "btc_range_pct", "whipsaw_pct",
                                                    "vol_ratio", "rv_z", "alt_down_share")},
               "rule_hits_during": n, "hits": hits,
               "trades_opened_during": int(len(during)),
               "floor_trades_during": int((during["enter_tag"] == "activity_floor").sum()),
               "pnl_opened_during": round(float(during["pnl"].sum()), 2),
               "verdict": "stress_materialised" if n >= RULE_MIN_HITS else "false_alarm",
               "scored_at": now.isoformat()}
        _log_embargo(rec)
        out.append(rec)
    return out
