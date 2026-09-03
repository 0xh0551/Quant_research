"""Per-bot exit actuator from live trade geometry (MFE/MAE) — the "analytics acts" layer.

Owner asks (2026-08-19):
  * «چرا فقط یک بات اکچوئیتور دارد؟ هر باتی اکچوئیتور خودش را داشته باشد» → one tuner,
    seven bots, each gets its own evidence-based take-profit in PRICE space, written to
    user_data/agent_exits.json and read by the shared strategy helper `_agent_exit.py`.
  * «تمایز مشکلِ ورود از مشکلِ خروج» → `diagnose()` labels each bot exit_problem /
    entry_problem / healthy from MFE + capture, so risk directives stop treating every
    bleeding bot the same way (sizing cuts don't fix a leak in the exit).
  * «MAE → اعتبارسنجی پهنای استاپ» → `stop_geometry()` (diagnostic only): how much of
    the stop distance winners use, and how many stop-outs had real profit first.

Honesty rules (platform): the counterfactual is exact for a flat TP (we know MFE), so we
only actuate what we can simulate. Guards: n>=MIN_N, improvement >= MIN_IMPROVE_USD raw and
smoothed, positive in BOTH chronological halves, tp in [MIN_TP, MAX_TP] price space. Every
number is in-sample by construction — expect the live effect to be smaller; the nightly
rerun + guards are what keep a lucky number from surviving.

Ratchet actuator (2026-08-28, Popeye MU post-mortem): a fixed TP kept failing the
stability gate because it cuts runners; an ARMED giveback ratchet (lock peak*(1-g) once
MFE >= arm) exits round-trips like MU (+3.3% → −3%) while letting winners run. Its
counterfactual is NOT exact from MFE alone (the 08-12 trailing lesson), so it is
path-simulated on 1h candles fetched from the bot's own venue, adverse-extreme-first
(pessimistic). Parameters are FIXED (RATCHET_ARM/RATCHET_GIVEBACK), not optimised per
bot — the 08-27 grid was flat across (arm, g), so we take the anti-overfit point. The
ratchet replaces the flat TP for a bot only when its pessimistic improvement beats the
TP's exact one and passes the same $-and-halves guards.

Read-only on bot DBs. Writes ONLY outputs/agent_exits_evidence.json and (atomic)
<user_data>/agent_exits.json.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src import local_config

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
EVIDENCE = OUT / "agent_exits_evidence.json"

UTC = UTC
FEE_RT = 0.0012           # round-trip taker fee on notional (conservative across venues)
MIN_N = 8
MIN_TP, MAX_TP = 0.01, 0.08   # 1% کف: زیرِ آن اسکالپِ نویزِ کندلی است (درسِ براکتِ 08-12)
GRID_STEP = 0.0025
SMOOTH_STEPS = 2          # ±0.5%
MIN_IMPROVE_USD = 20.0
MAX_LOOKBACK_D = 60

# راچتِ مسلح‌شونده — پارامترها ثابت و ضدِ overfit (گریدِ 08-27 در کل بازه مثبت بود)
RATCHET_ARM = 0.02        # price-space MFE that arms the ratchet
RATCHET_GIVEBACK = 0.40   # exit when price gives back this fraction of the peak move
RATCHET_MIN_COVERAGE = 0.8  # need candles for >=80% of trades or refuse to actuate
CANDLE_CACHE = OUT / "candle_cache"

# هر بات از «دوره‌ی معماریِ فعلی»اش سنجیده می‌شود — دوره‌های بازنشسته نمی‌آیند،
# وگرنه استراتژیِ بازنویسی‌شده با رفتارِ نسخهٔ قبلیِ خودش قضاوت می‌شود.
# تاریخ‌ها site-local‌اند و از configs/local.json می‌آیند (کلیدِ `bot_epochs`).
BOT_EPOCH = local_config.bot_epochs()
# تشخیص: MFE میانگین (قیمتی) بالای این و capture ≤ 0 با PnL منفی = مشکلِ خروج
DIAG_MFE_EXIT = 0.012
DIAG_CAPTURE_EXIT = 0.10
DIAG_MFE_ENTRY = 0.006


def _bot_dbs() -> dict[str, Path]:
    dbs = local_config.bot_databases()
    if dbs:
        return dbs
    ud = local_config.user_data_dir()
    if ud is None:
        return {}
    return {b: db for b, db in local_config.bot_databases().items() if db.exists()}


def load_bot_trades(bot: str, db: Path | None = None) -> pd.DataFrame:
    """Closed organic trades of `bot` since its epoch (max MAX_LOOKBACK_D), with
    price-space mfe/mae, stop distance and realised move."""
    db = db or _bot_dbs().get(bot)
    if db is None or not Path(db).exists():
        return pd.DataFrame()
    since = max(pd.Timestamp(BOT_EPOCH.get(bot, "2000-01-01")),
                pd.Timestamp.now() - pd.Timedelta(days=MAX_LOOKBACK_D)).strftime("%Y-%m-%d")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        df = pd.read_sql(
            "SELECT pair, is_short, open_rate, close_rate, max_rate, min_rate, stake_amount, "
            "leverage, close_profit_abs, exit_reason, enter_tag, open_date, close_date, "
            "initial_stop_loss_pct, stop_loss_pct "
            "FROM trades WHERE is_open=0 AND close_date >= ?", con, params=(since,))
    finally:
        con.close()
    df = df.dropna(subset=["open_rate", "close_rate", "max_rate", "min_rate"])
    if df.empty:
        return df
    side = np.where(df["is_short"] == 1, -1.0, 1.0)
    o = df["open_rate"].astype(float)
    df["mfe"] = np.where(side > 0, df["max_rate"] / o - 1, 1 - df["min_rate"] / o).clip(min=0)
    df["mae"] = np.where(side > 0, 1 - df["min_rate"] / o, df["max_rate"] / o - 1).clip(min=0)
    df["move"] = (df["close_rate"] / o - 1) * side
    lev = pd.to_numeric(df["leverage"], errors="coerce").fillna(1.0).clip(lower=1.0)
    df["leverage"] = lev
    # فاصله‌ی استاپ در فضای قیمت: stoploss فریک‌ترید نسبت به ROE است → ÷ اهرم
    isl = pd.to_numeric(df["initial_stop_loss_pct"], errors="coerce").abs()
    df["stop_dist"] = (isl / lev).where(isl.notna() & (isl > 0) & (isl < 1.0))
    df["organic"] = df["enter_tag"].fillna("") != "activity_floor"
    df["close_date"] = pd.to_datetime(df["close_date"])
    return df[df["organic"]].sort_values("close_date").reset_index(drop=True)


def sim_pnl(df: pd.DataFrame, tp: float) -> float:
    hit = df["mfe"] >= tp
    gain = (tp - FEE_RT) * df["stake_amount"] * df["leverage"]
    return float(np.where(hit, gain, df["close_profit_abs"]).sum())


def tune(df: pd.DataFrame) -> dict:
    """Grid + smoothing + guards -> {'tp': float|None, ...evidence}."""
    n = len(df)
    actual = round(float(df["close_profit_abs"].sum()), 2) if n else 0.0
    ev: dict = {"n": n, "actual_pnl": actual,
                "mfe_mean": round(float(df["mfe"].mean()), 4) if n else None,
                "mfe_median": round(float(df["mfe"].median()), 4) if n else None}
    if n < MIN_N:
        ev.update({"tp": None, "why": f"insufficient evidence (n={n} < {MIN_N})"})
        return ev
    grid = np.round(np.arange(MIN_TP, MAX_TP + 1e-9, GRID_STEP), 4)
    sims = np.array([sim_pnl(df, tp) for tp in grid])
    smooth = np.array([sims[max(0, i - SMOOTH_STEPS):i + SMOOTH_STEPS + 1].mean()
                       for i in range(len(grid))])
    i = int(np.argmax(smooth))
    tp = float(grid[i])
    raw_imp = round(float(sims[i] - actual), 2)
    smooth_imp = round(float(smooth[i] - actual), 2)
    half = n // 2
    h1, h2 = df.iloc[:half], df.iloc[half:]
    imp1 = round(sim_pnl(h1, tp) - float(h1["close_profit_abs"].sum()), 2)
    imp2 = round(sim_pnl(h2, tp) - float(h2["close_profit_abs"].sum()), 2)
    ev.update({"curve": [[float(g), round(float(s), 2)] for g, s in zip(grid, sims, strict=True)],
               "tp_candidate": tp, "sim_pnl": round(float(sims[i]), 2),
               "raw_improvement": raw_imp, "smooth_improvement": smooth_imp,
               "split_half_improvement": [imp1, imp2],
               "hit_share": round(float((df["mfe"] >= tp).mean()), 3)})
    if raw_imp < MIN_IMPROVE_USD or smooth_imp < MIN_IMPROVE_USD:
        ev.update({"tp": None, "why": f"improvement below ${MIN_IMPROVE_USD:.0f}"})
    elif i == 0:
        # قله روی لبه‌ی پایینِ گرید = نمی‌دانیم پایین‌تر چه می‌شود؛ بوی اسکالپِ نویز (درسِ 08-12) → رد
        ev.update({"tp": None, "why": "peak at the 1% grid edge — noise-level suspicion, refused"})
    elif imp1 <= 0 or imp2 <= 0:
        ev.update({"tp": None, "why": f"unstable across halves ({imp1}, {imp2})"})
    else:
        ev.update({"tp": tp, "why": "ok"})
    return ev


_EXCHANGES: dict[str, object] = {}


def _exchange_for(bot: str):
    """ccxt swap client from the bot's own freqtrade config (exchange.name); None = no ratchet."""
    if bot in _EXCHANGES:
        return _EXCHANGES[bot]
    ex = None
    try:
        import re

        import ccxt
        cfg_path = local_config.bot_configs().get(bot)
        raw = Path(cfg_path).read_text()
        # کانفیگ فریک‌ترید می‌تواند کامنت و کامای انتهایی داشته باشد (rapidjson) — json.loads نه
        raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)   # کامنتِ تمام‌خط (هرچه باشد)
        raw = re.sub(r"//[^\n\"]*$", "", raw, flags=re.M)  # کامنتِ انتهای خط، بدونِ " (URLها امن)
        raw = re.sub(r",(\s*[}\]])", r"\1", raw)
        name = json.loads(raw)["exchange"]["name"].lower()
        cls = getattr(ccxt, name, None) or getattr(ccxt, {"gate": "gateio"}.get(name, ""), None)
        if cls is not None:
            ex = cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    except Exception:
        ex = None
    _EXCHANGES[bot] = ex
    return ex


