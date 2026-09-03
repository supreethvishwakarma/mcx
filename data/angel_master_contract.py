"""
Angel One Master Contract (MCX)
──────────────────────────────────
Downloads Angel One's instrument master and resolves it into the
`symbol_master` table for CRUDEOIL / SILVER / GOLD options on MCX.

This is the single source of truth for symbol → token, strike, expiry,
lot size and tick size — MCX revises these periodically (lot sizes,
strike intervals, and expiry dates all change), so nothing here is
hardcoded. This mirrors the lesson already learned the hard way in the
NIFTY app: never hardcode expiry / contract specs, always resolve them
from the broker's live instrument master.

The download URL, MCX symbol-construction formula (name + expiry +
strike + CE/PE, strike divided by 100, tick_size divided by 100), and
producttype handling were verified against OpenAlgo's Angel One broker
plugin (github.com/marketcalls/openalgo,
broker/angel/database/master_contract_db.py) — a mature, community
-maintained multi-broker platform that already supports MCX in
production. This is a from-scratch, MIT-license-compatible
reimplementation for this project's own `symbol_master` schema, not a
copy-paste of their code.

Usage:
    python -m data.angel_master_contract          # refresh all 3 commodities
    python -m data.angel_master_contract --underlying CRUDEOIL
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Iterable

import pandas as pd
import requests

from database.db import get_engine
from utils.logger import get_logger

logger = get_logger("angel_master_contract")

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# MCX commodities this project trades options on. Angel One's master
# lists each underlying's name exactly as MCX designates it.
MCX_UNDERLYINGS = ("CRUDEOIL", "SILVER", "GOLD")

# Angel One instrumenttype codes for MCX commodity derivatives.
_MCX_FUT_TYPE = "FUTCOM"
_MCX_OPT_TYPE = "OPTFUT"


def _fetch_raw_master() -> pd.DataFrame:
    logger.info(f"Downloading Angel One instrument master from {SCRIP_MASTER_URL} ...")
    resp = requests.get(SCRIP_MASTER_URL, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    logger.info(f"Downloaded {len(df)} total instruments across all exchanges.")
    return df


def _convert_expiry(date_str: str):
    """Angel's raw expiry strings look like '19SEP2026'."""
    try:
        return datetime.strptime(date_str, "%d%b%Y").date()
    except (ValueError, TypeError):
        return None


def _build_option_symbol(name: str, expiry_compact: str, strike: float, option_type: str) -> str:
    """
    MCX options (OPTFUT) symbol format on Angel One:
        {NAME}{DDMMMYY}{STRIKE}{CE|PE}
    e.g. CRUDEOIL19SEP265800CE
    Strike is formatted without a trailing '.0' for whole numbers.
    """
    strike_str = str(strike)
    if strike_str.endswith(".0"):
        strike_str = strike_str[:-2]
    return f"{name}{expiry_compact}{strike_str}{option_type}"


def _build_future_symbol(name: str, expiry_compact: str) -> str:
    """MCX futures (FUTCOM) symbol format: {NAME}{DDMMMYY}FUT"""
    return f"{name}{expiry_compact}FUT"


def resolve_mcx_symbol_master(underlyings: Iterable[str] = MCX_UNDERLYINGS) -> pd.DataFrame:
    """
    Download and process the Angel One instrument master into rows
    matching this project's `symbol_master` schema, for the given MCX
    underlyings' options (OPTFUT) contracts only (not futures — this
    project trades options, per project scope).
    """
    raw = _fetch_raw_master()

    mcx = raw[(raw["exch_seg"] == "MCX") & (raw["instrumenttype"] == _MCX_OPT_TYPE)].copy()
    mcx = mcx[mcx["name"].isin(underlyings)]

    if mcx.empty:
        logger.warning(
            f"No MCX OPTFUT rows found for {list(underlyings)} — "
            "Angel One may not be listing options on these right now, or the "
            "instrument master's exchange/instrumenttype labels changed."
        )
        return pd.DataFrame(columns=[
            "symbol", "symbol_id", "underlying", "expiry", "strike",
            "option_type", "segment", "lot_size", "tick_size",
        ])

    mcx["expiry_date"] = mcx["expiry"].apply(_convert_expiry)
    mcx = mcx.dropna(subset=["expiry_date"])
    mcx["expiry_compact"] = mcx["expiry_date"].apply(lambda d: d.strftime("%d%b%y").upper())

    # Angel One's raw strike is the real strike × 100; same for tick_size.
    mcx["strike_val"] = mcx["strike"].astype(float) / 100
    mcx["tick_size_val"] = mcx["tick_size"].astype(float) / 100

    # brsymbol (Angel's own symbol string) ends in CE/PE — use that directly
    # rather than re-deriving it, it's already authoritative.
    mcx["option_type"] = mcx["symbol"].str[-2:]
    mcx = mcx[mcx["option_type"].isin(["CE", "PE"])]

    mcx["resolved_symbol"] = mcx.apply(
        lambda row: _build_option_symbol(
            row["name"], row["expiry_compact"], row["strike_val"], row["option_type"]
        ),
        axis=1,
    )

    out = pd.DataFrame({
        "symbol": mcx["resolved_symbol"],
        "symbol_id": pd.to_numeric(mcx["token"], errors="coerce"),
        "underlying": mcx["name"],
        "expiry": mcx["expiry_date"],
        "strike": mcx["strike_val"],
        "option_type": mcx["option_type"],
        "segment": "mcx_fo",
        "lot_size": mcx["lotsize"].astype(int),
        "tick_size": mcx["tick_size_val"],
    })

    out = out.drop_duplicates(subset=["symbol"])
    logger.info(
        f"Resolved {len(out)} MCX option contracts for {list(underlyings)} "
        f"(expiries: {sorted(out['expiry'].unique().tolist())[:5]}...)"
    )
    return out


def refresh_symbol_master(underlyings: Iterable[str] = MCX_UNDERLYINGS) -> int:
    """Resolve the current MCX option chain and upsert it into `symbol_master`."""
    df = resolve_mcx_symbol_master(underlyings)
    if df.empty:
        return 0

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import Table, MetaData

    engine = get_engine()
    meta = MetaData()
    meta.reflect(bind=engine, only=["symbol_master"])
    tbl = meta.tables["symbol_master"]

    rows = df.to_dict(orient="records")
    inserted = 0
    with engine.begin() as conn:
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            stmt = pg_insert(tbl).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "symbol_id": stmt.excluded.symbol_id,
                    "strike": stmt.excluded.strike,
                    "lot_size": stmt.excluded.lot_size,
                    "tick_size": stmt.excluded.tick_size,
                    "updated_at": datetime.now(),
                },
            )
            result = conn.execute(stmt)
            inserted += result.rowcount
    logger.info(f"symbol_master refreshed: {inserted} rows upserted.")
    return inserted


def get_lot_size(underlying: str) -> int:
    """
    Latest known lot size for an underlying, read from symbol_master
    (never hardcoded — MCX revises lot sizes periodically).
    """
    from database.db import read_sql
    df = read_sql(
        "SELECT lot_size FROM symbol_master WHERE underlying = :u "
        "ORDER BY updated_at DESC LIMIT 1",
        {"u": underlying},
    )
    if df.empty:
        raise ValueError(
            f"No symbol_master rows for {underlying} — run "
            f"`python -m data.angel_master_contract` to populate it first."
        )
    return int(df.iloc[0]["lot_size"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--underlying", action="append", help="Repeatable; defaults to all 3")
    args = parser.parse_args()
    refresh_symbol_master(args.underlying or MCX_UNDERLYINGS)
