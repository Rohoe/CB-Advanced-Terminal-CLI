"""
Unit tests for candle functionality.

Tests cover get_candles OHLCV structure, generate_candles count and volume
shape, and empty results for unknown products.

To run:
    pytest tests/test_candles.py -v
"""

import pytest
from unittest.mock import Mock

from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


# =============================================================================
# get_candles OHLCV Structure Tests
# =============================================================================

@pytest.mark.unit
class TestGetCandlesStructure:
    """Tests that get_candles returns correct OHLCV structure."""

    def test_candle_has_all_ohlcv_fields(self):
        """Each candle should have start, open, high, low, close, volume."""
        api = MockCoinbaseAPI()
        api.generate_candles('BTC-USD', hours=1, granularity='ONE_HOUR', seed=42)

        import time
        end = str(int(time.time()))
        start = str(int(time.time()) - 7200)

        result = api.get_candles('BTC-USD', start=start, end=end, granularity='ONE_HOUR')

        assert hasattr(result, 'candles')
        assert len(result.candles) > 0

        candle = result.candles[0]
        for field in ['start', 'open', 'high', 'low', 'close', 'volume']:
            assert hasattr(candle, field), f"Candle missing field: {field}"

    def test_high_gte_open_and_close(self):
        """High should be >= both open and close for every candle."""
        api = MockCoinbaseAPI()
        api.generate_candles('BTC-USD', hours=4, granularity='ONE_HOUR', seed=42)

        import time
        end = str(int(time.time()))
        start = str(int(time.time()) - 20000)

        result = api.get_candles('BTC-USD', start=start, end=end, granularity='ONE_HOUR')

        for candle in result.candles:
            high = float(candle.high)
            low = float(candle.low)
            open_p = float(candle.open)
            close_p = float(candle.close)
            assert high >= open_p, f"High {high} < Open {open_p}"
            assert high >= close_p, f"High {high} < Close {close_p}"
            assert low <= open_p, f"Low {low} > Open {open_p}"
            assert low <= close_p, f"Low {low} > Close {close_p}"

    def test_candle_values_are_strings(self):
        """All candle values should be strings (SDK convention)."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles('BTC-USD', hours=1, granularity='ONE_HOUR', seed=42)

        for candle in candles:
            for field in ['start', 'open', 'high', 'low', 'close', 'volume']:
                assert isinstance(candle[field], str), f"{field} should be str, got {type(candle[field])}"


# =============================================================================
# generate_candles Count and Volume Shape Tests
# =============================================================================

@pytest.mark.unit
class TestGenerateCandlesCountAndVolume:
    """Tests for generate_candles expected count and U-shaped volume."""

    def test_hourly_candles_count_for_24h(self):
        """24 hours of ONE_HOUR candles should produce 24 candles."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles(
            'BTC-USD', hours=24, granularity='ONE_HOUR', seed=42
        )
        assert len(candles) == 24

    def test_five_minute_candles_count_for_1h(self):
        """1 hour of FIVE_MINUTE candles should produce 12 candles."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles(
            'BTC-USD', hours=1, granularity='FIVE_MINUTE', seed=42
        )
        assert len(candles) == 12

    def test_one_minute_candles_count_for_1h(self):
        """1 hour of ONE_MINUTE candles should produce 60 candles."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles(
            'BTC-USD', hours=1, granularity='ONE_MINUTE', seed=42
        )
        assert len(candles) == 60

    def test_u_shaped_volume_profile(self):
        """Volume at edges should be higher than volume in the middle."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles(
            'BTC-USD', hours=24, granularity='ONE_HOUR', seed=42
        )

        volumes = [float(c['volume']) for c in candles]

        # Average of first and last quarter vs middle half
        quarter = len(volumes) // 4
        edge_avg = (sum(volumes[:quarter]) + sum(volumes[-quarter:])) / (2 * quarter)
        middle_avg = sum(volumes[quarter:-quarter]) / (len(volumes) - 2 * quarter)

        assert edge_avg > middle_avg, (
            f"Edge average volume ({edge_avg:.2f}) should be > "
            f"middle average ({middle_avg:.2f}) for U-shaped profile"
        )

    def test_seed_produces_reproducible_results(self):
        """Same seed should produce identical candle data."""
        api1 = MockCoinbaseAPI()
        candles1 = api1.generate_candles('BTC-USD', hours=4, granularity='ONE_HOUR', seed=123)

        api2 = MockCoinbaseAPI()
        candles2 = api2.generate_candles('BTC-USD', hours=4, granularity='ONE_HOUR', seed=123)

        assert len(candles1) == len(candles2)
        for c1, c2 in zip(candles1, candles2):
            assert c1['open'] == c2['open']
            assert c1['close'] == c2['close']
            assert c1['volume'] == c2['volume']

    def test_volume_is_positive(self):
        """All generated volumes should be positive."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles('BTC-USD', hours=24, granularity='ONE_HOUR', seed=42)

        for candle in candles:
            assert float(candle['volume']) > 0

    def test_candles_stored_on_api(self):
        """generate_candles should also store candles on the API instance."""
        api = MockCoinbaseAPI()
        api.generate_candles('ETH-USD', hours=2, granularity='ONE_HOUR', seed=42)

        assert 'ETH-USD' in api.candles
        assert len(api.candles['ETH-USD']) == 2


# =============================================================================
# Empty Result for Unknown Product Tests
# =============================================================================

@pytest.mark.unit
class TestEmptyResultForUnknownProduct:
    """Tests that unknown products return empty candle data."""

    def test_get_candles_returns_empty_for_unknown_product(self):
        """get_candles for an unknown product should return empty candles list."""
        api = MockCoinbaseAPI()

        import time
        end = str(int(time.time()))
        start = str(int(time.time()) - 3600)

        result = api.get_candles('NONEXISTENT-PAIR', start=start, end=end, granularity='ONE_HOUR')

        assert hasattr(result, 'candles')
        assert len(result.candles) == 0

    def test_set_candles_then_retrieve(self):
        """Manually set candles should be retrievable via get_candles."""
        api = MockCoinbaseAPI()

        import time
        now = int(time.time())
        test_candles = [{
            'start': str(now - 3600),
            'open': '100.00',
            'high': '105.00',
            'low': '95.00',
            'close': '102.00',
            'volume': '500.0'
        }]
        api.set_candles('CUSTOM-PAIR', test_candles)

        start = str(now - 7200)
        end = str(now)
        result = api.get_candles('CUSTOM-PAIR', start=start, end=end, granularity='ONE_HOUR')

        assert len(result.candles) == 1
        assert result.candles[0].close == '102.00'

    def test_generate_candles_uses_product_price(self):
        """generate_candles should use the product's price as base_price."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles('ETH-USD', hours=1, granularity='ONE_HOUR', seed=42)

        # ETH-USD price in MockCoinbaseAPI is 3000.00
        first_open = float(candles[0]['open'])
        assert 2500 < first_open < 3500, f"Expected price near 3000, got {first_open}"

    def test_generate_candles_default_price_for_unknown(self):
        """Unknown product should default to 50000.0 as base price."""
        api = MockCoinbaseAPI()
        candles = api.generate_candles('UNKNOWN-PAIR', hours=1, granularity='ONE_HOUR', seed=42)

        first_open = float(candles[0]['open'])
        assert 40000 < first_open < 60000, f"Expected price near 50000, got {first_open}"
