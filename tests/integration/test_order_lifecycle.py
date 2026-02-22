"""
Integration tests for order lifecycle.

These tests verify the complete order lifecycle from placement
through fill tracking and status updates.
"""

import pytest
import time
import uuid
from unittest.mock import Mock, patch
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


@pytest.mark.integration
class TestOrderLifecycle:
    """Integration tests for complete order lifecycle."""

    def test_complete_order_lifecycle_buy_order(
        self,
        terminal_with_mocks,
        mock_api_client
    ):
        """Test complete lifecycle: place order → track status → verify fill."""
        terminal = terminal_with_mocks

        # Mock product - needs to support both getattr() and dict subscript
        mock_product = Mock()
        mock_product.product_id = 'BTC-USDC'
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_product.base_increment = '0.0001'
        # Also support dict-style access for round_size/round_price
        mock_product.__getitem__ = lambda self, key: {
            'base_min_size': '0.0001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }[key]
        mock_api_client.get_product.return_value = mock_product

        # Mock limit_order_gtc to return order ID
        order_id = 'test-order-123'
        mock_response = Mock()
        mock_response.success = True
        mock_response.order_id = order_id
        mock_response.to_dict.return_value = {'order_id': order_id, 'success': True}
        mock_api_client.limit_order_gtc.return_value = mock_response

        # Mock get_fills to simulate order fill
        mock_fill = Mock()
        mock_fill.order_id = order_id
        mock_fill.size = '0.1'
        mock_fill.price = '50000.00'
        mock_fill.fee = '10.0'
        mock_fill.liquidity_indicator = 'M'  # 'M' for MAKER
        mock_fill.trade_id = 'trade-123'
        mock_fill.trade_time = '2024-01-01T00:00:00Z'

        mock_api_client.get_fills.return_value = Mock(fills=[mock_fill])

        # ACT - Place order
        with patch.object(terminal.market_data, 'get_account_balance', return_value=10000.0):
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='BUY',
                base_size='0.1',
                limit_price='50000'
            )

        # ASSERT - Order placed (returns dict)
        assert result is not None
        assert result['order_id'] == order_id
        assert mock_api_client.limit_order_gtc.call_count == 1

        # ACT - Check fills
        fills = terminal.check_order_fills_batch([order_id])

        # ASSERT - Fill data retrieved
        assert order_id in fills
        assert fills[order_id]['filled_size'] == 0.1
        assert fills[order_id]['average_price'] == 50000.0
        assert fills[order_id]['is_maker'] == True

    def test_background_order_status_checker(self):
        """Test background thread monitors orders and updates fills."""
        from app import TradingTerminal
        from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
        from storage import InMemoryTWAPStorage
        from config_manager import AppConfig

        # Create mock dependencies
        mock_api = MockCoinbaseAPI()
        mock_storage = InMemoryTWAPStorage()
        config = AppConfig()

        # Create terminal WITHOUT checker thread first
        terminal = TradingTerminal(
            api_client=mock_api,
            twap_storage=mock_storage,
            config=config,
            start_checker_thread=False  # Don't start yet
        )

        # Create TWAP order tracking BEFORE starting thread
        twap_id = str(uuid.uuid4())
        order_id = 'test-order-123'

        terminal.order_to_twap_map[order_id] = twap_id
        terminal.twap_orders[twap_id] = {
            'total_filled': 0.0,
            'total_value_filled': 0.0,
            'total_fees': 0.0,
            'maker_orders': 0,
            'taker_orders': 0
        }

        # Simulate fill
        mock_api.simulate_fill(
            order_id=order_id,
            filled_size=0.1,
            price=50000.0,
            is_maker=True
        )

        # NOW start the checker thread
        from threading import Thread
        terminal.checker_thread = Thread(target=terminal.order_status_checker)
        terminal.checker_thread.daemon = True
        terminal.checker_thread.start()

        # Queue order for checking
        terminal.order_queue.put({'order_id': order_id})

        # ACT - Wait for thread to process (need > 0.5s for queue timeout)
        time.sleep(1.5)

        # ASSERT - Thread updated tracking
        assert terminal.twap_orders[twap_id]['total_filled'] > 0
        assert order_id in terminal.filled_orders

        # Cleanup
        terminal.is_running = False
        terminal.checker_thread.join(timeout=2)

    def test_order_validation_rejects_below_minimum(
        self,
        terminal_with_mocks,
        mock_api_client
    ):
        """Test order validation rejects orders below minimum size."""
        terminal = terminal_with_mocks

        # Mock product - needs to support both getattr() and dict subscript
        mock_product = Mock()
        mock_product.product_id = 'BTC-USDC'
        mock_product.base_min_size = '0.001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_product.base_increment = '0.0001'
        # Also support dict-style access for round_size/round_price
        mock_product.__getitem__ = lambda self, key: {
            'base_min_size': '0.001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }[key]
        mock_api_client.get_product.return_value = mock_product

        # Mock account balance
        with patch.object(terminal.market_data, 'get_account_balance', return_value=100000.0):
            # ACT - Try to place order below minimum
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='BUY',
                base_size='0.0001',  # Below minimum of 0.001
                limit_price='50000'
            )

        # ASSERT - Order rejected
        assert result is None  # Order rejected
        assert mock_api_client.limit_order_gtc.call_count == 0  # No API call made

    def test_order_placement_handles_exceptions(
        self,
        terminal_with_mocks,
        mock_api_client
    ):
        """Test order placement handles exceptions gracefully."""
        terminal = terminal_with_mocks

        # Mock product - needs to support both getattr() and dict subscript
        mock_product = Mock()
        mock_product.product_id = 'BTC-USDC'
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_product.base_increment = '0.0001'
        # Also support dict-style access for round_size/round_price
        mock_product.__getitem__ = lambda self, key: {
            'base_min_size': '0.0001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }[key]
        mock_api_client.get_product.return_value = mock_product

        # Mock limit_order_gtc to raise exception
        mock_api_client.limit_order_gtc.side_effect = Exception("API error")

        # ACT - Place order that will fail
        with patch.object(terminal.market_data, 'get_account_balance', return_value=10000.0):
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='BUY',
                base_size='0.1',
                limit_price='50000'
            )

        # ASSERT - Order failed gracefully (returns None)
        assert result is None
        assert mock_api_client.limit_order_gtc.call_count == 1  # Called once, then failed

    def test_order_fills_batch_processing(
        self,
        terminal_with_mocks,
        mock_api_client
    ):
        """Test batch processing of order fills for efficiency."""
        terminal = terminal_with_mocks

        # Create multiple orders
        order_ids = [f'order-{i}' for i in range(5)]

        # Mock fills for each order
        mock_fills = []
        for i, order_id in enumerate(order_ids):
            fill = Mock()
            fill.size = str(0.1 + i * 0.01)
            fill.price = str(50000.0 + i * 100)
            fill.fee = '10.0'  # Changed from commission to fee
            fill.liquidity_indicator = 'M' if i % 2 == 0 else 'T'  # 'M' for MAKER, 'T' for TAKER
            fill.trade_id = f'trade-{i}'
            fill.trade_time = '2024-01-01T00:00:00Z'
            fill.order_id = order_id
            mock_fills.append(fill)

        mock_api_client.get_fills.return_value = Mock(fills=mock_fills)

        # ACT - Check fills in batch
        fills_result = terminal.check_order_fills_batch(order_ids)

        # ASSERT - All orders processed in single API call
        assert len(fills_result) == 5
        assert mock_api_client.get_fills.call_count == 1  # Single batch call

        # Verify fill data for each order
        for i, order_id in enumerate(order_ids):
            assert order_id in fills_result
            assert fills_result[order_id]['filled_size'] > 0
            assert fills_result[order_id]['is_maker'] == (i % 2 == 0)
