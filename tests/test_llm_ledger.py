"""The per-call ledger must be complete, cheap and unable to break a call."""
from __future__ import annotations

import json

from src.llm import client as llm_client


def _ledger_rows(path):
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_record_call_writes_one_row(tmp_path, monkeypatch):
    led = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "LEDGER_FILE", led)

    llm_client.QuantLLM._record_call(
        mode="sync", model="claude-sonnet-5", tier="smart", cost=0.0271,
        usage={"input": 3300, "output": 2050, "thinking": 900,
               "cache_read": 0, "cache_write": 300},
        max_tokens=3548, stop_reason="end_turn")

    rows = _ledger_rows(led)
    assert len(rows) == 1
    r = rows[0]
    assert r["mode"] == "sync" and r["model"] == "claude-sonnet-5"
    assert r["in"] == 3300 and r["out"] == 2050 and r["thinking"] == 900
    assert r["cost_usd"] == 0.0271
    assert r["stop_reason"] == "end_turn"
    assert r["ts"] and r["site"]  # attribution is automatic, never left blank


def test_skipped_calls_are_logged_too(tmp_path, monkeypatch):
    """A call refused by the budget cap is the thing most likely to be mistaken for a
    bug, so it has to leave a trace."""
    led = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "LEDGER_FILE", led)

    llm_client.QuantLLM._record_call(mode="sync", model="claude-sonnet-5", tier="smart", cost=0.0,
                            skipped="monthly_budget_exceeded", est_usd=0.05)

    r = _ledger_rows(led)[0]
    assert r["skipped"] == "monthly_budget_exceeded"
    assert r["cost_usd"] == 0.0 and r["est_usd"] == 0.05


def test_ledger_rotates_and_never_raises(tmp_path, monkeypatch):
    led = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "LEDGER_FILE", led)
    monkeypatch.setattr(llm_client, "LEDGER_MAX_BYTES", 200)

    for i in range(20):
        llm_client.QuantLLM._record_call(mode="sync", model="m", tier="cheap", cost=0.001,
                                usage={"input": i, "output": i})

    assert led.with_suffix(".jsonl.1").exists()   # rolled over, nothing lost silently
    assert _ledger_rows(led)                      # and the live file keeps taking writes

    # an unwritable path must be swallowed: accounting never takes the call down
    monkeypatch.setattr(llm_client, "LEDGER_FILE", tmp_path / "no-such-dir" / "x" / "l.jsonl")
    monkeypatch.setattr(llm_client.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    llm_client.QuantLLM._record_call(mode="sync", model="m", tier="cheap", cost=0.1)
