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
    Lightweight SQLite-backed cache with Timeframe-Aware Time-To-Live (TTL).
    Prevents stale results for ultra-fresh searches (e.g. past-1h).
    """

    TIMEFRAME_TTL: Dict[str, int] = {
        "past-1h": 60,       # 1 minute (ultra-fresh live polling)
        "past-4h": 300,      # 5 minutes
        "past-12h": 900,     # 15 minutes
        "past-24h": 1800,    # 30 minutes
        "past-7d": 7200,     # 2 hours
    }

    def __init__(self, db_path: Path = CACHE_DB_PATH, default_ttl: int = CACHE_TTL_SECONDS):
        self.db_path = db_path
        self.default_ttl = default_ttl
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    ttl_seconds INTEGER NOT NULL DEFAULT 1800
                )
            """)
            conn.commit()
            try:
                cursor.execute("ALTER TABLE search_cache ADD COLUMN ttl_seconds INTEGER NOT NULL DEFAULT 1800")
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists
                pass

    def get_ttl_for_timeframe(self, timeframe: str) -> int:
        return self.TIMEFRAME_TTL.get(timeframe.lower().strip(), self.default_ttl)

    def get(self, query_key: str, timeframe: str = "past-24h") -> Optional[List[Dict[str, Any]]]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json, timestamp, ttl_seconds FROM search_cache WHERE query_key = ?", 
                    (query_key.lower().strip(),)
                )
                row = cursor.fetchone()
                if not row:
                    return None

                data_json, timestamp, stored_ttl = row
                effective_ttl = self.get_ttl_for_timeframe(timeframe)

                if (time.time() - timestamp) > effective_ttl:
                    # Expired
                    cursor.execute("DELETE FROM search_cache WHERE query_key = ?", (query_key.lower().strip(),))
                    conn.commit()
                    return None

                return json.loads(data_json)
        except Exception:
            return None

    def set(self, query_key: str, data: List[Dict[str, Any]], timeframe: str = "past-24h"):
        if not data:
            return
        ttl = self.get_ttl_for_timeframe(timeframe)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO search_cache (query_key, data_json, timestamp, ttl_seconds)
                    VALUES (?, ?, ?, ?)
                """, (query_key.lower().strip(), json.dumps(data), time.time(), ttl))
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
