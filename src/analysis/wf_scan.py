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
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.statistics import (
    bootstrap_metric_ci,
    probability_of_backtest_overfitting,
    sharpe_significance,
)
from src.analysis.walk_forward import rolling_walk_forward_splits
from src.backtesting.engine import BacktestConfig, VectorizedBacktester
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
    # ── statistical-rigor fields (selection-bias defences) ──────────────
    psr: float = 0.0                 # P(true Sharpe > 0)
    dsr: float = float("nan")        # deflated Sharpe (multiple-testing aware)
    pbo: float = float("nan")        # dataset-level Prob. of Backtest Overfitting
    sharpe_ci_low: float = 0.0       # bootstrap 95% CI on annualized Sharpe
    sharpe_ci_high: float = 0.0
    deflated_pass: bool = False      # DSR ≥ 0.95 (true edge after deflation)


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
    stitched_by_result: list[np.ndarray] = []   # parallel to `results`, for DSR/PBO
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
            stitched_by_result.append(stitched.to_numpy(dtype=float))

    _attach_rigor_stats(results, stitched_by_result, bars_year)
    return results


def _attach_rigor_stats(
    results: list[ScanResult], stitched: list[np.ndarray], bars_year: int,
) -> None:
    """Compute PSR / Deflated-Sharpe / PBO / bootstrap-CI for a dataset's combos.

    These are the selection-bias defences: with N combos tried, a high Sharpe is
    only credible if it survives deflation (DSR≥0.95) and the dataset's PBO is low.
    """
    if not results:
        return
    n_trials = len(results)
    per_bar = [sharpe_significance(s, bars_year).sharpe_per_bar for s in stitched]
    sr_var = float(np.var(per_bar, ddof=1)) if n_trials > 1 else 0.0

    # dataset-level PBO across all combos (align to shortest stitched series)
    pbo = float("nan")
    if n_trials >= 2:
        min_len = min(s.size for s in stitched)
        if min_len >= 16:
            matrix = np.column_stack([s[:min_len] for s in stitched])
            pbo = probability_of_backtest_overfitting(matrix).get("pbo", float("nan"))

    for res, series in zip(results, stitched, strict=True):
        sig = sharpe_significance(series, bars_year, n_trials=n_trials, sr_variance=sr_var)
        res.psr = round(sig.psr, 4)
        res.dsr = round(sig.dsr, 4) if np.isfinite(sig.dsr) else float("nan")
        res.pbo = round(pbo, 4) if np.isfinite(pbo) else float("nan")
        res.deflated_pass = bool(np.isfinite(sig.dsr) and sig.dsr >= 0.95)
        if res.passed:
            ci = bootstrap_metric_ci(series, bars_year, n_boot=400)["sharpe"]
            res.sharpe_ci_low = round(ci["low"], 3)
            res.sharpe_ci_high = round(ci["high"], 3)


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

    # ── statistical-rigor summary (selection-bias dashboard) ────────────
    pbos = [r.pbo for r in results if r.pbo == r.pbo]  # drop NaN
    n_deflated = sum(1 for r in survivors if r.deflated_pass)
    rigor = {
        "n_trials": len(results),
        "median_pbo": round(float(pd.Series(pbos).median()), 4) if pbos else None,
        "n_deflated_pass": n_deflated,
        "deflated_frac": round(n_deflated / len(survivors), 3) if survivors else 0.0,
    }

    return {
        "version": 2,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "live_timeframe": live_timeframe,
        "n_scanned": len(results),
        "n_passed": len(survivors),
        "by_timeframe": by_tf,
        "by_symbol": by_symbol,
        "live_plan": live_plan,
        "top": [asdict(r) for r in survivors[:20]],
        "alerts": alerts,
        "rigor": rigor,
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
