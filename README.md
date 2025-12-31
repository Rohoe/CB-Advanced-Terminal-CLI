# Coinbase Advanced Trading Terminal

A Python-based command-line trading terminal for Coinbase Advanced Trade API with support for limit orders and Time-Weighted Average Price (TWAP) trading strategies.

## Features

- **Portfolio Management**: View account balances and USD valuations
- **Limit Orders**: Place and manage limit orders across all trading pairs
- **TWAP Orders**: Execute large orders over time to minimize market impact
  - Configurable number of slices and duration
  - Multiple price execution modes (limit, bid, mid, ask)
  - Detailed execution statistics and fill tracking
  - Automatic order persistence and recovery
- **Order Management**: View and cancel active orders
- **Rate Limiting**: Built-in token bucket rate limiter to prevent API throttling
- **Comprehensive Logging**: Detailed logging to files for audit and debugging
- **Intelligent Caching**: Optimized API usage through strategic caching

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

   Edit `keys.py` and add your Coinbase API key:
   ```python
   import getpass

   class Keys:
       api_key = "your-api-key-here"
       api_secret = getpass.getpass()
   ```

   **SECURITY WARNING**: Never commit your actual API credentials to version control. The API secret is prompted at runtime for security.

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
python app.py
```

You'll be prompted to enter your API secret. The terminal will then display a menu with available options.

### Main Menu Options

1. **View Portfolio Balances** - Display all account balances with USD valuations
2. **Place a Limit Order** - Execute a single limit order
3. **Place a TWAP Order** - Execute a time-weighted average price order
4. **Check TWAP Order Fills** - View detailed execution statistics for TWAP orders
5. **Show and Cancel Active Orders** - Manage open orders
6. **Exit** - Safely shutdown the terminal

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

## Project Structure

```
CB-Advanced-Terminal/
├── app.py              # Main trading terminal application
├── twap_tracker.py     # TWAP order persistence and tracking
├── keys.py             # API credentials (DO NOT COMMIT)
├── requirements.txt    # Python dependencies
├── CLAUDE.md          # Developer documentation
├── README.md          # This file
├── logs/              # Application logs (auto-generated)
└── twap_data/         # TWAP order persistence (auto-generated)
    ├── orders/        # TWAP order metadata
    └── fills/         # Order fill information
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

- **Never commit `keys.py` with real credentials** - Use `.gitignore`
- API secret is prompted at runtime and never stored
- API keys should have minimal required permissions
- Use separate API keys for testing vs production trading
- Regularly rotate API credentials
- Monitor API usage in Coinbase dashboard

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

## API Documentation

- Coinbase Advanced Trade Docs: https://docs.cdp.coinbase.com/advanced-trade/docs/welcome/
- Python SDK: https://github.com/coinbase/coinbase-advanced-py
- SDK Overview: https://docs.cdp.coinbase.com/advanced-trade/docs/sdk-overview

## Disclaimer

This software is for educational and personal use only. Cryptocurrency trading involves substantial risk of loss. The authors are not responsible for any financial losses incurred through use of this software. Always test with small amounts first and understand the risks involved.

Use at your own risk. This is not financial advice.
