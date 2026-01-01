"""
Pydantic schemas for Coinbase API responses.

These schemas validate that mock responses match the real API structure.
They handle the mixed access patterns (dot notation and dict access) used
by the Coinbase SDK.
"""
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, ConfigDict


# ============================================================================
# Account Responses
# ============================================================================

class Account(BaseModel):
    """Individual account object."""
    model_config = ConfigDict(extra='allow')

    currency: str
    available_balance: Dict[str, str]  # Dict access pattern: {'value': '...', 'currency': '...'}
    type: str
    ready: bool
    active: bool


class AccountsResponse(BaseModel):
    """Response from get_accounts()."""
    model_config = ConfigDict(extra='allow')

    accounts: List[Account]
    cursor: str = ''
    has_next: bool = False


# ============================================================================
# Product Responses
# ============================================================================

class Product(BaseModel):
    """Individual product object."""
    model_config = ConfigDict(extra='allow')

    product_id: str
    price: str
    volume_24h: Optional[str] = None

    # Constraint fields (can be accessed as dict too)
    base_min_size: Optional[str] = None
    base_max_size: Optional[str] = None
    base_increment: Optional[str] = None
    quote_increment: Optional[str] = None

    def __getitem__(self, key: str):
        """Support dict-style access for mixed patterns."""
        return getattr(self, key)


class ProductsResponse(BaseModel):
    """Response from get_products()."""
    model_config = ConfigDict(extra='allow')

    products: List[Product]

    def __getitem__(self, key: str):
        """Support dict-style access."""
        return getattr(self, key)


class ProductBook(BaseModel):
    """Response from get_product_book() - pure dict."""
    model_config = ConfigDict(extra='allow')

    pricebook: Dict[str, List[Dict[str, str]]]


# ============================================================================
# Order Responses
# ============================================================================

class SuccessResponse(BaseModel):
    """Nested success response in order."""
    model_config = ConfigDict(extra='allow')

    order_id: str


class ErrorResponse(BaseModel):
    """Nested error response."""
    model_config = ConfigDict(extra='allow')

    message: str
    error: Optional[str] = None


class OrderResponse(BaseModel):
    """Response from limit_order_gtc()."""
    model_config = ConfigDict(extra='allow')

    success: bool
    success_response: Optional[SuccessResponse] = None
    error_response: Optional[ErrorResponse] = None
    order_id: Optional[str] = None  # Sometimes direct access

    def to_dict(self) -> dict:
        """Mock the SDK's to_dict() method."""
        return self.model_dump()

    def __getitem__(self, key: str):
        """Support dict-style access."""
        if key == 'success_response' and self.success_response:
            return {'order_id': self.success_response.order_id}
        return getattr(self, key)


class Order(BaseModel):
    """Individual order object."""
    model_config = ConfigDict(extra='allow')

    order_id: str
    product_id: str
    side: str
    status: str
    order_configuration: Optional[Dict] = None


class OrdersResponse(BaseModel):
    """Response from list_orders()."""
    model_config = ConfigDict(extra='allow')

    orders: List[Order]


# ============================================================================
# Fill Responses
# ============================================================================

class Fill(BaseModel):
    """Individual fill object."""
    model_config = ConfigDict(extra='allow')

    order_id: str
    trade_id: str
    size: str
    price: str
    fee: str
    liquidity_indicator: str  # 'M' for MAKER, 'T' for TAKER
    trade_time: str


class FillsResponse(BaseModel):
    """Response from get_fills()."""
    model_config = ConfigDict(extra='allow')

    fills: List[Fill]


# ============================================================================
# Transaction Summary
# ============================================================================

class TransactionSummary(BaseModel):
    """Response from get_transaction_summary()."""
    model_config = ConfigDict(extra='allow')

    fee_tier: Dict[str, str]  # Dict access pattern


# ============================================================================
# Cancel Responses
# ============================================================================

class CancelResult(BaseModel):
    """Individual cancel result."""
    model_config = ConfigDict(extra='allow')

    order_id: str
    success: bool
    error: Optional[str] = None


class CancelResponse(BaseModel):
    """Response from cancel_orders()."""
    model_config = ConfigDict(extra='allow')

    results: List[CancelResult]


# ============================================================================
# Validation Helper Functions
# ============================================================================

def validate_accounts_response(response_data: dict) -> AccountsResponse:
    """
    Validate accounts response data against schema.

    Args:
        response_data: Raw response data to validate.

    Returns:
        Validated AccountsResponse instance.

    Raises:
        ValidationError: If data doesn't match schema.
    """
    return AccountsResponse(**response_data)


def validate_products_response(response_data: dict) -> ProductsResponse:
    """
    Validate products response data against schema.

    Args:
        response_data: Raw response data to validate.

    Returns:
        Validated ProductsResponse instance.

    Raises:
        ValidationError: If data doesn't match schema.
    """
    return ProductsResponse(**response_data)


def validate_fills_response(response_data: dict) -> FillsResponse:
    """
    Validate fills response data against schema.

    Args:
        response_data: Raw response data to validate.

    Returns:
        Validated FillsResponse instance.

    Raises:
        ValidationError: If data doesn't match schema.
    """
    return FillsResponse(**response_data)


def validate_order_response(response_data: dict) -> OrderResponse:
    """
    Validate order response data against schema.

    Args:
        response_data: Raw response data to validate.

    Returns:
        Validated OrderResponse instance.

    Raises:
        ValidationError: If data doesn't match schema.
    """
    return OrderResponse(**response_data)
