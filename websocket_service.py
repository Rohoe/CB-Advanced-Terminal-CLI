"""
WebSocket service for real-time market data and fill notifications.

Wraps the Coinbase SDK's WSClient for ticker data and user channel
for fill events. Provides a thread-safe price cache and callback
system for push-based fill detection.

Usage:
    from websocket_service import WebSocketService

    ws = WebSocketService(api_key, api_secret, config)
    ws.subscribe_ticker(["BTC-USD", "ETH-USD"])
    ws.subscribe_user()
    prices = ws.get_current_prices("BTC-USD")
    ws.stop()
"""

import json
import time
import logging
import threading
from typing import Optional, Dict, List, Callable, Any

from config_manager import WebSocketConfig


class WebSocketService:
    """Thread-safe WebSocket service for real-time prices and fill events."""

    def __init__(self, api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 config: Optional[WebSocketConfig] = None):
        """
        Initialize the WebSocket service.

        Args:
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            config: WebSocket configuration.
        """
        self._config = config or WebSocketConfig()
        self._api_key = api_key
        self._api_secret = api_secret

        # Price cache: product_id -> {bid, ask, mid, timestamp}
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._price_lock = threading.Lock()

        # Fill callbacks
        self._fill_callbacks: List[Callable[[dict], None]] = []
        self._fill_lock = threading.Lock()

        # WebSocket clients
        self._ticker_client = None
        self._user_client = None

        # State
        self._connected = False
        self._subscribed_products: List[str] = []

        logging.info("WebSocketService initialized")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, product_ids: Optional[List[str]] = None):
        """Start WebSocket connections.

        Args:
            product_ids: Products to subscribe to for ticker data.
        """
        if not self._config.enabled:
            logging.info("WebSocket disabled by config")
            return

        try:
            if self._config.ticker_enabled and product_ids:
                self._start_ticker(product_ids)

            if self._config.user_channel_enabled:
                self._start_user()

            self._connected = True
            logging.info("WebSocket connections started")

        except Exception as e:
            logging.error(f"Error starting WebSocket: {e}")
            self._connected = False

    def _start_ticker(self, product_ids: List[str]):
        """Start the ticker WebSocket client."""
        try:
            from coinbase.websocket import WSClient

            def on_ticker_message(msg):
                self._handle_ticker_message(msg)

            self._ticker_client = WSClient(
                api_key=self._api_key,
                api_secret=self._api_secret,
                on_message=on_ticker_message,
                retry=True,
                verbose=False,
            )

            self._ticker_client.open()
            self._ticker_client.ticker(product_ids=product_ids)
            self._subscribed_products = list(product_ids)
            logging.info(f"Ticker subscribed to {len(product_ids)} products")

        except Exception as e:
            logging.error(f"Error starting ticker WebSocket: {e}")

    def _start_user(self):
        """Start the user channel WebSocket client for fill events."""
        try:
            from coinbase.websocket import WSClient

            def on_user_message(msg):
                self._handle_user_message(msg)

            self._user_client = WSClient(
                api_key=self._api_key,
                api_secret=self._api_secret,
                on_message=on_user_message,
                retry=True,
                verbose=False,
            )

            self._user_client.open()
            self._user_client.user(product_ids=[])
            logging.info("User channel subscribed")

        except Exception as e:
            logging.error(f"Error starting user WebSocket: {e}")

    def subscribe_ticker(self, product_ids: List[str]):
        """Subscribe to ticker for additional products.

        Args:
            product_ids: Products to add to ticker subscription.
        """
        if not self._ticker_client:
            logging.warning("Ticker client not started")
            return

        new_products = [p for p in product_ids if p not in self._subscribed_products]
        if not new_products:
            return

        try:
            self._ticker_client.ticker(product_ids=new_products)
            self._subscribed_products.extend(new_products)
            logging.info(f"Added ticker subscriptions: {new_products}")
        except Exception as e:
            logging.error(f"Error subscribing to ticker: {e}")

    def register_fill_callback(self, callback: Callable[[dict], None]):
        """Register a callback for fill events.

        The callback receives a dict with:
            order_id, product_id, side, size, price, fee, trade_time

        Args:
            callback: Function called on each fill event.
        """
        with self._fill_lock:
            self._fill_callbacks.append(callback)

    def get_current_prices(self, product_id: str) -> Optional[Dict[str, float]]:
        """Get cached prices for a product.

        Returns None if no cached price or price is stale.

        Args:
            product_id: The product ID (e.g., "BTC-USD").

        Returns:
            Dict with 'bid', 'ask', 'mid' or None if stale/missing.
        """
        with self._price_lock:
            cached = self._price_cache.get(product_id)
            if not cached:
                return None

            age = time.time() - cached.get('timestamp', 0)
            if age > self._config.price_stale_seconds:
                return None

            return {
                'bid': cached['bid'],
                'ask': cached['ask'],
                'mid': cached['mid'],
            }

    def _handle_ticker_message(self, raw_msg: str):
        """Handle incoming ticker WebSocket message."""
        try:
            if isinstance(raw_msg, str):
                msg = json.loads(raw_msg)
            else:
                msg = raw_msg

            channel = msg.get('channel')
            if channel != 'ticker':
                return

            events = msg.get('events', [])
            for event in events:
                tickers = event.get('tickers', [])
                for ticker in tickers:
                    product_id = ticker.get('product_id')
                    if not product_id:
                        continue

                    try:
                        bid = float(ticker.get('best_bid', 0))
                        ask = float(ticker.get('best_ask', 0))
                        mid = (bid + ask) / 2 if bid and ask else 0

                        with self._price_lock:
                            self._price_cache[product_id] = {
                                'bid': bid,
                                'ask': ask,
                                'mid': mid,
                                'timestamp': time.time(),
                            }

                    except (ValueError, TypeError) as e:
                        logging.debug(f"Error parsing ticker for {product_id}: {e}")

        except json.JSONDecodeError:
            logging.debug("Non-JSON ticker message received")
        except Exception as e:
            logging.error(f"Error handling ticker message: {e}")

    def _handle_user_message(self, raw_msg: str):
        """Handle incoming user channel WebSocket message (fills)."""
        try:
            if isinstance(raw_msg, str):
                msg = json.loads(raw_msg)
            else:
                msg = raw_msg

            channel = msg.get('channel')
            if channel != 'user':
                return

            events = msg.get('events', [])
            for event in events:
                event_type = event.get('type', '')
                if event_type != 'snapshot' and event_type != 'update':
                    continue

                orders = event.get('orders', [])
                for order_data in orders:
                    status = order_data.get('status', '')
                    if status != 'FILLED':
                        continue

                    fill_event = {
                        'order_id': order_data.get('order_id'),
                        'product_id': order_data.get('product_id'),
                        'side': order_data.get('order_side'),
                        'size': order_data.get('cumulative_quantity', '0'),
                        'price': order_data.get('avg_price', '0'),
                        'fee': order_data.get('total_fees', '0'),
                        'trade_time': order_data.get('creation_time', ''),
                        'status': 'FILLED',
                    }

                    logging.info(f"WS fill event: {fill_event['order_id']}")

                    with self._fill_lock:
                        for callback in self._fill_callbacks:
                            try:
                                callback(fill_event)
                            except Exception as e:
                                logging.error(f"Fill callback error: {e}")

        except json.JSONDecodeError:
            logging.debug("Non-JSON user message received")
        except Exception as e:
            logging.error(f"Error handling user message: {e}")

    def stop(self):
        """Stop all WebSocket connections."""
        if self._ticker_client:
            try:
                self._ticker_client.close()
            except Exception as e:
                logging.error(f"Error closing ticker client: {e}")
            self._ticker_client = None

        if self._user_client:
            try:
                self._user_client.close()
            except Exception as e:
                logging.error(f"Error closing user client: {e}")
            self._user_client = None

        self._connected = False
        logging.info("WebSocket connections stopped")

    def get_subscribed_products(self) -> List[str]:
        """Get list of products subscribed to ticker."""
        return list(self._subscribed_products)

    def get_cached_products(self) -> List[str]:
        """Get list of products with cached prices."""
        with self._price_lock:
            return list(self._price_cache.keys())
