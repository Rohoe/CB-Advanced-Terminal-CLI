"""
Unit tests for input validators.

This file tests the InputValidator class which provides validation
for all user inputs including prices, sizes, TWAP parameters, etc.

To run these tests:
    pytest tests/test_validators.py
    pytest tests/test_validators.py::TestInputValidator::test_validate_price_valid
"""

import pytest
from validators import InputValidator, ValidationError


# =============================================================================
# Price Validation Tests
# =============================================================================

@pytest.mark.unit
class TestPriceValidation:
    """Tests for price validation."""

    def test_validate_price_valid(self):
        """Test that valid prices are accepted."""
        # Test various valid prices
        assert InputValidator.validate_price(100.5) == 100.5
        assert InputValidator.validate_price(0.0001) == 0.0001
        assert InputValidator.validate_price(1000000) == 1000000

    def test_validate_price_zero(self):
        """Test that zero price is rejected."""
        with pytest.raises(ValidationError, match="greater than 0"):
            InputValidator.validate_price(0)

    def test_validate_price_negative(self):
        """Test that negative prices are rejected."""
        with pytest.raises(ValidationError, match="greater than 0"):
            InputValidator.validate_price(-10)

    def test_validate_price_below_minimum(self):
        """Test that prices below minimum are rejected."""
        with pytest.raises(ValidationError, match="at least 0.01"):
            InputValidator.validate_price(0.005, min_price=0.01)

    def test_validate_price_invalid_type(self):
        """Test that invalid types are rejected."""
        with pytest.raises(ValidationError, match="must be a valid number"):
            InputValidator.validate_price("not a number")


# =============================================================================
# Size Validation Tests
# =============================================================================

@pytest.mark.unit
class TestSizeValidation:
    """Tests for order size validation."""

    def test_validate_size_valid(self):
        """Test that valid sizes are accepted."""
        result = InputValidator.validate_size(
            size=1.5,
            min_size=0.001,
            max_size=100
        )
        assert result == 1.5

    def test_validate_size_at_minimum(self):
        """Test that size exactly at minimum is accepted."""
        result = InputValidator.validate_size(
            size=0.001,
            min_size=0.001,
            max_size=100
        )
        assert result == 0.001

    def test_validate_size_at_maximum(self):
        """Test that size exactly at maximum is accepted."""
        result = InputValidator.validate_size(
            size=100,
            min_size=0.001,
            max_size=100
        )
        assert result == 100

    def test_validate_size_below_minimum(self):
        """Test that size below minimum is rejected."""
        with pytest.raises(ValidationError, match="at least 0.01"):
            InputValidator.validate_size(
                size=0.001,
                min_size=0.01,
                max_size=100
            )

    def test_validate_size_above_maximum(self):
        """Test that size above maximum is rejected."""
        with pytest.raises(ValidationError, match="cannot exceed 100"):
            InputValidator.validate_size(
                size=150,
                min_size=0.01,
                max_size=100
            )

    def test_validate_size_zero(self):
        """Test that zero size is rejected."""
        with pytest.raises(ValidationError, match="greater than 0"):
            InputValidator.validate_size(
                size=0,
                min_size=0.01,
                max_size=100
            )


# =============================================================================
# TWAP Duration Validation Tests
# =============================================================================

