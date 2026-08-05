"""Scenario stress-testing — what a tail day does to the *current* book.

Monte-Carlo cones say what typical variation looks like; they say nothing
about May-2021 or the FTX weekend. This module replays a library of named
crypto tail events (plus parametric shocks) against the fleet's live open
positions and reports, per scenario:

  • fleet & per-bot PnL (USD and % of equity)
  • liquidation count — isolated-margin approximation: a position is wiped
    when the adverse price move exceeds (1/leverage)·(1−maintenance_margin);
    the loss is then capped at its stake (that is what isolation buys you)
  • cost to flat everything through a stressed book (killswitch realism:
    per-order latency drift + stressed slippage on every exit)
  • a survives/critical/wiped verdict per scenario

Historical scenarios measure the actual worst peak-to-trough BTC move inside
the named window from the local parquet store; windows before local history
fall back to the documented canonical move (flagged ``data_available=false``).
Each asset moves beta-scaled (β from the fleet-risk snapshot when present):
``asset_move = β·market_move`` — the standard one-factor stress convention.

CLI:  python -m src.analysis.stress   → writes outputs/stress_report.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR = ROOT / "outputs"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_PATH = OUTPUTS_DIR / "stress_report.json"

MAINTENANCE_MARGIN = 0.005      # 0.5% — typical tier-1 perp maintenance
BASE_EXIT_SLIPPAGE_BPS = 5.0    # market-exit slippage in a calm book
KILLSWITCH_ORDER_LATENCY_S = 2.0


@dataclass(frozen=True)
class Scenario:
    """One stress case. ``market_move`` < 0 is a crash (BTC-equivalent move)."""

    key: str
    kind: str                       # "historical" | "shock"
    market_move: float | None = None    # for shocks; historical measures its own
    window: tuple[str, str] | None = None   # for historical replay
    fallback_move: float | None = None      # used when local data misses the window
    slippage_mult: float = 3.0      # how much the exit book deteriorates
    funding_rate_8h: float = 0.0    # concurrent funding shock (e.g. 0.003)
    funding_days: float = 1.0
    outage_hours: float = 0.0       # extra adverse drift while you cannot exit
    label_fa: str = ""
    label_en: str = ""


SCENARIOS: list[Scenario] = [
    Scenario("gap_5", "shock", market_move=-0.05, slippage_mult=2.0,
             label_fa="گپ −۵٪", label_en="−5% gap"),
    Scenario("gap_10", "shock", market_move=-0.10, slippage_mult=3.0,
             label_fa="گپ −۱۰٪", label_en="−10% gap"),
    Scenario("gap_20", "shock", market_move=-0.20, slippage_mult=5.0,
             label_fa="گپ −۲۰٪", label_en="−20% gap"),
    Scenario("melt_up_10", "shock", market_move=0.10, slippage_mult=2.0,
             label_fa="جهش +۱۰٪ (ریسک شورت‌ها)", label_en="+10% melt-up (short risk)"),
    Scenario("funding_spike", "shock", market_move=-0.03, funding_rate_8h=0.003,
             funding_days=3.0, slippage_mult=1.5,
             label_fa="جهش فاندینگ ۰٫۳٪/۸h × ۳ روز", label_en="funding spike 0.3%/8h × 3d"),
    Scenario("outage_4h", "shock", market_move=-0.06, outage_hours=4.0, slippage_mult=4.0,
             label_fa="قطعی صرافی ۴ ساعته در ریزش", label_en="4h exchange outage in a selloff"),
    Scenario("may_2021", "historical", window=("2021-05-17", "2021-05-24"),
             fallback_move=-0.30, label_fa="ریزش مه ۲۰۲۱", label_en="May-2021 crash"),
    Scenario("ftx_2022", "historical", window=("2022-11-07", "2022-11-11"),
             fallback_move=-0.25, slippage_mult=5.0,
             label_fa="سقوط FTX (نوامبر ۲۰۲۲)", label_en="FTX collapse (Nov-2022)"),
    Scenario("aug_2024", "historical", window=("2024-08-04", "2024-08-06"),
             fallback_move=-0.15, label_fa="آنوایند کری آگوست ۲۰۲۴", label_en="Aug-2024 carry unwind"),
    Scenario("apr_2025", "historical", window=("2025-04-06", "2025-04-10"),
             fallback_move=-0.12, label_fa="ریسک‌آف آوریل ۲۰۲۵", label_en="Apr-2025 risk-off"),
]


# ── historical window measurement ───────────────────────────────────────────

def _btc_daily() -> pd.Series:
    matches = sorted(PROCESSED_DIR.glob("*_BTCUSDT_1d.parquet"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return pd.Series(dtype=float)
    try:
        df = pd.read_parquet(matches[0], columns=["timestamp", "close"])
    except Exception:
        return pd.Series(dtype=float)
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return pd.Series(df["close"].astype(float).to_numpy(), index=ts).dropna()


def measure_window_move(closes: pd.Series, start: str, end: str) -> dict[str, Any] | None:
    """Worst peak-to-trough move of the window + the daily path for charting."""
    if closes.empty:
        return None
    win = closes[(closes.index >= pd.Timestamp(start, tz="UTC"))
                 & (closes.index <= pd.Timestamp(end, tz="UTC"))]
    if len(win) < 2:
        return None
    running_max = win.cummax()
    dd = win / running_max - 1.0
    worst = float(dd.min())
    path = [round(float(v / win.iloc[0] - 1.0), 4) for v in win]
    return {"move": worst, "path": path,
            "dates": [str(d.date()) for d in win.index]}


# ── position-level stress math ──────────────────────────────────────────────

@dataclass
class PositionStress:
    pnl: float = 0.0
    liquidated: bool = False
    exit_cost: float = 0.0


def stress_position(
    pos: dict[str, Any], market_move: float, beta: float,
    slippage_mult: float, funding_rate_8h: float, funding_days: float,
    outage_hours: float,
) -> PositionStress:
    """PnL of one open position under a beta-scaled market move."""
    notional = float(pos.get("notional_usd") or 0.0)
    stake = float(pos.get("stake_usd") or 0.0)
    lev = max(float(pos.get("leverage") or 1.0), 1.0)
    side = -1.0 if pos.get("side") == "short" else 1.0

    asset_move = beta * market_move
    # outage: adverse drift keeps running while you cannot exit (√t vol scaling
    # on a stressed 1%-per-√hour tail vol) — always *against* the position
    if outage_hours > 0:
        asset_move -= side * 0.01 * (outage_hours ** 0.5)

    raw_ret = side * asset_move          # return on notional
    liq_threshold = -(1.0 / lev) * (1.0 - MAINTENANCE_MARGIN)
    liquidated = raw_ret <= liq_threshold
    pnl = -stake if liquidated else raw_ret * notional

    # concurrent funding cash flow on surviving notional (long pays positive)
    if not liquidated and funding_rate_8h:
        periods = funding_days * 3.0
        pnl -= side * funding_rate_8h * periods * notional

    exit_cost = 0.0 if liquidated else notional * (
        BASE_EXIT_SLIPPAGE_BPS * slippage_mult / 1e4
    )
    return PositionStress(pnl=round(pnl, 2), liquidated=liquidated,
                          exit_cost=round(exit_cost, 2))


# ── the runner ──────────────────────────────────────────────────────────────

def _load_fleet() -> dict[str, Any]:
    """Live snapshot if the module is importable/configured, else last file."""
    try:
        from src.portfolio import fleet_risk
        return fleet_risk.build_snapshot()
    except Exception:
        try:
            return json.loads((OUTPUTS_DIR / "fleet_risk.json").read_text(encoding="utf-8"))
        except Exception:
            return {"positions": [], "per_bot": [], "per_asset": [], "fleet": {}}


def run_scenario(scn: Scenario, fleet: dict[str, Any],
                 btc: pd.Series | None = None) -> dict[str, Any]:
    positions = fleet.get("positions") or []
    betas = {a["base"]: a.get("beta_btc") for a in (fleet.get("per_asset") or [])}
    equity = float((fleet.get("fleet") or {}).get("equity_usd") or 0.0)

    move = scn.market_move
    data_available = None
    path: dict[str, Any] | None = None
    if scn.kind == "historical":
        measured = measure_window_move(
            btc if btc is not None else _btc_daily(), *scn.window
        ) if scn.window else None
        if measured:
            move, data_available = measured["move"], True
            path = {"dates": measured["dates"], "returns": measured["path"]}
        else:
            move, data_available = scn.fallback_move, False

    per_bot: dict[str, float] = {}
    total_pnl = 0.0
    total_exit = 0.0
    n_liq = 0
    worst: list[dict[str, Any]] = []
    for pos in positions:
        beta = betas.get(pos.get("base"))
        beta = float(beta) if isinstance(beta, (int, float)) else 1.0
        st = stress_position(pos, move or 0.0, beta, scn.slippage_mult,
                             scn.funding_rate_8h, scn.funding_days, scn.outage_hours)
        # killswitch latency drift: the book keeps moving while orders go out
        latency_h = len(positions) * KILLSWITCH_ORDER_LATENCY_S / 3600.0
        drift_cost = float(pos.get("notional_usd") or 0.0) * 0.01 * (latency_h ** 0.5)
        total_pnl += st.pnl
        total_exit += st.exit_cost + drift_cost
        n_liq += int(st.liquidated)
        per_bot[pos["bot"]] = per_bot.get(pos["bot"], 0.0) + st.pnl
        worst.append({"bot": pos["bot"], "pair": pos["pair"], "side": pos["side"],
                      "leverage": pos.get("leverage"), "pnl": st.pnl,
                      "liquidated": st.liquidated})

    worst.sort(key=lambda w: w["pnl"])
    pnl_pct = round(100.0 * total_pnl / equity, 2) if equity > 0 else None
    after = equity + total_pnl - total_exit
    verdict = (
        "wiped" if equity > 0 and after <= 0 else
        "critical" if pnl_pct is not None and pnl_pct <= -30 else
        "hit" if pnl_pct is not None and pnl_pct <= -10 else
        "ok"
    )
    return {
        "key": scn.key, "kind": scn.kind,
        "label_fa": scn.label_fa, "label_en": scn.label_en,
        "market_move": round(float(move or 0.0), 4),
        "data_available": data_available,
        "fleet_pnl_usd": round(total_pnl, 2),
        "fleet_pnl_pct": pnl_pct,
        "exit_cost_usd": round(total_exit, 2),
        "equity_before": round(equity, 2),
        "equity_after": round(after, 2),
        "n_liquidations": n_liq,
        "per_bot": {k: round(v, 2) for k, v in sorted(per_bot.items())},
        "worst_positions": worst[:5],
        "verdict": verdict,
        "btc_path": path,
    }


def build_report() -> dict[str, Any]:
    fleet = _load_fleet()
    btc = _btc_daily()
    results = [run_scenario(s, fleet, btc) for s in SCENARIOS]
    results.sort(key=lambda r: (r["fleet_pnl_usd"]))
    worst = results[0] if results else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "equity_usd": (fleet.get("fleet") or {}).get("equity_usd"),
        "n_positions": len(fleet.get("positions") or []),
        "assumptions": {
            "maintenance_margin": MAINTENANCE_MARGIN,
            "base_exit_slippage_bps": BASE_EXIT_SLIPPAGE_BPS,
            "killswitch_order_latency_s": KILLSWITCH_ORDER_LATENCY_S,
        },
        "worst_key": worst["key"] if worst else None,
        "scenarios": results,
    }


def write_report(path: Path = OUTPUT_PATH) -> dict[str, Any]:
    report = build_report()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = write_report()
    print(f"stress: {len(report['scenarios'])} scenarios on "
          f"{report['n_positions']} positions (equity ${report['equity_usd']})")
    for s in report["scenarios"]:
        print(f"  {s['key']:<14} move={s['market_move']:>7.2%}  "
              f"pnl=${s['fleet_pnl_usd']:>9,.0f} ({s['fleet_pnl_pct']}%)  "
              f"liq={s['n_liquidations']}  → {s['verdict']}")


if __name__ == "__main__":
    main()
