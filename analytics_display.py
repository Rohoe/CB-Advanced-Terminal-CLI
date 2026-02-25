"""
Analytics display for P&L summaries and execution reports.

Provides formatted terminal output for analytics data.

Usage:
    from analytics_display import AnalyticsDisplay

    display = AnalyticsDisplay(analytics_service)
    display.display_pnl_summary()
    display.display_execution_report()
"""

from tabulate import tabulate

from analytics_service import AnalyticsService
from ui_helpers import (
    print_header, print_subheader, print_info, print_warning,
    format_currency, info, highlight, success, error
)


class AnalyticsDisplay:
    """Formatted display of analytics data."""

    def __init__(self, analytics: AnalyticsService):
        self._analytics = analytics

    def display_pnl_summary(self, days=None):
        """Display P&L summary."""
        pnl = self._analytics.get_realized_pnl(days=days)

        period = f"Last {days} days" if days else "All time"
        print_header(f"\nP&L Summary ({period})")

        print(f"Net Value:    {format_currency(pnl['net_value'])}")
        print(f"Total Fees:   {format_currency(pnl['total_fees'], colored=False)}")
        print(f"Total Volume: {format_currency(pnl['total_volume'], colored=False)}")
        print(f"Num Trades:   {pnl['num_trades']}")

        if pnl['by_product']:
            print_subheader("\nBy Product")
            headers = ['Product', 'Side', 'Size', 'Value', 'Fees', 'Avg Price', 'Trades']
            rows = []
            for pid, sides in pnl['by_product'].items():
                for side_key, data in sides.items():
                    if data.get('num_trades', 0) == 0:
                        continue
                    rows.append([
                        pid,
                        'BUY' if side_key == 'buys' else 'SELL',
                        f"{data['total_size']:.8f}",
                        format_currency(data['total_value'], colored=False),
                        format_currency(data['total_fees'], colored=False),
                        format_currency(data['avg_price'], colored=False),
                        data['num_trades'],
                    ])
            if rows:
                print(tabulate(rows, headers=headers, tablefmt='simple'))
            else:
                print_info("No trade data available.")
        else:
            print_info("No trade data available.")

    def display_daily_pnl(self, days=30):
        """Display daily P&L over a period."""
        daily = self._analytics.get_cumulative_pnl(days=days)

        if not daily:
            print_info("No P&L data available for the period.")
            return

        print_header(f"\nDaily P&L (Last {days} Days)")
        headers = ['Date', 'Daily P&L', 'Cumulative', 'Fees', 'Trades']
        rows = []
        for d in daily:
            pnl_str = format_currency(d['daily_pnl'])
            cum_str = format_currency(d['cumulative_pnl'])
            rows.append([
                d['date'],
                pnl_str,
                cum_str,
                format_currency(d['daily_fees'], colored=False),
                d['num_trades'],
            ])
        print(tabulate(rows, headers=headers, tablefmt='simple'))

    def display_execution_report(self, order_id=None):
        """Display execution quality report."""
        if order_id:
            summary = self._analytics.get_execution_summary(order_id)
            if not summary:
                print_warning(f"No data found for order {order_id}")
                return
            self._display_single_execution(summary)
        else:
            self._display_overall_execution()

    def _display_single_execution(self, summary):
        """Display execution report for a single order."""
        print_header(f"\nExecution Report: {summary['order_id'][:12]}...")
        print(f"Strategy:   {summary['strategy_type']}")
        print(f"Product:    {info(summary['product_id'])}")
        print(f"Side:       {summary['side']}")
        print(f"Size:       {summary['total_size']:.8f} (filled: {summary['total_filled']:.8f})")
        print(f"Avg Price:  {format_currency(summary['avg_price'], colored=False)}")
        print(f"Total Value:{format_currency(summary['total_value'], colored=False)}")
        print(f"Total Fees: {format_currency(summary['total_fees'], colored=False)}")

        if summary['arrival_price']:
            print(f"Arrival:    {format_currency(summary['arrival_price'], colored=False)}")
        if summary['slippage_bps'] is not None:
            slip = summary['slippage_bps']
            slip_str = f"{slip:.1f} bps"
            if slip > 0:
                print(f"Slippage:   {error(slip_str)} (unfavorable)")
            else:
                print(f"Slippage:   {success(slip_str)} (favorable)")

        print(f"Num Fills:  {summary['num_fills']}")
        print(f"Status:     {summary['status']}")

    def _display_overall_execution(self):
        """Display overall execution quality metrics."""
        slippage = self._analytics.get_slippage_analysis()
        fill_rate = self._analytics.get_fill_rate_analysis()
        maker_taker = self._analytics.get_maker_taker_analysis()

        print_header("\nExecution Quality Report")

        print_subheader("\nSlippage Analysis")
        print(f"Average Slippage: {slippage['avg_slippage_bps']:.1f} bps")
        print(f"Worst Slippage:   {slippage['worst_slippage_bps']:.1f} bps")
        print(f"Best Slippage:    {slippage['best_slippage_bps']:.1f} bps")
        if slippage['by_strategy']:
            for strategy, data in slippage['by_strategy'].items():
                print(f"  {strategy}: {data['avg_slippage_bps']:.1f} bps ({data['num_trades']} trades)")

        print_subheader("\nFill Rate Analysis")
        print(f"Overall Fill Rate: {fill_rate['overall_fill_rate']:.1%}")
        print(f"Total Orders:      {fill_rate['total_orders']}")
        print(f"Total Filled:      {fill_rate['total_filled']}")
        if fill_rate['by_strategy']:
            for strategy, data in fill_rate['by_strategy'].items():
                print(f"  {strategy}: {data['filled_orders']}/{data['total_orders']} "
                      f"({data['avg_fill_rate']:.1%})")

        print_subheader("\nMaker/Taker Analysis")
        print(f"Average Maker Ratio: {maker_taker['avg_maker_ratio']:.1%}")
        print(f"Total Fees:          {format_currency(maker_taker['total_fees'], colored=False)}")

    def display_fee_summary(self, days=None):
        """Display fee analysis."""
        fees = self._analytics.get_fee_analysis(days=days)

        period = f"Last {days} days" if days else "All time"
        print_header(f"\nFee Analysis ({period})")

        print(f"Total Fees:    {format_currency(fees['total_fees'], colored=False)}")
        print(f"Total Volume:  {format_currency(fees['total_volume'], colored=False)}")
        print(f"Avg Fee Rate:  {fees['avg_fee_rate']:.4%}")
        print(f"Num Trades:    {fees['num_trades']}")

        if fees['by_strategy']:
            print_subheader("\nBy Strategy")
            headers = ['Strategy', 'Fees', 'Volume', 'Avg Rate', 'Trades']
            rows = []
            for strategy, data in fees['by_strategy'].items():
                rows.append([
                    strategy,
                    format_currency(data['fees'], colored=False),
                    format_currency(data['volume'], colored=False),
                    f"{data['avg_rate']:.4%}",
                    data['trades'],
                ])
            print(tabulate(rows, headers=headers, tablefmt='simple'))

        if fees['by_product']:
            print_subheader("\nBy Product")
            headers = ['Product', 'Fees', 'Volume', 'Avg Rate', 'Trades']
            rows = []
            for product, data in fees['by_product'].items():
                rows.append([
                    product,
                    format_currency(data['fees'], colored=False),
                    format_currency(data['volume'], colored=False),
                    f"{data['avg_rate']:.4%}",
                    data['trades'],
                ])
            print(tabulate(rows, headers=headers, tablefmt='simple'))
