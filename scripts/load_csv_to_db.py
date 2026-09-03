"""
Load Historical CSV Data into TimescaleDB
──────────────────────────────────────────
Reads CSV files from a data directory and bulk-inserts them into the
appropriate hypertables, auto-detecting minute-bar vs. tick shape by
columns present (no fixed filenames — the NIFTY-specific version this
was ported from expected exact names like "nifty_index_1m.csv" and
silently loaded nothing if your files were named differently, e.g.
"crudeoil_1m.csv"). The `symbol` column inside each CSV is read as-is
and written straight through — works for any underlying's symbol
strings without code changes.

Minute bars go through database.db.upsert_candles() (ON CONFLICT DO
NOTHING on symbol+timestamp) — safe to re-run, won't duplicate or crash
on overlapping data. Tick data has no such constraint in schema.sql, so
avoid loading the same tick file twice.

**Existing data is never truncated unless you explicitly pass --truncate.**
The version this was ported from truncated minute_candles AND tick_data
unconditionally whenever either table had any rows — a real risk once
you have live-collected or previously-imported data sitting there.

Usage:
  python scripts/load_csv_to_db.py --dir data/historical
  python scripts/load_csv_to_db.py --dir data/historical --truncate   # wipe first
  python scripts/load_csv_to_db.py --files crude_1m.csv gold_ticks.csv
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import get_engine, init_db, execute_sql, upsert_candles
from utils.logger import get_logger

logger = get_logger("csv_to_db")

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

MINUTE_BAR_COLUMNS = {"open", "high", "low", "close"}
TICK_COLUMNS = {"price"}


def _classify_csv(path: Path) -> str:
    """Return 'minute_bars', 'ticks', or 'unknown' based on the header row."""
    try:
        header = pd.read_csv(path, nrows=0).columns.str.lower().tolist()
    except Exception as e:
        logger.warning(f"  {path.name}: couldn't read header ({e}), skipping")
        return "unknown"
    cols = set(header)
    if MINUTE_BAR_COLUMNS.issubset(cols):
        return "minute_bars"
    if TICK_COLUMNS.issubset(cols):
        return "ticks"
    return "unknown"


def load_minute_bars(engine, csv_path: Path) -> int:
    """Load a 1-min bar CSV into minute_candles via upsert_candles() (safe to re-run)."""
    df = pd.read_csv(csv_path)
    if df.empty:
        logger.warning(f"  {csv_path.name}: empty CSV, skipping")
        return 0

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    if "vwap" not in df.columns:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        cum_tp_vol = (typical * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum().replace(0, np.nan)
        df["vwap"] = cum_tp_vol / cum_vol

    cols = ["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap"]
    if "oi" in df.columns:
        cols.append("oi")

    return upsert_candles(df[cols], table="minute_candles")


def load_tick_data(engine, csv_path: Path) -> int:
    """Load a tick CSV into tick_data. No unique constraint on this table —
    avoid loading the same file twice (it will duplicate rows, not error)."""
    df = pd.read_csv(csv_path)
    if df.empty:
        logger.warning(f"  {csv_path.name}: empty CSV, skipping")
        return 0

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    cols_map = ["timestamp", "symbol", "price", "volume", "oi",
                "bid_price", "ask_price", "bid_qty", "ask_qty"]
    out = pd.DataFrame()
    for col in cols_map:
        out[col] = df[col] if col in df.columns else None

    out.to_sql("tick_data", engine, if_exists="append", index=False,
               method="multi", chunksize=5000)
    return len(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DEFAULT_DATA_DIR,
                         help=f"Directory to scan recursively for CSVs (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--files", nargs="+", type=Path, default=None,
                         help="Explicit list of CSV files instead of scanning --dir")
    parser.add_argument("--truncate", action="store_true",
                         help="Wipe minute_candles and tick_data before loading. "
                              "Without this flag, existing data is left alone and new "
                              "rows are added on top (minute bars upsert safely; avoid "
                              "re-loading the same tick file twice).")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  CSV → TimescaleDB Loader")
    print("=" * 60)

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Database connection verified.")

    init_db()

    with engine.connect() as conn:
        mc_count = conn.execute(text("SELECT COUNT(*) FROM minute_candles")).scalar()
        td_count = conn.execute(text("SELECT COUNT(*) FROM tick_data")).scalar()
    logger.info(f"Current DB state: minute_candles={mc_count:,} rows, tick_data={td_count:,} rows")

    if args.truncate:
        if mc_count > 0 or td_count > 0:
            logger.warning("--truncate passed: wiping minute_candles and tick_data before loading.")
            execute_sql("TRUNCATE minute_candles")
            execute_sql("TRUNCATE tick_data")
    elif mc_count > 0 or td_count > 0:
        logger.info("Existing data found — leaving it in place (pass --truncate to wipe first).")

    if args.files:
        csv_files = [Path(f) for f in args.files]
    else:
        if not args.dir.exists():
            logger.error(f"Data directory does not exist: {args.dir}")
            sys.exit(1)
        csv_files = sorted(args.dir.rglob("*.csv"))
        logger.info(f"Scanning {args.dir} — found {len(csv_files)} CSV file(s).")

    stats = {"minute_bars_loaded": 0, "minute_files": 0, "tick_rows_loaded": 0, "tick_files": 0, "skipped": 0}
    t0 = time.time()

    for f in csv_files:
        kind = _classify_csv(f)
        if kind == "minute_bars":
            n = load_minute_bars(engine, f)
            stats["minute_bars_loaded"] += n
            stats["minute_files"] += 1
            logger.info(f"  {f.name}: {n:,} minute-bar rows")
        elif kind == "ticks":
            n = load_tick_data(engine, f)
            stats["tick_rows_loaded"] += n
            stats["tick_files"] += 1
            logger.info(f"  {f.name}: {n:,} tick rows")
        else:
            logger.warning(f"  {f.name}: columns don't match minute-bar or tick shape, skipping")
            stats["skipped"] += 1

    elapsed = time.time() - t0

    with engine.connect() as conn:
        mc_final = conn.execute(text("SELECT COUNT(*) FROM minute_candles")).scalar()
        td_final = conn.execute(text("SELECT COUNT(*) FROM tick_data")).scalar()
        mc_symbols = conn.execute(text("SELECT COUNT(DISTINCT symbol) FROM minute_candles")).scalar()
        td_symbols = conn.execute(text("SELECT COUNT(DISTINCT symbol) FROM tick_data")).scalar()
        mc_range = conn.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM minute_candles")).fetchone()

    print("\n" + "=" * 60)
    print("  LOAD COMPLETE")
    print("=" * 60)
    print(f"  Time: {elapsed:.1f}s  |  Files skipped (unrecognized shape): {stats['skipped']}")
    print(f"\n  minute_candles:")
    print(f"    Rows: {mc_final:,}  |  Symbols: {mc_symbols}  |  Range: {mc_range[0]} → {mc_range[1]}")
    print(f"    Files loaded: {stats['minute_files']}")
    print(f"\n  tick_data:")
    print(f"    Rows: {td_final:,}  |  Symbols: {td_symbols}")
    print(f"    Files loaded: {stats['tick_files']}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
