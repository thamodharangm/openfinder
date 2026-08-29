"""
core/linkedin_urls.py
=====================
Production-grade LinkedIn URL Normalization, Validation, ID Extraction & Redirect Unwrapping Engine.

Features:
- Strict validation ensuring only genuine recruiter/founder /posts/ URLs are processed.
- Robust normalization stripping all tracking parameters (utm_*, trackingId, rcm, refId, etc.).
- Direct extraction of 19-digit LinkedIn Activity Snowflake IDs and author slugs.
- Conversion of feed update URLs and URNs (urn:li:activity:*) into canonical /posts/ format.
- Unwrapping of search engine redirect wrappers (Yahoo RU=, Bing base64 /ck/, Google /url?q=).
"""

import base64
import re
from typing import Optional, Set, Tuple
import urllib.parse

# Pre-compiled high-performance regular expressions
_ACTIVITY_ID_PATTERN = re.compile(r'(?:activity[-:_]|share[-:_]|urn:li:activity:|urn:li:share:)?([0-9]{16,21})\b', re.IGNORECASE)
_POST_SLUG_PATTERN = re.compile(r'/posts/([a-zA-Z0-9_\-%]+?)(?:-activity-([0-9]{16,21}))?(?:[/?#]|$)', re.IGNORECASE)
_URN_ACTIVITY_PATTERN = re.compile(r'(?:urn:li:activity:|urn:li:share:)([0-9]{16,21})', re.IGNORECASE)
_BING_U_PATTERN = re.compile(r'[?&]u=([a-zA-Z0-9_\-%=]+)')
_YAHOO_RU_PATTERN = re.compile(r'[Rr][Uu]=([^/&]+)')
_GOOGLE_Q_PATTERN = re.compile(r'[?&]q=([^&]+)')

# Forbidden paths that never contain individual recruiter post updates
FORBIDDEN_PATH_PATTERNS = {
    "/jobs/",
    "/job/",
    "/jobs/view/",
    "/jobs/search/",
    "/company/",
    "/pulse/",
    "/learning/",
    "/school/",
    "/salary/",
    "/directory/",
    "/mynetwork/",
    "/messaging/",
    "/checkpoint/",
    "/authwall/",
    "/login/",
    "/signup/",
    "/legal/",
}

# Known tracking and referral query parameters to strip
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "trackingid", "rcm", "refid", "originalsubdomain", "updateurn",
    "midtoken", "eBP", "trk", "trkinfo", "original_referer", "lipi", "licu"
}


def is_valid_linkedin_post_url(url: str) -> bool:
    """
    Strictly validates that a URL is ONLY a genuine LinkedIn /posts/ URL.
    
    Allowed Examples:
      - https://www.linkedin.com/posts/username_slug-activity-7123456789012345678-abcd
      - https://in.linkedin.com/posts/username_slug-activity-7123456789012345678
      - https://www.linkedin.com/posts/activity-7123456789012345678
      
    Rejected Examples:
      - /jobs/, /jobs/view/, /feed/update/, /company/, /pulse/, shortlinks, login pages, etc.
    """
    if not url or not isinstance(url, str):
        return False

    clean_url = url.split("?")[0].split("#")[0].strip()
    if not clean_url:
        return False

    url_lower = clean_url.lower()

    # 1. Reject explicit forbidden paths
    for pattern in FORBIDDEN_PATH_PATTERNS:
        if pattern in url_lower:
            return False

    # 2. Parse URL structure
    try:
        # Add scheme if missing for parse stability
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"
        parsed = urllib.parse.urlparse(clean_url)
    except Exception:
        return False

    # 3. Hostname validation: Must be linkedin.com or *.linkedin.com
    hostname = parsed.netloc.lower()
    if not hostname:
        return False

    is_linkedin_host = hostname == "linkedin.com" or hostname.endswith(".linkedin.com")
    if not is_linkedin_host:
        return False

    # 4. Path validation: Must start with /posts/
    path = parsed.path.rstrip("/")
    if not path.lower().startswith("/posts/"):
        return False

    # 5. Slug validation: Must contain a valid post identifier after /posts/
    post_slug = path[len("/posts/"):].strip("/")
    if not post_slug or len(post_slug) < 3:
        return False

    return True


