#!/usr/bin/env bash
# پایپ‌لاینِ روزانهٔ لبه‌ها روی هاست (cron):
#   1) رفرشِ افزایشیِ دیتا (کندل‌های تازه)  ← لبه‌ها بیات نشوند
#   2) اسکنِ walk-forward + نوشتن manifest/report + کپی به noches و soodo
#   3) چرخش جفت‌ارز bot3/bot4/bot1/bot6 از روی امتیاز سازگاری RL/ML (با هیسترزیس)
# وضعیت اجرا در outputs/pipeline_status.json نوشته می‌شود تا داشبوردِ
# hnarimani («مانیتور مرکزی → Quant Research») بداند الان چه می‌گذرد.
set -uo pipefail

ROOT="/home/h0551user/Quant_research"
cd "$ROOT"
mkdir -p logs outputs
PY="$ROOT/.venv/bin/python"
STATUS="$ROOT/outputs/pipeline_status.json"
STARTED="$(date -Is)"
STEP="init"

st_run() {  # $1 = نام مرحلهٔ در حال اجرا
  STEP="$1"
  printf '{"state":"running","step":"%s","started_at":"%s"}\n' "$STEP" "$STARTED" > "$STATUS"
}
st_end() {  # $1 = true/false  $2 = failed step ("null" یا "\"step\"")
  printf '{"state":"idle","last_run":{"started_at":"%s","finished_at":"%s","ok":%s,"failed_step":%s}}\n' \
    "$STARTED" "$(date -Is)" "$1" "$2" > "$STATUS"
}

{
  echo "===== refresh $STARTED ====="
  st_run "data_refresh"
  if ! "$PY" scripts/refresh_data.py; then
    echo "WARN: data refresh had errors (continuing)"
  fi
  OK=true; FAILED=null
  st_run "wf_scan"
  # توجه: «--reload-bot6» حذف شد — bot6 دیگر با گیتِ سخت‌گیرِ deployable مستقر
  # نمی‌شود (که مدام فلتش می‌کرد). هم bot6 هم bot5 با پروفایلِ پرتکرار در
  # مرحلهٔ qr_bridge_refresh مدیریت می‌شوند. wf_scan فقط اسکن + dashboard را می‌نویسد.
  if ! "$PY" scripts/refresh_candidates.py "$@"; then
    OK=false; FAILED="\"wf_scan\""
    echo "FAIL: pipeline failed at step wf_scan"
  fi
  # چرخش جفت‌ارز بات‌های RL/ML (bot3/bot4/bot1) — هیسترزیس + ری‌استارت فقط در صورت تعویض
  st_run "pair_rotation"
  if ! "$PY" scripts/rotate_bot_pairs.py --apply; then
    OK=false; [ "$FAILED" = null ] && FAILED="\"pair_rotation\""
    echo "FAIL: pair rotation failed"
  fi
  # bot5 (gate) + bot6 (hyperliquid): بریجِ کوانتِ پرتکرار روی 15m — انتخابِ
  # پروفایلِ پرتکرار + فیلترِ نقدینگی از همین اسکن، با هیسترزیس (ری‌استارت فقط در
  # صورتِ تغییرِ پلن). جزئیات: scripts/refresh_qr_bridge.py
  st_run "qr_bridge_refresh"
  if ! "$PY" scripts/refresh_qr_bridge.py --bot all --apply; then
    OK=false; [ "$FAILED" = null ] && FAILED="\"qr_bridge_refresh\""
    echo "FAIL: qr bridge refresh failed"
  fi
  st_end "$OK" "$FAILED"
} >> logs/refresh_candidates.log 2>&1
