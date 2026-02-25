"""
Analytics service for P&L tracking and execution quality analysis.

Provides SQL-based queries against the unified orders database for:
- Realized P&L and cost basis
- Slippage analysis (vs arrival price)
- Fill rate and execution quality
- Maker/taker ratio analysis
- Fee analysis and optimization

Usage:
    from analytics_service import AnalyticsService

    analytics = AnalyticsService(database)
    pnl = analytics.get_realized_pnl()
    slippage = analytics.get_slippage_analysis("BTC-USD")
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from database import Database


class AnalyticsService:
    """SQL-based analytics engine for trading performance."""

    def __init__(self, db: Database):
        self._db = db

    # ==================== P&L ====================

    def get_realized_pnl(self, product_id: Optional[str] = None,
                         days: Optional[int] = None) -> Dict[str, Any]:
        """Get realized P&L summary.

        Args:
            product_id: Filter by product (None = all).
            days: Filter by last N days (None = all time).

        Returns:
            Dict with total_pnl, total_fees, total_volume, num_trades, by_product.
        """
        params = []
        where_clauses = []

        if product_id:
            where_clauses.append("product_id = ?")
            params.append(product_id)

        if days:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            where_clauses.append("completed_at >= ?")
            params.append(cutoff)

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Aggregate P&L
        row = self._db.fetchone(f"""
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN -total_value ELSE total_value END), 0) as net_value,
                COALESCE(SUM(total_fees), 0) as total_fees,
                COALESCE(SUM(total_value), 0) as total_volume,
                COUNT(*) as num_trades
            FROM pnl_ledger
            {where}
        """, params or None)

        # By product breakdown
        product_rows = self._db.fetchall(f"""
            SELECT
                product_id,
                side,
                COALESCE(SUM(total_size), 0) as total_size,
                COALESCE(SUM(total_value), 0) as total_value,
                COALESCE(SUM(total_fees), 0) as total_fees,
                COUNT(*) as num_trades,
                COALESCE(AVG(avg_price), 0) as avg_price
            FROM pnl_ledger
            {where}
            GROUP BY product_id, side
            ORDER BY total_value DESC
        """, params or None)

        by_product = {}
        for pr in product_rows:
            pid = pr['product_id']
            if pid not in by_product:
                by_product[pid] = {'buys': {}, 'sells': {}}

            side_key = 'buys' if pr['side'] == 'BUY' else 'sells'
            by_product[pid][side_key] = {
                'total_size': pr['total_size'],
                'total_value': pr['total_value'],
                'total_fees': pr['total_fees'],
                'num_trades': pr['num_trades'],
                'avg_price': pr['avg_price'],
            }

        return {
            'net_value': row['net_value'] if row else 0,
            'total_fees': row['total_fees'] if row else 0,
            'total_volume': row['total_volume'] if row else 0,
            'num_trades': row['num_trades'] if row else 0,
            'by_product': by_product,
        }

    def get_cost_basis(self, product_id: str) -> Dict[str, Any]:
        """Get cost basis for a product.

        Returns:
            Dict with total_bought, total_sold, avg_buy_price, avg_sell_price,
            net_position, unrealized_cost_basis.
        """
        row = self._db.fetchone("""
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN total_size ELSE 0 END), 0) as total_bought,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN total_size ELSE 0 END), 0) as total_sold,
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN total_value ELSE 0 END), 0) as buy_value,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN total_value ELSE 0 END), 0) as sell_value,
                COALESCE(SUM(total_fees), 0) as total_fees
            FROM pnl_ledger
            WHERE product_id = ?
        """, (product_id,))

        if not row or row['total_bought'] == 0:
            return {
                'total_bought': 0, 'total_sold': 0,
                'avg_buy_price': 0, 'avg_sell_price': 0,
                'net_position': 0, 'cost_basis': 0, 'total_fees': 0,
            }

        total_bought = row['total_bought']
        total_sold = row['total_sold']
        avg_buy = row['buy_value'] / total_bought if total_bought > 0 else 0
        avg_sell = row['sell_value'] / total_sold if total_sold > 0 else 0

        return {
            'total_bought': total_bought,
            'total_sold': total_sold,
            'avg_buy_price': avg_buy,
            'avg_sell_price': avg_sell,
            'net_position': total_bought - total_sold,
            'cost_basis': row['buy_value'],
            'total_fees': row['total_fees'],
        }

    def get_cumulative_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily cumulative P&L over a period.

        Returns:
            List of dicts with date, daily_pnl, cumulative_pnl, daily_fees.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        rows = self._db.fetchall("""
            SELECT
                DATE(completed_at) as trade_date,
                SUM(CASE WHEN side = 'SELL' THEN total_value ELSE -total_value END) as daily_pnl,
                SUM(total_fees) as daily_fees,
                COUNT(*) as num_trades
            FROM pnl_ledger
            WHERE completed_at >= ?
            GROUP BY DATE(completed_at)
            ORDER BY trade_date
        """, (cutoff,))

        result = []
        cumulative = 0
        for row in rows:
            cumulative += row['daily_pnl']
            result.append({
                'date': row['trade_date'],
                'daily_pnl': row['daily_pnl'],
                'cumulative_pnl': cumulative,
                'daily_fees': row['daily_fees'],
                'num_trades': row['num_trades'],
            })

        return result

    # ==================== Execution Quality ====================

    def get_slippage_analysis(self, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Analyze slippage vs arrival price.

        Returns:
            Dict with avg_slippage_bps, total_slippage_value,
            worst_slippage, best_slippage, by_strategy.
        """
        params = []
        where = ""
        if product_id:
            where = "WHERE product_id = ?"
            params.append(product_id)

        row = self._db.fetchone(f"""
            SELECT
                COALESCE(AVG(slippage_bps), 0) as avg_slippage_bps,
                COALESCE(MAX(slippage_bps), 0) as worst_slippage_bps,
                COALESCE(MIN(slippage_bps), 0) as best_slippage_bps,
                COUNT(*) as num_trades
            FROM pnl_ledger
            {where}
            AND slippage_bps IS NOT NULL
        """.replace("AND", "WHERE" if not where else "AND", 1) if not where else f"""
            SELECT
                COALESCE(AVG(slippage_bps), 0) as avg_slippage_bps,
                COALESCE(MAX(slippage_bps), 0) as worst_slippage_bps,
                COALESCE(MIN(slippage_bps), 0) as best_slippage_bps,
                COUNT(*) as num_trades
            FROM pnl_ledger
            {where}
            AND slippage_bps IS NOT NULL
        """, params or None)

        strategy_rows = self._db.fetchall(f"""
            SELECT
                strategy_type,
                COALESCE(AVG(slippage_bps), 0) as avg_slippage_bps,
                COUNT(*) as num_trades
            FROM pnl_ledger
            {where}
            {"AND" if where else "WHERE"} slippage_bps IS NOT NULL
            GROUP BY strategy_type
        """, params or None)

        by_strategy = {}
        for sr in strategy_rows:
            by_strategy[sr['strategy_type']] = {
                'avg_slippage_bps': sr['avg_slippage_bps'],
                'num_trades': sr['num_trades'],
            }

        return {
            'avg_slippage_bps': row['avg_slippage_bps'] if row else 0,
            'worst_slippage_bps': row['worst_slippage_bps'] if row else 0,
            'best_slippage_bps': row['best_slippage_bps'] if row else 0,
            'num_trades': row['num_trades'] if row else 0,
            'by_strategy': by_strategy,
        }

    def get_fill_rate_analysis(self) -> Dict[str, Any]:
        """Analyze fill rates across strategies.

        Returns:
            Dict with overall and per-strategy fill rates.
        """
        rows = self._db.fetchall("""
            SELECT
                strategy_type,
                COUNT(*) as total_orders,
                SUM(CASE WHEN status IN ('completed', 'partially_filled', 'FILLED') THEN 1 ELSE 0 END) as filled_orders,
                AVG(CASE WHEN total_size > 0 THEN
                    (SELECT COALESCE(SUM(f.filled_size), 0) FROM fills f WHERE f.parent_order_id = o.order_id) / total_size
                    ELSE 0 END) as avg_fill_rate
            FROM orders o
            GROUP BY strategy_type
        """)

        by_strategy = {}
        total_orders = 0
        total_filled = 0

        for row in rows:
            by_strategy[row['strategy_type']] = {
                'total_orders': row['total_orders'],
                'filled_orders': row['filled_orders'],
                'avg_fill_rate': row['avg_fill_rate'] or 0,
            }
            total_orders += row['total_orders']
            total_filled += row['filled_orders']

        return {
            'total_orders': total_orders,
            'total_filled': total_filled,
            'overall_fill_rate': total_filled / total_orders if total_orders > 0 else 0,
            'by_strategy': by_strategy,
        }

    def get_maker_taker_analysis(self) -> Dict[str, Any]:
        """Analyze maker/taker ratios and fee impact.

        Returns:
            Dict with maker_ratio, maker_fills, taker_fills, fee_savings.
        """
        row = self._db.fetchone("""
            SELECT
                COALESCE(AVG(maker_ratio), 0) as avg_maker_ratio,
                COUNT(*) as num_trades,
                COALESCE(SUM(total_fees), 0) as total_fees
            FROM pnl_ledger
        """)

        return {
            'avg_maker_ratio': row['avg_maker_ratio'] if row else 0,
            'num_trades': row['num_trades'] if row else 0,
            'total_fees': row['total_fees'] if row else 0,
        }

    def get_fee_analysis(self, days: Optional[int] = None) -> Dict[str, Any]:
        """Analyze trading fees.

        Returns:
            Dict with total_fees, avg_fee_rate, fees_by_strategy, fees_by_product.
        """
        params = []
        where = ""
        if days:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            where = "WHERE completed_at >= ?"
            params.append(cutoff)

        row = self._db.fetchone(f"""
            SELECT
                COALESCE(SUM(total_fees), 0) as total_fees,
                COALESCE(SUM(total_value), 0) as total_volume,
                COUNT(*) as num_trades
            FROM pnl_ledger
            {where}
        """, params or None)

        total_fees = row['total_fees'] if row else 0
        total_volume = row['total_volume'] if row else 0

        strategy_rows = self._db.fetchall(f"""
            SELECT
                strategy_type,
                COALESCE(SUM(total_fees), 0) as fees,
                COALESCE(SUM(total_value), 0) as volume,
                COUNT(*) as trades
            FROM pnl_ledger
            {where}
            GROUP BY strategy_type
        """, params or None)

        fees_by_strategy = {}
        for sr in strategy_rows:
            vol = sr['volume'] or 0
            fees_by_strategy[sr['strategy_type']] = {
                'fees': sr['fees'],
                'volume': vol,
                'avg_rate': sr['fees'] / vol if vol > 0 else 0,
                'trades': sr['trades'],
            }

        product_rows = self._db.fetchall(f"""
            SELECT
                product_id,
                COALESCE(SUM(total_fees), 0) as fees,
                COALESCE(SUM(total_value), 0) as volume,
                COUNT(*) as trades
            FROM pnl_ledger
            {where}
            GROUP BY product_id
            ORDER BY fees DESC
        """, params or None)

        fees_by_product = {}
        for pr in product_rows:
            vol = pr['volume'] or 0
            fees_by_product[pr['product_id']] = {
                'fees': pr['fees'],
                'volume': vol,
                'avg_rate': pr['fees'] / vol if vol > 0 else 0,
                'trades': pr['trades'],
            }

        return {
            'total_fees': total_fees,
            'total_volume': total_volume,
            'avg_fee_rate': total_fees / total_volume if total_volume > 0 else 0,
            'num_trades': row['num_trades'] if row else 0,
            'by_strategy': fees_by_strategy,
            'by_product': fees_by_product,
        }

    def get_execution_summary(self, order_id: str) -> Dict[str, Any]:
        """Get detailed execution summary for a specific order.

        Returns:
            Dict with order details, fills, slippage, timing.
        """
        order = self._db.fetchone(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        )
        if not order:
            return {}

        fills = self._db.fetchall(
            "SELECT * FROM fills WHERE parent_order_id = ? ORDER BY trade_time",
            (order_id,)
        )

        pnl = self._db.fetchone(
            "SELECT * FROM pnl_ledger WHERE order_id = ?", (order_id,)
        )

        snapshots = self._db.fetchall(
            "SELECT * FROM price_snapshots WHERE order_id = ? ORDER BY timestamp",
            (order_id,)
        )

        total_filled = sum(f['filled_size'] for f in fills)
        total_value = sum(f['filled_size'] * f['price'] for f in fills)
        total_fees = sum(f['fee'] for f in fills)
        avg_price = total_value / total_filled if total_filled > 0 else 0

        return {
            'order_id': order_id,
            'strategy_type': order['strategy_type'],
            'product_id': order['product_id'],
            'side': order['side'],
            'total_size': order['total_size'],
            'total_filled': total_filled,
            'avg_price': avg_price,
            'total_value': total_value,
            'total_fees': total_fees,
            'arrival_price': order['arrival_price'],
            'slippage_bps': pnl['slippage_bps'] if pnl else None,
            'num_fills': len(fills),
            'status': order['status'],
            'price_snapshots': [dict(s) for s in snapshots],
        }

    # ==================== Recording ====================

    def record_trade_completion(self, order_id: str, strategy_type: str,
                                product_id: str, side: str,
                                total_size: float, total_value: float,
                                total_fees: float, avg_price: float,
                                arrival_price: Optional[float] = None,
                                maker_ratio: float = 0.0):
        """Record a completed trade in the P&L ledger.

        Args:
            order_id: The order ID.
            strategy_type: Strategy type (twap, scaled, etc.).
            product_id: Product ID.
            side: BUY or SELL.
            total_size: Total filled size.
            total_value: Total filled value.
            total_fees: Total fees paid.
            avg_price: Volume-weighted average price.
            arrival_price: Market mid at order creation.
            maker_ratio: Fraction of fills that were maker.
        """
        slippage_bps = None
        if arrival_price and arrival_price > 0 and avg_price > 0:
            if side == 'BUY':
                slippage_bps = ((avg_price - arrival_price) / arrival_price) * 10000
            else:
                slippage_bps = ((arrival_price - avg_price) / arrival_price) * 10000

        self._db.execute("""
            INSERT INTO pnl_ledger
                (order_id, product_id, side, strategy_type, total_size,
                 total_value, total_fees, avg_price, arrival_price,
                 slippage_bps, maker_ratio, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, product_id, side, strategy_type,
            total_size, total_value, total_fees, avg_price,
            arrival_price, slippage_bps, maker_ratio,
            datetime.utcnow().isoformat()
        ))

        logging.info(f"Recorded trade completion for {order_id}: "
                     f"{side} {total_size} {product_id} @ {avg_price:.2f}")

    def record_price_snapshot(self, order_id: str, snapshot_type: str,
                               product_id: str, bid: float, ask: float,
                               mid: float):
        """Record a price snapshot for an order.

        Args:
            order_id: The order ID.
            snapshot_type: 'arrival', 'slice', or 'completion'.
            product_id: Product ID.
            bid: Bid price.
            ask: Ask price.
            mid: Mid price.
        """
        self._db.execute("""
            INSERT INTO price_snapshots
                (order_id, snapshot_type, product_id, bid, ask, mid, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, snapshot_type, product_id,
            bid, ask, mid, datetime.utcnow().isoformat()
        ))
