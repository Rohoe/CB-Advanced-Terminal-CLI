"""Tests for SQLite storage implementations."""

import pytest
from database import Database
from config_manager import DatabaseConfig
from sqlite_storage import (
    SQLiteTWAPStorage,
    SQLiteScaledOrderTracker,
    SQLiteConditionalOrderTracker,
)
from twap_tracker import TWAPOrder, OrderFill
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType
from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder


@pytest.fixture
def sqlite_db():
    """In-memory SQLite database for testing."""
    config = DatabaseConfig(db_path=":memory:", wal_mode=False)
    db = Database(config)
    yield db
    db.close()


@pytest.fixture
def sqlite_twap_storage(sqlite_db):
    return SQLiteTWAPStorage(sqlite_db)


@pytest.fixture
def sqlite_scaled_tracker(sqlite_db):
    return SQLiteScaledOrderTracker(sqlite_db)


@pytest.fixture
def sqlite_conditional_tracker(sqlite_db):
    return SQLiteConditionalOrderTracker(sqlite_db)


# =============================================================================
# TWAP Storage Tests
# =============================================================================

class TestSQLiteTWAPStorage:

    def test_save_and_get_order(self, sqlite_twap_storage, sample_twap_order):
        sqlite_twap_storage.save_twap_order(sample_twap_order)
        loaded = sqlite_twap_storage.get_twap_order(sample_twap_order.twap_id)
        assert loaded is not None
        assert loaded.twap_id == sample_twap_order.twap_id
        assert loaded.market == sample_twap_order.market
        assert loaded.side == sample_twap_order.side
        assert loaded.total_size == sample_twap_order.total_size
        assert loaded.num_slices == sample_twap_order.num_slices

    def test_get_nonexistent_order(self, sqlite_twap_storage):
        assert sqlite_twap_storage.get_twap_order("nonexistent") is None

    def test_save_and_get_fills(self, sqlite_twap_storage, sample_twap_order, sample_order_fills):
        sqlite_twap_storage.save_twap_order(sample_twap_order)
        sqlite_twap_storage.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        fills = sqlite_twap_storage.get_twap_fills(sample_twap_order.twap_id)
        assert len(fills) == 2
        assert fills[0].filled_size == 0.1
        assert fills[1].price == 50100.0

    def test_get_fills_empty(self, sqlite_twap_storage):
        assert sqlite_twap_storage.get_twap_fills("nonexistent") == []

    def test_list_twap_orders(self, sqlite_twap_storage, sample_twap_order):
        sqlite_twap_storage.save_twap_order(sample_twap_order)
        ids = sqlite_twap_storage.list_twap_orders()
        assert sample_twap_order.twap_id in ids

    def test_delete_twap_order(self, sqlite_twap_storage, sample_twap_order, sample_order_fills):
        sqlite_twap_storage.save_twap_order(sample_twap_order)
        sqlite_twap_storage.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        assert sqlite_twap_storage.delete_twap_order(sample_twap_order.twap_id)
        assert sqlite_twap_storage.get_twap_order(sample_twap_order.twap_id) is None
        assert sqlite_twap_storage.get_twap_fills(sample_twap_order.twap_id) == []

    def test_delete_nonexistent(self, sqlite_twap_storage):
        assert not sqlite_twap_storage.delete_twap_order("nonexistent")

    def test_calculate_statistics(self, sqlite_twap_storage, sample_twap_order, sample_order_fills):
        sqlite_twap_storage.save_twap_order(sample_twap_order)
        sqlite_twap_storage.save_twap_fills(sample_twap_order.twap_id, sample_order_fills)

        stats = sqlite_twap_storage.calculate_twap_statistics(sample_twap_order.twap_id)
        assert stats['twap_id'] == sample_twap_order.twap_id
        assert stats['num_fills'] == 2
        assert stats['total_filled'] == pytest.approx(0.2)
        assert stats['completion_rate'] == pytest.approx(20.0)

    def test_update_order(self, sqlite_twap_storage, sample_twap_order):
        sqlite_twap_storage.save_twap_order(sample_twap_order)

        sample_twap_order.status = 'completed'
        sample_twap_order.total_filled = 1.0
        sqlite_twap_storage.save_twap_order(sample_twap_order)

        loaded = sqlite_twap_storage.get_twap_order(sample_twap_order.twap_id)
        assert loaded.status == 'completed'


# =============================================================================
# Scaled Order Tracker Tests
# =============================================================================

