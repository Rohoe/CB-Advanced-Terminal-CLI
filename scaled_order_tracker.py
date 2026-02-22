"""
Persistence layer for scaled/ladder orders.

Provides JSON-based storage and retrieval for scaled orders,
using BaseOrderTracker for common file I/O.

Directory Structure:
    scaled_data/
        orders/
            {scaled_id}.json
"""

import logging
from typing import Optional, List

from base_tracker import BaseOrderTracker
from scaled_orders import ScaledOrder


class ScaledOrderTracker(BaseOrderTracker):
    """Manages persistence and retrieval of scaled orders."""

    def __init__(self, base_dir: str = "scaled_data"):
        super().__init__(base_dir, ["orders"])
        self.orders_dir = self._get_subdir("orders")

    def save_scaled_order(self, order: ScaledOrder) -> None:
        """Save or update a scaled order to JSON."""
        order_path = self._get_path("orders", order.scaled_id)
        self._save_json(order_path, order.to_dict(), f"scaled order {order.scaled_id}")
        logging.info(f"Saved scaled order {order.scaled_id}")

    def get_scaled_order(self, scaled_id: str) -> Optional[ScaledOrder]:
        """Retrieve a scaled order from JSON."""
        data = self._load_json(self._get_path("orders", scaled_id), f"scaled order {scaled_id}")
        if data is None:
            return None
        try:
            return ScaledOrder.from_dict(data)
        except Exception as e:
            logging.error(f"Error constructing scaled order {scaled_id}: {str(e)}")
            return None

    def list_scaled_orders(self, status: Optional[str] = None) -> List[ScaledOrder]:
        """List all scaled orders, optionally filtered by status."""
        orders = []
        try:
            for scaled_id in self._list_ids("orders"):
                order = self.get_scaled_order(scaled_id)
                if order:
                    if status is None or order.status == status:
                        orders.append(order)
            orders.sort(key=lambda x: x.created_at, reverse=True)
        except Exception as e:
            logging.error(f"Error listing scaled orders: {str(e)}")
        return orders

    def update_order_status(
        self,
        scaled_id: str,
        status: str,
        fill_info: Optional[dict] = None
    ) -> bool:
        """Update the status of a scaled order."""
        try:
            order = self.get_scaled_order(scaled_id)
            if not order:
                logging.warning(f"Scaled order {scaled_id} not found")
                return False

            order.status = status
            if fill_info:
                order.total_filled = fill_info.get('total_filled', order.total_filled)
                order.total_value_filled = fill_info.get('total_value_filled', order.total_value_filled)
                order.total_fees = fill_info.get('total_fees', order.total_fees)

            self.save_scaled_order(order)
            logging.info(f"Updated scaled order {scaled_id} status to {status}")
            return True

        except Exception as e:
            logging.error(f"Error updating scaled order {scaled_id}: {str(e)}")
            return False

    def update_level_status(
        self,
        scaled_id: str,
        level_number: int,
        status: str,
        order_id: Optional[str] = None,
        fill_info: Optional[dict] = None
    ) -> bool:
        """Update a specific level's status within a scaled order."""
        try:
            order = self.get_scaled_order(scaled_id)
            if not order:
                return False

            for level in order.levels:
                if level.level_number == level_number:
                    level.status = status
                    if order_id:
                        level.order_id = order_id
                    if fill_info:
                        level.filled_size = fill_info.get('filled_size', level.filled_size)
                        level.filled_value = fill_info.get('filled_value', level.filled_value)
                        level.fees = fill_info.get('fees', level.fees)
                        level.is_maker = fill_info.get('is_maker', level.is_maker)
                    break

            # Recalculate totals
            order.total_filled = sum(l.filled_size for l in order.levels)
            order.total_value_filled = sum(l.filled_value for l in order.levels)
            order.total_fees = sum(l.fees for l in order.levels)
            order.maker_orders = sum(1 for l in order.levels if l.status == 'filled' and l.is_maker)
            order.taker_orders = sum(1 for l in order.levels if l.status == 'filled' and not l.is_maker)

            self.save_scaled_order(order)
            return True

        except Exception as e:
            logging.error(f"Error updating level {level_number} for scaled order {scaled_id}: {str(e)}")
            return False

    def delete_scaled_order(self, scaled_id: str) -> bool:
        """Delete a scaled order file."""
        path = self._get_path("orders", scaled_id)
        result = self._delete_file(path, f"scaled order {scaled_id}")
        if result:
            logging.info(f"Deleted scaled order {scaled_id}")
        return result
