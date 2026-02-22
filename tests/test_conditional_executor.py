"""
Unit tests for ConditionalExecutor (conditional_executor.py).

Tests cover stop-loss direction detection, take-profit direction detection,
and bracket order validation.

To run:
    pytest tests/test_conditional_executor.py -v
"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, patch
from queue import Queue

from conditional_executor import ConditionalExecutor
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
            with patch.object(executor.order_executor, 'get_conditional_order_input',
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
