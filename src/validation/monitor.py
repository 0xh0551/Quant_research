"""Fleet-wide data-quality monitor for the Parquet store.

Runs the existing `DataValidator` across every dataset and rolls the per-file
issues (gaps, duplicates, malformed candles, outliers) into a single summary the
dashboard can surface — so silent data rot (a stalled feed, a venue with holes)
is visible instead of quietly poisoning backtests.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.analysis.cross_exchange import parse_stem
from src.validation.quality import DataValidator


def quality_report(processed_dir: Path, max_files: int | None = None) -> dict:
    items: list[dict] = []
    totals = {"datasets": 0, "with_gaps": 0, "with_dupes": 0, "with_malformed": 0, "clean": 0}
    paths = sorted(Path(processed_dir).glob("*.parquet"))
    if max_files:
        paths = paths[:max_files]
    for path in paths:
        info = parse_stem(path.stem)
        try:
            df = pd.read_parquet(path)
            rep = DataValidator(info["timeframe"]).validate(df)
        except Exception as exc:
            items.append({"file": path.name, **info, "error": str(exc)})
            continue
        by = {iss.name: iss.count for iss in rep.issues}
        gaps = by.get("missing_candles", 0)
        dupes = by.get("duplicate_candles", 0)
        malformed = by.get("malformed_rows", 0)
        outliers = by.get("price_outliers", by.get("outliers", 0))
        clean = (gaps == 0 and dupes == 0 and malformed == 0)
        totals["datasets"] += 1
        totals["with_gaps"] += int(gaps > 0)
        totals["with_dupes"] += int(dupes > 0)
        totals["with_malformed"] += int(malformed > 0)
        totals["clean"] += int(clean)
        coverage_days = 0
        if rep.start is not None and rep.end is not None:
            coverage_days = int((rep.end - rep.start).days)
        items.append({
            "file": path.name, "exchange": info["exchange"], "market": info["market"],
            "symbol": info["symbol"], "timeframe": info["timeframe"], "rows": rep.rows,
            "start": str(rep.start)[:10] if rep.start is not None else "",
            "end": str(rep.end)[:10] if rep.end is not None else "",
            "coverage_days": coverage_days,
            "gaps": gaps, "duplicates": dupes, "malformed": malformed,
            "outliers": outliers, "clean": clean, "passed": rep.passed,
        })
    # worst offenders first
    items.sort(key=lambda d: (d.get("clean", True), -(d.get("gaps", 0) + d.get("malformed", 0) * 5)))
    health = round(totals["clean"] / totals["datasets"] * 100, 1) if totals["datasets"] else 0.0
    return {"totals": totals, "health_pct": health, "items": items}
