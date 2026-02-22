"""
Unit tests for TWAPStrategy (twap_strategy.py).

Tests cover:
- Uniform interval calculation without jitter
- Jitter stays within bounds (fixed seed)
- All 4 price types (limit, bid, mid, ask)
- Participation rate cap skip/allow logic
- on_slice_complete tracks fills and failures

To run:
    pytest tests/test_twap_strategy.py -v
"""

import pytest
import time
from unittest.mock import Mock, patch

from twap_strategy import TWAPStrategy
from order_strategy import SliceSpec, StrategyStatus
from config_manager import AppConfig, TWAPConfig


# =============================================================================
# Helpers
# =============================================================================

def _make_config(**twap_overrides) -> AppConfig:
    """Create a test AppConfig with optional TWAP config overrides."""
    config = AppConfig.for_testing()
    for key, value in twap_overrides.items():
        setattr(config.twap, key, value)
    return config


def _make_strategy(
    num_slices=5,
    duration_minutes=10,
    price_type='limit',
    seed=42,
    config=None,
    api_client=None,
    **kwargs,
) -> TWAPStrategy:
    """Create a TWAPStrategy with sensible defaults for testing."""
    return TWAPStrategy(
        product_id=kwargs.get('product_id', 'BTC-USDC'),
        side=kwargs.get('side', 'BUY'),
        total_size=kwargs.get('total_size', 1.0),
        limit_price=kwargs.get('limit_price', 50000.0),
        num_slices=num_slices,
        duration_minutes=duration_minutes,
        price_type=price_type,
        config=config or _make_config(),
        api_client=api_client,
        seed=seed,
    )


# =============================================================================
# Uniform Intervals Without Jitter
# =============================================================================

@pytest.mark.unit
class TestCalculateSlicesUniform:
    """Tests for uniform slice timing without jitter."""

    @patch('twap_strategy.time')
    def test_correct_number_of_slices(self, mock_time):
        """calculate_slices should return exactly num_slices slices."""
        mock_time.time.return_value = 1000000.0
        strategy = _make_strategy(num_slices=5, duration_minutes=10)
        slices = strategy.calculate_slices()
        assert len(slices) == 5

    @patch('twap_strategy.time')
    def test_uniform_slice_sizes(self, mock_time):
        """All slices should have equal size = total_size / num_slices."""
        mock_time.time.return_value = 1000000.0
        strategy = _make_strategy(num_slices=4, total_size=2.0)
        slices = strategy.calculate_slices()
        for s in slices:
            assert s.size == pytest.approx(0.5)

    @patch('twap_strategy.time')
    def test_uniform_intervals_no_jitter(self, mock_time):
        """Without jitter, intervals should be perfectly uniform."""
        mock_time.time.return_value = 1000000.0
        config = _make_config(jitter_pct=0.0)
        strategy = _make_strategy(
            num_slices=4, duration_minutes=8, config=config
        )
        slices = strategy.calculate_slices()

        # 8 minutes / 4 slices = 120 seconds per interval
        expected_interval = 120.0
        for i in range(1, len(slices)):
            actual_interval = slices[i].scheduled_time - slices[i - 1].scheduled_time
            assert actual_interval == pytest.approx(expected_interval)

    @patch('twap_strategy.time')
    def test_slice_numbers_are_1_based(self, mock_time):
        """Slice numbers should be 1-based."""
        mock_time.time.return_value = 1000000.0
        strategy = _make_strategy(num_slices=3)
        slices = strategy.calculate_slices()
        assert [s.slice_number for s in slices] == [1, 2, 3]

    @patch('twap_strategy.time')
    def test_first_slice_at_start_time(self, mock_time):
        """First slice should be scheduled at the start time."""
        mock_time.time.return_value = 1000000.0
        strategy = _make_strategy(num_slices=3, duration_minutes=6)
        slices = strategy.calculate_slices()
        assert slices[0].scheduled_time == pytest.approx(1000000.0)

    @patch('twap_strategy.time')
    def test_price_type_propagated_to_slices(self, mock_time):
        """Slice price_type should match strategy price_type."""
        mock_time.time.return_value = 1000000.0
        strategy = _make_strategy(price_type='mid')
        slices = strategy.calculate_slices()
        for s in slices:
            assert s.price_type == 'mid'


