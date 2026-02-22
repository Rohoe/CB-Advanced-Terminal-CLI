"""
Unit tests for storage layer (FileBasedTWAPStorage, InMemoryTWAPStorage, StorageFactory).

To run:
    pytest tests/test_storage.py -v
"""

import pytest

from storage import FileBasedTWAPStorage, InMemoryTWAPStorage, StorageFactory
from twap_tracker import TWAPOrder, OrderFill


def _make_order(twap_id='test-twap-1'):
    return TWAPOrder(
        twap_id=twap_id, market='BTC-USDC', side='BUY',
        total_size=1.0, limit_price=50000.0, num_slices=10,
        start_time='2026-01-01T00:00:00Z', status='active',
        orders=['order-1', 'order-2'], failed_slices=[], slice_statuses=[]
    )


def _make_fills():
    return [
        OrderFill(order_id='order-1', trade_id='trade-1', filled_size=0.1,
                  price=50000.0, fee=2.0, is_maker=True, trade_time='2026-01-01T00:00:00Z'),
        OrderFill(order_id='order-2', trade_id='trade-2', filled_size=0.1,
                  price=50100.0, fee=3.0, is_maker=False, trade_time='2026-01-01T00:01:00Z'),
    ]


# =============================================================================
# FileBasedTWAPStorage Tests
# =============================================================================

@pytest.mark.unit
class TestFileBasedTWAPStorage:
    """Tests for FileBasedTWAPStorage using tmp_path."""

    @pytest.fixture
    def storage(self, tmp_path):
        return FileBasedTWAPStorage(base_path=str(tmp_path / 'twap_data'))

    def test_save_and_retrieve_order(self, storage):
        order = _make_order()
        storage.save_twap_order(order)
        loaded = storage.get_twap_order('test-twap-1')
        assert loaded is not None
        assert loaded.twap_id == 'test-twap-1'
        assert loaded.market == 'BTC-USDC'
        assert loaded.total_size == 1.0

    def test_get_nonexistent_order(self, storage):
        assert storage.get_twap_order('nonexistent') is None

    def test_save_and_retrieve_fills(self, storage):
        fills = _make_fills()
        storage.save_twap_fills('test-twap-1', fills)
        loaded = storage.get_twap_fills('test-twap-1')
        assert len(loaded) == 2
        assert loaded[0].order_id == 'order-1'
        assert loaded[1].price == 50100.0

    def test_get_fills_nonexistent(self, storage):
        fills = storage.get_twap_fills('nonexistent')
        assert fills == []

    def test_list_orders(self, storage):
        for i in range(3):
            storage.save_twap_order(_make_order(f'twap-{i}'))
        ids = storage.list_twap_orders()
        assert len(ids) == 3
        assert set(ids) == {'twap-0', 'twap-1', 'twap-2'}

    def test_list_orders_empty(self, storage):
        assert storage.list_twap_orders() == []

    def test_delete_order(self, storage):
        order = _make_order()
        fills = _make_fills()
        storage.save_twap_order(order)
        storage.save_twap_fills('test-twap-1', fills)
        assert storage.delete_twap_order('test-twap-1') is True
        assert storage.get_twap_order('test-twap-1') is None

    def test_delete_nonexistent(self, storage):
        assert storage.delete_twap_order('nonexistent') is False

    def test_statistics(self, storage):
        order = _make_order()
        fills = _make_fills()
        storage.save_twap_order(order)
        storage.save_twap_fills('test-twap-1', fills)
        stats = storage.calculate_twap_statistics('test-twap-1')
        assert stats['twap_id'] == 'test-twap-1'
        assert stats['total_filled'] == pytest.approx(0.2)
        assert stats['num_fills'] == 2

    def test_statistics_nonexistent(self, storage):
        stats = storage.calculate_twap_statistics('nonexistent')
        assert stats == {}


# =============================================================================
# InMemoryTWAPStorage Tests
# =============================================================================

