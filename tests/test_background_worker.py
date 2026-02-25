"""Tests for OrderStatusChecker background worker."""

import pytest
import threading
from queue import Queue
from unittest.mock import Mock, patch

from background_worker import OrderStatusChecker


# =============================================================================
# Helpers
# =============================================================================

def _make_terminal(**overrides):
    """Create a lightweight mock terminal with just the attrs OrderStatusChecker needs."""
    t = Mock()
    t.is_running = True
    t.twap_lock = threading.Lock()
    t.conditional_lock = threading.Lock()
    t.order_lock = threading.Lock()
    t.twap_orders = {}
    t.order_to_twap_map = {}
    t.order_to_conditional_map = {}
    t.filled_orders = []
    t.order_queue = Queue()
    t.check_order_fills_batch = Mock(return_value={})
    t.conditional_order_tracker = Mock()
    for k, v in overrides.items():
        setattr(t, k, v)
    return t


def _twap_order_entry(**kw):
    """Default TWAP order tracking dict."""
    defaults = {
        'total_filled': 0.0,
        'total_value_filled': 0.0,
        'total_fees': 0.0,
        'maker_orders': 0,
        'taker_orders': 0,
    }
    defaults.update(kw)
    return defaults


# =============================================================================
# _process_twap_order
# =============================================================================

class TestProcessTwapOrder:
    """Tests for _process_twap_order."""

    def test_filled_order_updates_stats(self):
        t = _make_terminal()
        t.order_to_twap_map = {'ord-1': 'twap-A'}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 0.5,
                'filled_value': 25000.0,
                'fees': 12.5,
                'is_maker': True,
            }
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-1')

        assert t.twap_orders['twap-A']['total_filled'] == 0.5
        assert t.twap_orders['twap-A']['total_value_filled'] == 25000.0
        assert t.twap_orders['twap-A']['total_fees'] == 12.5
        assert t.twap_orders['twap-A']['maker_orders'] == 1
        assert t.twap_orders['twap-A']['taker_orders'] == 0
        assert 'ord-1' in t.filled_orders

    def test_filled_taker_order(self):
        t = _make_terminal()
        t.order_to_twap_map = {'ord-1': 'twap-A'}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 1.0,
                'filled_value': 50000.0,
                'fees': 25.0,
                'is_maker': False,
            }
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-1')

        assert t.twap_orders['twap-A']['taker_orders'] == 1
        assert t.twap_orders['twap-A']['maker_orders'] == 0

    def test_unfilled_order_is_requeued(self):
        t = _make_terminal()
        t.order_to_twap_map = {'ord-1': 'twap-A'}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.check_order_fills_batch.return_value = {
            'ord-1': {'status': 'OPEN'}
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-1')

        assert 'ord-1' not in t.filled_orders
        assert not t.order_queue.empty()
        assert t.order_queue.get_nowait() == 'ord-1'

    def test_batch_collects_up_to_50(self):
        t = _make_terminal()
        # Put 55 orders on queue; first one is passed directly
        for i in range(54):
            t.order_queue.put(f'ord-{i}')
        t.order_to_twap_map = {f'ord-{i}': 'twap-A' for i in range(55)}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.check_order_fills_batch.return_value = {}

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-54')

        # Should have called batch check with up to 50 order IDs
        called_ids = t.check_order_fills_batch.call_args[0][0]
        assert len(called_ids) == 50

    def test_dict_format_order(self):
        t = _make_terminal()
        t.order_to_twap_map = {'ord-1': 'twap-A'}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 0.1,
                'filled_value': 5000.0,
                'fees': 2.5,
                'is_maker': True,
            }
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, {'order_id': 'ord-1'})

        assert 'ord-1' in t.filled_orders
        assert t.twap_orders['twap-A']['total_filled'] == 0.1

    def test_order_without_twap_mapping_is_skipped(self):
        t = _make_terminal()
        t.order_to_twap_map = {}  # no mapping
        t.check_order_fills_batch.return_value = {
            'ord-1': {'status': 'FILLED', 'filled_size': 1.0, 'filled_value': 50000.0, 'fees': 0, 'is_maker': True}
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-1')

        assert t.filled_orders == []

    def test_duplicate_fill_not_double_counted(self):
        t = _make_terminal()
        t.order_to_twap_map = {'ord-1': 'twap-A'}
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.filled_orders = ['ord-1']  # already filled
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 0.5,
                'filled_value': 25000.0,
                'fees': 12.5,
                'is_maker': True,
            }
        }

        checker = OrderStatusChecker(t)
        checker._process_twap_order(t, 'ord-1')

        # filled_orders should not have a duplicate
        assert t.filled_orders.count('ord-1') == 1
        # But stats still get updated (the guard is only on filled_orders list)
        assert t.twap_orders['twap-A']['total_filled'] == 0.5


# =============================================================================
# _process_conditional_order
# =============================================================================

