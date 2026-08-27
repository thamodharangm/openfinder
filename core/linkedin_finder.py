import re
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS, DEFAULT_LOCATION, DEFAULT_TIMEFRAME, DEFAULT_MAX_RESULTS
from core.spam_filter import is_spam_or_bait
from core.cache import SearchCache
from core.post_extractor import LinkedInPostExtractor
from core.linkedin_session import LinkedInSessionSearch


class LinkedInFinder:
    """
    Finds real-time genuine LinkedIn recruiter & founder hiring posts (strictly /posts/ & /feed/update/).
    Completely rejects and filters out any generic corporate job board listings (/jobs/view/).
    Extracts author, HR contact emails, phone numbers, and required tech stack.
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
        STRICT VALIDATION: Ensures URL is ONLY a personal recruiter/founder post or activity feed update.
        Completely rejects any /jobs/ or /jobs/view/ links.
        """
        if not url:
            return False
        url_lower = url.lower()

        # Reject non-LinkedIn
        if "linkedin.com" not in url_lower and "lnkd.in" not in url_lower:
            return False

        # Strictly BAN any job aggregator / corporate board links
        forbidden_patterns = ['/jobs/', '/job/', '/directory/', '/salary/', '/school/', '/learning/', '/pulse/', '/company/']
        if any(forbidden in url_lower for forbidden in forbidden_patterns):
            return False

        # Strictly require genuine personal/company social post paths
        return bool('/posts/' in url_lower or '/feed/update/' in url_lower or 'activity-' in url_lower or 'lnkd.in/p/' in url_lower)

    def clean_linkedin_url(self, raw_url: str) -> str:
        """
        Decodes redirect wrappers into clean LinkedIn post URLs.
        """
        if not raw_url:
            return ""

        if "RU=" in raw_url:
            match = re.search(r'RU=([^/&]+)', raw_url)
            if match:
                return urllib.parse.unquote(match.group(1))

        if "bing.com/ck/" in raw_url or "u=a1" in raw_url:
            try:
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                u_val = parsed_q.get("u", [""])[0]
                if u_val:
                    b64_str = u_val[2:] if u_val.startswith("a1") else u_val
                    padding = 4 - (len(b64_str) % 4)
                    if padding != 4:
                        b64_str += "=" * padding
                    import base64
                    decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                    if "linkedin.com" in decoded:
                        return decoded
            except Exception:
                pass

        return raw_url.split("?")[0]

    def search_recruiter_posts_yahoo(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[str]:
        """
        Searches Yahoo for indexed LinkedIn recruiter posts.
        """
        post_urls = []
        try:
            url = "https://search.yahoo.com/search"
            params = {"p": query, "n": max_results * 2, "age": "1w", "bt": "1w"}
            with httpx.Client(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a"):
                        raw_href = a.get("href", "")
                        clean_href = self.clean_linkedin_url(raw_href)
                        if self.is_valid_recruiter_post_url(clean_href):
                            if clean_href not in post_urls:
                                post_urls.append(clean_href)
        except Exception:
            pass
        return post_urls

    def build_post_queries(self, keywords: str, location: str = DEFAULT_LOCATION) -> List[str]:
        """
        Builds precision dorking queries targeting LinkedIn Posts only.
        """
        kw = re.sub(r'[/\\()|]', ' ', keywords)
        kw = re.sub(r'\s+', ' ', kw).replace('"', '').strip()
        loc = location.replace('"', '').strip() if location else ""

        return [
            f'site:linkedin.com/posts {kw} hiring {loc}'.strip(),
            f'site:linkedin.com/feed/update {kw} hiring {loc}'.strip(),
            f'site:linkedin.com/posts {kw} {loc} hiring'.strip(),
            f'site:linkedin.com/posts {kw} "hiring"'.strip(),
            f'site:linkedin.com/feed/update {kw} hiring'.strip()
        ]

    def search_hiring_posts(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: Optional[str] = DEFAULT_TIMEFRAME,
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Searches ONLY for genuine LinkedIn recruiter/founder posts.
        Fetches and extracts full post text, author, HR emails, phone numbers, and required skills.
        """
        cache_key = f"recruiter_posts::{keywords}::{location}::{remote_only}::{max_results}"
        cached = self.cache.get(cache_key)
        if cached is not None and len(cached) > 0:
            return cached

        queries = self.build_post_queries(keywords, location)
        found_urls = []

        for q in queries:
            urls = self.search_recruiter_posts_yahoo(q, max_results=max_results)
            for u in urls:
                if u not in found_urls and self.is_valid_recruiter_post_url(u):
                    found_urls.append(u)
            if len(found_urls) >= max_results:
                break

        parsed_posts = []
        for post_url in found_urls[:max_results]:
            post_data = LinkedInPostExtractor.extract_from_url(
                url=post_url,
                skills_taxonomy=self.skills_taxonomy
            )
            if post_data and "error" not in post_data:
                # Structure output format
                parsed_posts.append({
                    "title": post_data.get("job_role", keywords),
                    "company": post_data.get("author", "Hiring Recruiter"),
                    "author": post_data.get("author", "Hiring Recruiter"),
                    "work_mode": "Remote / WFH" if "remote" in post_data.get("full_post_content", "").lower() else "On-Site / Unspecified",
                    "salary_range": "Competitive / Disclosed in post",
                    "experience_required": "1-3+ Years (Estimated)",
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
        date_posted: Optional[str] = "past-week",
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search LinkedIn posts/content globally by keyword (the 'Posts' tab) 
        with an optional recency filter (past-24h, past-week, past-month).
        
        Extracts full post text, author, hiring company, HR contact emails,
        phone numbers, required skills, and tailored recruiter pitches.
        """
        # Map date_posted to time constraint
        age_param = "1w"
        if date_posted:
            dp_lower = date_posted.lower()
            if "24h" in dp_lower or "day" in dp_lower:
                age_param = "1d"
            elif "month" in dp_lower:
                age_param = "1m"
            elif "week" in dp_lower:
                age_param = "1w"

        cache_key = f"search_posts::{keywords}::{date_posted}::{max_results}"
        cached = self.cache.get(cache_key)
        if cached is not None and len(cached) > 0:
            return cached

        # 1. First priority: Authenticated LinkedIn Session Search (Posts Tab)
        session_results = LinkedInSessionSearch.search_posts_internal(
            keywords=keywords,
            date_posted=date_posted or "past-week",
            max_results=max_results,
            skills_taxonomy=self.skills_taxonomy
        )
        if session_results:
            self.cache.set(cache_key, session_results)
            return session_results

        # 2. Fallback: Search Engine Mirror Dorking
        clean_kw = re.sub(r'[/\\()|]', ' ', keywords)
        clean_kw = re.sub(r'\s+', ' ', clean_kw).replace('"', '').strip()

        queries = [
            f'site:linkedin.com/posts {clean_kw}',
            f'site:linkedin.com/feed/update {clean_kw}',
            f'site:linkedin.com/posts {clean_kw} "hiring"',
            f'site:linkedin.com {clean_kw} inurl:posts'
        ]

        found_urls = []
        for q in queries:
            try:
                url = "https://search.yahoo.com/search"
                params = {"p": q, "n": max_results * 2, "age": age_param, "bt": age_param}
                with httpx.Client(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.find_all("a"):
                            raw_href = a.get("href", "")
                            clean_href = self.clean_linkedin_url(raw_href)
                            if self.is_valid_recruiter_post_url(clean_href):
                                if clean_href not in found_urls:
                                    found_urls.append(clean_href)
            except Exception:
                pass
            if len(found_urls) >= max_results:
                break

        parsed_results = []
        for p_url in found_urls[:max_results]:
            post_info = LinkedInPostExtractor.extract_from_url(
                url=p_url,
                skills_taxonomy=self.skills_taxonomy
            )
            if post_info and "error" not in post_info:
                parsed_results.append(post_info)

        if parsed_results:
            self.cache.set(cache_key, parsed_results)

        return parsed_results
