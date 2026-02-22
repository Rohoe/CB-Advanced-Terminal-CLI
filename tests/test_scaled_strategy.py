"""
Unit tests for ScaledStrategy.
"""

import pytest
from scaled_strategy import ScaledStrategy
from scaled_orders import DistributionType
from order_strategy import StrategyStatus


@pytest.mark.unit
class TestScaledStrategyLinear:
    """Tests for linear distribution."""

    def test_linear_all_sizes_equal(self):
        """Linear distribution should give equal sizes."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]
        assert all(abs(s - 0.2) < 1e-10 for s in sizes)

    def test_linear_sizes_sum_to_total(self):
        """All sizes should sum to total_size."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=10,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        total = sum(s.size for s in slices)
        assert abs(total - 1.0) < 1e-10

    def test_linear_correct_number_of_slices(self):
        """Should return exact number of slices requested."""
        for n in [1, 2, 5, 10, 20]:
            strategy = ScaledStrategy(
                product_id='BTC-USDC', side='BUY', total_size=1.0,
                price_low=49000, price_high=51000, num_orders=n,
                distribution=DistributionType.LINEAR
            )
            slices = strategy.calculate_slices()
            assert len(slices) == n


@pytest.mark.unit
class TestScaledStrategyGeometric:
    """Tests for geometric distribution."""

    def test_geometric_sizes_sum_to_total(self):
        """Geometric sizes should sum to total."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.GEOMETRIC
        )
        slices = strategy.calculate_slices()
        total = sum(s.size for s in slices)
        assert abs(total - 1.0) < 1e-10

    def test_geometric_buy_more_at_low_prices(self):
        """BUY geometric should have more size at lower prices (favorable)."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.GEOMETRIC
        )
        slices = strategy.calculate_slices()
        # First slice (low price) should have more than last slice (high price)
        assert slices[0].size > slices[-1].size

    def test_geometric_sell_more_at_high_prices(self):
        """SELL geometric should have more size at higher prices (favorable)."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='SELL', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.GEOMETRIC
        )
        slices = strategy.calculate_slices()
        # Last slice (high price) should have more than first slice (low price)
        assert slices[-1].size > slices[0].size

    def test_geometric_each_weight_increases(self):
        """For SELL, each successive size should be larger (geometric progression)."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='SELL', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.GEOMETRIC
        )
        slices = strategy.calculate_slices()
        sizes = [s.size for s in slices]
        for i in range(1, len(sizes)):
            assert sizes[i] > sizes[i - 1]

    def test_geometric_single_order(self):
        """Single order geometric should return total size."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=1,
            distribution=DistributionType.GEOMETRIC
        )
        slices = strategy.calculate_slices()
        assert len(slices) == 1
        assert abs(slices[0].size - 1.0) < 1e-10


@pytest.mark.unit
class TestScaledStrategyFrontWeighted:
    """Tests for front-weighted distribution."""

    def test_front_weighted_sizes_sum_to_total(self):
        """Front-weighted sizes should sum to total."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.FRONT_WEIGHTED
        )
        slices = strategy.calculate_slices()
        total = sum(s.size for s in slices)
        assert abs(total - 1.0) < 1e-10

    def test_front_weighted_buy_more_near_market(self):
        """BUY front-weighted: more at high prices (near market)."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.FRONT_WEIGHTED
        )
        slices = strategy.calculate_slices()
        # For BUY, market is near high end, so last orders should be larger
        assert slices[-1].size > slices[0].size

    def test_front_weighted_sell_more_near_market(self):
        """SELL front-weighted: more at low prices (near market)."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='SELL', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.FRONT_WEIGHTED
        )
        slices = strategy.calculate_slices()
        # For SELL, market is near low end, so first orders should be larger
        assert slices[0].size > slices[-1].size


@pytest.mark.unit
class TestScaledStrategyPriceLevels:
    """Tests for price level calculation."""

    def test_prices_evenly_spaced(self):
        """Prices should be evenly spaced from low to high."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        prices = [s.price for s in slices]

        assert prices[0] == pytest.approx(49000, rel=1e-6)
        assert prices[-1] == pytest.approx(51000, rel=1e-6)

        # Check even spacing
        step = (51000 - 49000) / 4
        for i in range(len(prices)):
            assert prices[i] == pytest.approx(49000 + i * step, rel=1e-6)

    def test_single_order_at_midpoint(self):
        """Single order should be at midpoint of range."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=1,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        assert slices[0].price == pytest.approx(50000, rel=1e-6)

    def test_two_orders_at_extremes(self):
        """Two orders should be at low and high prices."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=2,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        assert slices[0].price == pytest.approx(49000, rel=1e-6)
        assert slices[1].price == pytest.approx(51000, rel=1e-6)

    def test_all_slices_have_limit_price_type(self):
        """All slices should use limit price type."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        for s in slices:
            assert s.price_type == "limit"


@pytest.mark.unit
class TestScaledStrategyBehavior:
    """Tests for strategy behavior methods."""

    def test_should_skip_always_false(self):
        """Scaled orders never skip slices."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.LINEAR
        )
        assert strategy.should_skip_slice(1, {}) is False
        assert strategy.should_skip_slice(5, {'bid': 49000}) is False

    def test_get_execution_price_returns_slice_price(self):
        """Execution price should be the pre-calculated slice price."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=5,
            distribution=DistributionType.LINEAR
        )
        slices = strategy.calculate_slices()
        for s in slices:
            assert strategy.get_execution_price(s, {}) == s.price

    def test_status_transitions(self):
        """Status should progress from PENDING to ACTIVE to COMPLETED."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=3,
            distribution=DistributionType.LINEAR
        )

        assert strategy._status == StrategyStatus.PENDING

        slices = strategy.calculate_slices()
        assert strategy._status == StrategyStatus.ACTIVE

        # Complete all slices
        for i in range(3):
            strategy.on_slice_complete(i + 1, f'order-{i}', {'filled_size': 0.1})
        assert strategy._status == StrategyStatus.COMPLETED

    def test_get_result_after_completion(self):
        """get_result should reflect completed state."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=0.3,
            price_low=49000, price_high=51000, num_orders=3,
            distribution=DistributionType.LINEAR
        )
        strategy.calculate_slices()

        strategy.on_slice_complete(1, 'order-1', {
            'filled_size': 0.1, 'filled_value': 4900.0, 'fees': 1.0
        })
        strategy.on_slice_complete(2, 'order-2', {
            'filled_size': 0.1, 'filled_value': 5000.0, 'fees': 1.0
        })
        strategy.on_slice_complete(3, None, None)  # Failed

        result = strategy.get_result()
        assert result.total_filled == pytest.approx(0.2)
        assert result.total_value == pytest.approx(9900.0)
        assert result.total_fees == pytest.approx(2.0)
        assert result.num_filled == 2
        assert result.num_failed == 1
        assert result.num_slices == 3

    def test_get_result_no_fills(self):
        """get_result with no fills should have zero totals."""
        strategy = ScaledStrategy(
            product_id='BTC-USDC', side='BUY', total_size=1.0,
            price_low=49000, price_high=51000, num_orders=3,
            distribution=DistributionType.LINEAR
        )
        result = strategy.get_result()
        assert result.total_filled == 0.0
        assert result.average_price == 0.0
