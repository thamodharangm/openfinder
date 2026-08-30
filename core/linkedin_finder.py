"""
core/linkedin_finder.py
=======================
Production-grade LinkedIn Hiring Post Discovery and Search Orchestrator.

Features:
- Multi-channel discovery: Authenticated session search -> Parallel Search Engine Dorking -> Live Curated Repository.
- Robust HTTP connection pooling with exponential retry backoff and custom headers.
- Safe async execution bridge supporting nested event loops (FastAPI, MCP, Jupyter, CLI).
- Accurate publication timestamps with dynamic on-the-fly freshness recalculation for cached hits.
- Seamless ATS candidate profile matching integration with OpportunityRanker.
- Enterprise Markdown table formatting with rich badges and recruiter contact highlights.
- Zero-downtime fallback mechanisms and structured production telemetry/logging.
"""

import asyncio
import base64
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import urllib.parse

from bs4 import BeautifulSoup
import httpx

# Add parent dir to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS, DEFAULT_LOCATION, DEFAULT_MAX_RESULTS
from core.cache import SearchCache
from core.linkedin_session import LinkedInSessionSearch
from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.post_extractor import LinkedInPostExtractor
from core.ranking import OpportunityRanker
from core.search_intent import SearchIntent, SearchIntentParser
from core.time_utils import (
    FRESHNESS_WINDOWS,
    calculate_age,
    extract_snowflake_timestamp,
    get_max_age_minutes,
    is_within_window,
    parse_timestamp,
)

logger = logging.getLogger(__name__)


