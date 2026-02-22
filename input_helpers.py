"""
Shared interactive input collection helpers.

Eliminates duplicated input-gathering loops across executors
(scaled, VWAP, conditional) for market, side, price, size, duration, and slices.
"""

from validators import InputValidator, ValidationError


class InteractiveInputHelper:
    """Reusable input collection methods for executor flows."""

    def __init__(self, market_data):
        self.market_data = market_data

    def get_market(self, get_input_fn):
        """Select a market. Returns product_id or None."""
        return self.market_data.select_market(get_input_fn)

    def get_side(self, get_input_fn):
        """Get buy/sell side from user. Returns 'BUY' or 'SELL'."""
        while True:
            side = get_input_fn("\nEnter order side (buy/sell)").upper()
            if side in ['BUY', 'SELL']:
                return side
            print("Invalid side. Please enter 'buy' or 'sell'.")

    def get_price(self, get_input_fn, prompt="\nEnter limit price"):
        """Get a validated price from user. Returns float."""
        while True:
            try:
                price = float(get_input_fn(prompt))
                InputValidator.validate_price(price)
                return price
            except (ValueError, ValidationError) as e:
                print(f"Invalid price: {e}")

    def get_size(self, get_input_fn, prompt="\nEnter order size"):
        """Get a positive size from user. Returns float."""
        while True:
            try:
                size = float(get_input_fn(prompt))
                if size <= 0:
                    print("Size must be greater than 0.")
                    continue
                return size
            except ValueError:
                print("Please enter a valid number.")

    def get_duration(self, get_input_fn, prompt="\nEnter duration in minutes"):
        """Get a validated duration in minutes. Returns int."""
        while True:
            try:
                duration = int(get_input_fn(prompt))
                InputValidator.validate_twap_duration(duration)
                return duration
            except (ValueError, ValidationError) as e:
                print(f"Invalid duration: {e}")

    def get_num_slices(self, get_input_fn, min_slices=2, max_slices=1000,
                       prompt="Enter number of slices"):
        """Get a validated number of slices. Returns int."""
        while True:
            try:
                num = int(get_input_fn(prompt))
                if num < min_slices:
                    print(f"Need at least {min_slices} slices.")
                    continue
                if num > max_slices:
                    print(f"Maximum {max_slices} slices.")
                    continue
                return num
            except ValueError:
                print("Please enter a valid number.")

    def display_market_conditions(self, product_id, side):
        """Fetch and display current market conditions."""
        current_prices = self.market_data.get_current_prices(product_id)
        if current_prices:
            self.market_data.display_market_conditions(product_id, side, current_prices)
        return current_prices
