# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based trading terminal for Coinbase Advanced Trade API with limit orders and Time-Weighted Average Price (TWAP) trading strategies.

## Running the Application

**Main execution:**
```bash
# Set API key as environment variable
export COINBASE_API_KEY="organizations/your-org-id/apiKeys/your-key-id"

# Run (will prompt for API secret)
python app.py
```

**Testing:**
```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run only unit tests (fast)
pytest -m unit

# Run specific test file
pytest tests/test_validators.py

# Run specific test
pytest tests/test_validators.py::TestPriceValidation::test_validate_price_valid
```

## Architecture Overview

### Dependency Injection Pattern

The codebase uses dependency injection throughout to enable testability:

**TradingTerminal** (`app.py:115-149`) accepts three injectable dependencies:
- `api_client`: APIClient interface - abstracts Coinbase API calls
- `twap_storage`: TWAPStorage interface - abstracts TWAP order persistence
- `config`: AppConfig - centralized application configuration

This enables testing with mock implementations (no real API calls, in-memory storage).

### Core Abstractions

**APIClient** (`api_client.py:25-166`)
- Abstract interface defining all Coinbase API operations
- Production: `CoinbaseAPIClient` wraps official SDK
- Testing: `MockCoinbaseAPI` (in `tests/mocks/`) provides fake responses
- Factory: `APIClientFactory` simplifies creation

**TWAPStorage** (`storage.py:29-124`)
- Abstract interface for TWAP order persistence
- Production: `FileBasedTWAPStorage` uses JSON files in `twap_data/`
- Testing: `InMemoryTWAPStorage` uses dictionaries
- Factory: `StorageFactory` simplifies creation

**Configuration Hierarchy** (`config_manager.py`)
- `AppConfig`: Main configuration aggregator
- Sub-configs: `RateLimitConfig`, `CacheConfig`, `TWAPConfig`, `RetryConfig`, `DisplayConfig`, `PrecisionConfig`
- All configurable via environment variables (e.g., `RATE_LIMIT_RPS`, `CACHE_ACCOUNT_TTL`)
- `AppConfig.for_testing()` provides fast test configuration

### Key Architectural Components

**Rate Limiter** (`app.py:75-113`)
- Token bucket algorithm prevents API throttling
- Default: 25 requests/second, burst of 50
- ALL API calls MUST call `self.rate_limiter.wait()` before execution
- Thread-safe with internal lock

**Caching System**
- Account cache: 60s TTL (app.py line ~151)
- Order status: 5s TTL
- Fills: 5s TTL
- Product metadata: 300s TTL
- All support `force_refresh=True` parameter

**Order Status Checker Thread** (app.py line ~133)
- Daemon thread monitors order fills in background
- Processes orders from queue in batches of up to 50
- Uses `check_order_fills_batch()` for efficiency
- Thread-safe with `self.order_lock`

**TWAP Execution Flow (legacy):**
1. User input → `get_order_input()` validates parameters
2. Create `TWAPOrder` dataclass with UUID
3. Persist via `twap_storage.save_twap_order()`
4. Loop through slices with timed intervals
5. Each slice: fetch prices → validate → `place_twap_slice()`
6. Background thread monitors fills via order queue
7. Display summary with `display_twap_summary()`

**TWAP Strategy Execution Flow (new):**
1. Create `TWAPStrategy` with parameters, config, and optional API client
2. Call `TWAPExecutor.execute_strategy(strategy)` which uses the `OrderStrategy` protocol:
   - `strategy.calculate_slices()` → uniform timing with optional jitter
   - For each slice: `should_skip_slice()` checks participation rate cap
   - `get_execution_price()` resolves 4 price types (limit/bid/mid/ask)
   - `on_slice_complete()` tracks fills and failures
3. Returns `StrategyResult` with execution metrics

**TWAPStrategy** (`twap_strategy.py`) features:
- Jitter: randomizes interval timing ±jitter_pct (seeded for test reproducibility)
- Participation rate cap: fetches candle volume, skips slice if `slice_size / recent_volume > cap`
- 4 price types: limit (fixed), bid, mid, ask (from order book)

### Data Models

