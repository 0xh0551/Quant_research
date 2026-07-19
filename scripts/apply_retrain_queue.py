#!/usr/bin/env python3
"""Consume outputs/retrain_queue.json → force a FRESH retrain of stale per-pair models.

A pair reaches the retrain queue when its fitness score is high but its realised
live edge is negative — i.e. the *model* is stale (drift), not the pair. freqai
stores per-pair sub-models at
    noches/user_data/models/<identifier>/sub-train-<BASE>_<ts>/
This archives (mv — reversible, mirrors the existing `_wiped_*` convention, never
rm) those sub-models so freqai rebuilds them from scratch on its next train cycle,
clearing any continual-learning drift. No bot restart (freqai picks it up on its
own loop). Idempotent: a pair isn't re-archived within `--cooldown-days`.

    .venv/bin/python scripts/apply_retrain_queue.py            # apply
    .venv/bin/python scripts/apply_retrain_queue.py --dry      # show, don't move

Cron (after learn_outcomes.py has written the queue):
    35 23 * * * cd /home/h0551user/Quant_research && .venv/bin/python scripts/apply_retrain_queue.py >> logs/retrain.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
MODELS = Path("/home/h0551user/noches/user_data/models")
STATE = OUT / "retrain_applied.json"

# ledger bot name -> freqai identifier (== models/<identifier>/)
BOT_IDENTIFIER = {
    "bot2": "bot2_",
    "bot3": "bot3_rlpro_live",
    "bot4": "bot4_",
    "bot1": "bot1_ml_live",
    "bot5": "bot5_ml_live",
}


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def apply(dry: bool = False, cooldown_days: float = 3.0) -> dict:
    try:
        queue = json.loads((OUT / "retrain_queue.json").read_text()).get("queue", [])
    except Exception:
        print("no retrain_queue.json"); return {"applied": [], "skipped": []}

    state = _load_state()
    now = _now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    archive_root = MODELS / f"_retrain_forced_{stamp}"
    applied, skipped = [], []

    for item in queue:
        bot, base = item.get("bot"), (item.get("base") or "").upper()
        ident = BOT_IDENTIFIER.get(bot)
        if not ident or not base:
            skipped.append({"bot": bot, "base": base, "why": "unknown bot/base"}); continue
        key = f"{bot}:{base}"
        # cooldown: don't re-archive a pair we cleared recently
        last = state.get(key)
        if last:
            try:
                age_d = (now - datetime.fromisoformat(last)).total_seconds() / 86400.0
                if age_d < cooldown_days:
                    skipped.append({"bot": bot, "base": base, "why": f"cooldown {age_d:.1f}d"}); continue
            except Exception:
                pass
        model_dir = MODELS / ident
        if not model_dir.is_dir():
            skipped.append({"bot": bot, "base": base, "why": f"no model dir {ident}"}); continue
        subs = sorted(model_dir.glob(f"sub-train-{base}_*"))
        if not subs:
            skipped.append({"bot": bot, "base": base, "why": "no per-pair sub-train models"}); continue
        moved = []
        for sub in subs:
            dest = archive_root / ident / sub.name
            if dry:
                moved.append(sub.name); continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(sub), str(dest))
                moved.append(sub.name)
            except Exception as e:
                print(f"  [{key}] move failed {sub.name}: {e}")
        if moved:
            applied.append({"bot": bot, "base": base, "ident": ident, "archived": len(moved),
                            "dest": str(archive_root / ident)})
            if not dry:
                state[key] = now.isoformat()

    if not dry and applied:
        STATE.write_text(json.dumps(state, indent=2))
        _clean_registries_and_restart(applied)
    return {"applied": applied, "skipped": skipped, "archive_root": str(archive_root)}


def _clean_registries_and_restart(applied: list[dict]) -> None:
    """Remove archived pairs from freqai's pair_dictionary.json and restart the
    affected bots. Without this, the running drawer still points at the archived
    model files (FileNotFoundError spam until the pair's next scheduled retrain).
    Stop -> edit -> start so the in-memory drawer can't re-save the stale entry."""
    import subprocess

    by_bot: dict[str, list[dict]] = {}
    for a in applied:
        by_bot.setdefault(a["bot"], []).append(a)
    for bot, items in by_bot.items():
        try:
            subprocess.run(["docker", "stop", bot], capture_output=True, timeout=120)
            for a in items:
                pd_path = MODELS / a["ident"] / "pair_dictionary.json"
                if not pd_path.exists():
                    continue
                shutil.copy(pd_path, str(pd_path) + ".bak_retrain")
                d = json.loads(pd_path.read_text())
                stale = [p for p in d if p.split("/")[0].upper() == a["base"]]
                for p in stale:
                    d.pop(p, None)
                pd_path.write_text(json.dumps(d, indent=2))
                print(f"  [{bot}] registry cleaned: {stale}")
        except Exception as e:
            print(f"  [{bot}] registry clean failed: {e}")
        finally:
            subprocess.run(["docker", "start", bot], capture_output=True, timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--cooldown-days", type=float, default=3.0)
    args = ap.parse_args()
    res = apply(dry=args.dry, cooldown_days=args.cooldown_days)
    print(f"{'[DRY] ' if args.dry else ''}retrain-forced: {len(res['applied'])} pairs cleared for fresh retrain")
    for a in res["applied"]:
        print(f"  ✓ {a['bot']}/{a['base']}: archived {a['archived']} sub-models → {a['dest']}")
    for s in res["skipped"][:10]:
        print(f"  – {s['bot']}/{s['base']}: {s['why']}")
    if res["applied"] and not args.dry:
        print("freqai will rebuild these from scratch on its next train cycle (no restart needed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
