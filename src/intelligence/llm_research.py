"""Claude + web_search research helper shared by the intelligence modules.

Two-step pattern: (1) a web_search-enabled call writes a prose report, (2) a cheap
schema-extraction call turns it into validated JSON. Extracted 2026-09-23 from the
retired incident module; used by src/intelligence/news_direction.py.
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def web_research(llm: Any, prompt: str, schema: dict, *, max_uses: int = 4,
                  tier: str = "cheap", label: str = "research") -> dict | None:
    """Two-step: web_search prose research -> cheap schema extraction (asking for JSON in
    the same call as web_search breaks on <cite> tags). Returns the validated dict or
    None. Budget-gated by the caller."""
    try:
        from src.llm.client import _parse_structured  # noqa: F401 (import check)
    except Exception:
        return None
    try:
        client = llm._c()
        model = llm.model_for(tier)
        resp = client.messages.create(
            model=model, max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
            messages=[{"role": "user", "content": prompt + "\n\nWrite your findings as a "
                       "clear, compact report with headed sections matching the fields you "
                       "will be asked for."}],
        )
        texts, urls, n_search = [], [], 0
        for b in resp.content:
            bt = getattr(b, "type", "")
            if bt == "text":
                texts.append(getattr(b, "text", "") or "")
                for c in (getattr(b, "citations", None) or []):
                    u = getattr(c, "url", None)
                    if u:
                        urls.append(u)
            elif bt == "server_tool_use":
                n_search += 1
        prose = re.sub(r"</?cite[^>]*>", "", "\n".join(texts)).strip()
        with contextlib.suppress(Exception):
            llm.record_web_search(resp.usage, model, n_search)
        if not prose:
            return None
        ext = llm.complete(
            f"Convert this {label} report into the JSON schema exactly. Keep the analyst's "
            "numbers and wording; if the report says it could not search, set "
            "researched=false (when the schema has that field). Add these citation URLs to "
            "sources if the schema has a sources field: " + ", ".join(sorted(set(urls))[:10])
            + "\n\nREPORT:\n" + prose[:9000],
            tier="cheap", json_schema=schema, max_tokens=1200, cache_system=False)
        data = ext.get("data") if isinstance(ext, dict) else None
        if isinstance(data, dict):
            data["_prose"] = prose[:3000]
            data["_n_searches"] = n_search
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("_web_research(%s) failed: %s", label, exc)
        return None