**TWAPOrder** (`twap_tracker.py`)
- Dataclass with complete TWAP execution metadata
- Persisted as JSON: `twap_data/orders/{twap_id}.json`

**OrderFill** (`twap_tracker.py`)
- Individual fill information with maker/taker status
- Persisted as JSON: `twap_data/fills/{twap_id}.json`

**In-memory TWAP tracking:**
```python
self.twap_orders = {
    'twap_id': {
        'total_filled': float,
        'total_value_filled': float,
        'total_fees': float,
        'maker_orders': int,
        'taker_orders': int,
        # ... other metrics
    }
}
self.order_to_twap_map = {'order_id': 'twap_id'}
```

**Trade Journal** (`trade_journal.py`, `trade_journal_tracker.py`)
- `TradeEntry`: Individual trade record with P&L tracking
- `Position`: Aggregate position for an asset with FIFO cost basis
- `DailyPnL`: Daily performance summary
- Persisted as JSON: `trade_journal/trades/{trade_id}.json`, `trade_journal/positions/{product_id}.json`, `trade_journal/daily/{YYYY-MM-DD}.json`
- Automatic trade recording for TWAP fills (via `update_twap_fills()`)
- FIFO matching for realized P&L calculation
- Unrealized P&L calculated on-demand using current market prices

### Validation Layer

**InputValidator** (`validators.py:47-416`)
- Static methods for all input validation
- Custom `ValidationError` with field context
- Validates: price, size, duration, slices, side, product_id, price_type
- Centralizes validation logic; use instead of inline checks

### UI Layer

**ui_helpers.py**
- Color-coded terminal output using colorama
- Helper functions: `success()`, `error()`, `warning()`, `info()`, `highlight()`
- Formatters: `format_currency()`, `format_percentage()`, `format_side()`, `format_status()`
- Print functions: `print_header()`, `print_success()`, `print_error()`, etc.

## Testing Infrastructure

**Test Organization:**
```
tests/
├── conftest.py              # Shared fixtures (mock_api_client, sandbox_client, etc.)
├── test_validators.py       # Unit tests for validators
├── test_rate_limiter.py     # Unit tests for rate limiter
├── test_twap_tracker.py     # Unit tests for TWAP tracker
├── test_trading_terminal.py # Unit tests for terminal
├── integration/             # Integration tests
│   ├── test_twap_execution.py       # TWAP execution with mocks
│   ├── test_order_lifecycle.py      # Order lifecycle with mocks
│   ├── test_portfolio_display.py    # Portfolio display with mocks
│   ├── test_sandbox_api.py          # Sandbox API endpoint tests
│   ├── test_sandbox_modules.py      # Extracted modules vs sandbox API
│   ├── test_scaled_execution.py     # Full scaled order flow (mock-based)
│   ├── test_vwap_execution.py       # Full VWAP order flow (mock-based)
│   └── test_vcr_recording.py        # VCR cassette recording/replay
├── mocks/                   # Mock implementations
│   └── mock_coinbase_api.py
├── schemas/                 # Pydantic API response schemas
│   └── api_responses.py
└── vcr_cassettes/           # Recorded API responses (YAML)
```

**Key Fixtures** (`tests/conftest.py`):
- `mock_api_client`: Pre-configured mock API client
- `mock_twap_storage`: In-memory storage for tests
- `test_app_config`: Fast test configuration
- `sample_twap_order`: Realistic test order data
- `terminal_with_mocks`: Fully configured terminal for integration tests
- `temp_storage_dir`: Auto-cleanup temp directory
- `sandbox_client`: CoinbaseAPIClient pointed at sandbox (no auth, patches SDK auth gate)

**Test Markers:**
- `@pytest.mark.unit`: Fast, isolated tests
- `@pytest.mark.integration`: Multi-component tests
- `@pytest.mark.slow`: Long-running tests
- `@pytest.mark.vcr`: Uses VCR.py for API recording/replay
- `@pytest.mark.sandbox`: Requires sandbox environment (`COINBASE_SANDBOX_MODE=true`)

