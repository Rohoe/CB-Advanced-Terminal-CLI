import logging
from keys import Keys
from coinbase.rest import RESTClient
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

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler()
        ]
    )
    
    # Log the start of the session
    logging.info("="*50)
    logging.info("Starting new trading session")
    logging.info("="*50)

# Call setup_logging at the start
setup_logging()

# Configurable parameters
CONFIG = {
    'retries': 3,
    'backoff_in_seconds': 1,
    'rate_limit_requests': 25,
    'rate_limit_burst': 50,
    'twap_slice_delay': 2,
}

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
    def __init__(self):
        """Initialize the trading terminal."""
        logging.info("Initializing TradingTerminal")
        try:
            self.client = None
            logging.debug("Creating RateLimiter")
            self.rate_limiter = RateLimiter(CONFIG['rate_limit_requests'], CONFIG['rate_limit_burst'])
            
            logging.debug("Initializing queues and locks")
            self.order_queue = Queue()
            self.filled_orders = []
            self.order_lock = Lock()
            self.is_running = True
            
            logging.debug("Starting checker thread")
            self.checker_thread = Thread(target=self.order_status_checker)
            self.checker_thread.daemon = True  # Make thread daemonic
            self.checker_thread.start()
            
            logging.debug("Initializing caches")
            self.order_status_cache = {}
            self.cache_ttl = 5
            self.failed_orders = set()
            
            self.precision_config = {
                'SOL-USDC': {'price': 2, 'size': 4},
                'BTC-USDC': {'price': 2, 'size': 8},
                'ETH-USDC': {'price': 2, 'size': 8},
            }
            
            self.twap_orders = {}
            self.order_to_twap_map = {}
            self.account_cache = {}
            self.account_cache_time = 0
            self.account_cache_ttl = 60
            self.fill_cache = {}
            self.fill_cache_time = 0
            self.fill_cache_ttl = 5
            
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

    def check_order_filled(self, order_id):
        """Check if an order has been filled."""
        if not order_id:
            return {'filled': False, 'filled_size': 0, 'filled_price': 0}

        current_time = time.time()
        
        # Check cache first
        if order_id in self.order_status_cache:
            cached_status, cache_time = self.order_status_cache[order_id]
            if current_time - cache_time < self.cache_ttl:
                return cached_status

        try:
            order_response = self.client.get_order(order_id)
            order = order_response['order']  # Direct dictionary access
            
            filled = order['status'] == 'FILLED'
            filled_size = float(order['filled_size']) if 'filled_size' in order else 0
            filled_price = float(order['average_filled_price'])
            
            status = {'filled': filled, 'filled_size': filled_size, 'filled_price': filled_price}
            
            # Update cache
            self.order_status_cache[order_id] = (status, current_time)
            
            return status
            
        except Exception as e:
            logging.error(f"Error checking order status for {order_id}: {str(e)}")
            return {'filled': False, 'filled_size': 0, 'filled_price': 0}

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
        """Check fills for multiple orders efficiently."""
        if not order_ids:
            return {}

        try:
            fills_response = self.client.get_fills(order_ids=order_ids)
            fills = fills_response['fills']  # Direct dictionary access
            
            fills_by_order = defaultdict(lambda: {
                'filled_size': 0.0,
                'filled_value': 0.0,
                'fees': 0.0,
                'is_maker': False
            })

            for fill in fills:
                order_id = fill['order_id']
                fill_size = float(fill['size'])
                fill_price = float(fill['price'])
                fill_fee = float(fill['fee']) if 'fee' in fill else 0
                is_maker = fill.get('liquidity_indicator') == 'M'

                fills_by_order[order_id]['filled_size'] += fill_size
                fills_by_order[order_id]['filled_value'] += fill_size * fill_price
                fills_by_order[order_id]['fees'] += fill_fee
                fills_by_order[order_id]['is_maker'] |= is_maker

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

    def place_limit_order(self):
        """Place a limit order with user input."""
        if not self.client:
            logging.warning("Attempt to place limit order without login")
            print("Please login first.")
            return

        logging.info("Starting limit order placement")
        
        # Get product ID using consolidated markets
        try:
            rows, headers, top_markets = self.get_consolidated_markets(20)
        except Exception as e:
            logging.error(f"Error fetching and processing market data: {str(e)}")
            print("Error fetching market data. Please try again.")
            return
            
        if not rows:
            logging.error("Failed to fetch top markets")
            print("Error fetching market data. Please try again.")
            return
            
        print("\nTop Markets by 24h Volume:")
        print("=" * 120)
        print(tabulate(rows, headers=headers, tablefmt="plain", numalign="left"))
        print("=" * 120)
        
        # Get market selection
        while True:
            product_choice = input("\nEnter the number of the market to trade (1-20): ")
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
                        
                    break
                else:
                    print("Invalid selection. Please enter a number between 1 and 20.")
            except ValueError:
                print("Please enter a valid number.")

        # Get side (buy/sell)
        while True:
            side = input("\nEnter order side (buy/sell): ").upper()
            if side in ['BUY', 'SELL']:
                break
            print("Invalid side. Please enter 'buy' or 'sell'.")

        # Get current market prices
        try:
            current_prices = self.get_current_prices(product_id)
            if current_prices:
                print(f"\nCurrent market prices for {product_id}:")
                print(f"Bid: ${current_prices['bid']:.2f}")
                print(f"Ask: ${current_prices['ask']:.2f}")
                print(f"Mid: ${current_prices['mid']:.2f}")
        except Exception as e:
            logging.error(f"Error fetching current prices: {str(e)}")
            print("Unable to fetch current market prices.")
            return

        # Get limit price
        while True:
            try:
                limit_price = float(input("\nEnter limit price: "))
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
                if base_size <= 0:
                    print("Size must be greater than 0.")
                    continue
                break
            except ValueError:
                print("Please enter a valid number.")

        # Show order summary and confirm
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
        if confirm != 'yes':
            print("Order cancelled.")
            return

        # Place the order
        try:
            order_response = self.place_limit_order_with_retry(
                product_id=product_id,
                side=side,
                base_size=str(base_size),
                limit_price=str(limit_price),
                client_order_id=f"limit-{int(time.time())}"
            )

            if order_response:
                order_id = order_response['order_id'] if 'order_id' in order_response else \
                        order_response['success_response']['order_id']
                logging.info(f"Limit order placed successfully. Order ID: {order_id}")
                print(f"\nOrder placed successfully!")
                print(f"Order ID: {order_id}")
            else:
                logging.error("Failed to place limit order")
                print("\nFailed to place order. Please try again.")

        except Exception as e:
            logging.error(f"Error placing limit order: {str(e)}")
            print(f"\nError placing order: {str(e)}")

    def update_twap_fills(self, twap_id):
        """Update fill information for a TWAP order."""
        if twap_id not in self.twap_orders:
            return

        twap_info = self.twap_orders[twap_id]
        order_ids = twap_info['orders']

        # Process orders in batches
        batch_size = 50
        for i in range(0, len(order_ids), batch_size):
            batch_order_ids = order_ids[i:i + batch_size]
            fills = self.check_order_fills_batch(batch_order_ids)

            for order_id, fill_info in fills.items():
                old_filled = twap_info.get(f'filled_{order_id}', 0)
                new_filled = fill_info['filled_size']
                
                if new_filled > old_filled:
                    twap_info[f'filled_{order_id}'] = new_filled
                    twap_info['total_filled'] += (new_filled - old_filled)
                    twap_info['total_value_filled'] += fill_info['filled_value']
                    twap_info['total_fees'] += fill_info['fees']
                    
                    if fill_info['is_maker']:
                        twap_info['maker_orders'] += 1
                    else:
                        twap_info['taker_orders'] += 1

    def place_limit_order_with_retry(self, product_id, side, base_size, limit_price, client_order_id=None):
        """Place a limit order with enhanced error handling and validation."""
        try:
            # Pre-order validation
            if float(base_size) <= 0:
                raise ValueError("Order size must be greater than 0")
                
            # Get minimum order size for the product
            product_info = self.client.get_product(product_id)
            base_min_size = float(product_info['base_min_size'])  # Direct dictionary access
            base_max_size = float(product_info['base_max_size'])  # Direct dictionary access
            quote_increment = float(product_info['quote_increment'])  # Direct dictionary access
            
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

            # Place the order
            order_response = self.client.limit_order_gtc(
                client_order_id=client_order_id or f"limit-order-{int(time.time())}",
                product_id=product_id,
                side=side,
                base_size=str(self.round_size(base_size, product_id)),
                limit_price=str(self.round_price(rounded_price, product_id))
            )
            
            # Handle response
            if 'success_response' in order_response:
                return order_response
            elif 'order_id' in order_response:
                return order_response
                
            logging.error(f"Unexpected order response format: {order_response}")
            return None
            
        except Exception as e:
            logging.error(f"Error placing limit order: {str(e)}")
            return None

    def place_twap_slice(self, twap_id, slice_number, total_slices, order_input, execution_price):
        """Place a single TWAP slice with comprehensive error handling."""
        try:
            twap_info = self.twap_orders[twap_id]
            total_target = float(order_input["base_size"])
            total_placed = twap_info['total_placed']
            remaining_quantity = total_target - total_placed
            
            # Calculate slice size
            if slice_number == total_slices:
                slice_size = remaining_quantity
            else:
                slice_size = order_input["base_size"] / total_slices
                
            # Validate minimum slice size
            product_info = self.client.get_product(order_input["product_id"])
            min_size = float(product_info['base_min_size'])  # Direct dictionary access
            
            if slice_size < min_size:
                logging.warning(f"Slice size {slice_size} is below minimum {min_size}. Adjusting to minimum.")
                slice_size = min_size

            # Place the order
            client_order_id = f"twap-{twap_id}-{slice_number}-{int(time.time())}"
            order_response = self.place_limit_order_with_retry(
                product_id=order_input["product_id"],
                side=order_input["side"],
                base_size=slice_size,
                limit_price=execution_price,
                client_order_id=client_order_id
            )
            
            if not order_response:
                self.twap_orders[twap_id]['failed_slices'].add(slice_number)
                if slice_number < total_slices:
                    remaining_slices = total_slices - slice_number
                    self.twap_orders[twap_id]['slice_size_adjustment'] = slice_size / remaining_slices
                return None
                
            # Extract order ID using direct dictionary access
            order_id = order_response['success_response']['order_id'] if 'success_response' in order_response else order_response['order_id']
            
            if order_id:
                self.twap_orders[twap_id]['orders'].append(order_id)
                self.twap_orders[twap_id]['total_placed'] += float(slice_size)
                self.twap_orders[twap_id]['total_value_placed'] += (
                    float(slice_size) * float(execution_price)
                )
                self.order_to_twap_map[order_id] = twap_id
                
                logging.info(f"TWAP slice {slice_number}/{total_slices} placed successfully. Order ID: {order_id}")
                return order_id
            
            logging.error(f"Failed to extract order ID from response: {order_response}")
            self.twap_orders[twap_id]['failed_slices'].add(slice_number)
            return None
            
        except Exception as e:
            logging.error(f"Error placing TWAP slice {slice_number}: {str(e)}")
            self.twap_orders[twap_id]['failed_slices'].add(slice_number)
            return None

    def get_active_orders(self):
        """Get list of active orders."""
        try:
            orders_response = self.client.list_orders()
            all_orders = orders_response['orders']  # Direct dictionary access
            active_orders = [order for order in all_orders 
                           if order['status'] in ['OPEN', 'PENDING']]  # Direct dictionary access
            return active_orders
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
                order_config = order['order_configuration']  # Direct dictionary access
                config_type = next(iter(order_config))
                config = order_config[config_type]
                
                size = config['base_size'] if 'base_size' in config else 'N/A'
                price = config['limit_price'] if 'limit_price' in config else 'N/A'
                
                table_data.append([
                    i,
                    order['order_id'],
                    order['product_id'],
                    order['side'],
                    size,
                    price,
                    order['status']
                ])

            print("\nActive Orders:")
            print(tabulate(table_data, headers=["Number", "Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))

            while True:
                action = input("\nWould you like to cancel any orders? (yes/no/all): ").lower()
                
                if action == 'no':
                    break
                elif action == 'all':
                    order_ids = [order['order_id'] for order in active_orders]
                    result = self.client.cancel_orders(order_ids)
                    cancelled_count = len(result['results']) if 'results' in result else 0
                    logging.info(f"Cancelled {cancelled_count} orders")
                    print(f"Cancelled {cancelled_count} orders.")
                    break
                elif action == 'yes':
                    order_number = input("Enter the Number of the order to cancel: ")
                    try:
                        order_index = int(order_number) - 1
                        if 0 <= order_index < len(active_orders):
                            order_id = active_orders[order_index]['order_id']
                            result = self.client.cancel_orders([order_id])
                            
                            if result and 'results' in result and result['results']:
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
        """Authenticate user and initialize the RESTClient."""
        logging.info("Initiating login process")
        print("Welcome to the Coinbase Trading Terminal!")
        
        try:
            logging.debug("Attempting to retrieve API credentials")
            api_key = Keys.api_key
            api_secret = Keys.api_secret

            logging.debug("Checking API credentials")
            if not api_key or not api_secret:
                raise ValueError("API key or secret not found")

            logging.debug("Initializing REST client")
            self.client = RESTClient(api_key=api_key, api_secret=api_secret, verbose=True)
            
            logging.debug("Waiting for rate limiter")
            self.rate_limiter.wait()
            
            logging.debug("Making test authentication request")
            test_response = self.client.get_accounts()
            
            # logging.debug(f"Authentication response received: {test_response}")
            
            # Access test_response.accounts which should be a list
            if not hasattr(test_response, 'accounts'):
                logging.error(f"Response missing accounts field")
                raise Exception("Failed to authenticate with API - 'accounts' not in response")
                
            # If we get here, authentication was successful
            logging.info("Login successful")
            print("Login successful!")
            return True
            
        except AttributeError as e:
            logging.error(f"API credentials error: {str(e)}", exc_info=True)
            print("Error accessing API credentials. Please check your Keys.py file.")
            self.client = None
            return False
        except Exception as e:
            logging.error(f"Login failed: {str(e)}", exc_info=True)
            print(f"Login failed: {str(e)}")
            self.client = None
            return False

    def order_status_checker(self):
        """Background thread to check order statuses efficiently."""
        while self.is_running:
            try:
                orders_to_check = []
                try:
                    while len(orders_to_check) < 50:  # Process up to 50 orders at a time
                        order = self.order_queue.get(timeout=1)
                        if order is None:  # Check for shutdown signal
                            return
                        orders_to_check.append(order)
                except Empty:
                    if not orders_to_check:  # No orders to process
                        continue

                # Get unique order IDs
                order_ids = list(set(order['order_id'] for order in orders_to_check if order.get('order_id')))
                if not order_ids:
                    continue

                # Get fills in batch
                fills_response = self.client.get_fills(order_ids=order_ids, limit=100)
                if 'fills' in fills_response:  # Direct dictionary access
                    fills = fills_response['fills']
                    processed_orders = set()
                    
                    for fill in fills:
                        order_id = fill['order_id']
                        twap_id = self.order_to_twap_map.get(order_id)
                        
                        if twap_id and order_id not in processed_orders:
                            with threading.Lock():
                                filled_size = float(fill['size'])  # Direct dictionary access
                                filled_price = float(fill['price'])  # Direct dictionary access
                                
                                self.twap_orders[twap_id]['total_filled'] += filled_size
                                self.twap_orders[twap_id]['total_value_filled'] += filled_size * filled_price
                                
                                # Track fees - direct dictionary access with default
                                fees = float(fill['fee']) if 'fee' in fill else 0
                                self.twap_orders[twap_id]['total_fees'] += fees
                                
                                processed_orders.add(order_id)

                # Put unprocessed orders back in queue
                for order in orders_to_check:
                    if order['order_id'] not in processed_orders:
                        self.order_queue.put(order)

            except Exception as e:
                logging.error(f"Error in order status checker: {str(e)}")
                continue

    def place_twap_order(self):
        """Place a Time-Weighted Average Price (TWAP) order with comprehensive logging."""
        if not self.client:
            logging.warning("Attempt to place TWAP order without login")
            print("Please login first.")
            return

        logging.info("=" * 50)
        logging.info("STARTING NEW TWAP ORDER")
        logging.info("=" * 50)

        order_input = self.get_order_input()
        if not order_input:
            return

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
            min_size = float(product_info['base_min_size'])  # Direct dictionary access
            max_size = float(product_info['base_max_size'])  # Direct dictionary access
            quote_increment = float(product_info['quote_increment'])  # Direct dictionary access
            
            logging.info(f"Product Constraints:")
            logging.info(f"Minimum Order Size: {min_size} {base_currency}")
            logging.info(f"Maximum Order Size: {max_size} {base_currency}")
            logging.info(f"Price Increment: {quote_increment} {quote_currency}")
            
            # Validate slice size
            slice_size = order_input["base_size"] / num_slices
            if slice_size < min_size:
                logging.error(f"Calculated slice size {slice_size} is below minimum {min_size}")
                print(f"Error: Slice size {slice_size} is below minimum {min_size}")
                return
        except Exception as e:
            logging.error(f"Error fetching product information: {str(e)}")
            print(f"Error fetching product information: {str(e)}")
            return

        print("\nSelect price type for order placement:")
        print("1. Original limit price")
        print("2. Current market bid")
        print("3. Current market mid")
        print("4. Current market ask")
        price_type = input("Enter your choice (1-4): ")

        # Create TWAP ID and initialize tracking
        twap_id = str(uuid.uuid4())
        self.twap_orders[twap_id] = {
            'orders': [],
            'total_placed': 0,
            'total_filled': 0,
            'total_value_placed': 0,
            'total_value_filled': 0,
            'start_time': time.time(),
            'failed_slices': set(),
            'status': 'active',
            'market': order_input['product_id'],
            'side': order_input['side'],
            'total_fees': 0,
            'maker_orders': 0,
            'taker_orders': 0,
            'slice_statuses': [],
            'price_skips': 0,
            'balance_skips': 0,
            'other_failures': 0
        }

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
                        self.twap_orders[twap_id]['balance_skips'] += 1
                        continue

                # Get current prices with detailed logging
                current_prices = self.get_current_prices(order_input["product_id"])
                if not current_prices:
                    logging.error(f"Failed to get current prices for slice {i+1}/{num_slices}")
                    print(f"Failed to get current prices for slice {i+1}/{num_slices}")
                    slice_info['status'] = 'price_fetch_failed'
                    self.twap_orders[twap_id]['other_failures'] += 1
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
                    execution_price = order_input["limit_price"]
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
                logging.info(f"User limit price: ${order_input['limit_price']:.2f}")
                
                slice_info['execution_price'] = execution_price
                slice_info['market_prices'] = current_prices

                # Price favorability check
                if order_input["side"] == "BUY":
                    price_favorable = execution_price <= order_input["limit_price"]
                    comparison = "above" if not price_favorable else "below or at"
                else:  # SELL
                    price_favorable = execution_price >= order_input["limit_price"]
                    comparison = "below" if not price_favorable else "above or at"

                if not price_favorable:
                    msg = f"Skipping slice {i+1}/{num_slices}: Price ${execution_price:.2f} is {comparison} limit ${order_input['limit_price']:.2f}"
                    logging.warning(msg)
                    print(msg)
                    slice_info['status'] = 'price_unfavorable'
                    self.twap_orders[twap_id]['price_skips'] += 1
                    continue

                # Place the slice
                try:
                    order_response = self.place_limit_order_with_retry(
                        product_id=order_input["product_id"],
                        side=order_input["side"],
                        base_size=str(slice_size),
                        limit_price=str(execution_price),
                        client_order_id=f"twap-{twap_id}-{i}-{int(time.time())}"
                    )

                    slice_info['order_response'] = order_response
                    
                    if order_response:
                        order_id = order_response['order_id'] if 'order_id' in order_response else \
                                 order_response['success_response']['order_id']
                        
                        self.twap_orders[twap_id]['orders'].append(order_id)
                        self.twap_orders[twap_id]['total_placed'] += slice_size
                        self.twap_orders[twap_id]['total_value_placed'] += (slice_size * execution_price)
                        self.order_to_twap_map[order_id] = twap_id

                        slice_info['status'] = 'placed'
                        slice_info['order_id'] = order_id
                        
                        logging.info(f"TWAP slice {i+1}/{num_slices} placed successfully:")
                        logging.info(f"Order ID: {order_id}")
                        logging.info(f"Size: {slice_size} {base_currency}")
                        logging.info(f"Price: ${execution_price:.2f} {quote_currency}")
                        print(f"TWAP slice {i+1}/{num_slices} placed. Order ID: {order_id}")
                    else:
                        error_msg = f"Failed to place TWAP slice {i+1}/{num_slices}"
                        if isinstance(order_response, dict) and 'error_response' in order_response:
                            error_msg += f": {order_response['error_response']}"
                        logging.error(error_msg)
                        print(error_msg)
                        slice_info['status'] = 'placement_failed'
                        self.twap_orders[twap_id]['other_failures'] += 1

                except Exception as e:
                    error_msg = f"Error placing TWAP slice {i+1}/{num_slices}: {str(e)}"
                    logging.error(error_msg)
                    print(error_msg)
                    slice_info['status'] = 'error'
                    slice_info['error'] = str(e)
                    self.twap_orders[twap_id]['other_failures'] += 1

                slice_info['end_time'] = time.time()
                slice_info['duration'] = slice_info['end_time'] - slice_info['start_time']
                self.twap_orders[twap_id]['slice_statuses'].append(slice_info)
                
                self.display_twap_progress(twap_id, i+1, num_slices)

        except Exception as e:
            logging.error(f"Error during TWAP execution: {str(e)}")
            print(f"Error during TWAP execution: {str(e)}")

        finally:
            end_time = time.time()
            execution_time = end_time - self.twap_orders[twap_id]['start_time']
            
            logging.info("\nTWAP Execution Summary:")
            logging.info(f"Total execution time: {execution_time:.2f} seconds")
            logging.info(f"Price-based skips: {self.twap_orders[twap_id]['price_skips']}")
            logging.info(f"Balance-based skips: {self.twap_orders[twap_id]['balance_skips']}")
            logging.info(f"Other failures: {self.twap_orders[twap_id]['other_failures']}")
            
            self.twap_orders[twap_id]['status'] = 'completed'
            self.display_twap_summary(twap_id)
            
            logging.info("=" * 50)
            logging.info("TWAP ORDER COMPLETED")
            logging.info("=" * 50)
            
        return twap_id

    def check_twap_order_fills(self, twap_id):
        """Check fills for a specific TWAP order more efficiently."""
        if twap_id not in self.twap_orders:
            print(f"TWAP order {twap_id} not found.")
            return

        twap_info = self.twap_orders[twap_id]
        logging.info(f"Checking fills for TWAP order {twap_id} with {len(twap_info['orders'])} orders")
        
        try:
            unique_order_ids = list(set(twap_info['orders']))
            batch_size = 50
            order_batches = [unique_order_ids[i:i + batch_size] for i in range(0, len(unique_order_ids), batch_size)]
            
            total_filled = 0
            total_value_filled = 0
            order_statuses = {}
            
            # Process each batch
            for batch in order_batches:
                logging.info(f"Processing batch of {len(batch)} orders")
                
                # Get fills for this batch
                try:
                    fills_response = self.client.get_fills(order_ids=batch)
                    if 'fills' in fills_response:
                        fills = fills_response['fills']  # Direct dictionary access
                        for fill in fills:
                            filled_size = float(fill['size'])
                            filled_price = float(fill['price'])
                            total_filled += filled_size
                            total_value_filled += filled_price * filled_size
                            
                            if fill.get('liquidity_indicator') == 'M':
                                twap_info['maker_orders'] += 1
                            else:
                                twap_info['taker_orders'] += 1
                                
                            fees = float(fill['fee']) if 'fee' in fill else 0
                            twap_info['total_fees'] += fees
                except Exception as e:
                    logging.error(f"Error getting fills for batch: {str(e)}")
                
                # Get order statuses in batch
                try:
                    orders_response = self.client.list_orders(order_ids=batch)
                    if 'orders' in orders_response:
                        orders = orders_response['orders']  # Direct dictionary access
                        for order in orders:
                            status = {
                                'status': order['status'],
                                'filled_size': float(order['filled_size']) if 'filled_size' in order else 0,
                                'price': float(order['average_filled_price']) if 'average_filled_price' in order else 0
                            }
                            order_statuses[order['order_id']] = status
                except Exception as e:
                    logging.error(f"Error getting order statuses for batch: {str(e)}")

            # Update TWAP info
            twap_info['total_filled'] = total_filled
            twap_info['total_value_filled'] = total_value_filled

            # Display order data
            order_data = []
            for order_id in unique_order_ids:
                status = order_statuses.get(order_id, {})
                order_status = status.get('status', 'UNKNOWN')
                filled_size = status.get('filled_size', 0)
                filled_value = filled_size * status.get('price', 0)
                
                order_data.append([
                    order_id[:8] + "...",
                    f"{filled_size:.8f}",
                    f"${filled_value:.2f}",
                    order_status
                ])

            print("\nTWAP Order Details:")
            print(tabulate(order_data, headers=["Order ID", "Filled Size", "USD Value Filled", "Status"], tablefmt="grid"))

            if twap_info['total_value_placed'] > 0:
                fill_percentage = (twap_info['total_value_filled'] / twap_info['total_value_placed']) * 100
                print(f"\nTotal Percentage Value Filled: {fill_percentage:.2f}%")
            
            self.display_twap_summary(twap_id)

        except Exception as e:
            logging.error(f"Error checking TWAP fills: {str(e)}")
            print(f"Error checking TWAP fills: {str(e)}")

    def get_twap_status(self, twap_id):
        """Get current status of a TWAP order."""
        if twap_id not in self.twap_orders:
            return "Not Found"
            
        twap_info = self.twap_orders[twap_id]
        
        try:
            unique_order_ids = list(set(twap_info['orders']))
            batch_size = 50
            order_batches = [unique_order_ids[i:i + batch_size] for i in range(0, len(unique_order_ids), batch_size)]
            
            total_orders = len(unique_order_ids)
            filled_count = 0
            cancelled_count = 0
            
            for batch in order_batches:
                orders_response = self.client.list_orders(order_ids=batch)
                if 'orders' in orders_response:
                    orders = orders_response['orders']  # Direct dictionary access
                    for order in orders:
                        if order['status'] == 'FILLED':
                            filled_count += 1
                        elif order['status'] == 'CANCELLED':
                            cancelled_count += 1
            
            if not total_orders:
                return "Unknown"
                
            if filled_count + cancelled_count == total_orders:
                return "Complete"
            elif filled_count > 0:
                return "Partially Filled"
            else:
                return "Active"
                
        except Exception as e:
            logging.error(f"Error getting TWAP status: {str(e)}")
            return "Error"

    def place_adaptive_twap_order(self):
        """Place an Adaptive Time-Weighted Average Price (TWAP) order."""
        if not self.client:
            logging.warning("Attempt to place Adaptive TWAP order without login")
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        duration = int(input("Enter Adaptive TWAP duration in minutes: "))
        num_slices = int(input("Enter number of slices for Adaptive TWAP: "))

        slice_size = order_input["base_size"] / num_slices
        slice_interval = duration * 60 / num_slices

        logging.info(f"Starting Adaptive TWAP order: {order_input['product_id']}, {order_input['side']}, "
                     f"Total Size: {order_input['base_size']}, Slices: {num_slices}, Duration: {duration} minutes")

        print(f"\nAdaptive TWAP Order Details:")
        print(f"Duration: {duration} minutes")
        print(f"Number of Slices: {num_slices}")
        print(f"Initial Size per Slice: {slice_size}")
        print(f"Interval between Slices: {slice_interval} seconds")

        confirm = input("\nDo you want to execute this Adaptive TWAP order? (yes/no): ").lower()
        if confirm != 'yes':
            logging.info("Adaptive TWAP order cancelled by user")
            print("Adaptive TWAP order cancelled.")
            return

        executed_quantity = 0
        start_time = time.time()

        for i in range(num_slices):
            try:
                product_info = self.client.get_product(order_input["product_id"])
                current_price = float(product_info['price'])  # Direct dictionary access
                
                # Adjust slice size based on price difference
                price_difference = abs(current_price - order_input["limit_price"]) / order_input["limit_price"]
                adjusted_slice_size = slice_size * (1 + price_difference)
                
                if (order_input["side"] == 'BUY' and current_price < order_input["limit_price"]) or \
                   (order_input["side"] == 'SELL' and current_price > order_input["limit_price"]):
                    adjusted_slice_size *= 1.2  # Increase size if price is favorable
                
                adjusted_slice_size = min(adjusted_slice_size, order_input["base_size"] - executed_quantity)
                
                order_response = self.client.market_order(
                    client_order_id=f"adaptive-twap-{int(time.time())}-{i}",
                    product_id=order_input["product_id"],
                    side=order_input["side"],
                    base_size=str(adjusted_slice_size)
                )
                
                # Check for successful order placement
                if 'success_response' in order_response or 'order_id' in order_response:
                    logging.info(f"Adaptive TWAP slice {i+1}/{num_slices} executed. "
                               f"Size: {adjusted_slice_size}, Price: {current_price}")
                    print(f"Adaptive TWAP slice {i+1}/{num_slices} executed. "
                          f"Size: {adjusted_slice_size}, Price: {current_price}")
                    executed_quantity += adjusted_slice_size
                else:
                    logging.error(f"Failed to place Adaptive TWAP slice {i+1}. Response: {order_response}")
                    print(f"Failed to place Adaptive TWAP slice {i+1}")

            except Exception as e:
                logging.error(f"Error executing Adaptive TWAP slice {i+1}: {str(e)}")
                print(f"Error executing Adaptive TWAP slice {i+1}: {str(e)}")

            if i < num_slices - 1:
                sleep_time = max(CONFIG['twap_slice_delay'], 
                               slice_interval - ((time.time() - start_time) % slice_interval))
                logging.info(f"Waiting {sleep_time:.2f} seconds before next slice...")
                print(f"Waiting {sleep_time:.2f} seconds before next slice...")
                time.sleep(sleep_time)

        logging.info(f"Adaptive TWAP order execution completed. Total executed: {executed_quantity}")
        print(f"Adaptive TWAP order execution completed. Total executed: {executed_quantity}")

    def run(self):
        """Main execution loop for the trading terminal."""
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
                self.place_limit_order()
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