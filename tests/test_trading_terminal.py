"""
Unit tests for TradingTerminal class.

These tests verify correct handling of API response objects and core
TradingTerminal functionality.

To run these tests:
    pytest tests/test_trading_terminal.py
    pytest tests/test_trading_terminal.py::TestAPIResponseHandling -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from app import TradingTerminal
from config_manager import AppConfig


# =============================================================================
# API Response Object Handling Tests
# =============================================================================

@pytest.mark.unit
class TestAPIResponseHandling:
    """
    Tests to ensure API response objects are handled correctly.

    These tests prevent regressions where code treats API objects as
    dictionaries (e.g., using .get() instead of getattr()).
    """

    def test_get_products_returns_object_not_dict(self, mock_api_client, test_app_config):
        """Test that get_products handles response objects correctly."""
        # Create mock products as objects (not dicts)
        mock_product1 = Mock()
        mock_product1.product_id = 'BTC-USD'
        mock_product1.price = '50000.00'

        mock_product2 = Mock()
        mock_product2.product_id = 'ETH-USD'
        mock_product2.price = '3000.00'

        # Mock response object with products attribute
        mock_response = Mock()
        mock_response.products = [mock_product1, mock_product2]

        mock_api_client.get_products.return_value = mock_response

        # Create terminal
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Call get_bulk_prices which uses get_products
        prices = terminal.get_bulk_prices(['BTC-USD', 'ETH-USD'])

        # Verify it extracted prices correctly from objects
        assert prices['BTC-USD'] == 50000.0
        assert prices['ETH-USD'] == 3000.0

    def test_get_product_returns_object_not_dict(self, mock_api_client, test_app_config):
        """Test that get_product handles response objects correctly."""
        # Create mock product as object
        mock_product = Mock()
        mock_product.product_id = 'BTC-USDC'
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.base_increment = '0.00000001'
        mock_product.quote_increment = '0.01'

        mock_api_client.get_product.return_value = mock_product

        # Create terminal
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock account balance to pass validation
        with patch.object(terminal, 'get_account_balance', return_value=1.0):
            # This should handle the object correctly
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='SELL',
                base_size='0.001',
                limit_price='50000'
            )

            # Verify it called get_product (may be called multiple times for size/price rounding)
            assert mock_api_client.get_product.called
            mock_api_client.get_product.assert_any_call('BTC-USDC')

    def test_limit_order_response_is_object(self, mock_api_client, test_app_config):
        """Test that limit order responses are handled as objects."""
        # Mock product info
        mock_product = Mock()
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        # Mock successful order response as object
        mock_order_response = Mock()
        mock_order_response.success = True
        mock_order_response.success_response = Mock(order_id='test-order-123')
        mock_order_response.to_dict.return_value = {
            'success_response': {'order_id': 'test-order-123'}
        }

        mock_api_client.limit_order_gtc.return_value = mock_order_response

        # Create terminal
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock balance
        with patch.object(terminal, 'get_account_balance', return_value=1.0):
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='SELL',
                base_size='0.001',
                limit_price='50000'
            )

            # Verify it returned the dictionary version
            assert result is not None
            assert 'success_response' in result
            assert result['success_response']['order_id'] == 'test-order-123'

    def test_get_accounts_returns_object_not_dict(self, mock_api_client, test_app_config):
        """Test that get_accounts handles response objects correctly."""
        # Create mock account objects
        mock_account1 = Mock()
        mock_account1.currency = 'BTC'
        mock_account1.available_balance = {'value': '1.5', 'currency': 'BTC'}
        mock_account1.type = 'CRYPTO'
        mock_account1.ready = True
        mock_account1.active = True

        mock_account2 = Mock()
        mock_account2.currency = 'USDC'
        mock_account2.available_balance = {'value': '50000.0', 'currency': 'USDC'}
        mock_account2.type = 'CRYPTO'
        mock_account2.ready = True
        mock_account2.active = True

        # Mock response object
        mock_response = Mock()
        mock_response.accounts = [mock_account1, mock_account2]
        mock_response.has_next = False  # No pagination
        mock_response.cursor = ''

        mock_api_client.get_accounts.return_value = mock_response

        # Create terminal
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Call get_accounts to load them into cache
        terminal.get_accounts(force_refresh=True)

        # Verify balances were extracted correctly from objects
        btc_balance = terminal.get_account_balance('BTC')
        usdc_balance = terminal.get_account_balance('USDC')

        assert btc_balance == 1.5
        assert usdc_balance == 50000.0


# =============================================================================
# Price and Size Rounding Tests
# =============================================================================

@pytest.mark.unit
class TestPriceAndSizeRounding:
    """Tests for price and size rounding functionality."""

    def test_round_size_to_increment(self, mock_api_client, test_app_config):
        """Test that order size is rounded to product increment."""
        # Mock product with 8 decimal places
        mock_product = Mock()
        mock_product.base_increment = '0.00000001'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Round a size
        rounded = terminal.round_size(1.123456789, 'BTC-USDC')

        # Should be rounded to 8 decimals (allow tiny floating point variance)
        assert rounded == pytest.approx(1.12345678, rel=1e-8)

    def test_round_size_already_valid(self, mock_api_client, test_app_config):
        """Test that already-valid sizes are unchanged."""
        mock_product = Mock()
        mock_product.base_increment = '0.00000001'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Size already at 8 decimals
        rounded = terminal.round_size(1.12345678, 'BTC-USDC')

        assert rounded == 1.12345678

    def test_round_price_to_increment(self, mock_api_client, test_app_config):
        """Test that price is rounded to quote increment."""
        mock_product = Mock()
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Round a price
        rounded = terminal.round_price(50000.567, 'BTC-USDC')

        # Should be rounded to nearest cent
        assert rounded == 50000.57


# =============================================================================
# Balance and Validation Tests
# =============================================================================

@pytest.mark.unit
class TestBalanceValidation:
    """Tests for balance checking and order validation."""

    def test_insufficient_balance_buy_order(self, mock_api_client, test_app_config):
        """Test that buy orders fail with insufficient quote currency balance."""
        # Mock product
        mock_product = Mock()
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock insufficient USDC balance
        with patch.object(terminal, 'get_account_balance', return_value=100.0):
            # Try to buy 1 BTC at $50,000 (need $50,000 but only have $100)
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='BUY',
                base_size='1.0',
                limit_price='50000'
            )

            # Should fail due to insufficient balance
            assert result is None

    def test_insufficient_balance_sell_order(self, mock_api_client, test_app_config):
        """Test that sell orders fail with insufficient base currency balance."""
        mock_product = Mock()
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock insufficient BTC balance
        with patch.object(terminal, 'get_account_balance', return_value=0.0001):
            # Try to sell 1 BTC but only have 0.0001 BTC
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='SELL',
                base_size='1.0',
                limit_price='50000'
            )

            # Should fail due to insufficient balance
            assert result is None

    def test_order_size_below_minimum(self, mock_api_client, test_app_config):
        """Test that orders below minimum size are rejected."""
        mock_product = Mock()
        mock_product.base_min_size = '0.0001'  # Minimum 0.0001 BTC
        mock_product.base_max_size = '10000'
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock sufficient balance
        with patch.object(terminal, 'get_account_balance', return_value=1.0):
            # Try to sell below minimum
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='SELL',
                base_size='0.00001',  # Below minimum
                limit_price='50000'
            )

            # Should fail due to below minimum size
            assert result is None

    def test_order_size_above_maximum(self, mock_api_client, test_app_config):
        """Test that orders above maximum size are rejected."""
        mock_product = Mock()
        mock_product.base_min_size = '0.0001'
        mock_product.base_max_size = '100'  # Maximum 100 BTC
        mock_product.quote_increment = '0.01'
        mock_api_client.get_product.return_value = mock_product

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Mock sufficient balance
        with patch.object(terminal, 'get_account_balance', return_value=1000.0):
            # Try to sell above maximum
            result = terminal.place_limit_order_with_retry(
                product_id='BTC-USDC',
                side='SELL',
                base_size='200',  # Above maximum
                limit_price='50000'
            )

            # Should fail due to above maximum size
            assert result is None


# =============================================================================
# Dependency Injection Tests
# =============================================================================

@pytest.mark.unit
class TestDependencyInjection:
    """Tests for dependency injection in TradingTerminal."""

    def test_terminal_accepts_injected_api_client(self, mock_api_client, test_app_config):
        """Test that TradingTerminal accepts injected API client."""
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        assert terminal.client is mock_api_client

    def test_terminal_accepts_injected_storage(self, mock_api_client, mock_twap_storage, test_app_config):
        """Test that TradingTerminal accepts injected TWAP storage."""
        terminal = TradingTerminal(
            api_client=mock_api_client,
            twap_storage=mock_twap_storage,
            config=test_app_config,
            start_checker_thread=False
        )

        assert terminal.twap_storage is mock_twap_storage

    def test_terminal_accepts_injected_config(self, mock_api_client):
        """Test that TradingTerminal accepts injected configuration."""
        custom_config = AppConfig()

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=custom_config,
            start_checker_thread=False
        )

        assert terminal.config is custom_config

    def test_terminal_uses_defaults_when_none_injected(self):
        """Test that TradingTerminal creates defaults when nothing injected."""
        terminal = TradingTerminal(
            api_client=Mock(),  # Need at least an API client
            start_checker_thread=False
        )

        # Should have created default config and storage
        assert terminal.config is not None
        assert terminal.twap_storage is not None


# =============================================================================
# Account Caching Tests
# =============================================================================

@pytest.mark.unit
class TestAccountCaching:
    """Tests for account balance caching."""

    def test_account_balance_cached(self, mock_api_client, test_app_config):
        """Test that account balances are cached."""
        # Create mock account
        mock_account = Mock()
        mock_account.currency = 'BTC'
        mock_account.available_balance = {'value': '1.5', 'currency': 'BTC'}
        mock_account.type = 'CRYPTO'
        mock_account.ready = True
        mock_account.active = True

        mock_response = Mock()
        mock_response.accounts = [mock_account]
        mock_response.has_next = False
        mock_response.cursor = ''
        mock_api_client.get_accounts.return_value = mock_response

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Load accounts into cache
        terminal.get_accounts(force_refresh=True)

        # Get balance multiple times
        balance1 = terminal.get_account_balance('BTC')
        balance2 = terminal.get_account_balance('BTC')
        balance3 = terminal.get_account_balance('BTC')

        # Should all be the same
        assert balance1 == 1.5
        assert balance2 == 1.5
        assert balance3 == 1.5

        # get_accounts should only be called once (cached)
        assert mock_api_client.get_accounts.call_count == 1

    def test_nonexistent_currency_returns_zero(self, mock_api_client, test_app_config):
        """Test that balance for nonexistent currency returns 0."""
        mock_response = Mock()
        mock_response.accounts = []
        mock_response.has_next = False
        mock_response.cursor = ''
        mock_api_client.get_accounts.return_value = mock_response

        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Load accounts into cache
        terminal.get_accounts(force_refresh=True)

        # Get balance for currency that doesn't exist
        balance = terminal.get_account_balance('XYZ')

        assert balance == 0.0