**Running integration tests:**
```bash
# Mock-based integration tests (no API keys needed, always run)
pytest tests/integration/test_scaled_execution.py tests/integration/test_vwap_execution.py -v

# Sandbox tests (Coinbase sandbox — supports Accounts and Orders only)
COINBASE_SANDBOX_MODE=true pytest -m sandbox -v

# VCR replay tests (uses recorded cassettes, no network needed)
pytest -m vcr -v
```

**Sandbox Limitations:**
The Coinbase Advanced Trade sandbox (`api-sandbox.coinbase.com`) only supports Accounts and Orders endpoints. Products, candles, product book, and transaction summary return 404. Tests for unsupported endpoints gracefully skip via `pytest.skip()`. The `sandbox_client` fixture bypasses the SDK's JWT auth gate since the sandbox requires no authentication.

**VCR.py Integration:**
- Records/replays HTTP interactions
- Cassettes stored in `tests/vcr_cassettes/`
- Filters sensitive headers (authorization, API keys)
- Use `@api_vcr.use_cassette('test_name.yaml')` decorator
- To re-record: delete cassettes and run with `COINBASE_SANDBOX_MODE=true`

## Important Patterns

**Coinbase API Response Objects:**
- Support both dot notation (`response.accounts`) and dict access (`response['products']`)
- Always handle both patterns when working with responses

**Thread Safety:**
- `self.order_lock` protects `filled_orders` list
- Use `with self.order_lock:` when modifying shared state
- `is_running` flag controls background thread lifecycle

**Precision Handling:**
- Product-specific increments fetched from API
- `round_size()` and `round_price()` methods
- Falls back to `config.precision` if API unavailable

**Error Handling:**
- Order placement validates: balance, min/max size, price increments
- TWAP slice failures tracked in `twap_order.failed_slices`
- Execution continues for remaining slices even if some fail

**Shutdown:**
- Set `self.is_running = False`
- Join background checker thread
- Clean exit without leaving orphaned threads

## Configuration

**Environment Variables:**
- `COINBASE_API_KEY`: API key (required)
- `COINBASE_API_SECRET`: API secret (optional, will prompt)
- `COINBASE_SANDBOX_MODE`: Set to 'true' for sandbox
- `RATE_LIMIT_RPS`: Requests per second (default: 25)
- `RATE_LIMIT_BURST`: Burst capacity (default: 50)
- `CACHE_ACCOUNT_TTL`: Account cache TTL (default: 60)
- `TWAP_JITTER_PCT`: Jitter percentage for TWAP intervals (default: 0.0)
- `TWAP_ADAPTIVE_ENABLED`: Enable adaptive cancel+replace (default: false)
- `TWAP_ADAPTIVE_TIMEOUT`: Adaptive timeout seconds (default: 30)
- `TWAP_ADAPTIVE_MAX_RETRIES`: Max adaptive retries (default: 3)
- `TWAP_PARTICIPATION_RATE_CAP`: Participation rate cap fraction (default: 0.0)
- `TWAP_VOLUME_LOOKBACK`: Volume lookback minutes (default: 5)
- `TWAP_MARKET_FALLBACK_ENABLED`: Enable market order fallback (default: false)
- `TWAP_MARKET_FALLBACK_REMAINING_SLICES`: Remaining slices for fallback (default: 1)
- See `config_manager.py` for full list

**Security:**
- API secret prompted at runtime, never stored to disk
- `.env` file git-ignored
- Use `Config.for_testing()` for tests to bypass environment

## Logging

- File: DEBUG level to `logs/trading_terminal_YYYYMMDD_HHMMSS.log`
- Console: ERROR level only (minimal output)
- All major operations logged with context
- Session boundaries marked with separator lines

## Dependencies

**Production** (`requirements.txt`):
- `coinbase-advanced-py`: Official Coinbase SDK
- `tabulate`: Table formatting
- `colorama`: Terminal colors

**Development** (`requirements-dev.txt`):
- `pytest`, `pytest-cov`, `pytest-mock`: Testing framework
- `freezegun`: Time mocking
- `vcrpy`: HTTP recording/replay
- `pydantic`: Schema validation
- `responses`: HTTP mocking
- Code quality: `black`, `flake8`, `mypy`, `isort`
