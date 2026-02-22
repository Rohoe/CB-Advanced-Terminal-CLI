"""
Integration tests using public Coinbase API endpoints (no auth required).

These tests validate real API response shapes against our Pydantic schemas
and verify OHLCV data integrity. They hit production public endpoints and
require no API keys, environment variables, or sandbox mode.

To run:
    pytest tests/integration/test_public_api.py -v

To skip (e.g., offline):
    pytest -m "not public_api"
"""

import pytest
import time

pytestmark = pytest.mark.public_api


@pytest.mark.integration
class TestPublicProducts:
    """Validate product endpoints against real production data."""

    def test_get_public_products(self, public_client):
        """get_public_products() returns a list with product_id and price."""
        response = public_client.get_public_products()

        products = response.get('products', []) if isinstance(response, dict) else getattr(response, 'products', [])
        assert len(products) > 0, "Expected at least one product"

        # Spot-check first product
        first = products[0]
        product_id = first.get('product_id') if isinstance(first, dict) else getattr(first, 'product_id', None)
        price = first.get('price') if isinstance(first, dict) else getattr(first, 'price', None)
        assert product_id is not None, "Product missing product_id"
        assert price is not None, "Product missing price"

    def test_get_public_product_btc_usd(self, public_client):
        """get_public_product('BTC-USD') returns increments and min size."""
        response = public_client.get_public_product('BTC-USD')

        def _get(key):
            return response.get(key) if isinstance(response, dict) else getattr(response, key, None)

        assert _get('product_id') == 'BTC-USD'
        assert _get('base_increment') is not None, "Missing base_increment"
        assert _get('quote_increment') is not None, "Missing quote_increment"
        assert _get('base_min_size') is not None, "Missing base_min_size"

        # Sanity: increments should be small positive numbers
        assert float(_get('base_increment')) > 0
        assert float(_get('quote_increment')) > 0
        assert float(_get('base_min_size')) > 0

    def test_get_public_product_book(self, public_client):
        """get_public_product_book('BTC-USD') returns bids and asks."""
        response = public_client.get_public_product_book('BTC-USD', limit=5)

        pricebook = response.get('pricebook') if isinstance(response, dict) else getattr(response, 'pricebook', None)
        assert pricebook is not None, "Missing pricebook"

        bids = pricebook.get('bids') if isinstance(pricebook, dict) else getattr(pricebook, 'bids', None)
        asks = pricebook.get('asks') if isinstance(pricebook, dict) else getattr(pricebook, 'asks', None)
        assert bids is not None and len(bids) > 0, "Expected at least one bid"
        assert asks is not None and len(asks) > 0, "Expected at least one ask"

        # Each entry should have price and size
        first_bid = bids[0]
        bid_price = first_bid.get('price') if isinstance(first_bid, dict) else getattr(first_bid, 'price', None)
        bid_size = first_bid.get('size') if isinstance(first_bid, dict) else getattr(first_bid, 'size', None)
        assert bid_price is not None, "Bid missing price"
        assert bid_size is not None, "Bid missing size"
        assert float(bid_price) > 0
        assert float(bid_size) > 0


@pytest.mark.integration
class TestPublicCandles:
    """Validate candle endpoints and OHLCV integrity."""

    def _fetch_candles(self, public_client, granularity='ONE_HOUR'):
        """Helper to fetch BTC-USD candles."""
        # Use window sizes that stay under the 350-candle API limit
        window_seconds = {
            'ONE_MINUTE': 300 * 60,      # 300 candles
            'FIVE_MINUTE': 300 * 5 * 60,  # 300 candles
            'ONE_HOUR': 86400,            # 24 candles
            'ONE_DAY': 86400 * 30,        # 30 candles
        }.get(granularity, 86400)
        end = str(int(time.time()))
        start = str(int(time.time()) - window_seconds)
        response = public_client.get_public_candles(
            product_id='BTC-USD',
            start=start,
            end=end,
            granularity=granularity,
        )
        if isinstance(response, dict):
            return response.get('candles', [])
        elif hasattr(response, 'candles'):
            return response.candles
        return list(response) if response else []

    def _candle_field(self, candle, field):
        """Extract field from candle (dict or object)."""
        if isinstance(candle, dict):
            return candle.get(field)
        return getattr(candle, field, None)

    def test_get_public_candles_one_hour(self, public_client):
        """Hourly candles have all OHLCV fields."""
        candles = self._fetch_candles(public_client)
        assert len(candles) > 0, "Expected at least one candle"

        candle = candles[0]
        for field in ('start', 'open', 'high', 'low', 'close', 'volume'):
            val = self._candle_field(candle, field)
            assert val is not None, f"Candle missing '{field}'"

    def test_candle_ohlcv_integrity(self, public_client):
        """OHLCV invariants: high >= low, high >= open/close, volume >= 0."""
        candles = self._fetch_candles(public_client)
        assert len(candles) > 0

        for candle in candles:
            o = float(self._candle_field(candle, 'open'))
            h = float(self._candle_field(candle, 'high'))
            l = float(self._candle_field(candle, 'low'))
            c = float(self._candle_field(candle, 'close'))
            v = float(self._candle_field(candle, 'volume'))

            assert h >= l, f"high ({h}) < low ({l})"
            assert h >= o, f"high ({h}) < open ({o})"
            assert h >= c, f"high ({h}) < close ({c})"
            assert l <= o, f"low ({l}) > open ({o})"
            assert l <= c, f"low ({l}) > close ({c})"
            assert v >= 0, f"volume ({v}) < 0"

    def test_get_public_candles_granularities(self, public_client):
        """Multiple granularities are accepted without error."""
        for granularity in ('ONE_MINUTE', 'FIVE_MINUTE', 'ONE_HOUR', 'ONE_DAY'):
            candles = self._fetch_candles(public_client, granularity=granularity)
            assert isinstance(candles, list), f"Expected list for {granularity}"
            # ONE_DAY may return fewer candles for a 24h window
            if granularity != 'ONE_DAY':
                assert len(candles) > 0, f"No candles returned for {granularity}"


@pytest.mark.integration
class TestPublicResponseSchemas:
    """Validate real responses against Pydantic schemas."""

    def test_product_matches_schema(self, public_client):
        """Real product response validates against Product schema."""
        from tests.schemas.api_responses import Product

        response = public_client.get_public_product('BTC-USD')
        data = response.to_dict() if hasattr(response, 'to_dict') else response

        validated = Product(**data)
        assert validated.product_id == 'BTC-USD'
        assert validated.base_increment is not None
        assert validated.quote_increment is not None

    def test_product_book_matches_schema(self, public_client):
        """Real product book has pricebook with bids/asks matching expected shape."""
        response = public_client.get_public_product_book('BTC-USD', limit=1)
        data = response.to_dict() if hasattr(response, 'to_dict') else response

        pricebook = data['pricebook']
        assert 'bids' in pricebook
        assert 'asks' in pricebook
        assert len(pricebook['bids']) > 0
        assert len(pricebook['asks']) > 0

        # Validate bid/ask entry shape
        bid = pricebook['bids'][0]
        assert 'price' in bid
        assert 'size' in bid
        assert float(bid['price']) > 0
        assert float(bid['size']) > 0
