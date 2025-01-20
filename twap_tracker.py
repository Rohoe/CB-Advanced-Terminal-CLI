import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

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
    
class TWAPTracker:
    def __init__(self, base_path: str = "twap_data"):
        """Initialize TWAPTracker with base path for JSON storage."""
        self.base_path = base_path
        self.orders_dir = os.path.join(base_path, "orders")
        self.fills_dir = os.path.join(base_path, "fills")
        self._ensure_directories()
        
    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        os.makedirs(self.orders_dir, exist_ok=True)
        os.makedirs(self.fills_dir, exist_ok=True)
        
    def _get_order_path(self, twap_id: str) -> str:
        """Get the file path for a TWAP order JSON."""
        return os.path.join(self.orders_dir, f"{twap_id}.json")
        
    def _get_fills_path(self, twap_id: str) -> str:
        """Get the file path for a TWAP fills JSON."""
        return os.path.join(self.fills_dir, f"{twap_id}.json")
        
    def save_twap_order(self, twap_order: TWAPOrder):
        """Save or update a TWAP order to JSON."""
        try:
            order_path = self._get_order_path(twap_order.twap_id)
            with open(order_path, 'w') as f:
                json.dump(asdict(twap_order), f, indent=2)
            logging.info(f"Saved TWAP order {twap_order.twap_id} to {order_path}")
        except Exception as e:
            logging.error(f"Error saving TWAP order: {str(e)}")
            
    def save_twap_fills(self, twap_id: str, fills: List[OrderFill]):
        """Save or update fills for a TWAP order."""
        try:
            fills_path = self._get_fills_path(twap_id)
            fills_data = [asdict(fill) for fill in fills]
            with open(fills_path, 'w') as f:
                json.dump(fills_data, f, indent=2)
            logging.info(f"Saved {len(fills)} fills for TWAP {twap_id}")
        except Exception as e:
            logging.error(f"Error saving TWAP fills: {str(e)}")
            
    def get_twap_order(self, twap_id: str) -> Optional[TWAPOrder]:
        """Retrieve a TWAP order from JSON."""
        try:
            order_path = self._get_order_path(twap_id)
            if not os.path.exists(order_path):
                return None
            with open(order_path, 'r') as f:
                data = json.load(f)
            return TWAPOrder(**data)
        except Exception as e:
            logging.error(f"Error loading TWAP order: {str(e)}")
            return None
            
    def get_twap_fills(self, twap_id: str) -> List[OrderFill]:
        """Retrieve fills for a TWAP order."""
        try:
            fills_path = self._get_fills_path(twap_id)
            if not os.path.exists(fills_path):
                return []
            with open(fills_path, 'r') as f:
                data = json.load(f)
            return [OrderFill(**fill_data) for fill_data in data]
        except Exception as e:
            logging.error(f"Error loading TWAP fills: {str(e)}")
            return []
            
    def list_twap_orders(self) -> List[str]:
        """List all TWAP order IDs."""
        try:
            files = os.listdir(self.orders_dir)
            return [f.replace('.json', '') for f in files if f.endswith('.json')]
        except Exception as e:
            logging.error(f"Error listing TWAP orders: {str(e)}")
            return []
            
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