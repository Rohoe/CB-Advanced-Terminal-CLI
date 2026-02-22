"""
TWAP executor extracted from TradingTerminal.

Handles TWAP order execution: slice timing, price selection, and progress tracking.
Supports both legacy execute_twap() and strategy-based execute_strategy() flows.
"""

from typing import Optional, Callable, List, Dict
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

    def _execute_slices(
        self,
        twap_order: TWAPOrder,
        order_input: dict,
        slice_size: float,
        slice_specs: List[Dict],
        get_price_fn: Callable,
        register_fn: Optional[Callable] = None,
        should_skip_fn: Optional[Callable] = None,
        on_complete_fn: Optional[Callable] = None,
    ):
        """
        Common slice execution loop used by both execute_twap and execute_strategy.

        Args:
            twap_order: TWAPOrder being executed.
            order_input: Dict with product_id, side, base_size, limit_price.
            slice_size: Size per slice.
            slice_specs: List of dicts with 'slice_number' and 'scheduled_time'.
            get_price_fn: (spec, current_prices) -> execution_price.
            register_fn: Optional (twap_id, order_id) callback.
            should_skip_fn: Optional (slice_number, market_data) -> bool.
            on_complete_fn: Optional (slice_number, order_id, fill_info) callback.
        """
        product_id = order_input["product_id"]
        side = order_input["side"]
        base_currency = product_id.split('-')[0]
        limit_price = float(order_input["limit_price"])
        num_slices = len(slice_specs)

        for spec in slice_specs:
            slice_number = spec['slice_number']
            scheduled_time = spec['scheduled_time']

            slice_info = {
                'slice_number': slice_number,
                'start_time': time.time(),
                'status': 'pending',
            }

            # Wait until scheduled time
            current_time = time.time()
            if current_time < scheduled_time:
                sleep_time = scheduled_time - current_time
                if sleep_time > 0:
                    logging.info(f"Waiting {sleep_time:.2f}s until next slice...")
                    print(f"Waiting {sleep_time:.2f} seconds until next slice...")
                    time.sleep(sleep_time)

            # Build market data
            market_data = {}
            current_prices = self.market_data.get_current_prices(product_id)
            if current_prices:
                market_data.update(current_prices)

            # Check participation rate cap via should_skip_fn
            if should_skip_fn and should_skip_fn(slice_number, market_data):
                msg = f"Skipping slice {slice_number}/{num_slices}: participation rate cap"
                logging.info(msg)
                print(msg)
                slice_info['status'] = 'skipped_participation_cap'
                twap_order.failed_slices.append(slice_number)
                if on_complete_fn:
                    on_complete_fn(slice_number, None, None)
                slice_info['end_time'] = time.time()
                twap_order.slice_statuses.append(slice_info)
                self.twap_tracker.save_twap_order(twap_order)
                continue

            # Check balance for sell orders
            if side == "SELL":
                available = self.market_data.get_account_balance(base_currency)
                if available < slice_size:
                    msg = f"Insufficient {base_currency} balance for slice {slice_number}"
                    logging.error(msg)
                    print(msg)
                    slice_info['status'] = 'balance_insufficient'
                    twap_order.failed_slices.append(slice_number)
                    if on_complete_fn:
                        on_complete_fn(slice_number, None, None)
                    slice_info['end_time'] = time.time()
                    twap_order.slice_statuses.append(slice_info)
                    self.twap_tracker.save_twap_order(twap_order)
                    continue

            if not current_prices:
                logging.error(f"Failed to get prices for slice {slice_number}")
                slice_info['status'] = 'price_fetch_failed'
                twap_order.failed_slices.append(slice_number)
                if on_complete_fn:
                    on_complete_fn(slice_number, None, None)
                slice_info['end_time'] = time.time()
                twap_order.slice_statuses.append(slice_info)
                self.twap_tracker.save_twap_order(twap_order)
                continue

            # Determine execution price
            execution_price = get_price_fn(spec, current_prices)
            slice_info['execution_price'] = execution_price
            slice_info['market_prices'] = current_prices

            # Price favorability check
            if side == "BUY":
                price_favorable = execution_price <= limit_price
            else:
                price_favorable = execution_price >= limit_price

            if not price_favorable:
                msg = f"Skipping slice {slice_number}/{num_slices}: unfavorable price ${execution_price:.2f}"
                logging.warning(msg)
                print(msg)
                slice_info['status'] = 'price_unfavorable'
                twap_order.failed_slices.append(slice_number)
                if on_complete_fn:
                    on_complete_fn(slice_number, None, None)
                slice_info['end_time'] = time.time()
                twap_order.slice_statuses.append(slice_info)
                self.twap_tracker.save_twap_order(twap_order)
                continue

            # Place the slice
            try:
                order_id = self.order_executor.place_twap_slice(
                    twap_order.twap_id, slice_number, num_slices,
                    order_input, execution_price, self.twap_tracker
                )

                if order_id:
                    twap_order.orders.append(order_id)
                    slice_info['status'] = 'placed'
                    slice_info['order_id'] = order_id

                    if register_fn:
                        register_fn(twap_order.twap_id, order_id)
                    if self.order_queue:
                        self.order_queue.put(order_id)

                    if on_complete_fn:
                        on_complete_fn(
                            slice_number, order_id,
                            {'filled_size': slice_size, 'price': execution_price, 'fee': 0.0}
                        )

                    slice_value = slice_size * execution_price
                    print(
                        f"\nOrder to {side.lower()} {slice_size} {base_currency} "
                        f"with value ${slice_value:.2f} placed successfully"
                    )
                    print(f"TWAP Progress: {len(twap_order.orders)}/{num_slices}")
                else:
                    slice_info['status'] = 'placement_failed'
                    twap_order.failed_slices.append(slice_number)
                    if on_complete_fn:
                        on_complete_fn(slice_number, None, None)

            except Exception as e:
                logging.error(f"Error placing slice {slice_number}: {str(e)}")
                slice_info['status'] = 'error'
                twap_order.failed_slices.append(slice_number)
                if on_complete_fn:
                    on_complete_fn(slice_number, None, None)

            slice_info['end_time'] = time.time()
            slice_info['duration'] = slice_info['end_time'] - slice_info['start_time']
            twap_order.slice_statuses.append(slice_info)
            self.twap_tracker.save_twap_order(twap_order)

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
        start_time = time.time()

        # Build slice specs with scheduled times
        slice_specs = [
            {'slice_number': i + 1, 'scheduled_time': start_time + i * slice_interval}
            for i in range(num_slices)
        ]

        # Price function based on price_type code
        def get_price(spec, current_prices):
            if price_type == '1':
                return float(order_input["limit_price"])
            elif price_type == '2':
                return current_prices['bid']
            elif price_type == '3':
                return current_prices['mid']
            else:
                return current_prices['ask']

        logging.info(f"Starting TWAP {twap_id}: {num_slices} slices over {duration}min")

        try:
            self._execute_slices(
                twap_order=twap_order,
                order_input=order_input,
                slice_size=slice_size,
                slice_specs=slice_specs,
                get_price_fn=get_price,
                register_fn=register_fn,
            )

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

        Args:
            strategy: An OrderStrategy implementation (e.g. TWAPStrategy).
            register_fn: Optional callback to register orders for monitoring.

        Returns:
            StrategyResult on completion, or None on failure.
        """
        product_id = strategy.product_id
        side = strategy.side

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

        # Build slice specs from strategy slices
        slice_specs = [
            {'slice_number': s.slice_number, 'scheduled_time': s.scheduled_time, '_spec': s}
            for s in slices
        ]

        # Build should_skip function with participation rate cap
        def should_skip(slice_number, market_data):
            if hasattr(strategy, 'get_recent_volume'):
                recent_vol = strategy.get_recent_volume(product_id)
                market_data['recent_volume'] = recent_vol
            return strategy.should_skip_slice(slice_number, market_data)

        # Price function using strategy
        def get_price(spec, current_prices):
            return strategy.get_execution_price(spec['_spec'], current_prices)

        try:
            self._execute_slices(
                twap_order=twap_order,
                order_input=order_input,
                slice_size=slice_size,
                slice_specs=slice_specs,
                get_price_fn=get_price,
                register_fn=register_fn,
                should_skip_fn=should_skip,
                on_complete_fn=strategy.on_slice_complete,
            )

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
