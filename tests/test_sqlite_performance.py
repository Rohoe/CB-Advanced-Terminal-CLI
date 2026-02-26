"""Performance tests for SQLite operations."""

import time
import threading
import pytest

from database import Database
from config_manager import DatabaseConfig
from analytics_service import AnalyticsService
from sqlite_storage import SQLiteTWAPStorage, SQLiteScaledOrderTracker
from twap_tracker import TWAPOrder
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType


@pytest.fixture
def perf_db(tmp_path):
    """File-backed DB for realistic performance testing."""
    db_path = str(tmp_path / "perf.db")
    config = DatabaseConfig(db_path=db_path, wal_mode=True)
    db = Database(config)
    yield db
    db.close()


@pytest.mark.slow
class TestSQLitePerformance:

    def test_insert_1000_orders_under_2s(self, perf_db):
        """Inserting 1000 orders should complete in < 2 seconds."""
        start = time.time()
        for i in range(1000):
            perf_db.execute("""
                INSERT INTO orders
                    (order_id, strategy_type, product_id, side, total_size, status, created_at)
                VALUES (?, 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
            """, (f"perf-{i}",))
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Took {elapsed:.2f}s"

        row = perf_db.fetchone("SELECT COUNT(*) as cnt FROM orders")
        assert row['cnt'] == 1000

    def test_insert_10000_fills_under_3s(self, perf_db):
        """Inserting 10000 fills should complete in < 3 seconds."""
        # Pre-create parent order
        perf_db.execute("""
            INSERT INTO orders
                (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('fill-parent', 'twap', 'BTC-USD', 'BUY', 100.0, 'active', '2026-01-01')
        """)

        start = time.time()
        params = []
        for i in range(10000):
            params.append((
                f"fill-{i}", f"child-{i}", 'fill-parent', f"trade-{i}",
                0.01, 50000.0, 0.5, 1, '2026-01-01T00:00:00Z'
            ))

        perf_db.executemany("""
            INSERT INTO fills
                (fill_id, child_order_id, parent_order_id, trade_id,
                 filled_size, price, fee, is_maker, trade_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, params)
        elapsed = time.time() - start
        assert elapsed < 3.0, f"Took {elapsed:.2f}s"

    def test_analytics_query_with_1000_trades(self, perf_db):
        """Analytics queries on 1000 trades should each be < 500ms."""
        analytics = AnalyticsService(perf_db)

        # Seed 1000 trades
        params = []
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        for i in range(1000):
            completed = (now - timedelta(days=i % 30)).isoformat()
            params.append((
                f"trade-{i}", 'BTC-USD', 'BUY' if i % 2 == 0 else 'SELL',
                'twap' if i % 3 == 0 else 'scaled',
                0.1, 5000.0, 2.5, 50000.0, 49950.0, 10.0, 0.7, completed
            ))
        perf_db.executemany("""
            INSERT INTO pnl_ledger
                (order_id, product_id, side, strategy_type, total_size,
                 total_value, total_fees, avg_price, arrival_price,
                 slippage_bps, maker_ratio, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, params)

        queries = [
            lambda: analytics.get_realized_pnl(),
            lambda: analytics.get_slippage_analysis(),
            lambda: analytics.get_fill_rate_analysis(),
            lambda: analytics.get_maker_taker_analysis(),
            lambda: analytics.get_fee_analysis(),
            lambda: analytics.get_cumulative_pnl(days=30),
        ]

        for query in queries:
            start = time.time()
            query()
            elapsed = time.time() - start
            assert elapsed < 0.5, f"Query took {elapsed:.2f}s"

    def test_list_scaled_orders_with_many_levels(self, perf_db):
        """100 orders x 20 levels should list in < 1 second."""
        tracker = SQLiteScaledOrderTracker(perf_db)

        for i in range(100):
            levels = []
            for j in range(20):
                levels.append(ScaledOrderLevel(
                    level_number=j + 1,
                    price=48000.0 + j * 200,
                    size=0.05,
                    status='pending',
                ))
            order = ScaledOrder(
                scaled_id=f'perf-scaled-{i}',
                product_id='BTC-USD',
                side='BUY',
                total_size=1.0,
                price_low=48000.0,
                price_high=52000.0,
                num_orders=20,
                distribution=DistributionType.LINEAR,
                status='active',
                levels=levels,
            )
            tracker.save_scaled_order(order)

        start = time.time()
        orders = tracker.list_scaled_orders()
        elapsed = time.time() - start

        assert len(orders) == 100
        assert elapsed < 1.0, f"Took {elapsed:.2f}s"

    def test_concurrent_analytics_queries(self, perf_db):
        """5 threads querying analytics simultaneously."""
        analytics = AnalyticsService(perf_db)

        # Seed some data
        for i in range(100):
            analytics.record_trade_completion(
                order_id=f'conc-{i}', strategy_type='twap', product_id='BTC-USD',
                side='BUY', total_size=0.1, total_value=5000.0, total_fees=2.5,
                avg_price=50000.0, arrival_price=49950.0, maker_ratio=0.7,
            )

        errors = []
        results = []

        def query_thread():
            try:
                pnl = analytics.get_realized_pnl()
                slippage = analytics.get_slippage_analysis()
                fees = analytics.get_fee_analysis()
                results.append((pnl, slippage, fees))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=query_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors: {errors}"
        assert len(results) == 5
        # All threads should see the same data
        for pnl, _, _ in results:
            assert pnl['num_trades'] == 100
