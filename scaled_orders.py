"""
Data models for scaled/ladder orders.

Scaled orders place multiple limit orders across a price range with configurable
size distribution. This enables building positions at different price levels.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class DistributionType(Enum):
    """How to distribute order sizes across price levels."""
    LINEAR = "linear"           # Equal sizes at each level
    GEOMETRIC = "geometric"     # Exponentially increasing toward favorable end
    FRONT_WEIGHTED = "front_weighted"  # More size near current market price


@dataclass
class ScaledOrderLevel:
    """A single price level in a scaled order."""
    level_number: int           # 1-based index
    price: float               # Price for this level
    size: float                # Size at this level
    order_id: Optional[str] = None   # Coinbase order ID once placed
    status: str = "pending"    # pending, placed, filled, failed, cancelled
    filled_size: float = 0.0
    filled_value: float = 0.0
    fees: float = 0.0
    is_maker: bool = True
    placed_at: Optional[str] = None
    filled_at: Optional[str] = None


@dataclass
class ScaledOrder:
    """Complete scaled/ladder order with all levels."""
    scaled_id: str
    product_id: str
    side: str                   # BUY or SELL
    total_size: float
    price_low: float
    price_high: float
    num_orders: int
    distribution: DistributionType
    status: str = "pending"     # pending, active, completed, cancelled, partial
    levels: List[ScaledOrderLevel] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    total_filled: float = 0.0
    total_value_filled: float = 0.0
    total_fees: float = 0.0
    maker_orders: int = 0
    taker_orders: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def fill_rate(self) -> float:
        """Percentage of total size that has been filled."""
        if self.total_size <= 0:
            return 0.0
        return (self.total_filled / self.total_size) * 100

    @property
    def average_price(self) -> float:
        """Volume-weighted average fill price."""
        if self.total_filled <= 0:
            return 0.0
        return self.total_value_filled / self.total_filled

    @property
    def num_placed(self) -> int:
        """Number of orders successfully placed."""
        return sum(1 for l in self.levels if l.status in ('placed', 'filled'))

    @property
    def num_filled(self) -> int:
        """Number of orders filled."""
        return sum(1 for l in self.levels if l.status == 'filled')

    @property
    def num_failed(self) -> int:
        """Number of orders that failed."""
        return sum(1 for l in self.levels if l.status == 'failed')

    def is_active(self) -> bool:
        """Check if the order is still active."""
        return self.status in ('pending', 'active', 'partial')

    def is_completed(self) -> bool:
        """Check if the order is fully completed."""
        return self.status in ('completed', 'cancelled')

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        from dataclasses import asdict
        data = asdict(self)
        data['distribution'] = self.distribution.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ScaledOrder':
        """Create from dictionary (JSON deserialization)."""
        data = data.copy()
        data['distribution'] = DistributionType(data['distribution'])
        levels_data = data.pop('levels', [])
        order = cls(**data)
        order.levels = [ScaledOrderLevel(**l) for l in levels_data]
        return order
