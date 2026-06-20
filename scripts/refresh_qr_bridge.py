#!/usr/bin/env python3
"""رفرشِ بات‌های «بریجِ کوانتِ پرتکرار» (bot5 روی gate، bot6 روی hyperliquid).

برخلاف گیتِ سخت‌گیرِ `deployable` (که بات‌ها را مدام فلت می‌کرد)، این‌جا پروفایلِ
«پرتکرار» اعمال می‌شود: edgeهای 15m که در walk-forward مثبت بوده‌اند (`passed`)
با positive_frac/splits/فراوانیِ کافی + فیلترِ نقدینگیِ همان صرافی. ریسکِ هر
تریدْ با بریکتِ ROE (TP ~۵-۷٪ / SL −۳.۵٪ + اهرمِ ATR-آگاه) و protections در
استراتژیِ مشترک `QuantResearchBridge` مدیریت می‌شود.

هر بات روی صرافی و نمادهای متفاوت ⇒ تنوعِ واقعی (bot5: gate/USDT،
bot6: hyperliquid/USDC).

ورودی : outputs/wf_candidates.json  (همان اسکنِ شبانهٔ wf_scan)
خروجی : manifestِ هر بات + whitelist + (در صورتِ تغییرِ پلن) ری‌استارت/بازسازی.
        هیسترزیس: فقط وقتی پلن عوض شده اقدام می‌کند؛ جفت‌های حذف‌شده یک چرخه
        killed=exit-only می‌مانند.

نکتهٔ deploy: تغییرِ env (مثل QR_TIMEFRAME) فقط با «docker compose up -d»
اعمال می‌شود؛ تغییرِ صرفِ manifest/config (bind-mount) با «docker restart».
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outputs" / "wf_candidates.json"
NOCHES = Path("/home/h0551user/noches")
UD = NOCHES / "user_data"

TF = "15m"

# پیکربندیِ هر بات
# ۲۰۲۶-۰۶-۲۰ — هر دو باتِ این بریج به استراتژیِ cross-sectional market-neutral مهاجرت
# کردند و دیگر از مانیفستِ rule-edge تغذیه نمی‌شوند. پس از این رفرشِ شبانه **جدا** شدند
# تا whitelist/config‌شان را clobber و کانتینر را ری‌استارت نکند (BOTS خالی = no-op):
#   • bot5 → bot5XSMN  (bybit، FreqAI μ/α، ۲۹ جفت)        — strategies/bot5XSMN.py
#   • bot6 → bot6XSMN   (hyperliquid، XS momentumِ قاعده‌محور، ۳۴ جفت) — strategies/bot6XSMN.py
# اگر باتی دوباره به مدلِ rule-bridge برگشت، ورودی‌اش را از _LEGACY_BOTS_DISABLED به BOTS برگردان.
BOTS: dict[str, dict] = {}
_LEGACY_BOTS_DISABLED: dict[str, dict] = {
    "bot5": {
        "container": "bot5",
        "exchange": "gate", "quote": "USDT", "swap_opt": True,
        "manifest": UD / "wf_candidates_bot5.json",
        "config": UD / "bot5_config.json",
        "env": NOCHES / "bot5.env",
        "top_n": 8, "min_vol": 3_000_000.0,
    },
    "bot6": {
        "container": "bot6",
        "exchange": "hyperliquid", "quote": "USDC", "swap_opt": False,
        "manifest": UD / "wf_candidates_bot6.json",
        "config": UD / "bot6_config.json",
        "env": NOCHES / "bot6.env",
        "top_n": 8, "min_vol": 1_000_000.0,  # حجمِ HL کوچک‌تر از gate
    },
}

MIN_POS_FRAC = 0.75
MIN_SPLITS = 4
MIN_TRADES_PER_SPLIT = 12.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base(sym: str) -> str:
    s = sym.split("/")[0].split(":")[0].upper()
    for q in ("USDT", "USDC", "BUSD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _pair(base: str, quote: str) -> str:
    return f"{base}/{quote}:{quote}"


def _quote_volumes(bases: list[str], bot: dict) -> dict[str, float]:
    """حجمِ ۲۴ساعتهٔ صرافیِ بات برای این base ها. خطا → {} (فیلتر off)."""
    try:
        import ccxt
        klass = getattr(ccxt, bot["exchange"])
        ex = klass({"options": {"defaultType": "swap"}} if bot["swap_opt"] else {})
        ex.load_markets()
        q = bot["quote"]
        syms = [_pair(b, q) for b in bases if _pair(b, q) in ex.markets]
        tk = ex.fetch_tickers(syms) if bot["swap_opt"] else ex.fetch_tickers()
        out = {}
        for b in bases:
            t = tk.get(_pair(b, q))
            if t:
                out[b] = float(t.get("quoteVolume") or t.get("baseVolume") or 0)
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"  [{bot['exchange']}] liquidity filter skipped (ccxt error: {exc})")
        return {}


def select(cands: list, bot: dict) -> list:
    pool = [
        c for c in cands
        if c.get("timeframe") == TF and c.get("passed")
        and (c.get("oos_positive_frac") or 0) >= MIN_POS_FRAC
        and (c.get("n_splits") or 0) >= MIN_SPLITS
        and (c.get("trades_per_split") or 0) >= MIN_TRADES_PER_SPLIT
    ]
    best: dict[str, dict] = {}
    for c in pool:
        b = _base(c["symbol"])
        if b not in best or c["oos_sharpe"] > best[b]["oos_sharpe"]:
            best[b] = c
    vols = _quote_volumes(list(best), bot)
    if vols:
        kept = {b: c for b, c in best.items() if vols.get(b, 0.0) >= bot["min_vol"]}
        dropped = sorted(set(best) - set(kept))
        if dropped:
            print(f"  liquidity/availability drop: {dropped}")
        best = kept or best
    ranked = sorted(best.values(), key=lambda c: -c["oos_sharpe"])
    return ranked[: bot["top_n"]]


def build_manifest(sel: list, old: dict, bot_name: str, quote: str) -> dict:
    now = _now()
    old_dep = {}
    for c in (old.get("candidates") or []):
        if c.get("deployed_at"):
            old_dep[(_base(c.get("symbol", "")), c.get("strategy"), bool(c.get("allow_short")))] = c["deployed_at"]
    ms = sum(c["oos_sharpe"] for c in sel) / len(sel) if sel else 1.0
    cands, live = [], set()
    for c in sel:
        b = _base(c["symbol"]); live.add(b)
        key = (b, c["strategy"], bool(c["allow_short"]))
        cands.append({
            "symbol": _pair(b, quote), "timeframe": TF,
            "strategy": c["strategy"], "allow_short": bool(c["allow_short"]),
            "oos_sharpe": round(c["oos_sharpe"], 3),
            "oos_positive_frac": c.get("oos_positive_frac"),
            "n_splits": c.get("n_splits"), "trades_per_split": c.get("trades_per_split"),
            "weight": round(min(1.5, max(0.5, c["oos_sharpe"] / ms)), 3),
            "deployed_at": old_dep.get(key, now),
        })
    for c in (old.get("candidates") or []):
        b = _base(c.get("symbol", ""))
        if b not in live and not c.get("killed"):
            d = dict(c); d["killed"] = True; d["killed_at"] = now
            d["kill_reason"] = "removed_from_plan"; cands.append(d)
    return {
        "version": 2, "bot": bot_name, "generated_at": now, "timeframe": TF,
        "n_scanned": None, "n_passed": sum(1 for c in cands if not c.get("killed")),
        "candidates": cands,
    }


def sig_of(cands: list) -> dict:
    return {_base(c["symbol"]): [c["strategy"], bool(c["allow_short"])]
            for c in cands if not c.get("killed")}


def update_whitelist(config_path: Path, pairs: list[str]) -> None:
    raw = config_path.read_text(encoding="utf-8")
    cfg = json.loads(re.sub(r"(^|\s)//.*$", "", raw, flags=re.M))
    cfg["exchange"]["pair_whitelist"] = pairs
    cfg["max_open_trades"] = max(6, cfg.get("max_open_trades", 6))
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")


def _env_tf(env_path: Path) -> str | None:
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("QR_TIMEFRAME="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def _set_env_tf(env_path: Path, tf: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    out, seen = [], False
    for ln in lines:
        if ln.strip().startswith("QR_TIMEFRAME="):
            out.append(f"QR_TIMEFRAME={tf}"); seen = True
        else:
            out.append(ln)
    if not seen:
        out.append(f"QR_TIMEFRAME={tf}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def run_bot(name: str, cands: list, apply: bool) -> None:
    bot = BOTS[name]
    sel = select(cands, bot)
    if not sel:
        print(f"{name}: no high-freq 15m candidates — manifest untouched.")
        return
    old = {}
    try:
        old = json.loads(bot["manifest"].read_text(encoding="utf-8"))
    except Exception:
        pass
    manifest = build_manifest(sel, old, name, bot["quote"])
    new_sig, old_sig = sig_of(manifest["candidates"]), sig_of(old.get("candidates", []))
    pairs = [c["symbol"] for c in manifest["candidates"] if not c.get("killed")]
    env_tf = _env_tf(bot["env"])
    tf_change = env_tf != TF
    changed = new_sig != old_sig or tf_change

    print(f"{name} plan ({len(pairs)} pairs): {new_sig}")
    print(f"  env_tf={env_tf} → {TF} (tf_change={tf_change}); plan_changed={new_sig != old_sig}")
    if not apply:
        print("  (dry — no flag) not writing.")
        return

    bot["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  manifest → {bot['manifest']}")
    if not changed:
        print(f"{name}: plan unchanged — no restart.")
        return
    update_whitelist(bot["config"], pairs)

    try:
        if tf_change:
            _set_env_tf(bot["env"], TF)
            subprocess.run(["docker", "compose", "up", "-d", bot["container"]],
                           cwd=str(NOCHES), check=True, timeout=180)
            print(f"{name}: recreated (env tf {env_tf}→{TF}).")
        else:
            subprocess.run(["docker", "restart", bot["container"]], check=True, timeout=180)
            print(f"{name}: restarted (plan changed).")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: {name} reload failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", choices=[*BOTS, "all"], default="all")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cands = json.loads(SRC.read_text(encoding="utf-8")).get("candidates", [])
    names = list(BOTS) if args.bot == "all" else [args.bot]
    for n in names:
        run_bot(n, cands, args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
