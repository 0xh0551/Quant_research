"""Per-symbol event/risk overlay: a 0..1 risk score bots scale position size by.

Two layers, combined into one `event_risk.json` = {symbol: {risk, reason, factors}}:

  * deterministic (free, live)   — funding-rate crowding (ccxt), realised-vol
    spike vs its own history (processed parquet), and book-liquidity stress
    (spread/sweep from the microstructure collector). These need no LLM.
  * event (optional, Claude)     — Claude + web_search gathers upcoming token
    unlocks, listing/delisting, and protocol events per base and returns a
    structured per-symbol event risk. This is the orthogonal, non-price signal
    a numeric model can't see. Gated behind `with_events` and grounded: the LLM
    must cite what it found, and its score is blended, never trusted blindly.

`risk` is 0 (size normally) .. 1 (size to near-zero / veto). Live bots map it to
a stake multiplier. Read-only inputs; writes only `outputs/event_risk.json`
(+ an atomic copy into the configured bot `user_data/` dir, when one is set in
the site-local config).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
PROCESSED = ROOT / "data" / "processed"
MS_LATEST = OUT / "microstructure_latest.json"
EVENT_CACHE = OUT / "event_catalysts.json"  # LLM catalyst results, refreshed a few x/day
from src import local_config

BOT_UD = local_config.user_data_dir()  # None on a plain research checkout

VENUE_MARKET = {"bybit": "futures", "gate": "futures", "okx": "futures", "hyperliquid": "futures"}


# --------------------------------------------------------------------------- #
# deterministic factors
# --------------------------------------------------------------------------- #
def _base(symbol: str) -> str:
    return symbol.split("/")[0]


def _parquet_for(symbol: str, venue: str, tf: str = "15m") -> Path | None:
    sym = symbol.split(":")[0].replace("/", "")  # BTC/USDT:USDT -> BTCUSDT
    mkt = VENUE_MARKET.get(venue, "futures")
    p = PROCESSED / f"{venue}_{mkt}_{sym}_{tf}.parquet"
    return p if p.exists() else None


def vol_spike(symbol: str, venue: str, tf: str = "15m", recent: int = 24, hist: int = 480) -> tuple[float, str]:
    """Realised-vol spike: recent vol vs its trailing distribution -> 0..1."""
    p = _parquet_for(symbol, venue, tf)
    if p is None:
        return 0.0, ""
    try:
        df = pd.read_parquet(p)
        col = "close" if "close" in df.columns else ("raw_close" if "raw_close" in df.columns else None)
        if col is None or len(df) < hist:
            return 0.0, ""
        ret = np.log(df[col]).diff()
        rv = ret.rolling(recent).std()
        cur = float(rv.iloc[-1])
        base = rv.iloc[-hist:-recent]
        mu, sd = float(base.mean()), float(base.std())
        if sd <= 0 or not np.isfinite(cur):
            return 0.0, ""
        z = (cur - mu) / sd
        risk = float(np.clip((z - 1.0) / 3.0, 0, 1))  # z>1 starts counting, z>=4 -> 1.0
        return (round(risk, 3), f"vol z={z:.1f}") if risk > 0.05 else (0.0, "")
    except Exception:
        return 0.0, ""


def funding_risk(symbols: list[str], venue: str) -> dict[str, tuple[float, str]]:
    """|funding| crowding per symbol via ccxt (free). High |funding| = crowded = risk."""
    out: dict[str, tuple[float, str]] = {}
    try:
        from src.execution.orderbook import make_exchange

        ex = make_exchange(venue)
        ex.load_markets()
    except Exception:
        return out
    for sym in symbols:
        try:
            fr = ex.fetch_funding_rate(sym)
            rate = float(fr.get("fundingRate") or 0.0)
            # typical 8h funding ~0.0001 (1bp); 0.001 (10bp) is very crowded
            risk = float(np.clip(abs(rate) / 0.001, 0, 1))
            out[sym] = (round(risk, 3), f"funding={rate*100:.3f}%") if risk > 0.05 else (0.0, "")
        except Exception:
            out[sym] = (0.0, "")
    return out


def liquidity_risk() -> dict[str, tuple[float, str]]:
    """Book-liquidity stress from the microstructure collector's latest snapshot."""
    if not MS_LATEST.exists():
        return {}
    try:
        books = json.loads(MS_LATEST.read_text()).get("books", {})
    except Exception:
        return {}
    out: dict[str, tuple[float, str]] = {}
    for sym, b in books.items():
        spread = b.get("spread_bps") or 0.0
        sweep = b.get("sell_sweep_bps_2000") or b.get("buy_sweep_bps_2000") or 0.0
        # >10bps spread or >15bps to sweep $2k = thin/risky to exit
        risk = float(np.clip(max(spread / 20.0, (sweep or 0) / 25.0), 0, 1))
        out[sym] = (round(risk, 3), f"spread={spread}bps") if risk > 0.1 else (0.0, "")
    return out


