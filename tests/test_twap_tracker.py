"""
Unit tests for TWAPTracker.

TWAPTracker handles persistence and statistics calculation for TWAP orders.
These tests verify correct storage and calculation of TWAP metrics.

To run these tests:
    pytest tests/test_twap_tracker.py
    pytest tests/test_twap_tracker.py::TestTWAPTrackerPersistence -v
"""

import pytest
import os
from twap_tracker import TWAPTracker, TWAPOrder, OrderFill


# =============================================================================
# Persistence Tests
# =============================================================================

@pytest.mark.unit
class TestTWAPTrackerPersistence:
    """Tests for TWAP order persistence (save/load)."""

    def test_initialization(self, temp_storage_dir):
        """Test that TWAPTracker creates necessary directories."""
        tracker = TWAPTracker(temp_storage_dir)

        # Verify directories were created
        assert os.path.exists(tracker.orders_dir)
        assert os.path.exists(tracker.fills_dir)

    def test_save_and_load_twap_order(self, temp_storage_dir, sample_twap_order):
        """
        Test saving and loading a TWAP order.

        This is a fundamental operation - we must be able to save
        an order and load it back with all data intact.
        """
        tracker = TWAPTracker(temp_storage_dir)

        # Save the order
        tracker.save_twap_order(sample_twap_order)

        # Load it back
        loaded = tracker.get_twap_order(sample_twap_order.twap_id)

        # Verify all fields match
        assert loaded is not None
        assert loaded.twap_id == sample_twap_order.twap_id
        assert loaded.market == sample_twap_order.market
        assert loaded.side == sample_twap_order.side
        assert loaded.total_size == sample_twap_order.total_size
        assert loaded.limit_price == sample_twap_order.limit_price
        assert loaded.num_slices == sample_twap_order.num_slices

    def test_load_nonexistent_order(self, temp_storage_dir):
        """Test that loading a nonexistent order returns None."""
        tracker = TWAPTracker(temp_storage_dir)

        # Try to load an order that doesn't exist
        loaded = tracker.get_twap_order('nonexistent-id')

        assert loaded is None

    def test_update_existing_order(self, temp_storage_dir, sample_twap_order):
        """Test that saving over an existing order updates it."""
        tracker = TWAPTracker(temp_storage_dir)

        # Save initial order
        tracker.save_twap_order(sample_twap_order)

        # Modify the order
        sample_twap_order.total_filled = 0.5
        sample_twap_order.status = 'completed'

        # Save again
        tracker.save_twap_order(sample_twap_order)

        # Load and verify updates
        loaded = tracker.get_twap_order(sample_twap_order.twap_id)
        assert loaded.total_filled == 0.5
        assert loaded.status == 'completed'

    def test_list_twap_orders(self, temp_storage_dir, sample_twap_order):
        """Test listing all TWAP orders."""
        tracker = TWAPTracker(temp_storage_dir)

        # Initially should be empty
        assert tracker.list_twap_orders() == []

        # Save one order
        tracker.save_twap_order(sample_twap_order)

        # Should now have one order
        order_ids = tracker.list_twap_orders()
        assert len(order_ids) == 1
        assert sample_twap_order.twap_id in order_ids

        # Create and save a second order
        order2 = TWAPOrder(
            twap_id='test-twap-456',
            market='ETH-USDC',
            side='SELL',
            total_size=10.0,
            limit_price=3000.0,
            num_slices=5,
            start_time='2025-01-01T00:00:00Z',
            status='active',
            orders=[],
            failed_slices=[],
            slice_statuses=[]
        )
        tracker.save_twap_order(order2)

        # Should now have two orders
        order_ids = tracker.list_twap_orders()
        assert len(order_ids) == 2
        assert 'test-twap-123' in order_ids
        assert 'test-twap-456' in order_ids


# =============================================================================
# Fill Persistence Tests
# =============================================================================