def normalize_linkedin_post_url(url: str, canonical_host: str = "www.linkedin.com") -> Optional[str]:
    """
    Normalizes any valid LinkedIn /posts/ URL or activity URL to a clean canonical format.
    
    Operations:
      - Normalizes subdomain (e.g. in.linkedin.com -> www.linkedin.com)
      - Strips all tracking tokens (utm_*, trackingId, rcm, refId, etc.)
      - Strips trailing slashes, fragments, and queries.
      
    Returns:
      Clean canonical URL string, or None if invalid.
    """
    if not url or not isinstance(url, str):
        return None

    unwrapped = unwrap_redirect_url(url) or url

    # Handle /feed/update/urn:li:activity:12345 conversion to /posts/activity-12345
    if "/feed/update/" in unwrapped:
        converted = convert_feed_update_to_post_url(unwrapped)
        if converted:
            unwrapped = converted

    if not is_valid_linkedin_post_url(unwrapped):
        return None

    clean_url = unwrapped.split("?")[0].split("#")[0].strip().rstrip("/")
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = f"https://{clean_url}"

    try:
        parsed = urllib.parse.urlparse(clean_url)
        path = parsed.path.rstrip("/")
        return f"https://{canonical_host}{path}"
    except Exception:
        return None


def extract_activity_id(url_or_urn: str) -> Optional[int]:
    """
    Extracts the 19-digit numeric LinkedIn Snowflake Activity ID from a URL, URN, or post slug.
    
    Examples:
      - https://www.linkedin.com/posts/user_slug-activity-7123456789012345678-abcd -> 7123456789012345678
      - urn:li:activity:7123456789012345678 -> 7123456789012345678
      - activity-7123456789012345678 -> 7123456789012345678
    """
    if not url_or_urn or not isinstance(url_or_urn, str):
        return None

    match = _ACTIVITY_ID_PATTERN.search(url_or_urn)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            pass

    return None


def extract_author_handle(url: str) -> Optional[str]:
    """
    Extracts the author's username or company handle from a LinkedIn /posts/ URL.
    
    Example:
      - https://www.linkedin.com/posts/sahilsingla98_were-hiring-activity-7123456789012345678-abcd
        -> "sahilsingla98"
    """
    if not url or not isinstance(url, str):
        return None

    match = _POST_SLUG_PATTERN.search(url)
    if match:
        slug = match.group(1)
        if "_" in slug:
            handle = slug.split("_")[0].strip()
            if handle and handle.lower() != "activity":
                return handle
        elif not slug.lower().startswith("activity-"):
            return slug.strip()

    return None


def convert_feed_update_to_post_url(url_or_urn: str, host: str = "www.linkedin.com") -> Optional[str]:
    """
    Converts a LinkedIn /feed/update/ URL or URN into a clean /posts/activity-ID URL.
    """
    if not url_or_urn or not isinstance(url_or_urn, str):
        return None

    act_id = extract_activity_id(url_or_urn)
    if act_id:
        return f"https://{host}/posts/activity-{act_id}"

    return None


def unwrap_redirect_url(raw_url: str) -> Optional[str]:
    """
    Unwraps search engine redirect URLs (Yahoo RU=, Bing base64 /ck/, Google /url?q=).
    """
    if not raw_url or not isinstance(raw_url, str):
        return None

    url_str = raw_url.strip()

    # 1. Yahoo RU= redirect
    if "RU=" in url_str or "ru=" in url_str:
        match = _YAHOO_RU_PATTERN.search(url_str)
        if match:
            return urllib.parse.unquote(match.group(1))

    # 2. Bing /ck/ base64 redirect (u=a1...)
    elif "bing.com/ck/" in url_str or "u=a1" in url_str:
        match = _BING_U_PATTERN.search(url_str)
        if match:
            u_val = match.group(1)
            b64_str = u_val[2:] if u_val.startswith("a1") else u_val
            padding = 4 - (len(b64_str) % 4)
            if padding != 4:
                b64_str += "=" * padding
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                if "linkedin.com" in decoded:
                    return decoded
            except Exception:
                pass

    # 3. Google /url?q= redirect
    elif "google.com/url" in url_str and "q=" in url_str:
        match = _GOOGLE_Q_PATTERN.search(url_str)
        if match:
            return urllib.parse.unquote(match.group(1))

    return url_str
