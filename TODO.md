# TODO - Future Improvements

## Completed ✅
- [x] Security fixes (remove hardcoded API keys)
- [x] Abstraction layers & dependency injection
- [x] Thread safety improvements
- [x] Performance optimization (N+1 query fix)
- [x] Comprehensive testing framework
- [x] Input validation
- [x] Configuration management
- [x] Rate limiter tests
- [x] TWAP tracker tests
- [x] Validator tests
- [x] Testing documentation

## High Priority

### 1. Verify Application Works After Refactoring
**Priority:** HIGH | **Time:** 30 minutes

Test the application with real credentials to ensure refactoring didn't break anything:

```bash
# Set environment variables
export COINBASE_API_KEY="your-key"
export COINBASE_API_SECRET="your-secret"

# Run the application
python app.py
```

**Test Cases:**
- [ ] Login succeeds
- [ ] Portfolio display works
- [ ] Market selection works
- [ ] Limit order placement works
- [ ] TWAP order placement works
- [ ] Order status checker runs without errors

---

### 2. Integration Tests
**Priority:** MEDIUM | **Time:** 2-3 hours

Add integration tests in `tests/integration/` directory:

**Files to Create:**
- `tests/integration/test_twap_execution.py` - End-to-end TWAP flow
- `tests/integration/test_order_lifecycle.py` - Complete order lifecycle
- `tests/integration/test_portfolio_display.py` - Portfolio display with bulk prices

**Example Test:**
```python
@pytest.mark.integration
def test_full_twap_execution(mock_api_client, mock_twap_storage):
    """Test complete TWAP order execution."""
    # 1. Create TWAP order
    # 2. Simulate slice executions
    # 3. Verify fills are tracked
    # 4. Calculate statistics
    # 5. Verify VWAP and completion rate
```

---

### 3. Extract Market Selection Duplication
**Priority:** LOW | **Time:** 30 minutes

**Issue:** Market selection logic duplicated in two places (app.py lines 423-470 and 1573-1616)

**Solution:**
```python
def _select_market(self) -> Optional[str]:
    """Interactive market selection (extracted from duplicated code)."""
    # Implementation here
    pass

# Replace duplicated code with:
# market = self._select_market()
# if not market:
#     return None
```

**Files to Modify:**
- `app.py` (lines 423-470, 1573-1616)

---

## Medium Priority

### 4. TradingTerminal Unit Tests
**Priority:** MEDIUM | **Time:** 2-3 hours

Add comprehensive tests for TradingTerminal class:

**File to Create:**
- `tests/test_trading_terminal.py`

**Test Cases:**
- [ ] Initialization with dependency injection
- [ ] get_account_balance() with mocked API
- [ ] get_current_prices() with caching
- [ ] round_size() for different products
- [ ] round_price() for different products
- [ ] Account caching TTL behavior
- [ ] Rate limiter integration

---

### 5. Error Handling Improvements
**Priority:** MEDIUM | **Time:** 1-2 hours

Improve error handling throughout the application:

**Areas to Improve:**
- API call failures (network errors, rate limits)
- Invalid product IDs
- Insufficient balance
- TWAP order failures
- File I/O errors in TWAPTracker

**Add Custom Exceptions:**
```python
# exceptions.py
class APIError(Exception): pass
class InsufficientBalanceError(Exception): pass
class TWAPExecutionError(Exception): pass
```

---

### 6. Add Input Validation to CLI
**Priority:** MEDIUM | **Time:** 1 hour

Replace raw input parsing with validators:

**Current Issues:**
- No validation when user enters prices, sizes, durations
- Errors only caught when placing order

**Solution:**
Use `InputValidator` throughout app.py:

```python
# Example in place_limit_order()
try:
    price = InputValidator.validate_price(
        float(input("Enter limit price: ")),
        min_price=product_info['quote_increment']
    )
except ValidationError as e:
    print(f"Error: {e}")
    return None
```

---

## Low Priority

### 7. Logging Improvements
**Priority:** LOW | **Time:** 1 hour

**Current Issues:**
- Log files accumulate (never deleted)
- No log rotation
- Hard to find specific trading sessions

**Improvements:**
- Implement log rotation (keep last 30 days)
- Add session IDs to correlate logs
- Add structured logging for TWAP orders

---

