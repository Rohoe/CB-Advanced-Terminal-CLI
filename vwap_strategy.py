"""
VWAP (Volume-Weighted Average Price) order strategy.

Uses historical volume profiles from candle data to distribute order sizes
proportionally to expected trading volume at each time period.
"""

import logging
import time
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from order_strategy import OrderStrategy, SliceSpec, StrategyResult, StrategyStatus


@dataclass
class VWAPStrategyConfig:
    """Configuration for VWAP strategy."""
    duration_minutes: int = 60
    num_slices: int = 10
    price_type: str = "mid"
    volume_lookback_hours: int = 24
    granularity: str = "ONE_HOUR"
    benchmark_enabled: bool = True


class VWAPStrategy(OrderStrategy):
    """
    Strategy that distributes order sizes proportionally to historical
    trading volume at each time period.

    Key insight: With a flat volume profile, VWAP degenerates to TWAP
    (equal sizes at each interval).
    """

    def __init__(
        self,
        product_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        num_slices: int,
        duration_minutes: int,
        api_client,
        config: Optional[VWAPStrategyConfig] = None,
    ):
        self.product_id = product_id
        self.side = side
        self.total_size = total_size
        self.limit_price = limit_price
        self.num_slices = num_slices
        self.duration_minutes = duration_minutes
        self.api_client = api_client
        self.vwap_config = config or VWAPStrategyConfig(
            duration_minutes=duration_minutes,
            num_slices=num_slices,
        )

        self.strategy_id = str(uuid.uuid4())
        self._slices: List[SliceSpec] = []
        self._completed_slices: Dict[int, Dict[str, Any]] = {}
        self._status = StrategyStatus.PENDING
        self._volume_profile: List[float] = []
        self._benchmark_vwap: float = 0.0

    def _fetch_volume_profile(self) -> List[float]:
        """
        Fetch historical candle data and build normalized volume profile by hour-of-day.

        Returns:
            List of normalized volume weights (sum to 1.0), one per slice.
        """
        try:
            lookback_hours = self.vwap_config.volume_lookback_hours
            granularity = self.vwap_config.granularity

            end = int(time.time())
            start = end - (lookback_hours * 3600)

            candles = self.api_client.get_candles(
                product_id=self.product_id,
                start=str(start),
                end=str(end),
                granularity=granularity
            )

            if not candles:
                logging.warning("No candle data available, falling back to flat profile")
                return self._flat_profile()

            # Extract volumes, handling both dict and object access
            volumes_by_hour = {}
            for candle in candles:
                if isinstance(candle, dict):
                    hour = int(candle.get('start', 0)) % 86400 // 3600
                    volume = float(candle.get('volume', 0))
                else:
                    hour = int(getattr(candle, 'start', 0)) % 86400 // 3600
                    volume = float(getattr(candle, 'volume', 0))

                if hour not in volumes_by_hour:
                    volumes_by_hour[hour] = []
                volumes_by_hour[hour].append(volume)

            # Average volume per hour-of-day
            avg_volumes = {}
            for hour, vols in volumes_by_hour.items():
                avg_volumes[hour] = sum(vols) / len(vols) if vols else 0

            if not avg_volumes or sum(avg_volumes.values()) == 0:
                return self._flat_profile()

            # Map slices to hours and get their volume weights
            now = datetime.now()
            duration_seconds = self.duration_minutes * 60
            slice_interval = duration_seconds / self.num_slices

            weights = []
            for i in range(self.num_slices):
                slice_time = now + timedelta(seconds=i * slice_interval)
                hour = slice_time.hour
                weight = avg_volumes.get(hour, 0)
                if weight == 0:
                    # Use average of all hours as fallback
                    weight = sum(avg_volumes.values()) / len(avg_volumes)
                weights.append(weight)

            # Normalize to sum to 1.0
            total_weight = sum(weights)
            if total_weight > 0:
                weights = [w / total_weight for w in weights]
            else:
                weights = self._flat_profile()

            self._volume_profile = weights
            return weights

        except Exception as e:
            logging.error(f"Error fetching volume profile: {str(e)}")
            return self._flat_profile()

    def _flat_profile(self) -> List[float]:
        """Return a flat (uniform) volume profile — equivalent to TWAP."""
        return [1.0 / self.num_slices] * self.num_slices

    def calculate_slices(self) -> List[SliceSpec]:
        """Calculate slices with sizes proportional to volume profile."""
        weights = self._fetch_volume_profile()

        now = time.time()
        duration_seconds = self.duration_minutes * 60
        slice_interval = duration_seconds / self.num_slices

        self._slices = []
        for i in range(self.num_slices):
            size = self.total_size * weights[i]
            self._slices.append(SliceSpec(
                slice_number=i + 1,
                size=size,
                price=self.limit_price,
                scheduled_time=now + i * slice_interval,
                price_type=self.vwap_config.price_type
            ))

        # Calculate benchmark VWAP if enabled
        if self.vwap_config.benchmark_enabled:
            self._benchmark_vwap = self._calculate_benchmark_vwap()

        self._status = StrategyStatus.ACTIVE
        return self._slices

    def _calculate_benchmark_vwap(self) -> float:
        """
        Calculate benchmark VWAP from candle data: sum(price * volume) / sum(volume).

        Uses the typical price (high + low + close) / 3 for each candle.
        """
        try:
            lookback_hours = self.vwap_config.volume_lookback_hours
            granularity = self.vwap_config.granularity

            end = int(time.time())
            start = end - (lookback_hours * 3600)

            candles = self.api_client.get_candles(
                product_id=self.product_id,
                start=str(start),
                end=str(end),
                granularity=granularity
            )

            if not candles:
                return 0.0

            sum_pv = 0.0
            sum_v = 0.0

            for candle in candles:
                if isinstance(candle, dict):
                    high = float(candle.get('high', 0))
                    low = float(candle.get('low', 0))
                    close = float(candle.get('close', 0))
                    volume = float(candle.get('volume', 0))
                else:
                    high = float(getattr(candle, 'high', 0))
                    low = float(getattr(candle, 'low', 0))
                    close = float(getattr(candle, 'close', 0))
                    volume = float(getattr(candle, 'volume', 0))

                typical_price = (high + low + close) / 3
                sum_pv += typical_price * volume
                sum_v += volume

            return sum_pv / sum_v if sum_v > 0 else 0.0

        except Exception as e:
            logging.error(f"Error calculating benchmark VWAP: {str(e)}")
            return 0.0

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

        if len(self._completed_slices) >= self.num_slices:
            self._status = StrategyStatus.COMPLETED

    def should_skip_slice(
        self,
        slice_number: int,
        market_data: Dict[str, Any]
    ) -> bool:
        """VWAP orders don't skip slices based on market conditions."""
        return False

    def get_execution_price(
        self,
        slice_spec: SliceSpec,
        market_data: Dict[str, Any]
    ) -> float:
        """Get execution price based on configured price type."""
        price_type = slice_spec.price_type

        if price_type == 'bid':
            return market_data.get('bid', self.limit_price)
        elif price_type == 'ask':
            return market_data.get('ask', self.limit_price)
        elif price_type == 'mid':
            return market_data.get('mid', self.limit_price)
        else:  # 'limit' or default
            return self.limit_price

    def get_execution_vwap(self) -> float:
        """Calculate the execution VWAP from actual fills."""
        total_value = 0.0
        total_size = 0.0

        for data in self._completed_slices.values():
            fill = data.get('fill_info') or {}
            size = fill.get('filled_size', 0)
            price = fill.get('price', 0)
            if size > 0 and price > 0:
                total_value += size * price
                total_size += size

        return total_value / total_size if total_size > 0 else 0.0

    def get_performance_vs_benchmark(self) -> Dict[str, float]:
        """
        Compare execution VWAP vs market benchmark VWAP.

        Returns:
            Dict with execution_vwap, benchmark_vwap, slippage_bps.
            Positive slippage = unfavorable for the side (paid more for BUY, got less for SELL).
            Negative slippage = favorable.
        """
        exec_vwap = self.get_execution_vwap()
        benchmark = self._benchmark_vwap

        if benchmark == 0 or exec_vwap == 0:
            return {
                'execution_vwap': exec_vwap,
                'benchmark_vwap': benchmark,
                'slippage_bps': 0.0
            }

        # Slippage in basis points
        if self.side == 'BUY':
            # For BUY: positive slippage means we paid more than benchmark
            slippage_bps = (exec_vwap - benchmark) / benchmark * 10000
        else:
            # For SELL: positive slippage means we got less than benchmark
            slippage_bps = (benchmark - exec_vwap) / benchmark * 10000

        return {
            'execution_vwap': exec_vwap,
            'benchmark_vwap': benchmark,
            'slippage_bps': slippage_bps
        }

    @property
    def volume_profile(self) -> List[float]:
        """Get the volume profile weights."""
        return self._volume_profile

    @property
    def benchmark_vwap(self) -> float:
        """Get the benchmark VWAP."""
        return self._benchmark_vwap

    def get_result(self) -> StrategyResult:
        """Get current strategy execution result with VWAP metadata."""
        total_filled = 0.0
        total_value = 0.0
        total_fees = 0.0
        num_filled = 0
        num_failed = 0

        for data in self._completed_slices.values():
            fill = data.get('fill_info') or {}
            if data.get('order_id'):
                filled_size = fill.get('filled_size', 0)
                if filled_size > 0:
                    total_filled += filled_size
                    total_value += fill.get('filled_value', filled_size * fill.get('price', 0))
                    total_fees += fill.get('fees', 0)
                    num_filled += 1
            else:
                num_failed += 1

        avg_price = total_value / total_filled if total_filled > 0 else 0.0
        exec_vwap = self.get_execution_vwap()
        perf = self.get_performance_vs_benchmark()

        return StrategyResult(
            strategy_id=self.strategy_id,
            status=self._status,
            total_size=self.total_size,
            total_filled=total_filled,
            total_value=total_value,
            total_fees=total_fees,
            average_price=avg_price,
            vwap=exec_vwap,
            num_slices=self.num_slices,
            num_filled=num_filled,
            num_failed=num_failed,
            metadata={
                'benchmark_vwap': self._benchmark_vwap,
                'slippage_bps': perf.get('slippage_bps', 0.0),
                'volume_profile': self._volume_profile,
            }
        )
