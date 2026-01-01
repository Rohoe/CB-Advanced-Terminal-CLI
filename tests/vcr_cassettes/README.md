# VCR Cassettes

This directory contains recorded HTTP interactions with the Coinbase API for testing purposes.

## What are VCR Cassettes?

VCR cassettes are YAML files that contain recorded HTTP requests and responses. When tests run:
- **First run**: HTTP requests are made to the real API and responses are recorded to cassettes
- **Subsequent runs**: Responses are replayed from cassettes without hitting the API

This provides:
- ✅ **Fast tests** - No network calls needed
- ✅ **Offline testing** - Tests work without internet
- ✅ **Deterministic tests** - Same responses every time
- ✅ **Regression detection** - Catch API changes

## Directory Structure

```
vcr_cassettes/
├── sandbox_*.yaml          # Safe to commit - sandbox responses
├── production_*.yaml       # DO NOT commit - may contain sensitive data
└── .gitignore             # Controls what gets committed
```

## Recording New Cassettes

To record new cassettes from the sandbox API:

```bash
# Delete existing cassettes to force re-recording
rm tests/vcr_cassettes/sandbox_*.yaml

# Run VCR recording tests with sandbox mode enabled
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v
```

## Re-recording Cassettes

If the Coinbase API changes, you may need to re-record cassettes:

```bash
# Delete specific cassette
rm tests/vcr_cassettes/sandbox_get_accounts.yaml

# Or delete all and re-record
rm tests/vcr_cassettes/*.yaml
COINBASE_SANDBOX_MODE=true pytest tests/integration/test_vcr_recording.py -v
```

## Security Notes

⚠️ **IMPORTANT**:
- Sandbox cassettes are safe to commit (no authentication required)
- Production cassettes may contain sensitive data and should NOT be committed
- The `.gitignore` is configured to only allow sandbox cassettes
- Always review cassettes before committing to ensure no secrets are included

## Cassette Format

Cassettes are YAML files containing:
```yaml
version: 1
interactions:
- request:
    uri: https://api-sandbox.coinbase.com/api/v3/brokerage/accounts
    method: GET
    headers: ...
  response:
    status: 200
    headers: ...
    body: ...
```

## Troubleshooting

**Tests failing with cassette errors?**
- Delete the cassette and re-record
- Check that the cassette file exists in `tests/vcr_cassettes/`
- Verify VCR configuration in `tests/vcr_config.py`

**Cassette not matching request?**
- Check `match_on` configuration in `tests/vcr_config.py`
- Ensure request parameters match exactly
- Consider using `match_on=['method', 'path']` for more lenient matching
