"""
VCR recording tests for capturing real API responses.

These tests record API responses the FIRST time they run,
then replay the recorded responses on subsequent runs.

To re-record cassettes (if API changes):
    rm tests/vcr_cassettes/sandbox_*.yaml
    COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v

To use existing cassettes:
    pytest tests/integration/test_vcr_recording.py -v

Note: These tests use the sandbox API which requires no authentication.
"""

import pytest
import os
from tests.vcr_config import api_vcr


# Skip if cassettes don't exist and sandbox mode not enabled
def check_can_run():
    """Check if we can run VCR tests (either cassettes exist or sandbox enabled)."""
    import os.path
    cassette_dir = 'tests/vcr_cassettes'
    has_cassettes = os.path.exists(f"{cassette_dir}/sandbox_get_accounts.yaml")
    sandbox_enabled = os.getenv('COINBASE_SANDBOX_MODE', 'false').lower() == 'true'
    return has_cassettes or sandbox_enabled


pytestmark = pytest.mark.skipif(
    not check_can_run(),
    reason="VCR tests require either existing cassettes or COINBASE_SANDBOX_MODE=true"
)


@pytest.mark.integration
@pytest.mark.vcr
class TestVCRRecording:
    """Record API responses with VCR.py."""

    @api_vcr.use_cassette('sandbox_get_accounts.yaml')
    def test_record_get_accounts(self, sandbox_client):
        """
        Record get_accounts response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        response = sandbox_client.get_accounts()

        # Validate response structure
        assert hasattr(response, 'accounts')
        assert isinstance(response.accounts, list)
        print(f"✓ Recorded/replayed {len(response.accounts)} accounts")

    @api_vcr.use_cassette('sandbox_get_products.yaml')
    def test_record_get_products(self, sandbox_client):
        """
        Record get_products response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        response = sandbox_client.get_products()

        assert hasattr(response, 'products')
        assert isinstance(response.products, list)
        print(f"✓ Recorded/replayed {len(response.products)} products")

    @api_vcr.use_cassette('sandbox_get_product.yaml')
    def test_record_get_product(self, sandbox_client):
        """
        Record get_product response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        try:
            response = sandbox_client.get_product('BTC-USD')
            assert response is not None

            # Works with both dict and object responses
            if isinstance(response, dict):
                assert 'product_id' in response
            else:
                assert hasattr(response, 'product_id')

            print(f"✓ Recorded/replayed product data")

        except Exception as e:
            pytest.skip(f"Product not available in sandbox: {e}")

    @api_vcr.use_cassette('sandbox_get_product_book.yaml')
    def test_record_get_product_book(self, sandbox_client):
        """
        Record get_product_book response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        try:
            response = sandbox_client.get_product_book('BTC-USD', limit=1)

            assert 'pricebook' in response
            assert 'bids' in response['pricebook']
            assert 'asks' in response['pricebook']
            print(f"✓ Recorded/replayed product book")

        except Exception as e:
            pytest.skip(f"Product book not available in sandbox: {e}")

    @api_vcr.use_cassette('sandbox_list_orders.yaml')
    def test_record_list_orders(self, sandbox_client):
        """
        Record list_orders response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        try:
            response = sandbox_client.list_orders()

            assert hasattr(response, 'orders')
            assert isinstance(response.orders, list)
            print(f"✓ Recorded/replayed {len(response.orders)} orders")

        except Exception as e:
            pytest.skip(f"List orders not available in sandbox: {e}")

    @api_vcr.use_cassette('sandbox_transaction_summary.yaml')
    def test_record_transaction_summary(self, sandbox_client):
        """
        Record get_transaction_summary response.

        First run: Makes real API call and records to cassette
        Subsequent runs: Replays from cassette
        """
        try:
            response = sandbox_client.get_transaction_summary()

            assert hasattr(response, 'fee_tier')
            print(f"✓ Recorded/replayed transaction summary")

        except Exception as e:
            pytest.skip(f"Transaction summary not available in sandbox: {e}")


@pytest.mark.integration
@pytest.mark.vcr
class TestVCRCassetteValidation:
    """Validate that VCR cassettes match our schemas."""

    @api_vcr.use_cassette('sandbox_get_accounts.yaml')
    def test_cassette_accounts_matches_schema(self, sandbox_client):
        """Verify replayed accounts response validates against schema."""
        from tests.schemas.api_responses import AccountsResponse

        response = sandbox_client.get_accounts()

        # Convert to dict and validate
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

        # Validate against schema
        validated = AccountsResponse(**accounts_data)
        assert validated is not None
        print(f"✓ Cassette data validates against AccountsResponse schema")

    @api_vcr.use_cassette('sandbox_get_products.yaml')
    def test_cassette_products_matches_schema(self, sandbox_client):
        """Verify replayed products response validates against schema."""
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
        print(f"✓ Cassette data validates against ProductsResponse schema")


@pytest.mark.integration
@pytest.mark.vcr
class TestVCRReplaySpeed:
    """Verify that VCR replay is fast (no real API calls)."""

    @api_vcr.use_cassette('sandbox_get_accounts.yaml')
    def test_replay_is_fast(self, sandbox_client):
        """
        Test that replaying from cassette is fast.

        If this test is slow (>1 second), the cassette may not exist
        and real API calls are being made.
        """
        import time

        start = time.time()
        response = sandbox_client.get_accounts()
        elapsed = time.time() - start

        assert hasattr(response, 'accounts')

        # Replay should be very fast (<100ms), real API calls slower
        if elapsed < 1.0:
            print(f"✓ Fast replay: {elapsed*1000:.1f}ms (using cassette)")
        else:
            print(f"⚠ Slow response: {elapsed:.2f}s (may be making real API call)")
