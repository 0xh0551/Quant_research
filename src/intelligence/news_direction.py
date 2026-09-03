"""News→direction gate: the agent the owner asked for (2026-08-21).

«با هوش باشد؛ طبق اخبار بفهمد اگر خبرِ مهم به بازار جهت می‌دهد، به بات‌ها امر کند
فقط در آن جهت ترید کنند؛ و دورِ اخبارِ مهمِ بی‌جهت، قبل و بعدش ترید تعطیل باشد.»

Three parts, all published as `global.direction_gate` in event_risk.json (hourly):

  1. macro calendar (outputs/macro_calendar.json) — scheduled events (FOMC, CPI, NFP,
     Jackson Hole, big crypto-policy dates). Refreshed weekly by Claude+web_search;
     the PAUSE window around a high-importance event is DETERMINISTIC and free:
     [at - PRE_H, at + POST_H] → organic entries closed both sides (floor trades at
     reduced size), unless a clear direction verdict overrides it.
  2. news classifier — Claude+web_search, TRIGGERED (not on a fixed clock): calendar
     window, |BTC 6h| move, vol-regime flip, or fleet bleeding. Two-step (prose
     research → cheap schema extraction, the incident lesson). Verdict: importance,
     direction long/short/unclear, confidence, ttl. importance>=0.7 & confidence>=0.7
     & direction in {long,short} → SIDE GATE: bots may only enter in that direction.
     important-but-unclear → short PAUSE (market digesting).
  3. scoring — every expired gate is scored deterministically (BTC return over the
     gate window vs the allowed direction) into outputs/direction_gate_log.jsonl.
     The gate must EARN trust the same way direction_calls and embargoes do.

Owner rules honoured: the direction comes from the AGENT reading the news (allowed by
the 2026-08-09 ruling; manual/static gating stays forbidden). Fail-open everywhere:
no file / stale / broken / expired / LLM-budget-exhausted → no gate. Owner override:
outputs/direction_gate_override.json {"suspend_until": iso}.

Writes ONLY under outputs/ and (via event_risk.build) event_risk.json.
"""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
CALENDAR = OUT / "macro_calendar.json"
STATE = OUT / "direction_gate_state.json"
LOG = OUT / "direction_gate_log.jsonl"
OVERRIDE = OUT / "direction_gate_override.json"

UTC = timezone.utc
PRE_H, POST_H = 2.0, 1.0          # pause window around a scheduled event
UNCLEAR_PAUSE_H = 4.0             # important news, no direction yet → short pause
MIN_IMPORTANCE = 0.7
MIN_CONFIDENCE = 0.7
SIDE_TTL_MIN_H, SIDE_TTL_MAX_H = 4.0, 24.0
SCAN_MIN_GAP_H = 4.0              # never burn LLM more often than this (تریگرهای خبری/کف)
MAX_LLM_PER_DAY = 4               # سقفِ سختِ روزانه‌ی تماس‌های خبری (2→4، حادثه‌ی 09-03)
# ── حادثه‌ی 2026-09-03 (BTC +4.8% زیرِ گیتِ «فقط شورت» ۱۴ساعته، بدونِ بازبینی): ──
FAST_GAP_H = 2.0                  # فاصله‌ی حداقل وقتی تریگر *قیمتی* است (btc_6h / contradiction)
CONTRA_6H = 2.0                   # % حرکتِ 6h خلافِ گیتِ side → ابطالِ فوری (همان TREND_HOLD_VETO_6H)
EMERGENCY_PER_DAY = 1             # یک تماسِ اضطراری بعد از ابطال، خارج از سقفِ روزانه
AUTHORITY_MIN_N = 10              # اختیارِ سخت فقط با کارنامه: n≥10 و hit-rate≥0.6
AUTHORITY_MIN_HIT = 0.6
# رزروِ بودجه (سهمی از سقفِ ماهانه به دلار) که این لایه به کارهای تحلیلی (بریفِ
# استراتژیست، پست‌مورتم، market brief) وامی‌گذارد — آدیت 08-28.
NEWS_RESERVE = float(os.environ.get("QUANT_NEWS_RESERVE", "0.9"))
QUIET_RESERVE = float(os.environ.get("QUANT_QUIET_RESERVE", "1.5"))
QUIET_SWEEP_H = 96.0              # اگر این‌قدر تماس نبود، یک جاروی آرام (کاتالیست‌ها کهنه نشوند)
EVENT_CACHE = OUT / "event_catalysts.json"   # همان کشِ event_risk — این‌جا پر می‌شود (ادغام 08-21)
CAL_STALE_D = 10.0                 # refresh calendar when older than this
CAL_LOOKAHEAD_D = 45
# market triggers (from the embargo detector's hourly signature — free)
TRIG_ABS_RET6H = 2.5              # |BTC 6h return| %
TRIG_REGIME_FLIP = 2.0
TRIG_ABS_RET24H = 6.0             # |BTC 24h return| % — رالی/ریزشِ پیوسته‌ای که
                                  # هیچ پنجره‌ی ۶ساعته‌اش تریگر نمی‌شود (آدیت 08-22:
                                  # BTC ‏+21%/3d و گیت فقط ۱۲h فعال بود)

