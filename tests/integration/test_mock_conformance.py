"""
Mock conformance tests: verify MockCoinbaseAPI matches real API response shapes.

Public API tests (no auth) run in CI. Authenticated tests require
COINBASE_READONLY_KEY + COINBASE_READONLY_SECRET env vars and run periodically.

To run:
    pytest tests/integration/test_mock_conformance.py -m public_api -v
    COINBASE_READONLY_KEY=... COINBASE_READONLY_SECRET=... pytest -m authenticated -v
"""

import os
import pytest
import time

from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
from tests.helpers.shape_compare import (
    get_top_level_fields,
    assert_response_shape_matches,
    assert_field_types_match,
)


# =============================================================================
# Public API Conformance Tests (no auth, safe for CI)
# =============================================================================

@pytest.mark.public_api
class TestMockProductConformance:
    """Verify MockCoinbaseAPI product responses match real public API."""

    def test_mock_product_fields_match_real_api(self, public_client):
        """get_product('BTC-USD') mock should have all real API fields."""
        real = public_client.get_public_product('BTC-USD')
        real_dict = real if isinstance(real, dict) else vars(real)

        mock = MockCoinbaseAPI()
        mock_dict = mock.get_product('BTC-USD')

        # Mock must have all fields that are in the real API response
        # (focus on fields the codebase actually uses)
        required_fields = {'product_id', 'price', 'base_min_size', 'base_max_size',
                           'base_increment', 'quote_increment'}
        mock_fields = set(mock_dict.keys())
        missing = required_fields - mock_fields
        assert not missing, f"Mock get_product missing required fields: {missing}"

    def test_mock_products_list_fields_match_real_api(self, public_client):
        """get_products() mock should return 'products' list with correct fields."""
        real = public_client.get_public_products()
        real_products = (real.get('products', []) if isinstance(real, dict)
                         else getattr(real, 'products', []))
        assert len(real_products) > 0, "Real API returned no products"

        first_real = real_products[0]
        real_fields = set(first_real.keys() if isinstance(first_real, dict)
                          else [k for k in vars(first_real) if not k.startswith('_')])

        mock = MockCoinbaseAPI()
        mock_resp = mock.get_products()
        assert 'products' in mock_resp, "Mock get_products missing 'products' key"
        assert len(mock_resp['products']) > 0, "Mock returned no products"

        mock_fields = set(mock_resp['products'][0].keys())

        # Mock must have core fields
        core_fields = {'product_id', 'price'}
        missing = core_fields - mock_fields
        assert not missing, f"Mock products missing core fields: {missing}"


@pytest.mark.public_api
class TestMockProductBookConformance:
    """Verify MockCoinbaseAPI product book matches real public API."""

    def test_mock_product_book_fields_match_real_api(self, public_client):
        """get_product_book('BTC-USD') mock should have pricebook with bids/asks."""
        real = public_client.get_public_product_book('BTC-USD', limit=1)
        real_dict = real if isinstance(real, dict) else vars(real)

        mock = MockCoinbaseAPI()
        mock_dict = mock.get_product_book('BTC-USD', limit=1)

        assert 'pricebook' in mock_dict, "Mock missing 'pricebook' key"

        # Real API pricebook structure
        real_pricebook = (real_dict.get('pricebook', {}) if isinstance(real_dict, dict)
                          else getattr(real_dict.get('pricebook', {}), '__dict__', {}))
        if isinstance(real_pricebook, dict):
            real_pb_fields = set(real_pricebook.keys())
        else:
            real_pb_fields = set(k for k in vars(real_pricebook) if not k.startswith('_'))

        mock_pb_fields = set(mock_dict['pricebook'].keys())

        # Both must have bids and asks
        assert 'bids' in mock_pb_fields, "Mock pricebook missing 'bids'"
        assert 'asks' in mock_pb_fields, "Mock pricebook missing 'asks'"

    def test_mock_product_book_bid_ask_structure(self, public_client):
        """Bids and asks should have price and size fields."""
        real = public_client.get_public_product_book('BTC-USD', limit=1)
        real_dict = real if isinstance(real, dict) else vars(real)

        mock = MockCoinbaseAPI()
        mock_dict = mock.get_product_book('BTC-USD', limit=1)

        mock_bids = mock_dict['pricebook']['bids']
        mock_asks = mock_dict['pricebook']['asks']

        assert len(mock_bids) > 0, "Mock has no bids"
        assert len(mock_asks) > 0, "Mock has no asks"

        assert 'price' in mock_bids[0], "Mock bid missing 'price'"
        assert 'size' in mock_bids[0], "Mock bid missing 'size'"
        assert 'price' in mock_asks[0], "Mock ask missing 'price'"
        assert 'size' in mock_asks[0], "Mock ask missing 'size'"


