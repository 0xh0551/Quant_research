"""Fleet-level risk aggregation across every live/paper bot.

Each bot manages its own risk, but nobody watches the *sum*: six bots can end
up long the same BTC-beta trade at once, and per-bot limits never see it. This
module reads every configured freqtrade DB (read-only), marks open positions to
the freshest local price, and rolls everything up into one snapshot:

  • per-position rows (bot, pair, side, leverage, notional, uPnL, price age)
  • per-asset net/gross exposure (long − short across all bots)
  • fleet aggregates — equity, gross/net notional, gross leverage,
    net BTC-beta-weighted delta, concentration (HHI), directional bias
  • pairwise return correlation of the held bases (crowding lens)
  • limit checks → structured alerts (level: warn / critical)

Deployment wiring (bot DBs, wallets, limits) lives in the gitignored
``configs/local.json``; without it everything degrades to an empty snapshot.

local.json keys used here (all optional)::

    "bot_dbs":       {"MyBot": "mybot.sqlite", ...}
    "bot_wallets":   {"MyBot": 1000.0}          # dry-run starting wallet, default 1000
    "fleet_risk_limits": {
        "max_gross_leverage": 3.0,              # gross notional / fleet equity
        "max_net_delta_pct": 200.0,             # |net beta-delta| as % of equity
        "max_asset_pct": 60.0,                  # single-asset gross as % of gross
        "max_bot_gross_leverage": 8.0,          # per-bot notional / bot equity
        "max_avg_pairwise_corr": 0.75           # crowding threshold
    }

CLI:  python -m src.portfolio.fleet_risk   → writes outputs/fleet_risk.json
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src import local_config

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_PATH = ROOT / "outputs" / "fleet_risk.json"

DEFAULT_WALLET = 1_000.0
DEFAULT_LIMITS: dict[str, float] = {
    "max_gross_leverage": 3.0,
    "max_net_delta_pct": 200.0,
    "max_asset_pct": 60.0,
    "max_bot_gross_leverage": 8.0,
    "max_avg_pairwise_corr": 0.75,
}

# price freshness: beyond this the mark price is flagged stale (still used —
# a stale mark is better than no mark, but the UI must show it).
PRICE_STALE_HOURS = 6.0
CORR_LOOKBACK_DAYS = 30
BETA_LOOKBACK_DAYS = 60


# ── freqtrade DB access (read-only) ─────────────────────────────────────────

def _connect_ro(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return None


def _bot_frames(db_path: Path) -> tuple[pd.DataFrame, float]:
    """(open positions, realized closed profit) for one bot DB."""
    con = _connect_ro(db_path)
    if con is None:
        return pd.DataFrame(), 0.0
    try:
        open_df = pd.read_sql_query(
            "SELECT pair, is_short, leverage, stake_amount, amount, open_rate, "
            "open_date, funding_fee_running FROM trades WHERE is_open=1",
            con,
        )
        closed = pd.read_sql_query(
            "SELECT COALESCE(SUM(close_profit_abs), 0) AS pnl "
            "FROM trades WHERE is_open=0 AND close_date IS NOT NULL",
            con,
        )
        realized = float(closed["pnl"].iloc[0] or 0.0)
    except Exception:
        open_df, realized = pd.DataFrame(), 0.0
    finally:
        con.close()
    return open_df, realized


# ── price / beta helpers from the local parquet store ───────────────────────

def _base_of(pair: str) -> str:
    return str(pair).split("/")[0].strip()


def _find_dataset(base: str, prefer_tfs: tuple[str, ...] = ("15m", "1h", "4h", "1d")) -> Path | None:
    """Freshest processed parquet whose symbol matches ``<base>USDT``."""
    if not PROCESSED_DIR.exists():
        return None
    for tf in prefer_tfs:
        matches = sorted(
            PROCESSED_DIR.glob(f"*_{base}USDT_{tf}.parquet"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None


def _tail_closes(path: Path, rows: int = 8_000) -> pd.Series:
    try:
        df = pd.read_parquet(path, columns=["timestamp", "close"])
    except Exception:
        return pd.Series(dtype=float)
    if df.empty:
        return pd.Series(dtype=float)
    df = df.tail(rows)
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    s = pd.Series(df["close"].astype(float).to_numpy(), index=ts)
    return s[~s.index.isna()]


def _mark_price(base: str) -> tuple[float | None, float | None]:
    """(latest close, age_hours) from the freshest local dataset."""
    path = _find_dataset(base)
    if path is None:
        return None, None
    closes = _tail_closes(path, rows=3)
    if closes.empty:
        return None, None
    age_h = (pd.Timestamp.now(tz=UTC) - closes.index[-1]).total_seconds() / 3600.0
    return float(closes.iloc[-1]), round(age_h, 2)


def _daily_returns(base: str, days: int) -> pd.Series:
    path = _find_dataset(base)
    if path is None:
        return pd.Series(dtype=float)
    closes = _tail_closes(path)
    if closes.empty:
        return pd.Series(dtype=float)
    daily = closes.resample("1D").last().dropna()
    cutoff = pd.Timestamp.now(tz=UTC) - pd.Timedelta(days=days)
    return daily[daily.index >= cutoff].pct_change().dropna()


def _betas_to_btc(bases: list[str]) -> dict[str, float]:
    """OLS beta of each base's daily returns to BTC (BTC itself → 1.0)."""
    btc = _daily_returns("BTC", BETA_LOOKBACK_DAYS)
    out: dict[str, float] = {}
    for base in bases:
        if base == "BTC":
            out[base] = 1.0
            continue
        r = _daily_returns(base, BETA_LOOKBACK_DAYS)
        joined = pd.concat([r, btc], axis=1, join="inner").dropna()
        if len(joined) < 10 or joined.iloc[:, 1].var() == 0:
            out[base] = float("nan")
            continue
        cov = joined.iloc[:, 0].cov(joined.iloc[:, 1])
        out[base] = round(float(cov / joined.iloc[:, 1].var()), 3)
    return out


