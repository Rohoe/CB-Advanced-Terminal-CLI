# Architecture Guide

> **As of:** 2026-02-26 · commit `84d549f` (test: add 89 tests for SQLite, WebSocket, analytics coverage gaps)

A plain-English walkthrough of how this trading terminal works, written for someone with a CS degree who wants to understand real-world software patterns.

---

## Table of Contents

1. [What Does This App Do?](#what-does-this-app-do)
2. [How It Starts Up](#how-it-starts-up)
3. [The Big Picture: Layers](#the-big-picture-layers)
4. [Key Design Patterns](#key-design-patterns)
   - [Dependency Injection](#dependency-injection)
   - [Abstract Interfaces](#abstract-interfaces)
   - [Strategy Pattern](#strategy-pattern)
   - [Producer-Consumer (Background Worker)](#producer-consumer-background-worker)
5. [The API Client Layer](#the-api-client-layer)
6. [Strategies: How Orders Get Executed](#strategies-how-orders-get-executed)
7. [Data Persistence (Storage & Database)](#data-persistence-storage--database)
8. [Real-Time Data: WebSockets](#real-time-data-websockets)
9. [Thread Safety: Why It Matters Here](#thread-safety-why-it-matters-here)
10. [Configuration System](#configuration-system)
11. [How Testing Works](#how-testing-works)
12. [Data Flow: Placing a TWAP Order End-to-End](#data-flow-placing-a-twap-order-end-to-end)

---

## What Does This App Do?

This is a command-line trading terminal that connects to the Coinbase cryptocurrency exchange. Instead of just placing a single buy/sell order, it supports **algorithmic trading strategies** — automated ways to split a large order into many smaller ones to get a better average price.

The three main strategies are:

- **TWAP** (Time-Weighted Average Price) — spreads an order evenly over time. If you want to buy 1 BTC over 2 hours, it places small orders every few minutes.
- **Scaled/Ladder** — places multiple orders at different price levels simultaneously. Like setting traps at various prices and waiting for the market to hit them.
- **VWAP** (Volume-Weighted Average Price) — like TWAP but places bigger orders during high-volume periods (when the market is busiest), which tends to get better prices.

It also supports **conditional orders** (stop-loss, take-profit) that trigger automatically when price hits a threshold.

---

## How It Starts Up

Here's what happens when you run `python app.py`:

```
1. setup_logging()          — creates a log file in logs/
2. TradingTerminal()        — builds all the components (see below)
3. terminal.run()
   ├── login()              — asks for your API credentials
   │   ├── creates the API client (connection to Coinbase)
   │   ├── tests the connection
   │   └── starts WebSocket for real-time prices
   └── while True:          — shows a numbered menu, waits for input
       └── dispatches to the right handler (place order, view portfolio, etc.)
```

The constructor (`__init__`) is where most of the interesting work happens. It creates every component the app needs and wires them together. Think of it like assembling a machine from parts before turning it on.

---

## The Big Picture: Layers

The app is organized into layers, each with a clear responsibility:

```
┌─────────────────────────────────────────────┐
│              UI Layer                       │
│   app.py (menu + input)                     │
│   display_service.py, ui_helpers.py         │
│   input_helpers.py, analytics_display.py    │
├─────────────────────────────────────────────┤
│           Execution Layer                   │
│   order_executor.py (places individual      │
│     orders with retry logic)                │
│   twap_executor.py, scaled_executor.py,     │
│     vwap_executor.py, conditional_executor  │
├─────────────────────────────────────────────┤
│           Strategy Layer                    │
│   order_strategy.py (abstract interface)    │
│   twap_strategy.py, scaled_strategy.py,     │
│     vwap_strategy.py                        │
├─────────────────────────────────────────────┤
│          Service Layer                      │
│   market_data.py (prices, candles, books)   │
│   precision_service.py (rounding)           │
│   analytics_service.py (P&L tracking)       │
│   websocket_service.py (real-time feed)     │
├─────────────────────────────────────────────┤
│        Infrastructure Layer                 │
│   api_client.py (Coinbase API wrapper)      │
│   database.py (SQLite)                      │
│   storage.py, sqlite_storage.py             │
│   config.py, config_manager.py              │
└─────────────────────────────────────────────┘
```

Each layer only talks to the layer below it. The UI layer never touches the database directly — it goes through services and executors. This separation makes it possible to test each layer independently.

---

## Key Design Patterns

### Dependency Injection

**What it is:** Instead of a class creating its own dependencies internally, they're passed in from outside (usually via the constructor).

**Why it matters:** It's the single most important pattern in this codebase. It's what makes the app testable.

**How it works here:**

```python
# Production code creates real components:
terminal = TradingTerminal(
    api_client=CoinbaseAPIClient(key, secret),   # real API
    database=Database("trading.db"),              # real database
)

# Test code swaps in fakes:
terminal = TradingTerminal(
    api_client=MockCoinbaseAPI(),                 # fake API (no network calls)
    database=Database(":memory:"),                # in-memory database (no files)
    start_checker_thread=False,                   # no background thread
)
```

The `TradingTerminal` class doesn't know or care whether it's talking to real Coinbase or a mock. It just calls methods on the `api_client` interface. This is the same principle behind why you can plug different USB devices into the same port — the port doesn't care what's on the other end, as long as it speaks USB.

Every service class follows this pattern. `TWAPExecutor` receives an `OrderExecutor`, `MarketData`, and `TWAPStorage` — it never creates them itself.

### Abstract Interfaces

**What it is:** A base class that defines *what* methods must exist, without implementing *how* they work.

**Example from this project:**

```python
# api_client.py — the "contract"
class APIClient(ABC):
    @abstractmethod
    def limit_order_gtc(self, client_order_id, product_id, side, base_size, limit_price):
        ...

    @abstractmethod
    def get_fills(self, order_ids):
        ...
    # ... 14 more methods

# The real implementation
class CoinbaseAPIClient(APIClient):
    def limit_order_gtc(self, ...):
        return self._sdk_client.limit_order_gtc(...)  # calls Coinbase

# The test implementation
class MockCoinbaseAPI(APIClient):
    def limit_order_gtc(self, ...):
        self.orders[order_id] = {...}  # stores in a dict
        return fake_response
```

Both `CoinbaseAPIClient` and `MockCoinbaseAPI` implement the same `APIClient` interface. Any code that accepts an `APIClient` works with either one. This is the **Liskov Substitution Principle** from your OOP classes — a subtype should be usable wherever its parent type is expected.

The same pattern is used for storage (`TWAPStorage` → `FileBasedTWAPStorage`, `InMemoryTWAPStorage`, `SQLiteTWAPStorage`).

### Strategy Pattern

**What it is:** Define a family of algorithms, encapsulate each one, and make them interchangeable.

**How it works here:**

All trading strategies implement the same four-method interface:

```python
class OrderStrategy(ABC):
    def calculate_slices(self) -> List[SliceSpec]:
        """Break the order into pieces. Returns a list of (size, price, time) tuples."""

    def should_skip_slice(self, slice_number, market_data) -> bool:
        """Should we skip this slice? (e.g., market too thin)"""

    def get_execution_price(self, slice_spec, market_data) -> float:
        """What price should we use for this slice right now?"""

    def on_slice_complete(self, slice_number, order_id, fill_info) -> None:
        """Called after each slice is placed — update internal tracking."""
```

Then `TWAPStrategy`, `ScaledStrategy`, and `VWAPStrategy` each implement this interface differently:

| Method | TWAP | Scaled | VWAP |
|--------|------|--------|------|
| `calculate_slices()` | Equal sizes, spaced evenly over time | Sizes vary by distribution, all placed at once | Sizes proportional to historical volume per hour |
| `should_skip_slice()` | Skip if our order is too large relative to market volume | Never skip | Never skip |
| `get_execution_price()` | Depends on price type: fixed, bid, mid, or ask | Pre-calculated price at each level | Same as TWAP |

The executor doesn't know which strategy it's running. It just calls the same four methods. To add a new strategy, you only need to write a new class that implements `OrderStrategy` — nothing else changes.

### Producer-Consumer (Background Worker)

**What it is:** One part of the program produces work items and puts them in a queue. Another part consumes items from the queue and processes them.

**How it works here:**

```
Main Thread (Producer)              Background Thread (Consumer)
─────────────────────               ──────────────────────────
Places an order on Coinbase  ──►
Puts order_id into Queue     ──►    Reads order_id from Queue
                                    Checks if order was filled
                                    If filled: records it
                                    If not: puts it back in Queue
```

Python's `Queue` class is thread-safe (multiple threads can read/write without data corruption), making it the perfect hand-off mechanism. The background thread runs as a **daemon** — it dies automatically when the main program exits, so you never get zombie threads.

---

## The API Client Layer

The `CoinbaseAPIClient` is a thin wrapper around the official Coinbase SDK. "Thin wrapper" means it adds very little logic — it mostly just translates our method calls into SDK calls:

```python
class CoinbaseAPIClient(APIClient):
    def __init__(self, api_key, api_secret):
        self._client = RESTClient(api_key=api_key, api_secret=api_secret)

    def limit_order_gtc(self, client_order_id, product_id, side, base_size, limit_price):
        return self._client.limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=str(base_size),
            limit_price=str(limit_price),
        )
```

**Why wrap the SDK at all?** Two reasons:

1. **Testability** — We can swap in `MockCoinbaseAPI` during tests without hitting the real API.
2. **Abstraction** — If Coinbase changes their SDK, we only update this one file. The rest of the app doesn't care.

The `APIClientFactory` provides convenience methods for creating clients:
- `create_from_config()` — for production
- `create_mock()` — for testing

---

## Strategies: How Orders Get Executed

Let's trace how a TWAP order actually runs. Say you want to buy 0.1 BTC over 10 minutes in 5 slices:

### Step 1: Create the Strategy

```python
strategy = TWAPStrategy(
    product_id="BTC-USD",
    side="BUY",
    total_size=0.1,
    num_slices=5,
    duration_minutes=10,
    limit_price=50000.0,
    price_type="limit",
    api_client=api_client,
    config=config,
)
```

### Step 2: Calculate Slices

`strategy.calculate_slices()` returns:

```python
[
    SliceSpec(slice=1, size=0.02, price=50000, time=0:00),
    SliceSpec(slice=2, size=0.02, price=50000, time=2:00),
    SliceSpec(slice=3, size=0.02, price=50000, time=4:00),
    SliceSpec(slice=4, size=0.02, price=50000, time=6:00),
    SliceSpec(slice=5, size=0.02, price=50000, time=8:00),
]
```

### Step 3: Execute Each Slice

The executor loops through slices:

```
For each slice:
  1. Sleep until scheduled_time
  2. Ask strategy: should_skip_slice()?        → "No"
  3. Ask strategy: get_execution_price()        → 50000.0
  4. Place limit order via API
  5. Put order_id in the queue for monitoring
  6. Tell strategy: on_slice_complete()
```

### Step 4: Background Monitoring

Meanwhile, the background worker thread picks up each order_id from the queue and polls Coinbase to see if it was filled (someone bought/sold at your price).

### Step 5: Results

After all slices execute, the strategy returns a `StrategyResult` with statistics: how much was filled, at what average price, total fees, etc.

---

## Data Persistence (Storage & Database)

### Why SQLite?

The app needs to remember your orders across restarts. If you start a TWAP that runs for 2 hours and your computer crashes at minute 90, you want to know what happened to the first 45 slices.

SQLite is an embedded database — it's a single file (`trading.db`) with no server to install. Python includes SQLite support in its standard library.

### The Database Class

`database.py` wraps SQLite with two important features:

**1. Thread-local connections**

SQLite connections aren't safe to share across threads. The `Database` class uses `threading.local()` to give each thread its own connection:

```python
class Database:
    def __init__(self, path):
        self._local = threading.local()  # each thread gets its own slot

    def _get_connection(self):
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self._path)
        return self._local.conn
```

**2. Context-managed transactions**

Instead of manually calling `commit()` and `rollback()`, you use `with` blocks:

```python
with db.transaction() as conn:
    conn.execute("INSERT INTO orders ...")
    conn.execute("INSERT INTO fills ...")
    # If anything raises an exception, both inserts are rolled back
    # If we reach the end, both are committed together
```

This guarantees **atomicity** — either both inserts happen, or neither does. No half-written data.

### Schema Overview

```
orders              — every order (TWAP, scaled, conditional)
  └── child_orders  — individual limit orders placed by strategies
      └── fills     — when Coinbase matches your order with a buyer/seller
  └── twap_slices   — timing details for each TWAP slice
  └── scaled_levels — price levels for scaled/ladder orders
price_snapshots     — market prices recorded at key moments (for analytics)
pnl_ledger          — profit/loss tracking per completed trade
```

### Storage Implementations

The project has three implementations of `TWAPStorage`:

| Implementation | Where Data Lives | Used For |
|---|---|---|
| `FileBasedTWAPStorage` | JSON files in `twap_data/` | Legacy (before SQLite was added) |
| `InMemoryTWAPStorage` | Python dictionaries | Unit tests (fast, no cleanup) |
| `SQLiteTWAPStorage` | SQLite database | Production (default) |

The `migrate_json_to_sqlite.py` module automatically moves data from JSON files to SQLite on first run, so existing users don't lose their history.

---

## Real-Time Data: WebSockets

### REST vs WebSocket

Most of the app uses **REST** (HTTP request → response). You ask Coinbase "what's the price of BTC?" and get a response. But for real-time prices, this is slow — you'd have to ask over and over.

**WebSocket** is a persistent connection. Coinbase pushes price updates to us as they happen, without us asking. Think of REST as checking your mailbox vs. WebSocket as getting notifications on your phone.

### How It's Used Here

The `WebSocketService` maintains two WebSocket connections:

1. **Ticker channel** — receives real-time bid/ask prices. These are cached in a dictionary with timestamps. If a cached price is older than 5 seconds, it's considered "stale" and ignored (we fall back to a REST call).

2. **User channel** — receives fill notifications. When one of your orders is matched, Coinbase pushes an event instead of us having to poll.

### Graceful Degradation

The WebSocket is **optional**. If it fails to connect, the app falls back to REST polling everywhere. This is a good engineering practice — don't let an enhancement become a single point of failure.

```python
# In market_data.py
def get_current_price(self, product_id):
    # Try WebSocket cache first (instant, free)
    if self.websocket_service:
        prices = self.websocket_service.get_current_prices(product_id)
        if prices:
            return prices['mid']

    # Fall back to REST (slower, costs a rate-limit token)
    ticker = self.api_client.get_product(product_id)
    return float(ticker['price'])
```

---

## Thread Safety: Why It Matters Here

### The Problem

This app has multiple threads running simultaneously:

- **Main thread**: handles user input and places orders
- **Background worker thread**: monitors order fills
- **WebSocket threads**: receive real-time data (managed by the SDK)

When two threads read/write the same data at the same time, you can get **race conditions** — bugs that happen randomly and are extremely hard to reproduce.

Example of what could go wrong without locks:

```
Thread A (main):    reads filled_orders → [order1, order2]
Thread B (worker):  reads filled_orders → [order1, order2]
Thread A:           appends order3 → [order1, order2, order3]
Thread B:           appends order4 → [order1, order2, order4]  ← order3 is lost!
```

### The Solution: Locks

A `Lock` is like a bathroom door lock. Only one thread can hold it at a time. If another thread tries to acquire a held lock, it waits.

```python
with self.order_lock:           # acquire the lock (wait if someone else has it)
    self.filled_orders.append(order_id)
                                # lock is automatically released when we exit the block
```

This project uses **per-domain locks** — separate locks for separate data:

| Lock | What It Protects |
|------|-----------------|
| `order_lock` | The list of filled orders |
| `twap_lock` | TWAP order tracking dictionaries |
| `conditional_lock` | Conditional order mappings |
| `scaled_lock` | Scaled order mappings |
| `_price_lock` | WebSocket price cache |

**Why separate locks?** If you used one big lock for everything, threads would block each other even when accessing unrelated data. Fine-grained locks allow more parallelism.

**Deadlock prevention:** The code never acquires two locks at the same time (no nesting), which makes deadlocks impossible.

---

## Configuration System

Configuration is split into two parts:

### 1. Credentials (`config.py`)

Handles the sensitive stuff — your API key and secret. The secret is never stored to disk. It's either provided via environment variable or prompted at runtime via `getpass` (which hides your typing).

### 2. App Settings (`config_manager.py`)

Everything else — rate limits, cache TTLs, strategy parameters, database paths. All loaded from environment variables with sensible defaults:

```python
class RateLimitConfig:
    requests_per_second: int  # default 25, override with RATE_LIMIT_RPS=50
    burst: int                # default 50, override with RATE_LIMIT_BURST=100
```

The `_env()` helper function handles the repetitive pattern of "read from env, use default if missing, convert to the right type":

```python
def _env(name, default, type_fn=str):
    raw = os.getenv(name, str(default))
    if type_fn is bool:
        return raw.lower() == 'true'
    return type_fn(raw)
```

**For testing**, `AppConfig.for_testing()` returns aggressive settings (1-second TTLs, no retries) so tests run fast.

---

## How Testing Works

### The Testing Philosophy

The project can't run its tests against real Coinbase — that would be slow, expensive (real money!), and flaky (depends on network). Instead, it uses **test doubles** at multiple levels:

### Layer 1: Unit Tests with Mocks

Each module is tested in isolation. Dependencies are replaced with `unittest.Mock` objects or purpose-built fakes:

```python
def test_twap_calculates_slices(mock_api_client, test_app_config):
    strategy = TWAPStrategy(
        api_client=mock_api_client,    # won't hit the network
        config=test_app_config,        # fast settings
        ...
    )
    slices = strategy.calculate_slices()
    assert len(slices) == 5
    assert all(s.size == 0.02 for s in slices)
```

### Layer 2: Integration Tests with MockCoinbaseAPI

`MockCoinbaseAPI` is a full in-memory fake of the Coinbase API. It simulates realistic behavior — it stores orders, simulates fills, generates candle data. Integration tests use it to verify that multiple components work together correctly:

```python
def test_twap_execution_end_to_end(terminal_with_mocks):
    # terminal_with_mocks uses MockCoinbaseAPI + in-memory SQLite
    # This tests the full flow: strategy → executor → API → storage
    terminal_with_mocks.execute_twap(...)
```

### Layer 3: Conformance Tests

These verify that `MockCoinbaseAPI` actually behaves like real Coinbase. They hit the real public API (no auth needed) and compare response shapes using Pydantic schemas:

```python
@pytest.mark.public_api
def test_mock_matches_real_products():
    real_response = public_client.get_products()
    mock_response = MockCoinbaseAPI().get_products()
    # Both should have the same field names and types
```

This creates a chain of trust: unit tests trust the mock → conformance tests verify the mock matches reality.

### Key Fixtures

Fixtures in `conftest.py` are reusable test setup. Think of them as "pre-built test environments":

- `mock_api_client` — a bare Mock with basic return values
- `sqlite_db` — an in-memory SQLite database (created and destroyed per test)
- `terminal_with_mocks` — a fully wired `TradingTerminal` with all fakes injected
- `sandbox_client` — points at Coinbase's sandbox environment for safe real-API testing

### Test Markers

Tests are tagged so you can run subsets:

```bash
pytest -m unit            # fast, no network
pytest -m public_api      # hits real Coinbase (read-only, no auth)
pytest -m "not public_api"  # everything except real API calls
```

---

## Data Flow: Placing a TWAP Order End-to-End

Here's the complete journey of a TWAP order through the system, connecting all the pieces:

```
User selects "TWAP Order" from menu
         │
         ▼
    ┌─────────┐     Validates input (product, side,
    │  app.py  │     size, duration, slices, price)
    └────┬────┘
         │
         ▼
    ┌────────────────┐     Creates TWAPStrategy with params
    │ twap_executor  │     Calls strategy.calculate_slices()
    └────┬───────────┘     Saves order to SQLite via twap_storage
         │
         │  For each slice:
         ▼
    ┌────────────────┐     Waits for scheduled time
    │ order_executor │     Calls rate_limiter.wait()
    └────┬───────────┘     Calls api_client.limit_order_gtc()
         │
         ├──────────────►  order_id goes into Queue
         │
         │                 ┌─────────────────────┐
         │                 │  background_worker   │  (separate thread)
         │                 │  reads from Queue     │
         │                 │  polls Coinbase for   │
         │                 │  fill status          │
         │                 │  updates storage      │
         │                 └─────────────────────┘
         │
         │                 ┌─────────────────────┐
         │                 │  websocket_service   │  (separate thread)
         │                 │  receives fill events │
         │                 │  notifies worker via  │
         │                 │  callback             │
         │                 └─────────────────────┘
         │
         ▼
    ┌────────────────┐
    │ analytics      │     Records P&L, slippage, fees
    │ service        │     Stores in pnl_ledger table
    └────────────────┘
         │
         ▼
    ┌────────────────┐
    │ display        │     Shows execution summary
    │ service        │     (filled %, avg price, fees)
    └────────────────┘
```

---

## Glossary

| Term | Meaning |
|------|---------|
| **GTC** | Good Till Cancelled — order stays open until filled or you cancel it |
| **TWAP** | Time-Weighted Average Price — spread orders evenly over time |
| **VWAP** | Volume-Weighted Average Price — place more during high-volume periods |
| **Maker** | Your order was waiting in the book; someone else matched it (lower fees) |
| **Taker** | Your order immediately matched someone else's waiting order (higher fees) |
| **Slice** | One piece of a larger algorithmic order |
| **Fill** | When an exchange matches your order — you actually bought/sold |
| **WAL mode** | Write-Ahead Logging — SQLite mode that allows concurrent reads during writes |
| **Daemon thread** | A thread that dies automatically when the main program exits |
| **Race condition** | Bug caused by two threads accessing shared data without coordination |
| **TTL** | Time To Live — how long a cached value is considered fresh |
| **Basis points (bps)** | 1/100th of a percent. 50 bps = 0.50% |
