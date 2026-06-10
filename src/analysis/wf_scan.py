"""Walk-forward scan: find strategy×timeframe×pair×direction combos with a
genuine out-of-sample edge, and export them as a candidate manifest that the
live freqtrade bots (Wall_E, Mickey) can consume.

Rationale: the noches RL/ML bots overfit — nightly validation rejects almost
every run (in-sample positive, OOS negative). This scan only promotes rule
strategies that stay positive across rolling OOS test windows, with realistic
futures costs (fees + slippage + perpetual funding) and short selling enabled.

The manifest is intentionally simple JSON so the freqtrade bridge strategy can
read it without importing this package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import pandas as pd

from src.backtesting.engine import BacktestConfig, VectorizedBacktester
from src.analysis.walk_forward import rolling_walk_forward_splits
from src.strategies.rules import build_strategy_signals

# هر بار چند ساعت است → برای محاسبهٔ funding و سالانه‌سازی Sharpe
TF_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5,
            "1h": 1.0, "2h": 2.0, "3h": 3.0, "4h": 4.0, "1d": 24.0}

# استراتژی‌های قاعده‌محور (ml_signal کنار گذاشته می‌شود؛ کند و مستعد overfit)
SCAN_STRATEGIES = [
    "ema_trend", "rsi_mean_reversion", "bollinger_mean_reversion",
    "donchian_breakout", "atr_breakout", "macd_cross", "stochastic_mr",
    "ichimoku", "supertrend", "vwap_deviation", "cmf_trend",
]


@dataclass
class ScanResult:
    dataset: str
    exchange: str
    symbol: str
    timeframe: str
    strategy: str
    allow_short: bool
    n_splits: int
    oos_mean_return: float       # میانگین بازده هر پنجرهٔ تست (مرکب)
    oos_positive_frac: float     # نسبت پنجره‌های تست با بازده مثبت
    oos_sharpe: float            # شارپِ بازدهی‌های الصاق‌شدهٔ تست
    oos_total_return: float      # بازده مرکب کل روی همهٔ پنجره‌های تست
    trades_per_split: float
    passed: bool


def _bars_per_year(timeframe: str) -> int:
    hpb = TF_HOURS.get(timeframe, 24.0)
    return max(1, int(round(24.0 * 365.0 / hpb)))


def _parse_dataset(stem: str) -> tuple[str, str, str]:
    """'bybit_futures_BTCUSDT_15m' → (exchange, symbol, timeframe)."""
    parts = stem.split("_")
    timeframe = parts[-1]
    symbol = parts[-2]
    exchange = "_".join(parts[:-2])
    return exchange, symbol, timeframe


def scan_dataset(
    data: pd.DataFrame,
    dataset: str,
    *,
    strategies: list[str] | None = None,
    train_size: int = 4000,
    test_size: int = 1000,
    min_trades_per_split: float = 2.0,
    min_positive_frac: float = 0.55,
    min_oos_mean_return: float = 0.0,
    funding_rate_8h: float = 0.0001,
) -> list[ScanResult]:
    exchange, symbol, timeframe = _parse_dataset(dataset)
    strategies = strategies or SCAN_STRATEGIES
    bars_year = _bars_per_year(timeframe)
    hours_per_bar = TF_HOURS.get(timeframe, 24.0)

    data = data.reset_index(drop=True)
    n = len(data)
    splits = rolling_walk_forward_splits(n, train_size, test_size)
    if not splits:
        return []

    results: list[ScanResult] = []
    for strategy in strategies:
        for allow_short in (False, True):
            try:
                signals = build_strategy_signals(data, strategy, allow_short=allow_short)
            except Exception:
                continue

            cfg = BacktestConfig(
                allow_short=allow_short,
                periods_per_year=bars_year,
                apply_funding=True,
                funding_rate_8h=funding_rate_8h,
                hours_per_bar=hours_per_bar,
            )
            bt = VectorizedBacktester(cfg)

            test_returns_all = []
            split_returns = []
            split_trades = []
            for sp in splits:
                seg = data.iloc[sp.test_start:sp.test_end]
                seg_sig = signals.iloc[sp.test_start:sp.test_end]
                if len(seg) < 5:
                    continue
                res = bt.run(seg.reset_index(drop=True), seg_sig.reset_index(drop=True))
                r = res.returns
                test_returns_all.append(r)
                split_returns.append(float((1.0 + r).prod() - 1.0))
                split_trades.append(float(res.position.diff().abs().fillna(0).gt(0).sum()))

            if not split_returns:
                continue

            n_sp = len(split_returns)
            oos_mean = sum(split_returns) / n_sp
            oos_pos_frac = sum(1 for x in split_returns if x > 0) / n_sp
            trades_avg = sum(split_trades) / n_sp
            stitched = pd.concat(test_returns_all, ignore_index=True)
            mu, sd = stitched.mean(), stitched.std(ddof=0)
            oos_sharpe = float((mu / sd) * (bars_year ** 0.5)) if sd and sd > 0 else 0.0
            oos_total = float((1.0 + stitched).prod() - 1.0)

            passed = (
                oos_mean > min_oos_mean_return
                and oos_pos_frac >= min_positive_frac
                and trades_avg >= min_trades_per_split
                and oos_sharpe > 0
            )
            results.append(ScanResult(
                dataset=dataset, exchange=exchange, symbol=symbol, timeframe=timeframe,
                strategy=strategy, allow_short=allow_short, n_splits=n_sp,
                oos_mean_return=round(oos_mean, 5),
                oos_positive_frac=round(oos_pos_frac, 3),
                oos_sharpe=round(oos_sharpe, 3),
                oos_total_return=round(oos_total, 5),
                trades_per_split=round(trades_avg, 1),
                passed=passed,
            ))
    return results


def scan_processed_dir(
    processed_dir: Path,
    *,
    only_symbols: list[str] | None = None,
    **kwargs,
) -> list[ScanResult]:
    out: list[ScanResult] = []
    for path in sorted(Path(processed_dir).glob("*.parquet")):
        stem = path.stem
        _, symbol, _ = _parse_dataset(stem)
        if only_symbols and symbol not in only_symbols:
            continue
        df = pd.read_parquet(path)
        if len(df) < 6000:
            continue
        out.extend(scan_dataset(df, stem, **kwargs))
    return out


def write_manifest(results: list[ScanResult], output_path: Path) -> Path:
    """Export survivors (passed=True) as a freqtrade-readable manifest."""
    survivors = [r for r in results if r.passed]
    survivors.sort(key=lambda r: r.oos_sharpe, reverse=True)
    manifest = {
        "version": 1,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "n_scanned": len(results),
        "n_passed": len(survivors),
        "candidates": [asdict(r) for r in survivors],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


# ── reporting (برای داشبورد Quant_research و گزارش ادمین soodo) ──────────────────

def _best_per_symbol(survivors: list[ScanResult], timeframe: str | None = None):
    """بهترین کاندید (بیشترین Sharpe) به ازای هر symbol، اختیاراً محدود به یک tf."""
    best: dict[str, ScanResult] = {}
    for r in survivors:
        if timeframe is not None and r.timeframe != timeframe:
            continue
        cur = best.get(r.symbol)
        if cur is None or r.oos_sharpe > cur.oos_sharpe:
            best[r.symbol] = r
    return best


def build_report(
    results: list[ScanResult],
    *,
    live_timeframe: str = "4h",
    better_tf_abs_margin: float = 0.1,
    better_tf_rel_margin: float = 0.25,
) -> dict:
    """گزارشِ خوانا برای داشبورد: شمارش‌ها، تفکیک tf/symbol، پلنِ زندهٔ بات و هشدارها.

    هشدارِ «تایم‌فریمِ بهتر»: اگر برای یک symbol بهترین کاندید روی tfِ دیگری به‌قدرِ
    کافی قوی‌تر از بهترین کاندیدِ tfِ زنده باشد، علامت‌گذاری می‌شود تا انسان دربارهٔ
    ری‌استارتِ بات (با تایم‌فریمِ جدید) تصمیم بگیرد — تغییر تایم‌فریم خودکار نیست.
    """
    survivors = sorted((r for r in results if r.passed),
                       key=lambda r: r.oos_sharpe, reverse=True)

    by_tf: dict[str, dict] = {}
    by_symbol: dict[str, dict] = {}
    for r in results:
        t = by_tf.setdefault(r.timeframe, {"scanned": 0, "passed": 0})
        t["scanned"] += 1
        t["passed"] += int(r.passed)
        s = by_symbol.setdefault(r.symbol, {"scanned": 0, "passed": 0})
        s["scanned"] += 1
        s["passed"] += int(r.passed)

    live_best = _best_per_symbol(survivors, timeframe=live_timeframe)
    global_best = _best_per_symbol(survivors, timeframe=None)

    live_plan = {
        sym: {
            "strategy": r.strategy,
            "allow_short": r.allow_short,
            "oos_sharpe": r.oos_sharpe,
            "oos_positive_frac": r.oos_positive_frac,
            "oos_total_return": r.oos_total_return,
            "exchange": r.exchange,
        }
        for sym, r in live_best.items()
    }

    alerts: list[dict] = []
    for sym, gb in global_best.items():
        if gb.timeframe == live_timeframe:
            continue
        lb = live_best.get(sym)
        live_sharpe = lb.oos_sharpe if lb else 0.0
        gap = gb.oos_sharpe - live_sharpe
        rel = gap / abs(live_sharpe) if live_sharpe else float("inf")
        if gap >= better_tf_abs_margin and rel >= better_tf_rel_margin:
            alerts.append({
                "type": "better_timeframe",
                "symbol": sym,
                "live_timeframe": live_timeframe,
                "live_strategy": lb.strategy if lb else None,
                "live_sharpe": live_sharpe,
                "candidate_timeframe": gb.timeframe,
                "candidate_strategy": gb.strategy,
                "candidate_sharpe": gb.oos_sharpe,
                "candidate_short": gb.allow_short,
                "gap": round(gap, 3),
                "message": (
                    f"{sym}: لبهٔ قوی‌تری روی {gb.timeframe} پیدا شد "
                    f"(Sharpe {gb.oos_sharpe:.2f} با {gb.strategy}) نسبت به تایم‌فریم زندهٔ "
                    f"{live_timeframe} (Sharpe {live_sharpe:.2f}). برای فعال‌سازی، بات باید با "
                    f"تایم‌فریم {gb.timeframe} ری‌استارت شود — این تغییر دستی/تأییدی است."
                ),
            })

    return {
        "version": 1,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "live_timeframe": live_timeframe,
        "n_scanned": len(results),
        "n_passed": len(survivors),
        "by_timeframe": by_tf,
        "by_symbol": by_symbol,
        "live_plan": live_plan,
        "top": [asdict(r) for r in survivors[:20]],
        "alerts": alerts,
    }


def write_report(report: dict, output_path: Path,
                 history_path: Path | None = None) -> Path:
    """گزارش را می‌نویسد و یک خط خلاصه به history (JSONL) اضافه می‌کند."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "generated_at": report["generated_at"],
            "n_scanned": report["n_scanned"],
            "n_passed": report["n_passed"],
            "n_alerts": len(report.get("alerts", [])),
            "live_timeframe": report.get("live_timeframe"),
            "top_symbol": report["top"][0]["symbol"] if report.get("top") else None,
            "top_sharpe": report["top"][0]["oos_sharpe"] if report.get("top") else None,
        }, ensure_ascii=False)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return output_path
