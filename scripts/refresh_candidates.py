#!/usr/bin/env python3
"""رفرشِ خودکارِ مانیفستِ کاندیداهای OOS-مثبت + گزارشِ لبه‌ها.

walk-forward scan را روی data/processed (همهٔ صرافی‌ها/تایم‌فریم‌های دانلودشده)
اجرا می‌کند و خروجی را در چند مکان می‌نویسد:
  - outputs/wf_candidates.json            مانیفستِ بات (QuantResearchBridge)
  - outputs/wf_report.json + wf_history.jsonl   گزارش/تاریخچهٔ داشبورد QR
  - <noches>/user_data/wf_candidates.json       مصرفِ Mickey
  - <noches>/user_data/wf_candidates_walle.json مصرفِ Wall_E
  - <soodo>/app_db/qr_report.json               گزارش برای ادمین soodo

انتخابِ خودکارِ جفت‌ها (--top-n):
  پس از اسکن، N جفتِ برتر بر اساسِ بهترین Sharpe OOS (در هر تایم‌فریم) انتخاب می‌شوند.
  whitelist هر دو بات (Mickey → Gate USDT، Wall_E → Hyperliquid USDC) به‌صورتِ
  خودکار در فایلِ کانفیگ نوشته می‌شود.

تایم‌فریمِ خودکار:
  بهترین تایم‌فریمِ مجموعه‌ای (ماکزیمم‌کردنِ مجموعِ Sharpe) انتخاب و در mickey.env /
  walle.env نوشته می‌شود. اگر تایم‌فریم عوض شد: docker compose up -d (recreate).
  اگر فقط استراتژی عوض شد: docker restart (سریع‌تر).
"""
import argparse
import json
import re
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

SIG_PATH = ROOT / "outputs" / ".live_plan_sig.json"
WALLE_SIG_PATH = ROOT / "outputs" / ".walle_plan_sig.json"

NOCHES_DIR = Path("/home/h0551user/noches")
MICKEY_ENV_PATH = NOCHES_DIR / "mickey.env"
WALLE_ENV_PATH = NOCHES_DIR / "walle.env"
MICKEY_CONFIG_PATH = NOCHES_DIR / "user_data" / "mickey_config.json"
WALLE_CONFIG_PATH = NOCHES_DIR / "user_data" / "walle_config.json"
WALLE_MANIFEST_PATH = NOCHES_DIR / "user_data" / "wf_candidates_walle.json"


# ── symbol helpers ─────────────────────────────────────────────────────────────

def _norm_sym(sym: str) -> str:
    """نرمال‌سازی به base: 'BTCUSDT', 'BTC/USDT:USDT', 'BTCUSDC' → 'BTC'"""
    s = sym.split("/")[0].split(":")[0].upper()
    for q in ("USDT", "USDC", "BUSD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _to_gate_pair(base: str) -> str:
    return f"{_norm_sym(base)}/USDT:USDT"


def _to_hyperliquid_pair(base: str) -> str:
    return f"{_norm_sym(base)}/USDC:USDC"


# ── best pairs / timeframe selection ──────────────────────────────────────────

def _best_n_pairs(results: list, n: int = 5) -> list[str]:
    """N base symbol برتر بر اساسِ بهترین Sharpe OOS (هر تایم‌فریم/استراتژی)."""
    best: dict[str, float] = {}
    for c in results:
        if not c.get("passed"):
            continue
        base = _norm_sym(c.get("symbol", ""))
        if not base:
            continue
        best[base] = max(best.get(base, 0.0), c.get("oos_sharpe", 0.0))
    return sorted(best, key=lambda s: -best[s])[:n]


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
    """امضای پایدارِ پلنِ زنده: {base: [strategy, allow_short]}"""
    plan = report.get("live_plan", {})
    norm_pairs = {_norm_sym(p) for p in pairs} if pairs else None
    sig = {}
    for sym, p in plan.items():
        base = _norm_sym(sym)
        if norm_pairs and base not in norm_pairs:
            continue
        sig[base] = [p.get("strategy"), bool(p.get("allow_short"))]
    return sig


# ── config whitelist update ────────────────────────────────────────────────────

def _update_config_whitelist(config_path: Path, pairs: list[str]) -> None:
    """به‌روزرسانیِ pair_whitelist در کانفیگِ freqtrade (با comments هم کار می‌کند)."""
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    formatted = ",\n            ".join(f'"{p}"' for p in pairs)
    new_text = re.sub(
        r'"pair_whitelist"\s*:\s*\[[^\]]*?\]',
        f'"pair_whitelist": [\n            {formatted}\n        ]',
        text,
        flags=re.DOTALL,
    )
    if new_text != text:
        config_path.write_text(new_text, encoding="utf-8")
        print(f"  whitelist → {config_path.name}: {pairs}")
    else:
        print(f"  WARN: pair_whitelist pattern not found in {config_path.name}")


# ── sig store ──────────────────────────────────────────────────────────────────

def _read_sig(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, "4h"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        tf = stored.pop("__timeframe__", "4h")
        return stored, tf
    except Exception:
        return {}, "4h"


def _write_sig(path: Path, tf: str, plan_sig: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"__timeframe__": tf, **plan_sig}, ensure_ascii=False),
        encoding="utf-8",
    )


# ── env file update ────────────────────────────────────────────────────────────

def _write_env_tf(env_path: Path, tf: str) -> None:
    if not env_path.exists():
        return
    lines = [ln for ln in env_path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("QR_TIMEFRAME=")]
    lines.append(f"QR_TIMEFRAME={tf}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  updated {env_path.name} → QR_TIMEFRAME={tf}")


