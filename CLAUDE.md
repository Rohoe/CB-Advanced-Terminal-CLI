# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based trading terminal for Coinbase Advanced Trade API with limit orders and algorithmic trading strategies (TWAP, scaled/ladder, VWAP, conditional).

## Running the Application

**Main execution:**
```bash
export COINBASE_API_KEY="organizations/your-org-id/apiKeys/your-key-id"
python app.py  # Will prompt for API secret
```

**Testing:**
```bash
pip install -r requirements-dev.txt
pytest                                    # All tests
pytest --cov=. --cov-report=html          # With coverage
pytest -m unit                            # Unit tests only
pytest -m public_api                      # Public API tests (no auth needed)
pytest -m authenticated                   # Authenticated conformance tests (needs .env keys)
pytest -m "not public_api"                # Skip public API tests (offline)
pytest -m sandbox                         # Sandbox tests (needs COINBASE_SANDBOX_MODE=true)
pytest -m vcr                             # VCR replay tests (offline)
pytest tests/test_validators.py           # Specific file
```

## Source Files

### Entry Point
- `app.py` — Main `TradingTerminal` class, CLI menu, rate limiter; delegates order monitoring to `background_worker.py`

### Core Infrastructure
- `api_client.py` — `APIClient` abstract interface + `CoinbaseAPIClient` production implementation + `APIClientFactory`
- `config.py` — `Config` class for API credentials (loads from env vars, prompts for secret)
- `config_manager.py` — `AppConfig` + sub-configs (`RateLimitConfig`, `CacheConfig`, `TWAPConfig`, `RetryConfig`, `DisplayConfig`, `PrecisionConfig`, `DatabaseConfig`, `WebSocketConfig`); all configurable via env vars; uses `_env()` helper for DRY env var loading
- `database.py` — Thread-safe `Database` class with WAL mode, thread-local connections, context-managed `transaction()`/`read()`, and unified schema (`orders`, `child_orders`, `fills`, `twap_slices`, `scaled_levels`, `price_snapshots`, `pnl_ledger`)
- `storage.py` — `TWAPStorage` abstract interface + `FileBasedTWAPStorage` (JSON in `twap_data/`) + `InMemoryTWAPStorage` for tests + `StorageFactory`
- `sqlite_storage.py` — `SQLiteTWAPStorage`, `SQLiteScaledOrderTracker`, `SQLiteConditionalOrderTracker` — SQLite implementations of storage ABCs
- `migrate_json_to_sqlite.py` — `JSONToSQLiteMigrator` auto-migrates existing JSON data to SQLite on startup
- `validators.py` — `InputValidator` static methods + `ValidationError`; validates price, size, duration, slices, side, product_id, price_type
- `market_data.py` — Market data fetching and caching (candles, order book, products); tries WebSocket cache first, falls back to REST
- `precision_service.py` — `PrecisionService` with `round_size()` and `round_price()` using product-specific increments
- `base_tracker.py` — `BaseOrderTracker` generic persistence base class (JSON file I/O, directory management)
- `input_helpers.py` — `InteractiveInputHelper` for validated user input collection (market, side, price, size, duration, slices)
- `background_worker.py` — `OrderStatusChecker` daemon thread for monitoring order fills; supports push-based WebSocket fills with REST polling fallback
- `order_view_service.py` — `OrderViewService` for order data access (active orders, history, conditional sync)
- `websocket_service.py` — `WebSocketService` wrapping SDK's `WSClient` for real-time ticker prices and user channel fills; thread-safe price cache with staleness check

### Analytics
- `analytics_service.py` — `AnalyticsService(db)` with P&L tracking (`get_realized_pnl`, `get_cost_basis`, `get_cumulative_pnl`), execution quality (`get_slippage_analysis`, `get_fill_rate_analysis`, `get_maker_taker_analysis`, `get_fee_analysis`), and arrival price recording
- `analytics_display.py` — `AnalyticsDisplay` with formatted terminal output for P&L summaries, execution reports, fee analysis, daily P&L

### Strategy System
- `order_strategy.py` — `OrderStrategy` protocol defining `calculate_slices()`, `should_skip_slice()`, `get_execution_price()`, `on_slice_complete()`
- `order_executor.py` — Generic `OrderExecutor` that drives any `OrderStrategy` implementation

### TWAP
- `twap_strategy.py` — `TWAPStrategy` implementing `OrderStrategy` with jitter, participation rate cap, 4 price types (limit/bid/mid/ask)
- `twap_executor.py` — `TWAPExecutor` orchestrating TWAP-specific execution flow
- `twap_tracker.py` — `TWAPOrder` and `OrderFill` dataclasses + persistence

