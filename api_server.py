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
from core.pitch_generator import OutreachPitchGenerator

app = FastAPI(
    title="OpenFinder - Professional LinkedIn AI Job Scout & Career Suite",
    description="Enterprise-Grade AI Career Engine for ChatGPT Actions, Claude Connectors, and Multi-Agent Workflows.",
    version="2.0.0",
    servers=[
        {"url": "http://127.0.0.1:8000", "description": "Local Development Server"}
    ]
)

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
        "service": "OpenFinder Universal AI Connector",
        "chatgpt_actions_ready": True,
        "claude_connectors_ready": True,
        "docs_url": "/docs",
        "openapi_url": "/openapi.json"
    }


# ==========================================
# 🟢 CLAUDE WEB CUSTOM CONNECTOR (MCP PROTOCOL)
# ==========================================

from fastapi.responses import JSONResponse, Response

@app.get("/.well-known/oauth-authorization-server", tags=["Claude"])
@app.get("/.well-known/oauth-protected-resource", tags=["Claude"])
def oauth_discovery():
    # Returning 404 explicitly tells Claude: 'No OAuth required, connect with No-Auth'
    return Response(status_code=404)


@app.post("/register", tags=["Claude"])
def dynamic_client_register():
    return Response(status_code=404)


@app.post("/", tags=["Claude"])
@app.post("/mcp", tags=["Claude"])
async def mcp_jsonrpc_endpoint(request: dict):
    """
    Handles native JSON-RPC 2.0 MCP requests sent by Claude Web Custom Connectors.
    """
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    # 1. Initialize
    if method == "initialize":
        client_proto = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "openfinder",
                    "version": "2.0.0"
                }
            }
        }

    # 2. Initialized Notification
    if method == "notifications/initialized":
        return JSONResponse(content={"jsonrpc": "2.0", "result": {}})

    # 3. Ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # 4. List Tools
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_hiring_posts",
                        "description": "Searches recent live LinkedIn recruiter hiring posts (past 7 days only, excluding generic job boards) with post links, emails, and requirements.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keywords": {
                                    "type": "string",
                                    "description": "Job role or technical skill (e.g. 'React Developer', 'Python Backend')"
                                },
                                "location": {
                                    "type": "string",
                                    "description": "Location (e.g. 'Bangalore', 'Remote', 'India')",
                                    "default": "India"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Max posts to fetch (default 10)",
                                    "default": 10
                                }
                            },
                            "required": ["keywords"]
                        }
                    },
                    {
                        "name": "generate_recruiter_pitch",
                        "description": "Generates 4 personalized, high-converting outreach message formats (LinkedIn Connection Note <300 chars, InMail, Formal Cover Email, Follow-Up).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_title": { "type": "string", "description": "Target job title" },
                                "company_name": { "type": "string", "description": "Company name", "default": "Hiring Team" },
                                "matched_skills": { "type": "string", "description": "Key skills (e.g. 'React, Node.js')", "default": "React" },
                                "candidate_name": { "type": "string", "description": "Your name", "default": "Candidate" }
                            },
                            "required": ["job_title"]
                        }
                    }
                ]
            }
        }

    # 5. Call Tool
    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "search_hiring_posts":
            keywords = args.get("keywords", "React Developer")
            location = args.get("location", "India")
            max_results = args.get("max_results", 10)

            posts = linkedin_finder.search_hiring_posts(
                keywords=keywords,
                location=location,
                timeframe="w",
                max_results=max_results
            )
            
            import json
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "success", "count": len(posts), "posts": posts}, indent=2)
                        }
                    ]
                }
            }

        if tool_name == "generate_recruiter_pitch":
            from core.pitch_generator import OutreachPitchGenerator
            job_title = args.get("job_title", "Software Engineer")
            company_name = args.get("company_name", "Hiring Team")
            matched_skills = [s.strip() for s in args.get("matched_skills", "React").split(",")]
            candidate_name = args.get("candidate_name", "Candidate")

            pitches = OutreachPitchGenerator.generate_suite(
                job_title=job_title,
                company_name=company_name,
                matched_skills=matched_skills,
                candidate_name=candidate_name
            )
            
            import json
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "success", "pitches": pitches}, indent=2)
                        }
                    ]
                }
            }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}


@app.post("/api/parse-resume", tags=["Resume"])
async def parse_resume_endpoint(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Parses candidate Resume PDF, extracts categorized technical skills,
    estimated seniority level, contact information, and target job titles.
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
    min_match_score: int = Form(35)
) -> Dict[str, Any]:
    """
    Upload Resume PDF -> Extracts Categorized Skills -> Searches Live LinkedIn Posts 
    -> Calculates Multi-Dimensional Weighted Match Scores -> Provides ATS Tailoring Advice.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        profile = resume_parser.parse(tmp_path)
        top_skills = profile.get("top_skills", [])
        primary_role = profile.get("primary_role", "Software Engineer")

        # Smart high-yield query selection
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
            "total_matches": len(ranked_jobs),
            "jobs": ranked_jobs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/api/search-hiring-posts", tags=["Jobs"])
def search_hiring_posts_endpoint(
    keywords: str = Query(..., description="Role or technical skill (e.g. 'React Developer', 'Python Backend')"),
    location: str = Query("India", description="Location (e.g. 'Bangalore', 'Remote', 'India')"),
    timeframe: str = Query("w", description="'d' (24h), 'w' (7 days), 'm' (month)"),
    remote_only: bool = Query(False, description="Filter only remote positions"),
    max_results: int = Query(10, description="Max results to fetch")
) -> Dict[str, Any]:
    """
    Searches real-time LinkedIn hiring posts with company name, work mode, 
    experience needed, salary hint, and apply links.
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
    job_title: str = Form(..., description="Job role title (e.g. 'React Developer')"),
    company_name: str = Form("Hiring Team", description="Target company name"),
    matched_skills: str = Form("React, Node.js", description="Comma-separated matched skills"),
    candidate_name: str = Form("Candidate", description="Your name for sign-off"),
    candidate_exp_years: int = Form(2, description="Years of candidate experience")
) -> Dict[str, Any]:
    """
    Generates 4 personalized, high-converting outreach formats:
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


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting OpenFinder v2.0 Professional Suite on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
