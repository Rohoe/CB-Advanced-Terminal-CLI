"""
Trading terminal application - thin orchestrator.

Composes extracted service modules and provides the main execution loop,
login flow, user input handling, and background order monitoring.
"""

from typing import Optional, Dict, List
from twap_tracker import TWAPTracker, TWAPOrder, OrderFill
import logging
from config import Config, ConfigurationError
from config_manager import AppConfig
from api_client import APIClient, CoinbaseAPIClient
from database import Database
from storage import TWAPStorage, FileBasedTWAPStorage
from sqlite_storage import SQLiteTWAPStorage, SQLiteScaledOrderTracker, SQLiteConditionalOrderTracker
from validators import InputValidator, ValidationError
import time
from threading import Lock, Thread
from queue import Queue, Empty
from datetime import datetime
import os
from ui_helpers import (
    success, error, warning, info, highlight,
    format_currency, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)
from market_data import MarketDataService
from order_executor import OrderExecutor, CancelledException
from twap_executor import TWAPExecutor
from conditional_executor import ConditionalExecutor
from display_service import DisplayService
from scaled_executor import ScaledExecutor
from vwap_executor import VWAPExecutor
from background_worker import OrderStatusChecker
from websocket_service import WebSocketService
from analytics_service import AnalyticsService
from analytics_display import AnalyticsDisplay


# Configure logging with both file and console output
def setup_logging():
    """Setup logging configuration"""
    if not os.path.exists('logs'):
        os.makedirs('logs')

    log_filename = f'logs/trading_terminal_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

    root_logger = logging.getLogger()

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)

    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info("="*50)
    logging.info("Starting new trading session")
    logging.info("="*50)

# Call setup_logging at the start
setup_logging()


class RateLimiter:
    """
    Implements a token bucket rate limiter.
    """
    def __init__(self, rate, burst):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_check = time.time()
        self.lock = Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            time_passed = now - self.last_check
            self.tokens = min(self.burst, self.tokens + time_passed * self.rate)
            self.last_check = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True
            else:
                return False

    def wait(self):
        while not self.acquire():
            time.sleep(0.05)


