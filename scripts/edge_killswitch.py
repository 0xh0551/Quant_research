#!/usr/bin/env python3
"""کیل‌سوییچِ لبه‌های زنده — «ارزان‌ترین بیمه در برابر لبه‌ای که مرده ولی هنوز ترید می‌کند».

هر ساعت (cron) برای هر بات (Mickey/Wall_E):
  - از مانیفستِ مستقرِ بات، قاعده‌های زنده (بدون killed) را می‌خواند.
  - PnL واقعیِ هر جفت از sqlite فریک‌ترید از لحظهٔ deployed_at جمع می‌شود
    (مجموع close_profit تریدهای بسته؛ محافظه‌کارانه — unrealized حساب نمی‌شود).
  - باندِ پایینِ انتظار از توزیع بازده OOS همان قاعده ساخته می‌شود:
        band = mu_bar*h − Z*sigma_bar*sqrt(h)      (Z=1.645 ≈ صدک ۵)
    h = تعداد کندل‌های سپری‌شده از استقرار.
  - اگر realized < band (و حداقل MIN_TRADES ترید بسته و MIN_BARS کندل گذشته):
    قاعده در مانیفست killed می‌شود (Bridge: ورود بسته + خروج اجباری)،
    در outputs/edge_kills.json ثبت و بات ری‌استارت می‌شود.

کیل تا اسکنِ سالمِ بعدی + حداقل ۲۴ ساعت فعال می‌ماند (refresh_candidates آن را
از انتخاب کنار می‌گذارد و بعد از انقضا دوباره قضاوت می‌کند).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
KILLS_PATH = OUT / "edge_kills.json"
NOCHES_USER_DATA = Path("/home/h0551user/noches/user_data")

Z_SCORE = 1.645      # صدک ۵ یک‌طرفه
MIN_BARS = 42        # حداقل کندل از استقرار (۷ روز در 4h) قبل از قضاوت
MIN_TRADES = 3       # حداقل تریدِ بسته — جلوی کیلِ کاذبِ قاعده‌های کم‌ترید را می‌گیرد

TF_HOURS = {"15m": 0.25, "30m": 0.5, "1h": 1.0, "2h": 2.0, "4h": 4.0, "1d": 24.0}

BOTS = {
    "Mickey": {
        "manifest": NOCHES_USER_DATA / "wf_candidates.json",
        "db": NOCHES_USER_DATA / "mickey.sqlite",
    },
    "Wall_E": {
        "manifest": NOCHES_USER_DATA / "wf_candidates_walle.json",
        "db": NOCHES_USER_DATA / "walle.sqlite",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_sym(sym: str) -> str:
    s = sym.split("/")[0].split(":")[0].upper()
    for q in ("USDT", "USDC", "BUSD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _realized(db_path: Path, base: str, since_iso: str) -> tuple[float, int]:
    """مجموع close_profit (کسر) و تعداد تریدهای بستهٔ این base از since."""
    since_sql = since_iso.replace("T", " ").split("+")[0].split(".")[0]
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        row = con.execute(
            "SELECT COALESCE(SUM(close_profit),0), COUNT(*) FROM trades "
            "WHERE is_open=0 AND close_date >= ? AND pair LIKE ?",
            (since_sql, f"{base}/%"),
        ).fetchone()
        return float(row[0] or 0.0), int(row[1] or 0)
    finally:
        con.close()


def _load_kills() -> dict:
    try:
        return json.loads(KILLS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"kills": []}


def check_bot(name: str, cfg: dict, kills: dict) -> bool:
    """True اگر چیزی کشته شد (نیاز به ری‌استارت)."""
    manifest_path: Path = cfg["manifest"]
    db_path: Path = cfg["db"]
    if not manifest_path.exists() or not db_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{name}: manifest unreadable ({exc})")
        return False

    changed = False
    now = _now()
    for c in manifest.get("candidates", []):
        if c.get("killed"):
            continue
        base = _norm_sym(c.get("symbol", ""))
        deployed_at = c.get("deployed_at")
        mu = c.get("oos_mu_bar") or 0.0
        sigma = c.get("oos_sigma_bar") or 0.0
        tf_h = TF_HOURS.get(c.get("timeframe", "4h"), 4.0)
        if not base or not deployed_at or sigma <= 0:
            continue
        try:
            t0 = datetime.fromisoformat(deployed_at)
        except Exception:
            continue
        h = (now - t0).total_seconds() / 3600.0 / tf_h
        if h < MIN_BARS:
            continue
        realized, n_trades = _realized(db_path, base, deployed_at)
        if n_trades < MIN_TRADES:
            continue
        band = mu * h - Z_SCORE * sigma * (h ** 0.5)
        if realized < band:
            print(f"{name}/{base}: KILL — realized={realized:.4f} < band={band:.4f} "
                  f"(h={h:.0f} bars, trades={n_trades}, rule={c.get('strategy')})")
            c["killed"] = True
            c["killed_at"] = now.isoformat()
            c["kill_reason"] = {
                "type": "below_expectation_band",
                "realized": round(realized, 5),
                "band_p5": round(band, 5),
                "bars_elapsed": round(h),
                "closed_trades": n_trades,
            }
            kills.setdefault("kills", []).append({
                "bot": name,
                "base": base,
                "strategy": c.get("strategy"),
                "allow_short": c.get("allow_short"),
                "killed_at": now.isoformat(),
                "realized": round(realized, 5),
                "band_p5": round(band, 5),
                "bars_elapsed": round(h),
                "closed_trades": n_trades,
            })
            changed = True
        else:
            print(f"{name}/{base}: ok — realized={realized:.4f} ≥ band={band:.4f} "
                  f"(h={h:.0f}, trades={n_trades})")

    if changed:
        manifest["generated_at"] = now.isoformat()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main() -> int:
    kills = _load_kills()
    any_change = False
    for name, cfg in BOTS.items():
        try:
            if check_bot(name, cfg, kills):
                any_change = True
                try:
                    subprocess.run(["docker", "restart", name], check=True, timeout=120)
                    print(f"{name}: restarted (kill applied)")
                except Exception as exc:  # noqa: BLE001
                    print(f"{name}: WARN restart failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: ERROR {exc}")
    if any_change:
        KILLS_PATH.write_text(json.dumps(kills, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    print(f"--- killswitch {datetime.now(timezone.utc).isoformat()} ---")
    sys.exit(main())
