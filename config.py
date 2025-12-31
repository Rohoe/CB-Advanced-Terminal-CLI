"""
Secure configuration management for the Coinbase Trading Terminal.

This module handles API credentials and configuration loading from environment
variables, replacing the hardcoded credentials approach.

Usage:
    # Set environment variables before running:
    # export COINBASE_API_KEY='organizations/your-org/apiKeys/your-key'
    # export COINBASE_API_SECRET='your-secret'  # Optional, will prompt if not set

    from config import Config
    config = Config()
    api_key = config.api_key
    api_secret = config.api_secret
"""

import os
import getpass
import logging
from typing import Optional


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


class Config:
    """
    Secure configuration management for API credentials.

    Loads API credentials from environment variables. The API secret can
    optionally be provided via interactive prompt for additional security.

    Environment Variables:
        COINBASE_API_KEY: Required. Your Coinbase API key.
        COINBASE_API_SECRET: Optional. Your Coinbase API secret.
                            If not set, will prompt interactively.

    Example:
        >>> config = Config()
        >>> client = RESTClient(api_key=config.api_key, api_secret=config.api_secret)
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 prompt_for_secret: bool = True):
        """
        Initialize configuration.

        Args:
            api_key: Override API key (for testing). If None, loads from env.
            api_secret: Override API secret (for testing). If None, loads from env or prompts.
            prompt_for_secret: If True and secret not in env, prompt user. If False, raise error.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._prompt_for_secret = prompt_for_secret

        # Validate on initialization
        self._validate()

    def _validate(self):
        """Validate that required configuration is available."""
        # Trigger loading to validate
        _ = self.api_key
        _ = self.api_secret

    @property
    def api_key(self) -> str:
        """
        Get the Coinbase API key.

        Returns:
            The API key string.

        Raises:
            ConfigurationError: If COINBASE_API_KEY environment variable is not set
                               and no override was provided.
        """
        if self._api_key:
            return self._api_key

        key = os.getenv('COINBASE_API_KEY')
        if not key:
            raise ConfigurationError(
                "COINBASE_API_KEY environment variable is not set.\n"
                "Please set it using:\n"
                "  export COINBASE_API_KEY='organizations/your-org-id/apiKeys/your-key-id'\n"
                "\n"
                "You can find your API key in the Coinbase Advanced Trade settings."
            )
        return key

    @property
    def api_secret(self) -> str:
        """
        Get the Coinbase API secret.

        Returns:
            The API secret string.

        Raises:
            ConfigurationError: If secret is not available and prompting is disabled.
        """
        if self._api_secret:
            return self._api_secret

        secret = os.getenv('COINBASE_API_SECRET')
        if secret:
            return secret

        if self._prompt_for_secret:
            logging.debug("API secret not in environment, prompting user")
            return getpass.getpass("Enter Coinbase API Secret: ")
        else:
            raise ConfigurationError(
                "COINBASE_API_SECRET environment variable is not set and "
                "interactive prompting is disabled."
            )

    @classmethod
    def from_env(cls) -> 'Config':
        """
        Create a Config instance from environment variables.

        This is the recommended way to create a Config for production use.

        Returns:
            A new Config instance.

        Raises:
            ConfigurationError: If required environment variables are not set.
        """
        return cls()

    @classmethod
    def for_testing(cls, api_key: str = "test-key", api_secret: str = "test-secret") -> 'Config':
        """
        Create a Config instance for testing purposes.

        This bypasses environment variable loading and uses provided test values.

        Args:
            api_key: Test API key to use.
            api_secret: Test API secret to use.

        Returns:
            A new Config instance with test credentials.
        """
        return cls(api_key=api_key, api_secret=api_secret, prompt_for_secret=False)


# For backward compatibility with code that imports Keys
class Keys:
    """
    DEPRECATED: Use Config class instead.

    This class is kept for backward compatibility but will be removed
    in a future version.
    """

    _config: Optional[Config] = None

    @classmethod
    def _get_config(cls) -> Config:
        if cls._config is None:
            cls._config = Config()
        return cls._config

    @property
    def api_key(self) -> str:
        """Get API key. DEPRECATED: Use Config().api_key instead."""
        return self._get_config().api_key

    @property
    def api_secret(self) -> str:
        """Get API secret. DEPRECATED: Use Config().api_secret instead."""
        return self._get_config().api_secret