class TradingTerminal:
    def __init__(self,
                 api_client: Optional[APIClient] = None,
                 twap_storage: Optional[TWAPStorage] = None,
                 config: Optional[AppConfig] = None,
                 start_checker_thread: bool = True,
                 database: Optional[Database] = None):
        """
        Initialize the trading terminal with dependency injection.

        Args:
            api_client: API client implementation (None = will be set during login).
            twap_storage: TWAP storage implementation (None = use file-based storage).
            config: Application configuration (None = load from environment).
            start_checker_thread: Whether to start the background order checker thread.
            database: Database instance (None = create from config).
        """
        logging.info("Initializing TradingTerminal")
        try:
            # Configuration
            self.config = config or AppConfig()
            logging.debug(f"Using configuration: rate_limit={self.config.rate_limit.requests_per_second}/s")

            # API Client (may be None initially, set during login)
            self.client = api_client

            # Database + auto-migration from JSON
            self.database = database or Database(self.config.database)
            from migrate_json_to_sqlite import JSONToSQLiteMigrator
            JSONToSQLiteMigrator(self.database).migrate_if_needed()

            # TWAP Storage (prefer SQLite, fall back to provided or file-based)
            if twap_storage:
                self.twap_storage = twap_storage
            else:
                self.twap_storage = SQLiteTWAPStorage(self.database)

            # For backward compatibility, also keep TWAPTracker reference
            if isinstance(self.twap_storage, FileBasedTWAPStorage):
                self.twap_tracker = self.twap_storage._tracker
            elif hasattr(self.twap_storage, '_tracker'):
                self.twap_tracker = self.twap_storage._tracker
            else:
                # InMemoryTWAPStorage implements the tracker interface directly
                self.twap_tracker = self.twap_storage

            # Rate Limiter
            logging.debug("Creating RateLimiter")
            self.rate_limiter = RateLimiter(
                self.config.rate_limit.requests_per_second,
                self.config.rate_limit.burst
            )

            # Thread synchronization
            logging.debug("Initializing queues and locks")
            self.order_queue = Queue()
            self.filled_orders = []
            self.order_lock = Lock()
            self.twap_lock = Lock()
            self.is_running = True

            # Initialize twap_orders before starting the checker thread
            logging.debug("Initializing TWAP tracking dictionaries")
            self.twap_orders = {}
            self.order_to_twap_map = {}

            # Conditional orders tracking (SQLite-backed)
            logging.debug("Initializing conditional order tracking")
            self.conditional_order_tracker = SQLiteConditionalOrderTracker(self.database)
            self.order_to_conditional_map = {}
            self.conditional_lock = Lock()

            # Scaled orders tracking
            logging.debug("Initializing scaled order tracking")
            self.order_to_scaled_map = {}
            self.scaled_lock = Lock()

            # Caches with TTLs from config
            logging.debug("Initializing caches")
            self.order_status_cache = {}
            self.cache_ttl = self.config.cache.order_status_ttl
            self.failed_orders = set()

            # Precision configuration
            self.precision_config = self.config.precision.product_overrides

            # Account cache
            self.account_cache = {}
            self.account_cache_time = 0
            self.account_cache_ttl = self.config.cache.account_ttl

            # Fill cache
            self.fill_cache = {}
            self.fill_cache_time = 0
            self.fill_cache_ttl = self.config.cache.fill_ttl

            # Fee tier cache
            self.fee_tier_cache = None
            self.fee_tier_cache_time = 0
            self.fee_tier_cache_ttl = 3600

            # WebSocket service (initialized after login when credentials are available)
            self.websocket_service = None

            # Initialize extracted service modules
            self._init_services()

            # Background thread for order status checking
            if start_checker_thread:
                logging.debug("Starting checker thread")
                self._status_checker = OrderStatusChecker(
                    self, self.websocket_service,
                    analytics_service=getattr(self, 'analytics_service', None)
                )
                self.checker_thread = Thread(target=self._status_checker.run)
                self.checker_thread.daemon = True
                self.checker_thread.start()
                logging.debug("Checker thread started")
            else:
                self.checker_thread = None
                logging.debug("Checker thread not started (disabled)")

            logging.info("TradingTerminal initialization completed successfully")

        except Exception as e:
            logging.critical(f"Failed to initialize TradingTerminal: {str(e)}", exc_info=True)
            raise

    def _init_services(self):
        """Initialize extracted service modules."""
        # MarketDataService
        self.market_data = MarketDataService(
            api_client=self.client,
            rate_limiter=self.rate_limiter,
            config=self.config
        )

        # OrderExecutor
        self.order_executor = OrderExecutor(
            api_client=self.client,
            market_data=self.market_data,
            rate_limiter=self.rate_limiter,
            config=self.config
        )

        # TWAPExecutor
        self.twap_executor = TWAPExecutor(
            order_executor=self.order_executor,
            market_data=self.market_data,
            twap_storage=self.twap_storage,
            order_queue=self.order_queue,
            config=self.config
        )

        # ConditionalExecutor
        self.conditional_executor = ConditionalExecutor(
            api_client=self.client,
            market_data=self.market_data,
            order_executor=self.order_executor,
            conditional_tracker=self.conditional_order_tracker,
            order_queue=self.order_queue,
            config=self.config
        )

        # ScaledExecutor (with SQLite-backed tracker)
        self.scaled_executor = ScaledExecutor(
            order_executor=self.order_executor,
            market_data=self.market_data,
            order_queue=self.order_queue,
            config=self.config,
            scaled_tracker=SQLiteScaledOrderTracker(self.database)
        )

        # VWAPExecutor
        self.vwap_executor = VWAPExecutor(
            twap_executor=self.twap_executor,
            market_data=self.market_data,
            api_client=self.client,
            config=self.config
        )

        # Analytics
        self.analytics_service = AnalyticsService(self.database)
        self.analytics_display = AnalyticsDisplay(self.analytics_service)

        # Wire analytics into executors
        self.twap_executor.analytics_service = self.analytics_service
        self.scaled_executor.analytics_service = self.analytics_service

        # DisplayService
        self.display_service = DisplayService(
            api_client=self.client,
            market_data=self.market_data,
            twap_storage=self.twap_storage,
            conditional_tracker=self.conditional_order_tracker,
            config=self.config
        )

    def get_input(self, prompt, allow_cancel=True):
        """
        Get user input with optional cancellation support.

        Args:
            prompt: The prompt to display to the user
            allow_cancel: If True, allows user to cancel by typing 'cancel', 'back', or 'q'

        Returns:
            The user's input string

        Raises:
            CancelledException: If user enters a cancel command and allow_cancel is True
        """
        if allow_cancel and "cancel" not in prompt.lower():
            prompt = prompt.rstrip() + " (or 'cancel' to go back): "

        user_input = input(prompt).strip()

        if allow_cancel and user_input.lower() in ['cancel', 'back', 'q', 'quit']:
            logging.debug(f"User cancelled operation with input: {user_input}")
            raise CancelledException("Operation cancelled by user")

        return user_input

    # ========================
    # Delegated Market Data Methods (backward compatibility)
    # ========================

    def get_accounts(self, force_refresh=False):
        """Get account information with caching."""
        return self.market_data.get_accounts(force_refresh)

    def get_account_balance(self, currency):
        """Get account balance for a specific currency."""
        return self.market_data.get_account_balance(currency)

    def get_bulk_prices(self, product_ids):
        """Get prices for multiple products in a single API call."""
        return self.market_data.get_bulk_prices(product_ids)

    def get_current_prices(self, product_id):
        """Get current bid, ask, and mid prices for a product."""
        return self.market_data.get_current_prices(product_id)

    def check_order_fills_batch(self, order_ids):
        """Check fills for multiple orders efficiently."""
        return self.market_data.check_order_fills_batch(order_ids)

    def _select_market(self):
        """Interactive market selection from top 20 markets by volume."""
        return self.market_data.select_market(self.get_input)

    def _display_market_conditions(self, product_id, side, current_prices=None):
        """Display current market conditions."""
        return self.market_data.display_market_conditions(product_id, side, current_prices)

    def round_size(self, size, product_id):
        """Round order size to appropriate precision."""
        return self.market_data.round_size(size, product_id)

    def round_price(self, price, product_id):
        """Round price to appropriate precision."""
        return self.market_data.round_price(price, product_id)

    # ========================
    # Delegated Order Executor Methods (backward compatibility)
    # ========================

    def get_fee_rates(self, force_refresh=False):
        """Get current fee rates with caching."""
        return self.order_executor.get_fee_rates(force_refresh)

    def calculate_estimated_fee(self, size, price, is_maker=True):
        """Calculate estimated fee for an order."""
        return self.order_executor.calculate_estimated_fee(size, price, is_maker)

    def place_limit_order_with_retry(self, product_id, side, base_size, limit_price, client_order_id=None):
        """Place a limit order with enhanced error handling and validation."""
        return self.order_executor.place_limit_order_with_retry(
            product_id, side, base_size, limit_price, client_order_id
        )

    def place_twap_slice(self, twap_id, slice_number, total_slices, order_input, execution_price):
        """Place a single TWAP slice."""
        return self.twap_executor.place_twap_slice(
            twap_id, slice_number, total_slices, order_input, execution_price, self.twap_tracker
        )

    def update_twap_fills(self, twap_id):
        """Update fill information for a TWAP order."""
        return self.twap_executor.update_twap_fills(twap_id, self.twap_tracker)

    def get_order_input(self):
        """Get common order parameters from user input."""
        return self.order_executor.get_order_input(self.get_input)

    def get_conditional_order_input(self):
        """Get order input without limit price."""
        return self.conditional_executor.get_conditional_order_input(self.get_input)

    # ========================
    # Delegated Display Methods (backward compatibility)
    # ========================

    def get_active_orders(self):
        """Get list of active orders."""
        return self.display_service.get_active_orders()

    def get_order_history(self, limit=100, product_id=None, order_status=None):
        """Get historical orders with optional filters."""
        return self.display_service.get_order_history(limit, product_id, order_status)

    def display_portfolio(self, accounts_data):
        """Display portfolio data."""
        return self.display_service.display_portfolio(accounts_data)

    def display_twap_progress(self, twap_id):
        """Display TWAP order progress."""
        return self.display_service.display_twap_progress(twap_id)

    def display_twap_summary(self, twap_id, show_orders=True):
        """Display comprehensive TWAP order summary."""
        return self.display_service.display_twap_summary(twap_id, show_orders)

    def display_all_twap_orders(self):
        """Display all TWAP orders."""
        return self.display_service.display_all_twap_orders()

    # ========================
    # Interactive Order Placement
    # ========================

    def place_limit_order(self):
        """Place a limit order with user input."""
        if not self.client:
            logging.warning("Attempt to place limit order without login")
            print_warning("Please login first.")
            return

        try:
            return self._place_limit_order_impl()
        except CancelledException:
            logging.info("Limit order placement cancelled by user")
            print_info("\nOrder placement cancelled. Returning to main menu.")
            return None

    def _place_limit_order_impl(self):
        """Internal implementation of place_limit_order."""
        try:
            product_id = self._select_market()
            if not product_id:
                return

            while True:
                side = self.get_input("\nEnter order side (buy/sell)").upper()
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            current_prices = self.get_current_prices(product_id)
            if current_prices:
                self._display_market_conditions(product_id, side, current_prices)

            while True:
                try:
                    limit_price = float(self.get_input("\nEnter limit price"))
                    if limit_price <= 0:
                        print("Price must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            while True:
                try:
                    base_size = float(self.get_input("\nEnter order size"))
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            maker_rate, taker_rate = self.get_fee_rates()
            estimated_fee_maker = self.calculate_estimated_fee(base_size, limit_price, is_maker=True)
            estimated_fee_taker = self.calculate_estimated_fee(base_size, limit_price, is_maker=False)

            print_header("\nOrder Summary")
            print(f"Product: {info(product_id)}")
            print(f"Side: {format_side(side)}")
            print(f"Size: {highlight(str(base_size))}")
            print(f"Limit Price: {format_currency(limit_price, colored=False)}")

            order_value = base_size * limit_price
            print(f"\nOrder Value: {format_currency(order_value, colored=False)}")

            print_subheader("\nEstimated Fees")
            print(f"If Maker ({maker_rate:.2%}): {format_currency(estimated_fee_maker, colored=False)}")
            print(f"If Taker ({taker_rate:.2%}): {format_currency(estimated_fee_taker, colored=False)}")

            if side == "BUY":
                total_cost_maker = order_value + estimated_fee_maker
                total_cost_taker = order_value + estimated_fee_taker
                print_subheader("\nTotal Cost (including fees)")
                print(f"Best case (maker): {format_currency(total_cost_maker, colored=False)}")
                print(f"Worst case (taker): {format_currency(total_cost_taker, colored=False)}")
            else:
                total_value_maker = order_value - estimated_fee_maker
                total_value_taker = order_value - estimated_fee_taker
                print_subheader("\nNet Proceeds (after fees)")
                print(f"Best case (maker): {format_currency(total_value_maker, colored=False)}")
                print(f"Worst case (taker): {format_currency(total_value_taker, colored=False)}")

            confirm = self.get_input("\nDo you want to place this order? (yes/no)").lower()

            if confirm != 'yes':
                print("Order cancelled.")
                return

            order_response = self.place_limit_order_with_retry(
                product_id=product_id,
                side=side,
                base_size=str(base_size),
                limit_price=str(limit_price),
                client_order_id=f"limit-{int(time.time())}"
            )

            if order_response:
                try:
                    if 'success_response' in order_response:
                        order_id = order_response['success_response']['order_id']
                    elif 'order_id' in order_response:
                        order_id = order_response['order_id']
                    else:
                        print("\nError: Could not find order ID in response")
                        return None

                    logging.info(f"Limit order placed successfully. Order ID: {order_id}")
                    print_success("\nOrder placed successfully!")
                    print(f"Order ID: {highlight(order_id)}")
                    return order_id

                except Exception as e:
                    logging.error(f"Error processing order response: {str(e)}")
                    print("\nError processing order response")
                    return None
            else:
                print("\nFailed to place order. Please try again.")
                return None

        except CancelledException:
            raise
        except Exception as e:
            logging.error(f"Error in place_limit_order: {str(e)}", exc_info=True)
            print_error(f"\nError placing order: {str(e)}")
            return None

    def place_twap_order(self):
        """Place a TWAP order."""
        if not self.client:
            print_warning("Please login first.")
            return None

        try:
            return self._place_twap_order_impl()
        except CancelledException:
            print_info("\nTWAP order placement cancelled. Returning to main menu.")
            return None

    def _place_twap_order_impl(self):
        """Internal implementation of place_twap_order."""
        order_input = self.get_order_input()
        if not order_input:
            return None

        product_id = order_input["product_id"]
        base_currency = product_id.split('-')[0]
        quote_currency = product_id.split('-')[1]

        duration = int(self.get_input("\nEnter TWAP duration in minutes"))
        num_slices = int(self.get_input("Enter number of slices for TWAP"))

        try:
            product_info = self.client.get_product(product_id)
            min_size = float(product_info['base_min_size'])

            slice_size = float(order_input["base_size"]) / num_slices
            if slice_size < min_size:
                print(f"Error: Slice size {slice_size} is below minimum {min_size}")
                return None
        except Exception as e:
            print(f"Error fetching product information: {str(e)}")
            return None

        print("\nSelect price type for order placement:")
        print("1. Original limit price")
        print("2. Current market bid")
        print("3. Current market mid")
        print("4. Current market ask")
        price_type = self.get_input("Enter your choice (1-4)")

        def register_fn(twap_id, order_id):
            with self.twap_lock:
                self.order_to_twap_map[order_id] = twap_id

        twap_id = self.twap_executor.execute_twap(
            order_input=order_input,
            duration=duration,
            num_slices=num_slices,
            price_type=price_type,
            get_input_fn=self.get_input,
            register_fn=register_fn
        )

        if twap_id:
            self.display_twap_summary(twap_id)

        return twap_id

    def check_twap_order_fills(self, twap_id):
        """Check fills for a specific TWAP order and display summary."""
        try:
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                print(f"TWAP order {twap_id} not found.")
                return

            print(f"\nChecking fills for TWAP order {twap_id}...")

            if self.update_twap_fills(twap_id):
                self.display_twap_summary(twap_id, show_orders=True)
            else:
                print("Error checking TWAP fills. Please try again.")

        except Exception as e:
            logging.error(f"Error checking TWAP fills: {str(e)}")
            print("Error checking TWAP fills. Please check the logs for details.")

    # ========================
    # VWAP Order Delegation
    # ========================

    def place_vwap_order(self):
        """Place a VWAP order."""
        if not self.client:
            print_warning("Please login first.")
            return None
        try:
            def register_fn(twap_id, order_id):
                with self.twap_lock:
                    self.order_to_twap_map[order_id] = twap_id

            return self.vwap_executor.place_vwap_order(self.get_input, register_fn=register_fn)
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
            return None

    def view_vwap_fills(self):
        """View VWAP execution summary."""
        if not self.client:
            print_warning("Please login first.")
            return
        try:
            strategies = self.vwap_executor._strategies
            if not strategies:
                print_info("No VWAP orders in this session.")
                return

            print_header("\nVWAP Orders")
            ids = list(strategies.keys())
            for i, sid in enumerate(ids):
                s = strategies[sid]
                print(f"{i+1}. {sid[:8]}... - {s.product_id} {s.side} {s.total_size}")

            num = self.get_input("Enter the number of the VWAP order to view")
            try:
                idx = int(num) - 1
                if 0 <= idx < len(ids):
                    self.vwap_executor.display_vwap_summary(ids[idx])
                else:
                    print_warning("Invalid number.")
            except ValueError:
                print_warning("Please enter a valid number.")
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")

    # ========================
    # Scaled Order Delegation
    # ========================

    def place_scaled_order(self):
        """Place a scaled/ladder order."""
        if not self.client:
            print_warning("Please login first.")
            return None
        try:
            scaled_id = self.scaled_executor.place_scaled_order(self.get_input)
            if scaled_id:
                # Register child orders for background monitoring
                order = self.scaled_executor.scaled_tracker.get_scaled_order(scaled_id)
                if order:
                    with self.scaled_lock:
                        for level in order.levels:
                            if level.order_id:
                                self.order_to_scaled_map[level.order_id] = (scaled_id, level.level_number)
            return scaled_id
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
            return None

    def view_scaled_order_fills(self):
        """View scaled order fills."""
        if not self.client:
            print_warning("Please login first.")
            return
        try:
            scaled_ids = self.scaled_executor.display_all_scaled_orders()
            if scaled_ids:
                num = self.get_input("Enter the number of the scaled order to view")
                try:
                    idx = int(num) - 1
                    if 0 <= idx < len(scaled_ids):
                        self.scaled_executor.display_scaled_summary(scaled_ids[idx])
                    else:
                        print_warning("Invalid scaled order number.")
                except ValueError:
                    print_warning("Please enter a valid number.")
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")

    # ========================
    # Conditional Order Delegation
    # ========================

    def place_stop_loss_order(self):
        """Place a stop-loss order."""
        if not self.client:
            print_warning("Please login first.")
            return None
        try:
            return self.conditional_executor.place_stop_loss_order(self.get_input)
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
            return None

    def place_take_profit_order(self):
        """Place a take-profit order."""
        if not self.client:
            print_warning("Please login first.")
            return None
        try:
            return self.conditional_executor.place_take_profit_order(self.get_input)
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
            return None

    def place_entry_with_bracket(self):
        """Place an entry order with bracket (TP/SL)."""
        if not self.client:
            print_warning("Please login first.")
            return None
        try:
            return self.conditional_executor.place_entry_with_bracket(self.get_input)
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
            return None

    # ========================
    # Portfolio & Orders Display
    # ========================

    def view_portfolio(self):
        """View and display the user's portfolio."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            print_info("\nFetching accounts (this may take a moment due to rate limiting)...")
            accounts = self.get_accounts(force_refresh=True)
            self.display_portfolio(accounts)
        except Exception as e:
            logging.error(f"Error fetching portfolio: {str(e)}")
            print_error(f"Error fetching portfolio: {str(e)}")

    def view_order_history(self):
        """Display order history with filters."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            self.display_service.view_order_history(self.get_input)
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")

    def view_all_active_orders(self):
        """Unified view and cancel interface for all active orders."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            self.display_service.view_all_active_orders(
                get_input_fn=self.get_input,
                conditional_lock=self.conditional_lock,
                order_to_conditional_map=self.order_to_conditional_map
            )
        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")

    def _sync_conditional_order_statuses(self):
        """Sync tracked conditional orders with actual Coinbase order statuses."""
        self.display_service._sync_conditional_order_statuses()

    # ========================
    # TWAP Status (in-memory tracking)
    # ========================

    def get_twap_status(self, twap_id):
        """Get comprehensive status of a TWAP order execution."""
        if twap_id not in self.twap_orders:
            return {
                'status': 'Not Found',
                'error': 'TWAP ID not found in system'
            }

        twap_info = self.twap_orders[twap_id]
        order_ids = twap_info['orders']

        if not order_ids:
            return {
                'status': 'Initialized',
                'total_orders': 0,
                'filled_orders': 0,
                'cancelled_orders': 0,
                'pending_orders': 0,
                'completion_rate': 0
            }

        try:
            fills = self.check_order_fills_batch(order_ids)

            filled_count = len([oid for oid in order_ids if fills.get(oid, {}).get('status') == 'FILLED'])
            cancelled_count = 0
            pending_count = 0

            unfilled_orders = [oid for oid in order_ids if fills.get(oid, {}).get('status') != 'FILLED']

            if unfilled_orders:
                self.rate_limiter.wait()
                orders_response = self.client.list_orders(order_ids=unfilled_orders)
                if hasattr(orders_response, 'orders'):
                    for order in orders_response.orders:
                        if order.status == 'CANCELLED':
                            cancelled_count += 1
                        elif order.status in ['PENDING', 'OPEN']:
                            pending_count += 1

            completion_rate = 0
            if twap_info['total_value_placed'] > 0:
                completion_rate = (twap_info['total_value_filled'] /
                                twap_info['total_value_placed']) * 100

            if pending_count == 0 and (filled_count + cancelled_count == len(order_ids)):
                status = 'Complete'
            elif filled_count > 0:
                status = 'Partially Filled'
            elif cancelled_count == len(order_ids):
                status = 'Cancelled'
            else:
                status = 'Active'

            return {
                'status': status,
                'total_orders': len(order_ids),
                'filled_orders': filled_count,
                'cancelled_orders': cancelled_count,
                'pending_orders': pending_count,
                'completion_rate': completion_rate
            }

        except Exception as e:
            logging.error(f"Error getting TWAP status: {str(e)}")
            return {
                'status': 'Error',
                'error': str(e)
            }

    # ========================
    # Background Thread
    # ========================

    def order_status_checker(self):
        """Background thread to check order statuses efficiently."""
        OrderStatusChecker(self).run()

    # ========================
    # Login & Main Loop
    # ========================

    def login(self):
        """Authenticate user and initialize the API client."""
        logging.info("Initiating login process")
        print_header("Welcome to the Coinbase Trading Terminal!")
        print_info("Authenticating with Coinbase API...")

        try:
            if self.client is not None:
                logging.info("API client already initialized via dependency injection")
                print("Login successful!")
                return True

            config = Config()
            api_key = config.api_key
            api_secret = config.api_secret

            if not api_key or not api_secret:
                raise ValueError("API key or secret not found")

            self.client = CoinbaseAPIClient(
                api_key=api_key,
                api_secret=api_secret,
                verbose=False
            )

            self.rate_limiter.wait()
            test_response = self.client.get_accounts()

            if not hasattr(test_response, 'accounts'):
                raise Exception("Failed to authenticate with API - 'accounts' not in response")

            # Re-initialize services with the real client
            self._init_services()

            # Start WebSocket after successful login
            self._start_websocket(api_key, api_secret)

            logging.info("Login successful")
            print_success("Login successful!")
            return True

        except ConfigurationError as e:
            logging.error(f"Configuration error: {str(e)}", exc_info=True)
            print_error(f"\nConfiguration Error:\n{str(e)}")
            self.client = None
            return False
        except AttributeError as e:
            logging.error(f"API credentials error: {str(e)}", exc_info=True)
            print_error("Error accessing API credentials. Please check your configuration.")
            self.client = None
            return False
        except Exception as e:
            logging.error(f"Login failed: {str(e)}", exc_info=True)
            print_error(f"Login failed: {str(e)}")
            self.client = None
            return False

    def _start_websocket(self, api_key: str, api_secret: str):
        """Start WebSocket service after successful login."""
        if not self.config.websocket.enabled:
            logging.info("WebSocket disabled by config")
            return

        try:
            self.websocket_service = WebSocketService(
                api_key=api_key,
                api_secret=api_secret,
                config=self.config.websocket,
            )
            self.websocket_service.start(product_ids=["BTC-USD", "ETH-USD", "SOL-USD"])

            # Wire into services
            self.market_data.websocket_service = self.websocket_service

            # Update background worker if it exists
            if hasattr(self, '_status_checker'):
                self._status_checker.websocket_service = self.websocket_service
                self.websocket_service.register_fill_callback(
                    self._status_checker._on_ws_fill
                )

            logging.info("WebSocket service started")
        except Exception as e:
            logging.warning(f"WebSocket failed to start (REST fallback active): {e}")
            self.websocket_service = None

    def run(self):
        """Main execution loop for the trading terminal."""
        try:
            if not self.login():
                print("Unable to start trading terminal due to login failure.")
                return

            while True:
                print_header("\nMain Menu")

                # Portfolio & History
                print(info("\n=== Portfolio & History ==="))
                print("1. View portfolio balances")
                print("2. View & manage orders")
                print("3. View order history")

                # Basic Orders
                print(info("\n=== Basic Orders ==="))
                print("4. Limit order")
                print("5. Stop-loss order (standalone)")
                print("6. Take-profit order (standalone)")

                # Advanced Orders
                print(info("\n=== Advanced Orders ==="))
                print("7. Entry + Bracket (new position with TP/SL)")

                # Algorithmic Trading
                print(info("\n=== Algorithmic Trading ==="))
                print("8. TWAP order")
                print("9. View TWAP fills")
                print("10. Scaled/Ladder order")
                print("11. View Scaled order fills")
                print("12. VWAP order")
                print("13. View VWAP fills")

                # Analytics
                print(info("\n=== Analytics ==="))
                print("14. View P&L Summary")
                print("15. View Execution Analytics")
                print("16. View Fee Analysis")

                try:
                    choice = self.get_input("\nEnter your choice (1-16)")
                except CancelledException:
                    print_info("\nExiting application.")
                    break

                if choice == '1':
                    self.view_portfolio()
                elif choice == '2':
                    self.view_all_active_orders()
                elif choice == '3':
                    self.view_order_history()
                elif choice == '4':
                    result = self.place_limit_order()
                elif choice == '5':
                    order_id = self.place_stop_loss_order()
                    if order_id:
                        print_success(f"Stop-loss order placed: {order_id}")
                elif choice == '6':
                    order_id = self.place_take_profit_order()
                    if order_id:
                        print_success(f"Take-profit order placed: {order_id}")
                elif choice == '7':
                    order_id = self.place_entry_with_bracket()
                    if order_id:
                        print_success(f"Entry+Bracket order placed: {order_id}")
                elif choice == '8':
                    twap_id = self.place_twap_order()
                    if twap_id:
                        print_success(f"TWAP order placed with ID: {highlight(twap_id)}")
                elif choice == '9':
                    try:
                        twap_ids = self.display_all_twap_orders()
                        if twap_ids:
                            twap_number = self.get_input("Enter the number of the TWAP order to check")
                            try:
                                twap_index = int(twap_number) - 1
                                if 0 <= twap_index < len(twap_ids):
                                    twap_id = twap_ids[twap_index]
                                    self.check_twap_order_fills(twap_id)
                                else:
                                    print_warning("Invalid TWAP order number.")
                            except ValueError:
                                print_warning("Please enter a valid number.")
                    except CancelledException:
                        print_info("\nCancelled. Returning to main menu.")
                elif choice == '10':
                    scaled_id = self.place_scaled_order()
                    if scaled_id:
                        print_success(f"Scaled order placed with ID: {highlight(scaled_id[:8])}...")
                elif choice == '11':
                    self.view_scaled_order_fills()
                elif choice == '12':
                    vwap_id = self.place_vwap_order()
                    if vwap_id:
                        print_success(f"VWAP order completed: {highlight(vwap_id[:8])}...")
                elif choice == '13':
                    self.view_vwap_fills()
                elif choice == '14':
                    self.analytics_display.display_pnl_summary()
                elif choice == '15':
                    self.analytics_display.display_execution_report()
                elif choice == '16':
                    self.analytics_display.display_fee_summary()
                else:
                    print_warning("Invalid choice. Please try again.")
        except Exception as e:
            logging.error(f"Critical error in main execution: {str(e)}", exc_info=True)
        finally:
            self.is_running = False
            if self.websocket_service:
                self.websocket_service.stop()
            if self.checker_thread and self.checker_thread.is_alive():
                self.checker_thread.join(timeout=5)
            if hasattr(self, 'database'):
                self.database.close()
    # End of the TradingTerminal class

def main():
    """Main entry point with enhanced error handling."""
    try:
        logging.info("Starting main() function")
        print("Initializing Coinbase Trading Terminal...")

        terminal = TradingTerminal()
        logging.info("TradingTerminal instance created successfully")

        print("Starting main execution loop...")
        logging.info("Calling terminal.run()")
        terminal.run()

    except KeyboardInterrupt:
        logging.info("Program terminated by user")
        print("\nProgram terminated by user")
    except Exception as e:
        logging.critical(f"Critical error in main execution: {str(e)}", exc_info=True)
        print(f"Critical error occurred: {str(e)}")
    finally:
        logging.info("Program shutting down")

if __name__ == "__main__":
    try:
        logging.info("Starting program from __main__")
        print(f"Current working directory: {os.getcwd()}")
        main()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        logging.critical("Fatal error occurred", exc_info=True)
