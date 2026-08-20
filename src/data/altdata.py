"""Alternative-data feeds: positioning, vol, basis and liquidations.

The regime/risk stack so far feeds only on realized OHLCV + funding. This
module adds the four series a perp desk actually watches for *forward-looking*
state, all from public endpoints, all fail-safe (a dead feed returns an empty
frame and the rest of the snapshot still builds):

  • DVOL          — Deribit's implied-volatility index (BTC/ETH): the market's
                    priced 30d vol, not yesterday's realized
  • long/short + taker ratios — Binance futures positioning: crowd skew
                    (global accounts) and aggressive flow (taker buy/sell)
  • premium index — mark-vs-index premium for every perp on the venue plus an
                    annualized quarterly-futures term structure (cash-and-carry
                    lens; deep backwardation = stress)
  • liquidations  — OKX public liquidation orders per instrument (the venue
                    that exposes them REST-side): forced-flow tape

Series are appended incrementally to ``data/altdata/*.parquet``;
``build_snapshot`` distills the latest state + small charting series into
``outputs/altdata_snapshot.json`` with language-neutral regime-hint codes the
dashboard resolves via i18n.

Symbols default to the majors and can be extended with ``altdata_symbols``
in the site-local config. CLI:

    python -m src.data.altdata          # refresh feeds + write snapshot
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src import local_config

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
ALTDATA_DIR = ROOT / "data" / "altdata"
SNAPSHOT_PATH = ROOT / "outputs" / "altdata_snapshot.json"

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DVOL_CURRENCIES = ["BTC", "ETH"]
HTTP_TIMEOUT = 15


def _symbols() -> list[str]:
    extra = [str(s) for s in (local_config._load().get("altdata_symbols") or [])]
    return list(dict.fromkeys(DEFAULT_SYMBOLS + extra))


# ── Deribit DVOL (implied vol index) ────────────────────────────────────────

def fetch_dvol(currency: str = "BTC", days: int = 30) -> pd.DataFrame:
    """Hourly DVOL candles → DataFrame[timestamp, dvol]. Empty on failure."""
    try:
        import requests
        end = int(time.time() * 1000)
        start = end - days * 86_400_000
        r = requests.get(
            "https://www.deribit.com/api/v2/public/get_volatility_index_data",
            params={"currency": currency, "start_timestamp": str(start),
                    "end_timestamp": str(end), "resolution": "3600"},
            timeout=HTTP_TIMEOUT,
        )
        rows = (r.json().get("result") or {}).get("data") or []
        if not rows:
            return pd.DataFrame(columns=["timestamp", "dvol"])
        df = pd.DataFrame(
            [{"timestamp": pd.to_datetime(x[0], unit="ms", utc=True),
              "dvol": float(x[4])} for x in rows]
        )
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as exc:
        logger.warning("DVOL fetch failed %s: %s", currency, exc)
        return pd.DataFrame(columns=["timestamp", "dvol"])


# ── Binance positioning ratios ──────────────────────────────────────────────

def fetch_long_short_ratio(symbol: str, period: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Global account long/short ratio → DataFrame[timestamp, ls_ratio]."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        rows = ex.fapiDataGetGlobalLongShortAccountRatio(
            {"symbol": symbol, "period": period, "limit": limit})
        df = pd.DataFrame([
            {"timestamp": pd.to_datetime(int(r["timestamp"]), unit="ms", utc=True),
             "ls_ratio": float(r["longShortRatio"])}
            for r in rows or []
        ])
        return df.sort_values("timestamp").reset_index(drop=True) if not df.empty else df
    except Exception as exc:
        logger.warning("L/S ratio fetch failed %s: %s", symbol, exc)
        return pd.DataFrame(columns=["timestamp", "ls_ratio"])


def fetch_taker_ratio(symbol: str, period: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Taker buy/sell volume ratio → DataFrame[timestamp, taker_ratio]."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        rows = ex.fapiDataGetTakerlongshortRatio(
            {"symbol": symbol, "period": period, "limit": limit})
        df = pd.DataFrame([
            {"timestamp": pd.to_datetime(int(r["timestamp"]), unit="ms", utc=True),
             "taker_ratio": float(r["buySellRatio"])}
            for r in rows or []
        ])
        return df.sort_values("timestamp").reset_index(drop=True) if not df.empty else df
    except Exception as exc:
        logger.warning("taker ratio fetch failed %s: %s", symbol, exc)
        return pd.DataFrame(columns=["timestamp", "taker_ratio"])


# ── premium index + term structure ──────────────────────────────────────────

def fetch_premium_index() -> pd.DataFrame:
    """Mark-vs-index premium for every Binance futures symbol (perp + dated)."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        rows = ex.fapiPublicGetPremiumIndex()
        out = []
        for r in rows or []:
            mark = float(r.get("markPrice") or 0.0)
            index = float(r.get("indexPrice") or 0.0)
            if mark <= 0 or index <= 0:
                continue
            out.append({
                "symbol": str(r.get("symbol")),
                "mark": mark, "index": index,
                "premium_bps": (mark / index - 1.0) * 1e4,
                "funding_rate": float(r.get("lastFundingRate") or 0.0),
                "next_funding_ts": int(r.get("nextFundingTime") or 0),
            })
        return pd.DataFrame(out)
    except Exception as exc:
        logger.warning("premium index fetch failed: %s", exc)
        return pd.DataFrame(columns=["symbol", "mark", "index", "premium_bps", "funding_rate"])


