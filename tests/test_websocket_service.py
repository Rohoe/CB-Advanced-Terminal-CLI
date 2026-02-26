"""Tests for WebSocket service."""

import json
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

from websocket_service import WebSocketService
from config_manager import WebSocketConfig


@pytest.fixture
def ws_config():
    return WebSocketConfig(
        enabled=True,
        ticker_enabled=True,
        user_channel_enabled=True,
        price_stale_seconds=5,
    )


@pytest.fixture
def ws_service(ws_config):
    return WebSocketService(
        api_key="test-key",
        api_secret="test-secret",
        config=ws_config,
    )


class TestWebSocketService:

    def test_initial_state(self, ws_service):
        assert not ws_service.is_connected
        assert ws_service.get_subscribed_products() == []
        assert ws_service.get_cached_products() == []

    def test_get_current_prices_no_cache(self, ws_service):
        assert ws_service.get_current_prices("BTC-USD") is None

    def test_get_current_prices_stale(self, ws_service):
        """Stale prices should return None."""
        ws_service._price_cache["BTC-USD"] = {
            'bid': 50000.0,
            'ask': 50010.0,
            'mid': 50005.0,
            'timestamp': time.time() - 100,  # Very old
        }
        assert ws_service.get_current_prices("BTC-USD") is None

    def test_get_current_prices_fresh(self, ws_service):
        """Fresh prices should be returned."""
        ws_service._price_cache["BTC-USD"] = {
            'bid': 50000.0,
            'ask': 50010.0,
            'mid': 50005.0,
            'timestamp': time.time(),
        }
        prices = ws_service.get_current_prices("BTC-USD")
        assert prices is not None
        assert prices['bid'] == 50000.0
        assert prices['ask'] == 50010.0
        assert prices['mid'] == 50005.0


class TestTickerMessageHandling:

    def test_valid_ticker_message(self, ws_service):
        msg = json.dumps({
            'channel': 'ticker',
            'events': [{
                'tickers': [{
                    'product_id': 'BTC-USD',
                    'best_bid': '49995.00',
                    'best_ask': '50005.00',
                }]
            }]
        })
        ws_service._handle_ticker_message(msg)

        prices = ws_service.get_current_prices("BTC-USD")
        assert prices is not None
        assert prices['bid'] == 49995.0
        assert prices['ask'] == 50005.0
        assert prices['mid'] == pytest.approx(50000.0)

    def test_multiple_products(self, ws_service):
        msg = json.dumps({
            'channel': 'ticker',
            'events': [{
                'tickers': [
                    {'product_id': 'BTC-USD', 'best_bid': '50000', 'best_ask': '50010'},
                    {'product_id': 'ETH-USD', 'best_bid': '3000', 'best_ask': '3005'},
                ]
            }]
        })
        ws_service._handle_ticker_message(msg)

        assert ws_service.get_current_prices("BTC-USD") is not None
        assert ws_service.get_current_prices("ETH-USD") is not None
        assert len(ws_service.get_cached_products()) == 2

    def test_non_ticker_channel_ignored(self, ws_service):
        msg = json.dumps({'channel': 'heartbeat', 'events': []})
        ws_service._handle_ticker_message(msg)
        assert ws_service.get_cached_products() == []

    def test_invalid_json(self, ws_service):
        ws_service._handle_ticker_message("not json")
        assert ws_service.get_cached_products() == []

    def test_dict_message(self, ws_service):
        """Should handle dict messages (not just strings)."""
        msg = {
            'channel': 'ticker',
            'events': [{
                'tickers': [{
                    'product_id': 'SOL-USD',
                    'best_bid': '100',
                    'best_ask': '101',
                }]
            }]
        }
        ws_service._handle_ticker_message(msg)
        assert ws_service.get_current_prices("SOL-USD") is not None


