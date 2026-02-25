"""
Storage abstraction layer for TWAP order persistence.

This module provides an abstract interface for TWAP order storage,
enabling dependency injection and making the code testable with
in-memory storage implementations.

Usage:
    # Production usage (file-based)
    from storage import FileBasedTWAPStorage
    storage = FileBasedTWAPStorage()

    # Testing usage (in-memory)
    from storage import InMemoryTWAPStorage
    storage = InMemoryTWAPStorage()

    # Both can be used interchangeably
    storage.save_twap_order(order)
    order = storage.get_twap_order(twap_id)
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
import logging

from twap_tracker import TWAPOrder, OrderFill, TWAPTracker


class TWAPStorage(ABC):
    """
    Abstract interface for TWAP order storage.

    This abstract class defines the contract for TWAP order persistence.
    Both FileBasedTWAPStorage (production) and InMemoryTWAPStorage (testing)
    implement this interface.

    Implementing this interface allows:
    - Dependency injection in TradingTerminal
    - In-memory storage for fast unit tests
    - Potential for alternative storage backends (database, cloud, etc.)
    """

    @abstractmethod
    def save_twap_order(self, twap_order: TWAPOrder) -> None:
        """
        Save or update a TWAP order.

        Args:
            twap_order: The TWAP order to save.
        """
        pass

    @abstractmethod
    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        """
        Retrieve a TWAP order by ID.

        Args:
            twap_id: The unique identifier of the TWAP order.

        Returns:
            The TWAP order if found, None otherwise.
        """
        pass

    @abstractmethod
    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]) -> None:
        """
        Save fills for a TWAP order.

        Args:
            twap_id: The TWAP order ID.
            fills: List of order fills to save.
        """
        pass

    @abstractmethod
    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        """
        Retrieve fills for a TWAP order.

        Args:
            twap_id: The TWAP order ID.

        Returns:
            List of order fills, empty list if none found.
        """
        pass

    @abstractmethod
    def list_twap_orders(self) -> List[str]:
        """
        List all TWAP order IDs.

        Returns:
            List of TWAP order IDs.
        """
        pass

    @abstractmethod
    def delete_twap_order(self, twap_id: str) -> bool:
        """
        Delete a TWAP order and its fills.

        Args:
            twap_id: The TWAP order ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        pass

    @abstractmethod
    def calculate_twap_statistics(self, twap_id: str) -> dict:
        """
        Calculate statistics for a TWAP order.

        Args:
            twap_id: The TWAP order ID.

        Returns:
            Dictionary with statistics (VWAP, completion rate, fees, etc.)
        """
        pass


