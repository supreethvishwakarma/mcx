"""
Seed Demo Candles
──────────────────
Populates `minute_candles` with synthetic CRUDEOIL-I data so the dashboard
(charts, regime detection, trade-suggestion scanning) has something to
read before a real TrueData/Angel One feed is connected.

This is for local/demo environments only (e.g. a fresh Codespace with an
empty database) — never run against a production DB that has real data.

Usage:
    python scripts/seed_demo_candles.py [--days N]
"""

import argparse
import sys
from datetime import datetime, timedelta

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from data.mock_data import generate_mock_minute_bars
from database.db import upsert_candles
from utils.helpers import now_ist
from utils.logger import get_logger

logger = get_logger("seed_demo_candles")

SYMBOL = "CRUDEOIL-I"


def _start_of_last_n_weekdays(n: int, end: datetime) -> datetime:
    """The date `n` weekdays before (and including) `end`, at midnight."""
    d = end
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return datetime.combine(d.date(), datetime.min.time())
        d -= timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=15, help="Trading days of history to generate")
    args = parser.parse_args()

    # Land exactly on today (IST) as the last generated day, so the scanner's
    # "latest 300 candles" window is fresh rather than several days stale.
    start_date = _start_of_last_n_weekdays(args.days, now_ist())
    df = generate_mock_minute_bars(symbol=SYMBOL, trading_days=args.days, start_date=start_date)

    inserted = upsert_candles(df, table="minute_candles")
    logger.info(f"Seeded {inserted} demo candles for {SYMBOL} ({args.days} trading days).")
    logger.info("This is SYNTHETIC data for UI testing only — not real market history.")


if __name__ == "__main__":
    main()
