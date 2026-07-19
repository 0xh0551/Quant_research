#!/usr/bin/env python3
"""Consolidate the per-bot Claude post-mortems into ONE prioritized action list.

Deterministic (no LLM, $0). Reads outputs/postmortem_<bot>.json (the Claude synthesis)
+ retrain_priority.json / drop_list.json, and writes outputs/risk_actions.json — a single
ranked "recommended actions" feed for the dashboard. This is the "actionable" arc of the
learning loop: the LLM diagnoses (post-mortem), this turns those diagnoses into a ranked
to-do; a human still decides (no automatic bot changes).

Ranking: each systemic fix inherits the $-impact of the cause it addresses (from the bot's
loss_by_cause_quote), so the biggest-bleed fixes float to the top across all bots.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "outputs")
BOTS = ["bot1", "bot2", "bot6", "bot5", "bot3", "bot4"]


def _load(name):
    try:
        with open(os.path.join(OUT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build() -> dict:
    actions = []
    for b in BOTS:
        pm = _load(f"postmortem_{b}.json")
        if not pm:
            continue
        syn = pm.get("synthesis") or {}
        loss_by_cause = pm.get("loss_by_cause_quote") or {}
        bot = pm.get("bot", b)
        headline = syn.get("headline", "")
        for fix in (syn.get("systemic_fixes") or [])[:3]:
            cause = fix.get("addresses_cause") or "unknown"
            impact = abs(float(loss_by_cause.get(cause, 0.0) or 0.0))  # $ this cause bled
            actions.append({
                "bot": bot,
                "cause": cause,
                "impact_quote": round(impact, 2),          # ranking key ($ bled by this cause)
                "fix": fix.get("fix", ""),
                "rationale": fix.get("rationale", ""),
                "headline": headline,
                "source": "postmortem",
                "generated_at": pm.get("generated_at"),
            })

    # fold in the learning-loop's retrain/drop flags as first-class actions
    retr = (_load("retrain_priority.json") or {}).get("retrain_priority") or []
    for r in retr:
        if r.get("action") in ("retrain", "drop"):
            actions.append({
                "bot": r.get("bot"),
                "cause": "stale_model" if r.get("action") == "retrain" else "bleeding_pair",
                "impact_quote": round(abs(float(r.get("decayed_avg_profit", 0.0) or 0.0)) * 100, 2),
                "fix": f"{r.get('action','').upper()} {r.get('base','')} — "
                       f"edge/trade {round((r.get('decayed_avg_profit') or 0)*100,2)}%, "
                       f"score {r.get('latest_selected_score')}",
                "rationale": "Learning loop flagged this pair (high score but bleeding, or decayed edge).",
                "headline": "",
                "source": "learning_loop",
                "generated_at": None,
            })

    # rank: biggest $-impact first; postmortem fixes with real $ outrank flags
    actions.sort(key=lambda a: (a.get("impact_quote") or 0.0), reverse=True)
    for i, a in enumerate(actions, 1):
        a["priority"] = i

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_actions": len(actions),
        "actions": actions[:20],  # top 20
    }


def main():
    payload = build()
    dest = os.path.join(OUT, "risk_actions.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dest)
    print(f"[build_risk_actions] wrote {payload['n_actions']} actions -> {dest}")


if __name__ == "__main__":
    main()
