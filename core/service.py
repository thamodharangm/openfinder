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
from core.linkedin_session import LinkedInSessionSearch
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

    def create_candidate_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates or updates a persistent candidate profile from structured JSON (e.g. sent by ChatGPT).
        """
        try:
            if not profile_data:
                return {
                    "status": "error",
                    "reason": "EMPTY_PAYLOAD",
                    "error": "profile_data cannot be empty."
                }

            # If raw skills list is passed as comma string, convert to list
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
                "target_locations": profile_data.get("target_locations", ["India"])
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
            return {
                "status": "error",
                "reason": ErrorCodes.PARSER_ERROR,
                "error": str(e)
            }

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
        candidate_skills: Optional[Union[str, List[str]]] = None,
        candidate_exp_years: Optional[int] = None,
        candidate_name: Optional[str] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Canonical Search Operation.
        Finds verified LinkedIn hiring /posts/ with exact freshness verification,
        directional hiring intent, role precision, ATS resume matching, and Opportunity Ranking.
        """
        # Validate and bound inputs (Default 20 results)
        bounded_max_results = max(20, min(int(max_results) if max_results else 20, 50))
        clean_query = query.strip() if query else "Software Engineer"
        clean_location = location.strip() if location else "India"

        # Resolve candidate profile
        resolved_profile = candidate_profile
        if not resolved_profile and candidate_profile_id:
            resolved_profile = self.profile_store.get_profile(candidate_profile_id)

        # Fallback to inline candidate skills if passed directly by ChatGPT
        if not resolved_profile and candidate_skills:
            if isinstance(candidate_skills, str):
                parsed_skills = [s.strip() for s in candidate_skills.split(",") if s.strip()]
            else:
                parsed_skills = list(candidate_skills)
            exp_val = candidate_exp_years or 2
            resolved_profile = {
                "candidate_name": candidate_name or "Candidate",
                "top_skills": parsed_skills,
                "years_of_experience": exp_val,
                "seniority_level": "Mid-Level" if exp_val >= 2 else "Junior / Entry-Level (0-2 Years)",
                "primary_role": clean_query
            }

        try:
            max_age_min = get_max_age_minutes(timeframe)
        except ValueError:
            timeframe = "past-24h"
            max_age_min = 1440

        # Smart Query Expansion: Generate 5-8 role synonyms for high-volume discovery
        q_lower = clean_query.lower()
        expanded_keywords = [clean_query]
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
        
        # Also concurrently search Remote if user specified a city like Bangalore
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

        from datetime import datetime, timezone
        from core.time_utils import extract_snowflake_timestamp
        now_utc = datetime.now(timezone.utc)

        seen_urls = set()
        raw_posts = []
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
                        # REJECT if older than max_age_min (e.g. 72h for past-3d, 24h for past-24h)
                        if age_hours > (max_age_min / 60.0):
                            continue
                        post["age_minutes"] = int(age_hours * 60)
                        post["age_hours"] = round(age_hours, 1)
                        post["posted_time"] = f"{int(age_hours)}h {int((age_hours%1)*60)}m ago" if age_hours < 24 else f"{int(age_hours//24)}d {int(age_hours%24)}h ago"
                    else:
                        posted_str = (post.get("posted_time") or post.get("age_text") or "").lower()
                        if any(w in posted_str for w in ["4d", "5d", "6d", "7d", "13d", "38d", "94d", "month", "yr", "year", "weeks", "w ago"]):
                            continue

                    seen_urls.add(u)
                    raw_posts.append(post)

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
                "match_score": p.get("candidate_match_score") or p.get("final_rank_score") or 85,
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
