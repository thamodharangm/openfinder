import os
import re
import time
import asyncio
import urllib.parse
from typing import List, Dict, Any, Optional, Set, Tuple
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
from core.search_intent import SearchIntentParser, SearchIntent
from core.post_extractor import LinkedInPostExtractor
from config import COMMON_SKILLS


class LinkedInSessionSearch:
    """
    High-Performance Asynchronous LinkedIn Content Search & Discovery Engine.
    Queries LinkedIn's internal 'Posts' Search Tab (/search/results/content/)
    with connection pooling, multi-query expansion, bounded async batch extraction,
    and granular timing metrics.
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

    TIMEOUT_CONFIG = httpx.Timeout(connect=3.0, read=4.0, write=3.0, pool=4.0)
    MAX_CONCURRENCY = 5

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
    def check_session_health(cls) -> Dict[str, Any]:
        """
        Validates whether session credentials are present and operational.
        """
        cookies = cls.get_cookies_dict()
        if "li_at" not in cookies or not cookies["li_at"]:
            return {
                "status": "unavailable",
                "valid": False,
                "reason": "Missing LINKEDIN_LI_AT session cookie in environment"
            }
        
        if len(cookies["li_at"]) < 20:
            return {
                "status": "invalid_credentials",
                "valid": False,
                "reason": "LINKEDIN_LI_AT format is invalid or truncated"
            }

        return {
            "status": "authenticated",
            "valid": True,
            "has_csrf": "JSESSIONID" in cookies
        }

    @classmethod
    async def search_posts_internal_async(
        cls,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10,
        skills_taxonomy: Optional[List[str]] = None,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_discovery_candidates: int = 40,
        max_concurrency: int = MAX_CONCURRENCY,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Asynchronously searches LinkedIn posts with connection pooling, multi-query expansion,
        bounded concurrent extraction, and timing metrics.
        """
        t_start = time.perf_counter()

        session_health = cls.check_session_health()
        if not session_health["valid"]:
            return []

        cookies = cls.get_cookies_dict()
        skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        
        intent = SearchIntentParser.parse(
            keywords=target_role or keywords,
            location=target_location or "India",
            timeframe=date_posted
        )

        max_age_minutes = intent.max_age_minutes

        if max_age_minutes <= 60:        # past-1h
            max_queries = 2
            max_pages = 2
        elif max_age_minutes <= 240:     # past-4h
            max_queries = 3
            max_pages = 2
        elif max_age_minutes <= 1440:    # past-24h
            max_queries = 4
            max_pages = 3
        else:                            # past-7d
            max_queries = 5
            max_pages = 4

        tf_param = "%22past-24h%22" if max_age_minutes <= 1440 else "%22past-week%22"

        headers = dict(cls.HEADERS)
        if "JSESSIONID" in cookies:
            headers["csrf-token"] = cookies["JSESSIONID"].strip('"')

        metrics = {
            "queries_attempted": 0,
            "pages_fetched": 0,
            "raw_candidates": 0,
            "unique_candidates": 0,
            "fresh_candidates": 0,
            "role_candidates": 0,
            "hiring_candidates": 0,
            "deep_extracted": 0,
            "final_results": 0,
            "timing_ms": {}
        }

        query_variants = intent.generate_diverse_session_queries(max_queries=max_queries)
        candidate_pool: List[Tuple[str, str, int]] = []
        discovered_urls_set: Set[str] = set()

        t_disc_start = time.perf_counter()

        # 1. Async Discovery Phase
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
        try:
            async with httpx.AsyncClient(headers=headers, cookies=cookies, timeout=cls.TIMEOUT_CONFIG, limits=limits, follow_redirects=True) as client:
                for q_str in query_variants:
                    metrics["queries_attempted"] += 1
                    encoded_kw = urllib.parse.quote(q_str)

                    for page_num in range(1, max_pages + 1):
                        metrics["pages_fetched"] += 1
                        page_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&datePosted={tf_param}&sortBy=%22date_posted%22&page={page_num}"
                        
                        resp = await client.get(page_url)
                        if resp.status_code != 200 or "login" in str(resp.url):
                            break

                        raw_text = resp.text
                        soup = BeautifulSoup(raw_text, "html.parser")

                        page_found_urls = []
                        for a in soup.find_all("a"):
                            href = a.get("href", "")
                            norm_url = normalize_linkedin_post_url(href)
                            if norm_url and norm_url not in page_found_urls:
                                page_found_urls.append(norm_url)

                        regex_posts = re.findall(r'https://[a-zA-Z0-9.-]*linkedin\.com/posts/[a-zA-Z0-9_\-%]+', raw_text)
                        for p in regex_posts:
                            norm_url = normalize_linkedin_post_url(p)
                            if norm_url and norm_url not in page_found_urls:
                                page_found_urls.append(norm_url)

                        metrics["raw_candidates"] += len(page_found_urls)

                        if not page_found_urls:
                            break

                        page_fresh_count = 0
                        new_on_page = 0
                        for u in page_found_urls:
                            if u not in discovered_urls_set:
                                discovered_urls_set.add(u)
                                new_on_page += 1
                                metrics["unique_candidates"] += 1

                                snow_dt = extract_snowflake_timestamp(u)
                                if snow_dt is not None:
                                    if is_within_window(snow_dt, max_age_minutes):
                                        page_fresh_count += 1
                                        metrics["fresh_candidates"] += 1
                                        candidate_pool.append((u, q_str, page_num))
                                else:
                                    page_fresh_count += 1
                                    metrics["fresh_candidates"] += 1
                                    candidate_pool.append((u, q_str, page_num))

                        if new_on_page == 0:
                            break
                        if page_fresh_count == 0 and len(page_found_urls) > 0:
                            break

                        if len(candidate_pool) >= max_discovery_candidates:
                            break

                    if len(candidate_pool) >= max_discovery_candidates:
                        break

        except Exception as e:
            print(f"LinkedIn session search error: {e}")

        t_disc_end = time.perf_counter()
        metrics["timing_ms"]["discovery_time_ms"] = int((t_disc_end - t_disc_start) * 1000)

        # 2. Async Concurrent Deep Extraction Phase
        t_ext_start = time.perf_counter()
        
        urls_to_extract = [item[0] for item in candidate_pool]
        url_metadata_map = {item[0]: (item[1], item[2]) for item in candidate_pool}

        extracted_batch = await LinkedInPostExtractor.extract_batch_async(
            urls=urls_to_extract,
            max_concurrency=max_concurrency,
            skills_taxonomy=skills_taxonomy,
            target_role=intent.target_role,
            target_location=intent.target_location,
            max_age_minutes=max_age_minutes
        )

        t_ext_end = time.perf_counter()
        metrics["timing_ms"]["extraction_time_ms"] = int((t_ext_end - t_ext_start) * 1000)

        # 3. Deterministic Filtering & Quality Ranking Phase
        t_rank_start = time.perf_counter()
        results = []

        for post_data in extracted_batch:
            metrics["deep_extracted"] += 1

            if not post_data or post_data.get("status") != "success":
                continue

            if post_data.get("hiring_intent") != "HIRING":
                continue
            metrics["hiring_candidates"] += 1

            role_score = post_data.get("role_match_score", 0)
            if intent.role_family != "GENERAL_SOFTWARE" and role_score < 50:
                continue
            metrics["role_candidates"] += 1

            p_url = post_data.get("post_url")
            cls._SEEN_POST_IDS.add(p_url)
            pitch_note = post_data.get("tailored_outreach_pitches", {}).get("linkedin_connection_note_300_chars", "")
            q_matched, p_page = url_metadata_map.get(p_url, ("", 1))

            compact_item = {
                "title": post_data.get("job_role", "Software Engineer"),
                "role": post_data.get("job_role", "Software Engineer"),
                "extracted_roles": post_data.get("extracted_roles", []),
                "author": post_data.get("author", "Hiring Recruiter"),
                "author_type": post_data.get("author_type", "RECRUITER"),
                "company": post_data.get("company", "Hiring Team"),
                "location": post_data.get("location", "Unspecified / Remote"),
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
                "recruiter_emails": post_data.get("recruiter_emails", []),
                "contact_emails": post_data.get("recruiter_emails", []),
                "contact_phones": post_data.get("contact_numbers", []),
                "contact_numbers": post_data.get("contact_numbers", []),
                "skills": post_data.get("detected_skills", []),
                "post_url": p_url,
                "connection_pitch": pitch_note,
                "discovery_source": "linkedin_session",
                "query_matched": q_matched,
                "page_found": p_page
            }
            results.append(compact_item)

        # Multi-signal Opportunity Ranking & Deterministic Tie-Breakers
        from core.ranking import OpportunityRanker
        ranked_results = OpportunityRanker.rank_opportunities(
            posts=results,
            target_role=intent.target_role,
            target_location=intent.target_location,
            max_age_minutes=max_age_minutes,
            apply_diversity=True
        )
        final_results = ranked_results[:max_results]

        t_rank_end = time.perf_counter()
        metrics["timing_ms"]["ranking_time_ms"] = int((t_rank_end - t_rank_start) * 1000)
        metrics["timing_ms"]["total_time_ms"] = int((t_rank_end - t_start) * 1000)
        metrics["final_results"] = len(final_results)

        if debug and final_results:
            final_results[0]["_funnel_metrics"] = metrics
            final_results[0]["_timing_ms"] = metrics["timing_ms"]

        return final_results

    @classmethod
    def search_posts_internal(
        cls,
        keywords: str,
        date_posted: str = "past-24h",
        max_results: int = 10,
        skills_taxonomy: Optional[List[str]] = None,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_discovery_candidates: int = 40,
        max_concurrency: int = MAX_CONCURRENCY,
        debug: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Synchronous entrypoint. Automatically delegates to async execution engine.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running inside an active loop (e.g. FastAPI / Jupyter)
                # Create a task in the loop or run directly
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    cls.search_posts_internal_async(
                        keywords=keywords,
                        date_posted=date_posted,
                        max_results=max_results,
                        skills_taxonomy=skills_taxonomy,
                        target_role=target_role,
                        target_location=target_location,
                        max_discovery_candidates=max_discovery_candidates,
                        max_concurrency=max_concurrency,
                        debug=debug
                    )
                )
            else:
                return loop.run_until_complete(
                    cls.search_posts_internal_async(
                        keywords=keywords,
                        date_posted=date_posted,
                        max_results=max_results,
                        skills_taxonomy=skills_taxonomy,
                        target_role=target_role,
                        target_location=target_location,
                        max_discovery_candidates=max_discovery_candidates,
                        max_concurrency=max_concurrency,
                        debug=debug
                    )
                )
        except Exception:
            return asyncio.run(
                cls.search_posts_internal_async(
                    keywords=keywords,
                    date_posted=date_posted,
                    max_results=max_results,
                    skills_taxonomy=skills_taxonomy,
                    target_role=target_role,
                    target_location=target_location,
                    max_discovery_candidates=max_discovery_candidates,
                    max_concurrency=max_concurrency,
                    debug=debug
                )
            )
