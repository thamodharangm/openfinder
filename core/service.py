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
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEFAULT_LOCATION, DEFAULT_MAX_RESULTS, DEFAULT_TIMEFRAME, ErrorCodes
from core.linkedin_finder import LinkedInFinder
from core.linkedin_session import LinkedInSessionSearch
from core.live_repository import get_curated_posts
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor
from core.profile_store import CandidateProfileStore
from core.ranking import OpportunityRanker
from core.resume_parser import ResumeParser
from core.spam_filter import HiringIntentScorer, calculate_hiring_intent_score, classify_post_type
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
                "candidate_name": candidate_name or "Candidate",
                "top_skills": parsed_skills,
                "skills": parsed_skills,
                "years_of_experience": exp_val,
                "seniority_level": "Mid-Level" if exp_val >= 2 else "Junior / Entry-Level (0-2 Years)",
                "primary_role": default_role
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
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Executes wide-matrix parallel search and deep pagination harvesting,
        applies numerical hiring intent scoring (score >= min_intent_score),
        classifies post type (DIRECT, RECRUITER, REFERRAL, AGENCY), and ranks by ATS match.
        """
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

        # 2. Harvest raw post dataset
        raw_harvested = await self.finder.harvest_query_matrix_async(
            roles=roles_list,
            locations=locs_list,
            timeframe=timeframe,
            max_pages=max_pages,
            target_count=bounded_target,
            debug=debug
        )

        total_harvested_raw = len(raw_harvested)

        # 3. Composite deduplication & Intent scoring
        now_utc = datetime.now(timezone.utc)
        seen_keys: Set[str] = set()
        verified_hiring_posts: List[Dict[str, Any]] = []
        rejected_intent_count = 0
        duplicates_count = 0

        for p in raw_harvested:
            u = p.get("post_url")
            if not u:
                continue

            author = (p.get("author") or "").strip().lower()
            company = (p.get("company") or "").strip().lower()
            dedupe_key = f"{u}::{author}::{company}"

            if dedupe_key in seen_keys:
                duplicates_count += 1
                continue
            seen_keys.add(dedupe_key)

            # Evaluate Hiring Intent Score
            snippet_text = p.get("raw_text") or p.get("snippet") or p.get("title") or ""
            author_title = p.get("author_title") or p.get("author_headline") or ""
            author_name = p.get("author") or ""

            intent_eval = HiringIntentScorer.evaluate(snippet_text, author_title, author_name)
            p["hiring_intent_score"] = intent_eval.score
            p["hiring_type"] = intent_eval.hiring_type
            p["intent_signals"] = intent_eval.signals
            p["is_hiring_intent"] = intent_eval.is_hiring_intent

            if intent_eval.score < min_intent_score or intent_eval.hiring_type == "NON_HIRING":
                rejected_intent_count += 1
                continue

            # Check Snowflake timestamp & age
            snow_dt = extract_snowflake_timestamp(u)
            if snow_dt is not None:
                age_hours = (now_utc - snow_dt).total_seconds() / 3600.0
                p["age_minutes"] = int(age_hours * 60)
                p["posted_time"] = f"{int(age_hours)}h ago" if age_hours < 24 else f"{int(age_hours//24)}d ago"
            else:
                p["posted_time"] = p.get("posted_time") or "Recently"

            p["is_live_post"] = True
            p["source_type"] = "Live LinkedIn Post"
            verified_hiring_posts.append(p)

        # 4. Fallback blend if harvested count is low
        if len(verified_hiring_posts) < 10:
            for r in roles_list[:2]:
                for loc in locs_list[:2]:
                    curated = get_curated_posts(role=r, location=loc, max_count=10)
                    for cp in curated:
                        u = cp.get("url")
                        if u and u not in seen_keys:
                            seen_keys.add(u)
                            snow_dt = extract_snowflake_timestamp(u)
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
                                "post_url": u,
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

        # 5. Opportunity Ranking & ATS Match Scoring
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
            clean_item = {
                "company": p.get("company", "Hiring Team"),
                "role": p.get("role") or p.get("job_role") or p.get("title") or "Software Engineer",
                "author": p.get("author", "Hiring Manager"),
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
                debug=debug
            )
        )
