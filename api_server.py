from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
import shutil
import tempfile
from pathlib import Path
import sys

# Ensure root in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.resume_parser import ResumeParser
from core.linkedin_finder import LinkedInFinder
from core.matcher import JobMatcher

app = FastAPI(
    title="OpenFinder - LinkedIn Job Scout & Resume Matcher API",
    description="Universal AI Connector & Plugin for ChatGPT Actions, Claude Connectors, and Custom AI Agents.",
    version="1.0.0",
    servers=[
        {"url": "http://localhost:8000", "description": "Local Development Server"}
    ]
)

# Enable CORS for cross-origin browser & AI clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()


@app.get("/", tags=["Health"])
def health_check():
    return {
        "status": "online",
        "service": "OpenFinder LinkedIn AI Connector",
        "chatgpt_actions_ready": True,
        "claude_mcp_ready": True,
        "docs_url": "/docs",
        "openapi_url": "/openapi.json"
    }


@app.post("/api/parse-resume", tags=["Resume"])
async def parse_resume_endpoint(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Upload a candidate Resume PDF and extract skills, experience, and target roles.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        profile = resume_parser.parse(tmp_path)
        return {"status": "success", "profile": profile}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/api/search-jobs-by-resume", tags=["Jobs"])
async def search_jobs_by_resume_endpoint(
    file: UploadFile = File(...),
    location: str = Form("India"),
    timeframe: str = Form("w"),
    remote_only: bool = Form(False),
    min_match_score: int = Form(40)
) -> Dict[str, Any]:
    """
    Upload Resume PDF, automatically search matching LinkedIn hiring posts, 
    and rank them by Match Score %.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        profile = resume_parser.parse(tmp_path)
        top_skills = profile.get("top_skills", [])
        inferred_roles = profile.get("inferred_target_roles", ["Software Engineer"])

        search_kw = inferred_roles[0] if inferred_roles else "Software Engineer"
        if len(top_skills) >= 2:
            search_kw = f"{top_skills[0]} {top_skills[1]}"

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
                "roles": inferred_roles,
                "skills": top_skills,
                "experience": profile.get("estimated_experience_years")
            },
            "total_matches": len(ranked_jobs),
            "jobs": ranked_jobs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/api/search-hiring-posts", tags=["Jobs"])
def search_hiring_posts_endpoint(
    keywords: str = Query(..., description="Role or skill keywords (e.g. 'React Developer', 'Python')"),
    location: str = Query("India", description="City or Country (e.g. 'Bangalore', 'Remote', 'India')"),
    timeframe: str = Query("w", description="'d' (24h), 'w' (7 days), 'm' (month)"),
    remote_only: bool = Query(False, description="Filter only remote jobs"),
    max_results: int = Query(10, description="Max results to fetch")
) -> Dict[str, Any]:
    """
    Direct LinkedIn hiring search endpoint (Ideal for ChatGPT Custom Actions).
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
            "query": keywords,
            "posts": posts
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/generate-pitch", tags=["Outreach"])
def generate_pitch_endpoint(
    post_snippet: str = Form(..., description="LinkedIn post text or description"),
    candidate_skills: Optional[str] = Form(None, description="Comma-separated candidate skills"),
    candidate_name: str = Form("Candidate", description="Your name")
) -> Dict[str, Any]:
    """
    Generate Cold LinkedIn DM and Email pitch tailored to the job opening.
    """
    skills_text = candidate_skills or "modern software engineering practices"
    
    cold_dm = (
        f"Hi [Hiring Manager / Recruiter Name],\n\n"
        f"I came across your recent LinkedIn hiring post. "
        f"I have extensive hands-on experience in {skills_text}, and my background closely aligns with your requirements.\n\n"
        f"Would you be open to a brief chat to discuss how I can add immediate value to your team?\n\n"
        f"Best regards,\n{candidate_name}"
    )

    email_pitch = (
        f"Subject: Application: Hiring Role - {candidate_name} ({skills_text[:30]}...)\n\n"
        f"Dear Hiring Team,\n\n"
        f"I noticed your opening shared on LinkedIn and wanted to formally apply.\n\n"
        f"Key Highlights:\n"
        f"• Core Tech Stack: {skills_text}\n"
        f"• Experience building scalable, production-ready solutions.\n\n"
        f"I have attached my resume and would welcome the opportunity to discuss further.\n\n"
        f"Best regards,\n{candidate_name}"
    )

    return {
        "status": "success",
        "linkedin_dm": cold_dm,
        "email_pitch": email_pitch
    }


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting OpenFinder Universal AI Plugin & API Connector on http://localhost:8000 ...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
