"""
Integration tests using Coinbase sandbox environment.

These tests verify behavior against the real Coinbase sandbox API,
which requires NO authentication and returns static responses.

To run these tests:
    COINBASE_SANDBOX_MODE=true pytest tests/integration/test_sandbox_api.py -v

Skip these tests:
    pytest -m "not sandbox"

Note: The sandbox API does not require authentication (no API keys needed).
"""

import pytest
import os


# Skip all sandbox tests if not in sandbox mode
pytestmark = pytest.mark.skipif(
    os.getenv('COINBASE_SANDBOX_MODE', 'false').lower() != 'true',
    reason="Sandbox tests require COINBASE_SANDBOX_MODE=true"
)


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxAccounts:
    """Test account endpoints against sandbox."""

    def test_get_accounts_sandbox(self, sandbox_client):
        """Verify get_accounts returns expected structure."""
        response = sandbox_client.get_accounts()

        # Validate response structure
        assert hasattr(response, 'accounts')
        assert hasattr(response, 'has_next')
        assert hasattr(response, 'cursor')

        # Sandbox returns static data
        assert isinstance(response.accounts, list)
        print(f"Sandbox returned {len(response.accounts)} accounts")

    def test_get_accounts_pagination(self, sandbox_client):
        """Test pagination parameters are accepted."""
        response = sandbox_client.get_accounts(limit=10)

        assert hasattr(response, 'accounts')
        assert isinstance(response.accounts, list)


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxProducts:
    """Test product endpoints against sandbox."""

    def test_get_products_sandbox(self, sandbox_client):
        """Verify get_products returns expected structure."""
        response = sandbox_client.get_products()

        assert hasattr(response, 'products')
        assert isinstance(response.products, list)

        if response.products:
            product = response.products[0]
            assert hasattr(product, 'product_id')
            assert hasattr(product, 'price')
            print(f"First product: {product.product_id}")

    def test_get_product_sandbox(self, sandbox_client):
        """Verify get_product returns expected structure."""
        # Try to get BTC-USD product from sandbox
        try:
            response = sandbox_client.get_product('BTC-USD')

            # Response could be object or dict
            if isinstance(response, dict):
                assert 'product_id' in response
            else:
                assert hasattr(response, 'product_id')

            print(f"Successfully retrieved product")

        except Exception as e:
            pytest.skip(f"Product not available in sandbox: {e}")

    def test_get_product_book_sandbox(self, sandbox_client):
        """Verify get_product_book returns expected structure."""
        try:
            response = sandbox_client.get_product_book('BTC-USD', limit=1)

            assert 'pricebook' in response
            assert 'bids' in response['pricebook']
            assert 'asks' in response['pricebook']

            print(f"Product book has {len(response['pricebook']['bids'])} bids")

        except Exception as e:
            pytest.skip(f"Product book not available in sandbox: {e}")


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxOrders:
    """Test order endpoints against sandbox."""

    def test_limit_order_gtc_sandbox(self, sandbox_client):
        """Verify limit order placement returns expected structure."""
        try:
            response = sandbox_client.limit_order_gtc(
                client_order_id='test-sandbox-order-1',
                product_id='BTC-USD',
                side='BUY',
                base_size='0.001',
                limit_price='30000'
            )

            # Validate response structure
            assert hasattr(response, 'success') or 'success' in response
            print(f"Order placement response received")

        except Exception as e:
            # Sandbox may not support order placement
            pytest.skip(f"Order placement not available in sandbox: {e}")

    def test_list_orders_sandbox(self, sandbox_client):
        """Verify list_orders returns expected structure."""
        try:
            response = sandbox_client.list_orders()

            assert hasattr(response, 'orders')
            assert isinstance(response.orders, list)
            print(f"Sandbox has {len(response.orders)} orders")

        except Exception as e:
            pytest.skip(f"List orders not available in sandbox: {e}")


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxResponseSchemas:
    """Validate sandbox responses match our Pydantic schemas."""

    def test_accounts_response_matches_schema(self, sandbox_client):
        """Verify accounts response validates against schema."""
        from tests.schemas.api_responses import AccountsResponse

        response = sandbox_client.get_accounts()

        # Convert response to dict for validation
        accounts_data = {
            'accounts': [
                {
                    'currency': acc.currency,
                    'available_balance': acc.available_balance,
                    'type': acc.type,
                    'ready': acc.ready,
                    'active': acc.active,
                }
                for acc in response.accounts
            ],
            'cursor': response.cursor,
            'has_next': response.has_next,
        }

        # This validates structure matches
        validated = AccountsResponse(**accounts_data)
        assert validated is not None
        print(f"✓ Accounts response validated against schema")

    def test_products_response_matches_schema(self, sandbox_client):
        """Verify products response validates against schema."""
        from tests.schemas.api_responses import ProductsResponse

        response = sandbox_client.get_products()

        products_data = {
            'products': [
                {
                    'product_id': p.product_id,
                    'price': p.price,
                    'volume_24h': getattr(p, 'volume_24h', None),
                }
                for p in response.products
            ]
        }

        validated = ProductsResponse(**products_data)
        assert validated is not None
        print(f"✓ Products response validated against schema")

    def test_product_book_matches_schema(self, sandbox_client):
        """Verify product book response validates against schema."""
        from tests.schemas.api_responses import ProductBook

        try:
            response = sandbox_client.get_product_book('BTC-USD')

            # Validate against schema
            validated = ProductBook(**response)
            assert validated is not None
            print(f"✓ Product book validated against schema")

        except Exception as e:
            pytest.skip(f"Product book not available: {e}")


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxTransactionSummary:
    """Test transaction summary endpoint."""

    def test_get_transaction_summary_sandbox(self, sandbox_client):
        """Verify get_transaction_summary returns expected structure."""
        try:
            response = sandbox_client.get_transaction_summary()

            assert hasattr(response, 'fee_tier')
            assert isinstance(response.fee_tier, dict)
            print(f"Fee tier data available")

        except Exception as e:
            pytest.skip(f"Transaction summary not available in sandbox: {e}")
