"""Claude-assisted trade post-mortems, grounded in hard execution numbers.

The project notes are full of *manual* post-mortems ("68% hit SL not ROI",
"winners round-tripped to -15%"). This automates that at fleet scale, and —
crucially — feeds Claude the deterministic evidence it should reason over
(per-fill slippage bps, the realised-edge prior, exit reason, DCA count) rather
than asking it to guess price direction. Claude's job here is *attribution and a
prioritised fix*, not prediction.

Per losing trade -> a compact evidenced record -> Claude -> a structured verdict
{primary_cause, confidence, evidence, suggested_fix}. Then a cheap deterministic
roll-up plus one synthesis call turns the verdicts into the 2-3 systemic fixes
for that bot.

Two modes:
  * sync  — a handful of worst trades, answered inline (Haiku); for interactive
            use and verification.
  * batch — the full losing-trade set via the Batch API (50% cheaper, <1h); for
            the nightly cron.

Reads bot sqlite read-only + outputs/pair_priors.json; writes only under outputs/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.execution.slippage import BOTS, USER_DATA, load_orders, load_trades
from src.llm.client import get_llm

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"

TAXONOMY = ["execution", "signal_stale", "risk_mgmt", "regime", "noise"]

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_cause": {"type": "string", "enum": TAXONOMY},
        "confidence": {"type": "number"},
        "evidence": {"type": "string"},
        "suggested_fix": {"type": "string"},
    },
    "required": ["primary_cause", "confidence", "evidence", "suggested_fix"],
    "additionalProperties": False,
}

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "systemic_fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fix": {"type": "string"},
                    "rationale": {"type": "string"},
                    "addresses_cause": {"type": "string", "enum": TAXONOMY},
                },
                "required": ["fix", "rationale", "addresses_cause"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "systemic_fixes"],
    "additionalProperties": False,
}

SYSTEM_RUBRIC = """You are a quant execution analyst reviewing closed losing trades from a 15-minute \
crypto futures bot. Attribute each loss to its DOMINANT cause using ONLY the evidence given — do not \
speculate about price direction. Cause taxonomy:

- execution : the loss was materially worsened by slippage, taker fills, fill latency, or non-fills \
(look at entry/exit slippage bps and taker vs maker).
- signal_stale : entry was on a base whose realised edge prior is negative while its fitness score is \
high (model says good, live says bad) — the signal itself is stale/miscalibrated.
- risk_mgmt : the stop/take-profit mechanics caused the damage (e.g. stop too tight vs volatility, a \
disaster-stop hit, DCA that deepened a loser).
- regime : the trade fought the prevailing regime (short hold, immediate adverse move, exit_reason = stop).
- noise : a normal-variance loss with no systemic tell.

