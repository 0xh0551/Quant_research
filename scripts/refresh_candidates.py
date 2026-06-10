#!/usr/bin/env python3
"""رفرش مانیفستِ کاندیداهای OOS-مثبت و کپی به مسیرِ بات‌های noches.

walk-forward scan را روی data/processed اجرا و نتیجه را در دو مکان می‌نویسد:
  - outputs/wf_candidates.json                (داخل Quant_research)
  - <noches>/user_data/wf_candidates.json     (برای QuantResearchBridge)

اجرا:
  .venv/bin/python scripts/refresh_candidates.py --symbols BTCUSDT SOLUSDT
کرانِ پیشنهادی (هفتگی): یکشنبه‌ها بعد از هایپراپت شبانه.
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.wf_scan import scan_processed_dir, write_manifest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "SOLUSDT"])
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "wf_candidates.json"))
    ap.add_argument("--noches", default="/home/h0551user/noches/user_data/wf_candidates.json",
                    help="مقصد کپی برای بات‌ها (خالی = کپی نکن)")
    ap.add_argument("--min-positive-frac", type=float, default=0.55)
    args = ap.parse_args()

    results = scan_processed_dir(
        Path(args.processed),
        only_symbols=args.symbols or None,
        min_positive_frac=args.min_positive_frac,
    )
    out = write_manifest(results, Path(args.out))
    n_pass = sum(1 for r in results if r.passed)
    print(f"scanned={len(results)} passed={n_pass} -> {out}")

    if args.noches:
        dest = Path(args.noches)
        if dest.parent.exists():
            shutil.copy(out, dest)
            print(f"copied manifest -> {dest}")
        else:
            print(f"skip noches copy (missing dir): {dest.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
