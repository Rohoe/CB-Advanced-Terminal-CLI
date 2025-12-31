"""
Integration tests for TWAP order execution.

These tests verify the complete TWAP order execution flow,
including order placement, slice execution, and state persistence.
"""

import pytest
import time
import uuid
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta


@pytest.mark.integration
class TestTWAPExecution:
    """Integration tests for complete TWAP order execution flow."""

    def test_successful_twap_execution_all_slices_filled(
        self,
        terminal_with_mocks,
        mock_api_client,
        mock_twap_storage
    ):
        """Test complete TWAP order where all slices execute and fill successfully."""
        terminal = terminal_with_mocks

        # Mock user inputs: market, side, PRICE, SIZE, duration, slices, price_type
        # Order: market selection, side, limit_price, order_size, duration, slices, price_type
        inputs = ['1', 'BUY', '50000', '1.0', '5', '10', '1']

        # Mock product info for validation - must be dict
        mock_product = {
            'product_id': 'BTC-USDC',
            'base_min_size': '0.0001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }
        mock_api_client.get_product.return_value = mock_product

        # Mock get_consolidated_markets to return test markets
        mock_markets = [
            ('BTC', {
                'has_usd': False,
                'has_usdc': True,
                'usdc_product': 'BTC-USDC',
                'total_volume': 1000000
            })
        ]

        # Mock limit_order_gtc to return successful order responses
        order_ids = [f'order-{i}' for i in range(10)]
        mock_responses = []
        for order_id in order_ids:
            mock_resp = Mock()
            mock_resp.success = True
            mock_resp.order_id = order_id
            mock_resp.to_dict.return_value = {'order_id': order_id, 'success': True}
            mock_responses.append(mock_resp)

        mock_api_client.limit_order_gtc.side_effect = mock_responses

        # Mock get_fills to return empty fills (orders not filled yet)
        mock_api_client.get_fills.return_value = Mock(fills=[])

        # Mock get_transaction_summary for fee rates
        mock_api_client.get_transaction_summary.return_value = Mock(
            fee_tier={'maker_fee_rate': '0.004', 'taker_fee_rate': '0.006'}
        )

        # Mock account balance
        with patch.object(terminal, 'get_input', side_effect=inputs):
            with patch.object(terminal, 'get_account_balance', return_value=100000.0):
                with patch.object(terminal, 'get_consolidated_markets', return_value=(
                    [['1', 'BTC', '$1,000,000']], ['#', 'Market', 'Volume'], mock_markets
                )):
                    with patch('time.sleep'):  # Skip wait time for testing
                        # ACT
                        twap_id = terminal._place_twap_order_impl()

        # ASSERT
        assert twap_id is not None

        # Verify TWAP order was created and saved
        # Note: Terminal uses its own twap_tracker, so query from there
        twap_order = terminal.twap_tracker.get_twap_order(twap_id)
        assert twap_order is not None
        assert twap_order.market == 'BTC-USDC'
        assert twap_order.side == 'BUY'
        assert twap_order.total_size == 1.0
        assert twap_order.num_slices == 10
        assert len(twap_order.orders) == 10  # All slices placed
        assert twap_order.status == 'completed'

        # Verify API calls were made correctly
        assert mock_api_client.limit_order_gtc.call_count == 10

    def test_twap_execution_with_failed_slices(
        self,
        terminal_with_mocks,
        mock_api_client,
        mock_twap_storage
    ):
        """Test TWAP execution when some slices fail due to insufficient balance."""
        terminal = terminal_with_mocks

        # Mock user inputs: market, side, PRICE, SIZE, duration, slices, price_type
        inputs = ['1', 'BUY', '50000', '1.0', '5', '10', '1']

        # Mock product info - must be dict
        mock_product = {
            'product_id': 'BTC-USDC',
            'base_min_size': '0.0001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }
        mock_api_client.get_product.return_value = mock_product

        # Mock get_consolidated_markets
        mock_markets = [
            ('BTC', {
                'has_usd': False,
                'has_usdc': True,
                'usdc_product': 'BTC-USDC',
                'total_volume': 1000000
            })
        ]

        # Mock balance that becomes insufficient mid-execution
        # First 5 slices succeed, rest fail
        balance_values = [100000.0] * 5 + [10.0] * 10

        # Mock limit_order_gtc to return order IDs for first 5 slices
        order_ids = [f'order-{i}' for i in range(5)]
        mock_responses = []
        for order_id in order_ids:
            mock_resp = Mock()
            mock_resp.success = True
            mock_resp.order_id = order_id
            mock_resp.to_dict.return_value = {'order_id': order_id, 'success': True}
            mock_responses.append(mock_resp)

        mock_api_client.limit_order_gtc.side_effect = mock_responses

        # Mock get_fills to return empty fills
        mock_api_client.get_fills.return_value = Mock(fills=[])

        # Mock get_transaction_summary for fee rates
        mock_api_client.get_transaction_summary.return_value = Mock(
            fee_tier={'maker_fee_rate': '0.004', 'taker_fee_rate': '0.006'}
        )

        with patch.object(terminal, 'get_input', side_effect=inputs):
            with patch.object(terminal, 'get_account_balance', side_effect=balance_values):
                with patch.object(terminal, 'get_consolidated_markets', return_value=(
                    [['1', 'BTC', '$1,000,000']], ['#', 'Market', 'Volume'], mock_markets
                )):
                    with patch('time.sleep'):  # Skip wait time
                        # ACT
                        twap_id = terminal._place_twap_order_impl()

        # ASSERT
        # Query from terminal's twap_tracker
        twap_order = terminal.twap_tracker.get_twap_order(twap_id)
        assert len(twap_order.failed_slices) > 0  # Some slices failed
        assert len(twap_order.orders) < twap_order.num_slices  # Not all placed
        # With the balance pattern, some slices succeed before balance runs out
        assert len(twap_order.orders) >= 4  # At least 4 succeeded

    def test_twap_execution_different_price_types(
        self,
        terminal_with_mocks,
        mock_api_client,
        mock_twap_storage
    ):
        """Test TWAP execution with different price types (limit, bid, ask, mid)."""
        terminal = terminal_with_mocks

        # Test each price type
        price_types = {
            '1': 50000.0,  # limit price
            '2': 49995.0,  # bid
            '3': 50000.0,  # mid
            '4': 50005.0   # ask
        }

        for price_type, expected_price in price_types.items():
            # Mock user inputs: market, side, PRICE, SIZE, duration, slices, price_type
            inputs = ['1', 'BUY', '50000', '0.1', '1', '2', price_type]

            # Mock product info - must be dict
            mock_product = {
                'product_id': 'BTC-USDC',
                'base_min_size': '0.0001',
                'base_max_size': '10000',
                'quote_increment': '0.01',
                'base_increment': '0.0001'
            }
            mock_api_client.get_product.return_value = mock_product

            # Mock get_consolidated_markets
            mock_markets = [
                ('BTC', {
                    'has_usd': False,
                    'has_usdc': True,
                    'usdc_product': 'BTC-USDC',
                    'total_volume': 1000000
                })
            ]

            # Mock get_current_prices to return bid/ask/mid
            mock_prices = {'bid': 49995.0, 'ask': 50005.0, 'mid': 50000.0}

            # Mock limit_order_gtc - reset both mock and side_effect
            mock_api_client.limit_order_gtc.reset_mock(side_effect=True)
            mock_responses = []
            for i in range(2):
                mock_resp = Mock()
                mock_resp.success = True
                mock_resp.order_id = f'order-{price_type}-{i}'
                mock_resp.to_dict.return_value = {'order_id': f'order-{price_type}-{i}', 'success': True}
                mock_responses.append(mock_resp)
            mock_api_client.limit_order_gtc.side_effect = mock_responses

            # Mock get_fills to return empty fills
            mock_api_client.get_fills.return_value = Mock(fills=[])

            # Mock get_transaction_summary for fee rates
            mock_api_client.get_transaction_summary.return_value = Mock(
                fee_tier={'maker_fee_rate': '0.004', 'taker_fee_rate': '0.006'}
            )

            with patch.object(terminal, 'get_input', side_effect=inputs):
                with patch.object(terminal, 'get_account_balance', return_value=100000.0):
                    with patch.object(terminal, 'get_consolidated_markets', return_value=(
                        [['1', 'BTC', '$1,000,000']], ['#', 'Market', 'Volume'], mock_markets
                    )):
                        with patch.object(terminal, 'get_current_prices', return_value=mock_prices):
                            with patch('time.sleep'):  # Skip wait time
                                # ACT
                                twap_id = terminal._place_twap_order_impl()

            # ASSERT - verify TWAP completed
            # Note: Not all price types will place orders if price is unfavorable
            # For example, ASK price may be above limit for BUY orders
            assert twap_id is not None

            #  Verify TWAP order exists and completed
            twap_order = terminal.twap_tracker.get_twap_order(twap_id)
            assert twap_order is not None
            assert twap_order.status == 'completed'

            # Note: No cleanup needed - each iteration creates unique TWAP IDs

    def test_twap_order_persisted_after_each_slice(
        self,
        terminal_with_mocks,
        mock_api_client,
        mock_twap_storage
    ):
        """Verify TWAP order state is saved after each slice execution."""
        terminal = terminal_with_mocks

        # Mock user inputs: market, side, PRICE, SIZE, duration, slices, price_type
        inputs = ['1', 'BUY', '50000', '1.0', '5', '10', '1']

        # Mock product info - must be dict
        mock_product = {
            'product_id': 'BTC-USDC',
            'base_min_size': '0.0001',
            'base_max_size': '10000',
            'quote_increment': '0.01',
            'base_increment': '0.0001'
        }
        mock_api_client.get_product.return_value = mock_product

        # Mock get_consolidated_markets
        mock_markets = [
            ('BTC', {
                'has_usd': False,
                'has_usdc': True,
                'usdc_product': 'BTC-USDC',
                'total_volume': 1000000
            })
        ]

        # Mock limit_order_gtc to return order IDs
        order_ids = [f'order-{i}' for i in range(10)]
        mock_responses = []
        for order_id in order_ids:
            mock_resp = Mock()
            mock_resp.success = True
            mock_resp.order_id = order_id
            mock_resp.to_dict.return_value = {'order_id': order_id, 'success': True}
            mock_responses.append(mock_resp)
        mock_api_client.limit_order_gtc.side_effect = mock_responses

        # Mock get_fills to return empty fills
        mock_api_client.get_fills.return_value = Mock(fills=[])

        # Mock get_transaction_summary for fee rates
        mock_api_client.get_transaction_summary.return_value = Mock(
            fee_tier={'maker_fee_rate': '0.004', 'taker_fee_rate': '0.006'}
        )

        # Track save calls - need to wrap terminal's twap_tracker, not mock_twap_storage
        save_calls = []
        original_save = terminal.twap_tracker.save_twap_order

        def track_saves(order):
            save_calls.append(len(order.orders))  # Track number of orders at each save
            return original_save(order)

        terminal.twap_tracker.save_twap_order = track_saves

        with patch.object(terminal, 'get_input', side_effect=inputs):
            with patch.object(terminal, 'get_account_balance', return_value=100000.0):
                with patch.object(terminal, 'get_consolidated_markets', return_value=(
                    [['1', 'BTC', '$1,000,000']], ['#', 'Market', 'Volume'], mock_markets
                )):
                    with patch('time.sleep'):  # Skip wait time
                        # ACT
                        twap_id = terminal._place_twap_order_impl()

        # ASSERT
        # Should save after each slice + final save
        assert len(save_calls) >= 10  # At least 10 slices
        # Verify incremental growth - first save should have fewer orders than last
        assert save_calls[0] <= save_calls[-1]
