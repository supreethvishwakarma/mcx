"""
Angel One SmartAPI Adapter
───────────────────────────
Real-money execution via Angel One's SmartAPI (formerly Angel Broking).

Authentication flow:
  1. Server holds API key, client code, password/PIN and a TOTP secret
  2. generateSession() exchanges those for jwtToken / refreshToken / feedToken
  3. All subsequent API calls use the jwtToken (valid for the trading day)
  4. TOTP can also be supplied per-call (e.g. typed in on the dashboard)
     instead of being derived from a stored secret

Required env vars:
  ANGEL_ONE_API_KEY       — from https://smartapi.angelbroking.com
  ANGEL_ONE_CLIENT_ID     — Angel One client code (e.g. "A123456")
  ANGEL_ONE_PASSWORD      — trading PIN / password

Optional:
  ANGEL_ONE_TOTP_SECRET   — base32 TOTP secret for 2FA (skip to pass a
                             fresh 6-digit code into authenticate() instead)
  ANGEL_ONE_ACCESS_TOKEN  — cached jwtToken, set after login

Install:
  pip install smartapi-python pyotp

Docs: https://smartapi.angelbroking.com/docs
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from broker.base_adapter import (
    BrokerAdapter,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
)
from utils.logger import get_logger

logger = get_logger("angelone_adapter")

# Map our OrderType → SmartAPI ordertype string
_ORDER_TYPE_MAP = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "STOPLOSS_LIMIT",
    OrderType.SL_MARKET: "STOPLOSS_MARKET",
}

# Map our ProductType → SmartAPI producttype string
_PRODUCT_MAP = {
    ProductType.MIS: "INTRADAY",
    ProductType.NRML: "CARRYFORWARD",
    ProductType.CNC: "DELIVERY",
}

# Reverse map for parsing broker responses back into our ProductType
_PRODUCT_MAP_REVERSE = {v: k for k, v in _PRODUCT_MAP.items()}


class AngelOneAdapter(BrokerAdapter):
    """
    SmartAPI broker adapter for real-money trading.

    Usage:
        adapter = AngelOneAdapter()
        if adapter.authenticate():
            resp = adapter.buy("NIFTY26041323800PE", quantity=25, tag="bearish_momentum")
    """

    def __init__(self):
        self._api_key = os.getenv("ANGEL_ONE_API_KEY", "")
        self._client_id = os.getenv("ANGEL_ONE_CLIENT_ID", "")
        self._password = os.getenv("ANGEL_ONE_PASSWORD", "")
        self._totp_secret = os.getenv("ANGEL_ONE_TOTP_SECRET", "")
        self._access_token = os.getenv("ANGEL_ONE_ACCESS_TOKEN", "")
        self._refresh_token = ""
        self._feed_token = ""
        self._smart_api = None  # SmartApi.SmartConnect instance
        self._connected = False
        self._symbol_token_cache: dict[str, str] = {}

    # ── Configuration ────────────────────────────────────────────────

    def configure(
        self,
        api_key: str = "",
        client_id: str = "",
        password: str = "",
        totp_secret: str = "",
    ) -> None:
        """
        Update credentials at runtime (e.g. submitted from the dashboard's
        broker-connection form) without restarting the server.

        Only non-empty fields overwrite the current value, so partial
        updates (e.g. rotating just the password) are safe.
        """
        if api_key:
            self._api_key = api_key
            os.environ["ANGEL_ONE_API_KEY"] = api_key
        if client_id:
            self._client_id = client_id
            os.environ["ANGEL_ONE_CLIENT_ID"] = client_id
        if password:
            self._password = password
            os.environ["ANGEL_ONE_PASSWORD"] = password
        if totp_secret:
            self._totp_secret = totp_secret
            os.environ["ANGEL_ONE_TOTP_SECRET"] = totp_secret

        # Credentials changed — any existing session is no longer valid.
        self._connected = False
        logger.info(f"Angel One credentials updated (client_id={self._client_id or 'unset'})")

    @property
    def has_credentials(self) -> bool:
        return bool(self._api_key and self._client_id and self._password)

    # ── Authentication ────────────────────────────────────────────────

    def authenticate(self, totp: Optional[str] = None) -> bool:
        """
        Authenticate with SmartAPI using client_id/password + TOTP.

        Unlike a browser-redirect OAuth flow, SmartAPI logs in directly:
        pass `totp` for a one-off 6-digit code (e.g. typed on the
        dashboard), or leave it unset to derive one from
        ANGEL_ONE_TOTP_SECRET automatically.
        """
        if not self._api_key or not self._client_id or not self._password:
            logger.error(
                "ANGEL_ONE_API_KEY / ANGEL_ONE_CLIENT_ID / ANGEL_ONE_PASSWORD not set in .env"
            )
            return False

        try:
            from SmartApi import SmartConnect
        except ImportError:
            logger.error("smartapi-python package not installed. Run: pip install smartapi-python")
            return False

        totp_code = totp
        if not totp_code:
            if not self._totp_secret:
                logger.error(
                    "No TOTP provided and ANGEL_ONE_TOTP_SECRET not set — "
                    "pass a fresh 6-digit code to authenticate(totp=...)"
                )
                return False
            try:
                import pyotp
                totp_code = pyotp.TOTP(self._totp_secret).now()
            except ImportError:
                logger.error("pyotp package not installed. Run: pip install pyotp")
                return False

        self._smart_api = SmartConnect(api_key=self._api_key)

        try:
            session = self._smart_api.generateSession(self._client_id, self._password, totp_code)
            if not session or not session.get("status", False):
                message = (session or {}).get("message", "unknown error")
                logger.error(f"Angel One authentication failed: {message}")
                self._connected = False
                return False

            data = session.get("data", {})
            self._access_token = data.get("jwtToken", "")
            self._refresh_token = data.get("refreshToken", "")
            self._feed_token = data.get("feedToken", "")
            self._connected = True

            # Persist token to env so it survives restarts (valid for the trading day)
            os.environ["ANGEL_ONE_ACCESS_TOKEN"] = self._access_token

            logger.info(f"Angel One authenticated: {self._client_id}")
            return True
        except Exception as e:
            logger.error(f"Angel One authentication failed: {e}")
            self._connected = False
            return False

    @property
    def feed_token(self) -> str:
        """Token required by SmartWebSocket for live tick streaming."""
        return self._feed_token

    @property
    def is_connected(self) -> bool:
        return self._connected and self._smart_api is not None

    @property
    def broker_name(self) -> str:
        return "Angel One"

    # ── Symbol Resolution ────────────────────────────────────────────────

    def _get_symbol_token(self, tradingsymbol: str, exchange: str) -> str:
        """
        SmartAPI orders are keyed by an exchange-issued symboltoken, not
        just the trading symbol. Resolve and cache it via searchScrip().
        """
        cache_key = f"{exchange}:{tradingsymbol}"
        if cache_key in self._symbol_token_cache:
            return self._symbol_token_cache[cache_key]

        try:
            result = self._smart_api.searchScrip(exchange, tradingsymbol)
            matches = (result or {}).get("data", [])
            token = matches[0]["symboltoken"] if matches else ""
            if token:
                self._symbol_token_cache[cache_key] = token
            return token
        except Exception as e:
            logger.error(f"Angel One symbol lookup failed: {tradingsymbol} — {e}")
            return ""

    # ── Order Placement ───────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(status=OrderStatus.ERROR, message="Not connected to Angel One")

        try:
            symbol_token = self._get_symbol_token(request.symbol, request.exchange)

            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": request.symbol,
                "symboltoken": symbol_token,
                "exchange": request.exchange,
                "transactiontype": request.side.value,
                "ordertype": _ORDER_TYPE_MAP.get(request.order_type, "MARKET"),
                "producttype": _PRODUCT_MAP.get(request.product, "INTRADAY"),
                "duration": "DAY",
                "quantity": str(request.quantity),
                "price": str(request.price) if request.price else "0",
                "squareoff": "0",
                "stoploss": "0",
                "ordertag": request.tag[:20] if request.tag else "",  # SmartAPI tag max 20 chars
            }

            if request.order_type in (OrderType.SL, OrderType.SL_MARKET):
                order_params["triggerprice"] = str(request.trigger_price)

            order_id = self._smart_api.placeOrder(order_params)

            logger.info(
                f"Angel One ORDER: {request.side.value} {request.symbol} "
                f"×{request.quantity} [{request.order_type.value}] → {order_id}"
            )

            return OrderResponse(
                order_id=str(order_id),
                status=OrderStatus.OPEN,
                filled_quantity=0,  # will be updated by get_order_status
                message=f"Order placed: {order_id}",
                timestamp=datetime.now(),
                raw=order_params,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Angel One order FAILED: {request.symbol} {request.side.value} — {error_msg}")

            # Detect specific rejection reasons
            status = OrderStatus.REJECTED
            if "insufficient" in error_msg.lower():
                status = OrderStatus.REJECTED
            elif "network" in error_msg.lower() or "timeout" in error_msg.lower():
                status = OrderStatus.ERROR

            return OrderResponse(
                status=status,
                message=error_msg,
                timestamp=datetime.now(),
            )

    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[OrderType] = None,
    ) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(status=OrderStatus.ERROR, message="Not connected")

        try:
            params = {"orderid": order_id, "variety": "NORMAL"}
            if quantity is not None:
                params["quantity"] = str(quantity)
            if price is not None:
                params["price"] = str(price)
            if trigger_price is not None:
                params["triggerprice"] = str(trigger_price)
            if order_type is not None:
                params["ordertype"] = _ORDER_TYPE_MAP.get(order_type, "MARKET")

            self._smart_api.modifyOrder(params)
            logger.info(f"Angel One MODIFY: {order_id} trigger=₹{trigger_price}")
            return OrderResponse(order_id=order_id, status=OrderStatus.OPEN, message="Modified")

        except Exception as e:
            logger.error(f"Angel One MODIFY failed: {order_id} — {e}")
            return OrderResponse(order_id=order_id, status=OrderStatus.ERROR, message=str(e))

    def cancel_order(self, order_id: str) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(status=OrderStatus.ERROR, message="Not connected")

        try:
            self._smart_api.cancelOrder(order_id=order_id, variety="NORMAL")
            logger.info(f"Angel One CANCEL: {order_id}")
            return OrderResponse(order_id=order_id, status=OrderStatus.CANCELLED, message="Cancelled")
        except Exception as e:
            logger.error(f"Angel One CANCEL failed: {order_id} — {e}")
            return OrderResponse(order_id=order_id, status=OrderStatus.ERROR, message=str(e))

    # ── Position & Order Queries ──────────────────────────────────────

    def get_positions(self) -> list[Position]:
        if not self.is_connected:
            return []

        try:
            data = self._smart_api.position()
            positions = []
            for pos in (data or {}).get("data") or []:
                net_qty = int(pos.get("netqty", 0))
                if net_qty != 0:
                    positions.append(Position(
                        symbol=pos["tradingsymbol"],
                        exchange=pos["exchange"],
                        quantity=net_qty,
                        average_price=float(pos.get("avgnetprice", 0)),
                        last_price=float(pos.get("ltp", 0)),
                        pnl=float(pos.get("pnl", 0)),
                        product=_PRODUCT_MAP_REVERSE.get(pos.get("producttype", "INTRADAY"), ProductType.MIS),
                    ))
            return positions
        except Exception as e:
            logger.error(f"Angel One get_positions failed: {e}")
            return []

    def get_order_status(self, order_id: str) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(status=OrderStatus.ERROR, message="Not connected")

        try:
            book = self._smart_api.orderBook()
            orders = (book or {}).get("data") or []
            latest = next((o for o in orders if str(o.get("orderid")) == str(order_id)), None)
            if not latest:
                return OrderResponse(order_id=order_id, status=OrderStatus.ERROR, message="No history")

            status_map = {
                "COMPLETE": OrderStatus.COMPLETE,
                "REJECTED": OrderStatus.REJECTED,
                "CANCELLED": OrderStatus.CANCELLED,
                "OPEN": OrderStatus.OPEN,
                "PENDING": OrderStatus.PENDING,
                "TRIGGER PENDING": OrderStatus.PENDING,
            }
            return OrderResponse(
                order_id=order_id,
                status=status_map.get(str(latest.get("status", "")).upper(), OrderStatus.PENDING),
                filled_quantity=int(latest.get("filledshares", 0) or 0),
                average_price=float(latest.get("averageprice", 0) or 0),
                message=latest.get("text", ""),
                raw=latest,
            )
        except Exception as e:
            logger.error(f"Angel One order_status failed: {order_id} — {e}")
            return OrderResponse(order_id=order_id, status=OrderStatus.ERROR, message=str(e))

    def get_orders_today(self) -> list[OrderResponse]:
        if not self.is_connected:
            return []

        try:
            book = self._smart_api.orderBook()
            orders = (book or {}).get("data") or []
            return [
                OrderResponse(
                    order_id=str(o["orderid"]),
                    status=OrderStatus.COMPLETE if str(o.get("status", "")).upper() == "COMPLETE" else OrderStatus.OPEN,
                    filled_quantity=int(o.get("filledshares", 0) or 0),
                    average_price=float(o.get("averageprice", 0) or 0),
                    message=o.get("text", ""),
                    raw=o,
                )
                for o in orders
            ]
        except Exception as e:
            logger.error(f"Angel One get_orders failed: {e}")
            return []

    # ── Safety ────────────────────────────────────────────────────────

    def kill_switch(self) -> list[OrderResponse]:
        """
        EMERGENCY: Cancel all open orders and close all positions at market.

        This is the nuclear option. Runs even if some individual operations
        fail — logs errors and continues.
        """
        if not self.is_connected:
            logger.error("KILL SWITCH: not connected to Angel One!")
            return []

        responses = []

        # 1. Cancel all pending orders
        try:
            book = self._smart_api.orderBook()
            orders = (book or {}).get("data") or []
            for o in orders:
                if str(o.get("status", "")).upper() in ("OPEN", "PENDING", "TRIGGER PENDING"):
                    try:
                        self._smart_api.cancelOrder(order_id=o["orderid"], variety="NORMAL")
                        logger.warning(f"KILL: cancelled order {o['orderid']}")
                    except Exception as e:
                        logger.error(f"KILL: cancel {o['orderid']} failed: {e}")
        except Exception as e:
            logger.error(f"KILL: fetch orders failed: {e}")

        # 2. Close all open positions
        try:
            positions = self.get_positions()
            for pos in positions:
                if pos.quantity > 0:
                    resp = self.sell(
                        pos.symbol, pos.quantity,
                        order_type=OrderType.MARKET,
                        tag="KILL_SWITCH",
                    )
                    responses.append(resp)
                    if resp.status == OrderStatus.ERROR:
                        # Retry once
                        logger.warning(f"KILL: retrying {pos.symbol}")
                        resp2 = self.sell(pos.symbol, pos.quantity, tag="KILL_RETRY")
                        responses.append(resp2)
                elif pos.quantity < 0:
                    resp = self.buy(
                        pos.symbol, abs(pos.quantity),
                        order_type=OrderType.MARKET,
                        tag="KILL_SWITCH",
                    )
                    responses.append(resp)
        except Exception as e:
            logger.error(f"KILL: close positions failed: {e}")

        logger.warning(f"KILL SWITCH COMPLETE: {len(responses)} exit orders placed")
        return responses

    # ── Helpers ────────────────────────────────────────────────────────

    def get_margins(self) -> dict:
        """Return available margin / funds (RMS limits)."""
        if not self.is_connected:
            return {}
        try:
            return self._smart_api.rmsLimit()
        except Exception as e:
            logger.error(f"Margins fetch failed: {e}")
            return {}