@pytest.fixture
def sample_scaled_order():
    return ScaledOrder(
        scaled_id='test-scaled-123',
        product_id='BTC-USDC',
        side='BUY',
        total_size=1.0,
        price_low=48000.0,
        price_high=52000.0,
        num_orders=5,
        distribution=DistributionType.LINEAR,
        status='active',
        levels=[
            ScaledOrderLevel(level_number=1, price=48000.0, size=0.2, order_id='o1', status='placed'),
            ScaledOrderLevel(level_number=2, price=49000.0, size=0.2, order_id='o2', status='placed'),
            ScaledOrderLevel(level_number=3, price=50000.0, size=0.2, order_id='o3', status='placed'),
            ScaledOrderLevel(level_number=4, price=51000.0, size=0.2, status='pending'),
            ScaledOrderLevel(level_number=5, price=52000.0, size=0.2, status='pending'),
        ]
    )


class TestSQLiteScaledOrderTracker:

    def test_save_and_get(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        loaded = sqlite_scaled_tracker.get_scaled_order(sample_scaled_order.scaled_id)
        assert loaded is not None
        assert loaded.scaled_id == sample_scaled_order.scaled_id
        assert loaded.product_id == 'BTC-USDC'
        assert loaded.distribution == DistributionType.LINEAR
        assert len(loaded.levels) == 5
        assert loaded.levels[0].price == 48000.0

    def test_get_nonexistent(self, sqlite_scaled_tracker):
        assert sqlite_scaled_tracker.get_scaled_order("nonexistent") is None

    def test_list_orders(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        orders = sqlite_scaled_tracker.list_scaled_orders()
        assert len(orders) == 1
        assert orders[0].scaled_id == sample_scaled_order.scaled_id

    def test_list_orders_filtered(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        assert len(sqlite_scaled_tracker.list_scaled_orders(status='active')) == 1
        assert len(sqlite_scaled_tracker.list_scaled_orders(status='completed')) == 0

    def test_update_order_status(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        result = sqlite_scaled_tracker.update_order_status(
            sample_scaled_order.scaled_id, 'completed',
            fill_info={'total_filled': 1.0}
        )
        assert result
        loaded = sqlite_scaled_tracker.get_scaled_order(sample_scaled_order.scaled_id)
        assert loaded.status == 'completed'
        assert loaded.total_filled == 1.0

    def test_update_level_status(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        result = sqlite_scaled_tracker.update_level_status(
            sample_scaled_order.scaled_id, 1, 'filled',
            fill_info={'filled_size': 0.2, 'filled_value': 9600.0, 'fees': 1.0}
        )
        assert result
        loaded = sqlite_scaled_tracker.get_scaled_order(sample_scaled_order.scaled_id)
        assert loaded.levels[0].status == 'filled'
        assert loaded.levels[0].filled_size == 0.2
        assert loaded.total_filled == pytest.approx(0.2)

    def test_delete(self, sqlite_scaled_tracker, sample_scaled_order):
        sqlite_scaled_tracker.save_scaled_order(sample_scaled_order)
        assert sqlite_scaled_tracker.delete_scaled_order(sample_scaled_order.scaled_id)
        assert sqlite_scaled_tracker.get_scaled_order(sample_scaled_order.scaled_id) is None


# =============================================================================
# Conditional Order Tracker Tests
# =============================================================================

@pytest.fixture
def sample_stop_limit():
    return StopLimitOrder(
        order_id='sl-123',
        client_order_id='client-sl-123',
        product_id='BTC-USDC',
        side='SELL',
        base_size='0.1',
        stop_price='48000',
        limit_price='47900',
        stop_direction='STOP_DIRECTION_STOP_DOWN',
        order_type='STOP_LOSS',
        status='PENDING',
        created_at='2026-01-01T00:00:00Z'
    )


@pytest.fixture
def sample_bracket():
    return BracketOrder(
        order_id='br-123',
        client_order_id='client-br-123',
        product_id='BTC-USDC',
        side='SELL',
        base_size='0.1',
        limit_price='55000',
        stop_trigger_price='48000',
        status='PENDING',
        created_at='2026-01-01T00:00:00Z'
    )


@pytest.fixture
def sample_attached_bracket():
    return AttachedBracketOrder(
        entry_order_id='ab-123',
        client_order_id='client-ab-123',
        product_id='BTC-USDC',
        side='BUY',
        base_size='0.1',
        entry_limit_price='50000',
        take_profit_price='55000',
        stop_loss_price='48000',
        status='PENDING',
        created_at='2026-01-01T00:00:00Z'
    )


class TestSQLiteConditionalOrderTracker:

    def test_save_get_stop_limit(self, sqlite_conditional_tracker, sample_stop_limit):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        loaded = sqlite_conditional_tracker.get_stop_limit_order(sample_stop_limit.order_id)
        assert loaded is not None
        assert loaded.order_id == sample_stop_limit.order_id
        assert loaded.stop_price == '48000'
        assert loaded.order_type == 'STOP_LOSS'

    def test_save_get_bracket(self, sqlite_conditional_tracker, sample_bracket):
        sqlite_conditional_tracker.save_bracket_order(sample_bracket)
        loaded = sqlite_conditional_tracker.get_bracket_order(sample_bracket.order_id)
        assert loaded is not None
        assert loaded.stop_trigger_price == '48000'

    def test_save_get_attached_bracket(self, sqlite_conditional_tracker, sample_attached_bracket):
        sqlite_conditional_tracker.save_attached_bracket_order(sample_attached_bracket)
        loaded = sqlite_conditional_tracker.get_attached_bracket_order(sample_attached_bracket.entry_order_id)
        assert loaded is not None
        assert loaded.take_profit_price == '55000'

    def test_list_all_active(self, sqlite_conditional_tracker, sample_stop_limit, sample_bracket):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        sqlite_conditional_tracker.save_bracket_order(sample_bracket)
        active = sqlite_conditional_tracker.list_all_active_orders()
        assert len(active) == 2

    def test_get_order_by_id(self, sqlite_conditional_tracker, sample_stop_limit):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        found = sqlite_conditional_tracker.get_order_by_id(sample_stop_limit.order_id)
        assert found is not None
        assert found.order_id == sample_stop_limit.order_id

    def test_update_status(self, sqlite_conditional_tracker, sample_stop_limit):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        result = sqlite_conditional_tracker.update_order_status(
            sample_stop_limit.order_id, 'stop_limit', 'FILLED',
            fill_info={'filled_size': '0.1', 'filled_value': '4800', 'fees': '2.88'}
        )
        assert result
        loaded = sqlite_conditional_tracker.get_stop_limit_order(sample_stop_limit.order_id)
        assert loaded.status == 'FILLED'
        assert loaded.filled_size == '0.1'

    def test_delete_order(self, sqlite_conditional_tracker, sample_stop_limit):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        assert sqlite_conditional_tracker.delete_order(sample_stop_limit.order_id, 'stop_limit')
        assert sqlite_conditional_tracker.get_stop_limit_order(sample_stop_limit.order_id) is None

    def test_statistics(self, sqlite_conditional_tracker, sample_stop_limit, sample_bracket):
        sqlite_conditional_tracker.save_stop_limit_order(sample_stop_limit)
        sqlite_conditional_tracker.save_bracket_order(sample_bracket)
        stats = sqlite_conditional_tracker.get_statistics()
        assert stats['stop_limit']['total'] == 1
        assert stats['stop_limit']['active'] == 1
        assert stats['bracket']['total'] == 1


# =============================================================================
# Database Tests
# =============================================================================

class TestDatabase:

    def test_schema_creation(self, sqlite_db):
        """Verify all tables are created."""
        tables = sqlite_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [t['name'] for t in tables]
        assert 'orders' in table_names
        assert 'child_orders' in table_names
        assert 'fills' in table_names
        assert 'twap_slices' in table_names
        assert 'scaled_levels' in table_names
        assert 'price_snapshots' in table_names
        assert 'pnl_ledger' in table_names

    def test_transaction_commit(self, sqlite_db):
        with sqlite_db.transaction() as conn:
            conn.execute(
                "INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('test-1', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
            )
        row = sqlite_db.fetchone("SELECT * FROM orders WHERE order_id = 'test-1'")
        assert row is not None

    def test_transaction_rollback(self, sqlite_db):
        try:
            with sqlite_db.transaction() as conn:
                conn.execute(
                    "INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ('test-2', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
                )
                raise ValueError("Intentional error")
        except ValueError:
            pass
        row = sqlite_db.fetchone("SELECT * FROM orders WHERE order_id = 'test-2'")
        assert row is None

    def test_idempotent_schema(self, sqlite_db):
        """Schema creation should be idempotent."""
        sqlite_db.initialize_schema()
        sqlite_db.initialize_schema()
        tables = sqlite_db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(tables) > 0
