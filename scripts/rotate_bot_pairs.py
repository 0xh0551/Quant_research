#!/usr/bin/env python3
"""چرخش خودکارِ جفت‌ارزِ بات‌های مدل‌محور (Gadget=RL، Klaymen/Popeye=ML) از روی امتیاز سازگاری.

شب‌ها بعد از اسکن لبه‌ها اجرا می‌شود (refresh_candidates.sh):
  - Gadget  ← امتیاز RL  (recommend_rl_coins، فیوچرز bybit 15m)
  - Klaymen ← امتیاز ML  (recommend_ml_coins، دیتای bybit/gate به‌عنوان پراکسی
              + فیلتر «روی سواپ USDT صرافی OKX لیست شده باشد»)
  - Popeye  ← امتیاز ML  (recommend_ml_coins، دیتای bybit 15m، جفت USDT)

Wall_E لبه‌محور است (نه ML fitness) و توسط refresh_candidates.py مدیریت می‌شود.

لایه‌های محافظ (همان فلسفهٔ پایپ‌لاین لبه‌ها):
  1) هیسترزیس: چالش‌گر باید switch_streak شب متوالی در تاپ-N بماند و
     switch_margin امتیاز از ضعیف‌ترین جفتِ مستقر بهتر باشد.
  2) ماندگاری: جفت مستقر قبل از min_dwell_days برداشته نمی‌شود
     (RL برای همگراییِ زنجیرهٔ continual به زمان نیاز دارد؛ cold start مفت نیست).
  3) جفتِ دارای پوزیشن باز هرگز برداشته نمی‌شود (تا شب بعد عقب می‌افتد).
  4) حداکثر یک تغییر در هر شب برای هر بات.

اعمال تغییر: docker stop → جراحی متنیِ pair_whitelist در کانفیگ (کانفیگ‌ها کامنت
// دارند؛ json.dump کل فایل ممنوع) → حذف مدلِ جفتِ خروجی (sub-train-*،
tensorboard/<BASE>، کلیدهای pair_dictionary) تا برگشتِ بعدی warm-start کهنه
نگیرد → docker start. بدون تغییر، ری‌استارتی هم در کار نیست.

خروجی‌ها (مصرف داشبوردهای hnarimani و soodo):
  - outputs/pair_assignments.json          وضعیت جاری + کاندیداهای برتر هر بات
  - outputs/pair_rotation_history.jsonl    دفترچهٔ رخدادها (swap/add/blocked/...)
  - outputs/pair_rotation_state.json       state داخلی هیسترزیس
  - <soodo>/app_db/qr_pair_rotation.json(.jsonl)  کپی برای ادمین soodo
"""
import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.recommend import recommend_ml_coins  # noqa: E402
from src.rl.recommend import recommend_rl_coins  # noqa: E402

OUT = ROOT / "outputs"
STATE_PATH = OUT / "pair_rotation_state.json"
ASSIGN_PATH = OUT / "pair_assignments.json"
HISTORY_PATH = OUT / "pair_rotation_history.jsonl"
OKX_CACHE = OUT / "okx_swap_bases.json"

NOCHES = Path("/home/h0551user/noches/user_data")

# پایه‌هایی که هیچ‌وقت کاندید ترید نیستند (استیبل/رپد)
BASE_BLACKLIST = {"USDC", "USDE", "DAI", "FDUSD", "TUSD", "BUSD", "USTC", "USDP",
                  "WBTC", "WETH", "STETH"}

