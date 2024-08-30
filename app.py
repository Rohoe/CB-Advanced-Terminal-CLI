from keys import Keys
from coinbase.rest import RESTClient
from getpass import getpass
import time
import json
from threading import Lock
from tabulate import tabulate
from datetime import datetime, timedelta, timezone

class RateLimiter:
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
        self.rate_limiter = RateLimiter(25, 50)  # 25 requests/sec, burst of 50

    def login(self):
        print("Welcome to the Coinbase Trading Terminal!")
        api_key = Keys.api_key
        api_secret = Keys.api_secret

        try:
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            # Test authentication by getting accounts
            self.rate_limited_get_accounts()
            print("Login successful!")
        except Exception as e:
            print(f"Login failed: {str(e)}")
            self.client = None

    def rate_limited_get_accounts(self, **kwargs):
        self.rate_limiter.wait()
        return self.client.get_accounts(**kwargs)

    def view_portfolio(self):
        if not self.client:
            print("Please login first.")
            return

        try:
            print("\nFetching accounts (this may take a moment due to rate limiting):")
            accounts = self.rate_limited_get_accounts(limit=100)
            self.display_portfolio(accounts)
        except Exception as e:
            print(f"Error fetching portfolio: {str(e)}")

    def display_portfolio(self, accounts_data):
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
                        ticker = self.client.get_product(product_id)
                        usd_price = float(ticker['price'])
                        usd_value = balance * usd_price
                    except Exception as e:
                        print(f"Warning: Couldn't get USD value for {currency}. Error: {str(e)}")
                        continue

                if usd_value >= 1:  # Only include assets worth $1 or more
                    portfolio_data.append([currency, balance, usd_value])
                    total_usd_value += usd_value

        # Sort portfolio data by USD value in descending order
        portfolio_data.sort(key=lambda x: x[2], reverse=True)

        # Prepare data for tabulate
        table_data = [[f"{row[0]} ({row[1]:.8f})", f"${row[2]:.2f}"] for row in portfolio_data]

        print("\nPortfolio Summary:")
        print(f"Total Portfolio Value: ${total_usd_value:.2f} USD")
        print("\nAsset Balances:")
        print(tabulate(table_data, headers=["Asset (Amount)", "USD Value"], tablefmt="grid"))

    def show_and_cancel_orders(self):
        if not self.client:
            print("Please login first.")
            return

        def get_active_orders():
            try:
                # Fetch orders without any filtering
                all_orders = self.client.list_orders()
                
                # Filter for active orders
                active_orders = [order for order in all_orders.get('orders', []) 
                                 if order['status'] in ['OPEN', 'PENDING']]
                return active_orders
            except Exception as e:
                print(f"Error fetching orders: {str(e)}")
                return []

        def display_orders(orders):
            if not orders:
                print("No active orders found.")
                return False

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
                    result = self.client.cancel_orders(order_ids)
                    print(f"Cancelled {len(result['results'])} orders.")
                    break  # Exit after cancelling all orders
                elif action == 'yes':
                    order_number = input("Enter the Number of the order to cancel: ")
                    try:
                        order_index = int(order_number) - 1
                        if 0 <= order_index < len(active_orders):
                            order_id = active_orders[order_index]['order_id']
                            result = self.client.cancel_orders([order_id])
                            if result['results']:
                                print(f"Order {order_id} cancelled successfully.")
                                active_orders = get_active_orders()  # Refresh the list of active orders
                                if not display_orders(active_orders):
                                    break  # Exit if there are no more active orders
                            else:
                                print(f"Failed to cancel order {order_id}.")
                        else:
                            print("Invalid order number.")
                    except ValueError:
                        print("Please enter a valid order number.")
                else:
                    print("Invalid input. Please enter 'yes', 'no', or 'all'.")

        except Exception as e:
            print(f"Error managing orders: {str(e)}")


    def get_top_markets(self):
        try:
            products = self.client.get_products()
            
            def get_usd_volume(product):
                try:
                    volume = float(product.get('volume_24h', '0'))
                    price = float(product.get('price', '0'))
                    return volume * price
                except ValueError:
                    return 0

            # Sort products by USD volume and get top 10
            top_products = sorted(products['products'], key=get_usd_volume, reverse=True)[:10]
            return [(product['product_id'], get_usd_volume(product)) for product in top_products]
        except Exception as e:
            print(f"Error fetching top markets: {str(e)}")
            return []

    def get_available_markets(self):
        try:
            products = self.client.get_products()
            return [product['product_id'] for product in products['products'] if product['status'] == 'online']
        except Exception as e:
            print(f"Error fetching available markets: {str(e)}")
            return []

    def get_active_orders(self):
        try:
            # Fetch orders without any filtering
            all_orders = self.client.list_orders()
            
            # Filter for active orders
            active_orders = [order for order in all_orders.get('orders', []) 
                             if order['status'] in ['OPEN', 'PENDING']]
            return active_orders
        except Exception as e:
            print(f"Error fetching orders: {str(e)}")
            return []
        
    
    def get_order_input(self):
        top_markets = self.get_top_markets()
        if not top_markets:
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
            print("Order cancelled.")
            return None

        return {
            "product_id": product_id,
            "side": side,
            "base_size": base_size,
            "limit_price": limit_price,
            "usd_value": usd_value
        }

    def place_limit_order(self):
        if not self.client:
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        try:
            order_response = self.client.limit_order_gtc(
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
        if not self.client:
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        duration = int(input("Enter TWAP duration in minutes: "))
        num_slices = int(input("Enter number of slices for TWAP: "))

        slice_size = order_input["base_size"] / num_slices
        slice_interval = duration * 60 / num_slices

        print(f"\nTWAP Order Details:")
        print(f"Market: {order_input['product_id']}")
        print(f"Side: {order_input['side']}")
        print(f"Total Quantity: {order_input['base_size']}")
        print(f"Limit Price: ${order_input['limit_price']:,.2f}")
        print(f"Total USD Value: ${order_input['usd_value']:,.2f}")
        print(f"Duration: {duration} minutes")
        print(f"Number of Slices: {num_slices}")
        print(f"Size per Slice: {slice_size}")
        print(f"Interval between Slices: {slice_interval:.2f} seconds")

        confirm = input("\nDo you want to execute this TWAP order? (yes/no): ").lower()
        if confirm != 'yes':
            print("TWAP order cancelled.")
            return

        total_executed = 0
        for i in range(num_slices):
            try:
                order_response = self.client.limit_order_gtc(
                    client_order_id=f"twap-order-{int(time.time())}-{i}",
                    product_id=order_input["product_id"],
                    side=order_input["side"],
                    base_size=str(slice_size),
                    limit_price=str(order_input["limit_price"])
                )
                if 'order_id' in order_response:
                    print(f"TWAP slice {i+1}/{num_slices} placed. Order ID: {order_response['order_id']}")
                    total_executed += slice_size
                else:
                    print(f"Failed to place TWAP slice {i+1}/{num_slices}.")
                    if 'error_response' in order_response:
                        print(f"Error details: {order_response['error_response']}")
                
                if i < num_slices - 1:
                    print(f"Waiting {slice_interval:.2f} seconds before next slice...")
                    time.sleep(slice_interval)
            except Exception as e:
                print(f"Error placing TWAP slice {i+1}: {str(e)}")

        print(f"TWAP order execution completed. Total quantity executed: {total_executed}")
        print(f"Total USD Value executed: ${total_executed * order_input['limit_price']:,.2f}")

    def place_adaptive_twap_order(self):
        if not self.client:
            print("Please login first.")
            return

        order_input = self.get_order_input()
        if not order_input:
            return

        duration = int(input("Enter Adaptive TWAP duration in minutes: "))
        num_slices = int(input("Enter number of slices for Adaptive TWAP: "))

        slice_size = order_input["base_size"] / num_slices
        slice_interval = duration * 60 / num_slices

        print(f"\nAdaptive TWAP Order Details:")
        print(f"Duration: {duration} minutes")
        print(f"Number of Slices: {num_slices}")
        print(f"Initial Size per Slice: {slice_size}")
        print(f"Interval between Slices: {slice_interval} seconds")

        confirm = input("\nDo you want to execute this Adaptive TWAP order? (yes/no): ").lower()
        if confirm != 'yes':
            print("Adaptive TWAP order cancelled.")
            return

        executed_quantity = 0
        start_time = time.time()

        for i in range(num_slices):
            current_price = float(self.client.get_product(order_input["product_id"])['price'])
            
            # Adjust slice size based on price difference
            price_difference = abs(current_price - order_input["limit_price"]) / order_input["limit_price"]
            adjusted_slice_size = slice_size * (1 + price_difference)
            
            if (order_input["side"] == 'BUY' and current_price < order_input["limit_price"]) or \
               (order_input["side"] == 'SELL' and current_price > order_input["limit_price"]):
                adjusted_slice_size *= 1.2  # Increase size if price is favorable
            
            adjusted_slice_size = min(adjusted_slice_size, order_input["base_size"] - executed_quantity)
            
            try:
                order_response = self.client.market_order(
                    client_order_id=f"adaptive-twap-{int(time.time())}-{i}",
                    product_id=order_input["product_id"],
                    side=order_input["side"],
                    base_size=str(adjusted_slice_size)
                )
                print(f"Adaptive TWAP slice {i+1}/{num_slices} executed. Size: {adjusted_slice_size}, Price: {current_price}")
                executed_quantity += adjusted_slice_size
            except Exception as e:
                print(f"Error executing Adaptive TWAP slice {i+1}: {str(e)}")

            if i < num_slices - 1:
                time.sleep(slice_interval - ((time.time() - start_time) % slice_interval))

        print(f"Adaptive TWAP order execution completed. Total executed: {executed_quantity}")

    def handle_order_response(self, order_response, usd_value):
        if 'order_id' in order_response:
            print(f"Order placed successfully. Order ID: {order_response['order_id']}")
            print(f"Order USD Value: ${usd_value:,.2f}")
        else:
            print("Order placement failed. No order ID received.")
            if 'error_response' in order_response:
                error_details = order_response['error_response']
                print(f"Error details: {error_details}")
            else:
                print("No specific error details available.")

        # Verify order placement
        time.sleep(2)  # Wait a bit for the order to be processed
        active_orders = self.get_active_orders()
        if any(order['order_id'] == order_response.get('order_id') for order in active_orders):
            print("Order verified in active orders list.")
        else:
            print("Warning: Order not found in active orders list. It may have failed or been immediately filled.")

    def handle_order_error(self, error_message):
        print(f"Error occurred while placing the order: {error_message}")
        if "INSUFFICIENT_FUND" in error_message:
            print("This may be due to insufficient funds.")
        elif "INVALID_SIZE" in error_message:
            print("This may be due to an invalid order size. The size might be too small or exceed your available balance.")
        elif "INVALID_PRICE" in error_message:
            print("This may be due to an invalid price. The price might be outside the allowed range for this product.")
  
    def run(self):
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
                print("Thank you for using the Coinbase Trading Terminal. Goodbye!")
                break
            else:
                print("Invalid choice. Please try again.")

def main():
    terminal = TradingTerminal()
    terminal.run()

if __name__ == "__main__":
    main()