"""
VCR.py configuration for recording and replaying API responses.

This module provides a pre-configured VCR instance that records HTTP
interactions with the Coinbase API and replays them in tests, eliminating
the need for live API calls during testing.

Usage:
    from tests.vcr_config import api_vcr

    @api_vcr.use_cassette('my_test.yaml')
    def test_api_call():
        # Make API call - will be recorded on first run,
        # replayed from cassette on subsequent runs
        response = client.get_accounts()
"""

import vcr

# VCR instance with custom settings for API testing
api_vcr = vcr.VCR(
    # Where to store recorded cassettes
    cassette_library_dir='tests/vcr_cassettes',

    # Record mode: 'once' means record on first run, replay thereafter
    # Options: 'once', 'new_episodes', 'none', 'all'
    record_mode='once',

    # Match requests on these attributes to find the right cassette
    match_on=['method', 'scheme', 'host', 'port', 'path', 'query'],

    # Filter sensitive headers from recordings
    filter_headers=['authorization', 'Authorization', 'CB-ACCESS-KEY', 'CB-ACCESS-SIGN'],

    # Decode compressed responses for readability
    decode_compressed_response=True,

    # Serialize as YAML for human-readable cassettes
    serializer='yaml',
)