BOTS = {
    "gadget": {
        "label": "Gadget", "container": "Gadget", "kind": "rl",
        "exchange": "bybit", "trade_timeframe": "15m", "score_timeframe": "15m",
        "score_venues": ("bybit",), "quote": "USDT",
        "config": NOCHES / "gadget_config.json",
        "sqlite": NOCHES / "gadget.sqlite",
        "models_dir": NOCHES / "models" / "gadget_rlpro_live",
        "manifest_path": None, "default_strategy": None,
        "n_pairs": 3, "min_dwell_days": 14.0,
        "switch_streak": 3, "switch_margin": 5,
        "okx_filter": False,
    },
    "klaymen": {
        "label": "Klaymen", "container": "Klaymen", "kind": "ml",
        "exchange": "okx", "trade_timeframe": "5m", "score_timeframe": "15m",
        "score_venues": ("bybit", "gate", "gateio", "gate_io"), "quote": "USDT",
        "config": NOCHES / "klaymen_config.json",
        "sqlite": NOCHES / "klaymen.sqlite",
        "models_dir": NOCHES / "models" / "Klaymen_",
        "manifest_path": None, "default_strategy": None,
        "n_pairs": 5, "min_dwell_days": 7.0,
        "switch_streak": 3, "switch_margin": 5,
        "okx_filter": True,
    },
    "popeye": {
        "label": "Popeye", "container": "Popeye", "kind": "ml",
        "exchange": "bybit", "trade_timeframe": "1h", "score_timeframe": "1h",
        "score_venues": ("bybit",), "quote": "USDT",
        "config": NOCHES / "popeye_config.json",
        "sqlite": NOCHES / "popeye.sqlite",
        "models_dir": NOCHES / "models" / "popeye_ml_live",
        "manifest_path": None, "default_strategy": None,
        "n_pairs": 5, "min_dwell_days": 7.0,
        "switch_streak": 2, "switch_margin": 5,
        "okx_filter": False,
        # Popeye تایم‌فریم را هم از لبهٔ ML کوانت می‌گیرد (هر چند ساعت، با هیسترزیس):
        # جفت‌ها روی همان تایم‌فریمی که ترید می‌شوند امتیازدهی می‌شوند.
        "select_timeframe": True,
        "candidate_timeframes": ["15m", "1h", "4h"],
        "tf_switch_streak": 2,   # چند اجرای متوالی tfِ بهتر بماند تا سوییچ کنیم (هیسترزیس)
        "tf_higher_bias": 3,     # tf بالاتر اگر در فاصلهٔ این امتیاز بود ترجیح دارد (تریدِ کمتر)
        "informative_higher": {"15m": "1h", "1h": "4h", "4h": "1d"},
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dwell_days(assigned_at: str) -> float:
    try:
        t = datetime.fromisoformat(assigned_at)
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except Exception:
        return 1e9  # نامعلوم = قدیمی فرض کن (مانع چرخش نشود)


# ── کانفیگ‌های freqtrade (با کامنت //) ────────────────────────────────────────

WL_RE = re.compile(r'("pair_whitelist"\s*:\s*\[)([^\]]*)(\])', re.S)


def _loads_tolerant(text: str):
    no_comments = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    no_trailing = re.sub(r",(\s*[}\]])", r"\1", no_comments)
    return json.loads(no_trailing)


def read_whitelist(config_path: Path) -> list[str]:
    m = WL_RE.search(config_path.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError(f"pair_whitelist not found in {config_path}")
    return re.findall(r'"([^"]+)"', m.group(2))


def write_whitelist(config_path: Path, pairs: list[str]) -> None:
    """فقط آرایهٔ pair_whitelist را عوض می‌کند؛ بقیهٔ فایل (و کامنت‌ها) دست‌نخورده."""
    text = config_path.read_text(encoding="utf-8")
    m = WL_RE.search(text)
    if not m:
        raise RuntimeError(f"pair_whitelist not found in {config_path}")
    inner = m.group(2)
    ind_m = re.search(r'\n(\s*)"', inner)
    ind = ind_m.group(1) if ind_m else " " * 12
    cind_m = re.search(r"\n(\s*)$", inner)
    cind = cind_m.group(1) if cind_m else " " * 8
    new_inner = "\n" + ",\n".join(f'{ind}"{p}"' for p in pairs) + "\n" + cind
    new_text = text[: m.start(2)] + new_inner + text[m.end(2):]
    parsed = _loads_tolerant(new_text)  # اعتبارسنجی قبل از نوشتن
    got = parsed["exchange"]["pair_whitelist"]
    if got != pairs:
        raise RuntimeError(f"whitelist round-trip mismatch: {got} != {pairs}")
    config_path.write_text(new_text, encoding="utf-8")


# ── تایم‌فریم freqtrade (کلید top-level + include_timeframes فِری‌ای‌آی) ─────────

TF_RE = re.compile(r'("timeframe"\s*:\s*")([^"]*)(")')
INC_TF_RE = re.compile(r'("include_timeframes"\s*:\s*\[)([^\]]*)(\])', re.S)
TF_ORDER = {"1m": 0, "3m": 1, "5m": 2, "15m": 3, "30m": 4,
            "1h": 5, "2h": 6, "4h": 7, "6h": 8, "12h": 9, "1d": 10}


def read_timeframe(config_path: Path) -> str | None:
    m = TF_RE.search(config_path.read_text(encoding="utf-8"))
    return m.group(2) if m else None


def write_timeframe(config_path: Path, timeframe: str,
                    include_timeframes: list[str]) -> None:
    """فقط مقدار top-level «timeframe» و آرایهٔ feature_parameters.include_timeframes
    را عوض می‌کند؛ بقیهٔ فایل (و کامنت‌ها) دست‌نخورده. freqtrade کلید کانفیگ را روی
    attribute استراتژی override می‌کند، پس استراتژی timeframe جدید را می‌گیرد."""
    text = config_path.read_text(encoding="utf-8")
    m = TF_RE.search(text)
    if not m:
        raise RuntimeError(f'top-level "timeframe" not found in {config_path}')
    text = text[: m.start()] + f'"timeframe": "{timeframe}"' + text[m.end():]
    mi = INC_TF_RE.search(text)
    if mi:
        new_inner = ", ".join(f'"{t}"' for t in include_timeframes)
        text = text[: mi.start(2)] + new_inner + text[mi.end(2):]
    parsed = _loads_tolerant(text)  # اعتبارسنجی قبل از نوشتن
    if parsed.get("timeframe") != timeframe:
        raise RuntimeError(f"timeframe round-trip mismatch: {parsed.get('timeframe')} != {timeframe}")
    config_path.write_text(text, encoding="utf-8")


# ── دیتا و امتیازها ───────────────────────────────────────────────────────────

def _pair_of(base: str, quote: str = "USDT") -> str:
    q = quote.upper()
    return f"{base}/{q}:{q}"


def _base_of(pair: str) -> str:
    return pair.split("/")[0]


def okx_swap_bases(ttl_days: float = 7.0) -> set[str] | None:
    """پایه‌های سواپ خطی USDT روی OKX (کش ۷روزه؛ شکست شبکه → کش کهنه؛ هیچ → None)."""
    cached = None
    try:
        cached = json.loads(OKX_CACHE.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 86400.0
        if age < ttl_days and cached.get("bases"):
            return set(cached["bases"])
    except Exception:
        pass
    # ccxt 4.5.56 روی okx خراب است (set_markets با id=None کرش می‌کند) → REST مستقیم
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})  # بدون UA → 403
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        bases = sorted({i["ctValCcy"] for i in data.get("data", [])
                        if i.get("settleCcy") == "USDT" and i.get("state") == "live"
                        and i.get("ctValCcy")})
        if bases:
            OKX_CACHE.write_text(json.dumps(
                {"fetched_at": _now(), "bases": bases}, ensure_ascii=False), encoding="utf-8")
            return set(bases)
    except Exception as exc:
        print(f"WARN: okx load_markets failed: {exc}")
    return set(cached["bases"]) if cached and cached.get("bases") else None


def score_table(spec: dict, processed_dir: Path) -> dict[str, dict]:
    """{base: {score, detail}} — بهترین امتیاز هر پایه روی venue های مجاز."""
    quote = spec.get("quote", "USDT")
    if spec["kind"] == "rl":
        rec = recommend_rl_coins(processed_dir, venues=spec["score_venues"],
                                 timeframe=spec["score_timeframe"], top_n=10**6)
        key = "rl_score"
    else:
        rec = recommend_ml_coins(processed_dir, venues=spec["score_venues"],
                                 timeframe=spec["score_timeframe"], top_n=10**6)
        key = "ml_score"
    table: dict[str, dict] = {}
    for r in rec["recommendations"]:
        sym = r["symbol"]
        if not sym.endswith(quote):
            continue
        base = sym[: -len(quote)]
        if base in BASE_BLACKLIST:
            continue
        cur = table.get(base)
        if cur is None or r[key] > cur["score"]:
            table[base] = {"score": int(r[key]), "detail": r}
    if spec["okx_filter"]:
        allowed = okx_swap_bases()
        if allowed is None:
            print("WARN: no OKX availability data — skipping OKX filter this run")
        else:
            incumbents = {_base_of(p) for p in read_whitelist(spec["config"])}
            table = {b: v for b, v in table.items() if b in allowed or b in incumbents}
    return table


def open_trade_pairs(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = con.execute("select pair from trades where is_open=1").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception as exc:
        print(f"WARN: open-trade check failed for {db_path}: {exc} — assuming open trades")
        return {"__UNKNOWN__"}  # محافظه‌کارانه: حذف را قفل کن


# ── state / دفترچه ───────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def log_event(apply: bool, **ev) -> dict:
    ev = {"ts": _now(), **ev}
    line = json.dumps(ev, ensure_ascii=False)
    print(("EVENT " if apply else "DRY   ") + line)
    if apply:
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return ev


# ── تصمیم برای یک بات ─────────────────────────────────────────────────────────

def decide(bot: str, spec: dict, st: dict, table: dict[str, dict],
           apply: bool) -> dict:
    """state[bot] را به‌روز می‌کند و تصمیم (و در حالت apply، اجرا) را برمی‌گرداند."""
    now = _now()
    bst = st.setdefault(bot, {"assignments": {}, "streaks": {}})
    assigns: dict = bst["assignments"]
    whitelist = read_whitelist(spec["config"])

    # هم‌گرایی با تغییرات دستی کاربر (مثل افزودن دستی BNB به گجت)
    if not assigns:
        for p in whitelist:
            assigns[p] = {"assigned_at": now, "source": "bootstrap"}
        log_event(apply, bot=spec["label"], event="bootstrap", pairs=whitelist)
    else:
        for p in whitelist:
            if p not in assigns:
                assigns[p] = {"assigned_at": now, "source": "manual"}
                log_event(apply, bot=spec["label"], event="manual_add", pair_in=p)
        for p in [q for q in assigns if q not in whitelist]:
            del assigns[p]
            log_event(apply, bot=spec["label"], event="manual_remove", pair_out=p)

    incumbents = [_base_of(p) for p in whitelist]
    ranked = sorted(table.items(), key=lambda kv: kv[1]["score"], reverse=True)
    target = [b for b, _ in ranked[: spec["n_pairs"]]]
    challengers = [b for b in target if b not in incumbents]

    # streak فقط برای چالش‌گرهای فعلی جلو می‌رود؛ بقیه صفر می‌شوند
    streaks = {b: min(bst["streaks"].get(b, 0) + 1, 99) for b in challengers}
    bst["streaks"] = streaks

    # امتیاز روز را روی جفت‌های مستقر هم ثبت کن (برای داشبورد)
    for p in whitelist:
        sc = table.get(_base_of(p), {}).get("score")
        assigns[p]["last_score"] = sc
        assigns[p]["score_at"] = now

    decision: dict = {"bot": spec["label"], "checked_at": now, "action": "hold",
                      "target_top": target, "challengers": streaks}
    open_pairs = open_trade_pairs(spec["sqlite"])

    ready = [b for b in challengers if streaks[b] >= spec["switch_streak"]]
    ready.sort(key=lambda b: table[b]["score"], reverse=True)

    quote = spec.get("quote", "USDT")
    change: dict | None = None
    if len(whitelist) < spec["n_pairs"] and ready:
        b = ready[0]
        change = {"action": "add", "pair_in": _pair_of(b, quote),
                  "score_in": table[b]["score"]}
    elif ready:
        # ضعیف‌ترین مستقرِ دارای امتیاز؛ بدونِ امتیاز = قابل‌سنجش نیست، معاف
        scored = [p for p in whitelist if table.get(_base_of(p))]
        if scored:
            weakest = min(scored, key=lambda p: table[_base_of(p)]["score"])
            w_base, w_score = _base_of(weakest), table[_base_of(weakest)]["score"]
            b = ready[0]
            blockers = []
            if table[b]["score"] < w_score + spec["switch_margin"]:
                blockers.append(f"margin<{spec['switch_margin']}")
            dwell = _dwell_days(assigns[weakest]["assigned_at"])
            if dwell < spec["min_dwell_days"]:
                blockers.append(f"dwell {dwell:.1f}d<{spec['min_dwell_days']:.0f}d")
            if weakest in open_pairs or "__UNKNOWN__" in open_pairs:
                blockers.append("open_trade")
            if blockers:
                decision.update(action="blocked", pair_in=_pair_of(b, quote),
                                pair_out=weakest, score_in=table[b]["score"],
                                score_out=w_score, blockers=blockers)
                log_event(apply, **{k: v for k, v in decision.items() if k != "challengers"},
                          event="blocked")
            else:
                change = {"action": "swap", "pair_in": _pair_of(b, quote), "pair_out": weakest,
                          "score_in": table[b]["score"], "score_out": w_score}

    if change:
        decision.update(change)
        new_wl = [p for p in whitelist if p != change.get("pair_out")]
        new_wl.append(change["pair_in"])
        if apply:
            try:
                apply_change(spec, new_wl, change.get("pair_out"))
                if change.get("pair_out"):
                    del assigns[change["pair_out"]]
                assigns[change["pair_in"]] = {
                    "assigned_at": now, "source": "auto",
                    "last_score": change["score_in"], "score_at": now}
                bst["streaks"].pop(_base_of(change["pair_in"]), None)
                log_event(apply, bot=spec["label"], event=change["action"],
                          **{k: v for k, v in change.items() if k != "action"},
                          new_whitelist=new_wl)
            except Exception as exc:
                decision.update(action="error", error=str(exc))
                log_event(apply, bot=spec["label"], event="error", error=str(exc),
                          attempted=change)
        else:
            log_event(apply, bot=spec["label"], event=f"would_{change['action']}",
                      **{k: v for k, v in change.items() if k != "action"},
                      new_whitelist=new_wl)
    return decision


# ── اعمال: stop → کانفیگ + پاکسازی مدل → start ───────────────────────────────

def _docker(cmd: str, container: str, timeout: int) -> None:
    r = subprocess.run(["docker", cmd, container], capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"docker {cmd} {container}: {r.stderr.strip()}")


def cleanup_pair_models(spec: dict, pair_out: str) -> None:
    """مدل جفتِ خروجی را کامل پاک کن تا برگشتِ بعدی fresh آموزش ببیند."""
    mdir = spec.get("models_dir")
    if not mdir:
        return  # بات بدون FreqAI (مثل Wall_E) — چیزی برای پاک کردن نیست
    base = _base_of(pair_out)
    for d in mdir.glob(f"sub-train-{base}_*"):
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(mdir / "tensorboard" / base, ignore_errors=True)
    pd_path = mdir / "pair_dictionary.json"
    if pd_path.exists():
        try:
            pdict = json.loads(pd_path.read_text(encoding="utf-8"))
            kept = {k: v for k, v in pdict.items() if _base_of(k) != base}
            if kept != pdict:
                pd_path.write_text(json.dumps(kept, indent=4), encoding="utf-8")
        except Exception as exc:
            print(f"WARN: pair_dictionary cleanup failed: {exc}")


def write_bot_manifest(spec: dict, assignments: dict, table: dict) -> None:
    """برای بات‌هایی که manifest_path دارند (مثل Wall_E) یک manifest ساده می‌نویسد.

    QuantResearchBridge این فایل را می‌خواند تا بداند هر جفت با چه استراتژی ترید کند.
    در سیستم جدید، جفت‌ها از ML fitness می‌آیند و استراتژی ثابت (default_strategy) است.
    """
    manifest_path = spec.get("manifest_path")
    if not manifest_path:
        return
    tf = spec["trade_timeframe"]
    strategy = spec.get("default_strategy", "ema_trend")
    candidates = []
    for pair, info in assignments.items():
        score = info.get("last_score") or table.get(_base_of(pair), {}).get("score", 50)
        oos_sharpe = round(float(score or 50) / 33.0, 2)  # score 0-100 → proxy 0-3
        candidates.append({
            "symbol": pair,
            "timeframe": tf,
            "strategy": strategy,
            "allow_short": True,
            "oos_sharpe": oos_sharpe,
            "weight": 1.0,
        })
    manifest = {
        "generated_at": _now(),
        "source": "rotate_bot_pairs",
        "candidates": candidates,
    }
    Path(manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest -> {manifest_path}")


def apply_change(spec: dict, new_whitelist: list[str], pair_out: str | None) -> None:
    _docker("stop", spec["container"], timeout=240)
    try:
        write_whitelist(spec["config"], new_whitelist)
        if pair_out:
            cleanup_pair_models(spec, pair_out)
    finally:
        _docker("start", spec["container"], timeout=120)


# ── انتخاب تایم‌فریم (فقط بات‌های select_timeframe، مثل Popeye) ─────────────────

def _tf_rank_score(table: dict[str, dict], n_pairs: int) -> float:
    """لبهٔ ML یک تایم‌فریم = میانگین امتیاز n جفتِ برترش."""
    scores = sorted((v["score"] for v in table.values()), reverse=True)[:n_pairs]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def select_timeframe_tables(spec: dict, processed_dir: Path
                            ) -> tuple[dict[str, dict], dict[str, float]]:
    """برای هر تایم‌فریم کاندید، جدول امتیاز ML بساز و رتبه‌اش را حساب کن."""
    tables_by_tf: dict[str, dict] = {}
    rank_by_tf: dict[str, float] = {}
    for tf in spec["candidate_timeframes"]:
        s = dict(spec)
        s["score_timeframe"] = tf
        tbl = score_table(s, processed_dir)
        tables_by_tf[tf] = tbl
        rank_by_tf[tf] = _tf_rank_score(tbl, spec["n_pairs"])
    return tables_by_tf, rank_by_tf


def pick_best_timeframe(rank_by_tf: dict[str, float], candidates: list[str],
                        higher_bias: float) -> str:
    """tf با بیشترین لبهٔ ML؛ اگر tf بالاتری در فاصلهٔ higher_bias از آن بود، آن را
    ترجیح بده (تایم‌فریم بزرگ‌تر = تریدِ کمتر = هم‌سو با هدف < ۱۰ ترید/روز)."""
    best = max(candidates, key=lambda tf: rank_by_tf.get(tf, 0.0))
    best_score = rank_by_tf.get(best, 0.0)
    for tf in sorted(candidates, key=lambda t: TF_ORDER.get(t, 99)):
        if (TF_ORDER.get(tf, 99) > TF_ORDER.get(best, 99)
                and rank_by_tf.get(tf, 0.0) >= best_score - higher_bias):
            best = tf
    return best


def wipe_all_models(spec: dict) -> None:
    """تغییر تایم‌فریم ⇒ همهٔ مدل‌های قبلی بی‌اعتبارند (ویژگی‌ها روی tf دیگری ساخته شده‌اند).
    محتویات را به یک trash منتقل کن (mv نه rm؛ inodeِ پوشه برای mountِ tb-popeye می‌ماند)."""
    mdir = spec.get("models_dir")
    if not mdir or not Path(mdir).exists():
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    trash = Path(mdir) / f".trash_{ts}"
    trash.mkdir(parents=True, exist_ok=True)
    for child in Path(mdir).iterdir():
        if child.name.startswith(".trash_"):
            continue
        shutil.move(str(child), str(trash / child.name))
    print(f"wiped all models → {trash}")


def apply_timeframe_switch(spec: dict, new_tf: str, new_whitelist: list[str]) -> None:
    """stop → نوشتن timeframe + include_timeframes + whitelist تازه → پاکسازی کاملِ
    مدل‌ها → start."""
    inc = [new_tf]
    higher = spec.get("informative_higher", {}).get(new_tf)
    if higher:
        inc.append(higher)
    _docker("stop", spec["container"], timeout=240)
    try:
        write_timeframe(spec["config"], new_tf, inc)
        write_whitelist(spec["config"], new_whitelist)
        wipe_all_models(spec)
    finally:
        _docker("start", spec["container"], timeout=120)


def decide_with_timeframe(bot: str, spec: dict, st: dict, processed_dir: Path,
                          apply: bool) -> tuple[dict, dict]:
    """مسیر Popeye: اول تایم‌فریم (هیسترزیس)، بعد چرخش جفت روی تایم‌فریمِ جاری.

    برمی‌گرداند (table_used, decision). table_used جدولِ تایم‌فریمِ مؤثر است
    (برای داشبورد). تصمیمِ tf_switch، چرخش جفت همان دور را رد می‌کند چون کل
    سبد بازانتخاب شده.
    """
    now = _now()
    bst = st.setdefault(bot, {"assignments": {}, "streaks": {}, "tf_streaks": {}})
    bst.setdefault("tf_streaks", {})

    tables_by_tf, rank_by_tf = select_timeframe_tables(spec, processed_dir)
    cur_tf = read_timeframe(spec["config"]) or spec["trade_timeframe"]
    best_tf = pick_best_timeframe(rank_by_tf, spec["candidate_timeframes"],
                                  float(spec.get("tf_higher_bias", 0)))
    print(f"[{spec['label']}] tf ranks {rank_by_tf}; current={cur_tf} best={best_tf}")

    # هیسترزیس tf: استریک فقط برای «تایم‌فریمِ متفاوتِ مطلوب» جلو می‌رود
    if best_tf != cur_tf:
        bst["tf_streaks"] = {best_tf: bst["tf_streaks"].get(best_tf, 0) + 1}
    else:
        bst["tf_streaks"] = {}
    tf_streak = bst["tf_streaks"].get(best_tf, 0)

    open_pairs = open_trade_pairs(spec["sqlite"])
    spec["score_timeframe"] = cur_tf

    if best_tf != cur_tf and tf_streak >= int(spec.get("tf_switch_streak", 2)):
        if open_pairs:  # تریدِ باز ⇒ سوییچ tf را عقب بینداز (مدل‌ها وایپ می‌شوند)
            decision = {"bot": spec["label"], "checked_at": now, "action": "tf_blocked",
                        "tf_from": cur_tf, "tf_to": best_tf, "tf_streak": tf_streak,
                        "blockers": ["open_trade"], "tf_ranks": rank_by_tf}
            log_event(apply, bot=spec["label"], event="tf_blocked",
                      tf_from=cur_tf, tf_to=best_tf, blockers=["open_trade"])
            spec["trade_timeframe"] = cur_tf
            return tables_by_tf.get(cur_tf, {}), decision

        ranked = sorted(tables_by_tf[best_tf].items(),
                        key=lambda kv: kv[1]["score"], reverse=True)
        quote = spec.get("quote", "USDT")
        new_basket = [_pair_of(b, quote) for b, _ in ranked[: spec["n_pairs"]]]
        decision = {"bot": spec["label"], "checked_at": now, "action": "tf_switch",
                    "tf_from": cur_tf, "tf_to": best_tf, "new_whitelist": new_basket,
                    "tf_ranks": rank_by_tf}
        if apply:
            try:
                apply_timeframe_switch(spec, best_tf, new_basket)
                bst["assignments"] = {
                    p: {"assigned_at": now, "source": "tf_switch",
                        "last_score": tables_by_tf[best_tf].get(_base_of(p), {}).get("score"),
                        "score_at": now}
                    for p in new_basket}
                bst["streaks"] = {}
                bst["tf_streaks"] = {}
                spec["trade_timeframe"] = best_tf
                spec["score_timeframe"] = best_tf
                log_event(apply, bot=spec["label"], event="tf_switch",
                          tf_from=cur_tf, tf_to=best_tf, new_whitelist=new_basket)
            except Exception as exc:
                decision.update(action="error", error=str(exc))
                log_event(apply, bot=spec["label"], event="error", error=str(exc),
                          attempted={"tf_switch": best_tf})
        else:
            log_event(apply, bot=spec["label"], event="would_tf_switch",
                      tf_from=cur_tf, tf_to=best_tf, new_whitelist=new_basket)
        return tables_by_tf[best_tf], decision

    # بدون سوییچ: چرخش معمولیِ جفت روی تایم‌فریمِ جاری
    spec["trade_timeframe"] = cur_tf
    table = tables_by_tf.get(cur_tf, {})
    decision = decide(bot, spec, st, table, apply)
    decision.update(tf_current=cur_tf, tf_best=best_tf, tf_streak=tf_streak,
                    tf_ranks=rank_by_tf)
    return table, decision


# ── خروجی داشبوردها ───────────────────────────────────────────────────────────

def write_assignments(st: dict, decisions: dict, tables: dict,
                      soodo_db: Path | None) -> None:
    # اجرای جزئی (مثل --bots popeye هر ۴ ساعت) نباید بخش بات‌های دیگر را در
    # داشبورد خالی کند → سکشن بات‌های پردازش‌نشده را از فایل قبلی نگه می‌داریم.
    try:
        prev = json.loads(ASSIGN_PATH.read_text(encoding="utf-8")).get("bots", {})
    except Exception:
        prev = {}
    bots_out = {}
    for bot, spec in BOTS.items():
        if bot not in tables and spec["label"] in prev:
            bots_out[spec["label"]] = prev[spec["label"]]
            continue
        bst = st.get(bot, {})
        table = tables.get(bot, {})
        quote = spec.get("quote", "USDT")
        ranked = sorted(table.items(), key=lambda kv: kv[1]["score"], reverse=True)
        assignments = bst.get("assignments", {})
        bots_out[spec["label"]] = {
            "kind": spec["kind"], "exchange": spec["exchange"],
            "trade_timeframe": spec["trade_timeframe"],
            "score_timeframe": spec["score_timeframe"],
            "n_pairs": spec["n_pairs"], "min_dwell_days": spec["min_dwell_days"],
            "switch_streak": spec["switch_streak"],
            "switch_margin": spec["switch_margin"],
            "pairs": assignments,
            "streaks": bst.get("streaks", {}),
            "candidates_top": [
                {"base": b, "pair": _pair_of(b, quote), "score": v["score"],
                 "incumbent": _pair_of(b, quote) in assignments,
                 "streak": bst.get("streaks", {}).get(b, 0),
                 "detail": v["detail"]}
                for b, v in ranked[:10]],
            "last_decision": decisions.get(bot),
        }
    payload = {"generated_at": _now(), "bots": bots_out}
    ASSIGN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"assignments -> {ASSIGN_PATH}")

    # manifest برای بات‌هایی که QuantResearchBridge از آن می‌خوانند (مثل Wall_E)
    for bot, spec in BOTS.items():
        if spec.get("manifest_path"):
            bst = st.get(bot, {})
            write_bot_manifest(spec, bst.get("assignments", {}), tables.get(bot, {}))

    if soodo_db and soodo_db.is_dir():
        try:
            shutil.copy2(ASSIGN_PATH, soodo_db / "qr_pair_rotation.json")
            if HISTORY_PATH.exists():
                shutil.copy2(HISTORY_PATH, soodo_db / "qr_pair_rotation_history.jsonl")
            print(f"synced -> {soodo_db}/qr_pair_rotation*.json")
        except Exception as exc:
            print(f"WARN: soodo sync failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="بدون این فلگ فقط dry-run است (نه state، نه کانفیگ، نه ری‌استارت)")
    ap.add_argument("--bots", nargs="*", default=list(BOTS),
                    choices=list(BOTS))
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--soodo-db", default="/home/h0551user/soodo/app_db")
    args = ap.parse_args()

    processed_dir = Path(args.processed)
    st = load_state()
    decisions, tables = {}, {}
    for bot in args.bots:
        spec = BOTS[bot]
        if spec.get("select_timeframe"):
            # Popeye: تایم‌فریم + جفت‌ها هر دو از لبهٔ ML کوانت (با هیسترزیس)
            table, decision = decide_with_timeframe(bot, spec, st, processed_dir,
                                                    apply=args.apply)
            tables[bot] = table
            decisions[bot] = decision
            d = decision
            extra = ""
            if d["action"] in ("tf_switch", "would_tf_switch", "tf_blocked"):
                extra = f" tf {d.get('tf_from')}→{d.get('tf_to')}"
            elif d["action"] != "hold":
                extra = f" {d.get('pair_out', '∅')} -> {d.get('pair_in', '')}"
            print(f"[{spec['label']}] decision: {d['action']}{extra}")
            continue
        table = score_table(spec, processed_dir)
        tables[bot] = table
        ranked = sorted(table.items(), key=lambda kv: kv[1]["score"], reverse=True)
        print(f"[{spec['label']}] scored {len(table)} bases; "
              f"top: {[(b, v['score']) for b, v in ranked[:6]]}")
        decisions[bot] = decide(bot, spec, st, table, apply=args.apply)
        d = decisions[bot]
        print(f"[{spec['label']}] decision: {d['action']}"
              + (f" {d.get('pair_out', '∅')} -> {d.get('pair_in', '')}"
                 if d["action"] != "hold" else ""))

    if args.apply:
        save_state(st)
        write_assignments(st, decisions, tables, Path(args.soodo_db))
    else:
        print("dry-run: state/assignments untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