def _correlation_matrix(bases: list[str]) -> dict[str, Any]:
    """Pairwise correlation of held bases' daily returns (crowding lens)."""
    series = {b: _daily_returns(b, CORR_LOOKBACK_DAYS) for b in bases}
    series = {b: s for b, s in series.items() if len(s) >= 8}
    if len(series) < 2:
        return {"bases": list(series), "matrix": [], "avg_pairwise": None}
    frame = pd.DataFrame(series).dropna()
    if len(frame) < 8:
        return {"bases": list(series), "matrix": [], "avg_pairwise": None}
    corr = frame.corr()
    tri = corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1))
    avg = float(np.nanmean(tri.to_numpy())) if tri.notna().any().any() else None
    return {
        "bases": list(corr.columns),
        "matrix": [[round(float(v), 3) for v in row] for row in corr.to_numpy()],
        "avg_pairwise": round(avg, 3) if avg is not None else None,
    }


# ── snapshot builder ────────────────────────────────────────────────────────

def _limits() -> dict[str, float]:
    cfg = (local_config._load().get("fleet_risk_limits") or {})
    merged = dict(DEFAULT_LIMITS)
    for k, v in cfg.items():
        try:
            merged[k] = float(v)
        except (TypeError, ValueError):
            pass
    return merged


def _wallets() -> dict[str, float]:
    raw = local_config._load().get("bot_wallets") or {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def build_snapshot() -> dict[str, Any]:
    """Aggregate every configured bot DB into one fleet risk snapshot."""
    bot_dbs = local_config.bot_databases()
    wallets = _wallets()
    limits = _limits()

    positions: list[dict[str, Any]] = []
    per_bot: list[dict[str, Any]] = []
    price_cache: dict[str, tuple[float | None, float | None]] = {}

    for bot, db_path in sorted(bot_dbs.items()):
        open_df, realized = _bot_frames(db_path)
        start_wallet = wallets.get(bot, DEFAULT_WALLET)
        bot_equity = start_wallet + realized
        bot_gross = 0.0
        bot_unrealized = 0.0
        n_open = 0

        for _, row in open_df.iterrows():
            base = _base_of(row["pair"])
            if base not in price_cache:
                price_cache[base] = _mark_price(base)
            mark, age_h = price_cache[base]
            side = -1 if int(row.get("is_short") or 0) else 1
            lev = float(row.get("leverage") or 1.0)
            stake = float(row.get("stake_amount") or 0.0)
            open_rate = float(row.get("open_rate") or 0.0)
            amount = float(row.get("amount") or 0.0)
            notional = (mark if mark else open_rate) * amount
            upnl = side * (mark - open_rate) * amount if (mark and open_rate) else None
            funding_run = row.get("funding_fee_running")
            positions.append({
                "bot": bot,
                "pair": str(row["pair"]),
                "base": base,
                "side": "short" if side < 0 else "long",
                "leverage": round(lev, 2),
                "stake_usd": round(stake, 2),
                "notional_usd": round(notional, 2),
                "open_rate": open_rate,
                "mark_price": mark,
                "price_age_hours": age_h,
                "price_stale": bool(age_h is not None and age_h > PRICE_STALE_HOURS),
                "unrealized_pnl": round(upnl, 2) if upnl is not None else None,
                "funding_running": round(float(funding_run), 4) if funding_run is not None else None,
                "signed_notional": round(side * notional, 2),
                "open_date": str(row.get("open_date") or ""),
            })
            bot_gross += notional
            bot_unrealized += upnl or 0.0
            n_open += 1

        per_bot.append({
            "bot": bot,
            "db_found": db_path.exists(),
            "equity_usd": round(bot_equity + bot_unrealized, 2),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(bot_unrealized, 2),
            "gross_notional": round(bot_gross, 2),
            "gross_leverage": round(bot_gross / bot_equity, 2) if bot_equity > 0 else None,
            "n_open": n_open,
        })

    pos_df = pd.DataFrame(positions)
    fleet_equity = float(sum(b["equity_usd"] for b in per_bot)) or 0.0

    # per-asset aggregation
    per_asset: list[dict[str, Any]] = []
    betas: dict[str, float] = {}
    net_delta = 0.0
    if not pos_df.empty:
        bases = sorted(pos_df["base"].unique().tolist())
        betas = _betas_to_btc(bases)
        for base, grp in pos_df.groupby("base"):
            gross = float(grp["notional_usd"].sum())
            net = float(grp["signed_notional"].sum())
            beta = betas.get(base, float("nan"))
            beta_delta = net * beta if np.isfinite(beta) else net  # fallback β=1
            net_delta += beta_delta
            per_asset.append({
                "base": base,
                "gross_notional": round(gross, 2),
                "net_notional": round(net, 2),
                "beta_btc": None if not np.isfinite(beta) else beta,
                "beta_delta": round(beta_delta, 2),
                "n_positions": int(len(grp)),
                "bots": sorted(grp["bot"].unique().tolist()),
            })
        per_asset.sort(key=lambda a: -a["gross_notional"])

    gross_notional = float(pos_df["notional_usd"].sum()) if not pos_df.empty else 0.0
    net_notional = float(pos_df["signed_notional"].sum()) if not pos_df.empty else 0.0
    gross_lev = gross_notional / fleet_equity if fleet_equity > 0 else 0.0
    hhi = (
        float(((pos_df.groupby("base")["notional_usd"].sum() / gross_notional) ** 2).sum())
        if gross_notional > 0
        else 0.0
    )
    corr = _correlation_matrix(sorted(pos_df["base"].unique().tolist())) if not pos_df.empty else {
        "bases": [], "matrix": [], "avg_pairwise": None,
    }

    fleet = {
        "equity_usd": round(fleet_equity, 2),
        "gross_notional": round(gross_notional, 2),
        "net_notional": round(net_notional, 2),
        "gross_leverage": round(gross_lev, 2),
        "net_beta_delta": round(net_delta, 2),
        "net_beta_delta_pct": round(100.0 * net_delta / fleet_equity, 1) if fleet_equity > 0 else None,
        "hhi": round(hhi, 3),
        "n_positions": int(len(pos_df)),
        "n_bots": len(per_bot),
        "avg_pairwise_corr": corr["avg_pairwise"],
    }

    alerts = _check_limits(fleet, per_asset, per_bot, limits)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "fleet": fleet,
        "per_bot": per_bot,
        "per_asset": per_asset,
        "positions": positions,
        "correlation": corr,
        "limits": limits,
        "alerts": alerts,
    }


