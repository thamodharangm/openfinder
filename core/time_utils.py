"""
core/time_utils.py
==================
Production-grade Timezone-Aware UTC Timestamp & LinkedIn Snowflake Intelligence Engine.

Features:
- Precision Snowflake decoding: Extracts exact publication millisecond from 19-digit LinkedIn Activity IDs.
- Comprehensive timeframe windows & aliases ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d', 'past-week', '1d', 'today', etc.).
- Multi-source DOM parser: Snowflake ID -> JSON-LD -> <meta article:published_time> -> <time datetime="..."> -> Relative text strings.
- Relative elapsed time parser ('2h ago', '45m ago', '1d ago', 'just now') into UTC datetime objects.
- Monotonic age calculation, freshness decay scoring, and human-readable age formatters.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ============================================================================
# 1. TIMEFRAME FRESHNESS WINDOWS & ALIASES
# ============================================================================

FRESHNESS_WINDOWS: Dict[str, int] = {
    "past-1h": 60,
    "past-4h": 240,
    "past-12h": 720,
    "past-24h": 1440,
    "past-3d": 4320,
    "past-7d": 4320,  # Enforce strict 3-day max cap for live fresh posts
}

TIMEFRAME_ALIASES: Dict[str, str] = {
    "1h": "past-1h",
    "4h": "past-4h",
    "12h": "past-12h",
    "24h": "past-24h",
    "1d": "past-24h",
    "d": "past-24h",
    "today": "past-24h",
    "past-day": "past-24h",
    "past-24hours": "past-24h",
    "3d": "past-3d",
    "3days": "past-3d",
    "past-3d": "past-3d",
    "past-3days": "past-3d",
    "7d": "past-3d",
    "1w": "past-3d",
    "w": "past-3d",
    "past-week": "past-3d",
    "week": "past-3d",
    "past-month": "past-3d",
    "month": "past-3d",
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

    # Direct match
    if tf_clean in FRESHNESS_WINDOWS:
        return FRESHNESS_WINDOWS[tf_clean]

    # Alias match
    if tf_clean in TIMEFRAME_ALIASES:
        canonical = TIMEFRAME_ALIASES[tf_clean]
        return FRESHNESS_WINDOWS[canonical]

    valid_keys = list(FRESHNESS_WINDOWS.keys()) + list(TIMEFRAME_ALIASES.keys())
    raise ValueError(f"Invalid timeframe '{timeframe}'. Must be one of: {valid_keys}")


# ============================================================================
# 2. SNOWFLAKE ACTIVITY ID DECODER
# ============================================================================

def extract_snowflake_timestamp(url_or_id: Union[str, int]) -> Optional[datetime]:
    """
    Extracts the exact publication datetime from a LinkedIn Snowflake activity/share ID.
    Formula: epoch_seconds = (activity_id >> 22) / 1000.0
    """
    if not url_or_id:
        return None

    raw_str = str(url_or_id).strip()

    # Matches activity-7498493404704591873 or activity:7498493404704591873 or urn:li:activity:7498... or share-12345
    match = re.search(r'(?:activity|share|ugcPost)[:-](\d{15,20})', raw_str)
    if match:
        aid_str = match.group(1)
    elif raw_str.isdigit() and len(raw_str) >= 15:
        aid_str = raw_str
    else:
        return None

    try:
        aid = int(aid_str)
        ts_sec = (aid >> 22) / 1000.0
        dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)

        # Sanity check: Ensure date is between 2015 and current year + 1
        now_yr = datetime.now(timezone.utc).year
        if 2015 <= dt.year <= now_yr + 1:
            return dt
        return None
    except Exception:
        return None


# ============================================================================
# 3. RELATIVE TIME STRING PARSER
# ============================================================================

_RELATIVE_TIME_REGEX = re.compile(
    r'(\d+)\s*(s|sec|seconds?|m|min|minutes?|h|hr|hours?|d|days?|w|weeks?|mo|months?|y|yrs?|years?)\s*(?:ago)?\b',
    re.IGNORECASE
)


def parse_relative_time_str(rel_str: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parses relative text representations ('2h ago', '45m ago', '3d ago', 'just now') into UTC datetime.
    """
    if not rel_str or not isinstance(rel_str, str):
        return None

    clean = rel_str.lower().strip()
    if clean in ["just now", "now", "recently", "moments ago", "few seconds ago"]:
        ref = now or datetime.now(timezone.utc)
        return ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)

    match = _RELATIVE_TIME_REGEX.search(clean)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    if unit.startswith("s"):
        return ref - timedelta(seconds=amount)
    elif unit.startswith("m") and not unit.startswith("mo"):
        return ref - timedelta(minutes=amount)
    elif unit.startswith("h"):
        return ref - timedelta(hours=amount)
    elif unit.startswith("d"):
        return ref - timedelta(days=amount)
    elif unit.startswith("w"):
        return ref - timedelta(weeks=amount)
    elif unit.startswith("mo"):
        return ref - timedelta(days=amount * 30)
    elif unit.startswith("y"):
        return ref - timedelta(days=amount * 365)

    return None


