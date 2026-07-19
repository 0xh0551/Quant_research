"""Close the QR learning loop by *reading* the write-only outcome ledger.

`rotate_bot_pairs.py` appends every rotation decision to
`outputs/selection_performance.jsonl` — selected fitness score vs realised PnL,
per deployed pair, per bot, per run. Until now nothing consumed it: the ±25 %
feedback in `selection_feedback.py` is re-derived from the last-30d sqlite on
every run and never accumulates. This module turns that ledger into three
persistent, actionable artifacts:

  1. `pair_priors.json`      — a time-decayed per-(bot,base) prior of realised
     edge (EWMA over the daily snapshot series). This is the *memory* the
     stateless market-structure fitness never had, plus a bounded `prior_mult`
     that `rotate_bot_pairs` can blend in as a long-horizon complement to the
     ephemeral 30d nudge.
  2. `score_calibration.json`— the honest check: does a higher selected fitness
     score actually predict higher realised edge? Cross-sectional rank-IC per
     bot and pooled. If this is ~0, the fitness formula itself needs work.
  3. `retrain_priority.json` — ranks (bot,base) that are *bleeding live despite a
     good score* (model stale → retrain) vs *low score and bleeding* (drop from
     universe) vs *trust*. This is the missing "attribution → retrain" arc.

Read-only over `outputs/` + bot sqlite; writes only under `outputs/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
LEDGER = OUT / "selection_performance.jsonl"


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #
def load_ledger(path: str | Path = LEDGER) -> pd.DataFrame:
    """One row per (ts, bot, base) exploded from each decision's `deployed` list."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    recs: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        ts = r.get("ts")
        bot = r.get("bot")
        kind = r.get("kind")
        for dep in r.get("deployed") or []:
            rz = dep.get("realized") or {}
            recs.append(
                {
                    "ts": ts,
                    "bot": bot,
                    "kind": kind,
                    "base": dep.get("base"),
                    "selected_score": dep.get("selected_score"),
                    "trades": rz.get("trades"),
                    "win_rate": rz.get("win_rate"),
                    "avg_profit": rz.get("avg_profit"),
                    "total_profit_abs": rz.get("total_profit_abs"),
                }
            )
    df = pd.DataFrame.from_records(recs)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["date"] = df["ts"].dt.date
    for c in ("selected_score", "trades", "win_rate", "avg_profit", "total_profit_abs"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["base", "ts", "avg_profit"])
    # dedup to one (bot, base, day) snapshot — take the last run of the day
    df = df.sort_values("ts").drop_duplicates(subset=["bot", "base", "date"], keep="last")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# calibration — does fitness predict live edge?
# --------------------------------------------------------------------------- #
def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    m = x.notna() & y.notna()
    if m.sum() < 3:
        return None
    xr = x[m].rank(method="average")
    yr = y[m].rank(method="average")
    if xr.nunique() < 2 or yr.nunique() < 2:
        return None
    return float(np.corrcoef(xr, yr)[0, 1])


def score_calibration(df: pd.DataFrame) -> dict:
    """Cross-sectional rank-IC of selected_score vs realised avg_profit.

    For each (bot, day) with >=3 deployed bases, correlate the score the rotation
    picked with the realised per-trade profit. Mean IC > 0 means the fitness
    ranking has live predictive power; ~0 means it doesn't.
    """
    out: dict = {"per_bot": {}, "pooled": {}}
    if df.empty:
        return out
    pooled_ics: list[float] = []
    for bot, g in df.groupby("bot"):
        ics: list[float] = []
        for _, day in g.groupby("date"):
            ic = _spearman(day["selected_score"], day["avg_profit"])
            if ic is not None and not np.isnan(ic):
                ics.append(ic)
        if ics:
            out["per_bot"][bot] = {
                "n_days": len(ics),
                "mean_rank_ic": round(float(np.mean(ics)), 3),
                "median_rank_ic": round(float(np.median(ics)), 3),
                "hit_rate_ic_positive": round(float(np.mean([i > 0 for i in ics])), 3),
            }
            pooled_ics.extend(ics)
    if pooled_ics:
        out["pooled"] = {
            "n_bot_days": len(pooled_ics),
            "mean_rank_ic": round(float(np.mean(pooled_ics)), 3),
            "hit_rate_ic_positive": round(float(np.mean([i > 0 for i in pooled_ics])), 3),
            "verdict": _calib_verdict(float(np.mean(pooled_ics))),
        }
    return out


def _calib_verdict(mean_ic: float) -> str:
    if mean_ic >= 0.15:
        return "fitness ranking has usable live predictive power — trust it more"
    if mean_ic >= 0.05:
        return "weak positive signal — fitness helps but blend heavily with realised prior"
    if mean_ic <= -0.05:
        return "INVERTED — higher fitness score currently predicts WORSE live edge; investigate the formula"
    return "~zero — fitness score does not predict live edge; lean on the realised prior, not raw fitness"


# --------------------------------------------------------------------------- #
# persisted prior — the memory the stateless fitness never had
# --------------------------------------------------------------------------- #
def build_priors(df: pd.DataFrame, half_life_days: float = 14.0, max_adj: float = 0.25,
                 full_scale_avg: float = 0.02) -> dict:
    """Time-decayed realised-edge prior per (bot, base)."""
    priors: dict = {}
    if df.empty:
        return priors
    hl = pd.Timedelta(days=half_life_days)
    for (bot, base), g in df.groupby(["bot", "base"]):
        g = g.sort_values("ts")
        # time-decayed EWMA of realised per-trade profit over the daily snapshots
        ew = g["avg_profit"].ewm(halflife=hl, times=g["ts"]).mean()
        decayed = float(ew.iloc[-1])
        last = g.iloc[-1]
        # bounded multiplier from the DECAYED edge (long memory; complements the
        # ephemeral 30d nudge in selection_feedback)
        adj = max(-max_adj, min(max_adj, (decayed / full_scale_avg) * max_adj))
        priors.setdefault(bot, {})[base] = {
            "decayed_avg_profit": round(decayed, 5),
            "latest_avg_profit": round(float(last["avg_profit"]), 5),
            "latest_win_rate": _f(last["win_rate"]),
            "latest_trades": _i(last["trades"]),
            "latest_selected_score": _i(last["selected_score"]),
            "n_snapshots": int(len(g)),
            "first_seen": str(g.iloc[0]["date"]),
            "last_seen": str(last["date"]),
            "prior_mult": round(1.0 + adj, 4),
        }
    return priors


