"""
Signal Generator
────────────────
Strategies 1-3 are inherited from the sibling NIFTY project (Product Vision
doc §9) and apply to any underlying — thresholds were tuned on NIFTY index
options and are NOT recalibrated for commodities (see CLAUDE.md):

  1. VWAP Momentum Breakout  – bullish breakout (Buy ATM Call)
  2. Bearish Momentum        – bearish breakdown (Buy ATM Put)
  3. Mean Reversion          – extreme RSI / Bollinger touch

Strategies 4-5 are new, commodity-specific, and NOT inherited from NIFTY —
built from web research on crude oil / precious metals trading behavior
(see commit message for sources), and UNBACKTESTED (no real MCX historical
data exists yet — see CLAUDE.md's "not yet wired" list). Treat both as
hypotheses to validate once real data is available, not verified defaults:

  4. Crude Inventory Volatility Breakout – CRUDEOIL only, EIA report window
  5. Precious Metals Trend Momentum      – GOLD/SILVER, multi-bar trend continuation

Each strategy returns a Signal dict or None.
The regime detector determines which strategies are active per scan cycle.
"""

from dataclasses import dataclass
from datetime import time as dt_time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import get_logger

logger = get_logger("signal_generator")


@dataclass
class Signal:
    """Represents a raw trading signal before ML filtering."""
    strategy: str
    direction: str          # "CALL" or "PUT"
    symbol: str
    entry_price: float
    technical_strength: float   # 0.0 – 1.0, used in final trade score
    details: Dict


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 1: VWAP Momentum Breakout
# ═══════════════════════════════════════════════════════════════════════════════


