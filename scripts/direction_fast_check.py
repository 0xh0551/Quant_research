#!/usr/bin/env python3
"""مسیرِ سریعِ گیتِ جهت‌دار (حادثه‌ی 2026-09-03) — هر ۱۰ دقیقه، بدونِ LLM مگر تریگرِ قیمتی.

کار: امضای زنده‌ی بازار (6h BTC و …) را می‌گیرد، update_direction_gate(fast=True) را صدا
می‌زند (ابطالِ گیتِ خلافِ حرکت ≥2%؛ تماسِ LLM فقط با تریگرِ قیمتی/اضطراری و با فاصله‌ی
FAST_GAP_H) و اگر گیت عوض شد، فقط بلاکِ global.direction_gate را در event_risk.json
(+ کپیِ user_data بات‌ها) به‌روز می‌کند — اسکنِ ساعتیِ کامل دست‌نخورده می‌ماند."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.intelligence.event_risk import OUT, BOT_UD  # noqa: E402
from src.intelligence.incident import live_signature  # noqa: E402
from src.intelligence.news_direction import update_direction_gate  # noqa: E402

def main() -> int:
    t0 = time.time()
    sig = None
    try:
        sig = live_signature()
        sig = {k: v for k, v in sig.items() if k not in ("majors", "alts")}
    except Exception as e:  # noqa: BLE001
        print(f"[fast] live_signature failed: {e} — falling back to embargo_state")
        try:
            sig = json.loads((OUT / "embargo_state.json").read_text()).get("last_signature")
        except Exception:
            sig = None
    try:
        before = json.loads((OUT / "event_risk.json").read_text())
    except Exception:
        before = None
    old_gate = ((before or {}).get("global") or {}).get("direction_gate")
    gate = update_direction_gate(sig, bleeding=None, fast=True)
    changed = json.dumps(gate, sort_keys=True) != json.dumps(old_gate, sort_keys=True)
    print(f"[fast] btc6h={(sig or {}).get('btc_ret_pct')} gate={(gate or {}).get('mode')}/"
          f"{(gate or {}).get('allowed')} authority={(gate or {}).get('authority')} changed={changed} "
          f"({time.time() - t0:.0f}s)")
    if changed and before is not None:
        g = before.setdefault("global", {})
        if gate:
            g["direction_gate"] = gate
        else:
            g.pop("direction_gate", None)
        g["reason"] = (f"{gate['reason']}; " if gate else "") + str(g.get("reason", "")).split("; ", 1)[-1]
        payload = json.dumps(before, indent=2)
        tmp = OUT / "event_risk.json.tmp"; tmp.write_text(payload); tmp.replace(OUT / "event_risk.json")
        if BOT_UD is not None:
            try:
                t = BOT_UD / "event_risk.json.tmp"; t.write_text(payload); t.replace(BOT_UD / "event_risk.json")
            except Exception as e:  # noqa: BLE001
                print(f"[fast] bot copy failed: {e}")
        print("[fast] event_risk.json direction_gate updated")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
