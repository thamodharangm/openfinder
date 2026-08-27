import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.fastmcp import FastMCP
from core.resume_parser import ResumeParser
from core.linkedin_finder import LinkedInFinder
from core.matcher import JobMatcher
from core.post_parser import PostParser

# Initialize FastMCP Server
mcp = FastMCP("LinkedIn Job Scout & Resume Matcher")

# Initialize core services
resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()


@mcp.tool()
def parse_resume(pdf_path: str) -> Dict[str, Any]:
    """
    Parses a PDF resume, extracting key technical skills, estimated years of experience, 
    and target job search roles.
    
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
    timeframe: str = "w",
    remote_only: bool = False,
    min_match_score: int = 40
) -> Dict[str, Any]:
    """
    Parses your Resume PDF, identifies your top skills and target roles, 
    searches recent genuine LinkedIn hiring posts, and ranks them by Match Score %.
    
    Args:
        resume_path: Path to your resume PDF (e.g. 'D:/resume.pdf' or 'sample_resume/resume.pdf').
        location: City or Country to search in (e.g. 'Bangalore', 'Chennai', 'India', 'USA').
        timeframe: 'd' (past 24 hours), 'w' (past 7 days), 'm' (past month).
        remote_only: True if looking only for remote positions.
        min_match_score: Minimum match percentage threshold to include (default 40%).
    """
    try:
        # 1. Parse Resume
        candidate_profile = resume_parser.parse(resume_path)
        top_skills = candidate_profile.get("top_skills", [])
        inferred_roles = candidate_profile.get("inferred_target_roles", ["Software Engineer"])

        if not top_skills:
            return {"error": "No technical skills could be extracted from the resume to perform matching."}

        # 2. Formulate query using target roles or high-priority skills
        if inferred_roles:
            search_kw = inferred_roles[0]
        elif len(top_skills) >= 2:
            search_kw = f"{top_skills[0]} {top_skills[1]}"
        elif top_skills:
            search_kw = top_skills[0]
        else:
            search_kw = "Software Developer"

        # 3. Search LinkedIn hiring posts
        raw_posts = linkedin_finder.search_hiring_posts(
            keywords=search_kw,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only,
            max_results=15
        )

        if not raw_posts:
            # Fallback search with the primary role title
            search_kw = inferred_roles[0] if inferred_roles else "Software Engineer"
            raw_posts = linkedin_finder.search_hiring_posts(
                keywords=search_kw,
                location=location,
                timeframe=timeframe,
                remote_only=remote_only,
                max_results=15
            )

        # 4. Score and Rank Posts
        ranked_jobs = JobMatcher.rank_and_score_posts(
            candidate_profile=candidate_profile,
            posts=raw_posts,
            min_score=min_match_score
        )

        return {
            "status": "success",
            "candidate_summary": {
                "inferred_roles": inferred_roles,
                "extracted_skills": top_skills,
                "experience": candidate_profile.get("estimated_experience_years")
            },
            "search_criteria": {
                "keywords_used": search_kw,
                "location": location,
                "timeframe": timeframe,
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
    timeframe: str = "w",
    remote_only: bool = False,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Directly searches recent genuine LinkedIn hiring posts by keywords without requiring a resume.
    
    Args:
        keywords: Role or skill keywords (e.g. 'React Developer', 'Golang Backend', 'Product Manager').
        location: City or Country (e.g. 'Bangalore', 'Remote', 'India').
        timeframe: 'd' (past 24h), 'w' (past week), 'm' (past month).
        remote_only: True to filter only remote roles.
        max_results: Number of hiring posts to retrieve (default 10).
    """
    try:
        posts = linkedin_finder.search_hiring_posts(
            keywords=keywords,
            location=location,
            timeframe=timeframe,
            remote_only=remote_only,
            max_results=max_results
        )
        return {
            "status": "success",
            "count": len(posts),
            "search_query": keywords,
            "posts": posts
        }
    except Exception as e:
        return {"error": f"Failed to search LinkedIn hiring posts: {str(e)}"}


@mcp.tool()
def generate_recruiter_pitch(
    post_details: str,
    resume_path: Optional[str] = None,
    candidate_name: Optional[str] = "Candidate"
) -> Dict[str, str]:
    """
    Drafts a personalized, high-converting Cold LinkedIn DM and Email pitch 
    matching the candidate's resume strengths to the job post requirements.
    
    Args:
        post_details: Text or URL snippet of the LinkedIn hiring post.
        resume_path: Optional path to resume PDF to incorporate specific project highlights.
        candidate_name: Your name to sign off with.
    """
    skills_text = ""
    if resume_path:
        try:
            profile = resume_parser.parse(resume_path)
            skills_text = ", ".join(profile.get("top_skills", []))
        except Exception:
            pass

    skills_mention = f"with strong experience in {skills_text}" if skills_text else "with relevant industry experience"

    cold_dm = (
        f"Hi [Hiring Manager / Recruiter Name],\n\n"
        f"I came across your recent LinkedIn post regarding the hiring opening. "
        f"I am a software professional {skills_mention}, and my background closely aligns with what your team is building.\n\n"
        f"I've attached my resume for your review. Would you be open to a quick 5-minute chat to discuss how I can contribute to this role?\n\n"
        f"Best regards,\n{candidate_name}"
    )

    email_pitch = (
        f"Subject: Application: Hiring Role - {candidate_name} ({skills_text[:30]}...)\n\n"
        f"Dear Hiring Team,\n\n"
        f"I noticed your job opening shared on LinkedIn and wanted to formally express my interest.\n\n"
        f"Key highlights of what I bring:\n"
        f"• Core Tech Stack: {skills_text or 'Relevant modern engineering practices'}\n"
        f"• Proven track record in developing scalable and performant solutions.\n\n"
        f"I have attached my resume and would love the opportunity to speak with you further.\n\n"
        f"Thank you for your time,\n{candidate_name}\n[Your Phone / Portfolio Link]"
    )

    return {
        "linkedin_dm_template": cold_dm,
        "email_pitch_template": email_pitch
    }


if __name__ == "__main__":
    # Start FastMCP server via stdio (standard for Claude Desktop / Antigravity / Cursor)
    mcp.run(transport="stdio")