class FileBasedTWAPStorage(TWAPStorage):
    """
    File-based implementation of TWAPStorage using TWAPTracker.

    This class wraps the existing TWAPTracker to provide a consistent
    interface for TWAP order storage.

    Data is stored as JSON files in the configured base path:
    - {base_path}/orders/{twap_id}.json - TWAP order metadata
    - {base_path}/fills/{twap_id}.json - Order fill information

    Example:
        storage = FileBasedTWAPStorage(base_path="twap_data")
        storage.save_twap_order(order)
        order = storage.get_twap_order("twap-123")
    """

    def __init__(self, base_path: str = "twap_data"):
        """
        Initialize file-based storage.

        Args:
            base_path: Directory path for storing TWAP data.
        """
        self._tracker = TWAPTracker(base_path)
        self._base_path = base_path
        logging.debug(f"FileBasedTWAPStorage initialized with base_path: {base_path}")

    def save_twap_order(self, twap_order: TWAPOrder) -> None:
        """Save or update a TWAP order to JSON file."""
        self._tracker.save_twap_order(twap_order)

    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        """Retrieve a TWAP order from JSON file."""
        return self._tracker.get_twap_order(twap_id)

    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]) -> None:
        """Save fills for a TWAP order to JSON file."""
        self._tracker.save_twap_fills(twap_id, fills)

    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        """Retrieve fills for a TWAP order from JSON file."""
        return self._tracker.get_twap_fills(twap_id)

    def list_twap_orders(self) -> List[str]:
        """List all TWAP order IDs from file system."""
        return self._tracker.list_twap_orders()

    def delete_twap_order(self, twap_id: str) -> bool:
        """
        Delete a TWAP order and its fills from file system.

        Args:
            twap_id: The TWAP order ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        import os

        order_path = self._tracker._get_order_path(twap_id)
        fills_path = self._tracker._get_fills_path(twap_id)

        deleted = False

        if os.path.exists(order_path):
            os.remove(order_path)
            deleted = True
            logging.info(f"Deleted TWAP order file: {order_path}")

        if os.path.exists(fills_path):
            os.remove(fills_path)
            logging.info(f"Deleted TWAP fills file: {fills_path}")

        return deleted

    def calculate_twap_statistics(self, twap_id: str) -> dict:
        """Calculate statistics for a TWAP order."""
        return self._tracker.calculate_twap_statistics(twap_id)


class InMemoryTWAPStorage(TWAPStorage):
    """
    In-memory implementation of TWAPStorage for testing.

    This class stores TWAP orders and fills in memory, making it
    ideal for unit tests where file I/O would slow down test execution
    and create side effects.

    Example:
        storage = InMemoryTWAPStorage()
        storage.save_twap_order(order)
        order = storage.get_twap_order("twap-123")
        storage.clear()  # Reset for next test
    """

    def __init__(self):
        """Initialize in-memory storage."""
        self._orders: Dict[str, TWAPOrder] = {}
        self._fills: Dict[str, List[OrderFill]] = {}
        logging.debug("InMemoryTWAPStorage initialized")

    def save_twap_order(self, twap_order: TWAPOrder) -> None:
        """Save or update a TWAP order in memory."""
        self._orders[twap_order.twap_id] = twap_order
        logging.debug(f"Saved TWAP order in memory: {twap_order.twap_id}")

    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        """Retrieve a TWAP order from memory."""
        return self._orders.get(twap_id)

    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]) -> None:
        """Save fills for a TWAP order in memory."""
        self._fills[twap_id] = fills
        logging.debug(f"Saved {len(fills)} fills for TWAP {twap_id}")

    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        """Retrieve fills for a TWAP order from memory."""
        return self._fills.get(twap_id, [])

    def list_twap_orders(self) -> List[str]:
        """List all TWAP order IDs from memory."""
        return list(self._orders.keys())

    def delete_twap_order(self, twap_id: str) -> bool:
        """
        Delete a TWAP order and its fills from memory.

        Args:
            twap_id: The TWAP order ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        deleted = False

        if twap_id in self._orders:
            del self._orders[twap_id]
            deleted = True

        if twap_id in self._fills:
            del self._fills[twap_id]

        return deleted

    def calculate_twap_statistics(self, twap_id: str) -> dict:
        """
        Calculate statistics for a TWAP order.

        Replicates the logic from TWAPTracker.calculate_twap_statistics
        for in-memory data.
        """
        order = self.get_twap_order(twap_id)
        if not order:
            return {}

        fills = self.get_twap_fills(twap_id)

        stats = {
            'twap_id': twap_id,
            'market': order.market,
            'side': order.side,
            'total_size': order.total_size,
            'total_filled': sum(fill.filled_size for fill in fills),
            'total_value_filled': sum(fill.filled_size * fill.price for fill in fills),
            'total_fees': sum(fill.fee for fill in fills),
            'maker_fills': sum(1 for fill in fills if fill.is_maker),
            'taker_fills': sum(1 for fill in fills if not fill.is_maker),
            'num_fills': len(fills),
            'completion_rate': 0.0,
            'average_price': 0.0,
            'vwap': 0.0
        }

        if stats['total_filled'] > 0:
            stats['completion_rate'] = (stats['total_filled'] / order.total_size) * 100
            stats['vwap'] = stats['total_value_filled'] / stats['total_filled']

        if fills:
            stats['first_fill_time'] = min(fill.trade_time for fill in fills)
            stats['last_fill_time'] = max(fill.trade_time for fill in fills)

        return stats

    def clear(self) -> None:
        """
        Clear all stored data.

        Useful for resetting state between tests.
        """
        self._orders.clear()
        self._fills.clear()
        logging.debug("InMemoryTWAPStorage cleared")

    def get_order_count(self) -> int:
        """Get the number of stored orders."""
        return len(self._orders)

    def get_fill_count(self) -> int:
        """Get the total number of stored fills across all orders."""
        return sum(len(fills) for fills in self._fills.values())


class StorageFactory:
    """
    Factory for creating storage instances.

    This factory simplifies storage creation and provides a single point
    for configuration-based storage instantiation.

    Example:
        # Create production storage
        storage = StorageFactory.create_file_based()

        # Create test storage
        storage = StorageFactory.create_in_memory()
    """

    @staticmethod
    def create_file_based(base_path: str = "twap_data") -> FileBasedTWAPStorage:
        """
        Create a file-based storage instance.

        Args:
            base_path: Directory path for storing TWAP data.

        Returns:
            Configured FileBasedTWAPStorage instance.
        """
        return FileBasedTWAPStorage(base_path=base_path)

    @staticmethod
    def create_in_memory() -> InMemoryTWAPStorage:
        """
        Create an in-memory storage instance for testing.

        Returns:
            InMemoryTWAPStorage instance.
        """
        return InMemoryTWAPStorage()

    @staticmethod
    def create_sqlite(db) -> TWAPStorage:
        """
        Create a SQLite-backed storage instance.

        Args:
            db: Database instance.

        Returns:
            SQLiteTWAPStorage instance.
        """
        from sqlite_storage import SQLiteTWAPStorage
        return SQLiteTWAPStorage(db)

    @staticmethod
    def create_default() -> TWAPStorage:
        """
        Create the default storage implementation.

        In production, this returns file-based storage.
        Override this method or use create_in_memory() for testing.

        Returns:
            Default TWAPStorage implementation.
        """
        return FileBasedTWAPStorage()
