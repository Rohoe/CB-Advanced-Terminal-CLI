"""
TWAP executor extracted from TradingTerminal.

Handles TWAP order execution: slice timing, price selection, and progress tracking.
Supports both legacy execute_twap() and strategy-based execute_strategy() flows.
"""

from typing import Optional
import logging
import time
import uuid
from datetime import datetime

from twap_tracker import TWAPOrder
from order_strategy import OrderStrategy, StrategyResult, StrategyStatus
from ui_helpers import print_info, print_warning, print_success, highlight


class TWAPExecutor:
    """
    Executes TWAP (Time-Weighted Average Price) orders by splitting
    a large order into smaller slices over a specified duration.
    """

    def __init__(self, order_executor, market_data, twap_storage, order_queue, config):
        """
        Args:
            order_executor: OrderExecutor instance.
            market_data: MarketDataService instance.
            twap_storage: TWAPStorage instance.
            order_queue: Queue for background order monitoring.
            config: AppConfig instance.
        """
        self.order_executor = order_executor
        self.market_data = market_data
        self.twap_storage = twap_storage
        self.order_queue = order_queue
        self.config = config

        # Get the underlying tracker for direct access
        if hasattr(twap_storage, '_tracker'):
            self.twap_tracker = twap_storage._tracker
        else:
            self.twap_tracker = twap_storage

    def execute_twap(self, order_input, duration, num_slices, price_type,
                     get_input_fn=None, register_fn=None):
        """
        Execute a TWAP order.

        Args:
            order_input: Dict with product_id, side, base_size, limit_price.
            duration: Duration in minutes.
            num_slices: Number of slices.
            price_type: Price type selection ('1'-'4').
            get_input_fn: Optional input function.
            register_fn: Optional callback to register orders for monitoring.

        Returns:
            twap_id on success, None on failure.
        """
        product_id = order_input["product_id"]
        base_currency = product_id.split('-')[0]
        quote_currency = product_id.split('-')[1]

        twap_id = str(uuid.uuid4())
        twap_order = TWAPOrder(
            twap_id=twap_id,
            market=product_id,
            side=order_input["side"],
            total_size=float(order_input["base_size"]),
            limit_price=float(order_input["limit_price"]),
            num_slices=num_slices,
            start_time=datetime.now().isoformat(),
            status="active",
            orders=[],
            failed_slices=[],
            slice_statuses=[]
        )

        self.twap_tracker.save_twap_order(twap_order)

        slice_size = float(order_input["base_size"]) / num_slices
        slice_interval = (duration * 60) / num_slices
        next_slice_time = time.time()

        logging.info(f"Starting TWAP {twap_id}: {num_slices} slices over {duration}min")

        try:
            for i in range(num_slices):
                slice_start_time = time.time()
                slice_info = {
                    'slice_number': i + 1,
                    'start_time': slice_start_time,
                    'status': 'pending'
                }

                current_time = time.time()
                if current_time < next_slice_time:
                    sleep_time = next_slice_time - current_time
                    if sleep_time > 0:
                        logging.info(f"Waiting {sleep_time:.2f}s until next slice...")
                        print(f"Waiting {sleep_time:.2f} seconds until next slice...")
                        time.sleep(sleep_time)

                next_slice_time = time.time() + slice_interval

                # Check balance for sell orders
                if order_input["side"] == "SELL":
                    available = self.market_data.get_account_balance(base_currency)
                    if available < slice_size:
                        msg = f"Insufficient {base_currency} balance for slice {i+1}"
                        logging.error(msg)
                        print(msg)
                        slice_info['status'] = 'balance_insufficient'
                        twap_order.failed_slices.append(i + 1)
                        continue

                # Get current prices
                current_prices = self.market_data.get_current_prices(product_id)
                if not current_prices:
                    logging.error(f"Failed to get prices for slice {i+1}")
                    slice_info['status'] = 'price_fetch_failed'
                    twap_order.failed_slices.append(i + 1)
                    continue

                # Determine execution price
                if price_type == '1':
                    execution_price = float(order_input["limit_price"])
                elif price_type == '2':
                    execution_price = current_prices['bid']
                elif price_type == '3':
                    execution_price = current_prices['mid']
                else:
                    execution_price = current_prices['ask']

                slice_info['execution_price'] = execution_price
                slice_info['market_prices'] = current_prices

                # Price favorability check
                if order_input["side"] == "BUY":
                    price_favorable = execution_price <= float(order_input["limit_price"])
                else:
                    price_favorable = execution_price >= float(order_input["limit_price"])

                if not price_favorable:
                    msg = f"Skipping slice {i+1}/{num_slices}: unfavorable price ${execution_price:.2f}"
                    logging.warning(msg)
                    print(msg)
                    slice_info['status'] = 'price_unfavorable'
                    twap_order.failed_slices.append(i + 1)
                    continue

                # Place the slice
                try:
                    order_id = self.order_executor.place_twap_slice(
                        twap_id, i + 1, num_slices, order_input,
                        execution_price, self.twap_tracker
                    )

                    if order_id:
                        twap_order.orders.append(order_id)
                        slice_info['status'] = 'placed'
                        slice_info['order_id'] = order_id

                        # Register for monitoring
                        if register_fn:
                            register_fn(twap_id, order_id)
                        if self.order_queue:
                            self.order_queue.put(order_id)

                        slice_value = slice_size * execution_price
                        print(f"\nOrder to {order_input['side'].lower()} {slice_size} {base_currency} "
                              f"with value ${slice_value:.2f} placed successfully")
                        print(f"TWAP Progress: {len(twap_order.orders)}/{num_slices}")
                    else:
                        slice_info['status'] = 'placement_failed'
                        twap_order.failed_slices.append(i + 1)

                except Exception as e:
                    logging.error(f"Error placing slice {i+1}: {str(e)}")
                    slice_info['status'] = 'error'
                    twap_order.failed_slices.append(i + 1)

                slice_info['end_time'] = time.time()
                slice_info['duration'] = slice_info['end_time'] - slice_info['start_time']
                twap_order.slice_statuses.append(slice_info)
                self.twap_tracker.save_twap_order(twap_order)

            # Final update
            twap_order.status = 'completed'
            self.twap_tracker.save_twap_order(twap_order)
            self.order_executor.update_twap_fills(twap_id, self.twap_tracker)

            logging.info(f"TWAP {twap_id} completed")
            return twap_id

        except Exception as e:
            logging.error(f"Error in TWAP execution: {str(e)}")
            if twap_order:
                twap_order.status = 'error'
                self.twap_tracker.save_twap_order(twap_order)
            return None

    def execute_strategy(self, strategy: OrderStrategy, register_fn=None) -> Optional[StrategyResult]:
        """
        Execute an order using the OrderStrategy protocol.

        This method uses the strategy's calculate_slices(), should_skip_slice(),
        get_execution_price(), and on_slice_complete() methods to drive execution.
        It creates a TWAPOrder for persistence and monitoring.

        Args:
            strategy: An OrderStrategy implementation (e.g. TWAPStrategy).
            register_fn: Optional callback to register orders for monitoring.

        Returns:
            StrategyResult on completion, or None on failure.
        """
        from twap_strategy import TWAPStrategy

        # Extract strategy parameters
        product_id = strategy.product_id
        side = strategy.side
        base_currency = product_id.split('-')[0]

        twap_id = strategy.strategy_id
        twap_order = TWAPOrder(
            twap_id=twap_id,
            market=product_id,
            side=side,
            total_size=strategy.total_size,
            limit_price=strategy.limit_price,
            num_slices=strategy.num_slices,
            start_time=datetime.now().isoformat(),
            status="active",
            orders=[],
            failed_slices=[],
            slice_statuses=[]
        )

        self.twap_tracker.save_twap_order(twap_order)

        slices = strategy.calculate_slices()
        slice_size = strategy.total_size / strategy.num_slices

        logging.info(
            f"Starting strategy {twap_id}: {strategy.num_slices} slices "
            f"over {strategy.duration_minutes}min"
        )

        order_input = {
            'product_id': product_id,
            'side': side,
            'base_size': strategy.total_size,
            'limit_price': strategy.limit_price,
        }

        try:
            for slice_spec in slices:
                i = slice_spec.slice_number - 1
                slice_info = {
                    'slice_number': slice_spec.slice_number,
                    'start_time': time.time(),
                    'status': 'pending',
                }

                # Wait until scheduled time
                current_time = time.time()
                if current_time < slice_spec.scheduled_time:
                    sleep_time = slice_spec.scheduled_time - current_time
                    if sleep_time > 0:
                        logging.info(f"Waiting {sleep_time:.2f}s until next slice...")
                        time.sleep(sleep_time)

                # Build market data for strategy decisions
                market_data = {}
                current_prices = self.market_data.get_current_prices(product_id)
                if current_prices:
                    market_data.update(current_prices)

                # Check participation rate cap via strategy
                if hasattr(strategy, 'get_recent_volume'):
                    recent_vol = strategy.get_recent_volume(product_id)
                    market_data['recent_volume'] = recent_vol

                if strategy.should_skip_slice(slice_spec.slice_number, market_data):
                    msg = (
                        f"Skipping slice {slice_spec.slice_number}/{strategy.num_slices}: "
                        f"participation rate cap"
                    )
                    logging.info(msg)
                    print(msg)
                    slice_info['status'] = 'skipped_participation_cap'
                    twap_order.failed_slices.append(slice_spec.slice_number)
                    strategy.on_slice_complete(slice_spec.slice_number, None, None)
                    slice_info['end_time'] = time.time()
                    twap_order.slice_statuses.append(slice_info)
                    self.twap_tracker.save_twap_order(twap_order)
                    continue

                # Check balance for sell orders
                if side == "SELL":
                    available = self.market_data.get_account_balance(base_currency)
                    if available < slice_size:
                        msg = f"Insufficient {base_currency} balance for slice {slice_spec.slice_number}"
                        logging.error(msg)
                        print(msg)
                        slice_info['status'] = 'balance_insufficient'
                        twap_order.failed_slices.append(slice_spec.slice_number)
                        strategy.on_slice_complete(slice_spec.slice_number, None, None)
                        slice_info['end_time'] = time.time()
                        twap_order.slice_statuses.append(slice_info)
                        self.twap_tracker.save_twap_order(twap_order)
                        continue

                if not current_prices:
                    logging.error(f"Failed to get prices for slice {slice_spec.slice_number}")
                    slice_info['status'] = 'price_fetch_failed'
                    twap_order.failed_slices.append(slice_spec.slice_number)
                    strategy.on_slice_complete(slice_spec.slice_number, None, None)
                    slice_info['end_time'] = time.time()
                    twap_order.slice_statuses.append(slice_info)
                    self.twap_tracker.save_twap_order(twap_order)
                    continue

                # Get execution price from strategy
                execution_price = strategy.get_execution_price(slice_spec, market_data)
                slice_info['execution_price'] = execution_price
                slice_info['market_prices'] = current_prices

                # Price favorability check
                if side == "BUY":
                    price_favorable = execution_price <= strategy.limit_price
                else:
                    price_favorable = execution_price >= strategy.limit_price

                if not price_favorable:
                    msg = (
                        f"Skipping slice {slice_spec.slice_number}/{strategy.num_slices}: "
                        f"unfavorable price ${execution_price:.2f}"
                    )
                    logging.warning(msg)
                    print(msg)
                    slice_info['status'] = 'price_unfavorable'
                    twap_order.failed_slices.append(slice_spec.slice_number)
                    strategy.on_slice_complete(slice_spec.slice_number, None, None)
                    slice_info['end_time'] = time.time()
                    twap_order.slice_statuses.append(slice_info)
                    self.twap_tracker.save_twap_order(twap_order)
                    continue

                # Place the slice
                try:
                    order_id = self.order_executor.place_twap_slice(
                        twap_id, slice_spec.slice_number, strategy.num_slices,
                        order_input, execution_price, self.twap_tracker
                    )

                    if order_id:
                        twap_order.orders.append(order_id)
                        slice_info['status'] = 'placed'
                        slice_info['order_id'] = order_id

                        if register_fn:
                            register_fn(twap_id, order_id)
                        if self.order_queue:
                            self.order_queue.put(order_id)

                        strategy.on_slice_complete(
                            slice_spec.slice_number,
                            order_id,
                            {
                                'filled_size': slice_size,
                                'price': execution_price,
                                'fee': 0.0,
                            },
                        )

                        slice_value = slice_size * execution_price
                        print(
                            f"\nOrder to {side.lower()} {slice_size} "
                            f"{base_currency} with value ${slice_value:.2f} "
                            f"placed successfully"
                        )
                        print(
                            f"Strategy Progress: "
                            f"{len(twap_order.orders)}/{strategy.num_slices}"
                        )
                    else:
                        slice_info['status'] = 'placement_failed'
                        twap_order.failed_slices.append(slice_spec.slice_number)
                        strategy.on_slice_complete(slice_spec.slice_number, None, None)

                except Exception as e:
                    logging.error(f"Error placing slice {slice_spec.slice_number}: {str(e)}")
                    slice_info['status'] = 'error'
                    twap_order.failed_slices.append(slice_spec.slice_number)
                    strategy.on_slice_complete(slice_spec.slice_number, None, None)

                slice_info['end_time'] = time.time()
                slice_info['duration'] = slice_info['end_time'] - slice_info['start_time']
                twap_order.slice_statuses.append(slice_info)
                self.twap_tracker.save_twap_order(twap_order)

            # Final update
            twap_order.status = 'completed'
            self.twap_tracker.save_twap_order(twap_order)
            self.order_executor.update_twap_fills(twap_id, self.twap_tracker)

            logging.info(f"Strategy {twap_id} completed")
            return strategy.get_result()

        except Exception as e:
            logging.error(f"Error in strategy execution: {str(e)}")
            if twap_order:
                twap_order.status = 'error'
                self.twap_tracker.save_twap_order(twap_order)
            return None

    def check_twap_order_fills(self, twap_id):
        """Check fills for a specific TWAP order."""
        try:
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                print(f"TWAP order {twap_id} not found.")
                return

            print(f"\nChecking fills for TWAP order {twap_id}...")
            self.order_executor.update_twap_fills(twap_id, self.twap_tracker)
        except Exception as e:
            logging.error(f"Error checking TWAP fills: {str(e)}")
            print("Error checking TWAP fills.")
