"""
Input validation for trading operations.

This module provides centralized validation for all user inputs in the trading
terminal, ensuring that invalid data is caught early with clear error messages.

Usage:
    from validators import InputValidator, ValidationError

    try:
        price = InputValidator.validate_price(user_input)
        size = InputValidator.validate_size(user_input, min_size=0.001, max_size=100)
        duration = InputValidator.validate_twap_duration(60)
    except ValidationError as e:
        print(f"Invalid input: {e}")
"""

import logging
from typing import Optional


class ValidationError(Exception):
    """
    Exception raised when input validation fails.

    This exception provides a user-friendly error message explaining
    what validation failed and how to fix it.

    Attributes:
        message: Human-readable description of the validation failure.
        field: Optional name of the field that failed validation.
        value: Optional value that was rejected.
    """

    def __init__(self, message: str, field: Optional[str] = None, value=None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.field:
            return f"{self.field}: {self.message}"
        return self.message


class InputValidator:
    """
    Centralized input validation for trading operations.

    All methods are static and can be called directly without instantiation.
    Each method returns the validated value if valid, or raises ValidationError
    if invalid.

    Example:
        >>> price = InputValidator.validate_price(100.50)
        >>> print(price)
        100.5

        >>> InputValidator.validate_price(-10)
        ValidationError: Price must be greater than 0
    """

    @staticmethod
    def validate_price(price: float, min_price: float = 0.0001) -> float:
        """
        Validate a price input.

        Args:
            price: The price value to validate.
            min_price: Minimum acceptable price (default: 0.0001).

        Returns:
            The validated price as a float.

        Raises:
            ValidationError: If price is not a positive number or below minimum.

        Example:
            >>> InputValidator.validate_price(50000.0)
            50000.0
            >>> InputValidator.validate_price(0)
            ValidationError: Price must be greater than 0
        """
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Price must be a valid number, got: {type(price).__name__}",
                field="price",
                value=price
            )

        if price <= 0:
            raise ValidationError(
                "Price must be greater than 0",
                field="price",
                value=price
            )

        if price < min_price:
            raise ValidationError(
                f"Price must be at least {min_price}",
                field="price",
                value=price
            )

        return price

    @staticmethod
    def validate_size(size: float, min_size: float, max_size: float) -> float:
        """
        Validate an order size.

        Args:
            size: The order size to validate.
            min_size: Minimum order size (from product specification).
            max_size: Maximum order size (from product specification).

        Returns:
            The validated size as a float.

        Raises:
            ValidationError: If size is outside the valid range.

        Example:
            >>> InputValidator.validate_size(0.5, min_size=0.001, max_size=100)
            0.5
            >>> InputValidator.validate_size(0.0001, min_size=0.001, max_size=100)
            ValidationError: Size must be at least 0.001
        """
        try:
            size = float(size)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Size must be a valid number, got: {type(size).__name__}",
                field="size",
                value=size
            )

        if size <= 0:
            raise ValidationError(
                "Size must be greater than 0",
                field="size",
                value=size
            )

        if size < min_size:
            raise ValidationError(
                f"Size must be at least {min_size}",
                field="size",
                value=size
            )

        if size > max_size:
            raise ValidationError(
                f"Size cannot exceed {max_size}",
                field="size",
                value=size
            )

        return size

    @staticmethod
    def validate_twap_duration(
        duration: int,
        min_duration: int = 1,
        max_duration: int = 1440
    ) -> int:
        """
        Validate TWAP duration in minutes.

        Args:
            duration: Duration in minutes.
            min_duration: Minimum duration in minutes (default: 1).
            max_duration: Maximum duration in minutes (default: 1440 = 24 hours).

        Returns:
            The validated duration as an integer.

        Raises:
            ValidationError: If duration is outside the valid range.

        Example:
            >>> InputValidator.validate_twap_duration(60)
            60
            >>> InputValidator.validate_twap_duration(0)
            ValidationError: Duration must be at least 1 minute(s)
        """
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Duration must be a valid integer, got: {type(duration).__name__}",
                field="duration",
                value=duration
            )

        if duration < min_duration:
            raise ValidationError(
                f"Duration must be at least {min_duration} minute(s)",
                field="duration",
                value=duration
            )

        if duration > max_duration:
            hours = max_duration // 60
            raise ValidationError(
                f"Duration cannot exceed {max_duration} minutes ({hours} hours)",
                field="duration",
                value=duration
            )

        return duration

    @staticmethod
    def validate_num_slices(
        num_slices: int,
        total_size: float,
        min_size: float,
        max_slices: int = 1000
    ) -> int:
        """
        Validate the number of TWAP slices.

        Ensures that:
        1. num_slices is at least 1
        2. num_slices doesn't exceed max_slices
        3. The resulting slice size is at least min_size

        Args:
            num_slices: Number of slices for the TWAP order.
            total_size: Total order size to be split into slices.
            min_size: Minimum order size for the product.
            max_slices: Maximum allowed number of slices (default: 1000).

        Returns:
            The validated num_slices as an integer.

        Raises:
            ValidationError: If num_slices would result in invalid slice sizes.

        Example:
            >>> InputValidator.validate_num_slices(10, total_size=1.0, min_size=0.01)
            10
            >>> InputValidator.validate_num_slices(200, total_size=1.0, min_size=0.01)
            ValidationError: Slice size (0.005) would be below minimum (0.01)
        """
        try:
            num_slices = int(num_slices)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Number of slices must be a valid integer, got: {type(num_slices).__name__}",
                field="num_slices",
                value=num_slices
            )

        if num_slices < 1:
            raise ValidationError(
                "Number of slices must be at least 1",
                field="num_slices",
                value=num_slices
            )

        if num_slices > max_slices:
            raise ValidationError(
                f"Number of slices cannot exceed {max_slices}",
                field="num_slices",
                value=num_slices
            )

        # Calculate slice size and validate
        slice_size = total_size / num_slices
        if slice_size < min_size:
            max_valid_slices = int(total_size / min_size)
            raise ValidationError(
                f"Slice size ({slice_size:.8f}) would be below minimum ({min_size}). "
                f"Reduce number of slices to at most {max_valid_slices}",
                field="num_slices",
                value=num_slices
            )

        return num_slices

    @staticmethod
    def validate_side(side: str) -> str:
        """
        Validate order side (BUY or SELL).

        Args:
            side: The order side, case-insensitive.

        Returns:
            The validated side in uppercase ('BUY' or 'SELL').

        Raises:
            ValidationError: If side is not 'buy' or 'sell'.

        Example:
            >>> InputValidator.validate_side('buy')
            'BUY'
            >>> InputValidator.validate_side('hold')
            ValidationError: Side must be 'buy' or 'sell'
        """
        if not isinstance(side, str):
            raise ValidationError(
                f"Side must be a string, got: {type(side).__name__}",
                field="side",
                value=side
            )

        side_upper = side.upper().strip()
        if side_upper not in ('BUY', 'SELL'):
            raise ValidationError(
                "Side must be 'buy' or 'sell'",
                field="side",
                value=side
            )

        return side_upper

    @staticmethod
    def validate_product_id(product_id: str) -> str:
        """
        Validate product ID format.

        Product IDs should be in the format 'BASE-QUOTE' (e.g., 'BTC-USD').

        Args:
            product_id: The product ID to validate.

        Returns:
            The validated product ID.

        Raises:
            ValidationError: If product ID format is invalid.

        Example:
            >>> InputValidator.validate_product_id('BTC-USD')
            'BTC-USD'
            >>> InputValidator.validate_product_id('BTCUSD')
            ValidationError: Product ID must be in format 'BASE-QUOTE'
        """
        if not isinstance(product_id, str):
            raise ValidationError(
                f"Product ID must be a string, got: {type(product_id).__name__}",
                field="product_id",
                value=product_id
            )

        product_id = product_id.upper().strip()

        if '-' not in product_id:
            raise ValidationError(
                "Product ID must be in format 'BASE-QUOTE' (e.g., 'BTC-USD')",
                field="product_id",
                value=product_id
            )

        parts = product_id.split('-')
        if len(parts) != 2:
            raise ValidationError(
                "Product ID must have exactly one '-' separator",
                field="product_id",
                value=product_id
            )

        base, quote = parts
        if not base or not quote:
            raise ValidationError(
                "Product ID must have both base and quote currencies",
                field="product_id",
                value=product_id
            )

        return product_id

    @staticmethod
    def validate_price_type(price_type: str) -> str:
        """
        Validate TWAP price type selection.

        Args:
            price_type: The price type selection (1-4).

        Returns:
            The validated price type.

        Raises:
            ValidationError: If price type is not valid.

        Example:
            >>> InputValidator.validate_price_type('1')
            '1'
            >>> InputValidator.validate_price_type('5')
            ValidationError: Price type must be 1, 2, 3, or 4
        """
        valid_types = ('1', '2', '3', '4')

        if not isinstance(price_type, str):
            price_type = str(price_type)

        price_type = price_type.strip()

        if price_type not in valid_types:
            raise ValidationError(
                "Price type must be 1, 2, 3, or 4:\n"
                "  1 = Original limit price\n"
                "  2 = Current market bid\n"
                "  3 = Current market mid\n"
                "  4 = Current market ask",
                field="price_type",
                value=price_type
            )

        return price_type

    @staticmethod
    def validate_price_range(price_low: float, price_high: float) -> tuple:
        """
        Validate a price range for scaled orders.

        Args:
            price_low: Lower bound of the price range.
            price_high: Upper bound of the price range.

        Returns:
            Tuple of (price_low, price_high) as floats.

        Raises:
            ValidationError: If range is invalid.
        """
        price_low = InputValidator.validate_price(price_low)
        price_high = InputValidator.validate_price(price_high)

        if price_low >= price_high:
            raise ValidationError(
                f"Low price ({price_low}) must be less than high price ({price_high})",
                field="price_range",
                value=(price_low, price_high)
            )

        return (price_low, price_high)

    @staticmethod
    def validate_num_orders(
        num_orders: int,
        total_size: float,
        min_size: float,
        max_orders: int = 100
    ) -> int:
        """
        Validate the number of orders for a scaled order.

        Ensures that:
        1. num_orders is at least 1
        2. num_orders doesn't exceed max_orders
        3. The minimum per-order size is at least min_size

        Args:
            num_orders: Number of orders to place.
            total_size: Total order size to split.
            min_size: Minimum order size for the product.
            max_orders: Maximum number of orders (default: 100).

        Returns:
            The validated num_orders as an integer.

        Raises:
            ValidationError: If num_orders would result in invalid order sizes.
        """
        try:
            num_orders = int(num_orders)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Number of orders must be a valid integer, got: {type(num_orders).__name__}",
                field="num_orders",
                value=num_orders
            )

        if num_orders < 1:
            raise ValidationError(
                "Number of orders must be at least 1",
                field="num_orders",
                value=num_orders
            )

        if num_orders > max_orders:
            raise ValidationError(
                f"Number of orders cannot exceed {max_orders}",
                field="num_orders",
                value=num_orders
            )

        # For linear distribution, each order gets total_size/num_orders
        # For other distributions, minimum per-order could be even smaller
        # Validate conservatively using linear (worst case for min size)
        min_per_order = total_size / num_orders
        if min_per_order < min_size:
            max_valid = int(total_size / min_size)
            raise ValidationError(
                f"Order size ({min_per_order:.8f}) would be below minimum ({min_size}). "
                f"Reduce number of orders to at most {max_valid}",
                field="num_orders",
                value=num_orders
            )

        return num_orders
