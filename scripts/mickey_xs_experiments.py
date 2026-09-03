#!/usr/bin/env python3
"""mickey_xs_experiments.py — گریدِ آزمایشیِ ویژگی/هدف/افق/جهان برای Mickey-XS (۲۰۲۶-۰۹-۰۳).

هر run = همان گیتِ شبانه (run_wf_gate: n_splits=8، میانه روی آفست‌های 0/48/96)،
خروجی در outputs/mickey_xs_experiments/<run>/metrics.json + summary.csv تجمعی.
هیچ‌چیز به outputs/mickey_xs_model.joblib / mickey_xs_gate.json نمی‌نویسد.

مشخصهٔ run: name=features:universe:target:horizon[:groups]
  مثال: xs_all=xs:liquid:raw:24:all   ablate_mom=xs:liquid:raw:24:resid,fund,oi,vol,dist,ta
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mickey_xs_train as T  # noqa: E402
from mickey_xs_features import parse_groups  # noqa: E402

EXP_ROOT = ROOT / "outputs" / "mickey_xs_experiments"
PROMO = {"min_ic": 0.03, "min_sharpe_net": 0.5, "min_cum_net": 0.0}


def parse_spec(spec: str) -> dict:
    name, rest = spec.split("=", 1)
    parts = rest.split(":")
    if len(parts) < 4:
        raise ValueError(f"bad spec {spec!r}")
    features, universe, target, horizon = parts[:4]
    groups = parts[4] if len(parts) > 4 else "all"
    return {"name": name.strip(), "features": features, "universe": universe,
            "target": target, "horizon": int(horizon),
            "groups": list(parse_groups(groups)) if features == "xs" else None}


def promoted(r: dict) -> bool:
    return (r.get("xs_ic_spearman", -1) >= PROMO["min_ic"]
            and r.get("sharpe_net", -9) > PROMO["min_sharpe_net"]
            and r.get("cum_net", -9) > PROMO["min_cum_net"])


def rebuild_summary() -> pd.DataFrame:
    rows = []
    for mf in sorted(EXP_ROOT.glob("*/metrics.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        wf, cfg = m["wf"], m["config"]
        rows.append({
            "run": m["run"], "features": cfg["features"], "universe": cfg["universe"],
            "n_bases": len(m["universe"]), "target": cfg["target"], "horizon": cfg["horizon"],
            "groups": ",".join(cfg["groups"]) if cfg.get("groups") else "",
            "n_feats": wf.get("n_feats"),
            "ic": wf.get("xs_ic_spearman"), "sharpe_gross": wf.get("sharpe_gross"),
            "sharpe_net": wf.get("sharpe_net"), "cum_net": wf.get("cum_net"),
            "turnover": wf.get("avg_turnover"), "hit_rate": wf.get("hit_rate"),
            "n_reb": wf.get("n_rebalances"),
            "ic_off0": wf["offsets"][0]["xs_ic_spearman"], "ic_off48": wf["offsets"][1]["xs_ic_spearman"],
            "ic_off96": wf["offsets"][2]["xs_ic_spearman"],
            "sh_off0": wf["offsets"][0]["sharpe_net"], "sh_off48": wf["offsets"][1]["sharpe_net"],
            "sh_off96": wf["offsets"][2]["sharpe_net"],
            "promote": promoted(wf), "gate_enabled": m.get("gate_enabled"),
            "minutes": m.get("minutes"),
        })
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["sharpe_net"], ascending=False)
        df.to_csv(EXP_ROOT / "summary.csv", index=False)
    return df


def run_one(spec: dict, n_jobs: int, force: bool) -> dict:
    out = EXP_ROOT / spec["name"]
    mf = out / "metrics.json"
    if mf.exists() and not force:
        print(f"[skip] {spec['name']} exists", flush=True)
        return json.loads(mf.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    log = out / "run.log"

    def say(msg: str):
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    bases = T.universe_bases(spec["universe"])
    say(f"== {spec['name']} :: {spec} :: universe n={len(bases)}")
    t0 = time.time()
    r = T.run_wf_gate(bases, features=spec["features"], target=spec["target"],
                      horizon=spec["horizon"], groups=spec["groups"], n_jobs=n_jobs, say=say)
    enabled = r.pop("enabled")
    m = {
        "run": spec["name"], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {k: spec[k] for k in ("features", "universe", "target", "horizon", "groups")},
        "params": {"tf": T.TF, "venue": T.VENUE, "k": T.K, "band": T.BAND, "cost": T.COST,
                   "n_splits": 8, "offsets": list(T.GATE_OFFSETS_BARS)},
        "wf": r, "gate_enabled": bool(enabled), "promote": promoted(r),
        "promotion_criteria": PROMO, "universe": bases,
        "minutes": round((time.time() - t0) / 60.0, 1),
    }
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"== done {spec['name']} in {m['minutes']} min: ic={r['xs_ic_spearman']} "
        f"sh_net={r['sharpe_net']} cum={r['cum_net']} promote={m['promote']}")
    rebuild_summary()
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="name=features:universe:target:horizon[:groups]")
    ap.add_argument("--n-jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    EXP_ROOT.mkdir(parents=True, exist_ok=True)
    for spec in args.runs:
        run_one(parse_spec(spec), args.n_jobs, args.force)
    df = rebuild_summary()
    if len(df):
        print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
