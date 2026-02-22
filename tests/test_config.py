"""
Unit tests for Config class (config.py).

Tests cover API key/secret loading from constructor, env vars,
interactive prompt, and factory methods.

To run:
    pytest tests/test_config.py -v
"""

import pytest
from unittest.mock import patch

from config import Config, ConfigurationError


@pytest.mark.unit
class TestAPIKeyLoading:
    """Tests for API key loading from various sources."""

    def test_api_key_from_constructor(self):
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.api_key == 'test-key'

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'env-key')
        config = Config(api_secret='test-secret')
        assert config.api_key == 'env-key'

    def test_api_key_missing_raises(self, monkeypatch):
        monkeypatch.delenv('COINBASE_API_KEY', raising=False)
        with pytest.raises(ConfigurationError, match="COINBASE_API_KEY"):
            Config(api_secret='test-secret')

    def test_constructor_key_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'env-key')
        config = Config(api_key='constructor-key', api_secret='test-secret')
        assert config.api_key == 'constructor-key'


@pytest.mark.unit
class TestAPISecretLoading:
    """Tests for API secret loading from various sources."""

    def test_api_secret_from_constructor(self):
        config = Config(api_key='test-key', api_secret='constructor-secret')
        assert config.api_secret == 'constructor-secret'

    def test_api_secret_from_env(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'test-key')
        monkeypatch.setenv('COINBASE_API_SECRET', 'env-secret')
        config = Config(prompt_for_secret=False)
        assert config.api_secret == 'env-secret'

    def test_api_secret_prompt(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'test-key')
        monkeypatch.delenv('COINBASE_API_SECRET', raising=False)
        with patch('config.getpass.getpass', return_value='prompted-secret'):
            config = Config(prompt_for_secret=True)
        assert config.api_secret == 'prompted-secret'

    def test_api_secret_no_prompt_raises(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'test-key')
        monkeypatch.delenv('COINBASE_API_SECRET', raising=False)
        with pytest.raises(ConfigurationError, match="COINBASE_API_SECRET"):
            Config(prompt_for_secret=False)

    def test_api_secret_cached_after_prompt(self, monkeypatch):
        """Secret should be cached so getpass is only called once."""
        monkeypatch.setenv('COINBASE_API_KEY', 'test-key')
        monkeypatch.delenv('COINBASE_API_SECRET', raising=False)
        with patch('config.getpass.getpass', return_value='prompted-secret') as mock_getpass:
            config = Config(prompt_for_secret=True)
            _ = config.api_secret
            _ = config.api_secret
        assert mock_getpass.call_count == 1


@pytest.mark.unit
class TestBaseURL:
    """Tests for base_url property."""

    def test_production_url_default(self, monkeypatch):
        monkeypatch.delenv('COINBASE_SANDBOX_MODE', raising=False)
        monkeypatch.delenv('COINBASE_BASE_URL', raising=False)
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.base_url == 'api.coinbase.com'

    def test_sandbox_url(self, monkeypatch):
        monkeypatch.setenv('COINBASE_SANDBOX_MODE', 'true')
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.base_url == 'api-sandbox.coinbase.com'

    def test_custom_url(self, monkeypatch):
        monkeypatch.delenv('COINBASE_SANDBOX_MODE', raising=False)
        monkeypatch.setenv('COINBASE_BASE_URL', 'custom.api.com')
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.base_url == 'custom.api.com'

    def test_is_sandbox_property(self, monkeypatch):
        monkeypatch.setenv('COINBASE_SANDBOX_MODE', 'true')
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.is_sandbox is True

    def test_is_not_sandbox(self, monkeypatch):
        monkeypatch.delenv('COINBASE_SANDBOX_MODE', raising=False)
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.is_sandbox is False

    def test_verbose_property(self, monkeypatch):
        monkeypatch.setenv('COINBASE_VERBOSE', 'true')
        config = Config(api_key='test-key', api_secret='test-secret')
        assert config.verbose is True


@pytest.mark.unit
class TestFactoryMethods:
    """Tests for factory methods."""

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv('COINBASE_API_KEY', 'env-key')
        monkeypatch.setenv('COINBASE_API_SECRET', 'env-secret')
        config = Config.from_env()
        assert config.api_key == 'env-key'
        assert config.api_secret == 'env-secret'

    def test_for_testing(self):
        config = Config.for_testing(api_key='test-key', api_secret='test-secret')
        assert config.api_key == 'test-key'
        assert config.api_secret == 'test-secret'

    def test_for_testing_defaults(self):
        config = Config.for_testing()
        assert config.api_key == 'test-key'
        assert config.api_secret == 'test-secret'
