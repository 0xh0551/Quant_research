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
    newest = 0.0
    refreshed_24h = 0
    refreshed_7d = 0

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
            refreshed_24h += 1
        if age_h <= 168:
            refreshed_7d += 1
        newest = max(newest, st.st_mtime)

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

    value = {
        "n_datasets": n,
        "total_gb": round(total_bytes / 1e9, 2),
        "n_symbols": len(symbols),
        "by_exchange": [{"k": k, "v": v} for k, v in exchanges.most_common(6)],
        "by_timeframe": _sorted_tf(dict(timeframes)),
        "refreshed_24h": refreshed_24h,
        "refreshed_7d": refreshed_7d,
        "newest_age_h": round((now - newest) / 3600, 2) if newest else None,
        "multi_venue_symbols": sum(1 for v in venues_by_symbol.values() if len(v) > 1),
        "n_venues": len({v for vs in venues_by_symbol.values() for v in vs}),
    }
    _ds_cache["value"] = value
    _ds_cache["at"] = now
    return value


# ── per-tile builders ─────────────────────────────────────────────────────────
# A tile shows three numbers and one chart, so each builder emits exactly the
# fields that view reads — nothing speculative. Raising is fine: `summary()`
# catches per tile, so one bad artifact cannot blank the grid.

def _tile_inventory() -> dict[str, Any]:
    s = _scan_store()
    return {
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
        "total_gb": s["total_gb"],
        "by_timeframe": s["by_timeframe"],
        "newest_age_h": s["newest_age_h"],
    }


def _tile_download() -> dict[str, Any]:
    s = _scan_store()
    return {
        "refreshed_24h": s["refreshed_24h"],
        "refreshed_7d": s["refreshed_7d"],
        "n_venues": s["n_venues"],
        "by_exchange": s["by_exchange"],
        "newest_age_h": s["newest_age_h"],
    }


