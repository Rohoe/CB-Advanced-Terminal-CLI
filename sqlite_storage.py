"""
SQLite-backed storage implementations for all order types.

Provides the same public APIs as the JSON-based trackers, backed by SQLite
for queryable persistence and cross-strategy analytics.

Usage:
    from database import Database
    from sqlite_storage import SQLiteTWAPStorage, SQLiteScaledOrderTracker, SQLiteConditionalOrderTracker

    db = Database()
    twap_storage = SQLiteTWAPStorage(db)
    scaled_tracker = SQLiteScaledOrderTracker(db)
    conditional_tracker = SQLiteConditionalOrderTracker(db)
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Union
from dataclasses import asdict

from database import Database
from storage import TWAPStorage
from twap_tracker import TWAPOrder, OrderFill
from scaled_order_tracker import ScaledOrderStorage
from scaled_orders import ScaledOrder, ScaledOrderLevel, DistributionType
from conditional_order_tracker import ConditionalOrderStorage
from conditional_orders import StopLimitOrder, BracketOrder, AttachedBracketOrder


class SQLiteTWAPStorage(TWAPStorage):
    """SQLite-backed TWAP order storage."""

    def __init__(self, db: Database):
        self._db = db

    def save_twap_order(self, twap_order: TWAPOrder) -> None:
        metadata = json.dumps({
            'num_slices': twap_order.num_slices,
            'total_placed': twap_order.total_placed,
            'total_value_placed': twap_order.total_value_placed,
            'maker_orders': twap_order.maker_orders,
            'taker_orders': twap_order.taker_orders,
            'failed_slices': twap_order.failed_slices or [],
            'slice_statuses': twap_order.slice_statuses or [],
            'orders': twap_order.orders,
        })

        with self._db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                    (order_id, strategy_type, product_id, side, total_size,
                     limit_price, status, created_at, metadata)
                VALUES (?, 'twap', ?, ?, ?, ?, ?, ?, ?)
            """, (
                twap_order.twap_id, twap_order.market, twap_order.side,
                twap_order.total_size, twap_order.limit_price,
                twap_order.status, twap_order.start_time, metadata
            ))

        logging.debug(f"Saved TWAP order {twap_order.twap_id} to SQLite")

    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        row = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ? AND strategy_type = 'twap'",
            (twap_id,)
        )
        if not row:
            return None
        return self._row_to_twap_order(row)

    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]) -> None:
        with self._db.transaction() as conn:
            # Remove existing fills for this order
            conn.execute(
                "DELETE FROM fills WHERE parent_order_id = ?", (twap_id,)
            )
            for fill in fills:
                fill_id = f"{fill.order_id}-{fill.trade_id}"
                conn.execute("""
                    INSERT OR REPLACE INTO fills
                        (fill_id, child_order_id, parent_order_id, trade_id,
                         filled_size, price, fee, is_maker, trade_time, liquidity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fill_id, fill.order_id, twap_id, fill.trade_id,
                    fill.filled_size, fill.price, fill.fee,
                    1 if fill.is_maker else 0, fill.trade_time,
                    'MAKER' if fill.is_maker else 'TAKER'
                ))

        logging.debug(f"Saved {len(fills)} fills for TWAP {twap_id}")

    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        rows = self._db.fetchall(
            "SELECT * FROM fills WHERE parent_order_id = ?", (twap_id,)
        )
        fills = []
        for row in rows:
            fills.append(OrderFill(
                order_id=row['child_order_id'],
                trade_id=row['trade_id'] or '',
                filled_size=row['filled_size'],
                price=row['price'],
                fee=row['fee'],
                is_maker=bool(row['is_maker']),
                trade_time=row['trade_time']
            ))
        return fills

    def list_twap_orders(self) -> List[str]:
        rows = self._db.fetchall(
            "SELECT order_id FROM orders WHERE strategy_type = 'twap'"
        )
        return [row['order_id'] for row in rows]

    def delete_twap_order(self, twap_id: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM fills WHERE parent_order_id = ?", (twap_id,))
            conn.execute("DELETE FROM twap_slices WHERE twap_order_id = ?", (twap_id,))
            conn.execute("DELETE FROM child_orders WHERE parent_order_id = ?", (twap_id,))
            result = conn.execute(
                "DELETE FROM orders WHERE order_id = ? AND strategy_type = 'twap'",
                (twap_id,)
            )
        deleted = result.rowcount > 0
        if deleted:
            logging.info(f"Deleted TWAP order {twap_id} from SQLite")
        return deleted

    def calculate_twap_statistics(self, twap_id: str) -> dict:
        order = self.get_twap_order(twap_id)
        if not order:
            return {}

        fills = self.get_twap_fills(twap_id)

        stats = {
            'twap_id': twap_id,
            'market': order.market,
            'side': order.side,
            'total_size': order.total_size,
            'total_filled': sum(f.filled_size for f in fills),
            'total_value_filled': sum(f.filled_size * f.price for f in fills),
            'total_fees': sum(f.fee for f in fills),
            'maker_fills': sum(1 for f in fills if f.is_maker),
            'taker_fills': sum(1 for f in fills if not f.is_maker),
            'num_fills': len(fills),
            'completion_rate': 0.0,
            'average_price': 0.0,
            'vwap': 0.0,
        }

        if stats['total_filled'] > 0:
            stats['completion_rate'] = (stats['total_filled'] / order.total_size) * 100
            stats['vwap'] = stats['total_value_filled'] / stats['total_filled']

        if fills:
            stats['first_fill_time'] = min(f.trade_time for f in fills)
            stats['last_fill_time'] = max(f.trade_time for f in fills)

        return stats

    def _row_to_twap_order(self, row) -> TWAPOrder:
        metadata = json.loads(row['metadata']) if row['metadata'] else {}
        return TWAPOrder(
            twap_id=row['order_id'],
            market=row['product_id'],
            side=row['side'],
            total_size=row['total_size'],
            limit_price=row['limit_price'] or 0.0,
            num_slices=metadata.get('num_slices', 0),
            start_time=row['created_at'],
            status=row['status'],
            orders=metadata.get('orders', []),
            total_placed=metadata.get('total_placed', 0.0),
            total_filled=metadata.get('total_filled', 0.0),
            total_value_placed=metadata.get('total_value_placed', 0.0),
            total_value_filled=metadata.get('total_value_filled', 0.0),
            total_fees=metadata.get('total_fees', 0.0),
            maker_orders=metadata.get('maker_orders', 0),
            taker_orders=metadata.get('taker_orders', 0),
            failed_slices=metadata.get('failed_slices', []),
            slice_statuses=metadata.get('slice_statuses', []),
        )


class SQLiteScaledOrderTracker(ScaledOrderStorage):
    """SQLite-backed scaled order storage."""

    def __init__(self, db: Database):
        self._db = db

    def save_scaled_order(self, order: ScaledOrder) -> None:
        metadata = json.dumps({
            'price_low': order.price_low,
            'price_high': order.price_high,
            'num_orders': order.num_orders,
            'distribution': order.distribution.value,
            'total_filled': order.total_filled,
            'total_value_filled': order.total_value_filled,
            'total_fees': order.total_fees,
            'maker_orders': order.maker_orders,
            'taker_orders': order.taker_orders,
            'extra': order.metadata,
        })

        with self._db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                    (order_id, strategy_type, product_id, side, total_size,
                     status, created_at, completed_at, metadata)
                VALUES (?, 'scaled', ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.scaled_id, order.product_id, order.side,
                order.total_size, order.status, order.created_at,
                order.completed_at, metadata
            ))

            # Save levels
            conn.execute(
                "DELETE FROM scaled_levels WHERE scaled_order_id = ?",
                (order.scaled_id,)
            )
            for level in order.levels:
                conn.execute("""
                    INSERT INTO scaled_levels
                        (scaled_order_id, level_number, price, size,
                         child_order_id, status, filled_size, filled_value,
                         fees, is_maker, placed_at, filled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.scaled_id, level.level_number, level.price,
                    level.size, level.order_id, level.status,
                    level.filled_size, level.filled_value, level.fees,
                    1 if level.is_maker else 0, level.placed_at, level.filled_at
                ))

        logging.debug(f"Saved scaled order {order.scaled_id} to SQLite")

    def get_scaled_order(self, scaled_id: str) -> Optional[ScaledOrder]:
        row = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ? AND strategy_type = 'scaled'",
            (scaled_id,)
        )
        if not row:
            return None

        level_rows = self._db.fetchall(
            "SELECT * FROM scaled_levels WHERE scaled_order_id = ? ORDER BY level_number",
            (scaled_id,)
        )

        return self._rows_to_scaled_order(row, level_rows)

    def list_scaled_orders(self, status: Optional[str] = None) -> List[ScaledOrder]:
        if status:
            rows = self._db.fetchall(
                "SELECT * FROM orders WHERE strategy_type = 'scaled' AND status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM orders WHERE strategy_type = 'scaled' ORDER BY created_at DESC"
            )

        orders = []
        for row in rows:
            level_rows = self._db.fetchall(
                "SELECT * FROM scaled_levels WHERE scaled_order_id = ? ORDER BY level_number",
                (row['order_id'],)
            )
            order = self._rows_to_scaled_order(row, level_rows)
            if order:
                orders.append(order)
        return orders

    def update_order_status(self, scaled_id: str, status: str,
                            fill_info: Optional[dict] = None) -> bool:
        order = self.get_scaled_order(scaled_id)
        if not order:
            return False
        order.status = status
        if fill_info:
            order.total_filled = fill_info.get('total_filled', order.total_filled)
            order.total_value_filled = fill_info.get('total_value_filled', order.total_value_filled)
            order.total_fees = fill_info.get('total_fees', order.total_fees)
        self.save_scaled_order(order)
        return True

    def update_level_status(self, scaled_id: str, level_number: int, status: str,
                            order_id: Optional[str] = None,
                            fill_info: Optional[dict] = None) -> bool:
        order = self.get_scaled_order(scaled_id)
        if not order:
            return False

        for level in order.levels:
            if level.level_number == level_number:
                level.status = status
                if order_id:
                    level.order_id = order_id
                if fill_info:
                    level.filled_size = fill_info.get('filled_size', level.filled_size)
                    level.filled_value = fill_info.get('filled_value', level.filled_value)
                    level.fees = fill_info.get('fees', level.fees)
                    level.is_maker = fill_info.get('is_maker', level.is_maker)
                break

        order.total_filled = sum(l.filled_size for l in order.levels)
        order.total_value_filled = sum(l.filled_value for l in order.levels)
        order.total_fees = sum(l.fees for l in order.levels)
        order.maker_orders = sum(1 for l in order.levels if l.status == 'filled' and l.is_maker)
        order.taker_orders = sum(1 for l in order.levels if l.status == 'filled' and not l.is_maker)

        self.save_scaled_order(order)
        return True

    def delete_scaled_order(self, scaled_id: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM scaled_levels WHERE scaled_order_id = ?", (scaled_id,))
            result = conn.execute(
                "DELETE FROM orders WHERE order_id = ? AND strategy_type = 'scaled'",
                (scaled_id,)
            )
        deleted = result.rowcount > 0
        if deleted:
            logging.info(f"Deleted scaled order {scaled_id} from SQLite")
        return deleted

    def _rows_to_scaled_order(self, row, level_rows) -> Optional[ScaledOrder]:
        try:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            levels = []
            for lr in level_rows:
                levels.append(ScaledOrderLevel(
                    level_number=lr['level_number'],
                    price=lr['price'],
                    size=lr['size'],
                    order_id=lr['child_order_id'],
                    status=lr['status'],
                    filled_size=lr['filled_size'],
                    filled_value=lr['filled_value'],
                    fees=lr['fees'],
                    is_maker=bool(lr['is_maker']),
                    placed_at=lr['placed_at'],
                    filled_at=lr['filled_at'],
                ))

            return ScaledOrder(
                scaled_id=row['order_id'],
                product_id=row['product_id'],
                side=row['side'],
                total_size=row['total_size'],
                price_low=metadata.get('price_low', 0.0),
                price_high=metadata.get('price_high', 0.0),
                num_orders=metadata.get('num_orders', 0),
                distribution=DistributionType(metadata.get('distribution', 'linear')),
                status=row['status'],
                levels=levels,
                created_at=row['created_at'] or '',
                completed_at=row['completed_at'],
                total_filled=metadata.get('total_filled', 0.0),
                total_value_filled=metadata.get('total_value_filled', 0.0),
                total_fees=metadata.get('total_fees', 0.0),
                maker_orders=metadata.get('maker_orders', 0),
                taker_orders=metadata.get('taker_orders', 0),
                metadata=metadata.get('extra', {}),
            )
        except Exception as e:
            logging.error(f"Error constructing scaled order: {e}")
            return None


class SQLiteConditionalOrderTracker(ConditionalOrderStorage):
    """SQLite-backed conditional order storage."""

    def __init__(self, db: Database):
        self._db = db

    # ==================== Stop-Limit ====================

    def save_stop_limit_order(self, order: StopLimitOrder) -> None:
        metadata = json.dumps(asdict(order))
        with self._db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                    (order_id, strategy_type, product_id, side, total_size,
                     limit_price, status, created_at, updated_at, metadata)
                VALUES (?, 'conditional', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id, order.product_id, order.side,
                float(order.base_size), float(order.limit_price),
                order.status, order.created_at, order.updated_at, metadata
            ))

    def get_stop_limit_order(self, order_id: str) -> Optional[StopLimitOrder]:
        row = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ? AND strategy_type = 'conditional'",
            (order_id,)
        )
        if not row:
            return None
        try:
            data = json.loads(row['metadata'])
            # Only reconstruct if it has stop_limit fields
            if 'stop_price' not in data:
                return None
            return StopLimitOrder(**data)
        except Exception as e:
            logging.error(f"Error loading stop-limit {order_id}: {e}")
            return None

    def list_stop_limit_orders(self, status: Optional[str] = None) -> List[StopLimitOrder]:
        rows = self._db.fetchall(
            "SELECT * FROM orders WHERE strategy_type = 'conditional' ORDER BY created_at DESC"
        )
        orders = []
        for row in rows:
            try:
                data = json.loads(row['metadata'])
                if 'stop_price' not in data or 'order_type' not in data:
                    continue
                order = StopLimitOrder(**data)
                if status is None or order.status == status:
                    orders.append(order)
            except Exception:
                continue
        return orders

    # ==================== Bracket ====================

    def save_bracket_order(self, order: BracketOrder) -> None:
        metadata = json.dumps(asdict(order))
        with self._db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                    (order_id, strategy_type, product_id, side, total_size,
                     limit_price, status, created_at, updated_at, metadata)
                VALUES (?, 'conditional', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id, order.product_id, order.side,
                float(order.base_size), float(order.limit_price),
                order.status, order.created_at, order.updated_at, metadata
            ))

    def get_bracket_order(self, order_id: str) -> Optional[BracketOrder]:
        row = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ? AND strategy_type = 'conditional'",
            (order_id,)
        )
        if not row:
            return None
        try:
            data = json.loads(row['metadata'])
            if 'stop_trigger_price' not in data:
                return None
            return BracketOrder(**data)
        except Exception as e:
            logging.error(f"Error loading bracket {order_id}: {e}")
            return None

    def list_bracket_orders(self, status: Optional[str] = None) -> List[BracketOrder]:
        rows = self._db.fetchall(
            "SELECT * FROM orders WHERE strategy_type = 'conditional' ORDER BY created_at DESC"
        )
        orders = []
        for row in rows:
            try:
                data = json.loads(row['metadata'])
                if 'stop_trigger_price' not in data:
                    continue
                order = BracketOrder(**data)
                if status is None or order.status == status:
                    orders.append(order)
            except Exception:
                continue
        return orders

    # ==================== Attached Bracket ====================

    def save_attached_bracket_order(self, order: AttachedBracketOrder) -> None:
        metadata = json.dumps(asdict(order))
        with self._db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                    (order_id, strategy_type, product_id, side, total_size,
                     limit_price, status, created_at, updated_at, metadata)
                VALUES (?, 'conditional', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.entry_order_id, order.product_id, order.side,
                float(order.base_size), float(order.entry_limit_price),
                order.status, order.created_at, order.updated_at, metadata
            ))

    def get_attached_bracket_order(self, order_id: str) -> Optional[AttachedBracketOrder]:
        row = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ? AND strategy_type = 'conditional'",
            (order_id,)
        )
        if not row:
            return None
        try:
            data = json.loads(row['metadata'])
            if 'entry_order_id' not in data:
                return None
            return AttachedBracketOrder(**data)
        except Exception as e:
            logging.error(f"Error loading attached bracket {order_id}: {e}")
            return None

    def list_attached_bracket_orders(self, status: Optional[str] = None) -> List[AttachedBracketOrder]:
        rows = self._db.fetchall(
            "SELECT * FROM orders WHERE strategy_type = 'conditional' ORDER BY created_at DESC"
        )
        orders = []
        for row in rows:
            try:
                data = json.loads(row['metadata'])
                if 'entry_order_id' not in data:
                    continue
                order = AttachedBracketOrder(**data)
                if status is None or order.status == status:
                    orders.append(order)
            except Exception:
                continue
        return orders

    # ==================== Unified Query ====================

    def list_all_active_orders(self) -> List[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        all_orders = []
        all_orders.extend([o for o in self.list_stop_limit_orders() if o.is_active()])
        all_orders.extend([o for o in self.list_bracket_orders() if o.is_active()])
        all_orders.extend([o for o in self.list_attached_bracket_orders() if o.is_active()])
        all_orders.sort(key=lambda x: x.created_at, reverse=True)
        return all_orders

    def get_order_by_id(self, order_id: str) -> Optional[Union[StopLimitOrder, BracketOrder, AttachedBracketOrder]]:
        order = self.get_stop_limit_order(order_id)
        if order:
            return order
        order = self.get_bracket_order(order_id)
        if order:
            return order
        return self.get_attached_bracket_order(order_id)

    def update_order_status(self, order_id: str, order_type: str, status: str,
                            fill_info: Optional[dict] = None) -> bool:
        try:
            if order_type == "stop_limit":
                order = self.get_stop_limit_order(order_id)
                if not order:
                    return False
                order.status = status
                order.update_timestamp()
                if fill_info:
                    order.filled_size = fill_info.get('filled_size', order.filled_size)
                    order.filled_value = fill_info.get('filled_value', order.filled_value)
                    order.fees = fill_info.get('fees', order.fees)
                    if status == "TRIGGERED":
                        order.triggered_at = fill_info.get('triggered_at')
                self.save_stop_limit_order(order)

            elif order_type == "bracket":
                order = self.get_bracket_order(order_id)
                if not order:
                    return False
                order.status = status
                order.update_timestamp()
                if fill_info:
                    order.total_filled_value = fill_info.get('total_filled_value', order.total_filled_value)
                    order.fees = fill_info.get('fees', order.fees)
                    if 'take_profit_filled_size' in fill_info:
                        order.take_profit_filled_size = fill_info['take_profit_filled_size']
                    if 'stop_loss_filled_size' in fill_info:
                        order.stop_loss_filled_size = fill_info['stop_loss_filled_size']
                self.save_bracket_order(order)

            elif order_type == "attached_bracket":
                order = self.get_attached_bracket_order(order_id)
                if not order:
                    return False
                order.status = status
                order.update_timestamp()
                if fill_info:
                    if status == "ENTRY_FILLED":
                        order.entry_filled_size = fill_info.get('filled_size', order.entry_filled_size)
                        order.entry_filled_value = fill_info.get('filled_value', order.entry_filled_value)
                        order.entry_fees = fill_info.get('fees', order.entry_fees)
                    elif status in ["TP_FILLED", "SL_FILLED"]:
                        order.exit_filled_size = fill_info.get('filled_size', order.exit_filled_size)
                        order.exit_filled_value = fill_info.get('filled_value', order.exit_filled_value)
                        order.exit_fees = fill_info.get('fees', order.exit_fees)
                self.save_attached_bracket_order(order)

            else:
                logging.error(f"Unknown order type: {order_type}")
                return False

            logging.info(f"Updated {order_type} order {order_id} to {status}")
            return True

        except Exception as e:
            logging.error(f"Error updating order {order_id}: {e}")
            return False

    def delete_order(self, order_id: str, order_type: str) -> bool:
        with self._db.transaction() as conn:
            result = conn.execute(
                "DELETE FROM orders WHERE order_id = ? AND strategy_type = 'conditional'",
                (order_id,)
            )
        deleted = result.rowcount > 0
        if deleted:
            logging.info(f"Deleted {order_type} order {order_id} from SQLite")
        return deleted

    def get_statistics(self) -> dict:
        stats = {
            'stop_limit': {'total': 0, 'active': 0, 'completed': 0, 'stop_loss': 0, 'take_profit': 0},
            'bracket': {'total': 0, 'active': 0, 'completed': 0},
            'attached_bracket': {'total': 0, 'active': 0, 'completed': 0},
        }

        for order in self.list_stop_limit_orders():
            stats['stop_limit']['total'] += 1
            if order.is_active():
                stats['stop_limit']['active'] += 1
            if order.is_completed():
                stats['stop_limit']['completed'] += 1
            if order.order_type == "STOP_LOSS":
                stats['stop_limit']['stop_loss'] += 1
            elif order.order_type == "TAKE_PROFIT":
                stats['stop_limit']['take_profit'] += 1

        for order in self.list_bracket_orders():
            stats['bracket']['total'] += 1
            if order.is_active():
                stats['bracket']['active'] += 1
            if order.is_completed():
                stats['bracket']['completed'] += 1

        for order in self.list_attached_bracket_orders():
            stats['attached_bracket']['total'] += 1
            if order.is_active():
                stats['attached_bracket']['active'] += 1
            if order.is_completed():
                stats['attached_bracket']['completed'] += 1

        return stats
