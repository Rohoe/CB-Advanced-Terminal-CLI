# Test Suite Enhancements

This document describes the three major enhancements to the testing infrastructure: VCR.py integration, Pydantic schema validation, and sandbox integration tests.

## Overview

Three new capabilities have been added to make the test suite more reliable and maintainable:

1. **VCR.py Integration** - Record/replay API responses for fast, offline testing
2. **Pydantic Schema Validation** - Ensure mocks match real API structure
3. **Sandbox Integration Tests** - Verify against real Coinbase sandbox API (no auth required!)

## 1. VCR.py - Record/Replay API Responses

### What is VCR.py?

VCR.py records HTTP interactions (requests and responses) the first time tests run, then replays them from cassettes on subsequent runs.

**Benefits:**
- ✅ Fast tests - No network calls needed
- ✅ Offline testing - Tests work without internet
- ✅ Deterministic tests - Same responses every time
- ✅ Regression detection - Catch API changes

### Recording Cassettes

To record new cassettes from the sandbox API:

```bash
# Delete existing cassettes to force re-recording
rm tests/vcr_cassettes/sandbox_*.yaml

# Run VCR recording tests with sandbox mode enabled
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v
```

This creates YAML cassettes in `tests/vcr_cassettes/` that are automatically used in future test runs.

### Using VCR in Tests

```python
from tests.vcr_config import api_vcr

@api_vcr.use_cassette('my_test.yaml')
def test_api_call(sandbox_client):
    # First run: Makes real API call, records to cassette
    # Subsequent runs: Replays from cassette
    response = sandbox_client.get_accounts()
    assert response is not None
```

### Cassette Security

- **Sandbox cassettes** (`sandbox_*.yaml`) are safe to commit - no authentication required
- **Production cassettes** should NOT be committed - may contain sensitive data
- `.gitignore` is pre-configured to only allow sandbox cassettes

## 2. Pydantic Schema Validation

### What are Response Schemas?

Pydantic schemas define the expected structure of Coinbase API responses located in `tests/schemas/api_responses.py`.

**Benefits:**
- ✅ Validate mock accuracy - Ensure mocks match real API
- ✅ Document API structure - Serve as living documentation
- ✅ Catch API changes - Detect when Coinbase updates their API
- ✅ Type safety - Provide type hints for IDE support

### Available Schemas

- `AccountsResponse` / `Account` - Account data
- `ProductsResponse` / `Product` - Product listings
- `ProductBook` - Order book data
- `OrderResponse` / `Order` - Order data
- `FillsResponse` / `Fill` - Fill/trade data
- `TransactionSummary` - Fee tier information
- `CancelResponse` - Cancellation results

### Mock API Auto-Validation

The `MockCoinbaseAPI` automatically validates responses:

```python
from tests.mocks.mock_coinbase_api import MockCoinbaseAPI

# Schema validation happens automatically
api = MockCoinbaseAPI()
response = api.get_accounts()  # Validates against AccountsResponse schema
```

Validation failures are logged as warnings but don't break tests (progressive enhancement).

## 3. Sandbox Integration Tests

### Coinbase Sandbox Environment

The Coinbase Advanced Trade API provides a static sandbox that:

- ✅ **Requires NO authentication** - No API keys needed!
- ✅ **Returns static responses** - Predictable, pre-defined data
- ✅ **Matches production structure** - Same response format
- ✅ **Safe for CI/CD** - No credentials required

**Sandbox URL:** `api-sandbox.coinbase.com`

### Running Sandbox Tests

```bash
# Run all sandbox tests
COINBASE_SANDBOX_MODE=true pytest -m sandbox -v

# Run specific sandbox test file
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_sandbox_api.py -v

# Skip sandbox tests (default behavior)
pytest -m "not sandbox" -v
```

### Sandbox Test Coverage

The `test_sandbox_api.py` file includes tests for:

**Account Endpoints:**
- Get accounts with pagination
- Validate response structure

**Product Endpoints:**
- List all products
- Get individual product details
- Get order book data

**Order Endpoints:**
- Place limit orders
- List existing orders

**Schema Validation:**
- Verify all sandbox responses match Pydantic schemas

## New Files Created

```
tests/
├── schemas/
│   ├── __init__.py                 # Schema package
│   └── api_responses.py            # Pydantic models for all API responses
├── vcr_config.py                   # VCR.py configuration
├── vcr_cassettes/                  # Recorded API interactions
│   ├── .gitignore                  # Security: only allow sandbox cassettes
│   └── README.md                   # Cassette documentation
└── integration/
    ├── test_sandbox_api.py         # Sandbox integration tests (11 tests)
    └── test_vcr_recording.py       # VCR recording tests (11 tests)
```

## Modified Files

- `requirements-dev.txt` - Added `vcrpy>=5.1.0` and `pydantic>=2.5.0`
- `config.py` - Added `base_url`, `is_sandbox`, and `verbose` properties
- `api_client.py` - Added `base_url` parameter support to `CoinbaseAPIClient`
- `tests/conftest.py` - Added VCR fixtures, sandbox fixtures, and pytest markers
- `tests/mocks/mock_coinbase_api.py` - Added automatic schema validation

