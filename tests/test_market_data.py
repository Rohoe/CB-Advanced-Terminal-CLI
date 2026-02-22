"""
Unit tests for MarketDataService (market_data.py).

Tests cover caching, bulk price fetching, mid-price calculation,
precision rounding, and batch fill checking.

To run:
    pytest tests/test_market_data.py -v
"""

import pytest
import time
from unittest.mock import Mock, patch

from market_data import MarketDataService
from config_manager import AppConfig
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


# =============================================================================
# Helpers
# =============================================================================

def _make_service(api_client=None, rate_limiter=None, config=None):
    """Build a MarketDataService wired to mocks."""
    api = api_client or MockCoinbaseAPI()
    rl = rate_limiter or Mock(wait=Mock(return_value=None))
    cfg = config or AppConfig.for_testing()
    return MarketDataService(api_client=api, rate_limiter=rl, config=cfg)


# =============================================================================
# Account Cache TTL Tests
# =============================================================================

@pytest.mark.unit
class TestAccountCacheTTL:
    """Tests for account cache time-to-live behaviour."""

    def test_accounts_fetched_on_first_call(self):
        """First call should hit the API and populate the cache."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        accounts = svc.get_accounts()

        assert 'BTC' in accounts
        assert 'USDC' in accounts

    def test_accounts_served_from_cache_within_ttl(self):
        """Subsequent calls within TTL should not hit the API again."""
        api = Mock(spec=MockCoinbaseAPI)
        mock_account = Mock(
            currency='BTC',
            available_balance={'value': '1.0', 'currency': 'BTC'},
            type='CRYPTO', ready=True, active=True
        )
        mock_response = Mock(accounts=[mock_account], cursor='', has_next=False)
        api.get_accounts.return_value = mock_response

        svc = _make_service(api_client=api)

        svc.get_accounts()
        svc.get_accounts()

        assert api.get_accounts.call_count == 1

    def test_accounts_refreshed_after_ttl_expires(self):
        """After TTL expires, the API should be called again."""
        api = Mock(spec=MockCoinbaseAPI)
        mock_account = Mock(
            currency='BTC',
            available_balance={'value': '1.0', 'currency': 'BTC'},
            type='CRYPTO', ready=True, active=True
        )
        mock_response = Mock(accounts=[mock_account], cursor='', has_next=False)
        api.get_accounts.return_value = mock_response

        cfg = AppConfig.for_testing()
        cfg.cache.account_ttl = 0  # Expire immediately
        svc = _make_service(api_client=api, config=cfg)

        svc.get_accounts()
        time.sleep(0.01)
        svc.get_accounts()

        assert api.get_accounts.call_count == 2

    def test_force_refresh_bypasses_cache(self):
        """force_refresh=True should always hit the API."""
        api = Mock(spec=MockCoinbaseAPI)
        mock_account = Mock(
            currency='BTC',
            available_balance={'value': '2.0', 'currency': 'BTC'},
            type='CRYPTO', ready=True, active=True
        )
        mock_response = Mock(accounts=[mock_account], cursor='', has_next=False)
        api.get_accounts.return_value = mock_response

        svc = _make_service(api_client=api)

        svc.get_accounts(force_refresh=True)
        svc.get_accounts(force_refresh=True)

        assert api.get_accounts.call_count == 2

    def test_get_account_balance_returns_zero_for_unknown(self):
        """Unknown currency should return 0."""
        svc = _make_service()
        balance = svc.get_account_balance('DOESNOTEXIST')
        assert balance == 0


# =============================================================================
# Bulk Price Fetching Tests
# =============================================================================

@pytest.mark.unit
class TestBulkPriceFetching:
    """Tests for get_bulk_prices."""

    def test_returns_requested_prices(self):
        """Should return prices for requested product IDs."""
        api = Mock()
        p1 = Mock(product_id='BTC-USD', price='50000.00')
        p2 = Mock(product_id='ETH-USD', price='3000.00')
        p3 = Mock(product_id='SOL-USD', price='100.00')
        api.get_products.return_value = Mock(products=[p1, p2, p3])

        svc = _make_service(api_client=api)
        prices = svc.get_bulk_prices(['BTC-USD', 'ETH-USD'])

        assert prices['BTC-USD'] == 50000.0
        assert prices['ETH-USD'] == 3000.0
        assert 'SOL-USD' not in prices

    def test_returns_empty_dict_on_api_error(self):
        """API errors should return an empty dict instead of raising."""
        api = Mock()
        api.get_products.side_effect = RuntimeError("API down")

        svc = _make_service(api_client=api)
        prices = svc.get_bulk_prices(['BTC-USD'])

        assert prices == {}

    def test_handles_dict_response_without_products_attr(self):
        """get_products returning a plain dict should yield empty prices."""
        api = Mock()
        api.get_products.return_value = {'products': []}

        svc = _make_service(api_client=api)
        prices = svc.get_bulk_prices(['BTC-USD'])

        assert prices == {}


# =============================================================================
# Mid-Price Calculation Tests
# =============================================================================

@pytest.mark.unit
class TestMidPriceCalculation:
    """Tests for get_current_prices mid-price calculation."""

    def test_mid_price_is_average_of_bid_ask(self):
        """Mid price should be (bid + ask) / 2."""
        api = MockCoinbaseAPI()
        api.order_books['BTC-USD'] = {
            'pricebook': {
                'bids': [{'price': '49990.00', 'size': '1.0'}],
                'asks': [{'price': '50010.00', 'size': '1.0'}]
            }
        }
        svc = _make_service(api_client=api)
        result = svc.get_current_prices('BTC-USD')

        assert result is not None
        assert result['bid'] == 49990.0
        assert result['ask'] == 50010.0
        assert result['mid'] == pytest.approx(50000.0)

    def test_returns_none_on_missing_product(self):
        """Should return None when product book is unavailable."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        result = svc.get_current_prices('NONEXISTENT-PAIR')
        assert result is None


