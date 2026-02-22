"""
Scaled/Ladder order strategy implementing OrderStrategy.

Calculates price levels and size distribution for placing multiple
limit orders across a price range.
"""

import logging
import time
from typing import List, Optional, Dict, Any

from order_strategy import OrderStrategy, SliceSpec, StrategyResult, StrategyStatus
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType


class ScaledStrategy(OrderStrategy):
    """
    Strategy for placing multiple limit orders across a price range.

    All orders are placed at time=0 (immediately), with prices spread
    across the specified range and sizes determined by the distribution type.
    """

    def __init__(
        self,
        product_id: str,
        side: str,
        total_size: float,
        price_low: float,
        price_high: float,
        num_orders: int,
        distribution: DistributionType = DistributionType.LINEAR,
    ):
        self.product_id = product_id
        self.side = side
        self.total_size = total_size
        self.price_low = price_low
        self.price_high = price_high
        self.num_orders = num_orders
        self.distribution = distribution

        self._slices: List[SliceSpec] = []
        self._completed_slices: Dict[int, Dict[str, Any]] = {}
        self._status = StrategyStatus.PENDING
        self._strategy_id = ""

    def calculate_slices(self) -> List[SliceSpec]:
        """Calculate all order levels with prices and sizes."""
        prices = self._calculate_price_levels()
        sizes = self._calculate_size_distribution()

        now = time.time()
        self._slices = []

        for i in range(self.num_orders):
            self._slices.append(SliceSpec(
                slice_number=i + 1,
                size=sizes[i],
                price=prices[i],
                scheduled_time=now,  # All placed immediately
                price_type="limit"
            ))

        self._status = StrategyStatus.ACTIVE
        return self._slices

    def _calculate_price_levels(self) -> List[float]:
        """Calculate evenly spaced prices from low to high."""
        if self.num_orders == 1:
            # Single order at midpoint
            return [(self.price_low + self.price_high) / 2]

        prices = []
        step = (self.price_high - self.price_low) / (self.num_orders - 1)
        for i in range(self.num_orders):
            prices.append(self.price_low + i * step)

        return prices

    def _calculate_size_distribution(self) -> List[float]:
        """Calculate sizes based on distribution type."""
        if self.distribution == DistributionType.LINEAR:
            return self._linear_distribution()
        elif self.distribution == DistributionType.GEOMETRIC:
            return self._geometric_distribution()
        elif self.distribution == DistributionType.FRONT_WEIGHTED:
            return self._front_weighted_distribution()
        else:
            return self._linear_distribution()

    def _linear_distribution(self) -> List[float]:
        """Equal size at each level."""
        size_per_order = self.total_size / self.num_orders
        return [size_per_order] * self.num_orders

    def _geometric_distribution(self) -> List[float]:
        """
        Exponentially increasing sizes toward favorable price end.

        For BUY: more size at lower prices (favorable).
        For SELL: more size at higher prices (favorable).

        Uses ratio=2 so each level gets ~2x the weight of the previous.
        """
        if self.num_orders == 1:
            return [self.total_size]

        ratio = 2.0
        # Generate raw weights: 1, ratio, ratio^2, ...
        weights = [ratio ** i for i in range(self.num_orders)]

        # For BUY orders, favorable = low price = beginning of list
        # For SELL orders, favorable = high price = end of list
        # Since prices go low->high, BUY wants more weight at start,
        # SELL wants more weight at end (which is already the default since weights increase)
        if self.side == 'BUY':
            weights = list(reversed(weights))
        # For SELL, weights already increase with price (favorable)

        total_weight = sum(weights)
        return [w / total_weight * self.total_size for w in weights]

    def _front_weighted_distribution(self) -> List[float]:
        """
        More size near current market price (first levels).

        For BUY: prices go low->high, market price is near high end, so weight toward end.
        For SELL: prices go low->high, market price is near low end, so weight toward start.

        Uses linear decreasing weights from market-proximal levels.
        """
        if self.num_orders == 1:
            return [self.total_size]

        # Weights decrease linearly: n, n-1, ..., 1
        weights = list(range(self.num_orders, 0, -1))

        # For BUY: market is near high prices, so reverse to put more weight at high end
        if self.side == 'BUY':
            weights = list(reversed(weights))
        # For SELL: market is near low prices, keep more weight at low end (start)

        total_weight = sum(weights)
        return [w / total_weight * self.total_size for w in weights]

    def on_slice_complete(
        self,
        slice_number: int,
        order_id: Optional[str],
        fill_info: Optional[Dict[str, Any]]
    ) -> None:
        """Record completion of a slice."""
        self._completed_slices[slice_number] = {
            'order_id': order_id,
            'fill_info': fill_info
        }

        # Check if all slices are done
        if len(self._completed_slices) >= self.num_orders:
            self._status = StrategyStatus.COMPLETED

    def should_skip_slice(
        self,
        slice_number: int,
        market_data: Dict[str, Any]
    ) -> bool:
        """Scaled orders never skip -- all levels are placed."""
        return False

    def get_execution_price(
        self,
        slice_spec: SliceSpec,
        market_data: Dict[str, Any]
    ) -> float:
        """Return the pre-calculated price for this level."""
        return slice_spec.price

    def get_result(self) -> StrategyResult:
        """Get current strategy execution result."""
        total_filled = 0.0
        total_value = 0.0
        total_fees = 0.0
        num_filled = 0
        num_failed = 0

        for slice_num, data in self._completed_slices.items():
            fill = data.get('fill_info') or {}
            if data.get('order_id'):
                if fill.get('filled_size', 0) > 0:
                    total_filled += fill['filled_size']
                    total_value += fill.get('filled_value', 0)
                    total_fees += fill.get('fees', 0)
                    num_filled += 1
            else:
                num_failed += 1

        avg_price = total_value / total_filled if total_filled > 0 else 0.0

        return StrategyResult(
            strategy_id=self._strategy_id,
            status=self._status,
            total_size=self.total_size,
            total_filled=total_filled,
            total_value=total_value,
            total_fees=total_fees,
            average_price=avg_price,
            vwap=avg_price,
            num_slices=self.num_orders,
            num_filled=num_filled,
            num_failed=num_failed
        )
