import os
import re
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.post_extractor import LinkedInPostExtractor
from config import COMMON_SKILLS


class LinkedInSessionSearch:
    """
    Directly queries LinkedIn's internal 'Posts' Search Tab (/search/results/content/)
    using an authenticated user session cookie (li_at).
    
    Provides 100% real-time recruiter hiring posts published in the last 24 hours,
    past week, or past month with complete author, email, phone, and skill intelligence.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1"
    }

    TIME_FILTERS = {
        "past-24h": "%22past-24h%22",
        "past-week": "%22past-week%22",
        "past-month": "%22past-month%22"
    }

    @classmethod
    def get_session_cookie(cls) -> Optional[str]:
        """Reads li_at cookie from environment or .env file."""
        return os.environ.get("LINKEDIN_LI_AT") or os.environ.get("LI_AT")

    @classmethod
    def search_posts_internal(
        cls,
        keywords: str,
        date_posted: str = "past-week",
        max_results: int = 10,
        skills_taxonomy: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes internal LinkedIn Posts tab search with authenticated session.
        """
        li_at = cls.get_session_cookie()
        if not li_at:
            return []

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        tf = cls.TIME_FILTERS.get(date_posted.lower(), "%22past-week%22")
        encoded_kw = urllib.parse.quote(keywords)
        url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&datePosted={tf}&sortBy=%22date_posted%22"

        cookies = {"li_at": li_at}
        post_urls = []

        try:
            with httpx.Client(headers=cls.HEADERS, cookies=cookies, timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code != 200 or "login" in str(resp.url):
                    return []

                # Parse post URLs from HTML
                # Look for activity URNs, urn:li:activity:..., /posts/..., /feed/update/...
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # 1. Regex search for post links and activity URNs in page
                raw_text = resp.text
                activity_ids = re.findall(r'urn:li:activity:(\d+)', raw_text)
                for aid in activity_ids:
                    p_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/"
                    if p_url not in post_urls:
                        post_urls.append(p_url)

                # 2. Extract from standard anchors
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    if ("/posts/" in href or "/feed/update/" in href) and "/jobs/" not in href:
                        clean = href.split("?")[0]
                        if clean not in post_urls:
                            post_urls.append(clean)

        except Exception as e:
            print(f"LinkedIn session search error: {e}")
            return []

        results = []
        for p_url in post_urls[:max_results]:
            post_data = LinkedInPostExtractor.extract_from_url(
                url=p_url,
                skills_taxonomy=skills_taxonomy
            )
            if post_data and "error" not in post_data:
                results.append(post_data)

        return results
