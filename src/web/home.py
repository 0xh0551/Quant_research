"""Home-screen tile summaries.

The dashboard's landing view is a launcher grid where every tile is a live
widget, so it needs one cheap call that summarises *every* section at once.
Everything here reads files that some other job already wrote (``outputs/*.json``)
or nothing more expensive than ``stat()`` on the parquet store — no backtests,
no exchange round-trips, no parquet parsing. A tile that cannot be built is
omitted rather than failing the whole payload, and the result is TTL-cached so
a page full of widgets costs one disk sweep, not nineteen.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "processed"
OUTPUTS_DIR = ROOT / "outputs"
LOG_DIR = ROOT / "logs"

_TTL_SECONDS = 20.0
_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_cache_lock = threading.Lock()

_TF_ORDER = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
_TF_SET = set(_TF_ORDER)


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_json(name: str) -> Any:
    path = OUTPUTS_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _age_hours(iso: str | None) -> float | None:
    """Hours since an ISO timestamp, tolerant of trailing Z / offsets."""
    if not iso:
        return None
    try:
        txt = str(iso).replace("Z", "+00:00")
        ts = datetime.fromisoformat(txt)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return round((datetime.now(UTC) - ts).total_seconds() / 3600, 2)
    except Exception:
        return None


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


def _sorted_tf(counts: dict[str, int]) -> list[dict[str, Any]]:
    known = [{"k": tf, "v": counts[tf]} for tf in _TF_ORDER if tf in counts]
    other = sorted(((k, v) for k, v in counts.items() if k not in _TF_SET), key=lambda kv: -kv[1])
    return known + [{"k": k, "v": v} for k, v in other]


# ── dataset store (stat-only sweep, no parquet parsing) ───────────────────────

_DS_TTL = 60.0
_ds_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _scan_store() -> dict[str, Any]:
    """One ``stat()`` sweep of the parquet store, cached for a minute.

    Names look like ``<exchange>[_<market>]_<SYMBOL>_<tf>.parquet``; the parts we
    need for tile KPIs are all in the filename plus the stat block, so nothing
    here touches file *contents* (the store is ~1 GB across ~2.2k files).
    """
    now = time.time()
    if _ds_cache["value"] is not None and now - _ds_cache["at"] < _DS_TTL:
        return _ds_cache["value"]

    exchanges: Counter[str] = Counter()
    timeframes: Counter[str] = Counter()
    symbols: set[str] = set()
    venues_by_symbol: dict[str, set[str]] = {}
    total_bytes = 0
    n = 0
    fresh_24h = 0
    stale_30d = 0
    newest = 0.0
    added_24h = 0
    added_7d = 0
    biggest = {"name": "", "mb": 0.0}

    try:
        entries = list(DATA_DIR.glob("*.parquet"))
    except Exception:
        entries = []

    for path in entries:
        try:
            st = path.stat()
        except OSError:
            continue
        n += 1
        total_bytes += st.st_size
        age_h = (now - st.st_mtime) / 3600
        if age_h <= 24:
            fresh_24h += 1
            added_24h += 1
        if age_h <= 168:
            added_7d += 1
        if age_h > 720:
            stale_30d += 1
        newest = max(newest, st.st_mtime)
        mb = st.st_size / 1e6
        if mb > biggest["mb"]:
            biggest = {"name": path.stem, "mb": round(mb, 1)}

        parts = path.stem.split("_")
        if len(parts) < 2:
            continue
        tf = parts[-1]
        if tf in _TF_SET:
            timeframes[tf] += 1
        exch = parts[0].lower()
        exchanges[exch] += 1
        core = parts[1:-1]
        if core and core[0].lower() in ("futures", "perp", "perpetual", "spot", "um", "cm"):
            venue = f"{exch}_{core[0].lower()}"
            sym = "_".join(core[1:])
        else:
            venue = exch
            sym = "_".join(core)
        if sym:
            symbols.add(sym)
            venues_by_symbol.setdefault(sym, set()).add(venue)

    multi_venue = sum(1 for v in venues_by_symbol.values() if len(v) > 1)
    value = {
        "n_datasets": n,
        "total_gb": round(total_bytes / 1e9, 2),
        "n_exchanges": len(exchanges),
        "n_symbols": len(symbols),
        "by_exchange": [{"k": k, "v": v} for k, v in exchanges.most_common(6)],
        "by_timeframe": _sorted_tf(dict(timeframes)),
        "fresh_24h": fresh_24h,
        "stale_30d": stale_30d,
        "added_24h": added_24h,
        "added_7d": added_7d,
        "newest_age_h": round((now - newest) / 3600, 2) if newest else None,
        "biggest": biggest,
        "multi_venue_symbols": multi_venue,
        "n_venues": len({v for vs in venues_by_symbol.values() for v in vs}),
    }
    _ds_cache["value"] = value
    _ds_cache["at"] = now
    return value


# ── per-tile builders ─────────────────────────────────────────────────────────
# Every builder returns a flat dict of primitives + short arrays. Raising is
# fine: `summary()` catches per tile so one bad artifact cannot blank the grid.

def _tile_inventory() -> dict[str, Any]:
    s = _scan_store()
    return {
        "n_datasets": s["n_datasets"],
        "total_gb": s["total_gb"],
        "n_exchanges": s["n_exchanges"],
        "n_symbols": s["n_symbols"],
        "fresh_24h": s["fresh_24h"],
        "stale_30d": s["stale_30d"],
        "by_timeframe": s["by_timeframe"],
        "by_exchange": s["by_exchange"],
        "newest_age_h": s["newest_age_h"],
        "biggest": s["biggest"],
    }


def _tile_download() -> dict[str, Any]:
    s = _scan_store()
    return {
        "refreshed_24h": s["added_24h"],
        "refreshed_7d": s["added_7d"],
        "newest_age_h": s["newest_age_h"],
        "n_venues": s["n_venues"],
        "by_exchange": s["by_exchange"],
    }


def _tile_quality() -> dict[str, Any]:
    cov = _read_json("data_coverage.json") or {}
    datasets = cov.get("datasets") or []
    n = int(cov.get("n_datasets") or len(datasets))
    scannable = int(cov.get("n_scannable") or 0)
    bars = [int(d.get("bars") or 0) for d in datasets]
    gaps = 0
    today = datetime.now(UTC).date()
    for d in datasets:
        last = d.get("last")
        if not last:
            continue
        try:
            if (today - datetime.fromisoformat(str(last)).date()).days > 3:
                gaps += 1
        except Exception:
            pass
    return {
        "n_datasets": n,
        "n_scannable": scannable,
        "scannable_pct": round(100 * scannable / n, 1) if n else None,
        "stale_gt_3d": gaps,
        "median_bars": int(sorted(bars)[len(bars) // 2]) if bars else None,
        "min_scan_bars": cov.get("min_scan_bars"),
        "age_h": _age_hours(cov.get("generated_at")),
    }


def _tile_edges() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    rigor = rep.get("rigor") or {}
    top = []
    for e in (rep.get("top") or [])[:4]:
        top.append({
            "symbol": e.get("symbol"), "strategy": e.get("strategy"),
            "timeframe": e.get("timeframe"),
            "oos_sharpe": _num(e.get("oos_sharpe")),
            "deployable": bool(e.get("deployable")),
        })
    by_tf = rep.get("by_timeframe") or {}
    tf_counts: dict[str, int] = {}
    tf_robust: dict[str, int] = {}
    for tf, v in by_tf.items():
        if isinstance(v, dict):
            tf_counts[tf] = int(v.get("passed") or 0)
            tf_robust[tf] = int(v.get("robust") or 0)
        else:
            tf_counts[tf] = int(v or 0)
    return {
        "n_scanned": rep.get("n_scanned"),
        "n_passed": rep.get("n_passed"),
        "n_robust": rep.get("n_robust"),
        "n_deployable": rep.get("n_deployable"),
        "n_alerts": len(rep.get("alerts") or []),
        "live_timeframe": rep.get("live_timeframe"),
        "median_pbo": _num(rigor.get("median_pbo")),
        "deflated_frac": _num(rigor.get("deflated_frac")),
        "by_timeframe": _sorted_tf(tf_counts),
        "by_timeframe_robust": _sorted_tf(tf_robust),
        "top": top,
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_fleet() -> dict[str, Any]:
    fr = _read_json("fleet_risk.json") or {}
    f = fr.get("fleet") or {}
    limits = fr.get("limits") or {}
    bots = []
    for b in (fr.get("per_bot") or []):
        bots.append({
            "bot": b.get("bot"),
            "gross_leverage": _num(b.get("gross_leverage")),
            "n_open": b.get("n_open"),
            "pnl": _num(b.get("realized_pnl", 0)) or 0,
        })
    bots.sort(key=lambda b: -(b["gross_leverage"] or 0))
    return {
        "equity_usd": _num(f.get("equity_usd")),
        "gross_leverage": _num(f.get("gross_leverage")),
        "max_gross_leverage": _num(limits.get("max_gross_leverage")),
        "net_beta_delta_pct": _num(f.get("net_beta_delta_pct")),
        "avg_pairwise_corr": _num(f.get("avg_pairwise_corr")),
        "n_positions": f.get("n_positions"),
        "n_bots": f.get("n_bots"),
        "hhi": _num(f.get("hhi")),
        "n_alerts": len(fr.get("alerts") or []),
        "bots": bots[:7],
        "age_h": _age_hours(fr.get("generated_at")),
    }


def _tile_portfolio() -> dict[str, Any]:
    fr = _read_json("fleet_risk.json") or {}
    assets = fr.get("per_asset") or []
    total = sum(abs(_num(a.get("gross_notional")) or 0) for a in assets)
    top = []
    for a in sorted(assets, key=lambda a: -(abs(_num(a.get("gross_notional")) or 0)))[:6]:
        g = abs(_num(a.get("gross_notional")) or 0)
        top.append({
            "base": a.get("base"),
            "gross": round(g, 1),
            "pct": round(100 * g / total, 1) if total else 0.0,
            "n_bots": len(a.get("bots") or []),
        })
    s = _scan_store()
    return {
        "n_assets": len(assets),
        "gross_usd": round(total, 1),
        "hhi": _num((fr.get("fleet") or {}).get("hhi")),
        "top": top,
        "n_candidates": s["n_datasets"],
        "age_h": _age_hours(fr.get("generated_at")),
    }


def _tile_pipeline() -> dict[str, Any]:
    hb = _read_json("pipeline_health.json") or {}
    counts = hb.get("counts") or {}
    status = _read_json("pipeline_status.json") or {}
    worst = None
    for j in sorted((hb.get("jobs") or []), key=lambda j: -(_num(j.get("age_hours")) or 0)):
        if j.get("status") in ("late", "missing"):
            worst = {"name": j.get("name"), "status": j.get("status"),
                     "age_h": _num(j.get("age_hours")), "severity": j.get("severity")}
            break
    prog = _read_json("wf_scan_progress.json") or {}
    return {
        "healthy": hb.get("healthy"),
        "n_jobs": hb.get("n_jobs"),
        "ok": counts.get("ok"), "late": counts.get("late"), "missing": counts.get("missing"),
        "n_critical_failing": len(hb.get("critical_failing") or []),
        "worst": worst,
        "run_state": status.get("state"),
        "run_step": status.get("step"),
        "run_started_age_h": _age_hours(status.get("started_at")),
        "scan_done": prog.get("done"), "scan_total": prog.get("total"),
        "age_h": _age_hours(hb.get("generated_at")),
    }


def _tile_attribution() -> dict[str, Any]:
    at = _read_json("attribution_report.json") or {}
    totals = at.get("totals") or {}
    per_bot = at.get("per_bot") or []
    worst = None
    if per_bot:
        w = max(per_bot, key=lambda b: _num(b.get("execution_drag")) or 0)
        worst = {"bot": w.get("bot"), "drag": _num(w.get("execution_drag")),
                 "mfe_capture": _num(w.get("mfe_capture_mean"))}
    caps = [_num(b.get("mfe_capture_mean")) for b in per_bot]
    caps = [c for c in caps if c is not None]
    return {
        "window_days": _num(at.get("window_days")),
        "net": _num(totals.get("net")),
        "intended": _num(totals.get("intended")),
        "fees": _num(totals.get("fees")),
        "funding": _num(totals.get("funding")),
        "entry_slip": _num(totals.get("entry_slip")),
        "exit_slip": _num(totals.get("exit_slip")),
        "n_bots": len(per_bot),
        "worst": worst,
        "mfe_capture_avg": round(sum(caps) / len(caps), 3) if caps else None,
        "age_h": _age_hours(at.get("generated_at")),
    }


def _tile_trials() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    rigor = rep.get("rigor") or {}
    out: dict[str, Any] = {
        "n_scanned_tonight": rep.get("n_scanned"),
        "n_trials": rigor.get("n_trials"),
        "median_pbo": _num(rigor.get("median_pbo")),
        "n_deflated_pass": rigor.get("n_deflated_pass"),
        "age_h": _age_hours(rep.get("generated_at")),
    }
    try:
        from src.tracking.trial_ledger import default_ledger

        stats = default_ledger().family_stats("wf_scan") or {}
        n_unique = stats.get("n_unique") or 0
        passed = stats.get("n_ever_passed") or 0
        out.update({
            "n_unique": n_unique,
            "n_runs_total": stats.get("n_runs_total"),
            "n_ever_passed": passed,
            "pass_rate": round(100 * passed / n_unique, 2) if n_unique else None,
        })
    except Exception:
        pass
    return out


def _tile_stress() -> dict[str, Any]:
    st = _read_json("stress_report.json") or {}
    scen = st.get("scenarios") or []
    equity = _num(st.get("equity_usd")) or 0.0
    rows = []
    n_liq = 0
    for s in scen:
        loss = _num(s.get("fleet_pnl_usd"))
        pct = _num(s.get("fleet_pnl_pct"))
        if pct is None and loss is not None and equity:
            pct = round(100 * loss / equity, 2)
        n_liq += int(s.get("n_liquidations") or 0)
        rows.append({
            "key": s.get("key"), "kind": s.get("kind"),
            "label_fa": s.get("label_fa"), "label_en": s.get("label_en"),
            "loss": loss, "loss_pct": pct,
            "n_liquidations": s.get("n_liquidations"),
        })
    rows.sort(key=lambda r: (r["loss"] if r["loss"] is not None else 0))
    return {
        "equity_usd": equity,
        "n_positions": st.get("n_positions"),
        "n_scenarios": len(scen),
        "worst_key": st.get("worst_key"),
        "worst": rows[0] if rows else None,
        "rows": rows[:5],
        "n_liquidations": n_liq,
        "age_h": _age_hours(st.get("generated_at")),
    }


def _tile_capacity() -> dict[str, Any]:
    cap = _read_json("capacity_report.json") or {}
    edges = cap.get("edges") or []
    caps = sorted(_num(e.get("capacity_notional")) or 0 for e in edges)
    tight = None
    if edges:
        t = min(edges, key=lambda e: _num(e.get("capacity_notional")) or 0)
        tight = {"symbol": t.get("symbol"), "venue": t.get("venue"),
                 "capacity": _num(t.get("capacity_notional"))}
    return {
        "n_edges": cap.get("n_edges") or len(edges),
        "n_books": cap.get("n_books"),
        "fee_rt_bps": _num(cap.get("fee_rt_bps")),
        "median_capacity": caps[len(caps) // 2] if caps else None,
        "total_capacity": round(sum(caps), 0) if caps else None,
        "tightest": tight,
        "venues": [{"k": k, "v": _num(v)} for k, v in (cap.get("venue_k_median") or {}).items()],
        "age_h": _age_hours(cap.get("generated_at")),
    }


def _tile_altdata() -> dict[str, Any]:
    ad = _read_json("altdata_snapshot.json") or {}
    dvol = ad.get("dvol") or {}
    btc = dvol.get("BTC") if isinstance(dvol.get("BTC"), dict) else {"value": dvol.get("BTC")}
    eth = dvol.get("ETH") if isinstance(dvol.get("ETH"), dict) else {"value": dvol.get("ETH")}
    series = (ad.get("dvol_series_btc") or {}).get("values") or []
    series = [_num(v) for v in series[-40:]]
    per_sym = {p.get("symbol"): p for p in (ad.get("per_symbol") or [])}
    fx = ad.get("funding_extremes") or []
    extreme = None
    if fx:
        e = max(fx, key=lambda f: abs(_num(f.get("funding_ann_pct")) or 0))
        extreme = {"symbol": e.get("symbol"), "funding_ann_pct": _num(e.get("funding_ann_pct"))}
    return {
        "dvol_btc": _num(btc.get("value") if isinstance(btc, dict) else btc),
        "dvol_eth": _num(eth.get("value") if isinstance(eth, dict) else eth),
        "dvol_series": [v for v in series if v is not None],
        "liquidations_24h_usd": _num(ad.get("liquidations_24h_usd")),
        "ls_ratio_btc": _num((per_sym.get("BTCUSDT") or {}).get("ls_ratio")),
        "n_funding_extremes": len(fx),
        "funding_extreme": extreme,
        "age_h": _age_hours(ad.get("generated_at")),
    }


def _tile_models() -> dict[str, Any]:
    pa = _read_json("pair_assignments.json") or {}
    bots = pa.get("bots") or {}
    rows = []
    n_pairs = 0
    for name, b in bots.items():
        k = len(b.get("pairs") or {})
        n_pairs += k
        rows.append({"bot": name, "kind": b.get("kind"), "n_pairs": k,
                     "exchange": b.get("exchange"), "timeframe": b.get("trade_timeframe")})
    rows.sort(key=lambda r: -r["n_pairs"])
    rq = _read_json("retrain_queue.json") or {}
    sp = _read_json("selection_performance.json") or {}
    n_adjusted = 0
    for b in (sp.get("bots") or {}).values():
        n_adjusted += len((b or {}).get("feedback_adjustments") or {})
    return {
        "n_bots": len(rows),
        "n_pairs": n_pairs,
        "bots": rows[:8],
        "retrain_queue": len(rq.get("queue") or []),
        "feedback_adjusted": n_adjusted,
        "age_h": _age_hours(pa.get("generated_at")),
    }


def _tile_research() -> dict[str, Any]:
    path = OUTPUTS_DIR / "experiments.jsonl"
    runs: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            line = line.strip()
            if line:
                with contextlib.suppress(Exception):
                    runs.append(json.loads(line))
    except Exception:
        pass
    names = Counter(r.get("name") for r in runs if r.get("name"))
    last = runs[-1] if runs else None
    s = _scan_store()
    return {
        "n_runs": len(runs),
        "by_name": [{"k": k, "v": v} for k, v in names.most_common(5)],
        "last_name": (last or {}).get("name"),
        "last_age_h": _age_hours(
            datetime.fromtimestamp((last or {}).get("ts") or 0, UTC).isoformat()) if last else None,
        "last_metrics": {k: _num(v) for k, v in ((last or {}).get("metrics") or {}).items()},
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
    }


def _tile_insights() -> dict[str, Any]:
    s = _scan_store()
    rep = _read_json("wf_report.json") or {}
    strat = Counter(e.get("strategy") for e in (rep.get("top") or []) if e.get("strategy"))
    return {
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
        "by_timeframe": s["by_timeframe"],
        "top_strategies": [{"k": k, "v": v} for k, v in strat.most_common(4)],
    }


def _tile_lab() -> dict[str, Any]:
    n_strategies = 0
    try:
        from src.strategies.rules import STRATEGY_PARAM_SPECS

        n_strategies = len(STRATEGY_PARAM_SPECS)
    except Exception:
        pass
    s = _scan_store()
    return {
        "n_strategies": n_strategies,
        "n_datasets": s["n_datasets"],
        "n_timeframes": len(s["by_timeframe"]),
    }


def _tile_report() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    top = rep.get("top") or []
    best = top[0] if top else None
    sharpes = [_num(e.get("oos_sharpe")) for e in top]
    sharpes = [x for x in sharpes if x is not None]
    return {
        "n_top": len(top),
        "best": {
            "symbol": (best or {}).get("symbol"), "strategy": (best or {}).get("strategy"),
            "timeframe": (best or {}).get("timeframe"),
            "oos_sharpe": _num((best or {}).get("oos_sharpe")),
            "oos_mean_return": _num((best or {}).get("oos_mean_return")),
        } if best else None,
        "sharpes": sharpes[:20],
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_crossex() -> dict[str, Any]:
    s = _scan_store()
    return {
        "multi_venue_symbols": s["multi_venue_symbols"],
        "n_venues": s["n_venues"],
        "n_symbols": s["n_symbols"],
        "by_exchange": s["by_exchange"],
    }


_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
_LOG_RE = re.compile(r"\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b")


def _tile_logs() -> dict[str, Any]:
    counts = Counter()
    last_error = None
    try:
        path = LOG_DIR / "app.log"
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 240_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()[-800:]
        for ln in lines:
            m = _LOG_RE.search(ln)
            if m:
                counts[m.group(1)] += 1
                if m.group(1) in ("ERROR", "CRITICAL"):
                    last_error = ln[:160]
    except Exception:
        lines = []
    return {
        "n_lines": len(lines),
        "levels": [{"k": lv, "v": counts.get(lv, 0)} for lv in _LOG_LEVELS],
        "n_errors": counts.get("ERROR", 0) + counts.get("CRITICAL", 0),
        "n_warnings": counts.get("WARNING", 0),
        "last_error": last_error,
    }


_BUILDERS = {
    "download": _tile_download,
    "inventory": _tile_inventory,
    "research": _tile_research,
    "report": _tile_report,
    "insights": _tile_insights,
    "lab": _tile_lab,
    "edges": _tile_edges,
    "crossex": _tile_crossex,
    "fleet": _tile_fleet,
    "altdata": _tile_altdata,
    "attribution": _tile_attribution,
    "trials": _tile_trials,
    "stress": _tile_stress,
    "capacity": _tile_capacity,
    "portfolio": _tile_portfolio,
    "models": _tile_models,
    "pipeline": _tile_pipeline,
    "quality": _tile_quality,
    "logs": _tile_logs,
}


def summary(force: bool = False) -> dict[str, Any]:
    """Every tile's KPI payload in one call, TTL-cached."""
    now = time.time()
    with _cache_lock:
        cached = _cache["payload"]
        if cached is not None and not force and now - _cache["at"] < _TTL_SECONDS:
            return cached

    tiles: dict[str, Any] = {}
    for key, build in _BUILDERS.items():
        try:
            tiles[key] = build()
        except Exception:  # a broken artifact blanks one widget, never the grid
            tiles[key] = {"error": True}

    payload = {"generated_at": datetime.now(UTC).isoformat(), "tiles": tiles}
    with _cache_lock:
        _cache["payload"] = payload
        _cache["at"] = time.time()
    return payload
