import os
import re
import urllib.parse
from typing import List, Dict, Any, Optional, Set
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.time_utils import (
    get_max_age_minutes,
    extract_snowflake_timestamp,
    is_within_window,
    calculate_age,
    FRESHNESS_WINDOWS
)
from core.post_extractor import LinkedInPostExtractor
from config import COMMON_SKILLS


class LinkedInSessionSearch:
    """
    Directly queries LinkedIn's internal 'Posts' Search Tab (/search/results/content/)
    using an authenticated user session cookie (li_at, JSESSIONID).
    
    Strictly discovers ONLY genuine /posts/ URLs and enforces exact minute-level freshness.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    # In-memory deduplication set of normalized URLs across requests
    _SEEN_POST_IDS: Set[str] = set()

    @classmethod
    def get_cookies_dict(cls) -> Dict[str, str]:
        """Loads all available LinkedIn session cookies from environment."""
        li_at = os.environ.get("LINKEDIN_LI_AT") or os.environ.get("LI_AT") or ""
        jsessionid = os.environ.get("LINKEDIN_JSESSIONID") or os.environ.get("JSESSIONID") or ""
        
        li_at = li_at.strip().strip('"').strip("'")
        jsessionid = jsessionid.strip().strip('"').strip("'")

        cookies = {}
        if li_at:
            cookies["li_at"] = li_at
        if jsessionid:
            cookies["JSESSIONID"] = f'"{jsessionid}"' if not jsessionid.startswith('"') else jsessionid
        return cookies

    @classmethod
    def search_posts_internal(
        cls,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10,
        skills_taxonomy: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes internal LinkedIn Posts tab search with authenticated session.
        Guarantees ONLY /posts/ URLs and enforces exact minute-level freshness window.
        """
        cookies = cls.get_cookies_dict()
        if "li_at" not in cookies:
            return []

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        
        try:
            max_age_minutes = get_max_age_minutes(date_posted)
        except ValueError:
            max_age_minutes = FRESHNESS_WINDOWS["past-24h"]

        # Map to LinkedIn's native query parameter
        if max_age_minutes <= 1440:  # <= 24h
            tf_param = "%22past-24h%22"
        else:
            tf_param = "%22past-week%22"

        encoded_kw = urllib.parse.quote(keywords)
        url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&datePosted={tf_param}&sortBy=%22date_posted%22"

        headers = dict(cls.HEADERS)
        if "JSESSIONID" in cookies:
            headers["csrf-token"] = cookies["JSESSIONID"].strip('"')

        discovered_post_urls: List[str] = []
        try:
            with httpx.Client(headers=headers, cookies=cookies, timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code != 200 or "login" in str(resp.url):
                    return []

                raw_text = resp.text
                soup = BeautifulSoup(raw_text, "html.parser")

                # Extract strictly from DOM anchors that match /posts/
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    norm_url = normalize_linkedin_post_url(href)
                    if norm_url:
                        if norm_url not in cls._SEEN_POST_IDS and norm_url not in discovered_post_urls:
                            discovered_post_urls.append(norm_url)

                # Also search text for direct https://www.linkedin.com/posts/... patterns
                regex_posts = re.findall(r'https://[a-zA-Z0-9.-]*linkedin\.com/posts/[a-zA-Z0-9_\-%]+', raw_text)
                for p in regex_posts:
                    norm_url = normalize_linkedin_post_url(p)
                    if norm_url and norm_url not in cls._SEEN_POST_IDS and norm_url not in discovered_post_urls:
                        discovered_post_urls.append(norm_url)

        except Exception as e:
            print(f"LinkedIn session search error: {e}")
            return []

        results = []

        for p_url in discovered_post_urls:
            if len(results) >= max_results:
                break

            # 1. DISCOVERY PRE-FILTER: Snowflake timestamp check
            snow_dt = extract_snowflake_timestamp(p_url)
            if snow_dt is not None:
                if not is_within_window(snow_dt, max_age_minutes):
                    continue

            # 2. VERIFICATION FILTER: Full post extraction & authoritative timestamp verification
            post_data = LinkedInPostExtractor.extract_from_url(
                url=p_url,
                skills_taxonomy=skills_taxonomy,
                max_age_minutes=max_age_minutes
            )

            if not post_data or post_data.get("status") != "success":
                continue

            # Record post as seen globally
            cls._SEEN_POST_IDS.add(p_url)

            # Compact structured output
            pitch_note = post_data.get("tailored_outreach_pitches", {}).get("linkedin_connection_note_300_chars", "")
            
            compact_item = {
                "role": post_data.get("job_role", "Software Engineer"),
                "author": post_data.get("author", "Hiring Recruiter"),
                "company": post_data.get("company", "Hiring Team"),
                "location": post_data.get("location", "Unspecified / Remote"),
                "published_at": post_data.get("published_at"),
                "age_minutes": post_data.get("age_minutes"),
                "age_hours": post_data.get("age_hours"),
                "posted_time": post_data.get("age_text", "Recently"),
                "recruiter_emails": post_data.get("recruiter_emails", []),
                "contact_phones": post_data.get("contact_numbers", []),
                "skills": post_data.get("detected_skills", []),
                "post_url": p_url,
                "connection_pitch": pitch_note
            }
            results.append(compact_item)

        return results
