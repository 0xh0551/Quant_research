#!/usr/bin/env python3
"""Reseed یک‌بارهٔ whitelist بات bot2 به ۶ جفتِ برترِ زندهٔ کوانت (RL fitness +
feedback + money-flow، با فیلتر نقدینگیِ bybit) — برای خروج فوری از سبدِ ضعیفِ فعلی
(SOL/BTC رتبهٔ ته‌جدول) به‌جای انتظارِ مسیر کندِ هیسترزیسِ شبانه.

پس از این، چرخشِ معمول (rotate_bot_pairs.py، cron هر ۴ساعت + شبانه) با dwell=10روز
سکان را به دست می‌گیرد. این اسکریپت idempotent نیست؛ یک‌بار اجرا و تمام.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.rotate_bot_pairs as R  # noqa: E402

BOT = "bot2"
spec = R.BOTS[BOT]
processed = ROOT / "data" / "processed"

# 1) ایمنی: پوزیشن باز نباید قطع شود
open_pairs = R.open_trade_pairs(spec["sqlite"])
if open_pairs:
    print(f"ABORT: open trades present {open_pairs} — reseed لغو شد (جفتِ بازدار حذف نمی‌شود)")
    sys.exit(1)

# 2) امتیازدهیِ زنده، دقیقاً مثل مسیر main (fitness → feedback → money-flow)
table = R.score_table(spec, processed)
perf = R.realized_performance(spec["sqlite"])
R.apply_feedback(table, perf)
mf = R.recommend_money_flow_coins(processed, venues=spec["score_venues"],
                                  timeframe=spec["score_timeframe"])
R.apply_money_flow(table, mf, spec.get("quote", "USDT"))

ranked = sorted(table.items(), key=lambda kv: kv[1]["score"], reverse=True)
quote = spec.get("quote", "USDT")
new_wl = [R._pair_of(b, quote) for b, _ in ranked[: spec["n_pairs"]]]

held = R.read_whitelist(spec["config"])
pairs_out = [p for p in held if p not in new_wl]
pairs_kept = [p for p in held if p in new_wl]
pairs_new = [p for p in new_wl if p not in held]

print(f"held now : {held}")
print(f"new wl   : {new_wl}")
print(f"  kept   : {pairs_kept}  (مدلشان حفظ می‌شود)")
print(f"  dropped: {pairs_out}   (مدلشان پاک می‌شود)")
print(f"  fresh  : {pairs_new}   (cold-start؛ FreqAI روی دیتای تاریخی آموزش می‌بیند)")
print(f"  scores : {[(b, v['score']) for b, v in ranked[: spec['n_pairs']]]}")

# 3) اعمال: stop → نوشتن whitelist + پاکسازی مدلِ جفت‌های خروجی → start
R._docker("stop", spec["container"], timeout=240)
try:
    R.write_whitelist(spec["config"], new_wl)
    for p in pairs_out:
        R.cleanup_pair_models(spec, p)
        print(f"  cleaned models for {p}")
finally:
    R._docker("start", spec["container"], timeout=120)
print("container restarted.")

# 4) seed کردن state تا dwell=10روز جفت‌های تازه را محافظت کند (وگرنه assigned_at
#    نامعلوم = قدیمی فرض می‌شود و دورِ بعد ممکن است churn کند)
now = R._now()
st = R.load_state()
st[BOT] = {
    "assignments": {
        p: {"assigned_at": now, "source": "reseed",
            "last_score": table.get(R._base_of(p), {}).get("score"), "score_at": now}
        for p in new_wl},
    "streaks": {},
}
R.save_state(st)
print(f"state seeded for {BOT}: {list(st[BOT]['assignments'])}")
print("DONE.")
