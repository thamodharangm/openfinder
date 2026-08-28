import sqlite3
import json
import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
import sys

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CACHE_DB_PATH, TIMEFRAME_TTLS


class SearchCache:
    """
    Production-Hardened SQLite Cache with Timeframe-Aware TTL,
    Thread-Safety, Corrupt-Data Recovery, and In-Memory Fallback.
    """

    _lock = threading.Lock()
    _in_memory_fallback: Dict[str, Tuple[float, int, List[Dict[str, Any]]]] = {}

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = db_path
        self._fallback_mode = False
        self._init_db()

    def _init_db(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=5.0) as conn:
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
                        pass
        except Exception:
            # Switch to safe in-memory fallback if disk/sqlite fails
            self._fallback_mode = True

    def get_ttl_for_timeframe(self, timeframe: str) -> int:
        clean = (timeframe or "past-24h").lower().strip()
        return TIMEFRAME_TTLS.get(clean, TIMEFRAME_TTLS.get("default", 1800))

    def get(self, query_key: str, timeframe: str = "past-24h") -> Optional[List[Dict[str, Any]]]:
        if not query_key:
            return None

        clean_key = query_key.lower().strip()
        effective_ttl = self.get_ttl_for_timeframe(timeframe)
        now = time.time()

        if self._fallback_mode:
            with self._lock:
                entry = self._in_memory_fallback.get(clean_key)
                if not entry:
                    return None
                ts, ttl, data = entry
                if (now - ts) > effective_ttl:
                    del self._in_memory_fallback[clean_key]
                    return None
                return data

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT data_json, timestamp, ttl_seconds FROM search_cache WHERE query_key = ?", 
                        (clean_key,)
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None

                    data_json, timestamp, _ = row
                    if (now - timestamp) > effective_ttl:
                        # Expired
                        cursor.execute("DELETE FROM search_cache WHERE query_key = ?", (clean_key,))
                        conn.commit()
                        return None

                    try:
                        return json.loads(data_json)
                    except json.JSONDecodeError:
                        # Graceful recovery from corrupt cache record
                        cursor.execute("DELETE FROM search_cache WHERE query_key = ?", (clean_key,))
                        conn.commit()
                        return None

        except Exception:
            return None

    def set(self, query_key: str, data: List[Dict[str, Any]], timeframe: str = "past-24h"):
        if not query_key or not data:
            return

        clean_key = query_key.lower().strip()
        ttl = self.get_ttl_for_timeframe(timeframe)
        now = time.time()

        if self._fallback_mode:
            with self._lock:
                self._in_memory_fallback[clean_key] = (now, ttl, data)
            return

        try:
            serialized = json.dumps(data)
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO search_cache (query_key, data_json, timestamp, ttl_seconds)
                        VALUES (?, ?, ?, ?)
                    """, (clean_key, serialized, now, ttl))
                    conn.commit()
        except Exception:
            with self._lock:
                self._in_memory_fallback[clean_key] = (now, ttl, data)

    def prune_expired(self):
        """Housekeeping: cleans up all stale cache rows."""
        now = time.time()
        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM search_cache WHERE (? - timestamp) > ttl_seconds", (now,))
                    conn.commit()
        except Exception:
            pass

    def clear(self):
        try:
            with self._lock:
                self._in_memory_fallback.clear()
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM search_cache")
                    conn.commit()
        except Exception:
            pass
