"""
Application configuration management.

This module provides centralized configuration for the trading terminal,
replacing hardcoded values with configurable settings that can be
loaded from environment variables.

Usage:
    from config_manager import AppConfig

    config = AppConfig()
    print(config.rate_limit.requests_per_second)  # 25
    print(config.cache.account_ttl)  # 60
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any


def _env(name: str, default, type_fn=str):
    """Read an environment variable with type conversion.

    For bools, accepts 'true'/'false' (case-insensitive).
    """
    raw = os.getenv(name, str(default))
    if type_fn is bool:
        return raw.lower() == 'true'
    return type_fn(raw)


@dataclass
class RateLimitConfig:
    """
    Configuration for API rate limiting.

    The trading terminal uses a token bucket rate limiter to prevent
    hitting Coinbase API rate limits.

    Attributes:
        requests_per_second: Rate at which tokens are replenished.
        burst: Maximum number of tokens (burst capacity).

    Environment Variables:
        RATE_LIMIT_RPS: Requests per second (default: 25)
        RATE_LIMIT_BURST: Burst capacity (default: 50)
    """
    requests_per_second: int = 25
    burst: int = 50


@dataclass
class CacheConfig:
    """
    Configuration for caching TTLs (Time-To-Live in seconds).

    Caching reduces API calls and improves performance, but stale
    data may affect trading decisions. Adjust TTLs based on your needs.

    Attributes:
        order_status_ttl: How long to cache order status (seconds).
        account_ttl: How long to cache account balances (seconds).
        fill_ttl: How long to cache fill information (seconds).
        product_ttl: How long to cache product metadata (seconds).

    Environment Variables:
        CACHE_ORDER_STATUS_TTL: Order status cache TTL (default: 5)
        CACHE_ACCOUNT_TTL: Account cache TTL (default: 60)
        CACHE_FILL_TTL: Fill cache TTL (default: 5)
        CACHE_PRODUCT_TTL: Product cache TTL (default: 300)
    """
    order_status_ttl: int = 5
    account_ttl: int = 60
    fill_ttl: int = 5
    product_ttl: int = 300  # 5 minutes - product info rarely changes


@dataclass
class TWAPConfig:
    """
    Configuration for TWAP (Time-Weighted Average Price) orders.

    Attributes:
        slice_delay: Minimum delay between slices in seconds.
        max_slices: Maximum number of slices allowed.
        max_duration_minutes: Maximum TWAP duration in minutes.
        min_duration_minutes: Minimum TWAP duration in minutes.
        jitter_pct: Randomize interval timing +/- this percentage (0.0 = disabled).
        adaptive_enabled: Whether to cancel+replace unfilled orders.
        adaptive_timeout_seconds: Seconds to wait before cancel+replace.
        adaptive_max_retries: Maximum cancel+replace attempts per slice.
        participation_rate_cap: Max slice as fraction of recent volume (0.0 = disabled).
        volume_lookback_minutes: Minutes of recent volume to consider for participation cap.
        market_fallback_enabled: Whether to use market orders for final slices.
        market_fallback_remaining_slices: Switch to market orders when this many slices remain.

    Environment Variables:
        TWAP_SLICE_DELAY: Delay between slices (default: 2)
        TWAP_MAX_SLICES: Maximum slices (default: 1000)
        TWAP_MAX_DURATION: Maximum duration in minutes (default: 1440)
        TWAP_MIN_DURATION: Minimum duration in minutes (default: 1)
        TWAP_JITTER_PCT: Jitter percentage (default: 0.0)
        TWAP_ADAPTIVE_ENABLED: Enable adaptive cancel+replace (default: false)
        TWAP_ADAPTIVE_TIMEOUT: Adaptive timeout in seconds (default: 30)
        TWAP_ADAPTIVE_MAX_RETRIES: Max adaptive retries (default: 3)
        TWAP_PARTICIPATION_RATE_CAP: Participation rate cap (default: 0.0)
        TWAP_VOLUME_LOOKBACK: Volume lookback in minutes (default: 5)
        TWAP_MARKET_FALLBACK_ENABLED: Enable market fallback (default: false)
        TWAP_MARKET_FALLBACK_REMAINING_SLICES: Remaining slices for fallback (default: 1)
    """
    slice_delay: int = 2
    max_slices: int = 1000
    max_duration_minutes: int = 1440  # 24 hours
    min_duration_minutes: int = 1
    jitter_pct: float = 0.0
    adaptive_enabled: bool = False
    adaptive_timeout_seconds: int = 30
    adaptive_max_retries: int = 3
    participation_rate_cap: float = 0.0
    volume_lookback_minutes: int = 5
    market_fallback_enabled: bool = False
    market_fallback_remaining_slices: int = 1


@dataclass
class VWAPConfig:
    """
    Configuration for VWAP orders.

    Attributes:
        default_lookback_hours: Default hours of historical data for volume profile.
        default_granularity: Default candle granularity for volume profile.
        benchmark_enabled: Whether to calculate and show benchmark VWAP.

    Environment Variables:
        VWAP_LOOKBACK_HOURS: Volume lookback hours (default: 24)
        VWAP_GRANULARITY: Candle granularity (default: ONE_HOUR)
        VWAP_BENCHMARK_ENABLED: Enable benchmark comparison (default: true)
    """
    default_lookback_hours: int = 24
    default_granularity: str = "ONE_HOUR"
    benchmark_enabled: bool = True


@dataclass
class RetryConfig:
    """
    Configuration for API call retry behavior.

    When API calls fail due to transient errors, the terminal can
    automatically retry with exponential backoff.

    Attributes:
        max_retries: Maximum number of retry attempts.
        backoff_seconds: Initial backoff delay in seconds.
        max_backoff: Maximum backoff delay in seconds.
        retryable_status_codes: HTTP status codes that trigger retry.

    Environment Variables:
        API_MAX_RETRIES: Maximum retries (default: 3)
        API_BACKOFF_SECONDS: Initial backoff (default: 1)
        API_MAX_BACKOFF: Maximum backoff (default: 30)
    """
    max_retries: int = 3
    backoff_seconds: int = 1
    max_backoff: int = 30
    retryable_status_codes: tuple = field(default_factory=lambda: (429, 500, 502, 503, 504))


@dataclass
class DisplayConfig:
    """
    Configuration for terminal display settings.

    Attributes:
        table_columns: Number of columns in market display.
        table_width: Width of table display.
        markets_to_show: Number of top markets to display.

    Environment Variables:
        DISPLAY_TABLE_COLUMNS: Table columns (default: 4)
        DISPLAY_TABLE_WIDTH: Table width (default: 120)
        DISPLAY_MARKETS: Number of markets (default: 20)
    """
    table_columns: int = 4
    table_width: int = 120
    markets_to_show: int = 20


@dataclass
class DatabaseConfig:
    """
    Configuration for SQLite database.

    Attributes:
        db_path: Path to the SQLite database file.
        wal_mode: Whether to use WAL journal mode for concurrent reads/writes.

    Environment Variables:
        DB_PATH: Database file path (default: trading.db)
        DB_WAL_MODE: Enable WAL mode (default: true)
    """
    db_path: str = "trading.db"
    wal_mode: bool = True


@dataclass
class WebSocketConfig:
    """
    Configuration for WebSocket connections.

    Attributes:
        enabled: Whether WebSocket is enabled.
        ticker_enabled: Whether to subscribe to ticker channel.
        user_channel_enabled: Whether to subscribe to user channel (fills).
        price_stale_seconds: Seconds before cached price is considered stale.

    Environment Variables:
        WS_ENABLED: Enable WebSocket (default: true)
        WS_TICKER_ENABLED: Enable ticker channel (default: true)
        WS_USER_CHANNEL_ENABLED: Enable user channel (default: true)
        WS_PRICE_STALE_SECONDS: Price staleness threshold (default: 5)
    """
    enabled: bool = True
    ticker_enabled: bool = True
    user_channel_enabled: bool = True
    price_stale_seconds: int = 5


@dataclass
class PrecisionConfig:
    """
    Product-specific precision configuration.

    Used as fallback when API product info is unavailable.
    """
    default_price_precision: int = 2
    default_size_precision: int = 8
    product_overrides: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        'SOL-USDC': {'price': 2, 'size': 4},
        'BTC-USDC': {'price': 2, 'size': 8},
        'ETH-USDC': {'price': 2, 'size': 8},
        'BTC-USD': {'price': 2, 'size': 8},
        'ETH-USD': {'price': 2, 'size': 8},
    })


class AppConfig:
    """
    Main application configuration.

    Aggregates all configuration sections and provides methods for
    loading configuration from environment variables.

    Usage:
        config = AppConfig()

        # Access rate limit settings
        rate = config.rate_limit.requests_per_second

        # Access cache settings
        ttl = config.cache.account_ttl

        # Access TWAP settings
        max_slices = config.twap.max_slices

    All settings can be overridden via environment variables.
    See individual config classes for environment variable names.
    """

    def __init__(self):
        """Initialize configuration from environment variables."""
        self.rate_limit = self._load_rate_limit_config()
        self.cache = self._load_cache_config()
        self.twap = self._load_twap_config()
        self.retry = self._load_retry_config()
        self.display = self._load_display_config()
        self.precision = PrecisionConfig()
        self.vwap = self._load_vwap_config()
        self.database = self._load_database_config()
        self.websocket = self._load_websocket_config()

    def _load_rate_limit_config(self) -> RateLimitConfig:
        """Load rate limit configuration from environment."""
        return RateLimitConfig(
            requests_per_second=_env('RATE_LIMIT_RPS', 25, int),
            burst=_env('RATE_LIMIT_BURST', 50, int),
        )

    def _load_cache_config(self) -> CacheConfig:
        """Load cache configuration from environment."""
        return CacheConfig(
            order_status_ttl=_env('CACHE_ORDER_STATUS_TTL', 5, int),
            account_ttl=_env('CACHE_ACCOUNT_TTL', 60, int),
            fill_ttl=_env('CACHE_FILL_TTL', 5, int),
            product_ttl=_env('CACHE_PRODUCT_TTL', 300, int),
        )

    def _load_twap_config(self) -> TWAPConfig:
        """Load TWAP configuration from environment."""
        return TWAPConfig(
            slice_delay=_env('TWAP_SLICE_DELAY', 2, int),
            max_slices=_env('TWAP_MAX_SLICES', 1000, int),
            max_duration_minutes=_env('TWAP_MAX_DURATION', 1440, int),
            min_duration_minutes=_env('TWAP_MIN_DURATION', 1, int),
            jitter_pct=_env('TWAP_JITTER_PCT', 0.0, float),
            adaptive_enabled=_env('TWAP_ADAPTIVE_ENABLED', False, bool),
            adaptive_timeout_seconds=_env('TWAP_ADAPTIVE_TIMEOUT', 30, int),
            adaptive_max_retries=_env('TWAP_ADAPTIVE_MAX_RETRIES', 3, int),
            participation_rate_cap=_env('TWAP_PARTICIPATION_RATE_CAP', 0.0, float),
            volume_lookback_minutes=_env('TWAP_VOLUME_LOOKBACK', 5, int),
            market_fallback_enabled=_env('TWAP_MARKET_FALLBACK_ENABLED', False, bool),
            market_fallback_remaining_slices=_env('TWAP_MARKET_FALLBACK_REMAINING_SLICES', 1, int),
        )

    def _load_retry_config(self) -> RetryConfig:
        """Load retry configuration from environment."""
        return RetryConfig(
            max_retries=_env('API_MAX_RETRIES', 3, int),
            backoff_seconds=_env('API_BACKOFF_SECONDS', 1, int),
            max_backoff=_env('API_MAX_BACKOFF', 30, int),
        )

    def _load_vwap_config(self) -> VWAPConfig:
        """Load VWAP configuration from environment."""
        return VWAPConfig(
            default_lookback_hours=_env('VWAP_LOOKBACK_HOURS', 24, int),
            default_granularity=_env('VWAP_GRANULARITY', 'ONE_HOUR'),
            benchmark_enabled=_env('VWAP_BENCHMARK_ENABLED', True, bool),
        )

    def _load_database_config(self) -> DatabaseConfig:
        """Load database configuration from environment."""
        return DatabaseConfig(
            db_path=_env('DB_PATH', 'trading.db'),
            wal_mode=_env('DB_WAL_MODE', True, bool),
        )

    def _load_websocket_config(self) -> WebSocketConfig:
        """Load WebSocket configuration from environment."""
        return WebSocketConfig(
            enabled=_env('WS_ENABLED', True, bool),
            ticker_enabled=_env('WS_TICKER_ENABLED', True, bool),
            user_channel_enabled=_env('WS_USER_CHANNEL_ENABLED', True, bool),
            price_stale_seconds=_env('WS_PRICE_STALE_SECONDS', 5, int),
        )

    def _load_display_config(self) -> DisplayConfig:
        """Load display configuration from environment."""
        return DisplayConfig(
            table_columns=_env('DISPLAY_TABLE_COLUMNS', 4, int),
            table_width=_env('DISPLAY_TABLE_WIDTH', 120, int),
            markets_to_show=_env('DISPLAY_MARKETS', 20, int),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.

        Useful for logging or debugging configuration values.

        Returns:
            Dictionary representation of all configuration.
        """
        return {
            'rate_limit': {
                'requests_per_second': self.rate_limit.requests_per_second,
                'burst': self.rate_limit.burst
            },
            'cache': {
                'order_status_ttl': self.cache.order_status_ttl,
                'account_ttl': self.cache.account_ttl,
                'fill_ttl': self.cache.fill_ttl,
                'product_ttl': self.cache.product_ttl
            },
            'twap': {
                'slice_delay': self.twap.slice_delay,
                'max_slices': self.twap.max_slices,
                'max_duration_minutes': self.twap.max_duration_minutes,
                'min_duration_minutes': self.twap.min_duration_minutes,
                'jitter_pct': self.twap.jitter_pct,
                'adaptive_enabled': self.twap.adaptive_enabled,
                'adaptive_timeout_seconds': self.twap.adaptive_timeout_seconds,
                'adaptive_max_retries': self.twap.adaptive_max_retries,
                'participation_rate_cap': self.twap.participation_rate_cap,
                'volume_lookback_minutes': self.twap.volume_lookback_minutes,
                'market_fallback_enabled': self.twap.market_fallback_enabled,
                'market_fallback_remaining_slices': self.twap.market_fallback_remaining_slices
            },
            'retry': {
                'max_retries': self.retry.max_retries,
                'backoff_seconds': self.retry.backoff_seconds,
                'max_backoff': self.retry.max_backoff
            },
            'display': {
                'table_columns': self.display.table_columns,
                'table_width': self.display.table_width,
                'markets_to_show': self.display.markets_to_show
            },
            'vwap': {
                'default_lookback_hours': self.vwap.default_lookback_hours,
                'default_granularity': self.vwap.default_granularity,
                'benchmark_enabled': self.vwap.benchmark_enabled
            },
            'database': {
                'db_path': self.database.db_path,
                'wal_mode': self.database.wal_mode
            },
            'websocket': {
                'enabled': self.websocket.enabled,
                'ticker_enabled': self.websocket.ticker_enabled,
                'user_channel_enabled': self.websocket.user_channel_enabled,
                'price_stale_seconds': self.websocket.price_stale_seconds
            }
        }

    @classmethod
    def for_testing(cls) -> 'AppConfig':
        """
        Create a configuration suitable for testing.

        Returns configuration with shorter TTLs and faster timeouts
        for quicker test execution.

        Returns:
            AppConfig instance optimized for testing.
        """
        config = cls()
        # Override for testing
        config.cache = CacheConfig(
            order_status_ttl=1,
            account_ttl=1,
            fill_ttl=1,
            product_ttl=1
        )
        config.retry = RetryConfig(
            max_retries=1,
            backoff_seconds=0,
            max_backoff=1
        )
        return config


# For backward compatibility with the old CONFIG dict
def get_legacy_config() -> Dict[str, Any]:
    """
    Get configuration in the legacy CONFIG dict format.

    This function provides backward compatibility with code that
    expects the old CONFIG dictionary format.

    Returns:
        Dictionary in the legacy CONFIG format.

    Deprecated:
        Use AppConfig class instead.
    """
    config = AppConfig()
    return {
        'retries': config.retry.max_retries,
        'backoff_in_seconds': config.retry.backoff_seconds,
        'rate_limit_requests': config.rate_limit.requests_per_second,
        'rate_limit_burst': config.rate_limit.burst,
        'twap_slice_delay': config.twap.slice_delay,
    }