def _trade_candles(ex, pair: str, t0: float, t1: float) -> list | None:
    """1h OHLCV for [t0, t1] via per-pair JSON cache — closed-trade windows never change,
    so the nightly rerun only hits the network for the newest trades."""
    CANDLE_CACHE.mkdir(parents=True, exist_ok=True)
    f = CANDLE_CACHE / (pair.replace("/", "_").replace(":", "_") + ".json")
    key = f"{int(t0)}_{int(t1)}"
    try:
        store = json.loads(f.read_text()) if f.exists() else {}
    except ValueError:
        store = {}
    if key in store:
        return store[key]
    out: list = []
    try:
        since = int(t0 * 1000)
        while since < t1 * 1000:
            batch = ex.fetch_ohlcv(pair, "1h", since=since, limit=500)
            if not batch:
                break
            out += batch
            since = batch[-1][0] + 3_600_000
            if len(batch) < 500:
                break
    except Exception:
        return None
    out = [c for c in out if t0 * 1000 <= c[0] <= t1 * 1000]
    store[key] = out
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(store))
    tmp.replace(f)
    return out


def _ratchet_trade_pnl(row, ex, arm: float, g: float) -> float | None:
    """Pessimistic 1h path sim of the armed ratchet for one closed trade: within each
    candle the ADVERSE extreme is applied before the favourable one, and the exit fill is
    the lock level itself. None = no candles (caller keeps the actual exit)."""
    t0 = pd.Timestamp(row["open_date"]).timestamp()
    t1 = pd.Timestamp(row["close_date"]).timestamp()
    o = _trade_candles(ex, row["pair"], t0, t1)
    if not o:
        return None
    op, short = float(row["open_rate"]), bool(row["is_short"])
    peak = 0.0
    for _ts, _o, hi, lo, _cl, _v in o:
        fav_adverse = (op - hi) / op if short else (lo - op) / op
        fav_best = (op - lo) / op if short else (hi - op) / op
        if peak >= arm:
            lock = peak * (1 - g)
            if fav_adverse <= lock:
                return float((lock - FEE_RT) * row["stake_amount"] * row["leverage"])
        peak = max(peak, fav_best)
    return float(row["close_profit_abs"])


