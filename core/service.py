import os
import sys
import tempfile
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DEFAULT_TIMEFRAME, DEFAULT_LOCATION, DEFAULT_MAX_RESULTS, ErrorCodes
from core.resume_parser import ResumeParser
from core.profile_store import CandidateProfileStore
from core.linkedin_finder import LinkedInFinder
from core.ranking import OpportunityRanker
from core.time_utils import get_max_age_minutes


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

            # Return safe, business-level candidate profile
            return {
                "status": "success",
                "candidate_profile_id": profile_id,
                "candidate_name": raw_profile.get("candidate_name", "Candidate"),
                "seniority_level": raw_profile.get("seniority_level", "Mid-Level"),
                "years_of_experience": raw_profile.get("years_of_experience", 2),
                "primary_role": raw_profile.get("primary_role", "Software Engineer"),
                "top_skills": raw_profile.get("top_skills", []),
                "target_roles": raw_profile.get("target_roles", []),
                "message": "Resume successfully parsed and candidate profile created. Use this candidate_profile_id in search queries for personalized matching."
            }

        except Exception as e:
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

    def get_candidate_profile(self, candidate_profile_id: str) -> Dict[str, Any]:
        """
        Retrieves a stored candidate profile by ID.
        """
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

    async def search_opportunities_async(
        self,
        query: str = "React Developer",
        location: str = DEFAULT_LOCATION,
        timeframe: str = DEFAULT_TIMEFRAME,
        max_results: int = DEFAULT_MAX_RESULTS,
        remote_only: bool = False,
        candidate_profile_id: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Canonical Search Operation.
        Finds verified LinkedIn hiring /posts/ with exact freshness verification,
        directional hiring intent, role precision, ATS resume matching, and Opportunity Ranking.
        """
        # Validate and bound inputs
        bounded_max_results = max(1, min(int(max_results) if max_results else 10, 30))
        clean_query = query.strip() if query else "Software Engineer"
        clean_location = location.strip() if location else "India"

        # Resolve candidate profile
        resolved_profile = candidate_profile
        if not resolved_profile and candidate_profile_id:
            resolved_profile = self.profile_store.get_profile(candidate_profile_id)

        try:
            max_age_min = get_max_age_minutes(timeframe)
        except ValueError:
            timeframe = "past-24h"
            max_age_min = 1440

        # Execute discovery and extraction
        raw_posts = await self.finder.search_hiring_posts_async(
            keywords=clean_query,
            location=clean_location,
            timeframe=timeframe,
            remote_only=remote_only,
            max_results=bounded_max_results,
            debug=debug
        )

        if not raw_posts:
            return {
                "status": "success",
                "query": clean_query,
                "location": clean_location,
                "timeframe": timeframe,
                "count": 0,
                "candidate_profile_id": candidate_profile_id,
                "results": [],
                "message": "No verified matching hiring posts found in the requested timeframe."
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

        # Format clean, compact business-level response for LLMs
        clean_results = []
        for p in final_posts:
            clean_item = {
                "company": p.get("company", "Hiring Team"),
                "role": p.get("role") or p.get("job_role") or p.get("title") or clean_query,
                "author": p.get("author", "Hiring Manager"),
                "author_type": p.get("author_type", "RECRUITER"),
                "location": p.get("location", "Unspecified / Remote"),
                "posted_time": p.get("posted_time") or p.get("age_text") or "Recently",
                "published_at": p.get("published_at"),
                "age_minutes": p.get("age_minutes", 0),
                "hiring_intent": p.get("hiring_intent", "HIRING"),
                "post_quality_score": p.get("post_quality_score", 85),
                "candidate_match_score": p.get("candidate_match_score"),
                "final_rank_score": p.get("final_rank_score", p.get("post_quality_score", 85)),
                "ranking_summary": p.get("ranking_summary", ""),
                "ranking_reasons": p.get("ranking_reasons", []),
                "recruiter_emails": p.get("recruiter_emails", []),
                "contact_numbers": p.get("contact_numbers", []),
                "skills": p.get("skills", []),
                "matched_skills": p.get("matched_skills", []),
                "missing_skills": p.get("missing_skills", []),
                "post_url": p.get("post_url")
            }
            clean_results.append(clean_item)

        response_payload = {
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
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for search_opportunities.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    self.search_opportunities_async(
                        query=query,
                        location=location,
                        timeframe=timeframe,
                        max_results=max_results,
                        remote_only=remote_only,
                        candidate_profile_id=candidate_profile_id,
                        candidate_profile=candidate_profile,
                        debug=debug
                    )
                )
            else:
                return loop.run_until_complete(
                    self.search_opportunities_async(
                        query=query,
                        location=location,
                        timeframe=timeframe,
                        max_results=max_results,
                        remote_only=remote_only,
                        candidate_profile_id=candidate_profile_id,
                        candidate_profile=candidate_profile,
                        debug=debug
                    )
                )
        except Exception:
            return asyncio.run(
                self.search_opportunities_async(
                    query=query,
                    location=location,
                    timeframe=timeframe,
                    max_results=max_results,
                    remote_only=remote_only,
                    candidate_profile_id=candidate_profile_id,
                    candidate_profile=candidate_profile,
                    debug=debug
                )
            )
