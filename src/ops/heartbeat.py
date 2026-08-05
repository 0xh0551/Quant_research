"""Pipeline heartbeat — did every scheduled job actually run?

A research platform run by cron dies quietly: a wiped crontab, a dead watcher
or a full disk stops a nightly job and nothing complains until someone notices
week-old data. The heartbeat inverts that: every scheduled job must leave a
fresh artifact, and this module audits all of them in one sweep.

Registry: ``configs/pipeline_jobs.json`` (committed, generic platform jobs)
merged with ``heartbeat_jobs`` from the site-local ``configs/local.json``
(same shape; a matching ``name`` overrides, unknown names extend — so a
deployment can register its own cron artifacts without touching the repo).

Each job declares an ``artifact`` (path or glob, relative to the repo root),
``max_age_hours`` and ``severity``. A job is:

  ok       fresh artifact of non-zero size
  late     artifact exists but older than max_age_hours
  missing  artifact absent (or empty)

Every run appends one summary line to ``outputs/pipeline_health_history.jsonl``
so the dashboard can show reliability over time, and the CLI exits non-zero
when any critical job is late/missing — cron-able as its own watchdog:

    python -m src.ops.heartbeat        # audit + write + exit code
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src import local_config

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT / "configs" / "pipeline_jobs.json"
OUTPUT_PATH = ROOT / "outputs" / "pipeline_health.json"
HISTORY_PATH = ROOT / "outputs" / "pipeline_health_history.jsonl"
HISTORY_KEEP = 2000


def load_registry() -> list[dict[str, Any]]:
    """Committed defaults merged with site-local heartbeat_jobs (name-keyed)."""
    jobs: dict[str, dict[str, Any]] = {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for j in data.get("jobs") or []:
            if j.get("name") and j.get("artifact"):
                jobs[str(j["name"])] = dict(j)
    except Exception:
        pass
    for j in local_config._load().get("heartbeat_jobs") or []:
        if isinstance(j, dict) and j.get("name") and j.get("artifact"):
            jobs[str(j["name"])] = {**jobs.get(str(j["name"]), {}), **j}
    return list(jobs.values())


def _resolve_artifact(pattern: str) -> Path | None:
    """Freshest existing match of a path-or-glob (relative to ROOT)."""
    p = Path(pattern)
    if not p.is_absolute():
        p = ROOT / pattern
    if any(ch in pattern for ch in "*?["):
        matches = [m for m in p.parent.glob(p.name) if m.is_file()]
        if not matches:
            return None
        return max(matches, key=lambda m: m.stat().st_mtime)
    return p if p.is_file() else None


def check_job(job: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    artifact = _resolve_artifact(str(job["artifact"]))
    max_age = float(job.get("max_age_hours") or 24.0)
    min_size = int(job.get("min_size_bytes") or 1)
    out: dict[str, Any] = {
        "name": job["name"],
        "artifact": str(job["artifact"]),
        "severity": job.get("severity", "warn"),
        "max_age_hours": max_age,
        "desc_fa": job.get("desc_fa", ""),
        "desc_en": job.get("desc_en", ""),
    }
    if artifact is None:
        out.update(status="missing", age_hours=None, size_bytes=None)
        return out
    st = artifact.stat()
    age_h = (now.timestamp() - st.st_mtime) / 3600.0
    if st.st_size < min_size:
        status = "missing"          # an empty artifact is a failed run, not a run
    elif age_h > max_age:
        status = "late"
    else:
        status = "ok"
    out.update(
        status=status,
        age_hours=round(age_h, 2),
        size_bytes=st.st_size,
        resolved_path=str(artifact.relative_to(ROOT)) if str(artifact).startswith(str(ROOT)) else str(artifact),
    )
    return out


def audit(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    jobs = [check_job(j, now) for j in load_registry()]
    order = {"missing": 0, "late": 1, "ok": 2}
    jobs.sort(key=lambda j: (order.get(j["status"], 3), j["name"]))
    counts = {
        "ok": sum(1 for j in jobs if j["status"] == "ok"),
        "late": sum(1 for j in jobs if j["status"] == "late"),
        "missing": sum(1 for j in jobs if j["status"] == "missing"),
    }
    critical_failing = [
        j["name"] for j in jobs
        if j["severity"] == "critical" and j["status"] != "ok"
    ]
    return {
        "generated_at": now.isoformat(),
        "counts": counts,
        "n_jobs": len(jobs),
        "healthy": not critical_failing and counts["missing"] == 0,
        "critical_failing": critical_failing,
        "jobs": jobs,
    }


def _append_history(report: dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "ts": report["generated_at"],
        **report["counts"],
        "critical_failing": report["critical_failing"],
    }, ensure_ascii=False)
    lines: list[str] = []
    if HISTORY_PATH.exists():
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    lines.append(line)
    HISTORY_PATH.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n", encoding="utf-8")


def read_history(limit: int = 200) -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    out = []
    for ln in HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def write_report(path: Path = OUTPUT_PATH) -> dict[str, Any]:
    report = audit()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_history(report)
    return report


def main() -> None:
    report = write_report()
    c = report["counts"]
    print(f"heartbeat: {c['ok']} ok / {c['late']} late / {c['missing']} missing "
          f"of {report['n_jobs']} jobs")
    for j in report["jobs"]:
        if j["status"] != "ok":
            age = f"{j['age_hours']}h" if j["age_hours"] is not None else "—"
            print(f"  [{j['severity']}] {j['name']:<18} {j['status']:<8} age={age}  ({j['artifact']})")
    raise SystemExit(2 if report["critical_failing"] else (1 if c["missing"] or c["late"] else 0))


if __name__ == "__main__":
    main()