def tune_ratchet(df: pd.DataFrame, bot: str) -> dict:
    """Path-simulated counterfactual of the fixed-parameter ratchet, same guards as tune():
    n, $-improvement, positive in both chronological halves, plus candle coverage."""
    n = len(df)
    ev: dict = {"arm_pct": RATCHET_ARM, "giveback": RATCHET_GIVEBACK, "n": n,
                "ratchet": None}
    if n < MIN_N:
        ev["why"] = f"insufficient evidence (n={n} < {MIN_N})"
        return ev
    ex = _exchange_for(bot)
    if ex is None:
        ev["why"] = "no exchange client for candle path-sim"
        return ev
    sims, covered = [], 0
    for _, row in df.iterrows():
        v = _ratchet_trade_pnl(row, ex, RATCHET_ARM, RATCHET_GIVEBACK)
        if v is None:
            v = float(row["close_profit_abs"])
        else:
            covered += 1
        sims.append(v)
    coverage = covered / n
    ev["candle_coverage"] = round(coverage, 3)
    s = pd.Series(sims)
    actual = float(df["close_profit_abs"].sum())
    half = n // 2
    imp = round(float(s.sum() - actual), 2)
    imp1 = round(float(s.iloc[:half].sum() - df["close_profit_abs"].iloc[:half].sum()), 2)
    imp2 = round(float(s.iloc[half:].sum() - df["close_profit_abs"].iloc[half:].sum()), 2)
    ev.update({"sim_pnl": round(float(s.sum()), 2), "improvement": imp,
               "split_half_improvement": [imp1, imp2]})
    if coverage < RATCHET_MIN_COVERAGE:
        ev["why"] = f"candle coverage {coverage:.0%} < {RATCHET_MIN_COVERAGE:.0%}"
    elif imp < MIN_IMPROVE_USD:
        ev["why"] = f"improvement below ${MIN_IMPROVE_USD:.0f}"
    elif imp1 <= 0 or imp2 <= 0:
        ev["why"] = f"unstable across halves ({imp1}, {imp2})"
    else:
        ev.update({"ratchet": {"arm_pct": RATCHET_ARM, "giveback": RATCHET_GIVEBACK},
                   "why": "ok"})
    return ev


