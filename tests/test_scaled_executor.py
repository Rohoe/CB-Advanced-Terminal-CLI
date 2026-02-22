"""
Unit tests for ScaledExecutor.
"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

from scaled_executor import ScaledExecutor
from scaled_orders import DistributionType
from scaled_order_tracker import ScaledOrderTracker
from config_manager import AppConfig
from queue import Queue


@pytest.mark.unit
class TestScaledExecutor:
    """Tests for ScaledExecutor."""

    @pytest.fixture
    def temp_dir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    @pytest.fixture
    def mock_order_executor(self):
        executor = Mock()
        executor.get_fee_rates.return_value = (0.004, 0.006)
        executor.place_limit_order_with_retry.return_value = {
            'order_id': 'test-order-id',
            'success': True
        }
        return executor

    @pytest.fixture
    def mock_market_data(self):
        md = Mock()
        md.select_market.return_value = 'BTC-USDC'
        md.get_current_prices.return_value = {'bid': 49995, 'ask': 50005, 'mid': 50000}
        md.display_market_conditions.return_value = None
        md.round_price.side_effect = lambda p, pid: round(p, 2)
        md.round_size.side_effect = lambda s, pid: round(s, 8)

        mock_product = Mock()
        mock_product.base_min_size = '0.0001'
        md.api_client = Mock()
        md.api_client.get_product.return_value = mock_product
        return md

    @pytest.fixture
    def executor(self, mock_order_executor, mock_market_data, temp_dir):
        config = AppConfig.for_testing()
        order_queue = Queue()
        ex = ScaledExecutor(
            order_executor=mock_order_executor,
            market_data=mock_market_data,
            order_queue=order_queue,
            config=config
        )
        # Use temp directory for tracker
        ex.scaled_tracker = ScaledOrderTracker(base_dir=temp_dir)
        return ex

    def test_place_scaled_order_all_placed(self, executor, mock_order_executor):
        """All N orders should be placed via the order executor."""
        # Mock inputs: side, low price, high price, size, num_orders, distribution, confirm
        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'yes'])
        get_input = Mock(side_effect=inputs)

        scaled_id = executor.place_scaled_order(get_input)

        assert scaled_id is not None
        assert mock_order_executor.place_limit_order_with_retry.call_count == 5

    def test_place_scaled_order_cancelled_by_user(self, executor, mock_order_executor):
        """User declining confirmation should cancel the order."""
        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'no'])
        get_input = Mock(side_effect=inputs)

        scaled_id = executor.place_scaled_order(get_input)

        assert scaled_id is None
        assert mock_order_executor.place_limit_order_with_retry.call_count == 0

    def test_place_scaled_order_partial_failure(self, executor, mock_order_executor):
        """Orders that fail should be marked as failed in the tracker."""
        # First 3 succeed, last 2 fail
        responses = [
            {'order_id': f'order-{i}', 'success': True} for i in range(3)
        ] + [None, None]
        mock_order_executor.place_limit_order_with_retry.side_effect = responses

        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'yes'])
        get_input = Mock(side_effect=inputs)

        scaled_id = executor.place_scaled_order(get_input)

        assert scaled_id is not None
        order = executor.scaled_tracker.get_scaled_order(scaled_id)
        assert order.status == 'partial'
        assert order.num_placed == 3
        assert order.num_failed == 2

    def test_place_scaled_order_all_fail(self, executor, mock_order_executor):
        """All orders failing should result in 'failed' status."""
        mock_order_executor.place_limit_order_with_retry.return_value = None

        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'yes'])
        get_input = Mock(side_effect=inputs)

        scaled_id = executor.place_scaled_order(get_input)

        assert scaled_id is not None
        order = executor.scaled_tracker.get_scaled_order(scaled_id)
        assert order.status == 'failed'

    def test_order_saved_after_each_level(self, executor, mock_order_executor):
        """Order should be saved to disk after each level for crash recovery."""
        save_count = [0]
        original_save = executor.scaled_tracker.save_scaled_order

        def counting_save(order):
            save_count[0] += 1
            return original_save(order)

        executor.scaled_tracker.save_scaled_order = counting_save

        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'yes'])
        get_input = Mock(side_effect=inputs)

        executor.place_scaled_order(get_input)

        # Should save after each level (5) + final status update (1)
        assert save_count[0] >= 5

    def test_each_order_meets_min_size(self, executor, mock_order_executor):
        """Each placed order should meet the minimum size."""
        calls = []
        def capture_calls(**kwargs):
            calls.append(kwargs)
            return {'order_id': 'test-id', 'success': True}

        mock_order_executor.place_limit_order_with_retry.side_effect = capture_calls

        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '1', 'yes'])
        get_input = Mock(side_effect=inputs)

        executor.place_scaled_order(get_input)

        for call_kwargs in calls:
            size = float(call_kwargs.get('base_size', 0))
            assert size >= 0.0001  # min_size from mock

    def test_display_scaled_summary(self, executor):
        """Summary display should not raise for valid order."""
        from scaled_orders import ScaledOrder, ScaledOrderLevel

        order = ScaledOrder(
            scaled_id='test-display',
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=3,
            distribution=DistributionType.LINEAR, status='active',
            total_filled=0.3, total_value_filled=14850.0, total_fees=3.0
        )
        for i in range(3):
            order.levels.append(ScaledOrderLevel(
                level_number=i+1, price=49000+i*1000, size=0.333,
                order_id=f'oid-{i}', status='filled' if i == 0 else 'placed',
                filled_size=0.3 if i == 0 else 0.0,
                filled_value=14850.0 if i == 0 else 0.0,
                fees=3.0 if i == 0 else 0.0,
            ))

        executor.scaled_tracker.save_scaled_order(order)
        # Should not raise
        executor.display_scaled_summary('test-display')

    def test_display_all_scaled_orders(self, executor):
        """Display all should return list of IDs."""
        from scaled_orders import ScaledOrder

        for i in range(3):
            order = ScaledOrder(
                scaled_id=f'test-{i}',
                product_id='BTC-USDC', side='BUY', total_size=1.0,
                price_low=49000, price_high=51000, num_orders=5,
                distribution=DistributionType.LINEAR
            )
            executor.scaled_tracker.save_scaled_order(order)

        result = executor.display_all_scaled_orders()
        assert result is not None
        assert len(result) == 3

    def test_display_all_empty(self, executor):
        """Display all with no orders should return None."""
        result = executor.display_all_scaled_orders()
        assert result is None

    def test_geometric_distribution_used(self, executor, mock_order_executor):
        """Geometric distribution should produce varying sizes."""
        calls = []
        def capture_calls(**kwargs):
            calls.append(float(kwargs.get('base_size', 0)))
            return {'order_id': 'test-id', 'success': True}

        mock_order_executor.place_limit_order_with_retry.side_effect = capture_calls

        inputs = iter(['BUY', '49000', '51000', '1.0', '5', '2', 'yes'])  # '2' = geometric
        get_input = Mock(side_effect=inputs)

        executor.place_scaled_order(get_input)

        # Geometric should have non-equal sizes
        assert len(set(round(s, 8) for s in calls)) > 1
