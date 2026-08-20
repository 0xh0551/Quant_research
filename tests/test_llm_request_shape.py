"""What we actually send to the API — thinking, effort and the output budget.

These models think adaptively when `thinking` is omitted and bill those tokens as
output, so "no thinking" is a request we have to make explicitly. These tests pin the
request shape, because the cost of getting it wrong is silent and monthly.
"""
from __future__ import annotations

import types
from typing import ClassVar

import pytest
from src.llm import client as llm_client


class _FakeUsage:
    input_tokens = 1000
    output_tokens = 200
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0
    output_tokens_details = types.SimpleNamespace(thinking_tokens=0)


class _FakeResp:
    model = "claude-sonnet-5"
    stop_reason = "end_turn"
    usage = _FakeUsage()
    content: ClassVar[list] = [types.SimpleNamespace(type="text", text='{"ok": true}')]


@pytest.fixture
def llm(tmp_path, monkeypatch):
    """A client that records the request instead of sending it."""
    monkeypatch.setattr(llm_client, "LEDGER_FILE", tmp_path / "calls.jsonl")
    monkeypatch.setattr(llm_client, "SPEND_FILE", tmp_path / "spend.json")
    obj = llm_client.QuantLLM(api_key="test")
    sent: dict = {}

    def _create(**kwargs):
        sent.clear()
        sent.update(kwargs)
        return _FakeResp()

    monkeypatch.setattr(obj, "_c", lambda: types.SimpleNamespace(
        messages=types.SimpleNamespace(create=_create)))
    return obj, sent


def test_thinking_disabled_is_sent_and_drops_the_headroom(llm):
    obj, sent = llm
    obj.complete("hi", tier="smart", max_tokens=1500, thinking="disabled")

    assert sent["thinking"] == {"type": "disabled"}
    # no thinking means no allowance to make room for it
    assert sent["max_tokens"] == 1500


def test_omitting_thinking_keeps_the_headroom(llm):
    """The default must stay as it was: the model may think, so budget for it."""
    obj, sent = llm
    obj.complete("hi", tier="smart", max_tokens=1500)

    assert "thinking" not in sent
    assert sent["max_tokens"] == 1500 + llm_client.THINKING_HEADROOM


def test_effort_rides_in_output_config_next_to_the_schema(llm):
    obj, sent = llm
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    obj.complete("hi", tier="smart", json_schema=schema, effort="low")

    oc = sent["output_config"]
    assert oc["effort"] == "low"
    assert oc["format"]["type"] == "json_schema"      # schema still enforced
    assert oc["format"]["schema"] == schema


def test_thinking_true_still_asks_for_adaptive(llm):
    obj, sent = llm
    obj.complete("hi", tier="smart", thinking=True)
    assert sent["thinking"] == {"type": "adaptive"}


def test_haiku_never_gets_a_thinking_block(llm):
    """Haiku is not a thinking model here; sending the param would be a 400 risk and
    there is no adaptive spend to suppress."""
    obj, sent = llm
    obj.complete("hi", tier="cheap", max_tokens=400, thinking="disabled")
    assert "thinking" not in sent
    assert sent["max_tokens"] == 400
