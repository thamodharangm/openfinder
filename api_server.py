from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
import shutil
import tempfile
import json
import asyncio
import uuid
from pathlib import Path
import sys

# Ensure UTF-8 stdout/stderr on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# Ensure root in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

from core.resume_parser import ResumeParser
from core.linkedin_finder import LinkedInFinder
from core.matcher import JobMatcher
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor

app = FastAPI(
    title="OpenFinder - Universal AI Career Scout & Claude Connector",
    description="Full Dual Protocol API supporting ChatGPT OpenAPI Actions and Claude Web Connectors (MCP SSE & JSON-RPC).",
    version="2.0.0"
)

# Enable CORS and bypass headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()

# Active SSE sessions
sessions: Dict[str, asyncio.Queue] = {}


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


from fastapi.responses import JSONResponse, Response, StreamingResponse, RedirectResponse

# ==========================================================
# 🟢 CLAUDE WEB CUSTOM CONNECTOR (OAUTH 2.0 & MCP PROTOCOL)
# ==========================================================

def get_public_base_url(request: Request) -> str:
    """Dynamically resolves the public HTTPS domain when behind tunnels or proxies."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "127.0.0.1:8000"
    proto = request.headers.get("x-forwarded-proto")
    if not proto:
        proto = "https" if any(k in host for k in ["loca.lt", "ngrok", "onrender.com", "railway.app"]) else "http"
    return f"{proto}://{host}"


@app.get("/.well-known/oauth-authorization-server")
def oauth_auth_server_discovery(request: Request):
    base_url = get_public_base_url(request)
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256", "plain"]
    }


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/{path:path}")
def oauth_protected_resource_discovery(request: Request):
    base_url = get_public_base_url(request)
    return {
        "resource": base_url,
        "authorization_servers": [base_url]
    }


@app.post("/register")
async def dynamic_client_register(request: Request):
    """
    RFC 7591 compliant Dynamic Client Registration for Claude Connectors.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    base_url = get_public_base_url(request)
    redirect_uris = body.get("redirect_uris", ["https://claude.ai", "https://chatgpt.com"])
    client_name = body.get("client_name", "Claude")

    import time
    return {
        "client_id": "openfinder_client_id",
        "client_secret": "openfinder_client_secret",
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "client_credentials", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "client_id_issued_at": int(time.time()),
        "client_secret_expires_at": 0,
        "registration_access_token": "openfinder_reg_token",
        "registration_client_uri": f"{base_url}/register"
    }


@app.api_route("/oauth/authorize", methods=["GET", "POST"])
async def oauth_authorize(
    request: Request,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
    client_id: Optional[str] = None
):
    """
    Instant zero-click auto-authorization for Claude Connectors.
    """
    if not redirect_uri:
        redirect_uri = request.query_params.get("redirect_uri")
    if not state:
        state = request.query_params.get("state")

    # If sent via form or json in POST
    if request.method == "POST" and not redirect_uri:
        try:
            form_or_json = await request.json()
            redirect_uri = form_or_json.get("redirect_uri", redirect_uri)
            state = form_or_json.get("state", state)
        except Exception:
            pass

    if redirect_uri:
        sep = "&" if "?" in redirect_uri else "?"
        state_param = f"&state={state}" if state else ""
        target = f"{redirect_uri}{sep}code=openfinder_auth_code{state_param}"
        print(f"🔀 [Claude OAuth] Auto-approving & redirecting Claude to: {target[:70]}...")
        return RedirectResponse(url=target, status_code=302)
    
    return {"status": "authorized", "code": "openfinder_auth_code"}


@app.api_route("/oauth/token", methods=["GET", "POST"])
async def oauth_token(request: Request):
    """
    Returns valid bearer & refresh token to Claude Connectors.
    """
    print("🔑 [Claude OAuth] Dispatched Bearer Access Token to Claude!")
    return {
        "access_token": "openfinder_secure_bearer_token",
        "token_type": "Bearer",
        "expires_in": 86400,
        "refresh_token": "openfinder_refresh_token",
        "scope": "read write"
    }


