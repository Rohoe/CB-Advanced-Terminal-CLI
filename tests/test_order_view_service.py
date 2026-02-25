"""Tests for OrderViewService."""

import pytest
from unittest.mock import Mock, MagicMock

from order_view_service import OrderViewService


# =============================================================================
# Helpers
# =============================================================================

def _make_service(api_client=None, market_data=None, conditional_tracker=None):
    """Create an OrderViewService with mocked dependencies."""
    api = api_client or Mock()
    md = market_data or Mock()
    md.rate_limiter = Mock(wait=Mock(return_value=None))
    ct = conditional_tracker or Mock()
    return OrderViewService(api_client=api, market_data=md, conditional_tracker=ct)


def _mock_order(order_id='ord-1', product_id='BTC-USDC', status='OPEN', **kwargs):
    """Create a mock order object with dot-access attributes."""
    order = Mock()
    order.order_id = order_id
    order.product_id = product_id
    order.status = status
    for k, v in kwargs.items():
        setattr(order, k, v)
    return order


# =============================================================================
# get_active_orders
# =============================================================================

class TestGetActiveOrders:

    def test_returns_open_and_pending_only(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('o1', status='OPEN'),
            _mock_order('o2', status='PENDING'),
            _mock_order('o3', status='FILLED'),
            _mock_order('o4', status='CANCELLED'),
        ])
        svc = _make_service(api_client=api)

        result = svc.get_active_orders()

        assert len(result) == 2
        assert {o.order_id for o in result} == {'o1', 'o2'}

    def test_empty_orders(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[])
        svc = _make_service(api_client=api)

        assert svc.get_active_orders() == []

    def test_missing_orders_attribute(self):
        api = Mock()
        api.list_orders.return_value = Mock(spec=[])  # no .orders attr
        svc = _make_service(api_client=api)

        assert svc.get_active_orders() == []

    def test_api_exception_returns_empty(self):
        api = Mock()
        api.list_orders.side_effect = RuntimeError("connection failed")
        svc = _make_service(api_client=api)

        assert svc.get_active_orders() == []


# =============================================================================
# get_order_history
# =============================================================================

class TestGetOrderHistory:

    def test_no_filters(self):
        orders = [_mock_order(f'o{i}', status='FILLED') for i in range(5)]
        api = Mock()
        api.list_orders.return_value = Mock(orders=orders)
        svc = _make_service(api_client=api)

        result = svc.get_order_history()

        assert len(result) == 5

    def test_filter_by_product_id(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('o1', product_id='BTC-USDC', status='FILLED'),
            _mock_order('o2', product_id='ETH-USDC', status='FILLED'),
            _mock_order('o3', product_id='BTC-USDC', status='OPEN'),
        ])
        svc = _make_service(api_client=api)

        result = svc.get_order_history(product_id='BTC-USDC')

        assert len(result) == 2
        assert all(o.product_id == 'BTC-USDC' for o in result)

    def test_filter_by_order_status(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('o1', status='FILLED'),
            _mock_order('o2', status='CANCELLED'),
            _mock_order('o3', status='OPEN'),
            _mock_order('o4', status='FILLED'),
        ])
        svc = _make_service(api_client=api)

        result = svc.get_order_history(order_status=['FILLED'])

        assert len(result) == 2
        assert all(o.status == 'FILLED' for o in result)

    def test_respects_limit(self):
        orders = [_mock_order(f'o{i}', status='FILLED') for i in range(20)]
        api = Mock()
        api.list_orders.return_value = Mock(orders=orders)
        svc = _make_service(api_client=api)

        result = svc.get_order_history(limit=5)

        assert len(result) == 5

    def test_combined_filters(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('o1', product_id='BTC-USDC', status='FILLED'),
            _mock_order('o2', product_id='ETH-USDC', status='FILLED'),
            _mock_order('o3', product_id='BTC-USDC', status='OPEN'),
            _mock_order('o4', product_id='BTC-USDC', status='FILLED'),
            _mock_order('o5', product_id='BTC-USDC', status='FILLED'),
        ])
        svc = _make_service(api_client=api)

        result = svc.get_order_history(product_id='BTC-USDC', order_status=['FILLED'], limit=2)

        assert len(result) == 2
        assert all(o.product_id == 'BTC-USDC' and o.status == 'FILLED' for o in result)

    def test_missing_orders_attribute(self):
        api = Mock()
        api.list_orders.return_value = Mock(spec=[])
        svc = _make_service(api_client=api)

        assert svc.get_order_history() == []

    def test_api_exception_returns_empty(self):
        api = Mock()
        api.list_orders.side_effect = RuntimeError("timeout")
        svc = _make_service(api_client=api)

        assert svc.get_order_history() == []

    def test_calls_rate_limiter(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[])
        md = Mock()
        md.rate_limiter = Mock(wait=Mock(return_value=None))
        svc = _make_service(api_client=api, market_data=md)

        svc.get_order_history()

        md.rate_limiter.wait.assert_called_once()


