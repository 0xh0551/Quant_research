"""Forward-test attribution — close the loop between backtest and live.

The walk-forward scan promotes edges that the live bots (Mickey, Wall_E) then
trade, but nothing checks whether the *realized* PnL tracks the *expected* OOS
PnL. Persistent divergence means decay or a broken assumption. This module reads
the scan's live plan (expected) and the freqtrade SQLite DBs (realized) and
reports the gap per symbol, flagging meaningful divergences.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# noches bot databases (best-effort; absent → realized side is simply empty)
DEFAULT_DB_PATHS = {
    "mickey": "/home/h0551user/noches/user_data/mickey.sqlite",
    "walle": "/home/h0551user/noches/user_data/walle.sqlite",
}


def _base(symbol: str) -> str:
    """'BTC/USDT:USDT' or 'BTCUSDT' → 'BTC'."""
    s = symbol.split("/")[0].split(":")[0]
    for q in ("USDT", "USDC", "USD", "IRT", "BTC"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def expected_from_report(report: dict) -> dict[str, dict]:
    """Per-symbol expected monthly % (approx) from the live plan's OOS return."""
    out: dict[str, dict] = {}
    for sym, p in (report.get("live_plan") or {}).items():
        # oos_total_return spans all stitched test windows; treat as a coarse
        # monthly-equivalent proxy (labeled "approximate" in the UI).
        out[_base(sym)] = {
            "expected_return": round(float(p.get("oos_total_return", 0.0)), 4),
            "strategy": p.get("strategy"),
            "oos_sharpe": p.get("oos_sharpe"),
        }
    return out


def realized_from_freqtrade(db_path: str | Path) -> dict[str, dict]:
    """Closed-trade realized PnL per base symbol from a freqtrade SQLite DB."""
    p = Path(db_path)
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute(
            "SELECT pair, COUNT(*), COALESCE(SUM(close_profit),0) "
            "FROM trades WHERE is_open=0 GROUP BY pair"
        )
        for pair, n, sum_profit in cur.fetchall():
            out[_base(pair)] = {"trades": int(n), "realized_return": round(float(sum_profit or 0.0), 4)}
        con.close()
    except Exception:
        return out
    return out


def attribution(
    report: dict, db_paths: dict[str, str] | None = None, divergence_threshold: float = 0.10,
) -> dict:
    """Expected vs realized per symbol + divergence alerts."""
    db_paths = db_paths or DEFAULT_DB_PATHS
    expected = expected_from_report(report)
    realized: dict[str, dict] = {}
    for bot, path in db_paths.items():
        for base, rec in realized_from_freqtrade(path).items():
            realized.setdefault(base, {"trades": 0, "realized_return": 0.0, "bots": []})
            realized[base]["trades"] += rec["trades"]
            realized[base]["realized_return"] += rec["realized_return"]
            realized[base]["bots"].append(bot)

    rows: list[dict] = []
    alerts: list[dict] = []
    for base in sorted(set(expected) | set(realized)):
        exp = expected.get(base, {}).get("expected_return")
        rl = realized.get(base, {}).get("realized_return")
        trades = realized.get(base, {}).get("trades", 0)
        divergence = None
        status = "no_trades" if not trades else "ok"
        if exp is not None and rl is not None and trades:
            divergence = round(rl - exp, 4)
            if abs(divergence) >= divergence_threshold:
                status = "diverging"
                alerts.append({"symbol": base, "expected": exp, "realized": rl, "divergence": divergence})
        rows.append({
            "symbol": base, "expected_return": exp, "realized_return": rl,
            "trades": trades, "divergence": divergence, "status": status,
            "strategy": expected.get(base, {}).get("strategy"),
        })
    return {
        "rows": rows,
        "alerts": alerts,
        "n_symbols": len(rows),
        "total_closed_trades": sum(r["trades"] or 0 for r in rows),
    }