class TestUserMessageHandling:

    def test_fill_event(self, ws_service):
        received = []
        ws_service.register_fill_callback(lambda e: received.append(e))

        msg = json.dumps({
            'channel': 'user',
            'events': [{
                'type': 'update',
                'orders': [{
                    'order_id': 'order-123',
                    'product_id': 'BTC-USD',
                    'order_side': 'BUY',
                    'status': 'FILLED',
                    'cumulative_quantity': '0.1',
                    'avg_price': '50000',
                    'total_fees': '2.50',
                    'creation_time': '2026-01-01T00:00:00Z',
                }]
            }]
        })
        ws_service._handle_user_message(msg)

        assert len(received) == 1
        assert received[0]['order_id'] == 'order-123'
        assert received[0]['status'] == 'FILLED'

    def test_non_filled_order_ignored(self, ws_service):
        received = []
        ws_service.register_fill_callback(lambda e: received.append(e))

        msg = json.dumps({
            'channel': 'user',
            'events': [{
                'type': 'update',
                'orders': [{
                    'order_id': 'order-456',
                    'status': 'OPEN',
                }]
            }]
        })
        ws_service._handle_user_message(msg)
        assert len(received) == 0

    def test_multiple_callbacks(self, ws_service):
        received1, received2 = [], []
        ws_service.register_fill_callback(lambda e: received1.append(e))
        ws_service.register_fill_callback(lambda e: received2.append(e))

        msg = json.dumps({
            'channel': 'user',
            'events': [{
                'type': 'update',
                'orders': [{'order_id': 'o1', 'status': 'FILLED'}]
            }]
        })
        ws_service._handle_user_message(msg)

        assert len(received1) == 1
        assert len(received2) == 1

    def test_callback_error_doesnt_break_others(self, ws_service):
        received = []
        ws_service.register_fill_callback(lambda e: 1/0)  # Will raise
        ws_service.register_fill_callback(lambda e: received.append(e))

        msg = json.dumps({
            'channel': 'user',
            'events': [{
                'type': 'update',
                'orders': [{'order_id': 'o2', 'status': 'FILLED'}]
            }]
        })
        ws_service._handle_user_message(msg)
        assert len(received) == 1

    def test_non_user_channel_ignored(self, ws_service):
        received = []
        ws_service.register_fill_callback(lambda e: received.append(e))

        msg = json.dumps({'channel': 'heartbeat', 'events': []})
        ws_service._handle_user_message(msg)
        assert len(received) == 0


