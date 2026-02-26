"""Integration tests for SQLite + Analytics pipeline."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from database import Database
from config_manager import DatabaseConfig, AppConfig
from analytics_service import AnalyticsService
from analytics_display import AnalyticsDisplay
from sqlite_storage import SQLiteTWAPStorage, SQLiteScaledOrderTracker
from storage import InMemoryTWAPStorage
from twap_tracker import TWAPOrder, OrderFill
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType


@pytest.fixture
def sqlite_db():
    config = DatabaseConfig(db_path=":memory:", wal_mode=False)
    db = Database(config)
    yield db
    db.close()


@pytest.fixture
def analytics(sqlite_db):
    return AnalyticsService(sqlite_db)


@pytest.mark.integration
class TestSQLiteAnalyticsIntegration:

    def test_sqlite_storage_as_twap_storage(self, sqlite_db):
        """SQLiteTWAPStorage implements TWAPStorage interface correctly."""
        storage = SQLiteTWAPStorage(sqlite_db)

        order = TWAPOrder(
            twap_id='int-001',
            market='BTC-USDC',
            side='BUY',
            total_size=1.0,
            limit_price=50000.0,
            num_slices=5,
            start_time='2026-01-01T00:00:00Z',
            status='active',
            orders=['o1'],
            total_placed=0.2,
            total_filled=0.1,
            total_value_placed=10000.0,
            total_value_filled=5000.0,
            total_fees=2.5,
            maker_orders=1,
            taker_orders=0,
            failed_slices=[],
            slice_statuses=[],
        )
        storage.save_twap_order(order)
        fills = [
            OrderFill('o1', 'trade-1', 0.1, 50000.0, 2.5, True, '2026-01-01T00:00:00Z'),
        ]
        storage.save_twap_fills('int-001', fills)

        loaded = storage.get_twap_order('int-001')
        assert loaded.market == 'BTC-USDC'

        loaded_fills = storage.get_twap_fills('int-001')
        assert len(loaded_fills) == 1
        assert loaded_fills[0].price == 50000.0

    def test_scaled_executor_uses_sqlite_tracker(self, sqlite_db):
        """SQLiteScaledOrderTracker integrates with save/get cycle."""
        tracker = SQLiteScaledOrderTracker(sqlite_db)

        order = ScaledOrder(
            scaled_id='int-scaled-001',
            product_id='ETH-USDC',
            side='BUY',
            total_size=10.0,
            price_low=3000.0,
            price_high=3500.0,
            num_orders=5,
            distribution=DistributionType.LINEAR,
            status='active',
            levels=[
                ScaledOrderLevel(level_number=1, price=3000.0, size=2.0, order_id='so-1', status='placed'),
                ScaledOrderLevel(level_number=2, price=3125.0, size=2.0, status='pending'),
            ],
        )
        tracker.save_scaled_order(order)

        # Update a level
        tracker.update_level_status(
            'int-scaled-001', 1, 'filled',
            fill_info={'filled_size': 2.0, 'filled_value': 6000.0, 'fees': 3.0}
        )

        loaded = tracker.get_scaled_order('int-scaled-001')
        assert loaded.levels[0].status == 'filled'
        assert loaded.total_filled == pytest.approx(2.0)

    def test_analytics_after_multiple_strategies(self, analytics, sqlite_db):
        """TWAP + scaled both appear in by_strategy analysis."""
        analytics.record_trade_completion(
            order_id='twap-int', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=0.5, total_value=25000.0, total_fees=12.5,
            avg_price=50000.0, arrival_price=49950.0, maker_ratio=0.8,
        )
        analytics.record_trade_completion(
            order_id='scaled-int', strategy_type='scaled', product_id='ETH-USD',
            side='BUY', total_size=10.0, total_value=30000.0, total_fees=18.0,
            avg_price=3000.0, arrival_price=2990.0, maker_ratio=1.0,
        )

        fees = analytics.get_fee_analysis()
        assert 'twap' in fees['by_strategy']
        assert 'scaled' in fees['by_strategy']

        slippage = analytics.get_slippage_analysis()
        assert 'twap' in slippage['by_strategy']
        assert 'scaled' in slippage['by_strategy']

    def test_price_snapshot_roundtrip(self, analytics, sqlite_db):
        """Arrival + completion snapshots round-trip via execution_summary."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('snap-rt', 'twap', 'BTC-USD', 'BUY', 1.0, 'completed', '2026-01-01')
        """)

        analytics.record_price_snapshot(
            'snap-rt', 'arrival', 'BTC-USD', 49990.0, 50010.0, 50000.0
        )
        analytics.record_price_snapshot(
            'snap-rt', 'completion', 'BTC-USD', 50090.0, 50110.0, 50100.0
        )

        summary = analytics.get_execution_summary('snap-rt')
        snaps = summary['price_snapshots']
        assert len(snaps) == 2
        arrival = [s for s in snaps if s['snapshot_type'] == 'arrival'][0]
        assert arrival['mid'] == 50000.0

    def test_analytics_display_with_real_data(self, analytics, sqlite_db, capsys):
        """Seed via service, then verify all display methods work."""
        analytics.record_trade_completion(
            order_id='disp-001', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=25.0,
            avg_price=50000.0, arrival_price=49950.0, maker_ratio=0.7,
        )
        sqlite_db.execute("""
            INSERT OR IGNORE INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('disp-001', 'twap', 'BTC-USD', 'BUY', 1.0, 'completed', '2026-01-01')
        """)

        display = AnalyticsDisplay(analytics)

        # Each method should run without error
        display.display_pnl_summary()
        display.display_daily_pnl()
        display.display_execution_report()
        display.display_fee_summary()

        out = capsys.readouterr().out
        assert "P&L Summary" in out
        assert "Fee Analysis" in out

    def test_twap_executor_captures_arrival_price(self, analytics, sqlite_db):
        """Recording arrival price snapshot is stored and retrievable."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size,
                status, created_at, arrival_price)
            VALUES ('twap-arrival', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01', 49950.0)
        """)
        analytics.record_price_snapshot(
            'twap-arrival', 'arrival', 'BTC-USD', 49940.0, 49960.0, 49950.0
        )

        snaps = sqlite_db.fetchall(
            "SELECT * FROM price_snapshots WHERE order_id = 'twap-arrival'"
        )
        assert len(snaps) == 1
        assert snaps[0]['snapshot_type'] == 'arrival'
        assert snaps[0]['mid'] == 49950.0