@pytest.mark.unit
class TestTWAPDurationValidation:
    """Tests for TWAP duration validation."""

    def test_validate_duration_valid(self):
        """Test that valid durations are accepted."""
        assert InputValidator.validate_twap_duration(60) == 60
        assert InputValidator.validate_twap_duration(1) == 1
        assert InputValidator.validate_twap_duration(1440) == 1440

    def test_validate_duration_too_short(self):
        """Test that duration below minimum is rejected."""
        with pytest.raises(ValidationError, match="at least 1 minute"):
            InputValidator.validate_twap_duration(0)

    def test_validate_duration_negative(self):
        """Test that negative duration is rejected."""
        with pytest.raises(ValidationError, match="at least 1 minute"):
            InputValidator.validate_twap_duration(-5)

    def test_validate_duration_too_long(self):
        """Test that duration exceeding maximum is rejected."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            InputValidator.validate_twap_duration(2000)

    def test_validate_duration_custom_range(self):
        """Test validation with custom min/max."""
        result = InputValidator.validate_twap_duration(
            duration=30,
            min_duration=10,
            max_duration=60
        )
        assert result == 30


# =============================================================================
# TWAP Num Slices Validation Tests
# =============================================================================

@pytest.mark.unit
class TestNumSlicesValidation:
    """Tests for number of TWAP slices validation."""

    def test_validate_num_slices_valid(self):
        """Test that valid number of slices is accepted."""
        result = InputValidator.validate_num_slices(
            num_slices=10,
            total_size=1.0,
            min_size=0.01
        )
        assert result == 10

    def test_validate_num_slices_minimum(self):
        """Test that 1 slice is accepted."""
        result = InputValidator.validate_num_slices(
            num_slices=1,
            total_size=1.0,
            min_size=0.01
        )
        assert result == 1

    def test_validate_num_slices_zero(self):
        """Test that zero slices is rejected."""
        with pytest.raises(ValidationError, match="at least 1"):
            InputValidator.validate_num_slices(
                num_slices=0,
                total_size=1.0,
                min_size=0.01
            )

    def test_validate_num_slices_exceeds_max(self):
        """Test that exceeding max slices is rejected."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            InputValidator.validate_num_slices(
                num_slices=2000,
                total_size=1.0,
                min_size=0.01,
                max_slices=1000
            )

    def test_validate_num_slices_below_minimum_size(self):
        """
        Test that slices resulting in size below minimum are rejected.

        This is a critical validation - if we split a 1.0 order into 200 slices,
        each slice would be 0.005, which is below the minimum of 0.01.
        """
        with pytest.raises(ValidationError, match="below minimum"):
            InputValidator.validate_num_slices(
                num_slices=200,  # Would create 0.005 per slice
                total_size=1.0,
                min_size=0.01
            )

    def test_validate_num_slices_error_message_includes_max(self):
        """Test that error message suggests maximum valid slices."""
        try:
            InputValidator.validate_num_slices(
                num_slices=200,
                total_size=1.0,
                min_size=0.01
            )
            assert False, "Should have raised ValidationError"
        except ValidationError as e:
            # Error message should suggest max valid slices (100)
            assert "100" in str(e)


# =============================================================================
# Side Validation Tests
# =============================================================================

@pytest.mark.unit
class TestSideValidation:
    """Tests for order side validation."""

    def test_validate_side_buy(self):
        """Test that 'buy' is accepted and normalized."""
        assert InputValidator.validate_side('buy') == 'BUY'
        assert InputValidator.validate_side('BUY') == 'BUY'
        assert InputValidator.validate_side('Buy') == 'BUY'

    def test_validate_side_sell(self):
        """Test that 'sell' is accepted and normalized."""
        assert InputValidator.validate_side('sell') == 'SELL'
        assert InputValidator.validate_side('SELL') == 'SELL'
        assert InputValidator.validate_side('Sell') == 'SELL'

    def test_validate_side_invalid(self):
        """Test that invalid sides are rejected."""
        with pytest.raises(ValidationError, match="must be 'buy' or 'sell'"):
            InputValidator.validate_side('hold')

    def test_validate_side_whitespace(self):
        """Test that whitespace is handled correctly."""
        assert InputValidator.validate_side('  buy  ') == 'BUY'


# =============================================================================
# Product ID Validation Tests
# =============================================================================

@pytest.mark.unit
class TestProductIDValidation:
    """Tests for product ID validation."""

    def test_validate_product_id_valid(self):
        """Test that valid product IDs are accepted."""
        assert InputValidator.validate_product_id('BTC-USD') == 'BTC-USD'
        assert InputValidator.validate_product_id('ETH-USDC') == 'ETH-USDC'
        assert InputValidator.validate_product_id('btc-usd') == 'BTC-USD'

    def test_validate_product_id_missing_separator(self):
        """Test that product IDs without separator are rejected."""
        with pytest.raises(ValidationError, match="must be in format"):
            InputValidator.validate_product_id('BTCUSD')

    def test_validate_product_id_multiple_separators(self):
        """Test that product IDs with multiple separators are rejected."""
        with pytest.raises(ValidationError, match="exactly one '-' separator"):
            InputValidator.validate_product_id('BTC-USD-EXTRA')

    def test_validate_product_id_empty_parts(self):
        """Test that product IDs with empty parts are rejected."""
        with pytest.raises(ValidationError, match="both base and quote"):
            InputValidator.validate_product_id('-USD')

        with pytest.raises(ValidationError, match="both base and quote"):
            InputValidator.validate_product_id('BTC-')


