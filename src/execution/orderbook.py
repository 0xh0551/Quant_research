"""L2 order-book microstructure features for the supported venues.

Slippage analytics (slippage.py) tells you what execution *cost* after the fact.
This tells you what it *would* cost right now, from live depth — the input a bot
needs to size to available liquidity and to place book-aware limits instead of
blindly crossing.

Per snapshot, from `ccxt.<exchange>().fetch_l2_order_book(symbol, depth)` (public,
no keys):
  * mid, microprice, spread_bps, top-of-book sizes
  * book imbalance over N levels  (bid_vol - ask_vol)/(bid_vol + ask_vol)
  * **sweep_bps(target_notional)** — how many bps you'd pay to market-fill a
    given notional by walking the book. This is a live, pre-trade slippage
    estimate; the same number live bots bleed on taker exits.

Order-flow imbalance (OFI) needs two consecutive snapshots, so it is computed
downstream from the rolling parquet, not per-fetch.
"""

from __future__ import annotations

import numpy as np

# ccxt exchange id + defaultType per supported venue
VENUES = {
    "bybit": {"id": "bybit", "type": "swap"},
    "gate": {"id": "gateio", "type": "swap"},
    "okx": {"id": "okx", "type": "swap"},
    "hyperliquid": {"id": "hyperliquid", "type": "swap"},
}


def make_exchange(venue: str):
    import ccxt

    spec = VENUES[venue]
    klass = getattr(ccxt, spec["id"])
    ex = klass({"enableRateLimit": True, "options": {"defaultType": spec["type"]}})
    return ex


def _sweep_bps(levels: list, target_notional: float, mid: float) -> float | None:
    """Bps paid to fill `target_notional` by walking `levels` [[price, size], ...]."""
    if not levels or mid <= 0:
        return None
    vwap = _vwap(levels, target_notional)
    if vwap is None:
        return None
    return round(abs(vwap - mid) / mid * 1e4, 3)


def _vwap(levels: list, target_notional: float) -> float | None:
    filled = 0.0
    qty = 0.0
    notional = 0.0
    for price, size in levels:
        price = float(price)
        size = float(size)
        avail = price * size
        take = min(avail, target_notional - filled)
        if take <= 0:
            break
        q = take / price
        qty += q
        notional += take
        filled += take
    if filled < target_notional * 0.999 or qty <= 0:
        return None
    return notional / qty


def book_features(book: dict, symbol: str, venue: str, target_notionals=(500.0, 2000.0), n_levels: int = 10) -> dict:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return {"symbol": symbol, "venue": venue, "ok": False}
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0
    bid_sz = float(bids[0][1])
    ask_sz = float(asks[0][1])
    microprice = (best_bid * ask_sz + best_ask * bid_sz) / (bid_sz + ask_sz) if (bid_sz + ask_sz) else mid

    bid_vol = sum(float(p) * float(s) for p, s in bids[:n_levels])
    ask_vol = sum(float(p) * float(s) for p, s in asks[:n_levels])
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) else 0.0

    feat = {
        "symbol": symbol,
        "venue": venue,
        "ok": True,
        "mid": mid,
        "spread_bps": round((best_ask - best_bid) / mid * 1e4, 3),
        "microprice_skew_bps": round((microprice - mid) / mid * 1e4, 3),
        "imbalance_n": round(imbalance, 4),
        "bid_notional_n": round(bid_vol, 1),
        "ask_notional_n": round(ask_vol, 1),
    }
    for tn in target_notionals:
        feat[f"buy_sweep_bps_{int(tn)}"] = _sweep_bps(asks, tn, mid)
        feat[f"sell_sweep_bps_{int(tn)}"] = _sweep_bps(bids, tn, mid)
    return feat


def compute_ofi(prev: dict, cur: dict) -> float | None:
    """Order-flow imbalance between two snapshots (simplified, sign of net depth push)."""
    if not prev or not cur or not prev.get("ok") or not cur.get("ok"):
        return None
    d_bid = cur["bid_notional_n"] - prev["bid_notional_n"]
    d_ask = cur["ask_notional_n"] - prev["ask_notional_n"]
    denom = abs(d_bid) + abs(d_ask)
    if denom == 0:
        return 0.0
    return round((d_bid - d_ask) / denom, 4)
