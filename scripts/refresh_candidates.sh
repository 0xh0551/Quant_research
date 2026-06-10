#!/usr/bin/env bash
# پایپ‌لاینِ روزانهٔ لبه‌ها روی هاست (cron):
#   1) رفرشِ افزایشیِ دیتا (کندل‌های تازه)  ← لبه‌ها بیات نشوند
#   2) اسکنِ walk-forward + نوشتن manifest/report + کپی به noches و soodo
#   3) ری‌استارتِ Mickey فقط اگر پلنِ زندهٔ جفت‌هایش عوض شده باشد (نه طبقِ زمان‌بندیِ ثابت)
# تغییرِ تایم‌فریم اینجا اتفاق نمی‌افتد؛ فقط رفرشِ قواعدِ همان تایم‌فریمِ زنده.
set -euo pipefail

ROOT="/home/h0551user/Quant_research"
cd "$ROOT"
mkdir -p logs
PY="$ROOT/.venv/bin/python"

{
  echo "===== refresh $(date -Is) ====="
  echo "--- step 1: data refresh ---"
  "$PY" scripts/refresh_data.py || echo "WARN: data refresh had errors (continuing)"
  echo "--- step 2/3: scan + conditional reload ---"
  "$PY" scripts/refresh_candidates.py --reload-mickey "$@"
} >> logs/refresh_candidates.log 2>&1
