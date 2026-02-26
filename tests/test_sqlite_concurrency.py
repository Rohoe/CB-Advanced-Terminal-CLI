"""Tests for SQLite concurrency with WAL mode."""

import threading
import pytest

from database import Database
from config_manager import DatabaseConfig


@pytest.fixture
def file_db(tmp_path):
    """Temp-file SQLite database with WAL mode."""
    db_path = str(tmp_path / "concurrent.db")
    config = DatabaseConfig(db_path=db_path, wal_mode=True)
    db = Database(config)
    yield db
    db.close()


class TestSQLiteConcurrency:

    def test_wal_mode_enabled(self, file_db):
        """WAL journal mode should be active."""
        row = file_db.fetchone("PRAGMA journal_mode")
        journal = list(row)[0]
        assert journal == 'wal'

    def test_concurrent_writes(self, tmp_path):
        """5 threads x 50 orders should all persist."""
        db_path = str(tmp_path / "writes.db")
        config = DatabaseConfig(db_path=db_path, wal_mode=True)
        db = Database(config)

        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    oid = f"t{thread_id}-o{i}"
                    db.execute("""
                        INSERT INTO orders
                            (order_id, strategy_type, product_id, side, total_size, status, created_at)
                        VALUES (?, 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
                    """, (oid,))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Writer errors: {errors}"

        row = db.fetchone("SELECT COUNT(*) as cnt FROM orders")
        assert row['cnt'] == 250
        db.close()

    def test_concurrent_read_write(self, tmp_path):
        """Writer + reader threads, reads should return consistent data."""
        db_path = str(tmp_path / "readwrite.db")
        config = DatabaseConfig(db_path=db_path, wal_mode=True)
        db = Database(config)

        # Pre-seed 10 rows
        for i in range(10):
            db.execute("""
                INSERT INTO orders
                    (order_id, strategy_type, product_id, side, total_size, status, created_at)
                VALUES (?, 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
            """, (f"seed-{i}",))

        read_counts = []
        write_errors = []

        def writer():
            try:
                for i in range(20):
                    db.execute("""
                        INSERT INTO orders
                            (order_id, strategy_type, product_id, side, total_size, status, created_at)
                        VALUES (?, 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
                    """, (f"new-{i}",))
            except Exception as e:
                write_errors.append(e)

        def reader():
            for _ in range(20):
                row = db.fetchone("SELECT COUNT(*) as cnt FROM orders")
                read_counts.append(row['cnt'])

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start()
        rt.start()
        wt.join()
        rt.join()

        assert write_errors == []
        # All reads should see >= 10 (the seed), each monotonically increasing or stable
        for c in read_counts:
            assert c >= 10

        db.close()

    def test_concurrent_twap_save_and_fill(self, tmp_path):
        """Concurrent saves of orders and fills should not conflict."""
        db_path = str(tmp_path / "twapfills.db")
        config = DatabaseConfig(db_path=db_path, wal_mode=True)
        db = Database(config)

        # Pre-create parent order
        db.execute("""
            INSERT INTO orders
                (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('parent-1', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
        """)

        errors = []

        def write_orders():
            try:
                for i in range(30):
                    db.execute("""
                        INSERT INTO orders
                            (order_id, strategy_type, product_id, side, total_size, status, created_at)
                        VALUES (?, 'twap', 'BTC-USD', 'BUY', 0.1, 'active', '2026-01-01')
                    """, (f"order-{i}",))
            except Exception as e:
                errors.append(e)

        def write_fills():
            try:
                for i in range(30):
                    db.execute("""
                        INSERT INTO fills
                            (fill_id, child_order_id, parent_order_id, trade_id,
                             filled_size, price, fee, is_maker, trade_time)
                        VALUES (?, ?, 'parent-1', ?, 0.01, 50000.0, 0.5, 1, '2026-01-01')
                    """, (f"fill-{i}", f"child-{i}", f"trade-{i}"))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=write_orders)
        t2 = threading.Thread(target=write_fills)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Concurrent errors: {errors}"

        orders = db.fetchone("SELECT COUNT(*) as cnt FROM orders")
        fills = db.fetchone("SELECT COUNT(*) as cnt FROM fills")
        assert orders['cnt'] == 31  # parent + 30
        assert fills['cnt'] == 30

        db.close()

    def test_transaction_isolation(self, tmp_path):
        """Uncommitted data should not be visible to other threads."""
        db_path = str(tmp_path / "isolation.db")
        config = DatabaseConfig(db_path=db_path, wal_mode=True)
        db = Database(config)

        barrier = threading.Barrier(2, timeout=5)
        read_result = [None]

        def writer():
            conn = db._get_connection()
            conn.execute("""
                INSERT INTO orders
                    (order_id, strategy_type, product_id, side, total_size, status, created_at)
                VALUES ('iso-1', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
            """)
            # Signal reader to check, before commit
            barrier.wait()
            # Wait for reader to complete check
            barrier.wait()
            conn.commit()

        def reader():
            # Wait for writer to insert (but not commit)
            barrier.wait()
            row = db.fetchone("SELECT COUNT(*) as cnt FROM orders WHERE order_id = 'iso-1'")
            read_result[0] = row['cnt']
            # Signal writer to proceed with commit
            barrier.wait()

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start()
        rt.start()
        wt.join()
        rt.join()

        # Reader should not see uncommitted data (WAL isolation)
        assert read_result[0] == 0

        # But after commit, the data should be there
        row = db.fetchone("SELECT COUNT(*) as cnt FROM orders WHERE order_id = 'iso-1'")
        assert row['cnt'] == 1

        db.close()
