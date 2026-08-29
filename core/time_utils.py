import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Union
from bs4 import BeautifulSoup


FRESHNESS_WINDOWS: Dict[str, int] = {
    "past-1h": 60,
    "past-4h": 240,
    "past-12h": 720,
    "past-24h": 1440,
    "past-3d": 4320,
    "past-7d": 4320,  # Enforce strict max 3-day window (4320 minutes)
}

# Supported aliases for backward compatibility with existing MCP / REST clients
TIMEFRAME_ALIASES: Dict[str, str] = {
    "1h": "past-1h",
    "4h": "past-4h",
    "12h": "past-12h",
    "24h": "past-24h",
    "1d": "past-24h",
    "d": "past-24h",
    "past-day": "past-24h",
    "3d": "past-3d",
    "3days": "past-3d",
    "past-3d": "past-3d",
    "past-3days": "past-3d",
    "7d": "past-3d",
    "1w": "past-3d",
    "w": "past-3d",
    "past-week": "past-3d",
    "past-month": "past-3d",
    "m": "past-3d",
}


def get_max_age_minutes(timeframe: Optional[str] = "past-24h") -> int:
    """
    Returns the maximum allowable post age in minutes for a given timeframe string.
    Raises ValueError for invalid timeframes.
    """
    if not timeframe:
        return FRESHNESS_WINDOWS["past-24h"]

    tf_clean = str(timeframe).lower().strip()
    
    # Direct match in standard windows
    if tf_clean in FRESHNESS_WINDOWS:
        return FRESHNESS_WINDOWS[tf_clean]

    # Check aliases
    if tf_clean in TIMEFRAME_ALIASES:
        canonical = TIMEFRAME_ALIASES[tf_clean]
        return FRESHNESS_WINDOWS[canonical]

    valid_keys = list(FRESHNESS_WINDOWS.keys()) + list(TIMEFRAME_ALIASES.keys())
    raise ValueError(f"Invalid timeframe '{timeframe}'. Must be one of: {valid_keys}")


def extract_snowflake_timestamp(url: str) -> Optional[datetime]:
    """
    Extracts the exact publication datetime from a LinkedIn Snowflake activity/share ID.
    Formula: epoch_seconds = (activity_id >> 22) / 1000.0
    """
    if not url:
        return None

    # Matches activity-7498493404704591873 or activity:7498493404704591873 or share-12345
    match = re.search(r'(?:activity|share)[:-](\d{15,})', url)
    if match:
        try:
            aid = int(match.group(1))
            ts_sec = (aid >> 22) / 1000.0
            return datetime.fromtimestamp(ts_sec, tz=timezone.utc)
        except Exception:
            return None
    return None


def parse_timestamp(
    soup_or_str: Optional[Union[BeautifulSoup, str]] = None,
    url: str = ""
) -> Optional[datetime]:
    """
    Extracts timezone-aware UTC publication timestamp in priority order:
    1. LinkedIn Activity ID / Snowflake timestamp (url)
    2. JSON-LD datePublished, dateCreated, uploadDate
    3. <meta property="article:published_time">
    4. <meta name="date">
    5. <time datetime="...">
    
    Returns None if timestamp cannot be verified.
    """
    # 1. Check Snowflake Activity ID first (exact to millisecond)
    if url:
        snow_dt = extract_snowflake_timestamp(url)
        if snow_dt is not None:
            return snow_dt

    if not soup_or_str:
        return None

    candidates = []

    # If a raw string was passed
    if isinstance(soup_or_str, str):
        candidates.append(soup_or_str)
    elif isinstance(soup_or_str, BeautifulSoup):
        # 2. JSON-LD schema
        for script in soup_or_str.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            for key in ["datePublished", "dateCreated", "uploadDate"]:
                match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
                if match:
                    candidates.append(match.group(1))

        # 3. Meta article:published_time
        meta_pub = soup_or_str.find("meta", attrs={"property": "article:published_time"})
        if meta_pub and meta_pub.get("content"):
            candidates.append(meta_pub.get("content"))

        # 4. Meta date
        meta_d = soup_or_str.find("meta", attrs={"name": "date"})
        if meta_d and meta_d.get("content"):
            candidates.append(meta_d.get("content"))

        # 5. <time datetime="...">
        for time_tag in soup_or_str.find_all("time"):
            val = time_tag.get("datetime")
            if val:
                candidates.append(val)

    # Parse and validate candidates
    for val in candidates:
        try:
            cleaned = str(val).strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

    return None


def calculate_age(
    published_at: datetime,
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Calculates exact elapsed age in minutes, hours, and human-readable text.
    Assumes timezone-aware UTC datetime.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    diff = now - published_at
    total_seconds = diff.total_seconds()

    # Reject future timestamps
    if total_seconds < 0:
        return {
            "is_valid": False,
            "is_future": True,
            "age_minutes": -1,
            "age_hours": -1,
            "age_text": "future",
            "published_at_utc": published_at.isoformat(),
        }

    total_minutes = int(total_seconds // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60

    if hours < 1:
        age_text = f"{minutes}m ago"
    elif hours < 24:
        age_text = f"{hours}h {minutes}m ago"
    else:
        days = hours // 24
        age_text = f"{days}d {hours % 24}h ago"

    return {
        "is_valid": True,
        "is_future": False,
        "age_minutes": total_minutes,
        "age_hours": hours,
        "age_text": age_text,
        "published_at_utc": published_at.isoformat(),
    }


def is_within_window(
    published_at: datetime,
    max_age_minutes: int,
    now: Optional[datetime] = None
) -> bool:
    """
    Checks if a post's age is strictly within [0, max_age_minutes).
    Boundary:
      age < max_age_minutes -> True
      age >= max_age_minutes -> False
      age < 0 (future) -> False
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    diff = now - published_at
    total_seconds = diff.total_seconds()

    if total_seconds < 0:
        return False

    return total_seconds < (max_age_minutes * 60)


def format_age(age_minutes: int) -> str:
    """Formats integer minutes to human-readable string."""
    if age_minutes < 0:
        return "Unknown"
    if age_minutes < 60:
        return f"{age_minutes}m ago"
    hours = age_minutes // 60
    mins = age_minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m ago"
    days = hours // 24
    return f"{days}d {hours % 24}h ago"
