"""Trial ledger — the cumulative multiple-testing account ("edge graveyard").

The nightly scan deflates Sharpe by the number of combos tried *tonight*. But
selection bias compounds across nights: re-running a thousand-combo scan every
evening for months means the family of hypotheses ever tried is far larger than
any single run, and the expected maximum lucky Sharpe rises accordingly. The
honest deflation benchmark is the *cumulative unique* trial count — with
re-tests of the same hypothesis counted once (they are the same bet, not new
evidence of breadth).

This module keeps that account in a small SQLite ledger:

  • every scanned hypothesis (dataset × strategy × direction [× params]) is
    upserted once; re-tests bump ``n_runs``/``last_seen`` and refresh its
    latest per-bar Sharpe
  • ``family_stats`` returns the cumulative unique count and the cross-
    hypothesis Sharpe variance — the two inputs Bailey/López-de-Prado
    deflation needs
  • ``deflate`` recomputes DSR against the *cumulative* benchmark, so a
    candidate that looks credible against tonight's 1 000 trials can be seen
    failing against the 10 000 ever tried
  • graveyard views: how many hypotheses ever passed, the daily discovery
    timeline, and the long tail of dead ideas

Wired into ``wf_scan.scan_processed_dir`` (every scan is recorded and each
result gains ``dsr_cum``); usable standalone for any other search family.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from src.analysis.statistics import deflated_sharpe_ratio

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "outputs" / "trial_ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    key_hash    TEXT NOT NULL,
    family      TEXT NOT NULL,
    dataset     TEXT NOT NULL DEFAULT '',
    exchange    TEXT NOT NULL DEFAULT '',
    symbol      TEXT NOT NULL DEFAULT '',
    timeframe   TEXT NOT NULL DEFAULT '',
    strategy    TEXT NOT NULL DEFAULT '',
    direction   TEXT NOT NULL DEFAULT '',
    params      TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    n_runs      INTEGER NOT NULL DEFAULT 1,
    sr_pb       REAL NOT NULL DEFAULT 0.0,
    best_sr_pb  REAL NOT NULL DEFAULT 0.0,
    n_obs       INTEGER NOT NULL DEFAULT 0,
    ever_passed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (family, key_hash)
);
CREATE INDEX IF NOT EXISTS idx_trials_family_seen ON trials (family, first_seen);
"""


