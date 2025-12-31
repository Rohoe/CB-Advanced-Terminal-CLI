# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based trading terminal for Coinbase Advanced Trade API. The application provides a command-line interface for executing trades, managing orders, and implementing Time-Weighted Average Price (TWAP) trading strategies.

## Running the Application

**Main execution:**
```bash
python app.py
```

The application will prompt for the API secret on startup (the API key is stored in `keys.py`).

## Project Architecture

### Core Components

**`app.py` - Main Trading Terminal (1971 lines)**
- `TradingTerminal` class: Main application controller with all trading functionality
- `RateLimiter` class: Token bucket rate limiter for API calls (lines 72-111)
- Multi-threaded architecture with background order status checker
- Comprehensive logging system with file and console handlers

**`twap_tracker.py` - TWAP Order Persistence**
- `TWAPTracker` class: JSON-based persistence for TWAP orders and fills
- `TWAPOrder` dataclass: TWAP order structure with execution tracking
- `OrderFill` dataclass: Individual fill information with maker/taker status
- Data stored in `twap_data/orders/` and `twap_data/fills/` directories

**`keys.py` - API Credentials**
- Contains Coinbase API key and prompts for secret using `getpass`
- IMPORTANT: This file contains real API credentials and should never be committed with actual secrets

### Key Architectural Patterns

**Rate Limiting System:**
- Token bucket implementation in `RateLimiter` class (app.py:72-111)
- Default: 25 requests/second with burst of 50 (configurable in CONFIG dict)
- ALL API calls must use `self.rate_limiter.wait()` before execution
- Critical for avoiding API rate limit errors

**Caching Strategy:**
- Account cache: 60-second TTL (app.py:151-152)
- Order status cache: 5-second TTL (app.py:141)
- Fill cache: 5-second TTL (app.py:154-155)
- All caches support force refresh via parameters

**TWAP Execution Flow:**
1. User provides order parameters via `get_order_input()` (app.py:1551-1676)
2. TWAP configuration: duration, slices, price type selection
3. `TWAPOrder` created with unique UUID and persisted to JSON
4. Loop through slices with interval timing between executions
5. Each slice: fetch current prices → validate → place order via `place_twap_slice()`
6. Background thread (`order_status_checker`) monitors fills in batches
7. Final summary with execution statistics via `display_twap_summary()`

**Order Status Checker Thread:**
- Daemon thread started in `__init__` (app.py:133-136)
- Processes orders from queue in batches of up to 50 (app.py:1108-1116)
- Uses `check_order_fills_batch()` for efficient batch fill checking
- Updates `twap_orders` dictionary with fill statistics
- Requeues unfilled orders for continued monitoring

**Precision Handling:**
- Product-specific precision config (app.py:144-148)
- `round_size()` and `round_price()` methods fetch product increment info from API
- Falls back to config if API call fails

### Data Structures

**TWAP Order Tracking (in-memory):**
```python
self.twap_orders = {
    'twap_id': {
        'total_filled': float,
        'total_value_filled': float,
        'total_fees': float,
        'maker_orders': int,
        'taker_orders': int,
        # ... other tracking fields
    }
}
self.order_to_twap_map = {'order_id': 'twap_id'}
```

**TWAP Persistence (JSON):**
- Orders: `twap_data/orders/{twap_id}.json` - TWAPOrder dataclass
- Fills: `twap_data/fills/{twap_id}.json` - List of OrderFill dataclasses
- Use `TWAPTracker` methods for all persistence operations

### Error Handling

**Order Placement Validation (app.py:732-813):**
- Pre-flight checks: balance, min/max size, price increments
- Product info fetched and validated before each order
- Comprehensive error logging with stack traces

**TWAP Slice Failure Handling:**
- Failed slices tracked in `twap_order.failed_slices` list
- Slice statuses recorded with error details in `slice_statuses`
- Insufficient balance, unfavorable prices, and API errors handled gracefully
- Execution continues for remaining slices even if some fail

### Logging System

**Configuration (app.py:20-61):**
- File logging: DEBUG level to `logs/trading_terminal_YYYYMMDD_HHMMSS.log`
- Console logging: ERROR level only
- All major operations logged with context (market conditions, balances, etc.)
- Session boundaries marked with separator lines

## Common Development Tasks

**Adding a new order type:**
1. Create order input collection method (follow pattern in `get_order_input()`)
2. Implement order placement logic with retry mechanism
3. Add validation for product constraints (min/max size, increments)
4. Integrate with rate limiter: `self.rate_limiter.wait()` before API calls
5. Add menu option in `run()` method
6. Follow logging patterns for debugging and audit trail

**Modifying TWAP execution:**
- Core logic in `place_twap_order()` (app.py:1165-1404)
- Slice placement in `place_twap_slice()` (app.py:815-884)
- Fill updates in `update_twap_fills()` (app.py:627-730)
- Always persist state changes with `self.twap_tracker.save_twap_order()`

**Working with the Coinbase API:**
- Uses `coinbase.rest.RESTClient` from coinbase-advanced-py SDK
- Response objects use both dot notation (`response.accounts`) and dictionary access (`response['products']`)
- Always handle both access patterns when working with API responses
- Check SDK docs: https://docs.cdp.coinbase.com/advanced-trade/docs/sdk-overview/

**Testing with rate limits:**
- Reduce `rate_limit_requests` in CONFIG for faster testing
- Use `force_refresh=True` on cache methods to bypass caching
- Monitor `logs/` directory for detailed API interaction logs

## Important Notes

- **Thread Safety:** `order_lock` protects `filled_orders` list; use `with self.order_lock:` when modifying
- **Shutdown Handling:** Set `self.is_running = False` and join checker thread before exit
- **Fee Calculation:** Fee tier fetched from `get_transaction_summary()` API call; defaults to 0.4% maker / 0.6% taker if unavailable
- **Market Selection:** Consolidates USD and USDC pairs in market display; handles both quote currencies
- **Price Types:** TWAP supports execution at limit price, bid, mid, or ask (user selectable per order)

## API Dependencies

**Required Python packages:**
- `coinbase-advanced-py` - Official Coinbase Advanced Trade SDK
- `tabulate` - Table formatting for terminal display
- Standard library: `logging`, `threading`, `queue`, `datetime`, `uuid`, `json`, `dataclasses`

**External APIs:**
- Coinbase Advanced Trade API
- Authentication: API key + secret (stored in `keys.py`)
- Rate limits enforced by RateLimiter class
