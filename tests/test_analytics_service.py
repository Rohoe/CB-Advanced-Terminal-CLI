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
