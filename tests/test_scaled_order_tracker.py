"""
Unit tests for ScaledOrderTracker persistence.
"""

import pytest
import os
import tempfile
import shutil

from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType
from scaled_order_tracker import ScaledOrderTracker


@pytest.mark.unit
class TestScaledOrderTracker:
    """Tests for ScaledOrderTracker persistence."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test data."""
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    @pytest.fixture
    def tracker(self, temp_dir):
        """Create a tracker with temp directory."""
        return ScaledOrderTracker(base_dir=temp_dir)

    @pytest.fixture
    def sample_order(self):
        """Create a sample scaled order."""
        order = ScaledOrder(
            scaled_id='test-123',
            product_id='BTC-USDC',
            side='BUY',
            total_size=1.0,
            price_low=49000.0,
            price_high=51000.0,
            num_orders=5,
            distribution=DistributionType.LINEAR,
            status='active'
        )
        for i in range(5):
            order.levels.append(ScaledOrderLevel(
                level_number=i + 1,
                price=49000.0 + i * 500.0,
                size=0.2,
                order_id=f'order-{i}',
                status='placed'
            ))
        return order

    def test_save_and_load_round_trip(self, tracker, sample_order):
        """Save and load should preserve all data."""
        tracker.save_scaled_order(sample_order)
        loaded = tracker.get_scaled_order('test-123')

        assert loaded is not None
        assert loaded.scaled_id == 'test-123'
        assert loaded.product_id == 'BTC-USDC'
        assert loaded.side == 'BUY'
        assert loaded.total_size == 1.0
        assert loaded.price_low == 49000.0
        assert loaded.price_high == 51000.0
        assert loaded.num_orders == 5
        assert loaded.distribution == DistributionType.LINEAR
        assert loaded.status == 'active'
        assert len(loaded.levels) == 5

    def test_load_nonexistent_returns_none(self, tracker):
        """Loading a non-existent order should return None."""
        assert tracker.get_scaled_order('nonexistent') is None

    def test_list_all_orders(self, tracker):
        """List should return all saved orders."""
        for i in range(3):
            order = ScaledOrder(
                scaled_id=f'test-{i}',
                product_id='BTC-USDC',
                side='BUY',
                total_size=1.0,
                price_low=49000.0,
                price_high=51000.0,
                num_orders=5,
                distribution=DistributionType.LINEAR,
            )
            tracker.save_scaled_order(order)

        orders = tracker.list_scaled_orders()
        assert len(orders) == 3

    def test_list_orders_with_status_filter(self, tracker):
        """List should filter by status."""
        for i, status in enumerate(['active', 'completed', 'active']):
            order = ScaledOrder(
                scaled_id=f'test-{i}',
                product_id='BTC-USDC',
                side='BUY',
                total_size=1.0,
                price_low=49000.0,
                price_high=51000.0,
                num_orders=5,
                distribution=DistributionType.LINEAR,
                status=status
            )
            tracker.save_scaled_order(order)

        active = tracker.list_scaled_orders(status='active')
        assert len(active) == 2
        completed = tracker.list_scaled_orders(status='completed')
        assert len(completed) == 1

    def test_update_order_status(self, tracker, sample_order):
        """Update status should persist."""
        tracker.save_scaled_order(sample_order)
        result = tracker.update_order_status('test-123', 'completed')
        assert result is True

        loaded = tracker.get_scaled_order('test-123')
        assert loaded.status == 'completed'

    def test_update_nonexistent_returns_false(self, tracker):
        """Updating non-existent order should return False."""
        result = tracker.update_order_status('nonexistent', 'completed')
        assert result is False

    def test_update_level_status(self, tracker, sample_order):
        """Update level status should persist."""
        tracker.save_scaled_order(sample_order)
        result = tracker.update_level_status(
            'test-123', 1, 'filled',
            fill_info={'filled_size': 0.2, 'filled_value': 9800.0, 'fees': 1.5, 'is_maker': True}
        )
        assert result is True

        loaded = tracker.get_scaled_order('test-123')
        level = loaded.levels[0]
        assert level.status == 'filled'
        assert level.filled_size == 0.2
        assert level.filled_value == 9800.0
        assert level.fees == 1.5

    def test_update_level_recalculates_totals(self, tracker, sample_order):
        """Updating a level should recalculate order totals."""
        tracker.save_scaled_order(sample_order)

        # Fill two levels
        tracker.update_level_status(
            'test-123', 1, 'filled',
            fill_info={'filled_size': 0.2, 'filled_value': 9800.0, 'fees': 1.0, 'is_maker': True}
        )
        tracker.update_level_status(
            'test-123', 2, 'filled',
            fill_info={'filled_size': 0.2, 'filled_value': 9900.0, 'fees': 1.5, 'is_maker': False}
        )

        loaded = tracker.get_scaled_order('test-123')
        assert loaded.total_filled == pytest.approx(0.4)
        assert loaded.total_value_filled == pytest.approx(19700.0)
        assert loaded.total_fees == pytest.approx(2.5)
        assert loaded.maker_orders == 1
        assert loaded.taker_orders == 1

    def test_delete_order(self, tracker, sample_order):
        """Delete should remove the order file."""
        tracker.save_scaled_order(sample_order)
        assert tracker.get_scaled_order('test-123') is not None

        result = tracker.delete_scaled_order('test-123')
        assert result is True
        assert tracker.get_scaled_order('test-123') is None

    def test_delete_nonexistent_returns_false(self, tracker):
        """Deleting non-existent order should return False."""
        result = tracker.delete_scaled_order('nonexistent')
        assert result is False

    def test_order_to_dict_from_dict_round_trip(self):
        """ScaledOrder serialization round-trip should preserve data."""
        order = ScaledOrder(
            scaled_id='test-456',
            product_id='ETH-USDC',
            side='SELL',
            total_size=10.0,
            price_low=3000.0,
            price_high=3500.0,
            num_orders=3,
            distribution=DistributionType.GEOMETRIC,
            status='partial',
            total_filled=5.0,
            total_value_filled=16000.0,
            total_fees=8.0,
        )
        order.levels.append(ScaledOrderLevel(
            level_number=1, price=3000.0, size=2.0,
            order_id='oid-1', status='filled',
            filled_size=2.0, filled_value=6000.0, fees=3.0
        ))

        data = order.to_dict()
        restored = ScaledOrder.from_dict(data)

        assert restored.scaled_id == 'test-456'
        assert restored.distribution == DistributionType.GEOMETRIC
        assert restored.side == 'SELL'
        assert len(restored.levels) == 1
        assert restored.levels[0].order_id == 'oid-1'
