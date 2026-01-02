# Coinbase Advanced Trading Terminal

A Python-based command-line trading terminal for Coinbase Advanced Trade API with support for limit orders and Time-Weighted Average Price (TWAP) trading strategies.

## Features

- **Portfolio Management**: View account balances and USD valuations with color-coded display
- **Limit Orders**: Place and manage limit orders across all trading pairs
  - Enhanced order preview with estimated fees (maker/taker rates)
  - Total cost/proceeds calculation including fees
  - Color-coded order confirmations
- **TWAP Orders**: Execute large orders over time to minimize market impact
  - Configurable number of slices and duration
  - Multiple price execution modes (limit, bid, mid, ask)
  - Detailed execution statistics and fill tracking
  - Automatic order persistence and recovery
- **Order History**: View historical orders with advanced filtering
  - Filter by product, status, or both
  - Color-coded order sides (BUY/SELL) and statuses
  - Summary statistics (filled, cancelled, etc.)
- **Order Management**: View and cancel active orders with color-coded status
- **Rate Limiting**: Built-in token bucket rate limiter to prevent API throttling
- **Comprehensive Logging**: Detailed logging to files for audit and debugging
- **Intelligent Caching**: Optimized API usage through strategic caching
- **Enhanced UI**: Color-coded terminal output for better readability
  - Green for success messages and positive values
  - Red for errors and warnings
  - Cyan for informational messages
  - Magenta for highlighted content

## Prerequisites

- Python 3.7 or higher
- Coinbase Advanced Trade API credentials (API key and secret)
- Active Coinbase account with trading enabled

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd CB-Advanced-Terminal
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API credentials**:

   The application uses environment variables for secure credential management.

   **Option A: Environment Variables (Recommended for Runtime Secret Entry)**
   ```bash
   # Set your API key
   export COINBASE_API_KEY="organizations/your-org-id/apiKeys/your-key-id"

   # Don't set API_SECRET - you'll be prompted when running the app
   python app.py
   ```

   **Option B: .env File (For Persistent Setup)**
   ```bash
   # Copy the example file
   cp .env.example .env

   # Edit .env with your API key only
   nano .env
   ```

   Add to `.env`:
   ```
   COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
   # Leave COINBASE_API_SECRET unset to be prompted at runtime
   ```

   Then run:
   ```bash
   # Load environment variables
   set -a && source .env && set +a

   # Run the application (will prompt for secret)
   python app.py
   ```

   **SECURITY NOTE**:
   - API secret is prompted at runtime and never stored to disk
   - The `.env` file is automatically ignored by git
   - Never commit actual credentials to version control

## Getting API Credentials

