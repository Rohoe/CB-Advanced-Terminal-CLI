"""
Scaled/Ladder order executor.

Handles user interaction, order placement, and display for scaled orders.
"""

import logging
import time
import uuid
from typing import Optional, Callable
from datetime import datetime
from tabulate import tabulate

from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType
from scaled_strategy import ScaledStrategy
from scaled_order_tracker import ScaledOrderTracker
from order_executor import CancelledException
from validators import InputValidator, ValidationError
from ui_helpers import (
    info, highlight, format_currency, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)


class ScaledExecutor:
    """
    Executes scaled/ladder orders by placing multiple limit orders
    across a price range.
    """

    def __init__(self, order_executor, market_data, order_queue, config):
        """
        Args:
            order_executor: OrderExecutor instance.
            market_data: MarketDataService instance.
            order_queue: Queue for background order monitoring.
            config: AppConfig instance.
        """
        self.order_executor = order_executor
        self.market_data = market_data
        self.order_queue = order_queue
        self.config = config
        self.scaled_tracker = ScaledOrderTracker()

    def place_scaled_order(self, get_input_fn: Callable) -> Optional[str]:
        """
        Interactive scaled order placement.

        Args:
            get_input_fn: Function to get user input.

        Returns:
            Scaled order ID if successful, None otherwise.
        """
        try:
            # Select market
            product_id = self.market_data.select_market(get_input_fn)
            if not product_id:
                return None

            # Get side
            while True:
                side = get_input_fn("\nEnter order side (buy/sell)").upper()
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            # Display market conditions
            current_prices = self.market_data.get_current_prices(product_id)
            if current_prices:
                self.market_data.display_market_conditions(product_id, side, current_prices)

            # Get price range
            while True:
                try:
                    price_low = float(get_input_fn("\nEnter low price"))
                    InputValidator.validate_price(price_low)
                    break
                except (ValueError, ValidationError) as e:
                    print(f"Invalid price: {e}")

            while True:
                try:
                    price_high = float(get_input_fn("Enter high price"))
                    InputValidator.validate_price(price_high)
                    if price_high <= price_low:
                        print("High price must be greater than low price.")
                        continue
                    break
                except (ValueError, ValidationError) as e:
                    print(f"Invalid price: {e}")

            # Get total size
            while True:
                try:
                    total_size = float(get_input_fn("\nEnter total order size"))
                    if total_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get number of orders
            try:
                product_info = self.market_data.api_client.get_product(product_id)
                if isinstance(product_info, dict):
                    min_size = float(product_info.get('base_min_size', '0.0001'))
                else:
                    min_size = float(getattr(product_info, 'base_min_size', '0.0001'))
            except Exception:
                min_size = 0.0001

            while True:
                try:
                    num_orders = int(get_input_fn(f"\nEnter number of orders (2-100)"))
                    if num_orders < 1:
                        print("Must have at least 1 order.")
                        continue
                    if num_orders > 100:
                        print("Maximum 100 orders.")
                        continue
                    # Check each order meets minimum size
                    min_per_order = total_size / num_orders
                    if min_per_order < min_size:
                        max_orders = int(total_size / min_size)
                        print(f"Each order would be {min_per_order:.8f}, below minimum {min_size}. Max orders: {max_orders}")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get distribution type
            print("\nSelect size distribution:")
            print("1. Linear (equal sizes)")
            print("2. Geometric (more at favorable prices)")
            print("3. Front-weighted (more near market price)")

            while True:
                dist_choice = get_input_fn("Enter your choice (1-3)")
                if dist_choice == '1':
                    distribution = DistributionType.LINEAR
                    break
                elif dist_choice == '2':
                    distribution = DistributionType.GEOMETRIC
                    break
                elif dist_choice == '3':
                    distribution = DistributionType.FRONT_WEIGHTED
                    break
                else:
                    print("Invalid choice. Enter 1, 2, or 3.")

            # Calculate strategy
            strategy = ScaledStrategy(
                product_id=product_id,
                side=side,
                total_size=total_size,
                price_low=price_low,
                price_high=price_high,
                num_orders=num_orders,
                distribution=distribution
            )
            slices = strategy.calculate_slices()

            # Round prices and sizes
            for s in slices:
                s.price = self.market_data.round_price(s.price, product_id)
                s.size = self.market_data.round_size(s.size, product_id)

            # Display preview
            self._display_preview(product_id, side, slices, distribution, total_size)

            # Get fee estimates
            maker_rate, taker_rate = self.order_executor.get_fee_rates()
            total_value = sum(s.price * s.size for s in slices)
            est_fee_maker = total_value * maker_rate
            est_fee_taker = total_value * taker_rate

            print(f"\nTotal Order Value: {format_currency(total_value, colored=False)}")
            print(f"Estimated Fee (maker {maker_rate:.2%}): {format_currency(est_fee_maker, colored=False)}")
            print(f"Estimated Fee (taker {taker_rate:.2%}): {format_currency(est_fee_taker, colored=False)}")

            # Confirm
            confirm = get_input_fn("\nPlace this scaled order? (yes/no)").lower()
            if confirm != 'yes':
                print("Scaled order cancelled.")
                return None

            # Execute
            scaled_id = str(uuid.uuid4())
            scaled_order = ScaledOrder(
                scaled_id=scaled_id,
                product_id=product_id,
                side=side,
                total_size=total_size,
                price_low=price_low,
                price_high=price_high,
                num_orders=num_orders,
                distribution=distribution,
                status='active'
            )

            # Place each order
            for s in slices:
                level = ScaledOrderLevel(
                    level_number=s.slice_number,
                    price=s.price,
                    size=s.size
                )

                try:
                    result = self.order_executor.place_limit_order_with_retry(
                        product_id=product_id,
                        side=side,
                        base_size=str(s.size),
                        limit_price=str(s.price),
                        client_order_id=f"scaled-{scaled_id[:8]}-{s.slice_number}"
                    )

                    if result:
                        # Extract order_id
                        if 'success_response' in result:
                            order_id = result['success_response']['order_id']
                        elif 'order_id' in result:
                            order_id = result['order_id']
                        else:
                            order_id = None

                        if order_id:
                            level.order_id = order_id
                            level.status = 'placed'
                            level.placed_at = datetime.now().isoformat()
                            print_success(f"  Level {s.slice_number}: {s.size} @ {format_currency(s.price, colored=False)} - Order {order_id[:8]}...")
                        else:
                            level.status = 'failed'
                            print_error(f"  Level {s.slice_number}: Failed - no order ID in response")
                    else:
                        level.status = 'failed'
                        print_error(f"  Level {s.slice_number}: Failed to place order")

                except Exception as e:
                    level.status = 'failed'
                    logging.error(f"Error placing scaled order level {s.slice_number}: {str(e)}")
                    print_error(f"  Level {s.slice_number}: Error - {str(e)}")

                scaled_order.levels.append(level)

                # Save after each level for crash recovery
                self.scaled_tracker.save_scaled_order(scaled_order)

            # Update final status
            placed = sum(1 for l in scaled_order.levels if l.status == 'placed')
            if placed == 0:
                scaled_order.status = 'failed'
            elif placed < num_orders:
                scaled_order.status = 'partial'
            else:
                scaled_order.status = 'active'

            scaled_order.completed_at = datetime.now().isoformat()
            self.scaled_tracker.save_scaled_order(scaled_order)

            print_success(f"\nScaled order {scaled_id[:8]}... placed: {placed}/{num_orders} orders")
            return scaled_id

        except CancelledException:
            raise
        except Exception as e:
            logging.error(f"Error placing scaled order: {str(e)}", exc_info=True)
            print_error(f"Error placing scaled order: {str(e)}")
            return None

    def _display_preview(self, product_id, side, slices, distribution, total_size):
        """Display a preview table of the scaled order."""
        print_header(f"\nScaled Order Preview - {product_id}")
        print(f"Side: {format_side(side)} | Distribution: {distribution.value}")
        print(f"Total Size: {highlight(str(total_size))}")

        headers = ['#', 'Price', 'Size', '% of Total', 'Value']
        rows = []
        for s in slices:
            pct = (s.size / total_size * 100) if total_size > 0 else 0
            value = s.price * s.size
            rows.append([
                s.slice_number,
                format_currency(s.price, colored=False),
                f"{s.size:.8f}",
                f"{pct:.1f}%",
                format_currency(value, colored=False)
            ])

        print(tabulate(rows, headers=headers, tablefmt='simple'))

    def display_scaled_summary(self, scaled_id: str) -> None:
        """Display fill status for a scaled order."""
        order = self.scaled_tracker.get_scaled_order(scaled_id)
        if not order:
            print_warning(f"Scaled order {scaled_id} not found.")
            return

        print_header(f"\nScaled Order Summary - {scaled_id[:8]}...")
        print(f"Market: {info(order.product_id)} | Side: {format_side(order.side)}")
        print(f"Distribution: {order.distribution.value}")
        print(f"Status: {format_status(order.status)}")
        print(f"Created: {order.created_at}")

        headers = ['#', 'Price', 'Size', 'Filled', 'Status', 'Order ID']
        rows = []
        for level in order.levels:
            rows.append([
                level.level_number,
                format_currency(level.price, colored=False),
                f"{level.size:.8f}",
                f"{level.filled_size:.8f}",
                format_status(level.status),
                (level.order_id[:8] + '...') if level.order_id else '-'
            ])

        print(tabulate(rows, headers=headers, tablefmt='simple'))

        print_subheader("\nTotals")
        print(f"Total Filled: {order.total_filled:.8f} / {order.total_size:.8f} ({order.fill_rate:.1f}%)")
        if order.total_filled > 0:
            print(f"Average Price: {format_currency(order.average_price, colored=False)}")
            print(f"Total Value: {format_currency(order.total_value_filled, colored=False)}")
            print(f"Total Fees: {format_currency(order.total_fees, colored=False)}")
        print(f"Orders: {order.num_placed} placed, {order.num_filled} filled, {order.num_failed} failed")

    def display_all_scaled_orders(self) -> Optional[list]:
        """Display all scaled orders and return list of IDs."""
        orders = self.scaled_tracker.list_scaled_orders()
        if not orders:
            print_info("No scaled orders found.")
            return None

        print_header("\nAll Scaled Orders")
        headers = ['#', 'ID', 'Market', 'Side', 'Size', 'Range', 'Levels', 'Filled', 'Status']
        rows = []
        scaled_ids = []

        for i, order in enumerate(orders):
            scaled_ids.append(order.scaled_id)
            rows.append([
                i + 1,
                order.scaled_id[:8] + '...',
                order.product_id,
                order.side,
                f"{order.total_size:.8f}",
                f"{format_currency(order.price_low, colored=False)} - {format_currency(order.price_high, colored=False)}",
                f"{order.num_filled}/{order.num_orders}",
                f"{order.fill_rate:.1f}%",
                format_status(order.status)
            ])

        print(tabulate(rows, headers=headers, tablefmt='simple'))
        return scaled_ids