# ============================================================================
# 4. MULTI-SOURCE DOM & METADATA TIMESTAMP PARSER
# ============================================================================

def parse_timestamp(
    soup_or_str: Optional[Union[BeautifulSoup, str]] = None,
    url: str = ""
) -> Optional[datetime]:
    """
    Extracts timezone-aware UTC publication timestamp in priority order:
    1. LinkedIn Activity ID / Snowflake timestamp (url)
    2. JSON-LD datePublished, dateCreated, uploadDate
    3. <meta property="article:published_time" / "og:published_time">
    4. <meta name="date" / "pubdate">
    5. <time datetime="...">
    6. Relative text snippet regex fallback
    """
    # 1. Check Snowflake Activity ID first (exact to millisecond)
    if url:
        snow_dt = extract_snowflake_timestamp(url)
        if snow_dt is not None:
            return snow_dt

    if not soup_or_str:
        return None

    candidates: List[str] = []

    # If raw ISO string was passed directly
    if isinstance(soup_or_str, str):
        candidates.append(soup_or_str)
    elif isinstance(soup_or_str, BeautifulSoup):
        # 2. JSON-LD schema
        for script in soup_or_str.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            for key in ["datePublished", "dateCreated", "uploadDate", "startDate"]:
                match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
                if match:
                    candidates.append(match.group(1))

        # 3. Meta article:published_time & og:published_time
        for prop in ["article:published_time", "og:published_time", "og:article:published_time"]:
            meta_pub = soup_or_str.find("meta", attrs={"property": prop})
            if meta_pub and meta_pub.get("content"):
                candidates.append(meta_pub.get("content"))

        # 4. Meta date
        for name in ["date", "pubdate", "publish-date"]:
            meta_d = soup_or_str.find("meta", attrs={"name": name})
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
            # Try relative parser
            rel_dt = parse_relative_time_str(str(val))
            if rel_dt is not None:
                return rel_dt

    return None


# ============================================================================
# 5. AGE & FRESHNESS CALCULATORS
# ============================================================================

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
        age_text = f"{minutes}m ago" if minutes > 0 else "just now"
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


def calculate_freshness_score(age_minutes: int, max_age_minutes: int = 1440) -> int:
    """
    Computes an explainable non-linear half-life freshness score from 100 down to 0.
    Recruiter responsiveness is highest in the first 4 hours (golden window).
    - < 60 mins: 95-100
    - 1h - 4h: 85-94
    - 4h - 12h: 70-84
    - 12h - 24h: 50-69
    - 24h+: smooth asymptotic decay capped at 0
    """
    if age_minutes < 0:
        return 0
    if max_age_minutes <= 0:
        return 50

    # Non-linear piecewise curve with exponential damping
    if age_minutes <= 60:
        # 100 down to 95 for first hour
        return int(round(100 - (age_minutes / 60.0) * 5))
    elif age_minutes <= 240:
        # 95 down to 85 for 1-4 hours
        frac = (age_minutes - 60) / 180.0
        return int(round(95 - frac * 10))
    elif age_minutes <= 720:
        # 85 down to 70 for 4-12 hours
        frac = (age_minutes - 240) / 480.0
        return int(round(85 - frac * 15))
    elif age_minutes <= max_age_minutes:
        # 70 down to 30 at window limit
        frac = (age_minutes - 720) / max(1.0, float(max_age_minutes - 720))
        return int(round(70 - frac * 40))
    else:
        # Beyond window edge
        over = age_minutes - max_age_minutes
        decay = max(0, int(round(30 * (0.5 ** (over / 1440.0)))))
        return max(0, min(decay, 30))



def format_age(age_minutes: int) -> str:
    """Formats integer minutes to human-readable string."""
    if age_minutes < 0:
        return "Unknown"
    if age_minutes < 60:
        return f"{age_minutes}m ago" if age_minutes > 0 else "just now"
    hours = age_minutes // 60
    mins = age_minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m ago"
    days = hours // 24
    return f"{days}d {hours % 24}h ago"