Weigh the hard numbers over narrative. Be terse and specific. suggested_fix must be one concrete, \
actionable change (a config knob, a mechanic, a universe change) — not generic advice."""


def _trade_prompt(t: dict) -> str:
    return (
        f"Trade: {t['bot']} {t['pair']} {'SHORT' if t['is_short'] else 'LONG'} "
        f"tag={t['enter_tag']} exit={t['exit_reason']} lev={t['leverage']:.1f}x\n"
        f"PnL: {t['close_profit_abs']:+.2f} quote ({t['close_profit']*100:+.2f}% ROI-of-margin proxy), "
        f"hold {t['hold_hours']:.1f}h\n"
        f"Execution: order_type={t['order_type']}, entry_slip={t['entry_slip_bps']}, "
        f"exit_slip={t['exit_slip_bps']} bps, fills={t['n_fills']} (dca_adds={t['dca_adds']}), "
        f"exit_fill_latency={t['exit_latency_s']}s\n"
        f"Base prior: decayed_edge={t['prior_decayed']}, prior_mult={t['prior_mult']}, "
        f"fitness_score={t['selected_score']}, base_flag={t['prior_flag']}\n"
    )


def _enrich(bot: str, db_path, priors: dict, n_worst: int, since_days: float) -> pd.DataFrame:
    trades = load_trades(db_path, since_days=since_days)
    if trades.empty:
        return trades
    losers = trades[trades["close_profit_abs"] < 0].nsmallest(n_worst, "close_profit_abs").copy()
    if losers.empty:
        return losers
    orders = load_orders(db_path, since_days=since_days)
    bp = priors.get(bot, {})

    def agg_orders(tid: int) -> dict:
        o = orders[orders["ft_trade_id"] == tid] if not orders.empty else pd.DataFrame()
        if o.empty:
            return {"order_type": "?", "entry_slip_bps": None, "exit_slip_bps": None,
                    "n_fills": 0, "dca_adds": 0, "exit_latency_s": None}
        entry = o[o["ft_order_side"] == "buy"] if bool(o["is_short"].iloc[0]) is False else o[o["ft_order_side"] == "sell"]
        # simpler: entry orders vs exit orders by ft_order_side matching trade direction
        entries = o[o["ft_order_side"].isin(["buy", "sell"])]
        # entry side = the side that opens; freqtrade tags exit differently, but ft_order_side
        # is buy/sell — use order sequence: first order(s) = entry, last = exit
        o_sorted = o.sort_values("order_date")
        exit_row = o_sorted.iloc[-1]
        entry_rows = o_sorted.iloc[:-1] if len(o_sorted) > 1 else o_sorted
        return {
            "order_type": exit_row["order_type"],
            "entry_slip_bps": round(float(entry_rows["adv_bps"].mean()), 2) if len(entry_rows) else None,
            "exit_slip_bps": round(float(exit_row["adv_bps"]), 2),
            "n_fills": int(len(o)),
            "dca_adds": int(max(0, len(entry_rows) - 1)),
            "exit_latency_s": round(float(exit_row["fill_latency_s"]), 2) if pd.notna(exit_row["fill_latency_s"]) else None,
        }

    recs = []
    for _, t in losers.iterrows():
        ex = agg_orders(int(t["id"]))
        pr = bp.get(t["base"], {})
        recs.append(
            {
                "id": int(t["id"]),
                "bot": bot,
                "pair": t["pair"],
                "base": t["base"],
                "is_short": int(t["is_short"]),
                "enter_tag": t["enter_tag"],
                "exit_reason": t["exit_reason"],
                "leverage": float(t["leverage"] or 1),
                "close_profit": float(t["close_profit"]),
                "close_profit_abs": float(t["close_profit_abs"]),
                "hold_hours": float(t["hold_hours"] or 0),
                "prior_decayed": pr.get("decayed_avg_profit"),
                "prior_mult": pr.get("prior_mult"),
                "selected_score": pr.get("latest_selected_score"),
                "prior_flag": _flag(pr),
                **ex,
            }
        )
    return pd.DataFrame.from_records(recs)


def _flag(pr: dict) -> str:
    d = pr.get("decayed_avg_profit")
    if d is None:
        return "unknown"
    if d >= 0:
        return "positive_edge"
    return "bleeding"


def analyze(bot: str, *, n_worst: int = 12, since_days: float = 45.0, mode: str = "sync",
            per_trade_tier: str = "cheap", synth_tier: str = "reasoning", write: bool = True) -> dict:
    db_path = USER_DATA / BOTS[bot]
    priors = _load_priors()
    df = _enrich(bot, db_path, priors, n_worst, since_days)
    if df.empty:
        return {"bot": bot, "note": "no losing trades in window"}

    llm = get_llm()
    if not llm.is_enabled():
        return {"bot": bot, "note": "LLM disabled (no key)", "n_losers": int(len(df))}

    # A closed trade's evidence never changes, so neither can its verdict — reuse
    # last night's. Measured 2026-08-12: the 10 worst losers in a 45-day window are
    # almost the same set every night (two bots once overlapped 100% on eight
    # consecutive runs), so ~92% of the per-trade calls were re-classifying trades
    # that had already been classified.
    cached = _cached_verdicts(_prior_run(bot))

    verdicts: dict[int, dict] = {}
    if mode == "batch":
        todo = [r for _, r in df.iterrows() if int(r["id"]) not in cached]
        if not todo:
            verdicts = {int(r["id"]): cached[int(r["id"])] for _, r in df.iterrows()}
            return _finish(bot, df, verdicts, llm, synth_tier, write, n_reused=len(verdicts))
        items = [{"custom_id": str(r["id"]), "prompt": _trade_prompt(r)} for r in todo]
        batch_id = llm.batch_submit(items, tier=per_trade_tier, system=SYSTEM_RUBRIC,
                                    json_schema=VERDICT_SCHEMA, max_tokens=400)
        return {"bot": bot, "mode": "batch", "batch_id": batch_id, "n_submitted": len(items),
                "n_reused": len(df) - len(items),
                "note": "poll batch_status(batch_id); then collect() to finish"}

    n_reused = 0
    for _, r in df.iterrows():
        tid = int(r["id"])
        if tid in cached:
            verdicts[tid] = cached[tid]
            n_reused += 1
            continue
        res = llm.complete(_trade_prompt(r), tier=per_trade_tier, system=SYSTEM_RUBRIC,
                           json_schema=VERDICT_SCHEMA, max_tokens=400)
        # Record WHY a verdict is missing (budget skip vs truncation vs bad JSON) —
        # a blanket "parse_error" hid which of those was happening.
        verdicts[tid] = res.get("data") or {
            "primary_cause": "noise", "confidence": 0, "suggested_fix": "-",
            "evidence": "unclassified: " + str(res.get("skipped") or res.get("parse_error")
                                               or "no_data")}

    return _finish(bot, df, verdicts, llm, synth_tier, write, n_reused=n_reused)


def _prior_run(bot: str) -> dict:
    """Last night's post-mortem for this bot ({} if none/unreadable)."""
    try:
        return json.loads((OUT / f"postmortem_{bot.lower()}.json").read_text())
    except Exception:
        return {}


