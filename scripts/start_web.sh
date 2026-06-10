#!/usr/bin/env bash
# راه‌اندازی سرورِ وبِ QR (FastAPI / uvicorn) با مدیریتِ PID.
# استفاده: ./scripts/start_web.sh [--force]
# crontab: @reboot /home/h0551user/Quant_research/scripts/start_web.sh
set -euo pipefail

ROOT="/home/h0551user/Quant_research"
PID_FILE="/tmp/qr_web.pid"
LOG="$ROOT/logs/web.log"
PY="$ROOT/.venv/bin/python"

mkdir -p "$ROOT/logs"

# متوقف‌کردنِ نمونهٔ قبلی
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "stopping old QR web (PID $OLD_PID)…"
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi
# fallback: کشتنِ هر uvicorn روی پورت ۸۰۰۰
pkill -f "uvicorn src.web.app:app" 2>/dev/null || true
sleep 0.5

cd "$ROOT"
nohup "$PY" -m uvicorn src.web.app:app \
    --host 0.0.0.0 --port 8000 \
    >> "$LOG" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
echo "QR web server started (PID $NEW_PID) — logs: $LOG"
