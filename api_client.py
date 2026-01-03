"""
API client abstraction layer.

This module provides an abstract interface for the Coinbase API client,
enabling dependency injection and making the code testable with mock clients.

Usage:
    # Production usage
    from api_client import CoinbaseAPIClient
    client = CoinbaseAPIClient(api_key="...", api_secret="...")

    # Testing usage
    from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
    client = MockCoinbaseAPI()

    # Both can be used interchangeably
    accounts = client.get_accounts()
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Any
import logging


class APIClient(ABC):
    """
    Abstract interface for Coinbase API operations.

    This abstract class defines the contract for all API operations
    used by the trading terminal. Both the production CoinbaseAPIClient
    and test MockCoinbaseAPI implement this interface.

    Implementing this interface allows:
    - Dependency injection in TradingTerminal
    - Easy mocking for unit tests
    - Potential for alternative API implementations
    """

    @abstractmethod
    def get_accounts(self, cursor: Optional[str] = None, limit: int = 250) -> Any:
        """
        Get account information with pagination support.

        Args:
            cursor: Pagination cursor for next page.
            limit: Maximum number of accounts to return.

        Returns:
            Response object with 'accounts' list, 'cursor', and 'has_next'.
        """
        pass

    @abstractmethod
    def get_product(self, product_id: str) -> dict:
        """
        Get product information.

        Args:
            product_id: Product identifier (e.g., 'BTC-USD').

        Returns:
            Dictionary with product details including:
            - product_id
            - price
            - base_min_size, base_max_size
            - base_increment, quote_increment
        """
        pass

    @abstractmethod
    def get_products(self) -> dict:
        """
        Get all available products.

        Returns:
            Dictionary with 'products' list containing all available products.
        """
        pass

    @abstractmethod
    def get_product_book(self, product_id: str, limit: int = 1) -> dict:
        """
        Get product order book.

        Args:
            product_id: Product identifier.
            limit: Number of price levels to return.

        Returns:
            Dictionary with 'pricebook' containing 'bids' and 'asks' lists.
        """
        pass

    @abstractmethod
    def limit_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str
    ) -> Any:
        """
        Place a limit order (Good-Til-Cancelled).

        Args:
            client_order_id: Client-generated order ID for idempotency.
            product_id: Product identifier.
            side: Order side ('BUY' or 'SELL').
            base_size: Order size in base currency (as string).
            limit_price: Limit price (as string).

        Returns:
            Response object with order details or error information.
        """
        pass

    @abstractmethod
    def get_fills(self, order_ids: List[str]) -> Any:
        """
        Get order fills.

        Args:
            order_ids: List of order IDs to get fills for.

        Returns:
            Response object with 'fills' list.
        """
        pass

    @abstractmethod
    def list_orders(self, order_ids: Optional[List[str]] = None) -> Any:
        """
        List orders.

        Args:
            order_ids: Optional list of specific order IDs to fetch.

        Returns:
            Response object with 'orders' list.
        """
        pass

    @abstractmethod
    def cancel_orders(self, order_ids: List[str]) -> Any:
        """
        Cancel orders.

        Args:
            order_ids: List of order IDs to cancel.

        Returns:
            Response object with 'results' list indicating success/failure.
        """
        pass

    @abstractmethod
    def get_transaction_summary(self) -> Any:
        """
        Get transaction summary including fee tiers.

        Returns:
            Response object with 'fee_tier' containing maker/taker rates.
        """
        pass

    @abstractmethod
    def stop_limit_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """
        Place a stop-limit order (Good-Til-Cancelled).

        This method handles both stop-loss and take-profit orders using
        the stop_direction parameter.

        Args:
            client_order_id: Unique order identifier
            product_id: Trading pair (e.g., "BTC-USD")
            side: "BUY" or "SELL"
            base_size: Order size as string
            limit_price: Execution price after trigger
            stop_price: Trigger price
            stop_direction: "STOP_DIRECTION_STOP_UP" or "STOP_DIRECTION_STOP_DOWN"

        Returns:
            CreateOrderResponse object with order details
        """
        pass

    @abstractmethod
    def stop_limit_order_gtc_buy(
        self,
        client_order_id: str,
        product_id: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """
        Place a BUY stop-limit order (convenience method).

        Args:
            client_order_id: Unique order identifier
            product_id: Trading pair
            base_size: Order size as string
            limit_price: Execution price after trigger
            stop_price: Trigger price
            stop_direction: Stop direction

        Returns:
            CreateOrderResponse object
        """
        pass

    @abstractmethod
    def stop_limit_order_gtc_sell(
        self,
        client_order_id: str,
        product_id: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """
        Place a SELL stop-limit order (convenience method).

        Args:
            client_order_id: Unique order identifier
            product_id: Trading pair
            base_size: Order size as string
            limit_price: Execution price after trigger
            stop_price: Trigger price
            stop_direction: Stop direction

        Returns:
            CreateOrderResponse object
        """
        pass

    @abstractmethod
    def trigger_bracket_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
        stop_trigger_price: str
    ) -> Any:
        """
        Place a bracket order (TP/SL for existing position).

        NOTE: This creates TP/SL for an EXISTING position.
        For entry + TP/SL, use create_order() with attached_order_configuration.

        Args:
            client_order_id: Unique order identifier
            product_id: Trading pair
            side: "BUY" or "SELL" (side of the position)
            base_size: Position size as string
            limit_price: Take-profit price
            stop_trigger_price: Stop-loss trigger price

        Returns:
            CreateOrderResponse object
        """
        pass

    @abstractmethod
    def create_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        order_configuration: dict,
        attached_order_configuration: Optional[dict] = None
    ) -> Any:
        """
        Generic order creation with optional attached TP/SL bracket.

        Example for entry + TP/SL:
            order_configuration = {
                "limit_limit_gtc": {
                    "baseSize": "0.01",
                    "limitPrice": "50000"
                }
            }
            attached_order_configuration = {
                "trigger_bracket_gtc": {
                    "limit_price": "55000",      # Take profit
                    "stop_trigger_price": "48000"  # Stop loss
                }
            }

        Args:
            client_order_id: Unique order identifier
            product_id: Trading pair
            side: "BUY" or "SELL"
            order_configuration: Main order config dict
            attached_order_configuration: Optional TP/SL bracket config

        Returns:
            CreateOrderResponse object
        """
        pass


class CoinbaseAPIClient(APIClient):
    """
    Production implementation of APIClient using Coinbase SDK.

    This class wraps the official Coinbase RESTClient and implements
    the APIClient interface for use in production.

    Example:
        from api_client import CoinbaseAPIClient

        client = CoinbaseAPIClient(
            api_key="organizations/.../apiKeys/...",
            api_secret="..."
        )

        accounts = client.get_accounts()
        for account in accounts.accounts:
            print(f"{account.currency}: {account.available_balance}")
    """

    def __init__(self, api_key: str, api_secret: str,
                 base_url: str = 'api.coinbase.com',
                 verbose: bool = False):
        """
        Initialize the Coinbase API client.

        Args:
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            base_url: Base URL for API (production or sandbox).
                     Default: 'api.coinbase.com' (production)
                     Sandbox: 'api-sandbox.coinbase.com'
            verbose: Enable verbose logging in the SDK.
        """
        from coinbase.rest import RESTClient

        self._client = RESTClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            verbose=verbose
        )
        logging.debug(f"CoinbaseAPIClient initialized with base_url={base_url}")

    def get_accounts(self, cursor: Optional[str] = None, limit: int = 250) -> Any:
        """Get account information with pagination support."""
        return self._client.get_accounts(cursor=cursor, limit=limit)

    def get_product(self, product_id: str) -> dict:
        """Get product information."""
        return self._client.get_product(product_id)

    def get_products(self) -> dict:
        """Get all available products."""
        return self._client.get_products()

    def get_product_book(self, product_id: str, limit: int = 1) -> dict:
        """Get product order book."""
        return self._client.get_product_book(product_id, limit=limit)

    def limit_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str
    ) -> Any:
        """Place a limit order (Good-Til-Cancelled)."""
        return self._client.limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
            limit_price=limit_price
        )

    def get_fills(self, order_ids: List[str]) -> Any:
        """Get order fills."""
        return self._client.get_fills(order_ids=order_ids)

    def list_orders(self, order_ids: Optional[List[str]] = None) -> Any:
        """List orders."""
        if order_ids:
            return self._client.list_orders(order_ids=order_ids)
        return self._client.list_orders()

    def cancel_orders(self, order_ids: List[str]) -> Any:
        """Cancel orders."""
        return self._client.cancel_orders(order_ids)

    def get_transaction_summary(self) -> Any:
        """Get transaction summary including fee tiers."""
        return self._client.get_transaction_summary()

    def stop_limit_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """Place a stop-limit order (Good-Til-Cancelled)."""
        return self._client.stop_limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
            limit_price=limit_price,
            stop_price=stop_price,
            stop_direction=stop_direction
        )

    def stop_limit_order_gtc_buy(
        self,
        client_order_id: str,
        product_id: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """Place a BUY stop-limit order (convenience method)."""
        return self._client.stop_limit_order_gtc_buy(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=base_size,
            limit_price=limit_price,
            stop_price=stop_price,
            stop_direction=stop_direction
        )

    def stop_limit_order_gtc_sell(
        self,
        client_order_id: str,
        product_id: str,
        base_size: str,
        limit_price: str,
        stop_price: str,
        stop_direction: str
    ) -> Any:
        """Place a SELL stop-limit order (convenience method)."""
        return self._client.stop_limit_order_gtc_sell(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=base_size,
            limit_price=limit_price,
            stop_price=stop_price,
            stop_direction=stop_direction
        )

    def trigger_bracket_order_gtc(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
        stop_trigger_price: str
    ) -> Any:
        """Place a bracket order (TP/SL for existing position)."""
        return self._client.trigger_bracket_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
            limit_price=limit_price,
            stop_trigger_price=stop_trigger_price
        )

    def create_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        order_configuration: dict,
        attached_order_configuration: Optional[dict] = None
    ) -> Any:
        """Generic order creation with optional attached TP/SL bracket."""
        if attached_order_configuration:
            return self._client.create_order(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                order_configuration=order_configuration,
                attached_order_configuration=attached_order_configuration
            )
        else:
            return self._client.create_order(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                order_configuration=order_configuration
            )


class APIClientFactory:
    """
    Factory for creating API client instances.

    This factory simplifies client creation and provides a single point
    for configuration-based client instantiation.

    Example:
        from api_client import APIClientFactory

        # Create from config
        client = APIClientFactory.create_from_config()

        # Create for testing
        client = APIClientFactory.create_mock()
    """

    @staticmethod
    def create_from_config() -> CoinbaseAPIClient:
        """
        Create a CoinbaseAPIClient using configuration.

        Loads API credentials and base URL from the Config class.

        Returns:
            Configured CoinbaseAPIClient instance.

        Raises:
            ConfigurationError: If credentials are not available.
        """
        from config import Config

        config = Config()
        return CoinbaseAPIClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            base_url=config.base_url,
            verbose=config.verbose
        )

    @staticmethod
    def create(api_key: str, api_secret: str,
               base_url: str = 'api.coinbase.com',
               verbose: bool = False) -> CoinbaseAPIClient:
        """
        Create a CoinbaseAPIClient with explicit credentials.

        Args:
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            base_url: Base URL for API (default: production).
            verbose: Enable verbose logging.

        Returns:
            Configured CoinbaseAPIClient instance.
        """
        return CoinbaseAPIClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            verbose=verbose
        )

    @staticmethod
    def create_mock() -> 'APIClient':
        """
        Create a mock API client for testing.

        Returns:
            Mock API client instance.

        Note:
            This method imports from tests.mocks, which should only
            be available in the test environment.
        """
        from tests.mocks.mock_coinbase_api import MockCoinbaseAPI
        return MockCoinbaseAPI()
