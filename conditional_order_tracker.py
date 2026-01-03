"""
Persistence layer for conditional orders.

This module provides JSON-based storage and retrieval for conditional orders,
following the same pattern as TWAPTracker. Each order type gets its own
subdirectory for organization.

Directory Structure:
    conditional_data/
        stop_limit/
            {order_id}.json
        bracket/
            {order_id}.json
        attached_bracket/
            {order_id}.json

Usage:
    from conditional_order_tracker import ConditionalOrderTracker

    tracker = ConditionalOrderTracker()

    # Save a stop-limit order
    tracker.save_stop_limit_order(stop_loss_order)

    # Retrieve it
    order = tracker.get_stop_limit_order(order_id)

    # List all active orders
    active = tracker.list_all_active_orders()
"""

import json
import os
import logging
from typing import Optional, List, Union
from dataclasses import asdict
from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder


class ConditionalOrderTracker:
    """
    Manages persistence and retrieval of conditional orders.

    This class handles saving, loading, and querying conditional orders
    using JSON file storage. Each order type is stored in its own subdirectory.
    """

    def __init__(self, base_dir: str = "conditional_data"):
        """
        Initialize the conditional order tracker.

        Args:
            base_dir: Base directory for all conditional order data
        """
        self.base_dir = base_dir
        self.stop_limit_dir = os.path.join(base_dir, "stop_limit")
        self.bracket_dir = os.path.join(base_dir, "bracket")
        self.attached_bracket_dir = os.path.join(base_dir, "attached_bracket")
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        os.makedirs(self.stop_limit_dir, exist_ok=True)
        os.makedirs(self.bracket_dir, exist_ok=True)
        os.makedirs(self.attached_bracket_dir, exist_ok=True)
        logging.debug(f"Initialized conditional order directories in {self.base_dir}")

    def _get_stop_limit_path(self, order_id: str) -> str:
        """Get file path for a stop-limit order JSON."""
        return os.path.join(self.stop_limit_dir, f"{order_id}.json")

    def _get_bracket_path(self, order_id: str) -> str:
        """Get file path for a bracket order JSON."""
        return os.path.join(self.bracket_dir, f"{order_id}.json")

    def _get_attached_bracket_path(self, order_id: str) -> str:
        """Get file path for an attached bracket order JSON."""
        return os.path.join(self.attached_bracket_dir, f"{order_id}.json")

    # ==================== Stop-Limit Order Methods ====================

    def save_stop_limit_order(self, order: StopLimitOrder) -> None:
        """
        Save or update a stop-limit order to JSON.

        Args:
            order: StopLimitOrder instance to save
        """
        try:
            order_path = self._get_stop_limit_path(order.order_id)
            with open(order_path, 'w') as f:
                json.dump(asdict(order), f, indent=2)
            logging.info(f"Saved stop-limit order {order.order_id} ({order.order_type})")
        except Exception as e:
            logging.error(f"Error saving stop-limit order {order.order_id}: {str(e)}")
            raise

    def get_stop_limit_order(self, order_id: str) -> Optional[StopLimitOrder]:
        """
        Retrieve a stop-limit order from JSON.

        Args:
            order_id: Coinbase order ID

        Returns:
            StopLimitOrder instance or None if not found
        """
        try:
            order_path = self._get_stop_limit_path(order_id)
            if not os.path.exists(order_path):
                return None
            with open(order_path, 'r') as f:
                data = json.load(f)
            return StopLimitOrder(**data)
        except Exception as e:
            logging.error(f"Error loading stop-limit order {order_id}: {str(e)}")
            return None

    def list_stop_limit_orders(self, status: Optional[str] = None) -> List[StopLimitOrder]:
        """
        List all stop-limit orders, optionally filtered by status.

        Args:
            status: Optional status filter (e.g., "PENDING", "FILLED")

        Returns:
            List of StopLimitOrder instances
        """
        orders = []
        try:
            if not os.path.exists(self.stop_limit_dir):
                return orders

            for filename in os.listdir(self.stop_limit_dir):
                if not filename.endswith('.json'):
                    continue

                order_id = filename[:-5]  # Remove .json extension
                order = self.get_stop_limit_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)

            # Sort by created_at descending (newest first)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing stop-limit orders: {str(e)}")

        return orders

    # ==================== Bracket Order Methods ====================

    def save_bracket_order(self, order: BracketOrder) -> None:
        """
        Save or update a bracket order to JSON.

        Args:
            order: BracketOrder instance to save
        """
        try:
            order_path = self._get_bracket_path(order.order_id)
            with open(order_path, 'w') as f:
                json.dump(asdict(order), f, indent=2)
            logging.info(f"Saved bracket order {order.order_id}")
        except Exception as e:
            logging.error(f"Error saving bracket order {order.order_id}: {str(e)}")
            raise

    def get_bracket_order(self, order_id: str) -> Optional[BracketOrder]:
        """
        Retrieve a bracket order from JSON.

        Args:
            order_id: Coinbase order ID

        Returns:
            BracketOrder instance or None if not found
        """
        try:
            order_path = self._get_bracket_path(order_id)
            if not os.path.exists(order_path):
                return None
            with open(order_path, 'r') as f:
                data = json.load(f)
            return BracketOrder(**data)
        except Exception as e:
            logging.error(f"Error loading bracket order {order_id}: {str(e)}")
            return None

    def list_bracket_orders(self, status: Optional[str] = None) -> List[BracketOrder]:
        """
        List all bracket orders, optionally filtered by status.

        Args:
            status: Optional status filter (e.g., "ACTIVE", "FILLED")

        Returns:
            List of BracketOrder instances
        """
        orders = []
        try:
            if not os.path.exists(self.bracket_dir):
                return orders

            for filename in os.listdir(self.bracket_dir):
                if not filename.endswith('.json'):
                    continue

                order_id = filename[:-5]  # Remove .json extension
                order = self.get_bracket_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)

            # Sort by created_at descending (newest first)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing bracket orders: {str(e)}")

        return orders

    # ==================== Attached Bracket Order Methods ====================

    def save_attached_bracket_order(self, order: AttachedBracketOrder) -> None:
        """
        Save or update an attached bracket order to JSON.

        Args:
            order: AttachedBracketOrder instance to save
        """
        try:
            order_path = self._get_attached_bracket_path(order.entry_order_id)
            with open(order_path, 'w') as f:
                json.dump(asdict(order), f, indent=2)
            logging.info(f"Saved attached bracket order {order.entry_order_id}")
        except Exception as e:
            logging.error(f"Error saving attached bracket order {order.entry_order_id}: {str(e)}")
            raise

    def get_attached_bracket_order(self, order_id: str) -> Optional[AttachedBracketOrder]:
        """
        Retrieve an attached bracket order from JSON.

        Args:
            order_id: Entry order ID

        Returns:
            AttachedBracketOrder instance or None if not found
        """
        try:
            order_path = self._get_attached_bracket_path(order_id)
            if not os.path.exists(order_path):
                return None
            with open(order_path, 'r') as f:
                data = json.load(f)
            return AttachedBracketOrder(**data)
        except Exception as e:
            logging.error(f"Error loading attached bracket order {order_id}: {str(e)}")
            return None

    def list_attached_bracket_orders(self, status: Optional[str] = None) -> List[AttachedBracketOrder]:
        """
        List all attached bracket orders, optionally filtered by status.

        Args:
            status: Optional status filter (e.g., "PENDING", "ENTRY_FILLED")

        Returns:
            List of AttachedBracketOrder instances
        """
        orders = []
        try:
            if not os.path.exists(self.attached_bracket_dir):
                return orders

            for filename in os.listdir(self.attached_bracket_dir):
                if not filename.endswith('.json'):
                    continue

                order_id = filename[:-5]  # Remove .json extension
                order = self.get_attached_bracket_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)

            # Sort by created_at descending (newest first)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing attached bracket orders: {str(e)}")

        return orders

    # ==================== Unified Query Methods ====================

    def list_all_active_orders(self) -> List[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        """
        List all active conditional orders across all types.

        Returns:
            List of all active order instances (mixed types)
        """
        all_orders = []

        # Get active stop-limit orders
        stop_limit_orders = self.list_stop_limit_orders()
        all_orders.extend([o for o in stop_limit_orders if o.is_active()])

        # Get active bracket orders
        bracket_orders = self.list_bracket_orders()
        all_orders.extend([o for o in bracket_orders if o.is_active()])

        # Get active attached bracket orders
        attached_orders = self.list_attached_bracket_orders()
        all_orders.extend([o for o in attached_orders if o.is_active()])

        # Sort by created_at descending
        all_orders.sort(key=lambda x: x.created_at, reverse=True)

        return all_orders

    def get_order_by_id(self, order_id: str) -> Optional[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        """
        Try to retrieve an order from any type by ID.

        This method searches all order types and returns the first match.

        Args:
            order_id: Coinbase order ID to search for

        Returns:
            Order instance or None if not found
        """
        # Try stop-limit first
        order = self.get_stop_limit_order(order_id)
        if order:
            return order

        # Try bracket
        order = self.get_bracket_order(order_id)
        if order:
            return order

        # Try attached bracket
        order = self.get_attached_bracket_order(order_id)
        if order:
            return order

        return None

    def update_order_status(
        self,
        order_id: str,
        order_type: str,
        status: str,
        fill_info: Optional[dict] = None
    ) -> bool:
        """
        Update the status of an order and optionally fill information.

        Args:
            order_id: Coinbase order ID
            order_type: Type of order ("stop_limit", "bracket", "attached_bracket")
            status: New status value
            fill_info: Optional dict with fill data (filled_size, filled_value, fees)

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            # Retrieve the order
            if order_type == "stop_limit":
                order = self.get_stop_limit_order(order_id)
                if not order:
                    logging.warning(f"Stop-limit order {order_id} not found")
                    return False

                order.status = status
                order.update_timestamp()

                if fill_info:
                    order.filled_size = fill_info.get('filled_size', order.filled_size)
                    order.filled_value = fill_info.get('filled_value', order.filled_value)
                    order.fees = fill_info.get('fees', order.fees)
                    if status == "TRIGGERED":
                        order.triggered_at = fill_info.get('triggered_at')

                self.save_stop_limit_order(order)

            elif order_type == "bracket":
                order = self.get_bracket_order(order_id)
                if not order:
                    logging.warning(f"Bracket order {order_id} not found")
                    return False

                order.status = status
                order.update_timestamp()

                if fill_info:
                    order.total_filled_value = fill_info.get('total_filled_value', order.total_filled_value)
                    order.fees = fill_info.get('fees', order.fees)
                    # Update specific TP or SL fills if provided
                    if 'take_profit_filled_size' in fill_info:
                        order.take_profit_filled_size = fill_info['take_profit_filled_size']
                    if 'stop_loss_filled_size' in fill_info:
                        order.stop_loss_filled_size = fill_info['stop_loss_filled_size']

                self.save_bracket_order(order)

            elif order_type == "attached_bracket":
                order = self.get_attached_bracket_order(order_id)
                if not order:
                    logging.warning(f"Attached bracket order {order_id} not found")
                    return False

                order.status = status
                order.update_timestamp()

                if fill_info:
                    # Update entry or exit fills based on status
                    if status == "ENTRY_FILLED":
                        order.entry_filled_size = fill_info.get('filled_size', order.entry_filled_size)
                        order.entry_filled_value = fill_info.get('filled_value', order.entry_filled_value)
                        order.entry_fees = fill_info.get('fees', order.entry_fees)
                    elif status in ["TP_FILLED", "SL_FILLED"]:
                        order.exit_filled_size = fill_info.get('filled_size', order.exit_filled_size)
                        order.exit_filled_value = fill_info.get('filled_value', order.exit_filled_value)
                        order.exit_fees = fill_info.get('fees', order.exit_fees)

                self.save_attached_bracket_order(order)

            else:
                logging.error(f"Unknown order type: {order_type}")
                return False

            logging.info(f"Updated {order_type} order {order_id} status to {status}")
            return True

        except Exception as e:
            logging.error(f"Error updating order {order_id}: {str(e)}")
            return False

    def delete_order(self, order_id: str, order_type: str) -> bool:
        """
        Delete an order file.

        Args:
            order_id: Coinbase order ID
            order_type: Type of order ("stop_limit", "bracket", "attached_bracket")

        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            if order_type == "stop_limit":
                path = self._get_stop_limit_path(order_id)
            elif order_type == "bracket":
                path = self._get_bracket_path(order_id)
            elif order_type == "attached_bracket":
                path = self._get_attached_bracket_path(order_id)
            else:
                logging.error(f"Unknown order type: {order_type}")
                return False

            if os.path.exists(path):
                os.remove(path)
                logging.info(f"Deleted {order_type} order {order_id}")
                return True
            else:
                logging.warning(f"Order file not found: {path}")
                return False

        except Exception as e:
            logging.error(f"Error deleting order {order_id}: {str(e)}")
            return False

    def get_statistics(self) -> dict:
        """
        Get statistics about conditional orders.

        Returns:
            Dict with counts by type and status
        """
        stats = {
            'stop_limit': {
                'total': 0,
                'active': 0,
                'completed': 0,
                'stop_loss': 0,
                'take_profit': 0
            },
            'bracket': {
                'total': 0,
                'active': 0,
                'completed': 0
            },
            'attached_bracket': {
                'total': 0,
                'active': 0,
                'completed': 0
            }
        }

        # Stop-limit stats
        stop_limit_orders = self.list_stop_limit_orders()
        stats['stop_limit']['total'] = len(stop_limit_orders)
        for order in stop_limit_orders:
            if order.is_active():
                stats['stop_limit']['active'] += 1
            if order.is_completed():
                stats['stop_limit']['completed'] += 1
            if order.order_type == "STOP_LOSS":
                stats['stop_limit']['stop_loss'] += 1
            elif order.order_type == "TAKE_PROFIT":
                stats['stop_limit']['take_profit'] += 1

        # Bracket stats
        bracket_orders = self.list_bracket_orders()
        stats['bracket']['total'] = len(bracket_orders)
        for order in bracket_orders:
            if order.is_active():
                stats['bracket']['active'] += 1
            if order.is_completed():
                stats['bracket']['completed'] += 1

        # Attached bracket stats
        attached_orders = self.list_attached_bracket_orders()
        stats['attached_bracket']['total'] = len(attached_orders)
        for order in attached_orders:
            if order.is_active():
                stats['attached_bracket']['active'] += 1
            if order.is_completed():
                stats['attached_bracket']['completed'] += 1

        return stats