@pytest.mark.unit
class TestFillPersistence:
    """Tests for order fill persistence."""

    def test_save_and_load_fills(self, temp_storage_dir, sample_order_fills):
        """Test saving and loading order fills."""
        tracker = TWAPTracker(temp_storage_dir)
        twap_id = 'test-twap-123'

        # Save fills
        tracker.save_twap_fills(twap_id, sample_order_fills)

        # Load fills
        loaded_fills = tracker.get_twap_fills(twap_id)

        # Verify count
        assert len(loaded_fills) == 2

        # Verify first fill
        assert loaded_fills[0].order_id == 'order-1'
        assert loaded_fills[0].filled_size == 0.1
        assert loaded_fills[0].price == 50000.0
        assert loaded_fills[0].is_maker is True

        # Verify second fill
        assert loaded_fills[1].order_id == 'order-2'
        assert loaded_fills[1].filled_size == 0.1
        assert loaded_fills[1].price == 50100.0
        assert loaded_fills[1].is_maker is False

    def test_load_fills_for_nonexistent_order(self, temp_storage_dir):
        """Test loading fills for an order that doesn't exist."""
        tracker = TWAPTracker(temp_storage_dir)

        fills = tracker.get_twap_fills('nonexistent-id')

        # Should return empty list, not None
        assert fills == []

    def test_update_fills(self, temp_storage_dir, sample_order_fills):
        """Test that saving fills replaces previous fills."""
        tracker = TWAPTracker(temp_storage_dir)
        twap_id = 'test-twap-123'

        # Save initial fills
        tracker.save_twap_fills(twap_id, sample_order_fills)

        # Create new fills
        new_fills = [
            OrderFill(
                order_id='order-3',
                trade_id='trade-3',
                filled_size=0.2,
                price=50200.0,
                fee=4.0,
                is_maker=True,
                trade_time='2025-01-01T00:02:00Z'
            )
        ]

        # Save new fills (should replace old ones)
        tracker.save_twap_fills(twap_id, new_fills)

        # Load and verify
        loaded_fills = tracker.get_twap_fills(twap_id)
        assert len(loaded_fills) == 1
        assert loaded_fills[0].order_id == 'order-3'


# =============================================================================
# Statistics Calculation Tests
# =============================================================================

@pytest.mark.unit
class TestTWAPStatistics:
    """Tests for TWAP statistics calculation."""

    def test_calculate_twap_statistics_basic(self, temp_storage_dir, sample_twap_order, sample_order_fills):
        """
        Test basic TWAP statistics calculation.

        This tests the core metrics: total filled, VWAP, fees, completion rate.
        """
        tracker = TWAPTracker(temp_storage_dir)

        # Save order and fills
        tracker.save_twap_order(sample_twap_order)
        tracker.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        # Calculate statistics
        stats = tracker.calculate_twap_statistics(sample_twap_order.twap_id)

        # Verify basic fields
        assert stats['twap_id'] == 'test-twap-123'
        assert stats['market'] == 'BTC-USDC'
        assert stats['side'] == 'BUY'
        assert stats['total_size'] == 1.0

        # Verify calculated metrics
        # total_filled = 0.1 + 0.1 = 0.2
        assert stats['total_filled'] == 0.2

        # total_value_filled = (0.1 * 50000) + (0.1 * 50100) = 10010
        assert stats['total_value_filled'] == 10010.0

        # total_fees = 2.0 + 3.0 = 5.0
        assert stats['total_fees'] == 5.0

        # VWAP = total_value / total_filled = 10010 / 0.2 = 50050
        assert stats['vwap'] == 50050.0

        # Completion rate = (0.2 / 1.0) * 100 = 20%
        assert stats['completion_rate'] == 20.0

    def test_calculate_statistics_maker_taker_counts(self, temp_storage_dir, sample_twap_order, sample_order_fills):
        """Test that maker/taker order counts are correct."""
        tracker = TWAPTracker(temp_storage_dir)

        tracker.save_twap_order(sample_twap_order)
        tracker.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        stats = tracker.calculate_twap_statistics(sample_twap_order.twap_id)

        # From sample_order_fills: 1 maker, 1 taker
        assert stats['maker_fills'] == 1
        assert stats['taker_fills'] == 1
        assert stats['num_fills'] == 2

    def test_calculate_statistics_no_fills(self, temp_storage_dir, sample_twap_order):
        """Test statistics for an order with no fills."""
        tracker = TWAPTracker(temp_storage_dir)

        tracker.save_twap_order(sample_twap_order)
        # Don't save any fills

        stats = tracker.calculate_twap_statistics(sample_twap_order.twap_id)

        # Should have zero values for fill-dependent metrics
        assert stats['total_filled'] == 0
        assert stats['total_value_filled'] == 0
        assert stats['total_fees'] == 0
        assert stats['maker_fills'] == 0
        assert stats['taker_fills'] == 0
        assert stats['num_fills'] == 0
        assert stats['completion_rate'] == 0.0
        assert stats['vwap'] == 0.0

    def test_calculate_statistics_nonexistent_order(self, temp_storage_dir):
        """Test statistics for a nonexistent order."""
        tracker = TWAPTracker(temp_storage_dir)

        stats = tracker.calculate_twap_statistics('nonexistent-id')

        # Should return empty dict
        assert stats == {}

    def test_calculate_statistics_includes_timestamps(self, temp_storage_dir, sample_twap_order, sample_order_fills):
        """Test that statistics include first and last fill times."""
        tracker = TWAPTracker(temp_storage_dir)

        tracker.save_twap_order(sample_twap_order)
        tracker.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        stats = tracker.calculate_twap_statistics(sample_twap_order.twap_id)

        assert 'first_fill_time' in stats
        assert 'last_fill_time' in stats
        assert stats['first_fill_time'] == '2025-01-01T00:00:00Z'
        assert stats['last_fill_time'] == '2025-01-01T00:01:00Z'