# --------------------------------------------------------------------------- #
# global market-regime gate (free, deterministic, fresh via ccxt)
# --------------------------------------------------------------------------- #
def regime_risk(ref_symbols: tuple = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
                er_bars: int = 48, cap: float = 0.6) -> tuple[float, str]:
    """Market-wide chop score 0..cap from Kaufman efficiency ratio on majors.

    ER = |net move| / sum(|bar moves|) over `er_bars` 15m bars (12h). Trending
    markets: ER >~ 0.25; dead chop: ER <~ 0.10 — where the RL bots' idle-penalty
    forces low-quality trades. Capped at `cap` so the GLOBAL gate shrinks size but
    never fully vetoes on its own (market-neutral bots still function in chop).
    Fetches fresh public OHLCV (no keys). Fails safe to 0 (no throttle).
    """
    try:
        from src.execution.orderbook import make_exchange

        ex = make_exchange("bybit")
        ers = []
        for sym in ref_symbols:
            try:
                ohlcv = ex.fetch_ohlcv(sym, "15m", limit=er_bars + 2)
                closes = [c[4] for c in ohlcv][-(er_bars + 1):]
                if len(closes) < er_bars + 1:
                    continue
                diffs = np.abs(np.diff(closes))
                denom = float(diffs.sum())
                if denom <= 0:
                    continue
                ers.append(abs(closes[-1] - closes[0]) / denom)
            except Exception:
                continue
        if not ers:
            return 0.0, ""
        er = float(np.mean(ers))
        # ER >= 0.18 -> no chop risk; ER 0 -> full chop
        chop = float(np.clip((0.18 - er) / 0.18, 0, 1))
        risk = round(chop * cap, 3)
        return (risk, f"market chop ER={er:.3f} ({len(ers)} majors, 12h)") if risk > 0.05 else (0.0, "")
    except Exception:
        return 0.0, ""


# --------------------------------------------------------------------------- #
# optional Claude + web_search event layer
# --------------------------------------------------------------------------- #
EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbols": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "base": {"type": "string"},
                    "event_risk": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["base", "event_risk", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["symbols"],
    "additionalProperties": False,
}


def event_layer(bases: list[str], tier: str = "cheap", max_uses: int = 2) -> dict[str, tuple[float, str]]:
    """Claude + web_search for near-term catalysts. Returns {base: (risk, reason)}.

    Uses Haiku + a low web-search cap, and respects the client's hard monthly
    budget: if the budget is exhausted it returns {} (deterministic-only) rather
    than spending. This is a MANUAL-only path (no cron) — see event_risk_scan.py.
    """
    from src.llm.client import WEB_SEARCH_USD, get_llm

    llm = get_llm()
    if not llm.is_enabled():
        return {}
    # budget gate: don't even start if a web-search sweep could breach the cap
    est = max_uses * WEB_SEARCH_USD + 0.02
    if not llm.budget_ok(est):
        print(f"[event_layer] skipped — monthly LLM budget reached (spent ${llm.month_spend():.2f})")
        return {}
    prompt = (
        "For each of these crypto assets, search for MAJOR near-term (next 7 days) catalysts that raise "
        "downside/volatility risk for a short-horizon futures bot: large token unlocks/vesting cliffs, "
        "exchange listing or DELISTING, mainnet/hard-fork events, or known regulatory/legal dates. "
        "Return event_risk 0 (nothing notable) to 1 (major imminent catalyst). Cite what you found in "
        "reason; if you find nothing for an asset, set 0 and say 'none found'. Assets: "
        + ", ".join(bases)
    )
    try:
        # web_search server tool (dynamic-filtering variant on current models)
        client = llm._c()
        model = llm.model_for(tier)
        # basic web-search variant (no code-execution dependency) so the cheap Haiku
        # tier can drive it; the 20260209 dynamic-filtering variant needs a model with
        # programmatic tool calling (Sonnet/Opus).
        resp = client.messages.create(
            model=model,
            max_tokens=3072,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
            messages=[{"role": "user", "content": prompt}],
        )
        # account for the web_search call (tokens + per-search fee) against the budget
        n_searches = 0
        try:
            n_searches = int(getattr(getattr(resp.usage, "server_tool_use", None), "web_search_requests", 0) or 0)
        except Exception:
            n_searches = max_uses
        llm.record_web_search(resp.usage, model, n_searches or max_uses)
        # extract the model's final text, then a follow-up structured pass to coerce JSON
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        coerce = llm.complete(
            "Convert this research into the schema. Text:\n\n" + text,
            tier="cheap", json_schema=EVENT_SCHEMA, max_tokens=2048,
        )
        data = coerce.get("data") or {}
        out: dict[str, tuple[float, str]] = {}
        for row in data.get("symbols", []):
            r = float(np.clip(row.get("event_risk", 0), 0, 1))
            out[row["base"].upper()] = (round(r, 3), row.get("reason", "")[:200])
        _write_event_cache(out)
        return out
    except Exception as e:
        print(f"[event_layer] skipped: {e}")
        return {}


