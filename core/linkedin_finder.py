import re
import asyncio
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
from core.search_intent import SearchIntentParser, SearchIntent
from core.spam_filter import is_spam_or_bait
from core.cache import SearchCache
from core.post_extractor import LinkedInPostExtractor
from core.linkedin_session import LinkedInSessionSearch


class LinkedInFinder:
    """
    High-Performance, High-Recall & High-Precision LinkedIn hiring post discovery engine.
    Supports asynchronous concurrent processing, connection pooling, exact publication timestamps,
    verified HIRING intent, role family matching, and discovery funnel metrics.
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
        """STRICT VALIDATION: Ensures URL is ONLY a genuine LinkedIn /posts/ URL."""
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
        """
        if not raw_url:
            return None

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

    async def search_recruiter_posts_yahoo_async(
        self,
        query: str,
        client: httpx.AsyncClient,
        page: int = 1,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[str]:
        """
        Asynchronously searches Yahoo for indexed LinkedIn /posts/ URLs.
        """
        post_urls = []
        try:
            url = "https://search.yahoo.com/search"
            start_b = (page - 1) * 10 + 1
            params = {"p": query, "b": str(start_b), "pz": "10"}
            resp = await client.get(url, params=params)
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

    def search_recruiter_posts_yahoo(self, query: str, page: int = 1, max_results: int = DEFAULT_MAX_RESULTS) -> List[str]:
        """
        Synchronous helper for search_recruiter_posts_yahoo.
        """
        try:
            url = "https://search.yahoo.com/search"
            start_b = (page - 1) * 10 + 1
            params = {"p": query, "b": str(start_b), "pz": "10"}
            with httpx.Client(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    post_urls = []
                    for a in soup.find_all("a"):
                        raw_href = a.get("href", "")
                        clean_href = self.clean_linkedin_url(raw_href)
                        if clean_href and is_valid_linkedin_post_url(clean_href):
                            if clean_href not in post_urls:
                                post_urls.append(clean_href)
                    return post_urls
        except Exception:
            pass
        return []

    async def search_hiring_posts_async(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: str = "past-24h",
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Asynchronously searches ONLY for genuine LinkedIn recruiter/founder /posts/ URLs.
        Features connection pooling, multi-query expansion, bounded async batch extraction,
        exact timestamps, and verified HIRING intent.
        """
        intent = SearchIntentParser.parse(
            keywords=keywords,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only
        )

        max_age_minutes = intent.max_age_minutes
        cache_key = f"hiring_posts::{intent.target_role}::{intent.target_location}::{timeframe}::{remote_only}::{max_results}"
        cached = self.cache.get(cache_key, timeframe=timeframe)
        if cached is not None and len(cached) > 0:
            return cached

        # 1. Primary: Authenticated LinkedIn Session Search (Posts Tab)
        session_posts = await LinkedInSessionSearch.search_posts_internal_async(
            keywords=intent.target_role,
            date_posted=timeframe,
            max_results=max_results,
            skills_taxonomy=self.skills_taxonomy,
            target_role=intent.target_role,
            target_location=intent.target_location,
            debug=debug
        )
        if session_posts:
            session_posts.sort(key=lambda x: x.get("post_quality_score", 0), reverse=True)
            self.cache.set(cache_key, session_posts, timeframe=timeframe)
            return session_posts

        # 2. Fallback: Search Engine Mirror Dorking with async extraction
        queries = intent.generate_dork_queries(max_queries=5)
        found_urls: List[str] = []

        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)
        async with httpx.AsyncClient(headers=self.headers, timeout=timeout, follow_redirects=True) as client:
            for q in queries:
                for p_num in range(1, 3):
                    urls = await self.search_recruiter_posts_yahoo_async(q, client=client, page=p_num, max_results=max_results)
                    for u in urls:
                        if u not in found_urls and is_valid_linkedin_post_url(u):
                            found_urls.append(u)
                    if len(found_urls) >= max_results * 4:
                        break

        # Snowflake pre-filter
        fresh_candidate_urls = []
        for post_url in found_urls:
            snow_dt = extract_snowflake_timestamp(post_url)
            if snow_dt is not None:
                if is_within_window(snow_dt, max_age_minutes):
                    fresh_candidate_urls.append(post_url)
            else:
                fresh_candidate_urls.append(post_url)

        # Async batch extraction
        extracted_posts = await LinkedInPostExtractor.extract_batch_async(
            urls=fresh_candidate_urls[:max_results * 3],
            max_concurrency=5,
            skills_taxonomy=self.skills_taxonomy,
            target_role=intent.target_role,
            target_location=intent.target_location,
            max_age_minutes=max_age_minutes
        )

        parsed_posts = []
        for post_data in extracted_posts:
            if not post_data or post_data.get("status") != "success":
                continue

            if post_data.get("hiring_intent") != "HIRING":
                continue

            role_score = post_data.get("role_match_score", 0)
            if intent.role_family != "GENERAL_SOFTWARE" and role_score < 50:
                continue

            post_url = post_data.get("post_url")
            parsed_posts.append({
                "title": post_data.get("job_role", intent.target_role),
                "role": post_data.get("job_role", intent.target_role),
                "extracted_roles": post_data.get("extracted_roles", []),
                "company": post_data.get("company", "Hiring Team"),
                "author": post_data.get("author", "Hiring Recruiter"),
                "author_type": post_data.get("author_type", "RECRUITER"),
                "location": post_data.get("location", "Unspecified / Remote"),
                "work_mode": "Remote / WFH" if "remote" in post_data.get("full_post_content", "").lower() else "On-Site / Unspecified",
                "salary_range": "Competitive / Disclosed in post",
                "experience_required": post_data.get("experience_fit", "1–2 Yrs"),
                "published_at": post_data.get("published_at"),
                "age_minutes": post_data.get("age_minutes"),
                "age_hours": post_data.get("age_hours"),
                "posted_time": post_data.get("age_text", "Recently"),
                "hiring_intent": post_data.get("hiring_intent", "HIRING"),
                "hiring_confidence": post_data.get("hiring_confidence", 0.9),
                "role_match_score": role_score,
                "role_match_reason": post_data.get("role_match_reason", ""),
                "location_match_score": post_data.get("location_match_score", 100),
                "experience_match_score": post_data.get("experience_match_score", 75),
                "post_quality_score": post_data.get("post_quality_score", 85),
                "is_spam": False,
                "required_skills": post_data.get("detected_skills", []),
                "recruiter_emails": post_data.get("recruiter_emails", []),
                "contact_emails": post_data.get("recruiter_emails", []),
                "contact_phones": post_data.get("contact_numbers", []),
                "contact_numbers": post_data.get("contact_numbers", []),
                "application_links": [post_url],
                "post_url": post_url,
                "discovery_source": "search_engine",
                "raw_snippet": post_data.get("full_post_content", "")[:350]
            })

        from core.ranking import OpportunityRanker
        ranked_posts = OpportunityRanker.rank_opportunities(
            posts=parsed_posts,
            target_role=intent.target_role,
            target_location=intent.target_location,
            max_age_minutes=max_age_minutes,
            apply_diversity=True
        )
        final_posts = ranked_posts[:max_results]

        if final_posts:
            self.cache.set(cache_key, final_posts, timeframe=timeframe)

        return final_posts

    def search_hiring_posts(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: str = "past-24h",
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Synchronous entrypoint for search_hiring_posts.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    self.search_hiring_posts_async(
                        keywords=keywords,
                        location=location,
                        timeframe=timeframe,
                        remote_only=remote_only,
                        max_results=max_results,
                        debug=debug
                    )
                )
            else:
                return loop.run_until_complete(
                    self.search_hiring_posts_async(
                        keywords=keywords,
                        location=location,
                        timeframe=timeframe,
                        remote_only=remote_only,
                        max_results=max_results,
                        debug=debug
                    )
                )
        except Exception:
            return asyncio.run(
                self.search_hiring_posts_async(
                    keywords=keywords,
                    location=location,
                    timeframe=timeframe,
                    remote_only=remote_only,
                    max_results=max_results,
                    debug=debug
                )
            )

    async def search_posts_async(
        self,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10,
        location: Optional[str] = None,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Asynchronously searches LinkedIn posts globally.
        """
        intent = SearchIntentParser.parse(
            keywords=keywords,
            location=location or "India",
            timeframe=date_posted
        )

        max_age_minutes = intent.max_age_minutes
        cache_key = f"search_posts::{intent.target_role}::{date_posted}::{intent.target_location}::{max_results}"
        cached = self.cache.get(cache_key, timeframe=date_posted)
        if cached is not None and len(cached) > 0:
            return cached

        session_results = await LinkedInSessionSearch.search_posts_internal_async(
            keywords=intent.target_role,
            date_posted=date_posted,
            max_results=max_results,
            skills_taxonomy=self.skills_taxonomy,
            target_role=intent.target_role,
            target_location=intent.target_location,
            debug=debug
        )
        if session_results:
            session_results.sort(key=lambda x: x.get("post_quality_score", 0), reverse=True)
            self.cache.set(cache_key, session_results, timeframe=date_posted)
            return session_results

        return await self.search_hiring_posts_async(
            keywords=keywords,
            location=location or "India",
            timeframe=date_posted,
            max_results=max_results,
            debug=debug
        )

    def search_posts(
        self,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10,
        location: Optional[str] = None,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Synchronous entrypoint for search_posts.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    self.search_posts_async(
                        keywords=keywords,
                        date_posted=date_posted,
                        max_results=max_results,
                        location=location,
                        debug=debug
                    )
                )
            else:
                return loop.run_until_complete(
                    self.search_posts_async(
                        keywords=keywords,
                        date_posted=date_posted,
                        max_results=max_results,
                        location=location,
                        debug=debug
                    )
                )
        except Exception:
            return asyncio.run(
                self.search_posts_async(
                    keywords=keywords,
                    date_posted=date_posted,
                    max_results=max_results,
                    location=location,
                    debug=debug
                )
            )
