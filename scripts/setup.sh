#!/usr/bin/env bash
# ============================================================================
# Quant Research — installer / first-run setup.
# Installs dependencies, then asks which language the dashboard should default
# to and persists the choice to configs/app.json (read by GET /api/config).
#
# Usage:
#   ./scripts/setup.sh                 # interactive
#   QR_DEFAULT_LANG=en ./scripts/setup.sh   # non-interactive (en|fa)
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$ROOT/configs/app.json"

echo "▸ Installing dependencies…"
if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT" && uv sync --extra dev)
else
    echo "  (uv not found — skipping dependency install; run 'make install' later)"
fi

# ── choose default language ────────────────────────────────────────────────
lang="${QR_DEFAULT_LANG:-}"

if [ -z "$lang" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "Choose the dashboard's default language / زبان پیش‌فرض داشبورد را انتخاب کنید:"
        echo "  [1] English"
        echo "  [2] فارسی (Persian)"
        printf "Selection [1/2] (default 1): "
        read -r choice || choice=""
        case "$choice" in
            2|fa|FA|persian|farsi) lang="fa" ;;
            *) lang="en" ;;
        esac
    else
        lang="fa"   # no TTY → keep the historical default
    fi
fi

case "$lang" in en|fa) ;; *) lang="en" ;; esac

mkdir -p "$ROOT/configs"
printf '{\n  "default_language": "%s"\n}\n' "$lang" > "$CFG"

echo ""
echo "✓ Default language set to '$lang'  →  $CFG"
echo "✓ Setup complete. Start the dashboard with:  make web"
