import logging
from keys import Keys
from coinbase.rest import RESTClient
import time
import random
from threading import Lock
from threading import Thread
from queue import Queue
from tabulate import tabulate
from datetime import datetime, timedelta, timezone
from functools import wraps

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configurable parameters
CONFIG = {
    'retries': 3,
    'backoff_in_seconds': 1,
    'rate_limit_requests': 25,
    'rate_limit_burst': 50,
    'twap_slice_delay': 2,  # Delay between TWAP slices in seconds
}

def retry_with_backoff(retries=CONFIG['retries'], backoff_in_seconds=CONFIG['backoff_in_seconds']):
    """
    Decorator for retrying a function with exponential backoff.
    """
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        raise
                    sleep = (backoff_in_seconds * 2 ** x + random.uniform(0, 1))
                    logging.warning(f"Retrying {func.__name__} in {sleep:.2f} seconds due to {str(e)}")
                    time.sleep(sleep)
                    x += 1
        return wrapped
    return wrapper

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
    def __init__(self):
        self.client = None
        self.rate_limiter = RateLimiter(CONFIG['rate_limit_requests'], CONFIG['rate_limit_burst'])

    # Authentication methods
    def login(self):
        """
        Authenticate user and initialize the RESTClient.
        """
        logging.info("Initiating login process")
        print("Welcome to the Coinbase Trading Terminal!")
        api_key = Keys.api_key
        api_secret = Keys.api_secret

        try:
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            self.rate_limited_get_accounts()
            logging.info("Login successful")
            print("Login successful!")
        except Exception as e:
            logging.error(f"Login failed: {str(e)}")
            print(f"Login failed: {str(e)}")
            self.client = None

    # API interaction methods
    @retry_with_backoff()
    def rate_limited_get_accounts(self, **kwargs):
        """
        Get accounts with rate limiting.
        """
        self.rate_limiter.wait()
        return self.client.get_accounts(**kwargs)

    @retry_with_backoff()
    def get_product(self, product_id):
        """
        Get product information.
        """
        return self.client.get_product(product_id)

    @retry_with_backoff()
    def get_product_book(self, product_id, limit):
        """
        Get product order book.
        """
        return self.client.get_product_book(product_id, limit=limit)

    @retry_with_backoff()
    def limit_order_gtc(self, **kwargs):
        """
        Place a limit order with Good Till Cancelled time in force.
        """
        return self.client.limit_order_gtc(**kwargs)

    @retry_with_backoff()
    def market_order(self, **kwargs):
        """
        Place a market order.
        """
        return self.client.market_order(**kwargs)

    @retry_with_backoff()
    def cancel_orders(self, order_ids):
        """
        Cancel specified orders.
        """
        return self.client.cancel_orders(order_ids)

    # Helper methods
    def get_current_prices(self, product_id: str):
        """
        Get current bid, ask, and mid prices for a product.
        """
        try:
            product_book = self.get_product_book(product_id, limit=1)
            if 'pricebook' in product_book:
                pricebook = product_book['pricebook']
                if 'bids' in pricebook and 'asks' in pricebook and pricebook['bids'] and pricebook['asks']:
                    bid = float(pricebook['bids'][0]['price'])
                    ask = float(pricebook['asks'][0]['price'])
                    mid = (bid + ask) / 2
                    return {'bid': bid, 'mid': mid, 'ask': ask}
                else:
                    logging.warning(f"Incomplete order book data for {product_id}. Current data: {pricebook}")
            else:
                logging.warning(f"Unexpected response format for {product_id}. Response: {product_book}")
            return None
        except Exception as e:
            logging.error(f"Error fetching current prices for {product_id}: {str(e)}")
            return None

    def get_top_markets(self):
        """
        Get top 10 markets by 24h USD volume.
        """
        try:
            products = self.client.get_products()
            
            def get_usd_volume(product):
                try:
                    volume = float(product.get('volume_24h', '0'))
                    price = float(product.get('price', '0'))
                    return volume * price
                except ValueError:
                    return 0

            top_products = sorted(products['products'], key=get_usd_volume, reverse=True)[:10]
            return [(product['product_id'], get_usd_volume(product)) for product in top_products]
        except Exception as e:
            logging.error(f"Error fetching top markets: {str(e)}")
            return []

    def get_active_orders(self):
        """
        Get list of active orders.
        """
        try:
            all_orders = self.client.list_orders()
            active_orders = [order for order in all_orders.get('orders', []) 
                             if order['status'] in ['OPEN', 'PENDING']]
            return active_orders
        except Exception as e:
            logging.error(f"Error fetching orders: {str(e)}")
            return []

    # User interaction methods
    def get_order_input(self):
        """
        Get order input from user.
        """
        top_markets = self.get_top_markets()
        if not top_markets:
            logging.warning("Unable to fetch top markets")
            print("Unable to fetch top markets. Please try again later.")
            return None

        print("\nTop 10 Markets by 24h USD Volume:")
        for i, (market, volume) in enumerate(top_markets, 1):
            print(f"{i}. {market} (USD Volume: ${volume:,.2f})")
        print("11. Enter a different market")

        while True:
            market_choice = input("Enter the number of the market you want to trade (1-11): ")
            try:
                choice = int(market_choice)
                if 1 <= choice <= 10:
                    product_id = top_markets[choice-1][0]
                    break
                elif choice == 11:
                    product_id = input("Enter the market symbol (e.g., BTC-USD): ").upper()
                    break
                else:
                    print("Invalid selection. Please choose a number between 1 and 11.")
            except ValueError:
                print("Please enter a valid number.")

        while True:
            side = input("Buy or Sell? ").upper()
            if side in ['BUY', 'SELL']:
                break
            print("Please enter either 'Buy' or 'Sell'.")

        while True:
            try:
                base_size = float(input("Enter the quantity: "))
                break
            except ValueError:
                print("Please enter a valid number for the quantity.")

        while True:
            try:
                limit_price = float(input("Enter the limit price: "))
                break
            except ValueError:
                print("Please enter a valid number for the limit price.")

        usd_value = base_size * limit_price

        print("\nOrder Summary:")
        print(f"Market: {product_id}")
        print(f"Side: {side}")
        print(f"Quantity: {base_size}")
        print(f"Limit Price: ${limit_price:,.2f}")
        print(f"Total USD Value: ${usd_value:,.2f}")

        confirm = input("\nDo you want to place this order? (yes/no): ").lower()
        if confirm != 'yes':
            logging.info("Order cancelled by user")
            print("Order cancelled.")
            return None

        return {
            "product_id": product_id,
            "side": side,
            "base_size": base_size,
            "limit_price": limit_price,
            "usd_value": usd_value
        }

    # Order placement methods
    def place_limit_order(self):
        """
        Place a limit order.
        """
        if not self.client:
            logging.warning("Attempt to place order without login")
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        try:
            order_response = self.limit_order_gtc(
                client_order_id=f"limit-order-{int(time.time())}",
                product_id=order_input["product_id"],
                side=order_input["side"],
                base_size=str(order_input["base_size"]),
                limit_price=str(order_input["limit_price"])
            )

            self.handle_order_response(order_response, order_input["usd_value"])

        except Exception as e:
            self.handle_order_error(str(e))



    def place_twap_order(self):
        """
        Place a Time-Weighted Average Price (TWAP) order with periodic checks for unfilled orders.
        """
        if not self.client:
            logging.warning("Attempt to place TWAP order without login")
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        duration = int(input("Enter TWAP duration in minutes: "))
        num_slices = int(input("Enter number of slices for TWAP: "))

        print("\nSelect price type for order placement:")
        print("1. Original limit price")
        print("2. Current market bid")
        print("3. Current market mid")
        print("4. Current market ask")
        price_type = input("Enter your choice (1-4): ")

        slice_size = order_input["base_size"] / num_slices
        slice_interval = duration * 60 / num_slices

        logging.info(f"Starting TWAP order: {order_input['product_id']}, {order_input['side']}, "
                     f"Total Size: {order_input['base_size']}, Slices: {num_slices}, Duration: {duration} minutes")

        print(f"\nTWAP Order Details:")
        print(f"Market: {order_input['product_id']}")
        print(f"Side: {order_input['side']}")
        print(f"Total Quantity: {order_input['base_size']}")
        print(f"Original Limit Price: ${order_input['limit_price']:,.2f}")
        print(f"Total USD Value (at limit price): ${order_input['usd_value']:,.2f}")
        print(f"Duration: {duration} minutes")
        print(f"Number of Slices: {num_slices}")
        print(f"Size per Slice: {slice_size}")
        print(f"Interval between Slices: {slice_interval:.2f} seconds")
        print(f"Price Type: {'Original Limit' if price_type == '1' else 'Market Bid' if price_type == '2' else 'Market Mid' if price_type == '3' else 'Market Ask'}")

        confirm = input("\nDo you want to execute this TWAP order? (yes/no): ").lower()
        if confirm != 'yes':
            logging.info("TWAP order cancelled by user")
            print("TWAP order cancelled.")
            return

        # Initialize order tracking
        orders = Queue()
        total_executed = 0
        total_value_executed = 0
        orders_placed = 0
        orders_filled = 0

        # Start the order checking thread
        checker_thread = Thread(target=self.order_status_checker, args=(orders,))
        checker_thread.start()

        try:
            for i in range(num_slices):
                current_prices = self.get_current_prices(order_input["product_id"])
                if not current_prices:
                    logging.warning(f"Skipping TWAP slice {i+1} due to error in fetching current prices.")
                    print(f"Skipping slice {i+1} due to error in fetching current prices.")
                    continue

                if price_type == '1':
                    execution_price = order_input["limit_price"]
                elif price_type == '2':
                    execution_price = current_prices['bid']
                elif price_type == '3':
                    execution_price = current_prices['mid']
                else:
                    execution_price = current_prices['ask']

                # Check if the execution price is favorable
                if (order_input["side"] == "BUY" and execution_price <= order_input["limit_price"]) or \
                   (order_input["side"] == "SELL" and execution_price >= order_input["limit_price"]):
                    order_response = self.limit_order_gtc(
                        client_order_id=f"twap-order-{int(time.time())}-{i}",
                        product_id=order_input["product_id"],
                        side=order_input["side"],
                        base_size=str(slice_size),
                        limit_price=str(execution_price)
                    )
                    orders_placed += 1
                    if 'order_id' in order_response:
                        logging.info(f"TWAP slice {i+1}/{num_slices} placed. Order ID: {order_response['order_id']}, "
                                     f"Execution Price: ${execution_price:,.2f}")
                        print(f"TWAP slice {i+1}/{num_slices} placed. Order ID: {order_response['order_id']}")
                        print(f"Execution Price: ${execution_price:,.2f}")
                        
                        # Add order to the queue for checking
                        orders.put({
                            'order_id': order_response['order_id'],
                            'size': slice_size,
                            'price': execution_price
                        })
                    else:
                        logging.error(f"Failed to place TWAP slice {i+1}/{num_slices}. "
                                      f"Error: {order_response.get('error_response', 'Unknown error')}")
                        print(f"Failed to place TWAP slice {i+1}/{num_slices}.")
                        if 'error_response' in order_response:
                            print(f"Error details: {order_response['error_response']}")
                else:
                    logging.info(f"Skipping TWAP slice {i+1} due to unfavorable price. "
                                 f"Current: ${execution_price:,.2f}, Limit: ${order_input['limit_price']:,.2f}")
                    print(f"Skipping slice {i+1} as the current price (${execution_price:,.2f}) is not favorable "
                          f"compared to the limit price (${order_input['limit_price']:,.2f}).")

                # Update and display progress
                total_executed, total_value_executed, orders_filled = self.update_order_stats(orders)
                self.display_twap_progress(i+1, num_slices, orders_placed, orders_filled, total_executed, total_value_executed)

                if i < num_slices - 1:
                    sleep_time = max(CONFIG['twap_slice_delay'], slice_interval)
                    logging.info(f"Waiting {sleep_time:.2f} seconds before next slice...")
                    print(f"Waiting {sleep_time:.2f} seconds before next slice...")
                    time.sleep(sleep_time)

        except Exception as e:
            logging.error(f"Error during TWAP execution: {str(e)}")
            print(f"Error during TWAP execution: {str(e)}")

        finally:
            # Signal the checker thread to stop
            orders.put(None)
            checker_thread.join()

            # Final update and display of stats
            total_executed, total_value_executed, orders_filled = self.update_order_stats(orders)
            self.display_twap_summary(orders_placed, orders_filled, total_executed, total_value_executed)

    def order_status_checker(self, orders):
        """
        Continuously check the status of unfilled orders.
        """
        while True:
            order = orders.get()
            if order is None:
                break

            filled_info = self.check_order_filled(order['order_id'])
            if filled_info['filled']:
                order['filled'] = True
                order['filled_size'] = filled_info['filled_size']
                order['filled_price'] = filled_info['filled_price']
            else:
                orders.put(order)  # Put the unfilled order back in the queue

            time.sleep(1)  # Avoid hitting rate limits

    def update_order_stats(self, orders):
        """
        Update order statistics based on the current state of orders.
        """
        total_executed = 0
        total_value_executed = 0
        orders_filled = 0

        # Create a copy of the queue to iterate over
        temp_queue = Queue()
        while not orders.empty():
            order = orders.get()
            if order.get('filled', False):
                total_executed += order['filled_size']
                total_value_executed += order['filled_size'] * order['filled_price']
                orders_filled += 1
            else:
                temp_queue.put(order)

        # Restore the original queue
        while not temp_queue.empty():
            orders.put(temp_queue.get())

        return total_executed, total_value_executed, orders_filled

    def check_order_filled(self, order_id):
        """
        Check if an order has been filled.
        """
        try:
            order = self.client.get_order(order_id)
            filled = order['status'] == 'FILLED'
            filled_size = float(order['filled_size']) if filled else 0
            filled_price = float(order['average_filled_price']) if filled else 0
            return {'filled': filled, 'filled_size': filled_size, 'filled_price': filled_price}
        except Exception as e:
            logging.error(f"Error checking order status: {str(e)}")
            return {'filled': False, 'filled_size': 0, 'filled_price': 0}

    def display_twap_progress(self, current_slice, total_slices, orders_placed, orders_filled, total_executed, total_value_executed):
        """
        Display the progress of the TWAP order execution.
        """
        print("\n" + "=" * 50)
        print(f"TWAP Progress: Slice {current_slice}/{total_slices}")
        print(f"Orders Placed: {orders_placed}")
        print(f"Orders Filled: {orders_filled}")
        print(f"Total Executed: {total_executed:.8f}")
        print(f"Total Value Executed: ${total_value_executed:.2f}")
        if total_executed > 0:
            avg_fill_price = total_value_executed / total_executed
            print(f"Average Fill Price: ${avg_fill_price:.2f}")
        print("=" * 50)

    def display_twap_summary(self, orders_placed, orders_filled, total_executed, total_value_executed):
        """
        Display the summary of the TWAP order execution.
        """
        print("\n" + "=" * 50)
        print("TWAP Order Execution Summary")
        print(f"Total Orders Placed: {orders_placed}")
        print(f"Total Orders Filled: {orders_filled}")
        print(f"Total Quantity Executed: {total_executed:.8f}")
        print(f"Total USD Value Executed: ${total_value_executed:.2f}")
        if total_executed > 0:
            avg_fill_price = total_value_executed / total_executed
            print(f"Average Fill Price: ${avg_fill_price:.2f}")
        print("=" * 50)

        logging.info(f"TWAP order execution completed. Orders Placed: {orders_placed}, "
                     f"Orders Filled: {orders_filled}, Total Executed: {total_executed:.8f}, "
                     f"Total USD Value: ${total_value_executed:.2f}")

    def place_adaptive_twap_order(self):
        """
        Place an Adaptive Time-Weighted Average Price (TWAP) order.
        """
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
                current_price = float(self.get_product(order_input["product_id"])['price'])
                
                # Adjust slice size based on price difference
                price_difference = abs(current_price - order_input["limit_price"]) / order_input["limit_price"]
                adjusted_slice_size = slice_size * (1 + price_difference)
                
                if (order_input["side"] == 'BUY' and current_price < order_input["limit_price"]) or \
                   (order_input["side"] == 'SELL' and current_price > order_input["limit_price"]):
                    adjusted_slice_size *= 1.2  # Increase size if price is favorable
                
                adjusted_slice_size = min(adjusted_slice_size, order_input["base_size"] - executed_quantity)
                
                order_response = self.market_order(
                    client_order_id=f"adaptive-twap-{int(time.time())}-{i}",
                    product_id=order_input["product_id"],
                    side=order_input["side"],
                    base_size=str(adjusted_slice_size)
                )
                logging.info(f"Adaptive TWAP slice {i+1}/{num_slices} executed. "
                             f"Size: {adjusted_slice_size}, Price: {current_price}")
                print(f"Adaptive TWAP slice {i+1}/{num_slices} executed. Size: {adjusted_slice_size}, Price: {current_price}")
                executed_quantity += adjusted_slice_size
            except Exception as e:
                logging.error(f"Error executing Adaptive TWAP slice {i+1}: {str(e)}")
                print(f"Error executing Adaptive TWAP slice {i+1}: {str(e)}")

            if i < num_slices - 1:
                sleep_time = max(CONFIG['twap_slice_delay'], slice_interval - ((time.time() - start_time) % slice_interval))
                logging.info(f"Waiting {sleep_time:.2f} seconds before next slice...")
                print(f"Waiting {sleep_time:.2f} seconds before next slice...")
                time.sleep(sleep_time)

        logging.info(f"Adaptive TWAP order execution completed. Total executed: {executed_quantity}")
        print(f"Adaptive TWAP order execution completed. Total executed: {executed_quantity}")

    def handle_order_response(self, order_response, usd_value):
        """
        Handle the response from an order placement.
        """
        if 'order_id' in order_response:
            logging.info(f"Order placed successfully. Order ID: {order_response['order_id']}, "
                         f"USD Value: ${usd_value:,.2f}")
            print(f"Order placed successfully. Order ID: {order_response['order_id']}")
            print(f"Order USD Value: ${usd_value:,.2f}")
        else:
            logging.error(f"Order placement failed. Response: {order_response}")
            print("Order placement failed. No order ID received.")
            if 'error_response' in order_response:
                error_details = order_response['error_response']
                logging.error(f"Error details: {error_details}")
                print(f"Error details: {error_details}")
            else:
                print("No specific error details available.")

        # Verify order placement
        time.sleep(2)  # Wait a bit for the order to be processed
        active_orders = self.get_active_orders()
        if any(order['order_id'] == order_response.get('order_id') for order in active_orders):
            logging.info("Order verified in active orders list.")
            print("Order verified in active orders list.")
        else:
            logging.warning("Order not found in active orders list. It may have failed or been immediately filled.")
            print("Warning: Order not found in active orders list. It may have failed or been immediately filled.")

    def handle_order_error(self, error_message):
        """
        Handle errors that occur during order placement.
        """
        logging.error(f"Error occurred while placing the order: {error_message}")
        print(f"Error occurred while placing the order: {error_message}")
        if "INSUFFICIENT_FUND" in error_message:
            print("This may be due to insufficient funds.")
        elif "INVALID_SIZE" in error_message:
            print("This may be due to an invalid order size. The size might be too small or exceed your available balance.")
        elif "INVALID_PRICE" in error_message:
            print("This may be due to an invalid price. The price might be outside the allowed range for this product.")

    def view_portfolio(self):
        """
        View and display the user's portfolio.
        """
        if not self.client:
            logging.warning("Attempt to view portfolio without login")
            print("Please login first.")
            return

        try:
            logging.info("Fetching accounts for portfolio view")
            print("\nFetching accounts (this may take a moment due to rate limiting):")
            accounts = self.rate_limited_get_accounts(limit=100)
            self.display_portfolio(accounts)
        except Exception as e:
            logging.error(f"Error fetching portfolio: {str(e)}")
            print(f"Error fetching portfolio: {str(e)}")

    def display_portfolio(self, accounts_data):
        """
        Display the portfolio data.
        """
        portfolio_data = []
        total_usd_value = 0

        for account in accounts_data.get('accounts', []):
            balance = float(account['available_balance']['value'])
            currency = account['currency']
            
            if balance > 0:
                if currency in ['USD', 'USDC', 'USDT', 'DAI']:
                    usd_value = balance
                else:
                    try:
                        product_id = f"{currency}-USD"
                        ticker = self.get_product(product_id)
                        usd_price = float(ticker['price'])
                        usd_value = balance * usd_price
                    except Exception as e:
                        logging.warning(f"Couldn't get USD value for {currency}. Error: {str(e)}")
                        print(f"Warning: Couldn't get USD value for {currency}. Error: {str(e)}")
                        continue

                if usd_value >= 1:  # Only include assets worth $1 or more
                    portfolio_data.append([currency, balance, usd_value])
                    total_usd_value += usd_value

        # Sort portfolio data by USD value in descending order
        portfolio_data.sort(key=lambda x: x[2], reverse=True)

        # Prepare data for tabulate
        table_data = [[f"{row[0]} ({row[1]:.8f})", f"${row[2]:.2f}"] for row in portfolio_data]

        logging.info(f"Portfolio summary generated. Total value: ${total_usd_value:.2f} USD")
        print("\nPortfolio Summary:")
        print(f"Total Portfolio Value: ${total_usd_value:.2f} USD")
        print("\nAsset Balances:")
        print(tabulate(table_data, headers=["Asset (Amount)", "USD Value"], tablefmt="grid"))

    def show_and_cancel_orders(self):
        """
        Display active orders and allow cancellation.
        """
        if not self.client:
            logging.warning("Attempt to show/cancel orders without login")
            print("Please login first.")
            return

        def get_active_orders():
            try:
                all_orders = self.client.list_orders()
                active_orders = [order for order in all_orders.get('orders', []) 
                                 if order['status'] in ['OPEN', 'PENDING']]
                return active_orders
            except Exception as e:
                logging.error(f"Error fetching orders: {str(e)}")
                print(f"Error fetching orders: {str(e)}")
                return []

        def display_orders(orders):
            if not orders:
                logging.info("No active orders found")
                print("No active orders found.")
                return False

            logging.info(f"Displaying {len(orders)} active orders")
            print("\nActive Orders:")
            table_data = []
            for i, order in enumerate(orders, 1):
                order_config = order['order_configuration']
                order_type = list(order_config.keys())[0]  # Get the type of order
                size = order_config[order_type].get('base_size', 'N/A')
                price = order_config[order_type].get('limit_price', 'N/A')
                
                table_data.append([
                    i,
                    order['order_id'],
                    order['product_id'],
                    order['side'],
                    size,
                    price,
                    order['status']
                ])

            print(tabulate(table_data, headers=["Number", "Order ID", "Product", "Side", "Size", "Price", "Status"], tablefmt="grid"))
            return True

        try:
            active_orders = get_active_orders()
            if not display_orders(active_orders):
                return  # Exit the function if there are no active orders

            while True:
                action = input("\nWould you like to cancel any orders? (yes/no/all): ").lower()
                if action == 'no':
                    break
                elif action == 'all':
                    order_ids = [order['order_id'] for order in active_orders]
                    result = self.cancel_orders(order_ids)
                    logging.info(f"Cancelled {len(result['results'])} orders")
                    print(f"Cancelled {len(result['results'])} orders.")
                    break  # Exit after cancelling all orders
                elif action == 'yes':
                    order_number = input("Enter the Number of the order to cancel: ")
                    try:
                        order_index = int(order_number) - 1
                        if 0 <= order_index < len(active_orders):
                            order_id = active_orders[order_index]['order_id']
                            result = self.cancel_orders([order_id])
                            if result['results']:
                                logging.info(f"Order {order_id} cancelled successfully")
                                print(f"Order {order_id} cancelled successfully.")
                                active_orders = get_active_orders()  # Refresh the list of active orders
                                if not display_orders(active_orders):
                                    break  # Exit if there are no more active orders
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

    def run(self):
        """
        Run the main loop of the trading terminal.
        """
        self.login()
        while True:
            print("\nWhat would you like to do?")
            print("1. View portfolio balances")
            print("2. Place a limit order")
            print("3. Place a TWAP order")
            print("4. Place an Adaptive TWAP order")
            print("5. Show and cancel active orders")
            print("6. Exit")
            
            choice = input("Enter your choice (1-6): ")
            
            if choice == '1':
                self.view_portfolio()
            elif choice == '2':
                self.place_limit_order()
            elif choice == '3':
                self.place_twap_order()
            elif choice == '4':
                self.place_adaptive_twap_order()
            elif choice == '5':
                self.show_and_cancel_orders()
            elif choice == '6':
                logging.info("User exited the trading terminal")
                print("Thank you for using the Coinbase Trading Terminal. Goodbye!")
                break
            else:
                print("Invalid choice. Please try again.")

def main():
    terminal = TradingTerminal()
    terminal.run()

if __name__ == "__main__":
    main()