### Scaled/Ladder Orders
- `scaled_orders.py` — `ScaledOrder` dataclass + distribution types (linear, exponential, flat)
- `scaled_strategy.py` — `ScaledStrategy` implementing `OrderStrategy`
- `scaled_executor.py` — `ScaledExecutor` orchestrating scaled order flow
- `scaled_order_tracker.py` — `ScaledOrderStorage` ABC + `ScaledOrderTracker` JSON persistence (in `scaled_data/`)

### VWAP
- `vwap_strategy.py` — `VWAPStrategy` with volume profile weighting and benchmark tracking
- `vwap_executor.py` — `VWAPExecutor` orchestrating VWAP execution

### Conditional Orders
- `conditional_orders.py` — `ConditionalOrder` dataclass + order types (stop-limit, bracket, attached bracket)
- `conditional_executor.py` — `ConditionalExecutor` monitoring trigger conditions
- `conditional_order_tracker.py` — `ConditionalOrderStorage` ABC + `ConditionalOrderTracker` JSON persistence (in `conditional_data/`)

### UI
- `display_service.py` — Portfolio display, order tables, TWAP summaries
- `ui_helpers.py` — Color-coded terminal output (colorama): `success()`, `error()`, `warning()`, `info()`, `highlight()`, formatters

## Architecture

### Dependency Injection

`TradingTerminal` (`app.py`) accepts injectable dependencies:
- `api_client`: `APIClient` interface — abstracts Coinbase API calls
- `twap_storage`: `TWAPStorage` interface — abstracts order persistence
- `database`: `Database` instance — SQLite persistence (defaults to `trading.db`)
- `config`: `AppConfig` — centralized configuration

Default storage is SQLite (`SQLiteTWAPStorage`, `SQLiteScaledOrderTracker`, `SQLiteConditionalOrderTracker`). Testing uses `MockCoinbaseAPI` (in `tests/mocks/`), `InMemoryTWAPStorage`, and in-memory SQLite (`sqlite_db` fixture).

### Rate Limiter (`app.py`)
- Token bucket algorithm: 25 req/s default, burst of 50
- ALL API calls MUST call `self.rate_limiter.wait()` before execution
- Thread-safe with internal lock

### Caching
- Account: 60s TTL | Order status: 5s | Fills: 5s | Product metadata: 300s
- All support `force_refresh=True`

### Order Status Checker Thread (`background_worker.py`)
- Daemon thread monitors order fills in background
- Batches up to 50 orders via `check_order_fills_batch()`
- Thread-safe with `self.order_lock`
- When WebSocket connected: push-based fill detection via callbacks, REST polling reduced to 30s backup
- Without WebSocket: REST polling at 0.5s intervals

### WebSocket (`websocket_service.py`)
- Optional enhancement — app works without WebSocket (REST fallback)
- Ticker channel: real-time prices cached with staleness check (`WS_PRICE_STALE_SECONDS`, default 5s)
- User channel: push-based fill events via `register_fill_callback()`
- Auto-reconnect via SDK's `retry=True`

### Analytics (`analytics_service.py`)
- P&L tracking via `pnl_ledger` table with slippage in basis points
- Arrival price capture: market mid recorded at order creation and slice placement
- Execution quality: slippage, fill rate, maker/taker ratio, fee analysis
- Menu items 14-16: P&L Summary, Execution Analytics, Fee Analysis

### Strategy Execution Flow
1. Create strategy (e.g., `TWAPStrategy`) with parameters, config, API client
2. Executor calls `strategy.calculate_slices()` for timing
3. Per slice: `should_skip_slice()` → `get_execution_price()` → place order → `on_slice_complete()`
4. Returns `StrategyResult` with execution metrics

## Testing Infrastructure

