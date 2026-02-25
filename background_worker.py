"""
Background order status checker thread.

Extracted from TradingTerminal to separate background monitoring
from the main application orchestrator.
"""

import logging
import time
from queue import Empty

from ui_helpers import format_currency, print_success


class OrderStatusChecker:
    """Background thread target that monitors order fills for TWAP and conditional orders.

    When a WebSocketService is provided, fill events are received via push
    callbacks. REST polling is reduced to a 30-second backup interval.
    Without WebSocket, REST polling continues at 0.5-second intervals.
    """

    def __init__(self, terminal, websocket_service=None, analytics_service=None):
        """
        Args:
            terminal: TradingTerminal instance (provides shared state and services).
            websocket_service: Optional WebSocketService for push-based fills.
            analytics_service: Optional AnalyticsService for P&L recording.
        """
        self.terminal = terminal
        self.websocket_service = websocket_service
        self.analytics_service = analytics_service

        # Register fill callback if WebSocket is available
        if websocket_service:
            websocket_service.register_fill_callback(self._on_ws_fill)
            self._ws_poll_interval = 30  # Reduced polling when WS connected
        else:
            self._ws_poll_interval = 0.5

    def _on_ws_fill(self, fill_event: dict):
        """Handle a fill event from WebSocket."""
        t = self.terminal
        order_id = fill_event.get('order_id')
        if not order_id:
            return

        logging.info(f"WS fill received for order {order_id}")

        # Check if it's a TWAP order
        with t.twap_lock:
            twap_id = t.order_to_twap_map.get(order_id)

        if twap_id:
            with t.order_lock:
                if order_id not in t.filled_orders:
                    t.filled_orders.append(order_id)

            try:
                filled_size = float(fill_event.get('size', 0))
                price = float(fill_event.get('price', 0))
                fee = float(fill_event.get('fee', 0))

                with t.twap_lock:
                    if twap_id in t.twap_orders:
                        t.twap_orders[twap_id]['total_filled'] += filled_size
                        t.twap_orders[twap_id]['total_value_filled'] += filled_size * price
                        t.twap_orders[twap_id]['total_fees'] += fee
            except (ValueError, TypeError):
                pass
            return

        # Check if it's a conditional order
        with t.conditional_lock:
            order_info = t.order_to_conditional_map.get(order_id)

        if order_info:
            order_type, conditional_id = order_info
            status = fill_event.get('status', 'FILLED')

            result = t.conditional_order_tracker.update_order_status(
                order_id=conditional_id,
                order_type=order_type,
                status=status,
                fill_info={
                    'filled_size': str(fill_event.get('size', 0)),
                    'filled_value': str(float(fill_event.get('size', 0)) * float(fill_event.get('price', 0))),
                    'fees': str(fill_event.get('fee', 0)),
                }
            )

            if result:
                with t.conditional_lock:
                    if order_id in t.order_to_conditional_map:
                        del t.order_to_conditional_map[order_id]

                print_success(f"\nConditional order {order_id[:8]}... FILLED! (via WebSocket)")

    def run(self):
        """Background thread to check order statuses efficiently."""
        t = self.terminal
        logging.debug("Starting order_status_checker thread")

        while t.is_running:
            try:
                has_orders = False
                with t.twap_lock:
                    has_orders = bool(t.twap_orders)
                with t.conditional_lock:
                    has_orders = has_orders or bool(t.order_to_conditional_map)

                if not has_orders:
                    time.sleep(5)
                    continue

                try:
                    order = t.order_queue.get(timeout=self._ws_poll_interval)

                    if order is None:
                        logging.debug("Received shutdown signal")
                        return

                    logging.debug(f"Retrieved order from queue: {order}")

                    with t.twap_lock:
                        order_id = order if isinstance(order, str) else order.get('order_id')
                        is_twap_order = order_id and order_id in t.order_to_twap_map

                    with t.conditional_lock:
                        cond_order_id = order if isinstance(order, str) else order.get('order_id') if isinstance(order, dict) else None
                        is_conditional_order = cond_order_id and cond_order_id in t.order_to_conditional_map

                    if is_twap_order:
                        self._process_twap_order(t, order)

                    elif is_conditional_order:
                        self._process_conditional_order(t, order)

                except Empty:
                    continue

            except Exception as e:
                logging.error(f"Error in order status checker: {str(e)}", exc_info=True)
                time.sleep(1)

        logging.debug("Order status checker thread shutting down")

    def _process_twap_order(self, t, order):
        """Process a batch of TWAP orders from the queue."""
        logging.debug(f"Processing TWAP order: {order}")
        orders_to_check = [order]

        while len(orders_to_check) < 50:
            try:
                order = t.order_queue.get_nowait()
                if order is None:
                    return
                with t.twap_lock:
                    order_id = order if isinstance(order, str) else order.get('order_id')
                    is_twap = order_id and order_id in t.order_to_twap_map
                if is_twap:
                    orders_to_check.append(order)
            except Empty:
                break

        order_ids = []
        for o in orders_to_check:
            oid = o if isinstance(o, str) else o.get('order_id')
            if oid:
                order_ids.append(oid)

        fills = t.check_order_fills_batch(order_ids)

        for order_data in orders_to_check:
            order_id = order_data if isinstance(order_data, str) else order_data.get('order_id')
            if not order_id:
                continue

            with t.twap_lock:
                twap_id = t.order_to_twap_map.get(order_id)

            if not twap_id:
                continue

            fill_info = fills.get(order_id, {})

            if fill_info.get('status') == 'FILLED':
                with t.order_lock:
                    if order_id not in t.filled_orders:
                        t.filled_orders.append(order_id)

                with t.twap_lock:
                    if twap_id in t.twap_orders:
                        t.twap_orders[twap_id]['total_filled'] += fill_info['filled_size']
                        t.twap_orders[twap_id]['total_value_filled'] += fill_info['filled_value']
                        t.twap_orders[twap_id]['total_fees'] += fill_info['fees']

                        if fill_info['is_maker']:
                            t.twap_orders[twap_id]['maker_orders'] += 1
                        else:
                            t.twap_orders[twap_id]['taker_orders'] += 1

        for order_data in orders_to_check:
            order_id = order_data if isinstance(order_data, str) else order_data.get('order_id')
            if order_id and order_id not in t.filled_orders:
                t.order_queue.put(order_data)

    def _process_conditional_order(self, t, order):
        """Process a conditional order from the queue."""
        logging.debug("Processing conditional order")
        order_id = order if isinstance(order, str) else order.get('order_id')

        with t.conditional_lock:
            order_info = t.order_to_conditional_map.get(order_id)

        if not order_info:
            return

        order_type, conditional_id = order_info

        fills = t.check_order_fills_batch([order_id])
        fill_info = fills.get(order_id, {})

        if fill_info.get('status') in ['FILLED', 'CANCELLED', 'EXPIRED']:
            result = t.conditional_order_tracker.update_order_status(
                order_id=conditional_id,
                order_type=order_type,
                status=fill_info.get('status'),
                fill_info={
                    'filled_size': str(fill_info.get('filled_size', 0)),
                    'filled_value': str(fill_info.get('filled_value', 0)),
                    'fees': str(fill_info.get('fees', 0))
                }
            )

            if result:
                logging.info(f"Conditional order {order_id} updated: {fill_info.get('status')}")

                with t.conditional_lock:
                    if order_id in t.order_to_conditional_map:
                        del t.order_to_conditional_map[order_id]

                if fill_info.get('status') == 'FILLED':
                    print_success(f"\nConditional order {order_id[:8]}... FILLED!")
                    print(f"Type: {order_type}")
                    print(f"Filled: {fill_info.get('filled_size')} @ {format_currency(fill_info.get('avg_price', 0))}")
        else:
            t.order_queue.put(order_id)
