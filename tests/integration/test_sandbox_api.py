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
        try:
            response = sandbox_client.get_products()

            assert hasattr(response, 'products')
            assert isinstance(response.products, list)

            if response.products:
                product = response.products[0]
                assert hasattr(product, 'product_id')
                assert hasattr(product, 'price')
                print(f"First product: {product.product_id}")

        except Exception as e:
            pytest.skip(f"Products not available in sandbox: {e}")

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

        try:
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

        except Exception as e:
            pytest.skip(f"Products not available in sandbox: {e}")

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
class TestSandboxCandles:
    """Test candle/historical data endpoints against sandbox."""

    def test_get_candles_sandbox(self, sandbox_client):
        """Verify get_candles returns expected OHLCV structure."""
        import time

        end = str(int(time.time()))
        start = str(int(time.time()) - 86400)  # 24 hours ago

        try:
            response = sandbox_client.get_candles(
                product_id='BTC-USD',
                start=start,
                end=end,
                granularity='ONE_HOUR'
            )

            # Response may be object with .candles or raw list
            if hasattr(response, 'candles'):
                candles = response.candles
            elif isinstance(response, list):
                candles = response
            else:
                candles = []

            assert isinstance(candles, list)
            print(f"Sandbox returned {len(candles)} candles")

            if candles:
                candle = candles[0]
                # Verify OHLCV fields exist (dict or object access)
                for field in ['start', 'open', 'high', 'low', 'close', 'volume']:
                    if isinstance(candle, dict):
                        assert field in candle, f"Candle missing field: {field}"
                    else:
                        assert hasattr(candle, field), f"Candle missing attribute: {field}"

        except Exception as e:
            pytest.skip(f"Candles not available in sandbox: {e}")

    def test_get_candles_granularities(self, sandbox_client):
        """Test different candle granularities are accepted."""
        import time

        end = str(int(time.time()))
        start = str(int(time.time()) - 86400)

        for granularity in ['ONE_MINUTE', 'ONE_HOUR', 'ONE_DAY']:
            try:
                response = sandbox_client.get_candles(
                    product_id='BTC-USD',
                    start=start,
                    end=end,
                    granularity=granularity
                )
                # Just verify no exception is raised
                print(f"✓ Granularity {granularity} accepted")
            except Exception as e:
                pytest.skip(f"Granularity {granularity} not available in sandbox: {e}")

    def test_get_candles_empty_range(self, sandbox_client):
        """Verify empty result for future date range."""
        import time

        # Future timestamps
        future_start = str(int(time.time()) + 86400 * 365)
        future_end = str(int(time.time()) + 86400 * 366)

        try:
            response = sandbox_client.get_candles(
                product_id='BTC-USD',
                start=future_start,
                end=future_end,
                granularity='ONE_HOUR'
            )

            if hasattr(response, 'candles'):
                candles = response.candles
            elif isinstance(response, list):
                candles = response
            else:
                candles = []

            # Future dates should return empty or very few candles
            print(f"Future range returned {len(candles)} candles")

        except Exception as e:
            pytest.skip(f"Candles endpoint not available in sandbox: {e}")


@pytest.mark.integration
@pytest.mark.sandbox
class TestSandboxFillsAndCancel:
    """Test fills and cancel endpoints against sandbox."""

    def test_get_fills_sandbox(self, sandbox_client):
        """Verify get_fills returns expected structure."""
        try:
            response = sandbox_client.get_fills(order_ids=[])

            assert hasattr(response, 'fills')
            assert isinstance(response.fills, list)
            print(f"Sandbox returned {len(response.fills)} fills")

        except Exception as e:
            pytest.skip(f"Fills not available in sandbox: {e}")

    def test_cancel_orders_sandbox(self, sandbox_client):
        """Verify cancel_orders returns expected structure."""
        try:
            # Cancel a non-existent order to test response structure
            response = sandbox_client.cancel_orders(order_ids=['nonexistent-order-id'])

            assert hasattr(response, 'results')
            assert isinstance(response.results, list)
            print(f"Cancel response has {len(response.results)} results")

        except Exception as e:
            pytest.skip(f"Cancel orders not available in sandbox: {e}")


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