# =============================================================================
# Fee Calculation Tests
# =============================================================================

@pytest.mark.unit
class TestFeeCalculation:
    """Tests for fee calculation logic."""

    def test_calculate_maker_fee(self, temp_storage_dir):
        """Test maker fee calculation."""
        tracker = TWAPTracker(temp_storage_dir)

        fee_tier = {
            'maker_fee_rate': '0.002',  # 0.2%
            'taker_fee_rate': '0.005'   # 0.5%
        }

        # Calculate maker fee for 1 BTC at $50,000
        fee = tracker.calculate_fee(
            fill_size=1.0,
            fill_price=50000.0,
            fee_tier=fee_tier,
            is_maker=True
        )

        # Expected: 1.0 * 50000.0 * 0.002 = 100.0
        assert fee == pytest.approx(100.0)

    def test_calculate_taker_fee(self, temp_storage_dir):
        """Test taker fee calculation."""
        tracker = TWAPTracker(temp_storage_dir)

        fee_tier = {
            'maker_fee_rate': '0.002',
            'taker_fee_rate': '0.005'
        }

        # Calculate taker fee for 2 BTC at $50,000
        fee = tracker.calculate_fee(
            fill_size=2.0,
            fill_price=50000.0,
            fee_tier=fee_tier,
            is_maker=False
        )

        # Expected: 2.0 * 50000.0 * 0.005 = 500.0
        assert fee == pytest.approx(500.0)

    def test_calculate_fee_zero_rate(self, temp_storage_dir):
        """Test fee calculation with zero fee rate."""
        tracker = TWAPTracker(temp_storage_dir)

        fee_tier = {
            'maker_fee_rate': '0',
            'taker_fee_rate': '0'
        }

        fee = tracker.calculate_fee(
            fill_size=1.0,
            fill_price=50000.0,
            fee_tier=fee_tier,
            is_maker=True
        )

        assert fee == 0.0

    def test_calculate_fee_small_amounts(self, temp_storage_dir):
        """Test fee calculation with small amounts."""
        tracker = TWAPTracker(temp_storage_dir)

        fee_tier = {
            'maker_fee_rate': '0.004',
            'taker_fee_rate': '0.006'
        }

        # Small order: 0.01 BTC at $50,000
        fee = tracker.calculate_fee(
            fill_size=0.01,
            fill_price=50000.0,
            fee_tier=fee_tier,
            is_maker=True
        )

        # Expected: 0.01 * 50000.0 * 0.004 = 2.0
        assert fee == pytest.approx(2.0)


# =============================================================================
# Integration Tests (Multiple Components)
# =============================================================================

@pytest.mark.unit
class TestTWAPTrackerIntegration:
    """Integration tests combining multiple TWAPTracker features."""

    def test_complete_twap_lifecycle(self, temp_storage_dir):
        """
        Test a complete TWAP order lifecycle.

        This simulates:
        1. Creating a TWAP order
        2. Adding fills over time
        3. Calculating statistics
        4. Verifying completion
        """
        tracker = TWAPTracker(temp_storage_dir)

        # Create TWAP order
        order = TWAPOrder(
            twap_id='lifecycle-test',
            market='BTC-USDC',
            side='BUY',
            total_size=1.0,
            limit_price=50000.0,
            num_slices=4,
            start_time='2025-01-01T00:00:00Z',
            status='active',
            orders=['order-1', 'order-2', 'order-3', 'order-4'],
            failed_slices=[],
            slice_statuses=[]
        )
        tracker.save_twap_order(order)

        # Simulate fills coming in over time
        fills = [
            OrderFill('order-1', 'trade-1', 0.25, 50000.0, 5.0, True, '2025-01-01T00:00:00Z'),
            OrderFill('order-2', 'trade-2', 0.25, 50050.0, 5.0, True, '2025-01-01T00:05:00Z'),
            OrderFill('order-3', 'trade-3', 0.25, 50100.0, 5.0, False, '2025-01-01T00:10:00Z'),
            OrderFill('order-4', 'trade-4', 0.25, 50150.0, 5.0, False, '2025-01-01T00:15:00Z'),
        ]
        tracker.save_twap_fills(order.twap_id, fills)

        # Calculate final statistics
        stats = tracker.calculate_twap_statistics(order.twap_id)

        # Verify order completed
        assert stats['total_filled'] == 1.0
        assert stats['completion_rate'] == 100.0

        # Verify VWAP calculation
        # VWAP = (0.25*50000 + 0.25*50050 + 0.25*50100 + 0.25*50150) / 1.0 = 50075
        assert stats['vwap'] == pytest.approx(50075.0)

        # Verify fees
        assert stats['total_fees'] == 20.0

        # Verify maker/taker split
        assert stats['maker_fills'] == 2
        assert stats['taker_fills'] == 2
