import sqlite3
import json
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
import sys

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CACHE_DB_PATH, CACHE_TTL_SECONDS


class SearchCache:
    """
    Lightweight SQLite-backed cache with Time-To-Live (TTL) 
    to provide instant responses and avoid redundant web queries.
    """

    def __init__(self, db_path: Path = CACHE_DB_PATH, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.db_path = db_path
        self.ttl = ttl_seconds
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            conn.commit()

    def get(self, query_key: str) -> Optional[List[Dict[str, Any]]]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json, timestamp FROM search_cache WHERE query_key = ?", 
                    (query_key.lower().strip(),)
                )
                row = cursor.fetchone()
                if not row:
                    return None

                data_json, timestamp = row
                if (time.time() - timestamp) > self.ttl:
                    # Expired
                    cursor.execute("DELETE FROM search_cache WHERE query_key = ?", (query_key.lower().strip(),))
                    conn.commit()
                    return None

                return json.loads(data_json)
        except Exception:
            return None

    def set(self, query_key: str, data: List[Dict[str, Any]]):
        if not data:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO search_cache (query_key, data_json, timestamp)
                    VALUES (?, ?, ?)
                """, (query_key.lower().strip(), json.dumps(data), time.time()))
                conn.commit()
        except Exception:
            pass

    def clear(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM search_cache")
                conn.commit()
        except Exception:
            pass
