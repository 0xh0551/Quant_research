"""Execution-quality analytics for live freqtrade bots.

Read-only over each bot's freqtrade sqlite (`trades` + `orders` tables). Quantifies
the P&L that leaks to *execution* rather than to a lack of alpha: per-fill and
per-trade slippage, taker/maker mix, fill latency, and limit-order non-fill rate.

Nothing here writes to a bot DB or config.
"""

from .slippage import (  # noqa: F401
    BOTS,
    USER_DATA,
    load_orders,
    load_trades,
    bot_execution_summary,
    fleet_report,
)
