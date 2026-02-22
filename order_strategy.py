"""
Order strategy abstraction layer.

This module defines the OrderStrategy interface that all algorithmic trading
strategies (TWAP, VWAP, Scaled) implement. It provides a common protocol for
slice calculation, execution control, and progress tracking.

Usage:
    from order_strategy import OrderStrategy, SliceSpec, StrategyResult

    class MyStrategy(OrderStrategy):
        def calculate_slices(self) -> List[SliceSpec]:
            ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class StrategyStatus(Enum):
    """Status of a strategy execution."""
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class SliceSpec:
    """
    Specification for a single order slice.

    Attributes:
        slice_number: 1-based slice index.
        size: Order size for this slice.
        price: Target price for this slice (may be updated at execution time).
        scheduled_time: When this slice should be executed (unix timestamp).
        price_type: How to determine execution price ('limit', 'bid', 'mid', 'ask').
    """
    slice_number: int
    size: float
    price: float
    scheduled_time: float
    price_type: str = "limit"


@dataclass
class StrategyResult:
    """
    Result of a completed strategy execution.

    Attributes:
        strategy_id: Unique identifier for this execution.
        status: Final status of the strategy.
        total_size: Total size requested.
        total_filled: Total size actually filled.
        total_value: Total value of fills (sum of size * price).
        total_fees: Total fees paid.
        average_price: Weighted average fill price.
        vwap: Volume-weighted average price of fills.
        num_slices: Total slices attempted.
        num_filled: Number of slices that filled.
        num_failed: Number of slices that failed.
        start_time: When execution started.
        end_time: When execution ended.
        metadata: Strategy-specific additional data.
    """
    strategy_id: str
    status: StrategyStatus
    total_size: float = 0.0
    total_filled: float = 0.0
    total_value: float = 0.0
    total_fees: float = 0.0
    average_price: float = 0.0
    vwap: float = 0.0
    num_slices: int = 0
    num_filled: int = 0
    num_failed: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class OrderStrategy(ABC):
    """
    Abstract base class for order execution strategies.

    Subclasses implement the strategy-specific logic for how to split
    an order into slices, when to skip slices, and how to determine
    execution prices.

    The execution engine (TWAPExecutor) calls these methods during
    order execution to get strategy decisions.
    """

    @abstractmethod
    def calculate_slices(self) -> List[SliceSpec]:
        """
        Calculate all slices for this strategy.

        Returns:
            List of SliceSpec defining each slice's size, price, and timing.
        """
        pass

    @abstractmethod
    def on_slice_complete(
        self,
        slice_number: int,
        order_id: Optional[str],
        fill_info: Optional[Dict[str, Any]]
    ) -> None:
        """
        Called after each slice is executed (successfully or not).

        Args:
            slice_number: 1-based index of the completed slice.
            order_id: Order ID if placed, None if skipped/failed.
            fill_info: Fill details if available.
        """
        pass

    @abstractmethod
    def should_skip_slice(
        self,
        slice_number: int,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Determine whether a slice should be skipped.

        Args:
            slice_number: 1-based index of the slice to check.
            market_data: Current market data (prices, volume, etc.).

        Returns:
            True if the slice should be skipped.
        """
        pass

    @abstractmethod
    def get_execution_price(
        self,
        slice_spec: SliceSpec,
        market_data: Dict[str, Any]
    ) -> float:
        """
        Determine the actual execution price for a slice.

        Args:
            slice_spec: The slice specification.
            market_data: Current market data with 'bid', 'ask', 'mid' keys.

        Returns:
            The price to use for this slice's order.
        """
        pass

    def get_result(self) -> StrategyResult:
        """
        Get the current strategy result.

        Subclasses should override this to provide strategy-specific results.

        Returns:
            StrategyResult with current execution state.
        """
        return StrategyResult(
            strategy_id="",
            status=StrategyStatus.PENDING
        )
