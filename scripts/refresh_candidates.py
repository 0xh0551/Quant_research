#!/usr/bin/env python3
"""رفرشِ خودکارِ مانیفستِ کاندیداهای OOS-مثبت + گزارشِ لبه‌ها.

walk-forward scan را روی data/processed (همهٔ صرافی‌ها/تایم‌فریم‌های دانلودشده)
اجرا می‌کند و خروجی را در چند مکان می‌نویسد:
  - outputs/wf_candidates.json            مانیفستِ بات (QuantResearchBridge)
  - outputs/wf_report.json + wf_history.jsonl   گزارش/تاریخچهٔ داشبورد QR
  - <noches>/user_data/wf_candidates.json       مصرفِ بات‌های زنده
  - <soodo>/app_db/qr_report.json               گزارش برای ادمین soodo

اجرا (روزانه): .venv/bin/python scripts/refresh_candidates.py

تایم‌فریمِ خودکار: اسکن همهٔ تایم‌فریم‌ها را بررسی می‌کند؛ بهترین تایم‌فریمِ
مجموعه‌ای برای جفت‌های Mickey (ماکزیمم‌کردنِ مجموعِ Sharpeِ OOS) به‌طورِ
خودکار انتخاب می‌شود. اگر تایم‌فریم تغییر کند، mickey.env به‌روز می‌شود و
Mickey با `docker compose up -d` بازسازی می‌شود (نه فقط restart). اگر فقط
استراتژی/جهت تغییر کند، `docker restart Mickey` کافی است.
"""
import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.wf_scan import (  # noqa: E402
    scan_processed_dir, write_manifest, build_report, write_report,
)

# امضای پلنِ زنده: تنها وقتی این عوض شود، بات ری‌استارت یا بازسازی می‌شود.
SIG_PATH = ROOT / "outputs" / ".live_plan_sig.json"
MICKEY_ENV_PATH = Path("/home/h0551user/noches/mickey.env")
NOCHES_DIR = Path("/home/h0551user/noches")


def _copy(src: Path, dest: Path, label: str) -> None:
    if dest.parent.exists():
        shutil.copy(src, dest)
        print(f"copied {label} -> {dest}")
    else:
        print(f"skip {label} copy (missing dir): {dest.parent}")


def _norm_sym(sym: str) -> str:
    return sym.replace("/", "").replace(":USDT", "").replace(":BTC", "").replace(":ETH", "")


def _best_collective_timeframe(results: list, pairs: list[str] | None) -> str:
    """بهترین تایم‌فریمِ مجموعه‌ای: ماکزیمم‌کردنِ مجموعِ بهترین Sharpe برای هر جفت."""
    norm = {_norm_sym(p) for p in (pairs or [])} if pairs else set()
    best_per: dict[tuple, float] = {}
    for c in results:
        if not c.get("passed"):
            continue
        sym = _norm_sym(c.get("symbol", ""))
        if norm and sym not in norm:
            continue
        key = (sym, c.get("timeframe", ""))
        best_per[key] = max(best_per.get(key, 0.0), c.get("oos_sharpe", 0.0))
    tf_total: dict[str, float] = defaultdict(float)
    for (_, tf), sh in best_per.items():
        tf_total[tf] += sh
    return max(tf_total, key=lambda t: tf_total[t]) if tf_total else "4h"


def _plan_signature(report: dict, pairs: list[str] | None) -> dict:
    """امضای پایدارِ پلنِ زنده: {symbol: [strategy, allow_short]} برای جفت‌های موردِ نظر."""
    plan = report.get("live_plan", {})
    sig = {}
    for sym, p in plan.items():
        if pairs and _norm_sym(sym) not in {_norm_sym(p2) for p2 in pairs}:
            continue
        sig[sym] = [p.get("strategy"), bool(p.get("allow_short"))]
    return sig


def _read_stored_sig() -> tuple[dict, str]:
    """بارگذاریِ امضا و تایم‌فریمِ ذخیره‌شده."""
    if not SIG_PATH.exists():
        return {}, "4h"
    try:
        stored = json.loads(SIG_PATH.read_text(encoding="utf-8"))
        tf = stored.pop("__timeframe__", "4h")
        return stored, tf
    except Exception:
        return {}, "4h"


def _write_mickey_env(tf: str) -> None:
    """به‌روزرسانیِ QR_TIMEFRAME در mickey.env."""
    if not MICKEY_ENV_PATH.exists():
        return
    lines = [ln for ln in MICKEY_ENV_PATH.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("QR_TIMEFRAME=")]
    lines.append(f"QR_TIMEFRAME={tf}")
    MICKEY_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"updated mickey.env → QR_TIMEFRAME={tf}")


