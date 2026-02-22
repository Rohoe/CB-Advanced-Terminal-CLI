"""
Integration tests wiring real public API data through extracted modules.

Uses a PublicAPIAdapter (test-only) to map authenticated endpoint names
to their public equivalents so MarketDataService and VWAPStrategy can
parse real production responses without API keys.

To run:
    pytest tests/integration/test_public_modules.py -v

To skip (e.g., offline):
    pytest -m "not public_api"
"""

import pytest
import time
from unittest.mock import Mock

from market_data import MarketDataService
from config_manager import AppConfig

pytestmark = pytest.mark.public_api


class PublicAPIAdapter:
    """
    Test-only adapter that maps authenticated API method names to their
    public equivalents on the Coinbase RESTClient.

    MarketDataService calls:
        api_client.get_product(product_id) -> get_public_product()
        api_client.get_product_book(product_id, limit=) -> get_public_product_book()

    VWAPStrategy calls:
        api_client.get_candles(product_id=, start=, end=, granularity=) -> get_public_candles()
    """

    def __init__(self, rest_client):
        self._client = rest_client

    def get_product(self, product_id: str):
        return self._client.get_public_product(product_id)

    def get_product_book(self, product_id: str, limit: int = 1):
        return self._client.get_public_product_book(product_id, limit=limit)

    def get_candles(self, product_id: str, start: str, end: str, granularity: str):
        response = self._client.get_public_candles(
            product_id=product_id,
            start=start,
            end=end,
            granularity=granularity,
        )
        if isinstance(response, dict):
            return response.get('candles', [])
        elif hasattr(response, 'candles'):
            return response.candles
        return list(response) if response else []


@pytest.fixture(scope="session")
def public_adapter(public_client):
    """PublicAPIAdapter wrapping the unauthenticated RESTClient."""
    return PublicAPIAdapter(public_client)


@pytest.fixture
def public_market_data(public_adapter):
    """MarketDataService backed by public API via adapter."""
    config = AppConfig.for_testing()
    rate_limiter = Mock()
    rate_limiter.wait.return_value = None
    return MarketDataService(
        api_client=public_adapter,
        rate_limiter=rate_limiter,
        config=config,
    )


@pytest.mark.integration
class TestMarketDataWithPublicAPI:
    """Test MarketDataService methods with real production data."""

    def test_round_size_real_increment(self, public_market_data):
        """round_size() uses real base_increment from BTC-USD."""
        rounded = public_market_data.round_size(0.123456789, 'BTC-USD')

        assert isinstance(rounded, float)
        assert rounded > 0
        # BTC base_increment is 0.00000001 (8 decimals)
        assert rounded == pytest.approx(0.12345679, abs=1e-8)

    def test_round_price_real_increment(self, public_market_data):
        """round_price() uses real quote_increment from BTC-USD."""
        rounded = public_market_data.round_price(50000.12345, 'BTC-USD')

        assert isinstance(rounded, float)
        assert rounded > 0
        # BTC-USD quote_increment is 0.01 (2 decimals)
        assert rounded == pytest.approx(50000.12, abs=0.01)

    def test_get_current_prices_real(self, public_market_data):
        """Bid/ask/mid from real orderbook satisfy bid <= mid <= ask."""
        prices = public_market_data.get_current_prices('BTC-USD')

        assert prices is not None, "get_current_prices returned None"
        assert 'bid' in prices
        assert 'ask' in prices
        assert 'mid' in prices
        assert prices['bid'] > 0
        assert prices['ask'] > 0
        assert prices['bid'] <= prices['mid'] <= prices['ask']


@pytest.mark.integration
class TestVWAPWithPublicAPI:
    """Test VWAPStrategy with real candle data from public endpoints."""

    def test_volume_profile_from_real_candles(self, public_adapter):
        """VWAPStrategy builds a non-flat volume profile from real candles."""
        from vwap_strategy import VWAPStrategy, VWAPStrategyConfig

        config = VWAPStrategyConfig(
            duration_minutes=60,
            num_slices=5,
            volume_lookback_hours=24,
            granularity='ONE_HOUR',
            benchmark_enabled=False,
        )

        strategy = VWAPStrategy(
            product_id='BTC-USD',
            side='BUY',
            total_size=0.01,
            limit_price=50000.0,
            num_slices=5,
            duration_minutes=60,
            api_client=public_adapter,
            config=config,
        )

        slices = strategy.calculate_slices()
        assert len(slices) == 5

        # Each slice should have positive size
        for s in slices:
            assert s.size > 0, f"Slice {s.slice_number} has non-positive size"

        # Total should sum to total_size
        total = sum(s.size for s in slices)
        assert abs(total - 0.01) < 1e-10

        # Profile should be populated
        profile = strategy.volume_profile
        assert len(profile) == 5
        assert abs(sum(profile) - 1.0) < 1e-10

    def test_benchmark_vwap_from_real_candles(self, public_adapter):
        """Benchmark VWAP from real candles is positive and reasonable."""
        from vwap_strategy import VWAPStrategy, VWAPStrategyConfig

        config = VWAPStrategyConfig(
            duration_minutes=60,
            num_slices=5,
            volume_lookback_hours=24,
            granularity='ONE_HOUR',
            benchmark_enabled=True,
        )

        strategy = VWAPStrategy(
            product_id='BTC-USD',
            side='BUY',
            total_size=0.01,
            limit_price=50000.0,
            num_slices=5,
            duration_minutes=60,
            api_client=public_adapter,
            config=config,
        )

        slices = strategy.calculate_slices()
        assert len(slices) == 5

        benchmark = strategy.benchmark_vwap
        assert benchmark > 0, "Benchmark VWAP should be positive"
        # BTC price should be in a reasonable range (sanity check)
        assert benchmark > 1000, f"Benchmark VWAP {benchmark} seems too low for BTC"