# ── trend-hold (تأیید مالک 2026-08-22): تمدیدِ رایگانِ گیتِ side بدونِ تماسِ LLM ──
# وقتی گیتِ خبریِ جهت‌دار منقضی می‌شود ولی روندِ چندساعته هنوز همان جهت را تأیید
# می‌کند، گیت تمدید می‌شود (source=trend_hold). در رویداد 08-22 یکی از بات‌ها
# ۱ دقیقه بعد از انقضای گیت چهار شورت باز کرد و همه استاپ خوردند — این شکاف را می‌بندد.
TREND_HOLD_MIN_24H = 3.0          # % بازده 24h BTC هم‌جهتِ گیت برای تمدید
TREND_HOLD_VETO_6H = 2.0          # % حرکتِ 6h خلافِ گیت → تمدید ممنوع (بگذار بمیرد)
TREND_HOLD_EXTEND_H = 6.0         # هر تمدید این‌قدر
TREND_HOLD_MAX_H = 48.0           # سقفِ عمرِ کل از since اولیه — حکمِ کهنه ابدی نمی‌شود
TREND_HOLD_LOOKAHEAD_MIN = 75     # تمدید «قبل» از انقضا (اجرای ساعتی شکاف نگذارد)

CAL_SCHEMA = {
    "type": "object",
    "properties": {"events": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"},
                       "type": {"type": "string"},
                       "at_utc": {"type": "string"},
                       "importance": {"type": "number"}},
        "required": ["name", "type", "at_utc", "importance"],
        "additionalProperties": False}}},
    "required": ["events"], "additionalProperties": False,
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "importance": {"type": "number"},
        "direction": {"type": "string", "enum": ["long", "short", "unclear", "none"]},
        "confidence": {"type": "number"},
        "scope": {"type": "string", "enum": ["market_wide", "specific_assets"]},
        "headline": {"type": "string"},
        "reason": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "ttl_h": {"type": "number"},
        "researched": {"type": "boolean"},
        "assets": {"type": "array", "items": {
            "type": "object",
            "properties": {"base": {"type": "string"},
                           "event_risk": {"type": "number"},
                           "reason": {"type": "string"}},
            "required": ["base", "event_risk", "reason"],
            "additionalProperties": False}},
    },
    "required": ["importance", "direction", "confidence", "scope", "headline",
                 "reason", "sources", "ttl_h", "researched", "assets"],
    "additionalProperties": False,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _save_json(p: Path, data) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str))
    tmp.replace(p)


