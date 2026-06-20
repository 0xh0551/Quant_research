#!/usr/bin/env python3
"""Probe what NATIVE Hyperliquid data is actually available (no proxy).
Decides the money-flow strategy's foundation: OHLCV depth, Open Interest, funding,
volume — all from HL's own API."""
import ccxt, time, json

ex = ccxt.hyperliquid()

print("=== 1) OHLCV depth (how many recent candles does HL give?) ===")
for tf in ("1h", "15m"):
    try:
        o = ex.fetch_ohlcv("BTC/USDC:USDC", tf, limit=5000)
        if o:
            span_h = (o[-1][0] - o[0][0]) / 3600_000
            print(f"  {tf}: {len(o)} candles | {time.strftime('%Y-%m-%d', time.gmtime(o[0][0]/1000))} "
                  f"-> {time.strftime('%Y-%m-%d', time.gmtime(o[-1][0]/1000))} (~{span_h/24:.0f} days)")
    except Exception as e:
        print(f"  {tf}: ERR {repr(e)[:120]}")

print("\n=== 2) metaAndAssetCtxs (OI, funding, day volume per coin = money-flow gold) ===")
try:
    info = ex.publicPostInfo({"type": "metaAndAssetCtxs"})
    meta, ctxs = info[0], info[1]
    names = [u["name"] for u in meta["universe"]]
    rows = []
    for nm, c in zip(names, ctxs):
        oi = float(c.get("openInterest", 0) or 0)
        mark = float(c.get("markPx", 0) or 0)
        vol = float(c.get("dayNtlVlm", 0) or 0)
        fund = float(c.get("funding", 0) or 0)
        rows.append((nm, oi * mark, vol, fund))
    rows.sort(key=lambda r: -r[1])
    print(f"  total coins: {len(names)} | fields per coin: {sorted(ctxs[0].keys())}")
    print(f"  {'coin':<8}{'OI_usd($M)':>12}{'dayVol($M)':>12}{'funding':>12}")
    for nm, oiusd, vol, fund in rows[:18]:
        print(f"  {nm:<8}{oiusd/1e6:>12.1f}{vol/1e6:>12.1f}{fund:>12.6f}")
    print(f"  ... ({len(rows)} total). coins with OI>$5M:", sum(1 for r in rows if r[1] > 5e6))
except Exception as e:
    print(f"  ERR {repr(e)[:200]}")

print("\n=== 3) funding-rate history (backtestable signal?) ===")
try:
    fh = ex.fetch_funding_rate_history("BTC/USDC:USDC", limit=500)
    if fh:
        print(f"  BTC funding history: {len(fh)} points | "
              f"{time.strftime('%Y-%m-%d', time.gmtime(fh[0]['timestamp']/1000))} -> "
              f"{time.strftime('%Y-%m-%d', time.gmtime(fh[-1]['timestamp']/1000))}")
except Exception as e:
    print(f"  ERR {repr(e)[:160]}")

print("\n=== 4) historical OI? (does HL backfill OI, or must we poll forward?) ===")
for meth in ("fetch_open_interest_history", "fetchOpenInterestHistory"):
    try:
        fn = getattr(ex, meth, None)
        if fn:
            oih = fn("BTC/USDC:USDC", "1h", limit=100)
            print(f"  {meth}: {len(oih)} points -> OI history IS available")
            break
    except Exception as e:
        print(f"  {meth}: {repr(e)[:120]}")
else:
    print("  no OI-history endpoint → must POLL metaAndAssetCtxs hourly to build OI series")