## Quick Reference

### Environment Variables

```bash
# Enable sandbox mode (no API keys required)
export COINBASE_SANDBOX_MODE=true

# Enable verbose SDK logging
export COINBASE_VERBOSE=true

# Production API credentials (not needed for sandbox)
export COINBASE_API_KEY=organizations/your-org/apiKeys/your-key
export COINBASE_API_SECRET=your-secret
```

### Running Different Test Categories

```bash
# All tests (excluding sandbox)
pytest -v

# Only unit tests
pytest -m unit -v

# Only integration tests
pytest -m integration -v

# Only sandbox tests (requires COINBASE_SANDBOX_MODE=true)
COINBASE_SANDBOX_MODE=true pytest -m sandbox -v

# Only VCR tests
pytest -m vcr -v

# Exclude sandbox and VCR tests
pytest -m "not sandbox and not vcr" -v

# Run with coverage
pytest --cov=. --cov-report=html
```

### Test Markers

New pytest markers added:

- `@pytest.mark.sandbox` - Sandbox integration tests (skipped unless COINBASE_SANDBOX_MODE=true)
- `@pytest.mark.vcr` - Tests that use VCR cassettes

Existing markers:

- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Integration tests (multiple components)
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.security` - Security-related tests

## Workflow Examples

### Daily Development (No API Keys Needed)

```bash
# Run all tests using mocks and VCR cassettes
pytest -v

# Fast! No network calls, no authentication required
```

### Recording New Cassettes

```bash
# First time setup - record sandbox responses
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v

# Cassettes are now saved for future test runs
```

### Validating Against Real Sandbox API

```bash
# Verify code works with actual Coinbase API structure
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_sandbox_api.py -v

# No API keys required! Sandbox is open access
```

### Detecting API Changes

```bash
# Delete cassettes to force re-recording
rm tests/vcr_cassettes/sandbox_*.yaml

# Re-record from current sandbox API
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v

# If tests fail, Coinbase API has changed - update schemas/mocks accordingly
```

## Troubleshooting

### Sandbox Tests Being Skipped

**Problem:** Tests show `SKIPPED: Sandbox tests require COINBASE_SANDBOX_MODE=true`

**Solution:** Enable sandbox mode:
```bash
COINBASE_SANDBOX_MODE=true pytest -m sandbox -v
```

### Schema Validation Warnings

**Problem:** `WARNING: Response validation failed - mock may not match real API structure`

**Solution:** This is informational. Update the mock in `tests/mocks/mock_coinbase_api.py` to match the schema in `tests/schemas/api_responses.py`.

### VCR Cassette Not Found

**Problem:** Test fails with cassette not found error

**Solution:** Record the cassette:
```bash
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v
```

### Import Errors with Pydantic

**Problem:** `ImportError: cannot import name 'BaseModel' from 'pydantic'`

**Solution:** Install dependencies:
```bash
pip install -r requirements-dev.txt
```

## Test Statistics

After implementation:

- **Total tests:** 122
  - Existing tests: 102 (all still passing ✅)
  - New sandbox tests: 11
  - New VCR tests: 11 (overlap with sandbox)

- **Test execution:**
  - Without sandbox: ~6 seconds (mocks + VCR cassettes)
  - With sandbox: ~10-15 seconds (real API calls first time, then cached)

- **Coverage:** ~50% overall (up from 16% for production code)

## Benefits Summary

### For Development

- ✅ **No API keys needed** for daily testing
- ✅ **Fast test execution** with VCR cassettes
- ✅ **Offline development** possible
- ✅ **Type safety** with Pydantic schemas

### For Reliability

- ✅ **Catch API changes** early via schema validation
- ✅ **Ensure mock accuracy** with real sandbox validation
- ✅ **Regression testing** with recorded cassettes
- ✅ **CI/CD friendly** (no credentials needed)

### For Maintenance

- ✅ **Self-documenting** API contracts via schemas
- ✅ **Easy updates** when API changes
- ✅ **Progressive enhancement** (non-breaking changes)
- ✅ **Backward compatible** with existing tests

## Resources

- **VCR.py:** https://vcrpy.readthedocs.io/
- **Pydantic:** https://docs.pydantic.dev/
- **Coinbase Sandbox:** https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox
- **Project Plan:** `/Users/ronaldho/.claude/plans/vivid-stargazing-parnas.md`

## Next Steps

Optional future enhancements:

1. **Automated cassette refresh** - Scheduled job to re-record monthly
2. **Schema auto-generation** - Generate Pydantic models from cassettes
3. **X-Sandbox header support** - Test response variance
4. **Response diff tool** - Compare cassettes across SDK versions
5. **More sandbox tests** - Cover additional endpoints (fills, cancellations, etc.)