@app.get("/sse")
@app.get("/mcp")
async def mcp_sse_endpoint(request: Request):
    """
    Standard MCP SSE Transport for Claude Web Connectors (GET /sse or GET /mcp).
    """
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    sessions[session_id] = queue

    async def event_generator():
        # First send the endpoint event as per MCP specification
        endpoint_url = f"/messages?session_id={session_id}"
        yield f"event: endpoint\ndata: {endpoint_url}\n\n"

        while True:
            if await request.is_disconnected():
                sessions.pop(session_id, None)
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"event: message\ndata: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                # Keep-alive ping
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/sse")
@app.post("/messages")
@app.post("/")
@app.post("/mcp")
async def mcp_message_handler(request: Request):
    """
    Handles JSON-RPC 2.0 messages from Claude Connectors (POST /sse, POST /mcp, POST /messages).
    """
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})
    client_proto = params.get("protocolVersion", "2024-11-05")

    print(f"📥 [Claude Connector] Received MCP Method: '{method}' (ID: {req_id})")

    response_payload = None

    # 1. Initialize
    if method == "initialize":
        response_payload = {
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

    # 2. Notifications
    elif method == "notifications/initialized":
        print("✅ [Claude Connector] Initialized successfully by Claude!")
        return Response(status_code=200)

    # 3. Ping
    elif method == "ping":
        response_payload = {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # 4. Tools List
    elif method == "tools/list":
        print("🛠️ [Claude Connector] Claude requested tools list -> Returning 4 tools")
        response_payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_posts",
                        "description": "Searches global LinkedIn posts/content by keyword (the 'Posts' tab) with recency filters (past-24h, past-week, past-month) and extracts HR contact emails, phone numbers, and tech stack. CRITICAL DISPLAY RULE: Always present results strictly as a horizontal Markdown table with columns: # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link. Never output vertical lists.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keywords": {
                                    "type": "string",
                                    "description": "Search query for LinkedIn posts (e.g. 'React Developer hiring Bangalore')"
                                },
                                "date_posted": {
                                    "type": "string",
                                    "description": "Recency filter: 'past-24h', 'past-week', or 'past-month'",
                                    "default": "past-week"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Max number of posts to fetch",
                                    "default": 10
                                }
                            },
                            "required": ["keywords"]
                        }
                    },
                    {
                        "name": "parse_linkedin_post",
                        "description": "Extracts author, hiring company, direct HR emails, phone numbers, tech stack, and tailored recruiter pitches from any LinkedIn post URL.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "post_url": {
                                    "type": "string",
                                    "description": "The LinkedIn post URL (e.g. https://www.linkedin.com/posts/... or /feed/update/...)"
                                },
                                "candidate_name": {
                                    "type": "string",
                                    "description": "Candidate's full name for customized pitches",
                                    "default": "Candidate"
                                },
                                "candidate_exp_years": {
                                    "type": "integer",
                                    "description": "Candidate's total years of experience",
                                    "default": 0
                                }
                            },
                            "required": ["post_url"]
                        }
                    },
                    {
                        "name": "search_hiring_posts",
                        "description": "Searches real-time live LinkedIn recruiter hiring posts with direct post links and contact details. CRITICAL DISPLAY RULE: Always present results strictly as a horizontal Markdown table with columns: # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link. Never output vertical lists.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keywords": {
                                    "type": "string",
                                    "description": "Job role or tech stack (e.g. 'React Developer', 'MERN Stack')"
                                },
                                "location": {
                                    "type": "string",
                                    "description": "Location (e.g. 'Bangalore', 'Remote', 'India')",
                                    "default": "India"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Max results to fetch",
                                    "default": 10
                                }
                            },
                            "required": ["keywords"]
                        }
                    },
                    {
                        "name": "generate_recruiter_pitch",
                        "description": "Generates 4 personalized recruiter outreach formats (Connection Note <300 chars, InMail, Formal Cover Email, Follow-Up).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_title": { "type": "string", "description": "Target job title" },
                                "company_name": { "type": "string", "description": "Target company name", "default": "Hiring Team" },
                                "matched_skills": { "type": "string", "description": "Key candidate skills", "default": "React" },
                                "candidate_name": { "type": "string", "description": "Candidate name", "default": "Candidate" }
                            },
                            "required": ["job_title"]
                        }
                    }
                ]
            }
        }

    # 5. Tools Call
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "search_posts":
            keywords = args.get("keywords", "React Developer hiring")
            date_posted = args.get("date_posted", "past-week")
            max_results = args.get("max_results", 10)

            posts = linkedin_finder.search_posts(
                keywords=keywords,
                date_posted=date_posted,
                max_results=max_results
            )
            table = LinkedInFinder.format_as_markdown_table(posts)
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "success", "count": len(posts), "markdown_table": table, "posts": posts}, indent=2)
                        }
                    ]
                }
            }

        elif tool_name == "parse_linkedin_post":
            post_url = args.get("post_url")
            c_name = args.get("candidate_name", "Candidate")
            c_exp = args.get("candidate_exp_years", 0)

            cand_profile = None
            if c_name != "Candidate" or c_exp > 0:
                cand_profile = {
                    "name": c_name,
                    "experience_years": c_exp,
                    "skills": [],
                    "target_roles": []
                }

            post_data = LinkedInPostExtractor.extract_from_url(
                url=post_url,
                candidate_profile=cand_profile
            )

            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "success", "post": post_data}, indent=2)
                        }
                    ]
                }
            }

        elif tool_name == "search_hiring_posts":
            keywords = args.get("keywords", "React Developer")
            location = args.get("location", "India")
            max_results = args.get("max_results", 10)

            posts = linkedin_finder.search_hiring_posts(
                keywords=keywords,
                location=location,
                timeframe="w",
                max_results=max_results
            )
            table = LinkedInFinder.format_as_markdown_table(posts)

            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "success", "count": len(posts), "markdown_table": table, "posts": posts}, indent=2)
                        }
                    ]
                }
            }

        elif tool_name == "generate_recruiter_pitch":
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

            response_payload = {
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

    if response_payload:
        # Check if session_id query param exists for SSE routing
        session_id = request.query_params.get("session_id")
        if session_id and session_id in sessions:
            await sessions[session_id].put(response_payload)
            return Response(status_code=202)
        return JSONResponse(content=response_payload)

    return JSONResponse(
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}
    )


