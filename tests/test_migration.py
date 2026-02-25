"""Tests for JSON-to-SQLite migration."""

import os
import json
import tempfile
import shutil
import pytest
from dataclasses import asdict

from database import Database
from config_manager import DatabaseConfig
from migrate_json_to_sqlite import JSONToSQLiteMigrator
from sqlite_storage import SQLiteTWAPStorage, SQLiteScaledOrderTracker, SQLiteConditionalOrderTracker
from twap_tracker import TWAPOrder, OrderFill
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType
from conditional_orders import StopLimitOrder


@pytest.fixture
def sqlite_db():
    config = DatabaseConfig(db_path=":memory:", wal_mode=False)
    db = Database(config)
    yield db
    db.close()


@pytest.fixture
def json_dirs():
    """Create temporary JSON data directories with fixture data."""
    base = tempfile.mkdtemp()

    # TWAP data
    twap_dir = os.path.join(base, "twap_data")
    os.makedirs(os.path.join(twap_dir, "orders"))
    os.makedirs(os.path.join(twap_dir, "fills"))

    twap_order = {
        'twap_id': 'twap-001',
        'market': 'BTC-USDC',
        'side': 'BUY',
        'total_size': 1.0,
        'limit_price': 50000.0,
        'num_slices': 10,
        'start_time': '2026-01-01T00:00:00Z',
        'status': 'completed',
        'orders': ['order-1', 'order-2'],
        'total_placed': 0.2,
        'total_filled': 0.2,
        'total_value_placed': 10000.0,
        'total_value_filled': 10000.0,
        'total_fees': 5.0,
        'maker_orders': 1,
        'taker_orders': 1,
        'failed_slices': [],
        'slice_statuses': [],
    }
    with open(os.path.join(twap_dir, "orders", "twap-001.json"), 'w') as f:
        json.dump(twap_order, f)

    fills = [
        {'order_id': 'order-1', 'trade_id': 'trade-1', 'filled_size': 0.1,
         'price': 50000.0, 'fee': 2.0, 'is_maker': True, 'trade_time': '2026-01-01T00:00:00Z'},
        {'order_id': 'order-2', 'trade_id': 'trade-2', 'filled_size': 0.1,
         'price': 50100.0, 'fee': 3.0, 'is_maker': False, 'trade_time': '2026-01-01T00:01:00Z'},
    ]
    with open(os.path.join(twap_dir, "fills", "twap-001.json"), 'w') as f:
        json.dump(fills, f)

    # Scaled data
    scaled_dir = os.path.join(base, "scaled_data")
    os.makedirs(os.path.join(scaled_dir, "orders"))

    scaled_order = {
        'scaled_id': 'scaled-001',
        'product_id': 'ETH-USDC',
        'side': 'BUY',
        'total_size': 10.0,
        'price_low': 3000.0,
        'price_high': 3500.0,
        'num_orders': 5,
        'distribution': 'linear',
        'status': 'active',
        'levels': [
            {'level_number': 1, 'price': 3000.0, 'size': 2.0, 'order_id': 'so-1', 'status': 'placed',
             'filled_size': 0.0, 'filled_value': 0.0, 'fees': 0.0, 'is_maker': True,
             'placed_at': '2026-01-01T00:00:00Z', 'filled_at': None},
        ],
        'created_at': '2026-01-01T00:00:00Z',
        'completed_at': None,
        'total_filled': 0.0,
        'total_value_filled': 0.0,
        'total_fees': 0.0,
        'maker_orders': 0,
        'taker_orders': 0,
        'metadata': {},
    }
    with open(os.path.join(scaled_dir, "orders", "scaled-001.json"), 'w') as f:
        json.dump(scaled_order, f)

    # Conditional data
    cond_dir = os.path.join(base, "conditional_data")
    os.makedirs(os.path.join(cond_dir, "stop_limit"))
    os.makedirs(os.path.join(cond_dir, "bracket"))
    os.makedirs(os.path.join(cond_dir, "attached_bracket"))

    stop_limit = {
        'order_id': 'cond-001',
        'client_order_id': 'client-cond-001',
        'product_id': 'BTC-USDC',
        'side': 'SELL',
        'base_size': '0.1',
        'stop_price': '48000',
        'limit_price': '47900',
        'stop_direction': 'STOP_DIRECTION_STOP_DOWN',
        'order_type': 'STOP_LOSS',
        'status': 'PENDING',
        'created_at': '2026-01-01T00:00:00Z',
    }
    with open(os.path.join(cond_dir, "stop_limit", "cond-001.json"), 'w') as f:
        json.dump(stop_limit, f)

    yield {
        'base': base,
        'twap_dir': twap_dir,
        'scaled_dir': scaled_dir,
        'conditional_dir': cond_dir,
    }

    shutil.rmtree(base, ignore_errors=True)


