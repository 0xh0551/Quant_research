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


def _tail_jsonl(name: str, n: int) -> list[dict[str, Any]]:
    """Last ``n`` records of an append-only log, newest last.

    Read from the end of the file: the rotation and health logs run to hundreds
    of thousands of lines and the tiles only ever want the tail.
    """
    path = OUTPUTS_DIR / name
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 400 * n))
            lines = fh.read().decode("utf-8", "replace").splitlines()[-n:]
    except Exception:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if line:
            with contextlib.suppress(Exception):
                out.append(json.loads(line))
    return out


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
    newest_rows: list[tuple[float, str]] = []

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
        newest_rows.append((st.st_mtime, path.stem))
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
    newest_rows.sort(reverse=True)
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
        "newest": [{"name": name, "age_h": round((now - mt) / 3600, 2)}
                   for mt, name in newest_rows[:4]],
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
        "newest": s["newest"],
        "by_timeframe": s["by_timeframe"],
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
    buckets = [("<2K", 0, 2000), ("2-6K", 2000, 6000), ("6-20K", 6000, 20000), ("20K+", 20000, 10**9)]
    hist = [{"k": lbl, "v": sum(1 for b in bars if lo <= b < hi)} for lbl, lo, hi in buckets]
    return {
        "n_datasets": n,
        "n_scannable": scannable,
        "scannable_pct": round(100 * scannable / n, 1) if n else None,
        "stale_gt_3d": gaps,
        "median_bars": int(sorted(bars)[len(bars) // 2]) if bars else None,
        "min_scan_bars": cov.get("min_scan_bars"),
        "bars_hist": hist,
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
    hist = _tail_jsonl("wf_history.jsonl", 30)
    return {
        "n_scanned": rep.get("n_scanned"),
        "n_passed": rep.get("n_passed"),
        "n_symbols": len(rep.get("by_symbol") or {}),
        "trend_passed": [int(h.get("n_passed") or 0) for h in hist],
        "trend_sharpe": [_num(h.get("top_sharpe")) or 0 for h in hist],
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
    card = (_read_json("golive_scorecard.json") or {}).get("bots") or {}
    bots = []
    for b in (fr.get("per_bot") or []):
        name = b.get("bot")
        m = (card.get(name) or {}).get("last_30d") or {}
        bots.append({
            "bot": name,
            "gross_leverage": _num(b.get("gross_leverage")),
            "n_open": b.get("n_open"),
            "pnl": _num(b.get("realized_pnl", 0)) or 0,
            "net_30d": _num(m.get("net")),
            "pf_30d": _num(m.get("pf")),
            "trades_30d": m.get("trades"),
            "dd_30d": _num(m.get("max_dd_pct")),
        })
    bots.sort(key=lambda b: -(b["gross_leverage"] or 0))
    stale = sum(1 for p in (fr.get("positions") or []) if p.get("price_stale"))
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
        "n_stale_prices": stale,
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
    hist = _tail_jsonl("pipeline_health_history.jsonl", 48)
    jobs = []
    for j in sorted((hb.get("jobs") or []),
                    key=lambda j: ({"missing": 0, "late": 1, "ok": 2}.get(j.get("status"), 3),
                                   -(_num(j.get("age_hours")) or 0))):
        jobs.append({
            "name": j.get("name"), "status": j.get("status"),
            "age_h": _num(j.get("age_hours")), "max_age_h": _num(j.get("max_age_hours")),
            "severity": j.get("severity"),
        })
    return {
        "healthy": hb.get("healthy"),
        "jobs": jobs[:5],
        "trend_ok": [int(h.get("ok") or 0) for h in hist],
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
    rows = sorted(
        ({"bot": b.get("bot"), "net": _num((b.get("components") or {}).get("net")),
          "drag": _num(b.get("execution_drag")), "n_trades": b.get("n_trades")}
         for b in per_bot if b.get("n_trades")),
        key=lambda r: -(r["drag"] or 0))
    return {
        "window_days": _num(at.get("window_days")),
        "net": _num(totals.get("net")),
        "intended": _num(totals.get("intended")),
        "fees": _num(totals.get("fees")),
        "funding": _num(totals.get("funding")),
        "entry_slip": _num(totals.get("entry_slip")),
        "exit_slip": _num(totals.get("exit_slip")),
        "n_bots": len(per_bot),
        "rows": rows[:4],
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
        breakdown = default_ledger().strategy_breakdown("wf_scan") or []
        rows = [{"k": r.get("strategy"),
                 "v": round(100 * (_num(r.get("pass_rate")) or 0), 1),
                 "n": r.get("n_hypotheses")}
                for r in breakdown if r.get("strategy")]
        rows.sort(key=lambda r: -r["v"])
        out["strategies"] = rows[:4]
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
    rows = [{"symbol": e.get("symbol"), "venue": e.get("venue"),
             "capacity": _num(e.get("capacity_notional")),
             "edge_bps": _num(e.get("edge_rt_bps"))}
            for e in sorted(edges, key=lambda e: _num(e.get("capacity_notional")) or 0)[:4]]
    return {
        "rows": rows,
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
    top_fund = sorted(fx, key=lambda f: -(abs(_num(f.get("funding_ann_pct")) or 0)))[:4]
    ev = _read_json("event_risk.json") or {}
    return {
        "funding_rows": [{"symbol": f.get("symbol"),
                          "ann": _num(f.get("funding_ann_pct")),
                          "premium_bps": _num(f.get("premium_bps"))} for f in top_fund],
        "event_risk": _num((ev.get("global") or {}).get("risk")),
        "n_event_symbols": ev.get("n_symbols"),
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

    card = (_read_json("golive_scorecard.json") or {}).get("bots") or {}
    for r in rows:
        m = (card.get(r["bot"]) or {}).get("last_30d") or {}
        r["net_30d"] = _num(m.get("net"))
        r["pf_30d"] = _num(m.get("pf"))
        r["trades_30d"] = m.get("trades")

    drops = _read_json("drop_list.json") or {}
    n_dropped = sum(len(v or []) for v in (drops.get("bots") or {}).values())
    prio = (_read_json("retrain_priority.json") or {}).get("retrain_priority") or []
    worst = [{"bot": x.get("bot"), "base": x.get("base"), "action": x.get("action"),
              "avg_profit": _num(x.get("decayed_avg_profit"))} for x in prio[:4]]
    return {
        "n_bots": len(rows),
        "n_pairs": n_pairs,
        "bots": rows[:8],
        "retrain_queue": len(rq.get("queue") or []),
        "feedback_adjusted": n_adjusted,
        "n_dropped": n_dropped,
        "worst_pairs": worst,
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
    recent = []
    for r in reversed(runs[-4:]):
        metrics = r.get("metrics") or {}
        first = next(iter(metrics.items()), (None, None))
        recent.append({
            "name": r.get("name"),
            "target": (r.get("params") or {}).get("filename") or (r.get("params") or {}).get("strategy"),
            "metric": first[0], "value": _num(first[1]),
            "age_h": _age_hours(datetime.fromtimestamp(r.get("ts") or 0, UTC).isoformat()),
        })
    s = _scan_store()
    return {
        "n_runs": len(runs),
        "recent": recent,
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
    ev = _read_json("event_risk.json") or {}
    ad = _read_json("altdata_snapshot.json") or {}
    per_sym = {p.get("symbol"): p for p in (ad.get("per_symbol") or [])}
    tf_top = Counter(e.get("timeframe") for e in (rep.get("top") or []) if e.get("timeframe"))
    return {
        "event_risk": _num((ev.get("global") or {}).get("risk")),
        "dvol_btc": _num((ad.get("dvol") or {}).get("BTC")),
        "ls_ratio_btc": _num((per_sym.get("BTCUSDT") or {}).get("ls_ratio")),
        "top_timeframes": [{"k": k, "v": v} for k, v in tf_top.most_common(4)],
        "n_datasets": s["n_datasets"],
        "n_symbols": s["n_symbols"],
        "by_timeframe": s["by_timeframe"],
        "top_strategies": [{"k": k, "v": v} for k, v in strat.most_common(4)],
    }


def _tile_lab() -> dict[str, Any]:
    names: list[str] = []
    n_params = 0
    try:
        from src.strategies.rules import STRATEGY_PARAM_SPECS

        names = list(STRATEGY_PARAM_SPECS)
        n_params = sum(len(v or {}) for v in STRATEGY_PARAM_SPECS.values())
    except Exception:
        pass
    s = _scan_store()
    return {
        "n_strategies": len(names),
        "strategies": names[:8],
        "n_params": n_params,
        "n_datasets": s["n_datasets"],
        "n_timeframes": len(s["by_timeframe"]),
    }


def _tile_report() -> dict[str, Any]:
    rep = _read_json("wf_report.json") or {}
    top = rep.get("top") or []
    best = top[0] if top else None
    sharpes = [_num(e.get("oos_sharpe")) for e in top]
    sharpes = [x for x in sharpes if x is not None]
    rows = [{"symbol": e.get("symbol"), "strategy": e.get("strategy"),
             "timeframe": e.get("timeframe"), "sharpe": _num(e.get("oos_sharpe")),
             "ret": _num(e.get("oos_mean_return"))} for e in top[:4]]
    return {
        "rows": rows,
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
    fc = _read_json("funding_carry.json") or {}
    carry = [{"base": c.get("base"), "short": c.get("short_venue"), "long": c.get("long_venue"),
              "spread": _num(c.get("gross_spread_ann_pct"))}
             for c in (fc.get("top_carry") or [])[:4]]
    return {
        "multi_venue_symbols": s["multi_venue_symbols"],
        "n_venues": s["n_venues"],
        "n_symbols": s["n_symbols"],
        "by_exchange": s["by_exchange"],
        "carry": carry,
        "best_spread": carry[0]["spread"] if carry else None,
        "n_carry": len(fc.get("top_carry") or []),
        "carry_age_h": _age_hours(fc.get("generated_at")),
    }


_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
_LOG_RE = re.compile(r"\b(CRITICAL|ERROR|WARNING|INFO|DEBUG)\b")


def _tile_logs() -> dict[str, Any]:
    counts = Counter()
    last_error = None
    problems: list[dict[str, str]] = []
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
                if m.group(1) in ("ERROR", "CRITICAL", "WARNING"):
                    problems.append({"level": m.group(1), "text": ln[-150:].strip()})
                if m.group(1) in ("ERROR", "CRITICAL"):
                    last_error = ln[:160]
    except Exception:
        lines = []
    return {
        "n_lines": len(lines),
        "levels": [{"k": lv, "v": counts.get(lv, 0)} for lv in _LOG_LEVELS],
        "n_errors": counts.get("ERROR", 0) + counts.get("CRITICAL", 0),
        "n_warnings": counts.get("WARNING", 0),
        "problems": problems[-3:][::-1],
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
