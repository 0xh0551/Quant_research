#!/usr/bin/env python3
"""رفرشِ خودکارِ مانیفستِ کاندیداهای OOS-مثبت + گزارشِ لبه‌ها.

walk-forward scan را روی data/processed (همهٔ صرافی‌ها/تایم‌فریم‌های دانلودشده)
اجرا می‌کند و خروجی را در چند مکان می‌نویسد:
  - outputs/wf_candidates.json            مانیفستِ بات (QuantResearchBridge)
  - outputs/wf_report.json + wf_history.jsonl   گزارش/تاریخچهٔ داشبورد QR
  - <noches>/user_data/wf_candidates.json       مصرفِ بات‌های زنده
  - <soodo>/app_db/qr_report.json               گزارش برای ادمین soodo

اجرا (هفتگی، بعد از هایپراپتِ شبانه):
  .venv/bin/python scripts/refresh_candidates.py

نکته دربارهٔ تایم‌فریم: اسکن همهٔ تایم‌فریم‌ها را بررسی می‌کند، اما بات زنده فقط
کاندیداهای `--live-timeframe` (پیش‌فرض 4h) را اجرا می‌کند. اگر لبهٔ قوی‌تری روی
تایم‌فریمِ دیگری پیدا شود، در گزارش به‌صورتِ «هشدار» می‌آید؛ تغییرِ تایم‌فریمِ بات
دستی/تأییدی است (نیازمند ری‌استارتِ کانتینر با کانفیگِ جدید) و خودکار نیست.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.wf_scan import (  # noqa: E402
    scan_processed_dir, write_manifest, build_report, write_report,
)

# امضای پلنِ زنده: تنها وقتی این عوض شود، بات ری‌استارت می‌شود (نه طبقِ یک زمان‌بندیِ ثابت).
SIG_PATH = ROOT / "outputs" / ".live_plan_sig.json"


def _copy(src: Path, dest: Path, label: str) -> None:
    if dest.parent.exists():
        shutil.copy(src, dest)
        print(f"copied {label} -> {dest}")
    else:
        print(f"skip {label} copy (missing dir): {dest.parent}")


def _plan_signature(report: dict, pairs: list[str] | None) -> dict:
    """امضای پایدارِ پلنِ زنده: {symbol: [strategy, allow_short]} برای جفت‌های موردِ نظر."""
    plan = report.get("live_plan", {})
    sig = {}
    for sym, p in plan.items():
        if pairs and sym not in pairs:
            continue
        sig[sym] = [p.get("strategy"), bool(p.get("allow_short"))]
    return sig


def _maybe_reload_mickey(report: dict, pairs: list[str] | None, force: bool) -> None:
    new_sig = _plan_signature(report, pairs)
    old_sig = {}
    if SIG_PATH.exists():
        try:
            old_sig = json.loads(SIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            old_sig = {}

    if not force and new_sig == old_sig:
        print(f"Mickey plan unchanged ({new_sig}) — no restart needed.")
        return

    print(f"Mickey plan changed: {old_sig} → {new_sig}")
    try:
        subprocess.run(["docker", "restart", "Mickey"], check=True, timeout=120)
        print("reloaded Mickey (docker restart)")
        SIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SIG_PATH.write_text(json.dumps(new_sig, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: reload Mickey failed: {exc}")


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
                    default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
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
    report = build_report(results, live_timeframe=args.live_timeframe)
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
        _maybe_reload_mickey(report, args.mickey_pairs, args.force_reload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
