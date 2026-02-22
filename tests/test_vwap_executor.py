"""
Unit tests for VWAPExecutor.
"""

import pytest
from unittest.mock import Mock, patch
from queue import Queue

from vwap_executor import VWAPExecutor
from vwap_strategy import VWAPStrategy
from order_strategy import StrategyResult, StrategyStatus
from config_manager import AppConfig


@pytest.mark.unit
class TestVWAPExecutor:
    """Tests for VWAPExecutor."""

    @pytest.fixture
    def mock_twap_executor(self):
        executor = Mock()
        result = StrategyResult(
            strategy_id='test-id',
            status=StrategyStatus.COMPLETED,
            total_size=1.0,
            total_filled=1.0,
            total_value=50000.0,
            num_slices=5,
            num_filled=5,
        )
        executor.execute_strategy.return_value = result
        return executor

    @pytest.fixture
    def mock_market_data(self):
        md = Mock()
        md.select_market.return_value = 'BTC-USDC'
        md.get_current_prices.return_value = {'bid': 49995, 'ask': 50005, 'mid': 50000}
        md.display_market_conditions.return_value = None
        md.round_size.side_effect = lambda s, pid: round(s, 8)
        md.round_price.side_effect = lambda p, pid: round(p, 2)
        return md

    @pytest.fixture
    def mock_api_client(self):
        api = Mock()
        api.get_candles.return_value = []
        return api

    @pytest.fixture
    def executor(self, mock_twap_executor, mock_market_data, mock_api_client):
        config = AppConfig.for_testing()
        return VWAPExecutor(
            twap_executor=mock_twap_executor,
            market_data=mock_market_data,
            api_client=mock_api_client,
            config=config
        )

    def test_place_vwap_order_success(self, executor, mock_twap_executor):
        """Successful VWAP order should call execute_strategy."""
        # Inputs: side, limit_price, size, duration, slices, price_type, lookback, confirm
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)

        assert result is not None
        assert mock_twap_executor.execute_strategy.call_count == 1

    def test_place_vwap_order_cancelled(self, executor, mock_twap_executor):
        """User declining should cancel."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'no'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)

        assert result is None
        assert mock_twap_executor.execute_strategy.call_count == 0

    def test_candle_api_called_with_correct_product(self, executor, mock_api_client):
        """Candle API should be called with the selected product."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        executor.place_vwap_order(get_input)

        # get_candles should have been called (by VWAPStrategy)
        assert mock_api_client.get_candles.called
        call_args = mock_api_client.get_candles.call_args
        assert call_args[1].get('product_id', call_args[0][0] if call_args[0] else None) == 'BTC-USDC' or \
               'BTC-USDC' in str(call_args)

    def test_execute_strategy_receives_vwap_strategy(self, executor, mock_twap_executor):
        """execute_strategy should receive a VWAPStrategy instance."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        executor.place_vwap_order(get_input)

        call_args = mock_twap_executor.execute_strategy.call_args
        strategy = call_args[0][0] if call_args[0] else call_args[1].get('strategy')
        assert isinstance(strategy, VWAPStrategy)

    def test_display_vwap_summary_not_found(self, executor):
        """Displaying non-existent strategy should warn."""
        # Should not raise
        executor.display_vwap_summary('nonexistent')

    def test_strategy_stored_after_execution(self, executor):
        """Strategy should be stored for later display."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)

        assert result is not None
        assert result in executor._strategies

    def test_display_vwap_summary_with_strategy(self, executor, mock_twap_executor):
        """Display summary with a stored strategy."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)
        assert result is not None

        # Should not raise
        executor.display_vwap_summary(result)

    def test_display_vwap_summary_by_strategy_instance(self, executor, mock_twap_executor):
        """Display summary when passing strategy object directly."""
        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)
        assert result is not None

        strategy = executor._strategies[result]
        executor.display_vwap_summary(strategy)  # Should not raise

    def test_market_selection_returns_none(self, executor, mock_market_data):
        """Should return None if market selection fails."""
        mock_market_data.select_market.return_value = None
        get_input = Mock(side_effect=['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])

        result = executor.place_vwap_order(get_input)
        assert result is None

    def test_execution_failure_returns_none(self, executor, mock_twap_executor):
        """Should return None on execution failure."""
        mock_twap_executor.execute_strategy.return_value = None

        inputs = iter(['BUY', '50000', '1.0', '60', '5', '3', '24', 'yes'])
        get_input = Mock(side_effect=inputs)

        result = executor.place_vwap_order(get_input)
        assert result is None