def _check_limits(
    fleet: dict[str, Any],
    per_asset: list[dict[str, Any]],
    per_bot: list[dict[str, Any]],
    limits: dict[str, float],
) -> list[dict[str, Any]]:
    """Structured limit breaches. `code` is language-neutral for the i18n layer."""
    alerts: list[dict[str, Any]] = []

    def add(code: str, level: str, value: float | None, limit: float, ctx: str = "") -> None:
        alerts.append({
            "code": code, "level": level, "value": value, "limit": limit, "context": ctx,
        })

    gl = fleet.get("gross_leverage") or 0.0
    if gl > limits["max_gross_leverage"]:
        add("gross_leverage", "critical" if gl > 1.5 * limits["max_gross_leverage"] else "warn",
            gl, limits["max_gross_leverage"])

    nd = fleet.get("net_beta_delta_pct")
    if nd is not None and abs(nd) > limits["max_net_delta_pct"]:
        add("net_delta", "critical" if abs(nd) > 1.5 * limits["max_net_delta_pct"] else "warn",
            nd, limits["max_net_delta_pct"])

    gross = fleet.get("gross_notional") or 0.0
    if gross > 0:
        for a in per_asset:
            pct = 100.0 * a["gross_notional"] / gross
            if pct > limits["max_asset_pct"]:
                add("asset_concentration", "warn", round(pct, 1), limits["max_asset_pct"], a["base"])

    for b in per_bot:
        if b.get("gross_leverage") and b["gross_leverage"] > limits["max_bot_gross_leverage"]:
            add("bot_leverage", "warn", b["gross_leverage"], limits["max_bot_gross_leverage"], b["bot"])
        if not b.get("db_found"):
            add("bot_db_missing", "critical", None, 0.0, b["bot"])

    apc = fleet.get("avg_pairwise_corr")
    if apc is not None and apc > limits["max_avg_pairwise_corr"]:
        add("crowding_corr", "warn", apc, limits["max_avg_pairwise_corr"])

    return alerts


def write_snapshot(path: Path = OUTPUT_PATH) -> dict[str, Any]:
    snap = build_snapshot()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def main() -> None:
    snap = write_snapshot()
    fleet = snap["fleet"]
    print(
        f"fleet_risk: equity=${fleet['equity_usd']}  gross={fleet['gross_notional']}"
        f"  lev={fleet['gross_leverage']}x  netΔ={fleet['net_beta_delta']}"
        f"  positions={fleet['n_positions']}  alerts={len(snap['alerts'])}"
    )
    for a in snap["alerts"]:
        print(f"  [{a['level']}] {a['code']} value={a['value']} limit={a['limit']} {a['context']}")
    raise SystemExit(2 if any(a["level"] == "critical" for a in snap["alerts"]) else 0)


if __name__ == "__main__":
    main()