def _maybe_reload_mickey(results: list, report: dict, pairs: list[str] | None, force: bool) -> None:
    best_tf = _best_collective_timeframe(results, pairs)
    new_sig = _plan_signature(report, pairs)
    old_sig, old_tf = _read_stored_sig()

    tf_changed = best_tf != old_tf
    plan_changed = new_sig != old_sig

    if not force and not tf_changed and not plan_changed:
        print(f"Mickey unchanged (tf={best_tf}, plan={new_sig}) — no restart needed.")
        return

    stored = {"__timeframe__": best_tf, **new_sig}

    if tf_changed:
        print(f"Mickey timeframe: {old_tf} → {best_tf}  (writing mickey.env + recreate)")
        _write_mickey_env(best_tf)
        try:
            subprocess.run(
                ["docker", "compose", "up", "-d", "Mickey"],
                check=True, timeout=180, cwd=str(NOCHES_DIR),
            )
            print(f"recreated Mickey with QR_TIMEFRAME={best_tf}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Mickey recreate failed: {exc}")
    else:
        print(f"Mickey plan changed (same tf={best_tf}): {old_sig} → {new_sig}")
        try:
            subprocess.run(["docker", "restart", "Mickey"], check=True, timeout=120)
            print("reloaded Mickey (docker restart)")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: reload Mickey failed: {exc}")

    SIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIG_PATH.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="فیلتر symbol (خالی = همهٔ دانلودشده‌ها)")
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "wf_candidates.json"))
    ap.add_argument("--report", default=str(ROOT / "outputs" / "wf_report.json"))
    ap.add_argument("--history", default=str(ROOT / "outputs" / "wf_history.jsonl"))
    ap.add_argument("--noches", default="/home/h0551user/noches/user_data/wf_candidates.json",
                    help="مقصدِ مانیفست برای بات‌ها (خالی = کپی نکن)")
    ap.add_argument("--soodo-report", default="/home/h0551user/soodo/app_db/qr_report.json",
                    help="مقصدِ گزارش برای ادمین soodo (خالی = کپی نکن)")
    ap.add_argument("--live-timeframe", default="4h",
                    help="تایم‌فریمی که بات زنده اجرا می‌کند (مبنای هشدارِ tfِ بهتر)")
    ap.add_argument("--min-positive-frac", type=float, default=0.55)
    ap.add_argument("--reload-mickey", action="store_true",
                    help="اگر پلنِ زندهٔ جفت‌های Mickey عوض شد، کانتینر را ری‌استارت کن")
    ap.add_argument("--mickey-pairs", nargs="*",
                    default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"],
                    help="جفت‌هایی که تغییرِ پلنِ آن‌ها باعثِ ری‌استارتِ Mickey می‌شود")
    ap.add_argument("--force-reload", action="store_true",
                    help="بدونِ بررسیِ تغییر، همیشه Mickey را ری‌استارت کن")
    args = ap.parse_args()

    results = scan_processed_dir(
        Path(args.processed),
        only_symbols=args.symbols or None,
        min_positive_frac=args.min_positive_frac,
    )
    out = write_manifest(results, Path(args.out))

    # تایم‌فریمِ خودکار: اگر reload-mickey فعال است، بهترین tf را انتخاب کن.
    live_tf = args.live_timeframe
    if args.reload_mickey or args.force_reload:
        detected = _best_collective_timeframe(results, args.mickey_pairs)
        if detected != live_tf:
            print(f"auto-tf: {live_tf} → {detected} (better collective Sharpe for Mickey pairs)")
        live_tf = detected

    report = build_report(results, live_timeframe=live_tf)
    rep = write_report(report, Path(args.report), Path(args.history))

    n_pass = report["n_passed"]
    n_alerts = len(report["alerts"])
    tf_brk = " ".join(f"{tf}:{d['passed']}/{d['scanned']}"
                      for tf, d in sorted(report["by_timeframe"].items()))
    print(f"scanned={len(results)} passed={n_pass} alerts={n_alerts}")
    print(f"by_timeframe: {tf_brk}")
    print(f"manifest -> {out}")
    print(f"report   -> {rep}")
    for a in report["alerts"]:
        print(f"  ALERT  {a['message']}")

    if args.noches:
        _copy(out, Path(args.noches), "manifest")
    if args.soodo_report:
        _copy(rep, Path(args.soodo_report), "report")

    if args.reload_mickey or args.force_reload:
        _maybe_reload_mickey(results, report, args.mickey_pairs, args.force_reload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
