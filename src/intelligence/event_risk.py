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
import re
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


# A verdict that admits no research happened is NOT a risk reading. Dropping these
# is the whole point of _priority_bases: unknown must fall through to 0.0 (no signal),
# never to the 0.5 the model likes to hedge with.
_NO_RESEARCH = re.compile(
    r"unable to search|insufficient data|could not (?:search|verify|find|access)|"
    r"no (?:data|information) available|unverified", re.I)


def _priority_bases(bases: list[str], k: int) -> list[str]:
    """The k bases actually worth researching: biggest live gross exposure first.

    2026-08-12: this used to ask about every whitelisted base (41 of them) with a
    2-search budget. The model researched two and hedged the other 39 at risk 0.5
    with reason "Unable to search" — paying for a signal that was 89% "I don't
    know". A catalyst only costs money where money is at risk, so rank by the
    fleet's gross notional per base and research the top of that list properly.
    Bases with no open exposure fall back to the deterministic layer, which is
    what they had anyway.
    """
    weight: dict[str, float] = {}
    try:
        fr = json.loads((OUT / "fleet_risk.json").read_text())
        for a in fr.get("per_asset") or []:
            b = str(a.get("base") or "").upper()
            if b:
                weight[b] = float(a.get("gross_notional") or 0.0)
    except Exception:
        pass  # no exposure file -> fall through to the whitelist order
    return sorted(bases, key=lambda b: -weight.get(b.upper(), 0.0))[:k]


