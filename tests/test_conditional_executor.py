"""
Unit tests for ConditionalExecutor (conditional_executor.py).

Tests cover stop-loss direction detection, take-profit direction detection,
bracket order validation, entry+bracket placement, view/cancel/sync operations.

To run:
    pytest tests/test_conditional_executor.py -v
"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, patch
from queue import Queue

from conditional_executor import ConditionalExecutor
from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder
from conditional_order_tracker import ConditionalOrderTracker
from order_executor import OrderExecutor
from market_data import MarketDataService
from config_manager import AppConfig
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


# =============================================================================
# Helpers
# =============================================================================

def _make_conditional_executor(api_client=None, config=None, tracker_dir=None):
    """Build a ConditionalExecutor with mocked dependencies."""
    api = api_client or MockCoinbaseAPI()
    cfg = config or AppConfig.for_testing()
    rl = Mock(wait=Mock(return_value=None))
    md = MarketDataService(api_client=api, rate_limiter=rl, config=cfg)
    oe = OrderExecutor(api_client=api, market_data=md, rate_limiter=rl, config=cfg)
    order_queue = Queue()

    if tracker_dir is None:
        tracker_dir = tempfile.mkdtemp()
    tracker = ConditionalOrderTracker(base_dir=tracker_dir)

    executor = ConditionalExecutor(
        api_client=api,
        market_data=md,
        order_executor=oe,
        conditional_tracker=tracker,
        order_queue=order_queue,
        config=cfg
    )
    return executor, api, md, tracker, tracker_dir


# =============================================================================
# Stop-Loss Direction Detection Tests
# =============================================================================

@pytest.mark.unit
class TestStopLossDirection:
    """Tests that stop-loss direction is auto-detected correctly."""

    def test_sell_stop_loss_below_market_is_stop_down(self):
        """SELL stop-loss with stop below market should use STOP_DIRECTION_STOP_DOWN."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('BTC', 10.0)

        try:
            # Mock get_conditional_order_input to return SELL order
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'SELL', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                # stop_price=48000 (below mid=50000), limit_price=47900, confirm=yes
                inputs = iter(['48000', '47900', 'yes'])
                order_id = executor.place_stop_loss_order(lambda prompt: next(inputs))

            assert order_id is not None
            # Verify the saved order
            order = tracker.get_stop_limit_order(order_id)
            assert order is not None
            assert order.stop_direction == 'STOP_DIRECTION_STOP_DOWN'
            assert order.order_type == 'STOP_LOSS'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_buy_stop_loss_above_market_is_stop_up(self):
        """BUY stop-loss with stop above market should use STOP_DIRECTION_STOP_UP."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('USDC', 100000.0)

        try:
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'BUY', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                # stop_price=52000 (above mid=50000) for BUY = stop loss
                inputs = iter(['52000', '52100', 'yes'])
                order_id = executor.place_stop_loss_order(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_stop_limit_order(order_id)
            assert order is not None
            assert order.stop_direction == 'STOP_DIRECTION_STOP_UP'
            assert order.order_type == 'STOP_LOSS'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_sell_stop_above_market_detected_as_take_profit(self):
        """SELL stop above market should be detected as TAKE_PROFIT."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('BTC', 10.0)

        try:
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'SELL', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                # stop_price=55000 (above mid=50000) for SELL = take profit
                inputs = iter(['55000', '54900', 'yes'])
                order_id = executor.place_stop_loss_order(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_stop_limit_order(order_id)
            assert order is not None
            assert order.stop_direction == 'STOP_DIRECTION_STOP_UP'
            assert order.order_type == 'TAKE_PROFIT'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# Take-Profit Direction Detection Tests
# =============================================================================

@pytest.mark.unit
class TestTakeProfitDirection:
    """Tests that take-profit direction is set correctly."""

    def test_sell_take_profit_uses_stop_up(self):
        """SELL take-profit should use STOP_DIRECTION_STOP_UP."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('BTC', 10.0)

        try:
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'SELL', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                inputs = iter(['55000', '54900', 'yes'])
                order_id = executor.place_take_profit_order(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_stop_limit_order(order_id)
            assert order is not None
            assert order.stop_direction == 'STOP_DIRECTION_STOP_UP'
            assert order.order_type == 'TAKE_PROFIT'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_buy_take_profit_uses_stop_down(self):
        """BUY take-profit should use STOP_DIRECTION_STOP_DOWN."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('USDC', 100000.0)

        try:
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'BUY', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                inputs = iter(['48000', '48100', 'yes'])
                order_id = executor.place_take_profit_order(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_stop_limit_order(order_id)
            assert order is not None
            assert order.stop_direction == 'STOP_DIRECTION_STOP_DOWN'
            assert order.order_type == 'TAKE_PROFIT'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_cancelled_take_profit_returns_none(self):
        """User declining confirmation should return None."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(executor, 'get_conditional_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'SELL', 'base_size': 0.1}), \
                 patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}):

                inputs = iter(['55000', '54900', 'no'])
                order_id = executor.place_take_profit_order(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# Bracket Validation Tests
# =============================================================================

@pytest.mark.unit
class TestBracketValidation:
    """Tests for bracket order validation (TP/SL relationship)."""

    def test_sell_bracket_sl_below_tp_succeeds(self):
        """SELL bracket: SL < TP should be valid."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('BTC', 10.0)

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                # product, side, size, tp_price, sl_price, confirm
                inputs = iter(['BTC-USDC', 'SELL', '0.1', '55000', '48000', 'yes'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_bracket_order(order_id)
            assert order is not None
            assert order.limit_price == str(md.round_price(55000, 'BTC-USDC'))
            assert order.stop_trigger_price == str(md.round_price(48000, 'BTC-USDC'))
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_sell_bracket_sl_above_tp_rejected(self):
        """SELL bracket: SL >= TP should be rejected."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                # SL (56000) > TP (55000) -- invalid for SELL
                inputs = iter(['BTC-USDC', 'SELL', '0.1', '55000', '56000', 'yes'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_buy_bracket_sl_above_tp_succeeds(self):
        """BUY (short exit) bracket: SL > TP should be valid."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('USDC', 100000.0)

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                # For BUY (short exit): SL should be above TP
                inputs = iter(['BTC-USDC', 'BUY', '0.1', '45000', '52000', 'yes'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is not None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_buy_bracket_sl_below_tp_rejected(self):
        """BUY (short exit) bracket: SL <= TP should be rejected."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                # For BUY (short exit): SL (44000) < TP (45000) -- invalid
                inputs = iter(['BTC-USDC', 'BUY', '0.1', '45000', '44000', 'yes'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_bracket_cancelled_by_user(self):
        """User declining confirmation should return None."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                inputs = iter(['BTC-USDC', 'SELL', '0.1', '55000', '48000', 'no'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_invalid_side_rejected(self):
        """Invalid side should return None."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(md, 'get_current_prices',
                              return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
                 patch.object(md, 'display_market_conditions'):

                inputs = iter(['BTC-USDC', 'INVALID', '0.1', '55000', '48000', 'yes'])
                order_id = executor.place_bracket_for_position(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# Entry + Bracket Tests
# =============================================================================

@pytest.mark.unit
class TestEntryWithBracket:
    """Tests for place_entry_with_bracket."""

    def test_buy_entry_with_bracket_success(self):
        """BUY entry with valid TP > SL should succeed."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('USDC', 100000.0)

        try:
            with patch.object(executor.order_executor, 'get_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'BUY',
                                            'base_size': 0.1, 'limit_price': 50000.0}):
                # tp_price, sl_price, confirm
                inputs = iter(['55000', '48000', 'yes'])
                order_id = executor.place_entry_with_bracket(lambda prompt: next(inputs))

            assert order_id is not None
            order = tracker.get_attached_bracket_order(order_id)
            assert order is not None
            assert order.status == 'PENDING'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_sell_entry_with_bracket_success(self):
        """SELL entry with valid SL > TP should succeed."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        api.set_account_balance('BTC', 10.0)

        try:
            with patch.object(executor.order_executor, 'get_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'SELL',
                                            'base_size': 0.1, 'limit_price': 50000.0}):
                # For SELL: SL must be above TP
                inputs = iter(['48000', '52000', 'yes'])
                order_id = executor.place_entry_with_bracket(lambda prompt: next(inputs))

            assert order_id is not None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_buy_entry_bracket_sl_above_tp_rejected(self):
        """BUY entry with SL >= TP should be rejected."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(executor.order_executor, 'get_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'BUY',
                                            'base_size': 0.1, 'limit_price': 50000.0}):
                # SL (56000) >= TP (55000) — invalid for BUY
                inputs = iter(['55000', '56000', 'yes'])
                order_id = executor.place_entry_with_bracket(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_entry_bracket_user_cancellation(self):
        """User declining should return None."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(executor.order_executor, 'get_order_input',
                              return_value={'product_id': 'BTC-USDC', 'side': 'BUY',
                                            'base_size': 0.1, 'limit_price': 50000.0}):
                inputs = iter(['55000', '48000', 'no'])
                order_id = executor.place_entry_with_bracket(lambda prompt: next(inputs))

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_entry_bracket_no_order_input(self):
        """If get_order_input returns None, should return None."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()

        try:
            with patch.object(executor.order_executor, 'get_order_input', return_value=None):
                order_id = executor.place_entry_with_bracket(lambda prompt: '')

            assert order_id is None
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# View Conditional Orders Tests
# =============================================================================

@pytest.mark.unit
class TestViewConditionalOrders:
    """Tests for view_conditional_orders."""

    def test_view_empty_state(self):
        """Empty tracker should print 'No conditional orders found'."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            executor.view_conditional_orders()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_view_with_stop_limit_orders(self):
        """Should display stop-limit orders table."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-view-1', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            executor.view_conditional_orders()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_view_with_bracket_orders(self):
        """Should display bracket orders table."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_bracket_order(BracketOrder(
                order_id='br-view-1', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                limit_price='55000', stop_trigger_price='48000',
                status='ACTIVE', created_at='2026-01-01T12:00:00Z'
            ))
            executor.view_conditional_orders()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_view_with_attached_bracket_orders(self):
        """Should display attached bracket orders table."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_attached_bracket_order(AttachedBracketOrder(
                entry_order_id='ab-view-1', client_order_id='c-1',
                product_id='BTC-USD', side='BUY', base_size='0.1',
                entry_limit_price='50000', take_profit_price='55000',
                stop_loss_price='48000', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            executor.view_conditional_orders()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_view_with_mixed_orders_shows_stats(self):
        """Mixed orders should show summary stats."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-mix-1', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            tracker.save_bracket_order(BracketOrder(
                order_id='br-mix-1', client_order_id='c-2',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                limit_price='55000', stop_trigger_price='48000',
                status='ACTIVE', created_at='2026-01-02T12:00:00Z'
            ))
            executor.view_conditional_orders()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# Cancel Conditional Orders Tests
# =============================================================================

@pytest.mark.unit
class TestCancelConditionalOrders:
    """Tests for cancel_conditional_orders."""

    def test_cancel_no_active_orders(self):
        """No active orders should print info and return."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            executor.cancel_conditional_orders(lambda prompt: '')
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_cancel_single_order(self):
        """Cancelling a single order should update status."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-cancel-1', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            # Register in mock API so cancel works
            api.orders['sl-cancel-1'] = {
                'order_id': 'sl-cancel-1', 'status': 'PENDING',
                'product_id': 'BTC-USD', 'side': 'SELL'
            }

            inputs = iter(['1'])
            executor.cancel_conditional_orders(lambda prompt: next(inputs))

            loaded = tracker.get_stop_limit_order('sl-cancel-1')
            assert loaded.status == 'CANCELLED'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_cancel_all_orders(self):
        """Cancelling 'all' should cancel all active orders."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            for i in range(2):
                oid = f'sl-cancel-all-{i}'
                tracker.save_stop_limit_order(StopLimitOrder(
                    order_id=oid, client_order_id=f'c-{i}',
                    product_id='BTC-USD', side='SELL', base_size='0.1',
                    stop_price='48000', limit_price='47900',
                    stop_direction='STOP_DIRECTION_STOP_DOWN',
                    order_type='STOP_LOSS', status='PENDING',
                    created_at=f'2026-01-0{i+1}T12:00:00Z'
                ))
                api.orders[oid] = {
                    'order_id': oid, 'status': 'PENDING',
                    'product_id': 'BTC-USD', 'side': 'SELL'
                }

            inputs = iter(['all'])
            executor.cancel_conditional_orders(lambda prompt: next(inputs))

            for i in range(2):
                loaded = tracker.get_stop_limit_order(f'sl-cancel-all-{i}')
                assert loaded.status == 'CANCELLED'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)


# =============================================================================
# Sync Conditional Order Statuses Tests
# =============================================================================

@pytest.mark.unit
class TestSyncConditionalStatuses:
    """Tests for sync_conditional_order_statuses."""

    def test_api_filled_updates_tracker(self):
        """API status FILLED should update tracker."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-sync-1', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            # Set the API order status to FILLED
            api.orders['sl-sync-1'] = {
                'order_id': 'sl-sync-1', 'status': 'FILLED',
                'product_id': 'BTC-USD', 'side': 'SELL'
            }

            executor.sync_conditional_order_statuses()

            loaded = tracker.get_stop_limit_order('sl-sync-1')
            assert loaded.status == 'FILLED'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_missing_order_marked_cancelled(self):
        """Order not in API response should be marked CANCELLED."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-sync-missing', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='PENDING',
                created_at='2026-01-01T12:00:00Z'
            ))
            # Don't add to api.orders — simulates order not found in API

            executor.sync_conditional_order_statuses()

            loaded = tracker.get_stop_limit_order('sl-sync-missing')
            assert loaded.status == 'CANCELLED'
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_completed_orders_not_re_synced(self):
        """Already-completed orders should not be re-synced."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            tracker.save_stop_limit_order(StopLimitOrder(
                order_id='sl-sync-done', client_order_id='c-1',
                product_id='BTC-USD', side='SELL', base_size='0.1',
                stop_price='48000', limit_price='47900',
                stop_direction='STOP_DIRECTION_STOP_DOWN',
                order_type='STOP_LOSS', status='FILLED',
                created_at='2026-01-01T12:00:00Z'
            ))

            executor.sync_conditional_order_statuses()

            loaded = tracker.get_stop_limit_order('sl-sync-done')
            assert loaded.status == 'FILLED'  # Should remain FILLED
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)

    def test_sync_handles_api_error(self):
        """API error during sync should not crash."""
        executor, api, md, tracker, tracker_dir = _make_conditional_executor()
        try:
            # Make list_orders raise
            api.list_orders = Mock(side_effect=RuntimeError("API error"))

            executor.sync_conditional_order_statuses()  # Should not raise
        finally:
            shutil.rmtree(tracker_dir, ignore_errors=True)
