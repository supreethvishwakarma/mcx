"""
Market Stream (Angel One SmartWebSocket)
──────────────────────────────────────────
Live tick feed from Angel One's SmartWebSocket V2.
Used during market hours for real-time data ingestion.

SmartWebSocket V2 provides:
  - LTP, volume, OHLC, 5-level market depth, open interest
  - ~100-500ms latency
  - No historical tick data (use TrueData for that)
"""

from datetime import datetime
from typing import Callable, List, Optional

from config.settings import (
    ANGEL_ONE_API_KEY,
    ANGEL_ONE_ACCESS_TOKEN,
    ANGEL_ONE_CLIENT_ID,
    ANGEL_ONE_FEED_TOKEN,
)
from utils.logger import get_logger

logger = get_logger("market_stream")

# SmartAPI exchangeType codes used when subscribing. MCX=5 verified against
# marketcalls/openalgo's broker/angel/streaming/angel_mapping.py — Angel One's
# own docs don't spell this out clearly.
_EXCHANGE_TYPE_MCX = 5

# Subscription mode: 1=LTP, 2=Quote, 3=SnapQuote (full depth)
_MODE_SNAP_QUOTE = 3


class AngelOneStream:
    """Wraps Angel One SmartWebSocket V2 for live market data."""

    def __init__(self):
        self._ws = None
        self._callbacks: List[Callable] = []
        self._instrument_tokens: List[str] = []

    def connect(self, instrument_tokens: List[str]):
        """
        Connect to SmartWebSocket and subscribe to given instrument tokens.
        Instrument tokens map to specific NIFTY/BANKNIFTY option contracts.
        """
        self._instrument_tokens = instrument_tokens

        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            self._ws = SmartWebSocketV2(
                ANGEL_ONE_ACCESS_TOKEN, ANGEL_ONE_API_KEY, ANGEL_ONE_CLIENT_ID, ANGEL_ONE_FEED_TOKEN
            )
            self._ws.on_data = self._on_data
            self._ws.on_open = self._on_open
            self._ws.on_close = self._on_close
            self._ws.on_error = self._on_error

            logger.info("Connecting to Angel One SmartWebSocket...")
            self._ws.connect()

        except ImportError:
            logger.warning(
                "smartapi-python not installed or not configured. "
                "Live Angel One stream unavailable."
            )
        except Exception as e:
            logger.error(f"Angel One WebSocket connection failed: {e}")

    def _on_open(self, wsapp):
        logger.info("Angel One SmartWebSocket connected.")
        if self._instrument_tokens:
            token_list = [{
                "exchangeType": _EXCHANGE_TYPE_MCX,
                "tokens": self._instrument_tokens,
            }]
            self._ws.subscribe("stream_1", _MODE_SNAP_QUOTE, token_list)
            logger.info(
                f"Subscribed to {len(self._instrument_tokens)} instruments."
            )

    def _on_data(self, wsapp, message):
        tick = self._parse_tick(message)
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")

    def _on_close(self, wsapp):
        logger.warning("Angel One SmartWebSocket closed.")

    def _on_error(self, wsapp, error):
        logger.error(f"Angel One SmartWebSocket error: {error}")

    def add_callback(self, callback: Callable):
        """Register a function to receive parsed tick dicts."""
        self._callbacks.append(callback)

    def disconnect(self):
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
        logger.info("Angel One SmartWebSocket disconnected.")

    # ── Tick Parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_tick(raw: dict) -> dict:
        """
        Convert a SmartWebSocket V2 tick payload into our standard tick format.
        SnapQuote mode provides: last_traded_price, volume, depth, OI, etc.
        Prices arrive scaled ×100 on NSE/NFO feeds — divide by 100 to get
        rupees. UNVERIFIED for MCX: commodity prices (₹/barrel, ₹/10g,
        ₹/kg) may use a different or no scaling factor on Angel One's feed.
        Confirm against a live tick before trusting this division.
        """
        buy_depth = raw.get("best_5_buy_data") or [{}]
        sell_depth = raw.get("best_5_sell_data") or [{}]

        return {
            "timestamp": raw.get("exchange_timestamp", datetime.now()),
            "symbol": str(raw.get("token", "")),
            "price": float(raw.get("last_traded_price", 0)) / 100,
            "volume": int(raw.get("volume_trade_for_the_day", 0)),
            "bid_price": float(buy_depth[0].get("price", 0)) / 100 if buy_depth else 0.0,
            "ask_price": float(sell_depth[0].get("price", 0)) / 100 if sell_depth else 0.0,
            "bid_qty": int(buy_depth[0].get("quantity", 0)) if buy_depth else 0,
            "ask_qty": int(sell_depth[0].get("quantity", 0)) if sell_depth else 0,
            "oi": int(raw.get("open_interest", 0)),
        }
