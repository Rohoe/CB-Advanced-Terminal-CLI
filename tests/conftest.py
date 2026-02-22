"""
Pytest configuration and shared fixtures.

This file contains fixtures that are automatically discovered by pytest
and can be used in any test file. Fixtures help set up test data, mock
objects, and clean up after tests.

For more information on pytest fixtures:
https://docs.pytest.org/en/stable/fixture.html
"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, MagicMock
from typing import List

# Import from our modules
from api_client import APIClient
from storage import TWAPStorage, InMemoryTWAPStorage
from twap_tracker import TWAPOrder, OrderFill
from config import Config
from config_manager import AppConfig


# =============================================================================
# API Client Fixtures
# =============================================================================

@pytest.fixture
def mock_api_client():
    """
    Create a mock API client for testing.

    This fixture creates a mock object that implements the APIClient interface
    without making real API calls. It's set up with default responses that can
    be overridden in individual tests.

    Usage in tests:
        def test_something(mock_api_client):
            # The mock client is automatically injected
            # Override default behavior if needed
            mock_api_client.get_product.return_value = {'price': '100.00'}

            # Use the mock in your test
            price = mock_api_client.get_product('BTC-USD')['price']
            assert price == '100.00'

    Returns:
        Mock object configured with common API responses.
    """
    client = Mock(spec=APIClient)

    # Setup default account response
    client.get_accounts.return_value = Mock(
        accounts=[
            Mock(
                currency='BTC',
                available_balance={'value': '1.5', 'currency': 'BTC'},
                type='CRYPTO',
                ready=True,
                active=True
            ),
            Mock(
                currency='USDC',
                available_balance={'value': '10000', 'currency': 'USDC'},
                type='CRYPTO',
                ready=True,
                active=True
            )
        ],
        cursor='',
        has_next=False
    )

    # Setup default product response
    client.get_product.return_value = {
        'product_id': 'BTC-USDC',
        'price': '50000.00',
        'base_min_size': '0.0001',
        'base_max_size': '10000',
        'base_increment': '0.00000001',
        'quote_increment': '0.01',
        'volume_24h': '1000'
    }

    # Setup default product book response
    client.get_product_book.return_value = {
        'pricebook': {
            'bids': [{'price': '49995.00', 'size': '1.0'}],
            'asks': [{'price': '50005.00', 'size': '1.0'}]
        }
    }

    # Setup default products response
    client.get_products.return_value = {
        'products': [
            {'product_id': 'BTC-USD', 'price': '50000.00', 'volume_24h': '1000'},
            {'product_id': 'ETH-USD', 'price': '3000.00', 'volume_24h': '500'},
            {'product_id': 'SOL-USD', 'price': '100.00', 'volume_24h': '200'},
        ]
    }

    return client


# =============================================================================
# Storage Fixtures
# =============================================================================

@pytest.fixture
def mock_twap_storage():
    """
    Create an in-memory TWAP storage for testing.

    This fixture provides a clean, in-memory storage implementation that
    persists data only for the duration of the test. Each test gets a fresh
    storage instance automatically.

    Usage in tests:
        def test_save_order(mock_twap_storage, sample_twap_order):
            # Save an order
            mock_twap_storage.save_twap_order(sample_twap_order)

            # Verify it was saved
            loaded = mock_twap_storage.get_twap_order(sample_twap_order.twap_id)
            assert loaded.twap_id == sample_twap_order.twap_id

    Returns:
        InMemoryTWAPStorage instance.
    """
    return InMemoryTWAPStorage()


@pytest.fixture
def temp_storage_dir():
    """
    Create a temporary directory for file-based storage tests.

    This fixture creates a real temporary directory, yields it to the test,
    and automatically cleans it up after the test completes.

    Usage in tests:
        def test_file_storage(temp_storage_dir):
            # temp_storage_dir is a path to a temporary directory
            tracker = TWAPTracker(temp_storage_dir)
            # Use the tracker...
            # Directory is automatically cleaned up after test

    Yields:
        str: Path to temporary directory.
    """
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_twap_order():
    """
    Create a sample TWAP order for testing.

    This fixture provides a realistic TWAP order that can be used
    in tests without having to create one manually each time.

    Usage in tests:
        def test_order_processing(sample_twap_order):
            assert sample_twap_order.market == 'BTC-USDC'
            assert sample_twap_order.num_slices == 10

    Returns:
        TWAPOrder instance with sample data.
    """
    return TWAPOrder(
        twap_id='test-twap-123',
        market='BTC-USDC',
        side='BUY',
        total_size=1.0,
        limit_price=50000.0,
        num_slices=10,
        start_time='2025-01-01T00:00:00Z',
        status='active',
        orders=['order-1', 'order-2', 'order-3'],
        total_placed=0.3,
        total_filled=0.2,
        total_value_placed=15000.0,
        total_value_filled=10000.0,
        total_fees=5.0,
        maker_orders=1,
        taker_orders=1,
        failed_slices=[],
        slice_statuses=[]
    )


@pytest.fixture
def sample_order_fills():
    """
    Create sample order fills for testing.

    Returns:
        List of OrderFill instances.
    """
    return [
        OrderFill(
            order_id='order-1',
            trade_id='trade-1',
            filled_size=0.1,
            price=50000.0,
            fee=2.0,
            is_maker=True,
            trade_time='2025-01-01T00:00:00Z'
        ),
        OrderFill(
            order_id='order-2',
            trade_id='trade-2',
            filled_size=0.1,
            price=50100.0,
            fee=3.0,
            is_maker=False,
            trade_time='2025-01-01T00:01:00Z'
        )
    ]


@pytest.fixture
def sample_candle_data():
    """
    Create sample candle data (24h of hourly candles) for testing.

    Returns:
        List of candle dicts with OHLCV data.
    """
    import time

    base_price = 50000.0
    candles = []
    end_ts = int(time.time())
    start_ts = end_ts - (24 * 3600)

    for i in range(24):
        candle_start = start_ts + (i * 3600)
        # U-shaped volume profile
        position = i / 23.0
        u_factor = 1.0 + 2.0 * (2.0 * (position - 0.5)) ** 2
        volume = 100.0 * u_factor

        price_offset = (i - 12) * 10  # Simple linear price movement
        open_price = base_price + price_offset
        close_price = open_price + 5

        candles.append({
            'start': str(candle_start),
            'open': str(round(open_price, 2)),
            'high': str(round(max(open_price, close_price) + 20, 2)),
            'low': str(round(min(open_price, close_price) - 20, 2)),
            'close': str(round(close_price, 2)),
            'volume': str(round(volume, 4)),
        })

    return candles


# =============================================================================
# Configuration Fixtures
# =============================================================================

@pytest.fixture
def test_config():
    """
    Create a Config instance for testing (bypasses environment variables).

    This fixture provides test credentials that don't require environment
    variables to be set.

    Returns:
        Config instance with test credentials.
    """
    return Config.for_testing(
        api_key='test-api-key',
        api_secret='test-api-secret'
    )


@pytest.fixture
def test_app_config():
    """
    Create an AppConfig instance optimized for testing.

    This fixture provides configuration with shorter timeouts and TTLs
    for faster test execution.

    Returns:
        AppConfig instance configured for testing.
    """
    return AppConfig.for_testing()


# =============================================================================
# Helper Fixtures
# =============================================================================

@pytest.fixture
def mock_rate_limiter():
    """
    Create a mock rate limiter that doesn't actually delay.

    Useful for tests where you don't want rate limiting to slow down
    test execution.

    Returns:
        Mock RateLimiter that always permits requests immediately.
    """
    from app import RateLimiter

    limiter = Mock(spec=RateLimiter)
    limiter.acquire.return_value = True
    limiter.wait.return_value = None  # No delay
    return limiter


# =============================================================================
# Test Utilities
# =============================================================================

@pytest.fixture
def assert_valid_order():
    """
    Provide a helper function to validate order structure.

    Usage in tests:
        def test_create_order(assert_valid_order):
            order = create_some_order()
            assert_valid_order(order)

    Returns:
        Function that asserts order is valid.
    """
    def _assert(order_dict):
        """Assert that an order dictionary has required fields."""
        required_fields = ['order_id', 'product_id', 'side', 'size', 'price']
        for field in required_fields:
            assert field in order_dict, f"Order missing required field: {field}"
        return True

    return _assert


# =============================================================================
# Cleanup Hooks
# =============================================================================

@pytest.fixture(autouse=True)
def reset_environment():
    """
    Automatically reset environment between tests.

    This fixture runs before and after every test to ensure clean state.
    The autouse=True means it runs automatically without being requested.

    Yields:
        None (this is a setup/teardown fixture).
    """
    # Setup (before test)
    import os
    original_env = os.environ.copy()

    yield  # Test runs here

    # Teardown (after test)
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def terminal_with_mocks(mock_api_client, mock_twap_storage, test_app_config, mock_rate_limiter):
    """
    Fully configured TradingTerminal for integration tests.

    This fixture provides a TradingTerminal instance with all dependencies
    mocked out, making it suitable for integration testing without real API calls.

    Args:
        mock_api_client: Mocked API client fixture
        mock_twap_storage: In-memory TWAP storage fixture
        test_app_config: Test application config fixture
        mock_rate_limiter: Mocked rate limiter fixture

    Returns:
        TradingTerminal: Configured terminal instance ready for testing

    Usage in tests:
        def test_something(terminal_with_mocks):
            # Use the pre-configured terminal
            result = terminal_with_mocks.some_method()
            assert result is not None
    """
    from app import TradingTerminal

    terminal = TradingTerminal(
        api_client=mock_api_client,
        twap_storage=mock_twap_storage,
        config=test_app_config,
        start_checker_thread=False  # Disable background thread for most tests
    )
    terminal.rate_limiter = mock_rate_limiter

    return terminal


# =============================================================================
# VCR Fixtures for Recording API Responses
# =============================================================================

@pytest.fixture
def vcr_cassette_dir():
    """
    Directory for VCR cassettes.

    Returns:
        str: Path to cassette directory.
    """
    return 'tests/vcr_cassettes'


@pytest.fixture
def vcr_config():
    """
    VCR configuration dictionary.

    Returns:
        dict: VCR configuration options.
    """
    return {
        'cassette_library_dir': 'tests/vcr_cassettes',
        'record_mode': 'once',
        'match_on': ['method', 'scheme', 'host', 'port', 'path', 'query'],
        'filter_headers': ['authorization', 'Authorization', 'CB-ACCESS-KEY', 'CB-ACCESS-SIGN'],
        'decode_compressed_response': True,
        'serializer': 'yaml',
    }


@pytest.fixture
def api_vcr(vcr_config):
    """
    VCR instance for recording API calls.

    This fixture provides a pre-configured VCR instance that can be
    used to record and replay HTTP interactions with the Coinbase API.

    Usage:
        @api_vcr.use_cassette('my_test.yaml')
        def test_api_call(api_vcr):
            # API calls will be recorded/replayed
            response = client.get_accounts()

    Returns:
        vcr.VCR: Configured VCR instance.
    """
    import vcr
    return vcr.VCR(**vcr_config)


# =============================================================================
# Sandbox API Fixtures
# =============================================================================

@pytest.fixture
def sandbox_client():
    """
    Create API client pointing to Coinbase sandbox.

    The sandbox environment requires NO authentication and returns
    static, pre-defined responses.

    Returns:
        CoinbaseAPIClient: Client configured for sandbox environment.

    Note:
        This fixture requires COINBASE_SANDBOX_MODE=true to be set
        for integration tests to run.
    """
    from api_client import CoinbaseAPIClient

    return CoinbaseAPIClient(
        api_key='',  # Not required for sandbox
        api_secret='',  # Not required for sandbox
        base_url='api-sandbox.coinbase.com',
        verbose=True
    )


# =============================================================================
# Pytest Configuration Hooks
# =============================================================================

def pytest_configure(config):
    """
    Pytest configuration hook.

    This runs once before any tests and can be used to set up
    global test configuration.
    """
    # Add custom markers documentation
    config.addinivalue_line(
        "markers",
        "unit: marks tests as unit tests (fast, isolated)"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (slower, multiple components)"
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow running tests"
    )
    config.addinivalue_line(
        "markers",
        "security: marks tests as security-related tests"
    )
    config.addinivalue_line(
        "markers",
        "sandbox: marks tests as sandbox integration tests (requires COINBASE_SANDBOX_MODE=true)"
    )
    config.addinivalue_line(
        "markers",
        "vcr: marks tests that use VCR.py for recording/replaying API calls"
    )


def pytest_collection_modifyitems(config, items):
    """
    Modify test items after collection.

    This can be used to automatically add markers to tests based on
    their location or name.
    """
    for item in items:
        # Auto-mark tests in integration/ directory
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        # Auto-mark slow tests
        elif "slow" in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
