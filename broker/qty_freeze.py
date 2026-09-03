"""
Exchange Freeze Quantity Handling
────────────────────────────────────
MCX (like NFO) enforces a maximum order quantity per single order —
"freeze quantity." An order above it is rejected by the exchange; the
correct handling is to split it into multiple orders, each at or below
the cap.

Unlike lot size/strike/expiry, freeze quantity is NOT part of Angel One's
instrument master JSON — it's published separately per exchange circular
and revised periodically. marketcalls/openalgo (a mature, multi-broker
platform with production MCX support) confirms this: their
`database/qty_freeze_db.py` seeds it from an admin-managed CSV, not
derived automatically. This module follows the same shape — a
configurable table, not a live-resolved one — because there is no API
to resolve it from.

**FREEZE_QTY below is NOT seeded with real values.** Populate it from
MCX's published freeze-quantity circular (check mcxindia.com's circulars
section, or your broker's risk/margin page) before trading real size.
Leaving an underlying unconfigured means "unknown" — place_order() logs
a warning and does NOT split (fails open), so an oversized order will
simply be rejected by the exchange rather than silently mis-split.
"""

from __future__ import annotations

from typing import Optional

from utils.logger import get_logger

logger = get_logger("qty_freeze")

# underlying -> max quantity per single order. Empty until populated from a
# real MCX circular — see module docstring.
FREEZE_QTY: dict[str, int] = {}


def get_freeze_qty(underlying: str) -> Optional[int]:
    """None means unconfigured/unknown — caller should fail open, not assume no limit."""
    return FREEZE_QTY.get(underlying.upper())


def split_order_quantity(quantity: int, freeze_qty: Optional[int]) -> list[int]:
    """
    Split `quantity` into chunks each <= freeze_qty (all chunks equal-sized
    where possible, remainder in the last chunk). Returns [quantity]
    unchanged if freeze_qty is None or quantity already fits.
    """
    if not freeze_qty or freeze_qty <= 0 or quantity <= freeze_qty:
        return [quantity]

    chunks = []
    remaining = quantity
    while remaining > 0:
        chunk = min(freeze_qty, remaining)
        chunks.append(chunk)
        remaining -= chunk
    return chunks
