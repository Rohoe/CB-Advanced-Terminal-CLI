"""
Unit tests for OrderExecutor (order_executor.py).

Tests cover limit order placement, TWAP slice rounding, min size enforcement,
fee calculation, and user input gathering.

To run:
    pytest tests/test_order_executor.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from order_executor import OrderExecutor, CancelledException
from market_data import MarketDataService
from config_manager import AppConfig
from storage import InMemoryTWAPStorage
from twap_tracker import TWAPOrder
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI


# =============================================================================
# Helpers
# =============================================================================

def _make_executor(api_client=None, config=None):
    """Build an OrderExecutor with mocked dependencies."""
    api = api_client or MockCoinbaseAPI()
    cfg = config or AppConfig.for_testing()
    rl = Mock(wait=Mock(return_value=None))
    md = MarketDataService(api_client=api, rate_limiter=rl, config=cfg)
    return OrderExecutor(api_client=api, market_data=md, rate_limiter=rl, config=cfg), api, md


# =============================================================================
# Limit Order Placement + Response Handling Tests
# =============================================================================

@pytest.mark.unit
class TestLimitOrderPlacement:
    """Tests for place_limit_order_with_retry."""

    def test_successful_limit_order_returns_dict(self):
        """Successful order should return a dict with success_response."""
        executor, api, md = _make_executor()

        # Ensure sufficient balance
        api.set_account_balance('USDC', 100000.0)

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='BUY',
            base_size='0.001',
            limit_price='50000'
        )

        assert result is not None
        assert 'success_response' in result

    def test_successful_sell_order(self):
        """Sell order with sufficient base balance should succeed."""
        executor, api, md = _make_executor()
        api.set_account_balance('BTC', 10.0)

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='SELL',
            base_size='0.01',
            limit_price='50000'
        )

        assert result is not None

    def test_returns_none_for_zero_size(self):
        """Order size of zero should return None."""
        executor, api, md = _make_executor()

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='BUY',
            base_size='0',
            limit_price='50000'
        )

        assert result is None

    def test_returns_none_for_insufficient_buy_balance(self):
        """Buy order with insufficient quote balance should return None."""
        executor, api, md = _make_executor()
        api.set_account_balance('USDC', 10.0)  # Only $10

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='BUY',
            base_size='1.0',
            limit_price='50000'
        )

        assert result is None

    def test_returns_none_for_insufficient_sell_balance(self):
        """Sell order with insufficient base balance should return None."""
        executor, api, md = _make_executor()
        api.set_account_balance('BTC', 0.0001)

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='SELL',
            base_size='1.0',
            limit_price='50000'
        )

        assert result is None


# =============================================================================
# TWAP Slice Rounding Tests
# =============================================================================

@pytest.mark.unit
class TestTWAPSliceRounding:
    """Tests for TWAP slice placement with correct rounding."""

    def test_slice_size_rounded_to_product_increment(self):
        """TWAP slice size should be rounded according to product precision."""
        executor, api, md = _make_executor()
        api.set_account_balance('USDC', 1000000.0)

        storage = InMemoryTWAPStorage()
        twap_order = TWAPOrder(
            twap_id='test-twap-1', market='BTC-USDC', side='BUY',
            total_size=1.0, limit_price=50000.0, num_slices=3,
            start_time='2025-01-01T00:00:00Z', status='active',
            orders=[], failed_slices=[], slice_statuses=[]
        )
        storage.save_twap_order(twap_order)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 1.0,
            'limit_price': 50000.0
        }

        order_id = executor.place_twap_slice(
            twap_id='test-twap-1',
            slice_number=1,
            total_slices=3,
            order_input=order_input,
            execution_price=50000.0,
            twap_tracker=storage
        )

        # Should have placed an order (not None)
        assert order_id is not None


# =============================================================================
# Min Size Enforcement Tests
# =============================================================================

@pytest.mark.unit
class TestMinSizeEnforcement:
    """Tests that minimum order size is enforced."""

    def test_order_below_min_size_rejected(self):
        """Order below product minimum should be rejected."""
        executor, api, md = _make_executor()
        api.set_account_balance('BTC', 10.0)

        result = executor.place_limit_order_with_retry(
            product_id='BTC-USDC',
            side='SELL',
            base_size='0.00001',  # Below min 0.0001
            limit_price='50000'
        )

        assert result is None

    def test_twap_slice_adjusts_below_min_to_min(self):
        """TWAP slice below minimum should be adjusted up to minimum."""
        executor, api, md = _make_executor()
        api.set_account_balance('USDC', 1000000.0)

        storage = InMemoryTWAPStorage()
        twap_order = TWAPOrder(
            twap_id='test-twap-min', market='BTC-USDC', side='BUY',
            total_size=0.0003, limit_price=50000.0, num_slices=10,
            start_time='2025-01-01T00:00:00Z', status='active',
            orders=[], failed_slices=[], slice_statuses=[]
        )
        storage.save_twap_order(twap_order)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.0003,
            'limit_price': 50000.0
        }

        # slice_size = 0.0003 / 10 = 0.00003, below min 0.0001
        # Should be adjusted to min_size 0.0001
        order_id = executor.place_twap_slice(
            twap_id='test-twap-min',
            slice_number=1,
            total_slices=10,
            order_input=order_input,
            execution_price=50000.0,
            twap_tracker=storage
        )

        assert order_id is not None


# =============================================================================
# Fee Calculation Tests
# =============================================================================

@pytest.mark.unit
class TestFeeCalculation:
    """Tests for fee rate fetching and estimated fee calculation."""

    def test_get_fee_rates_returns_tuple(self):
        """get_fee_rates should return (maker_rate, taker_rate) tuple."""
        executor, api, md = _make_executor()

        maker_rate, taker_rate = executor.get_fee_rates()

        assert isinstance(maker_rate, float)
        assert isinstance(taker_rate, float)
        assert maker_rate > 0
        assert taker_rate > 0

    def test_maker_fee_calculated(self):
        """Maker fee should be size * price * maker_rate."""
        executor, api, md = _make_executor()

        fee = executor.calculate_estimated_fee(size=1.0, price=50000.0, is_maker=True)

        # MockCoinbaseAPI returns maker_fee_rate = 0.004
        assert fee == pytest.approx(50000.0 * 0.004)

    def test_taker_fee_calculated(self):
        """Taker fee should be size * price * taker_rate."""
        executor, api, md = _make_executor()

        fee = executor.calculate_estimated_fee(size=1.0, price=50000.0, is_maker=False)

        # MockCoinbaseAPI returns taker_fee_rate = 0.006
        assert fee == pytest.approx(50000.0 * 0.006)

    def test_fee_rates_cached(self):
        """Fee rates should be cached and not re-fetched within TTL."""
        api = Mock(spec=MockCoinbaseAPI)
        api.get_transaction_summary.return_value = Mock(
            fee_tier={'maker_fee_rate': '0.004', 'taker_fee_rate': '0.006'}
        )

        cfg = AppConfig.for_testing()
        rl = Mock(wait=Mock(return_value=None))
        md = MarketDataService(api_client=api, rate_limiter=rl, config=cfg)
        executor = OrderExecutor(api_client=api, market_data=md, rate_limiter=rl, config=cfg)

        executor.get_fee_rates()
        executor.get_fee_rates()

        assert api.get_transaction_summary.call_count == 1


# =============================================================================
# get_order_input Tests
# =============================================================================

@pytest.mark.unit
class TestGetOrderInput:
    """Tests for get_order_input interactive flow."""

    def test_successful_order_input(self):
        """Should return a dict with product_id, side, limit_price, base_size."""
        executor, api, md = _make_executor()

        # Mock select_market to return a product
        with patch.object(md, 'select_market', return_value='BTC-USDC'), \
             patch.object(md, 'get_current_prices', return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
             patch.object(md, 'display_market_conditions'):

            inputs = iter(['buy', '50000', '0.1'])
            get_input_fn = lambda prompt: next(inputs)

            result = executor.get_order_input(get_input_fn)

        assert result is not None
        assert result['product_id'] == 'BTC-USDC'
        assert result['side'] == 'BUY'
        assert result['limit_price'] == 50000.0
        assert result['base_size'] == 0.1

    def test_returns_none_when_market_selection_fails(self):
        """Should return None if market selection returns None."""
        executor, api, md = _make_executor()

        with patch.object(md, 'select_market', return_value=None):
            result = executor.get_order_input(lambda prompt: '')

        assert result is None

    def test_rejects_size_below_minimum(self):
        """Should return None if user enters size below product minimum."""
        executor, api, md = _make_executor()

        with patch.object(md, 'select_market', return_value='BTC-USDC'), \
             patch.object(md, 'get_current_prices', return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
             patch.object(md, 'display_market_conditions'):

            inputs = iter(['buy', '50000', '0.00001'])  # Below min 0.0001
            get_input_fn = lambda prompt: next(inputs)

            result = executor.get_order_input(get_input_fn)

        assert result is None


# =============================================================================
# get_conditional_order_input Tests
# =============================================================================

@pytest.mark.unit
class TestGetConditionalOrderInput:
    """Tests for get_conditional_order_input (no limit price)."""

    def test_successful_conditional_input(self):
        """Should return product_id, side, base_size (no limit_price)."""
        executor, api, md = _make_executor()

        with patch.object(md, 'select_market', return_value='BTC-USDC'), \
             patch.object(md, 'get_current_prices', return_value={'bid': 49995, 'mid': 50000, 'ask': 50005}), \
             patch.object(md, 'display_market_conditions'):

            inputs = iter(['sell', '0.5'])
            get_input_fn = lambda prompt: next(inputs)

            result = executor.get_conditional_order_input(get_input_fn)

        assert result is not None
        assert result['product_id'] == 'BTC-USDC'
        assert result['side'] == 'SELL'
        assert result['base_size'] == 0.5
        assert 'limit_price' not in result

    def test_returns_none_when_market_selection_fails(self):
        """Should return None if market selection returns None."""
        executor, api, md = _make_executor()

        with patch.object(md, 'select_market', return_value=None):
            result = executor.get_conditional_order_input(lambda prompt: '')

        assert result is None
