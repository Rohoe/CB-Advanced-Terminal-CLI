"""
Persistence layer for conditional orders.

Provides an abstract interface and JSON-based implementation for
conditional order storage, using BaseOrderTracker for common file I/O.

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

import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Union
from dataclasses import asdict

from base_tracker import BaseOrderTracker
from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder


class ConditionalOrderStorage(ABC):
    """Abstract interface for conditional order persistence."""

    @abstractmethod
    def save_stop_limit_order(self, order: StopLimitOrder) -> None:
        pass

    @abstractmethod
    def get_stop_limit_order(self, order_id: str) -> Optional[StopLimitOrder]:
        pass

    @abstractmethod
    def list_stop_limit_orders(self, status: Optional[str] = None) -> List[StopLimitOrder]:
        pass

    @abstractmethod
    def save_bracket_order(self, order: BracketOrder) -> None:
        pass

    @abstractmethod
    def get_bracket_order(self, order_id: str) -> Optional[BracketOrder]:
        pass

    @abstractmethod
    def list_bracket_orders(self, status: Optional[str] = None) -> List[BracketOrder]:
        pass

    @abstractmethod
    def save_attached_bracket_order(self, order: AttachedBracketOrder) -> None:
        pass

    @abstractmethod
    def get_attached_bracket_order(self, order_id: str) -> Optional[AttachedBracketOrder]:
        pass

    @abstractmethod
    def list_attached_bracket_orders(self, status: Optional[str] = None) -> List[AttachedBracketOrder]:
        pass

    @abstractmethod
    def list_all_active_orders(self) -> List[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        pass

    @abstractmethod
    def get_order_by_id(self, order_id: str) -> Optional[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        pass

    @abstractmethod
    def update_order_status(self, order_id: str, order_type: str, status: str,
                            fill_info: Optional[dict] = None) -> bool:
        pass

    @abstractmethod
    def delete_order(self, order_id: str, order_type: str) -> bool:
        pass

    @abstractmethod
    def get_statistics(self) -> dict:
        pass


class ConditionalOrderTracker(ConditionalOrderStorage, BaseOrderTracker):
    """
    Manages persistence and retrieval of conditional orders.

    This class handles saving, loading, and querying conditional orders
    using JSON file storage. Each order type is stored in its own subdirectory.
    """

    def __init__(self, base_dir: str = "conditional_data"):
        super().__init__(base_dir, ["stop_limit", "bracket", "attached_bracket"])
        self.stop_limit_dir = self._get_subdir("stop_limit")
        self.bracket_dir = self._get_subdir("bracket")
        self.attached_bracket_dir = self._get_subdir("attached_bracket")

    # ==================== Stop-Limit Order Methods ====================

    def save_stop_limit_order(self, order: StopLimitOrder) -> None:
        """Save or update a stop-limit order to JSON."""
        path = self._get_path("stop_limit", order.order_id)
        self._save_json(path, asdict(order), f"stop-limit order {order.order_id}")
        logging.info(f"Saved stop-limit order {order.order_id} ({order.order_type})")

    def get_stop_limit_order(self, order_id: str) -> Optional[StopLimitOrder]:
        """Retrieve a stop-limit order from JSON."""
        data = self._load_json(self._get_path("stop_limit", order_id), f"stop-limit order {order_id}")
        if data is None:
            return None
        try:
            return StopLimitOrder(**data)
        except Exception as e:
            logging.error(f"Error constructing stop-limit order {order_id}: {str(e)}")
            return None

    def list_stop_limit_orders(self, status: Optional[str] = None) -> List[StopLimitOrder]:
        """List all stop-limit orders, optionally filtered by status."""
        orders = []
        try:
            for order_id in self._list_ids("stop_limit"):
                order = self.get_stop_limit_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing stop-limit orders: {str(e)}")
        return orders

    # ==================== Bracket Order Methods ====================

    def save_bracket_order(self, order: BracketOrder) -> None:
        """Save or update a bracket order to JSON."""
        path = self._get_path("bracket", order.order_id)
        self._save_json(path, asdict(order), f"bracket order {order.order_id}")
        logging.info(f"Saved bracket order {order.order_id}")

    def get_bracket_order(self, order_id: str) -> Optional[BracketOrder]:
        """Retrieve a bracket order from JSON."""
        data = self._load_json(self._get_path("bracket", order_id), f"bracket order {order_id}")
        if data is None:
            return None
        try:
            return BracketOrder(**data)
        except Exception as e:
            logging.error(f"Error constructing bracket order {order_id}: {str(e)}")
            return None

    def list_bracket_orders(self, status: Optional[str] = None) -> List[BracketOrder]:
        """List all bracket orders, optionally filtered by status."""
        orders = []
        try:
            for order_id in self._list_ids("bracket"):
                order = self.get_bracket_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing bracket orders: {str(e)}")
        return orders

    # ==================== Attached Bracket Order Methods ====================

    def save_attached_bracket_order(self, order: AttachedBracketOrder) -> None:
        """Save or update an attached bracket order to JSON."""
        path = self._get_path("attached_bracket", order.entry_order_id)
        self._save_json(path, asdict(order), f"attached bracket order {order.entry_order_id}")
        logging.info(f"Saved attached bracket order {order.entry_order_id}")

    def get_attached_bracket_order(self, order_id: str) -> Optional[AttachedBracketOrder]:
        """Retrieve an attached bracket order from JSON."""
        data = self._load_json(self._get_path("attached_bracket", order_id), f"attached bracket order {order_id}")
        if data is None:
            return None
        try:
            return AttachedBracketOrder(**data)
        except Exception as e:
            logging.error(f"Error constructing attached bracket order {order_id}: {str(e)}")
            return None

    def list_attached_bracket_orders(self, status: Optional[str] = None) -> List[AttachedBracketOrder]:
        """List all attached bracket orders, optionally filtered by status."""
        orders = []
        try:
            for order_id in self._list_ids("attached_bracket"):
                order = self.get_attached_bracket_order(order_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing attached bracket orders: {str(e)}")
        return orders

    # ==================== Unified Query Methods ====================

    def list_all_active_orders(self) -> List[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        """List all active conditional orders across all types."""
        all_orders = []

        stop_limit_orders = self.list_stop_limit_orders()
        all_orders.extend([o for o in stop_limit_orders if o.is_active()])

        bracket_orders = self.list_bracket_orders()
        all_orders.extend([o for o in bracket_orders if o.is_active()])

        attached_orders = self.list_attached_bracket_orders()
        all_orders.extend([o for o in attached_orders if o.is_active()])

        all_orders.sort(key=lambda x: x.created_at, reverse=True)
        return all_orders

    def get_order_by_id(self, order_id: str) -> Optional[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        """Try to retrieve an order from any type by ID."""
        order = self.get_stop_limit_order(order_id)
        if order:
            return order

        order = self.get_bracket_order(order_id)
        if order:
            return order

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
        """Update the status of an order and optionally fill information."""
        try:
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
        """Delete an order file."""
        try:
            if order_type == "stop_limit":
                path = self._get_path("stop_limit", order_id)
            elif order_type == "bracket":
                path = self._get_path("bracket", order_id)
            elif order_type == "attached_bracket":
                path = self._get_path("attached_bracket", order_id)
            else:
                logging.error(f"Unknown order type: {order_type}")
                return False

            result = self._delete_file(path, f"{order_type} order {order_id}")
            if result:
                logging.info(f"Deleted {order_type} order {order_id}")
            else:
                logging.warning(f"Order file not found for {order_type} order {order_id}")
            return result

        except Exception as e:
            logging.error(f"Error deleting order {order_id}: {str(e)}")
            return False

    def get_statistics(self) -> dict:
        """Get statistics about conditional orders."""
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

        bracket_orders = self.list_bracket_orders()
        stats['bracket']['total'] = len(bracket_orders)
        for order in bracket_orders:
            if order.is_active():
                stats['bracket']['active'] += 1
            if order.is_completed():
                stats['bracket']['completed'] += 1

        attached_orders = self.list_attached_bracket_orders()
        stats['attached_bracket']['total'] = len(attached_orders)
        for order in attached_orders:
            if order.is_active():
                stats['attached_bracket']['active'] += 1
            if order.is_completed():
                stats['attached_bracket']['completed'] += 1

        return stats