def capture_stats(df: pd.DataFrame) -> dict:
    """Sum-weighted capture (realised move / MFE) — same definition as the FreqUI tab."""
    if df.empty:
        return {"capture_weighted": None, "capture_median": None}
    pos = df[df["mfe"] > 0]
    cw = float(pos["move"].sum() / pos["mfe"].sum()) if len(pos) and pos["mfe"].sum() > 0 else None
    cm = float((pos["move"] / pos["mfe"]).median()) if len(pos) else None
    return {"capture_weighted": round(cw, 3) if cw is not None else None,
            "capture_median": round(cm, 3) if cm is not None else None}


def diagnose(df: pd.DataFrame) -> dict:
    """entry_problem / exit_problem / healthy / insufficient — from MFE + capture + PnL."""
    n = len(df)
    if n < MIN_N:
        return {"label": "insufficient", "n": n}
    pnl = float(df["close_profit_abs"].sum())
    mfe = float(df["mfe"].mean())
    cs = capture_stats(df)
    cw = cs["capture_weighted"] if cs["capture_weighted"] is not None else 0.0
    if pnl > 0 and cw > 0.15:
        label = "healthy"
    elif mfe >= DIAG_MFE_EXIT and cw <= DIAG_CAPTURE_EXIT:
        label = "exit_problem"        # پول روی میز بود؛ خروج آن را پس داد
    elif mfe < DIAG_MFE_ENTRY:
        label = "entry_problem"       # هیچ‌وقت واقعاً کار نکرد؛ ورود/انتخاب مشکل دارد
    elif pnl <= 0:
        label = "mixed"
    else:
        label = "healthy"
    return {"label": label, "n": n, "pnl": round(pnl, 2), "mfe_mean": round(mfe, 4), **cs,
            "hint": {"exit_problem": "signal finds moves; exits leak them -> actuator/TP, not sizing cuts",
                     "entry_problem": "moves never materialise -> sizing cut / bench / rotation",
                     "mixed": "small MFE and weak capture -> both sides weak",
                     "healthy": "keep", "insufficient": "wait"}[label]}


def stop_geometry(df: pd.DataFrame) -> dict:
    """Diagnostic: are stops too tight/wide? (no actuation)
    - winners' MAE as a share of the stop distance (p50/p90): near 1 = survived by luck
    - stop-outs that had MFE >= 1% price first (gave back, then stopped) = ratchet problem
    - share of exits that are stops"""
    if df.empty:
        return {}
    w = df[df["close_profit_abs"] > 0]
    ws = w.dropna(subset=["stop_dist"])
    usage = (ws["mae"] / ws["stop_dist"]).replace([np.inf], np.nan).dropna() if len(ws) else pd.Series(dtype=float)
    stops = df[df["exit_reason"].fillna("").str.contains("stop|liquidation", case=False)]
    gave_back = stops[stops["mfe"] >= 0.01]
    return {"n_winners": len(w), "n_with_stop_info": len(ws),
            "winner_stop_usage_p50": round(float(usage.quantile(0.5)), 2) if len(usage) else None,
            "winner_stop_usage_p90": round(float(usage.quantile(0.9)), 2) if len(usage) else None,
            "winners_near_stop_share": round(float((usage >= 0.8).mean()), 3) if len(usage) else None,
            "stop_exits": len(stops), "stop_exit_share": round(float(len(stops) / len(df)), 3),
            "stop_exits_gave_back_first": len(gave_back),
            "stop_exits_gave_back_usd": round(float(gave_back["close_profit_abs"].sum()), 2),
            "median_stop_dist_pct": round(float(df["stop_dist"].median() * 100), 3) if df["stop_dist"].notna().any() else None,
            "read": ("stops look TIGHT (many winners used >80% of the distance)" if len(usage) and float((usage >= 0.8).mean()) > 0.3
                     else "stops wide enough for winners" if len(usage) else "no stop info")}


