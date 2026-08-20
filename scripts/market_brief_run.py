#!/usr/bin/env python3
"""Daily LLM market brief — a short, grounded read of the market situation for the
external execution dashboard.

Grounded: feeds Claude ONLY facts already computed by the deterministic layers
(regime, event catalysts, fleet go-live posture, top risk action) — never raw price —
and asks for a 3-part narrative (regime read / key risks / fleet takeaway).

Cost-safe: one Sonnet call/day (~$0.01), gated by the client's hard $5 monthly cap. If
the LLM is disabled or the budget is reached, it writes a DETERMINISTIC fallback brief
(assembled from the same facts, no narrative) so the dashboard always has content.

Writes outputs/market_brief.json (atomic).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # load-bearing
from src.llm.client import get_llm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "outputs")

SYSTEM = (
    "You are a crypto trading-desk risk analyst. You write a terse daily brief for the "
    "operator of a 6-bot algial fleet (all currently paper/dry-run). Use ONLY the facts "
    "provided — never invent prices, numbers, or events. Be concrete and non-promotional. "
    "regime_read: one sentence on the market regime and what it means for sizing. "
    "key_risks: 2-4 bullet strings, each naming the catalyst/symbol and the concrete risk. "
    "fleet_takeaway: one sentence on what the fleet should watch or do today."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "regime_read": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "fleet_takeaway": {"type": "string"},
    },
    "required": ["regime_read", "key_risks", "fleet_takeaway"],
    "additionalProperties": False,
}


def _load(name):
    try:
        with open(os.path.join(OUT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _facts() -> dict:
    er = _load("event_risk.json") or {}
    cat = (_load("event_catalysts.json") or {}).get("events") or {}
    gl = (_load("golive_scorecard.json") or {}).get("bots") or {}
    ex = (_load("execution_report.json") or {}).get("fleet") or {}
    acts = (_load("risk_actions.json") or {}).get("actions") or []
    glob = er.get("global") or {}
    cats = sorted(cat.items(), key=lambda kv: -(kv[1].get("risk", 0) or 0))[:6]
    return {
        "regime": {"risk": glob.get("risk"), "reason": glob.get("reason")},
        "catalysts": [{"symbol": k, "risk": v.get("risk"), "reason": (v.get("reason") or "")[:220]}
                      for k, v in cats],
        "fleet": {
            "gross_pnl_quote": ex.get("gross_pnl_quote"),
            "slip_pct_of_gross": ex.get("slip_pct_of_gross"),
            "ready": [b for b, g in gl.items() if g.get("ready_for_live")],
            "not_ready": [b for b, g in gl.items() if not g.get("ready_for_live")],
        },
        "top_action": (acts[0] if acts else None),
    }


def _fallback(f: dict) -> dict:
    reg = f["regime"]
    chop = (reg.get("risk") or 0) > 0.05
    risks = [f"{c['symbol']}: {c['reason']}" for c in f["catalysts"] if (c.get("risk") or 0) >= 0.5]
    return {
        "regime_read": (f"Chop/range — efficiency risk {reg.get('risk')}; sizes reduced. {reg.get('reason','')}"
                        if chop else f"Trending/nominal — no size cut. {reg.get('reason','')}"),
        "key_risks": risks or ["No high-risk catalysts flagged; market nominal."],
        "fleet_takeaway": (f"Top action: {f['top_action']['fix'][:160]}" if f.get("top_action")
                           else "No fleet actions queued; monitor slippage and regime."),
        "_source": "deterministic_fallback",
    }


def run() -> dict:
    f = _facts()
    llm = get_llm()
    brief, cost, model, source = None, 0.0, None, None
    if llm.is_enabled():
        prompt = "FACTS (JSON):\n" + json.dumps(f, ensure_ascii=False)
        # 600 answer tokens over a JSON fact sheet: this rewrites facts we already
        # computed into prose, it does not decide anything. Sonnet would otherwise think
        # adaptively (billed as output) before writing those few lines — several times
        # the answer itself. Nothing here needs reasoning depth, so it is turned off.
        res = llm.complete(prompt, tier="smart", system=SYSTEM, json_schema=SCHEMA,
                           max_tokens=600, cache_system=True, thinking="disabled")
        if res.get("skipped"):
            source = "budget_skipped"
        elif res.get("data"):
            brief, cost, model, source = res["data"], res.get("cost_usd", 0.0), res.get("model"), "llm"
    if brief is None:
        brief = _fallback(f)
        source = source or "llm_disabled"
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source, "model": model, "cost_usd": round(cost, 6),
        "month_spend": round(llm.month_spend(), 4), "budget_remaining": llm.budget_remaining(),
        "brief": brief,
        "facts": f,  # keep the grounding facts so the dashboard can show sources
    }
    dest = os.path.join(OUT, "market_brief.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, dest)
    print(f"[market_brief] source={source} cost=${cost:.5f} month=${out['month_spend']:.3f}/$5")
    return out


if __name__ == "__main__":
    run()
