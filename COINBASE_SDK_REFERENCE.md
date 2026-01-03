# Coinbase Advanced Trade Python SDK - Complete API Reference

This document provides comprehensive method signatures and response structures for the `coinbase-advanced-py` Python SDK.

## Table of Contents
1. [Order Methods](#order-methods)
2. [Account Methods](#account-methods)
3. [Product Methods](#product-methods)
4. [Fees Methods](#fees-methods)
5. [Response Objects](#response-objects)
6. [Common Types](#common-types)

---

## Order Methods

### create_order()

Generic order creation with optional attached TP/SL bracket.

```python
def create_order(
    self,
    client_order_id: str,
    product_id: str,
    side: str,
    order_configuration: dict,
    self_trade_prevention_id: Optional[str] = None,
    leverage: Optional[str] = None,
    margin_type: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    **kwargs,
) -> CreateOrderResponse
```

**Parameters:**
- `client_order_id`: Client-generated unique order identifier for idempotency
- `product_id`: Trading pair (e.g., "BTC-USD")
- `side`: Order side - "BUY" or "SELL"
- `order_configuration`: Main order config dict (e.g., `{"limit_limit_gtc": {"baseSize": "0.01", "limitPrice": "50000"}}`)
- `self_trade_prevention_id`: Optional ID to prevent self-trading
- `leverage`: Optional leverage multiplier
- `margin_type`: Optional margin type
- `retail_portfolio_id`: Optional portfolio identifier
- `**kwargs`: Additional parameters

**Returns:** `CreateOrderResponse`

**Example order_configuration:**
```python
order_configuration = {
    "limit_limit_gtc": {
        "baseSize": "0.01",
        "limitPrice": "50000"
    }
}
```

---

### limit_order_gtc()

Place a limit order (Good-Til-Cancelled).

```python
def limit_order_gtc(
    self,
    client_order_id: str,
    product_id: str,
    side: str,
    base_size: str,
    limit_price: str,
    post_only: bool = False,
    self_trade_prevention_id: Optional[str] = None,
    leverage: Optional[str] = None,
    margin_type: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    **kwargs,
) -> CreateOrderResponse
```

**Parameters:**
- `client_order_id`: Unique order identifier
- `product_id`: Trading pair
- `side`: "BUY" or "SELL"
- `base_size`: Order size in base currency (as string)
- `limit_price`: Limit price (as string)
- `post_only`: If True, order will only be posted if it doesn't immediately match (default: False)
- Other parameters same as `create_order`

**Returns:** `CreateOrderResponse`

**Convenience methods:**
- `limit_order_gtc_buy()` - Same parameters minus `side` (hardcoded to "BUY")
- `limit_order_gtc_sell()` - Same parameters minus `side` (hardcoded to "SELL")

---

### stop_limit_order_gtc()

Place a stop-limit order (Good-Til-Cancelled).

```python
def stop_limit_order_gtc(
    self,
    client_order_id: str,
    product_id: str,
    side: str,
    base_size: str,
    limit_price: str,
    stop_price: str,
    stop_direction: str,
    self_trade_prevention_id: Optional[str] = None,
    leverage: Optional[str] = None,
    margin_type: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    **kwargs,
) -> CreateOrderResponse
```

**Parameters:**
- `client_order_id`: Unique order identifier
- `product_id`: Trading pair
- `side`: "BUY" or "SELL"
- `base_size`: Order size as string
- `limit_price`: Execution price after trigger
- `stop_price`: Trigger price
- `stop_direction`: "STOP_DIRECTION_STOP_UP" or "STOP_DIRECTION_STOP_DOWN"

**Stop Direction Guide:**
- `STOP_DIRECTION_STOP_UP`: Triggers when price moves UP (for buy stop-loss or sell take-profit)
- `STOP_DIRECTION_STOP_DOWN`: Triggers when price moves DOWN (for sell stop-loss or buy take-profit)

**Returns:** `CreateOrderResponse`

**Convenience methods:**
- `stop_limit_order_gtc_buy()` - Same parameters minus `side`
- `stop_limit_order_gtc_sell()` - Same parameters minus `side`
- `stop_limit_order_gtd()`, `stop_limit_order_gtd_buy()`, `stop_limit_order_gtd_sell()` - GTD variants with end_time parameter

---

### trigger_bracket_order_gtc()

Place a bracket order (TP/SL for existing position).

**IMPORTANT:** This creates TP/SL for an EXISTING position. For entry + TP/SL, use `create_order()` with `attached_order_configuration`.

```python
def trigger_bracket_order_gtc(
    self,
    client_order_id: str,
    product_id: str,
    side: str,
    base_size: str,
    limit_price: str,
    stop_trigger_price: str,
    self_trade_prevention_id: Optional[str] = None,
    leverage: Optional[str] = None,
    margin_type: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    **kwargs,
) -> CreateOrderResponse
```

**Parameters:**
- `client_order_id`: Unique order identifier
- `product_id`: Trading pair
- `side`: "BUY" or "SELL" (side of the POSITION, not the bracket orders)
- `base_size`: Position size as string
- `limit_price`: Take-profit price
- `stop_trigger_price`: Stop-loss trigger price

**Returns:** `CreateOrderResponse`

**Convenience methods:**
- `trigger_bracket_order_gtc_buy()` - Same parameters minus `side`
- `trigger_bracket_order_gtc_sell()` - Same parameters minus `side`
- `trigger_bracket_order_gtd()`, etc. - GTD variants

---

### cancel_orders()

Cancel one or more orders.

```python
def cancel_orders(
    self,
    order_ids: List[str],
    **kwargs
) -> CancelOrdersResponse
```

**Parameters:**
- `order_ids`: List of order IDs to cancel

**Returns:** `CancelOrdersResponse` with results list indicating success/failure for each order

---

### list_orders()

List orders with optional filters.

```python
def list_orders(
    self,
    order_ids: Optional[List[str]] = None,
    product_ids: Optional[List[str]] = None,
    order_status: Optional[List[str]] = None,
    limit: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    order_types: Optional[str] = None,
    order_side: Optional[str] = None,
    cursor: Optional[str] = None,
    product_type: Optional[str] = None,
    order_placement_source: Optional[str] = None,
    contract_expiry_type: Optional[str] = None,
    asset_filters: Optional[List[str]] = None,
    retail_portfolio_id: Optional[str] = None,
    time_in_forces: Optional[str] = None,
    sort_by: Optional[str] = None,
    **kwargs,
) -> ListOrdersResponse
```

**Parameters:**
- `order_ids`: Filter by specific order IDs
- `product_ids`: Filter by trading pairs
- `order_status`: Filter by status (e.g., ["OPEN", "FILLED", "CANCELLED"])
- `limit`: Maximum number of orders to return
- `start_date`: Start date filter (ISO 8601 format)
- `end_date`: End date filter
- `order_types`: Order type filter
- `order_side`: "BUY" or "SELL"
- `cursor`: Pagination cursor
- `product_type`: Product type (e.g., "FUTURE")
- Other filters as needed

**Returns:** `ListOrdersResponse` with orders array and pagination info

---

### get_fills()

Get order fills (executions).

```python
def get_fills(
    self,
    order_ids: Optional[List[str]] = None,
    trade_ids: Optional[List[str]] = None,
    product_ids: Optional[List[str]] = None,
    start_sequence_timestamp: Optional[str] = None,
    end_sequence_timestamp: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
    sort_by: Optional[str] = None,
    **kwargs,
) -> ListFillsResponse
```

**Parameters:**
- `order_ids`: Filter by order IDs
- `trade_ids`: Filter by trade IDs
- `product_ids`: Filter by trading pairs
- `start_sequence_timestamp`: Start timestamp
- `end_sequence_timestamp`: End timestamp
- `retail_portfolio_id`: Portfolio filter
- `limit`: Max number of fills
- `cursor`: Pagination cursor
- `sort_by`: Sort order

**Returns:** `ListFillsResponse` with fills array

---

### Other Order Methods

**Market Orders:**
- `market_order()`, `market_order_buy()`, `market_order_sell()`

**Limit IOC (Immediate or Cancel):**
- `limit_order_ioc()`, `limit_order_ioc_buy()`, `limit_order_ioc_sell()`

**Limit GTD (Good-Til-Date):**
- `limit_order_gtd()`, `limit_order_gtd_buy()`, `limit_order_gtd_sell()`

**Limit FOK (Fill or Kill):**
- `limit_order_fok()`, `limit_order_fok_buy()`, `limit_order_fok_sell()`

**Order Management:**
- `get_order()` - Get single order by ID
- `edit_order()` - Edit order size or price
- `preview_edit_order()` - Simulate edit
- `preview_order()` - Simulate order creation
- `close_position()` - Close position

---

## Account Methods

### get_accounts()

Get list of accounts with pagination.

```python
def get_accounts(
    self,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
    retail_portfolio_id: Optional[str] = None,
    **kwargs,
) -> ListAccountsResponse
```

**Parameters:**
- `limit`: Maximum number of accounts to return
- `cursor`: Pagination cursor
- `retail_portfolio_id`: Portfolio filter

**Returns:** `ListAccountsResponse`

---

### get_account()

Get single account by UUID.

```python
def get_account(
    self,
    account_uuid: str,
    **kwargs
) -> GetAccountResponse
```

**Parameters:**
- `account_uuid`: Account UUID identifier

**Returns:** `GetAccountResponse`

---

## Product Methods

### get_products()

Get list of all available products.

```python
def get_products(
    self,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    product_type: Optional[str] = None,
    product_ids: Optional[List[str]] = None,
    contract_expiry_type: Optional[str] = None,
    expiring_contract_status: Optional[str] = None,
    get_tradability_status: Optional[bool] = False,
    get_all_products: Optional[bool] = False,
    **kwargs,
) -> ListProductsResponse
```

**Parameters:**
- `limit`: Max products to return
- `offset`: Offset for pagination
- `product_type`: Filter by type
- `product_ids`: Filter by specific product IDs
- `contract_expiry_type`: Contract expiry filter
- `expiring_contract_status`: Contract status filter
- `get_tradability_status`: Include tradability info
- `get_all_products`: Get all products (ignores limit)

**Returns:** `ListProductsResponse`

---

### get_product()

Get single product information.

```python
def get_product(
    self,
    product_id: str,
    get_tradability_status: Optional[bool] = False,
    **kwargs
) -> GetProductResponse
```

**Parameters:**
- `product_id`: Product identifier (e.g., "BTC-USD")
- `get_tradability_status`: Include tradability info

**Returns:** `GetProductResponse`

---

### get_product_book()

Get product order book (bids and asks).

```python
def get_product_book(
    self,
    product_id: str,
    limit: Optional[int] = None,
    aggregation_price_increment: Optional[str] = None,
    **kwargs,
) -> GetProductBookResponse
```

**Parameters:**
- `product_id`: Product identifier
- `limit`: Number of price levels to return
- `aggregation_price_increment`: Price aggregation level

**Returns:** `GetProductBookResponse`

---

## Fees Methods

### get_transaction_summary()

Get transaction summary including fee tiers and volumes.

```python
def get_transaction_summary(
    self,
    product_type: Optional[str] = None,
    contract_expiry_type: Optional[str] = None,
    product_venue: Optional[str] = None,
    **kwargs
) -> GetTransactionSummaryResponse
```

**Parameters:**
- `product_type`: Filter by product type
- `contract_expiry_type`: Filter by contract expiry
- `product_venue`: Filter by product venue

**Returns:** `GetTransactionSummaryResponse`

---

## Response Objects

### CreateOrderResponse

Returned by all order creation methods.

```python
class CreateOrderResponse(BaseResponse):
    success: bool
    failure_reason: Optional[Dict[str, Any]]
    order_id: Optional[str]
    success_response: Optional[CreateOrderSuccess]
    error_response: Optional[CreateOrderError]
    order_configuration: Optional[OrderConfiguration]
```

**Fields:**
- `success` (bool): Whether order was created successfully
- `failure_reason` (dict, optional): Failure details if unsuccessful
- `order_id` (str, optional): Unique order identifier if successful
- `success_response` (CreateOrderSuccess, optional): Success details
  - `order_id`: Order UUID
  - `product_id`: Trading pair
  - `side`: "BUY" or "SELL"
  - `client_order_id`: Client-provided ID
- `error_response` (CreateOrderError, optional): Error details
  - `error`: Error code (e.g., "UNKNOWN_FAILURE_REASON")
  - `message`: Human-readable error message
  - `error_details`: Detailed error description
  - `preview_failure_reason`: Preview-specific failure
  - `new_order_failure_reason`: Order creation failure reason
- `order_configuration` (OrderConfiguration, optional): Order config used

**JSON Example:**
```json
{
  "success": true,
  "success_response": {
    "order_id": "11111-00000-000000",
    "product_id": "BTC-USD",
    "side": "BUY",
    "client_order_id": "0000-00000-000000"
  },
  "order_configuration": {
    "limit_limit_gtc": {
      "base_size": "0.01",
      "limit_price": "50000.00"
    }
  }
}
```

---

### CancelOrdersResponse

Returned by `cancel_orders()`.

```python
class CancelOrdersResponse(BaseResponse):
    results: Optional[List[CancelOrderObject]]
```

**Fields:**
- `results` (list): Array of cancellation results
  - Each object contains:
    - `success` (bool): Whether cancellation succeeded
    - `failure_reason` (str): Reason if failed (e.g., "UNKNOWN_CANCEL_FAILURE_REASON")
    - `order_id` (str): Order ID that was attempted to cancel

**JSON Example:**
```json
{
  "results": [
    {
      "success": true,
      "order_id": "0000-000000-000000"
    },
    {
      "success": false,
      "failure_reason": "UNKNOWN_CANCEL_FAILURE_REASON",
      "order_id": "1111-111111-111111"
    }
  ]
}
```

---

### ListOrdersResponse

Returned by `list_orders()`.

```python
class ListOrdersResponse(BaseResponse):
    orders: List[Order]
    sequence: Optional[int]
    has_next: bool
    cursor: Optional[str]
```

**Fields:**
- `orders` (list): Array of Order objects
- `sequence` (int, optional): Sequence number
- `has_next` (bool): Whether more pages exist
- `cursor` (str, optional): Pagination cursor for next page

**Order Object Fields** (based on API documentation):
- `order_id`: Unique order identifier
- `product_id`: Trading pair
- `user_id`: User identifier
- `side`: "BUY" or "SELL"
- `order_configuration`: Order-type-specific configuration object
- `status`: Order status (e.g., "OPEN", "FILLED", "CANCELLED")
- `created_time`: Order creation timestamp
- `filled_size`: Amount filled (string)
- `average_filled_price`: Average execution price (string)
- Additional fields may include:
  - `total_value_after_fees`
  - `total_fees`
  - `completion_percentage`
  - `time_in_force`

**Order Configuration Types:**
The `order_configuration` object can be one of:
- `market_market_ioc`: Market order Immediate or Cancel
- `limit_limit_gtc`: Limit order Good Till Cancelled
- `limit_limit_gtd`: Limit order Good Till Date
- `limit_limit_fok`: Limit order Fill or Kill
- `stop_limit_stop_limit_gtc`: Stop-limit GTC
- `stop_limit_stop_limit_gtd`: Stop-limit GTD
- `trigger_bracket_gtc`: Bracket order GTC
- `twap_limit_gtd`: TWAP order

---

### ListFillsResponse

Returned by `get_fills()`.

```python
class ListFillsResponse(BaseResponse):
    fills: Optional[List[Fill]]
    cursor: Optional[str]
```

**Fields:**
- `fills` (list): Array of Fill objects
- `cursor` (str, optional): Pagination cursor

**Fill Object Fields:**
- `entry_id`: Unique fill entry identifier
- `trade_id`: Trade identifier
- `order_id`: Associated order ID
- `trade_time`: Execution timestamp (ISO 8601)
- `trade_type`: Type (e.g., "FILL")
- `price`: Execution price (string)
- `size`: Fill size (string)
- `commission`: Commission/fee amount (string)
- `product_id`: Trading pair
- `sequence_timestamp`: Sequence timestamp
- `liquidity_indicator`: "MAKER" or "TAKER" or "UNKNOWN_LIQUIDITY_INDICATOR"
- `size_in_quote`: Boolean - if size is in quote currency
- `user_id`: User identifier
- `side`: "BUY" or "SELL"
- `retail_portfolio_id`: Portfolio ID
- `fillSource`: Fill source
- `commission_detail_total`: Detailed commission breakdown object
  - `total_commission`: Total commission
  - `gst_commission`: GST component
  - `withholding_commission`: Withholding component
  - `client_commission`: Client component

**JSON Example:**
```json
{
  "fills": [
    {
      "entry_id": "22222-2222222-22222222",
      "trade_id": "1111-11111-111111",
      "order_id": "0000-000000-000000",
      "trade_time": "2021-05-31T09:59:59.000Z",
      "trade_type": "FILL",
      "price": "10000.00",
      "size": "0.001",
      "commission": "1.25",
      "product_id": "BTC-USD",
      "liquidity_indicator": "MAKER",
      "side": "BUY"
    }
  ],
  "cursor": "789100"
}
```

---

### ListAccountsResponse

Returned by `get_accounts()`.

```python
class ListAccountsResponse(BaseResponse):
    accounts: Optional[List[Account]]
    has_next: Optional[bool]
    cursor: Optional[str]
    size: Optional[int]
```

**Fields:**
- `accounts` (list): Array of Account objects
- `has_next` (bool): Whether more pages exist
- `cursor` (str): Pagination cursor
- `size` (int): Number of accounts returned

---

### GetAccountResponse

Returned by `get_account()`.

```python
class GetAccountResponse(BaseResponse):
    account: Optional[Account]
```

**Fields:**
- `account` (Account): Single account object

**Account Object Fields:**
- `uuid`: Account UUID identifier
- `name`: Account name
- `currency`: Currency symbol (e.g., "USD", "BTC")
- `available_balance`: Object with `value` and `currency` fields
  - `value`: Available balance amount (string)
  - `currency`: Currency code
- `hold`: Balance on hold
- `default`: Boolean - if default account
- `active`: Boolean - if account is active
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp
- `deleted_at`: Deletion timestamp (if deleted)
- `type`: Account type (e.g., "FIAT", "CRYPTO")
- `ready`: Boolean - if account is ready

---

### GetProductResponse

Returned by `get_product()`.

```python
class GetProductResponse(BaseResponse):
    product_id: str
    price: str
    price_percentage_change_24h: str
    volume_24h: str
    volume_percentage_change_24h: str
    base_increment: str
    quote_increment: str
    quote_min_size: str
    quote_max_size: str
    base_min_size: str
    base_max_size: str
    base_name: str
    quote_name: str
    watched: bool
    is_disabled: bool
    new: bool
    cancel_only: bool
    limit_only: bool
    post_only: bool
    trading_disabled: bool
    auction_mode: bool
    product_type: Optional[str]
    quote_currency_id: Optional[str]
    base_currency_id: Optional[str]
    # ... additional optional fields
```

**Key Fields:**
- `product_id`: Trading pair identifier
- `price`: Current price
- `price_percentage_change_24h`: 24h price change %
- `volume_24h`: 24h trading volume
- `base_increment`: Minimum base size increment
- `quote_increment`: Minimum quote price increment
- `base_min_size`: Minimum order size
- `base_max_size`: Maximum order size
- Trading flags: `is_disabled`, `cancel_only`, `limit_only`, `post_only`, `trading_disabled`

---

### ListProductsResponse

Returned by `get_products()`.

```python
class ListProductsResponse(BaseResponse):
    products: Optional[List[Product]]
    num_products: Optional[int]
```

**Fields:**
- `products` (list): Array of Product objects (same structure as GetProductResponse)
- `num_products` (int): Total number of products

---

### GetProductBookResponse

Returned by `get_product_book()`.

```python
class GetProductBookResponse(BaseResponse):
    pricebook: PriceBook
    last: Optional[str]
    mid_market: Optional[str]
    spread_bps: Optional[str]
    spread_absolute: Optional[str]
```

**Fields:**
- `pricebook` (PriceBook): Order book snapshot
  - `bids` (list): Array of bid price levels
    - Each: `{"price": "50000.00", "size": "0.5"}`
  - `asks` (list): Array of ask price levels
    - Each: `{"price": "50001.00", "size": "0.3"}`
- `last` (str): Last trade identifier
- `mid_market` (str): Midpoint between best bid and ask
- `spread_bps` (str): Bid-ask spread in basis points
- `spread_absolute` (str): Absolute spread value

---

### GetTransactionSummaryResponse

Returned by `get_transaction_summary()`.

```python
class GetTransactionSummaryResponse(BaseResponse):
    total_volume: float
    total_fees: float
    fee_tier: FeeTier
    margin_rate: Optional[Dict[str, Any]]
    goods_and_services_tax: Optional[Dict[str, Any]]
    advanced_trade_only_volumes: Optional[float]
    advanced_trade_only_fees: Optional[float]
    coinbase_pro_volume: Optional[float]
    coinbase_pro_fees: Optional[float]
    total_balance: Optional[str]
    has_promo_fee: Optional[bool]
```

**Fields:**
- `total_volume` (float): Total trading volume
- `total_fees` (float): Total fees paid
- `fee_tier` (FeeTier): Current fee tier information
  - `pricing_tier` (str): Tier name
  - `usd_from`, `usd_to` (str): USD volume range
  - `taker_fee_rate` (str): Taker fee percentage (e.g., "0.006" for 0.6%)
  - `maker_fee_rate` (str): Maker fee percentage (e.g., "0.004" for 0.4%)
  - `aop_from`, `aop_to` (str): AOP range boundaries
- `margin_rate` (dict, optional): Margin rate info
- `goods_and_services_tax` (dict, optional): Tax details
- `advanced_trade_only_volumes` (float, optional): Advanced Trade volume
- `advanced_trade_only_fees` (float, optional): Advanced Trade fees
- `has_promo_fee` (bool, optional): Promotional fee status

---

## Common Types

### Amount

```python
class Amount(BaseResponse):
    value: Optional[str]
    currency: Optional[str]
```

Used for monetary values throughout the API.

---

## Response Object Access Patterns

The SDK supports both **dot notation** and **dictionary access** for response objects:

```python
# Dot notation (preferred)
accounts = client.get_accounts()
for account in accounts.accounts:
    print(account.currency)
    print(account.available_balance.value)

# Dictionary access (fallback)
print(accounts['accounts'][0]['currency'])
```

**Note:** Not every nested field has been defined for dot-notation access. Fields that are not defined are still accessible using standard bracket notation.

---

## Error Handling

All response objects inherit from `BaseResponse` which includes error handling capabilities. When an API call fails:

```python
response = client.limit_order_gtc(...)

if hasattr(response, 'success') and not response.success:
    # Order failed
    if response.error_response:
        print(f"Error: {response.error_response.error}")
        print(f"Message: {response.error_response.message}")
        print(f"Details: {response.error_response.error_details}")
```

---

## Important Notes

1. **String Types for Numeric Values**: All price and size parameters are **strings**, not floats. This prevents floating-point precision errors:
   ```python
   # Correct
   client.limit_order_gtc(base_size="0.01", limit_price="50000.00")

   # Incorrect
   client.limit_order_gtc(base_size=0.01, limit_price=50000.00)
   ```

2. **Idempotency**: Use unique `client_order_id` values to prevent duplicate orders. The same `client_order_id` will return the original order if called again.

3. **Rate Limiting**: The SDK does NOT handle rate limiting automatically. Implement your own rate limiter (25 requests/second recommended).

4. **Pagination**: Methods returning lists (accounts, orders, fills) support pagination via `cursor` and `has_next` fields.

5. **Order Status Values**: Common status values include:
   - `OPEN`: Active order
   - `FILLED`: Completely filled
   - `CANCELLED`: Cancelled by user
   - `EXPIRED`: Expired (GTD orders)
   - `FAILED`: Order failed

6. **Liquidity Indicators**: Fill objects include liquidity indicator:
   - `MAKER`: Order provided liquidity (lower fees)
   - `TAKER`: Order removed liquidity (higher fees)
   - `UNKNOWN_LIQUIDITY_INDICATOR`: Unknown

7. **Timestamps**: All timestamps use ISO 8601 format: `"2021-05-31T09:59:59.000Z"`

---

## Sources

- [Coinbase Advanced Python SDK - GitHub](https://github.com/coinbase/coinbase-advanced-py)
- [Coinbase Advanced API Python SDK Documentation](https://coinbase.github.io/coinbase-advanced-py/)
- [Coinbase Advanced Trade API Reference](https://docs.cdp.coinbase.com/advanced-trade/docs/welcome)
- [Create Order API Documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order)
- [List Orders API Documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-orders)
- [List Fills API Documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-fills)
- [Get Transaction Summary API Documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/fees/get-transaction-summary)

---

## Version Information

This documentation is based on:
- SDK: `coinbase-advanced-py` (latest version as of January 2026)
- API: Coinbase Advanced Trade API v3
- Documentation Date: January 3, 2026
