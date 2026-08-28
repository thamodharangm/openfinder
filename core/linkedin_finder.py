import re
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS, DEFAULT_LOCATION, DEFAULT_MAX_RESULTS
from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.time_utils import (
    get_max_age_minutes,
    extract_snowflake_timestamp,
    is_within_window,
    calculate_age,
    FRESHNESS_WINDOWS
)
from core.spam_filter import is_spam_or_bait
from core.cache import SearchCache
from core.post_extractor import LinkedInPostExtractor
from core.linkedin_session import LinkedInSessionSearch


class LinkedInFinder:
    """
    Finds real-time genuine LinkedIn recruiter & founder hiring posts (STRICTLY /posts/ URLs only).
    Completely rejects any corporate job board listings (/jobs/view/) or feed links.
    Enforces exact minute-level publication freshness.
    """

    def __init__(self, skills_taxonomy: Optional[List[str]] = None):
        self.skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        self.cache = SearchCache()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

    @staticmethod
    def is_valid_recruiter_post_url(url: str) -> bool:
        """
        STRICT VALIDATION: Ensures URL is ONLY a genuine LinkedIn /posts/ URL.
        """
        return is_valid_linkedin_post_url(url)

    @staticmethod
    def format_as_markdown_table(posts: List[Dict[str, Any]]) -> str:
        """
        Formats a list of hiring posts into a clean, horizontal Markdown table.
        Columns: # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link
        """
        if not posts:
            return "No posts found matching the criteria."

        headers = ["#", "Company", "Role", "Experience", "Location", "Posted Time", "HR Contact / Email", "Direct Link"]
        alignments = [":---:", "---", "---", ":---:", "---", ":---:", "---", ":---:"]
        
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(alignments) + " |"
        ]

        for idx, p in enumerate(posts, 1):
            company = str(p.get("company") or "Hiring Team").replace("|", "-").strip()
            role = str(p.get("role") or p.get("job_role") or p.get("title") or "Developer").replace("|", "-").strip()
            exp = str(p.get("experience_required") or p.get("experience") or "1–2 Yrs").replace("|", "-").strip()
            loc = str(p.get("location") or "Unspecified / Remote").replace("|", "-").strip()
            posted = str(p.get("posted_time") or p.get("age_text") or "Recently").replace("|", "-").strip()

            emails = p.get("recruiter_emails") or p.get("contact_emails") or []
            phones = p.get("contact_phones") or p.get("contact_numbers") or []
            contacts = []
            if emails:
                contacts.extend([f"`{e}`" for e in emails[:2]])
            if phones:
                contacts.extend([f"`{ph}`" for ph in phones[:1]])
            contact_str = ", ".join(contacts) if contacts else "In Post"

            url = p.get("post_url", "")
            link_str = f"[View Post]({url})" if url else "N/A"

            lines.append(f"| {idx} | **{company}** | {role} | {exp} | {loc} | {posted} | {contact_str} | {link_str} |")

        return "\n".join(lines)

    def clean_linkedin_url(self, raw_url: str) -> Optional[str]:
        """
        Decodes redirect wrappers and normalizes into a clean LinkedIn /posts/ URL.
        Returns None if not a valid /posts/ URL.
        """
        if not raw_url:
            return None

        # Decode Yahoo / Bing redirect wrappers
        decoded_url = raw_url
        if "RU=" in raw_url:
            match = re.search(r'RU=([^/&]+)', raw_url)
            if match:
                decoded_url = urllib.parse.unquote(match.group(1))

        elif "bing.com/ck/" in raw_url or "u=a1" in raw_url:
            try:
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                u_val = parsed_q.get("u", [""])[0]
                if u_val:
                    b64_str = u_val[2:] if u_val.startswith("a1") else u_val
                    padding = 4 - (len(b64_str) % 4)
                    if padding != 4:
                        b64_str += "=" * padding
                    import base64
                    decoded_candidate = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                    if "linkedin.com" in decoded_candidate:
                        decoded_url = decoded_candidate
            except Exception:
                pass

        return normalize_linkedin_post_url(decoded_url)

    def search_recruiter_posts_yahoo(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[str]:
        """
        Searches Yahoo for indexed LinkedIn /posts/ URLs.
        """
        post_urls = []
        try:
            url = "https://search.yahoo.com/search"
            params = {"p": query, "n": max_results * 2}
            with httpx.Client(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a"):
                        raw_href = a.get("href", "")
                        clean_href = self.clean_linkedin_url(raw_href)
                        if clean_href and is_valid_linkedin_post_url(clean_href):
                            if clean_href not in post_urls:
                                post_urls.append(clean_href)
        except Exception:
            pass
        return post_urls

    def build_post_queries(self, keywords: str, location: str = DEFAULT_LOCATION) -> List[str]:
        """
        Builds precision dorking queries targeting ONLY LinkedIn /posts/.
        Completely excludes /feed/update/ or other paths.
        """
        kw = re.sub(r'[/\\()|]', ' ', keywords)
        kw = re.sub(r'\s+', ' ', kw).replace('"', '').strip()
        loc = location.replace('"', '').strip() if location else ""

        return [
            f'site:linkedin.com/posts {kw} hiring {loc}'.strip(),
            f'site:linkedin.com/posts {kw} {loc} hiring'.strip(),
            f'site:linkedin.com/posts {kw} "hiring"'.strip(),
            f'site:linkedin.com/posts {kw} developer hiring'.strip()
        ]

    def search_hiring_posts(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: str = "past-24h",
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Searches ONLY for genuine LinkedIn recruiter/founder /posts/ URLs.
        Enforces exact minute-level freshness window.
        """
        try:
            max_age_minutes = get_max_age_minutes(timeframe)
        except ValueError:
            max_age_minutes = FRESHNESS_WINDOWS["past-24h"]

        cache_key = f"hiring_posts::{keywords}::{location}::{timeframe}::{remote_only}::{max_results}"
        cached = self.cache.get(cache_key)
        if cached is not None and len(cached) > 0:
            return cached

        # 1. First priority: Authenticated LinkedIn Session Search (Posts Tab)
        search_query = f"{keywords} hiring {location}".strip() if location and location.lower() != "india" else f"{keywords} hiring".strip()
        session_posts = LinkedInSessionSearch.search_posts_internal(
            keywords=search_query,
            date_posted=timeframe,
            max_results=max_results,
            skills_taxonomy=self.skills_taxonomy
        )
        if session_posts:
            self.cache.set(cache_key, session_posts)
            return session_posts

        # 2. Fallback: Search Engine Mirror Dorking (Targeting site:linkedin.com/posts only)
        queries = self.build_post_queries(keywords, location)
        found_urls: List[str] = []

        for q in queries:
            urls = self.search_recruiter_posts_yahoo(q, max_results=max_results)
            for u in urls:
                if u not in found_urls and is_valid_linkedin_post_url(u):
                    found_urls.append(u)
            if len(found_urls) >= max_results:
                break

        parsed_posts = []
        for post_url in found_urls:
            if len(parsed_posts) >= max_results:
                break

            # Discovery Pre-Filter: Snowflake timestamp check
            snow_dt = extract_snowflake_timestamp(post_url)
            if snow_dt is not None:
                if not is_within_window(snow_dt, max_age_minutes):
                    continue

            # Verification: Full post extraction & exact age verification
            post_data = LinkedInPostExtractor.extract_from_url(
                url=post_url,
                skills_taxonomy=self.skills_taxonomy,
                max_age_minutes=max_age_minutes
            )
            if post_data and post_data.get("status") == "success":
                parsed_posts.append({
                    "title": post_data.get("job_role", keywords),
                    "company": post_data.get("company", "Hiring Team"),
                    "author": post_data.get("author", "Hiring Recruiter"),
                    "work_mode": "Remote / WFH" if "remote" in post_data.get("full_post_content", "").lower() else "On-Site / Unspecified",
                    "salary_range": "Competitive / Disclosed in post",
                    "experience_required": "1-3+ Years (Estimated)",
                    "published_at": post_data.get("published_at"),
                    "age_minutes": post_data.get("age_minutes"),
                    "age_hours": post_data.get("age_hours"),
                    "posted_time": post_data.get("age_text", "Recently"),
                    "required_skills": post_data.get("detected_skills", []),
                    "contact_emails": post_data.get("recruiter_emails", []),
                    "contact_phones": post_data.get("contact_numbers", []),
                    "application_links": [post_url],
                    "post_url": post_url,
                    "raw_snippet": post_data.get("full_post_content", "")[:350]
                })

        if parsed_posts:
            self.cache.set(cache_key, parsed_posts)

        return parsed_posts

    def search_posts(
        self,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search LinkedIn posts globally by keyword with an exact freshness window.
        Supported windows: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'.
        """
        try:
            max_age_minutes = get_max_age_minutes(date_posted)
        except ValueError:
            max_age_minutes = FRESHNESS_WINDOWS["past-24h"]

        cache_key = f"search_posts::{keywords}::{date_posted}::{max_results}"
        cached = self.cache.get(cache_key)
        if cached is not None and len(cached) > 0:
            return cached

        # 1. First priority: Authenticated LinkedIn Session Search (Posts Tab)
        session_results = LinkedInSessionSearch.search_posts_internal(
            keywords=keywords,
            date_posted=date_posted,
            max_results=max_results,
            skills_taxonomy=self.skills_taxonomy
        )
        if session_results:
            self.cache.set(cache_key, session_results)
            return session_results

        # 2. Fallback: Search Engine Mirror Dorking (site:linkedin.com/posts only)
        clean_kw = re.sub(r'[/\\()|]', ' ', keywords)
        clean_kw = re.sub(r'\s+', ' ', clean_kw).replace('"', '').strip()

        queries = [
            f'site:linkedin.com/posts {clean_kw} hiring',
            f'site:linkedin.com/posts {clean_kw}',
            f'site:linkedin.com/posts {clean_kw} "hiring"'
        ]

        found_urls = []
        for q in queries:
            urls = self.search_recruiter_posts_yahoo(q, max_results=max_results)
            for u in urls:
                if u not in found_urls and is_valid_linkedin_post_url(u):
                    found_urls.append(u)
            if len(found_urls) >= max_results:
                break

        parsed_results = []
        for p_url in found_urls:
            if len(parsed_results) >= max_results:
                break

            # Discovery Pre-Filter: Snowflake timestamp check
            snow_dt = extract_snowflake_timestamp(p_url)
            if snow_dt is not None:
                if not is_within_window(snow_dt, max_age_minutes):
                    continue

            # Verification: Full post extraction
            post_info = LinkedInPostExtractor.extract_from_url(
                url=p_url,
                skills_taxonomy=self.skills_taxonomy,
                max_age_minutes=max_age_minutes
            )
            if post_info and post_info.get("status") == "success":
                parsed_results.append(post_info)

        if parsed_results:
            self.cache.set(cache_key, parsed_results)

        return parsed_results