def pair_capture(df: pd.DataFrame, min_n: int = 4) -> list[dict]:
    """Per-pair capture league — the visible form of «جفت‌هایی که MFE بزرگ دارند ولی
    capture منفی» (big moves we never bank). Diagnostic; rotation penalty is a
    separate owner decision."""
    rows = []
    for pair, g in df.groupby("pair"):
        if len(g) < min_n:
            continue
        cs = capture_stats(g)
        rows.append({"pair": pair, "n": len(g), "pnl": round(float(g["close_profit_abs"].sum()), 2),
                     "mfe_mean": round(float(g["mfe"].mean()), 4), **cs,
                     "flag": ("big_mfe_negative_capture" if float(g["mfe"].mean()) >= 0.02
                              and (cs["capture_weighted"] or 0) <= 0 else "")})
    return sorted(rows, key=lambda r: r["pnl"])[:12]


def tune_fleet() -> tuple[dict, dict]:
    """Returns (payload_for_bots, evidence). payload = {bot: {tp_long_pct, tp_short_pct,
    diagnosis, ...}} written to user_data/agent_exits.json."""
    payload_bots, evidence = {}, {}
    for bot in _bot_dbs():
        df = load_bot_trades(bot)
        pooled = tune(df) if len(df) else {"n": 0, "tp": None, "why": "no trades"}
        sides = {}
        for name, sub in (("long", df[df["is_short"] == 0] if len(df) else df),
                          ("short", df[df["is_short"] == 1] if len(df) else df)):
            sides[name] = tune(sub) if len(sub) >= MIN_N else {"n": len(sub), "tp": None,
                                                                "why": "n<MIN_N -> pooled"}
        tp_long = sides["long"].get("tp") or pooled.get("tp")
        tp_short = sides["short"].get("tp") or pooled.get("tp")
        rt = tune_ratchet(df, bot) if len(df) else {"ratchet": None, "why": "no trades"}
        # راچت جای TP ثابت می‌نشیند فقط وقتی شبیه‌سازیِ بدبینانه‌اش از بهبودِ دقیقِ TP بهتر
        # باشد — دو اکچوئیتورِ هم‌زمان رفتاری می‌سازد که هیچ‌کدام از سیم‌ها معتبرش نکرده.
        tp_imp = pooled.get("raw_improvement") if pooled.get("tp") is not None else None
        use_ratchet = rt.get("ratchet") is not None and (
            tp_imp is None or float(rt.get("improvement") or 0) >= float(tp_imp))
        if use_ratchet:
            tp_long = tp_short = None
        diag = diagnose(df) if len(df) else {"label": "insufficient", "n": 0}
        stops = stop_geometry(df) if len(df) else {}
        pairs = pair_capture(df) if len(df) else []
        payload_bots[bot] = {
            "tp_long_pct": tp_long, "tp_short_pct": tp_short,
            "ratchet": rt.get("ratchet") if use_ratchet else None,
            "diagnosis": diag.get("label"),
            "epoch": BOT_EPOCH.get(bot), "n": len(df),
            "why": (f"ratchet: {rt.get('why')}" if use_ratchet else pooled.get("why")),
        }
        evidence[bot] = {"pooled": pooled, "sides": sides, "ratchet": rt,
                        "diagnosis": diag,
                        "stop_geometry": stops, "pair_capture": pairs,
                        "epoch": BOT_EPOCH.get(bot), "n": len(df)}
    return payload_bots, evidence


def write(payload_bots: dict, evidence: dict) -> Path | None:
    now = datetime.now(UTC).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({"generated_at": now, "bots": evidence}, indent=1,
                                   ensure_ascii=False, default=str))
    ud = local_config.user_data_dir()
    if ud is None:
        return None
    payload = {"generated_at": now, "source": "exit_tuner.py (MFE counterfactual, per bot)",
               "bots": payload_bots}
    tmp = ud / "agent_exits.json.tmp"
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    tmp.replace(ud / "agent_exits.json")
    return ud / "agent_exits.json"