def _ids(trades) -> set[int]:
    """Trade ids as plain ints — the stored JSON and a live pandas row do not
    otherwise compare equal (numpy int64 vs int vs str)."""
    out = set()
    for t in trades:
        try:
            out.add(int(t["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _cached_verdicts(prior: dict) -> dict[int, dict]:
    """{trade_id: verdict} from a previous run — only verdicts worth reusing.

    An `unclassified:` verdict is a failed call, not an answer, so it is never
    cached; that trade gets another attempt tonight.
    """
    out: dict[int, dict] = {}
    for t in prior.get("trades") or []:
        v = t.get("verdict") or {}
        if not v.get("primary_cause"):
            continue
        if str(v.get("evidence", "")).startswith("unclassified"):
            continue
        try:
            out[int(t["id"])] = v
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _finish(bot: str, df: pd.DataFrame, verdicts: dict, llm, synth_tier: str, write: bool,
            *, n_reused: int = 0) -> dict:
    from collections import Counter

    causes = Counter(v.get("primary_cause", "noise") for v in verdicts.values())
    # dollar-weighted cause: which cause is destroying the most money
    loss_by_cause: dict[str, float] = {}
    for _, r in df.iterrows():
        v = verdicts.get(int(r["id"]), {})
        c = v.get("primary_cause", "noise")
        loss_by_cause[c] = loss_by_cause.get(c, 0.0) + float(r["close_profit_abs"])

    trades_out = []
    for _, r in df.iterrows():
        v = verdicts.get(int(r["id"]), {})
        trades_out.append({**{k: r[k] for k in ("id", "pair", "enter_tag", "exit_reason",
                                                "close_profit_abs", "exit_slip_bps", "prior_flag",
                                                # 2026-08-12: تا امروز محاسبه می‌شدند ولی به آرتیفکت
                                                # نمی‌رسیدند → پایین‌دست null می‌دید
                                                "prior_decayed", "prior_mult", "selected_score")},
                           "verdict": v})

    # The synthesis is the expensive call (Sonnet). Its whole input is the verdict
    # set — so when that set is unchanged, buying it again returns the same answer
    # at full price. Reuse the previous one instead.
    prior = _prior_run(bot)
    prior_syn = prior.get("synthesis") or {}
    same_trades = _ids(prior.get("trades") or []) == _ids(trades_out)
    reusable = bool(prior_syn.get("systemic_fixes")) and not prior_syn.get("degraded")
    if same_trades and reusable:
        synth = {**prior_syn, "reused_from": prior.get("generated_at")}
    else:
        synth = _synthesize(bot, causes, loss_by_cause, trades_out, llm, synth_tier)

    out = {
        "bot": bot,
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "n_analyzed": int(len(df)),
        "n_verdicts_reused": int(n_reused),
        "cause_counts": dict(causes),
        "loss_by_cause_quote": {k: round(v, 2) for k, v in sorted(loss_by_cause.items(), key=lambda x: x[1])},
        "synthesis": synth,
        "trades": trades_out,
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"postmortem_{bot.lower()}.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def _synthesize(bot, causes, loss_by_cause, trades_out, llm, tier) -> dict:
    ev = {
        "bot": bot,
        "cause_counts": dict(causes),
        "loss_by_cause_quote": {k: round(v, 2) for k, v in loss_by_cause.items()},
        "worst_trades": sorted(trades_out, key=lambda t: t["close_profit_abs"])[:6],
    }
    prompt = (
        "Here are per-trade loss attributions for one bot. Identify the 2-3 SYSTEMIC fixes that would "
        "recover the most money, ordered by expected impact. Ground each fix in the dollar-weighted "
        "cause breakdown.\n\n" + json.dumps(ev, default=str)
    )
    # 1500 = room for a headline + 3 grounded fixes.
    #
    # effort=low (2026-08-19): Sonnet thinks adaptively unless told otherwise and those
    # tokens are billed as output — the 905 it once spent reasoning before writing a
    # character are what truncated the old 800-token budget into "synthesis parse
    # error". Depth is reduced rather than removed: this output names the systemic fixes
    # that build_risk_actions turns into ranked actions, so it is judgment-adjacent, not
    # a restatement. The dollar ranking it works from is already ours, which is why
    # shallow reasoning is enough — but "no reasoning" is a bigger step than the
    # evidence so far supports. Revisit once the call ledger shows what it actually
    # spends here.
    res = llm.complete(prompt, tier=tier, system=SYSTEM_RUBRIC, json_schema=SYNTH_SCHEMA,
                       max_tokens=1500, effort="low")
    data = res.get("data")
    if data:
        return data
    # Never hand the dashboard an error string: fall back to the deterministic roll-up
    # the per-trade verdicts already support, and label it so nobody mistakes it for
    # Claude's synthesis.
    return _fallback_synthesis(bot, loss_by_cause, trades_out,
                               reason=res.get("skipped") or res.get("parse_error") or "no_data")


def _fallback_synthesis(bot, loss_by_cause, trades_out, *, reason: str) -> dict:
    """Deterministic stand-in when the synthesis call is unusable ($0, no LLM).

    Ranks causes by dollars bled and promotes the per-trade `suggested_fix` from the
    worst trade of each cause — grounded in the same evidence, just not synthesised.
    """
    ranked = sorted(loss_by_cause.items(), key=lambda kv: kv[1])  # most negative first
    fixes = []
    for cause, bled in ranked[:3]:
        worst = min(
            (t for t in trades_out if (t.get("verdict") or {}).get("primary_cause") == cause),
            key=lambda t: t["close_profit_abs"], default=None)
        if worst is None:
            continue
        fixes.append({
            "fix": (worst.get("verdict") or {}).get("suggested_fix", ""),
            "rationale": f"{cause} bled {bled:.2f} quote across the analysed losers; "
                         f"worst single trade {worst.get('pair')} {worst['close_profit_abs']:.2f}.",
            "addresses_cause": cause,
        })
    top = ranked[0] if ranked else ("noise", 0.0)
    return {
        "headline": f"[deterministic fallback — synthesis unavailable: {reason}] "
                    f"{bot}: {top[0]} is the biggest bleed ({top[1]:.2f} quote).",
        "systemic_fixes": fixes,
        "degraded": reason,
    }


def collect(bot: str, batch_id: str, *, since_days: float = 45.0, n_worst: int = 12,
            synth_tier: str = "reasoning", write: bool = True) -> dict:
    """Finish a batch run once batch_status(batch_id) == 'ended'."""
    llm = get_llm()
    verdicts_raw = llm.batch_results(batch_id, as_json=True)
    df = _enrich(bot, USER_DATA / BOTS[bot], _load_priors(), n_worst, since_days)
    verdicts = {int(k): v for k, v in verdicts_raw.items() if isinstance(v, dict) and "primary_cause" in v}
    return _finish(bot, df, verdicts, llm, synth_tier, write)


def _load_priors() -> dict:
    p = OUT / "pair_priors.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("priors", {})
        except Exception:
            return {}
    return {}
