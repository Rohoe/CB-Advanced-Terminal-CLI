"""
Conditional order executor extracted from TradingTerminal.

Handles stop-loss, take-profit, bracket, and entry+bracket orders.
"""

from typing import Optional
import logging
import uuid
from datetime import datetime
from threading import Lock

from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder
from ui_helpers import (
    format_currency, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info, success, error, warning, info
)


class ConditionalExecutor:
    """
    Handles placement and management of conditional orders:
    stop-loss, take-profit, bracket, and entry+bracket.
    """

    def __init__(self, api_client, market_data, order_executor,
                 conditional_tracker, order_queue, config):
        self.api_client = api_client
        self.market_data = market_data
        self.order_executor = order_executor
        self.conditional_tracker = conditional_tracker
        self.order_queue = order_queue
        self.config = config
        self.order_to_conditional_map = {}
        self.conditional_lock = Lock()

    def get_conditional_order_input(self, get_input_fn):
        """Get order input without limit price (for conditional orders)."""
        from order_executor import CancelledException
        try:
            product_id = self.market_data.select_market(get_input_fn)
            if not product_id:
                return None

            while True:
                side = get_input_fn("\nEnter order side (buy/sell)").upper()
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            current_prices = self.market_data.get_current_prices(product_id)
            if current_prices:
                self.market_data.display_market_conditions(product_id, side, current_prices)

            while True:
                try:
                    base_size = float(get_input_fn("\nEnter order size"))
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            product_info = self.api_client.get_product(product_id)
            min_size = float(product_info['base_min_size'])
            if base_size < min_size:
                print(f"Error: Order size must be at least {min_size}")
                return None

            return {
                "product_id": product_id,
                "side": side,
                "base_size": base_size
            }

        except CancelledException:
            raise
        except Exception as e:
            logging.error(f"Error getting conditional order input: {str(e)}", exc_info=True)
            print(f"Error getting conditional order input: {str(e)}")
            return None

    def place_stop_loss_order(self, get_input_fn):
        """Place a stop-loss order using native Coinbase SDK."""
        try:
            print_header("Place Stop-Loss Order")
            print_info("This creates a NEW stop-loss order.")

            order_input = self.get_conditional_order_input(get_input_fn)
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])

            current_prices = self.market_data.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']

            stop_price = float(get_input_fn(f"\nEnter stop price (trigger level)"))
            limit_price = float(get_input_fn("Enter limit price (execute after trigger)"))

            # Auto-determine direction
            if side == "SELL":
                if stop_price < current_price:
                    stop_direction = "STOP_DIRECTION_STOP_DOWN"
                    order_type_display = "STOP_LOSS"
                else:
                    stop_direction = "STOP_DIRECTION_STOP_UP"
                    order_type_display = "TAKE_PROFIT"
            else:
                if stop_price > current_price:
                    stop_direction = "STOP_DIRECTION_STOP_UP"
                    order_type_display = "STOP_LOSS"
                else:
                    stop_direction = "STOP_DIRECTION_STOP_DOWN"
                    order_type_display = "TAKE_PROFIT"

            # Confirm
            print(f"\nType: {order_type_display} | {product_id} {format_side(side)} {base_size}")
            print(f"Stop: {format_currency(stop_price)} | Limit: {format_currency(limit_price)}")

            confirm = get_input_fn("Confirm order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Order cancelled.")
                return None

            rounded_stop = self.market_data.round_price(stop_price, product_id)
            rounded_limit = self.market_data.round_price(limit_price, product_id)
            rounded_size = self.market_data.round_size(float(base_size), product_id)

            client_order_id = f"sl-{str(uuid.uuid4())[:8]}"
            self.market_data.rate_limiter.wait()

            if side == "SELL":
                response = self.api_client.stop_limit_order_gtc_sell(
                    client_order_id=client_order_id, product_id=product_id,
                    base_size=str(rounded_size), limit_price=str(rounded_limit),
                    stop_price=str(rounded_stop), stop_direction=stop_direction
                )
            else:
                response = self.api_client.stop_limit_order_gtc_buy(
                    client_order_id=client_order_id, product_id=product_id,
                    base_size=str(rounded_size), limit_price=str(rounded_limit),
                    stop_price=str(rounded_stop), stop_direction=stop_direction
                )

            if hasattr(response, 'success') and not response.success:
                error_msg = "Unknown error"
                if hasattr(response, 'error_response') and response.error_response:
                    error_msg = response.error_response.get('message', 'Unknown error')
                print_error(f"Failed: {error_msg}")
                return None

            order_id = None
            if hasattr(response, 'success_response') and response.success_response:
                sr = response.success_response
                order_id = sr.get('order_id') if isinstance(sr, dict) else getattr(sr, 'order_id', None)

            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            stop_order = StopLimitOrder(
                order_id=order_id, client_order_id=client_order_id,
                product_id=product_id, side=side, base_size=str(rounded_size),
                stop_price=str(rounded_stop), limit_price=str(rounded_limit),
                stop_direction=stop_direction, order_type=order_type_display,
                status="PENDING", created_at=datetime.utcnow().isoformat() + "Z"
            )
            self.conditional_tracker.save_stop_limit_order(stop_order)

            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("stop_limit", order_id)
                self.order_queue.put(order_id)

            print_success(f"\n{order_type_display} order placed! ID: {order_id}")
            return order_id

        except Exception as e:
            logging.error(f"Error placing stop-loss order: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")
            return None

    def place_take_profit_order(self, get_input_fn):
        """Place a take-profit order."""
        try:
            print_header("Place Take-Profit Order")
            order_input = self.get_conditional_order_input(get_input_fn)
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])

            current_prices = self.market_data.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']
            stop_price = float(get_input_fn(f"\nEnter take-profit price (trigger level)"))
            limit_price = float(get_input_fn("Enter limit price (execute after trigger)"))

            if side == "SELL":
                stop_direction = "STOP_DIRECTION_STOP_UP"
            else:
                stop_direction = "STOP_DIRECTION_STOP_DOWN"

            confirm = get_input_fn("Confirm order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                return None

            rounded_stop = self.market_data.round_price(stop_price, product_id)
            rounded_limit = self.market_data.round_price(limit_price, product_id)
            rounded_size = self.market_data.round_size(float(base_size), product_id)

            client_order_id = f"tp-{str(uuid.uuid4())[:8]}"
            self.market_data.rate_limiter.wait()

            if side == "SELL":
                response = self.api_client.stop_limit_order_gtc_sell(
                    client_order_id=client_order_id, product_id=product_id,
                    base_size=str(rounded_size), limit_price=str(rounded_limit),
                    stop_price=str(rounded_stop), stop_direction=stop_direction
                )
            else:
                response = self.api_client.stop_limit_order_gtc_buy(
                    client_order_id=client_order_id, product_id=product_id,
                    base_size=str(rounded_size), limit_price=str(rounded_limit),
                    stop_price=str(rounded_stop), stop_direction=stop_direction
                )

            order_id = None
            if hasattr(response, 'success_response') and response.success_response:
                sr = response.success_response
                order_id = sr.get('order_id') if isinstance(sr, dict) else getattr(sr, 'order_id', None)

            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            tp_order = StopLimitOrder(
                order_id=order_id, client_order_id=client_order_id,
                product_id=product_id, side=side, base_size=str(rounded_size),
                stop_price=str(rounded_stop), limit_price=str(rounded_limit),
                stop_direction=stop_direction, order_type="TAKE_PROFIT",
                status="PENDING", created_at=datetime.utcnow().isoformat() + "Z"
            )
            self.conditional_tracker.save_stop_limit_order(tp_order)

            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("stop_limit", order_id)
                self.order_queue.put(order_id)

            print_success(f"\nTAKE_PROFIT order placed! ID: {order_id}")
            return order_id

        except Exception as e:
            logging.error(f"Error placing take-profit order: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")
            return None

    def place_bracket_for_position(self, get_input_fn):
        """Place a bracket order (TP/SL) on an existing position."""
        try:
            print_header("Place Bracket Order (TP/SL on Existing Position)")

            product_id = get_input_fn("Enter product (e.g., BTC-USD)")
            side = get_input_fn("Enter position side to exit (BUY or SELL)").upper()
            if side not in ["BUY", "SELL"]:
                print_error("Side must be BUY or SELL")
                return None

            base_size = get_input_fn(f"Enter position size to protect")

            current_prices = self.market_data.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch prices.")
                return None

            current_price = current_prices['mid']
            self.market_data.display_market_conditions(product_id, side, current_prices)

            tp_price = float(get_input_fn("\nEnter take-profit price"))
            sl_price = float(get_input_fn("Enter stop-loss price"))

            # Validate
            if side == "SELL":
                if sl_price >= tp_price:
                    print_error("Stop-loss must be below take-profit.")
                    return None
            else:
                if sl_price <= tp_price:
                    print_error("Stop-loss must be above take-profit for SHORT.")
                    return None

            confirm = get_input_fn("Confirm bracket order? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                return None

            rounded_tp = self.market_data.round_price(tp_price, product_id)
            rounded_sl = self.market_data.round_price(sl_price, product_id)
            rounded_size = self.market_data.round_size(float(base_size), product_id)

            client_order_id = f"bracket-{str(uuid.uuid4())[:8]}"
            self.market_data.rate_limiter.wait()

            response = self.api_client.trigger_bracket_order_gtc(
                client_order_id=client_order_id, product_id=product_id,
                side=side, base_size=str(rounded_size),
                limit_price=str(rounded_tp), stop_trigger_price=str(rounded_sl)
            )

            order_id = None
            if hasattr(response, 'success_response') and response.success_response:
                sr = response.success_response
                order_id = sr.get('order_id') if isinstance(sr, dict) else getattr(sr, 'order_id', None)

            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            bracket_order = BracketOrder(
                order_id=order_id, client_order_id=client_order_id,
                product_id=product_id, side=side, base_size=str(rounded_size),
                limit_price=str(rounded_tp), stop_trigger_price=str(rounded_sl),
                status="ACTIVE", created_at=datetime.utcnow().isoformat() + "Z"
            )
            self.conditional_tracker.save_bracket_order(bracket_order)

            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("bracket", order_id)
                self.order_queue.put(order_id)

            print_success(f"\nBracket order placed! ID: {order_id}")
            return order_id

        except Exception as e:
            logging.error(f"Error placing bracket order: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")
            return None

    def place_entry_with_bracket(self, get_input_fn):
        """Place an entry order with attached TP/SL bracket."""
        try:
            print_header("Place Entry Order with TP/SL Bracket")

            order_input = self.order_executor.get_order_input(get_input_fn)
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])
            entry_price = float(order_input["limit_price"])

            tp_price = float(get_input_fn("\nEnter take-profit price"))
            sl_price = float(get_input_fn("Enter stop-loss price"))

            # Validate
            if side == "BUY":
                if sl_price >= tp_price:
                    print_error("Stop-loss must be below take-profit.")
                    return None
            else:
                if sl_price <= tp_price:
                    print_error("Stop-loss must be above take-profit for SELL.")
                    return None

            confirm = get_input_fn("Confirm entry + bracket? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                return None

            rounded_entry = self.market_data.round_price(entry_price, product_id)
            rounded_tp = self.market_data.round_price(tp_price, product_id)
            rounded_sl = self.market_data.round_price(sl_price, product_id)
            rounded_size = self.market_data.round_size(float(base_size), product_id)

            order_configuration = {
                "limit_limit_gtc": {
                    "baseSize": str(rounded_size),
                    "limitPrice": str(rounded_entry)
                }
            }
            attached_order_configuration = {
                "trigger_bracket_gtc": {
                    "limit_price": str(rounded_tp),
                    "stop_trigger_price": str(rounded_sl)
                }
            }

            client_order_id = f"entry-bracket-{str(uuid.uuid4())[:8]}"
            self.market_data.rate_limiter.wait()

            response = self.api_client.create_order(
                client_order_id=client_order_id, product_id=product_id,
                side=side, order_configuration=order_configuration,
                attached_order_configuration=attached_order_configuration
            )

            order_id = None
            if hasattr(response, 'success_response') and response.success_response:
                sr = response.success_response
                order_id = sr.get('order_id') if isinstance(sr, dict) else getattr(sr, 'order_id', None)

            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            attached_bracket = AttachedBracketOrder(
                entry_order_id=order_id, client_order_id=client_order_id,
                product_id=product_id, side=side, base_size=str(rounded_size),
                entry_limit_price=str(rounded_entry),
                take_profit_price=str(rounded_tp), stop_loss_price=str(rounded_sl),
                status="PENDING", created_at=datetime.utcnow().isoformat() + "Z"
            )
            self.conditional_tracker.save_attached_bracket_order(attached_bracket)

            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("attached_bracket", order_id)
                self.order_queue.put(order_id)

            print_success(f"\nEntry+Bracket order placed! ID: {order_id}")
            return order_id

        except Exception as e:
            logging.error(f"Error placing entry+bracket: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")
            return None

    def view_conditional_orders(self):
        """Display all conditional orders."""
        from tabulate import tabulate
        try:
            print_header("Conditional Orders")
            stop_limit_orders = self.conditional_tracker.list_stop_limit_orders()
            bracket_orders = self.conditional_tracker.list_bracket_orders()
            attached_bracket_orders = self.conditional_tracker.list_attached_bracket_orders()

            if not stop_limit_orders and not bracket_orders and not attached_bracket_orders:
                print_info("No conditional orders found.")
                return

            if stop_limit_orders:
                print_subheader(f"Stop-Limit Orders ({len(stop_limit_orders)})")
                table_data = []
                for order in stop_limit_orders:
                    table_data.append([
                        order.order_id[:12] + "...", order.order_type,
                        order.product_id, format_side(order.side),
                        order.base_size, format_currency(float(order.stop_price)),
                        format_currency(float(order.limit_price)),
                        order.status, order.created_at[:19]
                    ])
                print(tabulate(table_data, headers=["ID", "Type", "Product", "Side", "Size", "Stop", "Limit", "Status", "Created"], tablefmt="grid"))

            if bracket_orders:
                print_subheader(f"Bracket Orders ({len(bracket_orders)})")
                table_data = []
                for order in bracket_orders:
                    table_data.append([
                        order.order_id[:12] + "...", order.product_id,
                        format_side(order.side), order.base_size,
                        format_currency(float(order.limit_price)),
                        format_currency(float(order.stop_trigger_price)),
                        order.status, order.created_at[:19]
                    ])
                print(tabulate(table_data, headers=["ID", "Product", "Side", "Size", "TP", "SL", "Status", "Created"], tablefmt="grid"))

            if attached_bracket_orders:
                print_subheader(f"Entry + Bracket Orders ({len(attached_bracket_orders)})")
                table_data = []
                for order in attached_bracket_orders:
                    table_data.append([
                        order.entry_order_id[:12] + "...", order.product_id,
                        format_side(order.side), order.base_size,
                        order.entry_limit_price, order.take_profit_price,
                        order.stop_loss_price, order.status, order.created_at[:19]
                    ])
                print(tabulate(table_data, headers=["ID", "Product", "Side", "Size", "Entry", "TP", "SL", "Status", "Created"], tablefmt="grid"))

            stats = self.conditional_tracker.get_statistics()
            print_header("Summary")
            print(f"Stop-Limit: {stats['stop_limit']['total']} | Bracket: {stats['bracket']['total']} | Entry+Bracket: {stats['attached_bracket']['total']}")

        except Exception as e:
            logging.error(f"Error viewing conditional orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def cancel_conditional_orders(self, get_input_fn):
        """Cancel pending/active conditional orders."""
        try:
            print_header("Cancel Conditional Orders")
            active_orders = self.conditional_tracker.list_all_active_orders()
            if not active_orders:
                print_info("No active conditional orders.")
                return

            for i, order in enumerate(active_orders, 1):
                if hasattr(order, 'order_type'):
                    print(f"{i}. {order.order_type} - {order.product_id} {order.side} | ID: {order.order_id[:12]}...")
                elif hasattr(order, 'entry_order_id'):
                    print(f"{i}. Entry+Bracket - {order.product_id} {order.side} | ID: {order.entry_order_id[:12]}...")
                else:
                    print(f"{i}. Bracket - {order.product_id} {order.side} | ID: {order.order_id[:12]}...")

            selection = get_input_fn("Enter order numbers to cancel (comma-separated, or 'all')")
            if selection.lower() == 'all':
                orders_to_cancel = active_orders
            else:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                orders_to_cancel = [active_orders[i] for i in indices if 0 <= i < len(active_orders)]

            if not orders_to_cancel:
                return

            cancelled = 0
            for order in orders_to_cancel:
                order_id = getattr(order, 'entry_order_id', None) or order.order_id
                order_type = "attached_bracket" if hasattr(order, 'entry_order_id') else \
                             "stop_limit" if hasattr(order, 'order_type') else "bracket"
                try:
                    self.market_data.rate_limiter.wait()
                    response = self.api_client.cancel_orders([order_id])
                    if hasattr(response, 'results') and response.results:
                        self.conditional_tracker.update_order_status(
                            order_id=order_id, order_type=order_type,
                            status="CANCELLED", fill_info=None
                        )
                        with self.conditional_lock:
                            self.order_to_conditional_map.pop(order_id, None)
                        cancelled += 1
                except Exception as e:
                    logging.error(f"Error cancelling {order_id}: {str(e)}")

            print_success(f"Cancelled {cancelled} order(s).")

        except Exception as e:
            logging.error(f"Error in cancel_conditional_orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def sync_conditional_order_statuses(self):
        """Sync tracked conditional orders with actual API statuses."""
        try:
            self.market_data.rate_limiter.wait()
            all_api_orders = self.api_client.list_orders()
            api_statuses = {}
            if hasattr(all_api_orders, 'orders'):
                for order in all_api_orders.orders:
                    api_statuses[order.order_id] = order.status

            for order in self.conditional_tracker.list_stop_limit_orders():
                if order.is_completed():
                    continue
                api_status = api_statuses.get(order.order_id)
                if api_status in ['CANCELLED', 'EXPIRED', 'FAILED', 'FILLED']:
                    self.conditional_tracker.update_order_status(
                        order_id=order.order_id, order_type="stop_limit",
                        status=api_status, fill_info=None
                    )
                elif order.order_id not in api_statuses:
                    self.conditional_tracker.update_order_status(
                        order_id=order.order_id, order_type="stop_limit",
                        status="CANCELLED", fill_info=None
                    )
        except Exception as e:
            logging.error(f"Error syncing conditional statuses: {str(e)}", exc_info=True)