def _copy(src: Path, dest: Path, label: str) -> None:
    if dest.parent.exists():
        shutil.copy(src, dest)
        print(f"copied {label} -> {dest}")
    else:
        print(f"skip {label} copy (missing dir): {dest.parent}")


# ── generic bot reload ─────────────────────────────────────────────────────────

def _maybe_reload_bot(
    *,
    bot_name: str,
    results: list,
    report: dict,
    pairs: list[str] | None,
    force: bool,
    env_path: Path,
    config_path: Path,
    manifest_src: Path,
    manifest_dst: Path | None,
    sig_path: Path,
    pair_formatter,
) -> None:
    best_tf = _best_collective_timeframe(results, pairs)
    best_bases = pairs if pairs is not None else _best_n_pairs(results)
    new_sig = _plan_signature(report, best_bases)
    old_sig, old_tf = _read_sig(sig_path)

    tf_changed = best_tf != old_tf
    plan_changed = new_sig != old_sig

    # همیشه whitelist و manifest رو به‌روز کن (حتی اگر restart نشود)
    if best_bases and config_path.exists():
        _update_config_whitelist(config_path, [pair_formatter(b) for b in best_bases])
    if manifest_dst is not None:
        _copy(manifest_src, manifest_dst, f"{bot_name} manifest")

    if not force and not tf_changed and not plan_changed:
        print(f"{bot_name} unchanged (tf={best_tf}) — no restart needed.")
        return

    if tf_changed:
        print(f"{bot_name} timeframe: {old_tf} → {best_tf}  (env update + recreate)")
        _write_env_tf(env_path, best_tf)
        try:
            subprocess.run(
                ["docker", "compose", "up", "-d", bot_name],
                check=True, timeout=180, cwd=str(NOCHES_DIR),
            )
            print(f"  reloaded {bot_name} (docker compose up -d)")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: {bot_name} recreate failed: {exc}")
    else:
        print(f"{bot_name} plan changed (same tf={best_tf}) → docker restart")
        try:
            subprocess.run(["docker", "restart", bot_name], check=True, timeout=120)
            print(f"  reloaded {bot_name} (docker restart)")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: {bot_name} restart failed: {exc}")

    _write_sig(sig_path, best_tf, new_sig)


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "wf_candidates.json"))
    ap.add_argument("--report", default=str(ROOT / "outputs" / "wf_report.json"))
    ap.add_argument("--history", default=str(ROOT / "outputs" / "wf_history.jsonl"))
    ap.add_argument("--noches", default="/home/h0551user/noches/user_data/wf_candidates.json")
    ap.add_argument("--soodo-report", default="/home/h0551user/soodo/app_db/qr_report.json")
    ap.add_argument("--live-timeframe", default="4h")
    ap.add_argument("--min-positive-frac", type=float, default=0.55)
    ap.add_argument("--top-n", type=int, default=5,
                    help="N جفتِ برتر برای whitelist بات‌ها")
    # Mickey
    ap.add_argument("--reload-mickey", action="store_true")
    ap.add_argument("--mickey-pairs", nargs="*", default=None,
                    help="اگر تعیین شود، whitelist ثابت می‌ماند؛ خالی = auto top-N")
    ap.add_argument("--force-reload", action="store_true")
    # Wall_E
    ap.add_argument("--reload-walle", action="store_true")
    ap.add_argument("--walle-pairs", nargs="*", default=None,
                    help="جفت‌های Wall_E (base مثل BTC)؛ خالی = auto top-N")
    ap.add_argument("--force-reload-walle", action="store_true")
    args = ap.parse_args()

    results = scan_processed_dir(
        Path(args.processed),
        only_symbols=args.symbols or None,
        min_positive_frac=args.min_positive_frac,
    )
    out = write_manifest(results, Path(args.out))

    # تایم‌فریم و جفت‌های خودکار
    live_tf = args.live_timeframe
    if args.reload_mickey or args.force_reload:
        auto_pairs = args.mickey_pairs or _best_n_pairs(results, n=args.top_n)
        detected_tf = _best_collective_timeframe(results, auto_pairs)
        if detected_tf != live_tf:
            print(f"auto-tf: {live_tf} → {detected_tf}")
        live_tf = detected_tf
        args.mickey_pairs = auto_pairs

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

    if args.soodo_report:
        _copy(rep, Path(args.soodo_report), "report")

    if args.reload_mickey or args.force_reload:
        _maybe_reload_bot(
            bot_name="Mickey",
            results=results,
            report=report,
            pairs=args.mickey_pairs,
            force=args.force_reload,
            env_path=MICKEY_ENV_PATH,
            config_path=MICKEY_CONFIG_PATH,
            manifest_src=out,
            manifest_dst=Path(args.noches) if args.noches else None,
            sig_path=SIG_PATH,
            pair_formatter=_to_gate_pair,
        )
    elif args.noches:
        _copy(out, Path(args.noches), "Mickey manifest")

    if args.reload_walle or args.force_reload_walle:
        walle_pairs = args.walle_pairs or _best_n_pairs(results, n=args.top_n)
        _maybe_reload_bot(
            bot_name="Wall_E",
            results=results,
            report=report,
            pairs=walle_pairs,
            force=args.force_reload_walle,
            env_path=WALLE_ENV_PATH,
            config_path=WALLE_CONFIG_PATH,
            manifest_src=out,
            manifest_dst=WALLE_MANIFEST_PATH,
            sig_path=WALLE_SIG_PATH,
            pair_formatter=_to_hyperliquid_pair,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
