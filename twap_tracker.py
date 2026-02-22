import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from base_tracker import BaseOrderTracker

@dataclass
class TWAPOrder:
    twap_id: str
    market: str
    side: str
    total_size: float
    limit_price: float
    num_slices: int
    start_time: str
    status: str
    orders: List[str]
    total_placed: float = 0.0
    total_filled: float = 0.0
    total_value_placed: float = 0.0
    total_value_filled: float = 0.0
    total_fees: float = 0.0
    maker_orders: int = 0
    taker_orders: int = 0
    failed_slices: List[int] = None
    slice_statuses: List[Dict] = None

@dataclass
class OrderFill:
    order_id: str
    trade_id: str
    filled_size: float
    price: float
    fee: float
    is_maker: bool
    trade_time: str

class TWAPTracker(BaseOrderTracker):
    def __init__(self, base_path: str = "twap_data"):
        """Initialize TWAPTracker with base path for JSON storage."""
        super().__init__(base_path, ["orders", "fills"])
        self.orders_dir = self._get_subdir("orders")
        self.fills_dir = self._get_subdir("fills")

    def _get_order_path(self, twap_id: str) -> str:
        """Get the file path for a TWAP order JSON."""
        return self._get_path("orders", twap_id)

    def _get_fills_path(self, twap_id: str) -> str:
        """Get the file path for a TWAP fills JSON."""
        return self._get_path("fills", twap_id)

    def save_twap_order(self, twap_order: TWAPOrder):
        """Save or update a TWAP order to JSON."""
        try:
            order_path = self._get_order_path(twap_order.twap_id)
            self._save_json(order_path, asdict(twap_order), f"TWAP order {twap_order.twap_id}")
            logging.info(f"Saved TWAP order {twap_order.twap_id} to {order_path}")
        except Exception as e:
            logging.error(f"Error saving TWAP order: {str(e)}")

    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]):
        """Save or update fills for a TWAP order."""
        try:
            fills_path = self._get_fills_path(twap_id)
            fills_data = [asdict(fill) for fill in fills]
            self._save_json(fills_path, fills_data, f"TWAP fills for {twap_id}")
            logging.info(f"Saved {len(fills)} fills for TWAP {twap_id}")
        except Exception as e:
            logging.error(f"Error saving TWAP fills: {str(e)}")

    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        """Retrieve a TWAP order from JSON."""
        data = self._load_json(self._get_order_path(twap_id), f"TWAP order {twap_id}")
        if data is None:
            return None
        try:
            return TWAPOrder(**data)
        except Exception as e:
            logging.error(f"Error constructing TWAP order: {str(e)}")
            return None

    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        """Retrieve fills for a TWAP order."""
        data = self._load_json(self._get_fills_path(twap_id), f"TWAP fills for {twap_id}")
        if data is None:
            return []
        try:
            return [OrderFill(**fill_data) for fill_data in data]
        except Exception as e:
            logging.error(f"Error constructing TWAP fills: {str(e)}")
            return []

    def list_twap_orders(self) -> List[str]:
        """List all TWAP order IDs."""
        return self._list_ids("orders")

    def calculate_fee(self, fill_size: float, fill_price: float, fee_tier: dict, is_maker: bool) -> float:
        """Calculate fee for a fill based on fee tier."""
        try:
            rate = float(fee_tier['maker_fee_rate']) if is_maker else float(fee_tier['taker_fee_rate'])
            return fill_size * fill_price * rate
        except Exception as e:
            logging.error(f"Error calculating fee: {str(e)}")
            return 0.0

    def calculate_twap_statistics(self, twap_id: str) -> dict:
        """Calculate comprehensive statistics for a TWAP order."""
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
