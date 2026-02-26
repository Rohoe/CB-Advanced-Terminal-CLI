"""Tests for analytics display module."""

import pytest
from unittest.mock import patch, MagicMock

from database import Database
from config_manager import DatabaseConfig
from analytics_service import AnalyticsService
from analytics_display import AnalyticsDisplay


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
def display(analytics):
    return AnalyticsDisplay(analytics)


@pytest.fixture
def seeded_display(analytics, sqlite_db, display):
    """Display with seeded data."""
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

    # Seed orders for fill rate analysis
    from datetime import datetime
    today = datetime.utcnow().isoformat()
    for oid, stype, pid, side, size in [
        ('twap-001', 'twap', 'BTC-USD', 'BUY', 0.5),
        ('twap-002', 'twap', 'BTC-USD', 'SELL', 0.3),
        ('scaled-001', 'scaled', 'ETH-USD', 'BUY', 10.0),
    ]:
        sqlite_db.execute("""
            INSERT OR IGNORE INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (oid, stype, pid, side, size, 'completed', today))

    return display


class TestDisplayPnlSummary:

    def test_display_pnl_summary_empty(self, display, capsys):
        """Empty DB should print 'No trade data available'."""
        display.display_pnl_summary()
        out = capsys.readouterr().out
        assert "No trade data available" in out

    def test_display_pnl_summary_with_data(self, seeded_display, capsys):
        """Should include net value, fees, product table."""
        seeded_display.display_pnl_summary()
        out = capsys.readouterr().out
        assert "Net Value" in out
        assert "Total Fees" in out
        assert "BTC-USD" in out
        assert "ETH-USD" in out

    def test_display_pnl_summary_with_days(self, seeded_display, capsys):
        """Header should say 'Last 7 days'."""
        seeded_display.display_pnl_summary(days=7)
        out = capsys.readouterr().out
        assert "Last 7 days" in out


class TestDisplayDailyPnl:

    def test_display_daily_pnl_empty(self, display, capsys):
        """Empty DB should print info message."""
        display.display_daily_pnl()
        out = capsys.readouterr().out
        assert "No P&L data available" in out

    def test_display_daily_pnl_with_data(self, seeded_display, capsys):
        """Should show table with Date, P&L columns."""
        seeded_display.display_daily_pnl()
        out = capsys.readouterr().out
        assert "Daily P&L" in out
        assert "Date" in out
        assert "Cumulative" in out


class TestDisplayExecutionReport:

    def test_display_execution_report_no_order(self, display, capsys):
        """Missing order ID should print warning."""
        display.display_execution_report(order_id='nonexistent')
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_display_execution_report_single(self, seeded_display, sqlite_db, capsys):
        """Single order report should print strategy, product, size, fees."""
        # Add a fill so summary has data
        sqlite_db.execute("""
            INSERT INTO fills (fill_id, child_order_id, parent_order_id, trade_id,
                filled_size, price, fee, is_maker, trade_time)
            VALUES ('f1', 'c1', 'twap-001', 't1', 0.25, 50000.0, 6.0, 1, '2026-01-01')
        """)
        seeded_display.display_execution_report(order_id='twap-001')
        out = capsys.readouterr().out
        assert "twap" in out
        assert "BTC-USD" in out
        assert "Num Fills" in out

    def test_display_execution_report_overall(self, seeded_display, capsys):
        """Overall report should show slippage, fill rate, maker/taker."""
        seeded_display.display_execution_report()
        out = capsys.readouterr().out
        assert "Slippage Analysis" in out
        assert "Fill Rate" in out
        assert "Maker/Taker" in out

    def test_display_single_execution_arrival_zero(self, analytics, sqlite_db, capsys):
        """arrival_price=0.0 should still display the Arrival line (bug fix)."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at, arrival_price)
            VALUES ('arr-zero', 'twap', 'BTC-USD', 'BUY', 1.0, 'completed', '2026-01-01', 0.0)
        """)
        display = AnalyticsDisplay(analytics)
        display.display_execution_report(order_id='arr-zero')
        out = capsys.readouterr().out
        assert "Arrival" in out

    def test_display_single_execution_no_slippage(self, analytics, sqlite_db, capsys):
        """When slippage_bps is None, slippage line should be omitted."""
        sqlite_db.execute("""
            INSERT INTO orders (order_id, strategy_type, product_id, side, total_size, status, created_at)
            VALUES ('no-slip', 'twap', 'BTC-USD', 'BUY', 1.0, 'completed', '2026-01-01')
        """)
        display = AnalyticsDisplay(analytics)
        display.display_execution_report(order_id='no-slip')
        out = capsys.readouterr().out
        assert "Slippage:" not in out


class TestDisplayFeeSummary:

    def test_display_fee_summary_empty(self, display, capsys):
        """Empty DB should show zeros without crashing."""
        display.display_fee_summary()
        out = capsys.readouterr().out
        assert "Fee Analysis" in out
        assert "Total Fees" in out

    def test_display_fee_summary_with_data(self, seeded_display, capsys):
        """Should show by-strategy and by-product tables."""
        seeded_display.display_fee_summary()
        out = capsys.readouterr().out
        assert "By Strategy" in out
        assert "By Product" in out
        assert "twap" in out
        assert "scaled" in out
