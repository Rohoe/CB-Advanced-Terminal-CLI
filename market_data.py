"""
Market data service extracted from TradingTerminal.

Provides market data operations including account info, prices, order book,
market selection, and precision rounding.
"""

from typing import Optional, Dict, List, Any
import math
import logging
import time
from collections import defaultdict
from tabulate import tabulate
from ui_helpers import print_warning, format_currency


class MarketDataService:
    """
    Handles all market data operations: accounts, prices, order book,
    market selection, and precision rounding.
    """

    def __init__(self, api_client, rate_limiter, config):
        self.api_client = api_client
        self.rate_limiter = rate_limiter
        self.config = config

        # Account cache
        self.account_cache = {}
        self.account_cache_time = 0
        self.account_cache_ttl = config.cache.account_ttl

        # Precision config
        self.precision_config = config.precision.product_overrides

    def get_accounts(self, force_refresh=False):
        """Get account information with caching."""
        current_time = time.time()
        if force_refresh or not self.account_cache or (current_time - self.account_cache_time) > self.account_cache_ttl:
            try:
                logging.info("Fetching fresh account data from API")
                all_accounts = []
                cursor = None
                has_next = True

                while has_next:
                    self.rate_limiter.wait()
                    accounts_response = self.api_client.get_accounts(
                        cursor=cursor, limit=250
                    )
                    accounts = accounts_response.accounts
                    all_accounts.extend(accounts)
                    cursor = accounts_response.cursor if hasattr(accounts_response, 'cursor') else ''
                    has_next = accounts_response.has_next
                    logging.debug(f"Fetched {len(accounts)} accounts. Cursor: {cursor}, Has next: {has_next}")
                    if not cursor:
                        break

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
            balance = float(accounts[currency]['available_balance']['value'])
            logging.info(f"Retrieved balance for {currency}: {balance}")
            return balance
        logging.warning(f"No account found for currency: {currency}")
        return 0

    def get_bulk_prices(self, product_ids: List[str]) -> Dict[str, float]:
        """Get prices for multiple products in a single API call."""
        prices = {}
        try:
            logging.debug(f"Fetching bulk prices for {len(product_ids)} products")
            self.rate_limiter.wait()
            products_response = self.api_client.get_products()
            products = products_response.products if hasattr(products_response, 'products') else []

            for product in products:
                product_id = getattr(product, 'product_id', None)
                if product_id and product_id in product_ids:
                    try:
                        price = getattr(product, 'price', 0)
                        prices[product_id] = float(price)
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Could not parse price for {product_id}: {e}")

            logging.info(f"Successfully fetched {len(prices)} prices out of {len(product_ids)} requested")
        except Exception as e:
            logging.error(f"Error fetching bulk prices: {str(e)}", exc_info=True)
        return prices

    def get_current_prices(self, product_id: str):
        """Get current bid, ask, and mid prices for a product."""
        try:
            product_book = self.api_client.get_product_book(product_id, limit=1)
            pricebook = product_book['pricebook']
            if pricebook['bids'] and pricebook['asks']:
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
            fills_response = self.api_client.get_fills(order_ids=order_ids)
            if not hasattr(fills_response, 'fills'):
                logging.warning("No fills data in response")
                return {}

            fills = fills_response.fills
            fills_by_order = defaultdict(lambda: {
                'filled_size': 0.0, 'filled_value': 0.0, 'fees': 0.0,
                'is_maker': False, 'average_price': 0.0, 'status': 'UNKNOWN'
            })

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
        """Get top markets by 24h USD volume, consolidating USD and USDC pairs."""
        try:
            products_response = self.api_client.get_products()
            products = products_response['products']

            consolidated = {}
            for product in products:
                product_id = product['product_id']
                base_currency = product_id.split('-')[0]
                quote_currency = product_id.split('-')[1]

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
                        'total_volume': 0, 'has_usd': False, 'has_usdc': False,
                        'usd_product': None, 'usdc_product': None
                    }

                consolidated[base_currency]['total_volume'] += usd_volume
                if quote_currency == 'USD':
                    consolidated[base_currency]['has_usd'] = True
                    consolidated[base_currency]['usd_product'] = product_id
                else:
                    consolidated[base_currency]['has_usdc'] = True
                    consolidated[base_currency]['usdc_product'] = product_id

            top_markets = sorted(
                [(k, v) for k, v in consolidated.items() if v['has_usd'] or v['has_usdc']],
                key=lambda x: x[1]['total_volume'], reverse=True
            )[:limit]

            NUM_COLUMNS = 4
            rows = []
            current_row = []
            for i, (base_currency, data) in enumerate(top_markets, 1):
                volume_millions = data['total_volume'] / 1_000_000
                current_row.extend([f"{i}.", f"{base_currency}-USD(C)", f"${volume_millions:.2f}M"])
                if i % NUM_COLUMNS == 0:
                    rows.append(current_row)
                    current_row = []

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

    def select_market(self, get_input_fn) -> Optional[str]:
        """
        Interactive market selection from top 20 markets by volume.

        Args:
            get_input_fn: Callable that takes a prompt string and returns user input.

        Returns:
            Selected product_id or None.
        """
        rows, headers, top_markets = self.get_consolidated_markets(20)
        if not rows:
            logging.error("Failed to fetch top markets")
            print("Error fetching market data. Please try again.")
            return None

        print("\nTop Markets by 24h Volume:")
        print("=" * 120)
        print(tabulate(rows, headers=headers, tablefmt="plain", numalign="left"))
        print("=" * 120)

        while True:
            product_choice = get_input_fn("\nEnter the number of the market to trade (1-20)")
            try:
                index = int(product_choice)
                if 1 <= index <= len(top_markets):
                    base_currency, market_data = top_markets[index - 1]
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
                            quote_choice = get_input_fn(f"Select quote currency (1-{len(available_quotes)})")
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

                    if quote_currency == 'USD':
                        product_id = market_data['usd_product']
                    else:
                        product_id = market_data['usdc_product']

                    return product_id
                else:
                    print("Invalid selection. Please enter a number between 1 and 20.")
            except ValueError:
                print("Please enter a valid number.")

    def display_market_conditions(self, product_id: str, side: str, current_prices: dict = None):
        """Display current market conditions including prices and balance information."""
        try:
            base_currency = product_id.split('-')[0]
            quote_currency = product_id.split('-')[1]

            if not current_prices:
                current_prices = self.get_current_prices(product_id)
                if not current_prices:
                    print_warning("Unable to fetch current market prices.")
                    return

            self.rate_limiter.wait()
            base_balance = self.get_account_balance(base_currency)
            self.rate_limiter.wait()
            quote_balance = self.get_account_balance(quote_currency)

            print("\nCurrent Market Conditions:")
            print("=" * 50)
            print(f"Current prices for {product_id}:")
            print(f"Bid: ${current_prices['bid']:.2f}")
            print(f"Ask: ${current_prices['ask']:.2f}")
            print(f"Mid: ${current_prices['mid']:.2f}")
            print("-" * 50)

            if side == 'BUY':
                potential_size = quote_balance / current_prices['ask']
                print(f"Available {quote_currency}: {quote_balance:.2f}")
                print(f"Maximum {base_currency} you can buy at current ask: {potential_size:.8f}")
                print("\nExample trade sizes:")
                for pct in [25, 50, 75, 100]:
                    size = (potential_size * pct) / 100
                    cost = size * current_prices['ask']
                    print(f"{pct}% - Size: {size:.8f} {base_currency} (Cost: ${cost:.2f} {quote_currency})")
            else:
                potential_value = base_balance * current_prices['bid']
                print(f"Available {base_currency}: {base_balance:.8f}")
                print(f"Total value at current bid: ${potential_value:.2f}")
                print("\nExample trade sizes:")
                for pct in [25, 50, 75, 100]:
                    size = (base_balance * pct) / 100
                    value = size * current_prices['bid']
                    print(f"{pct}% - Size: {size:.8f} {base_currency} (Value: ${value:.2f} {quote_currency})")

            print("=" * 50)

        except Exception as e:
            logging.error(f"Error displaying market conditions: {str(e)}")
            print_warning("Error displaying market conditions. Continuing...")

    def round_size(self, size, product_id):
        """Round order size to appropriate precision for the product."""
        try:
            product_info = self.api_client.get_product(product_id)
            base_increment = float(product_info['base_increment'])
            if base_increment >= 1:
                precision = 0
            else:
                precision = abs(int(math.log10(base_increment)))
            return round(float(size), precision)
        except Exception as e:
            logging.error(f"Error rounding size: {str(e)}")
            if product_id in self.precision_config:
                precision = self.precision_config[product_id]['size']
                return round(float(size), precision)
            return float(size)

    def round_price(self, price, product_id):
        """Round price to appropriate precision for the product."""
        try:
            product_info = self.api_client.get_product(product_id)
            quote_increment = float(product_info['quote_increment'])
            if quote_increment >= 1:
                precision = 0
            else:
                precision = abs(int(math.log10(quote_increment)))
            return round(float(price), precision)
        except Exception as e:
            logging.error(f"Error rounding price: {str(e)}")
            if product_id in self.precision_config:
                precision = self.precision_config[product_id]['price']
                return round(float(price), precision)
            return float(price)