class TestWebSocketLifecycle:

    def test_disabled_by_config(self):
        config = WebSocketConfig(enabled=False)
        ws = WebSocketService(config=config)
        ws.start(product_ids=["BTC-USD"])
        assert not ws.is_connected

    def test_stop(self, ws_service):
        ws_service._connected = True
        ws_service.stop()
        assert not ws_service.is_connected

    @patch('websocket_service.WebSocketService._start_ticker')
    @patch('websocket_service.WebSocketService._start_user')
    def test_start_calls_both(self, mock_user, mock_ticker, ws_service):
        ws_service.start(product_ids=["BTC-USD"])
        mock_ticker.assert_called_once_with(["BTC-USD"])
        mock_user.assert_called_once()
        assert ws_service.is_connected

    @patch('websocket_service.WebSocketService._start_ticker')
    @patch('websocket_service.WebSocketService._start_user')
    def test_start_ticker_only_enabled(self, mock_user, mock_ticker):
        """Only ticker enabled → user channel not started."""
        config = WebSocketConfig(
            enabled=True,
            ticker_enabled=True,
            user_channel_enabled=False,
        )
        ws = WebSocketService(api_key="k", api_secret="s", config=config)
        ws.start(product_ids=["BTC-USD"])
        mock_ticker.assert_called_once_with(["BTC-USD"])
        mock_user.assert_not_called()
        assert ws.is_connected

    @patch('websocket_service.WebSocketService._start_ticker')
    @patch('websocket_service.WebSocketService._start_user')
    def test_start_user_only_enabled(self, mock_user, mock_ticker):
        """Only user channel enabled → ticker not started."""
        config = WebSocketConfig(
            enabled=True,
            ticker_enabled=False,
            user_channel_enabled=True,
        )
        ws = WebSocketService(api_key="k", api_secret="s", config=config)
        ws.start(product_ids=["BTC-USD"])
        mock_ticker.assert_not_called()
        mock_user.assert_called_once()
        assert ws.is_connected

    @patch('websocket_service.WebSocketService._start_ticker')
    def test_start_ticker_failure_sets_connected_true(self, mock_ticker, ws_service):
        """If ticker raises, _connected should be False."""
        mock_ticker.side_effect = Exception("connection error")
        ws_service.start(product_ids=["BTC-USD"])
        # Bug: _connected is set to True after the try block, even if ticker fails
        # This documents current behavior (connected=False because exception in try)
        assert not ws_service.is_connected

    def test_subscribe_ticker_no_client(self, ws_service):
        """subscribe_ticker without start should not crash."""
        ws_service.subscribe_ticker(["BTC-USD"])
        assert ws_service.get_subscribed_products() == []

    def test_stop_without_start(self, ws_service):
        """stop() without start should not crash."""
        ws_service.stop()
        assert not ws_service.is_connected

    def test_stop_idempotent(self, ws_service):
        """Double stop should not crash."""
        ws_service._connected = True
        ws_service.stop()
        ws_service.stop()
        assert not ws_service.is_connected


class TestWebSocketTickerEdgeCases:

    def test_ticker_missing_product_id(self, ws_service):
        """Ticker with missing product_id should not crash."""
        msg = json.dumps({
            'channel': 'ticker',
            'events': [{
                'tickers': [{'best_bid': '100', 'best_ask': '101'}]
            }]
        })
        ws_service._handle_ticker_message(msg)
        assert ws_service.get_cached_products() == []

    def test_ticker_non_numeric_bid(self, ws_service):
        """Non-numeric bid/ask should be handled gracefully."""
        msg = json.dumps({
            'channel': 'ticker',
            'events': [{
                'tickers': [{
                    'product_id': 'BTC-USD',
                    'best_bid': 'NaN',
                    'best_ask': 'NaN',
                }]
            }]
        })
        ws_service._handle_ticker_message(msg)
        # NaN is a valid float, but mid calculation should still work
        # (float('NaN') doesn't raise, just produces NaN)
        cached = ws_service.get_cached_products()
        # Product was cached (float('NaN') doesn't throw ValueError)
        assert 'BTC-USD' in cached

    def test_get_cached_products_thread_safe(self, ws_service):
        """Concurrent update + read should not crash."""
        import threading

        def update():
            for i in range(50):
                msg = json.dumps({
                    'channel': 'ticker',
                    'events': [{
                        'tickers': [{'product_id': f'PROD-{i}', 'best_bid': '100', 'best_ask': '101'}]
                    }]
                })
                ws_service._handle_ticker_message(msg)

        def read():
            for _ in range(50):
                ws_service.get_cached_products()
                ws_service.get_current_prices("BTC-USD")

        t1 = threading.Thread(target=update)
        t2 = threading.Thread(target=read)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # No crash = success

    def test_subscribe_ticker_deduplicates(self, ws_service):
        """Subscribing same product twice should not duplicate."""
        ws_service._ticker_client = MagicMock()
        ws_service._subscribed_products = ["BTC-USD"]

        ws_service.subscribe_ticker(["BTC-USD", "ETH-USD"])

        # Only ETH-USD should be new
        ws_service._ticker_client.ticker.assert_called_once_with(product_ids=["ETH-USD"])
        assert "ETH-USD" in ws_service._subscribed_products
        assert ws_service._subscribed_products.count("BTC-USD") == 1
