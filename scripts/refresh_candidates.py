#!/usr/bin/env python3
"""رفرشِ خودکارِ مانیفستِ کاندیداهای OOS-مثبت + گزارشِ لبه‌ها + استقرارِ محافظت‌شده.

walk-forward scan را روی data/processed اجرا می‌کند و خروجی را می‌نویسد:
  - outputs/wf_candidates.json                  مخزن کامل پژوهشی (همهٔ passed ها)
  - outputs/wf_report.json + wf_history.jsonl   گزارش/تاریخچهٔ داشبورد QR
  - outputs/selection_state.json                وضعیت انتخاب/هیسترزیس (داشبورد)
  - <noches>/user_data/wf_candidates.json       مانیفستِ فیلترشدهٔ Mickey (پلن مستقر)
  - <noches>/user_data/wf_candidates_walle.json مانیفستِ فیلترشدهٔ Wall_E
  - <soodo>/app_db/qr_report.json               گزارش برای ادمین soodo

لایه‌های محافظ استقرار (در برابر نفرین برنده و تعقیب لبه):
  1) گیتِ استحکام (apply_robustness): سازگاری بین‌صرافی + ≥min_splits پنجرهٔ OOS
     + positive_frac سختگیرانه + Deflated Sharpe — فقط «deployable» ها قابل استقرارند.
  2) سبدِ کم‌همبسته: انتخاب حریصانه با سقف همبستگی + وزنِ inverse-vol×Sharpe
     (وزن در مانیفست می‌نشیند؛ Bridge با custom_stake_amount اعمالش می‌کند).
  3) هیسترزیس: پلنِ جدید فقط وقتی جایگزین می‌شود که switch_streak اسکنِ متوالی
     با حاشیهٔ switch_margin بهتر بماند. حذفِ قاعدهٔ مرده/کشته فوری است.
  4) کیل‌سوییچ (edge_killswitch.py): ارزِ کشته تا اسکنِ سالم بعدی + حداقل ۲۴h کنار می‌ماند.
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.wf_scan import (  # noqa: E402
    apply_robustness, build_report, scan_processed_dir, write_manifest, write_report,
)

OUT = ROOT / "outputs"
KILLS_PATH = OUT / "edge_kills.json"
SELECTION_STATE_PATH = OUT / "selection_state.json"

NOCHES_DIR = Path("/home/h0551user/noches")
WALLE_SIG_PATH    = OUT / ".walle_plan_sig.json"
WALLE_ENV_PATH    = NOCHES_DIR / "walle.env"
WALLE_CONFIG_PATH = NOCHES_DIR / "user_data" / "walle_config.json"
WALLE_MANIFEST_PATH = NOCHES_DIR / "user_data" / "wf_candidates_walle.json"

KILL_MIN_HOURS = 24  # کیل حداقل این‌قدر فعال می‌ماند، حتی اگر اسکن جدید پاکش کند


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── symbol helpers ─────────────────────────────────────────────────────────────

def _norm_sym(sym: str) -> str:
    """نرمال‌سازی به base: 'BTCUSDT', 'BTC/USDT:USDT', 'BTCUSDC' → 'BTC'"""
    s = sym.split("/")[0].split(":")[0].upper()
    for q in ("USDT", "USDC", "BUSD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


# ── portfolio selection (سبد کم‌همبسته + وزن) ─────────────────────────────────

def _best_per_base(pool: list, exclude: set[str]) -> dict:
    """بهترین کاندیدِ deployable هر base (اول DSR، بعد Sharpe)."""
    best: dict[str, object] = {}
    for r in pool:
        b = _norm_sym(r.symbol)
        if not b or b in exclude:
            continue
        cur = best.get(b)
        r_dsr = r.dsr if r.dsr == r.dsr else -1.0
        if cur is None:
            best[b] = r
            continue
        c_dsr = cur.dsr if cur.dsr == cur.dsr else -1.0
        if (r_dsr, r.oos_sharpe) > (c_dsr, cur.oos_sharpe):
            best[b] = r
    return best


def _load_returns(processed_dir: Path, candidates: list, lookback: int) -> dict:
    """سری بازده هر base از parquet خودش (برای همبستگی و vol)."""
    rets: dict[str, pd.Series] = {}
    for r in candidates:
        base = _norm_sym(r.symbol)
        path = processed_dir / f"{r.dataset}.parquet"
        try:
            close = pd.read_parquet(path, columns=["close"])["close"].tail(lookback + 1)
            rets[base] = close.pct_change().dropna().reset_index(drop=True)
        except Exception:
            continue
    return rets


def select_portfolio(
    results: list,
    *,
    timeframe: str,
    top_n: int,
    corr_cap: float,
    processed_dir: Path,
    exclude: set[str],
    only_bases: list[str] | None = None,
) -> tuple[list, dict[str, float], dict]:
    """انتخاب سبد: deployable ها → بهترین هر base → سقف همبستگی → وزن‌دهی.

    وزن = (Sharpe / vol) نرمال‌شده حول ۱ و محدود به [0.5, 1.5] — بات با
    custom_stake_amount استیک هر جفت را در همین وزن ضرب می‌کند.
    """
    pool = [r for r in results if r.deployable and r.timeframe == timeframe]
    best = _best_per_base(pool, exclude)
    if only_bases is not None:
        norm = {_norm_sym(b) for b in only_bases}
        best = {b: r for b, r in best.items() if b in norm}

    ranked = sorted(
        best.values(),
        key=lambda r: (-(r.dsr if r.dsr == r.dsr else -1.0), -r.oos_sharpe),
    )
    rets = _load_returns(processed_dir, ranked, lookback=1080)

    selected, corr_dropped = [], []
    for r in ranked:
        base = _norm_sym(r.symbol)
        s = rets.get(base)
        blocked_by = None
        if s is not None and len(s) > 60:
            for q in selected:
                qb = _norm_sym(q.symbol)
                t = rets.get(qb)
                if t is None or len(t) < 60:
                    continue
                n = min(len(s), len(t))
                c = s.tail(n).reset_index(drop=True).corr(t.tail(n).reset_index(drop=True))
                if c == c and abs(c) >= corr_cap:
                    blocked_by = {"blocked_by": qb, "corr": round(float(c), 3)}
                    break
        if blocked_by:
            corr_dropped.append({"base": base, **blocked_by})
            continue
        selected.append(r)
        if len(selected) >= top_n:
            break

    weights_raw: dict[str, float] = {}
    for r in selected:
        base = _norm_sym(r.symbol)
        s = rets.get(base)
        vol = float(s.std()) if s is not None and len(s) > 60 else None
        conf = max(r.oos_sharpe, 0.1)
        weights_raw[base] = conf / vol if vol and vol > 0 else conf
    weights: dict[str, float] = {}
    if weights_raw:
        mean_w = sum(weights_raw.values()) / len(weights_raw)
        for base, v in weights_raw.items():
            weights[base] = round(min(1.5, max(0.5, v / mean_w)), 3)

    diag = {
        "pool_size": len(pool),
        "bases_considered": len(best),
        "corr_cap": corr_cap,
        "corr_dropped": corr_dropped,
    }
    return selected, weights, diag


# ── kills (کیل‌سوییچ) ──────────────────────────────────────────────────────────

def _load_kills() -> dict:
    try:
        return json.loads(KILLS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"kills": []}


def _active_kills(kills: dict, bot: str) -> set[str]:
    """کیل‌های فعال این بات. کیلِ قدیمی‌تر از KILL_MIN_HOURS در «اسکن جدید» پاک می‌شود."""
    now = datetime.now(timezone.utc)
    active, kept = set(), []
    for k in kills.get("kills", []):
        try:
            age_ok = (now - datetime.fromisoformat(k["killed_at"])) >= timedelta(hours=KILL_MIN_HOURS)
        except Exception:
            age_ok = True
        if k.get("bot") == bot and not age_ok:
            active.add(k["base"])
            kept.append(k)
        elif k.get("bot") == bot and age_ok:
            # منقضی — اسکن جدید دوباره قضاوت می‌کند؛ از فایل حذف می‌شود
            continue
        else:
            kept.append(k)
    kills["kills"] = kept
    return active


def _to_hyperliquid_pair(base: str) -> str:
    return f"{base}/USDC:USDC"


_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "1d": 1440,
}


def _walle_best_timeframe(results: list, upgrade_factor: float = 1.5) -> str | None:
    """کوچکترین TF با لبه روی Hyperliquid؛ فقط اگر TF بزرگ‌تر upgrade_factor برابر بیشتر اج داشت ارتقا می‌یابد."""
    tf_total: dict[str, float] = {}
    for r in results:
        if r.deployable:
            tf_total[r.timeframe] = tf_total.get(r.timeframe, 0.0) + r.oos_sharpe
    if not tf_total:
        return None
    available = sorted(tf_total.keys(), key=lambda t: _TF_MINUTES.get(t, 99999))
    best, best_score = available[0], tf_total[available[0]]
    for tf in available[1:]:
        if tf_total[tf] > best_score * upgrade_factor:
            best, best_score = tf, tf_total[tf]
    return best


def _save_kills(kills: dict) -> None:
    KILLS_PATH.write_text(json.dumps(kills, ensure_ascii=False, indent=2), encoding="utf-8")


# ── hysteresis state ──────────────────────────────────────────────────────────

def _read_sig(path: Path) -> tuple[dict, str | None]:
    if not path.exists():
        return {}, None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        tf = stored.pop("__timeframe__", None)
        return stored, tf
    except Exception:
        return {}, None


def _write_sig(path: Path, tf: str, plan_sig: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"__timeframe__": tf, **plan_sig}, ensure_ascii=False),
        encoding="utf-8",
    )


def _pending_path(bot: str) -> Path:
    return OUT / f".pending_plan_{bot}.json"


def _read_pending(bot: str) -> dict:
    try:
        return json.loads(_pending_path(bot).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_pending(bot: str, pending: dict | None) -> None:
    p = _pending_path(bot)
    if pending is None:
        p.unlink(missing_ok=True)
    else:
        p.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")


def _derive_deployed_from_manifest(manifest_path: Path, tf_fallback: str) -> tuple[dict, str | None]:
    """اگر sig نبود، پلنِ مستقر را از مانیفستِ فعلی بات استخراج کن (baseline هیسترزیس)."""
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, None
    tf = m.get("timeframe") or tf_fallback
    best: dict[str, tuple] = {}
    for c in m.get("candidates", []):
        if c.get("timeframe") != tf:
            continue
        b = _norm_sym(c.get("symbol", ""))
        cur = best.get(b)
        if cur is None or c.get("oos_sharpe", -9) > cur[2]:
            best[b] = (c.get("strategy"), bool(c.get("allow_short")), c.get("oos_sharpe", 0))
    return {b: [v[0], v[1]] for b, v in best.items()}, tf


# ── config / env writers ───────────────────────────────────────────────────────

def _update_config_whitelist(config_path: Path, pairs: list[str]) -> None:
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


def _write_env_tf(env_path: Path, tf: str) -> None:
    if not env_path.exists():
        return
    lines = [ln for ln in env_path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("QR_TIMEFRAME=")]
    lines.append(f"QR_TIMEFRAME={tf}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  updated {env_path.name} → QR_TIMEFRAME={tf}")


def _write_bot_manifest(
    manifest_path: Path, bot: str, tf: str,
    selected: list, weights: dict[str, float],
    exit_only_bases: set[str] | None = None,
) -> None:
    """مانیفستِ فیلترشدهٔ بات: فقط پلنِ مستقر + وزن. deployed_at قاعده‌های
    بدون‌تغییر حفظ می‌شود تا افقِ قضاوتِ کیل‌سوییچ ریست نشود.

    exit_only_bases: قاعده‌های حذف‌شده‌ای که ممکن است هنوز پوزیشن باز داشته
    باشند؛ یک چرخه با killed=true در مانیفست می‌مانند تا Bridge ورود را ببندد
    ولی «خروج اجباری» بدهد (بدون این، پوزیشنِ باز بدون سیگنال خروج می‌ماند).
    """
    old_candidates: list[dict] = []
    old_deployed_at: dict[tuple, str] = {}
    try:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_candidates = old.get("candidates", [])
        for c in old_candidates:
            key = (_norm_sym(c.get("symbol", "")), c.get("strategy"), bool(c.get("allow_short")))
            if c.get("deployed_at"):
                old_deployed_at[key] = c["deployed_at"]
    except Exception:
        pass

    now = _now_iso()
    cands = []
    for r in selected:
        base = _norm_sym(r.symbol)
        d = asdict(r)
        # NaN در JSON مجاز نیست (json.load بات سختگیر نیست ولی تمیز بنویسیم)
        for k, v in list(d.items()):
            if isinstance(v, float) and v != v:
                d[k] = None
        d["weight"] = weights.get(base, 1.0)
        d["deployed_at"] = old_deployed_at.get((base, r.strategy, r.allow_short), now)
        cands.append(d)

    # قاعده‌های حذف‌شده → exit-only برای یک چرخه (killed های قبلی حمل نمی‌شوند)
    live_bases = {_norm_sym(r.symbol) for r in selected}
    for c in old_candidates:
        base = _norm_sym(c.get("symbol", ""))
        if (exit_only_bases and base in exit_only_bases
                and base not in live_bases and not c.get("killed")):
            d = dict(c)
            d["killed"] = True
            d["killed_at"] = now
            d["kill_reason"] = d.get("kill_reason") or "removed_from_plan"
            cands.append(d)

    manifest = {
        "version": 2,
        "bot": bot,
        "generated_at": now,
        "timeframe": tf,
        "n_scanned": None,
        "n_passed": len(cands),
        "candidates": cands,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  manifest → {manifest_path} ({len(cands)} rules)")


# ── deployment decision (هیسترزیس) ─────────────────────────────────────────────

def _current_rule_metric(results: list, base: str, tf: str, rule: list) -> object | None:
    """متریکِ امروزِ قاعدهٔ مستقر (بهترین صرافی)."""
    cand = None
    for r in results:
        if (_norm_sym(r.symbol) == base and r.timeframe == tf
                and r.strategy == rule[0] and bool(r.allow_short) == bool(rule[1])):
            if cand is None or r.oos_sharpe > cand.oos_sharpe:
                cand = r
    return cand


def decide_and_maybe_deploy(
    *,
    bot: str,
    results: list,
    selected: list,
    weights: dict[str, float],
    tf: str,
    kills_active: set[str],
    sig_path: Path,
    env_path: Path,
    config_path: Path,
    manifest_path: Path,
    pair_formatter,
    switch_streak: int,
    switch_margin: float,
    do_deploy: bool,
    force: bool,
    diag: dict,
) -> dict:
    """تصمیم هیسترزیس + (در صورت فلگ) اجرا. خلاصهٔ وضعیت را برمی‌گرداند."""
    proposed_rules = {_norm_sym(r.symbol): r for r in selected}
    proposed_sig = {b: [r.strategy, bool(r.allow_short)] for b, r in proposed_rules.items()}

    deployed_sig, deployed_tf = _read_sig(sig_path)
    if not deployed_sig:
        deployed_sig, deployed_tf = _derive_deployed_from_manifest(manifest_path, tf)
    cold_start = not deployed_sig
    deployed_tf = deployed_tf or tf

    # ۱) حذف فوری: قاعدهٔ مستقری که دیگر deployable نیست، یا base کشته شده
    final_sig = {}
    removals = []
    for base, rule in deployed_sig.items():
        cur = _current_rule_metric(results, base, deployed_tf, rule)
        alive = cur is not None and cur.deployable
        if base in kills_active:
            removals.append({"base": base, "reason": "killswitch"})
        elif not alive:
            removals.append({"base": base, "reason": "rule_no_longer_robust"})
        else:
            final_sig[base] = rule

    # ۲) اضافه/تعویض: نیازمند حاشیه + استریک
    candidate_changes = {}
    margin_blocked = []
    for base, rule in proposed_sig.items():
        if final_sig.get(base) == rule:
            continue
        if base in final_sig:  # تعویض قاعدهٔ زنده → حاشیه لازم
            inc = _current_rule_metric(results, base, deployed_tf, final_sig[base])
            inc_sharpe = inc.oos_sharpe if inc else 0.0
            cand_sharpe = proposed_rules[base].oos_sharpe
            if cand_sharpe < inc_sharpe + switch_margin:
                margin_blocked.append({
                    "base": base, "incumbent_sharpe": inc_sharpe,
                    "candidate_sharpe": cand_sharpe, "margin": switch_margin,
                })
                continue
        candidate_changes[base] = rule

    tf_change = tf != deployed_tf
    pending = _read_pending(bot)
    streak = 0
    if cold_start or force:
        final_sig.update(candidate_changes)
        applied_changes = candidate_changes
        _write_pending(bot, None)
    elif candidate_changes or tf_change:
        same_as_pending = (
            pending.get("sig") == candidate_changes and pending.get("tf") == tf
        )
        streak = (pending.get("streak", 0) + 1) if same_as_pending else 1
        if streak >= switch_streak:
            final_sig.update(candidate_changes)
            applied_changes = candidate_changes
            _write_pending(bot, None)
        else:
            applied_changes = {}
            tf_change = False  # تا تأیید استریک، tf مستقر می‌ماند
            _write_pending(bot, {
                "sig": candidate_changes, "tf": tf, "streak": streak,
                "first_seen": pending.get("first_seen") or _now_iso(),
                "updated_at": _now_iso(),
            })
    else:
        applied_changes = {}
        tf_change = False
        _write_pending(bot, None)

    deploy_tf = tf if (cold_start or force or applied_changes or tf_change) else deployed_tf
    plan_changed = final_sig != deployed_sig or deploy_tf != deployed_tf

    summary = {
        "bot": bot,
        "timeframe_proposed": tf,
        "timeframe_deployed": deployed_tf,
        "cold_start": cold_start,
        "proposed": proposed_sig,
        "deployed_before": deployed_sig,
        "final": final_sig,
        "removals": removals,
        "margin_blocked": margin_blocked,
        "pending": _read_pending(bot) or None,
        "streak_required": switch_streak,
        "weights": weights,
        "kills_active": sorted(kills_active),
        "selection": diag,
        "will_deploy": bool(do_deploy and plan_changed),
        "decided_at": _now_iso(),
    }

    if not do_deploy:
        print(f"{bot}: plan computed (deploy skipped — no flag). changed={plan_changed}")
        return summary
    if not plan_changed:
        print(f"{bot}: unchanged (tf={deployed_tf}) — no restart needed.")
        return summary

    # ── اجرا ──
    final_rules = []
    for base, rule in final_sig.items():
        r = proposed_rules.get(base)
        if r is None or [r.strategy, bool(r.allow_short)] != rule:
            r = _current_rule_metric(results, base, deploy_tf, rule)
        if r is not None:
            final_rules.append(r)
    removed_bases = {rm["base"] for rm in removals}
    _write_bot_manifest(manifest_path, bot, deploy_tf, final_rules, weights,
                        exit_only_bases=removed_bases)
    if final_sig:
        _update_config_whitelist(config_path, [pair_formatter(b) for b in final_sig])
    else:
        # whitelist خالی freqtrade را می‌شکند؛ جفت‌ها می‌مانند و بات از طریق
        # مانیفستِ بدون قاعده flat می‌شود (و exit-only ها پوزیشن باز را می‌بندند)
        print(f"  {bot}: empty plan — whitelist untouched (flat via manifest)")

    if deploy_tf != deployed_tf:
        print(f"{bot} timeframe: {deployed_tf} → {deploy_tf} (env update + recreate)")
        _write_env_tf(env_path, deploy_tf)
        cmd = ["docker", "compose", "up", "-d", bot]
        kwargs = {"cwd": str(NOCHES_DIR)}
    else:
        print(f"{bot} plan changed (tf={deploy_tf}) → docker restart")
        cmd, kwargs = ["docker", "restart", bot], {}
    try:
        subprocess.run(cmd, check=True, timeout=180, **kwargs)
        print(f"  reloaded {bot}")
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: {bot} reload failed: {exc}")

    _write_sig(sig_path, deploy_tf, final_sig)
    summary["deployed_after"] = final_sig
    summary["timeframe_deployed"] = deploy_tf
    return summary


# ── timeframe انتخابی از استخر deployable ─────────────────────────────────────

def _best_collective_timeframe(results: list, bases: list[str] | None) -> str | None:
    norm = {_norm_sym(b) for b in (bases or [])} if bases else set()
    best_per: dict[tuple, float] = {}
    for r in results:
        if not r.deployable:
            continue
        sym = _norm_sym(r.symbol)
        if norm and sym not in norm:
            continue
        key = (sym, r.timeframe)
        best_per[key] = max(best_per.get(key, 0.0), r.oos_sharpe)
    tf_total: dict[str, float] = {}
    for (_, tf), sh in best_per.items():
        tf_total[tf] = tf_total.get(tf, 0.0) + sh
    return max(tf_total, key=lambda t: tf_total[t]) if tf_total else None


def _copy(src: Path, dest: Path, label: str) -> None:
    import shutil
    if dest.parent.exists():
        shutil.copy(src, dest)
        print(f"copied {label} -> {dest}")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--out", default=str(OUT / "wf_candidates.json"))
    ap.add_argument("--report", default=str(OUT / "wf_report.json"))
    ap.add_argument("--history", default=str(OUT / "wf_history.jsonl"))
    ap.add_argument("--soodo-report", default="/home/h0551user/soodo/app_db/qr_report.json")
    ap.add_argument("--live-timeframe", default="4h")
    ap.add_argument("--min-positive-frac", type=float, default=0.55,
                    help="گیتِ passed (استخر پژوهشی)")
    ap.add_argument("--top-n", type=int, default=5)
    # گیت استحکام (deployable)
    ap.add_argument("--min-venues", type=int, default=2)
    ap.add_argument("--min-splits", type=int, default=4)
    ap.add_argument("--robust-positive-frac", type=float, default=0.70)
    ap.add_argument("--min-dsr", type=float, default=0.20)
    # سبد
    ap.add_argument("--corr-cap", type=float, default=0.80)
    # هیسترزیس
    ap.add_argument("--switch-streak", type=int, default=3)
    ap.add_argument("--switch-margin", type=float, default=0.20)
    # Wall_E (لبه‌محور، Hyperliquid)
    ap.add_argument("--reload-walle", action="store_true",
                    help="اعمال پلن Wall_E (مانیفست + ری‌استارت در صورت تغییر)")
    ap.add_argument("--force-reload-walle", action="store_true",
                    help="اعمال فوری Wall_E بدون شرط استریک")
    ap.add_argument("--walle-pairs", nargs="*", default=None,
                    help="محدود کردن انتخاب Wall_E به این base ها")
    args = ap.parse_args()

    processed_dir = Path(args.processed)
    results = scan_processed_dir(
        processed_dir,
        only_symbols=args.symbols or None,
        min_positive_frac=args.min_positive_frac,
    )

    gate = apply_robustness(
        results,
        min_venues=args.min_venues,
        min_splits=args.min_splits,
        min_positive_frac=args.robust_positive_frac,
        min_dsr=args.min_dsr,
    )
    out = write_manifest(results, Path(args.out))

    # تایم‌فریم زنده از استخر deployable (در نبودش، آرگومان)
    live_tf = _best_collective_timeframe(results, None) or args.live_timeframe

    report = build_report(results, live_timeframe=live_tf,
                          plan_pool="deployable", gate=gate)
    rep = write_report(report, Path(args.report), Path(args.history))

    tf_brk = " ".join(f"{tf}:{d['robust']}/{d['passed']}/{d['scanned']}"
                      for tf, d in sorted(report["by_timeframe"].items()))
    print(f"scanned={len(results)} passed={report['n_passed']} "
          f"robust={report['n_robust']} deployable={report['n_deployable']}")
    print(f"by_timeframe (robust/passed/scanned): {tf_brk}")
    print(f"manifest -> {out}")
    print(f"report   -> {rep}")
    for a in report["alerts"]:
        print(f"  ALERT  {a['message']}")

    if args.soodo_report:
        _copy(rep, Path(args.soodo_report), "report")

    # ── Wall_E: لبه‌محور روی دیتای Hyperliquid (کوچکترین TF با لبه) ─────────────
    hl_results = [r for r in results if r.exchange.startswith("hyperliquid")]
    hl_tf = _walle_best_timeframe(hl_results) or args.live_timeframe
    kills = _load_kills()
    hl_kills = _active_kills(kills, "Wall_E")
    hl_selected, hl_weights, hl_diag = select_portfolio(
        hl_results,
        timeframe=hl_tf,
        top_n=5,
        corr_cap=args.corr_cap,
        processed_dir=processed_dir,
        exclude=hl_kills,
        only_bases=args.walle_pairs,
    )
    print(f"Wall_E tf={hl_tf} selected={[_norm_sym(r.symbol) for r in hl_selected]}")
    walle_summary = decide_and_maybe_deploy(
        bot="Wall_E",
        results=hl_results,
        selected=hl_selected,
        weights=hl_weights,
        tf=hl_tf,
        kills_active=hl_kills,
        sig_path=WALLE_SIG_PATH,
        env_path=WALLE_ENV_PATH,
        config_path=WALLE_CONFIG_PATH,
        manifest_path=WALLE_MANIFEST_PATH,
        pair_formatter=_to_hyperliquid_pair,
        switch_streak=args.switch_streak,
        switch_margin=args.switch_margin,
        do_deploy=args.reload_walle or args.force_reload_walle,
        force=args.force_reload_walle,
        diag=hl_diag,
    )
    _save_kills(kills)

    selection_state = {
        "generated_at": _now_iso(), "gate": gate,
        "live_timeframe": live_tf,
        "bots": {"Wall_E": walle_summary},
    }
    SELECTION_STATE_PATH.write_text(
        json.dumps(selection_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"selection state -> {SELECTION_STATE_PATH}")

    # ── سینکِ فایل‌های کمکی برای داشبورد «لبه‌های کوانت» در ادمین soodo ──
    if args.soodo_report:
        soodo_db = Path(args.soodo_report).parent
        for src, name in (
            (SELECTION_STATE_PATH, "qr_selection_state.json"),
            (KILLS_PATH, "qr_edge_kills.json"),
            (Path(args.history), "qr_wf_history.jsonl"),
            (OUT / "pipeline_status.json", "qr_pipeline_status.json"),
            (WALLE_MANIFEST_PATH, "qr_walle_manifest.json"),
        ):
            try:
                if src.exists():
                    _copy(src, soodo_db / name, name)
            except Exception as exc:  # noqa: BLE001 — سینک داشبورد نباید پایپ‌لاین را بشکند
                print(f"WARN: copy {name} failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
