"""Site-local deployment configuration (optional).

The open-source platform is deployment-agnostic: it does not know which live
bots exist, where their freqtrade databases live, or where API keys are kept.
Operators who wire the platform to a live fleet describe their site in
``configs/local.json`` (gitignored), e.g.::

    {
      "user_data": "/path/to/freqtrade/user_data",
      "bot_dbs": {"MyBot": "mybot.sqlite"},
      "env_files": ["/path/to/.env"]
    }

Every accessor degrades gracefully when the file (or a key) is absent, so the
research/backtest/dashboard stack runs fine without any local config.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_JSON = _ROOT / "configs" / "local.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    path = Path(os.environ.get("QR_LOCAL_CONFIG", _LOCAL_JSON))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def user_data_dir() -> Path | None:
    """The live bots' freqtrade ``user_data`` dir, or None when not configured."""
    raw = _load().get("user_data")
    return Path(raw) if raw else None


def bot_databases() -> dict[str, Path]:
    """Mapping of bot name -> absolute path to its freqtrade sqlite DB."""
    ud = user_data_dir()
    out: dict[str, Path] = {}
    for name, db in (_load().get("bot_dbs") or {}).items():
        p = Path(db)
        if not p.is_absolute() and ud is not None:
            p = ud / p
        out[str(name)] = p
    return out


def bridge_bot_databases() -> dict[str, Path]:
    """Subset of :func:`bot_databases` that trade walk-forward bridge edges.

    Used by forward-test attribution so realized PnL is only compared against
    bots that actually execute the scanned edges.
    """
    names = {str(n) for n in (_load().get("bridge_bots") or [])}
    return {n: p for n, p in bot_databases().items() if n in names}


def env_files() -> list[Path]:
    """Optional .env files to scan for API keys (e.g. ANTHROPIC_API_KEY)."""
    return [Path(p) for p in (_load().get("env_files") or [])]
