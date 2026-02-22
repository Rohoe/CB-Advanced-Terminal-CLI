"""
Order view service: data-access operations for order querying and status syncing.

Extracted from DisplayService to separate data fetching from presentation.
"""

import logging
from typing import Optional, List


class OrderViewService:
    """Fetches and filters orders from the API; syncs conditional order statuses."""

    def __init__(self, api_client, market_data, conditional_tracker):
        self.api_client = api_client
        self.market_data = market_data
        self.conditional_tracker = conditional_tracker

    def get_active_orders(self):
        """Get list of active orders."""
        try:
            orders_response = self.api_client.list_orders()

            if hasattr(orders_response, 'orders'):
                all_orders = orders_response.orders
                active_orders = [order for order in all_orders
                            if order.status in ['OPEN', 'PENDING']]
                return active_orders
            else:
                logging.warning("No orders field found in response")
                return []

        except Exception as e:
            logging.error(f"Error fetching orders: {str(e)}")
            return []

    def get_order_history(self, limit: int = 100, product_id: Optional[str] = None,
                         order_status: Optional[List[str]] = None):
        """Get historical orders with optional filters."""
        try:
            logging.info(f"Fetching order history (limit={limit}, product={product_id}, status={order_status})")

            self.market_data.rate_limiter.wait()

            orders_response = self.api_client.list_orders()

            if not hasattr(orders_response, 'orders'):
                logging.warning("No orders field found in response")
                return []

            all_orders = orders_response.orders

            filtered_orders = []
            for order in all_orders:
                if product_id and order.product_id != product_id:
                    continue
                if order_status and order.status not in order_status:
                    continue
                filtered_orders.append(order)
                if len(filtered_orders) >= limit:
                    break

            logging.info(f"Retrieved {len(filtered_orders)} orders (from {len(all_orders)} total)")
            return filtered_orders

        except Exception as e:
            logging.error(f"Error fetching order history: {str(e)}", exc_info=True)
            return []

    def sync_conditional_order_statuses(self, rate_limiter):
        """Sync tracked conditional orders with actual Coinbase order statuses."""
        try:
            rate_limiter.wait()
            all_api_orders = self.api_client.list_orders()

            api_order_statuses = {}
            if hasattr(all_api_orders, 'orders'):
                for order in all_api_orders.orders:
                    api_order_statuses[order.order_id] = order.status

            stop_limit_orders = self.conditional_tracker.list_stop_limit_orders()
            for order in stop_limit_orders:
                if order.is_completed():
                    continue

                if order.order_id in api_order_statuses:
                    api_status = api_order_statuses[order.order_id]
                    if api_status in ['CANCELLED', 'EXPIRED', 'FAILED', 'FILLED']:
                        logging.info(f"Syncing conditional order {order.order_id}: status changed to {api_status}")
                        self.conditional_tracker.update_order_status(
                            order_id=order.order_id,
                            order_type="stop_limit",
                            status=api_status,
                            fill_info=None
                        )
                else:
                    logging.info(f"Syncing conditional order {order.order_id}: not found in API, marking as CANCELLED")
                    self.conditional_tracker.update_order_status(
                        order_id=order.order_id,
                        order_type="stop_limit",
                        status="CANCELLED",
                        fill_info=None
                    )

        except Exception as e:
            logging.error(f"Error syncing conditional order statuses: {str(e)}", exc_info=True)