def _hypothesis_key(dataset: str, strategy: str, direction: str, params: str = "") -> str:
    raw = f"{dataset}|{strategy}|{direction}|{params}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class TrialLedger:
    def __init__(self, db_path: Path | str = DEFAULT_DB, timeout: float = 30.0) -> None:
        """``timeout`` is how long a call waits for the write lock.

        The default suits the nightly writers, which must not drop trials. A
        reader that is only decorating a dashboard should pass something short
        instead: while ``wf_scan`` holds the lock it would otherwise block for
        the full thirty seconds, which is long enough to hang a page.
        """
        self.db_path = Path(db_path)
        self.timeout = timeout
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=self.timeout)

    # ── recording ───────────────────────────────────────────────────────

    def record_trials(self, family: str, trials: Iterable[dict[str, Any]]) -> int:
        """Upsert scanned hypotheses; returns how many were NEW (first sight).

        Each trial dict: dataset, strategy, direction, sr_pb, n_obs and
        optionally exchange/symbol/timeframe/params/passed.
        """
        now = time.time()
        new = 0
        with self._conn() as con:
            for t in trials:
                params = str(t.get("params") or "")
                key = _hypothesis_key(
                    str(t.get("dataset") or ""), str(t.get("strategy") or ""),
                    str(t.get("direction") or ""), params,
                )
                sr = float(t.get("sr_pb") or 0.0)
                passed = 1 if t.get("passed") else 0
                cur = con.execute(
                    "SELECT n_runs, best_sr_pb, ever_passed FROM trials "
                    "WHERE family=? AND key_hash=?", (family, key),
                ).fetchone()
                if cur is None:
                    con.execute(
                        "INSERT INTO trials (key_hash, family, dataset, exchange, symbol,"
                        " timeframe, strategy, direction, params, first_seen, last_seen,"
                        " n_runs, sr_pb, best_sr_pb, n_obs, ever_passed)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
                        (key, family, str(t.get("dataset") or ""), str(t.get("exchange") or ""),
                         str(t.get("symbol") or ""), str(t.get("timeframe") or ""),
                         str(t.get("strategy") or ""), str(t.get("direction") or ""), params,
                         now, now, sr, sr, int(t.get("n_obs") or 0), passed),
                    )
                    new += 1
                else:
                    n_runs, best_sr, ever = cur
                    con.execute(
                        "UPDATE trials SET last_seen=?, n_runs=?, sr_pb=?, best_sr_pb=?,"
                        " n_obs=?, ever_passed=? WHERE family=? AND key_hash=?",
                        (now, n_runs + 1, sr, max(float(best_sr), sr),
                         int(t.get("n_obs") or 0), max(int(ever), passed), family, key),
                    )
        return new

    # ── the deflation account ───────────────────────────────────────────

    def family_stats(self, family: str) -> dict[str, Any]:
        with self._conn() as con:
            row = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(n_runs),0), MIN(first_seen), MAX(last_seen),"
                " COALESCE(SUM(ever_passed),0) FROM trials WHERE family=?", (family,),
            ).fetchone()
            srs = [r[0] for r in con.execute(
                "SELECT sr_pb FROM trials WHERE family=?", (family,)).fetchall()]
        n_unique, n_runs, first_ts, last_ts, n_ever_passed = row
        sr_var = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
        return {
            "family": family,
            "n_unique": int(n_unique),
            "n_runs_total": int(n_runs),
            "n_ever_passed": int(n_ever_passed),
            "sr_variance": sr_var,
            "first_seen": first_ts,
            "last_seen": last_ts,
        }

    def deflate(
        self, family: str, sr_pb: float, n_obs: int,
        skew: float = 0.0, kurtosis: float = 3.0,
        stats: dict | None = None,
    ) -> float:
        """DSR of one candidate against the family's cumulative unique trials.

        stats: خروجیِ از-پیش-محاسبه‌ی family_stats — برای حلقه‌های بزرگ (اسکنِ
        شبانه ~6.6k نتیجه) پاس بدهید تا per-result دو کوئریِ کاملِ جدول نخورد
        (فیکس 2026-08-08: همین O(N²) بود که deflation را وسطِ کار می‌کشت).
        """
        if stats is None:
            stats = self.family_stats(family)
        if stats["n_unique"] < 2 or stats["sr_variance"] <= 0 or n_obs < 3:
            return float("nan")
        return deflated_sharpe_ratio(
            sr_pb, n_obs, skew, kurtosis, stats["n_unique"], stats["sr_variance"],
        )

    # ── graveyard views ─────────────────────────────────────────────────

    def timeline(self, family: str) -> list[dict[str, Any]]:
        """Per-day count of newly discovered unique hypotheses (cumulative too)."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT DATE(first_seen,'unixepoch') d, COUNT(*) FROM trials"
                " WHERE family=? GROUP BY d ORDER BY d", (family,),
            ).fetchall()
        out, cum = [], 0
        for day, count in rows:
            cum += count
            out.append({"date": day, "new": int(count), "cumulative": cum})
        return out

    def strategy_breakdown(self, family: str, limit: int = 20) -> list[dict[str, Any]]:
        """Which strategies were tried most — and how often they ever passed."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT strategy, COUNT(*), SUM(ever_passed), AVG(sr_pb), MAX(best_sr_pb)"
                " FROM trials WHERE family=? GROUP BY strategy"
                " ORDER BY COUNT(*) DESC LIMIT ?", (family, limit),
            ).fetchall()
        return [
            {"strategy": s, "n_hypotheses": int(n), "n_ever_passed": int(p or 0),
             "pass_rate": round((p or 0) / n, 4) if n else 0.0,
             "avg_sr_pb": round(float(a or 0.0), 5), "best_sr_pb": round(float(b or 0.0), 5)}
            for s, n, p, a, b in rows
        ]


def default_ledger() -> TrialLedger:
    return TrialLedger(DEFAULT_DB)