class TestJSONToSQLiteMigrator:

    def test_migrate_if_needed_runs(self, sqlite_db, json_dirs):
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=json_dirs['twap_dir'],
            scaled_dir=json_dirs['scaled_dir'],
            conditional_dir=json_dirs['conditional_dir'],
        )
        result = migrator.migrate_if_needed()
        assert result is True

    def test_migrate_twap(self, sqlite_db, json_dirs):
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=json_dirs['twap_dir'],
            scaled_dir=json_dirs['scaled_dir'],
            conditional_dir=json_dirs['conditional_dir'],
        )
        migrator.migrate()

        storage = SQLiteTWAPStorage(sqlite_db)
        order = storage.get_twap_order('twap-001')
        assert order is not None
        assert order.market == 'BTC-USDC'
        assert order.total_size == 1.0

        fills = storage.get_twap_fills('twap-001')
        assert len(fills) == 2

    def test_migrate_scaled(self, sqlite_db, json_dirs):
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=json_dirs['twap_dir'],
            scaled_dir=json_dirs['scaled_dir'],
            conditional_dir=json_dirs['conditional_dir'],
        )
        migrator.migrate()

        tracker = SQLiteScaledOrderTracker(sqlite_db)
        order = tracker.get_scaled_order('scaled-001')
        assert order is not None
        assert order.product_id == 'ETH-USDC'
        assert len(order.levels) == 1

    def test_migrate_conditional(self, sqlite_db, json_dirs):
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=json_dirs['twap_dir'],
            scaled_dir=json_dirs['scaled_dir'],
            conditional_dir=json_dirs['conditional_dir'],
        )
        migrator.migrate()

        tracker = SQLiteConditionalOrderTracker(sqlite_db)
        order = tracker.get_stop_limit_order('cond-001')
        assert order is not None
        assert order.order_type == 'STOP_LOSS'

    def test_idempotent(self, sqlite_db, json_dirs):
        """Second migration should be skipped (DB not empty)."""
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=json_dirs['twap_dir'],
            scaled_dir=json_dirs['scaled_dir'],
            conditional_dir=json_dirs['conditional_dir'],
        )
        assert migrator.migrate_if_needed() is True
        assert migrator.migrate_if_needed() is False

    def test_no_json_dirs(self, sqlite_db):
        """No migration when JSON dirs don't exist."""
        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir="/nonexistent/twap",
            scaled_dir="/nonexistent/scaled",
            conditional_dir="/nonexistent/conditional",
        )
        assert migrator.migrate_if_needed() is False

    def test_empty_json_dirs(self, sqlite_db):
        """No migration when JSON dirs are empty."""
        base = tempfile.mkdtemp()
        twap_dir = os.path.join(base, "twap_data")
        os.makedirs(twap_dir)

        migrator = JSONToSQLiteMigrator(
            sqlite_db,
            twap_dir=twap_dir,
            scaled_dir=os.path.join(base, "scaled_data"),
            conditional_dir=os.path.join(base, "conditional_data"),
        )
        assert migrator.migrate_if_needed() is False
        shutil.rmtree(base, ignore_errors=True)