def term_structure(premium: pd.DataFrame, base_symbol: str = "BTCUSDT") -> list[dict[str, Any]]:
    """Annualized basis of the perp + dated futures of one underlier.

    Dated symbols look like ``BTCUSDT_260327`` (YYMMDD expiry).
    """
    if premium.empty:
        return []
    rows = premium[premium["symbol"].str.startswith(base_symbol)]
    perp_row = rows[rows["symbol"] == base_symbol]
    index_price = float(perp_row["index"].iloc[0]) if not perp_row.empty else None
    out: list[dict[str, Any]] = []
    now = pd.Timestamp.now(tz=UTC)
    for _, r in rows.iterrows():
        sym = r["symbol"]
        if sym == base_symbol:
            out.append({"tenor": "perp", "days": 0.0,
                        "basis_ann_pct": round(float(r["funding_rate"]) * 3 * 365 * 100, 2),
                        "price": float(r["mark"])})
            continue
        try:
            expiry = pd.Timestamp(
                datetime.strptime(sym.split("_")[1], "%y%m%d"), tz="UTC"
            )
        except Exception:
            continue
        days = max((expiry - now).total_seconds() / 86400.0, 0.5)
        ref = index_price or float(r["index"])
        basis_ann = (float(r["mark"]) / ref - 1.0) * (365.0 / days)
        out.append({"tenor": sym.split("_")[1], "days": round(days, 1),
                    "basis_ann_pct": round(basis_ann * 100, 2), "price": float(r["mark"])})
    out.sort(key=lambda x: x["days"])
    return out


# ── liquidations (OKX public REST) ──────────────────────────────────────────

def _okx_contract_values(uly: str) -> dict[str, float]:
    """instId → contract value (in base units) for one OKX swap underlier."""
    try:
        import requests
        r = requests.get(
            "https://www.okx.com/api/v5/public/instruments",
            params={"instType": "SWAP", "uly": uly}, timeout=HTTP_TIMEOUT,
        )
        return {
            str(i.get("instId")): float(i.get("ctVal") or 0.0)
            for i in (r.json().get("data") or []) if i.get("ctVal")
        }
    except Exception:
        return {}