# =============================================================================
# sync_conditional_order_statuses
# =============================================================================

class TestSyncConditionalOrderStatuses:

    def test_syncs_cancelled_status(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('ord-1', status='CANCELLED'),
        ])
        tracker = Mock()
        tracked_order = Mock()
        tracked_order.order_id = 'ord-1'
        tracked_order.is_completed.return_value = False
        tracker.list_stop_limit_orders.return_value = [tracked_order]

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_called_once_with(
            order_id='ord-1',
            order_type='stop_limit',
            status='CANCELLED',
            fill_info=None,
        )

    def test_syncs_filled_status(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('ord-1', status='FILLED'),
        ])
        tracker = Mock()
        tracked_order = Mock()
        tracked_order.order_id = 'ord-1'
        tracked_order.is_completed.return_value = False
        tracker.list_stop_limit_orders.return_value = [tracked_order]

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_called_once_with(
            order_id='ord-1',
            order_type='stop_limit',
            status='FILLED',
            fill_info=None,
        )

    def test_skips_already_completed(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('ord-1', status='FILLED'),
        ])
        tracker = Mock()
        tracked_order = Mock()
        tracked_order.order_id = 'ord-1'
        tracked_order.is_completed.return_value = True
        tracker.list_stop_limit_orders.return_value = [tracked_order]

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_not_called()

    def test_missing_from_api_marked_cancelled(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[])  # order not in API
        tracker = Mock()
        tracked_order = Mock()
        tracked_order.order_id = 'ord-missing'
        tracked_order.is_completed.return_value = False
        tracker.list_stop_limit_orders.return_value = [tracked_order]

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_called_once_with(
            order_id='ord-missing',
            order_type='stop_limit',
            status='CANCELLED',
            fill_info=None,
        )

    def test_open_orders_not_synced(self):
        """Orders still OPEN in API should not trigger a status update."""
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('ord-1', status='OPEN'),
        ])
        tracker = Mock()
        tracked_order = Mock()
        tracked_order.order_id = 'ord-1'
        tracked_order.is_completed.return_value = False
        tracker.list_stop_limit_orders.return_value = [tracked_order]

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_not_called()

    def test_api_exception_no_crash(self):
        api = Mock()
        api.list_orders.side_effect = RuntimeError("network error")
        tracker = Mock()
        svc = _make_service(api_client=api, conditional_tracker=tracker)

        # Should not raise
        svc.sync_conditional_order_statuses()

        tracker.update_order_status.assert_not_called()

    def test_multiple_orders_mixed_statuses(self):
        api = Mock()
        api.list_orders.return_value = Mock(orders=[
            _mock_order('ord-1', status='FILLED'),
            _mock_order('ord-2', status='OPEN'),
            _mock_order('ord-3', status='CANCELLED'),
        ])
        tracker = Mock()
        orders = []
        for oid in ['ord-1', 'ord-2', 'ord-3', 'ord-4']:
            o = Mock()
            o.order_id = oid
            o.is_completed.return_value = False
            orders.append(o)
        tracker.list_stop_limit_orders.return_value = orders

        svc = _make_service(api_client=api, conditional_tracker=tracker)
        svc.sync_conditional_order_statuses()

        # ord-1 FILLED, ord-3 CANCELLED, ord-4 missing -> CANCELLED
        # ord-2 is OPEN so no update
        assert tracker.update_order_status.call_count == 3
        statuses = {call[1]['order_id']: call[1]['status']
                    for call in tracker.update_order_status.call_args_list}
        assert statuses == {
            'ord-1': 'FILLED',
            'ord-3': 'CANCELLED',
            'ord-4': 'CANCELLED',
        }