# --------------------------------------------------------------------------- #
# attribution -> retrain / drop priority
# --------------------------------------------------------------------------- #
def retrain_priority(df: pd.DataFrame, priors: dict, *, min_trades: int = 8,
                     bleed_thresh: float = -0.001) -> list[dict]:
    """Rank (bot,base) by 'bleeding live despite selection'.

    retrain : good score but persistently negative realised edge -> model stale
    drop    : low score AND bleeding -> just exclude from the universe
    trust   : decayed edge positive
    watch   : negative but too few trades / borderline
    """
    if df.empty:
        return []
    # median selected score per bot to define "high score"
    med_score = df.groupby("bot")["selected_score"].median().to_dict()
    items: list[dict] = []
    for bot, bases in priors.items():
        thr = med_score.get(bot, 60)
        for base, p in bases.items():
            decayed = p["decayed_avg_profit"]
            trades = p["latest_trades"] or 0
            score = p["latest_selected_score"] or 0
            if decayed >= 0:
                action, sev = "trust", 0.0
            elif trades < min_trades:
                action, sev = "watch", abs(min(decayed, 0)) * 0.3
            elif decayed <= bleed_thresh and score >= thr:
                action = "retrain"  # score says good, live says bad -> stale model
                sev = abs(decayed) * np.log1p(trades) * 2.0
            elif decayed <= bleed_thresh:
                action = "drop"  # low score and bleeding -> exclude
                sev = abs(decayed) * np.log1p(trades)
            else:
                action, sev = "watch", abs(decayed) * np.log1p(trades) * 0.5
            items.append(
                {
                    "bot": bot,
                    "base": base,
                    "action": action,
                    "priority": round(float(sev), 4),
                    "decayed_avg_profit": decayed,
                    "latest_selected_score": score,
                    "score_vs_median": round(score - thr, 1),
                    "latest_trades": trades,
                    "latest_win_rate": p["latest_win_rate"],
                    "prior_mult": p["prior_mult"],
                }
            )
    items.sort(key=lambda d: d["priority"], reverse=True)
    return items


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
CONFIGS = ROOT / "configs"


def _load_manual_drops() -> dict[str, list[str]]:
    """Owner-curated persistent exclusions: {bot: [base,...]}. Merged into drop_list."""
    p = CONFIGS / "manual_drops.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        return {k: [b.upper() for b in v] for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, list)}
    except Exception:
        return {}


def build_drop_list(prio: list[dict], manual: dict[str, list[str]]) -> dict[str, list[str]]:
    """Bases to EXCLUDE from selection now: learned drops + retrain-flagged (they
    keep bleeding until retrained) + owner-curated manual drops."""
    out: dict[str, set] = {}
    for p in prio:
        if p["action"] in ("drop", "retrain"):
            out.setdefault(p["bot"], set()).add(p["base"])
    for bot, bases in manual.items():
        out.setdefault(bot, set()).update(b.upper() for b in bases)
    return {bot: sorted(bs) for bot, bs in out.items()}


def build_retrain_queue(prio: list[dict]) -> list[dict]:
    """High-score-but-bleeding pairs whose model is stale → queue for retrain,
    ordered by priority. (These are also excluded live via the drop list.)"""
    q = [
        {"bot": p["bot"], "base": p["base"], "priority": p["priority"],
         "decayed_avg_profit": p["decayed_avg_profit"], "latest_selected_score": p["latest_selected_score"],
         "latest_trades": p["latest_trades"]}
        for p in prio if p["action"] == "retrain"
    ]
    return sorted(q, key=lambda d: d["priority"], reverse=True)


def run(half_life_days: float = 14.0, write: bool = True) -> dict:
    df = load_ledger()
    calib = score_calibration(df)
    priors = build_priors(df, half_life_days=half_life_days)
    prio = retrain_priority(df, priors)
    manual = _load_manual_drops()
    drop_list = build_drop_list(prio, manual)
    retrain_queue = build_retrain_queue(prio)
    meta = {
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat() + "Z",
        "ledger_rows": int(len(df)),
        "bots": sorted(df["bot"].unique().tolist()) if not df.empty else [],
        "half_life_days": half_life_days,
    }
    result = {"meta": meta, "calibration": calib, "priors": priors, "retrain_priority": prio,
              "drop_list": drop_list, "retrain_queue": retrain_queue}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "pair_priors.json").write_text(json.dumps({"meta": meta, "priors": priors}, indent=2))
        (OUT / "score_calibration.json").write_text(json.dumps({"meta": meta, "calibration": calib}, indent=2))
        (OUT / "retrain_priority.json").write_text(json.dumps({"meta": meta, "retrain_priority": prio}, indent=2))
        (OUT / "drop_list.json").write_text(json.dumps({"meta": meta, "manual": manual, "bots": drop_list}, indent=2))
        (OUT / "retrain_queue.json").write_text(json.dumps({"meta": meta, "queue": retrain_queue}, indent=2))
    return result


def _f(x):
    try:
        return round(float(x), 3)
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