# =============================================================================
# Price Type Validation Tests
# =============================================================================

@pytest.mark.unit
class TestPriceTypeValidation:
    """Tests for TWAP price type validation."""

    def test_validate_price_type_valid(self):
        """Test that valid price types are accepted."""
        assert InputValidator.validate_price_type('1') == '1'
        assert InputValidator.validate_price_type('2') == '2'
        assert InputValidator.validate_price_type('3') == '3'
        assert InputValidator.validate_price_type('4') == '4'

    def test_validate_price_type_invalid(self):
        """Test that invalid price types are rejected."""
        with pytest.raises(ValidationError, match="must be 1, 2, 3, or 4"):
            InputValidator.validate_price_type('5')

        with pytest.raises(ValidationError, match="must be 1, 2, 3, or 4"):
            InputValidator.validate_price_type('0')

    def test_validate_price_type_whitespace(self):
        """Test that whitespace is handled."""
        assert InputValidator.validate_price_type('  1  ') == '1'


# =============================================================================
# ValidationError Tests
# =============================================================================

@pytest.mark.unit
class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_message(self):
        """Test that ValidationError has correct message."""
        error = ValidationError("Test error message")
        assert str(error) == "Test error message"

    def test_validation_error_with_field(self):
        """Test ValidationError with field name."""
        error = ValidationError("Invalid value", field="price")
        assert "price" in str(error)
        assert "Invalid value" in str(error)

    def test_validation_error_attributes(self):
        """Test that ValidationError stores attributes."""
        error = ValidationError("Test", field="size", value=0.001)
        assert error.field == "size"
        assert error.value == 0.001
        assert error.message == "Test"


# =============================================================================
# Price Range Validation Tests
# =============================================================================

@pytest.mark.unit
class TestPriceRangeValidation:
    """Tests for validate_price_range (scaled orders)."""

    def test_valid_range(self):
        low, high = InputValidator.validate_price_range(100.0, 200.0)
        assert low == 100.0
        assert high == 200.0

    def test_low_equals_high_rejected(self):
        with pytest.raises(ValidationError, match="must be less than"):
            InputValidator.validate_price_range(100.0, 100.0)

    def test_low_greater_than_high_rejected(self):
        with pytest.raises(ValidationError, match="must be less than"):
            InputValidator.validate_price_range(200.0, 100.0)

    def test_negative_low_rejected(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            InputValidator.validate_price_range(-10.0, 100.0)

    def test_negative_high_rejected(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            InputValidator.validate_price_range(10.0, -100.0)

    def test_very_close_prices_accepted(self):
        low, high = InputValidator.validate_price_range(100.0, 100.01)
        assert low < high


# =============================================================================
# Num Orders Validation Tests
# =============================================================================

@pytest.mark.unit
class TestNumOrdersValidation:
    """Tests for validate_num_orders (scaled orders)."""

    def test_valid_num_orders(self):
        result = InputValidator.validate_num_orders(
            num_orders=10, total_size=1.0, min_size=0.01
        )
        assert result == 10

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            InputValidator.validate_num_orders(
                num_orders=0, total_size=1.0, min_size=0.01
            )

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            InputValidator.validate_num_orders(
                num_orders=-5, total_size=1.0, min_size=0.01
            )

    def test_exceeds_max_rejected(self):
        with pytest.raises(ValidationError, match="cannot exceed"):
            InputValidator.validate_num_orders(
                num_orders=200, total_size=1.0, min_size=0.01, max_orders=100
            )

    def test_per_order_below_min_size(self):
        with pytest.raises(ValidationError):
            InputValidator.validate_num_orders(
                num_orders=200, total_size=1.0, min_size=0.01
            )

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError, match="must be a valid integer"):
            InputValidator.validate_num_orders(
                num_orders="abc", total_size=1.0, min_size=0.01
            )

    def test_single_order_accepted(self):
        result = InputValidator.validate_num_orders(
            num_orders=1, total_size=1.0, min_size=0.01
        )
        assert result == 1

    def test_error_suggests_max_valid(self):
        try:
            InputValidator.validate_num_orders(
                num_orders=200, total_size=1.0, min_size=0.01
            )
        except ValidationError as e:
            assert "100" in str(e)

    def test_at_max_accepted(self):
        result = InputValidator.validate_num_orders(
            num_orders=100, total_size=1.0, min_size=0.01, max_orders=100
        )
        assert result == 100
