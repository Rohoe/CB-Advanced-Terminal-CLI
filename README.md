# Coinbase Advanced Trading Terminal

A Python-based command-line trading terminal for Coinbase Advanced Trade API with support for limit orders and algorithmic trading strategies.

## Features

- **Portfolio Management** — View account balances and USD valuations with color-coded display
- **Limit Orders** — Place and manage limit orders with fee preview (maker/taker estimates, total cost/proceeds)
- **TWAP Orders** — Split large orders into time-weighted slices to minimize market impact
  - Configurable slices, duration, and price modes (limit, bid, mid, ask)
  - Jitter, participation rate cap, adaptive cancel+replace
- **Scaled/Ladder Orders** — Distribute orders across a price range with linear, exponential, or flat distribution
- **VWAP Orders** — Volume-weighted execution with volume profile weighting and benchmark tracking
- **Conditional Orders** — Stop-limit, bracket, and attached bracket order types with trigger monitoring
- **Order History** — Filter by product, status, or both with color-coded display
- **Order Management** — View and cancel active orders
- **Rate Limiting** — Token bucket rate limiter (25 req/s, burst of 50)
- **Intelligent Caching** — TTL-based caching for accounts, orders, fills, and product metadata
- **Logging** — DEBUG-level file logging, ERROR-level console output

## Prerequisites

- Python 3.7+
- Coinbase Advanced Trade API credentials ([setup guide](https://docs.cdp.coinbase.com/advanced-trade/docs/auth))
- Active Coinbase account with trading enabled

## Installation

```bash
git clone <repository-url>
cd CB-Advanced-Terminal-CLI
pip install -r requirements.txt
```

## Configuration

```bash
# Set your API key (required)
export COINBASE_API_KEY="organizations/your-org-id/apiKeys/your-key-id"

# Run the app (will prompt for API secret)
python app.py
```

Alternatively, copy `.env.example` to `.env` and set your API key there:
```bash
cp .env.example .env
set -a && source .env && set +a
python app.py
```

**Security:** API secret is prompted at runtime and never stored to disk. The `.env` file is git-ignored.

## Usage

### Main Menu

1. **View Portfolio Balances** — All accounts with USD valuations
2. **Place a Limit Order** — Single limit order with fee preview
3. **Place a TWAP Order** — Time-weighted average price execution
4. **Check TWAP Order Fills** — Execution statistics for TWAP orders
5. **Show and Cancel Active Orders** — Manage open orders
6. **View Order History** — Past orders with filtering

### TWAP Order Example

```
Market: BTC-USDC
Side: BUY
Total Size: 0.1 BTC
Limit Price: $100,000
Duration: 60 minutes
Slices: 12
Price Mode: Market mid

→ 12 orders of ~0.00833 BTC each, placed every 5 minutes
```

## Project Structure

```
├── app.py                      # Main terminal + CLI menu
├── api_client.py               # API client abstraction
├── config.py                   # Credential management
├── config_manager.py           # Application configuration
├── storage.py                  # Storage abstraction
├── validators.py               # Input validation
├── market_data.py              # Market data + caching
├── display_service.py          # Portfolio/order display
├── ui_helpers.py               # Terminal color utilities
├── order_strategy.py           # OrderStrategy protocol
├── order_executor.py           # Generic strategy executor
├── twap_strategy.py            # TWAP strategy
├── twap_executor.py            # TWAP executor
├── twap_tracker.py             # TWAP persistence
├── scaled_orders.py            # Scaled order types
├── scaled_strategy.py          # Scaled strategy
├── scaled_executor.py          # Scaled executor
├── scaled_order_tracker.py     # Scaled persistence
├── vwap_strategy.py            # VWAP strategy
├── vwap_executor.py            # VWAP executor
├── conditional_orders.py       # Conditional order types
├── conditional_executor.py     # Conditional executor
├── conditional_order_tracker.py # Conditional persistence
├── tests/                      # Test suite
├── logs/                       # Application logs (auto-generated)
├── twap_data/                  # TWAP order data (auto-generated)
├── scaled_data/                # Scaled order data (auto-generated)
└── conditional_data/           # Conditional order data (auto-generated)
```

## Testing

```bash
pip install -r requirements-dev.txt

pytest                           # All tests
pytest --cov=. --cov-report=html # With coverage
pytest -m unit                   # Unit tests only
pytest -m public_api             # Public API tests (no auth needed)
pytest -m vcr                    # VCR replay tests (offline)
```

See [CLAUDE.md](CLAUDE.md) for detailed testing infrastructure documentation.

## API Documentation

- [Coinbase Advanced Trade Docs](https://docs.cdp.coinbase.com/advanced-trade/docs/welcome/)
- [Python SDK](https://github.com/coinbase/coinbase-advanced-py)
- [SDK Reference](COINBASE_SDK_REFERENCE.md)

## Disclaimer

This software is for educational and personal use only. Cryptocurrency trading involves substantial risk of loss. The authors are not responsible for any financial losses incurred through use of this software. Always test with small amounts first.

Use at your own risk. This is not financial advice.
