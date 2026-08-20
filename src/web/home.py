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
from typing import Any, cast

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "processed"
OUTPUTS_DIR = ROOT / "outputs"
LOG_DIR = ROOT / "logs"

_TTL_SECONDS = 20.0
_BUILD_BUDGET_SECONDS = 8.0
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
_RECENCY = [("<1h", 1), ("<6h", 6), ("<24h", 24), ("<7d", 168), ("older", 10**9)]


def _scan_store() -> dict[str, Any]:
    """One ``stat()`` sweep of the parquet store, cached for a minute.

    Names look like ``<exchange>[_<market>]_<SYMBOL>_<tf>.parquet``; everything
    the tiles need is in the filename plus the stat block, so nothing here reads
    file *contents* (the store is ~1 GB across ~2.2k files).
    """
    now = time.time()
    if _ds_cache["value"] is not None and now - _ds_cache["at"] < _DS_TTL:
        return cast(dict[str, Any], _ds_cache["value"])

    venues: Counter[str] = Counter()
    timeframes: Counter[str] = Counter()
    matrix: Counter[tuple[str, str]] = Counter()
    symbols: set[str] = set()
    venues_by_symbol: dict[str, set[str]] = {}
    recency: Counter[str] = Counter()
    total_bytes = 0
    n = 0
    newest = 0.0

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
        newest = max(newest, st.st_mtime)
        age_h = (now - st.st_mtime) / 3600
        for label, ceiling in _RECENCY:
            if age_h < ceiling:
                recency[label] += 1
                break

        parts = path.stem.split("_")
        if len(parts) < 2:
            continue
        tf = parts[-1]
        exch = parts[0].lower()
        core = parts[1:-1]
        if core and core[0].lower() in ("futures", "perp", "perpetual", "spot", "um", "cm"):
            venue = exch
            sym = "_".join(core[1:])
        else:
            venue = exch
            sym = "_".join(core)
        venues[venue] += 1
        if tf in _TF_SET:
            timeframes[tf] += 1
            matrix[(venue, tf)] += 1
        if sym:
            symbols.add(sym)
            venues_by_symbol.setdefault(sym, set()).add(venue)

    top_venues = [v for v, _ in venues.most_common(5)]
    tf_order = [tf for tf in _TF_ORDER if tf in timeframes]
    value = {
        "n_datasets": n,
        "total_gb": round(total_bytes / 1e9, 2),
        "n_symbols": len(symbols),
        "newest_age_h": round((now - newest) / 3600, 2) if newest else None,
        "recency": [{"k": lbl, "v": recency.get(lbl, 0)} for lbl, _ in _RECENCY],
        # venue x timeframe coverage grid — the inventory's own view of the store
        "matrix": {
            "venues": top_venues,
            "timeframes": tf_order,
            "cells": [[matrix.get((v, tf), 0) for tf in tf_order] for v in top_venues],
        },
        "multi_venue_symbols": sum(1 for v in venues_by_symbol.values() if len(v) > 1),
        "n_venues": len(venues),
    }
    _ds_cache["value"] = value
    _ds_cache["at"] = now
    return value


# ── per-tile builders ─────────────────────────────────────────────────────────
# Each tile gets the one signal that belongs to *its* module and nothing else —
# the same series drawn on three tiles teaches nobody anything. Raising is fine:
# `summary()` catches per tile, so one bad artifact cannot blank the grid.

def _tile_inventory() -> dict[str, Any]:
    """Coverage: which venue holds which timeframes, as a density grid."""
    s = _scan_store()
    return {
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
        "total_gb": s["total_gb"],
        "matrix": s["matrix"],
    }


def _tile_download() -> dict[str, Any]:
    """Freshness: how the store's age is distributed right now."""
    s = _scan_store()
    return {
        "recency": s["recency"],
        "n_venues": s["n_venues"],
        "newest_age_h": s["newest_age_h"],
        "n_datasets": s["n_datasets"],
    }