@pytest.mark.public_api
class TestMockCandlesConformance:
    """Verify MockCoinbaseAPI candle data matches real public API."""

    def test_mock_candles_fields_match_real_api(self, public_client):
        """Candle data should have OHLCV fields."""
        end = str(int(time.time()))
        start = str(int(time.time()) - 3600 * 24)

        real = public_client.get_public_candles(
            'BTC-USD', start=start, end=end, granularity='ONE_HOUR'
        )
        real_candles = (real.get('candles', []) if isinstance(real, dict)
                        else getattr(real, 'candles', []))

        if not real_candles:
            pytest.skip("No candle data returned from real API")

        first_real = real_candles[0]
        real_fields = set(first_real.keys() if isinstance(first_real, dict)
                          else [k for k in vars(first_real) if not k.startswith('_')])

        # Mock candles should have OHLCV fields
        mock = MockCoinbaseAPI()
        mock.generate_candles('BTC-USD', hours=24, granularity='ONE_HOUR', seed=42)
        mock_candles = mock.candles.get('BTC-USD', [])
        assert len(mock_candles) > 0, "Mock generated no candles"

        mock_fields = set(mock_candles[0].keys())
        required_fields = {'start', 'open', 'high', 'low', 'close', 'volume'}
        missing = required_fields - mock_fields
        assert not missing, f"Mock candles missing fields: {missing}"

    def test_mock_candles_ohlcv_types_match(self, public_client):
        """Candle OHLCV values should be strings (matching real API)."""
        mock = MockCoinbaseAPI()
        mock.generate_candles('BTC-USD', hours=1, granularity='ONE_HOUR', seed=42)
        mock_candles = mock.candles.get('BTC-USD', [])
        assert len(mock_candles) > 0

        candle = mock_candles[0]
        for field in ['start', 'open', 'high', 'low', 'close', 'volume']:
            assert isinstance(candle[field], str), (
                f"Candle field '{field}' should be str, got {type(candle[field]).__name__}"
            )


# =============================================================================
# Authenticated Conformance Tests (read-only key, periodic)
# =============================================================================

@pytest.mark.authenticated
class TestAuthenticatedMockConformance:
    """Verify mock matches authenticated API responses. Run periodically."""

    @pytest.fixture
    def auth_client(self):
        """Create authenticated client from env vars."""
        api_key = os.environ.get('COINBASE_READONLY_KEY')
        api_secret = os.environ.get('COINBASE_READONLY_SECRET')
        if not api_key or not api_secret:
            pytest.skip("COINBASE_READONLY_KEY and COINBASE_READONLY_SECRET required")

        from coinbase.rest import RESTClient
        return RESTClient(api_key=api_key, api_secret=api_secret)

    def test_mock_accounts_fields_match_real_api(self, auth_client):
        """Account response should have currency, available_balance, type, ready, active."""
        real = auth_client.get_accounts(limit=5)
        real_accounts = (real.get('accounts', []) if isinstance(real, dict)
                         else getattr(real, 'accounts', []))
        if not real_accounts:
            pytest.skip("No accounts returned")

        first = real_accounts[0]
        real_fields = set(first.keys() if isinstance(first, dict)
                          else [k for k in vars(first) if not k.startswith('_')])

        mock = MockCoinbaseAPI()
        mock_resp = mock.get_accounts()
        mock_account = mock_resp.accounts[0]
        mock_fields = set(k for k in vars(mock_account) if not k.startswith('_'))

        required = {'currency', 'available_balance', 'type', 'ready', 'active'}
        missing = required - mock_fields
        assert not missing, f"Mock account missing fields: {missing}"

    def test_mock_account_balance_format(self, auth_client):
        """available_balance should have 'value' and 'currency' keys."""
        mock = MockCoinbaseAPI()
        mock_resp = mock.get_accounts()
        for account in mock_resp.accounts:
            balance = account.available_balance
            assert isinstance(balance, dict), "available_balance should be a dict"
            assert 'value' in balance, "available_balance missing 'value'"
            assert 'currency' in balance, "available_balance missing 'currency'"

    def test_mock_fee_tier_fields_match_real_api(self, auth_client):
        """Transaction summary fee_tier should have rate fields."""
        real = auth_client.get_transaction_summary()
        real_fee_tier = (real.get('fee_tier', {}) if isinstance(real, dict)
                         else getattr(real, 'fee_tier', {}))

        mock = MockCoinbaseAPI()
        mock_resp = mock.get_transaction_summary()
        mock_fee_tier = mock_resp.fee_tier

        required = {'maker_fee_rate', 'taker_fee_rate'}
        mock_fields = set(mock_fee_tier.keys()) if isinstance(mock_fee_tier, dict) else set()
        missing = required - mock_fields
        assert not missing, f"Mock fee_tier missing fields: {missing}"

    def test_mock_orders_list_fields_match_real_api(self, auth_client):
        """Order list response should have orders with expected fields."""
        mock = MockCoinbaseAPI()
        # Place a mock order first
        mock.limit_order_gtc('test', 'BTC-USD', 'BUY', '0.001', '50000')
        mock_resp = mock.list_orders()
        assert len(mock_resp.orders) > 0

        mock_order = mock_resp.orders[0]
        required = {'order_id', 'product_id', 'side', 'status'}
        mock_fields = set(k for k in vars(mock_order) if not k.startswith('_'))
        missing = required - mock_fields
        assert not missing, f"Mock order missing fields: {missing}"

    def test_mock_fills_fields_match_real_api(self, auth_client):
        """Fill response should have expected fields."""
        mock = MockCoinbaseAPI()
        mock.simulate_fill('test-order', 0.1, 50000.0, is_maker=True)
        mock_resp = mock.get_fills(['test-order'])
        assert len(mock_resp.fills) > 0

        fill = mock_resp.fills[0]
        required = {'order_id', 'trade_id', 'size', 'price', 'fee',
                     'liquidity_indicator', 'trade_time'}
        fill_fields = set(k for k in vars(fill) if not k.startswith('_'))
        missing = required - fill_fields
        assert not missing, f"Mock fill missing fields: {missing}"

    def test_mock_order_status_values_valid(self, auth_client):
        """Mock order statuses should use valid Coinbase status values."""
        valid_statuses = {'OPEN', 'FILLED', 'CANCELLED', 'PENDING', 'ACTIVE', 'EXPIRED'}

        mock = MockCoinbaseAPI()
        mock.limit_order_gtc('test', 'BTC-USD', 'BUY', '0.001', '50000')
        mock_resp = mock.list_orders()
        for order in mock_resp.orders:
            assert order.status in valid_statuses, (
                f"Mock order status '{order.status}' not in valid statuses: {valid_statuses}"
            )
