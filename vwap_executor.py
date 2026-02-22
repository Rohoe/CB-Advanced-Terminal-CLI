"""
VWAP order executor.

Handles user interaction, volume profile display, order execution via TWAPExecutor,
and benchmark comparison for VWAP orders.
"""

import logging
import time
from typing import Optional, Callable
from datetime import datetime
from tabulate import tabulate

from vwap_strategy import VWAPStrategy, VWAPStrategyConfig
from order_executor import CancelledException
from validators import InputValidator, ValidationError
from ui_helpers import (
    info, highlight, format_currency, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)


class VWAPExecutor:
    """
    Executes VWAP orders using volume-weighted slice sizing.

    Delegates actual slice execution to TWAPExecutor.execute_strategy().
    """

    def __init__(self, twap_executor, market_data, api_client, config):
        """
        Args:
            twap_executor: TWAPExecutor instance (used for execute_strategy).
            market_data: MarketDataService instance.
            api_client: APIClient instance (for candle data).
            config: AppConfig instance.
        """
        self.twap_executor = twap_executor
        self.market_data = market_data
        self.api_client = api_client
        self.config = config

        # Store strategy references for display later
        self._strategies: dict = {}

    def place_vwap_order(self, get_input_fn: Callable, register_fn=None) -> Optional[str]:
        """
        Interactive VWAP order placement.

        Args:
            get_input_fn: Function to get user input.
            register_fn: Optional callback to register orders for monitoring.

        Returns:
            Strategy ID if successful, None otherwise.
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

            # Get limit price
            while True:
                try:
                    limit_price = float(get_input_fn("\nEnter limit price"))
                    InputValidator.validate_price(limit_price)
                    break
                except (ValueError, ValidationError) as e:
                    print(f"Invalid price: {e}")

            # Get total size
            while True:
                try:
                    total_size = float(get_input_fn("Enter total order size"))
                    if total_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get duration
            while True:
                try:
                    duration = int(get_input_fn("\nEnter VWAP duration in minutes"))
                    InputValidator.validate_twap_duration(duration)
                    break
                except (ValueError, ValidationError) as e:
                    print(f"Invalid duration: {e}")

            # Get number of slices
            while True:
                try:
                    num_slices = int(get_input_fn("Enter number of slices"))
                    if num_slices < 2:
                        print("Need at least 2 slices.")
                        continue
                    if num_slices > 1000:
                        print("Maximum 1000 slices.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get price type
            print("\nSelect price type for order placement:")
            print("1. Limit price")
            print("2. Current market bid")
            print("3. Current market mid")
            print("4. Current market ask")

            price_type_map = {'1': 'limit', '2': 'bid', '3': 'mid', '4': 'ask'}
            while True:
                choice = get_input_fn("Enter your choice (1-4)")
                if choice in price_type_map:
                    price_type = price_type_map[choice]
                    break
                print("Invalid choice.")

            # Get lookback hours
            while True:
                try:
                    lookback = int(get_input_fn("\nVolume lookback hours (default 24)") or "24")
                    if lookback < 1 or lookback > 168:
                        print("Lookback must be 1-168 hours.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Create strategy config
            vwap_config = VWAPStrategyConfig(
                duration_minutes=duration,
                num_slices=num_slices,
                price_type=price_type,
                volume_lookback_hours=lookback,
                granularity="ONE_HOUR",
                benchmark_enabled=True
            )

            # Create strategy
            strategy = VWAPStrategy(
                product_id=product_id,
                side=side,
                total_size=total_size,
                limit_price=limit_price,
                num_slices=num_slices,
                duration_minutes=duration,
                api_client=self.api_client,
                config=vwap_config
            )

            # Calculate slices (this fetches volume profile)
            slices = strategy.calculate_slices()

            # Round sizes
            for s in slices:
                s.size = self.market_data.round_size(s.size, product_id)

            # Display volume profile
            self._display_volume_profile(strategy, slices, product_id, side, total_size)

            # Display benchmark
            if strategy.benchmark_vwap > 0:
                print(f"\nBenchmark VWAP ({lookback}h): {format_currency(strategy.benchmark_vwap, colored=False)}")

            # Confirm
            confirm = get_input_fn("\nPlace this VWAP order? (yes/no)").lower()
            if confirm != 'yes':
                print("VWAP order cancelled.")
                return None

            # Store strategy for later display
            self._strategies[strategy.strategy_id] = strategy

            # Execute via TWAPExecutor
            print_info(f"\nExecuting VWAP order with {num_slices} slices over {duration} minutes...")
            result = self.twap_executor.execute_strategy(strategy, register_fn=register_fn)

            if result:
                strategy_id = strategy.strategy_id
                print_success(f"\nVWAP order completed: {strategy_id[:8]}...")
                self.display_vwap_summary(strategy)
                return strategy_id
            else:
                print_error("VWAP order execution failed.")
                return None

        except CancelledException:
            raise
        except Exception as e:
            logging.error(f"Error placing VWAP order: {str(e)}", exc_info=True)
            print_error(f"Error placing VWAP order: {str(e)}")
            return None

    def _display_volume_profile(self, strategy, slices, product_id, side, total_size):
        """Display the volume profile and slice sizing."""
        print_header(f"\nVWAP Order Preview - {product_id}")
        print(f"Side: {format_side(side)} | Total Size: {highlight(str(total_size))}")
        print(f"Duration: {strategy.duration_minutes}min | Slices: {strategy.num_slices}")

        profile = strategy.volume_profile
        if not profile:
            print_warning("No volume profile data available.")
            return

        headers = ['#', 'Volume Weight', 'Size', '% of Total', 'Bar']
        rows = []
        max_weight = max(profile) if profile else 1.0

        for i, s in enumerate(slices):
            weight = profile[i] if i < len(profile) else 0
            pct = (s.size / total_size * 100) if total_size > 0 else 0
            bar_len = int((weight / max_weight) * 20) if max_weight > 0 else 0
            bar = '#' * bar_len
            rows.append([
                s.slice_number,
                f"{weight:.4f}",
                f"{s.size:.8f}",
                f"{pct:.1f}%",
                bar
            ])

        print(tabulate(rows, headers=headers, tablefmt='simple'))

    def display_vwap_summary(self, strategy_or_id) -> None:
        """
        Display VWAP execution summary with benchmark comparison.

        Args:
            strategy_or_id: VWAPStrategy instance or strategy ID string.
        """
        if isinstance(strategy_or_id, str):
            strategy = self._strategies.get(strategy_or_id)
            if not strategy:
                print_warning(f"VWAP strategy {strategy_or_id} not found.")
                return
        else:
            strategy = strategy_or_id

        result = strategy.get_result()
        perf = strategy.get_performance_vs_benchmark()

        print_header(f"\nVWAP Execution Summary - {result.strategy_id[:8]}...")
        print(f"Market: {info(strategy.product_id)} | Side: {format_side(strategy.side)}")
        print(f"Status: {format_status(result.status.value)}")

        print_subheader("\nExecution Results")
        print(f"Total Filled: {result.total_filled:.8f} / {result.total_size:.8f}")
        print(f"Slices: {result.num_filled} filled, {result.num_failed} failed out of {result.num_slices}")

        if result.total_filled > 0:
            print(f"Average Price: {format_currency(result.average_price, colored=False)}")
            print(f"Total Value: {format_currency(result.total_value, colored=False)}")
            print(f"Total Fees: {format_currency(result.total_fees, colored=False)}")

        if perf['benchmark_vwap'] > 0 and perf['execution_vwap'] > 0:
            print_subheader("\nBenchmark Comparison")
            print(f"Execution VWAP: {format_currency(perf['execution_vwap'], colored=False)}")
            print(f"Benchmark VWAP: {format_currency(perf['benchmark_vwap'], colored=False)}")

            slippage = perf['slippage_bps']
            if slippage > 0:
                print(f"Slippage: {slippage:.1f} bps (unfavorable)")
            elif slippage < 0:
                print(f"Slippage: {abs(slippage):.1f} bps (favorable)")
            else:
                print(f"Slippage: 0.0 bps (at benchmark)")