def _write_event_cache(events: dict[str, tuple[float, str]]) -> None:
    payload = {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "events": {b: {"risk": r, "reason": rs} for b, (r, rs) in events.items()},
    }
    try:
        EVENT_CACHE.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _load_event_cache(max_age_h: float = 8.0) -> dict[str, tuple[float, str]]:
    """Reuse recent LLM catalysts so the cheap hourly blend keeps the event signal
    between the (less frequent) --with-events refreshes."""
    if not EVENT_CACHE.exists():
        return {}
    try:
        data = json.loads(EVENT_CACHE.read_text())
        gen = pd.Timestamp(str(data.get("generated_at", "")).rstrip("Z"))
        if (pd.Timestamp.utcnow().tz_localize(None) - gen) > pd.Timedelta(hours=max_age_h):
            return {}
        return {b: (float(v.get("risk", 0)), v.get("reason", "")) for b, v in data.get("events", {}).items()}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# combine + write
# --------------------------------------------------------------------------- #
def build(venue_symbols: dict[str, list[str]], with_events: bool = False,
          weights=(0.35, 0.30, 0.35), event_weight: float = 0.6, write: bool = True) -> dict:
    """venue_symbols = {venue: [pair,...]} -> event_risk.json payload.

    Deterministic risk = weighted blend of (vol, funding, liquidity). If
    `with_events`, blend in the Claude event score with `event_weight` (a hard
    catalyst can dominate). Final risk is clamped 0..1.
    """
    liq = liquidity_risk()
    all_bases = sorted({_base(s) for syms in venue_symbols.values() for s in syms})
    # Refresh the LLM catalyst cache only when asked (it costs); always blend the
    # most recent cached catalysts so the cheap hourly run keeps the event signal.
    if with_events:
        event_layer(all_bases)
    events = _load_event_cache()

    result: dict[str, dict] = {}
    for venue, symbols in venue_symbols.items():
        fund = funding_risk(symbols, venue)
        for sym in symbols:
            v, vr = vol_spike(sym, venue)
            f, fr = fund.get(sym, (0.0, ""))
            lq, lr = liq.get(sym, (0.0, ""))
            det = weights[0] * v + weights[1] * f + weights[2] * lq
            reasons = [r for r in (vr, fr, lr) if r]
            ev, evr = events.get(_base(sym), (0.0, ""))
            if ev > 0:  # cached catalyst present -> blend (a hard event can dominate)
                risk = (1 - event_weight) * det + event_weight * ev
                if evr:
                    reasons.append(f"event:{evr}")
            else:
                risk = det
            result[sym] = {
                "risk": round(float(np.clip(risk, 0, 1)), 3),
                "reason": "; ".join(reasons) or "nominal",
                "factors": {"vol": v, "funding": f, "liquidity": lq, "event": ev},
                "venue": venue,
            }

    g_risk, g_reason = regime_risk()
    payload = {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "with_events": with_events,
        "n_symbols": len(result),
        "global": {"risk": g_risk, "reason": g_reason or "nominal"},
        "symbols": result,
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "event_risk.json").write_text(json.dumps(payload, indent=2))
        # atomic copy into the bind-mounted dir the bots hot-read (if configured)
        if BOT_UD is not None:
            try:
                tmp = BOT_UD / "event_risk.json.tmp"
                tmp.write_text(json.dumps(payload, indent=2))
                tmp.replace(BOT_UD / "event_risk.json")
            except Exception as e:
                print(f"[event_risk] could not write to bot user_data: {e}")
    return payload
