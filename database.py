"""
SQLite database foundation for the trading terminal.

Provides a thread-safe Database class with WAL mode, context-managed
transactions, and schema initialization for all order types.

Usage:
    from database import Database

    db = Database("trading.db")
    with db.transaction() as conn:
        conn.execute("INSERT INTO orders ...")
"""

import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Optional

from config_manager import DatabaseConfig


class Database:
    """Thread-safe SQLite database with WAL mode and schema management."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize the database.

        Args:
            config: DatabaseConfig instance. Uses defaults if None.
        """
        self._config = config or DatabaseConfig()
        self._db_path = self._config.db_path
        self._local = threading.local()
        self._lock = threading.Lock()

        # Initialize schema on the calling thread's connection
        conn = self._get_connection()
        if self._config.wal_mode:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self.initialize_schema()
        logging.info(f"Database initialized: {self._db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            if self._config.wal_mode:
                conn.execute("PRAGMA journal_mode=WAL")
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def transaction(self):
        """Context manager for database transactions.

        Yields a connection. Commits on success, rolls back on exception.

        Usage:
            with db.transaction() as conn:
                conn.execute("INSERT INTO ...")
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def read(self):
        """Context manager for read-only access (no commit/rollback).

        Usage:
            with db.read() as conn:
                rows = conn.execute("SELECT ...").fetchall()
        """
        conn = self._get_connection()
        yield conn

    def execute(self, sql: str, params=None):
        """Execute a single SQL statement with auto-commit."""
        conn = self._get_connection()
        try:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    def executemany(self, sql: str, params_list):
        """Execute a SQL statement with multiple parameter sets."""
        conn = self._get_connection()
        try:
            result = conn.executemany(sql, params_list)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    def fetchone(self, sql: str, params=None):
        """Execute a query and return one row."""
        conn = self._get_connection()
        if params:
            return conn.execute(sql, params).fetchone()
        return conn.execute(sql).fetchone()

    def fetchall(self, sql: str, params=None):
        """Execute a query and return all rows."""
        conn = self._get_connection()
        if params:
            return conn.execute(sql, params).fetchall()
        return conn.execute(sql).fetchall()

    def close(self):
        """Close the thread-local connection if open."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    def initialize_schema(self):
        """Create all tables if they don't exist."""
        conn = self._get_connection()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        logging.debug("Database schema initialized")


_SCHEMA_SQL = """
-- Unified orders table with strategy_type discriminator
CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,
    strategy_type   TEXT NOT NULL,  -- 'twap', 'scaled', 'conditional', 'limit'
    product_id      TEXT NOT NULL,
    side            TEXT NOT NULL,  -- 'BUY' or 'SELL'
    total_size      REAL NOT NULL,
    limit_price     REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    completed_at    TEXT,
    arrival_price   REAL,          -- market mid price at order creation
    metadata        TEXT DEFAULT '{}',  -- JSON blob for strategy-specific data
    UNIQUE(order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_type);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product_id);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);

-- Child orders (individual limit orders placed by strategies)
CREATE TABLE IF NOT EXISTS child_orders (
    child_order_id  TEXT PRIMARY KEY,
    parent_order_id TEXT NOT NULL,
    slice_number    INTEGER,
    product_id      TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            REAL NOT NULL,
    price           REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    placed_at       TEXT,
    filled_at       TEXT,
    arrival_price   REAL,          -- market mid at slice placement time
    metadata        TEXT DEFAULT '{}',
    FOREIGN KEY (parent_order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_child_parent ON child_orders(parent_order_id);
CREATE INDEX IF NOT EXISTS idx_child_status ON child_orders(status);

-- Fills from the exchange
CREATE TABLE IF NOT EXISTS fills (
    fill_id         TEXT PRIMARY KEY,
    child_order_id  TEXT NOT NULL,
    parent_order_id TEXT NOT NULL,
    trade_id        TEXT,
    filled_size     REAL NOT NULL,
    price           REAL NOT NULL,
    fee             REAL NOT NULL DEFAULT 0,
    is_maker        INTEGER NOT NULL DEFAULT 0,
    trade_time      TEXT NOT NULL,
    liquidity       TEXT           -- 'MAKER' or 'TAKER'
);

CREATE INDEX IF NOT EXISTS idx_fills_child ON fills(child_order_id);
CREATE INDEX IF NOT EXISTS idx_fills_parent ON fills(parent_order_id);
CREATE INDEX IF NOT EXISTS idx_fills_time ON fills(trade_time);

-- TWAP slice details
CREATE TABLE IF NOT EXISTS twap_slices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    twap_order_id   TEXT NOT NULL,
    slice_number    INTEGER NOT NULL,
    scheduled_time  REAL,
    execution_time  REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    execution_price REAL,
    market_bid      REAL,
    market_ask      REAL,
    market_mid      REAL,
    child_order_id  TEXT,
    skip_reason     TEXT,
    FOREIGN KEY (twap_order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_twap_slices_order ON twap_slices(twap_order_id);

-- Scaled order levels
CREATE TABLE IF NOT EXISTS scaled_levels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scaled_order_id TEXT NOT NULL,
    level_number    INTEGER NOT NULL,
    price           REAL NOT NULL,
    size            REAL NOT NULL,
    child_order_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    filled_size     REAL NOT NULL DEFAULT 0,
    filled_value    REAL NOT NULL DEFAULT 0,
    fees            REAL NOT NULL DEFAULT 0,
    is_maker        INTEGER NOT NULL DEFAULT 1,
    placed_at       TEXT,
    filled_at       TEXT,
    FOREIGN KEY (scaled_order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_scaled_levels_order ON scaled_levels(scaled_order_id);

-- Price snapshots for analytics
CREATE TABLE IF NOT EXISTS price_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL,
    snapshot_type   TEXT NOT NULL,  -- 'arrival', 'slice', 'completion'
    product_id      TEXT NOT NULL,
    bid             REAL,
    ask             REAL,
    mid             REAL,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_order ON price_snapshots(order_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON price_snapshots(timestamp);

-- P&L ledger for trade completion tracking
CREATE TABLE IF NOT EXISTS pnl_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL,
    product_id      TEXT NOT NULL,
    side            TEXT NOT NULL,
    strategy_type   TEXT NOT NULL,
    total_size      REAL NOT NULL,
    total_value     REAL NOT NULL,
    total_fees      REAL NOT NULL,
    avg_price       REAL NOT NULL,
    arrival_price   REAL,
    slippage_bps    REAL,          -- slippage in basis points
    maker_ratio     REAL,          -- fraction of fills that were maker
    completed_at    TEXT NOT NULL,
    metadata        TEXT DEFAULT '{}',
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_pnl_product ON pnl_ledger(product_id);
CREATE INDEX IF NOT EXISTS idx_pnl_time ON pnl_ledger(completed_at);
CREATE INDEX IF NOT EXISTS idx_pnl_strategy ON pnl_ledger(strategy_type);
"""