# ==========================================================
# 🟢 CHATGPT OPENAPI REST ENDPOINTS
# ==========================================================

@app.post("/api/parse-resume", tags=["Resume"])
async def parse_resume_endpoint(file: UploadFile = File(...)) -> Dict[str, Any]:
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
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        profile = resume_parser.parse(tmp_path)
        top_skills = profile.get("top_skills", [])
        primary_role = profile.get("primary_role", "Software Engineer")

        search_kw = primary_role
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
        return {"status": "error", "message": str(e)}


@app.post("/api/generate-pitch", tags=["Outreach"])
def generate_pitch_endpoint(
    job_title: str = Form(..., description="Job role title (e.g. 'React Developer')"),
    company_name: str = Form("Hiring Team", description="Target company name"),
    matched_skills: str = Form("React, Node.js", description="Comma-separated matched skills"),
    candidate_name: str = Form("Candidate", description="Your name for sign-off"),
    candidate_exp_years: int = Form(2, description="Years of candidate experience")
) -> Dict[str, Any]:
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


@app.get("/api/parse-post", tags=["Post Parser"])
@app.post("/api/parse-post", tags=["Post Parser"])
def parse_post_endpoint(
    post_url: str = Query(..., description="Direct LinkedIn Post URL or shortlink"),
    candidate_name: str = Query("Candidate", description="Your name for outreach sign-off"),
    candidate_exp_years: int = Query(2, description="Your years of experience")
) -> Dict[str, Any]:
    """
    Directly extracts structured hiring data (HR email, phone, skills, role)
    from any LinkedIn recruiter post URL and generates customized outreach pitches.
    """
    return LinkedInPostExtractor.extract_from_url(
        url=post_url,
        candidate_name=candidate_name,
        candidate_exp_years=candidate_exp_years
    )


@app.get("/api/search-posts", tags=["Post Search"])
@app.post("/api/search-posts", tags=["Post Search"])
def search_posts_endpoint(
    keywords: str = Query(..., description="Post keywords (e.g. 'React Developer hiring Bangalore')"),
    date_posted: str = Query("past-week", description="Recency filter ('past-24h', 'past-week', 'past-month')"),
    max_results: int = Query(10, description="Max posts to retrieve")
) -> Dict[str, Any]:
    """
    Searches LinkedIn posts/content globally by keyword (the "Posts" tab) with recency filters.
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
    import uvicorn
    print("🚀 Starting OpenFinder v2.0 Universal Dual Protocol Server on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
