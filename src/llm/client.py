"""Shared Claude client for the Quant Research platform.

Standalone (no web-framework deps) so QR cron jobs can call Claude without
dragging a web app in. Resolves `ANTHROPIC_API_KEY` from the environment or,
failing that, from the optional `.env` files listed in the site-local config
(`configs/local.json`, gitignored). Fails safe: `is_enabled()` is False when no
key is found, and `complete()` raises a clear error rather than calling with no
auth.

Wraps the three things every QR LLM use needs:
  * tiered models  — cheap=Haiku 4.5, smart=Sonnet 5, reasoning=Opus 4.8
  * prompt caching  — a large stable `system` prefix is cached (reads ~0.1x)
  * structured output — `output_config.format` json_schema -> validated dict
  * Batch API       — 50% cheaper for non-latency-sensitive fan-out (post-mortems)

Model IDs are the current canonical strings; do not append date suffixes.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# canonical current model IDs (no date suffixes)
MODELS = {
    "cheap": "claude-haiku-4-5",
    "smart": "claude-sonnet-5",
    "reasoning": "claude-opus-4-8",
}
# USD per 1M tokens (input, output). Sonnet 5 ships intro pricing through 2026-08-31,
# then reverts to (3.0, 15.0) — see _price_for() for the date-aware switch so the cost
# tracker (and the $5 cap) stay accurate after the intro window ends.
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-4-8": (5.0, 25.0),
}
SONNET_INTRO_END = date(2026, 8, 31)
SONNET_STANDARD = (3.0, 15.0)

# 2026-08-12: Sonnet/Opus emit adaptive `thinking` blocks even when `thinking` is not
# requested, and those tokens are billed against max_tokens BEFORE a single character of
# the answer. A max_tokens sized for the JSON alone therefore returns a JSON string cut
# mid-token -> json.loads fails -> the caller silently degrades. That is exactly how the
# nightly post-mortems shipped `"headline": "synthesis parse error"` to the dashboard
# (800 tokens: 905 wanted for thinking alone) and how the market brief quietly fell back
# to its deterministic text. So max_tokens now means "budget for the answer" and this
# allowance is added on top for models that think.
THINKING_MODELS = {"claude-sonnet-5", "claude-opus-4-8", "claude-opus-5", "claude-fable-5"}
THINKING_HEADROOM = 2048
MAX_OUTPUT_TOKENS = 32000  # ceiling for the truncation retry


def _parse_structured(text: str, stop_reason: str | None) -> tuple[Any | None, str | None]:
    """json.loads with the usual rescues. -> (data, parse_error).

    Structured output normally returns bare JSON, but a fenced block or a stray
    preamble should not cost us the whole answer. A truncated answer is reported as
    such so the caller can retry with a bigger budget instead of guessing.
    """
    if not text:
        return None, ("truncated_before_text" if stop_reason == "max_tokens" else "empty")
    for candidate in (text, _strip_fence(text), _outermost_object(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate), None
        except Exception:
            continue
    return None, ("truncated" if stop_reason == "max_tokens" else "invalid_json")


def _strip_fence(text: str) -> str | None:
    t = text.strip()
    if not t.startswith("```"):
        return None
    body = t.split("\n", 1)[1] if "\n" in t else ""
    return body.rsplit("```", 1)[0].strip() or None


def _outermost_object(text: str) -> str | None:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else None

# Hard monthly spend ceiling — even manual runs cannot exceed this. Enforced as a TRUE
# cap: complete()/batch_submit() pre-reserve each call's worst-case cost via
# budget_ok(est), so spend can never cross MONTHLY_BUDGET_USD (no last-call overshoot).
# Override per-run with QUANT_LLM_MONTHLY_BUDGET.
#
# 2026-08-09: owner set $3-4/mo -> 3.5 (strategist via Batch ~$1.5 + post-mortems ~$1.2
#             + market brief ~$0.3).
# 2026-08-12: owner raised to 5.0. The 3.5 target was written when the strategist brief
#             was weekly; it went daily on 08-09 and the burn rate roughly doubled
#             (July $0.117/day -> August $0.225/day), so 3.5 was going to run out around
#             the 15th and silently mute every LLM feature until the 1st. NOTE 5.0 still
#             does not cover a full month at 0.225/day (~$7 would) — it buys to ~the
#             22nd. Revisit the strategist cadence if the mute recurs.
_ROOT = Path(__file__).resolve().parents[2]
SPEND_FILE = _ROOT / "outputs" / "llm_spend.json"
MONTHLY_BUDGET_USD = float(os.environ.get("QUANT_LLM_MONTHLY_BUDGET", "5.0"))
WEB_SEARCH_USD = 0.01  # ~$10 / 1000 Anthropic web searches

from src import local_config

_ENV_FILES = local_config.env_files()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
_KEY_NAMES = ["ANTHROPIC_API_KEY", "ANTHROPOC_API_LAB"]  # 2nd = legacy alias some site .env files use


def _read_env_key() -> str | None:
    for name in _KEY_NAMES:
        v = os.environ.get(name)
        if v:
            return v
    for envf in _ENV_FILES:
        if not envf.exists():
            continue
        try:
            for line in envf.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, val = line.partition("=")
                if k.strip() in _KEY_NAMES:
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            continue
    return None


class QuantLLM:
    """Thin, quant-tuned wrapper over the Anthropic SDK."""

    def __init__(self, api_key: str | None = None):
        self._key = api_key or _read_env_key()
        self._client = None

    def is_enabled(self) -> bool:
        return bool(self._key)

    def _c(self):
        if self._client is None:
            if not self._key:
                raise RuntimeError(
                    "No ANTHROPIC_API_KEY (env or site-local .env files). LLM features disabled."
                )
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._key)
        return self._client

    @staticmethod
    def model_for(tier: str) -> str:
        return MODELS.get(tier, tier)  # accept a tier alias or a raw model id

    # ------------------------------------------------------------------ #
    # hard monthly budget — guarantees spend stays under MONTHLY_BUDGET_USD
    # ------------------------------------------------------------------ #
    def month_spend(self) -> float:
        try:
            return float(json.loads(SPEND_FILE.read_text()).get(_month_key(), 0.0))
        except Exception:
            return 0.0

    def budget_remaining(self) -> float:
        return round(max(0.0, MONTHLY_BUDGET_USD - self.month_spend()), 4)

    def budget_ok(self, est: float = 0.0) -> bool:
        return (self.month_spend() + est) <= MONTHLY_BUDGET_USD

    def _record_spend(self, usd: float) -> None:
        if not usd or usd <= 0:
            return
        try:
            data = json.loads(SPEND_FILE.read_text()) if SPEND_FILE.exists() else {}
        except Exception:
            data = {}
        mk = _month_key()
        data[mk] = round(float(data.get(mk, 0.0)) + float(usd), 6)
        try:
            SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
            SPEND_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def complete(
        self,
        prompt: str,
        *,
        tier: str = "smart",
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 4096,
        thinking: bool = False,
        cache_system: bool = True,
        thinking_headroom: int | None = None,
        retry_on_truncation: bool = True,
    ) -> dict[str, Any]:
        """One request. Returns {"text", "data"(if json_schema), "usage", "model", "cost_usd"}.

        `system` is sent as a cached block when `cache_system` (reads ~0.1x on
        repeated calls with the same prefix). `json_schema` forces a validated
        JSON object via output_config.format and populates `data`.

        `max_tokens` is the budget for the *answer*. Thinking-capable models spend
        output tokens on `thinking` blocks first (see THINKING_HEADROOM), so an
        extra allowance is added on top automatically; pass `thinking_headroom=0`
        to opt out. On a truncated structured answer the call is retried once with
        a doubled budget (disable with `retry_on_truncation=False`).
        """
        model = self.model_for(tier)
        headroom = thinking_headroom if thinking_headroom is not None else (
            THINKING_HEADROOM if model in THINKING_MODELS else 0)
        budget = max_tokens + headroom
        attempt, out = 0, None
        while True:
            out = self._complete_once(model, prompt, system=system, json_schema=json_schema,
                                      budget=budget, thinking=thinking, tier=tier,
                                      cache_system=cache_system)
            truncated = out.get("stop_reason") == "max_tokens"
            if (out.get("skipped") or not json_schema or out.get("data") is not None
                    or not truncated or not retry_on_truncation or attempt >= 1):
                break
            # The answer was cut mid-JSON — almost always thinking ate the budget.
            attempt += 1
            budget = min(budget * 2, MAX_OUTPUT_TOKENS)
            _log.warning("%s: structured answer truncated (output=%s, thinking=%s); "
                         "retrying with max_tokens=%s", model,
                         out["usage"].get("output"), out["usage"].get("thinking"), budget)
        return out

    def _complete_once(self, model, prompt, *, system, json_schema, budget,
                       thinking, tier, cache_system) -> dict[str, Any]:
        # Pre-reserve this call's WORST-CASE cost so the monthly ceiling is a hard cap
        # (no final-call overshoot): conservatively assume up to 10k input tokens (covers
        # cache-write inflation) + the full output budget at this model's rate.
        pin, pout = self._price_for(model)
        est = (10000 * pin + budget * pout) / 1e6
        if not self.budget_ok(est):
            return {"text": "", "data": None, "model": model, "cost_usd": 0.0,
                    "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
                    "skipped": "monthly_budget_exceeded", "month_spend": self.month_spend(),
                    "budget_remaining": self.budget_remaining()}
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": budget,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            block = {"type": "text", "text": system}
            if cache_system:
                block["cache_control"] = {"type": "ephemeral"}
            kwargs["system"] = [block]
        if json_schema:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        if thinking and tier in ("smart", "reasoning"):
            kwargs["thinking"] = {"type": "adaptive"}

        resp = self._c().messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        details = getattr(resp.usage, "output_tokens_details", None)
        out: dict[str, Any] = {
            "text": text,
            "model": resp.model,
            "stop_reason": getattr(resp, "stop_reason", None),
            "max_tokens": budget,
            "usage": {
                "input": resp.usage.input_tokens,
                "output": resp.usage.output_tokens,
                "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
                "thinking": getattr(details, "thinking_tokens", 0) or 0,
            },
        }
        out["cost_usd"] = self._cost(model, out["usage"])
        self._record_spend(out["cost_usd"])
        if json_schema:
            out["data"], out["parse_error"] = _parse_structured(text, out["stop_reason"])
        return out

    def record_web_search(self, usage, model: str, n_searches: int) -> float:
        """Account for a raw web_search call (tokens + per-search fee) against the budget."""
        u = {"input": getattr(usage, "input_tokens", 0), "output": getattr(usage, "output_tokens", 0),
             "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0}
        cost = self._cost(model, u) + n_searches * WEB_SEARCH_USD
        self._record_spend(cost)
        return cost

    def count_tokens(self, prompt: str, *, tier: str = "smart", system: str | None = None) -> int:
        kwargs: dict[str, Any] = {
            "model": self.model_for(tier),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        return self._c().messages.count_tokens(**kwargs).input_tokens

    # ------------------------------------------------------------------ #
    # Batch API — 50% cheaper for non-latency-sensitive fan-out
    # ------------------------------------------------------------------ #
    def batch_submit(
        self,
        items: list[dict],
        *,
        tier: str = "smart",
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 2048,
        cache_system: bool = True,
        thinking_headroom: int | None = None,
    ) -> str:
        """items = [{"custom_id": str, "prompt": str}, ...] -> batch id.

        A shared `system` (e.g. the post-mortem rubric) is cached across the whole
        batch, so a big fixed prefix is billed once at the cache-write rate.
        `max_tokens` is the answer budget; thinking headroom is added as in complete()
        — a batch cannot be retried cheaply, so getting the budget right matters more.
        """
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        model = self.model_for(tier)
        headroom = thinking_headroom if thinking_headroom is not None else (
            THINKING_HEADROOM if model in THINKING_MODELS else 0)
        max_tokens = max_tokens + headroom
        pin, pout = self._price_for(model)
        est = len(items) * (10000 * pin + max_tokens * pout) / 1e6 * 0.5  # Batch is 50% off
        if not self.budget_ok(est):
            raise RuntimeError(
                f"monthly LLM budget reached (${self.month_spend():.2f}/${MONTHLY_BUDGET_USD}); batch not submitted"
            )
        sysblock = None
        if system:
            b = {"type": "text", "text": system}
            if cache_system:
                b["cache_control"] = {"type": "ephemeral"}
            sysblock = [b]

        reqs = []
        for it in items:
            params: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": it["prompt"]}],
            }
            if sysblock:
                params["system"] = sysblock
            if json_schema:
                params["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
            reqs.append(Request(custom_id=it["custom_id"], params=MessageCreateParamsNonStreaming(**params)))
        return self._c().messages.batches.create(requests=reqs).id

    def batch_status(self, batch_id: str) -> str:
        return self._c().messages.batches.retrieve(batch_id).processing_status

    def batch_results(self, batch_id: str, *, as_json: bool = False) -> dict[str, Any]:
        """{custom_id: text-or-parsed-dict} for succeeded results."""
        out: dict[str, Any] = {}
        batch_cost = 0.0
        for res in self._c().messages.batches.results(batch_id):
            if res.result.type != "succeeded":
                out[res.custom_id] = {"_error": res.result.type}
                continue
            msg = res.result.message
            u = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens,
                 "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
                 "cache_write": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0}
            batch_cost += self._cost(msg.model, u) * 0.5  # Batch API is 50% off
            text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            if as_json:
                data, err = _parse_structured(text, getattr(msg, "stop_reason", None))
                out[res.custom_id] = data if data is not None else {
                    "_parse_error": err, "_text": text[:200]}
            else:
                out[res.custom_id] = text
        self._record_spend(batch_cost)
        return out

    # ------------------------------------------------------------------ #
    @staticmethod
    def _price_for(model: str) -> tuple[float, float]:
        """(input, output) $/1M — date-aware so Sonnet reverts to standard after intro."""
        if model == "claude-sonnet-5" and datetime.now(timezone.utc).date() > SONNET_INTRO_END:
            return SONNET_STANDARD
        if model in PRICES:
            return PRICES[model]
        # فیکس 2026-08-08: API گاهی idِ اسنپ‌شاتِ تاریخ‌دار برمی‌گرداند
        # (claude-sonnet-5-20260203) → قبلاً (0,0) یعنی هزینه‌ی ثبت‌نشده و
        # فرسایشِ بی‌صدای سقفِ بودجه. اول prefix-match، وگرنه گران‌ترین تعرفه.
        for known, price in PRICES.items():
            if model.startswith(known):
                return price
        return max(PRICES.values(), key=lambda p: p[1])

    @staticmethod
    def _cost(model: str, usage: dict) -> float:
        pin, pout = QuantLLM._price_for(model)
        # cache reads ~0.1x input, cache writes ~1.25x input (5-min TTL)
        billed_in = usage["input"] + usage["cache_read"] * 0.1 + usage["cache_write"] * 1.25
        return round((billed_in * pin + usage["output"] * pout) / 1e6, 6)


_singleton: QuantLLM | None = None


def get_llm() -> QuantLLM:
    global _singleton
    if _singleton is None:
        _singleton = QuantLLM()
    return _singleton
