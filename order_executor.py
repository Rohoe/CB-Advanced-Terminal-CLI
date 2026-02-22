"""
Order executor extracted from TradingTerminal.

Handles order placement, fee calculation, and user input gathering
for order parameters.
"""

from typing import Optional, Dict, List, Tuple
import logging
import time
import math

from validators import InputValidator, ValidationError
from ui_helpers import (
    info, highlight, format_currency, format_side,
    print_header, print_subheader, print_success, print_error,
    print_warning, print_info
)


class CancelledException(Exception):
    """Exception raised when user cancels an operation."""
    pass


class OrderExecutor:
    """
    Handles order placement with validation, retry logic, and fee calculation.
    """

    def __init__(self, api_client, market_data, rate_limiter, config):
        """
        Args:
            api_client: APIClient instance.
            market_data: MarketDataService instance.
            rate_limiter: RateLimiter instance.
            config: AppConfig instance.
        """
        self.api_client = api_client
        self.market_data = market_data
        self.rate_limiter = rate_limiter
        self.config = config

        # Fee tier cache
        self.fee_tier_cache = None
        self.fee_tier_cache_time = 0
        self.fee_tier_cache_ttl = 3600

    def get_fee_rates(self, force_refresh: bool = False) -> Tuple[float, float]:
        """Get current fee rates with caching. Returns (maker_rate, taker_rate)."""
        current_time = time.time()
        if not force_refresh and self.fee_tier_cache and (current_time - self.fee_tier_cache_time) < self.fee_tier_cache_ttl:
            return self.fee_tier_cache

        try:
            self.rate_limiter.wait()
            fee_info = self.api_client.get_transaction_summary()

            maker_rate = 0.006
            taker_rate = 0.006

            if hasattr(fee_info, 'fee_tier'):
                fee_tier = fee_info.fee_tier
                if isinstance(fee_tier, dict):
                    maker_rate = float(fee_tier.get('maker_fee_rate', 0.006))
                    taker_rate = float(fee_tier.get('taker_fee_rate', 0.006))
                elif hasattr(fee_tier, 'maker_fee_rate') and hasattr(fee_tier, 'taker_fee_rate'):
                    maker_rate = float(fee_tier.maker_fee_rate)
                    taker_rate = float(fee_tier.taker_fee_rate)
            elif isinstance(fee_info, dict) and 'fee_tier' in fee_info:
                fee_tier = fee_info['fee_tier']
                if isinstance(fee_tier, dict):
                    maker_rate = float(fee_tier.get('maker_fee_rate', 0.006))
                    taker_rate = float(fee_tier.get('taker_fee_rate', 0.006))

            self.fee_tier_cache = (maker_rate, taker_rate)
            self.fee_tier_cache_time = current_time
            return (maker_rate, taker_rate)

        except Exception as e:
            logging.error(f"Error fetching fee rates: {str(e)}", exc_info=True)
            return (0.006, 0.006)

    def calculate_estimated_fee(self, size: float, price: float, is_maker: bool = True) -> float:
        """Calculate estimated fee for an order."""
        try:
            maker_rate, taker_rate = self.get_fee_rates()
            order_value = size * price
            fee_rate = maker_rate if is_maker else taker_rate
            return order_value * fee_rate
        except Exception as e:
            logging.error(f"Error calculating fee: {str(e)}", exc_info=True)
            return size * price * 0.006

    def place_limit_order_with_retry(self, product_id, side, base_size, limit_price, client_order_id=None):
        """Place a limit order with enhanced error handling and validation."""
        try:
            if float(base_size) <= 0:
                raise ValueError("Order size must be greater than 0")

            product_info = self.api_client.get_product(product_id)
            base_min_size = float(getattr(product_info, 'base_min_size', 0.0001))
            base_max_size = float(getattr(product_info, 'base_max_size', 1000000))
            quote_increment = float(getattr(product_info, 'quote_increment', 0.01))

            if float(base_size) < base_min_size:
                logging.warning(f"Order size {base_size} is below minimum {base_min_size} for {product_id}")
                print(f"\nError: Order size {base_size} is below minimum {base_min_size} for {product_id}")
                return None

            if float(base_size) > base_max_size:
                logging.warning(f"Order size {base_size} is above maximum {base_max_size} for {product_id}")
                print(f"\nError: Order size {base_size} is above maximum {base_max_size} for {product_id}")
                return None

            rounded_price = round(float(limit_price) / quote_increment) * quote_increment

            if side == "BUY":
                quote_currency = product_id.split('-')[1]
                required_funds = float(base_size) * float(limit_price)
                available_balance = self.market_data.get_account_balance(quote_currency)
                if available_balance < required_funds:
                    print(f"\nError: Insufficient {quote_currency} balance. Need {required_funds:.2f}, have {available_balance:.2f}")
                    return None
            else:
                base_currency = product_id.split('-')[0]
                available_balance = self.market_data.get_account_balance(base_currency)
                if available_balance < float(base_size):
                    print(f"\nError: Insufficient {base_currency} balance. Need {float(base_size):.8f}, have {available_balance:.8f}")
                    return None

            order_response = self.api_client.limit_order_gtc(
                client_order_id=client_order_id or f"limit-order-{int(time.time())}",
                product_id=product_id,
                side=side,
                base_size=str(self.market_data.round_size(base_size, product_id)),
                limit_price=str(self.market_data.round_price(rounded_price, product_id))
            )

            if order_response:
                if hasattr(order_response, 'success') and order_response.success:
                    return order_response.to_dict()
                if hasattr(order_response, 'error_response') and order_response.error_response:
                    error_msg = order_response.error_response.get('message', 'Unknown error')
                    logging.error(f"Order placement failed: {error_msg}")
                    return None

            return None

        except Exception as e:
            logging.error(f"Error placing limit order: {str(e)}")
            return None

    def get_order_input(self, get_input_fn):
        """
        Get common order parameters from user input.

        Args:
            get_input_fn: Callable for user input (prompt -> str).

        Returns:
            Dict with product_id, side, limit_price, base_size, or None.
        """
        try:
            product_id = self.market_data.select_market(get_input_fn)
            if not product_id:
                return None

            while True:
                side = get_input_fn("\nEnter order side (buy/sell)").upper()
                if side in ['BUY', 'SELL']:
                    break
                print("Invalid side. Please enter 'buy' or 'sell'.")

            current_prices = self.market_data.get_current_prices(product_id)
            if current_prices:
                self.market_data.display_market_conditions(product_id, side, current_prices)

            while True:
                try:
                    limit_price = float(get_input_fn("\nEnter limit price"))
                    if limit_price <= 0:
                        print("Price must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            while True:
                try:
                    base_size = float(get_input_fn("\nEnter order size"))
                    if base_size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid number.")

            product_info = self.api_client.get_product(product_id)
            min_size = float(product_info['base_min_size'])
            if base_size < min_size:
                print(f"Error: Order size must be at least {min_size}")
                return None

            return {
                "product_id": product_id,
                "side": side,
                "limit_price": limit_price,
                "base_size": base_size
            }

        except CancelledException:
            raise
        except Exception as e:
            logging.error(f"Error getting order input: {str(e)}", exc_info=True)
            print(f"Error getting order input: {str(e)}")
            return None

