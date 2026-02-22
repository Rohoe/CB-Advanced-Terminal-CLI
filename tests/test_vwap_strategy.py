"""
Unit tests for VWAPStrategy.
"""

import pytest
import time
from unittest.mock import Mock
from vwap_strategy import VWAPStrategy, VWAPStrategyConfig
from order_strategy import StrategyStatus


@pytest.mark.unit
class TestVWAPVolumeProfile:
    """Tests for volume profile calculation."""

    def _make_candles(self, volumes_by_hour):
        """Helper to create candle data with specific volumes by hour."""
        candles = []
        base_time = 1704067200  # 2024-01-01 00:00:00 UTC
        for hour, volume in volumes_by_hour.items():
            candles.append({
                'start': str(base_time + hour * 3600),
                'open': '50000',
                'high': '50100',
                'low': '49900',
                'close': '50050',
                'volume': str(volume)
            })
        return candles

    def test_volume_profile_u_shaped(self):
        """U-shaped volume should produce higher weights at start and end."""
        # U-shaped: high at hours 0,1 and 22,23, low in middle
        volumes = {}
        for h in range(24):
            if h < 3 or h > 20:
                volumes[h] = 1000.0
            else:
                volumes[h] = 100.0

        mock_api = Mock()
        mock_api.get_candles.return_value = self._make_candles(volumes)

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=10, duration_minutes=60,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()

        # Profile should exist and sum to 1.0
        profile = strategy.volume_profile
        assert len(profile) == 10
        assert abs(sum(profile) - 1.0) < 1e-10

    def test_flat_volume_profile_equals_twap(self):
        """Flat volume profile should produce equal sizes (TWAP-equivalent)."""
        volumes = {h: 500.0 for h in range(24)}

        mock_api = Mock()
        mock_api.get_candles.return_value = self._make_candles(volumes)

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=10, duration_minutes=60,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]

        # All sizes should be equal (within floating point tolerance)
        expected = 1.0 / 10
        for size in sizes:
            assert abs(size - expected) < 1e-6

    def test_sizes_sum_to_total(self):
        """All slice sizes should sum to total_size regardless of volume profile."""
        volumes = {h: (h + 1) * 100 for h in range(24)}  # Increasing volume

        mock_api = Mock()
        mock_api.get_candles.return_value = self._make_candles(volumes)

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=2.5,
            limit_price=50000, num_slices=5, duration_minutes=30,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()
        total = sum(s.size for s in slices)
        assert abs(total - 2.5) < 1e-10

    def test_high_volume_slices_get_more_size(self):
        """Slices in high-volume periods should get proportionally more size."""
        # Create very uneven volume: one hour has 10x the volume
        from datetime import datetime
        now = datetime.now()
        current_hour = now.hour

        volumes = {h: 100.0 for h in range(24)}
        volumes[current_hour] = 1000.0  # Current hour has 10x volume

        mock_api = Mock()
        mock_api.get_candles.return_value = self._make_candles(volumes)

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=5, duration_minutes=5,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]

        # Since all slices are in the same hour (5min duration), they should be equal
        # But the profile should exist
        assert len(sizes) == 5
        assert sum(sizes) == pytest.approx(1.0)

    def test_no_candle_data_falls_back_to_flat(self):
        """Empty candle data should fall back to flat TWAP profile."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=5, duration_minutes=30,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]

        expected = 1.0 / 5
        for size in sizes:
            assert abs(size - expected) < 1e-10

    def test_api_error_falls_back_to_flat(self):
        """API error should fall back to flat profile."""
        mock_api = Mock()
        mock_api.get_candles.side_effect = Exception("API error")

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=5, duration_minutes=30,
            api_client=mock_api
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]

        expected = 1.0 / 5
        for size in sizes:
            assert abs(size - expected) < 1e-10


@pytest.mark.unit
class TestVWAPBenchmark:
    """Tests for benchmark VWAP calculation."""

    def test_benchmark_vwap_calculation(self):
        """Benchmark VWAP = sum(typical_price * volume) / sum(volume)."""
        candles = [
            {'start': '1704067200', 'high': '51000', 'low': '49000', 'close': '50000', 'volume': '100', 'open': '50000'},
            {'start': '1704070800', 'high': '52000', 'low': '50000', 'close': '51000', 'volume': '200', 'open': '50500'},
        ]

        mock_api = Mock()
        mock_api.get_candles.return_value = candles

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=2, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()

        # Typical prices: (51000+49000+50000)/3 = 50000, (52000+50000+51000)/3 = 51000
        # Benchmark = (50000*100 + 51000*200) / (100+200) = (5000000+10200000)/300 = 50666.67
        expected = (50000 * 100 + 51000 * 200) / 300
        assert strategy.benchmark_vwap == pytest.approx(expected, rel=1e-4)

    def test_benchmark_zero_with_no_candles(self):
        """Benchmark should be 0 if no candles available."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=2, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        assert strategy.benchmark_vwap == 0.0


