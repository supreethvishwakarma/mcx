"""
Broker Adapter (Angel One SmartAPI)
─────────────────────────────────────
Handles all communication with the Angel One SmartAPI.

Order types supported:
  - Market order (entry)
  - SL-M order  (exchange-managed stop loss)
  - Limit order  (target exit)
  - Cancel order

From the docs (§15):
  Stop loss should be exchange-managed.
"""

from typing import Optional

from config.settings import ANGEL_ONE_API_KEY, ANGEL_ONE_ACCESS_TOKEN
from utils.logger import get_logger

logger = get_logger("broker_adapter")


class BrokerAdapter:
    """
    Wraps Angel One SmartAPI for order execution.
    Lazy-initializes the SmartConnect client on first use.
    """

    def __init__(self):
        self._smart_api = None

    def _get_smart_api(self):
        if self._smart_api is None:
            try:
                from SmartApi import SmartConnect

                self._smart_api = SmartConnect(api_key=ANGEL_ONE_API_KEY, access_token=ANGEL_ONE_ACCESS_TOKEN)
                logger.info("Angel One SmartAPI initialized.")
            except ImportError:
                logger.error(
                    "smartapi-python package not installed. "
                    "Install with: pip install smartapi-python"
                )
                raise
            except Exception as e:
                logger.error(f"Angel One SmartAPI initialization failed: {e}")
                raise
        return self._smart_api

    # ── Entry Order ───────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        price: float = 0,
        exchange: str = "NFO",
        product: str = "INTRADAY",
    ) -> Optional[str]:
        """
        Place an entry order. Returns the SmartAPI order ID.

        Args:
            symbol: trading symbol (e.g. "NIFTY2540322500CE")
            qty: quantity
            side: "BUY" or "SELL"
            order_type: "MARKET" or "LIMIT"
            price: limit price (only for LIMIT orders)
            exchange: "NFO" for F&O
            product: "INTRADAY" for MIS-equivalent intraday
        """
        smart_api = self._get_smart_api()

        params = {
            "tradingsymbol": symbol,
            "exchange": exchange,
            "transactiontype": side,
            "quantity": str(qty),
            "ordertype": order_type,
            "producttype": product,
            "variety": "NORMAL",
            "duration": "DAY",
        }

        if order_type == "LIMIT" and price > 0:
            params["price"] = str(price)

        try:
            order_id = smart_api.placeOrder(params)
            logger.info(f"Order placed: {symbol} {side} qty={qty} → {order_id}")
            return str(order_id)
        except Exception as e:
            logger.error(f"Order failed: {symbol} {side} qty={qty} – {e}")
            raise

    # ── Stop Loss Order (Exchange-Managed SL-M) ──────────────────────────────

    def place_sl_order(
        self,
        symbol: str,
        qty: int,
        trigger_price: float,
        side: str = "SELL",
        exchange: str = "NFO",
        product: str = "INTRADAY",
    ) -> Optional[str]:
        """
        Place a stop-loss market (SL-M) order.
        This is exchange-managed – executes automatically when trigger is hit.
        """
        smart_api = self._get_smart_api()

        try:
            order_id = smart_api.placeOrder({
                "tradingsymbol": symbol,
                "exchange": exchange,
                "transactiontype": side,
                "quantity": str(qty),
                "ordertype": "STOPLOSS_MARKET",
                "triggerprice": str(trigger_price),
                "producttype": product,
                "variety": "NORMAL",
                "duration": "DAY",
            })
            logger.info(f"SL order placed: {symbol} trigger={trigger_price} → {order_id}")
            return str(order_id)
        except Exception as e:
            logger.error(f"SL order failed: {symbol} trigger={trigger_price} – {e}")
            raise

    # ── Target Order (Limit) ──────────────────────────────────────────────────

    def place_target_order(
        self,
        symbol: str,
        qty: int,
        price: float,
        side: str = "SELL",
        exchange: str = "NFO",
        product: str = "INTRADAY",
    ) -> Optional[str]:
        """Place a limit order as target exit."""
        return self.place_order(
            symbol=symbol,
            qty=qty,
            side=side,
            order_type="LIMIT",
            price=price,
            exchange=exchange,
            product=product,
        )

    # ── Cancel Order ──────────────────────────────────────────────────────────

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """Cancel an open order by its SmartAPI order ID."""
        smart_api = self._get_smart_api()
        try:
            smart_api.cancelOrder(order_id=order_id, variety=variety)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {order_id} – {e}")
            return False

    # ── Order Status ──────────────────────────────────────────────────────────

    def get_order_status(self, order_id: str) -> dict:
        """Fetch status of a specific order."""
        smart_api = self._get_smart_api()
        try:
            book = smart_api.orderBook()
            orders = (book or {}).get("data") or []
            return next((o for o in orders if str(o.get("orderid")) == str(order_id)), {})
        except Exception as e:
            logger.error(f"Status fetch failed: {order_id} – {e}")
            return {}

    def get_positions(self) -> dict:
        """Fetch current positions."""
        smart_api = self._get_smart_api()
        try:
            return smart_api.position()
        except Exception as e:
            logger.error(f"Positions fetch failed: {e}")
            return {}


# ── Legacy compatibility ──────────────────────────────────────────────────────

_adapter: Optional[BrokerAdapter] = None


def place_order(symbol: str, qty: int, side: str):
    """Legacy function."""
    global _adapter
    if _adapter is None:
        _adapter = BrokerAdapter()
    _adapter.place_order(symbol, qty, side)