# =============================================================================
# Jitter Within Bounds
# =============================================================================

@pytest.mark.unit
class TestJitter:
    """Tests for jitter on slice timing."""

    @patch('twap_strategy.time')
    def test_jitter_within_bounds(self, mock_time):
        """Jittered intervals should stay within +/- jitter_pct of the base interval."""
        mock_time.time.return_value = 1000000.0
        config = _make_config(jitter_pct=0.1)  # 10% jitter
        strategy = _make_strategy(
            num_slices=10, duration_minutes=10, config=config, seed=42
        )
        slices = strategy.calculate_slices()

        base_interval = (10 * 60) / 10  # 60 seconds
        max_jitter = base_interval * 0.1  # 6 seconds

        # First slice has no jitter
        assert slices[0].scheduled_time == pytest.approx(1000000.0)

        # Subsequent slices should be within bounds of their nominal time
        for i in range(1, len(slices)):
            nominal_time = 1000000.0 + (i * base_interval)
            actual_time = slices[i].scheduled_time
            deviation = actual_time - nominal_time
            assert abs(deviation) <= max_jitter + 0.001, (
                f"Slice {i+1}: deviation {deviation:.3f}s exceeds max {max_jitter:.3f}s"
            )

    @patch('twap_strategy.time')
    def test_jitter_reproducible_with_seed(self, mock_time):
        """Same seed should produce identical jitter."""
        mock_time.time.return_value = 1000000.0
        config = _make_config(jitter_pct=0.2)

        strategy1 = _make_strategy(num_slices=5, config=config, seed=123)
        slices1 = strategy1.calculate_slices()

        strategy2 = _make_strategy(num_slices=5, config=config, seed=123)
        slices2 = strategy2.calculate_slices()

        for s1, s2 in zip(slices1, slices2):
            assert s1.scheduled_time == pytest.approx(s2.scheduled_time)

    @patch('twap_strategy.time')
    def test_different_seeds_produce_different_jitter(self, mock_time):
        """Different seeds should produce different jitter values."""
        mock_time.time.return_value = 1000000.0
        config = _make_config(jitter_pct=0.2)

        strategy1 = _make_strategy(num_slices=5, config=config, seed=1)
        slices1 = strategy1.calculate_slices()

        strategy2 = _make_strategy(num_slices=5, config=config, seed=999)
        slices2 = strategy2.calculate_slices()

        # At least one slice should differ (extremely unlikely to be identical)
        any_different = False
        for s1, s2 in zip(slices1[1:], slices2[1:]):
            if abs(s1.scheduled_time - s2.scheduled_time) > 0.001:
                any_different = True
                break
        assert any_different

    @patch('twap_strategy.time')
    def test_no_jitter_on_first_slice(self, mock_time):
        """First slice should never have jitter applied."""
        mock_time.time.return_value = 1000000.0
        config = _make_config(jitter_pct=0.5)  # Large jitter
        strategy = _make_strategy(num_slices=5, config=config, seed=42)
        slices = strategy.calculate_slices()
        assert slices[0].scheduled_time == pytest.approx(1000000.0)


# =============================================================================
# All 4 Price Types
# =============================================================================

