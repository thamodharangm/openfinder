import re
import urllib.parse
from typing import Optional


FORBIDDEN_PATH_PATTERNS = [
    "/jobs/",
    "/job/",
    "/jobs/view/",
    "jobs/view",
    "/feed/update/",
    "/feed/",
    "/company/",
    "/pulse/",
    "/learning/",
    "/school/",
    "/salary/",
    "/directory/",
    "lnkd.in/p/",
]


def is_valid_linkedin_post_url(url: str) -> bool:
    """
    Strictly validates that a URL is ONLY a genuine LinkedIn /posts/ URL.
    
    Allowed:
      https://www.linkedin.com/posts/username_slug-activity-12345...
      https://in.linkedin.com/posts/username_slug...
      
    Rejected:
      /jobs/, /jobs/view/, /feed/update/, /company/, /pulse/, /activity-, shortlinks, etc.
    """
    if not url or not isinstance(url, str):
        return False

    # 1. Strip query params, fragments, and whitespace
    clean_url = url.split("?")[0].split("#")[0].strip()
    if not clean_url:
        return False

    url_lower = clean_url.lower()

    # 2. Check forbidden patterns first
    if any(pattern in url_lower for pattern in FORBIDDEN_PATH_PATTERNS):
        return False

    # 3. Parse URL structure
    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception:
        return False

    # 4. Hostname validation: Must be linkedin.com or *.linkedin.com
    hostname = parsed.netloc.lower()
    if not hostname:
        return False

    is_linkedin_host = hostname == "linkedin.com" or hostname.endswith(".linkedin.com")
    if not is_linkedin_host:
        return False

    # 5. Path validation: Must start with /posts/
    path = parsed.path.rstrip("/")
    if not path.lower().startswith("/posts/"):
        return False

    # 6. Slug validation: Must contain a non-empty slug after /posts/
    post_slug = path[len("/posts/"):].strip("/")
    if not post_slug:
        return False

    return True


def normalize_linkedin_post_url(url: str) -> Optional[str]:
    """
    Normalizes a LinkedIn /posts/ URL to a clean canonical format.
    
    If the supplied URL is NOT a valid /posts/ URL, returns None.
    Does NOT convert /feed/update/ or other formats.
    """
    if not is_valid_linkedin_post_url(url):
        return None

    clean_url = url.split("?")[0].split("#")[0].strip().rstrip("/")
    parsed = urllib.parse.urlparse(clean_url)
    
    # Standardize scheme and domain
    scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
    hostname = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    
    return f"{scheme}://{hostname}{path}"
