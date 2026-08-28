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
from core.post_extractor import LinkedInPostExtractor
from config import COMMON_SKILLS


class LinkedInSessionSearch:
    """
    Directly queries LinkedIn's internal 'Posts' Search Tab (/search/results/content/)
    using an authenticated user session cookie (li_at, JSESSIONID).
    
    Includes global link deduplication and token-optimized compact payloads.
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

    TIME_FILTERS = {
        "past-24h": "%22past-24h%22",
        "past-week": "%22past-week%22",
        "past-month": "%22past-month%22"
    }

    # In-memory deduplication set across requests
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
        date_posted: str = "past-week",
        max_results: int = 10,
        skills_taxonomy: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes internal LinkedIn Posts tab search with authenticated session.
        Guarantees zero duplicate links and returns token-efficient structured items.
        """
        cookies = cls.get_cookies_dict()
        if "li_at" not in cookies:
            return []

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        tf = cls.TIME_FILTERS.get(date_posted.lower(), "%22past-week%22")
        encoded_kw = urllib.parse.quote(keywords)
        url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&datePosted={tf}&sortBy=%22date_posted%22"

        headers = dict(cls.HEADERS)
        if "JSESSIONID" in cookies:
            headers["csrf-token"] = cookies["JSESSIONID"].strip('"')

        collected_urls = []
        try:
            with httpx.Client(headers=headers, cookies=cookies, timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code != 200 or "login" in str(resp.url):
                    return []

                raw_text = resp.text
                
                # Extract activity IDs
                activity_ids = re.findall(r'urn:li:activity:(\d+)', raw_text)
                for aid in activity_ids:
                    if aid not in cls._SEEN_POST_IDS:
                        p_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/"
                        if p_url not in collected_urls:
                            collected_urls.append(p_url)

                # Extract share IDs
                share_ids = re.findall(r'urn:li:share:(\d+)', raw_text)
                for sid in share_ids:
                    if sid not in cls._SEEN_POST_IDS:
                        p_url = f"https://www.linkedin.com/feed/update/urn:li:share:{sid}/"
                        if p_url not in collected_urls:
                            collected_urls.append(p_url)

                # Extract from DOM anchors (excluding corporate /company/ or /jobs/)
                soup = BeautifulSoup(raw_text, "html.parser")
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    if ("/posts/" in href or "/feed/update/" in href) and "/jobs/" not in href and "/company/" not in href:
                        clean = href.split("?")[0].rstrip("/") + "/"
                        # Check ID
                        match_id = re.search(r'(?:activity|share)[:-](\d+)', clean)
                        pid = match_id.group(1) if match_id else clean
                        if pid not in cls._SEEN_POST_IDS and clean not in collected_urls:
                            collected_urls.append(clean)

        except Exception as e:
            print(f"LinkedIn session search error: {e}")
            return []

        results = []
        seen_authors_and_roles = set()
        import time
        import datetime

        for p_url in collected_urls:
            if len(results) >= max_results:
                break

            # STRICT SNOWFLAKE TIMESTAMP FILTER: Drop any post outside target timeframe
            ts = cls.get_post_timestamp(p_url)
            posted_human = "Recently"
            if ts is not None:
                age_sec = time.time() - ts
                dp = date_posted.lower()
                if "24h" in dp or "day" in dp:
                    if age_sec > (86400 * 1.15):
                        continue
                elif "week" in dp or "1w" in dp:
                    if age_sec > (7 * 86400 * 1.1):
                        continue
                elif "month" in dp or "1m" in dp:
                    if age_sec > (31 * 86400 * 1.05):
                        continue
                
                # Human readable age
                dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                if age_sec < 3600:
                    posted_human = f"{int(age_sec // 60)} mins ago"
                elif age_sec < 86400:
                    posted_human = f"{int(age_sec // 3600)} hrs ago"
                else:
                    posted_human = f"{int(age_sec // 86400)} days ago"

            post_data = LinkedInPostExtractor.extract_from_url(
                url=p_url,
                skills_taxonomy=skills_taxonomy
            )
            if not post_data or "error" in post_data:
                continue

            author = post_data.get("author", "").strip()
            role = post_data.get("job_role", "").strip()
            dedup_key = f"{author}::{role}".lower()

            # Skip duplicate author + role reposts
            if dedup_key in seen_authors_and_roles:
                continue
            seen_authors_and_roles.add(dedup_key)

            # Record post as seen globally
            match_id = re.search(r'(\d{15,})', p_url)
            if match_id:
                cls._SEEN_POST_IDS.add(match_id.group(1))

            # Token-Efficient Compact Output (saves ~70% LLM tokens)
            pitch_note = post_data.get("tailored_outreach_pitches", {}).get("linkedin_connection_note_300_chars", "")
            
            compact_item = {
                "role": role,
                "author": author,
                "company": post_data.get("company", "Hiring Team"),
                "location": post_data.get("location", "Unspecified / Remote"),
                "posted_time": posted_human,
                "recruiter_emails": post_data.get("recruiter_emails", []),
                "contact_phones": post_data.get("contact_numbers", []),
                "skills": post_data.get("detected_skills", []),
                "post_url": p_url,
                "connection_pitch": pitch_note
            }
            results.append(compact_item)

        return results

    @classmethod
    def get_post_timestamp(cls, post_url: str) -> Optional[float]:
        """Extracts exact creation timestamp (in seconds) from LinkedIn snowflake activity/share ID."""
        match = re.search(r'(?:activity|share)[:-](\d+)', post_url)
        if match:
            try:
                aid = int(match.group(1))
                return (aid >> 22) / 1000.0
            except Exception:
                pass
        return None
