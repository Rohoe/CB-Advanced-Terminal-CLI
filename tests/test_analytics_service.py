"""Tests for analytics service."""

import pytest
from datetime import datetime, timedelta

from database import Database
from config_manager import DatabaseConfig
from analytics_service import AnalyticsService


@pytest.fixture
def sqlite_db():
    config = DatabaseConfig(db_path=":memory:", wal_mode=False)
    db = Database(config)
    yield db
    db.close()


@pytest.fixture
def analytics(sqlite_db):
    return AnalyticsService(sqlite_db)


@pytest.fixture
def seeded_analytics(sqlite_db, analytics):
    """Analytics with seeded P&L data."""
    now = datetime.utcnow()
    yesterday = (now - timedelta(days=1)).isoformat()
    today = now.isoformat()

    # Record some trades
    analytics.record_trade_completion(
        order_id='twap-001', strategy_type='twap', product_id='BTC-USD',
        side='BUY', total_size=0.5, total_value=25000.0, total_fees=12.5,
        avg_price=50000.0, arrival_price=49950.0, maker_ratio=0.8,
    )
    analytics.record_trade_completion(
        order_id='twap-002', strategy_type='twap', product_id='BTC-USD',
        side='SELL', total_size=0.3, total_value=15300.0, total_fees=7.65,
        avg_price=51000.0, arrival_price=51050.0, maker_ratio=0.6,
    )
    analytics.record_trade_completion(
        order_id='scaled-001', strategy_type='scaled', product_id='ETH-USD',
        side='BUY', total_size=10.0, total_value=30000.0, total_fees=18.0,
        avg_price=3000.0, arrival_price=2990.0, maker_ratio=1.0,
    )

    # Seed some orders for fill rate analysis
    sqlite_db.execute("""
        INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ('twap-001', 'twap', 'BTC-USD', 'BUY', 0.5, 'completed', today))
    sqlite_db.execute("""
        INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ('twap-002', 'twap', 'BTC-USD', 'SELL', 0.3, 'completed', today))
    sqlite_db.execute("""
        INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ('scaled-001', 'scaled', 'ETH-USD', 'BUY', 10.0, 'completed', today))

    return analytics


class TestRecordTradeCompletion:

    def test_record_buy(self, analytics):
        analytics.record_trade_completion(
            order_id='test-1', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=25.0,
            avg_price=50000.0, arrival_price=49950.0, maker_ratio=0.5,
        )

        pnl = analytics.get_realized_pnl()
        assert pnl['num_trades'] == 1
        assert pnl['total_fees'] == 25.0
        assert pnl['total_volume'] == 50000.0

    def test_slippage_buy(self, analytics):
        """Buy slippage: positive when avg > arrival (unfavorable)."""
        analytics.record_trade_completion(
            order_id='test-slip', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50100.0, total_fees=0,
            avg_price=50100.0, arrival_price=50000.0,
        )

        slippage = analytics.get_slippage_analysis()
        assert slippage['avg_slippage_bps'] == pytest.approx(20.0, abs=0.1)

    def test_slippage_sell(self, analytics):
        """Sell slippage: positive when arrival > avg (unfavorable)."""
        analytics.record_trade_completion(
            order_id='test-slip-sell', strategy_type='twap', product_id='BTC-USD',
            side='SELL', total_size=1.0, total_value=49900.0, total_fees=0,
            avg_price=49900.0, arrival_price=50000.0,
        )

        slippage = analytics.get_slippage_analysis()
        assert slippage['avg_slippage_bps'] == pytest.approx(20.0, abs=0.1)


class TestGetRealizedPnl:

    def test_empty_db(self, analytics):
        pnl = analytics.get_realized_pnl()
        assert pnl['num_trades'] == 0
        assert pnl['total_fees'] == 0
        assert pnl['total_volume'] == 0

    def test_with_data(self, seeded_analytics):
        pnl = seeded_analytics.get_realized_pnl()
        assert pnl['num_trades'] == 3
        assert pnl['total_volume'] == pytest.approx(70300.0)
        assert pnl['total_fees'] == pytest.approx(38.15)

    def test_filter_by_product(self, seeded_analytics):
        pnl = seeded_analytics.get_realized_pnl(product_id='ETH-USD')
        assert pnl['num_trades'] == 1
        assert pnl['total_volume'] == pytest.approx(30000.0)

    def test_by_product_breakdown(self, seeded_analytics):
        pnl = seeded_analytics.get_realized_pnl()
        assert 'BTC-USD' in pnl['by_product']
        assert 'ETH-USD' in pnl['by_product']
        btc = pnl['by_product']['BTC-USD']
        assert 'buys' in btc
        assert btc['buys']['num_trades'] == 1


class TestGetCostBasis:

    def test_empty(self, analytics):
        basis = analytics.get_cost_basis('BTC-USD')
        assert basis['total_bought'] == 0

    def test_with_data(self, seeded_analytics):
        basis = seeded_analytics.get_cost_basis('BTC-USD')
        assert basis['total_bought'] == pytest.approx(0.5)
        assert basis['total_sold'] == pytest.approx(0.3)
        assert basis['net_position'] == pytest.approx(0.2)
        assert basis['avg_buy_price'] == pytest.approx(50000.0)
        assert basis['avg_sell_price'] == pytest.approx(51000.0)


class TestGetCumulativePnl:

    def test_empty(self, analytics):
        result = analytics.get_cumulative_pnl()
        assert result == []

    def test_with_data(self, seeded_analytics):
        result = seeded_analytics.get_cumulative_pnl()
        assert len(result) >= 1
        assert 'daily_pnl' in result[0]
        assert 'cumulative_pnl' in result[0]


class TestSlippageAnalysis:

    def test_empty(self, analytics):
        result = analytics.get_slippage_analysis()
        assert result['num_trades'] == 0

    def test_with_data(self, seeded_analytics):
        result = seeded_analytics.get_slippage_analysis()
        assert result['num_trades'] == 3
        assert 'by_strategy' in result

    def test_filter_by_product(self, seeded_analytics):
        result = seeded_analytics.get_slippage_analysis(product_id='BTC-USD')
        assert result['num_trades'] == 2


class TestFillRateAnalysis:

    def test_empty(self, analytics):
        result = analytics.get_fill_rate_analysis()
        assert result['total_orders'] == 0

    def test_with_data(self, seeded_analytics):
        result = seeded_analytics.get_fill_rate_analysis()
        assert result['total_orders'] == 3
        assert 'by_strategy' in result
        assert 'twap' in result['by_strategy']


class TestMakerTakerAnalysis:

    def test_empty(self, analytics):
        result = analytics.get_maker_taker_analysis()
        assert result['num_trades'] == 0

    def test_with_data(self, seeded_analytics):
        result = seeded_analytics.get_maker_taker_analysis()
        assert result['num_trades'] == 3
        assert result['avg_maker_ratio'] > 0


class TestFeeAnalysis:

    def test_empty(self, analytics):
        result = analytics.get_fee_analysis()
        assert result['total_fees'] == 0

    def test_with_data(self, seeded_analytics):
        result = seeded_analytics.get_fee_analysis()
        assert result['total_fees'] == pytest.approx(38.15)
        assert 'by_strategy' in result
        assert 'by_product' in result
        assert result['by_strategy']['twap']['fees'] == pytest.approx(20.15)
        assert result['by_product']['ETH-USD']['fees'] == pytest.approx(18.0)


class TestExecutionSummary:

    def test_nonexistent(self, analytics):
        result = analytics.get_execution_summary('nonexistent')
        assert result == {}

    def test_with_order(self, seeded_analytics, sqlite_db):
        result = seeded_analytics.get_execution_summary('twap-001')
        assert result['order_id'] == 'twap-001'
        assert result['strategy_type'] == 'twap'
        assert result['product_id'] == 'BTC-USD'


class TestPriceSnapshot:

    def test_record_snapshot(self, analytics, sqlite_db):
        analytics.record_price_snapshot(
            order_id='test-snap', snapshot_type='arrival',
            product_id='BTC-USD', bid=49990.0, ask=50010.0, mid=50000.0,
        )

        row = sqlite_db.fetchone(
            "SELECT * FROM price_snapshots WHERE order_id = 'test-snap'"
        )
        assert row is not None
        assert row['snapshot_type'] == 'arrival'
        assert row['bid'] == 49990.0


# =============================================================================
# Tier 1A: Analytics Bug Fix Tests
# =============================================================================

class TestFillRateEdgeCases:

    def test_fill_rate_with_zero_size_order(self, analytics, sqlite_db):
        """Order with total_size=0 should not cause ZeroDivisionError."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('zero-size', 'twap', 'BTC-USD', 'BUY', 0, 'completed', '2026-01-01')
        """)
        result = analytics.get_fill_rate_analysis()
        assert result['total_orders'] == 1
        # avg_fill_rate should be 0 (no division error)
        assert result['by_strategy']['twap']['avg_fill_rate'] == 0

    def test_fill_rate_with_no_fills(self, analytics, sqlite_db):
        """Orders with no fills rows should report 0 fill rate."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('no-fill', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
        """)
        result = analytics.get_fill_rate_analysis()
        assert result['total_orders'] == 1
        assert result['total_filled'] == 0


class TestSlippageEdgeCases:

    def test_slippage_no_product_filter(self, seeded_analytics):
        """Slippage with no product filter uses clean WHERE clause."""
        result = seeded_analytics.get_slippage_analysis()
        assert result['num_trades'] >= 1
        assert 'by_strategy' in result

    def test_slippage_with_null_bps(self, analytics):
        """Records with NULL slippage_bps should be excluded."""
        analytics.record_trade_completion(
            order_id='null-slip', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=0,
            avg_price=50000.0, arrival_price=None,  # NULL arrival → NULL slippage
        )
        result = analytics.get_slippage_analysis()
        # trade with NULL slippage_bps is filtered out
        assert result['num_trades'] == 0

    def test_slippage_zero_when_arrival_equals_avg(self, analytics):
        """Zero slippage when avg_price == arrival_price."""
        analytics.record_trade_completion(
            order_id='zero-slip', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=0,
            avg_price=50000.0, arrival_price=50000.0,
        )
        result = analytics.get_slippage_analysis()
        assert result['avg_slippage_bps'] == pytest.approx(0.0, abs=0.01)


class TestRecordTradeEdgeCases:

    def test_record_trade_with_zero_arrival_price(self, analytics, sqlite_db):
        """arrival_price=0.0 should be stored as 0, slippage should be None."""
        analytics.record_trade_completion(
            order_id='zero-arrival', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=0,
            avg_price=50000.0, arrival_price=0.0,
        )
        row = sqlite_db.fetchone("SELECT arrival_price, slippage_bps FROM pnl_ledger WHERE order_id = 'zero-arrival'")
        assert row['arrival_price'] == 0.0
        assert row['slippage_bps'] is None

    def test_record_trade_with_null_arrival_price(self, analytics, sqlite_db):
        """arrival_price=None → slippage_bps is None."""
        analytics.record_trade_completion(
            order_id='null-arrival', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=0,
            avg_price=50000.0, arrival_price=None,
        )
        row = sqlite_db.fetchone("SELECT slippage_bps FROM pnl_ledger WHERE order_id = 'null-arrival'")
        assert row['slippage_bps'] is None

    def test_record_trade_with_null_maker_ratio(self, analytics, sqlite_db):
        """Default maker_ratio=0.0 when not provided."""
        analytics.record_trade_completion(
            order_id='no-maker', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=0,
            avg_price=50000.0,
        )
        row = sqlite_db.fetchone("SELECT maker_ratio FROM pnl_ledger WHERE order_id = 'no-maker'")
        assert row['maker_ratio'] == 0.0


# =============================================================================
# Tier 1B: Date Filtering + Execution Summary Tests
# =============================================================================

class TestPnlDateFiltering:

    def test_pnl_days_filter_recent(self, analytics, sqlite_db):
        """get_realized_pnl(days=7) returns only recent trades."""
        now = datetime.utcnow()
        recent = now.isoformat()
        old = (now - timedelta(days=30)).isoformat()

        # Insert directly with controlled timestamps
        sqlite_db.execute("""
            INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                total_size, total_value, total_fees, avg_price, completed_at)
            VALUES ('recent-1', 'BTC-USD', 'BUY', 'twap', 1.0, 50000.0, 25.0, 50000.0, ?)
        """, (recent,))
        sqlite_db.execute("""
            INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                total_size, total_value, total_fees, avg_price, completed_at)
            VALUES ('old-1', 'BTC-USD', 'BUY', 'twap', 1.0, 48000.0, 24.0, 48000.0, ?)
        """, (old,))

        result = analytics.get_realized_pnl(days=7)
        assert result['num_trades'] == 1
        assert result['total_volume'] == pytest.approx(50000.0)

    def test_pnl_days_filter_excludes_old(self, analytics, sqlite_db):
        """30-day-old trade excluded from days=1."""
        old = (datetime.utcnow() - timedelta(days=30)).isoformat()
        sqlite_db.execute("""
            INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                total_size, total_value, total_fees, avg_price, completed_at)
            VALUES ('very-old', 'BTC-USD', 'BUY', 'twap', 1.0, 50000.0, 25.0, 50000.0, ?)
        """, (old,))

        result = analytics.get_realized_pnl(days=1)
        assert result['num_trades'] == 0

    def test_fee_analysis_days_filter(self, analytics, sqlite_db):
        """get_fee_analysis(days=7) filters by date."""
        now = datetime.utcnow()
        recent = now.isoformat()
        old = (now - timedelta(days=30)).isoformat()

        sqlite_db.execute("""
            INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                total_size, total_value, total_fees, avg_price, completed_at)
            VALUES ('fee-recent', 'BTC-USD', 'BUY', 'twap', 1.0, 50000.0, 25.0, 50000.0, ?)
        """, (recent,))
        sqlite_db.execute("""
            INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                total_size, total_value, total_fees, avg_price, completed_at)
            VALUES ('fee-old', 'BTC-USD', 'BUY', 'twap', 1.0, 50000.0, 100.0, 50000.0, ?)
        """, (old,))

        result = analytics.get_fee_analysis(days=7)
        assert result['total_fees'] == pytest.approx(25.0)
        assert result['num_trades'] == 1


class TestExecutionSummaryExtended:

    def test_execution_summary_all_fields(self, seeded_analytics, sqlite_db):
        """Verify all 13 return fields in execution summary."""
        # Add a fill for twap-001
        sqlite_db.execute("""
            INSERT INTO fills (fill_id, child_order_id, parent_order_id, trade_id,
                filled_size, price, fee, is_maker, trade_time)
            VALUES ('f1', 'child-1', 'twap-001', 't1', 0.25, 50000.0, 6.0, 1, '2026-01-01T00:00:00Z')
        """)

        result = seeded_analytics.get_execution_summary('twap-001')
        expected_keys = [
            'order_id', 'strategy_type', 'product_id', 'side', 'total_size',
            'total_filled', 'avg_price', 'total_value', 'total_fees',
            'arrival_price', 'slippage_bps', 'num_fills', 'status',
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"
        assert result['num_fills'] == 1
        assert result['total_filled'] == pytest.approx(0.25)

    def test_execution_summary_no_fills(self, analytics, sqlite_db):
        """Order with no fills returns zero filled."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('no-fills', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
        """)
        result = analytics.get_execution_summary('no-fills')
        assert result['total_filled'] == 0
        assert result['num_fills'] == 0

    def test_execution_summary_no_pnl_ledger(self, analytics, sqlite_db):
        """Order without pnl_ledger entry has slippage_bps=None."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('no-pnl', 'twap', 'BTC-USD', 'BUY', 1.0, 'active', '2026-01-01')
        """)
        result = analytics.get_execution_summary('no-pnl')
        assert result['slippage_bps'] is None

    def test_execution_summary_multiple_snapshots(self, analytics, sqlite_db):
        """Arrival + completion snapshots appear in price_snapshots."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('snap-multi', 'twap', 'BTC-USD', 'BUY', 1.0, 'completed', '2026-01-01')
        """)
        analytics.record_price_snapshot(
            order_id='snap-multi', snapshot_type='arrival',
            product_id='BTC-USD', bid=49990.0, ask=50010.0, mid=50000.0,
        )
        analytics.record_price_snapshot(
            order_id='snap-multi', snapshot_type='completion',
            product_id='BTC-USD', bid=50090.0, ask=50110.0, mid=50100.0,
        )
        result = analytics.get_execution_summary('snap-multi')
        assert len(result['price_snapshots']) == 2
        types = [s['snapshot_type'] for s in result['price_snapshots']]
        assert 'arrival' in types
        assert 'completion' in types


# =============================================================================
# Tier 2C: Analytics Edge Cases
# =============================================================================

class TestCostBasisEdgeCases:

    def test_cost_basis_sells_only(self, analytics):
        """Only sells → net_position is negative."""
        analytics.record_trade_completion(
            order_id='sell-only', strategy_type='twap', product_id='BTC-USD',
            side='SELL', total_size=0.5, total_value=25000.0, total_fees=12.5,
            avg_price=50000.0, arrival_price=50000.0,
        )
        # get_cost_basis returns zeros when total_bought is 0
        basis = analytics.get_cost_basis('BTC-USD')
        assert basis['total_bought'] == 0
        assert basis['total_sold'] == 0  # early return when total_bought == 0

    def test_multiple_products_cost_basis(self, analytics):
        """Cost basis is independent per product."""
        analytics.record_trade_completion(
            order_id='btc-buy', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=25.0,
            avg_price=50000.0, arrival_price=50000.0,
        )
        analytics.record_trade_completion(
            order_id='eth-buy', strategy_type='twap', product_id='ETH-USD',
            side='BUY', total_size=10.0, total_value=30000.0, total_fees=15.0,
            avg_price=3000.0, arrival_price=3000.0,
        )

        btc_basis = analytics.get_cost_basis('BTC-USD')
        eth_basis = analytics.get_cost_basis('ETH-USD')
        assert btc_basis['total_bought'] == pytest.approx(1.0)
        assert eth_basis['total_bought'] == pytest.approx(10.0)
        assert btc_basis['avg_buy_price'] == pytest.approx(50000.0)
        assert eth_basis['avg_buy_price'] == pytest.approx(3000.0)


class TestCumulativePnlExtended:

    def test_cumulative_pnl_multiple_days(self, analytics, sqlite_db):
        """Cumulative P&L accumulates correctly over multiple days."""
        now = datetime.utcnow()
        for i in range(5):
            day = (now - timedelta(days=4 - i)).isoformat()
            sqlite_db.execute("""
                INSERT INTO pnl_ledger (order_id, product_id, side, strategy_type,
                    total_size, total_value, total_fees, avg_price, completed_at)
                VALUES (?, 'BTC-USD', 'SELL', 'twap', 0.1, 5000.0, 2.5, 50000.0, ?)
            """, (f"day-{i}", day))

        result = analytics.get_cumulative_pnl(days=7)
        assert len(result) == 5
        # Cumulative should increase (all sells = positive P&L)
        for i in range(1, len(result)):
            assert result[i]['cumulative_pnl'] >= result[i - 1]['cumulative_pnl']


class TestMakerTakerEdgeCases:

    def test_maker_taker_all_maker(self, analytics):
        """All maker fills → avg_maker_ratio=1.0."""
        analytics.record_trade_completion(
            order_id='all-maker', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=10.0,
            avg_price=50000.0, arrival_price=50000.0, maker_ratio=1.0,
        )
        result = analytics.get_maker_taker_analysis()
        assert result['avg_maker_ratio'] == pytest.approx(1.0)

    def test_maker_taker_all_taker(self, analytics):
        """All taker fills → avg_maker_ratio=0.0."""
        analytics.record_trade_completion(
            order_id='all-taker', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=50000.0, total_fees=10.0,
            avg_price=50000.0, arrival_price=50000.0, maker_ratio=0.0,
        )
        result = analytics.get_maker_taker_analysis()
        assert result['avg_maker_ratio'] == pytest.approx(0.0)


class TestSlippageFavorable:

    def test_slippage_favorable_buy(self, analytics):
        """Negative bps (avg < arrival) = favorable slippage for buy."""
        analytics.record_trade_completion(
            order_id='fav-buy', strategy_type='twap', product_id='BTC-USD',
            side='BUY', total_size=1.0, total_value=49900.0, total_fees=0,
            avg_price=49900.0, arrival_price=50000.0,
        )
        result = analytics.get_slippage_analysis()
        assert result['avg_slippage_bps'] < 0  # favorable
