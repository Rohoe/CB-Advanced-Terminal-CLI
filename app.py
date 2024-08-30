from coinbase.rest import RESTClient
from getpass import getpass
import time
import json
from threading import Lock

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
        api_key = "organizations/29e097b9-9d48-4149-96a6-8a5269cda74a/apiKeys/918888b7-118a-4915-b2bc-4342e959eb39"
        api_secret = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIKbAwmX+3Vy6upbfZ4WbcnpA+o5Pq1IEJqPKcrDfz4R6oAoGCCqGSM49\nAwEHoUQDQgAEvS2/e2/Pq/+UfD4Oghax0npFdJEitdYlbvJc/SatMWldLcgmSrQT\n9ddsqmsf+PAIjwj5Wtq2lHFcaJY62E/UIw==\n-----END EC PRIVATE KEY-----\n"
        
        try:
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            # Test authentication by getting accounts
            self.rate_limited_get_accounts()
            print("Login successful!")
            self.check_api_permissions()
        except Exception as e:
            print(f"Login failed: {str(e)}")
            self.client = None

    def rate_limited_get_accounts(self, **kwargs):
        self.rate_limiter.wait()
        return self.client.get_accounts(**kwargs)

    def check_api_permissions(self):
        try:
            permissions = self.client.get_api_key_permissions()
            print("\nAPI Key Permissions:")
            print(json.dumps(permissions, indent=2))
        except Exception as e:
            print(f"Error fetching API key permissions: {str(e)}")

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
        total_usd_value = 0
        non_zero_accounts = []

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

                total_usd_value += usd_value

                non_zero_accounts.append({
                    'currency': currency,
                    'balance': balance,
                    'usd_value': usd_value
                })

        print("\nPortfolio Summary:")
        print(f"Total Portfolio Value: ${total_usd_value:.2f} USD")
        print("\nIndividual Asset Balances:")
        for account in non_zero_accounts:
            print(f"{account['currency']}:")
            print(f"  Balance: {account['balance']} {account['currency']}")
            print(f"  USD Value: ${account['usd_value']:.2f}")
            print()

    def place_limit_order(self):
        if not self.client:
            print("Please login first.")
            return

        product_id = input("Enter the market (e.g., BTC-USD): ")
        side = input("Buy or Sell? ").lower()
        base_size = input("Enter the quantity: ")
        limit_price = input("Enter the limit price: ")

        try:
            order = self.client.limit_order_gtc(
                client_order_id=f"limit-order-{int(time.time())}",
                product_id=product_id,
                side=side,
                base_size=base_size,
                limit_price=limit_price
            )
            print(f"Limit order placed successfully. Order ID: {order['order_id']}")
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    def place_twap_order(self):
        print("TWAP order functionality is not directly supported by the Coinbase Advanced API.")
        print("To implement TWAP, you would need to create a custom algorithm that breaks down")
        print("a large order into smaller pieces and executes them over time.")
        # ... (rest of the TWAP order logic remains unchanged)

    def run(self):
        self.login()
        while True:
            print("\nWhat would you like to do?")
            print("1. View portfolio balances")
            print("2. Place a limit order")
            print("3. Place a TWAP order")
            print("4. Exit")
            
            choice = input("Enter your choice (1-4): ")
            
            if choice == '1':
                self.view_portfolio()
            elif choice == '2':
                self.place_limit_order()
            elif choice == '3':
                self.place_twap_order()
            elif choice == '4':
                print("Thank you for using the Coinbase Trading Terminal. Goodbye!")
                break
            else:
                print("Invalid choice. Please try again.")

def main():
    terminal = TradingTerminal()
    terminal.run()

if __name__ == "__main__":
    main()