1. Log in to [Coinbase Advanced Trade](https://www.coinbase.com/advanced-trade)
2. Navigate to Settings → API
3. Create a new API key with appropriate permissions:
   - View account balance
   - Trade
   - View orders
4. Save your API key and secret securely

For detailed instructions, see: https://docs.cdp.coinbase.com/advanced-trade/docs/auth

## Usage

### Starting the Terminal

```bash
# Make sure your API key is set
export COINBASE_API_KEY="organizations/your-org-id/apiKeys/your-key-id"

# Run the application
python app.py
```

When you start the application:
1. You'll be prompted to enter your API secret (secure, hidden input)
2. The app will authenticate with Coinbase
3. Your account balances will load
4. The main menu will appear

### Main Menu Options

1. **View Portfolio Balances** - Display all account balances with USD valuations
2. **Place a Limit Order** - Execute a single limit order with fee preview
3. **Place a TWAP Order** - Execute a time-weighted average price order
4. **Check TWAP Order Fills** - View detailed execution statistics for TWAP orders
5. **Show and Cancel Active Orders** - Manage open orders
6. **View Order History** - View past orders with filtering options

### Placing a TWAP Order

TWAP orders split a large order into smaller "slices" executed over time:

1. Select **option 3** from the main menu
2. Choose your trading pair from the top markets
3. Specify order side (BUY or SELL)
4. Enter limit price (maximum buy price or minimum sell price)
5. Enter total order size
6. Configure TWAP parameters:
   - Duration in minutes
   - Number of slices
7. Select price execution mode:
   - Original limit price (static)
   - Current market bid (dynamic)
   - Current market mid (dynamic)
   - Current market ask (dynamic)

The terminal will execute slices at regular intervals and provide real-time progress updates.

### Example TWAP Order

```
Market: BTC-USDC
Side: BUY
Total Size: 0.1 BTC
Limit Price: $100,000
Duration: 60 minutes
Slices: 12
Price Mode: Market mid

Result: 12 orders of ~0.00833 BTC each, placed every 5 minutes
```

### Viewing Order History

Access comprehensive order history with flexible filtering:

1. Select **option 6** from the main menu
2. Choose filter criteria:
   - All orders (last 100)
   - Filter by specific product
   - Filter by order status (FILLED, CANCELLED, EXPIRED, FAILED)
   - Combine product and status filters
3. View color-coded results with:
   - Order timestamps
   - Product, side (BUY/SELL), size, and price
   - Calculated order value
   - Order status
   - Summary statistics

### Enhanced Order Preview

When placing limit orders, you'll now see:
- Estimated maker fee (0.4% default)
- Estimated taker fee (0.6% default)
- Total cost/proceeds including fees
- Best/worst case scenarios
- Color-coded order summary

## Project Structure

```
CB-Advanced-Terminal/
├── app.py              # Main trading terminal application
├── twap_tracker.py     # TWAP order persistence and tracking
├── config.py           # Secure configuration management
├── config_manager.py   # Application configuration
├── validators.py       # Input validation
├── api_client.py       # API client abstraction
├── storage.py          # Storage abstraction
├── ui_helpers.py       # Terminal UI color utilities
├── requirements.txt    # Python dependencies
├── requirements-dev.txt # Testing dependencies
├── .env.example        # Environment variable template
├── .env               # Your credentials (git-ignored, DO NOT COMMIT)
├── CLAUDE.md          # Developer documentation
├── README.md          # This file
├── TESTING.md         # Testing guide
├── TODO.md            # Future improvements
├── ENHANCEMENTS.md    # Future enhancement ideas
├── logs/              # Application logs (auto-generated)
├── twap_data/         # TWAP order persistence (auto-generated)
│   ├── orders/        # TWAP order metadata
│   └── fills/         # Order fill information
└── tests/             # Test suite
    ├── conftest.py    # Test fixtures
    ├── test_validators.py
    ├── test_rate_limiter.py
    ├── test_twap_tracker.py
    ├── integration/   # Integration tests
    └── mocks/         # Mock implementations
```

## Logging

All trading activity is logged to timestamped files in the `logs/` directory:

- File logs: DEBUG level with full details
- Console logs: ERROR level only (minimal output)
- Log format: `YYYYMMDD_HHMMSS.log`

Check logs for detailed execution information, API interactions, and troubleshooting.

## TWAP Order Persistence

TWAP orders and their fills are automatically saved to JSON files in `twap_data/`:

- Orders can be recovered and analyzed after application restart
- Detailed execution statistics available for historical analysis
- Use "Check TWAP Order Fills" menu option to view saved orders

## Rate Limiting

The terminal implements a token bucket rate limiter to prevent API throttling:

- Default: 25 requests/second with burst capacity of 50
- Configurable in `app.py` CONFIG dictionary
- All API calls automatically rate-limited

## Important Security Notes

- **Never commit `.env` with real credentials** - It's automatically git-ignored
- **Never hardcode credentials in source files**
- API secret is prompted at runtime and never stored to disk
- API keys should have minimal required permissions
- Use separate API keys for testing vs production trading
- Regularly rotate API credentials
- Monitor API usage in Coinbase dashboard
- Environment variables are loaded securely via `config.py`

## Error Handling

The terminal includes comprehensive error handling:

- Balance validation before order placement
- Order size minimum/maximum checks
- Price increment validation
- Network error recovery with retries
- Failed TWAP slice tracking and reporting

## Known Limitations

- Terminal-based UI (no graphical interface)
- Single account per session
- No support for market orders (limit orders only)
- TWAP execution continues even if application restarts (orders remain on exchange)

## Troubleshooting

**Login fails with authentication error:**
- Verify API key and secret are correct
- Check API key permissions in Coinbase dashboard
- Ensure API key is not expired or revoked

**Order placement fails:**
- Check account balance is sufficient
- Verify order size meets product minimums
- Ensure price is within reasonable spread

**Rate limit errors:**
- Reduce `rate_limit_requests` in CONFIG
- Add delays between manual operations
- Check Coinbase API status

## Testing

This project includes a comprehensive test suite. See `TESTING.md` for detailed information.

### Quick Start

```bash
# Install testing dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html
open htmlcov/index.html

# Run only unit tests
pytest -m unit
```

### Test Coverage

- **validators.py:** 90.55%
- **twap_tracker.py:** 87.10%
- **RateLimiter:** 100% (all tests passing)
- **TradingTerminal:** API response object handling, balance validation, rounding
- **87+ total tests** covering core business logic

For more information, see the [Testing Guide](TESTING.md).

## API Documentation

- Coinbase Advanced Trade Docs: https://docs.cdp.coinbase.com/advanced-trade/docs/welcome/
- Python SDK: https://github.com/coinbase/coinbase-advanced-py
- SDK Overview: https://docs.cdp.coinbase.com/advanced-trade/docs/sdk-overview

## Disclaimer

This software is for educational and personal use only. Cryptocurrency trading involves substantial risk of loss. The authors are not responsible for any financial losses incurred through use of this software. Always test with small amounts first and understand the risks involved.

Use at your own risk. This is not financial advice.