@pytest.mark.unit
class TestGetExecutionPrice:
    """Tests for get_execution_price with all 4 price types."""

    def _market_data(self):
        return {'bid': 49990.0, 'ask': 50010.0, 'mid': 50000.0}

    def _slice_spec(self, price_type):
        return SliceSpec(
            slice_number=1, size=0.1, price=50000.0,
            scheduled_time=0, price_type=price_type
        )

    def test_limit_price_type(self):
        """'limit' should return the strategy's limit_price."""
        strategy = _make_strategy(price_type='limit', limit_price=48000.0)
        price = strategy.get_execution_price(
            self._slice_spec('limit'), self._market_data()
        )
        assert price == pytest.approx(48000.0)

    def test_bid_price_type(self):
        """'bid' should return the market bid price."""
        strategy = _make_strategy(price_type='bid')
        price = strategy.get_execution_price(
            self._slice_spec('bid'), self._market_data()
        )
        assert price == pytest.approx(49990.0)

    def test_mid_price_type(self):
        """'mid' should return the market mid price."""
        strategy = _make_strategy(price_type='mid')
        price = strategy.get_execution_price(
            self._slice_spec('mid'), self._market_data()
        )
        assert price == pytest.approx(50000.0)

    def test_ask_price_type(self):
        """'ask' should return the market ask price."""
        strategy = _make_strategy(price_type='ask')
        price = strategy.get_execution_price(
            self._slice_spec('ask'), self._market_data()
        )
        assert price == pytest.approx(50010.0)

    def test_unknown_price_type_falls_back_to_limit(self):
        """Unknown price_type should fall back to limit_price."""
        strategy = _make_strategy(price_type='unknown', limit_price=45000.0)
        price = strategy.get_execution_price(
            SliceSpec(
                slice_number=1, size=0.1, price=45000.0,
                scheduled_time=0, price_type='unknown'
            ),
            self._market_data(),
        )
        assert price == pytest.approx(45000.0)


# =============================================================================
# Participation Rate Cap
# =============================================================================

@pytest.mark.unit
class TestParticipationRateCap:
    """Tests for should_skip_slice with participation rate cap."""

    def test_no_cap_never_skips(self):
        """With cap=0.0 (disabled), should never skip."""
        config = _make_config(participation_rate_cap=0.0)
        strategy = _make_strategy(config=config)
        assert strategy.should_skip_slice(1, {'recent_volume': 100.0}) is False

    def test_skip_when_over_cap(self):
        """Should skip when slice_size / recent_volume > cap."""
        config = _make_config(participation_rate_cap=0.05)  # 5%
        # total_size=1.0, num_slices=5, so slice_size=0.2
        # recent_volume=2.0 -> 0.2/2.0 = 0.1 > 0.05 -> skip
        strategy = _make_strategy(
            num_slices=5, total_size=1.0, config=config
        )
        assert strategy.should_skip_slice(1, {'recent_volume': 2.0}) is True

    def test_allow_when_under_cap(self):
        """Should not skip when slice_size / recent_volume < cap."""
        config = _make_config(participation_rate_cap=0.05)  # 5%
        # total_size=1.0, num_slices=5, so slice_size=0.2
        # recent_volume=100.0 -> 0.2/100.0 = 0.002 < 0.05 -> allow
        strategy = _make_strategy(
            num_slices=5, total_size=1.0, config=config
        )
        assert strategy.should_skip_slice(1, {'recent_volume': 100.0}) is False

    def test_skip_when_exactly_at_cap(self):
        """Should not skip when exactly at cap (not strictly greater)."""
        config = _make_config(participation_rate_cap=0.05)
        # slice_size=0.2, volume=4.0 -> 0.2/4.0 = 0.05 = cap -> not skip
        strategy = _make_strategy(
            num_slices=5, total_size=1.0, config=config
        )
        assert strategy.should_skip_slice(1, {'recent_volume': 4.0}) is False

    def test_skip_when_no_volume_data(self):
        """Should skip when recent_volume is 0 or missing (safety)."""
        config = _make_config(participation_rate_cap=0.05)
        strategy = _make_strategy(config=config)

        # No volume key
        assert strategy.should_skip_slice(1, {}) is True
        # Zero volume
        assert strategy.should_skip_slice(1, {'recent_volume': 0.0}) is True

    def test_get_recent_volume_from_api(self):
        """get_recent_volume should sum candle volumes from the API client."""
        mock_api = Mock()
        candle1 = Mock(volume='100.5')
        candle2 = Mock(volume='200.3')
        mock_api.get_candles.return_value = Mock(candles=[candle1, candle2])

        config = _make_config(volume_lookback_minutes=5)
        strategy = _make_strategy(config=config, api_client=mock_api)

        volume = strategy.get_recent_volume('BTC-USDC')
        assert volume == pytest.approx(300.8)
        mock_api.get_candles.assert_called_once()

    def test_get_recent_volume_no_api_client(self):
        """get_recent_volume returns 0.0 when no api_client is set."""
        strategy = _make_strategy(api_client=None)
        assert strategy.get_recent_volume('BTC-USDC') == 0.0