def _tile_quality() -> dict[str, Any]:
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

    buckets = [("<2K", 0, 2000), ("2-6K", 2000, 6000), ("6-20K", 6000, 20000), ("20K+", 20000, 10**9)]
    return {
        "scannable_pct": round(100 * scannable / n, 1) if n else None,
        "median_bars": bars[len(bars) // 2] if bars else None,
        "stale_gt_3d": stale,
        "bars_hist": [{"k": lbl, "v": sum(1 for b in bars if lo <= b < hi)} for lbl, lo, hi in buckets],
    }


def _tile_research() -> dict[str, Any]:
    n_runs = 0
    path = OUTPUTS_DIR / "experiments.jsonl"
    with contextlib.suppress(Exception):
        n_runs = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    s = _scan_store()
    return {
        "n_runs": n_runs,
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
        "by_timeframe": s["by_timeframe"],
    }


def _tile_insights() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    ev = _read_json("event_risk.json") or {}
    ad = _read_json("altdata_snapshot.json") or {}
    per_sym = {p.get("symbol"): p for p in (ad.get("per_symbol") or [])}
    strat = Counter(e.get("strategy") for e in (rep.get("top") or []) if e.get("strategy"))
    return {
        "event_risk": _num((ev.get("global") or {}).get("risk")),
        "dvol_btc": _num((ad.get("dvol") or {}).get("BTC")),
        "ls_ratio_btc": _num((per_sym.get("BTCUSDT") or {}).get("ls_ratio")),
        "top_strategies": [{"k": k, "v": v} for k, v in strat.most_common(4)],
    }


def _tile_lab() -> dict[str, Any]:
    n_strategies = n_params = 0
    with contextlib.suppress(Exception):
        from src.strategies.rules import STRATEGY_PARAM_SPECS

        n_strategies = len(STRATEGY_PARAM_SPECS)
        n_params = sum(len(v or {}) for v in STRATEGY_PARAM_SPECS.values())
    s = _scan_store()
    return {
        "n_strategies": n_strategies,
        "n_params": n_params,
        "n_datasets": s["n_datasets"],
        "by_timeframe": s["by_timeframe"],
    }


def _tile_report() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    top = rep.get("top") or []
    best = top[0] if top else None
    sharpes = [x for x in (_num(e.get("oos_sharpe")) for e in top) if x is not None]
    return {
        "n_top": len(top),
        "best": {
            "oos_sharpe": _num(best.get("oos_sharpe")),
            "oos_mean_return": _num(best.get("oos_mean_return")),
        } if best else None,
        "sharpes": sharpes[:20],
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_edges() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    # `by_timeframe` values are per-timeframe dicts, not bare counts — reading
    # the wrong key silently renders an all-zero chart, so both series are
    # derived from the one parse and both are covered by the tests.
    passed: dict[str, int] = {}
    robust: dict[str, int] = {}
    for tf, v in (rep.get("by_timeframe") or {}).items():
        if isinstance(v, dict):
            passed[tf] = int(v.get("passed") or 0)
            robust[tf] = int(v.get("robust") or 0)
        else:
            passed[tf] = int(v or 0)
    return {
        "n_passed": rep.get("n_passed"),
        "n_deployable": rep.get("n_deployable"),
        "median_pbo": _num((rep.get("rigor") or {}).get("median_pbo")),
        "live_timeframe": rep.get("live_timeframe"),
        "by_timeframe": _sorted_tf(passed),
        "by_timeframe_robust": _sorted_tf(robust),
        "age_h": _age_hours(rep.get("generated_at")),
    }


def _tile_trials() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    out: dict[str, Any] = {
        "n_deflated_pass": (rep.get("rigor") or {}).get("n_deflated_pass"),
        "age_h": _age_hours(rep.get("generated_at")),
    }
    with contextlib.suppress(Exception):
        from src.tracking.trial_ledger import default_ledger

        ledger = default_ledger()
        stats = ledger.family_stats("wf_scan") or {}
        n_unique = stats.get("n_unique") or 0
        passed = stats.get("n_ever_passed") or 0
        rows = [{"k": r.get("strategy"), "v": round(100 * (_num(r.get("pass_rate")) or 0), 1)}
                for r in (ledger.strategy_breakdown("wf_scan") or []) if r.get("strategy")]
        rows.sort(key=lambda r: -r["v"])
        out.update({
            "n_unique": n_unique,
            "pass_rate": round(100 * passed / n_unique, 2) if n_unique else None,
            "strategies": rows[:4],
        })
    return out


def _tile_capacity() -> dict[str, Any]:
    cap = _read_json("capacity_report.json") or {}
    edges = cap.get("edges") or []
    caps = sorted(x for x in (_num(e.get("capacity_notional")) for e in edges) if x is not None)
    tightest = sorted(edges, key=lambda e: _num(e.get("capacity_notional")) or 0)[:4]
    return {
        "n_books": cap.get("n_books"),
        "median_capacity": caps[len(caps) // 2] if caps else None,
        "total_capacity": round(sum(caps), 0) if caps else None,
        "rows": [{"symbol": e.get("symbol"), "capacity": _num(e.get("capacity_notional"))}
                 for e in tightest],
        "age_h": _age_hours(cap.get("generated_at")),
    }


def _tile_crossex() -> dict[str, Any]:
    s = _scan_store()
    fc = _read_json("funding_carry.json") or {}
    carry = [{"base": c.get("base"), "spread": _num(c.get("gross_spread_ann_pct"))}
             for c in (fc.get("top_carry") or [])[:4]]
    return {
        "best_spread": carry[0]["spread"] if carry else None,
        "multi_venue_symbols": s["multi_venue_symbols"],
        "n_venues": s["n_venues"],
        "carry": carry,
        "carry_age_h": _age_hours(fc.get("generated_at")),
    }


def _bot_scorecard() -> dict[str, dict[str, Any]]:
    """Per-bot 30-day trading record, keyed by bot name."""
    return (_read_json("golive_scorecard.json") or {}).get("bots") or {}


def _tile_fleet() -> dict[str, Any]:
    fr = _read_json("fleet_risk.json") or {}
    f = fr.get("fleet") or {}
    card = _bot_scorecard()
    bots = []
    for b in (fr.get("per_bot") or []):
        m = (card.get(b.get("bot")) or {}).get("last_30d") or {}
        bots.append({"bot": b.get("bot"), "net_30d": _num(m.get("net")),
                     "trades_30d": m.get("trades")})
    return {
        "equity_usd": _num(f.get("equity_usd")),
        "gross_leverage": _num(f.get("gross_leverage")),
        "max_gross_leverage": _num((fr.get("limits") or {}).get("max_gross_leverage")),
        "net_beta_delta_pct": _num(f.get("net_beta_delta_pct")),
        "n_alerts": len(fr.get("alerts") or []),
        "bots": bots[:8],
        "age_h": _age_hours(fr.get("generated_at")),
    }


def _tile_portfolio() -> dict[str, Any]:
    fr = _read_json("fleet_risk.json") or {}
    assets = fr.get("per_asset") or []
    total = sum(abs(_num(a.get("gross_notional")) or 0) for a in assets)
    top = []
    for a in sorted(assets, key=lambda a: -(abs(_num(a.get("gross_notional")) or 0)))[:6]:
        g = abs(_num(a.get("gross_notional")) or 0)
        top.append({"base": a.get("base"), "pct": round(100 * g / total, 1) if total else 0.0})
    return {
        "gross_usd": round(total, 1),
        "hhi": _num((fr.get("fleet") or {}).get("hhi")),
        "n_assets": len(assets),
        "top": top,
        "age_h": _age_hours(fr.get("generated_at")),
    }


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
        rows.append({"key": s.get("key"), "loss": loss, "loss_pct": pct})
    rows.sort(key=lambda r: (r["loss"] if r["loss"] is not None else 0))
    return {
        "worst": rows[0] if rows else None,
        "rows": rows[:4],
        "n_liquidations": n_liq,
        "age_h": _age_hours(st.get("generated_at")),
    }


def _tile_attribution() -> dict[str, Any]:
    at = _read_json("attribution_report.json") or {}
    totals = at.get("totals") or {}
    caps = [x for x in (_num(b.get("mfe_capture_mean")) for b in (at.get("per_bot") or []))
            if x is not None]
    return {
        "net": _num(totals.get("net")),
        "intended": _num(totals.get("intended")),
        "fees": _num(totals.get("fees")),
        "funding": _num(totals.get("funding")),
        "exit_slip": _num(totals.get("exit_slip")),
        "mfe_capture_avg": round(sum(caps) / len(caps), 3) if caps else None,
        "age_h": _age_hours(at.get("generated_at")),
    }


def _tile_altdata() -> dict[str, Any]:
    ad = _read_json("altdata_snapshot.json") or {}
    dvol = ad.get("dvol") or {}
    series = [v for v in ((ad.get("dvol_series_btc") or {}).get("values") or [])[-40:]
              if _num(v) is not None]
    return {
        "dvol_btc": _num(dvol.get("BTC")),
        "dvol_eth": _num(dvol.get("ETH")),
        "dvol_series": [_num(v) for v in series],
        "liquidations_24h_usd": _num(ad.get("liquidations_24h_usd")),
        "age_h": _age_hours(ad.get("generated_at")),
    }


def _tile_pipeline() -> dict[str, Any]:
    hb = _read_json("pipeline_health.json") or {}
    counts = hb.get("counts") or {}
    status = _read_json("pipeline_status.json") or {}
    return {
        "healthy": hb.get("healthy"),
        "n_jobs": hb.get("n_jobs"),
        "ok": counts.get("ok"), "late": counts.get("late"), "missing": counts.get("missing"),
        "run_state": status.get("state"),
        "run_step": status.get("step"),
        "age_h": _age_hours(hb.get("generated_at")),
    }


def _tile_models() -> dict[str, Any]:
    pa = _read_json("pair_assignments.json") or {}
    card = _bot_scorecard()
    rows = []
    n_pairs = 0
    for name, b in (pa.get("bots") or {}).items():
        k = len(b.get("pairs") or {})
        n_pairs += k
        m = (card.get(name) or {}).get("last_30d") or {}
        rows.append({"bot": name, "n_pairs": k, "net_30d": _num(m.get("net"))})
    rows.sort(key=lambda r: -r["n_pairs"])
    drops = _read_json("drop_list.json") or {}
    return {
        "n_pairs": n_pairs,
        "n_bots": len(rows),
        "n_dropped": sum(len(v or []) for v in (drops.get("bots") or {}).values()),
        "bots": rows[:8],
        "age_h": _age_hours(pa.get("generated_at")),
    }


_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
_LOG_RE = re.compile(r"\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b")


def _tile_logs() -> dict[str, Any]:
    counts: Counter[str] = Counter()
    lines: list[str] = []
    with contextlib.suppress(Exception), (LOG_DIR / "app.log").open("rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 240_000))
        lines = fh.read().decode("utf-8", "replace").splitlines()[-800:]
    for ln in lines:
        m = _LOG_RE.search(ln)
        if m:
            counts[m.group(1)] += 1
    return {
        "n_lines": len(lines),
        "n_errors": counts.get("ERROR", 0) + counts.get("CRITICAL", 0),
        "n_warnings": counts.get("WARNING", 0),
        "levels": [{"k": lv, "v": counts.get(lv, 0)} for lv in _LOG_LEVELS],
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
