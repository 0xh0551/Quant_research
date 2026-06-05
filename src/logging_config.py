"""Centralized logging configuration for the Quant Research Platform."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONSOLE_FMT = "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s"
_FILE_FMT = "%(asctime)s  %(levelname)-8s  %(name)-30s  %(filename)s:%(lineno)d  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_LEVEL_COLORS = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[35m",  # magenta
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{_RESET}"
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_dir: Path | str | None = None,
) -> Path | None:
    """Configure root logger with console + rotating file handlers.

    Returns the log directory path if file logging is enabled.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any handlers added by earlier calls or by uvicorn/FastAPI
    for h in root.handlers[:]:
        root.removeHandler(h)

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Console handler (colored)
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(_ColorFormatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
    root.addHandler(console)

    if log_dir is None:
        return None

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Main rotating log (10 MB x 5 backups)
    main_file = logging.handlers.RotatingFileHandler(
        log_path / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    main_file.setLevel(logging.DEBUG)
    main_file.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    root.addHandler(main_file)

    # Errors-only log (permanent, no rotation limit)
    error_file = logging.handlers.RotatingFileHandler(
        log_path / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    root.addHandler(error_file)

    # Quiet noisy third-party libraries
    for noisy in ("httpx", "httpcore", "urllib3", "ccxt", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — level=%s  log_dir=%s", level, log_path
    )
    return log_path


def tail_log(log_dir: Path | str, filename: str = "app.log", lines: int = 200) -> list[str]:
    """Return the last `lines` lines from a log file."""
    path = Path(log_dir) / filename
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        return fh.readlines()[-lines:]
