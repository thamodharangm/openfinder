import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Ensure UTF-8 stdout/stderr on Windows terminals & MCP transports
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except Exception:
        class FastMCP:
            def __init__(self, name): self.name = name
            def tool(self): return lambda f: f
            def run(self, transport="stdio"): pass

from core.service import OpenFinderService
from core.resume_parser import ResumeParser
from core.linkedin_finder import LinkedInFinder
from core.matcher import JobMatcher
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor

# Initialize FastMCP Server
mcp = FastMCP("OpenFinder - Universal AI Job Catcher for Freshers & Experienced")

# Initialize core services
service = OpenFinderService()
resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()


# ==============================================================================
# CANONICAL PRODUCT MCP TOOLS (PHASE 8)
# ==============================================================================

@mcp.tool()
def upload_resume(resume_path: str) -> Dict[str, Any]:
    """
    Uploads and parses a candidate PDF resume, extracts structured skills,
    seniority, and target roles, persists the profile, and returns a unique
    candidate_profile_id for personalized job searches.

    Args:
        resume_path: Path to the candidate's PDF resume on disk (e.g. 'C:/Users/.../resume.pdf').
    """
    return service.upload_resume(resume_path)


@mcp.tool()
def get_candidate_profile(candidate_profile_id: str) -> Dict[str, Any]:
    """
    Retrieves a stored candidate profile by its unique candidate_profile_id.

    Args:
        candidate_profile_id: Unique candidate profile ID (e.g. 'prof_a1b2c3d4e5f6').
    """
    return service.get_candidate_profile(candidate_profile_id)


