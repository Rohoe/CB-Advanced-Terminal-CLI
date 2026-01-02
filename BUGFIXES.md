# Bug Fixes - 2026-01-02

## Issue #1: Order History API Error

**Problem:**
```
TypeError: list_orders() got an unexpected keyword argument 'limit'
```

**Root Cause:**
The Coinbase API client's `list_orders()` method only accepts `order_ids` parameter, not `limit`, `cursor`, `product_id`, or `order_status` parameters.

**Solution:**
Modified `get_order_history()` method to:
1. Fetch all orders without parameters
2. Apply filters (product_id, order_status, limit) in Python after fetching
3. This approach works but may be slower for accounts with many orders

**Files Changed:**
- `app.py` - lines 1096-1145

**Code Change:**
```python
# Before: Tried to pass unsupported parameters to API
orders_response = self.client.list_orders(
    limit=min(250, limit - len(all_orders)),
    cursor=cursor,
    product_id=product_id,
    order_status=order_status
)

# After: Fetch all orders and filter in Python
orders_response = self.client.list_orders()
# ... then filter results in Python loop
```

## Issue #2: Cancellation Shows Error Messages

**Problem:**
When user cancels with 'q', 'cancel', or 'back', the application showed error messages and stack traces instead of gracefully handling the cancellation.

**Example:**
```
2026-01-02 14:22:52,125 - ERROR - app.py:803 - Error in place_limit_order: Operation cancelled by user
Traceback (most recent call last):
  ...
CancelledException: Operation cancelled by user

Error placing order: Operation cancelled by user
```

**Root Cause:**
The generic `Exception` handler was catching `CancelledException` and logging it as an error.

**Solution:**
1. Added explicit `CancelledException` handlers before generic `Exception` handlers
2. Re-raise `CancelledException` to let outer handler deal with it
3. Changed error messages to info messages with color coding
4. Replaced `print()` calls with `print_warning()` and `print_info()` for consistency

**Files Changed:**
- `app.py` - lines 612-627, 802-809, 1630-1642

**Code Change:**
```python
# Before: CancelledException caught by generic Exception handler
except Exception as e:
    logging.error(f"Error in place_limit_order: {str(e)}", exc_info=True)
    print(f"\nError placing order: {str(e)}")
    return None

# After: Explicit CancelledException handler that re-raises
except CancelledException:
    # Already handled in outer try-catch, just re-raise
    raise
except Exception as e:
    logging.error(f"Error in place_limit_order: {str(e)}", exc_info=True)
    print_error(f"\nError placing order: {str(e)}")
    return None
```

## Testing

Both fixes have been applied and should now work correctly:

1. **Order History**: Now fetches all orders and filters them in Python. Works with the actual Coinbase API limitations.

2. **Cancellation**: User can now cancel any operation with 'q', 'cancel', or 'back' and see a friendly info message instead of error output.

## Future Improvements

### Order History Optimization
If performance becomes an issue with large order histories, consider:
- Implementing caching of order history with TTL
- Adding date range filters (if supported by API)
- Pagination in the UI (show 20 at a time with next/prev)

### API Client Enhancement
Consider updating `api_client.py` to better document actual API parameter support based on Coinbase SDK capabilities.