def _tile_quality() -> dict[str, Any]:
    """Fitness for scanning: the share of the store long enough to walk forward."""
    cov = _read_json("data_coverage.json") or {}
    datasets = cov.get("datasets") or []
    n = int(cov.get("n_datasets") or len(datasets))
    scannable = int(cov.get("n_scannable") or 0)
    bars = sorted(int(d.get("bars") or 0) for d in datasets)

    stale = 0
    today = datetime.now(UTC).date()
    for d in datasets:
        last = d.get("last")
        if not last:
            continue
        with contextlib.suppress(Exception):
            if (today - datetime.fromisoformat(str(last)).date()).days > 3:
                stale += 1
    return {
        "scannable_pct": round(100 * scannable / n, 1) if n else None,
        "n_scannable": scannable,
        "n_datasets": n,
        "median_bars": bars[len(bars) // 2] if bars else None,
        "stale_gt_3d": stale,
    }


def _tile_research() -> dict[str, Any]:
    """Reach: how far back the store lets a backtest run."""
    cov = _read_json("data_coverage.json") or {}
    datasets = cov.get("datasets") or []
    firsts, lasts, spans = [], [], []
    for d in datasets:
        first, last = d.get("first"), d.get("last")
        if not (first and last):
            continue
        with contextlib.suppress(Exception):
            fd = datetime.fromisoformat(str(first)).date()
            ld = datetime.fromisoformat(str(last)).date()
            firsts.append(fd)
            lasts.append(ld)
            spans.append((ld - fd).days)
    n_runs = 0
    with contextlib.suppress(Exception):
        n_runs = sum(1 for line in (OUTPUTS_DIR / "experiments.jsonl")
                     .read_text(encoding="utf-8").splitlines() if line.strip())
    spans.sort()
    s = _scan_store()
    return {
        "n_runs": n_runs,
        "n_symbols": s["n_symbols"],
        "first": str(min(firsts)) if firsts else None,
        "last": str(max(lasts)) if lasts else None,
        "median_span_days": spans[len(spans) // 2] if spans else None,
        "max_span_days": spans[-1] if spans else None,
    }


def _tile_insights() -> dict[str, Any]:
    """Regime: three market gauges the strategy picker is conditioned on."""
    ev = _read_json("event_risk.json") or {}
    ad = _read_json("altdata_snapshot.json") or {}
    per_sym = {p.get("symbol"): p for p in (ad.get("per_symbol") or [])}
    series = [x for x in (_num(v) for v in
                          (ad.get("dvol_series_btc") or {}).get("values") or []) if x is not None]
    dvol = _num((ad.get("dvol") or {}).get("BTC"))
    pct = None
    if series and dvol is not None:
        pct = round(100 * sum(1 for v in series if v <= dvol) / len(series))
    ls = _num((per_sym.get("BTCUSDT") or {}).get("ls_ratio"))
    return {
        "gauges": [
            {"k": "event_risk", "v": _num((ev.get("global") or {}).get("risk")), "max": 1.0},
            {"k": "dvol_pct", "v": (pct / 100 if pct is not None else None), "max": 1.0},
            # 0.5..2.0 long/short mapped onto the same 0..1 track
            {"k": "ls_skew", "v": (min(1.0, max(0.0, (ls - 0.5) / 1.5)) if ls else None), "max": 1.0},
        ],
        "dvol_btc": dvol,
        "ls_ratio_btc": ls,
        "n_event_symbols": ev.get("n_symbols"),
    }


def _tile_lab() -> dict[str, Any]:
    """Palette: every strategy the optimiser can be pointed at."""
    names: list[str] = []
    n_params = 0
    with contextlib.suppress(Exception):
        from src.strategies.rules import STRATEGY_PARAM_SPECS

        names = list(STRATEGY_PARAM_SPECS)
        n_params = sum(len(v or {}) for v in STRATEGY_PARAM_SPECS.values())
    return {"strategies": names, "n_strategies": len(names), "n_params": n_params}


def _tile_report() -> dict[str, Any]:
    """Decay: how fast OOS quality falls away from the best edge."""
    rep = _read_json("wf_report.json") or {}
    top = rep.get("top") or []
    sharpes = [x for x in (_num(e.get("oos_sharpe")) for e in top) if x is not None]
    best = top[0] if top else None
    return {
        "sharpes": sharpes[:20],
        "n_top": len(top),
        "best_sharpe": _num((best or {}).get("oos_sharpe")),
        "best_return": _num((best or {}).get("oos_mean_return")),
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_edges() -> dict[str, Any]:
    """Survival: the scan funnel from every candidate down to what deploys."""
    rep = _read_json("wf_report.json") or {}
    return {
        "funnel": [
            {"k": "scanned", "v": rep.get("n_scanned")},
            {"k": "passed", "v": rep.get("n_passed")},
            {"k": "robust", "v": rep.get("n_robust")},
            {"k": "deployable", "v": rep.get("n_deployable")},
        ],
        "median_pbo": _num((rep.get("rigor") or {}).get("median_pbo")),
        "live_timeframe": rep.get("live_timeframe"),
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_trials() -> dict[str, Any]:
    """Multiple testing: which strategy families clear the bar, and how often."""
    rep = _read_json("wf_report.json") or {}
    out: dict[str, Any] = {"age_h": _age_hours(rep.get("generated_at")),
                           "n_deflated_pass": (rep.get("rigor") or {}).get("n_deflated_pass")}
    with contextlib.suppress(Exception):
        from src.tracking.trial_ledger import DEFAULT_DB, TrialLedger

        # The nightly scan holds this database's write lock for hours. A tile is
        # decoration: wait a moment, then go without it rather than hang the
        # whole launcher behind one panel.
        ledger = TrialLedger(DEFAULT_DB, timeout=1.5)
        stats = ledger.family_stats("wf_scan") or {}
        n_unique = stats.get("n_unique") or 0
        passed = stats.get("n_ever_passed") or 0
        rows: list[dict[str, Any]] = [
            {"k": r.get("strategy"), "v": round(100 * (_num(r.get("pass_rate")) or 0), 1)}
            for r in (ledger.strategy_breakdown("wf_scan") or []) if r.get("strategy")]
        rows.sort(key=lambda r: -float(r["v"]))
        out.update({
            "n_unique": n_unique,
            "pass_rate": round(100 * passed / n_unique, 2) if n_unique else None,
            "strategies": rows[:5],
        })
    return out


def _tile_capacity() -> dict[str, Any]:
    """Scale: where every live edge sits on a log dollar axis."""
    cap = _read_json("capacity_report.json") or {}
    edges = cap.get("edges") or []
    points = [{"v": _num(e.get("capacity_notional")), "k": e.get("symbol")}
              for e in edges if _num(e.get("capacity_notional"))]
    points.sort(key=lambda p: p["v"])
    caps = [p["v"] for p in points]
    return {
        "points": points[:24],
        "median_capacity": caps[len(caps) // 2] if caps else None,
        "min_capacity": caps[0] if caps else None,
        "n_books": cap.get("n_books"),
        "age_h": _age_hours(cap.get("generated_at")),
    }


def _tile_crossex() -> dict[str, Any]:
    """Carry: the funding rate at each leg of the best cross-venue spreads."""
    s = _scan_store()
    fc = _read_json("funding_carry.json") or {}
    carry = []
    for c in (fc.get("top_carry") or [])[:4]:
        carry.append({
            "base": c.get("base"),
            "short": _num(c.get("short_ann_pct")), "short_venue": c.get("short_venue"),
            "long": _num(c.get("long_ann_pct")), "long_venue": c.get("long_venue"),
            "spread": _num(c.get("gross_spread_ann_pct")),
        })
    return {
        "carry": carry,
        "best_spread": carry[0]["spread"] if carry else None,
        "multi_venue_symbols": s["multi_venue_symbols"],
        "n_venues": s["n_venues"],
        "carry_age_h": _age_hours(fc.get("generated_at")),
    }


def _bot_scorecard() -> dict[str, dict[str, Any]]:
    """Per-bot 30-day trading record, keyed by bot name."""
    return (_read_json("golive_scorecard.json") or {}).get("bots") or {}


def _tile_fleet() -> dict[str, Any]:
    """Headroom: gross leverage read against the limit it must not cross."""
    fr = _read_json("fleet_risk.json") or {}
    f = fr.get("fleet") or {}
    return {
        "gross_leverage": _num(f.get("gross_leverage")),
        "max_gross_leverage": _num((fr.get("limits") or {}).get("max_gross_leverage")),
        "equity_usd": _num(f.get("equity_usd")),
        "net_beta_delta_pct": _num(f.get("net_beta_delta_pct")),
        "n_positions": f.get("n_positions"),
        "n_alerts": len(fr.get("alerts") or []),
        "age_h": _age_hours(fr.get("generated_at")),
    }


def _tile_portfolio() -> dict[str, Any]:
    """Concentration: the open book as areas, biggest holding first."""
    fr = _read_json("fleet_risk.json") or {}
    assets = fr.get("per_asset") or []
    total = sum(abs(_num(a.get("gross_notional")) or 0) for a in assets)
    top = []
    for a in sorted(assets, key=lambda a: -(abs(_num(a.get("gross_notional")) or 0)))[:7]:
        g = abs(_num(a.get("gross_notional")) or 0)
        top.append({"base": a.get("base"), "pct": round(100 * g / total, 1) if total else 0.0})
    return {
        "top": top,
        "gross_usd": round(total, 1),
        "hhi": _num((fr.get("fleet") or {}).get("hhi")),
        "n_assets": len(assets),
        "age_h": _age_hours(fr.get("generated_at")),
    }


def _tile_stress() -> dict[str, Any]:
    """Tail: every scenario's hit placed on one equity-loss axis."""
    st = _read_json("stress_report.json") or {}
    scen = st.get("scenarios") or []
    equity = _num(st.get("equity_usd")) or 0.0
    ticks, n_liq = [], 0
    for s in scen:
        loss = _num(s.get("fleet_pnl_usd"))
        pct = _num(s.get("fleet_pnl_pct"))
        if pct is None and loss is not None and equity:
            pct = round(100 * loss / equity, 2)
        n_liq += int(s.get("n_liquidations") or 0)
        if pct is not None:
            ticks.append({"k": s.get("key"), "v": pct})
    ticks.sort(key=lambda r: r["v"])
    return {
        "ticks": ticks,
        "worst_pct": ticks[0]["v"] if ticks else None,
        "worst_key": ticks[0]["k"] if ticks else None,
        "n_liquidations": n_liq,
        "n_scenarios": len(scen),
        "age_h": _age_hours(st.get("generated_at")),
    }


def _tile_attribution() -> dict[str, Any]:
    """Bridge: what the intended alpha paid away before it reached net."""
    at = _read_json("attribution_report.json") or {}
    tot = at.get("totals") or {}
    return {
        "steps": [
            {"k": "intended", "v": _num(tot.get("intended"))},
            {"k": "fees", "v": -abs(_num(tot.get("fees")) or 0)},
            {"k": "entry", "v": _num(tot.get("entry_slip"))},
            {"k": "exit", "v": _num(tot.get("exit_slip"))},
            {"k": "funding", "v": _num(tot.get("funding"))},
        ],
        "net": _num(tot.get("net")),
        "window_days": _num(at.get("window_days")),
        "age_h": _age_hours(at.get("generated_at")),
    }


def _tile_altdata() -> dict[str, Any]:
    """Implied vol: the BTC DVOL track behind today's reading."""
    ad = _read_json("altdata_snapshot.json") or {}
    dvol = ad.get("dvol") or {}
    series = [x for x in (_num(v) for v in
                          ((ad.get("dvol_series_btc") or {}).get("values") or [])[-60:])
              if x is not None]
    return {
        "dvol_series": series,
        "dvol_btc": _num(dvol.get("BTC")),
        "dvol_eth": _num(dvol.get("ETH")),
        "liquidations_24h_usd": _num(ad.get("liquidations_24h_usd")),
        "age_h": _age_hours(ad.get("generated_at")),
    }


def _tile_pipeline() -> dict[str, Any]:
    """Schedule: one pip per job, filled by how much of its budget is spent."""
    hb = _read_json("pipeline_health.json") or {}
    counts = hb.get("counts") or {}
    status = _read_json("pipeline_status.json") or {}
    jobs = []
    for j in (hb.get("jobs") or []):
        age, cap = _num(j.get("age_hours")), _num(j.get("max_age_hours"))
        jobs.append({
            "k": j.get("name"),
            "status": j.get("status"),
            "used": round(min(1.5, age / cap), 2) if (age is not None and cap) else None,
        })
    jobs.sort(key=lambda j: -(j["used"] or 0))
    return {
        "jobs": jobs,
        "ok": counts.get("ok"), "late": counts.get("late"), "missing": counts.get("missing"),
        "n_jobs": hb.get("n_jobs"),
        "healthy": hb.get("healthy"),
        "run_state": status.get("state"),
        "run_step": status.get("step"),
        "age_h": _age_hours(hb.get("generated_at")),
    }


def _tile_models() -> dict[str, Any]:
    """Allocation: how the live pair budget is split across the bots."""
    pa = _read_json("pair_assignments.json") or {}
    card = _bot_scorecard()
    rows, n_pairs = [], 0
    for name, b in (pa.get("bots") or {}).items():
        k = len(b.get("pairs") or {})
        n_pairs += k
        m = (card.get(name) or {}).get("last_30d") or {}
        rows.append({"k": name, "v": k, "net": _num(m.get("net"))})
    rows.sort(key=lambda r: -r["v"])
    drops = _read_json("drop_list.json") or {}
    return {
        "split": rows,
        "n_pairs": n_pairs,
        "n_bots": len(rows),
        "n_dropped": sum(len(v or []) for v in (drops.get("bots") or {}).values()),
        "age_h": _age_hours(pa.get("generated_at")),
    }


_LOG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d):\d\d:\d\d\s+.*?\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b")


def _tile_logs() -> dict[str, Any]:
    """Chatter: hourly log volume, so a quiet or a screaming service shows."""
    lines: list[str] = []
    with contextlib.suppress(Exception), (LOG_DIR / "app.log").open("rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 900_000))
        lines = fh.read().decode("utf-8", "replace").splitlines()[-4000:]

    per_hour: Counter[str] = Counter()
    errors = warnings = 0
    for ln in lines:
        m = _LOG_RE.match(ln)
        if not m:
            continue
        per_hour[m.group(1)] += 1
        if m.group(2) in ("ERROR", "CRITICAL"):
            errors += 1
        elif m.group(2) == "WARNING":
            warnings += 1

    hours = sorted(per_hour)[-24:]
    return {
        "hourly": [per_hour[h] for h in hours],
        "n_hours": len(hours),
        "n_errors": errors,
        "n_warnings": warnings,
        "n_lines": len(lines),
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
            return cast(dict[str, Any], cached)

    tiles: dict[str, Any] = {}
    deadline = time.monotonic() + _BUILD_BUDGET_SECONDS
    for key, build in _BUILDERS.items():
        if time.monotonic() > deadline:
            # Something upstream is slow. Ship the tiles that are ready rather
            # than leave the whole wall on skeletons.
            tiles[key] = {"error": True}
            continue
        try:
            tiles[key] = build()
        except Exception:  # a broken artifact blanks one widget, never the grid
            tiles[key] = {"error": True}

    payload = {"generated_at": datetime.now(UTC).isoformat(), "tiles": tiles}
    with _cache_lock:
        _cache["payload"] = payload
        _cache["at"] = time.time()
    return payload