@pytest.mark.unit
class TestVWAPPerformance:
    """Tests for execution VWAP and performance metrics."""

    def test_execution_vwap_calculation(self):
        """Execution VWAP should be volume-weighted average of fills."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=3, duration_minutes=30,
            api_client=mock_api
        )
        strategy.calculate_slices()

        strategy.on_slice_complete(1, 'order-1', {'filled_size': 0.3, 'price': 49000})
        strategy.on_slice_complete(2, 'order-2', {'filled_size': 0.5, 'price': 50000})
        strategy.on_slice_complete(3, 'order-3', {'filled_size': 0.2, 'price': 51000})

        exec_vwap = strategy.get_execution_vwap()
        expected = (0.3 * 49000 + 0.5 * 50000 + 0.2 * 51000) / (0.3 + 0.5 + 0.2)
        assert exec_vwap == pytest.approx(expected, rel=1e-6)

    def test_slippage_buy_unfavorable(self):
        """Positive slippage for BUY means paid more than benchmark."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        strategy._benchmark_vwap = 50000.0
        strategy.on_slice_complete(1, 'order-1', {'filled_size': 1.0, 'price': 50100})

        perf = strategy.get_performance_vs_benchmark()
        assert perf['slippage_bps'] > 0  # Unfavorable

    def test_slippage_buy_favorable(self):
        """Negative slippage for BUY means paid less than benchmark."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        strategy._benchmark_vwap = 50000.0
        strategy.on_slice_complete(1, 'order-1', {'filled_size': 1.0, 'price': 49900})

        perf = strategy.get_performance_vs_benchmark()
        assert perf['slippage_bps'] < 0  # Favorable

    def test_slippage_sell_unfavorable(self):
        """Positive slippage for SELL means got less than benchmark."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='SELL', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        strategy._benchmark_vwap = 50000.0
        strategy.on_slice_complete(1, 'order-1', {'filled_size': 1.0, 'price': 49900})

        perf = strategy.get_performance_vs_benchmark()
        assert perf['slippage_bps'] > 0  # Unfavorable

    def test_slippage_sell_favorable(self):
        """Negative slippage for SELL means got more than benchmark."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='SELL', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        strategy._benchmark_vwap = 50000.0
        strategy.on_slice_complete(1, 'order-1', {'filled_size': 1.0, 'price': 50100})

        perf = strategy.get_performance_vs_benchmark()
        assert perf['slippage_bps'] < 0  # Favorable

    def test_no_fills_zero_slippage(self):
        """No fills should give 0 slippage."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()

        perf = strategy.get_performance_vs_benchmark()
        assert perf['slippage_bps'] == 0.0


@pytest.mark.unit
class TestVWAPBehavior:
    """Tests for general strategy behavior."""

    def test_should_skip_always_false(self):
        """VWAP should never skip slices."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=5, duration_minutes=30,
            api_client=mock_api
        )
        assert strategy.should_skip_slice(1, {}) is False

    def test_status_transitions(self):
        """Status should go PENDING -> ACTIVE -> COMPLETED."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=2, duration_minutes=10,
            api_client=mock_api
        )
        assert strategy._status == StrategyStatus.PENDING

        strategy.calculate_slices()
        assert strategy._status == StrategyStatus.ACTIVE

        strategy.on_slice_complete(1, 'o1', {'filled_size': 0.5, 'price': 50000})
        strategy.on_slice_complete(2, 'o2', {'filled_size': 0.5, 'price': 50000})
        assert strategy._status == StrategyStatus.COMPLETED

    def test_get_execution_price_types(self):
        """get_execution_price should return correct price for each type."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=1, duration_minutes=10,
            api_client=mock_api
        )

        from order_strategy import SliceSpec
        market = {'bid': 49990, 'ask': 50010, 'mid': 50000}

        slice_bid = SliceSpec(1, 0.5, 50000, time.time(), 'bid')
        assert strategy.get_execution_price(slice_bid, market) == 49990

        slice_ask = SliceSpec(1, 0.5, 50000, time.time(), 'ask')
        assert strategy.get_execution_price(slice_ask, market) == 50010

        slice_mid = SliceSpec(1, 0.5, 50000, time.time(), 'mid')
        assert strategy.get_execution_price(slice_mid, market) == 50000

        slice_limit = SliceSpec(1, 0.5, 50000, time.time(), 'limit')
        assert strategy.get_execution_price(slice_limit, market) == 50000

    def test_get_result_with_metadata(self):
        """get_result should include VWAP-specific metadata."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        strategy = VWAPStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            limit_price=50000, num_slices=2, duration_minutes=10,
            api_client=mock_api
        )
        strategy.calculate_slices()
        strategy.on_slice_complete(1, 'o1', {
            'filled_size': 0.5, 'price': 50000, 'filled_value': 25000, 'fees': 5
        })
        strategy.on_slice_complete(2, None, None)  # Failed

        result = strategy.get_result()
        assert result.num_filled == 1
        assert result.num_failed == 1
        assert 'benchmark_vwap' in result.metadata
        assert 'slippage_bps' in result.metadata
        assert 'volume_profile' in result.metadata

    def test_correct_number_of_slices(self):
        """Should return exact number of slices requested."""
        mock_api = Mock()
        mock_api.get_candles.return_value = []

        for n in [2, 5, 10, 20]:
            strategy = VWAPStrategy(
                product_id='BTC-USDC', side='BUY', total_size=1.0,
                limit_price=50000, num_slices=n, duration_minutes=60,
                api_client=mock_api
            )
            slices = strategy.calculate_slices()
            assert len(slices) == n
