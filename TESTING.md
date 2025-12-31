# Testing Guide

Complete guide to testing the Coinbase Advanced Trading Terminal.

## Table of Contents
- [Quick Start](#quick-start)
- [Understanding Testing](#understanding-testing)
- [Installation](#installation)
- [Running Tests](#running-tests)
- [Test Structure](#test-structure)
- [Writing New Tests](#writing-new-tests)
- [Debugging Failed Tests](#debugging-failed-tests)
- [Best Practices](#best-practices)
- [Common Issues](#common-issues)

---

## Quick Start

```bash
# Install testing dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

---

## Understanding Testing

### What is Testing?

Testing is the process of verifying that your code works correctly. Instead of manually testing features by running the app, automated tests check that functions behave as expected.

**Benefits:**
- **Catch bugs early** - Tests fail when you break something
- **Confidence** - Know your changes don't break existing features
- **Documentation** - Tests show how code should be used
- **Refactoring safety** - Change code with confidence

### Types of Tests

#### Unit Tests
Test individual functions/methods in isolation.

**Example:** Testing that price validation rejects negative numbers.

```python
def test_validate_price_negative():
    """Test that negative prices are rejected."""
    with pytest.raises(ValidationError):
        InputValidator.validate_price(-10)
```

**When to use:** Testing pure functions, calculations, validation logic.

#### Integration Tests
Test multiple components working together.

**Example:** Testing that a TWAP order is saved and can be loaded back.

```python
def test_twap_order_lifecycle():
    """Test saving and loading a TWAP order."""
    tracker = TWAPTracker()
    tracker.save_twap_order(order)
    loaded = tracker.get_twap_order(order.twap_id)
    assert loaded.twap_id == order.twap_id
```

**When to use:** Testing workflows, API integration, database operations.

### Test Markers

Tests can be marked to organize them:

- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Slower integration tests
- `@pytest.mark.slow` - Tests that take time to run

---

## Installation

### 1. Install Testing Dependencies

```bash
pip install -r requirements-dev.txt
```

This installs:
- **pytest** - Testing framework
- **pytest-cov** - Coverage reporting
- **pytest-mock** - Mocking utilities
- **freezegun** - Time mocking for testing

### 2. Verify Installation

```bash
pytest --version
```

Should output something like: `pytest 7.4.0`

---

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_validators.py

# Run a specific test class
pytest tests/test_validators.py::TestPriceValidation

# Run a specific test
pytest tests/test_validators.py::TestPriceValidation::test_validate_price_valid

# Run tests matching a pattern
pytest -k "price"  # Runs all tests with "price" in name
```

### Running by Marker

```bash
# Run only unit tests (fast)
pytest -m unit

# Run only integration tests
pytest -m integration

# Run everything except slow tests
pytest -m "not slow"
```

### With Coverage

```bash
# Run tests with coverage
pytest --cov=.

# Generate HTML coverage report
pytest --cov=. --cov-report=html

# Open the report (macOS)
open htmlcov/index.html

# Open the report (Linux)
xdg-open htmlcov/index.html
```

### Useful Options

```bash
# Stop at first failure
pytest -x

# Re-run only failed tests from last run
pytest --lf

# Show local variables in tracebacks
pytest -l

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

---

## Test Structure

### Directory Layout

```
tests/
├── __init__.py              # Makes 'tests' a Python package
├── conftest.py              # Shared fixtures and configuration
├── test_validators.py       # Tests for validators module
├── test_rate_limiter.py     # Tests for RateLimiter
├── test_twap_tracker.py     # Tests for TWAPTracker
├── integration/             # Integration tests
│   ├── __init__.py
│   └── test_twap_execution.py
└── mocks/                   # Mock implementations
    ├── __init__.py
    └── mock_coinbase_api.py
```

### Test File Naming

- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

**Example:**
```python
# File: test_validators.py

class TestPriceValidation:  # Test class
    def test_validate_price_valid(self):  # Test function
        assert InputValidator.validate_price(100.0) == 100.0
```

---

## Writing New Tests

### Anatomy of a Test

```python
import pytest
from validators import InputValidator, ValidationError

@pytest.mark.unit
def test_validate_price_accepts_valid_prices():
    """Test that valid prices are accepted."""
    # Arrange - Set up test data
    price = 100.0

    # Act - Call the function being tested
    result = InputValidator.validate_price(price)

    # Assert - Verify the result
    assert result == 100.0
```

### Using Fixtures

Fixtures provide test data or setup. They're defined in `conftest.py` and automatically injected.

```python
def test_save_order(mock_twap_storage, sample_twap_order):
    """
    Test saving an order.

    mock_twap_storage and sample_twap_order are fixtures
    automatically provided by pytest.
    """
    # Use the fixtures
    mock_twap_storage.save_twap_order(sample_twap_order)

    # Verify it was saved
    loaded = mock_twap_storage.get_twap_order(sample_twap_order.twap_id)
    assert loaded is not None
```

### Testing Exceptions

```python
def test_validate_price_rejects_negative():
    """Test that negative prices raise ValidationError."""
    with pytest.raises(ValidationError, match="greater than 0"):
        InputValidator.validate_price(-10)
```

**Explanation:**
- `pytest.raises(ValidationError)` - Expects ValidationError to be raised
- `match="greater than 0"` - Error message must contain this text

### Testing with Mocks

Mocks simulate external dependencies (API calls, databases):

```python
def test_get_account_balance(mock_api_client):
    """Test getting account balance with mocked API."""
    # Mock API is already set up with test data
    terminal = TradingTerminal(api_client=mock_api_client)

    balance = terminal.get_account_balance('BTC')

    # Verify balance from mock data
    assert balance == 1.5
```

### Parameterized Tests

Test the same logic with different inputs:

```python
@pytest.mark.parametrize("price,expected", [
    (100.0, 100.0),
    (0.001, 0.001),
    (999999, 999999),
])
def test_validate_price_various_inputs(price, expected):
    """Test price validation with various valid inputs."""
    assert InputValidator.validate_price(price) == expected
```

---

## Example: Writing a Complete Test

Let's write a test for a new feature step-by-step.

### Scenario: Test that order size is rounded correctly

**1. Create the test file (if needed):**
```bash
touch tests/test_order_rounding.py
```

**2. Write the test:**
```python
"""
Tests for order size rounding functionality.
"""

import pytest
from app import TradingTerminal

@pytest.mark.unit
class TestOrderRounding:
    """Tests for order size and price rounding."""

    def test_round_size_to_increment(self, mock_api_client, test_app_config):
        """
        Test that order size is rounded to product increment.

        BTC-USDC has base_increment of 0.00000001 (8 decimals).
        A size of 1.123456789 should round to 1.12345678.
        """
        # Arrange - Set up terminal with mocked dependencies
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False  # Don't start background thread in tests
        )

        # Act - Round a size
        rounded = terminal.round_size(1.123456789, 'BTC-USDC')

        # Assert - Verify it's rounded to 8 decimals
        assert rounded == 1.12345678

    def test_round_size_already_valid(self, mock_api_client, test_app_config):
        """Test that already-valid sizes are unchanged."""
        terminal = TradingTerminal(
            api_client=mock_api_client,
            config=test_app_config,
            start_checker_thread=False
        )

        # Size already at 8 decimals
        rounded = terminal.round_size(1.12345678, 'BTC-USDC')

        assert rounded == 1.12345678
```

**3. Run the test:**
```bash
pytest tests/test_order_rounding.py -v
```

**4. Verify it passes:**
```
tests/test_order_rounding.py::TestOrderRounding::test_round_size_to_increment PASSED
tests/test_order_rounding.py::TestOrderRounding::test_round_size_already_valid PASSED
```

---

## Debugging Failed Tests

### Reading Test Output

When a test fails, pytest shows:

```
FAILED tests/test_validators.py::test_validate_price_negative - AssertionError

def test_validate_price_negative():
    with pytest.raises(ValidationError):
>       InputValidator.validate_price(-10)
E       Failed: DID NOT RAISE <class 'validators.ValidationError'>
```

**How to read this:**
- `FAILED tests/test_validators.py::test_validate_price_negative` - Which test failed
- `AssertionError` - Type of failure
- `>` marks the failing line
- `E` shows the error message

### Common Failure Patterns

#### AssertionError
```
>       assert result == expected
E       AssertionError: assert 99.99 == 100.0
```

**Solution:** The values don't match. Check your logic or expected value.

#### DID NOT RAISE
```
E       Failed: DID NOT RAISE <class 'ValidationError'>
```

**Solution:** Expected an exception but none was raised. Check exception logic.

#### Fixture Not Found
```
E       fixture 'nonexistent_fixture' not found
```

**Solution:** Fixture doesn't exist or is misspelled. Check `conftest.py`.

### Debugging Strategies

#### 1. Add Print Statements
```python
def test_something():
    result = calculate_something()
    print(f"Result: {result}")  # Shows in test output with -s flag
    assert result == expected
```

Run with `-s` to see print output:
```bash
pytest tests/test_file.py::test_something -s
```

#### 2. Use pytest.set_trace()
```python
def test_something():
    result = calculate_something()
    pytest.set_trace()  # Drops into debugger here
    assert result == expected
```

#### 3. Run Single Test
```bash
pytest tests/test_file.py::test_specific_test -v
```

#### 4. Show Local Variables
```bash
pytest -l  # Shows local variables in failure output
```

---

## Best Practices

### 1. Test One Thing Per Test
❌ **Bad:**
```python
def test_everything():
    """Test validation, saving, and loading."""
    validator.validate(data)
    storage.save(data)
    loaded = storage.load()
    assert loaded == data
```

✅ **Good:**
```python
def test_validation():
    """Test that validation works."""
    assert validator.validate(data) is True

def test_saving():
    """Test that data can be saved."""
    storage.save(data)
    assert os.path.exists(storage_path)

def test_loading():
    """Test that data can be loaded."""
    storage.save(data)
    loaded = storage.load()
    assert loaded == data
```

### 2. Use Descriptive Names
❌ **Bad:** `test_1`, `test_validation`

✅ **Good:** `test_validate_price_rejects_negative_values`

### 3. Write Clear Docstrings
```python
def test_validate_twap_duration_boundary():
    """
    Test TWAP duration validation at boundaries.

    Duration of 1 minute should be accepted (minimum).
    Duration of 1440 minutes should be accepted (maximum).
    Duration of 0 or 1441 should be rejected.
    """
```

### 4. Arrange-Act-Assert Pattern
```python
def test_something():
    # Arrange - Set up test conditions
    price = 100.0

    # Act - Perform the action
    result = validator.validate_price(price)

    # Assert - Verify the outcome
    assert result == 100.0
```

### 5. Clean Up After Tests
Use fixtures for automatic cleanup:
```python
@pytest.fixture
def temp_file():
    """Create temporary file, clean up after test."""
    path = "/tmp/test_file.txt"
    yield path
    # Cleanup happens here automatically
    if os.path.exists(path):
        os.remove(path)
```

---

## Common Issues

### Import Errors
**Problem:**
```
ModuleNotFoundError: No module named 'validators'
```

**Solution:**
Run pytest from the project root directory:
```bash
cd /Users/ronaldho/CB-Advanced-Terminal
pytest
```

### Fixture Not Found
**Problem:**
```
fixture 'mock_api_client' not found
```

**Solution:**
Ensure `conftest.py` exists in `tests/` directory and contains the fixture.

### Tests Pass Locally But Fail in CI
**Problem:** Tests depend on local state (files, environment variables).

**Solution:**
- Use fixtures for file creation/cleanup
- Don't rely on hardcoded paths
- Mock external dependencies

### Slow Tests
**Problem:** Tests take too long to run.

**Solution:**
```bash
# Run only fast unit tests
pytest -m unit

# Skip slow tests
pytest -m "not slow"

# Run tests in parallel
pip install pytest-xdist
pytest -n auto
```

---

## Coverage Goals

### What is Coverage?

Coverage measures what percentage of your code is tested.

```bash
pytest --cov=. --cov-report=term-missing
```

Output:
```
Name                Stmts   Miss  Cover   Missing
-------------------------------------------------
app.py               500    150    70%   45-67, 123-145
validators.py         50      5    90%   89-93
config.py             30      0   100%
-------------------------------------------------
TOTAL                580    155    73%
```

### Coverage Targets

- **Overall:** Aim for >80%
- **Critical modules:** >95%
  - Order placement logic
  - TWAP execution
  - Validation
  - Fee calculation

### Viewing HTML Coverage Report

```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

This shows exactly which lines aren't covered by tests.

---

## Next Steps

1. **Run the existing tests** to ensure everything works
2. **Try writing a simple test** for a function you understand
3. **Read existing test files** to learn patterns
4. **Ask questions** if you get stuck!

### Helpful Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Python Testing with pytest (Book)](https://pragprog.com/titles/bopytest/)
- [Real Python: Testing Guide](https://realpython.com/pytest-python-testing/)

---

## Quick Reference

### Common pytest Commands
```bash
pytest                          # Run all tests
pytest -v                       # Verbose output
pytest -x                       # Stop at first failure
pytest --lf                     # Rerun last failures
pytest -m unit                  # Run unit tests only
pytest -k "price"               # Run tests matching "price"
pytest --cov=.                  # With coverage
pytest tests/test_file.py       # Run specific file
```

### Common Assertions
```python
assert x == y                   # Equality
assert x != y                   # Inequality
assert x > y                    # Greater than
assert x in [1, 2, 3]          # Membership
assert "text" in string         # Substring
assert obj is None              # Identity
assert obj is not None          # Not None
```

### Expecting Exceptions
```python
with pytest.raises(ValueError):
    function_that_raises()

with pytest.raises(ValueError, match="error message"):
    function_that_raises()
```

### Using Fixtures
```python
def test_something(fixture_name):
    # fixture_name is automatically provided
    result = fixture_name.do_something()
    assert result is True
```

---

**Happy Testing! 🧪**