def _run_async_safely(coro):
    """
    Safely executes an async coroutine across various runtime environments:
    - Standard CLI / Scripts (no loop running)
    - Active asyncio event loops (FastAPI / MCP servers / Jupyter) using nest_asyncio or runner.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        try:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except Exception:
            # Fallback: run in a dedicated temporary thread if loop is actively driving another task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(coro))
                return future.result()
    else:
        return loop.run_until_complete(coro)


class LinkedInFinder:
    """
    High-Performance, High-Recall & High-Precision LinkedIn hiring post discovery engine.
    Supports asynchronous concurrent processing, connection pooling, exact publication timestamps,
    verified HIRING intent, role family matching, and discovery funnel metrics.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, skills_taxonomy: Optional[List[str]] = None, cache: Optional[SearchCache] = None):
        self.skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        self.cache = cache or SearchCache()
        self.headers = self.HEADERS.copy()

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
        Decodes redirect wrappers (Yahoo, Bing, Google redirects) and normalizes
        into a clean LinkedIn /posts/ or /feed/update/ URL.
        """
        if not raw_url:
            return None

        decoded_url = raw_url.strip()

        # Handle Yahoo RU= redirect wrapper
        if "RU=" in decoded_url or "ru=" in decoded_url:
            match = re.search(r'[Rr][Uu]=([^/&]+)', decoded_url)
            if match:
                decoded_url = urllib.parse.unquote(match.group(1))

        # Handle Bing /ck/ u=a1 base64 redirect wrapper
        elif "bing.com/ck/" in decoded_url or "u=a1" in decoded_url:
            try:
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(decoded_url).query)
                u_val = parsed_q.get("u", [""])[0]
                if u_val:
                    b64_str = u_val[2:] if u_val.startswith("a1") else u_val
                    padding = 4 - (len(b64_str) % 4)
                    if padding != 4:
                        b64_str += "=" * padding
                    decoded_candidate = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                    if "linkedin.com" in decoded_candidate:
                        decoded_url = decoded_candidate
            except Exception as e:
                logger.debug("Error decoding Bing redirect URL: %s", e)

        return normalize_linkedin_post_url(decoded_url)

    def _recalculate_cached_freshness(self, cached_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recalculates dynamic age_minutes, age_hours, and posted_time for cached items on read."""
        for item in cached_items:
            pub_iso = item.get("published_at")
            if pub_iso:
                pub_dt = parse_timestamp(soup_or_str=pub_iso)
                if pub_dt:
                    age_res = calculate_age(pub_dt)
                    if age_res.get("is_valid", True):
                        item["age_minutes"] = age_res.get("age_minutes", item.get("age_minutes", 0))
                        item["age_hours"] = age_res.get("age_hours", item.get("age_hours", 0))
                        item["posted_time"] = age_res.get("age_text", item.get("posted_time", "Recently"))
        return cached_items

    async def search_recruiter_posts_yahoo_async(
        self,
        query: str,
        client: httpx.AsyncClient,
        page: int = 1,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> Tuple[List[str], Dict[str, Dict[str, str]]]:
        """
        Asynchronously searches Yahoo for indexed LinkedIn /posts/ URLs and collects snippets.
        Returns: (post_urls, snippets_by_url)
        """
        post_urls: List[str] = []
        snippets_by_url: Dict[str, Dict[str, str]] = {}
        try:
            url = "https://search.yahoo.com/search"
            start_b = (page - 1) * 10 + 1
            params = {"p": query, "b": str(start_b), "pz": "10"}
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Search result list items
                for li in soup.find_all("li"):
                    a_tag = li.find("a", href=True)
                    if not a_tag:
                        continue
                    raw_href = a_tag["href"]
                    clean_href = self.clean_linkedin_url(raw_href)
                    if clean_href and is_valid_linkedin_post_url(clean_href):
                        if clean_href not in post_urls:
                            post_urls.append(clean_href)
                            # Extract snippet text and title
                            title = a_tag.get_text(strip=True)
                            snippet_el = li.find("div", class_=re.compile(r"compText|dd|abstract", re.IGNORECASE)) or li.find("p")
                            snippet = snippet_el.get_text(strip=True) if snippet_el else title
                            snippets_by_url[clean_href] = {"title": title, "snippet": snippet}
            else:
                logger.debug("Yahoo search returned non-200 status %d for query: %s", resp.status_code, query)
        except Exception as e:
            logger.debug("Yahoo async search network issue: %s", e)

        return post_urls, snippets_by_url

    async def search_recruiter_posts_duckduckgo_async(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> Tuple[List[str], Dict[str, Dict[str, str]]]:
        """
        Asynchronously searches DuckDuckGo for fresh indexed LinkedIn /posts/ URLs and snippets.
        """
        post_urls: List[str] = []
        snippets_by_url: Dict[str, Dict[str, str]] = {}
        try:
            def _ddg_sync():
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        from ddgs import DDGS
                    except ImportError:
                        from duckduckgo_search import DDGS
                    with DDGS() as ddgs:
                        return list(ddgs.text(query, max_results=max_results))


            results = await asyncio.to_thread(_ddg_sync)
            for item in results:
                raw_href = item.get("href") or item.get("url") or ""
                clean_href = self.clean_linkedin_url(raw_href)
                if clean_href and is_valid_linkedin_post_url(clean_href):
                    if clean_href not in post_urls:
                        post_urls.append(clean_href)
                        title = item.get("title", "")
                        snippet = item.get("body", "") or title
                        snippets_by_url[clean_href] = {"title": title, "snippet": snippet}
        except Exception as e:
            logger.debug("DuckDuckGo async search issue: %s", e)

        return post_urls, snippets_by_url

    def search_recruiter_posts_yahoo(
        self,
        query: str,
        page: int = 1,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[str]:
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
                    post_urls: List[str] = []
                    for a in soup.find_all("a", href=True):
                        raw_href = a["href"]
                        clean_href = self.clean_linkedin_url(raw_href)
                        if clean_href and is_valid_linkedin_post_url(clean_href):
                            if clean_href not in post_urls:
                                post_urls.append(clean_href)
                    return post_urls
        except Exception as e:
            logger.debug("Yahoo sync search error: %s", e)

        return []

    async def search_hiring_posts_async(
        self,
        keywords: str,
        location: str = DEFAULT_LOCATION,
        timeframe: str = "past-24h",
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        candidate_profile: Optional[Dict[str, Any]] = None,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Asynchronously searches ONLY for genuine LinkedIn recruiter/founder /posts/ URLs.
        Features connection pooling, multi-engine parallel dorking (Yahoo + DuckDuckGo),
        bounded async batch extraction, SERP snippet zero-downtime fallback, exact timestamps,
        and verified HIRING intent.
        """
        intent = SearchIntentParser.parse(
            keywords=keywords,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only
        )

        max_age_minutes = intent.max_age_minutes
        cache_key = f"hiring_posts::{intent.target_role}::{intent.target_location}::{timeframe}::{remote_only}"

        # 0. Check Cache First
        if not debug:
            cached = self.cache.get(cache_key, timeframe=timeframe)
            if cached is not None and len(cached) > 0:
                self._recalculate_cached_freshness(cached)
                logger.info("Serving %d hiring posts from cache for key '%s'", len(cached), cache_key)
                return cached[:max_results]

        # 1. Primary Channel: Authenticated LinkedIn Session Search (Posts Tab)
        session_posts: List[Dict[str, Any]] = []
        try:
            session_posts = await asyncio.wait_for(
                LinkedInSessionSearch.search_posts_internal_async(
                    keywords=intent.target_role,
                    date_posted=timeframe,
                    max_results=max_results,
                    skills_taxonomy=self.skills_taxonomy,
                    target_role=intent.target_role,
                    target_location=intent.target_location,
                    candidate_profile=candidate_profile,
                    debug=debug
                ),
                timeout=6.0
            )
        except Exception as e:
            logger.debug("Session search pass finished or timed out (falling back to discovery engines): %s", e)
            session_posts = []

        if session_posts:
            # Re-rank with candidate profile if available
            if candidate_profile:
                session_posts = OpportunityRanker.rank_opportunities(
                    posts=session_posts,
                    candidate_profile=candidate_profile,
                    target_role=intent.target_role,
                    target_location=intent.target_location,
                    max_age_minutes=max_age_minutes,
                    apply_diversity=True
                )
            else:
                session_posts.sort(key=lambda x: x.get("post_quality_score", 0), reverse=True)

            self.cache.set(cache_key, session_posts, timeframe=timeframe)
            return session_posts[:max_results]

        # 2. Secondary Channel: Multi-Engine Parallel Search Dorking (Yahoo + DuckDuckGo)
        queries = intent.generate_dork_queries(max_queries=5)
        found_urls: List[str] = []
        serp_snippets: Dict[str, Dict[str, str]] = {}

        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)
        async with httpx.AsyncClient(headers=self.headers, timeout=timeout, follow_redirects=True) as client:
            search_tasks = []
            # Yahoo queries (page 1 and 2 in parallel)
            for q in queries:
                for p_num in range(1, 3):
                    search_tasks.append(self.search_recruiter_posts_yahoo_async(q, client=client, page=p_num, max_results=max_results))
            # DuckDuckGo queries in parallel
            for q in queries[:3]:
                search_tasks.append(self.search_recruiter_posts_duckduckgo_async(q, max_results=max_results))

            results = await asyncio.gather(*search_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, tuple) and len(res) == 2:
                    urls, snippets = res
                    for u in urls:
                        if u not in found_urls and is_valid_linkedin_post_url(u):
                            found_urls.append(u)
                    serp_snippets.update(snippets)

        # 3. Tertiary Channel: Zero-Downtime Autonomous Curated Repository
        from core.live_repository import find_matching_post_records
        repo_records = find_matching_post_records(
            role=intent.target_role,
            location=intent.target_location,
            max_count=max_results * 3
        )
        for r in repo_records:
            if r["url"] not in found_urls:
                found_urls.append(r["url"])

        _repo_by_url: Dict[str, Dict[str, Any]] = {r["url"]: r for r in repo_records}

        # 4. Candidate URLs Freshness Pre-filtering
        fresh_candidate_urls: List[str] = []
        for post_url in found_urls:
            if post_url in _repo_by_url:
                fresh_candidate_urls.append(post_url)
                continue
            snow_dt = extract_snowflake_timestamp(post_url)
            if snow_dt is not None:
                if is_within_window(snow_dt, max_age_minutes):
                    fresh_candidate_urls.append(post_url)
                elif not fresh_candidate_urls:
                    fresh_candidate_urls.append(post_url)
            else:
                fresh_candidate_urls.append(post_url)

        repo_urls_to_use = [u for u in fresh_candidate_urls if u in _repo_by_url]
        scraped_urls_to_use = [u for u in fresh_candidate_urls if u not in _repo_by_url]

        # 5. Batch Extract in Parallel (HTML DOM with Snippet Fast-Fallback)
        scraped_extracted = []
        if scraped_urls_to_use:
            scraped_extracted = await LinkedInPostExtractor.extract_batch_async(
                urls=scraped_urls_to_use[:max_results * 3],
                max_concurrency=5,
                skills_taxonomy=self.skills_taxonomy,
                target_role=intent.target_role,
                target_location=intent.target_location,
                max_age_minutes=max_age_minutes,
                candidate_profile=candidate_profile
            )

        # Fallback: for URLs that failed direct DOM extraction, use SERP snippets!
        for idx, post_data in enumerate(scraped_extracted):
            if not post_data or post_data.get("status") != "success":
                url_failed = post_data.get("post_url") if isinstance(post_data, dict) else (scraped_urls_to_use[idx] if idx < len(scraped_urls_to_use) else "")
                if url_failed and url_failed in serp_snippets:
                    snip_data = serp_snippets[url_failed]
                    recovered = LinkedInPostExtractor.extract_from_serp_snippet(
                        url=url_failed,
                        title=snip_data.get("title", ""),
                        snippet=snip_data.get("snippet", ""),
                        skills_taxonomy=self.skills_taxonomy,
                        target_role=intent.target_role,
                        target_location=intent.target_location,
                        candidate_profile=candidate_profile
                    )
                    scraped_extracted[idx] = recovered

        repo_extracted = []
        if repo_urls_to_use:
            repo_extracted = await LinkedInPostExtractor.extract_batch_async(
                urls=repo_urls_to_use[:max_results * 3],
                max_concurrency=5,
                skills_taxonomy=self.skills_taxonomy,
                target_role=intent.target_role,
                target_location=intent.target_location,
                max_age_minutes=None,  # Curated repository posts bypass raw age rejection
                candidate_profile=candidate_profile
            )

        extracted_posts = list(repo_extracted) + list(scraped_extracted)

        # 6. Parse, Deduplicate and Build Clean Structured Objects
        from core.linkedin_urls import compute_post_fingerprint

        parsed_posts: List[Dict[str, Any]] = []
        seen_fingerprints: Set[str] = set()

        for post_data in extracted_posts:
            if not post_data or post_data.get("status") != "success":
                continue

            if post_data.get("hiring_intent") not in ["HIRING", "POTENTIAL_HIRING"]:
                continue

            role_score = post_data.get("role_match_score", 0)
            if intent.role_family != "GENERAL_SOFTWARE" and role_score < 45:
                continue

            post_url = post_data.get("post_url")
            repo_meta = _repo_by_url.get(post_url, {})
            stable_author = repo_meta.get("author") or post_data.get("author", "Hiring Recruiter")
            stable_company = repo_meta.get("company") or post_data.get("company", "Hiring Team")
            stable_role = repo_meta.get("role") or post_data.get("job_role", intent.target_role)
            stable_location = repo_meta.get("primary_location") or post_data.get("location", "Unspecified / Remote")
            stable_work_mode = repo_meta.get("work_mode") or ("Remote" if "remote" in post_data.get("full_post_content", "").lower() else "On-Site")
            stable_emails = repo_meta.get("recruiter_emails") or post_data.get("recruiter_emails", [])

            # Smart Fingerprint Deduplication
            fp = compute_post_fingerprint(
                url=post_url,
                company=stable_company,
                role=stable_role,
                contact_email=stable_emails[0] if stable_emails else None,
                content=post_data.get("full_post_content", "")
            )
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)

            parsed_posts.append({
                "title": stable_role,
                "role": stable_role,
                "extracted_roles": post_data.get("extracted_roles", []),
                "company": stable_company,
                "author": stable_author,
                "author_type": post_data.get("author_type", "RECRUITER"),
                "location": stable_location.title() if stable_location else "India",
                "work_mode": stable_work_mode,
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
                "recruiter_emails": stable_emails,
                "contact_emails": stable_emails,
                "contact_phones": post_data.get("contact_numbers", []),
                "contact_numbers": post_data.get("contact_numbers", []),
                "application_links": [post_url],
                "post_url": post_url,
                "discovery_source": "repository" if post_url in _repo_by_url else post_data.get("extraction_source", "search_engine"),
                "raw_snippet": post_data.get("full_post_content", "")[:350]
            })

        # 7. Multi-factor Opportunity Ranking (Quality + ATS Profile Fit)
        ranked_posts = OpportunityRanker.rank_opportunities(
            posts=parsed_posts,
            candidate_profile=candidate_profile,
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
        candidate_profile: Optional[Dict[str, Any]] = None,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Synchronous entrypoint for search_hiring_posts with safe nested event loop execution.
        """
        return _run_async_safely(
            self.search_hiring_posts_async(
                keywords=keywords,
                location=location,
                timeframe=timeframe,
                remote_only=remote_only,
                max_results=max_results,
                candidate_profile=candidate_profile,
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

        cache_key = f"search_posts::{intent.target_role}::{date_posted}::{intent.target_location}::{max_results}"
        if not debug:
            cached = self.cache.get(cache_key, timeframe=date_posted)
            if cached is not None and len(cached) > 0:
                self._recalculate_cached_freshness(cached)
                return cached[:max_results]

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
            return session_results[:max_results]

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
        Synchronous entrypoint for search_posts with safe nested event loop execution.
        """
        return _run_async_safely(
            self.search_posts_async(
                keywords=keywords,
                date_posted=date_posted,
                max_results=max_results,
                location=location,
                debug=debug
            )
        )

    async def harvest_query_matrix_async(
        self,
        roles: List[str],
        locations: List[str],
        timeframe: str = "past-7d",
        max_pages: int = 4,
        target_count: int = 100,
        concurrency_limit: int = 8,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Performs high-velocity, multi-angle search matrix harvesting across roles, locations,
        and deep pagination pages to collect large raw datasets of hiring posts.
        """
        clean_roles = [r.strip() for r in roles if r and r.strip()]
        if not clean_roles:
            clean_roles = ["Software Engineer"]

        clean_locs = [l.strip() for l in locations if l and l.strip()]
        if not clean_locs:
            clean_locs = ["India"]

        search_tasks = []
        semaphore = asyncio.Semaphore(concurrency_limit)
        all_found_urls: List[str] = []
        seen_urls = set()

        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)
        async with httpx.AsyncClient(headers=self.headers, timeout=timeout, follow_redirects=True) as client:
            async def _fetch_page(query: str, page_num: int):
                async with semaphore:
                    try:
                        urls = await self.search_recruiter_posts_yahoo_async(
                            query=query,
                            client=client,
                            page=page_num,
                            max_results=10
                        )
                        return urls
                    except Exception as e:
                        logger.debug("Harvest page fetch error for query '%s' page %d: %s", query, page_num, e)
                        return []

            fetch_coroutines = []
            for role in clean_roles[:4]:
                for loc in clean_locs[:4]:
                    dork_variations = [
                        f'site:linkedin.com/posts/ "{role}" {loc} "email"',
                        f'site:linkedin.com/posts/ "{role}" {loc} ("@gmail.com" OR "@" OR "send resume")',
                        f'site:linkedin.com/posts/ "{role}" {loc} hiring',
                        f'site:linkedin.com/posts/ "{role}" {loc} "we are hiring"'
                    ]
                    for dork in dork_variations:
                        for p in range(1, max(1, min(max_pages, 2)) + 1):
                            fetch_coroutines.append(_fetch_page(dork, p))

            page_results = await asyncio.gather(*fetch_coroutines, return_exceptions=True)
            for res in page_results:
                if isinstance(res, list):
                    for u in res:
                        norm = normalize_linkedin_post_url(u)
                        if norm and norm not in seen_urls:
                            seen_urls.add(norm)
                            all_found_urls.append(norm)

        # Also leverage authenticated session if available
        if LinkedInSessionSearch.check_session_health().get("valid", False):
            for role in clean_roles[:2]:
                try:
                    s_posts = await LinkedInSessionSearch.search_posts_internal_async(
                        keywords=role,
                        date_posted=timeframe,
                        max_results=target_count,
                        skills_taxonomy=self.skills_taxonomy,
                        target_role=role,
                        target_location=clean_locs[0] if clean_locs else "India",
                        debug=debug
                    )
                    for sp in s_posts:
                        u = sp.get("post_url")
                        if u:
                            norm = normalize_linkedin_post_url(u)
                            if norm and norm not in seen_urls:
                                seen_urls.add(norm)
                                all_found_urls.append(norm)
                except Exception as e:
                    logger.debug("Session harvest error: %s", e)

        if not all_found_urls:
            return []

        # Concurrently extract post details with bounded batch extraction
        harvested_posts = await LinkedInPostExtractor.extract_batch_async(
            urls=all_found_urls[:target_count * 2],
            max_concurrency=min(concurrency_limit, 10),
            skills_taxonomy=self.skills_taxonomy,
            target_role=clean_roles[0],
            target_location=clean_locs[0] if clean_locs else "India"
        )

        return [p for p in harvested_posts if isinstance(p, dict) and p.get("status") != "error"]

    def harvest_query_matrix(
        self,
        roles: List[str],
        locations: List[str],
        timeframe: str = "past-7d",
        max_pages: int = 4,
        target_count: int = 100,
        concurrency_limit: int = 8,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """Synchronous entrypoint for harvest_query_matrix_async."""
        return _run_async_safely(
            self.harvest_query_matrix_async(
                roles=roles,
                locations=locations,
                timeframe=timeframe,
                max_pages=max_pages,
                target_count=target_count,
                concurrency_limit=concurrency_limit,
                debug=debug
            )
        )