def vwap_momentum_breakout(row: dict, symbol: str = "") -> Optional[Signal]:
    """
    Entry conditions (from docs):
      - price > VWAP
      - RSI > 55
      - volume spike
      - EMA20 > EMA50

    Trade: Buy ATM Call
    """
    required = ["close", "vwap", "rsi", "ema20", "ema50"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    conditions = {
        "price_above_vwap": row["close"] > row.get("vwap", 0),
        "rsi_above_55": row["rsi"] > 55,
        "ema20_above_ema50": row["ema20"] > row["ema50"],
        "volume_spike": row.get("volume_spike", 0) == 1 or row.get("volume_ratio", 0) > 1.5,
    }

    met = sum(conditions.values())
    # Require at least 3 of 4 conditions (flexible for real markets)
    if met >= 3:
        strength = met / len(conditions)
        return Signal(
            strategy="vwap_momentum_breakout",
            direction="CALL",
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 2: Bearish Momentum
# ═══════════════════════════════════════════════════════════════════════════════


def bearish_momentum(row: dict, symbol: str = "") -> Optional[Signal]:
    """
    Entry conditions (from docs):
      - price < VWAP
      - RSI < 45
      - EMA20 < EMA50
      - volume spike

    Trade: Buy ATM Put
    """
    required = ["close", "vwap", "rsi", "ema20", "ema50"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    conditions = {
        "price_below_vwap": row["close"] < row.get("vwap", float("inf")),
        "rsi_below_45": row["rsi"] < 45,
        "ema20_below_ema50": row["ema20"] < row["ema50"],
        "volume_spike": row.get("volume_spike", 0) == 1 or row.get("volume_ratio", 0) > 1.5,
    }

    met = sum(conditions.values())
    if met >= 3:
        strength = met / len(conditions)
        return Signal(
            strategy="bearish_momentum",
            direction="PUT",
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 3: Mean Reversion
# ═══════════════════════════════════════════════════════════════════════════════


def mean_reversion(row: dict, symbol: str = "") -> Optional[Signal]:
    """
    Entry conditions (from docs):
      - RSI extreme (oversold < 30 or overbought > 70)
      - price far from VWAP
      - Bollinger band touch

    Trade: Counter-trend
      - RSI < 30 → Buy CALL (expect bounce)
      - RSI > 70 → Buy PUT (expect pullback)
    """
    required = ["close", "rsi"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    is_oversold = row["rsi"] < 30
    is_overbought = row["rsi"] > 70

    if not (is_oversold or is_overbought):
        return None

    # Check Bollinger band touch
    bb_lower = row.get("bollinger_lower")
    bb_upper = row.get("bollinger_upper")
    vwap_dist = abs(row.get("vwap_dist", 0))

    conditions = {}

    if is_oversold:
        conditions["rsi_extreme"] = True
        conditions["near_bb_lower"] = (
            bb_lower is not None and row["close"] <= bb_lower * 1.002
        )
        conditions["far_from_vwap"] = vwap_dist > 0.003
        direction = "CALL"
    else:
        conditions["rsi_extreme"] = True
        conditions["near_bb_upper"] = (
            bb_upper is not None and row["close"] >= bb_upper * 0.998
        )
        conditions["far_from_vwap"] = vwap_dist > 0.003
        direction = "PUT"

    met = sum(conditions.values())
    if met >= 2:
        strength = met / len(conditions)
        return Signal(
            strategy="mean_reversion",
            direction=direction,
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 4: Crude Inventory Volatility Breakout (CRUDEOIL only)
# ═══════════════════════════════════════════════════════════════════════════════

# EIA Weekly Petroleum Status Report releases Wed 10:30 AM ET, which is
# ~20:00-21:00 IST depending on US DST (EST vs EDT) — falls inside MCX's
# 9:00 AM-11:30 PM session. Widened to a window since the exact IST time
# shifts twice a year and this hasn't been verified against a live report
# release. Crude oil "trends hard, reverses hard" around this event and
# the initial move tends to overshoot then revert quickly (see commit
# message for sources) — this strategy is deliberately NOT a
# CONTINUATION_STRATEGIES-style hold; pair it with a tight/fast exit in
# risk_profiles, not a wide trailing stop.
_EIA_WINDOW_START = dt_time(19, 45)
_EIA_WINDOW_END = dt_time(21, 30)


def crude_inventory_volatility_breakout(row: dict, symbol: str = "") -> Optional[Signal]:
    """
    CRUDEOIL-only. Entry conditions:
      - Wednesday, within the EIA inventory report window (IST, DST-widened)
      - A volatility/volume spike just occurred (the report moved the market)
      - Price breaking the recent range in one direction

    Trade: direction follows the breakout (Buy Call on upside break, Buy Put
    on downside break). UNBACKTESTED — see module docstring.
    """
    if "CRUDEOIL" not in symbol.upper():
        return None

    required = ["close", "atr", "volume_ratio", "roc_10", "timestamp"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    ts = row["timestamp"]
    if not isinstance(ts, (pd.Timestamp,)):
        try:
            ts = pd.Timestamp(ts)
        except (TypeError, ValueError):
            return None

    in_window = ts.weekday() == 2 and _EIA_WINDOW_START <= ts.time() <= _EIA_WINDOW_END
    if not in_window:
        return None

    conditions = {
        "in_eia_window": True,
        "volatility_spike": row.get("vol_regime") == "HIGH" or row.get("volume_ratio", 0) > 2.0,
        "volume_spike": row.get("volume_spike", 0) == 1 or row.get("volume_ratio", 0) > 2.0,
        "directional_momentum": abs(row.get("roc_10", 0)) > 0.3,
    }

    met = sum(conditions.values())
    if met >= 3:
        direction = "CALL" if row.get("roc_10", 0) > 0 else "PUT"
        strength = met / len(conditions)
        return Signal(
            strategy="crude_inventory_volatility_breakout",
            direction=direction,
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 5: Precious Metals Trend Momentum (GOLD/SILVER only)
# ═══════════════════════════════════════════════════════════════════════════════


def precious_metals_trend_momentum(row: dict, symbol: str = "") -> Optional[Signal]:
    """
    GOLD/SILVER only. Entry conditions (multi-bar trend continuation, not a
    single-bar breakout — precious metals trend persistently once started,
    per research on CTA/trend-following performance in gold/silver):
      - EMA9 > EMA20 > EMA50 (or the inverse for downtrend) — established trend
      - ROC(20) confirms sustained momentum in the trend direction
      - ADX above 20 (trend strength, not chop)

    Trade: direction follows the established trend. UNBACKTESTED — see
    module docstring.
    """
    upper = symbol.upper()
    if "GOLD" not in upper and "SILVER" not in upper:
        return None

    required = ["close", "ema9", "ema20", "ema50", "roc_20", "adx"]
    if not all(k in row and row[k] is not None for k in required):
        return None

    uptrend = row["ema9"] > row["ema20"] > row["ema50"]
    downtrend = row["ema9"] < row["ema20"] < row["ema50"]
    if not (uptrend or downtrend):
        return None

    trending = row.get("adx", 0) > 20
    if uptrend:
        conditions = {
            "established_uptrend": True,
            "momentum_confirms": row.get("roc_20", 0) > 0.2,
            "trend_strength": trending,
        }
        direction = "CALL"
    else:
        conditions = {
            "established_downtrend": True,
            "momentum_confirms": row.get("roc_20", 0) < -0.2,
            "trend_strength": trending,
        }
        direction = "PUT"

    met = sum(conditions.values())
    if met >= 2:
        strength = met / len(conditions)
        return Signal(
            strategy="precious_metals_trend_momentum",
            direction=direction,
            symbol=symbol,
            entry_price=row["close"],
            technical_strength=round(strength, 2),
            details=conditions,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_MAP = {
    "vwap_momentum_breakout": vwap_momentum_breakout,
    "bearish_momentum": bearish_momentum,
    "mean_reversion": mean_reversion,
    "crude_inventory_volatility_breakout": crude_inventory_volatility_breakout,
    "precious_metals_trend_momentum": precious_metals_trend_momentum,
}


def generate_signals(
    row: dict,
    symbol: str = "",
    active_strategies: List[str] = None,
) -> List[Signal]:
    """
    Run all active strategies on the latest feature row.
    Returns list of Signal objects (may be empty).
    """
    if active_strategies is None:
        active_strategies = list(STRATEGY_MAP.keys())

    signals = []
    for name in active_strategies:
        func = STRATEGY_MAP.get(name)
        if func is None:
            continue
        sig = func(row, symbol)
        if sig is not None:
            signals.append(sig)
            logger.info(
                f"Signal: {name} → {sig.direction} for {symbol} "
                f"(strength={sig.technical_strength})"
            )

    return signals


def generate_signal(row: dict) -> Optional[str]:
    """Legacy compatibility: returns 'CALL', 'PUT', or None."""
    signals = generate_signals(row)
    if signals:
        return signals[0].direction
    return None