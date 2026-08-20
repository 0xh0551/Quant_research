"""Keeps site-local identity out of the public repository.

The platform is deployment-agnostic: it learns which bots exist, where their
databases and configs live, and when each one's current architecture began,
from ``configs/local.json`` — which is gitignored. Nothing tracked should name
an operator's live fleet.

This test deliberately does not contain the names it looks for. It reads them
from the local config at runtime, so the guard itself cannot become the leak,
and skips entirely on a clone that has no site config (CI, a fresh checkout).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src import local_config

ROOT = Path(__file__).resolve().parents[1]
# Text files only; a bot name cannot hide in a screenshot's pixels.
_BINARY = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".parquet", ".db",
           ".joblib", ".pyc", ".lock", ".gz", ".zip"}


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    return [ROOT / f for f in out
            if f and (ROOT / f).is_file() and (ROOT / f).suffix.lower() not in _BINARY]


def _site_names() -> list[str]:
    """Every identifier the site config knows a live bot by."""
    names = set(local_config.bot_databases())
    names |= set(local_config.bot_epochs())
    for db in local_config.bot_databases().values():
        names.add(db.stem)                       # the on-disk short form too
    return sorted(n for n in names if len(n) > 3)


@pytest.mark.skipif(not _site_names(), reason="no site config — nothing to check against")
def test_no_tracked_file_names_a_live_bot():
    names = _site_names()
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b",
                         re.IGNORECASE)
    hits: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}")
    assert not hits, (
        "tracked files name a live bot — move the identifier into "
        f"configs/local.json instead:\n  " + "\n  ".join(hits[:20])
    )
