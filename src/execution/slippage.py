"""Execution-quality analytics from freqtrade order/trade DBs (read-only).

Two independent slippage lenses, both derived from data freqtrade already records
(no new instrumentation needed):

  * TRADE level  — `open_rate`/`close_rate` (VWAP actually filled) vs
    `open_rate_requested`/`close_rate_requested` (what the strategy asked for).
    This is the truest "did we get the price we wanted" measure and captures the
    whole entry/exit, DCA fills included.
  * ORDER level  — per fill, `price` (submitted) vs `average` (filled), tagged by
    `order_type` (market/taker vs limit/maker) and `side`. Adds fill latency
    (`order_date` -> `order_filled_date`) and the limit-order cancel/non-fill rate,
    which is the *hidden* cost of a maker strategy.

Slippage is expressed as **adverse basis points** (positive = worse than intended):
  buy  adverse_bps = (filled - intended) / intended * 1e4
  sell adverse_bps = (intended - filled) / intended * 1e4
and as a **quote-currency cost** (adverse_bps/1e4 * notional) so it can be summed
against realised PnL to show what fraction of gross edge execution is eating.

All DB access is `mode=ro`; every failure fails safe to an empty frame.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

USER_DATA = Path("/home/h0551user/noches/user_data")

# canonical bot -> live sqlite (the root-level *.sqlite files are 0-byte decoys;
# the real DBs live under user_data/, WAL mode)
BOTS: dict[str, str] = {
    "Bender": "bender.sqlite",
    "Gadget": "gadget.sqlite",
    "Klaymen": "klaymen.sqlite",
    "Popeye": "popeye.sqlite",
    "Mickey": "mickey.sqlite",
    "Wall_E": "walle.sqlite",
}


def _connect_ro(db_path: str | Path) -> sqlite3.Connection | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return None


def load_trades(db_path: str | Path, since_days: float | None = None) -> pd.DataFrame:
    """Closed trades with the requested-vs-actual rate columns."""
    con = _connect_ro(db_path)
    if con is None:
        return pd.DataFrame()
    where = "is_open=0 AND close_date IS NOT NULL"
    params: tuple = ()
    if since_days is not None:
        cutoff = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=since_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        where += " AND close_date >= ?"
        params = (cutoff,)
    try:
        df = pd.read_sql_query(
            "SELECT id, pair, is_short, leverage, enter_tag, exit_reason, "
            "open_rate, open_rate_requested, close_rate, close_rate_requested, "
            "amount, stake_amount, open_trade_value, "
            "close_profit, close_profit_abs, open_date, close_date "
            f"FROM trades WHERE {where}",
            con,
            params=params,
        )
    except Exception:
        con.close()
        return pd.DataFrame()
    con.close()
    if df.empty:
        return df

    df["base"] = df["pair"].str.split("/").str[0]
    df["is_short"] = df["is_short"].fillna(0).astype(int)
    for c in ("open_date", "close_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["hold_hours"] = (df["close_date"] - df["open_date"]).dt.total_seconds() / 3600.0

    # entry slippage: long buys in, short sells in
    df["entry_adv_bps"] = _adverse_bps(
        requested=df["open_rate_requested"],
        actual=df["open_rate"],
        is_buy=df["is_short"] == 0,
    )
    # exit slippage: long sells out, short buys out
    df["exit_adv_bps"] = _adverse_bps(
        requested=df["close_rate_requested"],
        actual=df["close_rate"],
        is_buy=df["is_short"] == 1,
    )
    notional = df["open_trade_value"].where(df["open_trade_value"] > 0, df["stake_amount"] * df["leverage"].clip(lower=1))
    df["notional"] = notional.fillna(df["stake_amount"]).fillna(0.0)
    # round-trip execution cost in quote ccy (entry + exit legs of the same notional)
    df["exec_cost_quote"] = (
        (df["entry_adv_bps"].fillna(0) + df["exit_adv_bps"].fillna(0)) / 1e4 * df["notional"]
    )
    return df


def load_orders(db_path: str | Path, since_days: float | None = None) -> pd.DataFrame:
    """Per-order fills joined to their trade for side/tag context."""
    con = _connect_ro(db_path)
    if con is None:
        return pd.DataFrame()
    where = "o.average IS NOT NULL AND o.price IS NOT NULL AND o.price > 0 AND o.filled > 0"
    params: tuple = ()
    if since_days is not None:
        cutoff = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=since_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        where += " AND o.order_date >= ?"
        params = (cutoff,)
    try:
        df = pd.read_sql_query(
            "SELECT o.ft_trade_id, o.ft_pair AS pair, o.ft_order_side, o.order_type, o.side, "
            "o.price, o.average, o.filled, o.cost, o.status, "
            "o.order_date, o.order_filled_date, t.is_short, t.enter_tag "
            "FROM orders o LEFT JOIN trades t ON t.id = o.ft_trade_id "
            f"WHERE {where}",
            con,
            params=params,
        )
    except Exception:
        con.close()
        return pd.DataFrame()
    con.close()
    if df.empty:
        return df

    df["base"] = df["pair"].str.split("/").str[0]
    df["is_buy"] = df["side"].str.lower().eq("buy")
    df["adv_bps"] = _adverse_bps(requested=df["price"], actual=df["average"], is_buy=df["is_buy"])
    df["notional"] = df["cost"].where(df["cost"] > 0, df["filled"] * df["average"])
    df["adv_cost_quote"] = df["adv_bps"] / 1e4 * df["notional"]
    for c in ("order_date", "order_filled_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["fill_latency_s"] = (df["order_filled_date"] - df["order_date"]).dt.total_seconds()
    df["is_taker"] = df["order_type"].str.lower().eq("market")
    return df


def _adverse_bps(requested: pd.Series, actual: pd.Series, is_buy: pd.Series) -> pd.Series:
    """Adverse slippage in bps: positive = filled worse than requested."""
    requested = pd.to_numeric(requested, errors="coerce")
    actual = pd.to_numeric(actual, errors="coerce")
    diff = np.where(is_buy, actual - requested, requested - actual)
    with np.errstate(divide="ignore", invalid="ignore"):
        bps = diff / requested * 1e4
    bps = pd.Series(bps, index=requested.index)
    return bps.where(requested > 0)


def _cancel_rate(db_path: str | Path, since_days: float | None) -> dict:
    """Limit-order non-fill rate: the hidden cost of a maker strategy."""
    con = _connect_ro(db_path)
    if con is None:
        return {}
    where = "order_type IS NOT NULL"
    params: tuple = ()
    if since_days is not None:
        cutoff = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=since_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        where += " AND order_date >= ?"
        params = (cutoff,)
    try:
        rows = con.execute(
            f"SELECT order_type, status, COUNT(*) FROM orders WHERE {where} GROUP BY order_type, status",
            params,
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()
    limit_total = sum(n for ot, _, n in rows if (ot or "").lower() == "limit")
    limit_cxl = sum(n for ot, st, n in rows if (ot or "").lower() == "limit" and (st or "").lower() in ("canceled", "cancelled", "expired"))
    return {
        "limit_orders": int(limit_total),
        "limit_canceled": int(limit_cxl),
        "limit_cancel_rate": round(limit_cxl / limit_total, 4) if limit_total else None,
    }


def _wavg(values: pd.Series, weights: pd.Series) -> float | None:
    m = values.notna() & weights.notna() & (weights > 0)
    if not m.any():
        return None
    return float(np.average(values[m], weights=weights[m]))


def bot_execution_summary(bot: str, db_path: str | Path, since_days: float | None = 45.0) -> dict:
    """One bot's execution scorecard. Returns a JSON-safe dict.

    Headline slippage $/bps come from the ORDER level (per-fill `price` vs
    `average`, order_type-aware): clean for takers (real slippage) and ~0 for
    makers (fills at the posted limit), with the maker cost captured separately
    as the limit non-fill rate. Trade-level `open_rate_requested` vs `open_rate`
    is kept only as an `intent_vs_fill` diagnostic — it is *unreliable for market
    entries* (the requested rate isn't a genuine target), so it is never summed
    into the headline cost.
    """
    trades = load_trades(db_path, since_days=since_days)
    orders = load_orders(db_path, since_days=since_days)
    out: dict = {"bot": bot, "since_days": since_days, "n_trades": int(len(trades))}
    if trades.empty:
        out["note"] = "no closed trades in window"
        return out

    gross = float(trades["close_profit_abs"].sum())
    out["gross_pnl_quote"] = round(gross, 2)
    out["notional_traded_quote"] = round(float(trades["notional"].sum()), 2)

    slip_cost = 0.0
    if not orders.empty:
        taker = orders[orders["is_taker"]]
        maker = orders[~orders["is_taker"]]
        slip_cost = float(orders["adv_cost_quote"].sum())
        out["orders"] = {
            "n_fills": int(len(orders)),
            "taker_fills": int(len(taker)),
            "maker_fills": int(len(maker)),
            "taker_slip_bps_wavg": _round(_wavg(taker["adv_bps"], taker["notional"])),
            "maker_slip_bps_wavg": _round(_wavg(maker["adv_bps"], maker["notional"])),
            "taker_slip_cost_quote": round(float(taker["adv_cost_quote"].sum()), 2) if not taker.empty else 0.0,
            "maker_slip_cost_quote": round(float(maker["adv_cost_quote"].sum()), 2) if not maker.empty else 0.0,
            "market_fill_latency_p50_s": _round(taker["fill_latency_s"].median()) if not taker.empty else None,
            "market_fill_latency_p95_s": _round(taker["fill_latency_s"].quantile(0.95)) if not taker.empty else None,
        }
        out["orders"].update(_cancel_rate(db_path, since_days))

    # headline: order-level realised slippage cost
    out["slip_cost_quote"] = round(slip_cost, 2)
    out["slip_pct_of_gross"] = _pct_of_gross(slip_cost, gross)
    # diagnostic only (limit-reliable; market-entry values are noisy — see docstring)
    out["intent_vs_fill_bps"] = {
        "entry": _round(_wavg(trades["entry_adv_bps"], trades["notional"])),
        "exit": _round(_wavg(trades["exit_adv_bps"], trades["notional"])),
    }

    # worst offenders by realised execution cost (order level, so market exits show up)
    if not orders.empty:
        by_base = orders.groupby("base")["adv_cost_quote"].sum().sort_values(ascending=False)
        out["worst_bases_by_slip_cost"] = {k: round(float(v), 2) for k, v in by_base.head(5).items()}
        by_tag = orders.groupby(orders["enter_tag"].fillna("?"))["adv_cost_quote"].sum().sort_values(ascending=False)
        out["worst_tags_by_slip_cost"] = {k: round(float(v), 2) for k, v in by_tag.head(4).items()}
    return out


def fleet_report(user_data: str | Path = USER_DATA, since_days: float | None = 45.0) -> dict:
    """Execution scorecard across every bot + a fleet roll-up."""
    ud = Path(user_data)
    bots = {b: bot_execution_summary(b, ud / f, since_days=since_days) for b, f in BOTS.items()}
    gross = sum(b.get("gross_pnl_quote", 0.0) or 0.0 for b in bots.values())
    slip = sum(b.get("slip_cost_quote", 0.0) or 0.0 for b in bots.values())
    notional = sum(b.get("notional_traded_quote", 0.0) or 0.0 for b in bots.values())
    ann = None
    if since_days:
        ann = round(slip / since_days * 365.0, 2)
    return {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "window_days": since_days,
        "fleet": {
            "gross_pnl_quote": round(gross, 2),
            "roundtrip_slip_cost_quote": round(slip, 2),
            "slip_pct_of_gross": _pct_of_gross(slip, gross),
            "notional_traded_quote": round(notional, 2),
            "annualized_slip_drag_quote": ann,
        },
        "bots": bots,
    }


def _round(x, nd: int = 2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)


def _pct_of_gross(cost: float, gross: float):
    if not gross:
        return None
    # cost is a drag; express as % of |gross| so sign is intuitive
    return round(cost / abs(gross) * 100.0, 1)