def event_layer(bases: list[str], tier: str = "cheap", max_uses: int = 5,
                top_k: int = 6) -> dict[str, tuple[float, str]]:
    """Claude + web_search for near-term catalysts. Returns {base: (risk, reason)}.

    Only the `top_k` bases with the most live exposure are researched, with a
    search budget sized to actually cover them (see _priority_bases). Uses Haiku
    and respects the client's hard monthly budget: if the budget is exhausted it
    returns {} (deterministic-only) rather than spending.
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
    bases = _priority_bases(bases, top_k)
    if not bases:
        return {}
    prompt = (
        "For each of these crypto assets, search for MAJOR near-term (next 7 days) catalysts that raise "
        "downside/volatility risk for a short-horizon futures bot: large token unlocks/vesting cliffs, "
        "exchange listing or DELISTING, mainnet/hard-fork events, or known regulatory/legal dates. "
        "Return event_risk 0 (nothing notable) to 1 (major imminent catalyst). Cite what you found in "
        "reason; if you searched and found nothing for an asset, set 0 and say 'none found'. "
        "CRITICAL: if you could NOT research an asset, OMIT it from the output entirely — never guess "
        "a middling score for it, and never return a row whose reason says you could not search. "
        "Assets: " + ", ".join(bases)
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
        dropped = []
        for row in data.get("symbols", []):
            reason = row.get("reason", "")
            # Belt and braces alongside the prompt: an "I couldn't look it up" row is
            # not evidence of risk, and build() blends anything > 0 at event_weight
            # 0.6 — so letting a hedged 0.5 through would impose a 0.30 risk floor on
            # that symbol for nothing.
            if _NO_RESEARCH.search(reason):
                dropped.append(row.get("base", "?"))
                continue
            r = float(np.clip(row.get("event_risk", 0), 0, 1))
            out[row["base"].upper()] = (round(r, 3), reason[:200])
        if dropped:
            print(f"[event_layer] dropped {len(dropped)} un-researched rows: {', '.join(dropped)}")
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


def _load_event_cache(max_age_h: float = 26.0) -> dict[str, tuple[float, str]]:
    """Reuse recent LLM catalysts so the cheap hourly blend keeps the event signal
    between the (less frequent) --with-events refreshes.

    2026-08-08: 8h→26h. با ران روزانه‌ی --with-events، کش ۸ساعته یعنی لایه‌ی
    رویداد ۱۶h/روز کور بود (آنلاک AVAX فلگ‌شده ولی event_risk صفر، sizing ×1.2
    روی پوزیشن باز). کاتالیزورها افق چندروزه دارند؛ ۲۶h یک ران خطارفته را هم
    پوشش می‌دهد. ران دومِ روزانه (16:17) تازگی را به ≤۸h می‌رساند."""
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
# ── altdata blend (2026-08-05): DVOL/positioning پیش‌نگر + بایاسِ فاندینگ ─────
_ALTDATA_PATH = OUT / "altdata_snapshot.json"
_ALTDATA_STALE_H = 9.0  # کرونِ altdata هر ۶ ساعت است


def _load_altdata() -> dict | None:
    try:
        st = _ALTDATA_PATH.stat()
        if (pd.Timestamp.utcnow().timestamp() - st.st_mtime) > _ALTDATA_STALE_H * 3600:
            return None
        return json.loads(_ALTDATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def altdata_global_risk(alt: dict | None) -> tuple[float, str]:
    """ریسکِ رژیمِ پیش‌نگر از دیتای جایگزین — مکملِ regime_risk (که گذشته‌نگر است).

    دو مؤلفه، هر دو کران‌دار و fail-safe:
      • DVOL: سطحِ فعلی نسبت به توزیعِ ۳۰روزهٔ خودش (percentile) + جهشِ ۲۴ساعته.
        وولِ ضمنی «قیمتِ آینده» است؛ اسپایکش قبل از ریزش در OHLCV دیده می‌شود.
      • L/S crowding: انحرافِ شدیدِ نسبتِ long/short بایننس = جمعیتِ یک‌طرفه →
        ریسکِ liquidation-cascade.
    خروجی حداکثر 0.5 — مثل گیتِ chop هرگز به‌تنهایی وتو نمی‌کند."""
    if not alt:
        return 0.0, ""
    risk, reasons = 0.0, []
    try:
        series = alt.get("dvol_series_btc") or {}
        vals = [float(v) for v in (series.get("values") or []) if v is not None]
        if len(vals) >= 48:
            cur = vals[-1]
            pctile = sum(1 for v in vals if v <= cur) / len(vals)
            chg24 = (cur / vals[-25] - 1.0) if len(vals) >= 25 and vals[-25] > 0 else 0.0
            dvol_risk = 0.0
            if pctile >= 0.90:
                dvol_risk += 0.25
            elif pctile >= 0.75:
                dvol_risk += 0.12
            if chg24 >= 0.15:
                dvol_risk += 0.20
            elif chg24 >= 0.08:
                dvol_risk += 0.10
            if dvol_risk > 0:
                reasons.append(f"DVOL {cur:.0f} (p{pctile*100:.0f}, {chg24:+.0%}/24h)")
            risk = max(risk, min(0.4, dvol_risk))
    except Exception:
        pass
    try:
        ls = alt.get("ls_series_btc") or {}
        lvals = [float(v) for v in (ls.get("values") or []) if v is not None]
        if lvals:
            cur_ls = lvals[-1]
            if cur_ls >= 2.2 or cur_ls <= 0.45:
                risk = min(0.5, risk + 0.15)
                reasons.append(f"L/S crowding {cur_ls:.2f}")
    except Exception:
        pass
    return round(risk, 3), "; ".join(reasons)


def altdata_funding_bias(alt: dict | None) -> dict[str, float]:
    """{BASE: funding_ann_pct} از فاندینگ‌های افراطیِ altdata. قرارداد علامت:
    مثبت = لانگ‌ها می‌پردازند (استاندارد پرپ). مصرف‌کننده: _risk_overlay.entry_mult
    که ورودِ خلافِ فاندینگِ شدید را کوچک/وتو می‌کند و ورودِ گیرندهٔ فاندینگ را
    کمی جایزه می‌دهد."""
    if not alt:
        return {}
    out: dict[str, float] = {}
    try:
        for row in alt.get("funding_extremes") or []:
            sym = str(row.get("symbol", ""))
            base = sym[:-4] if sym.endswith("USDT") else (sym[:-4] if sym.endswith("USDC") else sym)
            ann = row.get("funding_ann_pct")
            if base and ann is not None:
                out[base] = round(float(ann), 1)
    except Exception:
        return {}
    return out


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
    # altdata blend (2026-08-05): رژیمِ پیش‌نگر (DVOL/L-S) با گیتِ گذشته‌نگرِ chop
    # max می‌شود؛ بایاسِ فاندینگ به‌صورت کلیدِ مجزا منتشر می‌شود (side-آگاه است و
    # نمی‌تواند داخل ریسکِ بی‌جهتِ symbols حل شود).
    alt = _load_altdata()
    alt_risk, alt_reason = altdata_global_risk(alt)
    if alt_risk > g_risk:
        g_risk, g_reason = alt_risk, (alt_reason or "altdata regime")
    elif alt_reason:
        g_reason = f"{g_reason or 'nominal'}; {alt_reason}"
    # incident-learning embargo (2026-08-17): if the live market fingerprint matches a
    # learned incident rule, publish global.embargo -> bots block organic entries and
    # size activity-floor trades by floor_mult. Fail-open: any error -> no embargo.
    embargo = None
    try:
        from src.intelligence.incident import update_embargo
        embargo = update_embargo(_priority_bases(all_bases, 12))
    except Exception as e:  # never let the detector break the hourly scan
        print(f"[event_risk] embargo detector failed: {e}")
    if embargo:
        g_reason = f"{embargo['reason']}; {g_reason or 'nominal'}"
    payload = {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "with_events": with_events,
        "n_symbols": len(result),
        "global": {"risk": g_risk, "reason": g_reason or "nominal",
                   **({"embargo": embargo} if embargo else {})},
        "funding_bias": altdata_funding_bias(alt),
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
