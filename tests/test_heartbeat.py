from __future__ import annotations

import time
from datetime import UTC, datetime

from src.ops import heartbeat


def test_check_job_ok(tmp_path):
    art = tmp_path / "fresh.json"
    art.write_text("{}")
    job = {"name": "j", "artifact": str(art), "max_age_hours": 1, "severity": "critical"}
    out = heartbeat.check_job(job)
    assert out["status"] == "ok"
    assert out["age_hours"] < 1


def test_check_job_late(tmp_path):
    art = tmp_path / "old.json"
    art.write_text("{}")
    two_hours_ago = time.time() - 2 * 3600
    import os
    os.utime(art, (two_hours_ago, two_hours_ago))
    job = {"name": "j", "artifact": str(art), "max_age_hours": 1, "severity": "warn"}
    assert heartbeat.check_job(job)["status"] == "late"


def test_check_job_missing_and_empty(tmp_path):
    job = {"name": "j", "artifact": str(tmp_path / "nope.json"), "max_age_hours": 1}
    assert heartbeat.check_job(job)["status"] == "missing"
    empty = tmp_path / "empty.json"
    empty.write_text("")
    job2 = {"name": "j2", "artifact": str(empty), "max_age_hours": 1}
    # an empty artifact is a failed run, not a run
    assert heartbeat.check_job(job2)["status"] == "missing"


def test_check_job_glob_picks_freshest(tmp_path):
    old = tmp_path / "a_1.parquet"
    new = tmp_path / "a_2.parquet"
    old.write_text("x")
    new.write_text("y")
    import os
    os.utime(old, (time.time() - 9000, time.time() - 9000))
    job = {"name": "g", "artifact": str(tmp_path / "a_*.parquet"), "max_age_hours": 1}
    out = heartbeat.check_job(job, datetime.now(UTC))
    assert out["status"] == "ok"          # freshest match wins


def test_audit_flags_critical():
    report = heartbeat.audit()
    assert "counts" in report and "jobs" in report
    # healthy is false iff a critical job is not ok or something is missing
    crit_bad = any(j["severity"] == "critical" and j["status"] != "ok" for j in report["jobs"])
    missing = report["counts"]["missing"] > 0
    assert report["healthy"] == (not crit_bad and not missing)
