"""
Display service extracted from TradingTerminal.

Handles all display-related operations: TWAP progress, TWAP summary,
portfolio display, order history, and active order management.
"""

from typing import Optional, List, Dict
import logging
from datetime import datetime
from tabulate import tabulate
from collections import defaultdict

from ui_helpers import (
    success, error, warning, info, highlight,
    format_currency, format_percentage, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)


class DisplayService:
    """
    Handles all display and presentation operations for the trading terminal.
    """

    def __init__(self, api_client, market_data, twap_storage, conditional_tracker, config):
        """
        Args:
            api_client: APIClient instance.
            market_data: MarketDataService instance.
            twap_storage: TWAPStorage instance.
            conditional_tracker: ConditionalOrderTracker instance.
            config: AppConfig instance.
        """
        self.api_client = api_client
        self.market_data = market_data
        self.twap_storage = twap_storage
        self.conditional_tracker = conditional_tracker
        self.config = config

        # Get the underlying tracker for direct access
        if hasattr(twap_storage, '_tracker'):
            self.twap_tracker = twap_storage._tracker
        else:
            self.twap_tracker = twap_storage

    def display_twap_progress(self, twap_id: str):
        """Display current progress of TWAP order execution."""
        try:
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                logging.warning(f"TWAP order {twap_id} not found")
                return

            stats = self.twap_tracker.calculate_twap_statistics(twap_id)

            print("\nTWAP Order Progress:")
            print(f"Market: {twap_order.market}")
            print(f"Side: {twap_order.side}")
            print(f"Status: {twap_order.status}")
            print("-" * 50)

            # Order progress
            completion_pct = (twap_order.total_filled / twap_order.total_size * 100) if twap_order.total_size > 0 else 0
            print(f"Total Size: {twap_order.total_size:.8f}")
            print(f"Amount Filled: {twap_order.total_filled:.8f}")
            print(f"Completion: {completion_pct:.1f}%")

            # Value and fees
            if twap_order.total_value_filled > 0:
                print(f"\nExecution Value: ${twap_order.total_value_filled:.2f}")
                print(f"Total Fees: ${twap_order.total_fees:.2f}")
                fee_bps = (twap_order.total_fees / twap_order.total_value_filled) * 10000
                print(f"Fee Impact: {fee_bps:.1f} bps")

            # Execution quality
            if stats.get('vwap'):
                print(f"\nExecution Quality:")
                print(f"VWAP: ${stats['vwap']:.2f}")
                if 'slippage' in stats:
                    print(f"Slippage: {stats['slippage']:.2f}%")
                if 'execution_speed' in stats:
                    print(f"Execution Speed: {stats['execution_speed']:.1f}%/hour")

            # Order breakdown
            total_orders = twap_order.maker_orders + twap_order.taker_orders
            if total_orders > 0:
                maker_pct = (twap_order.maker_orders / total_orders) * 100
                print(f"\nOrder Analysis:")
                print(f"Total Orders: {total_orders}")
                print(f"Maker Orders: {twap_order.maker_orders}")
                print(f"Taker Orders: {twap_order.taker_orders}")
                print(f"Maker Ratio: {maker_pct:.1f}%")

            if twap_order.failed_slices:
                print(f"\nFailed Slices: {len(twap_order.failed_slices)}")

            print("\n" + "=" * 50)

        except Exception as e:
            logging.error(f"Error displaying TWAP progress: {str(e)}")
            print("Error displaying TWAP progress. Check logs for details.")

    def display_twap_summary(self, twap_id: str, show_orders: bool = True):
        """Display comprehensive TWAP order summary using saved data."""
        try:
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                print(f"No data found for TWAP order {twap_id}")
                return

            stats = self.twap_tracker.calculate_twap_statistics(twap_id)
            fills = self.twap_tracker.get_twap_fills(twap_id)

            print("\nTWAP Order Summary:")
            print("=" * 80)
            print(f"TWAP ID: {twap_id}")
            print(f"Market: {twap_order.market}")
            print(f"Side: {twap_order.side}")
            print(f"Status: {twap_order.status}")
            print("-" * 80)

            # Basic statistics
            completion_rate = (twap_order.total_filled / twap_order.total_size * 100) if twap_order.total_size > 0 else 0
            print("\nExecution Summary:")
            print(f"Total Size: {twap_order.total_size:.8f}")
            print(f"Amount Filled: {twap_order.total_filled:.8f}")
            print(f"Completion Rate: {completion_rate:.1f}%")

            # Value and fees
            if twap_order.total_value_filled > 0:
                print(f"\nValue Summary:")
                print(f"Total Value: ${twap_order.total_value_filled:.2f}")
                print(f"Average Price: ${stats.get('vwap', 0):.2f}")
                print(f"Total Fees: ${twap_order.total_fees:.2f}")
                fee_bps = (twap_order.total_fees / twap_order.total_value_filled) * 10000
                print(f"Fee Impact: {fee_bps:.1f} bps")

            # Execution quality metrics
            if 'slippage' in stats:
                print(f"\nExecution Quality:")
                print(f"VWAP: ${stats['vwap']:.2f}")
                print(f"Price Slippage: {stats['slippage']:.2f}%")
                if 'price_range' in stats:
                    print(f"Price Range: ${stats['price_range']:.2f}")
                if 'execution_duration' in stats:
                    duration_mins = stats['execution_duration'] / 60
                    print(f"Execution Duration: {duration_mins:.1f} minutes")
                    print(f"Execution Speed: {stats['execution_speed']:.1f}%/hour")

            # Order type breakdown
            total_orders = twap_order.maker_orders + twap_order.taker_orders
            if total_orders > 0:
                maker_pct = (twap_order.maker_orders / total_orders) * 100
                print(f"\nOrder Analysis:")
                print(f"Total Orders: {total_orders}")
                print(f"Maker Orders: {twap_order.maker_orders}")
                print(f"Taker Orders: {twap_order.taker_orders}")
                print(f"Maker Percentage: {maker_pct:.1f}%")

            # Failed slices
            if twap_order.failed_slices:
                print(f"\nExecution Issues:")
                print(f"Failed Slices: {len(twap_order.failed_slices)}")
                print(f"Failed Slice Numbers: {', '.join(map(str, twap_order.failed_slices))}")

            # Detailed fill information
            if show_orders and fills:
                print("\nDetailed Fill Information:")
                print("=" * 80)
                headers = ["Time", "Order ID", "Size", "Price", "Value", "Fee", "Type"]
                fill_data = []

                for fill in fills:
                    fill_time = datetime.fromisoformat(fill.trade_time.replace('Z', '+00:00'))
                    fill_value = fill.filled_size * fill.price
                    order_id = fill.order_id[:8] + "..."
                    fill_type = "Maker" if fill.is_maker else "Taker"

                    fill_data.append([
                        fill_time.strftime("%H:%M:%S"),
                        order_id,
                        f"{fill.filled_size:.8f}",
                        f"${fill.price:.2f}",
                        f"${fill_value:.2f}",
                        f"${fill.fee:.2f}",
                        fill_type
                    ])

                print(tabulate(fill_data, headers=headers, tablefmt="grid"))

        except Exception as e:
            logging.error(f"Error displaying TWAP summary: {str(e)}")
            print("Error displaying TWAP summary. Check logs for details.")

    def display_all_twap_orders(self):
        """Display comprehensive list of all TWAP orders with execution statistics.

        Returns:
            list: List of TWAP order IDs that were displayed, or empty list if none found
        """
        try:
            twap_ids = self.twap_tracker.list_twap_orders()
            if not twap_ids:
                print("No TWAP orders found")
                return []

            print("\nTWAP Orders:")
            print("=" * 100)

            for i, twap_id in enumerate(twap_ids, 1):
                twap_order = self.twap_tracker.get_twap_order(twap_id)
                if not twap_order:
                    continue

                stats = self.twap_tracker.calculate_twap_statistics(twap_id)

                print(f"\n{i}. TWAP ID: {twap_id}")
                print(f"   Market: {twap_order.market}")
                print(f"   Side: {twap_order.side}")
                print(f"   Status: {twap_order.status}")
                print(f"   Orders: {len(twap_order.orders)} total")

                if twap_order.failed_slices:
                    print(f"   Failed Slices: {len(twap_order.failed_slices)}")

                if stats.get('total_value_filled', 0) > 0:
                    print(f"   Total Value Filled: ${stats['total_value_filled']:.2f}")
                    print(f"   Completion Rate: {stats['completion_rate']:.1f}%")

                    maker_fills = stats.get('maker_fills', 0)
                    taker_fills = stats.get('taker_fills', 0)
                    if maker_fills + taker_fills > 0:
                        maker_pct = (maker_fills / (maker_fills + taker_fills) * 100)
                        print(f"   Maker/Taker: {maker_pct:.1f}% maker")

                    total_fees = stats.get('total_fees', 0)
                    if total_fees > 0:
                        fee_bps = (total_fees / stats['total_value_filled']) * 10000
                        print(f"   Total Fees: ${total_fees:.2f} ({fee_bps:.1f} bps)")

                    if 'vwap' in stats:
                        print(f"   VWAP: ${stats['vwap']:.2f}")

                print("-" * 100)

            return twap_ids

        except Exception as e:
            logging.error(f"Error displaying TWAP orders: {str(e)}")
            print("Error displaying TWAP orders. Please check the logs for details.")
            return []

    def display_portfolio(self, accounts_data):
        """
        Display the portfolio data with optimized price fetching.

        Uses bulk price fetching to reduce API calls from N to 1,
        where N is the number of non-stablecoin assets.
        """
        portfolio_data = []
        total_usd_value = 0

        stablecoins = {'USD', 'USDC', 'USDT', 'DAI'}

        # First pass: identify currencies needing price lookup
        currencies_needing_prices = []
        for currency, account in accounts_data.items():
            balance = float(account['available_balance']['value'])
            if balance > 0 and currency not in stablecoins:
                currencies_needing_prices.append(currency)

        # Bulk price lookup
        product_ids = [f"{currency}-USD" for currency in currencies_needing_prices]
        prices = self.market_data.get_bulk_prices(product_ids) if product_ids else {}

        # Second pass: calculate values using cached prices
        for currency, account in accounts_data.items():
            balance = float(account['available_balance']['value'])
            logging.info(f"Processing {currency} balance: {balance}")

            if balance > 0:
                if currency in stablecoins:
                    usd_value = balance
                else:
                    product_id = f"{currency}-USD"
                    usd_price = prices.get(product_id)

                    if usd_price is None:
                        logging.warning(f"No price found for {product_id}, skipping")
                        continue

                    usd_value = balance * usd_price

                if usd_value >= 1:
                    portfolio_data.append([currency, balance, usd_value])
                    total_usd_value += usd_value
                    logging.info(f"Added {currency} to portfolio: Balance={balance}, USD Value=${usd_value:.2f}")

        # Sort and display portfolio
        portfolio_data.sort(key=lambda x: x[2], reverse=True)
        table_data = [[f"{row[0]} ({row[1]:.8f})", f"${row[2]:.2f}"] for row in portfolio_data]

        logging.info(f"Portfolio summary generated. Total value: ${total_usd_value:.2f} USD")
        print_header("\nPortfolio Summary")
        print(f"Total Portfolio Value: {highlight(format_currency(total_usd_value, colored=False))}")
        print_subheader("\nAsset Balances:")
        print(tabulate(table_data, headers=["Asset (Amount)", "USD Value"], tablefmt="grid"))

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

    def view_order_history(self, get_input_fn):
        """Display order history with filters and colored output."""
        try:
            print_header("Order History")

            print("\nFilter options:")
            print("1. All orders (last 100)")
            print("2. Filter by product")
            print("3. Filter by status")
            print("4. Filter by product and status")

            filter_choice = get_input_fn("Select filter option (1-4)")

            product_id = None
            order_status = None

            if filter_choice in ['2', '4']:
                product_id = self.market_data.select_market(get_input_fn)
                if not product_id:
                    return

            if filter_choice in ['3', '4']:
                print("\nStatus filter:")
                print("1. FILLED")
                print("2. CANCELLED")
                print("3. EXPIRED")
                print("4. FAILED")
                print("5. All completed (FILLED, CANCELLED, EXPIRED)")

                status_choice = get_input_fn("Select status filter (1-5)")

                status_map = {
                    '1': ['FILLED'],
                    '2': ['CANCELLED'],
                    '3': ['EXPIRED'],
                    '4': ['FAILED'],
                    '5': ['FILLED', 'CANCELLED', 'EXPIRED']
                }
                order_status = status_map.get(status_choice, None)

            print_info("\nFetching order history...")
            orders = self.get_order_history(
                limit=100,
                product_id=product_id,
                order_status=order_status
            )

            if not orders:
                print_warning("No orders found matching the criteria.")
                return

            table_data = []
            for order in orders:
                order_config = order.order_configuration
                config_type = next(iter(vars(order_config)))
                config = getattr(order_config, config_type)

                size = getattr(config, 'base_size', 'N/A')
                price = getattr(config, 'limit_price', getattr(config, 'market_market_ioc', {}).get('quote_size', 'N/A'))

                try:
                    if size != 'N/A' and price != 'N/A':
                        value = float(size) * float(price)
                        value_str = format_currency(value, colored=True)
                    else:
                        value_str = 'N/A'
                except:
                    value_str = 'N/A'

                created_time = datetime.fromisoformat(order.created_time.replace('Z', '+00:00'))
                time_str = created_time.strftime("%Y-%m-%d %H:%M:%S")

                order_id_short = order.order_id[:12] + "..."

                table_data.append([
                    time_str,
                    order_id_short,
                    order.product_id,
                    format_side(order.side),
                    size,
                    price if price != 'N/A' else 'N/A',
                    value_str,
                    format_status(order.status)
                ])

            print_subheader(f"\nFound {len(orders)} orders:")
            print(tabulate(
                table_data,
                headers=["Time", "Order ID", "Product", "Side", "Size", "Price", "Value", "Status"],
                tablefmt="grid"
            ))

            filled_orders = [o for o in orders if o.status == 'FILLED']
            cancelled_orders = [o for o in orders if o.status == 'CANCELLED']

            print_subheader("\nSummary:")
            print(f"Total Orders: {len(orders)}")
            print(f"{format_status('FILLED')}: {len(filled_orders)}")
            print(f"{format_status('CANCELLED')}: {len(cancelled_orders)}")

        except Exception as e:
            logging.error(f"Error viewing order history: {str(e)}", exc_info=True)
            print_error(f"Error viewing order history: {str(e)}")

    def view_all_active_orders(self, get_input_fn, rate_limiter, conditional_lock,
                                order_to_conditional_map):
        """
        Unified view and cancel interface for all active orders.
        Displays orders grouped by type with color-coded status, then offers cancellation.
        """
        try:
            print_header("Active Orders & Management")

            # Get regular orders
            print_info("\nFetching regular orders...")
            all_api_orders = self.get_active_orders()

            # Filter out stop-limit orders
            regular_orders = []
            for order in all_api_orders:
                order_config = order.order_configuration
                config_type = next(iter(vars(order_config)))
                if not config_type.startswith('stop_limit_stop_limit'):
                    regular_orders.append(order)

            # Get conditional orders and sync their statuses
            print_info("Fetching conditional orders...")
            self._sync_conditional_order_statuses(rate_limiter)
            conditional_orders = self.conditional_tracker.list_all_active_orders()

            # Build numbered list for potential cancellation
            numbered_orders = []

            # Display regular orders
            if regular_orders:
                print_header("\nRegular Orders (Limit, Market)")
                table_data = []
                for order in regular_orders:
                    order_config = order.order_configuration
                    config_type = next(iter(vars(order_config)))
                    config = getattr(order_config, config_type)

                    size = getattr(config, 'base_size', 'N/A')
                    price = getattr(config, 'limit_price', 'N/A')

                    numbered_orders.append({
                        'type': 'regular',
                        'order': order,
                        'display': f"{order.product_id} {order.side} {size} @ {price}",
                        'order_id': order.order_id,
                        'status': order.status
                    })

                    table_data.append([
                        f"#{len(numbered_orders)}",
                        order.order_id[:12] + "...",
                        order.product_id,
                        format_side(order.side),
                        size,
                        price,
                        format_status(order.status)
                    ])

                print(tabulate(table_data, headers=["#", "Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))
            else:
                print_info("No active regular orders.")

            # Display conditional orders
            if conditional_orders:
                print_header("\nConditional Orders (Stop-Loss, Take-Profit, Brackets)")

                stop_limit_orders = [o for o in conditional_orders if hasattr(o, 'order_type')]
                bracket_orders = [o for o in conditional_orders if not hasattr(o, 'order_type') and not hasattr(o, 'entry_order_id')]
                attached_bracket_orders = [o for o in conditional_orders if hasattr(o, 'entry_order_id')]

                if stop_limit_orders:
                    print_info("\nStop-Loss / Take-Profit Orders:")
                    table_data = []
                    for order in stop_limit_orders:
                        numbered_orders.append({
                            'type': 'conditional',
                            'order': order,
                            'display': f"{order.order_type} - {order.product_id} {order.side} {order.base_size} (Stop: {order.stop_price})",
                            'order_id': order.order_id,
                            'conditional_type': 'stop_limit',
                            'status': order.status
                        })

                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "TRIGGERED":
                            status_display = info(order.status)
                        elif order.status == "FILLED":
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            f"#{len(numbered_orders)}",
                            order.order_id[:12] + "...",
                            order.order_type,
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.stop_price,
                            order.limit_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["#", "Order ID", "Type", "Product", "Side", "Size", "Stop Price", "Limit Price", "Status"], tablefmt="grid"))

                if bracket_orders:
                    print_info("\nBracket Orders (TP/SL on Position):")
                    table_data = []
                    for order in bracket_orders:
                        numbered_orders.append({
                            'type': 'conditional',
                            'order': order,
                            'display': f"Bracket - {order.product_id} {order.side} {order.base_size} (TP: {order.limit_price}, SL: {order.stop_trigger_price})",
                            'order_id': order.order_id,
                            'conditional_type': 'bracket',
                            'status': order.status
                        })

                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "ACTIVE":
                            status_display = info(order.status)
                        elif order.status == "FILLED":
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            f"#{len(numbered_orders)}",
                            order.order_id[:12] + "...",
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.limit_price,
                            order.stop_trigger_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["#", "Order ID", "Product", "Side", "Size", "TP Price", "SL Price", "Status"], tablefmt="grid"))

                if attached_bracket_orders:
                    print_info("\nEntry + Bracket Orders (Entry with TP/SL):")
                    table_data = []
                    for order in attached_bracket_orders:
                        numbered_orders.append({
                            'type': 'conditional',
                            'order': order,
                            'display': f"Entry+Bracket - {order.product_id} {order.side} {order.base_size} (Entry: {order.entry_limit_price})",
                            'order_id': order.entry_order_id,
                            'conditional_type': 'attached_bracket',
                            'status': order.status
                        })

                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "ENTRY_FILLED":
                            status_display = info(order.status)
                        elif order.status in ["TP_FILLED", "SL_FILLED"]:
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            f"#{len(numbered_orders)}",
                            order.entry_order_id[:12] + "...",
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.entry_limit_price,
                            order.take_profit_price,
                            order.stop_loss_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["#", "Order ID", "Product", "Side", "Size", "Entry", "TP", "SL", "Status"], tablefmt="grid"))

            else:
                print_info("No active conditional orders.")

            # Display summary
            total_orders = len(numbered_orders)
            print("\n" + "="*50)
            print_info(f"Total active orders: {total_orders}")
            print_info(f"  Regular: {len(regular_orders)}")
            print_info(f"  Conditional: {len(conditional_orders)}")
            print("="*50)

            # Offer to cancel orders
            if total_orders > 0:
                print()
                cancel_choice = get_input_fn("Would you like to cancel any orders? (yes/no)").lower()

                if cancel_choice in ['yes', 'y']:
                    selection = get_input_fn("Enter order numbers to cancel (comma-separated, or 'all')")

                    if selection.lower() == 'all':
                        orders_to_cancel = numbered_orders
                    else:
                        try:
                            indices = [int(x.strip()) - 1 for x in selection.split(',')]
                            orders_to_cancel = [numbered_orders[i] for i in indices if 0 <= i < len(numbered_orders)]
                        except (ValueError, IndexError):
                            print_error("Invalid selection.")
                            return

                    if not orders_to_cancel:
                        print_info("No orders selected.")
                        return

                    print_warning(f"\nYou are about to cancel {len(orders_to_cancel)} order(s):")
                    for order_info in orders_to_cancel:
                        print(f"  - {order_info['display']}")

                    confirm = get_input_fn("\nConfirm cancellation? (yes/no)")
                    if confirm.lower() not in ['yes', 'y']:
                        print_info("Cancellation aborted.")
                        return

                    cancelled_count = 0
                    failed_count = 0

                    for order_info in orders_to_cancel:
                        try:
                            order_id = order_info['order_id']

                            rate_limiter.wait()
                            response = self.api_client.cancel_orders([order_id])

                            cancel_success = False
                            if hasattr(response, 'results') and response.results:
                                result = response.results[0]
                                cancel_success = getattr(result, 'success', False)

                            if cancel_success:
                                if order_info['type'] == 'conditional':
                                    self.conditional_tracker.update_order_status(
                                        order_id=order_id,
                                        order_type=order_info['conditional_type'],
                                        status="CANCELLED",
                                        fill_info=None
                                    )
                                    with conditional_lock:
                                        if order_id in order_to_conditional_map:
                                            del order_to_conditional_map[order_id]

                                print_success(f"Cancelled: {order_id[:12]}...")
                                cancelled_count += 1
                            else:
                                error_msg = getattr(result, 'failure_reason', 'Unknown error') if hasattr(response, 'results') else "Unknown error"
                                print_error(f"Failed to cancel {order_id[:12]}...: {error_msg}")
                                failed_count += 1

                        except Exception as e:
                            logging.error(f"Error cancelling order {order_id}: {str(e)}")
                            print_error(f"Error cancelling {order_id[:12]}...: {str(e)}")
                            failed_count += 1

                    print("\n" + "="*50)
                    print_success(f"Successfully cancelled: {cancelled_count}")
                    if failed_count > 0:
                        print_error(f"Failed to cancel: {failed_count}")
                    print("="*50)

        except Exception as e:
            logging.error(f"Error in view_all_active_orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def _sync_conditional_order_statuses(self, rate_limiter):
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
