"""
Unit tests for TWAPExecutor.execute_strategy() (twap_executor.py).

Tests cover:
- Strategy-based execution via execute_strategy()
- Participation rate cap uses candle data to skip slices
- Backward compatibility of execute_twap()

To run:
    pytest tests/test_twap_executor_enhanced.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from queue import Queue

from twap_executor import TWAPExecutor
from twap_strategy import TWAPStrategy
from order_executor import OrderExecutor
from market_data import MarketDataService
from config_manager import AppConfig
from storage import InMemoryTWAPStorage
from twap_tracker import TWAPOrder
from order_strategy import StrategyStatus
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


def _make_strategy(api_client=None, config=None, **kwargs):
    """Create a TWAPStrategy with test defaults."""
    cfg = config or AppConfig.for_testing()
    return TWAPStrategy(
        product_id=kwargs.get('product_id', 'BTC-USDC'),
        side=kwargs.get('side', 'BUY'),
        total_size=kwargs.get('total_size', 0.03),
        limit_price=kwargs.get('limit_price', 55000.0),
        num_slices=kwargs.get('num_slices', 3),
        duration_minutes=kwargs.get('duration_minutes', 1),
        price_type=kwargs.get('price_type', 'limit'),
        config=cfg,
        api_client=api_client,
        seed=kwargs.get('seed', 42),
    )


# =============================================================================
# Strategy-Based Execution
# =============================================================================

@pytest.mark.unit
class TestExecuteStrategy:
    """Tests for execute_strategy() method."""

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_all_slices_placed_via_strategy(self, mock_strategy_time, mock_exec_time):
        """All slices should be placed when using execute_strategy with favorable prices."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        strategy = _make_strategy(
            api_client=api,
            limit_price=55000.0,
            price_type='limit',
        )

        result = twap_exec.execute_strategy(strategy)

        assert result is not None
        assert result.num_filled == 3
        assert result.num_failed == 0

        # Verify TWAPOrder persisted
        twap_order = storage.get_twap_order(strategy.strategy_id)
        assert twap_order is not None
        assert twap_order.status == 'completed'
        assert len(twap_order.orders) == 3

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_strategy_sell_all_placed(self, mock_strategy_time, mock_exec_time):
        """SELL slices should all be placed with favorable prices."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('BTC', 10.0)

        strategy = _make_strategy(
            api_client=api,
            side='SELL',
            limit_price=40000.0,
            price_type='limit',
        )

        result = twap_exec.execute_strategy(strategy)

        assert result is not None
        assert result.num_filled == 3

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_strategy_unfavorable_price_skips(self, mock_strategy_time, mock_exec_time):
        """Slices with unfavorable prices should be skipped."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        # BUY with limit below market ask (~50005) -> unfavorable
        strategy = _make_strategy(
            api_client=api,
            limit_price=10000.0,  # Way below market
            price_type='ask',
        )

        result = twap_exec.execute_strategy(strategy)

        assert result is not None
        twap_order = storage.get_twap_order(strategy.strategy_id)
        assert len(twap_order.orders) == 0
        assert len(twap_order.failed_slices) == 3

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_strategy_orders_queued(self, mock_strategy_time, mock_exec_time):
        """Placed order IDs should be put on the order queue."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        strategy = _make_strategy(api_client=api)
        twap_exec.execute_strategy(strategy)

        queued_ids = []
        while not order_queue.empty():
            queued_ids.append(order_queue.get_nowait())
        assert len(queued_ids) == 3

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_strategy_result_has_correct_metadata(self, mock_strategy_time, mock_exec_time):
        """Strategy result should contain correct metadata."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        strategy = _make_strategy(api_client=api, price_type='limit')
        result = twap_exec.execute_strategy(strategy)

        assert result.metadata['product_id'] == 'BTC-USDC'
        assert result.metadata['side'] == 'BUY'
        assert result.metadata['price_type'] == 'limit'


# =============================================================================
# Participation Rate Cap with Candle Data
# =============================================================================

