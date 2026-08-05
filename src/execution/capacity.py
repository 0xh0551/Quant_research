"""Capacity / market-impact curves — how much capital an edge survives.

A validated edge is only worth the size it can carry. This module answers
"at what order size does our own impact eat the alpha?" per symbol, by
combining two measured cost sources:

  1. **Instantaneous book impact** — calibrated from real L2 sweep costs the
     order-book collector records (``outputs/microstructure_latest.json``:
     ``{buy,sell}_sweep_bps_{500,2000}``). Fitting ``impact = k·√notional``
     through the measured points gives a per-symbol ``k`` (worst side, so
     capacity is conservative). Symbols without a book fall back to the
     venue-median ``k``.
  2. **Participation impact** — the classic square-root ADV model
     ``impact = c·√(notional/ADV)·1e4`` for footprint that persists beyond the
     top of the book. ADV comes from the local parquet store (30d).

The effective impact at size N is ``max`` of the two (they bound different
regimes), doubled for a round trip. Against it stands the edge's measured
round-trip alpha from the walk-forward report (``oos_mean_return`` per split /
``trades_per_split``). Reported per edge:

  • ``capacity_notional``   — largest order size with net expectancy > 0
  • ``half_edge_notional``  — size where impact consumes half the net edge
                              (a sane operating point, not a cliff edge)
  • ``utilization``         — current live order size vs capacity (from the
                              fleet-risk snapshot, when available)
  • the full net-edge curve for charting

CLI:  python -m src.execution.capacity   → writes outputs/capacity_report.json
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR = ROOT / "outputs"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_PATH = OUTPUTS_DIR / "capacity_report.json"

ADV_LOOKBACK_DAYS = 30
ADV_IMPACT_COEF = 0.1          # same convention as portfolio.risk.capacity_estimate
DEFAULT_FEE_RT_BPS = 11.0      # taker in+out on a typical perp venue
SIZE_GRID_USD = [
    10, 25, 50, 100, 250, 500, 1_000, 2_000, 5_000,
    10_000, 25_000, 50_000, 100_000, 250_000,
]


# ── L2 calibration ──────────────────────────────────────────────────────────

def load_l2_books(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or (OUTPUTS_DIR / "microstructure_latest.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("books") or {}
    except Exception:
        return {}


def calibrate_k(book: dict[str, Any]) -> float | None:
    """Fit impact = k·√N through the measured sweep points (worst side)."""
    ks: list[float] = []
    for notional in (500, 2000):
        buy = book.get(f"buy_sweep_bps_{notional}")
        sell = book.get(f"sell_sweep_bps_{notional}")
        vals = [v for v in (buy, sell) if isinstance(v, (int, float)) and v >= 0]
        if vals:
            ks.append(max(vals) / math.sqrt(notional))
    return float(np.mean(ks)) if ks else None


def calibrate_all(books: dict[str, dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    """(per-base k, per-venue median k). Base = 'AAVE' from 'AAVE/USDT:USDT'."""
    per_base: dict[str, float] = {}
    per_venue: dict[str, list[float]] = {}
    for pair, book in books.items():
        k = calibrate_k(book)
        if k is None:
            continue
        base = str(pair).split("/")[0]
        per_base[base] = k
        per_venue.setdefault(str(book.get("venue") or ""), []).append(k)
    venue_median = {v: float(np.median(ks)) for v, ks in per_venue.items() if ks}
    return per_base, venue_median


# ── ADV from the parquet store ──────────────────────────────────────────────

def adv_usd(base: str, prefer_tfs: tuple[str, ...] = ("15m", "1h", "4h", "1d")) -> float | None:
    for tf in prefer_tfs:
        matches = sorted(
            PROCESSED_DIR.glob(f"*_{base}USDT_{tf}.parquet"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not matches:
            continue
        try:
            df = pd.read_parquet(matches[0], columns=["timestamp", "close", "volume"])
        except Exception:
            continue
        if df.empty:
            continue
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.Timestamp.now(tz=UTC) - pd.Timedelta(days=ADV_LOOKBACK_DAYS)
        recent = df[ts >= cutoff]
        if recent.empty:
            continue
        usd = (recent["close"].astype(float) * recent["volume"].astype(float)).sum()
        days = max((ts.max() - max(ts.min(), cutoff)).total_seconds() / 86400.0, 1.0)
        return float(usd / days)
    return None


# ── the impact + capacity math ──────────────────────────────────────────────

def impact_bps(notional: float, k_l2: float | None, adv: float | None,
               adv_coef: float = ADV_IMPACT_COEF) -> float:
    """One-way impact at order size ``notional`` (bps). Max of book-sweep and
    participation regimes; ∞ when neither source is available."""
    parts: list[float] = []
    if k_l2 is not None:
        parts.append(k_l2 * math.sqrt(max(notional, 0.0)))
    if adv and adv > 0:
        parts.append(adv_coef * math.sqrt(notional / adv) * 1e4)
    return max(parts) if parts else float("inf")


def capacity_curve(
    edge_rt_bps: float, fee_rt_bps: float, k_l2: float | None, adv: float | None,
    grid: list[float] | None = None,
) -> dict[str, Any]:
    """Net round-trip expectancy across the size grid + capacity points."""
    grid = grid or SIZE_GRID_USD
    points = []
    for n in grid:
        imp_rt = 2.0 * impact_bps(n, k_l2, adv)
        net = edge_rt_bps - fee_rt_bps - imp_rt
        points.append({"notional": n, "impact_rt_bps": round(imp_rt, 2), "net_edge_bps": round(net, 2)})

    gross_net = edge_rt_bps - fee_rt_bps  # net of fees at zero size
    capacity = None
    half_edge = None
    if gross_net > 0:
        # closed-form under the √N regime: impact_rt(N) = 2k√N (book regime
        # dominates at these sizes); fall back to grid scan when only ADV known
        for prev, cur in zip(points, points[1:]):
            if prev["net_edge_bps"] > 0 >= cur["net_edge_bps"]:
                # linear interpolation in √N space
                f = prev["net_edge_bps"] / (prev["net_edge_bps"] - cur["net_edge_bps"])
                capacity = prev["notional"] + f * (cur["notional"] - prev["notional"])
                break
        if capacity is None and points and points[-1]["net_edge_bps"] > 0:
            capacity = float(points[-1]["notional"])  # beyond the grid — report grid max
        for prev, cur in zip(points, points[1:]):
            half = gross_net / 2.0
            if prev["net_edge_bps"] > half >= cur["net_edge_bps"]:
                f = (prev["net_edge_bps"] - half) / (prev["net_edge_bps"] - cur["net_edge_bps"])
                half_edge = prev["notional"] + f * (cur["notional"] - prev["notional"])
                break
        if half_edge is None and capacity is not None:
            half_edge = capacity / 4.0  # √ model: half the edge at a quarter of the size
    return {
        "curve": points,
        "capacity_notional": round(capacity, 0) if capacity else 0.0,
        "half_edge_notional": round(half_edge, 0) if half_edge else 0.0,
    }


# ── report builder ──────────────────────────────────────────────────────────

def _current_order_sizes() -> dict[str, float]:
    """Live per-base average order notional from the fleet-risk snapshot."""
    try:
        snap = json.loads((OUTPUTS_DIR / "fleet_risk.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    sizes: dict[str, list[float]] = {}
    for p in snap.get("positions") or []:
        if p.get("notional_usd"):
            sizes.setdefault(p["base"], []).append(float(p["notional_usd"]))
    return {b: float(np.mean(v)) for b, v in sizes.items()}


def build_report(fee_rt_bps: float = DEFAULT_FEE_RT_BPS, max_edges: int = 40) -> dict[str, Any]:
    """Capacity analysis for every scanned edge with measurable economics."""
    try:
        wf = json.loads((OUTPUTS_DIR / "wf_report.json").read_text(encoding="utf-8"))
    except Exception:
        wf = {}
    books = load_l2_books()
    k_base, k_venue = calibrate_all(books)
    live_sizes = _current_order_sizes()

    rows: list[dict[str, Any]] = []
    for entry in (wf.get("top") or [])[:max_edges]:
        trades = float(entry.get("trades_per_split") or 0.0)
        mean_ret = float(entry.get("oos_mean_return") or 0.0)
        if trades <= 0:
            continue
        edge_rt_bps = mean_ret / trades * 1e4  # OOS return per round trip, in bps
        base = str(entry.get("symbol") or "").replace("USDT", "")
        venue = str(entry.get("exchange") or "").split("_")[0]
        k = k_base.get(base, k_venue.get(venue))
        adv = adv_usd(base)
        cap = capacity_curve(edge_rt_bps, fee_rt_bps, k, adv)
        current = live_sizes.get(base)
        capacity = cap["capacity_notional"]
        rows.append({
            "symbol": entry.get("symbol"),
            "base": base,
            "venue": venue,
            "strategy": entry.get("strategy"),
            "timeframe": entry.get("timeframe"),
            "edge_rt_bps": round(edge_rt_bps, 2),
            "fee_rt_bps": fee_rt_bps,
            "k_l2": round(k, 4) if k is not None else None,
            "adv_usd": round(adv, 0) if adv else None,
            "capacity_notional": capacity,
            "half_edge_notional": cap["half_edge_notional"],
            "current_order_usd": round(current, 0) if current else None,
            "utilization_pct": (
                round(100.0 * current / capacity, 1) if current and capacity else None
            ),
            "deployable": bool(entry.get("deployable")),
            "curve": cap["curve"],
        })

    rows.sort(key=lambda r: (r["capacity_notional"] or 0.0))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "fee_rt_bps": fee_rt_bps,
        "n_books": len(books),
        "n_edges": len(rows),
        "venue_k_median": {k: round(v, 4) for k, v in k_venue.items()},
        "edges": rows,
    }


def write_report(path: Path = OUTPUT_PATH, **kw: Any) -> dict[str, Any]:
    report = build_report(**kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = write_report()
    print(f"capacity: {report['n_edges']} edges analysed against {report['n_books']} L2 books")
    for r in report["edges"][:10]:
        print(
            f"  {r['symbol']:<12} edge={r['edge_rt_bps']:>7.1f}bps  "
            f"cap=${r['capacity_notional']:>10,.0f}  half=${r['half_edge_notional']:>10,.0f}  "
            f"util={r['utilization_pct'] if r['utilization_pct'] is not None else '—'}%"
        )


if __name__ == "__main__":
    main()
