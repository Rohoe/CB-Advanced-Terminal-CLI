"""
Persistence layer for scaled/ladder orders.

Provides JSON-based storage and retrieval for scaled orders,
following the same pattern as ConditionalOrderTracker.

Directory Structure:
    scaled_data/
        orders/
            {scaled_id}.json
"""

import json
import os
import logging
from typing import Optional, List

from scaled_orders import ScaledOrder


class ScaledOrderTracker:
    """Manages persistence and retrieval of scaled orders."""

    def __init__(self, base_dir: str = "scaled_data"):
        self.base_dir = base_dir
        self.orders_dir = os.path.join(base_dir, "orders")
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        os.makedirs(self.orders_dir, exist_ok=True)
        logging.debug(f"Initialized scaled order directories in {self.base_dir}")

    def _get_order_path(self, scaled_id: str) -> str:
        """Get file path for a scaled order JSON."""
        return os.path.join(self.orders_dir, f"{scaled_id}.json")

    def save_scaled_order(self, order: ScaledOrder) -> None:
        """Save or update a scaled order to JSON."""
        try:
            order_path = self._get_order_path(order.scaled_id)
            with open(order_path, 'w') as f:
                json.dump(order.to_dict(), f, indent=2)
            logging.info(f"Saved scaled order {order.scaled_id}")
        except Exception as e:
            logging.error(f"Error saving scaled order {order.scaled_id}: {str(e)}")
            raise

    def get_scaled_order(self, scaled_id: str) -> Optional[ScaledOrder]:
        """Retrieve a scaled order from JSON."""
        try:
            order_path = self._get_order_path(scaled_id)
            if not os.path.exists(order_path):
                return None
            with open(order_path, 'r') as f:
                data = json.load(f)
            return ScaledOrder.from_dict(data)
        except Exception as e:
            logging.error(f"Error loading scaled order {scaled_id}: {str(e)}")
            return None

    def list_scaled_orders(self, status: Optional[str] = None) -> List[ScaledOrder]:
        """List all scaled orders, optionally filtered by status."""
        orders = []
        try:
            if not os.path.exists(self.orders_dir):
                return orders

            for filename in os.listdir(self.orders_dir):
                if not filename.endswith('.json'):
                    continue

                scaled_id = filename[:-5]
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
        try:
            path = self._get_order_path(scaled_id)
            if os.path.exists(path):
                os.remove(path)
                logging.info(f"Deleted scaled order {scaled_id}")
                return True
            return False
        except Exception as e:
            logging.error(f"Error deleting scaled order {scaled_id}: {str(e)}")
            return False
