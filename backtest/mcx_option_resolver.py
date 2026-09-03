"""
MCX Option Contract Resolver
──────────────────────────────
Resolves CRUDEOIL/SILVER/GOLD option contracts for a given underlying
price and timestamp. Replaces the NIFTY app's option_resolver.py, which
assumed a single underlying with a fixed ₹50 strike gap and NSE's weekly
Tuesday-ish expiry — none of which hold for MCX commodities (each has
its own strike interval, and MCX options expire monthly on dates that
vary per commodity and change when the exchange revises the calendar).

Everything here resolves against the `symbol_master` table, which
data/angel_master_contract.py populates from Angel One's live
instrument master. There is no hardcoded expiry, strike gap, or symbol
format — populate symbol_master first:

    python -m data.angel_master_contract

MCX options are physically/deliverable settled near expiry (unlike
NIFTY's cash-settled index options) — see get_days_to_expiry() callers
for the safety cutoff this implies.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from database.db import read_sql
from utils.logger import get_logger

logger = get_logger("mcx_option_resolver")

_OPTION_PREMIUM_CACHE: dict = {}


def get_nearest_expiry(underlying: str, ref_date: date) -> Optional[date]:
    """Nearest MCX expiry on or after ref_date, from the live instrument master."""
    df = read_sql(
        "SELECT DISTINCT expiry FROM symbol_master "
        "WHERE underlying = :u AND expiry >= :d ORDER BY expiry ASC LIMIT 1",
        {"u": underlying, "d": str(ref_date)},
    )
    if df.empty:
        logger.warning(
            f"No expiry found for {underlying} >= {ref_date} — symbol_master may be "
            f"stale or empty. Run: python -m data.angel_master_contract"
        )
        return None
    return pd.to_datetime(df.iloc[0]["expiry"]).date()


def get_available_strikes(underlying: str, expiry: date) -> list[float]:
    """All strikes Angel One actually lists for this underlying+expiry."""
    df = read_sql(
        "SELECT DISTINCT strike FROM symbol_master "
        "WHERE underlying = :u AND expiry = :e ORDER BY strike ASC",
        {"u": underlying, "e": str(expiry)},
    )
    return df["strike"].tolist()


def get_atm_strike(underlying: str, expiry: date, price: float) -> Optional[float]:
    """Nearest listed strike to `price` — never assumes a fixed strike gap."""
    strikes = get_available_strikes(underlying, expiry)
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - price))


def build_option_symbol(underlying: str, expiry: date, strike: float, opt_type: str) -> Optional[str]:
    """
    Look up the exact Angel One trading symbol from symbol_master rather
    than re-deriving the string a second time — symbol_master already
    holds Angel's authoritative format for this contract.
    """
    df = read_sql(
        "SELECT symbol FROM symbol_master WHERE underlying = :u AND expiry = :e "
        "AND strike = :s AND option_type = :ot LIMIT 1",
        {"u": underlying, "e": str(expiry), "s": strike, "ot": opt_type},
    )
    if df.empty:
        return None
    return df.iloc[0]["symbol"]


def get_days_to_expiry(ref_date: date, expiry: date) -> int:
    """Calendar days to expiry (MCX trades through weekends' worth of calendar,
    but the session itself is Mon-Fri like NSE)."""
    return max(0, (expiry - ref_date).days)


def is_within_physical_settlement_window(ref_date: date, expiry: date, cutoff_days: int = 3) -> bool:
    """
    MCX commodity options are deliverable — holding into the last few
    sessions before expiry risks physical settlement (a real commodity
    delivery obligation, not a cash settlement like NIFTY). Order
    manager / risk layer should refuse new entries and force-close
    existing positions once this returns True.
    """
    return get_days_to_expiry(ref_date, expiry) <= cutoff_days


def load_option_premiums_for_day(symbol: str, trading_date: date) -> pd.DataFrame:
    """
    Load option premium data for a single day — tick data first, falling
    back to 1-min candles. Same contract as the NIFTY app's version:
    `df.attrs["_mode"]` is "tick" or "candle".
    """
    cache_key = (symbol, str(trading_date))
    if cache_key in _OPTION_PREMIUM_CACHE:
        return _OPTION_PREMIUM_CACHE[cache_key]

    tick_df = read_sql(
        "SELECT timestamp, price as premium, bid_price as bid, ask_price as ask "
        "FROM tick_data WHERE symbol = :sym AND timestamp::date = :dt ORDER BY timestamp",
        {"sym": symbol, "dt": str(trading_date)},
    )
    if not tick_df.empty and len(tick_df) >= 50:
        tick_df["timestamp"] = pd.to_datetime(tick_df["timestamp"])
        tick_df["bid"] = tick_df["bid"].where(tick_df["bid"] > 0, tick_df["premium"])
        tick_df["ask"] = tick_df["ask"].where(tick_df["ask"] > 0, tick_df["premium"])
        tick_df.attrs["_mode"] = "tick"
        _OPTION_PREMIUM_CACHE[cache_key] = tick_df
        return tick_df

    df = read_sql(
        "SELECT timestamp, open, high, low, close as premium, volume, oi "
        "FROM minute_candles WHERE symbol = :sym AND timestamp::date = :dt ORDER BY timestamp",
        {"sym": symbol, "dt": str(trading_date)},
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.attrs["_mode"] = "candle"
    _OPTION_PREMIUM_CACHE[cache_key] = df
    return df


def resolve_option_at_entry(
    underlying: str,
    price: float,
    timestamp: pd.Timestamp,
    direction: str,
) -> Optional[dict]:
    """
    Resolve the ATM option contract at trade entry for a commodity.
    Returns dict with symbol, expiry, strike, entry_premium, dte, premium_df.
    """
    ref_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
    expiry = get_nearest_expiry(underlying, ref_date)
    if expiry is None:
        return None

    opt_type = "CE" if direction == "CALL" else "PE"
    strikes = get_available_strikes(underlying, expiry)
    if not strikes:
        return None

    # Try nearest strike, then walk outward through listed strikes by distance.
    strikes_by_distance = sorted(strikes, key=lambda s: abs(s - price))
    premium_df = pd.DataFrame()
    actual_strike = None
    for strike in strikes_by_distance[:21]:
        symbol = build_option_symbol(underlying, expiry, strike, opt_type)
        if not symbol:
            continue
        pdf = load_option_premiums_for_day(symbol, ref_date)
        if not pdf.empty:
            premium_df = pdf
            actual_strike = strike
            break

    if premium_df.empty or actual_strike is None:
        return None

    symbol = build_option_symbol(underlying, expiry, actual_strike, opt_type)
    ts = pd.to_datetime(timestamp)
    mask = (premium_df["timestamp"] - ts).abs() <= pd.Timedelta(minutes=1)
    matching = premium_df[mask]
    if matching.empty:
        return None

    return {
        "symbol": symbol,
        "underlying": underlying,
        "expiry": expiry,
        "strike": actual_strike,
        "opt_type": opt_type,
        "entry_premium": float(matching.iloc[0]["premium"]),
        "dte": get_days_to_expiry(ref_date, expiry),
        "premium_df": premium_df,
    }


def clear_cache():
    global _OPTION_PREMIUM_CACHE
    _OPTION_PREMIUM_CACHE = {}
