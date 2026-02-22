"""
Unit tests for ConditionalOrderTracker persistence.

Tests cover CRUD operations for all three order types (stop-limit, bracket,
attached bracket), unified queries, status updates, deletion, and statistics.

To run:
    pytest tests/test_conditional_order_tracker.py -v
"""

import pytest
import tempfile
import shutil

from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder
from conditional_order_tracker import ConditionalOrderTracker


@pytest.mark.unit
class TestStopLimitCRUD:
    """Tests for stop-limit order CRUD operations."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    @pytest.fixture
    def sample_stop_limit(self):
        return StopLimitOrder(
            order_id='sl-001',
            client_order_id='client-sl-001',
            product_id='BTC-USD',
            side='SELL',
            base_size='0.1',
            stop_price='48000',
            limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS',
            status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )

    def test_save_and_retrieve(self, tracker, sample_stop_limit):
        tracker.save_stop_limit_order(sample_stop_limit)
        loaded = tracker.get_stop_limit_order('sl-001')
        assert loaded is not None
        assert loaded.order_id == 'sl-001'
        assert loaded.product_id == 'BTC-USD'
        assert loaded.stop_price == '48000'
        assert loaded.status == 'PENDING'

    def test_overwrite(self, tracker, sample_stop_limit):
        tracker.save_stop_limit_order(sample_stop_limit)
        sample_stop_limit.status = 'TRIGGERED'
        tracker.save_stop_limit_order(sample_stop_limit)
        loaded = tracker.get_stop_limit_order('sl-001')
        assert loaded.status == 'TRIGGERED'

    def test_get_nonexistent(self, tracker):
        assert tracker.get_stop_limit_order('nonexistent') is None

    def test_list_all(self, tracker):
        for i in range(3):
            order = StopLimitOrder(
                order_id=f'sl-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_stop_limit_order(order)
        orders = tracker.list_stop_limit_orders()
        assert len(orders) == 3

    def test_list_by_status(self, tracker):
        for i, status in enumerate(['PENDING', 'FILLED', 'PENDING']):
            order = StopLimitOrder(
                order_id=f'sl-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status=status,
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_stop_limit_order(order)
        pending = tracker.list_stop_limit_orders(status='PENDING')
        assert len(pending) == 2
        filled = tracker.list_stop_limit_orders(status='FILLED')
        assert len(filled) == 1


@pytest.mark.unit
class TestBracketCRUD:
    """Tests for bracket order CRUD operations."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    @pytest.fixture
    def sample_bracket(self):
        return BracketOrder(
            order_id='br-001',
            client_order_id='client-br-001',
            product_id='BTC-USD',
            side='SELL',
            base_size='0.1',
            limit_price='55000',
            stop_trigger_price='48000',
            status='ACTIVE',
            created_at='2026-01-01T12:00:00Z'
        )

    def test_save_and_retrieve(self, tracker, sample_bracket):
        tracker.save_bracket_order(sample_bracket)
        loaded = tracker.get_bracket_order('br-001')
        assert loaded is not None
        assert loaded.order_id == 'br-001'
        assert loaded.limit_price == '55000'
        assert loaded.stop_trigger_price == '48000'

    def test_overwrite(self, tracker, sample_bracket):
        tracker.save_bracket_order(sample_bracket)
        sample_bracket.status = 'FILLED'
        tracker.save_bracket_order(sample_bracket)
        loaded = tracker.get_bracket_order('br-001')
        assert loaded.status == 'FILLED'

    def test_get_nonexistent(self, tracker):
        assert tracker.get_bracket_order('nonexistent') is None

    def test_list_all(self, tracker):
        for i in range(3):
            order = BracketOrder(
                order_id=f'br-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                limit_price='55000', stop_trigger_price='48000',
                status='ACTIVE',
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_bracket_order(order)
        orders = tracker.list_bracket_orders()
        assert len(orders) == 3

    def test_list_by_status(self, tracker):
        for i, status in enumerate(['ACTIVE', 'FILLED', 'ACTIVE']):
            order = BracketOrder(
                order_id=f'br-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                limit_price='55000', stop_trigger_price='48000',
                status=status,
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_bracket_order(order)
        active = tracker.list_bracket_orders(status='ACTIVE')
        assert len(active) == 2


@pytest.mark.unit
class TestAttachedBracketCRUD:
    """Tests for attached bracket order CRUD operations."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    @pytest.fixture
    def sample_attached(self):
        return AttachedBracketOrder(
            entry_order_id='ab-001',
            client_order_id='client-ab-001',
            product_id='BTC-USD',
            side='BUY',
            base_size='0.1',
            entry_limit_price='50000',
            take_profit_price='55000',
            stop_loss_price='48000',
            status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )

    def test_save_and_retrieve(self, tracker, sample_attached):
        tracker.save_attached_bracket_order(sample_attached)
        loaded = tracker.get_attached_bracket_order('ab-001')
        assert loaded is not None
        assert loaded.entry_order_id == 'ab-001'
        assert loaded.take_profit_price == '55000'
        assert loaded.stop_loss_price == '48000'

    def test_overwrite(self, tracker, sample_attached):
        tracker.save_attached_bracket_order(sample_attached)
        sample_attached.status = 'ENTRY_FILLED'
        tracker.save_attached_bracket_order(sample_attached)
        loaded = tracker.get_attached_bracket_order('ab-001')
        assert loaded.status == 'ENTRY_FILLED'

    def test_get_nonexistent(self, tracker):
        assert tracker.get_attached_bracket_order('nonexistent') is None

    def test_list_all(self, tracker):
        for i in range(3):
            order = AttachedBracketOrder(
                entry_order_id=f'ab-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='BUY', base_size='0.1',
                entry_limit_price='50000', take_profit_price='55000',
                stop_loss_price='48000', status='PENDING',
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_attached_bracket_order(order)
        orders = tracker.list_attached_bracket_orders()
        assert len(orders) == 3

    def test_list_by_status(self, tracker):
        for i, status in enumerate(['PENDING', 'ENTRY_FILLED', 'TP_FILLED']):
            order = AttachedBracketOrder(
                entry_order_id=f'ab-{i}', client_order_id=f'client-{i}',
                product_id='BTC-USD', side='BUY', base_size='0.1',
                entry_limit_price='50000', take_profit_price='55000',
                stop_loss_price='48000', status=status,
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            )
            tracker.save_attached_bracket_order(order)
        pending = tracker.list_attached_bracket_orders(status='PENDING')
        assert len(pending) == 1
        filled = tracker.list_attached_bracket_orders(status='ENTRY_FILLED')
        assert len(filled) == 1


@pytest.mark.unit
class TestUnifiedQueries:
    """Tests for cross-type query methods."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    def _add_mixed_orders(self, tracker):
        """Add one of each type with mixed statuses."""
        tracker.save_stop_limit_order(StopLimitOrder(
            order_id='sl-1', client_order_id='c-sl-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        ))
        tracker.save_stop_limit_order(StopLimitOrder(
            order_id='sl-2', client_order_id='c-sl-2',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='FILLED',
            created_at='2026-01-02T12:00:00Z'
        ))
        tracker.save_bracket_order(BracketOrder(
            order_id='br-1', client_order_id='c-br-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            limit_price='55000', stop_trigger_price='48000',
            status='ACTIVE', created_at='2026-01-03T12:00:00Z'
        ))
        tracker.save_attached_bracket_order(AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-ab-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='ENTRY_FILLED',
            created_at='2026-01-04T12:00:00Z'
        ))

    def test_list_all_active_orders_mixed_types(self, tracker):
        self._add_mixed_orders(tracker)
        active = tracker.list_all_active_orders()
        # sl-1 (PENDING), br-1 (ACTIVE), ab-1 (ENTRY_FILLED) are active
        assert len(active) == 3

    def test_list_all_active_orders_empty(self, tracker):
        active = tracker.list_all_active_orders()
        assert len(active) == 0

    def test_get_order_by_id_stop_limit(self, tracker):
        self._add_mixed_orders(tracker)
        order = tracker.get_order_by_id('sl-1')
        assert order is not None
        assert isinstance(order, StopLimitOrder)

    def test_get_order_by_id_bracket(self, tracker):
        self._add_mixed_orders(tracker)
        order = tracker.get_order_by_id('br-1')
        assert order is not None
        assert isinstance(order, BracketOrder)

    def test_get_order_by_id_attached_bracket(self, tracker):
        self._add_mixed_orders(tracker)
        order = tracker.get_order_by_id('ab-1')
        assert order is not None
        assert isinstance(order, AttachedBracketOrder)

    def test_get_order_by_id_nonexistent(self, tracker):
        self._add_mixed_orders(tracker)
        assert tracker.get_order_by_id('nonexistent') is None


@pytest.mark.unit
class TestStatusUpdates:
    """Tests for update_order_status across all types."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    def test_update_stop_limit_status(self, tracker):
        order = StopLimitOrder(
            order_id='sl-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_stop_limit_order(order)
        result = tracker.update_order_status('sl-1', 'stop_limit', 'TRIGGERED')
        assert result is True
        loaded = tracker.get_stop_limit_order('sl-1')
        assert loaded.status == 'TRIGGERED'

    def test_update_stop_limit_with_fill_info(self, tracker):
        order = StopLimitOrder(
            order_id='sl-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_stop_limit_order(order)
        result = tracker.update_order_status('sl-1', 'stop_limit', 'FILLED', fill_info={
            'filled_size': '0.1', 'filled_value': '4790', 'fees': '2.5'
        })
        assert result is True
        loaded = tracker.get_stop_limit_order('sl-1')
        assert loaded.filled_size == '0.1'
        assert loaded.filled_value == '4790'
        assert loaded.fees == '2.5'

    def test_update_stop_limit_triggered_at(self, tracker):
        order = StopLimitOrder(
            order_id='sl-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_stop_limit_order(order)
        result = tracker.update_order_status('sl-1', 'stop_limit', 'TRIGGERED', fill_info={
            'triggered_at': '2026-01-02T15:00:00Z'
        })
        assert result is True
        loaded = tracker.get_stop_limit_order('sl-1')
        assert loaded.triggered_at == '2026-01-02T15:00:00Z'

    def test_update_stop_limit_nonexistent(self, tracker):
        result = tracker.update_order_status('nonexistent', 'stop_limit', 'FILLED')
        assert result is False

    def test_update_bracket_status(self, tracker):
        order = BracketOrder(
            order_id='br-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            limit_price='55000', stop_trigger_price='48000',
            status='ACTIVE', created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_bracket_order(order)
        result = tracker.update_order_status('br-1', 'bracket', 'FILLED', fill_info={
            'total_filled_value': '5500', 'fees': '3.0',
            'take_profit_filled_size': '0.1'
        })
        assert result is True
        loaded = tracker.get_bracket_order('br-1')
        assert loaded.status == 'FILLED'
        assert loaded.take_profit_filled_size == '0.1'
        assert loaded.total_filled_value == '5500'

    def test_update_bracket_with_stop_loss_fill(self, tracker):
        order = BracketOrder(
            order_id='br-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            limit_price='55000', stop_trigger_price='48000',
            status='ACTIVE', created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_bracket_order(order)
        result = tracker.update_order_status('br-1', 'bracket', 'FILLED', fill_info={
            'stop_loss_filled_size': '0.1'
        })
        assert result is True
        loaded = tracker.get_bracket_order('br-1')
        assert loaded.stop_loss_filled_size == '0.1'

    def test_update_bracket_nonexistent(self, tracker):
        result = tracker.update_order_status('nonexistent', 'bracket', 'FILLED')
        assert result is False

    def test_update_attached_bracket_entry_filled(self, tracker):
        order = AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_attached_bracket_order(order)
        result = tracker.update_order_status('ab-1', 'attached_bracket', 'ENTRY_FILLED', fill_info={
            'filled_size': '0.1', 'filled_value': '5000', 'fees': '2.0'
        })
        assert result is True
        loaded = tracker.get_attached_bracket_order('ab-1')
        assert loaded.status == 'ENTRY_FILLED'
        assert loaded.entry_filled_size == '0.1'
        assert loaded.entry_filled_value == '5000'
        assert loaded.entry_fees == '2.0'

    def test_update_attached_bracket_tp_filled(self, tracker):
        order = AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='ENTRY_FILLED',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_attached_bracket_order(order)
        result = tracker.update_order_status('ab-1', 'attached_bracket', 'TP_FILLED', fill_info={
            'filled_size': '0.1', 'filled_value': '5500', 'fees': '2.5'
        })
        assert result is True
        loaded = tracker.get_attached_bracket_order('ab-1')
        assert loaded.status == 'TP_FILLED'
        assert loaded.exit_filled_size == '0.1'

    def test_update_attached_bracket_sl_filled(self, tracker):
        order = AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='ENTRY_FILLED',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_attached_bracket_order(order)
        result = tracker.update_order_status('ab-1', 'attached_bracket', 'SL_FILLED', fill_info={
            'filled_size': '0.1', 'filled_value': '4800', 'fees': '2.0'
        })
        assert result is True
        loaded = tracker.get_attached_bracket_order('ab-1')
        assert loaded.status == 'SL_FILLED'
        assert loaded.exit_filled_size == '0.1'

    def test_update_attached_bracket_nonexistent(self, tracker):
        result = tracker.update_order_status('nonexistent', 'attached_bracket', 'ENTRY_FILLED')
        assert result is False

    def test_update_unknown_order_type(self, tracker):
        result = tracker.update_order_status('any-id', 'unknown_type', 'FILLED')
        assert result is False


@pytest.mark.unit
class TestDeleteOrder:
    """Tests for order deletion."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    def test_delete_stop_limit(self, tracker):
        order = StopLimitOrder(
            order_id='sl-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_stop_limit_order(order)
        assert tracker.delete_order('sl-1', 'stop_limit') is True
        assert tracker.get_stop_limit_order('sl-1') is None

    def test_delete_bracket(self, tracker):
        order = BracketOrder(
            order_id='br-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            limit_price='55000', stop_trigger_price='48000',
            status='ACTIVE', created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_bracket_order(order)
        assert tracker.delete_order('br-1', 'bracket') is True
        assert tracker.get_bracket_order('br-1') is None

    def test_delete_attached_bracket(self, tracker):
        order = AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        )
        tracker.save_attached_bracket_order(order)
        assert tracker.delete_order('ab-1', 'attached_bracket') is True
        assert tracker.get_attached_bracket_order('ab-1') is None

    def test_delete_nonexistent(self, tracker):
        assert tracker.delete_order('nonexistent', 'stop_limit') is False

    def test_delete_unknown_type(self, tracker):
        assert tracker.delete_order('any-id', 'unknown_type') is False


@pytest.mark.unit
class TestStatistics:
    """Tests for get_statistics."""

    @pytest.fixture
    def tracker(self, tmp_path):
        return ConditionalOrderTracker(base_dir=str(tmp_path))

    def test_empty_statistics(self, tracker):
        stats = tracker.get_statistics()
        assert stats['stop_limit']['total'] == 0
        assert stats['bracket']['total'] == 0
        assert stats['attached_bracket']['total'] == 0

    def test_mixed_order_counts(self, tracker):
        # 2 stop-limit (1 active, 1 filled)
        for i, status in enumerate(['PENDING', 'FILLED']):
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id=f'sl-{i}', client_order_id=f'c-sl-{i}',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status=status,
                created_at=f'2026-01-0{i+1}T12:00:00Z'
            ))
        # 1 bracket (active)
        tracker.save_bracket_order(BracketOrder(
            order_id='br-1', client_order_id='c-br-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            limit_price='55000', stop_trigger_price='48000',
            status='ACTIVE', created_at='2026-01-01T12:00:00Z'
        ))
        # 1 attached bracket (completed)
        tracker.save_attached_bracket_order(AttachedBracketOrder(
            entry_order_id='ab-1', client_order_id='c-ab-1',
            product_id='BTC-USD', side='BUY', base_size='0.1',
            entry_limit_price='50000', take_profit_price='55000',
            stop_loss_price='48000', status='TP_FILLED',
            created_at='2026-01-01T12:00:00Z'
        ))

        stats = tracker.get_statistics()
        assert stats['stop_limit']['total'] == 2
        assert stats['stop_limit']['active'] == 1
        assert stats['stop_limit']['completed'] == 1
        assert stats['bracket']['total'] == 1
        assert stats['bracket']['active'] == 1
        assert stats['attached_bracket']['total'] == 1
        assert stats['attached_bracket']['completed'] == 1

    def test_stop_loss_vs_take_profit_counting(self, tracker):
        tracker.save_stop_limit_order(StopLimitOrder(
            order_id='sl-1', client_order_id='c-1',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='48000', limit_price='47900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='PENDING',
            created_at='2026-01-01T12:00:00Z'
        ))
        tracker.save_stop_limit_order(StopLimitOrder(
            order_id='sl-2', client_order_id='c-2',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='55000', limit_price='54900',
            stop_direction='STOP_DIRECTION_STOP_UP',
            order_type='TAKE_PROFIT', status='PENDING',
            created_at='2026-01-02T12:00:00Z'
        ))
        tracker.save_stop_limit_order(StopLimitOrder(
            order_id='sl-3', client_order_id='c-3',
            product_id='BTC-USD', side='SELL', base_size='0.1',
            stop_price='45000', limit_price='44900',
            stop_direction='STOP_DIRECTION_STOP_DOWN',
            order_type='STOP_LOSS', status='FILLED',
            created_at='2026-01-03T12:00:00Z'
        ))

        stats = tracker.get_statistics()
        assert stats['stop_limit']['stop_loss'] == 2
        assert stats['stop_limit']['take_profit'] == 1
