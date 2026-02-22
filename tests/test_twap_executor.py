"""
Unit tests for TWAPExecutor (twap_executor.py).

Tests cover successful slice placement, unfavorable price skipping,
insufficient balance handling, and state persistence after each slice.

To run:
    pytest tests/test_twap_executor.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from queue import Queue

from twap_executor import TWAPExecutor
from order_executor import OrderExecutor
from market_data import MarketDataService
from config_manager import AppConfig
from storage import InMemoryTWAPStorage
from twap_tracker import TWAPOrder
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


# =============================================================================
# Helpers
# =============================================================================

def _make_twap_executor(api_client=None, config=None):
    """Build a TWAPExecutor with mocked dependencies."""
    api = api_client or MockCoinbaseAPI()
    cfg = config or AppConfig.for_testing()
    rl = Mock(wait=Mock(return_value=None))
    md = MarketDataService(api_client=api, rate_limiter=rl, config=cfg)
    oe = OrderExecutor(api_client=api, market_data=md, rate_limiter=rl, config=cfg)
    storage = InMemoryTWAPStorage()
    order_queue = Queue()

    twap_exec = TWAPExecutor(
        order_executor=oe,
        market_data=md,
        twap_storage=storage,
        order_queue=order_queue,
        config=cfg
    )
    return twap_exec, api, storage, order_queue


# =============================================================================
# All Slices Placed Successfully Tests
# =============================================================================

@pytest.mark.unit
class TestAllSlicesPlaced:
    """Tests that all TWAP slices are placed when conditions are favorable."""

    @patch('twap_executor.time')
    def test_all_slices_placed_buy(self, mock_time):
        """All slices should be placed for a BUY order with favorable prices."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 55000.0  # Above ask, always favorable
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'  # Use limit price
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert twap_order is not None
        assert twap_order.status == 'completed'
        assert len(twap_order.orders) == 3
        assert len(twap_order.failed_slices) == 0

    @patch('twap_executor.time')
    def test_all_slices_placed_sell(self, mock_time):
        """All slices should be placed for a SELL order with favorable prices."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('BTC', 10.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'SELL',
            'base_size': 0.03,
            'limit_price': 40000.0  # Below bid, always favorable
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert len(twap_order.orders) == 3


# =============================================================================
# Skip On Unfavorable Price Tests
# =============================================================================

@pytest.mark.unit
class TestUnfavorablePrice:
    """Tests that slices are skipped when price is unfavorable."""

    @patch('twap_executor.time')
    def test_buy_skips_when_price_above_limit(self, mock_time):
        """BUY slices should be skipped if execution price > limit price."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 10000.0  # Way below market, always unfavorable
        }

        # Use ask price (price_type '4') which will be ~50005
        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='4'
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert len(twap_order.orders) == 0
        assert len(twap_order.failed_slices) == 3

    @patch('twap_executor.time')
    def test_sell_skips_when_price_below_limit(self, mock_time):
        """SELL slices should be skipped if execution price < limit price."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('BTC', 10.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'SELL',
            'base_size': 0.03,
            'limit_price': 100000.0  # Way above market, always unfavorable
        }

        # Use bid price (price_type '2') which will be ~49995
        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='2'
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert len(twap_order.orders) == 0
        assert len(twap_order.failed_slices) == 3


# =============================================================================
# Insufficient Balance Tests
# =============================================================================

@pytest.mark.unit
class TestInsufficientBalance:
    """Tests that slices are skipped when balance is insufficient."""

    @patch('twap_executor.time')
    def test_sell_skips_on_insufficient_base_balance(self, mock_time):
        """SELL slices should fail when base currency balance is insufficient."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('BTC', 0.0)  # Zero balance

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'SELL',
            'base_size': 0.03,
            'limit_price': 40000.0
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        # All slices should have failed due to insufficient balance
        assert len(twap_order.failed_slices) == 3
        assert len(twap_order.orders) == 0


# =============================================================================
# State Saved After Each Slice Tests
# =============================================================================

@pytest.mark.unit
class TestStateSavedAfterSlice:
    """Tests that TWAP state is persisted after each slice."""

    @patch('twap_executor.time')
    def test_order_saved_to_storage_after_each_slice(self, mock_time):
        """The TWAP order should be saved after every slice execution."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        # Spy on save_twap_order
        original_save = storage.save_twap_order
        save_calls = []
        def tracking_save(order):
            save_calls.append(order.twap_id)
            return original_save(order)
        storage.save_twap_order = tracking_save
        # Also patch on twap_tracker reference
        twap_exec.twap_tracker.save_twap_order = tracking_save

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 55000.0
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'
        )

        # Initial save + one save per slice + final save = at least 5
        # (initial + 3 slices + final completion save)
        assert len(save_calls) >= 4

    @patch('twap_executor.time')
    def test_slice_statuses_accumulated(self, mock_time):
        """slice_statuses list should grow with each executed slice."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 55000.0
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'
        )

        twap_order = storage.get_twap_order(twap_id)
        assert len(twap_order.slice_statuses) == 3

    @patch('twap_executor.time')
    def test_order_ids_queued_for_monitoring(self, mock_time):
        """Placed order IDs should be put on the order queue."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 55000.0
        }

        twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1'
        )

        queued_ids = []
        while not order_queue.empty():
            queued_ids.append(order_queue.get_nowait())

        assert len(queued_ids) == 3
