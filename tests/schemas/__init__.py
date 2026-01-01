"""
Pydantic schemas for Coinbase API responses.

This module contains Pydantic models that define the structure of
Coinbase API responses. These schemas are used to:

1. Validate that mock API responses match the real API structure
2. Document the expected response format
3. Catch API changes early during testing

Usage:
    from tests.schemas.api_responses import AccountsResponse

    # Validate a response
    validated = AccountsResponse(**response_data)
"""
