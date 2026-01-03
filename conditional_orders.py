"""
Conditional order data models for stop-loss, take-profit, and bracket orders.

This module provides dataclasses for tracking conditional orders placed via
the Coinbase Advanced Trade API. All conditional orders use native Coinbase
SDK methods rather than client-side monitoring.

Order Types:
    - StopLimitOrder: Both stop-loss and take-profit orders
    - BracketOrder: TP/SL bracket on existing positions
    - AttachedBracketOrder: Entry order with attached TP/SL bracket

Usage:
    from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder

    # Create a stop-loss order
    stop_loss = StopLimitOrder(
        order_id="order-123",
        client_order_id="sl-001",
        product_id="BTC-USD",
        side="SELL",
        base_size="0.1",
        stop_price="48000",
        limit_price="47900",
        stop_direction="STOP_DIRECTION_STOP_DOWN",
        order_type="STOP_LOSS",
        status="PENDING",
        created_at="2026-01-03T12:00:00Z"
    )
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class StopLimitOrder:
    """
    Stop-limit order - used for BOTH stop-loss and take-profit orders.

    The stop_direction parameter determines the trigger behavior:
    - STOP_DIRECTION_STOP_DOWN: Triggers when price falls to stop_price
      (stop-loss for LONG, take-profit for SHORT)
    - STOP_DIRECTION_STOP_UP: Triggers when price rises to stop_price
      (take-profit for LONG, stop-loss for SHORT)

    Examples:
        Stop-Loss (SELL):
            - Own BTC at $50k, want to sell if it drops to $48k
            - stop_direction = "STOP_DIRECTION_STOP_DOWN"
            - stop_price = "48000" (trigger when price falls)
            - limit_price = "47900" (sell at this price or better)

        Take-Profit (SELL):
            - Own BTC at $50k, want to sell if it rises to $55k
            - stop_direction = "STOP_DIRECTION_STOP_UP"
            - stop_price = "55000" (trigger when price rises)
            - limit_price = "54900" (sell at this price or better)

    Attributes:
        order_id: Coinbase order ID from API response
        client_order_id: Client-generated unique order identifier
        product_id: Trading pair (e.g., "BTC-USD")
        side: Order side ("BUY" or "SELL")
        base_size: Order size in base currency (as string)
        stop_price: Trigger price that activates the order
        limit_price: Execution price after trigger
        stop_direction: Direction for stop trigger
        order_type: Display type ("STOP_LOSS" or "TAKE_PROFIT")
        status: Order status (PENDING, TRIGGERED, FILLED, CANCELLED, EXPIRED)
        created_at: ISO timestamp of order creation
        updated_at: ISO timestamp of last update
        triggered_at: ISO timestamp when stop was triggered
        filled_size: Amount filled (as string)
        filled_value: Total value filled (as string)
        fees: Trading fees paid (as string)
        error_message: Error message if order failed
    """

    order_id: str
    client_order_id: str
    product_id: str
    side: str  # BUY or SELL
    base_size: str  # Size as string (SDK requirement)
    stop_price: str  # Trigger price
    limit_price: str  # Execution price after trigger
    stop_direction: str  # STOP_DIRECTION_STOP_UP or STOP_DIRECTION_STOP_DOWN
    order_type: str  # "STOP_LOSS" or "TAKE_PROFIT" (for display)
    status: str  # PENDING, TRIGGERED, FILLED, CANCELLED, EXPIRED
    created_at: str  # ISO timestamp
    updated_at: Optional[str] = None
    triggered_at: Optional[str] = None
    filled_size: str = "0"
    filled_value: str = "0"
    fees: str = "0"
    error_message: Optional[str] = None

    def is_active(self) -> bool:
        """Check if order is still active (pending or triggered)."""
        return self.status in ["PENDING", "TRIGGERED"]

    def is_completed(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in ["FILLED", "CANCELLED", "EXPIRED"]

    def update_timestamp(self):
        """Update the updated_at timestamp to current time."""
        self.updated_at = datetime.utcnow().isoformat() + "Z"


@dataclass
class BracketOrder:
    """
    Bracket order with take-profit and stop-loss for existing positions.

    This order type is used with trigger_bracket_order_gtc() for positions
    you already hold. It sets both TP and SL in a single order.

    For entry + TP/SL, use AttachedBracketOrder instead.

    Example:
        You own 0.1 BTC at $50k, want TP at $55k and SL at $48k:
        - side = "SELL" (selling the position)
        - base_size = "0.1"
        - limit_price = "55000" (take-profit)
        - stop_trigger_price = "48000" (stop-loss)

    Attributes:
        order_id: Coinbase order ID from API response
        client_order_id: Client-generated unique order identifier
        product_id: Trading pair (e.g., "BTC-USD")
        side: Side of the position ("BUY" or "SELL")
        base_size: Position size (as string)
        limit_price: Take-profit price
        stop_trigger_price: Stop-loss trigger price
        status: Order status (PENDING, ACTIVE, FILLED, CANCELLED)
        created_at: ISO timestamp of order creation
        updated_at: ISO timestamp of last update
        take_profit_filled_size: TP fill amount (as string)
        stop_loss_filled_size: SL fill amount (as string)
        total_filled_value: Total value of fills (as string)
        fees: Trading fees paid (as string)
        take_profit_order_id: Child TP order ID (if available)
        stop_loss_order_id: Child SL order ID (if available)
        error_message: Error message if order failed
    """

    order_id: str
    client_order_id: str
    product_id: str
    side: str  # BUY or SELL (of the position)
    base_size: str  # Position size
    limit_price: str  # Take-profit price
    stop_trigger_price: str  # Stop-loss trigger price
    status: str  # PENDING, ACTIVE, FILLED, CANCELLED
    created_at: str
    updated_at: Optional[str] = None
    # Filled data
    take_profit_filled_size: str = "0"
    stop_loss_filled_size: str = "0"
    total_filled_value: str = "0"
    fees: str = "0"
    # Child order IDs (if available from API response)
    take_profit_order_id: Optional[str] = None
    stop_loss_order_id: Optional[str] = None
    error_message: Optional[str] = None

    def is_active(self) -> bool:
        """Check if bracket is still active."""
        return self.status in ["PENDING", "ACTIVE"]

    def is_completed(self) -> bool:
        """Check if bracket is in a terminal state."""
        return self.status in ["FILLED", "CANCELLED"]

    def update_timestamp(self):
        """Update the updated_at timestamp to current time."""
        self.updated_at = datetime.utcnow().isoformat() + "Z"


@dataclass
class AttachedBracketOrder:
    """
    Entry order with attached TP/SL bracket.

    This order type is created using create_order() with
    attached_order_configuration. It places an entry order and
    automatically activates TP/SL when the entry fills.

    Example:
        Enter BTC at $50k with TP at $55k and SL at $48k:
        - side = "BUY"
        - entry_limit_price = "50000" (entry)
        - take_profit_price = "55000" (TP)
        - stop_loss_price = "48000" (SL)

    Status Flow:
        PENDING → ENTRY_FILLED → (TP_FILLED or SL_FILLED) → CANCELLED (other side)

    Attributes:
        entry_order_id: Main entry order ID
        client_order_id: Client-generated unique order identifier
        product_id: Trading pair (e.g., "BTC-USD")
        side: Order side ("BUY" or "SELL")
        base_size: Order size (as string)
        entry_limit_price: Entry limit price
        take_profit_price: TP trigger price
        stop_loss_price: SL trigger price
        status: Order status (PENDING, ENTRY_FILLED, TP_FILLED, SL_FILLED, CANCELLED)
        created_at: ISO timestamp of order creation
        updated_at: ISO timestamp of last update
        entry_filled_size: Entry fill amount (as string)
        entry_filled_value: Entry fill value (as string)
        entry_fees: Entry trading fees (as string)
        exit_filled_size: Exit (TP/SL) fill amount (as string)
        exit_filled_value: Exit fill value (as string)
        exit_fees: Exit trading fees (as string)
        take_profit_order_id: Child TP order ID
        stop_loss_order_id: Child SL order ID
        error_message: Error message if order failed
    """

    entry_order_id: str
    client_order_id: str
    product_id: str
    side: str  # BUY or SELL
    base_size: str  # Order size
    entry_limit_price: str  # Entry price
    take_profit_price: str  # TP trigger
    stop_loss_price: str  # SL trigger
    status: str  # PENDING, ENTRY_FILLED, TP_FILLED, SL_FILLED, CANCELLED
    created_at: str
    updated_at: Optional[str] = None
    # Entry fill data
    entry_filled_size: str = "0"
    entry_filled_value: str = "0"
    entry_fees: str = "0"
    # Exit fill data
    exit_filled_size: str = "0"
    exit_filled_value: str = "0"
    exit_fees: str = "0"
    # Child order IDs
    take_profit_order_id: Optional[str] = None
    stop_loss_order_id: Optional[str] = None
    error_message: Optional[str] = None

    def is_active(self) -> bool:
        """Check if any part of the order is still active."""
        return self.status in ["PENDING", "ENTRY_FILLED"]

    def is_completed(self) -> bool:
        """Check if order is fully completed."""
        return self.status in ["TP_FILLED", "SL_FILLED", "CANCELLED"]

    def update_timestamp(self):
        """Update the updated_at timestamp to current time."""
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def get_total_fees(self) -> float:
        """Calculate total fees (entry + exit)."""
        try:
            entry = float(self.entry_fees) if self.entry_fees else 0.0
            exit_val = float(self.exit_fees) if self.exit_fees else 0.0
            return entry + exit_val
        except (ValueError, TypeError):
            return 0.0
