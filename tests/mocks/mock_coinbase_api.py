"""
Mock Coinbase API client for testing.

This module provides an in-memory mock implementation of the Coinbase API
that can be used for testing without making real API calls.

Usage:
    from tests.mocks.mock_coinbase_api import MockCoinbaseAPI

    # Create mock client
    client = MockCoinbaseAPI()

    # Use just like the real client
    accounts = client.get_accounts()
    product = client.get_product('BTC-USD')
"""

from typing import List, Optional, Any, Dict
from unittest.mock import Mock
import logging

from api_client import APIClient

# Import schemas for validation (optional - logs warnings if validation fails)
try:
    from tests.schemas.api_responses import (
        AccountsResponse, ProductsResponse, ProductBook,
        FillsResponse, OrderResponse, OrdersResponse,
        CancelResponse, TransactionSummary
    )
    SCHEMAS_AVAILABLE = True
except ImportError:
    SCHEMAS_AVAILABLE = False
    logging.debug("Pydantic schemas not available - skipping validation")


class MockCoinbaseAPI(APIClient):
    """
    In-memory mock of Coinbase API for testing.

    This class implements the APIClient interface with in-memory storage,
    allowing tests to verify behavior without hitting the real API.

    Example:
        # Create mock API
        api = MockCoinbaseAPI()

        # Set up test data
        api.set_account_balance('BTC', 1.5)

        # Place orders
        response = api.limit_order_gtc(
            client_order_id='test-order-1',
            product_id='BTC-USD',
            side='BUY',
            base_size='0.1',
            limit_price='50000'
        )

        # Verify orders
        orders = api.list_orders()
        assert len(orders.orders) == 1
    """

    def __init__(self):
        """Initialize mock API with default test data."""
        # In-memory storage
        self.accounts: Dict[str, Dict] = {}
        self.products: Dict[str, Dict] = {}
        self.orders: Dict[str, Dict] = {}
        self.fills: Dict[str, List[Dict]] = {}
        self.order_books: Dict[str, Dict] = {}

        # Setup default test data
        self._setup_default_data()

        logging.debug("MockCoinbaseAPI initialized with test data")

    def _setup_default_data(self):
        """Setup realistic test data."""
        # Default accounts
        self.accounts = {
            'BTC': {
                'currency': 'BTC',
                'available_balance': {'value': '1.0', 'currency': 'BTC'},
                'type': 'CRYPTO',
                'ready': True,
                'active': True
            },
            'USDC': {
                'currency': 'USDC',
                'available_balance': {'value': '50000.0', 'currency': 'USDC'},
                'type': 'CRYPTO',
                'ready': True,
                'active': True
            },
            'ETH': {
                'currency': 'ETH',
                'available_balance': {'value': '10.0', 'currency': 'ETH'},
                'type': 'CRYPTO',
                'ready': True,
                'active': True
            }
        }

        # Default products
        self.products = {
            'BTC-USD': {
                'product_id': 'BTC-USD',
                'price': '50000.00',
                'base_min_size': '0.0001',
                'base_max_size': '10000',
                'base_increment': '0.00000001',
                'quote_increment': '0.01',
                'volume_24h': '1000'
            },
            'BTC-USDC': {
                'product_id': 'BTC-USDC',
                'price': '50000.00',
                'base_min_size': '0.0001',
                'base_max_size': '10000',
                'base_increment': '0.00000001',
                'quote_increment': '0.01',
                'volume_24h': '1000'
            },
            'ETH-USD': {
                'product_id': 'ETH-USD',
                'price': '3000.00',
                'base_min_size': '0.001',
                'base_max_size': '10000',
                'base_increment': '0.00000001',
                'quote_increment': '0.01',
                'volume_24h': '500'
            },
            'SOL-USD': {
                'product_id': 'SOL-USD',
                'price': '100.00',
                'base_min_size': '0.01',
                'base_max_size': '100000',
                'base_increment': '0.0001',
                'quote_increment': '0.01',
                'volume_24h': '200'
            }
        }

        # Default order books
        for product_id, product in self.products.items():
            price = float(product['price'])
            self.order_books[product_id] = {
                'pricebook': {
                    'bids': [{'price': str(price - 5), 'size': '1.0'}],
                    'asks': [{'price': str(price + 5), 'size': '1.0'}]
                }
            }

    # =========================================================================
    # Helper Methods for Test Setup
    # =========================================================================

    def set_account_balance(self, currency: str, balance: float):
        """
        Set account balance for testing.

        Args:
            currency: Currency code (e.g., 'BTC', 'USDC').
            balance: Balance amount.
        """
        if currency not in self.accounts:
            self.accounts[currency] = {
                'currency': currency,
                'available_balance': {'value': str(balance), 'currency': currency},
                'type': 'CRYPTO',
                'ready': True,
                'active': True
            }
        else:
            self.accounts[currency]['available_balance']['value'] = str(balance)

    def add_product(self, product_id: str, price: str, **kwargs):
        """
        Add a product for testing.

        Args:
            product_id: Product identifier (e.g., 'BTC-USD').
            price: Current price.
            **kwargs: Additional product fields.
        """
        self.products[product_id] = {
            'product_id': product_id,
            'price': price,
            'base_min_size': kwargs.get('base_min_size', '0.0001'),
            'base_max_size': kwargs.get('base_max_size', '10000'),
            'base_increment': kwargs.get('base_increment', '0.00000001'),
            'quote_increment': kwargs.get('quote_increment', '0.01'),
            'volume_24h': kwargs.get('volume_24h', '100')
        }

    def simulate_fill(self, order_id: str, filled_size: float, price: float, is_maker: bool = True):
        """
        Simulate an order fill for testing.

        Args:
            order_id: Order ID to fill.
            filled_size: Amount filled.
            price: Fill price.
            is_maker: Whether this is a maker order.
        """
        if order_id not in self.fills:
            self.fills[order_id] = []

        self.fills[order_id].append({
            'order_id': order_id,
            'trade_id': f'trade-{len(self.fills[order_id]) + 1}',
            'size': str(filled_size),
            'price': str(price),
            'fee': str(filled_size * price * (0.004 if is_maker else 0.006)),
            'liquidity_indicator': 'M' if is_maker else 'T',
            'trade_time': '2025-01-01T00:00:00Z'
        })

        # Update order status
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'FILLED'

    # =========================================================================
    # Schema Validation Helper
    # =========================================================================

    def _validate_response(self, schema_class, data: dict, method_name: str):
        """
        Validate response data against Pydantic schema.

        Logs a warning if validation fails but doesn't raise an exception.
        This allows tests to continue while catching schema mismatches.

        Args:
            schema_class: Pydantic model class to validate against.
            data: Response data to validate.
            method_name: API method name for logging.
        """
        if not SCHEMAS_AVAILABLE:
            return

        try:
            schema_class(**data)
            logging.debug(f"{method_name}: Response validation passed")
        except Exception as e:
            logging.warning(
                f"{method_name}: Response validation failed - "
                f"mock may not match real API structure. Error: {e}"
            )

    # =========================================================================
    # APIClient Interface Implementation
    # =========================================================================

    def get_accounts(self, cursor: Optional[str] = None, limit: int = 250) -> Any:
        """Get account information."""
        accounts_list = [Mock(**data) for data in self.accounts.values()]

        # Validate response structure
        self._validate_response(
            AccountsResponse,
            {
                'accounts': list(self.accounts.values()),
                'cursor': '',
                'has_next': False
            },
            'get_accounts'
        )

        return Mock(
            accounts=accounts_list,
            cursor='',
            has_next=False
        )

    def get_product(self, product_id: str) -> dict:
        """Get product information."""
        if product_id not in self.products:
            raise ValueError(f"Product {product_id} not found")
        return self.products[product_id]

    def get_products(self) -> dict:
        """Get all available products."""
        return {'products': list(self.products.values())}

    def get_product_book(self, product_id: str, limit: int = 1) -> dict:
        """Get product order book."""
        if product_id not in self.order_books:
            # Generate default order book if not exists
            if product_id in self.products:
                price = float(self.products[product_id]['price'])
                self.order_books[product_id] = {
                    'pricebook': {
                        'bids': [{'price': str(price - 5), 'size': '1.0'}],
                        'asks': [{'price': str(price + 5), 'size': '1.0'}]
                    }
                }
            else:
                raise ValueError(f"Product {product_id} not found")

        return self.order_books[product_id]

    def limit_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str
    ) -> Any:
        """Place a limit order (Good-Til-Cancelled)."""
        order_id = f"mock-order-{len(self.orders) + 1}"

        self.orders[order_id] = {
            'order_id': order_id,
            'client_order_id': client_order_id,
            'product_id': product_id,
            'side': side,
            'base_size': base_size,
            'limit_price': limit_price,
            'status': 'OPEN',
            'created_time': '2025-01-01T00:00:00Z'
        }

        # Return success response
        return Mock(
            success=True,
            success_response=Mock(order_id=order_id),
            to_dict=lambda: {'success_response': {'order_id': order_id}}
        )

    def get_fills(self, order_ids: List[str]) -> Any:
        """Get order fills."""
        all_fills = []
        for order_id in order_ids:
            if order_id in self.fills:
                for fill in self.fills[order_id]:
                    all_fills.append(Mock(**fill))

        return Mock(fills=all_fills)

    def list_orders(self, order_ids: Optional[List[str]] = None) -> Any:
        """List orders."""
        if order_ids:
            orders = [self.orders[oid] for oid in order_ids if oid in self.orders]
        else:
            orders = list(self.orders.values())

        return Mock(orders=[Mock(**order) for order in orders])

    def cancel_orders(self, order_ids: List[str]) -> Any:
        """Cancel orders."""
        results = []
        for order_id in order_ids:
            if order_id in self.orders:
                self.orders[order_id]['status'] = 'CANCELLED'
                results.append({'order_id': order_id, 'success': True})
            else:
                results.append({'order_id': order_id, 'success': False, 'error': 'Not found'})

        return Mock(results=results)

    def get_transaction_summary(self) -> Any:
        """Get transaction summary including fee tiers."""
        return Mock(
            fee_tier={
                'maker_fee_rate': '0.004',
                'taker_fee_rate': '0.006',
                'volume_30d': '100000'
            }
        )

    # =========================================================================
    # Test Utility Methods
    # =========================================================================

    def reset(self):
        """Reset mock to initial state."""
        self.accounts.clear()
        self.products.clear()
        self.orders.clear()
        self.fills.clear()
        self.order_books.clear()
        self._setup_default_data()
        logging.debug("MockCoinbaseAPI reset to initial state")

    def get_order_count(self) -> int:
        """Get number of orders placed."""
        return len(self.orders)

    def get_fill_count(self) -> int:
        """Get total number of fills across all orders."""
        return sum(len(fills) for fills in self.fills.values())