# =============================================================================
# on_slice_complete Tracking
# =============================================================================

@pytest.mark.unit
class TestOnSliceComplete:
    """Tests for on_slice_complete tracking."""

    def test_tracks_successful_fill(self):
        """Successful fill should be tracked in _filled_slices."""
        strategy = _make_strategy()
        strategy.on_slice_complete(
            slice_number=1,
            order_id='order-123',
            fill_info={'filled_size': 0.2, 'price': 50000.0, 'fee': 1.5},
        )

        assert len(strategy._filled_slices) == 1
        assert strategy._filled_slices[0]['order_id'] == 'order-123'
        assert strategy._total_filled == pytest.approx(0.2)
        assert strategy._total_value == pytest.approx(10000.0)
        assert strategy._total_fees == pytest.approx(1.5)

    def test_tracks_order_without_fill_info(self):
        """Order placed without fill info should still be tracked."""
        strategy = _make_strategy()
        strategy.on_slice_complete(
            slice_number=1,
            order_id='order-456',
            fill_info=None,
        )

        assert len(strategy._filled_slices) == 1
        assert strategy._total_filled == 0.0

    def test_tracks_failed_slice(self):
        """Failed slice (no order_id) should be tracked in _failed_slices."""
        strategy = _make_strategy()
        strategy.on_slice_complete(
            slice_number=3,
            order_id=None,
            fill_info=None,
        )

        assert len(strategy._failed_slices) == 1
        assert 3 in strategy._failed_slices

    def test_multiple_fills_accumulate(self):
        """Multiple fills should accumulate totals."""
        strategy = _make_strategy()
        strategy.on_slice_complete(
            1, 'o1', {'filled_size': 0.1, 'price': 50000.0, 'fee': 1.0}
        )
        strategy.on_slice_complete(
            2, 'o2', {'filled_size': 0.2, 'price': 51000.0, 'fee': 2.0}
        )

        assert strategy._total_filled == pytest.approx(0.3)
        assert strategy._total_value == pytest.approx(0.1 * 50000 + 0.2 * 51000)
        assert strategy._total_fees == pytest.approx(3.0)
        assert len(strategy._filled_slices) == 2


# =============================================================================
# get_result
# =============================================================================

@pytest.mark.unit
class TestGetResult:
    """Tests for get_result strategy result."""

    def test_pending_result_when_no_slices_executed(self):
        """Result should be PENDING when nothing has executed."""
        strategy = _make_strategy()
        result = strategy.get_result()
        assert result.status == StrategyStatus.PENDING
        assert result.num_filled == 0
        assert result.num_failed == 0

    def test_completed_result_when_all_slices_done(self):
        """Result should be COMPLETED when all slices are accounted for."""
        strategy = _make_strategy(num_slices=2)
        strategy.on_slice_complete(1, 'o1', {'filled_size': 0.5, 'price': 50000.0, 'fee': 1.0})
        strategy.on_slice_complete(2, 'o2', {'filled_size': 0.5, 'price': 50000.0, 'fee': 1.0})
        result = strategy.get_result()
        assert result.status == StrategyStatus.COMPLETED
        assert result.num_filled == 2

    def test_average_price_calculation(self):
        """Average price should be total_value / total_filled."""
        strategy = _make_strategy(num_slices=2)
        strategy.on_slice_complete(1, 'o1', {'filled_size': 0.5, 'price': 48000.0, 'fee': 0.0})
        strategy.on_slice_complete(2, 'o2', {'filled_size': 0.5, 'price': 52000.0, 'fee': 0.0})
        result = strategy.get_result()
        expected_avg = (0.5 * 48000 + 0.5 * 52000) / 1.0
        assert result.average_price == pytest.approx(expected_avg)

    def test_result_metadata_contains_strategy_info(self):
        """Result metadata should contain strategy parameters."""
        strategy = _make_strategy(price_type='mid')
        result = strategy.get_result()
        assert result.metadata['price_type'] == 'mid'
        assert result.metadata['product_id'] == 'BTC-USDC'
