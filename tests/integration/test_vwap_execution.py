"""
Mock-based integration test for VWAP order execution.

This test exercises the full VWAPStrategy flow end-to-end using
MockCoinbaseAPI, verifying that:
- Volume profile is calculated from candle data
- Slice sizes are proportional to volume profile weights
- Benchmark VWAP is calculated correctly
- Strategy result includes performance metrics

No real API calls are made.

Note: VWAPStrategy iterates directly over the get_candles() return value
(treats it as a list of candles), unlike TWAPStrategy which accesses
response.candles. This test uses a wrapper to provide the expected format.
"""

import pytest
import time
from unittest.mock import Mock

from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
from vwap_strategy import VWAPStrategy, VWAPStrategyConfig
from order_strategy import StrategyStatus


class VWAPCompatibleMockAPI(MockCoinbaseAPI):
    """
    MockCoinbaseAPI subclass that returns candle data in the format
    VWAPStrategy expects (directly iterable list of candle dicts).
    """

    def get_candles(self, product_id, start, end, granularity):
        """Return candle list directly (VWAPStrategy iterates over the response)."""
        candles = self.candles.get(product_id, [])

        # Filter by time range
        filtered = []
        for candle in candles:
            candle_start = int(candle['start'])
            if int(start) <= candle_start <= int(end):
                filtered.append(candle)

        if not filtered:
            filtered = candles

        return filtered


@pytest.fixture
def vwap_test_env():
    """Set up a complete environment for VWAP integration testing."""
    api_client = VWAPCompatibleMockAPI()

    # Generate realistic candle data with U-shaped volume profile
    api_client.generate_candles(
        product_id='BTC-USD',
        hours=24,
        granularity='ONE_HOUR',
        base_price=50000.0,
        seed=42  # Reproducible
    )

    return api_client


@pytest.mark.integration
class TestFullVWAPOrderFlow:
    """End-to-end test of VWAP order execution."""

    def test_full_vwap_order_flow(self, vwap_test_env):
        """
        Complete VWAP order flow:
        1. Create VWAPStrategy with 5 slices over 60 minutes
        2. calculate_slices() fetches candle data and builds volume profile
        3. Slice sizes are proportional to historical volume
        4. Benchmark VWAP is computed from candle typical prices
        5. Simulate fills and verify performance metrics
        """
        api_client = vwap_test_env

        vwap_config = VWAPStrategyConfig(
            duration_minutes=60,
            num_slices=5,
            price_type='mid',
            volume_lookback_hours=24,
            granularity='ONE_HOUR',
            benchmark_enabled=True,
        )

        strategy = VWAPStrategy(
            product_id='BTC-USD',
            side='BUY',
            total_size=1.0,
            limit_price=50000.0,
            num_slices=5,
            duration_minutes=60,
            api_client=api_client,
            config=vwap_config,
        )

        # Step 1: Calculate slices (triggers volume profile fetch)
        slices = strategy.calculate_slices()

        assert len(slices) == 5, f"Expected 5 slices, got {len(slices)}"

        # Step 2: Verify volume profile was built from candle data
        profile = strategy.volume_profile
        assert len(profile) == 5, f"Volume profile should have 5 weights, got {len(profile)}"
        assert abs(sum(profile) - 1.0) < 1e-10, f"Profile should sum to 1.0, got {sum(profile)}"

        # All weights should be positive
        for w in profile:
            assert w > 0, f"All profile weights should be positive, got {w}"

        print(f"Volume profile weights: {[f'{w:.4f}' for w in profile]}")

        # Step 3: Verify slice sizes sum to total_size
        total_size = sum(s.size for s in slices)
        assert abs(total_size - 1.0) < 1e-10, f"Slice sizes should sum to 1.0, got {total_size}"

        # Each slice should have size proportional to its weight
        for i, s in enumerate(slices):
            expected_size = 1.0 * profile[i]
            assert abs(s.size - expected_size) < 1e-10, \
                f"Slice {i+1} size {s.size} != expected {expected_size}"

        # Step 4: Verify benchmark VWAP was calculated
        benchmark = strategy.benchmark_vwap
        assert benchmark > 0, f"Benchmark VWAP should be positive, got {benchmark}"
        # Should be close to base price (50000) since candle data centers there
        assert 45000 < benchmark < 55000, f"Benchmark {benchmark} seems unreasonable"
        print(f"Benchmark VWAP: ${benchmark:.2f}")

        # Step 5: Simulate fills and check performance
        for i, s in enumerate(slices):
            # Simulate filled at slightly different prices
            fill_price = 50000.0 + (i - 2) * 50  # Spread around 50000
            strategy.on_slice_complete(
                slice_number=s.slice_number,
                order_id=f'mock-order-{i+1}',
                fill_info={
                    'filled_size': s.size,
                    'filled_value': s.size * fill_price,
                    'price': fill_price,
                    'fees': s.size * fill_price * 0.004,
                }
            )

        # Step 6: Verify strategy result
        result = strategy.get_result()
        assert result.status == StrategyStatus.COMPLETED
        assert result.total_size == 1.0
        assert abs(result.total_filled - 1.0) < 1e-10
        assert result.total_value > 0
        assert result.total_fees > 0
        assert result.num_filled == 5
        assert result.num_failed == 0
        assert result.average_price > 0

        # Step 7: Verify performance vs benchmark
        perf = strategy.get_performance_vs_benchmark()
        assert 'execution_vwap' in perf
        assert 'benchmark_vwap' in perf
        assert 'slippage_bps' in perf
        assert perf['execution_vwap'] > 0
        assert perf['benchmark_vwap'] > 0

        # Metadata should contain benchmark info
        assert 'benchmark_vwap' in result.metadata
        assert 'slippage_bps' in result.metadata
        assert 'volume_profile' in result.metadata

        print(f"\n✓ Full VWAP order flow completed:")
        print(f"  Execution VWAP: ${perf['execution_vwap']:.2f}")
        print(f"  Benchmark VWAP: ${perf['benchmark_vwap']:.2f}")
        print(f"  Slippage: {perf['slippage_bps']:.2f} bps")
        print(f"  Total filled: {result.total_filled:.4f}")
        print(f"  Total value: ${result.total_value:.2f}")
        print(f"  Total fees: ${result.total_fees:.2f}")
