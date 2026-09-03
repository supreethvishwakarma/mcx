"""
Utility Helpers
───────────────
Common utility functions used across the system.
"""

from datetime import datetime, timedelta, timezone, time as dt_time

from config.settings import (
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
)

_IST_OFFSET = timedelta(hours=5, minutes=30)


def now_ist() -> datetime:
    """
    Current IST time, as a naive datetime.

    The rest of this codebase treats `datetime.now()` as if it were already
    IST (per CLAUDE.md: "Python uses naive local IST for comparisons"), which
    only holds on a machine whose system clock is set to IST. On a cloud
    container (Codespaces, most PaaS hosts) the system clock is UTC, which
    silently shifts every market-hours check by 5:30 — this converts
    explicitly instead of trusting the host's local time.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None) + _IST_OFFSET


def is_market_open(now: datetime = None) -> bool:
    """Check if NSE market is currently open (9:15 AM – 3:30 PM IST, Mon–Fri)."""
    now = now or now_ist()

    # Weekend check
    if now.weekday() >= 5:
        return False

    market_open = dt_time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = dt_time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)

    return market_open <= now.time() <= market_close


def round_to_tick(price: float, tick_size: float = 0.05) -> float:
    """Round price to nearest tick size (NSE options tick = 0.05)."""
    return round(round(price / tick_size) * tick_size, 2)


def calculate_stop_loss(entry: float, atr: float, multiplier: float = 1.5) -> float:
    """Calculate stop loss based on ATR."""
    return round(entry - (atr * multiplier), 2)


def calculate_target(entry: float, atr: float, multiplier: float = 2.0) -> float:
    """Calculate target based on ATR (risk-reward)."""
    return round(entry + (atr * multiplier), 2)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division with zero-safety."""
    if denominator == 0 or denominator is None:
        return default
    return numerator / denominator