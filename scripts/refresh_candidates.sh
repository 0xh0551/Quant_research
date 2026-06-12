#!/usr/bin/env bash
# پایپ‌لاینِ روزانهٔ لبه‌ها روی هاست (cron):
#   1) رفرشِ افزایشیِ دیتا (کندل‌های تازه)  ← لبه‌ها بیات نشوند
#   2) اسکنِ walk-forward + نوشتن manifest/report + کپی به noches و soodo
#   3) ری‌استارتِ Mickey/Wall_E فقط اگر پلنِ زندهٔ جفت‌هایشان عوض شده باشد
#   4) چرخش جفت‌ارز Gadget/Klaymen از روی امتیاز سازگاری RL/ML (با هیسترزیس)
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
  if ! "$PY" scripts/refresh_candidates.py --reload-mickey --reload-walle "$@"; then
    OK=false; FAILED="\"wf_scan\""
    echo "FAIL: pipeline failed at step wf_scan"
  fi
  # چرخش جفت‌ارز بات‌های RL/ML (Gadget/Klaymen) — هیسترزیس + ری‌استارت فقط در صورت تعویض
  st_run "pair_rotation"
  if ! "$PY" scripts/rotate_bot_pairs.py --apply; then
    OK=false; [ "$FAILED" = null ] && FAILED="\"pair_rotation\""
    echo "FAIL: pair rotation failed"
  fi
  st_end "$OK" "$FAILED"
} >> logs/refresh_candidates.log 2>&1