def _log_event(rec: dict) -> None:
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# macro calendar
# --------------------------------------------------------------------------- #
def refresh_calendar(llm) -> bool:
    """Weekly Claude+web_search refresh of the scheduled-events calendar."""
    from src.intelligence.incident import _web_research  # shared two-step helper
    prompt = (
        "List the exact UTC date-times of upcoming SCHEDULED events in the next "
        f"{CAL_LOOKAHEAD_D} days that historically move crypto markets: FOMC decisions "
        "and minutes, CPI, PPI, PCE, NFP releases, Fed chair speeches (incl. Jackson Hole), "
        "and major scheduled crypto-policy events (hearings, summits, ETF deadlines, "
        "large scheduled unlocks of majors). Importance 0-1 (FOMC/CPI/Jackson-Hole ~0.8-1.0; "
        "minor speeches ~0.4). Only events with a KNOWN date; use ISO 8601 UTC."
    )
    data = _web_research(llm, prompt, CAL_SCHEMA, max_uses=4, label="macro_calendar")
    if not data or not isinstance(data.get("events"), list) or not data["events"]:
        return False
    events = []
    for e in data["events"]:
        try:
            at = pd.Timestamp(e["at_utc"])
            at = at.tz_localize(UTC) if at.tzinfo is None else at.tz_convert(UTC)
            events.append({"name": str(e["name"])[:120], "type": str(e["type"])[:40],
                           "at_utc": at.isoformat(), "importance": float(e["importance"])})
        except Exception:
            continue
    if not events:
        return False
    _save_json(CALENDAR, {"generated_at": _now().isoformat(),
                          "events": sorted(events, key=lambda x: x["at_utc"])})
    log.info("macro_calendar refreshed: %d events", len(events))
    return True