```
tests/
├── conftest.py                    # Shared fixtures
├── test_validators.py             # Input validation
├── test_config.py                 # Config/credentials loading
├── test_rate_limiter.py           # Rate limiter
├── test_twap_tracker.py           # TWAP persistence
├── test_trading_terminal.py       # Terminal unit tests
├── test_candles.py                # Candle data
├── test_market_data.py            # Market data module
├── test_order_executor.py         # Order executor
├── test_conditional_executor.py   # Conditional orders
├── test_conditional_order_tracker.py # Conditional order tracker persistence
├── test_storage.py                # Storage layer (file-based + in-memory)
├── test_twap_executor.py          # TWAP executor
├── test_twap_executor_enhanced.py # TWAP enhanced features
├── test_twap_strategy.py          # TWAP strategy
├── test_scaled_executor.py        # Scaled executor
├── test_scaled_order_tracker.py   # Scaled tracker
├── test_scaled_strategy.py        # Scaled strategy
├── test_vwap_executor.py          # VWAP executor
├── test_vwap_strategy.py          # VWAP strategy
├── test_sqlite_storage.py         # SQLite storage implementations
├── test_migration.py              # JSON-to-SQLite migration
├── test_websocket_service.py      # WebSocket service
├── test_analytics_service.py      # Analytics engine
├── helpers/
│   └── shape_compare.py           # Response shape comparison utility
├── integration/                   # Integration tests
│   ├── test_mock_conformance.py   # Mock vs real API conformance (public + authenticated)
│   ├── test_twap_execution.py     # TWAP with mocks
│   ├── test_order_lifecycle.py    # Order lifecycle with mocks
│   ├── test_portfolio_display.py  # Portfolio display with mocks
│   ├── test_scaled_execution.py   # Scaled order flow (mock-based)
│   ├── test_vwap_execution.py     # VWAP order flow (mock-based)
│   ├── test_sandbox_api.py        # Sandbox API endpoints
│   ├── test_sandbox_modules.py    # Modules vs sandbox API
│   ├── test_public_api.py         # Public endpoint validation (no auth)
│   ├── test_public_modules.py     # Modules wired to public API (no auth)
│   └── test_vcr_recording.py      # VCR cassette recording/replay
├── mocks/
│   └── mock_coinbase_api.py       # Mock API (supports strict_validation mode)
├── schemas/
│   └── api_responses.py           # Pydantic response schemas
└── vcr_cassettes/                 # Recorded API responses (YAML)
```

**Key Fixtures** (`tests/conftest.py`):
- `mock_api_client` / `mock_twap_storage` / `test_app_config` — fast test defaults
- `sqlite_db` / `sqlite_twap_storage` — in-memory SQLite fixtures
- `terminal_with_mocks` — fully configured terminal with in-memory SQLite for integration tests
- `sandbox_client` — CoinbaseAPIClient pointed at sandbox (patches SDK auth gate)

**Test Markers:** `unit`, `integration`, `slow`, `vcr`, `sandbox`, `public_api`, `authenticated`

**Mock Conformance Testing:**
- `public_api` tests verify mock matches real public API response shapes (no auth needed, safe for CI)
- `authenticated` tests verify mock matches authenticated API responses (requires `COINBASE_READONLY_KEY` + `COINBASE_READONLY_SECRET` in `.env`)
- `MockCoinbaseAPI` supports `strict_validation=True` to raise on schema mismatches

**Sandbox Limitations:** Only Accounts and Orders endpoints work. Products, candles, product book, and transaction summary return 404. Tests skip gracefully.

## Important Patterns

- **API Responses:** Support both dot notation and dict access — handle both
- **Thread Safety:** `self.order_lock` protects `filled_orders`; use `with self.order_lock:`
- **Precision:** Product-specific increments from API; `round_size()`/`round_price()` methods; falls back to `config.precision`
- **Error Handling:** Validates balance, min/max size, price increments before placement; failed slices tracked, execution continues
- **Shutdown:** Set `self.is_running = False`, join background thread

## Configuration

**Environment Variables:**
- `COINBASE_API_KEY` (required), `COINBASE_API_SECRET` (optional, will prompt)
- `COINBASE_READONLY_KEY`, `COINBASE_READONLY_SECRET` — read-only key for authenticated conformance tests
- `COINBASE_SANDBOX_MODE` — set `true` for sandbox
- `RATE_LIMIT_RPS` (25), `RATE_LIMIT_BURST` (50)
- `CACHE_ACCOUNT_TTL` (60)
- `TWAP_JITTER_PCT` (0.0), `TWAP_ADAPTIVE_ENABLED` (false), `TWAP_ADAPTIVE_TIMEOUT` (30), `TWAP_ADAPTIVE_MAX_RETRIES` (3)
- `TWAP_PARTICIPATION_RATE_CAP` (0.0), `TWAP_VOLUME_LOOKBACK` (5)
- `TWAP_MARKET_FALLBACK_ENABLED` (false), `TWAP_MARKET_FALLBACK_REMAINING_SLICES` (1)
- `DB_PATH` (trading.db), `DB_WAL_MODE` (true)
- `WS_ENABLED` (true), `WS_TICKER_ENABLED` (true), `WS_USER_CHANNEL_ENABLED` (true), `WS_PRICE_STALE_SECONDS` (5)
- See `config_manager.py` for full list

**Security:** API secret prompted at runtime, never stored to disk. `.env` is git-ignored.

## Logging

- File: DEBUG level to `logs/trading_terminal_YYYYMMDD_HHMMSS.log`
- Console: ERROR level only

## Dependencies

**Production** (`requirements.txt`): `coinbase-advanced-py`, `tabulate`, `colorama`

**Development** (`requirements-dev.txt`): `pytest`, `pytest-cov`, `pytest-mock`, `freezegun`, `vcrpy`, `pydantic`, `responses`, `black`, `flake8`, `mypy`, `isort`
