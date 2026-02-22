"""
TWAP strategy implementation.

This module implements the OrderStrategy interface for Time-Weighted Average Price
execution. It provides uniform slice timing with optional jitter, participation
rate cap checking via candle volume data, and all four price type modes.

Usage:
    from twap_strategy import TWAPStrategy

    strategy = TWAPStrategy(
        product_id='BTC-USD',
        side='BUY',
        total_size=1.0,
        limit_price=50000.0,
        num_slices=10,
        duration_minutes=60,
        price_type='mid',
        config=app_config,
        api_client=client,
    )

    slices = strategy.calculate_slices()
    for s in slices:
        if not strategy.should_skip_slice(s.slice_number, market_data):
            price = strategy.get_execution_price(s, market_data)
            ...
"""

import logging
import random
import time
import uuid
from typing import Dict, Any, List, Optional

from order_strategy import OrderStrategy, SliceSpec, StrategyResult, StrategyStatus
from config_manager import AppConfig


class TWAPStrategy(OrderStrategy):
    """
    Time-Weighted Average Price strategy.

    Splits a large order into uniform slices executed at regular intervals.
    Supports optional jitter on timing and participation rate cap checking.

    Attributes:
        strategy_id: Unique identifier for this strategy execution.
        product_id: Trading pair (e.g. 'BTC-USD').
        side: 'BUY' or 'SELL'.
        total_size: Total order size in base currency.
        limit_price: Limit price for favorability checks.
        num_slices: Number of slices to split into.
        duration_minutes: Total execution duration in minutes.
        price_type: One of 'limit', 'bid', 'mid', 'ask'.
        config: Application configuration.
        api_client: API client for candle data (participation rate cap).
    """

    def __init__(
        self,
        product_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        num_slices: int,
        duration_minutes: float,
        price_type: str = 'limit',
        config: Optional[AppConfig] = None,
        api_client=None,
        seed: Optional[int] = None,
    ):
        """
        Initialize TWAP strategy.

        Args:
            product_id: Trading pair.
            side: 'BUY' or 'SELL'.
            total_size: Total order size.
            limit_price: Limit price.
            num_slices: Number of slices.
            duration_minutes: Duration in minutes.
            price_type: Price determination mode ('limit', 'bid', 'mid', 'ask').
            config: AppConfig instance.
            api_client: API client for candle volume lookups.
            seed: Random seed for jitter reproducibility in tests.
        """
        self.strategy_id = str(uuid.uuid4())
        self.product_id = product_id
        self.side = side
        self.total_size = total_size
        self.limit_price = limit_price
        self.num_slices = num_slices
        self.duration_minutes = duration_minutes
        self.price_type = price_type
        self.config = config or AppConfig()
        self.api_client = api_client

        # Random generator (seeded for test reproducibility)
        self._rng = random.Random(seed)

        # Tracking state
        self._filled_slices: List[Dict[str, Any]] = []
        self._skipped_slices: List[int] = []
        self._failed_slices: List[int] = []
        self._total_filled: float = 0.0
        self._total_value: float = 0.0
        self._total_fees: float = 0.0
        self._start_time: Optional[str] = None
        self._end_time: Optional[str] = None

    def calculate_slices(self) -> List[SliceSpec]:
        """
        Calculate uniform slices with optional jitter on timing.

        Each slice gets an equal portion of total_size. Timing is evenly
        spaced across the duration, with optional random jitter applied
        to each interval based on config.twap.jitter_pct.

        Returns:
            List of SliceSpec with timing, size, and price type.
        """
        slice_size = self.total_size / self.num_slices
        interval_seconds = (self.duration_minutes * 60) / self.num_slices
        jitter_pct = self.config.twap.jitter_pct

        start_time = time.time()
        slices = []

        for i in range(self.num_slices):
            scheduled = start_time + (i * interval_seconds)

            # Apply jitter if configured
            if jitter_pct > 0 and i > 0:  # No jitter on the first slice
                max_jitter = interval_seconds * jitter_pct
                jitter = self._rng.uniform(-max_jitter, max_jitter)
                scheduled += jitter

            slices.append(SliceSpec(
                slice_number=i + 1,
                size=slice_size,
                price=self.limit_price,
                scheduled_time=scheduled,
                price_type=self.price_type,
            ))

        return slices

    def should_skip_slice(
        self,
        slice_number: int,
        market_data: Dict[str, Any],
    ) -> bool:
        """
        Determine whether a slice should be skipped based on participation rate cap.

        If participation_rate_cap is 0 (disabled), always returns False.
        Otherwise, fetches recent candle volume and checks whether
        slice_size / recent_volume exceeds the cap.

        Args:
            slice_number: 1-based slice index.
            market_data: Dict with at least 'recent_volume' key (float),
                         or empty if volume data is unavailable.

        Returns:
            True if the slice should be skipped.
        """
        cap = self.config.twap.participation_rate_cap
        if cap <= 0:
            return False

        recent_volume = market_data.get('recent_volume', 0.0)
        if recent_volume <= 0:
            # If we can't determine volume, skip to be safe
            logging.warning(
                f"Slice {slice_number}: no recent volume data, skipping "
                f"due to participation rate cap"
            )
            return True

        slice_size = self.total_size / self.num_slices
        participation_rate = slice_size / recent_volume

        if participation_rate > cap:
            logging.info(
                f"Slice {slice_number}: participation rate {participation_rate:.4f} "
                f"exceeds cap {cap:.4f}, skipping"
            )
            return True

        return False

    def get_execution_price(
        self,
        slice_spec: SliceSpec,
        market_data: Dict[str, Any],
    ) -> float:
        """
        Determine execution price for a slice based on price_type.

        Price types:
            'limit': Use the fixed limit_price from the strategy.
            'bid': Use current best bid.
            'mid': Use midpoint between bid and ask.
            'ask': Use current best ask.

        Args:
            slice_spec: The slice specification.
            market_data: Dict with 'bid', 'ask', 'mid' keys.

        Returns:
            The price to use for this slice.
        """
        price_type = slice_spec.price_type

        if price_type == 'limit':
            return self.limit_price
        elif price_type == 'bid':
            return float(market_data.get('bid', self.limit_price))
        elif price_type == 'mid':
            return float(market_data.get('mid', self.limit_price))
        elif price_type == 'ask':
            return float(market_data.get('ask', self.limit_price))
        else:
            logging.warning(f"Unknown price_type '{price_type}', using limit price")
            return self.limit_price

    def on_slice_complete(
        self,
        slice_number: int,
        order_id: Optional[str],
        fill_info: Optional[Dict[str, Any]],
    ) -> None:
        """
        Track slice completion.

        Args:
            slice_number: 1-based slice index.
            order_id: Order ID if placed, None if skipped/failed.
            fill_info: Dict with 'filled_size', 'price', 'fee' keys, or None.
        """
        if order_id and fill_info:
            self._filled_slices.append({
                'slice_number': slice_number,
                'order_id': order_id,
                **fill_info,
            })
            self._total_filled += fill_info.get('filled_size', 0.0)
            self._total_value += (
                fill_info.get('filled_size', 0.0) * fill_info.get('price', 0.0)
            )
            self._total_fees += fill_info.get('fee', 0.0)
        elif order_id:
            # Order placed but no fill info yet
            self._filled_slices.append({
                'slice_number': slice_number,
                'order_id': order_id,
            })
        else:
            self._failed_slices.append(slice_number)

    def get_recent_volume(self, product_id: str) -> float:
        """
        Fetch recent trading volume from candle data.

        Uses the api_client to get candles for the configured lookback
        period and sums up the volume.

        Args:
            product_id: Trading pair.

        Returns:
            Total volume over the lookback period, or 0.0 on failure.
        """
        if not self.api_client:
            return 0.0

        try:
            lookback = self.config.twap.volume_lookback_minutes
            end_ts = int(time.time())
            start_ts = end_ts - (lookback * 60)

            # Use ONE_MINUTE granularity for short lookbacks, FIVE_MINUTE for longer
            if lookback <= 5:
                granularity = 'ONE_MINUTE'
            else:
                granularity = 'FIVE_MINUTE'

            response = self.api_client.get_candles(
                product_id=product_id,
                start=str(start_ts),
                end=str(end_ts),
                granularity=granularity,
            )

            total_volume = 0.0
            if hasattr(response, 'candles'):
                for candle in response.candles:
                    vol = getattr(candle, 'volume', '0')
                    total_volume += float(vol)

            return total_volume

        except Exception as e:
            logging.error(f"Error fetching recent volume: {e}")
            return 0.0

    def get_result(self) -> StrategyResult:
        """
        Get the current strategy execution result.

        Returns:
            StrategyResult with current execution metrics.
        """
        num_filled = len(self._filled_slices)
        num_failed = len(self._failed_slices)

        if num_filled + num_failed >= self.num_slices:
            status = StrategyStatus.COMPLETED
        elif num_filled > 0 or num_failed > 0:
            status = StrategyStatus.ACTIVE
        else:
            status = StrategyStatus.PENDING

        avg_price = 0.0
        if self._total_filled > 0:
            avg_price = self._total_value / self._total_filled

        return StrategyResult(
            strategy_id=self.strategy_id,
            status=status,
            total_size=self.total_size,
            total_filled=self._total_filled,
            total_value=self._total_value,
            total_fees=self._total_fees,
            average_price=avg_price,
            vwap=avg_price,
            num_slices=self.num_slices,
            num_filled=num_filled,
            num_failed=num_failed,
            start_time=self._start_time,
            end_time=self._end_time,
            metadata={
                'product_id': self.product_id,
                'side': self.side,
                'price_type': self.price_type,
                'jitter_pct': self.config.twap.jitter_pct,
                'participation_rate_cap': self.config.twap.participation_rate_cap,
            },
        )