def calendar_events(now: datetime | None = None) -> list[dict]:
    now = now or _now()
    cal = _load_json(CALENDAR, {})
    out = []
    for e in cal.get("events") or []:
        try:
            at = datetime.fromisoformat(e["at_utc"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            if at > now - timedelta(hours=POST_H + 12):
                out.append({**e, "at": at})
        except Exception:
            continue
    return out


def calendar_pause(now: datetime | None = None) -> dict | None:
    """Deterministic (free) pause window around the nearest high-importance event."""
    now = now or _now()
    for e in calendar_events(now):
        if float(e.get("importance", 0)) < MIN_IMPORTANCE:
            continue
        start = e["at"] - timedelta(hours=PRE_H)
        end = e["at"] + timedelta(hours=POST_H)
        if start <= now <= end:
            return {"mode": "pause", "until": end.isoformat(),
                    "reason": f"scheduled event: {e['name']} @ {e['at_utc']}",
                    "source": "calendar", "event": e["name"]}
    return None


def _upcoming_or_recent_event(now: datetime, within_h: float = 8.0) -> dict | None:
    for e in calendar_events(now):
        if float(e.get("importance", 0)) < MIN_IMPORTANCE:
            continue
        if abs((e["at"] - now).total_seconds()) <= within_h * 3600:
            return e
    return None


# --------------------------------------------------------------------------- #
# triggered news classification
# --------------------------------------------------------------------------- #
def _market_trigger(live_sig: dict | None) -> str | None:
    s = live_sig or {}
    try:
        if abs(float(s.get("btc_ret_pct") or 0)) >= TRIG_ABS_RET6H:
            return f"btc_6h_move={s.get('btc_ret_pct')}%"
        if float(s.get("vol_regime_flip") or 0) >= TRIG_REGIME_FLIP:
            return f"vol_regime_flip={s.get('vol_regime_flip')}"
    except Exception:
        pass
    return None


def classify_news(llm, context: str, bases: list[str] | None = None) -> dict | None:
    from src.intelligence.incident import _web_research
    asset_part = ""
    if bases:
        asset_part = (
            " ALSO, for these crypto assets the fleet holds, list near-term (7d) per-asset "
            "catalysts (unlocks/vesting cliffs, listing/DELISTING, mainnet/forks, legal dates) "
            "as assets[]: event_risk 0 (nothing) to 1 (major imminent); omit an asset you could "
            "not research (never guess): " + ", ".join(bases) + ".")
    prompt = (
        "You are the news-direction officer of a crypto perp-futures bot fleet. "
        f"Trigger context: {context}. Search for the MAJOR market-moving news right now "
        "(last 24h) and anything imminent: central-bank actions/statements, macro prints, "
        "government/policy moves on crypto, war/geopolitics, exchange/stablecoin incidents, "
        "ETF flows. Judge the NET effect on the CRYPTO market over the next several hours "
        "to a day:\n"
        "- direction 'long' = news gives the market a clear upward push (e.g. dovish "
        "surprise, pro-crypto policy, massive short squeeze fuel)\n"
        "- 'short' = clear downward push\n"
        "- 'unclear' = important but direction not yet resolved (pre-event, mixed)\n"
        "- 'none' = nothing important is happening\n"
        "importance = how market-moving (0-1); confidence = how sure about the direction. "
        "ttl_h = how long the push should dominate (4-24). Cite sources. Never guess: if "
        "you could not research, researched=false and direction='none'." + asset_part
    )
    v = _web_research(llm, prompt, VERDICT_SCHEMA, max_uses=3, label="news_direction")
    # ادغام 08-21: همین یک تماس، کشِ کاتالیستِ per-base را هم تازه می‌کند (جاروی
    # روزانه‌ی جداگانه‌ی event_layer حذف شد — بزرگ‌ترین خرجِ ثابتِ ماه بود).
    if v and v.get("researched") and isinstance(v.get("assets"), list):
        try:
            events = {}
            for a in v["assets"]:
                b = str(a.get("base", "")).upper().strip()
                if b:
                    events[b] = {"risk": float(a.get("event_risk") or 0.0),
                                 "reason": str(a.get("reason", ""))[:200]}
            _save_json(EVENT_CACHE, {
                "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
                "source": "news_direction combined sweep",
                "events": events})
        except Exception as exc:
            log.warning("catalyst cache write failed: %s", exc)
    return v


def _policy(verdict: dict, now: datetime) -> dict | None:
    """Verdict → gate (side / pause / None)."""
    if not verdict or not verdict.get("researched"):
        return None
    imp = float(verdict.get("importance") or 0)
    conf = float(verdict.get("confidence") or 0)
    d = verdict.get("direction")
    if imp < MIN_IMPORTANCE:
        return None
    if d in ("long", "short") and conf >= MIN_CONFIDENCE:
        ttl = float(min(max(float(verdict.get("ttl_h") or 8), SIDE_TTL_MIN_H), SIDE_TTL_MAX_H))
        return {"mode": "side", "allowed": d, "until": (now + timedelta(hours=ttl)).isoformat(),
                "reason": f"news[{imp:.2f}/{conf:.2f}]: {verdict.get('headline', '')[:140]}",
                "source": "news", "headline": verdict.get("headline"),
                "sources": (verdict.get("sources") or [])[:6]}
    if d == "unclear":
        return {"mode": "pause", "until": (now + timedelta(hours=UNCLEAR_PAUSE_H)).isoformat(),
                "reason": f"important news, direction unclear: {verdict.get('headline', '')[:120]}",
                "source": "news", "headline": verdict.get("headline")}
    return None


# --------------------------------------------------------------------------- #
# scoring (free, deterministic)
# --------------------------------------------------------------------------- #
def _btc_ret_pct(t0: pd.Timestamp, t1: pd.Timestamp) -> float | None:
    try:
        from src.intelligence.incident import _ohlcv_1h
        df = _ohlcv_1h("BTC/USDT:USDT", pd.Timestamp(t0) - pd.Timedelta(hours=2), pd.Timestamp(t1))
        w = df[(df["ts"] >= pd.Timestamp(t0)) & (df["ts"] <= pd.Timestamp(t1))]
        if len(w) < 2:
            return None
        return round((float(w["c"].iloc[-1]) / float(w["o"].iloc[0]) - 1) * 100, 3)
    except Exception:
        return None


def score_expired(st: dict, now: datetime) -> None:
    """Score every logged gate whose TTL has passed and is not yet scored."""
    try:
        recs = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    except Exception:
        return
    scored = {r.get("since") for r in recs if r.get("event") == "scored"}
    for r in recs:
        if r.get("event") != "start" or r.get("since") in scored:
            continue
        until = pd.Timestamp(r["until"])
        if until.tzinfo is None:
            until = until.tz_localize(UTC)
        if until > pd.Timestamp(now):
            continue
        ret = _btc_ret_pct(pd.Timestamp(r["since"]), until)
        rec = {"event": "scored", "since": r["since"], "until": r["until"],
               "mode": r.get("mode"), "allowed": r.get("allowed"),
               "btc_ret_pct": ret, "scored_at": now.isoformat()}
        if r.get("mode") == "side" and ret is not None:
            signed = ret if r.get("allowed") == "long" else -ret
            rec["verdict"] = "hit" if signed >= 0.3 else ("miss" if signed <= -0.3 else "flat")
        _log_event(rec)


def gate_track_record() -> dict:
    try:
        recs = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    except Exception:
        return {}
    sc = [r for r in recs if r.get("event") == "scored" and r.get("mode") == "side"]
    hits = sum(1 for r in sc if r.get("verdict") == "hit")
    misses = sum(1 for r in sc if r.get("verdict") == "miss")
    return {"n_scored_side": len(sc), "hits": hits, "misses": misses}


# --------------------------------------------------------------------------- #
# trend-hold: تمدیدِ رایگانِ گیتِ side (تأیید مالک 2026-08-22)
# --------------------------------------------------------------------------- #
def _trend_hold(active: dict, until: datetime, live_sig: dict | None,
                now: datetime) -> dict | None:
    """گیتِ فعالِ side که به انقضا رسیده را، اگر روند تأیید کند، تمدید می‌کند.
    None = تمدید نشد (مسیرِ انقضای عادی)."""
    try:
        # گیتی که مدت‌هاست مرده (اسکنرِ خوابیده) احیا نمی‌شود — فقط لبِ انقضا
        if until < now - timedelta(minutes=90):
            return None
        since = datetime.fromisoformat(str(active.get("since")))
        since = since.replace(tzinfo=UTC) if since.tzinfo is None else since
        if now + timedelta(hours=TREND_HOLD_EXTEND_H) > since + timedelta(hours=TREND_HOLD_MAX_H):
            return None                     # سقفِ عمر — حکمِ خبریِ کهنه ابدی نمی‌شود
        allowed = active.get("allowed")
        sign = 1.0 if allowed == "long" else -1.0
        r24 = _btc_ret_pct(pd.Timestamp(now) - pd.Timedelta(hours=24), pd.Timestamp(now))
        if r24 is None or sign * r24 < TREND_HOLD_MIN_24H:
            return None                     # روند دیگر تأیید نمی‌کند
        r6 = None
        try:
            r6 = float((live_sig or {}).get("btc_ret_pct"))
        except (TypeError, ValueError):
            pass
        if r6 is None:
            r6 = _btc_ret_pct(pd.Timestamp(now) - pd.Timedelta(hours=6), pd.Timestamp(now))
        if r6 is not None and sign * r6 <= -TREND_HOLD_VETO_6H:
            return None                     # حرکتِ تندِ خلافِ جهت — بگذار بمیرد
        held = dict(active)
        held["until"] = (now + timedelta(hours=TREND_HOLD_EXTEND_H)).isoformat()
        held["source"] = "trend_hold"
        held["trend_holds"] = int(active.get("trend_holds", 0)) + 1
        held["reason"] = (f"trend-hold #{held['trend_holds']} (btc24h {r24:+.1f}%, "
                          f"btc6h {r6 if r6 is None else round(r6, 2)}) of: "
                          f"{str(active.get('reason', ''))[:140]}")
        _log_event({**held, "event": "trend_hold_extend", "at": now.isoformat()})
        return held
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# hourly entry point (called from event_risk.build)
# --------------------------------------------------------------------------- #
def update_direction_gate(live_sig: dict | None = None, *, now: datetime | None = None,
                          bleeding: bool | None = None, bases: list[str] | None = None,
                          fast: bool = False) -> dict | None:
    """Returns the `global.direction_gate` payload or None. Persists state/log/score."""
    now = now or _now()
    st = _load_json(STATE, {})
    # owner override
    try:
        ov = _load_json(OVERRIDE, {})
        su = datetime.fromisoformat(str(ov.get("suspend_until")))
        if su.tzinfo is None:
            su = su.replace(tzinfo=UTC)
        if now < su:
            if st.get("active"):
                _log_event({**st["active"], "event": "suspended_by_owner", "at": now.isoformat()})
                st["active"] = None
                _save_json(STATE, st)
            return None
    except Exception:
        pass

    score_expired(st, now)

    active = st.get("active")
    if active:
        try:
            until = datetime.fromisoformat(str(active["until"]))
            until = until.replace(tzinfo=UTC) if until.tzinfo is None else until
        except Exception:
            until = now
        # trend-hold (08-22): گیتِ side که منقضی شده/تا اجرای بعدی منقضی می‌شود،
        # اگر روند هنوز هم‌جهت است بدونِ LLM تمدید شود — ولی نه بیش از
        # TREND_HOLD_MAX_H از since اولیه، و نه بعد از حرکتِ 6h خلافِ جهت.
        if active.get("mode") == "side" and \
                until <= now + timedelta(minutes=TREND_HOLD_LOOKAHEAD_MIN):
            held = _trend_hold(active, until, live_sig, now)
            if held is not None:
                active = held
                until = datetime.fromisoformat(active["until"])
        if until <= now:
            _log_event({**active, "event": "expired", "at": now.isoformat()})
            active = None

    # A) ابطال (09-03): گیتِ side فعال + حرکتِ 6h BTC خلافِ جهت ≥ CONTRA_6H → همین حالا لغو.
    #    قبلاً فقط «تمدید» وتو می‌شد و حکمِ غلط تا انقضا (۱۴h) لشگر را قفل می‌کرد.
    contradicted = None
    if active and active.get("mode") == "side":
        r6 = None
        try:
            r6 = float((live_sig or {}).get("btc_ret_pct"))
        except (TypeError, ValueError):
            pass
        if r6 is None:
            try:
                r6 = _btc_ret_pct(pd.Timestamp(now) - pd.Timedelta(hours=6), pd.Timestamp(now))
            except Exception:
                r6 = None
        _sign = 1.0 if active.get("allowed") == "long" else -1.0
        if r6 is not None and _sign * float(r6) <= -CONTRA_6H:
            _log_event({**active, "event": "contradicted", "btc6h": round(float(r6), 2),
                        "at": now.isoformat()})
            contradicted = f"contradiction: gate={active.get('allowed')} vs btc_6h={round(float(r6), 2)}%"
            active = None

    # 1) deterministic calendar pause (free) — only if no side gate is active
    cal = calendar_pause(now)
    if cal and (not active or active.get("mode") == "pause"):
        if not active or active.get("reason") != cal["reason"]:
            cal_rec = {**cal, "since": now.isoformat(), "event": "start"}
            _log_event(cal_rec)
        active = {**cal, "since": (active or {}).get("since", now.isoformat())}

    # 2) triggered LLM classification
    trig = contradicted                       # ابطال = تریگرِ قیمتیِ با اولویت
    ev = _upcoming_or_recent_event(now)
    if trig is None and ev:
        trig = f"scheduled event near: {ev['name']} @ {ev['at_utc']}"
    if trig is None:
        trig = _market_trigger(live_sig)
    if trig is None and not active:
        # تریگرِ 24h (08-22): رالی/ریزشِ پیوسته‌ای که هیچ ۶ساعته‌اش از آستانه
        # نمی‌گذرد — فقط وقتی گیتی فعال نیست (گیتِ فعال را trend-hold زنده نگه
        # می‌دارد؛ این‌جا برای «شروعِ» پوششِ یک روندِ بی‌گیت است).
        try:
            _r24 = _btc_ret_pct(pd.Timestamp(now) - pd.Timedelta(hours=24), pd.Timestamp(now))
            if _r24 is not None and abs(_r24) >= TRIG_ABS_RET24H:
                trig = f"btc_24h_move={_r24}%"
        except Exception:
            pass
    if trig is None and bleeding:
        trig = "fleet bleeding"
    last_llm = st.get("last_llm_at")
    gap_ok, quiet = True, False
    try:
        age = None if last_llm is None else (now - datetime.fromisoformat(last_llm))
        _price_trig = bool(trig) and str(trig).startswith(("btc_", "contradiction", "vol_regime"))
        gap_ok = age is None or age >= timedelta(hours=FAST_GAP_H if _price_trig else SCAN_MIN_GAP_H)
        if trig is None and (age is None or age >= timedelta(hours=QUIET_SWEEP_H)):
            trig, quiet = f"quiet catalyst sweep ({QUIET_SWEEP_H:.0f}h without a triggered scan)", True
    except Exception:
        pass
    # سقفِ سختِ روزانه — هیچ روزی بیش از MAX_LLM_PER_DAY تماسِ خبری
    day_key = now.strftime("%Y-%m-%d")
    used_today = int((st.get("llm_daily") or {}).get(day_key, 0))
    _emerg = int((st.get("emergency_daily") or {}).get(day_key, 0))
    if used_today >= MAX_LLM_PER_DAY:
        if contradicted and _emerg < EMERGENCY_PER_DAY:
            st["emergency_daily"] = {day_key: _emerg + 1}   # تماسِ اضطراری بعد از ابطال
            gap_ok = True
        else:
            trig = None
    if fast and trig and not str(trig).startswith(("btc_", "contradiction", "vol_regime")):
        trig = None                                          # مسیرِ سریع (۱۰ دقیقه‌ای) فقط تریگرِ قیمتی
    if trig and gap_ok:
        try:
            from src.llm.client import get_llm
            llm = get_llm()
            # جاروی آرام (زمان‌بندی‌شده) رزروِ هوشِ واکنشی را نمی‌خورد
            # اولویتِ بودجه (آدیت 2026-08-28): این اسکن ۸۰٪ مصرفِ ماه را می‌خورد و
            # بریفِ استراتژیست/پست‌مورتم را گرسنه می‌گذاشت. حالا اسکنِ تریگرشده هم
            # سهمی (NEWS_RESERVE) برای کارهای تحلیلی نگه می‌دارد؛ جاروی آرام بیشتر.
            ok = llm.budget_ok(0.10, reserve=QUIET_RESERVE) if quiet \
                else llm.budget_ok(0.10, reserve=NEWS_RESERVE)
            if llm.is_enabled() and ok:
                # weekly calendar refresh piggybacks on a triggered run
                cal_data = _load_json(CALENDAR, {})
                try:
                    cal_age_d = (now - datetime.fromisoformat(str(cal_data.get("generated_at")))).days
                except Exception:
                    cal_age_d = 999
                if cal_age_d >= CAL_STALE_D and llm.budget_ok(0.20):
                    refresh_calendar(llm)
                verdict = classify_news(llm, trig, bases)
                st["last_llm_at"] = now.isoformat()
                st["llm_daily"] = {day_key: used_today + 1}
                st["last_verdict"] = verdict
                st["last_trigger"] = trig
                gate = _policy(verdict or {}, now)
                if gate:
                    if active and active.get("mode") == "side" and gate["mode"] == "side" \
                            and active.get("allowed") == gate.get("allowed"):
                        active["until"] = max(str(active["until"]), gate["until"])
                        active["reason"] = gate["reason"]
                        active["extensions"] = int(active.get("extensions", 0)) + 1
                    else:
                        if active:
                            _log_event({**active, "event": "replaced", "at": now.isoformat()})
                        active = {**gate, "since": now.isoformat(), "trigger": trig}
                        _log_event({**active, "event": "start"})
                elif verdict is not None and active and active.get("source") == "news":
                    # the news layer itself says nothing important anymore → release early
                    _log_event({**active, "event": "released_by_rescan", "at": now.isoformat()})
                    active = None
            else:
                st["last_skip"] = f"budget/disabled at {now.isoformat()}"
        except Exception as exc:
            log.warning("news classification failed: %s", exc)

    st["active"] = active
    st["last_checked"] = now.isoformat()
    _save_json(STATE, st)
    if not active:
        return None
    out = {k: active.get(k) for k in ("mode", "allowed", "until", "reason", "source", "since")}
    out["active"] = True
    # D) اختیار بر پایه‌ی کارنامه (09-03): گیتِ side فقط با n≥AUTHORITY_MIN_N و hit≥0.6
    #    «سخت» است (سمتِ مخالف = 0)؛ وگرنه «نرم» (سمتِ مخالف ×0.5). pause تقویمی همیشه سخت.
    tr = gate_track_record()
    _n = int(tr.get("hits", 0)) + int(tr.get("misses", 0))
    _hit = (int(tr.get("hits", 0)) / _n) if _n else 0.0
    earned = _n >= AUTHORITY_MIN_N and _hit >= AUTHORITY_MIN_HIT
    out["authority"] = "hard" if (active.get("mode") == "pause" or earned) else "soft"
    out["track_record"] = {"n": _n, "hit_rate": round(_hit, 2)}
    return out
