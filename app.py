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

            logging.info("TradingTerminal initialization completed successfully")

        except Exception as e:
            logging.critical(f"Failed to initialize TradingTerminal: {str(e)}", exc_info=True)
            raise
    
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
            print("Please login first.")
            return

        logging.debug("Starting limit order placement")
        
        try:
            # Get market data
            logging.debug("Fetching market data")
            rows, headers, top_markets = self.get_consolidated_markets(20)
            
            if not rows:
                logging.error("Failed to fetch top markets")
                print("Error fetching market data. Please try again.")
                return
                
            print("\nTop Markets by 24h Volume:")
            print("=" * 120)
            print(tabulate(rows, headers=headers, tablefmt="plain", numalign="left"))
            print("=" * 120)
            
            # Get market selection
            logging.debug("Getting market selection")
            while True:
                product_choice = input("\nEnter the number of the market to trade (1-20): ")
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
                                quote_choice = input(f"Select quote currency (1-{len(available_quotes)}): ")
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
                        break
                    else:
                        print("Invalid selection. Please enter a number between 1 and 20.")
                except ValueError:
                    print("Please enter a valid number.")

            # Get side
            while True:
                side = input("\nEnter order side (buy/sell): ").upper()
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
                    limit_price = float(input("\nEnter limit price: "))
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
                    base_size = float(input("\nEnter order size: "))
                    logging.debug(f"User entered base size: {base_size}")
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            # Show order summary
            print("\nOrder Summary:")
            print(f"Product: {product_id}")
            print(f"Side: {side}")
            print(f"Size: {base_size}")
            print(f"Limit Price: ${limit_price:.2f}")

            if side == "BUY":
                total_cost = base_size * limit_price
                print(f"Total Cost: ${total_cost:.2f}")
            else:
                total_value = base_size * limit_price
                print(f"Total Value: ${total_value:.2f}")

            confirm = input("\nDo you want to place this order? (yes/no): ").lower()
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
                    print(f"\nOrder placed successfully!")
                    print(f"Order ID: {order_id}")
                    
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

        except Exception as e:
            logging.error(f"Error in place_limit_order: {str(e)}", exc_info=True)
            print(f"\nError placing order: {str(e)}")
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

            # Get current fee rates from transaction summary
            try:
                fee_info = self.client.get_transaction_summary()
                if hasattr(fee_info, 'fee_tier') and isinstance(fee_info.fee_tier, dict):
                    fee_tier = fee_info.fee_tier
                    maker_rate = float(fee_tier.get('maker_fee_rate', '0.004'))
                    taker_rate = float(fee_tier.get('taker_fee_rate', '0.006'))
                    logging.info(f"Current fee rates - Maker: {maker_rate:.4%}, Taker: {taker_rate:.4%}")
                else:
                    logging.warning("Unable to get fee tier info, using default rates")
                    maker_rate = 0.004  # 0.4%
                    taker_rate = 0.006  # 0.6%
            except Exception as e:
                logging.error(f"Error getting fee rates: {str(e)}")
                maker_rate = 0.004
                taker_rate = 0.006

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
            base_min_size = float(product_info['base_min_size'])
            base_max_size = float(product_info['base_max_size'])
            quote_increment = float(product_info['quote_increment'])
            
            # Validate order size
            if float(base_size) < base_min_size:
                logging.warning(f"Order size {base_size} is below minimum {base_min_size} for {product_id}")
                return None
                
            if float(base_size) > base_max_size:
                logging.warning(f"Order size {base_size} is above maximum {base_max_size} for {product_id}")
                return None
                
            # Round price to appropriate increment
            rounded_price = round(float(limit_price) / quote_increment) * quote_increment
            
            # Get available balance
            if side == "BUY":
                quote_currency = product_id.split('-')[1]
                required_funds = float(base_size) * float(limit_price)
                available_balance = self.get_account_balance(quote_currency)
                if available_balance < required_funds:
                    logging.warning(f"Insufficient {quote_currency} balance")
                    return None
            else:
                base_currency = product_id.split('-')[0]
                available_balance = self.get_account_balance(base_currency)
                if available_balance < float(base_size):
                    logging.warning(f"Insufficient {base_currency} balance")
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

    def show_and_cancel_orders(self):
        """Display active orders and allow cancellation."""
        if not self.client:
            logging.warning("Attempt to show/cancel orders without login")
            print("Please login first.")
            return

        try:
            active_orders = self.get_active_orders()
            
            if not active_orders:
                logging.info("No active orders found")
                print("No active orders found.")
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
                    order.side,
                    size,
                    price,
                    order.status
                ])

            print("\nActive Orders:")
            print(tabulate(table_data, headers=["Number", "Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))

            while True:
                action = input("\nWould you like to cancel any orders? (yes/no/all): ").lower()
                
                if action == 'no':
                    break
                elif action == 'all':
                    order_ids = [order.order_id for order in active_orders]
                    result = self.client.cancel_orders(order_ids)
                    if hasattr(result, 'results'):
                        cancelled_count = len(result.results)
                        logging.info(f"Cancelled {cancelled_count} orders")
                        print(f"Cancelled {cancelled_count} orders.")
                    break
                elif action == 'yes':
                    order_number = input("Enter the Number of the order to cancel: ")
                    try:
                        order_index = int(order_number) - 1
                        if 0 <= order_index < len(active_orders):
                            order_id = active_orders[order_index].order_id
                            result = self.client.cancel_orders([order_id])
                            
                            if result and hasattr(result, 'results') and result.results:
                                logging.info(f"Order {order_id} cancelled successfully")
                                print(f"Order {order_id} cancelled successfully.")
                                active_orders = self.get_active_orders()
                                if not active_orders:
                                    break
                            else:
                                logging.error(f"Failed to cancel order {order_id}")
                                print(f"Failed to cancel order {order_id}.")
                        else:
                            print("Invalid order number.")
                    except ValueError:
                        print("Please enter a valid order number.")
                else:
                    print("Invalid input. Please enter 'yes', 'no', or 'all'.")

        except Exception as e:
            logging.error(f"Error managing orders: {str(e)}")
            print(f"Error managing orders: {str(e)}")        

    def view_portfolio(self):
        """View and display the user's portfolio."""
        if not self.client:
            logging.warning("Attempt to view portfolio without login")
            print("Please login first.")
            return

        try:
            logging.info("Fetching accounts for portfolio view")
            print("\nFetching accounts (this may take a moment due to rate limiting):")
            accounts = self.get_accounts(force_refresh=True)
            self.display_portfolio(accounts)
        except Exception as e:
            logging.error(f"Error fetching portfolio: {str(e)}")
            print(f"Error fetching portfolio: {str(e)}")

    def display_portfolio(self, accounts_data):
        """Display the portfolio data."""
        portfolio_data = []
        total_usd_value = 0

        for currency, account in accounts_data.items():
            balance = float(account['available_balance']['value'])  # Direct dictionary access
            logging.info(f"Processing {currency} balance: {balance}")
            
            if balance > 0:
                if currency in ['USD', 'USDC', 'USDT', 'DAI']:
                    usd_value = balance
                else:
                    try:
                        self.rate_limiter.wait()
                        product_id = f"{currency}-USD"
                        ticker = self.client.get_product(product_id)
                        usd_price = float(ticker['price'])  # Direct dictionary access
                        usd_value = balance * usd_price
                    except Exception as e:
                        logging.warning(f"Couldn't get USD value for {currency}. Error: {str(e)}")
                        continue

                if usd_value >= 1:
                    portfolio_data.append([currency, balance, usd_value])
                    total_usd_value += usd_value
                    logging.info(f"Added {currency} to portfolio: Balance={balance}, USD Value=${usd_value:.2f}")

        # Sort and display portfolio
        portfolio_data.sort(key=lambda x: x[2], reverse=True)
        table_data = [[f"{row[0]} ({row[1]:.8f})", f"${row[2]:.2f}"] for row in portfolio_data]

        logging.info(f"Portfolio summary generated. Total value: ${total_usd_value:.2f} USD")
        print("\nPortfolio Summary:")
        print(f"Total Portfolio Value: ${total_usd_value:.2f} USD")
        print("\nAsset Balances:")
        print(tabulate(table_data, headers=["Asset (Amount)", "USD Value"], tablefmt="grid"))

    def login(self):
        """Authenticate user and initialize the API client."""
        logging.info("Initiating login process")
        print("Welcome to the Coinbase Trading Terminal!")

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
            print("Login successful!")
            return True

        except ConfigurationError as e:
            logging.error(f"Configuration error: {str(e)}", exc_info=True)
            print(f"\nConfiguration Error:\n{str(e)}")
            self.client = None
            return False
        except AttributeError as e:
            logging.error(f"API credentials error: {str(e)}", exc_info=True)
            print("Error accessing API credentials. Please check your configuration.")
            self.client = None
            return False
        except Exception as e:
            logging.error(f"Login failed: {str(e)}", exc_info=True)
            print(f"Login failed: {str(e)}")
            self.client = None
            return False

    def order_status_checker(self):
        """Background thread to check order statuses efficiently."""
        logging.debug("Starting order_status_checker thread")
        
        while self.is_running:
            try:
                if not self.twap_orders:
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
            print("Please login first.")
            return None

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

        duration = int(input("Enter TWAP duration in minutes: "))
        num_slices = int(input("Enter number of slices for TWAP: "))

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
        price_type = input("Enter your choice (1-4): ")

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
            # Get market data for selection
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
            while True:
                product_choice = input("\nEnter the number of the market to trade (1-20): ")
                logging.debug(f"User selected market number: {product_choice}")
                try:
                    index = int(product_choice)
                    if 1 <= index <= len(top_markets):
                        base_currency, market_data = top_markets[index - 1]
                        
                        # Handle quote currency selection
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
                                quote_choice = input(f"Select quote currency (1-{len(available_quotes)}): ")
                                try:
                                    quote_index = int(quote_choice)
                                    if 1 <= quote_index <= len(available_quotes):
                                        quote_currency = available_quotes[quote_index - 1]
                                        break
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
                        break
                    print("Invalid selection. Please enter a number between 1 and 20.")
                except ValueError:
                    print("Please enter a valid number.")

            # Get side
            while True:
                side = input("\nEnter order side (buy/sell): ").upper()
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
                    limit_price = float(input("\nEnter limit price: "))
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
                    base_size = float(input("\nEnter order size: "))
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

        except Exception as e:
            logging.error(f"Error getting order input: {str(e)}", exc_info=True)
            print(f"Error getting order input: {str(e)}")
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
        """Display comprehensive list of all TWAP orders with execution statistics."""
        try:
            # Get list of all TWAP orders from tracker
            twap_ids = self.twap_tracker.list_twap_orders()
            if not twap_ids:
                print("No TWAP orders found")
                return
                
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

        except Exception as e:
            logging.error(f"Error displaying TWAP orders: {str(e)}")
            print("Error displaying TWAP orders. Please check the logs for details.")

    def run(self):
        """Main execution loop for the trading terminal."""
        try:
            if not self.login():
                print("Unable to start trading terminal due to login failure.")
                return
                    
            while True:
                print("\nWhat would you like to do?")
                print("1. View portfolio balances")
                print("2. Place a limit order")
                print("3. Place a TWAP order")
                print("4. Check TWAP order fills")
                print("5. Show and cancel active orders")
                print("6. Exit")
                
                choice = input("Enter your choice (1-6): ")
                
                if choice == '1':
                    self.view_portfolio()
                elif choice == '2':
                    logging.debug("Starting limit order placement from run()")
                    result = self.place_limit_order()
                    logging.debug(f"Limit order placement completed with result: {result}")
                    logging.debug("Returning to main menu")
                elif choice == '3':
                    twap_id = self.place_twap_order()
                    if twap_id:
                        print(f"TWAP order placed with ID: {twap_id}")
                elif choice == '4':
                    self.display_all_twap_orders()
                    twap_number = input("Enter the number of the TWAP order to check: ")
                    try:
                        twap_index = int(twap_number) - 1
                        if 0 <= twap_index < len(self.twap_orders):
                            twap_id = list(self.twap_orders.keys())[twap_index]
                            self.check_twap_order_fills(twap_id)
                        else:
                            print("Invalid TWAP order number.")
                    except ValueError:
                        print("Please enter a valid number.")
                elif choice == '5':
                    self.show_and_cancel_orders()
                elif choice == '6':
                    if self.checker_thread and self.checker_thread.is_alive():
                        self.is_running = False
                        self.checker_thread.join()
                    print("Thank you for using the Coinbase Trading Terminal. Goodbye!")
                    break
                else:
                    print("Invalid choice. Please try again.")
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