# =============================================================================
# Rounding Tests
# =============================================================================

@pytest.mark.unit
class TestRounding:
    """Tests for round_size and round_price with product increments."""

    def test_round_size_8_decimal_places(self):
        """Size should be rounded to the precision implied by base_increment."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        rounded = svc.round_size(1.123456789, 'BTC-USD')
        assert rounded == pytest.approx(1.12345678, rel=1e-8)

    def test_round_size_4_decimal_places(self):
        """SOL has 4 decimal base_increment."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        rounded = svc.round_size(1.23456, 'SOL-USD')
        assert rounded == pytest.approx(1.2346, rel=1e-4)

    def test_round_price_2_decimal_places(self):
        """Price with quote_increment 0.01 should round to 2 decimals."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        rounded = svc.round_price(50000.567, 'BTC-USD')
        assert rounded == 50000.57

    def test_round_price_already_valid(self):
        """Already-valid price should remain unchanged."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        rounded = svc.round_price(50000.01, 'BTC-USD')
        assert rounded == 50000.01

    def test_round_size_fallback_on_api_error(self):
        """If API call fails, precision_config overrides should be used."""
        api = Mock()
        api.get_product.side_effect = RuntimeError("API error")

        svc = _make_service(api_client=api)
        # BTC-USD is in the default precision overrides
        rounded = svc.round_size(1.123456789, 'BTC-USD')
        assert rounded == pytest.approx(1.12345679, rel=1e-8)

    def test_round_price_fallback_on_api_error(self):
        """If API call fails, precision_config overrides should be used."""
        api = Mock()
        api.get_product.side_effect = RuntimeError("API error")

        svc = _make_service(api_client=api)
        rounded = svc.round_price(50000.567, 'BTC-USD')
        assert rounded == 50000.57


# =============================================================================
# Batch Fill Checking Tests
# =============================================================================

@pytest.mark.unit
class TestBatchFillChecking:
    """Tests for check_order_fills_batch."""

    def test_returns_fills_grouped_by_order(self):
        """Should return fill data keyed by order ID."""
        api = MockCoinbaseAPI()
        api.simulate_fill('order-1', 0.1, 50000.0, is_maker=True)
        api.simulate_fill('order-2', 0.2, 3000.0, is_maker=False)

        svc = _make_service(api_client=api)
        result = svc.check_order_fills_batch(['order-1', 'order-2'])

        assert 'order-1' in result
        assert result['order-1']['filled_size'] == pytest.approx(0.1)
        assert result['order-1']['status'] == 'FILLED'

        assert 'order-2' in result
        assert result['order-2']['filled_size'] == pytest.approx(0.2)

    def test_returns_empty_for_no_fills(self):
        """Orders with no fills should not appear in the result."""
        api = MockCoinbaseAPI()
        svc = _make_service(api_client=api)

        result = svc.check_order_fills_batch(['nonexistent-order'])
        assert result == {} or 'nonexistent-order' not in result

    def test_returns_empty_for_empty_input(self):
        """Empty order list should return an empty dict."""
        svc = _make_service()
        result = svc.check_order_fills_batch([])
        assert result == {}

    def test_average_price_calculated_correctly(self):
        """Average price should be total_value / total_size."""
        api = MockCoinbaseAPI()
        api.simulate_fill('order-1', 0.5, 50000.0, is_maker=True)
        api.simulate_fill('order-1', 0.5, 52000.0, is_maker=False)

        svc = _make_service(api_client=api)
        result = svc.check_order_fills_batch(['order-1'])

        expected_avg = (0.5 * 50000.0 + 0.5 * 52000.0) / 1.0
        assert result['order-1']['average_price'] == pytest.approx(expected_avg)
