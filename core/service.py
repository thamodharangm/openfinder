"""
core/service.py
===============
Production-grade Canonical Product Service Layer for OpenFinder.

Powers:
- ChatGPT Custom GPT Actions
- Claude & Antigravity MCP Tools
- REST API Server (FastAPI)
- Command Line Interface (CLI)

Features:
- Unified, secure, and business-focused API contract.
- Dual resume ingestion: Native PDF (`upload_resume`) + Raw Text (`upload_resume_text`).
- Persistent candidate profile storage and retrieval across turns.
- Multi-signal concurrent opportunity search with strict freshness, ATS profile matching, and soft company diversity.
- Direct single-post parser and multi-persona recruiter pitch generator.
- Safe cross-framework async loop runner (_run_async_safely).
"""

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Union

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEFAULT_LOCATION, DEFAULT_MAX_RESULTS, DEFAULT_TIMEFRAME, ErrorCodes
from core.adaptive_harvester import DynamicKeywordExtractor, QueryYieldTracker
from core.hiring_intent import JobRoleExtractor
from core.linkedin_finder import LinkedInFinder
from core.linkedin_session import LinkedInSessionSearch
from core.linkedin_urls import normalize_linkedin_post_url
from core.live_repository import get_curated_posts
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor
from core.profile_store import CandidateProfileStore
from core.ranking import OpportunityRanker
from core.resume_parser import ResumeParser
from core.spam_filter import HiringIntentScorer
from core.time_utils import extract_snowflake_timestamp, get_max_age_minutes

logger = logging.getLogger(__name__)


def _run_async_safely(coro):
    """Safely executes an async coroutine across sync / nested event loops."""
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
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(coro))
                return future.result()
    else:
        return loop.run_until_complete(coro)


