"""
Generic base class for JSON-based order persistence.

Provides common file I/O operations (save, load, list, delete, directory
management) that are shared across TWAPTracker, ScaledOrderTracker, and
ConditionalOrderTracker.

Subclasses supply their own serialization/deserialization and public API;
this base handles only the repeated JSON-on-disk plumbing.
"""

import json
import os
import logging
from typing import Optional, List


class BaseOrderTracker:
    """Low-level JSON file persistence shared by all order trackers."""

    def __init__(self, base_dir: str, subdirs: List[str]):
        self.base_dir = base_dir
        self._subdirs = {name: os.path.join(base_dir, name) for name in subdirs}
        self._ensure_directories()

    def _ensure_directories(self):
        for path in self._subdirs.values():
            os.makedirs(path, exist_ok=True)

    def _get_subdir(self, name: str) -> str:
        return self._subdirs[name]

    def _get_path(self, subdir_name: str, item_id: str) -> str:
        return os.path.join(self._subdirs[subdir_name], f"{item_id}.json")

    def _save_json(self, path: str, data: dict, label: str = "item") -> None:
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving {label}: {e}")
            raise

    def _load_json(self, path: str, label: str = "item") -> Optional[dict]:
        try:
            if not os.path.exists(path):
                return None
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading {label}: {e}")
            return None

    def _list_ids(self, subdir_name: str) -> List[str]:
        try:
            dir_path = self._subdirs[subdir_name]
            if not os.path.exists(dir_path):
                return []
            return [f[:-5] for f in os.listdir(dir_path) if f.endswith('.json')]
        except Exception as e:
            logging.error(f"Error listing items in {subdir_name}: {e}")
            return []

    def _delete_file(self, path: str, label: str = "item") -> bool:
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            logging.error(f"Error deleting {label}: {e}")
            return False