class TestProcessConditionalOrder:
    """Tests for _process_conditional_order."""

    def test_filled_conditional_updates_tracker(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 1.0,
                'filled_value': 50000.0,
                'fees': 25.0,
                'avg_price': 50000.0,
            }
        }
        t.conditional_order_tracker.update_order_status.return_value = True

        checker = OrderStatusChecker(t)
        with patch('background_worker.print_success'):
            checker._process_conditional_order(t, 'ord-1')

        t.conditional_order_tracker.update_order_status.assert_called_once_with(
            order_id='cond-A',
            order_type='stop_limit',
            status='FILLED',
            fill_info={
                'filled_size': '1.0',
                'filled_value': '50000.0',
                'fees': '25.0',
            }
        )
        assert 'ord-1' not in t.order_to_conditional_map

    def test_cancelled_conditional_updates_tracker(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'CANCELLED',
                'filled_size': 0,
                'filled_value': 0,
                'fees': 0,
            }
        }
        t.conditional_order_tracker.update_order_status.return_value = True

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, 'ord-1')

        t.conditional_order_tracker.update_order_status.assert_called_once()
        call_kwargs = t.conditional_order_tracker.update_order_status.call_args[1]
        assert call_kwargs['status'] == 'CANCELLED'
        assert 'ord-1' not in t.order_to_conditional_map

    def test_expired_conditional_updates_tracker(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('bracket', 'cond-B')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'EXPIRED',
                'filled_size': 0,
                'filled_value': 0,
                'fees': 0,
            }
        }
        t.conditional_order_tracker.update_order_status.return_value = True

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, 'ord-1')

        call_kwargs = t.conditional_order_tracker.update_order_status.call_args[1]
        assert call_kwargs['status'] == 'EXPIRED'

    def test_unfilled_conditional_is_requeued(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {'status': 'OPEN'}
        }

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, 'ord-1')

        assert not t.order_queue.empty()
        assert t.order_queue.get_nowait() == 'ord-1'
        # Should still be in the map
        assert 'ord-1' in t.order_to_conditional_map

    def test_unknown_conditional_id_returns_early(self):
        t = _make_terminal()
        t.order_to_conditional_map = {}  # no mapping

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, 'ord-unknown')

        t.check_order_fills_batch.assert_not_called()

    def test_dict_format_conditional_order(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {'status': 'OPEN'}
        }

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, {'order_id': 'ord-1'})

        t.check_order_fills_batch.assert_called_once_with(['ord-1'])
        # Requeued as order_id string (per the code: t.order_queue.put(order_id))
        assert t.order_queue.get_nowait() == 'ord-1'

    def test_tracker_returns_false_no_removal(self):
        """If update_order_status returns False, order stays in map."""
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}
        t.check_order_fills_batch.return_value = {
            'ord-1': {
                'status': 'FILLED',
                'filled_size': 1.0,
                'filled_value': 50000.0,
                'fees': 25.0,
            }
        }
        t.conditional_order_tracker.update_order_status.return_value = False

        checker = OrderStatusChecker(t)
        checker._process_conditional_order(t, 'ord-1')

        # Should NOT be removed since tracker returned False
        assert 'ord-1' in t.order_to_conditional_map


# =============================================================================
# run loop
# =============================================================================

class TestRunLoop:
    """Tests for the run() main loop."""

    def test_shutdown_signal_exits(self):
        t = _make_terminal()
        t.twap_orders = {'twap-A': {}}
        t.order_queue.put(None)

        checker = OrderStatusChecker(t)
        checker.run()  # Should exit without hanging

    def test_no_active_orders_sleeps(self):
        t = _make_terminal()
        # No twap_orders and no conditional orders

        def stop_after_one_iteration(*args, **kwargs):
            t.is_running = False

        with patch('background_worker.time.sleep', side_effect=stop_after_one_iteration) as mock_sleep:
            checker = OrderStatusChecker(t)
            checker.run()

        mock_sleep.assert_called_with(5)

    def test_exception_in_processing_continues(self):
        t = _make_terminal()
        t.twap_orders = {'twap-A': {}}
        t.order_to_twap_map = {'ord-1': 'twap-A'}

        # Make batch check raise, then stop the loop on the error-handler sleep
        t.check_order_fills_batch.side_effect = RuntimeError("API error")
        t.order_queue.put('ord-1')

        def stop_loop(*args, **kwargs):
            t.is_running = False

        with patch('background_worker.time.sleep', side_effect=stop_loop):
            checker = OrderStatusChecker(t)
            checker.run()

        # Should not raise; the loop catches and continues
        t.check_order_fills_batch.assert_called()

    def test_processes_twap_order_from_queue(self):
        t = _make_terminal()
        t.twap_orders = {'twap-A': _twap_order_entry()}
        t.order_to_twap_map = {'ord-1': 'twap-A'}

        def fill_and_stop(order_ids):
            # Stop the loop after processing so we don't hang
            t.is_running = False
            return {
                'ord-1': {
                    'status': 'FILLED',
                    'filled_size': 0.1,
                    'filled_value': 5000.0,
                    'fees': 2.5,
                    'is_maker': True,
                }
            }

        t.check_order_fills_batch.side_effect = fill_and_stop
        t.order_queue.put('ord-1')

        checker = OrderStatusChecker(t)
        checker.run()

        assert 'ord-1' in t.filled_orders

    def test_processes_conditional_order_from_queue(self):
        t = _make_terminal()
        t.order_to_conditional_map = {'ord-1': ('stop_limit', 'cond-A')}

        def check_and_stop(order_ids):
            # Stop the loop after processing
            t.is_running = False
            return {'ord-1': {'status': 'OPEN'}}

        t.check_order_fills_batch.side_effect = check_and_stop
        t.order_queue.put('ord-1')

        checker = OrderStatusChecker(t)
        with patch('background_worker.time.sleep'):
            checker.run()

        t.check_order_fills_batch.assert_called_with(['ord-1'])