class OpenFinderService:
    """
    Canonical Product Service Layer for OpenFinder.
    Powers ChatGPT Custom GPT Actions, Claude MCP Tools, REST Endpoints, and CLI
    with a unified, secure, and business-focused API contract.
    """

    def __init__(self):
        self.resume_parser = ResumeParser()
        self.profile_store = CandidateProfileStore()
        self.finder = LinkedInFinder()

    def upload_resume(
        self,
        pdf_path_or_bytes: Union[str, bytes],
        filename: str = "resume.pdf"
    ) -> Dict[str, Any]:
        """
        Parses a candidate PDF resume, persists the normalized candidate profile in SQLite,
        and returns a clean, safe profile object with a unique candidate_profile_id.
        """
        temp_file_path = None
        try:
            if isinstance(pdf_path_or_bytes, bytes):
                # Write to safe temporary file
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_path_or_bytes)
                    temp_file_path = tmp.name
                target_path = temp_file_path
            else:
                target_path = str(pdf_path_or_bytes)

            # Parse resume using hardened parser
            raw_profile = self.resume_parser.parse(target_path)

            # Store in candidate profile store
            profile_id = self.profile_store.save_profile(raw_profile)

            return {
                "status": "success",
                "candidate_profile_id": profile_id,
                "candidate_name": raw_profile.get("candidate_name", "Candidate"),
                "seniority_level": raw_profile.get("seniority_level", "Mid-Level"),
                "years_of_experience": raw_profile.get("years_of_experience", 2),
                "primary_role": raw_profile.get("primary_role", "Software Engineer"),
                "top_skills": raw_profile.get("top_skills", []),
                "target_roles": raw_profile.get("target_roles", []),
                "education": raw_profile.get("education"),
                "desired_domains": raw_profile.get("desired_domains"),
                "github_url": raw_profile.get("github_url"),
                "linkedin_url": raw_profile.get("linkedin_url"),
                "portfolio_url": raw_profile.get("portfolio_url"),
                "message": "Resume successfully parsed and candidate profile created. Use this candidate_profile_id in search queries for personalized matching."
            }

        except Exception as e:
            logger.error("Error uploading/parsing resume: %s", e)
            return {
                "status": "error",
                "reason": ErrorCodes.PARSER_ERROR,
                "error": str(e)
            }
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    def upload_resume_text(self, resume_text: str) -> Dict[str, Any]:
        """
        Directly parses candidate plain text CV and stores persistent profile.
        """
        try:
            if not resume_text or not resume_text.strip():
                return {
                    "status": "error",
                    "reason": "EMPTY_PAYLOAD",
                    "error": "resume_text cannot be empty."
                }

            raw_profile = self.resume_parser.parse_from_text(resume_text)
            profile_id = self.profile_store.save_profile(raw_profile)

            return {
                "status": "success",
                "candidate_profile_id": profile_id,
                "candidate_name": raw_profile.get("candidate_name", "Candidate"),
                "seniority_level": raw_profile.get("seniority_level", "Mid-Level"),
                "years_of_experience": raw_profile.get("years_of_experience", 2),
                "primary_role": raw_profile.get("primary_role", "Software Engineer"),
                "top_skills": raw_profile.get("top_skills", []),
                "target_roles": raw_profile.get("target_roles", []),
                "education": raw_profile.get("education"),
                "desired_domains": raw_profile.get("desired_domains"),
                "github_url": raw_profile.get("github_url"),
                "linkedin_url": raw_profile.get("linkedin_url"),
                "portfolio_url": raw_profile.get("portfolio_url"),
                "message": "Resume text successfully parsed and candidate profile created. Use this candidate_profile_id in search queries."
            }

        except Exception as e:
            logger.error("Error parsing resume text: %s", e)
            return {
                "status": "error",
                "reason": ErrorCodes.PARSER_ERROR,
                "error": str(e)
            }

    def create_candidate_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates or updates a persistent candidate profile from structured JSON.
        """
        try:
            if not profile_data or not isinstance(profile_data, dict):
                return {
                    "status": "error",
                    "reason": "EMPTY_PAYLOAD",
                    "error": "profile_data cannot be empty."
                }

            skills = profile_data.get("skills") or profile_data.get("top_skills") or []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",") if s.strip()]

            name = profile_data.get("candidate_name") or profile_data.get("name") or "Candidate"
            exp_years = profile_data.get("years_of_experience") or profile_data.get("experience_years") or 2
            if isinstance(exp_years, str):
                try:
                    import re
                    exp_years = int(re.search(r'\d+', exp_years).group(0))
                except Exception:
                    exp_years = 2

            primary_role = profile_data.get("primary_role") or "Software Engineer"
            target_roles = profile_data.get("target_roles") or [primary_role]
            if isinstance(target_roles, str):
                target_roles = [r.strip() for r in target_roles.split(",") if r.strip()]

            profile_to_save = {
                "candidate_name": name,
                "email": profile_data.get("email"),
                "phone": profile_data.get("phone"),
                "years_of_experience": exp_years,
                "seniority_level": profile_data.get("seniority_level") or ("Junior / Entry-Level" if exp_years <= 2 else "Mid-Level"),
                "primary_role": primary_role,
                "top_skills": skills,
                "target_roles": target_roles,
                "target_locations": profile_data.get("target_locations", ["India"]),
                "education": profile_data.get("education"),
                "desired_domains": profile_data.get("desired_domains"),
                "github_url": profile_data.get("github_url"),
                "linkedin_url": profile_data.get("linkedin_url"),
                "portfolio_url": profile_data.get("portfolio_url"),
            }

            pid = self.profile_store.save_profile(profile_to_save)
            return {
                "status": "success",
                "candidate_profile_id": pid,
                "candidate_name": name,
                "seniority_level": profile_to_save["seniority_level"],
                "years_of_experience": exp_years,
                "primary_role": primary_role,
                "top_skills": skills,
                "target_roles": target_roles,
                "message": "Candidate profile successfully stored. Use this candidate_profile_id in search queries."
            }
        except Exception as e:
            logger.error("Error creating candidate profile: %s", e)
            return {
                "status": "error",
                "reason": ErrorCodes.PARSER_ERROR,
                "error": str(e)
            }

    def get_candidate_profile(self, candidate_profile_id: str) -> Dict[str, Any]:
        """Retrieves a stored candidate profile by ID."""
        if not candidate_profile_id:
            return {
                "status": "error",
                "reason": "MISSING_PROFILE_ID",
                "error": "candidate_profile_id parameter is required."
            }

        profile = self.profile_store.get_profile(candidate_profile_id)
        if not profile:
            return {
                "status": "error",
                "reason": "PROFILE_NOT_FOUND",
                "error": f"No candidate profile found with ID '{candidate_profile_id}'."
            }

        return {
            "status": "success",
            "candidate_profile": profile
        }

    def _resolve_candidate_profile(
        self,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        default_role: str = "Software Engineer"
    ) -> Optional[Dict[str, Any]]:
        """Resolves candidate profile from explicit dict, stored ID, or inline skills."""
        resolved = candidate_profile
        if not resolved and candidate_profile_id:
            resolved = self.profile_store.get_profile(candidate_profile_id)

        if not resolved and candidate_skills:
            if isinstance(candidate_skills, str):
                parsed_skills = [s.strip() for s in candidate_skills.split(",") if s.strip()]
            else:
                parsed_skills = list(candidate_skills)
            exp_val = candidate_exp_years or 2
            resolved = {
                "candidate_name": candidate_name or "Thamodharan Ganesan",
                "top_skills": parsed_skills,
                "skills": parsed_skills,
                "years_of_experience": exp_val,
                "seniority_level": "Mid-Level" if exp_val >= 2 else "Junior / Entry-Level (0-2 Years)",
                "primary_role": default_role
            }

        if not resolved:
            default_skills = ["React.js", "Node.js", "Express.js", "MongoDB", "JavaScript", "Next.js"]
            resolved = {
                "candidate_name": candidate_name or "Thamodharan Ganesan",
                "top_skills": default_skills,
                "skills": default_skills,
                "years_of_experience": candidate_exp_years or 2,
                "seniority_level": "Mid-Level",
                "primary_role": default_role or "MERN Stack Developer"
            }
        return resolved

    async def search_opportunities_async(
        self,
        query: str = "React Developer",
        location: str = DEFAULT_LOCATION,
        timeframe: str = DEFAULT_TIMEFRAME,
        max_results: int = DEFAULT_MAX_RESULTS,
        remote_only: bool = False,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Asynchronously searches across LinkedIn for verified hiring opportunities,
        ranks posts using multi-signal scoring against candidate profile, and enforces freshness.
        """
        clean_query = query.strip() if query else "Software Engineer"
        clean_location = location.strip() if location else "India"
        bounded_max_results = max(20, min(int(max_results) if max_results else 20, 50))

        # Resolve candidate profile
        resolved_profile = self._resolve_candidate_profile(
            candidate_profile_id=candidate_profile_id,
            candidate_profile=candidate_profile,
            candidate_skills=candidate_skills,
            candidate_exp_years=candidate_exp_years,
            candidate_name=candidate_name,
            default_role=clean_query
        )

        try:
            max_age_min = get_max_age_minutes(timeframe)
        except ValueError:
            timeframe = "past-24h"
            max_age_min = 1440

        # Smart Query Expansion: Generate role synonyms for high-volume discovery
        q_lower = clean_query.lower()
        expanded_keywords: List[str] = [clean_query]
        if any(k in q_lower for k in ["react", "frontend", "mern"]):
            for syn in ["React Developer", "MERN Stack", "Frontend Developer", "React Native", "Full Stack Developer"]:
                if syn.lower() not in [k.lower() for k in expanded_keywords]:
                    expanded_keywords.append(syn)
        elif any(k in q_lower for k in ["node", "backend", "express"]):
            for syn in ["Node.js Developer", "Backend Developer", "MERN Stack", "Full Stack Developer"]:
                if syn.lower() not in [k.lower() for k in expanded_keywords]:
                    expanded_keywords.append(syn)
        elif any(k in q_lower for k in ["python", "fastapi", "django"]):
            for syn in ["Python Developer", "Backend Engineer", "FastAPI", "Python Django"]:
                if syn.lower() not in [k.lower() for k in expanded_keywords]:
                    expanded_keywords.append(syn)
        elif any(k in q_lower for k in ["full stack", "fullstack", "software engineer"]):
            for syn in ["Full Stack Developer", "MERN Developer", "Software Engineer", "Frontend Developer"]:
                if syn.lower() not in [k.lower() for k in expanded_keywords]:
                    expanded_keywords.append(syn)

        if resolved_profile:
            t_skills = [s.lower() for s in resolved_profile.get("top_skills", [])]
            if ("react" in t_skills or "react.js" in t_skills) and "React Developer" not in expanded_keywords:
                expanded_keywords.append("React Developer")
            if ("node.js" in t_skills or "express.js" in t_skills) and "Node.js Developer" not in expanded_keywords:
                expanded_keywords.append("Node.js Developer")
            if ("react native" in t_skills or "expo" in t_skills) and "React Native" not in expanded_keywords:
                expanded_keywords.append("React Native")

        # Execute concurrent multi-query discovery across target location and Remote
        search_tasks = [
            self.finder.search_hiring_posts_async(
                keywords=kw,
                location=clean_location,
                timeframe=timeframe,
                remote_only=remote_only,
                max_results=15,
                debug=debug
            )
            for kw in expanded_keywords[:6]
        ]

        if clean_location.lower() not in ["remote", "india"] and not remote_only:
            for kw in expanded_keywords[:3]:
                search_tasks.append(
                    self.finder.search_hiring_posts_async(
                        keywords=kw,
                        location="Remote",
                        timeframe=timeframe,
                        remote_only=True,
                        max_results=10,
                        debug=debug
                    )
                )

        results_lists = await asyncio.gather(*search_tasks, return_exceptions=True)

        now_utc = datetime.now(timezone.utc)
        seen_urls: Set[str] = set()
        raw_posts: List[Dict[str, Any]] = []

        for res_list in results_lists:
            if isinstance(res_list, list):
                for post in res_list:
                    u = post.get("post_url")
                    if not u or u in seen_urls:
                        continue

                    # Strict Snowflake and age verification
                    snow_dt = extract_snowflake_timestamp(u)
                    if snow_dt is not None:
                        age_hours = (now_utc - snow_dt).total_seconds() / 3600.0
                        if age_hours > (max_age_min / 60.0):
                            continue
                        post["age_minutes"] = int(age_hours * 60)
                        post["age_hours"] = round(age_hours, 1)
                        post["posted_time"] = (
                            f"{int(age_hours)}h {int((age_hours%1)*60)}m ago"
                            if age_hours < 24
                            else f"{int(age_hours//24)}d {int(age_hours%24)}h ago"
                        )
                    else:
                        posted_str = (post.get("posted_time") or post.get("age_text") or "").lower()
                        if any(w in posted_str for w in ["4d", "5d", "6d", "7d", "13d", "38d", "94d", "month", "yr", "year", "weeks", "w ago"]):
                            continue

                    seen_urls.add(u)
                    raw_posts.append(post)

        # If live scraping returned fewer results, blend with curated verified recruiter repository
        if len(raw_posts) < bounded_max_results:
            curated = get_curated_posts(role=clean_query, location=clean_location, max_count=bounded_max_results)
            for cp in curated:
                u = cp.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    snow_dt = extract_snowflake_timestamp(u)
                    age_hours = (now_utc - snow_dt).total_seconds() / 3600.0 if snow_dt else 12.0
                    post_item = {
                        "title": cp.get("role", clean_query),
                        "role": cp.get("role", clean_query),
                        "company": cp.get("company", "Verified Tech Partner"),
                        "author": cp.get("author", "Hiring Lead"),
                        "location": cp.get("primary_location", clean_location),
                        "work_mode": cp.get("work_mode", "Hybrid"),
                        "recruiter_emails": cp.get("recruiter_emails", []),
                        "contact_numbers": [],
                        "post_url": u,
                        "age_minutes": int(age_hours * 60),
                        "posted_time": f"{int(age_hours)}h ago" if age_hours < 24 else f"{int(age_hours//24)}d ago",
                        "skills": cp.get("keywords", []),
                        "hiring_intent": "HIRING",
                        "is_live_post": False,
                        "source_type": "Curated Directory (Fallback)",
                        "salary_range": "Competitive / Disclosed in post",
                        "snippet": f"Hiring {cp.get('role')} at {cp.get('company')} ({cp.get('primary_location')}). Apply with resume."
                    }
                    raw_posts.append(post_item)

        if not raw_posts:
            session_valid = LinkedInSessionSearch.check_session_health().get("valid", False)
            diag_msg = "No verified matching hiring posts found in the requested timeframe."
            if not session_valid:
                diag_msg += " (Tip: Configure LINKEDIN_LI_AT environment variable on Render for direct LinkedIn API discovery)."

            return {
                "status": "success",
                "query": clean_query,
                "location": clean_location,
                "timeframe": timeframe,
                "count": 0,
                "candidate_profile_id": candidate_profile_id,
                "session_authenticated": session_valid,
                "results": [],
                "message": diag_msg
            }

        # Multi-signal opportunity ranking & soft company diversity
        ranked_posts = OpportunityRanker.rank_opportunities(
            posts=raw_posts,
            candidate_profile=resolved_profile,
            target_role=clean_query,
            target_location=clean_location,
            max_age_minutes=max_age_min,
            apply_diversity=True
        )

        final_posts = ranked_posts[:bounded_max_results]

        # Format clean, business-level response
        clean_results: List[Dict[str, Any]] = []
        for p in final_posts:
            clean_item = {
                "company": p.get("company", "Hiring Team"),
                "role": p.get("role") or p.get("job_role") or p.get("title") or clean_query,
                "author": p.get("author", "Hiring Manager"),
                "author_type": p.get("author_type", "RECRUITER"),
                "location": p.get("location", "Unspecified / Remote"),
                "is_live_post": p.get("is_live_post", True),
                "source_type": p.get("source_type", "Live LinkedIn Post"),
                "posted_time": p.get("posted_time") or p.get("age_text") or "Recently",
                "published_at": p.get("published_at"),
                "age_minutes": p.get("age_minutes", 0),
                "salary_range": p.get("salary_range", "Competitive / Disclosed in post"),
                "hiring_intent": p.get("hiring_intent", "HIRING"),
                "post_quality_score": p.get("post_quality_score", 85),
                "candidate_match_score": p.get("candidate_match_score"),
                "match_score": p.get("candidate_match_score") or p.get("final_rank_score") or 85,
                "final_rank_score": p.get("final_rank_score", p.get("post_quality_score", 85)),
                "ranking_summary": p.get("ranking_summary", ""),
                "ranking_reasons": p.get("ranking_reasons", []),
                "recruiter_emails": p.get("recruiter_emails", []),
                "contact_numbers": p.get("contact_numbers", []),
                "skills": p.get("skills", []),
                "matched_skills": p.get("matched_skills", []),
                "missing_skills": p.get("missing_skills", []),
                "tailored_outreach_pitches": p.get("tailored_outreach_pitches", {}),
                "post_url": p.get("post_url")
            }
            clean_results.append(clean_item)

        response_payload: Dict[str, Any] = {
            "status": "success",
            "query": clean_query,
            "location": clean_location,
            "timeframe": timeframe,
            "count": len(clean_results),
            "candidate_profile_id": candidate_profile_id,
            "candidate_name": resolved_profile.get("candidate_name") if resolved_profile else None,
            "results": clean_results
        }

        if debug and final_posts and "_funnel_metrics" in final_posts[0]:
            response_payload["_funnel_metrics"] = final_posts[0]["_funnel_metrics"]
            response_payload["_timing_ms"] = final_posts[0].get("_timing_ms", {})

        return response_payload

    def search_opportunities(
        self,
        query: str = "React Developer",
        location: str = DEFAULT_LOCATION,
        timeframe: str = DEFAULT_TIMEFRAME,
        max_results: int = DEFAULT_MAX_RESULTS,
        remote_only: bool = False,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """Synchronous wrapper for search_opportunities."""
        return _run_async_safely(
            self.search_opportunities_async(
                query=query,
                location=location,
                timeframe=timeframe,
                max_results=max_results,
                remote_only=remote_only,
                candidate_profile_id=candidate_profile_id,
                candidate_profile=candidate_profile,
                candidate_skills=candidate_skills,
                candidate_exp_years=candidate_exp_years,
                candidate_name=candidate_name,
                debug=debug
            )
        )

    async def linkedin_resume_match_async(
        self,
        candidate_profile_id: str,
        location: str = DEFAULT_LOCATION,
        timeframe: str = "past-24h",
        max_results: int = 20,
        min_match_score: int = 40,
        remote_only: bool = False,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        LinkedIn-Session-Exclusive, Resume-Mandatory Opportunity Finder.

        Fetches ONLY verified LinkedIn /posts/ hiring announcements discovered via
        authenticated LinkedIn session cookies (li_at + JSESSIONID). No curated
        repository, no Yahoo/DuckDuckGo search engine fallbacks.

        Results are strictly ranked by 6-factor ATS match score derived from the
        candidate's uploaded resume profile. Includes per-job skill gap analysis.

        Args:
            candidate_profile_id: Mandatory — ID of the uploaded resume profile.
            location: Target location (e.g. 'Bangalore', 'Remote', 'India').
            timeframe: Freshness window ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d').
            max_results: Maximum number of matched results to return (default 20, max 50).
            min_match_score: Minimum ATS match score 0-100 to include in results (default 40).
            remote_only: If True, only include remote-friendly positions.
            debug: If True, include funnel metrics in the response.
        """
        # ── 1. Validate resume profile ──────────────────────────────────────
        if not candidate_profile_id or not candidate_profile_id.strip():
            return {
                "status": "error",
                "reason": "MISSING_PROFILE_ID",
                "error": (
                    "candidate_profile_id is required for linkedin_resume_match. "
                    "Upload your resume first using upload_resume or upload_resume_text."
                )
            }

        candidate_profile = self.profile_store.get_profile(candidate_profile_id.strip())
        if not candidate_profile:
            return {
                "status": "error",
                "reason": "PROFILE_NOT_FOUND",
                "error": (
                    f"No resume profile found for ID '{candidate_profile_id}'. "
                    "Please upload your resume using upload_resume or upload_resume_text."
                )
            }

        # ── 2. Validate LinkedIn session ────────────────────────────────────
        session_health = LinkedInSessionSearch.check_session_health()
        if not session_health.get("valid", False):
            return {
                "status": "error",
                "reason": "LINKEDIN_SESSION_UNAVAILABLE",
                "error": (
                    "LinkedIn session cookies not configured or expired. "
                    "Set LINKEDIN_LI_AT and LINKEDIN_JSESSIONID in the .env file."
                ),
                "session_status": session_health
            }

        # ── 3. Build role queries from resume ───────────────────────────────
        primary_role   = candidate_profile.get("primary_role") or "Software Engineer"
        target_roles   = candidate_profile.get("target_roles") or [primary_role]
        top_skills     = candidate_profile.get("top_skills") or candidate_profile.get("skills") or []
        exp_years      = candidate_profile.get("years_of_experience") or 0
        cand_name      = candidate_profile.get("candidate_name") or "Candidate"
        clean_location = location.strip() if location else DEFAULT_LOCATION
        bounded_max    = max(5, min(int(max_results), 50))

        # Build role query set: primary role + top-2 skills as targeted queries
        role_queries: List[str] = []
        for role in target_roles[:3]:
            if role and role.strip():
                role_queries.append(role.strip())
        if top_skills:
            # Add a skill-combo query for specificity
            skill_combo = " ".join(top_skills[:3])
            role_queries.append(f"{primary_role} {skill_combo}")
        if not role_queries:
            role_queries = ["Software Engineer"]
        # Deduplicate while preserving order
        seen_q: Set[str] = set()
        unique_queries: List[str] = []
        for q in role_queries:
            ql = q.lower()
            if ql not in seen_q:
                seen_q.add(ql)
                unique_queries.append(q)

        # ── 4. LinkedIn-Session-Only discovery (parallel across role queries) ──
        logger.info(
            "linkedin_resume_match: Starting LinkedIn-session-only search "
            "for profile '%s' (%s) with %d role queries",
            cand_name, candidate_profile_id, len(unique_queries)
        )

        session_tasks = [
            LinkedInSessionSearch.search_posts_internal_async(
                keywords=q,
                date_posted=timeframe,
                max_results=bounded_max * 2,           # over-fetch, then re-rank
                skills_taxonomy=self.finder.skills_taxonomy,
                target_role=q,
                target_location=clean_location,
                candidate_profile=candidate_profile,
                max_discovery_candidates=60,
                debug=debug
            )
            for q in unique_queries[:5]               # max 5 parallel queries
        ]
        result_batches = await asyncio.gather(*session_tasks, return_exceptions=True)

        # ── 5. Merge, deduplicate, re-rank by ATS match score ───────────────
        from core.matcher import JobMatcher
        seen_urls: Set[str] = set()
        raw_posts: List[Dict[str, Any]] = []

        for batch in result_batches:
            if not isinstance(batch, list):
                continue
            for post in batch:
                url = post.get("post_url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Only keep genuine LinkedIn hiring posts
                if post.get("hiring_intent") not in ("HIRING", "POTENTIAL_HIRING"):
                    continue

                # Skip non-remote if remote_only requested
                if remote_only:
                    post_loc = str(post.get("location", "")).lower()
                    work_mode = str(post.get("work_mode", "")).lower()
                    post_content = str(post.get("full_post_content", "") or post.get("raw_snippet", "")).lower()
                    if "remote" not in post_loc and "remote" not in work_mode and "remote" not in post_content:
                        continue

                # Re-compute deep ATS match using the full candidate profile
                job_post_dict = {
                    "title":              post.get("role") or post.get("title") or primary_role,
                    "required_skills":    post.get("skills") or post.get("required_skills") or [],
                    "experience_required": post.get("experience_required") or post.get("experience_fit") or "",
                    "description":        post.get("full_post_content") or post.get("raw_snippet") or "",
                    "domains":            post.get("domains") or [],
                    "location":           post.get("location") or "",
                    "remote":             "remote" in str(post.get("location", "")).lower(),
                    "education_required": post.get("education_required") or "",
                }
                deep_match = JobMatcher.calculate_deep_match(candidate_profile, job_post_dict)
                match_score = deep_match.get("match_score", 0)

                # Apply minimum ATS match threshold
                if match_score < min_match_score:
                    continue

                post["match_score"]         = match_score
                post["match_grade"]         = deep_match.get("match_grade", "")
                post["matched_skills"]      = deep_match.get("matched_skills", [])
                post["missing_skills"]      = deep_match.get("missing_skills", [])
                post["ats_recommendations"] = deep_match.get("ats_recommendations", [])
                post["tech_score"]          = deep_match.get("tech_score")
                post["exp_score"]           = deep_match.get("exp_score")
                post["role_score"]          = deep_match.get("role_score")
                post["domain_score"]        = deep_match.get("domain_score")
                post["location_score"]      = deep_match.get("location_score")

                # Skill gap analysis: projected score if missing skills are added
                missing = deep_match.get("missing_skills", [])
                if missing:
                    projected_score = min(100, match_score + len(missing) * 6)
                    post["skill_gap_analysis"] = {
                        "current_match_score": match_score,
                        "projected_score_if_upskilled": projected_score,
                        "skills_to_add": missing[:8],
                        "quick_win_recommendation": (
                            f"Adding {', '.join(missing[:3])} to your resume could raise your match "
                            f"from {match_score}% → ~{projected_score}% for this role."
                        ) if missing else None
                    }
                else:
                    post["skill_gap_analysis"] = {
                        "current_match_score": match_score,
                        "projected_score_if_upskilled": match_score,
                        "skills_to_add": [],
                        "quick_win_recommendation": "Strong match — your resume aligns well with this role!"
                    }

                raw_posts.append(post)

        # ── 6. Sort by match_score (primary) then freshness (secondary) ──────
        raw_posts.sort(
            key=lambda p: (p.get("match_score", 0), -p.get("age_minutes", 9999)),
            reverse=True
        )
        final_posts = raw_posts[:bounded_max]

        # ── 7. Build clean response ──────────────────────────────────────────
        clean_results: List[Dict[str, Any]] = []
        for p in final_posts:
            recruiter_emails = p.get("recruiter_emails") or p.get("contact_emails") or []
            # Auto-generate outreach pitch for posts with email
            outreach_pitches = p.get("tailored_outreach_pitches") or {}
            if recruiter_emails and not outreach_pitches:
                try:
                    from core.pitch_generator import OutreachPitchGenerator
                    role_title = (p.get("role") or primary_role)[:80]
                    outreach_pitches = OutreachPitchGenerator.generate_suite(
                        job_title=role_title,
                        company_name=p.get("company") or "Hiring Team",
                        matched_skills=p.get("matched_skills") or top_skills[:5],
                        candidate_name=cand_name,
                        candidate_exp_years=exp_years,
                        recipient_name=p.get("author") or "Hiring Manager",
                        recipient_email=recruiter_emails[0] if recruiter_emails else None,
                    )
                except Exception:
                    pass

            clean_results.append({
                "company":              p.get("company") or "Hiring Team",
                "role":                 p.get("role") or p.get("title") or primary_role,
                "author":               p.get("author") or "Hiring Manager",
                "author_type":          p.get("author_type") or "RECRUITER",
                "location":             p.get("location") or "Unspecified / Remote",
                "work_mode":            p.get("work_mode") or "Unspecified",
                "posted_time":          p.get("posted_time") or p.get("age_text") or "Recently",
                "age_minutes":          p.get("age_minutes") or 0,
                "hiring_intent":        p.get("hiring_intent") or "HIRING",

                # ATS Match
                "match_score":          p.get("match_score"),
                "match_grade":          p.get("match_grade"),
                "matched_skills":       p.get("matched_skills") or [],
                "missing_skills":       p.get("missing_skills") or [],
                "ats_recommendations":  p.get("ats_recommendations") or [],
                "skill_gap_analysis":   p.get("skill_gap_analysis") or {},
                "score_breakdown": {
                    "tech_stack":       p.get("tech_score"),
                    "experience":       p.get("exp_score"),
                    "role_alignment":   p.get("role_score"),
                    "domain":           p.get("domain_score"),
                    "location":         p.get("location_score"),
                },

                # Contact & Apply
                "recruiter_emails":     recruiter_emails,
                "contact_numbers":      p.get("contact_numbers") or p.get("contact_phones") or [],
                "post_url":             p.get("post_url"),
                "source":               "LinkedIn Session (Authenticated)",
                "outreach_pitches":     outreach_pitches,
            })

        # ── 8. Return structured response ────────────────────────────────────
        session_info = {
            "authenticated": True,
            "has_csrf": session_health.get("has_csrf", False),
            "queries_used": unique_queries,
            "total_linkedin_posts_discovered": len(seen_urls),
            "posts_above_min_match_threshold": len(raw_posts),
        }

        if not clean_results:
            tips = []
            if len(seen_urls) == 0:
                tips.append("LinkedIn session may have expired — refresh LINKEDIN_LI_AT in .env.")
            else:
                tips.append(f"Found {len(seen_urls)} LinkedIn posts but none cleared the {min_match_score}% match threshold.")
                tips.append(f"Try lowering min_match_score to 25 or broadening the location.")
            return {
                "status": "success",
                "candidate_name": cand_name,
                "candidate_profile_id": candidate_profile_id,
                "location": clean_location,
                "timeframe": timeframe,
                "count": 0,
                "results": [],
                "session_info": session_info,
                "tips": tips,
            }

        return {
            "status": "success",
            "candidate_name": cand_name,
            "candidate_profile_id": candidate_profile_id,
            "primary_role": primary_role,
            "top_skills": top_skills[:10],
            "location": clean_location,
            "timeframe": timeframe,
            "min_match_score": min_match_score,
            "count": len(clean_results),
            "results": clean_results,
            "session_info": session_info,
            "message": (
                f"Found {len(clean_results)} LinkedIn hiring posts matched to {cand_name}'s resume "
                f"(min ATS score: {min_match_score}%). All results are live, authenticated LinkedIn posts."
            ),
        }

    def linkedin_resume_match(
        self,
        candidate_profile_id: str,
        location: str = DEFAULT_LOCATION,
        timeframe: str = "past-24h",
        max_results: int = 20,
        min_match_score: int = 40,
        remote_only: bool = False,
        debug: bool = False
    ) -> Dict[str, Any]:
        """Synchronous entrypoint for linkedin_resume_match_async."""
        return _run_async_safely(
            self.linkedin_resume_match_async(
                candidate_profile_id=candidate_profile_id,
                location=location,
                timeframe=timeframe,
                max_results=max_results,
                min_match_score=min_match_score,
                remote_only=remote_only,
                debug=debug,
            )
        )

    def parse_linkedin_post(
        self,
        url: str,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        candidate_profile_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Direct single LinkedIn /posts/ intelligence extraction."""
        candidate_profile = None
        if candidate_profile_id:
            candidate_profile = self.profile_store.get_profile(candidate_profile_id)

        return LinkedInPostExtractor.extract_from_url(
            url=url,
            target_role=target_role,
            target_location=target_location,
            candidate_profile=candidate_profile
        )

    def generate_pitch(
        self,
        job_title: str,
        company_name: str = "your team",
        matched_skills: Optional[Union[List[str], str]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        recipient_name: Optional[str] = None,
        recipient_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates multi-persona recruiter pitches and 1-click email deep links."""
        return OutreachPitchGenerator.generate_suite(
            job_title=job_title,
            company_name=company_name,
            matched_skills=matched_skills,
            candidate_name=candidate_name,
            candidate_exp_years=candidate_exp_years,
            recipient_name=recipient_name,
            recipient_email=recipient_email
        )

    async def bulk_harvest_opportunities_async(
        self,
        roles: Optional[Union[List[str], str]] = None,
        locations: Optional[Union[List[str], str]] = None,
        timeframe: str = "past-7d",
        target_count: int = 50,
        min_intent_score: int = 60,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        max_pages: int = 4,
        max_time_seconds: int = 25,
        adaptive_mode: bool = True,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Adaptive Yield-Optimized Bulk Harvester:
        - Strict 25s execution guardrail for Claude Web / Desktop MCP stability.
        - Multi-Armed Bandit Query Yield Tracking (boosts high-yield vectors, prunes spam branches).
        - Dynamic Keyword & Hub Discovery (extracts emerging roles/terms from initial wave).
        - Two-Stage Precision Verification (Hiring Intent Score >= min_intent_score).
        - Composite Deduplication and ATS Match Ranking.
        """
        start_time = time.time()

        # 1. Normalize input parameters
        if isinstance(roles, str):
            roles_list = [r.strip() for r in roles.split(",") if r.strip()]
        elif isinstance(roles, list):
            roles_list = [str(r).strip() for r in roles if str(r).strip()]
        else:
            roles_list = ["React Developer", "MERN Stack", "Frontend Engineer", "Node.js Developer"]

        if isinstance(locations, str):
            locs_list = [l.strip() for l in locations.split(",") if l.strip()]
        elif isinstance(locations, list):
            locs_list = [str(l).strip() for l in locations if str(l).strip()]
        else:
            locs_list = ["Bangalore", "Chennai", "Hyderabad", "Pune", "Remote"]

        bounded_target = max(10, min(int(target_count), 200))
        resolved_profile = self._resolve_candidate_profile(
            candidate_profile_id=candidate_profile_id,
            candidate_profile=candidate_profile,
            candidate_skills=candidate_skills,
            candidate_exp_years=candidate_exp_years,
            candidate_name=candidate_name
        )

        yield_tracker = QueryYieldTracker()
        now_utc = datetime.now(timezone.utc)
        seen_keys: Set[str] = set()
        seen_urls: Set[str] = set()
        verified_hiring_posts: List[Dict[str, Any]] = []
        total_harvested_raw = 0
        rejected_intent_count = 0
        duplicates_count = 0
        waves_executed = 0
        stop_reason = "target_reached"

        # Build tech relevance tokens from requested roles
        req_tech_tokens: Set[str] = set()
        for r in roles_list:
            for tok in re.split(r'[\s/,-]+', r.lower()):
                if len(tok) >= 3 and tok not in ["developer", "engineer", "lead", "specialist", "hiring", "team", "senior", "junior"]:
                    req_tech_tokens.add(tok)

        def is_tech_relevant(post_role: str, content: str) -> bool:
            if not req_tech_tokens:
                return True
            combo = f"{post_role} {content[:400]}".lower()
            return any(tok in combo for tok in req_tech_tokens)

        # Wave 1: Primary Query Matrix Harvesting
        waves_executed += 1
        raw_wave_1 = await self.finder.harvest_query_matrix_async(
            roles=roles_list[:4],
            locations=locs_list[:4],
            timeframe=timeframe,
            max_pages=max_pages,
            target_count=bounded_target,
            debug=debug
        )
        total_harvested_raw += len(raw_wave_1)

        for p in raw_wave_1:
            u = p.get("post_url")
            if not u:
                continue

            norm_u = normalize_linkedin_post_url(u) or u
            author = (p.get("author") or "").strip().lower()
            company = (p.get("company") or "").strip().lower()
            dedupe_key = f"{norm_u}::{author}::{company}"

            if dedupe_key in seen_keys or norm_u in seen_urls:
                duplicates_count += 1
                continue
            seen_keys.add(dedupe_key)
            seen_urls.add(norm_u)

            snippet_text = p.get("full_post_content") or p.get("raw_text") or p.get("snippet") or p.get("title") or ""
            author_title = p.get("author_title") or p.get("author_headline") or ""
            author_name = p.get("author") or ""
            role_val = p.get("role") or p.get("job_role") or p.get("title") or roles_list[0]
            p["role"] = role_val

            # Enforce strict tech role relevance (filters out off-target C++, Azure DevOps, etc.)
            if not is_tech_relevant(role_val, snippet_text):
                rejected_intent_count += 1
                continue

            intent_eval = HiringIntentScorer.evaluate(snippet_text, author_title, author_name)
            p["hiring_intent_score"] = intent_eval.score
            p["hiring_type"] = intent_eval.hiring_type
            p["intent_signals"] = intent_eval.signals
            p["is_hiring_intent"] = intent_eval.is_hiring_intent

            category = role_val
            yield_tracker.record_query(
                query=f"{category} in {p.get('location', 'India')}",
                category=category,
                raw_count=1,
                verified_count=1 if intent_eval.score >= min_intent_score else 0
            )

            if intent_eval.score < min_intent_score or intent_eval.hiring_type == "NON_HIRING":
                rejected_intent_count += 1
                continue

            snow_dt = extract_snowflake_timestamp(u)
            if snow_dt is not None:
                age_hours = (now_utc - snow_dt).total_seconds() / 3600.0
                p["age_minutes"] = int(age_hours * 60)
                p["posted_time"] = f"{int(age_hours)}h ago" if age_hours < 24 else f"{int(age_hours//24)}d ago"
            else:
                p["posted_time"] = p.get("posted_time") or "Recently"

            p["is_live_post"] = True
            p["source_type"] = "Live LinkedIn Post"

            # Auto-generate 1-click recruiter outreach pitch suite if emails are extracted
            if p.get("recruiter_emails") and not p.get("tailored_outreach_pitches"):
                try:
                    clean_pitch_role = re.sub(r'#\S+', '', role_val).strip()
                    clean_pitch_role = re.sub(r'\s+', ' ', clean_pitch_role).strip()
                    if len(clean_pitch_role) < 4 or clean_pitch_role.lower() in ["alert", "for", "hiring", "immediate", "job opening"]:
                        clean_pitch_role = roles_list[0] if roles_list else "MERN Stack Developer"

                    p["tailored_outreach_pitches"] = OutreachPitchGenerator.generate_suite(
                        job_title=clean_pitch_role,
                        company_name=p.get("company", "Hiring Team"),
                        matched_skills=p.get("skills", []),
                        candidate_name=resolved_profile.get("candidate_name", "Thamodharan Ganesan") if resolved_profile else "Thamodharan Ganesan",
                        candidate_exp_years=resolved_profile.get("years_of_experience", 2) if resolved_profile else 2,
                        recipient_name=p.get("author", "Hiring Team"),
                        recipient_email=p["recruiter_emails"][0]
                    )
                except Exception:
                    pass

            verified_hiring_posts.append(p)

        # Wave 2: Adaptive Dynamic Keyword Expansion (if target not yet reached and time budget remains)
        elapsed = time.time() - start_time
        if adaptive_mode and len(verified_hiring_posts) < bounded_target and elapsed < (max_time_seconds - 6):
            discovered_roles, discovered_locs = DynamicKeywordExtractor.extract_emerging_terms(
                verified_hiring_posts,
                roles_list,
                locs_list
            )

            if discovered_roles or discovered_locs:
                waves_executed += 1
                adaptive_roles = discovered_roles if discovered_roles else roles_list[:2]
                adaptive_locs = discovered_locs if discovered_locs else locs_list[:2]

                raw_wave_2 = await self.finder.harvest_query_matrix_async(
                    roles=adaptive_roles,
                    locations=adaptive_locs,
                    timeframe=timeframe,
                    max_pages=2,
                    target_count=max(10, bounded_target - len(verified_hiring_posts)),
                    debug=debug
                )
                total_harvested_raw += len(raw_wave_2)

                for p in raw_wave_2:
                    u = p.get("post_url")
                    if not u:
                        continue
                    norm_u = normalize_linkedin_post_url(u) or u
                    author = (p.get("author") or "").strip().lower()
                    company = (p.get("company") or "").strip().lower()
                    dedupe_key = f"{norm_u}::{author}::{company}"
                    if dedupe_key in seen_keys or norm_u in seen_urls:
                        duplicates_count += 1
                        continue
                    seen_keys.add(dedupe_key)
                    seen_urls.add(norm_u)

                    snippet_text = p.get("full_post_content") or p.get("raw_text") or p.get("snippet") or p.get("title") or ""
                    author_title = p.get("author_title") or p.get("author_headline") or ""
                    author_name = p.get("author") or ""
                    role_val = p.get("role") or p.get("job_role") or p.get("title") or roles_list[0]
                    p["role"] = role_val

                    # Enforce strict tech role relevance
                    if not is_tech_relevant(role_val, snippet_text):
                        rejected_intent_count += 1
                        continue

                    intent_eval = HiringIntentScorer.evaluate(snippet_text, author_title, author_name)
                    p["hiring_intent_score"] = intent_eval.score
                    p["hiring_type"] = intent_eval.hiring_type
                    p["intent_signals"] = intent_eval.signals
                    p["is_hiring_intent"] = intent_eval.is_hiring_intent

                    if intent_eval.score < min_intent_score or intent_eval.hiring_type == "NON_HIRING":
                        rejected_intent_count += 1
                        continue

                    snow_dt = extract_snowflake_timestamp(u)
                    if snow_dt is not None:
                        age_hours = (now_utc - snow_dt).total_seconds() / 3600.0
                        p["age_minutes"] = int(age_hours * 60)
                        p["posted_time"] = f"{int(age_hours)}h ago" if age_hours < 24 else f"{int(age_hours//24)}d ago"
                    else:
                        p["posted_time"] = p.get("posted_time") or "Recently"

                    p["is_live_post"] = True
                    p["source_type"] = "Live LinkedIn Post"

                    if p.get("recruiter_emails") and not p.get("tailored_outreach_pitches"):
                        try:
                            clean_pitch_role = re.sub(r'#\S+', '', role_val).strip()
                            clean_pitch_role = re.sub(r'\s+', ' ', clean_pitch_role).strip()
                            if len(clean_pitch_role) < 4 or clean_pitch_role.lower() in ["alert", "for", "hiring", "immediate", "job opening"]:
                                clean_pitch_role = roles_list[0] if roles_list else "MERN Stack Developer"

                            p["tailored_outreach_pitches"] = OutreachPitchGenerator.generate_suite(
                                job_title=clean_pitch_role,
                                company_name=p.get("company", "Hiring Team"),
                                matched_skills=p.get("skills", []),
                                candidate_name=resolved_profile.get("candidate_name", "Thamodharan Ganesan") if resolved_profile else "Thamodharan Ganesan",
                                candidate_exp_years=resolved_profile.get("years_of_experience", 2) if resolved_profile else 2,
                                recipient_name=p.get("author", "Hiring Team"),
                                recipient_email=p["recruiter_emails"][0]
                            )
                        except Exception:
                            pass

                    verified_hiring_posts.append(p)

        # Fallback blend strictly if verified count is low, with unique URL enforcement
        if len(verified_hiring_posts) < 5:
            for r in roles_list[:2]:
                for loc in locs_list[:2]:
                    curated = get_curated_posts(role=r, location=loc, max_count=5)
                    for cp in curated:
                        u = cp.get("url")
                        norm_u = normalize_linkedin_post_url(u) or u if u else None
                        if norm_u and norm_u not in seen_urls:
                            seen_urls.add(norm_u)
                            snow_dt = extract_snowflake_timestamp(norm_u)
                            age_hours = (now_utc - snow_dt).total_seconds() / 3600.0 if snow_dt else 12.0
                            verified_hiring_posts.append({
                                "title": cp.get("role", r),
                                "role": cp.get("role", r),
                                "company": cp.get("company", "Verified Tech Partner"),
                                "author": cp.get("author", "Hiring Lead"),
                                "location": cp.get("primary_location", loc),
                                "work_mode": cp.get("work_mode", "Hybrid"),
                                "recruiter_emails": cp.get("recruiter_emails", []),
                                "contact_numbers": [],
                                "post_url": norm_u,
                                "age_minutes": int(age_hours * 60),
                                "posted_time": f"{int(age_hours)}h ago" if age_hours < 24 else f"{int(age_hours//24)}d ago",
                                "skills": cp.get("keywords", []),
                                "hiring_intent_score": 85,
                                "hiring_type": "RECRUITER_HIRING",
                                "is_live_post": False,
                                "source_type": "Curated Directory (Fallback)",
                                "salary_range": "Competitive / Disclosed in post",
                                "snippet": f"Hiring {cp.get('role')} at {cp.get('company')} ({cp.get('primary_location')})."
                            })

        # Determine stop reason
        total_time = round(time.time() - start_time, 2)
        if len(verified_hiring_posts) >= bounded_target:
            stop_reason = "target_reached"
        elif total_time >= (max_time_seconds - 2):
            stop_reason = "time_budget_exhausted"
        else:
            stop_reason = "diminishing_returns"

        # Multi-signal Opportunity Ranking & ATS Match Scoring
        ranked = OpportunityRanker.rank_opportunities(
            posts=verified_hiring_posts,
            candidate_profile=resolved_profile,
            target_role=roles_list[0] if roles_list else "Software Engineer",
            target_location=locs_list[0] if locs_list else "India",
            max_age_minutes=get_max_age_minutes(timeframe),
            apply_diversity=True
        )

        final_dataset = ranked[:bounded_target]

        clean_results: List[Dict[str, Any]] = []
        for p in final_dataset:
            post_loc = (p.get("location") or "").lower()
            if any(fl in post_loc for fl in ["lahore", "karachi", "islamabad", "pakistan", "dhaka", "bangladesh"]) and not any(loc.lower() in ["pakistan", "lahore", "bangladesh"] for loc in locs_list):
                continue

            # Clean author
            raw_author = p.get("author") or "Hiring Manager"
            if re.search(r'-(?:share|activity|ugcpost)-\d+', raw_author, re.IGNORECASE) or any(x in raw_author.lower() for x in ["ushiring", "techrecruitment", "jobalert", "share 74"]):
                clean_author = "Hiring Lead"
            elif len(raw_author) > 30 and " " not in raw_author:
                clean_author = "Hiring Lead"
            else:
                clean_author = raw_author

            # Clean role
            raw_role = p.get("role") or p.get("job_role") or p.get("title") or roles_list[0]
            clean_role = JobRoleExtractor.normalize_job_title(raw_role, fallback_role=roles_list[0])

            clean_item = {
                "company": p.get("company", "Hiring Team"),
                "role": clean_role,
                "author": clean_author,
                "hiring_type": p.get("hiring_type", "RECRUITER_HIRING"),
                "hiring_intent_score": p.get("hiring_intent_score", 85),
                "location": p.get("location", "Unspecified / Remote"),
                "work_mode": p.get("work_mode", "Hybrid"),
                "posted_time": p.get("posted_time") or "Recently",
                "age_minutes": p.get("age_minutes", 0),
                "salary_range": p.get("salary_range", "Competitive / Disclosed in post"),
                "candidate_match_score": p.get("candidate_match_score"),
                "match_score": p.get("candidate_match_score") or p.get("final_rank_score") or 85,
                "is_live_post": p.get("is_live_post", True),
                "source_type": p.get("source_type", "Live LinkedIn Post"),
                "recruiter_emails": p.get("recruiter_emails", []),
                "skills": p.get("skills", []),
                "matched_skills": p.get("matched_skills", []),
                "missing_skills": p.get("missing_skills", []),
                "tailored_outreach_pitches": p.get("tailored_outreach_pitches", {}),
                "post_url": p.get("post_url")
            }
            clean_results.append(clean_item)

        return {
            "status": "success",
            "roles": roles_list,
            "locations": locs_list,
            "timeframe": timeframe,
            "target_count": bounded_target,
            "min_intent_score": min_intent_score,
            "count": len(clean_results),
            "harvest_telemetry": {
                "stop_reason": stop_reason,
                "waves_executed": waves_executed,
                "execution_time_seconds": total_time,
                "max_time_budget_seconds": max_time_seconds,
                "yield_summary": yield_tracker.get_summary()
            },
            "funnel_metrics": {
                "total_harvested_raw": total_harvested_raw,
                "duplicates_removed": duplicates_count,
                "intent_filtered_out": rejected_intent_count,
                "verified_opportunities_ready": len(clean_results)
            },
            "candidate_profile_id": candidate_profile_id,
            "candidate_name": resolved_profile.get("candidate_name") if resolved_profile else None,
            "results": clean_results
        }

    def bulk_harvest_opportunities(
        self,
        roles: Optional[Union[List[str], str]] = None,
        locations: Optional[Union[List[str], str]] = None,
        timeframe: str = "past-7d",
        target_count: int = 50,
        min_intent_score: int = 60,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        max_pages: int = 4,
        max_time_seconds: int = 25,
        adaptive_mode: bool = True,
        debug: bool = False
    ) -> Dict[str, Any]:
        """Synchronous entrypoint for bulk_harvest_opportunities."""
        return _run_async_safely(
            self.bulk_harvest_opportunities_async(
                roles=roles,
                locations=locations,
                timeframe=timeframe,
                target_count=target_count,
                min_intent_score=min_intent_score,
                candidate_profile_id=candidate_profile_id,
                candidate_profile=candidate_profile,
                candidate_skills=candidate_skills,
                candidate_exp_years=candidate_exp_years,
                candidate_name=candidate_name,
                max_pages=max_pages,
                max_time_seconds=max_time_seconds,
                adaptive_mode=adaptive_mode,
                debug=debug
            )
        )

    async def prewarm_cache_async(
        self,
        roles: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        timeframe: str = "past-24h",
        max_posts_per_target: int = 15
    ) -> Dict[str, Any]:
        """
        Asynchronously pre-warms SQLite cache and curated repository for high-frequency queries.
        """
        from core.adaptive_harvester import BackgroundPrewarmer
        return await BackgroundPrewarmer.prewarm_async(
            roles=roles,
            locations=locations,
            timeframe=timeframe,
            max_posts_per_target=max_posts_per_target
        )

    def prewarm_cache(
        self,
        roles: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        timeframe: str = "past-24h",
        max_posts_per_target: int = 15
    ) -> Dict[str, Any]:
        """
        Synchronous entrypoint for prewarm_cache.
        """
        return _run_async_safely(
            self.prewarm_cache_async(
                roles=roles,
                locations=locations,
                timeframe=timeframe,
                max_posts_per_target=max_posts_per_target
            )
        )

    async def classify_hiring_post_async(
        self,
        text: str,
        author: str = "",
        url: str = "",
        target_role: Optional[str] = None,
        target_location: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Asynchronously classifies post text using AI Hiring Intent Classifier with SQLite persistence.
        """
        from core.ai_classifier import AIHiringIntentClassifier
        classifier = AIHiringIntentClassifier()
        res = await classifier.classify_async(
            text=text,
            author=author,
            url=url,
            target_role=target_role,
            target_location=target_location
        )
        return {
            "status": "success",
            "classification": res.to_dict()
        }

    def classify_hiring_post(
        self,
        text: str,
        author: str = "",
        url: str = "",
        target_role: Optional[str] = None,
        target_location: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synchronous entrypoint for classify_hiring_post.
        """
        return _run_async_safely(
            self.classify_hiring_post_async(
                text=text,
                author=author,
                url=url,
                target_role=target_role,
                target_location=target_location
            )
        )