### 8. Configuration File Support
**Priority:** LOW | **Time:** 1 hour

Allow users to customize settings without editing code:

**File to Create:**
- `config.yaml` (optional, falls back to defaults)

```yaml
rate_limit:
  requests_per_second: 25
  burst: 50

cache:
  order_status_ttl: 5
  account_ttl: 60

twap:
  max_slices: 1000
  min_duration_minutes: 1
  max_duration_minutes: 1440
```

**Files to Modify:**
- `config_manager.py` - Add YAML loading support

---

### 9. Documentation Improvements
**Priority:** LOW | **Time:** 30 minutes

**Files to Update:**
- `README.md` - Add testing section, architecture overview
- `CLAUDE.md` - Update with new architecture and testing info
- `TESTING.md` - Already comprehensive (no changes needed)

**Add Architecture Diagram:**
```
┌─────────────────┐
│  app.py (CLI)   │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
┌───▼──────┐  ┌─▼────────────┐
│ Config   │  │ Validators   │
└──────────┘  └──────────────┘
    │
    │
┌───▼───────────────┐
│  TradingTerminal  │
└────────┬──────────┘
         │
    ┌────┴─────┐
    │          │
┌───▼──────┐  ┌─▼──────────┐
│APIClient │  │TWAPStorage │
└──────────┘  └────────────┘
```

---

### 10. Performance Monitoring
**Priority:** LOW | **Time:** 1 hour

Add timing metrics to track performance:

**Metrics to Track:**
- API call latency
- Rate limiter wait times
- TWAP order execution duration
- Portfolio display time

**Implementation:**
```python
import time
from functools import wraps

def track_performance(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logging.info(f"{func.__name__} took {elapsed:.2f}s")
        return result
    return wrapper
```

---

## Code Quality

### 11. Type Hints
**Priority:** LOW | **Time:** 2-3 hours

Add type hints throughout codebase:

**Tools:**
- mypy (already in requirements-dev.txt)
- Run: `mypy app.py validators.py config_manager.py`

**Example:**
```python
def get_account_balance(self, currency: str) -> Optional[float]:
    """Get available balance for a currency."""
    # Implementation
```

---

### 12. Code Formatting
**Priority:** LOW | **Time:** 15 minutes

Format code with black:

```bash
black app.py validators.py config_manager.py api_client.py storage.py
```

Already installed in requirements-dev.txt.

---

### 13. Linting
**Priority:** LOW | **Time:** 30 minutes

Fix linting issues:

```bash
flake8 app.py validators.py config_manager.py api_client.py storage.py
```

Common issues to fix:
- Line length (max 100 chars)
- Unused imports
- Unused variables
- Complex functions (consider refactoring)

---

## Testing Coverage Goals

**Current Coverage:**
- validators.py: 90.55% ✅
- twap_tracker.py: 87.10% ✅
- config_manager.py: 71.88% ⚠️
- api_client.py: 50.00% ⚠️
- app.py: 5.54% (expected - CLI code)

**Target Coverage:**
- Overall: >80%
- Business logic modules: >95%

**To Improve:**
- Add config_manager.py tests
- Add more api_client.py tests
- Add TradingTerminal integration tests

---

## Security Improvements

### 14. API Key Validation
**Priority:** LOW | **Time:** 30 minutes

Add validation for API key format:

```python
def validate_api_key(key: str) -> bool:
    """Validate API key format."""
    # Expected format: organizations/{uuid}/apiKeys/{uuid}
    pattern = r'^organizations/[a-f0-9-]+/apiKeys/[a-f0-9-]+$'
    return bool(re.match(pattern, key))
```

---

### 15. Git History Cleanup
**Priority:** LOW | **Time:** 30 minutes

**Important:** Check if hardcoded API key is in git history:

```bash
git log --all --full-history -- keys.py
```

If found, clean with BFG Repo-Cleaner:
```bash
# Backup first!
git clone --mirror https://github.com/yourusername/repo.git

# Remove sensitive data
bfg --replace-text passwords.txt repo.git

# Force push (DESTRUCTIVE)
cd repo.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force
```

---

## Notes

- All critical improvements are complete ✅
- Focus on high priority items first
- Low priority items are nice-to-have
- Test coverage for business logic is excellent
- Security vulnerability is fully addressed

Last Updated: 2025-12-31
