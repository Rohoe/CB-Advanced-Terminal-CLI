"""
Mock-based integration test for scaled/ladder order execution.

This test exercises the full ScaledExecutor flow end-to-end using
MockCoinbaseAPI, verifying that:
- ScaledStrategy calculates correct price levels and sizes
- OrderExecutor places each level correctly
- ScaledOrderTracker persists the order
- Summary display renders without errors

No real API calls are made.
"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock
from queue import Queue

from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
from market_data import MarketDataService
from order_executor import OrderExecutor
from scaled_executor import ScaledExecutor
from scaled_orders import DistributionType
from config_manager import AppConfig


@pytest.fixture
def scaled_test_env():
    """Set up a complete environment for scaled order integration testing."""
    api_client = MockCoinbaseAPI()
    config = AppConfig.for_testing()

    rate_limiter = Mock()
    rate_limiter.wait.return_value = None

    market_data = MarketDataService(
        api_client=api_client,
        rate_limiter=rate_limiter,
        config=config
    )

    order_executor = OrderExecutor(
        api_client=api_client,
        market_data=market_data,
        rate_limiter=rate_limiter,
        config=config
    )

    order_queue = Queue()

    # Use temp directory for tracker storage
    temp_dir = tempfile.mkdtemp()

    executor = ScaledExecutor(
        order_executor=order_executor,
        market_data=market_data,
        order_queue=order_queue,
        config=config
    )
    # Override tracker to use temp directory
    from scaled_order_tracker import ScaledOrderTracker
    executor.scaled_tracker = ScaledOrderTracker(base_dir=temp_dir)

    yield {
        'api_client': api_client,
        'executor': executor,
        'market_data': market_data,
        'order_executor': order_executor,
        'temp_dir': temp_dir,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.integration
class TestFullScaledOrderFlow:
    """End-to-end test of scaled order placement."""

    def test_full_scaled_order_flow(self, scaled_test_env):
        """
        Complete scaled order flow:
        1. User selects BTC-USDC, BUY, price range 48000-52000, 5 levels, linear
        2. Each level is placed via OrderExecutor
        3. Order is persisted via ScaledOrderTracker
        4. Summary display works without errors
        """
        env = scaled_test_env
        executor = env['executor']
        api_client = env['api_client']

        # Ensure USDC balance is sufficient
        api_client.set_account_balance('USDC', 100000.0)

        # Simulate user input sequence
        input_sequence = iter([
            '1',        # Select first market (BTC)
            '2',        # Select USDC quote
            'buy',      # Side
            '48000',    # Low price
            '52000',    # High price
            '0.05',     # Total size
            '5',        # Number of orders
            '1',        # Linear distribution
            'yes',      # Confirm
        ])

        def mock_input(prompt):
            return next(input_sequence)

        scaled_id = executor.place_scaled_order(mock_input)

        # Verify order was placed
        assert scaled_id is not None, "Scaled order should return an ID"

        # Verify orders were placed in the mock API
        assert api_client.get_order_count() == 5, f"Expected 5 orders, got {api_client.get_order_count()}"

        # Verify tracker persisted the order
        order = executor.scaled_tracker.get_scaled_order(scaled_id)
        assert order is not None, "Scaled order should be persisted"
        assert order.product_id == 'BTC-USDC'
        assert order.side == 'BUY'
        assert order.num_orders == 5
        assert order.distribution == DistributionType.LINEAR
        assert len(order.levels) == 5

        # Verify price levels span the range
        prices = [l.price for l in order.levels]
        assert prices[0] == pytest.approx(48000.0, abs=1.0)
        assert prices[-1] == pytest.approx(52000.0, abs=1.0)

        # Verify sizes are approximately equal (linear distribution)
        sizes = [l.size for l in order.levels]
        expected_size = 0.05 / 5
        for size in sizes:
            assert size == pytest.approx(expected_size, rel=0.01)

        # Verify all levels were placed successfully
        placed = sum(1 for l in order.levels if l.status == 'placed')
        assert placed == 5, f"Expected 5 placed levels, got {placed}"

        # Verify summary display works without exceptions
        executor.display_scaled_summary(scaled_id)

        print(f"✓ Full scaled order flow completed: {scaled_id[:8]}...")
        print(f"  5 levels placed from $48,000 to $52,000")
        print(f"  Total size: 0.05 BTC, distribution: linear")