def fetch_liquidations(inst_family: str = "BTC-USDT", limit: int = 100) -> pd.DataFrame:
    """Recent filled liquidation orders on OKX swaps → one row per fill.

    OKX sizes are in *contracts*; notional = price × size × ctVal (per-contract
    base amount from the instruments endpoint — without it a BTC swap would be
    overstated 100×, so rows without a known ctVal are dropped).
    """
    try:
        import requests
        ct_vals = _okx_contract_values(inst_family)
        r = requests.get(
            "https://www.okx.com/api/v5/public/liquidation-orders",
            params={"instType": "SWAP", "state": "filled", "uly": inst_family,
                    "limit": str(limit)},
            timeout=HTTP_TIMEOUT,
        )
        out = []
        for inst in (r.json().get("data") or []):
            inst_id = str(inst.get("instId") or "")
            ct_val = ct_vals.get(inst_id)
            if not ct_val:
                continue
            for d in inst.get("details") or []:
                px = float(d.get("bkPx") or 0.0)
                sz = float(d.get("sz") or 0.0)
                out.append({
                    "timestamp": pd.to_datetime(int(d.get("ts") or 0), unit="ms", utc=True),
                    "inst": inst_id,
                    "side": str(d.get("side") or ""),      # buy = shorts liquidated
                    "price": px,
                    "notional_usd": px * sz * ct_val,
                })
        df = pd.DataFrame(out)
        return df.sort_values("timestamp").reset_index(drop=True) if not df.empty else df
    except Exception as exc:
        logger.warning("liquidations fetch failed %s: %s", inst_family, exc)
        return pd.DataFrame(columns=["timestamp", "inst", "side", "price", "notional_usd"])


# ── incremental parquet persistence ─────────────────────────────────────────

def _append_parquet(df: pd.DataFrame, name: str,
                    dedupe_on: str | list[str] = "timestamp") -> Path | None:
    if df.empty:
        return None
    ALTDATA_DIR.mkdir(parents=True, exist_ok=True)
    path = ALTDATA_DIR / f"{name}.parquet"
    if path.exists():
        try:
            old = pd.read_parquet(path)
            df = pd.concat([old, df], ignore_index=True)
        except Exception:
            pass
    keys = [dedupe_on] if isinstance(dedupe_on, str) else list(dedupe_on)
    df = df.drop_duplicates(subset=keys, keep="last").sort_values(keys[0])
    df.to_parquet(path, index=False)
    return path


def _read_series(name: str, tail: int = 720) -> pd.DataFrame:
    path = ALTDATA_DIR / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path).tail(tail)
    except Exception:
        return pd.DataFrame()


# ── refresh + snapshot ──────────────────────────────────────────────────────

def refresh_all() -> dict[str, int]:
    """Pull every feed incrementally; returns rows fetched per feed."""
    counts: dict[str, int] = {}
    for cur in DVOL_CURRENCIES:
        df = fetch_dvol(cur)
        _append_parquet(df, f"dvol_{cur}")
        counts[f"dvol_{cur}"] = len(df)
    for sym in _symbols():
        ls = fetch_long_short_ratio(sym)
        _append_parquet(ls, f"ls_ratio_{sym}")
        counts[f"ls_ratio_{sym}"] = len(ls)
        tk = fetch_taker_ratio(sym)
        _append_parquet(tk, f"taker_ratio_{sym}")
        counts[f"taker_ratio_{sym}"] = len(tk)
    liq = fetch_liquidations("BTC-USDT")
    # فیکس 2026-08-08: dedupe فقط-روی-timestamp فیل‌های متمایزِ هم‌میلی‌ثانیه‌ی
    # آبشارِ لیکوییدیشن را به یک ردیف فرو می‌ریخت — دقیقاً رژیمی که این فید
    # برایش وجود دارد.
    _append_parquet(liq, "liquidations_BTC",
                    dedupe_on=["timestamp", "inst", "side", "price"])
    counts["liquidations_BTC"] = len(liq)
    return counts


def _regime_hints(dvol_btc: pd.DataFrame, ls: pd.DataFrame,
                  term: list[dict[str, Any]]) -> list[str]:
    """Language-neutral hint codes (resolved by the dashboard i18n layer)."""
    hints: list[str] = []
    if not dvol_btc.empty and len(dvol_btc) > 100:
        cur = float(dvol_btc["dvol"].iloc[-1])
        pct = float((dvol_btc["dvol"] < cur).mean())
        if pct >= 0.9:
            hints.append("dvol_high")
        elif pct <= 0.1:
            hints.append("dvol_low")
    if not ls.empty:
        cur = float(ls["ls_ratio"].iloc[-1])
        if cur >= 3.0:
            hints.append("crowd_long")
        elif cur <= 0.7:
            hints.append("crowd_short")
    dated = [x for x in term if x["tenor"] != "perp"]
    if dated and min(x["basis_ann_pct"] for x in dated) < 0:
        hints.append("backwardation")
    return hints


