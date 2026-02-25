"""
JSON-to-SQLite migration for existing order data.

Reads JSON files from twap_data/, scaled_data/, conditional_data/ and
inserts them into the SQLite database. Auto-runs on startup if JSON
directories contain data and the database is empty.

Usage:
    from migrate_json_to_sqlite import JSONToSQLiteMigrator

    migrator = JSONToSQLiteMigrator(database)
    migrator.migrate_if_needed()
"""

import os
import logging
from typing import Optional

from database import Database
from twap_tracker import TWAPTracker
from scaled_order_tracker import ScaledOrderTracker
from conditional_order_tracker import ConditionalOrderTracker
from sqlite_storage import (
    SQLiteTWAPStorage,
    SQLiteScaledOrderTracker,
    SQLiteConditionalOrderTracker,
)


class JSONToSQLiteMigrator:
    """Migrates existing JSON-based order data into SQLite."""

    def __init__(self, db: Database,
                 twap_dir: str = "twap_data",
                 scaled_dir: str = "scaled_data",
                 conditional_dir: str = "conditional_data"):
        self._db = db
        self._twap_dir = twap_dir
        self._scaled_dir = scaled_dir
        self._conditional_dir = conditional_dir

    def migrate_if_needed(self) -> bool:
        """Run migration only if JSON dirs have data and DB is empty.

        Returns:
            True if migration ran, False if skipped.
        """
        if not self._has_json_data():
            logging.debug("No JSON data directories found, skipping migration")
            return False

        if not self._db_is_empty():
            logging.debug("Database already has data, skipping migration")
            return False

        logging.info("Starting JSON-to-SQLite migration")
        self.migrate()
        logging.info("JSON-to-SQLite migration complete")
        return True

    def migrate(self):
        """Run full migration of all order types."""
        self._migrate_twap()
        self._migrate_scaled()
        self._migrate_conditional()

    def _has_json_data(self) -> bool:
        """Check if any JSON data directories exist with data."""
        for data_dir in [self._twap_dir, self._scaled_dir, self._conditional_dir]:
            if not os.path.isdir(data_dir):
                continue
            for root, dirs, files in os.walk(data_dir):
                if any(f.endswith('.json') for f in files):
                    return True
        return False

    def _db_is_empty(self) -> bool:
        """Check if the orders table is empty."""
        row = self._db.fetchone("SELECT COUNT(*) as cnt FROM orders")
        return row['cnt'] == 0

    def _migrate_twap(self):
        """Migrate TWAP orders and fills from JSON to SQLite."""
        if not os.path.isdir(self._twap_dir):
            return

        try:
            json_tracker = TWAPTracker(self._twap_dir)
            sqlite_storage = SQLiteTWAPStorage(self._db)

            twap_ids = json_tracker.list_twap_orders()
            migrated = 0

            for twap_id in twap_ids:
                try:
                    order = json_tracker.get_twap_order(twap_id)
                    if order:
                        sqlite_storage.save_twap_order(order)
                        fills = json_tracker.get_twap_fills(twap_id)
                        if fills:
                            sqlite_storage.save_twap_fills(twap_id, fills)
                        migrated += 1
                except Exception as e:
                    logging.error(f"Error migrating TWAP order {twap_id}: {e}")

            logging.info(f"Migrated {migrated}/{len(twap_ids)} TWAP orders")
        except Exception as e:
            logging.error(f"Error during TWAP migration: {e}")

    def _migrate_scaled(self):
        """Migrate scaled orders from JSON to SQLite."""
        if not os.path.isdir(self._scaled_dir):
            return

        try:
            json_tracker = ScaledOrderTracker(self._scaled_dir)
            sqlite_tracker = SQLiteScaledOrderTracker(self._db)

            orders = json_tracker.list_scaled_orders()
            migrated = 0

            for order in orders:
                try:
                    sqlite_tracker.save_scaled_order(order)
                    migrated += 1
                except Exception as e:
                    logging.error(f"Error migrating scaled order {order.scaled_id}: {e}")

            logging.info(f"Migrated {migrated}/{len(orders)} scaled orders")
        except Exception as e:
            logging.error(f"Error during scaled migration: {e}")

    def _migrate_conditional(self):
        """Migrate conditional orders from JSON to SQLite."""
        if not os.path.isdir(self._conditional_dir):
            return

        try:
            json_tracker = ConditionalOrderTracker(self._conditional_dir)
            sqlite_tracker = SQLiteConditionalOrderTracker(self._db)

            # Stop-limit orders
            stop_limit_orders = json_tracker.list_stop_limit_orders()
            for order in stop_limit_orders:
                try:
                    sqlite_tracker.save_stop_limit_order(order)
                except Exception as e:
                    logging.error(f"Error migrating stop-limit {order.order_id}: {e}")

            # Bracket orders
            bracket_orders = json_tracker.list_bracket_orders()
            for order in bracket_orders:
                try:
                    sqlite_tracker.save_bracket_order(order)
                except Exception as e:
                    logging.error(f"Error migrating bracket {order.order_id}: {e}")

            # Attached bracket orders
            attached_orders = json_tracker.list_attached_bracket_orders()
            for order in attached_orders:
                try:
                    sqlite_tracker.save_attached_bracket_order(order)
                except Exception as e:
                    logging.error(f"Error migrating attached bracket {order.entry_order_id}: {e}")

            total = len(stop_limit_orders) + len(bracket_orders) + len(attached_orders)
            logging.info(f"Migrated {total} conditional orders")
        except Exception as e:
            logging.error(f"Error during conditional migration: {e}")
