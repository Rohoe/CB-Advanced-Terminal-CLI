"""
Precision service for product-specific price and size rounding.

Extracted from MarketDataService to separate precision logic from
market data concerns.
"""

import math
import logging


class PrecisionService:
    """Rounds prices and sizes to product-specific increments."""

    def __init__(self, api_client, precision_config: dict):
        """
        Args:
            api_client: APIClient instance (for product metadata).
            precision_config: Product override dict from AppConfig.precision.
        """
        self.api_client = api_client
        self.precision_config = precision_config

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
            logging.error(f"Error rounding size: {e}")
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
            logging.error(f"Error rounding price: {e}")
            if product_id in self.precision_config:
                precision = self.precision_config[product_id]['price']
                return round(float(price), precision)
            return float(price)