def build_snapshot() -> dict[str, Any]:
    premium = fetch_premium_index()
    term_btc = term_structure(premium, "BTCUSDT")
    term_eth = term_structure(premium, "ETHUSDT")

    dvol_btc = _read_series("dvol_BTC")
    ls_btc = _read_series("ls_ratio_BTCUSDT")

    def series_out(df: pd.DataFrame, col: str) -> dict[str, list]:
        if df.empty:
            return {"ts": [], "values": []}
        return {
            "ts": [str(t) for t in pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")],
            "values": [round(float(v), 4) for v in df[col]],
        }

    # 2026-08-08: در آبشارِ واقعی 500 ردیف حتی ۲۴h را پوشش نمی‌دهد → جمعِ
    # liquidations_24h_usd بی‌صدا کم‌نمایی می‌شد. نمایش همچنان tail(30) است.
    liq = _read_series("liquidations_BTC", tail=20000)
    liq_24h = 0.0
    liq_rows: list[dict[str, Any]] = []
    if not liq.empty:
        cutoff = pd.Timestamp.now(tz=UTC) - pd.Timedelta(hours=24)
        recent = liq[pd.to_datetime(liq["timestamp"]) >= cutoff]
        liq_24h = float(recent["notional_usd"].sum()) if not recent.empty else 0.0
        liq_rows = [
            {"ts": str(r["timestamp"]), "side": r["side"],
             "notional_usd": round(float(r["notional_usd"]), 0)}
            for _, r in liq.tail(30).iloc[::-1].iterrows()
        ]

    # funding extremes across the venue (perps only)
    extremes: list[dict[str, Any]] = []
    if not premium.empty:
        perps = premium[~premium["symbol"].str.contains("_")].copy()
        perps["funding_ann_pct"] = perps["funding_rate"] * 3 * 365 * 100
        hot = perps.reindex(perps["funding_ann_pct"].abs().sort_values(ascending=False).index).head(12)
        extremes = [
            {"symbol": r["symbol"], "funding_ann_pct": round(float(r["funding_ann_pct"]), 1),
             "premium_bps": round(float(r["premium_bps"]), 2)}
            for _, r in hot.iterrows()
        ]

    per_symbol = []
    for sym in _symbols():
        ls_s = _read_series(f"ls_ratio_{sym}")
        tk_s = _read_series(f"taker_ratio_{sym}")
        per_symbol.append({
            "symbol": sym,
            "ls_ratio": round(float(ls_s["ls_ratio"].iloc[-1]), 3) if not ls_s.empty else None,
            "taker_ratio": round(float(tk_s["taker_ratio"].iloc[-1]), 3) if not tk_s.empty else None,
        })

    snap = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dvol": {
            cur: (round(float(s["dvol"].iloc[-1]), 2) if not (s := _read_series(f"dvol_{cur}")).empty else None)
            for cur in DVOL_CURRENCIES
        },
        "dvol_series_btc": series_out(dvol_btc, "dvol"),
        "ls_series_btc": series_out(ls_btc, "ls_ratio"),
        "term_structure": {"BTCUSDT": term_btc, "ETHUSDT": term_eth},
        "funding_extremes": extremes,
        "per_symbol": per_symbol,
        "liquidations_24h_usd": round(liq_24h, 0),
        "recent_liquidations": liq_rows,
        "regime_hints": _regime_hints(dvol_btc, ls_btc, term_btc),
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def main() -> None:
    counts = refresh_all()
    snap = build_snapshot()
    fetched = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"altdata refreshed: {fetched}")
    print(f"snapshot: dvol={snap['dvol']}  hints={snap['regime_hints']}  "
          f"liq24h=${snap['liquidations_24h_usd']:,.0f}")


if __name__ == "__main__":
    main()