@pytest.mark.unit
class TestParticipationRateCapExecution:
    """Tests for participation rate cap during strategy execution."""

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_slices_skipped_when_over_participation_cap(self, mock_strategy_time, mock_exec_time):
        """Slices should be skipped when participation rate exceeds cap."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        api = MockCoinbaseAPI()
        api.set_account_balance('USDC', 1000000.0)

        # Set very low volume candles so participation rate is high
        api.set_candles('BTC-USDC', [
            {'start': '999700', 'open': '50000', 'high': '50100',
             'low': '49900', 'close': '50050', 'volume': '0.001'},
        ])

        config = AppConfig.for_testing()
        config.twap.participation_rate_cap = 0.01  # 1% cap

        twap_exec, _, storage, order_queue = _make_twap_executor(
            api_client=api, config=config
        )

        # total_size=0.03, num_slices=3 -> slice_size=0.01
        # volume=0.001 -> participation=0.01/0.001=10.0 >> 0.01 -> skip
        strategy = _make_strategy(
            api_client=api,
            config=config,
            total_size=0.03,
            num_slices=3,
        )

        result = twap_exec.execute_strategy(strategy)

        assert result is not None
        twap_order = storage.get_twap_order(strategy.strategy_id)
        # All slices should be skipped due to participation cap
        assert len(twap_order.orders) == 0
        assert len(twap_order.failed_slices) == 3

    @patch('twap_executor.time')
    @patch('twap_strategy.time')
    def test_slices_placed_when_under_participation_cap(self, mock_strategy_time, mock_exec_time):
        """Slices should be placed when participation rate is under cap."""
        mock_exec_time.time.return_value = 1000000.0
        mock_exec_time.sleep = Mock()
        mock_strategy_time.time.return_value = 1000000.0

        api = MockCoinbaseAPI()
        api.set_account_balance('USDC', 1000000.0)

        # Set high volume candles so participation rate is low
        api.set_candles('BTC-USDC', [
            {'start': '999700', 'open': '50000', 'high': '50100',
             'low': '49900', 'close': '50050', 'volume': '10000.0'},
        ])

        config = AppConfig.for_testing()
        config.twap.participation_rate_cap = 0.05  # 5% cap

        twap_exec, _, storage, order_queue = _make_twap_executor(
            api_client=api, config=config
        )

        # total_size=0.03, num_slices=3 -> slice_size=0.01
        # volume=10000 -> participation=0.01/10000 = 0.000001 < 0.05 -> allow
        strategy = _make_strategy(
            api_client=api,
            config=config,
            total_size=0.03,
            num_slices=3,
        )

        result = twap_exec.execute_strategy(strategy)

        assert result is not None
        twap_order = storage.get_twap_order(strategy.strategy_id)
        assert len(twap_order.orders) == 3
        assert len(twap_order.failed_slices) == 0


# =============================================================================
# Backward Compatibility of execute_twap()
# =============================================================================

@pytest.mark.unit
class TestBackwardCompatibility:
    """Tests that execute_twap() still works as before."""

    @patch('twap_executor.time')
    def test_execute_twap_still_works(self, mock_time):
        """execute_twap should still complete successfully."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('USDC', 1000000.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'BUY',
            'base_size': 0.03,
            'limit_price': 55000.0,
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1',
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert twap_order.status == 'completed'
        assert len(twap_order.orders) == 3

    @patch('twap_executor.time')
    def test_execute_twap_sell_still_works(self, mock_time):
        """execute_twap with SELL should still work."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        twap_exec, api, storage, order_queue = _make_twap_executor()
        api.set_account_balance('BTC', 10.0)

        order_input = {
            'product_id': 'BTC-USDC',
            'side': 'SELL',
            'base_size': 0.03,
            'limit_price': 40000.0,
        }

        twap_id = twap_exec.execute_twap(
            order_input=order_input,
            duration=1,
            num_slices=3,
            price_type='1',
        )

        assert twap_id is not None
        twap_order = storage.get_twap_order(twap_id)
        assert len(twap_order.orders) == 3

    @patch('twap_executor.time')
    def test_execute_twap_price_types_unchanged(self, mock_time):
        """execute_twap price type codes ('1'-'4') should still work."""
        mock_time.time.return_value = 1000000.0
        mock_time.sleep = Mock()

        for price_type in ['1', '2', '3', '4']:
            twap_exec, api, storage, order_queue = _make_twap_executor()
            api.set_account_balance('USDC', 1000000.0)

            order_input = {
                'product_id': 'BTC-USDC',
                'side': 'BUY',
                'base_size': 0.03,
                'limit_price': 55000.0,
            }

            twap_id = twap_exec.execute_twap(
                order_input=order_input,
                duration=1,
                num_slices=2,
                price_type=price_type,
            )

            assert twap_id is not None, f"Failed for price_type={price_type}"