@mcp.tool()
def search_opportunities(
    query: str = "React Developer",
    location: str = "India",
    timeframe: str = "past-24h",
    max_results: int = 10,
    remote_only: bool = False,
    candidate_profile_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Canonical Opportunity Search Tool.
    Discovers verified LinkedIn recruiter hiring /posts/ with exact freshness validation
    (past-1h, past-4h, past-12h, past-24h, past-7d), directional hiring intent, role precision,
    and multi-signal opportunity ranking against candidate profile.

    Args:
        query: Target job role or technical skills (e.g. 'React Developer', 'MERN Stack', 'Python FastAPI').
        location: City or region (e.g. 'Bangalore', 'Chennai', 'Remote', 'India').
        timeframe: Recency filter ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'). Default 'past-24h'.
        max_results: Maximum opportunities to return (1-30, default 10).
        remote_only: True to restrict to remote roles.
        candidate_profile_id: Optional stored candidate profile ID for ATS skill and experience fit ranking.
    """
    return service.search_opportunities(
        query=query,
        location=location,
        timeframe=timeframe,
        max_results=max_results,
        remote_only=remote_only,
        candidate_profile_id=candidate_profile_id
    )


# ==============================================================================
# LEGACY & SPECIALIZED MCP TOOLS
# ==============================================================================

@mcp.tool()
def parse_resume(pdf_path: str) -> Dict[str, Any]:
    """
    Deeply parses a candidate PDF resume, extracting categorized technical skills
    (Frontend, Backend, Cloud, AI/ML), estimated seniority level, contact info, and target roles.
    
    Args:
        pdf_path: Absolute or relative path to the candidate's resume PDF file.
    """
    try:
        return resume_parser.parse(pdf_path)
    except Exception as e:
        return {"error": f"Failed to parse resume PDF: {str(e)}"}


@mcp.tool()
def search_jobs_by_resume(
    resume_path: str,
    location: str = "India",
    timeframe: str = "past-24h",
    remote_only: bool = False,
    min_match_score: int = 35
) -> Dict[str, Any]:
    """
    Deeply parses Resume PDF, queries real-time LinkedIn hiring posts, 
    calculates multi-dimensional weighted match scores, and provides ATS optimization advice.
    
    Args:
        resume_path: Path to candidate resume PDF (e.g. 'D:/my_resume.pdf').
        location: City or Country to search in (e.g. 'Bangalore', 'Remote', 'India').
        timeframe: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'.
        remote_only: True if looking only for remote positions.
        min_match_score: Minimum match percentage threshold (default 35%).
    """
    try:
        profile = resume_parser.parse(resume_path)
        top_skills = profile.get("top_skills", [])
        primary_role = profile.get("primary_role", "Software Engineer")

        # Pick high-yield search keywords (e.g. 'React Developer' or 'React Node.js')
        if len(top_skills) >= 2:
            search_kw = f"{top_skills[0]} {top_skills[1]}"
        elif top_skills:
            search_kw = f"{top_skills[0]} Developer"
        else:
            search_kw = "Software Developer"

        posts = linkedin_finder.search_hiring_posts(
            keywords=search_kw,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only,
            max_results=15
        )

        ranked_jobs = JobMatcher.rank_and_score_posts(
            candidate_profile=profile,
            posts=posts,
            min_score=min_match_score
        )

        return {
            "status": "success",
            "candidate_profile": {
                "name": profile.get("candidate_name"),
                "seniority": profile.get("seniority_level"),
                "years_experience": profile.get("years_of_experience"),
                "target_roles": profile.get("target_roles"),
                "skills_categorized": profile.get("skills_categorized")
            },
            "search_criteria": {
                "keywords_used": search_kw,
                "location": location,
                "remote_only": remote_only
            },
            "total_matches_found": len(ranked_jobs),
            "matched_jobs": ranked_jobs
        }

    except Exception as e:
        return {"error": f"Error in resume-based job search: {str(e)}"}


@mcp.tool()
def search_linkedin_hiring(
    keywords: str,
    location: str = "India",
    timeframe: str = "past-24h",
    remote_only: bool = False,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Searches recent genuine LinkedIn /posts/ URLs with extracted company names, 
    work mode (Remote/Hybrid/Onsite), salary hints, and apply links.
    
    CRITICAL DISPLAY RULE: Always present results as a clean, horizontal Markdown table with columns:
    # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link.
    Do NOT output vertical bullet lists.
    
    Args:
        keywords: Job role or skills (e.g. 'React Developer', 'Python Backend').
        location: City or Country (e.g. 'Bangalore', 'Remote', 'India').
        timeframe: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'.
        remote_only: True to filter only remote roles.
        max_results: Max number of posts (default 10).
    """
    try:
        posts = linkedin_finder.search_hiring_posts(
            keywords=keywords,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only,
            max_results=max_results
        )
        table = LinkedInFinder.format_as_markdown_table(posts)
        return {
            "status": "success",
            "count": len(posts),
            "query": keywords,
            "markdown_table": table,
            "posts": posts
        }
    except Exception as e:
        return {"error": f"Failed to search LinkedIn hiring posts: {str(e)}"}


@mcp.tool()
def generate_recruiter_pitch(
    job_title: str,
    company_name: str = "Hiring Team",
    matched_skills: str = "React, Node.js",
    candidate_name: str = "Candidate",
    candidate_exp_years: int = 2
) -> Dict[str, Any]:
    """
    Generates 4 high-converting recruiter outreach templates:
      1. LinkedIn Connection Note (<300 chars)
      2. InMail / Direct Message
      3. Formal Executive Cover Email
      4. Day-3 Follow-Up Note
    """
    skills_list = [s.strip() for s in matched_skills.split(",") if s.strip()]
    pitches = OutreachPitchGenerator.generate_suite(
        job_title=job_title,
        company_name=company_name,
        matched_skills=skills_list,
        candidate_name=candidate_name,
        candidate_exp_years=candidate_exp_years
    )
    return {
        "status": "success",
        "job_title": job_title,
        "company": company_name,
        "pitches": pitches
    }


@mcp.tool()
def parse_linkedin_post(
    post_url: str,
    candidate_name: str = "Candidate",
    candidate_exp_years: int = 2
) -> Dict[str, Any]:
    """
    Directly extracts structured hiring intelligence from any LinkedIn Post, 
    Activity Feed update, or Shortlink, extracting HR contact emails, phone numbers,
    required tech stack, and generating personalized recruiter pitches.
    
    Args:
        post_url: Direct URL to the LinkedIn post (e.g. 'https://www.linkedin.com/posts/...').
        candidate_name: Your name for the pitch sign-off.
        candidate_exp_years: Your years of experience.
    """
    try:
        data = LinkedInPostExtractor.extract_from_url(
            url=post_url,
            candidate_name=candidate_name,
            candidate_exp_years=candidate_exp_years
        )
        return {"status": "success", "post": data}
    except Exception as e:
        return {"error": f"Failed to parse post URL: {str(e)}"}


@mcp.tool()
def search_posts(
    keywords: str,
    date_posted: Optional[str] = "past-24h",
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Search LinkedIn posts globally by keyword (the 'Posts' tab) with an exact freshness filter.
    
    CRITICAL DISPLAY RULE: Always present the search results to the user as a clean, horizontal Markdown table with columns: 
    # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link.
    Do NOT output vertical bullet lists.
    
    Args:
        keywords: Search query (e.g. 'React Developer hiring Bangalore', 'looking for MERN developer').
        date_posted: Recency filter ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'). Default is 'past-24h'.
        max_results: Maximum number of posts to fetch (default: 10).
    """
    finder = LinkedInFinder()
    results = finder.search_posts(
        keywords=keywords,
        date_posted=date_posted,
        max_results=max_results
    )
    table = LinkedInFinder.format_as_markdown_table(results)
    return {
        "status": "success",
        "count": len(results),
        "query": keywords,
        "date_posted": date_posted,
        "markdown_table": table,
        "posts": results
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