@pytest.mark.unit
class TestInMemoryTWAPStorage:
    """Tests for InMemoryTWAPStorage."""

    @pytest.fixture
    def storage(self):
        return InMemoryTWAPStorage()

    def test_save_and_retrieve_order(self, storage):
        order = _make_order()
        storage.save_twap_order(order)
        loaded = storage.get_twap_order('test-twap-1')
        assert loaded is not None
        assert loaded.twap_id == 'test-twap-1'

    def test_get_nonexistent_order(self, storage):
        assert storage.get_twap_order('nonexistent') is None

    def test_save_and_retrieve_fills(self, storage):
        fills = _make_fills()
        storage.save_twap_fills('test-twap-1', fills)
        loaded = storage.get_twap_fills('test-twap-1')
        assert len(loaded) == 2

    def test_get_fills_nonexistent(self, storage):
        assert storage.get_twap_fills('nonexistent') == []

    def test_list_orders(self, storage):
        for i in range(3):
            storage.save_twap_order(_make_order(f'twap-{i}'))
        ids = storage.list_twap_orders()
        assert len(ids) == 3

    def test_delete_order(self, storage):
        storage.save_twap_order(_make_order())
        storage.save_twap_fills('test-twap-1', _make_fills())
        assert storage.delete_twap_order('test-twap-1') is True
        assert storage.get_twap_order('test-twap-1') is None
        assert storage.get_twap_fills('test-twap-1') == []

    def test_delete_nonexistent(self, storage):
        assert storage.delete_twap_order('nonexistent') is False

    def test_clear(self, storage):
        storage.save_twap_order(_make_order())
        storage.save_twap_fills('test-twap-1', _make_fills())
        storage.clear()
        assert storage.get_order_count() == 0
        assert storage.get_fill_count() == 0

    def test_get_order_count(self, storage):
        assert storage.get_order_count() == 0
        storage.save_twap_order(_make_order('t1'))
        storage.save_twap_order(_make_order('t2'))
        assert storage.get_order_count() == 2

    def test_get_fill_count(self, storage):
        assert storage.get_fill_count() == 0
        storage.save_twap_fills('t1', _make_fills())
        assert storage.get_fill_count() == 2

    def test_statistics_with_fills(self, storage):
        order = _make_order()
        fills = _make_fills()
        storage.save_twap_order(order)
        storage.save_twap_fills('test-twap-1', fills)
        stats = storage.calculate_twap_statistics('test-twap-1')
        assert stats['total_filled'] == pytest.approx(0.2)
        assert stats['completion_rate'] == pytest.approx(20.0)
        assert stats['vwap'] == pytest.approx(50050.0)
        assert stats['maker_fills'] == 1
        assert stats['taker_fills'] == 1
        assert 'first_fill_time' in stats
        assert 'last_fill_time' in stats

    def test_statistics_empty_fills(self, storage):
        storage.save_twap_order(_make_order())
        stats = storage.calculate_twap_statistics('test-twap-1')
        assert stats['total_filled'] == 0
        assert stats['completion_rate'] == 0.0
        assert stats['vwap'] == 0.0

    def test_statistics_nonexistent(self, storage):
        assert storage.calculate_twap_statistics('nonexistent') == {}


# =============================================================================
# StorageFactory Tests
# =============================================================================

@pytest.mark.unit
class TestStorageFactory:
    """Tests for StorageFactory."""

    def test_create_file_based(self, tmp_path):
        storage = StorageFactory.create_file_based(base_path=str(tmp_path / 'data'))
        assert isinstance(storage, FileBasedTWAPStorage)

    def test_create_in_memory(self):
        storage = StorageFactory.create_in_memory()
        assert isinstance(storage, InMemoryTWAPStorage)

    def test_create_default(self, tmp_path):
        # Default creates file-based
        storage = StorageFactory.create_default()
        assert isinstance(storage, FileBasedTWAPStorage)
