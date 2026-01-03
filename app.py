from typing import Optional, Dict, List
from twap_tracker import TWAPTracker, TWAPOrder, OrderFill
import math
import logging
from config import Config, ConfigurationError
from config_manager import AppConfig
from api_client import APIClient, CoinbaseAPIClient
from storage import TWAPStorage, FileBasedTWAPStorage
from validators import InputValidator, ValidationError
import time
import random
import threading
from threading import Lock
from threading import Thread
from queue import Queue, Empty
from tabulate import tabulate
from datetime import datetime, timedelta, timezone
from functools import wraps
from collections import defaultdict
import uuid
import os
from ui_helpers import (
    Colors, success, error, warning, info, highlight,
    format_currency, format_percentage, format_side, format_status,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)

# Configure logging with both file and console output
def setup_logging():
    """Setup logging configuration"""
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Generate log filename with timestamp
    log_filename = f'logs/trading_terminal_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

    # Get the root logger
    root_logger = logging.getLogger()
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Setup file handler (keeps DEBUG level)
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Setup console handler (only shows INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger.setLevel(logging.DEBUG)  # Allow all logs to be processed
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Log the start of the session
    logging.info("="*50)
    logging.info("Starting new trading session")
    logging.info("="*50)

# Call setup_logging at the start
setup_logging()

class CancelledException(Exception):
    """Exception raised when user cancels an operation."""
    pass

class RateLimiter:
    """
    Implements a token bucket rate limiter.
    """
    def __init__(self, rate, burst):
        """
        Initialize rate limiter.
        rate: rate at which tokens are added
        burst: maximum number of tokens
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_check = time.time()
        self.lock = Lock()

    def acquire(self):
        """
        Try to acquire a token.
        Returns True if successful, False otherwise.
        """
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
        """
        Wait until a token is available.
        """
        while not self.acquire():
            time.sleep(0.05)

class TradingTerminal:
    def __init__(self,
                 api_client: Optional[APIClient] = None,
                 twap_storage: Optional[TWAPStorage] = None,
                 config: Optional[AppConfig] = None,
                 start_checker_thread: bool = True):
        """
        Initialize the trading terminal with dependency injection.

        Args:
            api_client: API client implementation (None = will be set during login).
            twap_storage: TWAP storage implementation (None = use file-based storage).
            config: Application configuration (None = load from environment).
            start_checker_thread: Whether to start the background order checker thread.
        """
        logging.info("Initializing TradingTerminal")
        try:
            # Configuration
            self.config = config or AppConfig()
            logging.debug(f"Using configuration: rate_limit={self.config.rate_limit.requests_per_second}/s")

            # API Client (may be None initially, set during login)
            self.client = api_client

            # TWAP Storage
            self.twap_storage = twap_storage or FileBasedTWAPStorage()

            # For backward compatibility, also keep TWAPTracker reference
            if isinstance(self.twap_storage, FileBasedTWAPStorage):
                self.twap_tracker = self.twap_storage._tracker
            else:
                # Create a dummy tracker for in-memory storage
                self.twap_tracker = TWAPTracker()

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
            self.twap_lock = Lock()  # NEW: Dedicated lock for TWAP data
            self.is_running = True

            # Initialize twap_orders before starting the checker thread
            logging.debug("Initializing TWAP tracking dictionaries")
            self.twap_orders = {}
            self.order_to_twap_map = {}

            # Conditional orders tracking
            logging.debug("Initializing conditional order tracking")
            from conditional_order_tracker import ConditionalOrderTracker
            self.conditional_order_tracker = ConditionalOrderTracker()
            self.order_to_conditional_map = {}  # {order_id: (order_type, conditional_id)}
            self.conditional_lock = Lock()

            # Background thread for order status checking
            if start_checker_thread:
                logging.debug("Starting checker thread")
                self.checker_thread = Thread(target=self.order_status_checker)
                self.checker_thread.daemon = True
                logging.debug("Setting checker thread as daemon")
                self.checker_thread.start()
                logging.debug("Checker thread started")
            else:
                self.checker_thread = None
                logging.debug("Checker thread not started (disabled)")

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
            self.fee_tier_cache_ttl = 3600  # Cache for 1 hour (fee tiers change infrequently)

            logging.info("TradingTerminal initialization completed successfully")

        except Exception as e:
            logging.critical(f"Failed to initialize TradingTerminal: {str(e)}", exc_info=True)
            raise

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
            # Add cancel hint to prompt if not already present
            prompt = prompt.rstrip() + " (or 'cancel' to go back): "

        user_input = input(prompt).strip()

        if allow_cancel and user_input.lower() in ['cancel', 'back', 'q', 'quit']:
            logging.debug(f"User cancelled operation with input: {user_input}")
            raise CancelledException("Operation cancelled by user")

        return user_input

    def get_accounts(self, force_refresh=False):
        """Get account information with caching."""
        current_time = time.time()
        if force_refresh or not self.account_cache or (current_time - self.account_cache_time) > self.account_cache_ttl:
            try:
                logging.info("Fetching fresh account data from API")
                all_accounts = []
                cursor = None
                has_next = True  # Initialize to True to enter the loop
                
                while has_next:
                    # Wait for rate limiter before each API call
                    self.rate_limiter.wait()
                    
                    # Make API call with cursor if available
                    accounts_response = self.client.get_accounts(
                        cursor=cursor,
                        limit=250  # Maximum allowed by the API
                    )
                    
                    # Extract accounts using dot notation
                    accounts = accounts_response.accounts
                    all_accounts.extend(accounts)
                    
                    # Update pagination state using dot notation
                    cursor = accounts_response.cursor if hasattr(accounts_response, 'cursor') else ''
                    has_next = accounts_response.has_next
                    
                    # Log pagination info
                    logging.debug(f"Fetched {len(accounts)} accounts. Cursor: {cursor}, Has next: {has_next}")
                    
                    # Break if no cursor for next page
                    if not cursor:
                        break

                # Create account cache using currency as key - with dictionary access for available_balance
                self.account_cache = {
                    account.currency: {
                        'currency': account.currency,
                        'available_balance': {
                            'value': account.available_balance['value'],
                            'currency': account.available_balance['currency']
                        },
                        'type': account.type,
                        'ready': account.ready,
                        'active': account.active
                    } for account in all_accounts if hasattr(account, 'currency')
                }
                self.account_cache_time = current_time
                
                logging.info(f"Fetched {len(all_accounts)} accounts total")
                return self.account_cache
                
            except Exception as e:
                logging.error(f"Error fetching accounts: {str(e)}", exc_info=True)
                return {}
                
        return self.account_cache

    def get_account_balance(self, currency):
        """Get account balance for a specific currency."""
        logging.debug(f"get_account_balance called for currency: {currency}")
        accounts = self.get_accounts()
        
        if currency in accounts:
            account = accounts[currency]
            balance = float(account['available_balance']['value'])
            logging.info(f"Retrieved balance for {currency}: {balance}")
            return balance
            
        logging.warning(f"No account found for currency: {currency}")
        return 0

    def get_bulk_prices(self, product_ids: List[str]) -> Dict[str, float]:
        """
        Get prices for multiple products in a single API call.

        This method fetches all products at once and extracts prices for the
        requested product IDs, significantly reducing API calls compared to
        fetching each product individually.

        Args:
            product_ids: List of product IDs to fetch prices for (e.g., ['BTC-USD', 'ETH-USD']).

        Returns:
            Dictionary mapping product_id to price (float).

        Example:
            >>> prices = terminal.get_bulk_prices(['BTC-USD', 'ETH-USD', 'SOL-USD'])
            >>> print(prices['BTC-USD'])
            50000.0
        """
        prices = {}

        try:
            logging.debug(f"Fetching bulk prices for {len(product_ids)} products")
            self.rate_limiter.wait()

            # Single API call to get all products
            products_response = self.client.get_products()

            # The response is an object with a 'products' attribute, not a dict
            products = products_response.products if hasattr(products_response, 'products') else []

            # Extract prices for requested product IDs
            for product in products:
                # Product is also an object, not a dict
                product_id = getattr(product, 'product_id', None)
                if product_id and product_id in product_ids:
                    try:
                        price = getattr(product, 'price', 0)
                        prices[product_id] = float(price)
                        logging.debug(f"Got price for {product_id}: {prices[product_id]}")
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Could not parse price for {product_id}: {e}")

            logging.info(f"Successfully fetched {len(prices)} prices out of {len(product_ids)} requested")

        except Exception as e:
            logging.error(f"Error fetching bulk prices: {str(e)}", exc_info=True)

        return prices

    def get_current_prices(self, product_id: str):
        """Get current bid, ask, and mid prices for a product."""
        try:
            product_book = self.client.get_product_book(product_id, limit=1)
            pricebook = product_book['pricebook']  # Direct dictionary access
            
            if pricebook['bids'] and pricebook['asks']:  # Direct dictionary access
                bid = float(pricebook['bids'][0]['price'])
                ask = float(pricebook['asks'][0]['price'])
                mid = (bid + ask) / 2
                return {'bid': bid, 'mid': mid, 'ask': ask}
                
            logging.warning(f"Incomplete order book data for {product_id}")
            return None
            
        except Exception as e:
            logging.error(f"Error fetching current prices for {product_id}: {str(e)}")
            return None

    def check_order_fills_batch(self, order_ids):
        """Check fills for multiple orders efficiently.
        Returns a dictionary mapping order IDs to their fill information.
        """
        if not order_ids:
            return {}

        try:
            fills_response = self.client.get_fills(order_ids=order_ids)
            if not hasattr(fills_response, 'fills'):
                logging.warning("No fills data in response")
                return {}
                
            fills = fills_response.fills
            
            fills_by_order = defaultdict(lambda: {
                'filled_size': 0.0,
                'filled_value': 0.0,
                'fees': 0.0,
                'is_maker': False,
                'average_price': 0.0,
                'status': 'UNKNOWN'
            })

            # First pass: accumulate fill data
            for fill in fills:
                order_id = fill.order_id
                fill_size = float(fill.size)
                fill_price = float(fill.price)
                fill_value = fill_size * fill_price
                fill_fee = float(fill.fee) if hasattr(fill, 'fee') else 0
                is_maker = getattr(fill, 'liquidity_indicator', '') == 'M'

                order_data = fills_by_order[order_id]
                order_data['filled_size'] += fill_size
                order_data['filled_value'] += fill_value
                order_data['fees'] += fill_fee
                order_data['is_maker'] |= is_maker

            # Second pass: calculate average prices and determine status
            for order_id, data in fills_by_order.items():
                if data['filled_size'] > 0:
                    data['average_price'] = data['filled_value'] / data['filled_size']
                    data['status'] = 'FILLED'
                else:
                    data['status'] = 'UNFILLED'

            return fills_by_order
                
        except Exception as e:
            logging.error(f"Error checking fills batch: {str(e)}")
            return {}

    def get_consolidated_markets(self, limit=20):
        """Get top markets by 24h USD volume, consolidating USD and USDC pairs.
        
        Args:
            limit (int): Number of top markets to return. Defaults to 20.
        """
        try:
            products_response = self.client.get_products()
            products = products_response['products']  # Direct dictionary access
            
            # Group products by base currency
            consolidated = {}
            for product in products:
                product_id = product['product_id']
                base_currency = product_id.split('-')[0]
                quote_currency = product_id.split('-')[1]
                
                # Only process USD and USDC pairs
                if quote_currency not in ['USD', 'USDC']:
                    continue
                    
                try:
                    volume = float(product['volume_24h'])
                    price = float(product['price'])
                    usd_volume = volume * price
                except (KeyError, ValueError):
                    continue
                    
                if base_currency not in consolidated:
                    consolidated[base_currency] = {
                        'total_volume': 0,
                        'has_usd': False,
                        'has_usdc': False,
                        'usd_product': None,
                        'usdc_product': None
                    }
                
                consolidated[base_currency]['total_volume'] += usd_volume
                if quote_currency == 'USD':
                    consolidated[base_currency]['has_usd'] = True
                    consolidated[base_currency]['usd_product'] = product_id
                else:  # USDC
                    consolidated[base_currency]['has_usdc'] = True
                    consolidated[base_currency]['usdc_product'] = product_id

            # Sort by total volume and take top N
            top_markets = sorted(
                [(k, v) for k, v in consolidated.items() if v['has_usd'] or v['has_usdc']], 
                key=lambda x: x[1]['total_volume'], 
                reverse=True
            )[:limit]

            # Format into rows for display
            NUM_COLUMNS = 4
            rows = []
            current_row = []
            
            for i, (base_currency, data) in enumerate(top_markets, 1):
                volume_millions = data['total_volume'] / 1_000_000
                market_info = [
                    f"{i}.",
                    f"{base_currency}-USD(C)",
                    f"${volume_millions:.2f}M"
                ]
                current_row.extend(market_info)
                
                if i % NUM_COLUMNS == 0:
                    rows.append(current_row)
                    current_row = []
            
            # Add any remaining items in the last row
            if current_row:
                while len(current_row) < NUM_COLUMNS * 3:
                    current_row.extend(['', '', ''])
                rows.append(current_row)

            headers = []
            for i in range(NUM_COLUMNS):
                headers.extend(['#', 'Market', 'Volume'])

            return rows, headers, top_markets

        except Exception as e:
            logging.error(f"Error fetching consolidated markets: {str(e)}")
            return [], [], []

    def _select_market(self) -> Optional[str]:
        """
        Interactive market selection from top 20 markets by volume.
        Prompts user to select market and quote currency.

        Returns:
            str: Selected product_id (e.g., 'BTC-USDC')
            None: If market data unavailable

        Raises:
            CancelledException: If user cancels selection
        """
        # Get market data
        logging.debug("Fetching market data")
        rows, headers, top_markets = self.get_consolidated_markets(20)

        if not rows:
            logging.error("Failed to fetch top markets")
            print("Error fetching market data. Please try again.")
            return None

        print("\nTop Markets by 24h Volume:")
        print("=" * 120)
        print(tabulate(rows, headers=headers, tablefmt="plain", numalign="left"))
        print("=" * 120)

        # Get market selection
        logging.debug("Getting market selection")
        while True:
            product_choice = self.get_input("\nEnter the number of the market to trade (1-20)")
            logging.debug(f"User selected market number: {product_choice}")
            try:
                index = int(product_choice)
                if 1 <= index <= len(top_markets):
                    base_currency, market_data = top_markets[index - 1]

                    # Handle quote currency selection
                    logging.debug(f"Processing quote currency selection for {base_currency}")
                    available_quotes = []
                    if market_data['has_usd']:
                        available_quotes.append('USD')
                    if market_data['has_usdc']:
                        available_quotes.append('USDC')

                    if len(available_quotes) > 1:
                        print(f"\nAvailable quote currencies for {base_currency}:")
                        for i, quote in enumerate(available_quotes, 1):
                            print(f"{i}. {quote}")

                        while True:
                            quote_choice = self.get_input(f"Select quote currency (1-{len(available_quotes)})")
                            logging.debug(f"User selected quote currency option: {quote_choice}")
                            try:
                                quote_index = int(quote_choice)
                                if 1 <= quote_index <= len(available_quotes):
                                    quote_currency = available_quotes[quote_index - 1]
                                    break
                                else:
                                    print(f"Please enter a number between 1 and {len(available_quotes)}")
                            except ValueError:
                                print("Please enter a valid number")
                    else:
                        quote_currency = available_quotes[0]

                    product_id = f"{base_currency}-{quote_currency}"
                    if quote_currency == 'USD':
                        product_id = market_data['usd_product']
                    else:
                        product_id = market_data['usdc_product']

                    logging.debug(f"Final product_id selected: {product_id}")
                    return product_id
                else:
                    print("Invalid selection. Please enter a number between 1 and 20.")
            except ValueError:
                print("Please enter a valid number.")

    def _register_twap_order(self, twap_id: str, order_id: str):
        """
        Thread-safe TWAP order registration.

        Args:
            twap_id: The TWAP order ID.
            order_id: The individual order ID to register.
        """
        with self.twap_lock:
            self.order_to_twap_map[order_id] = twap_id
            if twap_id not in self.twap_orders:
                self.twap_orders[twap_id] = {
                    'total_filled': 0.0,
                    'total_value_filled': 0.0,
                    'total_fees': 0.0,
                    'maker_orders': 0,
                    'taker_orders': 0,
                    'orders': []
                }
            logging.debug(f"Registered order {order_id} for TWAP {twap_id}")

    def place_limit_order(self):
        """Place a limit order with user input."""
        if not self.client:
            logging.warning("Attempt to place limit order without login")
            print_warning("Please login first.")
            return

        logging.debug("Starting limit order placement")

        try:
            # Outer try block to catch cancellations
            return self._place_limit_order_impl()
        except CancelledException:
            logging.info("Limit order placement cancelled by user")
            print_info("\nOrder placement cancelled. Returning to main menu.")
            return None

    def _place_limit_order_impl(self):
        """Internal implementation of place_limit_order with cancellation support."""
        try:
            # Get market selection
            product_id = self._select_market()
            if not product_id:
                return

            # Get side
            while True:
                side = self.get_input("\nEnter order side (buy/sell)").upper()
                logging.debug(f"User selected side: {side}")
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            # Get current prices and show balances
            current_prices = self.get_current_prices(product_id)
            base_currency = product_id.split('-')[0]
            quote_currency = product_id.split('-')[1]

            # Get balances with rate limiting
            logging.debug(f"Fetching balances for {base_currency} and {quote_currency}")
            self.rate_limiter.wait()
            base_balance = self.get_account_balance(base_currency)
            self.rate_limiter.wait()
            quote_balance = self.get_account_balance(quote_currency)
            
            print("\nCurrent Market Conditions:")
            print("=" * 50)

            if current_prices:
                print(f"Current prices for {product_id}:")
                print(f"Bid: ${current_prices['bid']:.2f}")
                print(f"Ask: ${current_prices['ask']:.2f}")
                print(f"Mid: ${current_prices['mid']:.2f}")
                print("-" * 50)

                try:
                    if side == 'BUY':
                        potential_size = quote_balance / current_prices['ask']  # Use ask price for buying
                        print(f"Available {quote_currency}: {quote_balance:.2f}")
                        print(f"Maximum {base_currency} you can buy at current ask: {potential_size:.8f}")
                        
                        # Show example trade sizes at different percentages
                        print("\nExample trade sizes:")
                        percentages = [25, 50, 75, 100]
                        for pct in percentages:
                            size = (potential_size * pct) / 100
                            cost = size * current_prices['ask']
                            print(f"{pct}% - Size: {size:.8f} {base_currency} (Cost: ${cost:.2f} {quote_currency})")
                    else:  # SELL
                        potential_value = base_balance * current_prices['bid']  # Use bid price for selling
                        print(f"Available {base_currency}: {base_balance:.8f}")
                        print(f"Total value at current bid: ${potential_value:.2f}")
                        
                        # Show example trade sizes at different percentages
                        print("\nExample trade sizes:")
                        percentages = [25, 50, 75, 100]
                        for pct in percentages:
                            size = (base_balance * pct) / 100
                            value = size * current_prices['bid']
                            print(f"{pct}% - Size: {size:.8f} {base_currency} (Value: ${value:.2f} {quote_currency})")
                    
                    print("=" * 50)
                except Exception as e:
                    logging.error(f"Error calculating trade sizes: {str(e)}")
                    print("\nError calculating trade sizes. Proceeding with order placement.")

            # Get limit price
            while True:
                try:
                    limit_price = float(self.get_input("\nEnter limit price"))
                    logging.debug(f"User entered limit price: {limit_price}")
                    if limit_price <= 0:
                        print("Price must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get order size
            while True:
                try:
                    base_size = float(self.get_input("\nEnter order size"))
                    logging.debug(f"User entered base size: {base_size}")
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get actual fee rates
            maker_rate, taker_rate = self.get_fee_rates()

            # Calculate estimated fee
            estimated_fee_maker = self.calculate_estimated_fee(base_size, limit_price, is_maker=True)
            estimated_fee_taker = self.calculate_estimated_fee(base_size, limit_price, is_maker=False)

            # Show order summary with fee estimates
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
            logging.debug(f"User confirmation: {confirm}")

            if confirm != 'yes':
                logging.info("Order cancelled by user")
                print("Order cancelled.")
                return

            # Place the order
            logging.debug("Placing limit order")
            order_response = self.place_limit_order_with_retry(
                product_id=product_id,
                side=side,
                base_size=str(base_size),
                limit_price=str(limit_price),
                client_order_id=f"limit-{int(time.time())}"
            )

            logging.debug(f"Order response received: {order_response}")

            if order_response:
                try:
                    # Extract order ID from the response structure
                    if 'success_response' in order_response:
                        order_id = order_response['success_response']['order_id']
                    elif 'order_id' in order_response:
                        order_id = order_response['order_id']
                    else:
                        logging.error("Could not find order ID in response")
                        print("\nError: Could not find order ID in response")
                        return None

                    logging.info(f"Limit order placed successfully. Order ID: {order_id}")
                    print_success("\nOrder placed successfully!")
                    print(f"Order ID: {highlight(order_id)}")
                    
                    # Explicitly return without any further processing
                    logging.debug("Returning from place_limit_order with order ID")
                    return order_id
                    
                except Exception as e:
                    logging.error(f"Error processing order response: {str(e)}")
                    print("\nError processing order response")
                    return None
            else:
                logging.error("Failed to place limit order")
                print("\nFailed to place order. Please try again.")
                return None

        except CancelledException:
            # Already handled in outer try-catch, just re-raise
            raise
        except Exception as e:
            logging.error(f"Error in place_limit_order: {str(e)}", exc_info=True)
            print_error(f"\nError placing order: {str(e)}")
            return None
        finally:
            logging.debug("Exiting place_limit_order function")

    def update_twap_fills(self, twap_id: str) -> bool:
        """Update fill information for a TWAP order with fee calculations."""
        try:
            # Get the TWAP order
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                logging.warning(f"TWAP order {twap_id} not found")
                return False

            # Get current fee rates using cached method
            maker_rate, taker_rate = self.get_fee_rates()
            logging.info(f"Using fee rates for TWAP fills - Maker: {maker_rate:.4%}, Taker: {taker_rate:.4%}")

            # Get fills for all orders
            fills = []
            total_filled = 0.0
            total_value_filled = 0.0
            total_fees = 0.0
            maker_orders = 0
            taker_orders = 0

            for order_id in twap_order.orders:
                try:
                    # Rate limit handling
                    self.rate_limiter.wait()
                    
                    order_fills = self.client.get_fills(order_ids=[order_id])
                    if not hasattr(order_fills, 'fills'):
                        continue

                    for fill in order_fills.fills:
                        is_maker = getattr(fill, 'liquidity_indicator', '') == 'MAKER'
                        fill_size = float(fill.size)
                        fill_price = float(fill.price)
                        fill_value = fill_size * fill_price
                        
                        # Calculate fee based on maker/taker status
                        fee = fill_value * (maker_rate if is_maker else taker_rate)
                        
                        fills.append(OrderFill(
                            order_id=fill.order_id,
                            trade_id=fill.trade_id,
                            filled_size=fill_size,
                            price=fill_price,
                            fee=fee,
                            is_maker=is_maker,
                            trade_time=fill.trade_time
                        ))
                        
                        # Update totals
                        total_filled += fill_size
                        total_value_filled += fill_value
                        total_fees += fee
                        if is_maker:
                            maker_orders += 1
                        else:
                            taker_orders += 1

                except Exception as e:
                    logging.error(f"Error processing fills for order {order_id}: {str(e)}")
                    continue

            # Save updated fills
            self.twap_tracker.save_twap_fills(twap_id, fills)

            # Update TWAP order status
            twap_order.total_filled = total_filled
            twap_order.total_value_filled = total_value_filled
            twap_order.total_fees = total_fees
            twap_order.maker_orders = maker_orders
            twap_order.taker_orders = taker_orders

            if total_filled >= twap_order.total_size:
                twap_order.status = 'completed'
            elif total_filled > 0:
                twap_order.status = 'partially_filled'

            self.twap_tracker.save_twap_order(twap_order)
            
            # Log update summary
            logging.info(f"Updated TWAP {twap_id} fills:")
            logging.info(f"Total filled: {total_filled:.8f}")
            logging.info(f"Total value: ${total_value_filled:.2f}")
            logging.info(f"Total fees: ${total_fees:.2f}")
            logging.info(f"Maker/Taker ratio: {maker_orders}/{taker_orders}")

            return True

        except Exception as e:
            logging.error(f"Error updating TWAP fills: {str(e)}")
            return False
        
    def place_limit_order_with_retry(self, product_id, side, base_size, limit_price, client_order_id=None):
        """Place a limit order with enhanced error handling and validation."""
        logging.debug("Entering place_limit_order_with_retry")
        try:
            # Pre-order validation
            if float(base_size) <= 0:
                raise ValueError("Order size must be greater than 0")
                
            # Get minimum order size for the product
            product_info = self.client.get_product(product_id)
            # Product info is an object, not a dict
            base_min_size = float(getattr(product_info, 'base_min_size', 0.0001))
            base_max_size = float(getattr(product_info, 'base_max_size', 1000000))
            quote_increment = float(getattr(product_info, 'quote_increment', 0.01))
            
            # Validate order size
            if float(base_size) < base_min_size:
                error_msg = f"Order size {base_size} is below minimum {base_min_size} for {product_id}"
                logging.warning(error_msg)
                print(f"\nError: {error_msg}")
                return None

            if float(base_size) > base_max_size:
                error_msg = f"Order size {base_size} is above maximum {base_max_size} for {product_id}"
                logging.warning(error_msg)
                print(f"\nError: {error_msg}")
                return None
                
            # Round price to appropriate increment
            rounded_price = round(float(limit_price) / quote_increment) * quote_increment
            
            # Get available balance
            if side == "BUY":
                quote_currency = product_id.split('-')[1]
                required_funds = float(base_size) * float(limit_price)
                available_balance = self.get_account_balance(quote_currency)
                if available_balance < required_funds:
                    error_msg = f"Insufficient {quote_currency} balance. Need {required_funds:.2f}, have {available_balance:.2f}"
                    logging.warning(error_msg)
                    print(f"\nError: {error_msg}")
                    return None
            else:
                base_currency = product_id.split('-')[0]
                available_balance = self.get_account_balance(base_currency)
                if available_balance < float(base_size):
                    error_msg = f"Insufficient {base_currency} balance. Need {float(base_size):.8f}, have {available_balance:.8f}"
                    logging.warning(error_msg)
                    print(f"\nError: {error_msg}")
                    return None

            logging.debug("Placing limit order with Coinbase API")
            # Place the order
            order_response = self.client.limit_order_gtc(
                client_order_id=client_order_id or f"limit-order-{int(time.time())}",
                product_id=product_id,
                side=side,
                base_size=str(self.round_size(base_size, product_id)),
                limit_price=str(self.round_price(rounded_price, product_id))
            )
            
            try:
                logging.debug(f"Received response from Coinbase API: {order_response}")
                logging.debug(f"Response type: {type(order_response)}")
                                
                if order_response:
                    logging.debug("order_response exists")
                    
                    # Check if the order was successful
                    if hasattr(order_response, 'success') and order_response.success:
                        logging.info("Limit order placed successfully")
                        logging.debug("Exiting place_limit_order_with_retry with success")
                        return order_response.to_dict()  # Convert to dictionary for consistent handling
                    
                    # Check for error response
                    if hasattr(order_response, 'error_response') and order_response.error_response:
                        error_msg = order_response.error_response.get('message', 'Unknown error')
                        logging.error(f"Order placement failed: {error_msg}")
                        return None
                
                logging.error(f"Unexpected order response format: {order_response}")
                logging.debug("Exiting place_limit_order_with_retry with failure")
                return None

            except Exception as e:
                logging.error(f"Exception in handling order response: {str(e)}", exc_info=True)
                return None
            
        except Exception as e:
            logging.error(f"Error placing limit order: {str(e)}")
            logging.debug("Exiting place_limit_order_with_retry with exception")
            return None

    def place_twap_slice(self, twap_id: str, slice_number: int, total_slices: int, 
                        order_input: dict, execution_price: float) -> Optional[str]:
        """Place a single TWAP slice with comprehensive error handling."""
        try:
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                logging.error(f"TWAP order {twap_id} not found")
                return None

            # Calculate slice size
            total_target = float(order_input["base_size"])
            total_placed = sum(1 for _ in twap_order.orders)
            remaining_quantity = total_target - total_placed

            if slice_number == total_slices:
                slice_size = remaining_quantity
            else:
                slice_size = total_target / total_slices

            # Validate minimum slice size
            product_info = self.client.get_product(order_input["product_id"])
            min_size = float(product_info['base_min_size'])
            
            # Round size and price to appropriate precision
            rounded_size = self.round_size(slice_size, order_input["product_id"])
            rounded_price = self.round_price(execution_price, order_input["product_id"])
            
            if rounded_size < min_size:
                logging.warning(f"Slice size {rounded_size} is below minimum {min_size}. Adjusting to minimum.")
                rounded_size = min_size

            # Generate unique client order ID
            client_order_id = f"twap-{twap_id}-{slice_number}-{int(time.time())}"

            # Place the order with retry
            order_response = self.place_limit_order_with_retry(
                product_id=order_input["product_id"],
                side=order_input["side"],
                base_size=str(rounded_size),
                limit_price=str(rounded_price),
                client_order_id=client_order_id
            )

            if not order_response:
                logging.error("Failed to place slice order")
                return None

            # Extract order ID using dot notation or dict access as appropriate
            if isinstance(order_response, dict):
                order_id = (order_response.get('success_response', {}).get('order_id') or 
                        order_response.get('order_id'))
            else:
                order_id = (getattr(order_response.success_response, 'order_id', None) if 
                        hasattr(order_response, 'success_response') else 
                        getattr(order_response, 'order_id', None))

            if not order_id:
                logging.error("Could not extract order ID from response")
                return None

            logging.info(f"Successfully placed slice {slice_number}/{total_slices}")
            logging.info(f"Order ID: {order_id}")
            logging.info(f"Size: {rounded_size}")
            logging.info(f"Price: {rounded_price}")

            return order_id

        except Exception as e:
            logging.error(f"Error placing TWAP slice: {str(e)}")
            return None

    def get_active_orders(self):
        """Get list of active orders."""
        try:
            orders_response = self.client.list_orders()

            # Use dot notation instead of dictionary access
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
        """
        Get historical orders with optional filters.

        Args:
            limit: Maximum number of orders to retrieve (default 100)
            product_id: Filter by specific product (e.g., 'BTC-USDC')
            order_status: Filter by order status list (e.g., ['FILLED', 'CANCELLED'])

        Returns:
            List of historical order objects
        """
        try:
            logging.info(f"Fetching order history (limit={limit}, product={product_id}, status={order_status})")

            self.rate_limiter.wait()

            # Fetch all orders (API doesn't support filtering parameters)
            orders_response = self.client.list_orders()

            if not hasattr(orders_response, 'orders'):
                logging.warning("No orders field found in response")
                return []

            all_orders = orders_response.orders

            # Apply filters in Python
            filtered_orders = []
            for order in all_orders:
                # Filter by product_id
                if product_id and order.product_id != product_id:
                    continue

                # Filter by order_status
                if order_status and order.status not in order_status:
                    continue

                filtered_orders.append(order)

                # Stop if we've reached the limit
                if len(filtered_orders) >= limit:
                    break

            logging.info(f"Retrieved {len(filtered_orders)} orders (from {len(all_orders)} total)")
            return filtered_orders

        except Exception as e:
            logging.error(f"Error fetching order history: {str(e)}", exc_info=True)
            return []

    def get_fee_rates(self, force_refresh: bool = False):
        """
        Get current fee rates for the account with caching.

        Args:
            force_refresh: Force refresh even if cached data is available

        Returns:
            Tuple of (maker_rate, taker_rate) as floats
        """
        current_time = time.time()

        # Check cache
        if not force_refresh and self.fee_tier_cache and (current_time - self.fee_tier_cache_time) < self.fee_tier_cache_ttl:
            logging.debug(f"Using cached fee rates: {self.fee_tier_cache}")
            return self.fee_tier_cache

        try:
            logging.info("Fetching fee tier information from API")
            self.rate_limiter.wait()

            fee_info = self.client.get_transaction_summary()
            logging.debug(f"Transaction summary response type: {type(fee_info)}")
            logging.debug(f"Transaction summary response: {fee_info}")

            # Try different ways to access fee tier
            maker_rate = 0.006  # Default conservative estimate
            taker_rate = 0.006  # Default conservative estimate

            # Method 1: Try as object attribute
            if hasattr(fee_info, 'fee_tier'):
                fee_tier = fee_info.fee_tier
                logging.debug(f"Fee tier type: {type(fee_tier)}")
                logging.debug(f"Fee tier content: {fee_tier}")

                # Check if it's a dict
                if isinstance(fee_tier, dict):
                    maker_rate = float(fee_tier.get('maker_fee_rate', 0.006))
                    taker_rate = float(fee_tier.get('taker_fee_rate', 0.006))
                    logging.info(f"Parsed fee rates from dict - Maker: {maker_rate:.4%}, Taker: {taker_rate:.4%}")
                # Check if it's an object with attributes
                elif hasattr(fee_tier, 'maker_fee_rate') and hasattr(fee_tier, 'taker_fee_rate'):
                    maker_rate = float(fee_tier.maker_fee_rate)
                    taker_rate = float(fee_tier.taker_fee_rate)
                    logging.info(f"Parsed fee rates from object - Maker: {maker_rate:.4%}, Taker: {taker_rate:.4%}")
                else:
                    logging.warning(f"Fee tier has unexpected format: {type(fee_tier)}")

            # Method 2: Try as dict
            elif isinstance(fee_info, dict) and 'fee_tier' in fee_info:
                fee_tier = fee_info['fee_tier']
                if isinstance(fee_tier, dict):
                    maker_rate = float(fee_tier.get('maker_fee_rate', 0.006))
                    taker_rate = float(fee_tier.get('taker_fee_rate', 0.006))
                    logging.info(f"Parsed fee rates from response dict - Maker: {maker_rate:.4%}, Taker: {taker_rate:.4%}")

            # Cache the result
            self.fee_tier_cache = (maker_rate, taker_rate)
            self.fee_tier_cache_time = current_time

            logging.info(f"Fee rates cached: Maker={maker_rate:.4%}, Taker={taker_rate:.4%}")
            return (maker_rate, taker_rate)

        except Exception as e:
            logging.error(f"Error fetching fee rates: {str(e)}", exc_info=True)
            # Return conservative default
            default_rates = (0.006, 0.006)
            logging.warning(f"Using default fee rates: {default_rates}")
            return default_rates

    def calculate_estimated_fee(self, size: float, price: float, is_maker: bool = True) -> float:
        """
        Calculate estimated fee for an order.

        Args:
            size: Order size
            price: Order price
            is_maker: Whether order is likely to be a maker order (default True for limit orders)

        Returns:
            Estimated fee in USD
        """
        try:
            maker_rate, taker_rate = self.get_fee_rates()
            order_value = size * price
            fee_rate = maker_rate if is_maker else taker_rate
            estimated_fee = order_value * fee_rate

            logging.debug(f"Estimated fee: ${estimated_fee:.2f} ({fee_rate:.4%} of ${order_value:.2f})")
            return estimated_fee

        except Exception as e:
            logging.error(f"Error calculating fee: {str(e)}", exc_info=True)
            # Fallback to conservative estimate
            return size * price * 0.006

    def view_order_history(self):
        """Display order history with filters and colored output."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            print_header("Order History")

            # Ask user for filters
            print("\nFilter options:")
            print("1. All orders (last 100)")
            print("2. Filter by product")
            print("3. Filter by status")
            print("4. Filter by product and status")

            try:
                filter_choice = self.get_input("Select filter option (1-4)")
            except CancelledException:
                print_info("Cancelled. Returning to main menu.")
                return

            product_id = None
            order_status = None

            # Handle filter selection
            if filter_choice in ['2', '4']:
                product_id = self._select_market()
                if not product_id:
                    return

            if filter_choice in ['3', '4']:
                print("\nStatus filter:")
                print("1. FILLED")
                print("2. CANCELLED")
                print("3. EXPIRED")
                print("4. FAILED")
                print("5. All completed (FILLED, CANCELLED, EXPIRED)")

                try:
                    status_choice = self.get_input("Select status filter (1-5)")
                except CancelledException:
                    print_info("Cancelled. Returning to main menu.")
                    return

                status_map = {
                    '1': ['FILLED'],
                    '2': ['CANCELLED'],
                    '3': ['EXPIRED'],
                    '4': ['FAILED'],
                    '5': ['FILLED', 'CANCELLED', 'EXPIRED']
                }
                order_status = status_map.get(status_choice, None)

            # Fetch orders
            print_info("\nFetching order history...")
            orders = self.get_order_history(
                limit=100,
                product_id=product_id,
                order_status=order_status
            )

            if not orders:
                print_warning("No orders found matching the criteria.")
                return

            # Display orders in a table
            table_data = []
            for order in orders:
                # Extract order details
                order_config = order.order_configuration
                config_type = next(iter(vars(order_config)))
                config = getattr(order_config, config_type)

                size = getattr(config, 'base_size', 'N/A')
                price = getattr(config, 'limit_price', getattr(config, 'market_market_ioc', {}).get('quote_size', 'N/A'))

                # Calculate order value if possible
                try:
                    if size != 'N/A' and price != 'N/A':
                        value = float(size) * float(price)
                        value_str = format_currency(value, colored=True)
                    else:
                        value_str = 'N/A'
                except:
                    value_str = 'N/A'

                # Format created time
                created_time = datetime.fromisoformat(order.created_time.replace('Z', '+00:00'))
                time_str = created_time.strftime("%Y-%m-%d %H:%M:%S")

                # Truncate order ID for display
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

            # Summary statistics
            filled_orders = [o for o in orders if o.status == 'FILLED']
            cancelled_orders = [o for o in orders if o.status == 'CANCELLED']

            print_subheader("\nSummary:")
            print(f"Total Orders: {len(orders)}")
            print(f"{format_status('FILLED')}: {len(filled_orders)}")
            print(f"{format_status('CANCELLED')}: {len(cancelled_orders)}")

        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
        except Exception as e:
            logging.error(f"Error viewing order history: {str(e)}", exc_info=True)
            print_error(f"Error viewing order history: {str(e)}")

    def show_and_cancel_orders(self):
        """Display active orders and allow cancellation."""
        if not self.client:
            logging.warning("Attempt to show/cancel orders without login")
            print_warning("Please login first.")
            return

        try:
            self._show_and_cancel_orders_impl()
        except CancelledException:
            logging.info("Show and cancel orders cancelled by user")
            print_info("\nCancelled. Returning to main menu.")

    def _show_and_cancel_orders_impl(self):
        """Internal implementation of show_and_cancel_orders with cancellation support."""
        try:
            active_orders = self.get_active_orders()

            if not active_orders:
                logging.info("No active orders found")
                print_info("No active orders found.")
                return

            # Display orders
            table_data = []
            for i, order in enumerate(active_orders, 1):
                order_config = order.order_configuration
                config_type = next(iter(vars(order_config)))
                config = getattr(order_config, config_type)
                
                size = getattr(config, 'base_size', 'N/A')
                price = getattr(config, 'limit_price', 'N/A')
                
                table_data.append([
                    i,
                    order.order_id,
                    order.product_id,
                    format_side(order.side),
                    size,
                    price,
                    format_status(order.status)
                ])

            print_header("\nActive Orders")
            print(tabulate(table_data, headers=["Number", "Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))

            while True:
                action = self.get_input("\nWould you like to cancel any orders? (yes/no/all)").lower()

                if action == 'no':
                    break
                elif action == 'all':
                    order_ids = [order.order_id for order in active_orders]
                    result = self.client.cancel_orders(order_ids)
                    if hasattr(result, 'results'):
                        cancelled_count = len(result.results)
                        logging.info(f"Cancelled {cancelled_count} orders")
                        print_success(f"Cancelled {cancelled_count} orders.")
                    break
                elif action == 'yes':
                    order_number = self.get_input("Enter the Number of the order to cancel")
                    try:
                        order_index = int(order_number) - 1
                        if 0 <= order_index < len(active_orders):
                            order_id = active_orders[order_index].order_id
                            result = self.client.cancel_orders([order_id])

                            if result and hasattr(result, 'results') and result.results:
                                logging.info(f"Order {order_id} cancelled successfully")
                                print_success(f"Order {order_id} cancelled successfully.")
                                active_orders = self.get_active_orders()
                                if not active_orders:
                                    break
                            else:
                                logging.error(f"Failed to cancel order {order_id}")
                                print_error(f"Failed to cancel order {order_id}.")
                        else:
                            print_warning("Invalid order number.")
                    except ValueError:
                        print_warning("Please enter a valid order number.")
                else:
                    print_warning("Invalid input. Please enter 'yes', 'no', or 'all'.")

        except Exception as e:
            logging.error(f"Error managing orders: {str(e)}")
            print_error(f"Error managing orders: {str(e)}")        

    def view_portfolio(self):
        """View and display the user's portfolio."""
        if not self.client:
            logging.warning("Attempt to view portfolio without login")
            print_warning("Please login first.")
            return

        try:
            logging.info("Fetching accounts for portfolio view")
            print_info("\nFetching accounts (this may take a moment due to rate limiting)...")
            accounts = self.get_accounts(force_refresh=True)
            self.display_portfolio(accounts)
        except Exception as e:
            logging.error(f"Error fetching portfolio: {str(e)}")
            print_error(f"Error fetching portfolio: {str(e)}")

    def display_portfolio(self, accounts_data):
        """
        Display the portfolio data with optimized price fetching.

        Uses bulk price fetching to reduce API calls from N to 1,
        where N is the number of non-stablecoin assets.
        """
        portfolio_data = []
        total_usd_value = 0

        # Stablecoins that are treated as $1 USD
        stablecoins = {'USD', 'USDC', 'USDT', 'DAI'}

        # First pass: identify currencies needing price lookup
        currencies_needing_prices = []
        for currency, account in accounts_data.items():
            balance = float(account['available_balance']['value'])
            if balance > 0 and currency not in stablecoins:
                currencies_needing_prices.append(currency)

        # Bulk price lookup - SINGLE API CALL instead of N calls
        product_ids = [f"{currency}-USD" for currency in currencies_needing_prices]
        prices = self.get_bulk_prices(product_ids) if product_ids else {}

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

    def login(self):
        """Authenticate user and initialize the API client."""
        logging.info("Initiating login process")
        print_header("Welcome to the Coinbase Trading Terminal!")
        print_info("Authenticating with Coinbase API...")

        try:
            # If client already provided via dependency injection, skip initialization
            if self.client is not None:
                logging.info("API client already initialized via dependency injection")
                print("Login successful!")
                return True

            logging.debug("Attempting to retrieve API credentials from environment")
            config = Config()
            api_key = config.api_key
            api_secret = config.api_secret

            logging.debug("Checking API credentials")
            if not api_key or not api_secret:
                raise ValueError("API key or secret not found")

            logging.debug("Initializing API client")
            self.client = CoinbaseAPIClient(
                api_key=api_key,
                api_secret=api_secret,
                verbose=False
            )

            logging.debug("Waiting for rate limiter")
            self.rate_limiter.wait()

            logging.debug("Making test authentication request")
            test_response = self.client.get_accounts()

            logging.debug(f"Authentication response received: {test_response}")

            # Access test_response.accounts which should be a list
            if not hasattr(test_response, 'accounts'):
                logging.error(f"Response missing accounts field")
                raise Exception("Failed to authenticate with API - 'accounts' not in response")

            # If we get here, authentication was successful
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

    def order_status_checker(self):
        """Background thread to check order statuses efficiently."""
        logging.debug("Starting order_status_checker thread")

        while self.is_running:
            try:
                # Check if there are any orders to monitor
                has_orders = False
                with self.twap_lock:
                    has_orders = bool(self.twap_orders)
                with self.conditional_lock:
                    has_orders = has_orders or bool(self.order_to_conditional_map)

                if not has_orders:
                    time.sleep(5)
                    continue

                try:
                    order = self.order_queue.get(timeout=0.5)

                    if order is None:
                        logging.debug("Received shutdown signal")
                        return

                    logging.debug(f"Retrieved order from queue: {order}")

                    # Thread-safe check for TWAP order
                    with self.twap_lock:
                        is_twap_order = order.get('order_id') in self.order_to_twap_map

                    # Thread-safe check for conditional order
                    with self.conditional_lock:
                        is_conditional_order = order in self.order_to_conditional_map or (isinstance(order, dict) and order.get('order_id') in self.order_to_conditional_map)

                    if is_twap_order:
                        logging.debug(f"Processing TWAP order: {order.get('order_id')}")
                        orders_to_check = [order]

                        # Collect additional orders for batch processing
                        while len(orders_to_check) < 50:
                            try:
                                order = self.order_queue.get_nowait()
                                if order is None:
                                    return
                                # Thread-safe check
                                with self.twap_lock:
                                    is_twap = order.get('order_id') in self.order_to_twap_map
                                if is_twap:
                                    orders_to_check.append(order)
                            except Empty:
                                break

                        # Process orders in batch
                        order_ids = [order['order_id'] for order in orders_to_check
                                if 'order_id' in order]

                        fills = self.check_order_fills_batch(order_ids)

                        # Update TWAP tracking for each order
                        for order_data in orders_to_check:
                            order_id = order_data.get('order_id')
                            if not order_id:
                                continue

                            # Thread-safe access to TWAP mapping
                            with self.twap_lock:
                                twap_id = self.order_to_twap_map.get(order_id)

                            if not twap_id:
                                continue

                            fill_info = fills.get(order_id, {})

                            if fill_info.get('status') == 'FILLED':
                                with self.order_lock:
                                    if order_id not in self.filled_orders:
                                        self.filled_orders.append(order_id)

                                # Thread-safe update of TWAP statistics
                                with self.twap_lock:
                                    if twap_id in self.twap_orders:  # Add existence check
                                        self.twap_orders[twap_id]['total_filled'] += fill_info['filled_size']
                                        self.twap_orders[twap_id]['total_value_filled'] += fill_info['filled_value']
                                        self.twap_orders[twap_id]['total_fees'] += fill_info['fees']

                                        if fill_info['is_maker']:
                                            self.twap_orders[twap_id]['maker_orders'] += 1
                                        else:
                                            self.twap_orders[twap_id]['taker_orders'] += 1

                        # Requeue unfilled orders
                        for order_data in orders_to_check:
                            order_id = order_data.get('order_id')
                            if order_id and order_id not in self.filled_orders:
                                self.order_queue.put(order_data)

                    elif is_conditional_order:
                        # Handle conditional orders
                        logging.debug("Processing conditional order")
                        order_id = order if isinstance(order, str) else order.get('order_id')

                        with self.conditional_lock:
                            order_info = self.order_to_conditional_map.get(order_id)

                        if not order_info:
                            continue

                        order_type, conditional_id = order_info

                        # Check order status
                        fills = self.check_order_fills_batch([order_id])
                        fill_info = fills.get(order_id, {})

                        if fill_info.get('status') in ['FILLED', 'CANCELLED', 'EXPIRED']:
                            # Update conditional order tracker
                            success = self.conditional_order_tracker.update_order_status(
                                order_id=conditional_id,
                                order_type=order_type,
                                status=fill_info.get('status'),
                                fill_info={
                                    'filled_size': str(fill_info.get('filled_size', 0)),
                                    'filled_value': str(fill_info.get('filled_value', 0)),
                                    'fees': str(fill_info.get('fees', 0))
                                }
                            )

                            if success:
                                logging.info(f"Conditional order {order_id} updated: {fill_info.get('status')}")

                                # Remove from monitoring if completed
                                with self.conditional_lock:
                                    if order_id in self.order_to_conditional_map:
                                        del self.order_to_conditional_map[order_id]

                                # Display notification
                                if fill_info.get('status') == 'FILLED':
                                    print_success(f"\nConditional order {order_id[:8]}... FILLED!")
                                    print(f"Type: {order_type}")
                                    print(f"Filled: {fill_info.get('filled_size')} @ {format_currency(fill_info.get('avg_price', 0))}")
                        else:
                            # Requeue for continued monitoring
                            self.order_queue.put(order_id)

                except Empty:
                    continue

            except Exception as e:
                logging.error(f"Error in order status checker: {str(e)}", exc_info=True)
                time.sleep(1)

        logging.debug("Order status checker thread shutting down")

    def place_twap_order(self):
        """Place a Time-Weighted Average Price (TWAP) order with comprehensive logging."""
        if not self.client:
            logging.warning("Attempt to place TWAP order without login")
            print_warning("Please login first.")
            return None

        try:
            return self._place_twap_order_impl()
        except CancelledException:
            logging.info("TWAP order placement cancelled by user")
            print_info("\nTWAP order placement cancelled. Returning to main menu.")
            return None

    def _place_twap_order_impl(self):
        """Internal implementation of place_twap_order with cancellation support."""
        logging.info("=" * 50)
        logging.info("STARTING NEW TWAP ORDER")
        logging.info("=" * 50)

        order_input = self.get_order_input()
        if not order_input:
            return None

        # Get account balances
        base_currency = order_input["product_id"].split('-')[0]
        quote_currency = order_input["product_id"].split('-')[1]
        base_balance = self.get_account_balance(base_currency)
        quote_balance = self.get_account_balance(quote_currency)
        
        logging.info(f"Account Balances:")
        logging.info(f"{base_currency} Balance: {base_balance:.8f}")
        logging.info(f"{quote_currency} Balance: {quote_balance:.8f}")

        duration = int(self.get_input("Enter TWAP duration in minutes"))
        num_slices = int(self.get_input("Enter number of slices for TWAP"))

        # Get product information for validation
        try:
            product_info = self.client.get_product(order_input["product_id"])
            min_size = float(product_info['base_min_size'])
            max_size = float(product_info['base_max_size'])
            quote_increment = float(product_info['quote_increment'])
            
            logging.info(f"Product Constraints:")
            logging.info(f"Minimum Order Size: {min_size} {base_currency}")
            logging.info(f"Maximum Order Size: {max_size} {base_currency}")
            logging.info(f"Price Increment: {quote_increment} {quote_currency}")
            
            # Validate slice size
            slice_size = float(order_input["base_size"]) / num_slices
            if slice_size < min_size:
                logging.error(f"Calculated slice size {slice_size} is below minimum {min_size}")
                print(f"Error: Slice size {slice_size} is below minimum {min_size}")
                return None
        except Exception as e:
            logging.error(f"Error fetching product information: {str(e)}")
            print(f"Error fetching product information: {str(e)}")
            return None

        print("\nSelect price type for order placement:")
        print("1. Original limit price")
        print("2. Current market bid")
        print("3. Current market mid")
        print("4. Current market ask")
        price_type = self.get_input("Enter your choice (1-4)")

        # Create TWAP ID and initialize tracking
        twap_id = str(uuid.uuid4())
        twap_order = TWAPOrder(
            twap_id=twap_id,
            market=order_input["product_id"],
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
        
        # Save initial TWAP order state
        self.twap_tracker.save_twap_order(twap_order)

        # Log TWAP configuration
        logging.info("\nTWAP Configuration:")
        logging.info(f"TWAP ID: {twap_id}")
        logging.info(f"Market: {order_input['product_id']}")
        logging.info(f"Side: {order_input['side']}")
        logging.info(f"Total Size: {order_input['base_size']} {base_currency}")
        logging.info(f"Slice Size: {slice_size} {base_currency}")
        logging.info(f"Limit Price: {order_input['limit_price']} {quote_currency}")
        logging.info(f"Duration: {duration} minutes")
        logging.info(f"Number of Slices: {num_slices}")
        logging.info(f"Interval between slices: {(duration * 60) / num_slices:.2f} seconds")

        slice_interval = (duration * 60) / num_slices
        next_slice_time = time.time()

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
                        logging.info(f"Waiting {sleep_time:.2f} seconds until next slice...")
                        print(f"Waiting {sleep_time:.2f} seconds until next slice...")
                        time.sleep(sleep_time)

                next_slice_time = time.time() + slice_interval

                # Check available balance
                if order_input["side"] == "SELL":
                    available_balance = self.get_account_balance(base_currency)
                    if available_balance < slice_size:
                        msg = f"Insufficient {base_currency} balance for slice {i+1}. Required: {slice_size}, Available: {available_balance}"
                        logging.error(msg)
                        print(msg)
                        slice_info['status'] = 'balance_insufficient'
                        twap_order.failed_slices.append(i+1)
                        continue

                # Get current prices with detailed logging
                current_prices = self.get_current_prices(order_input["product_id"])
                if not current_prices:
                    logging.error(f"Failed to get current prices for slice {i+1}/{num_slices}")
                    print(f"Failed to get current prices for slice {i+1}/{num_slices}")
                    slice_info['status'] = 'price_fetch_failed'
                    twap_order.failed_slices.append(i+1)
                    continue

                # Log market conditions
                logging.info(f"\nSlice {i+1}/{num_slices} Market Conditions:")
                logging.info(f"Time: {datetime.now().strftime('%H:%M:%S')}")
                logging.info(f"Bid: ${current_prices['bid']:.2f}")
                logging.info(f"Mid: ${current_prices['mid']:.2f}")
                logging.info(f"Ask: ${current_prices['ask']:.2f}")
                logging.info(f"Spread: ${(current_prices['ask'] - current_prices['bid']):.3f}")

                # Determine execution price
                if price_type == '1':
                    execution_price = float(order_input["limit_price"])
                    price_source = "limit price"
                elif price_type == '2':
                    execution_price = current_prices['bid']
                    price_source = "market bid"
                elif price_type == '3':
                    execution_price = current_prices['mid']
                    price_source = "market mid"
                else:
                    execution_price = current_prices['ask']
                    price_source = "market ask"

                logging.info(f"Selected execution price: ${execution_price:.2f} (source: {price_source})")
                
                slice_info['execution_price'] = execution_price
                slice_info['market_prices'] = current_prices

                # Price favorability check
                if order_input["side"] == "BUY":
                    price_favorable = execution_price <= float(order_input["limit_price"])
                    comparison = "above" if not price_favorable else "below or at"
                else:  # SELL
                    price_favorable = execution_price >= float(order_input["limit_price"])
                    comparison = "below" if not price_favorable else "above or at"

                if not price_favorable:
                    msg = f"Skipping slice {i+1}/{num_slices}: Price ${execution_price:.2f} is {comparison} limit ${order_input['limit_price']:.2f}"
                    logging.warning(msg)
                    print(msg)
                    slice_info['status'] = 'price_unfavorable'
                    twap_order.failed_slices.append(i+1)
                    continue

                # Place the slice order
                try:
                    order_id = self.place_twap_slice(twap_id, i+1, num_slices, order_input, execution_price)
                    
                    if order_id:
                        twap_order.orders.append(order_id)
                        slice_info['status'] = 'placed'
                        slice_info['order_id'] = order_id
                        
                        logging.info(f"TWAP slice {i+1}/{num_slices} placed successfully:")
                        logging.info(f"Order ID: {order_id}")
                        logging.info(f"Size: {slice_size} {base_currency}")
                        logging.info(f"Price: ${execution_price:.2f} {quote_currency}")
                        
                        # Calculate slice value
                        slice_value = slice_size * execution_price
                        
                        # Enhanced progress update with order details
                        print(f"\nOrder to {order_input['side'].lower()} {slice_size} {base_currency} " 
                            f"with value ${slice_value:.2f} placed successfully")
                        print(f"\nTWAP Progress Update:")
                        print(f"Slices Placed: {len(twap_order.orders)}/{num_slices}")
                        if twap_order.failed_slices:
                            print(f"Failed Slices: {len(twap_order.failed_slices)}")
                        
                    else:
                        slice_info['status'] = 'placement_failed'
                        twap_order.failed_slices.append(i+1)
                        logging.error(f"Failed to place TWAP slice {i+1}/{num_slices}")
                        print(f"Failed to place TWAP slice {i+1}/{num_slices}")

                except Exception as e:
                    error_msg = f"Error placing TWAP slice {i+1}/{num_slices}: {str(e)}"
                    logging.error(error_msg)
                    print(error_msg)
                    slice_info['status'] = 'error'
                    slice_info['error'] = str(e)
                    twap_order.failed_slices.append(i+1)

                slice_info['end_time'] = time.time()
                slice_info['duration'] = slice_info['end_time'] - slice_info['start_time']
                twap_order.slice_statuses.append(slice_info)
                
                # Save updated TWAP order state after each slice
                self.twap_tracker.save_twap_order(twap_order)

            # Final update and display
            twap_order.status = 'completed'
            self.twap_tracker.save_twap_order(twap_order)
            
            # Update final fill information before showing summary
            self.update_twap_fills(twap_id)
            self.display_twap_summary(twap_id)
            
            logging.info("=" * 50)
            logging.info("TWAP ORDER COMPLETED")
            logging.info("=" * 50)
            
            return twap_id

        except Exception as e:
            logging.error(f"Error in TWAP order execution: {str(e)}")
            if twap_order:
                twap_order.status = 'error'
                self.twap_tracker.save_twap_order(twap_order)
            return None

    def check_twap_order_fills(self, twap_id):
        """Check fills for a specific TWAP order and display summary."""
        try:
            # Get TWAP order from tracker
            twap_order = self.twap_tracker.get_twap_order(twap_id)
            if not twap_order:
                logging.warning(f"TWAP order {twap_id} not found")
                print(f"TWAP order {twap_id} not found.")
                return

            logging.info(f"Checking fills for TWAP order {twap_id}")
            print(f"\nChecking fills for TWAP order {twap_id}...")
            
            # Update fill information
            if self.update_twap_fills(twap_id):
                # Display updated summary with detailed order information
                self.display_twap_summary(twap_id, show_orders=True)
            else:
                print("Error checking TWAP fills. Please try again.")

        except Exception as e:
            logging.error(f"Error checking TWAP fills: {str(e)}")
            print("Error checking TWAP fills. Please check the logs for details.")

    # ========================
    # Conditional Order Methods
    # ========================

    def place_stop_loss_order(self):
        """Place a stop-loss order using native Coinbase SDK."""
        if not self.client:
            print_warning("Please login first.")
            return None

        try:
            from conditional_orders import StopLimitOrder
            from datetime import datetime
            import uuid

            print_header("Place Stop-Loss Order")
            print_info("This creates a NEW stop-loss order (not modifying an existing position).")
            print_info("The order will trigger when price reaches your stop price.\n")

            # Get order input (product, side, size only - no limit price)
            order_input = self.get_conditional_order_input()
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])  # Convert to string for API

            # Fetch current price for validation
            current_prices = self.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']
            print(f"\nCurrent market price: {format_currency(current_price)}")

            # Get stop price (trigger price)
            stop_price_str = self.get_input(f"\nEnter stop price (trigger when price reaches this level)")
            try:
                stop_price = float(stop_price_str)
            except ValueError:
                print_error("Invalid stop price. Must be a number.")
                return None

            # Get limit price (execution price after trigger)
            limit_price_str = self.get_input("Enter limit price (execute at this price after trigger)")
            try:
                limit_price = float(limit_price_str)
            except ValueError:
                print_error("Invalid limit price. Must be a number.")
                return None

            # Auto-determine stop_direction and validate
            if side == "SELL":
                if stop_price < current_price:
                    stop_direction = "STOP_DIRECTION_STOP_DOWN"
                    order_type_display = "STOP_LOSS"
                    print_info(f"Stop-loss SELL order: will trigger when price drops to {format_currency(stop_price)}")
                else:
                    stop_direction = "STOP_DIRECTION_STOP_UP"
                    order_type_display = "TAKE_PROFIT"
                    print_info(f"Take-profit SELL order: will trigger when price rises to {format_currency(stop_price)}")

                # Validate limit price
                if limit_price > stop_price:
                    print_warning(f"Warning: Limit price ({format_currency(limit_price)}) is above stop price ({format_currency(stop_price)}).")
                    print_warning("This may result in unfavorable execution.")

            else:  # BUY
                if stop_price > current_price:
                    stop_direction = "STOP_DIRECTION_STOP_UP"
                    order_type_display = "STOP_LOSS"
                    print_info(f"Stop-loss BUY order: will trigger when price rises to {format_currency(stop_price)}")
                else:
                    stop_direction = "STOP_DIRECTION_STOP_DOWN"
                    order_type_display = "TAKE_PROFIT"
                    print_info(f"Take-profit BUY order: will trigger when price drops to {format_currency(stop_price)}")

                # Validate limit price
                if limit_price < stop_price:
                    print_warning(f"Warning: Limit price ({format_currency(limit_price)}) is below stop price ({format_currency(stop_price)}).")
                    print_warning("This may result in unfavorable execution.")

            # Display order summary
            print("\n" + "="*50)
            print_header("Order Summary")
            print(f"Type: {order_type_display}")
            print(f"Product: {product_id}")
            print(f"Side: {format_side(side)}")
            print(f"Size: {base_size}")
            print(f"Stop Price (Trigger): {format_currency(stop_price)}")
            print(f"Limit Price (Execute): {format_currency(limit_price)}")
            print(f"Current Price: {format_currency(current_price)}")
            print("="*50 + "\n")

            confirm = self.get_input("Confirm order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Order cancelled.")
                return None

            # Place the order
            client_order_id = f"sl-{str(uuid.uuid4())[:8]}"

            logging.info(f"Placing {order_type_display} order: {side} {base_size} {product_id} @ stop={stop_price}, limit={limit_price}")

            self.rate_limiter.wait()

            if side == "SELL":
                response = self.client.stop_limit_order_gtc_sell(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    base_size=base_size,
                    limit_price=limit_price_str,
                    stop_price=stop_price_str,
                    stop_direction=stop_direction
                )
            else:  # BUY
                response = self.client.stop_limit_order_gtc_buy(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    base_size=base_size,
                    limit_price=limit_price_str,
                    stop_price=stop_price_str,
                    stop_direction=stop_direction
                )

            # Check response
            if hasattr(response, 'success') and not response.success:
                # error_response is a dict, not an object
                error_msg = "Unknown error"
                if hasattr(response, 'error_response') and response.error_response:
                    error_msg = response.error_response.get('message', 'Unknown error')
                print_error(f"Failed to place order: {error_msg}")
                logging.error(f"Order placement failed: {error_msg}")
                return None

            # Extract order ID
            order_id = response.success_response.order_id if hasattr(response, 'success_response') else None
            if not order_id:
                print_error("Order placed but no order ID returned.")
                logging.error("No order ID in response")
                return None

            # Create StopLimitOrder object
            stop_order = StopLimitOrder(
                order_id=order_id,
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                stop_price=stop_price_str,
                limit_price=limit_price_str,
                stop_direction=stop_direction,
                order_type=order_type_display,
                status="PENDING",
                created_at=datetime.utcnow().isoformat() + "Z"
            )

            # Save to tracker
            self.conditional_order_tracker.save_stop_limit_order(stop_order)

            # Add to monitoring
            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("stop_limit", order_id)
                self.order_queue.put(order_id)

            # Display success
            print_success(f"\n{order_type_display} order placed successfully!")
            print(f"Order ID: {order_id}")
            print(f"Status: Pending (waiting for trigger at {format_currency(stop_price)})")

            logging.info(f"{order_type_display} order placed: {order_id}")

            return order_id

        except CancelledException:
            print_info("\nOrder placement cancelled.")
            return None
        except Exception as e:
            logging.error(f"Error placing stop-loss order: {str(e)}", exc_info=True)
            print_error(f"Error placing order: {str(e)}")
            return None

    def place_take_profit_order(self):
        """Place a take-profit order (wrapper around stop-loss with reversed logic)."""
        if not self.client:
            print_warning("Please login first.")
            return None

        try:
            from conditional_orders import StopLimitOrder
            from datetime import datetime
            import uuid

            print_header("Place Take-Profit Order")
            print_info("This creates a NEW take-profit order (not modifying an existing position).")
            print_info("The order will trigger when price reaches your target profit level.\n")

            # Get order input (product, side, size only - no limit price)
            order_input = self.get_conditional_order_input()
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])  # Convert to string for API

            # Fetch current price
            current_prices = self.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']
            print(f"\nCurrent market price: {format_currency(current_price)}")

            # Get stop price (trigger price) - for take-profit, this should be ABOVE current for SELL
            stop_price_str = self.get_input(f"\nEnter take-profit price (trigger when price reaches this level)")
            try:
                stop_price = float(stop_price_str)
            except ValueError:
                print_error("Invalid price. Must be a number.")
                return None

            # Validate that it's actually a take-profit
            if side == "SELL" and stop_price <= current_price:
                print_warning(f"For a take-profit SELL, stop price should be ABOVE current price ({format_currency(current_price)}).")
                confirm = self.get_input("Continue anyway? (yes/no)")
                if confirm.lower() not in ['yes', 'y']:
                    return None

            # Get limit price
            limit_price_str = self.get_input("Enter limit price (execute at this price after trigger)")
            try:
                limit_price = float(limit_price_str)
            except ValueError:
                print_error("Invalid limit price. Must be a number.")
                return None

            # Determine stop_direction (take-profit uses UP for SELL)
            if side == "SELL":
                stop_direction = "STOP_DIRECTION_STOP_UP"
            else:  # BUY uses DOWN for take-profit
                stop_direction = "STOP_DIRECTION_STOP_DOWN"

            order_type_display = "TAKE_PROFIT"

            # Display order summary
            print("\n" + "="*50)
            print_header("Order Summary")
            print(f"Type: {order_type_display}")
            print(f"Product: {product_id}")
            print(f"Side: {format_side(side)}")
            print(f"Size: {base_size}")
            print(f"Take-Profit Price (Trigger): {format_currency(stop_price)}")
            print(f"Limit Price (Execute): {format_currency(limit_price)}")
            print(f"Current Price: {format_currency(current_price)}")
            print("="*50 + "\n")

            confirm = self.get_input("Confirm order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Order cancelled.")
                return None

            # Place the order
            client_order_id = f"tp-{str(uuid.uuid4())[:8]}"

            logging.info(f"Placing TAKE_PROFIT order: {side} {base_size} {product_id} @ stop={stop_price}, limit={limit_price}")

            self.rate_limiter.wait()

            if side == "SELL":
                response = self.client.stop_limit_order_gtc_sell(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    base_size=base_size,
                    limit_price=limit_price_str,
                    stop_price=stop_price_str,
                    stop_direction=stop_direction
                )
            else:  # BUY
                response = self.client.stop_limit_order_gtc_buy(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    base_size=base_size,
                    limit_price=limit_price_str,
                    stop_price=stop_price_str,
                    stop_direction=stop_direction
                )

            # Check response
            if hasattr(response, 'success') and not response.success:
                # error_response is a dict, not an object
                error_msg = "Unknown error"
                if hasattr(response, 'error_response') and response.error_response:
                    error_msg = response.error_response.get('message', 'Unknown error')
                print_error(f"Failed to place order: {error_msg}")
                return None

            # Extract order ID
            order_id = response.success_response.order_id if hasattr(response, 'success_response') else None
            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            # Create StopLimitOrder object
            tp_order = StopLimitOrder(
                order_id=order_id,
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                stop_price=stop_price_str,
                limit_price=limit_price_str,
                stop_direction=stop_direction,
                order_type=order_type_display,
                status="PENDING",
                created_at=datetime.utcnow().isoformat() + "Z"
            )

            # Save to tracker
            self.conditional_order_tracker.save_stop_limit_order(tp_order)

            # Add to monitoring
            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("stop_limit", order_id)
                self.order_queue.put(order_id)

            # Display success
            print_success(f"\nTAKE_PROFIT order placed successfully!")
            print(f"Order ID: {order_id}")
            print(f"Status: Pending (waiting for trigger at {format_currency(stop_price)})")

            logging.info(f"TAKE_PROFIT order placed: {order_id}")

            return order_id

        except CancelledException:
            print_info("\nOrder placement cancelled.")
            return None
        except Exception as e:
            logging.error(f"Error placing take-profit order: {str(e)}", exc_info=True)
            print_error(f"Error placing order: {str(e)}")
            return None

    def place_bracket_for_position(self):
        """Place a bracket order (TP/SL) on an existing position."""
        if not self.client:
            print_warning("Please login first.")
            return None

        try:
            from conditional_orders import BracketOrder
            from datetime import datetime
            import uuid

            print_header("Place Bracket Order (TP/SL on Existing Position)")
            print_info("This PROTECTS a position you already own.")
            print_info("It sets both take-profit and stop-loss orders on your existing holdings.\n")

            # Get position info
            product_id = self.get_input("Enter product (e.g., BTC-USD)")
            side = self.get_input("Enter position side to exit (BUY or SELL)").upper()

            if side not in ["BUY", "SELL"]:
                print_error("Side must be BUY or SELL")
                return None

            base_size = self.get_input(f"Enter position size to protect")

            # Fetch current price
            current_prices = self.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']
            print(f"\nCurrent market price: {format_currency(current_price)}")

            # Get take-profit price
            tp_price_str = self.get_input("\nEnter take-profit price (exit when price reaches this level)")
            try:
                tp_price = float(tp_price_str)
            except ValueError:
                print_error("Invalid take-profit price. Must be a number.")
                return None

            # Get stop-loss price
            sl_price_str = self.get_input("Enter stop-loss price (exit when price drops to this level)")
            try:
                sl_price = float(sl_price_str)
            except ValueError:
                print_error("Invalid stop-loss price. Must be a number.")
                return None

            # Validate bracket prices for LONG position (SELL side)
            if side == "SELL":
                if tp_price <= current_price:
                    print_warning(f"For a LONG position, take-profit ({format_currency(tp_price)}) should be ABOVE current price ({format_currency(current_price)}).")
                if sl_price >= current_price:
                    print_warning(f"For a LONG position, stop-loss ({format_currency(sl_price)}) should be BELOW current price ({format_currency(current_price)}).")
                if sl_price >= tp_price:
                    print_error("Stop-loss price must be below take-profit price.")
                    return None
            else:  # BUY side (SHORT position)
                if tp_price >= current_price:
                    print_warning(f"For a SHORT position, take-profit ({format_currency(tp_price)}) should be BELOW current price ({format_currency(current_price)}).")
                if sl_price <= current_price:
                    print_warning(f"For a SHORT position, stop-loss ({format_currency(sl_price)}) should be ABOVE current price ({format_currency(current_price)}).")
                if sl_price <= tp_price:
                    print_error("Stop-loss price must be above take-profit price for SHORT positions.")
                    return None

            # Display order summary
            print("\n" + "="*50)
            print_header("Bracket Order Summary")
            print(f"Product: {product_id}")
            print(f"Position Side: {format_side(side)}")
            print(f"Size: {base_size}")
            print(f"Current Price: {format_currency(current_price)}")
            print(f"Take-Profit: {format_currency(tp_price)}")
            print(f"Stop-Loss: {format_currency(sl_price)}")
            if side == "SELL":
                profit_range = tp_price - current_price
                loss_range = current_price - sl_price
                print(f"Potential Profit Range: {format_currency(profit_range)} (+{(profit_range/current_price)*100:.2f}%)")
                print(f"Risk Range: {format_currency(loss_range)} (-{(loss_range/current_price)*100:.2f}%)")
            print("="*50 + "\n")

            confirm = self.get_input("Confirm bracket order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Order cancelled.")
                return None

            # Place the bracket order
            client_order_id = f"bracket-{str(uuid.uuid4())[:8]}"

            logging.info(f"Placing bracket order: {side} {base_size} {product_id} @ TP={tp_price}, SL={sl_price}")

            self.rate_limiter.wait()

            response = self.client.trigger_bracket_order_gtc(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                limit_price=tp_price_str,
                stop_trigger_price=sl_price_str
            )

            # Check response
            if hasattr(response, 'success') and not response.success:
                # error_response is a dict, not an object
                error_msg = "Unknown error"
                if hasattr(response, 'error_response') and response.error_response:
                    error_msg = response.error_response.get('message', 'Unknown error')
                print_error(f"Failed to place bracket order: {error_msg}")
                return None

            # Extract order ID
            order_id = response.success_response.order_id if hasattr(response, 'success_response') else None
            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            # Create BracketOrder object
            bracket_order = BracketOrder(
                order_id=order_id,
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                limit_price=tp_price_str,
                stop_trigger_price=sl_price_str,
                status="ACTIVE",
                created_at=datetime.utcnow().isoformat() + "Z"
            )

            # Save to tracker
            self.conditional_order_tracker.save_bracket_order(bracket_order)

            # Add to monitoring
            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("bracket", order_id)
                self.order_queue.put(order_id)

            # Display success
            print_success(f"\nBracket order placed successfully!")
            print(f"Order ID: {order_id}")
            print(f"Status: Active")
            print(f"Take-Profit trigger: {format_currency(tp_price)}")
            print(f"Stop-Loss trigger: {format_currency(sl_price)}")

            logging.info(f"Bracket order placed: {order_id}")

            return order_id

        except CancelledException:
            print_info("\nOrder placement cancelled.")
            return None
        except Exception as e:
            logging.error(f"Error placing bracket order: {str(e)}", exc_info=True)
            print_error(f"Error placing order: {str(e)}")
            return None

    def place_entry_with_bracket(self):
        """Place an entry order with attached TP/SL bracket."""
        if not self.client:
            print_warning("Please login first.")
            return None

        try:
            from conditional_orders import AttachedBracketOrder
            from datetime import datetime
            import uuid

            print_header("Place Entry Order with TP/SL Bracket")
            print_info("This places a NEW entry order with automatic TP/SL protection.")
            print_info("When your entry order fills, the TP/SL bracket automatically activates.\n")

            # Get order input
            order_input = self.get_order_input()
            if not order_input:
                return None

            product_id = order_input["product_id"]
            side = order_input["side"]
            base_size = str(order_input["base_size"])  # Convert to string for API
            entry_price = float(order_input["limit_price"])

            # Fetch current price
            current_prices = self.get_current_prices(product_id)
            if not current_prices:
                print_error("Failed to fetch current market prices.")
                return None

            current_price = current_prices['mid']
            print(f"\nCurrent market price: {format_currency(current_price)}")
            print(f"Entry limit price: {format_currency(entry_price)}")

            # Get take-profit price
            tp_price_str = self.get_input("\nEnter take-profit price (will activate after entry fills)")
            try:
                tp_price = float(tp_price_str)
            except ValueError:
                print_error("Invalid take-profit price. Must be a number.")
                return None

            # Get stop-loss price
            sl_price_str = self.get_input("Enter stop-loss price (will activate after entry fills)")
            try:
                sl_price = float(sl_price_str)
            except ValueError:
                print_error("Invalid stop-loss price. Must be a number.")
                return None

            # Validate bracket prices relative to ENTRY price
            if side == "BUY":
                # For BUY entry: TP should be above entry, SL should be below entry
                if tp_price <= entry_price:
                    print_warning(f"For a BUY entry, take-profit ({format_currency(tp_price)}) should be ABOVE entry price ({format_currency(entry_price)}).")
                if sl_price >= entry_price:
                    print_warning(f"For a BUY entry, stop-loss ({format_currency(sl_price)}) should be BELOW entry price ({format_currency(entry_price)}).")
                if sl_price >= tp_price:
                    print_error("Stop-loss must be below take-profit.")
                    return None
            else:  # SELL
                # For SELL entry: TP should be below entry, SL should be above entry
                if tp_price >= entry_price:
                    print_warning(f"For a SELL entry, take-profit ({format_currency(tp_price)}) should be BELOW entry price ({format_currency(entry_price)}).")
                if sl_price <= entry_price:
                    print_warning(f"For a SELL entry, stop-loss ({format_currency(sl_price)}) should be ABOVE entry price ({format_currency(entry_price)}).")
                if sl_price <= tp_price:
                    print_error("Stop-loss must be above take-profit for SELL orders.")
                    return None

            # Display order summary
            print("\n" + "="*50)
            print_header("Entry + Bracket Order Summary")
            print(f"Product: {product_id}")
            print(f"Side: {format_side(side)}")
            print(f"Size: {base_size}")
            print(f"Entry Limit Price: {format_currency(entry_price)}")
            print(f"Take-Profit: {format_currency(tp_price)}")
            print(f"Stop-Loss: {format_currency(sl_price)}")
            print(f"Current Price: {format_currency(current_price)}")
            if side == "BUY":
                profit_range = tp_price - entry_price
                loss_range = entry_price - sl_price
                print(f"Potential Profit: {format_currency(profit_range)} (+{(profit_range/entry_price)*100:.2f}%)")
                print(f"Max Risk: {format_currency(loss_range)} (-{(loss_range/entry_price)*100:.2f}%)")
                risk_reward = profit_range / loss_range if loss_range > 0 else 0
                print(f"Risk/Reward Ratio: 1:{risk_reward:.2f}")
            print("="*50 + "\n")

            confirm = self.get_input("Confirm entry + bracket order placement? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Order cancelled.")
                return None

            # Build order configuration
            order_configuration = {
                "limit_limit_gtc": {
                    "baseSize": base_size,
                    "limitPrice": order_input["limit_price"]
                }
            }

            attached_order_configuration = {
                "trigger_bracket_gtc": {
                    "limit_price": tp_price_str,
                    "stop_trigger_price": sl_price_str
                }
            }

            # Place the order
            client_order_id = f"entry-bracket-{str(uuid.uuid4())[:8]}"

            logging.info(f"Placing entry+bracket: {side} {base_size} {product_id} @ entry={entry_price}, TP={tp_price}, SL={sl_price}")

            self.rate_limiter.wait()

            response = self.client.create_order(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                order_configuration=order_configuration,
                attached_order_configuration=attached_order_configuration
            )

            # Check response
            if hasattr(response, 'success') and not response.success:
                # error_response is a dict, not an object
                error_msg = "Unknown error"
                if hasattr(response, 'error_response') and response.error_response:
                    error_msg = response.error_response.get('message', 'Unknown error')
                print_error(f"Failed to place order: {error_msg}")
                return None

            # Extract order ID
            order_id = response.success_response.order_id if hasattr(response, 'success_response') else None
            if not order_id:
                print_error("Order placed but no order ID returned.")
                return None

            # Create AttachedBracketOrder object
            attached_bracket = AttachedBracketOrder(
                entry_order_id=order_id,
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                entry_limit_price=order_input["limit_price"],
                take_profit_price=tp_price_str,
                stop_loss_price=sl_price_str,
                status="PENDING",
                created_at=datetime.utcnow().isoformat() + "Z"
            )

            # Save to tracker
            self.conditional_order_tracker.save_attached_bracket_order(attached_bracket)

            # Add to monitoring
            with self.conditional_lock:
                self.order_to_conditional_map[order_id] = ("attached_bracket", order_id)
                self.order_queue.put(order_id)

            # Display success
            print_success(f"\nEntry + Bracket order placed successfully!")
            print(f"Entry Order ID: {order_id}")
            print(f"Status: Pending entry fill at {format_currency(entry_price)}")
            print(f"Once filled, TP/SL will activate:")
            print(f"  - Take-Profit: {format_currency(tp_price)}")
            print(f"  - Stop-Loss: {format_currency(sl_price)}")

            logging.info(f"Entry+Bracket order placed: {order_id}")

            return order_id

        except CancelledException:
            print_info("\nOrder placement cancelled.")
            return None
        except Exception as e:
            logging.error(f"Error placing entry+bracket order: {str(e)}", exc_info=True)
            print_error(f"Error placing order: {str(e)}")
            return None

    def view_conditional_orders(self):
        """Display all conditional orders with filtering options."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            from tabulate import tabulate

            print_header("Conditional Orders")

            # Get all orders
            stop_limit_orders = self.conditional_order_tracker.list_stop_limit_orders()
            bracket_orders = self.conditional_order_tracker.list_bracket_orders()
            attached_bracket_orders = self.conditional_order_tracker.list_attached_bracket_orders()

            if not stop_limit_orders and not bracket_orders and not attached_bracket_orders:
                print_info("No conditional orders found.")
                return

            # Display stop-limit orders
            if stop_limit_orders:
                print_subheader(f"Stop-Limit Orders ({len(stop_limit_orders)})")
                table_data = []
                for order in stop_limit_orders:
                    # Color code status
                    if order.status == "PENDING":
                        status_display = warning(order.status)
                    elif order.status == "TRIGGERED":
                        status_display = info(order.status)
                    elif order.status == "FILLED":
                        status_display = success(order.status)
                    else:
                        status_display = error(order.status)

                    table_data.append([
                        order.order_id[:12] + "...",
                        order.order_type,
                        order.product_id,
                        format_side(order.side),
                        order.base_size,
                        format_currency(float(order.stop_price)),
                        format_currency(float(order.limit_price)),
                        status_display,
                        order.created_at[:19]
                    ])

                headers = ["Order ID", "Type", "Product", "Side", "Size", "Stop Price", "Limit Price", "Status", "Created"]
                print(tabulate(table_data, headers=headers, tablefmt="grid"))
                print()

            # Display bracket orders
            if bracket_orders:
                print_subheader(f"Bracket Orders ({len(bracket_orders)})")
                table_data = []
                for order in bracket_orders:
                    # Color code status
                    if order.status in ["PENDING", "ACTIVE"]:
                        status_display = info(order.status)
                    elif order.status == "FILLED":
                        status_display = success(order.status)
                    else:
                        status_display = error(order.status)

                    table_data.append([
                        order.order_id[:12] + "...",
                        order.product_id,
                        format_side(order.side),
                        order.base_size,
                        format_currency(float(order.limit_price)),
                        format_currency(float(order.stop_trigger_price)),
                        status_display,
                        order.created_at[:19]
                    ])

                headers = ["Order ID", "Product", "Side", "Size", "TP Price", "SL Price", "Status", "Created"]
                print(tabulate(table_data, headers=headers, tablefmt="grid"))
                print()

            # Display attached bracket orders
            if attached_bracket_orders:
                print_subheader(f"Entry + Bracket Orders ({len(attached_bracket_orders)})")
                table_data = []
                for order in attached_bracket_orders:
                    # Color code status
                    if order.status == "PENDING":
                        status_display = warning(order.status)
                    elif order.status == "ENTRY_FILLED":
                        status_display = info(order.status)
                    elif order.status in ["TP_FILLED", "SL_FILLED"]:
                        status_display = success(order.status)
                    else:
                        status_display = error(order.status)

                    table_data.append([
                        order.entry_order_id[:12] + "...",
                        order.product_id,
                        format_side(order.side),
                        order.base_size,
                        format_currency(float(order.entry_limit_price)),
                        format_currency(float(order.take_profit_price)),
                        format_currency(float(order.stop_loss_price)),
                        status_display,
                        order.created_at[:19]
                    ])

                headers = ["Order ID", "Product", "Side", "Size", "Entry", "TP", "SL", "Status", "Created"]
                print(tabulate(table_data, headers=headers, tablefmt="grid"))
                print()

            # Display summary
            stats = self.conditional_order_tracker.get_statistics()
            print_header("Summary")
            print(f"Stop-Limit Orders: {stats['stop_limit']['total']} (Active: {stats['stop_limit']['active']}, Completed: {stats['stop_limit']['completed']})")
            print(f"  - Stop-Loss: {stats['stop_limit']['stop_loss']}")
            print(f"  - Take-Profit: {stats['stop_limit']['take_profit']}")
            print(f"Bracket Orders: {stats['bracket']['total']} (Active: {stats['bracket']['active']}, Completed: {stats['bracket']['completed']})")
            print(f"Entry+Bracket Orders: {stats['attached_bracket']['total']} (Active: {stats['attached_bracket']['active']}, Completed: {stats['attached_bracket']['completed']})")

        except Exception as e:
            logging.error(f"Error viewing conditional orders: {str(e)}", exc_info=True)
            print_error(f"Error viewing orders: {str(e)}")

    def cancel_conditional_orders(self):
        """Cancel pending/active conditional orders."""
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            print_header("Cancel Conditional Orders")

            # Get active orders
            active_orders = self.conditional_order_tracker.list_all_active_orders()

            if not active_orders:
                print_info("No active conditional orders to cancel.")
                return

            # Display active orders
            print_info(f"Found {len(active_orders)} active orders:\n")
            for i, order in enumerate(active_orders, 1):
                if hasattr(order, 'order_type'):  # StopLimitOrder
                    print(f"{i}. {order.order_type} - {order.product_id} {format_side(order.side)} {order.base_size}")
                    print(f"   Order ID: {order.order_id}")
                    print(f"   Status: {order.status}")
                elif hasattr(order, 'entry_order_id'):  # AttachedBracketOrder
                    print(f"{i}. Entry+Bracket - {order.product_id} {format_side(order.side)} {order.base_size}")
                    print(f"   Order ID: {order.entry_order_id}")
                    print(f"   Status: {order.status}")
                else:  # BracketOrder
                    print(f"{i}. Bracket - {order.product_id} {format_side(order.side)} {order.base_size}")
                    print(f"   Order ID: {order.order_id}")
                    print(f"   Status: {order.status}")
                print()

            # Get user selection
            selection = self.get_input("Enter order numbers to cancel (comma-separated, or 'all')")

            if selection.lower() == 'all':
                orders_to_cancel = active_orders
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(',')]
                    orders_to_cancel = [active_orders[i] for i in indices if 0 <= i < len(active_orders)]
                except (ValueError, IndexError):
                    print_error("Invalid selection.")
                    return

            if not orders_to_cancel:
                print_info("No orders selected.")
                return

            # Confirm cancellation
            print_warning(f"\nYou are about to cancel {len(orders_to_cancel)} order(s).")
            confirm = self.get_input("Confirm cancellation? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Cancellation aborted.")
                return

            # Cancel each order
            cancelled_count = 0
            failed_count = 0

            for order in orders_to_cancel:
                try:
                    # Get order ID
                    if hasattr(order, 'entry_order_id'):
                        order_id = order.entry_order_id
                        order_type = "attached_bracket"
                    elif hasattr(order, 'order_type'):
                        order_id = order.order_id
                        order_type = "stop_limit"
                    else:
                        order_id = order.order_id
                        order_type = "bracket"

                    # Cancel via API
                    self.rate_limiter.wait()
                    response = self.client.cancel_orders([order_id])

                    # Check response
                    success = False
                    if hasattr(response, 'results') and response.results:
                        result = response.results[0]
                        # CancelOrderObject has attributes, not dict methods
                        success = getattr(result, 'success', False)

                    if success:
                        # Update tracker
                        self.conditional_order_tracker.update_order_status(
                            order_id=order_id,
                            order_type=order_type,
                            status="CANCELLED",
                            fill_info=None
                        )

                        # Remove from monitoring
                        with self.conditional_lock:
                            if order_id in self.order_to_conditional_map:
                                del self.order_to_conditional_map[order_id]

                        print_success(f"Cancelled: {order_id[:12]}...")
                        cancelled_count += 1
                    else:
                        # Get error message from CancelOrderObject attributes
                        error_msg = getattr(result, 'failure_reason', 'Unknown error') if hasattr(response, 'results') else "Unknown error"
                        print_error(f"Failed to cancel {order_id[:12]}...: {error_msg}")
                        failed_count += 1

                except Exception as e:
                    logging.error(f"Error cancelling order {order_id}: {str(e)}")
                    print_error(f"Error cancelling {order_id[:12]}...: {str(e)}")
                    failed_count += 1

            # Display summary
            print("\n" + "="*50)
            print_success(f"Successfully cancelled: {cancelled_count}")
            if failed_count > 0:
                print_error(f"Failed to cancel: {failed_count}")
            print("="*50)

        except CancelledException:
            print_info("\nCancellation aborted.")
        except Exception as e:
            logging.error(f"Error in cancel_conditional_orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def view_all_active_orders(self):
        """
        Unified view of all active orders (regular + conditional).
        Displays orders grouped by type with color-coded status.
        """
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            print_header("All Active Orders")

            # Get regular orders
            print_info("\nFetching regular orders...")
            regular_orders = self.get_active_orders()

            # Get conditional orders
            print_info("Fetching conditional orders...")
            conditional_orders = self.conditional_order_tracker.list_all_active_orders()

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

                    table_data.append([
                        order.order_id[:12] + "...",
                        order.product_id,
                        format_side(order.side),
                        size,
                        price,
                        format_status(order.status)
                    ])

                print(tabulate(table_data, headers=["Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))
            else:
                print_info("No active regular orders.")

            # Display conditional orders
            if conditional_orders:
                print_header("\nConditional Orders (Stop-Loss, Take-Profit, Brackets)")

                # Separate by type
                stop_limit_orders = [o for o in conditional_orders if hasattr(o, 'order_type')]
                bracket_orders = [o for o in conditional_orders if not hasattr(o, 'order_type') and not hasattr(o, 'entry_order_id')]
                attached_bracket_orders = [o for o in conditional_orders if hasattr(o, 'entry_order_id')]

                # Display stop-limit orders
                if stop_limit_orders:
                    print_info("\nStop-Loss / Take-Profit Orders:")
                    table_data = []
                    for order in stop_limit_orders:
                        # Color code status
                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "TRIGGERED":
                            status_display = info(order.status)
                        elif order.status == "FILLED":
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            order.order_id[:12] + "...",
                            order.order_type,
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.stop_price,
                            order.limit_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["Order ID", "Type", "Product", "Side", "Size", "Stop Price", "Limit Price", "Status"], tablefmt="grid"))

                # Display bracket orders
                if bracket_orders:
                    print_info("\nBracket Orders (TP/SL on Position):")
                    table_data = []
                    for order in bracket_orders:
                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "ACTIVE":
                            status_display = info(order.status)
                        elif order.status == "FILLED":
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            order.order_id[:12] + "...",
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.limit_price,
                            order.stop_trigger_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["Order ID", "Product", "Side", "Size", "TP Price", "SL Price", "Status"], tablefmt="grid"))

                # Display attached bracket orders
                if attached_bracket_orders:
                    print_info("\nEntry + Bracket Orders (Entry with TP/SL):")
                    table_data = []
                    for order in attached_bracket_orders:
                        if order.status == "PENDING":
                            status_display = warning(order.status)
                        elif order.status == "ENTRY_FILLED":
                            status_display = info(order.status)
                        elif order.status in ["TP_FILLED", "SL_FILLED"]:
                            status_display = success(order.status)
                        else:
                            status_display = error(order.status)

                        table_data.append([
                            order.entry_order_id[:12] + "...",
                            order.product_id,
                            format_side(order.side),
                            order.base_size,
                            order.entry_limit_price,
                            order.take_profit_price,
                            order.stop_loss_price,
                            status_display
                        ])
                    print(tabulate(table_data, headers=["Order ID", "Product", "Side", "Size", "Entry", "TP", "SL", "Status"], tablefmt="grid"))

            else:
                print_info("No active conditional orders.")

            # Display summary
            total_orders = len(regular_orders) + len(conditional_orders)
            print("\n" + "="*50)
            print_info(f"Total active orders: {total_orders}")
            print_info(f"  Regular: {len(regular_orders)}")
            print_info(f"  Conditional: {len(conditional_orders)}")
            print("="*50)

        except CancelledException:
            print_info("\nCancelled. Returning to main menu.")
        except Exception as e:
            logging.error(f"Error in view_all_active_orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def cancel_any_orders(self):
        """
        Unified interface for cancelling any type of active order.
        Handles both regular orders and conditional orders.
        """
        if not self.client:
            print_warning("Please login first.")
            return

        try:
            print_header("Cancel Orders")

            # Get all active orders
            regular_orders = self.get_active_orders()
            conditional_orders = self.conditional_order_tracker.list_all_active_orders()

            if not regular_orders and not conditional_orders:
                print_info("No active orders to cancel.")
                return

            # Build combined list with metadata
            all_orders = []

            # Add regular orders
            for order in regular_orders:
                order_config = order.order_configuration
                config_type = next(iter(vars(order_config)))
                config = getattr(order_config, config_type)
                size = getattr(config, 'base_size', 'N/A')
                price = getattr(config, 'limit_price', 'N/A')

                all_orders.append({
                    'type': 'regular',
                    'order': order,
                    'display': f"Regular Order - {order.product_id} {format_side(order.side)} {size} @ {price}",
                    'order_id': order.order_id,
                    'status': order.status
                })

            # Add conditional orders
            for order in conditional_orders:
                if hasattr(order, 'order_type'):  # StopLimitOrder
                    display = f"{order.order_type} - {order.product_id} {format_side(order.side)} {order.base_size} (Stop: {order.stop_price})"
                    order_id = order.order_id
                    order_type = "stop_limit"
                elif hasattr(order, 'entry_order_id'):  # AttachedBracketOrder
                    display = f"Entry+Bracket - {order.product_id} {format_side(order.side)} {order.base_size} (Entry: {order.entry_limit_price})"
                    order_id = order.entry_order_id
                    order_type = "attached_bracket"
                else:  # BracketOrder
                    display = f"Bracket - {order.product_id} {format_side(order.side)} {order.base_size} (TP: {order.limit_price}, SL: {order.stop_trigger_price})"
                    order_id = order.order_id
                    order_type = "bracket"

                all_orders.append({
                    'type': 'conditional',
                    'order': order,
                    'display': display,
                    'order_id': order_id,
                    'conditional_type': order_type,
                    'status': order.status
                })

            # Display all orders
            print_info(f"Found {len(all_orders)} active order(s):\n")
            for i, order_info in enumerate(all_orders, 1):
                print(f"{i}. {order_info['display']}")
                print(f"   Order ID: {order_info['order_id'][:12]}...")
                print(f"   Status: {order_info['status']}")
                print()

            # Get user selection
            selection = self.get_input("Enter order numbers to cancel (comma-separated, or 'all')")

            if selection.lower() == 'all':
                orders_to_cancel = all_orders
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(',')]
                    orders_to_cancel = [all_orders[i] for i in indices if 0 <= i < len(all_orders)]
                except (ValueError, IndexError):
                    print_error("Invalid selection.")
                    return

            if not orders_to_cancel:
                print_info("No orders selected.")
                return

            # Confirm cancellation
            print_warning(f"\nYou are about to cancel {len(orders_to_cancel)} order(s).")
            confirm = self.get_input("Confirm cancellation? (yes/no)")
            if confirm.lower() not in ['yes', 'y']:
                print_info("Cancellation aborted.")
                return

            # Cancel each order
            cancelled_count = 0
            failed_count = 0

            for order_info in orders_to_cancel:
                try:
                    order_id = order_info['order_id']

                    # Cancel via API
                    self.rate_limiter.wait()
                    response = self.client.cancel_orders([order_id])

                    # Check response
                    success = False
                    if hasattr(response, 'results') and response.results:
                        result = response.results[0]
                        # CancelOrderObject has attributes, not dict methods
                        success = getattr(result, 'success', False)

                    if success:
                        # Update conditional order tracker if needed
                        if order_info['type'] == 'conditional':
                            self.conditional_order_tracker.update_order_status(
                                order_id=order_id,
                                order_type=order_info['conditional_type'],
                                status="CANCELLED",
                                fill_info=None
                            )

                            # Remove from monitoring
                            with self.conditional_lock:
                                if order_id in self.order_to_conditional_map:
                                    del self.order_to_conditional_map[order_id]

                        print_success(f"Cancelled: {order_id[:12]}...")
                        cancelled_count += 1
                    else:
                        # Get error message from CancelOrderObject attributes
                        error_msg = getattr(result, 'failure_reason', 'Unknown error') if hasattr(response, 'results') else "Unknown error"
                        print_error(f"Failed to cancel {order_id[:12]}...: {error_msg}")
                        failed_count += 1

                except Exception as e:
                    logging.error(f"Error cancelling order {order_id}: {str(e)}")
                    print_error(f"Error cancelling {order_id[:12]}...: {str(e)}")
                    failed_count += 1

            # Display summary
            print("\n" + "="*50)
            print_success(f"Successfully cancelled: {cancelled_count}")
            if failed_count > 0:
                print_error(f"Failed to cancel: {failed_count}")
            print("="*50)

        except CancelledException:
            print_info("\nCancellation aborted.")
        except Exception as e:
            logging.error(f"Error in cancel_any_orders: {str(e)}", exc_info=True)
            print_error(f"Error: {str(e)}")

    def get_twap_status(self, twap_id):
        """Get comprehensive status of a TWAP order execution."""
        if twap_id not in self.twap_orders:
            logging.warning(f"TWAP order {twap_id} not found")
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
            # Get latest fill information
            fills = self.check_order_fills_batch(order_ids)
            
            filled_count = len([oid for oid in order_ids if fills.get(oid, {}).get('status') == 'FILLED'])
            cancelled_count = 0
            pending_count = 0
            
            # Check remaining unfilled orders
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
            
            # Calculate completion rate
            completion_rate = 0
            if twap_info['total_value_placed'] > 0:
                completion_rate = (twap_info['total_value_filled'] / 
                                twap_info['total_value_placed']) * 100
            
            # Determine overall status
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

    def round_size(self, size, product_id):
        """Round order size to appropriate precision for the product."""
        try:
            # Get product info for precision
            product_info = self.client.get_product(product_id)
            base_increment = float(product_info['base_increment'])
            
            # Calculate precision from base increment
            if base_increment >= 1:
                precision = 0
            else:
                precision = abs(int(math.log10(base_increment)))
                
            return round(float(size), precision)
            
        except Exception as e:
            logging.error(f"Error rounding size: {str(e)}")
            # Fallback to product-specific precision from config
            if product_id in self.precision_config:
                precision = self.precision_config[product_id]['size']
                return round(float(size), precision)
            return float(size)  # Return as-is if no precision info available

    def round_price(self, price, product_id):
        """Round price to appropriate precision for the product."""
        try:
            # Get product info for precision
            product_info = self.client.get_product(product_id)
            quote_increment = float(product_info['quote_increment'])
            
            # Calculate precision from quote increment
            if quote_increment >= 1:
                precision = 0
            else:
                precision = abs(int(math.log10(quote_increment)))
                
            return round(float(price), precision)
            
        except Exception as e:
            logging.error(f"Error rounding price: {str(e)}")
            # Fallback to product-specific precision from config
            if product_id in self.precision_config:
                precision = self.precision_config[product_id]['price']
                return round(float(price), precision)
            return float(price)  # Return as-is if no precision info available

    def get_order_input(self):
        """
        Helper function to get common order parameters from user input.
        Returns a dictionary with the order parameters or None if input validation fails.
        """
        logging.info("Getting order input parameters from user")

        try:
            # Get market selection
            product_id = self._select_market()
            if not product_id:
                return None

            # Get side
            while True:
                side = self.get_input("\nEnter order side (buy/sell)").upper()
                logging.debug(f"User selected side: {side}")
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            # Get current prices
            current_prices = self.get_current_prices(product_id)
            if current_prices:
                print(f"\nCurrent market prices for {product_id}:")
                print(f"Bid: ${current_prices['bid']:.2f}")
                print(f"Ask: ${current_prices['ask']:.2f}")
                print(f"Mid: ${current_prices['mid']:.2f}")

            # Get limit price
            while True:
                try:
                    limit_price = float(self.get_input("\nEnter limit price"))
                    logging.debug(f"User entered limit price: {limit_price}")
                    if limit_price <= 0:
                        print("Price must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Get order size
            while True:
                try:
                    base_size = float(self.get_input("\nEnter order size"))
                    logging.debug(f"User entered base size: {base_size}")
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Validate against minimum order size
            product_info = self.client.get_product(product_id)
            min_size = float(product_info['base_min_size'])
            if base_size < min_size:
                logging.error(f"Order size {base_size} is below minimum {min_size}")
                print(f"Error: Order size must be at least {min_size}")
                return None

            return {
                "product_id": product_id,
                "side": side,
                "limit_price": limit_price,
                "base_size": base_size
            }

        except CancelledException:
            # User cancelled - exit gracefully without error logging
            raise
        except Exception as e:
            logging.error(f"Error getting order input: {str(e)}", exc_info=True)
            print(f"Error getting order input: {str(e)}")
            return None

    def get_conditional_order_input(self):
        """
        Simplified input for conditional orders (stop-loss, take-profit, brackets).
        Gets market, side, and size WITHOUT asking for limit price.
        Returns a dictionary with the order parameters or None if validation fails.
        """
        logging.info("Getting conditional order input parameters from user")

        try:
            # Get market selection
            product_id = self._select_market()
            if not product_id:
                return None

            # Get side
            while True:
                side = self.get_input("\nEnter order side (buy/sell)").upper()
                logging.debug(f"User selected side: {side}")
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            # Get order size
            while True:
                try:
                    base_size = float(self.get_input("\nEnter order size"))
                    logging.debug(f"User entered base size: {base_size}")
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Validate against minimum order size
            product_info = self.client.get_product(product_id)
            min_size = float(product_info['base_min_size'])
            if base_size < min_size:
                logging.error(f"Order size {base_size} is below minimum {min_size}")
                print(f"Error: Order size must be at least {min_size}")
                return None

            return {
                "product_id": product_id,
                "side": side,
                "base_size": base_size
            }

        except CancelledException:
            # User cancelled - exit gracefully without error logging
            raise
        except Exception as e:
            logging.error(f"Error getting conditional order input: {str(e)}", exc_info=True)
            print(f"Error getting conditional order input: {str(e)}")
            return None

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
                    order_id = fill.order_id[:8] + "..."  # Truncate for display
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
            # Get list of all TWAP orders from tracker
            twap_ids = self.twap_tracker.list_twap_orders()
            if not twap_ids:
                print("No TWAP orders found")
                return []

            print("\nTWAP Orders:")
            print("=" * 100)

            for i, twap_id in enumerate(twap_ids, 1):
                # Get order and stats from tracker
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

                    # Show maker/taker split if fills exist
                    maker_fills = stats.get('maker_fills', 0)
                    taker_fills = stats.get('taker_fills', 0)
                    if maker_fills + taker_fills > 0:
                        maker_pct = (maker_fills / (maker_fills + taker_fills) * 100)
                        print(f"   Maker/Taker: {maker_pct:.1f}% maker")

                    # Show fees if present
                    total_fees = stats.get('total_fees', 0)
                    if total_fees > 0:
                        fee_bps = (total_fees / stats['total_value_filled']) * 10000
                        print(f"   Total Fees: ${total_fees:.2f} ({fee_bps:.1f} bps)")

                    # Show VWAP if available
                    if 'vwap' in stats:
                        print(f"   VWAP: ${stats['vwap']:.2f}")

                print("-" * 100)

            return twap_ids

        except Exception as e:
            logging.error(f"Error displaying TWAP orders: {str(e)}")
            print("Error displaying TWAP orders. Please check the logs for details.")
            return []

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
                print("2. View order history")

                # Basic Orders
                print(info("\n=== Basic Orders ==="))
                print("3. Limit order")
                print("4. Stop-loss order (standalone)")
                print("5. Take-profit order (standalone)")

                # Advanced Orders
                print(info("\n=== Advanced Orders ==="))
                print("6. Entry + Bracket (new position with TP/SL)")
                print("7. Bracket Existing Position (add TP/SL protection)")

                # Algorithmic Trading
                print(info("\n=== Algorithmic Trading ==="))
                print("8. TWAP order")
                print("9. View TWAP fills")

                # Order Management
                print(info("\n=== Order Management ==="))
                print("10. View active orders")
                print("11. Cancel orders")

                try:
                    choice = self.get_input("\nEnter your choice (1-11)")
                except CancelledException:
                    print_info("\nExiting application.")
                    break

                if choice == '1':
                    self.view_portfolio()
                elif choice == '2':
                    self.view_order_history()
                elif choice == '3':
                    logging.debug("Starting limit order placement from run()")
                    result = self.place_limit_order()
                    logging.debug(f"Limit order placement completed with result: {result}")
                    logging.debug("Returning to main menu")
                elif choice == '4':
                    order_id = self.place_stop_loss_order()
                    if order_id:
                        print_success(f"Stop-loss order placed: {order_id}")
                elif choice == '5':
                    order_id = self.place_take_profit_order()
                    if order_id:
                        print_success(f"Take-profit order placed: {order_id}")
                elif choice == '6':
                    order_id = self.place_entry_with_bracket()
                    if order_id:
                        print_success(f"Entry+Bracket order placed: {order_id}")
                elif choice == '7':
                    order_id = self.place_bracket_for_position()
                    if order_id:
                        print_success(f"Bracket order placed: {order_id}")
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
                    # Combined view: show all active orders (regular + conditional)
                    self.view_all_active_orders()
                elif choice == '11':
                    # Combined cancel: cancel any active orders
                    self.cancel_any_orders()
                else:
                    print_warning("Invalid choice. Please try again.")
        except Exception as e:
            logging.error(f"Critical error in main execution: {str(e)}", exc_info=True)
        finally:
            self.is_running = False
            if self.checker_thread and self.checker_thread.is_alive():
                self.checker_thread.join(timeout=5)  # Wait up to 5 seconds for thread to clean up
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