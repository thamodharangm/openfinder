"""
api_server.py
=============
Production-grade Universal AI Job Catcher & Multi-Protocol API Server for OpenFinder.

Features:
- Dual Protocol Architecture:
  1. Claude Web Custom Connector (OAuth 2.0 Auto-Auth + MCP SSE Transport + JSON-RPC 2.0).
  2. ChatGPT OpenAPI Actions (Strict JSON Schema validation & REST endpoints).
  3. FastAPI Web Application Server with Swagger UI (/docs) and ReDoc (/redoc).
- Comprehensive Tools Suite:
  - `search_opportunities`: Exact freshness (past-1h to past-7d), ATS resume matching, and opportunity ranking.
  - `upload_resume_text`: Instant plain-text CV ingestion without multipart file upload.
  - `get_candidate_profile`: Retrieve stored candidate profile across conversational turns.
  - `generate_recruiter_pitch`: 1-Click composer deep links (Mailto, Gmail, Outlook) & multi-persona outreach suites.
  - `parse_linkedin_post`: Single LinkedIn /posts/ URL intelligence extraction.
  - `search_posts` & `search_hiring_posts`: Global posts search with horizontal Markdown table formatting.
- Async lifespan management, robust error boundaries, and cross-platform UTF-8 terminal encoding.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Union
import urllib.parse
import uuid

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

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from core.linkedin_finder import LinkedInFinder
from core.linkedin_session import LinkedInSessionSearch
from core.matcher import JobMatcher
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor
from core.resume_parser import ResumeParser
from core.service import OpenFinderService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("openfinder")

# Active SSE sessions for Claude MCP Connectors
sessions: Dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI Lifespan Manager for startup and shutdown hooks."""
    logger.info("🚀 [OpenFinder] Initializing Dual Protocol API Server...")
    # Pre-warm services
    _ = OpenFinderService()
    yield
    logger.info("🛑 [OpenFinder] Shutting down API Server. Cleaning active sessions...")
    sessions.clear()


app = FastAPI(
    title="OpenFinder - Universal MCP Job Connector for Freshers & Experienced",
    description="Full Dual Protocol API supporting Claude Web Connectors (MCP SSE & JSON-RPC) and ChatGPT OpenAPI Actions.",
    version="2.0.0",
    lifespan=lifespan,
    servers=[
        {"url": "https://openfinder.onrender.com", "description": "Production OpenFinder API Server"}
    ]
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = OpenFinderService()
resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()


# ==========================================================
# 🟢 HEALTH & DIAGNOSTICS ENDPOINTS
# ==========================================================

@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
def health_check():
    """System health check and diagnostics."""
    session_health = LinkedInSessionSearch.check_session_health()
    profile_stats = service.profile_store.get_stats()
    return {
        "status": "online",
        "service": "OpenFinder Universal AI Connector",
        "version": "2.0.0",
        "chatgpt_actions_ready": True,
        "claude_connectors_ready": True,
        "linkedin_authenticated": session_health.get("valid", False),
        "candidate_profiles_stored": profile_stats.get("total_saved_profiles", 0),
        "docs_url": "/docs",
        "openapi_url": "/openapi.json"
    }


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


@app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@app.get("/.well-known/openid-configuration", include_in_schema=False)
def oauth_metadata_discovery(request: Request):
    base_url = get_public_base_url(request)
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256", "plain"]
    }


@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def oauth_protected_resource_discovery(request: Request):
    base_url = get_public_base_url(request)
    return {
        "resource": base_url,
        "authorization_servers": [base_url]
    }


@app.post("/register", include_in_schema=False)
async def dynamic_client_register(request: Request):
    """RFC 7591 compliant Dynamic Client Registration for Claude Connectors."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    base_url = get_public_base_url(request)
    redirect_uris = body.get("redirect_uris", ["https://claude.ai", "https://chatgpt.com"])
    client_name = body.get("client_name", "Claude")

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


@app.api_route("/oauth/authorize", methods=["GET", "POST"], include_in_schema=False)
async def oauth_authorize(
    request: Request,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
    client_id: Optional[str] = None
):
    """Instant zero-click auto-authorization for Claude Connectors."""
    if not redirect_uri:
        redirect_uri = request.query_params.get("redirect_uri")
    if not state:
        state = request.query_params.get("state")

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
        logger.info(f"🔀 [Claude OAuth] Auto-approving & redirecting to: {target[:70]}...")
        return RedirectResponse(url=target, status_code=302)

    return {"status": "authorized", "code": "openfinder_auth_code"}


@app.api_route("/oauth/token", methods=["GET", "POST"], include_in_schema=False)
async def oauth_token(request: Request):
    """Returns valid bearer & refresh token to Claude Connectors."""
    return {
        "access_token": "openfinder_secure_bearer_token",
        "token_type": "Bearer",
        "expires_in": 86400,
        "refresh_token": "openfinder_refresh_token",
        "scope": "read write"
    }


@app.get("/sse", include_in_schema=False)
@app.get("/mcp", include_in_schema=False)
async def mcp_sse_endpoint(request: Request):
    """Standard MCP SSE Transport for Claude Web Connectors."""
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    sessions[session_id] = queue

    async def event_generator():
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


@app.post("/sse", include_in_schema=False)
@app.post("/messages", include_in_schema=False)
@app.post("/", include_in_schema=False)
@app.post("/mcp", include_in_schema=False)
async def mcp_message_handler(request: Request):
    """Handles JSON-RPC 2.0 messages from Claude Connectors."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})
    client_proto = params.get("protocolVersion", "2024-11-05")

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
        return Response(status_code=200)

    # 3. Ping
    elif method == "ping":
        response_payload = {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # 4. Tools List
    elif method == "tools/list":
        response_payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_opportunities",
                        "description": "Canonical search tool discovering verified LinkedIn recruiter hiring /posts/ with exact freshness validation (past-1h, past-4h, past-12h, past-24h, past-7d), directional hiring intent, and opportunity ranking against candidate profile or inline skills.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": { "type": "string", "description": "Job role or technical skills (e.g. 'React Developer', 'Python FastAPI')", "default": "React Developer" },
                                "location": { "type": "string", "description": "City or Region (e.g. 'Bangalore', 'Remote', 'India')", "default": "India" },
                                "timeframe": { "type": "string", "description": "Freshness window ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d')", "default": "past-24h" },
                                "max_results": { "type": "integer", "description": "Max opportunities (1-30)", "default": 23 },
                                "remote_only": { "type": "boolean", "description": "Filter for remote positions only", "default": False },
                                "candidate_profile_id": { "type": "string", "description": "Optional stored candidate profile ID for ATS skill & experience matching" },
                                "candidate_skills": { "type": "string", "description": "Comma-separated technical skills (e.g. 'React, Node.js, Express, MongoDB')" },
                                "candidate_exp_years": { "type": "integer", "description": "Candidate years of experience", "default": 1 },
                                "candidate_name": { "type": "string", "description": "Candidate full name" }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "upload_resume_text",
                        "description": "Parses candidate plain text CV and stores persistent profile for ATS matching across search turns.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "resume_text": { "type": "string", "description": "Plain text content of the candidate's resume/CV" }
                            },
                            "required": ["resume_text"]
                        }
                    },
                    {
                        "name": "get_candidate_profile",
                        "description": "Retrieves a stored candidate resume profile by its unique candidate_profile_id.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "candidate_profile_id": { "type": "string", "description": "Unique candidate profile ID (e.g. 'prof_a1b2c3d4e5f6')" }
                            },
                            "required": ["candidate_profile_id"]
                        }
                    },
                    {
                        "name": "generate_recruiter_pitch",
                        "description": "Generates 4 personalized recruiter outreach formats (Connection Note <300 chars, InMail, Formal Cover Email with 1-Click 'Open in Mail App' button/mailto deep link, Follow-Up).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_title": { "type": "string", "description": "Target job title" },
                                "company_name": { "type": "string", "description": "Target company name", "default": "Hiring Team" },
                                "matched_skills": { "type": "string", "description": "Key candidate skills", "default": "React" },
                                "candidate_name": { "type": "string", "description": "Candidate name", "default": "Candidate" },
                                "candidate_exp_years": { "type": "integer", "description": "Candidate total years of experience", "default": 1 },
                                "recipient_name": { "type": "string", "description": "Recruiter / Hiring Manager name", "default": "Hiring Team" },
                                "recipient_email": { "type": "string", "description": "Recruiter contact email (e.g. 'hr@company.com')" }
                            },
                            "required": ["job_title"]
                        }
                    },
                    {
                        "name": "parse_linkedin_post",
                        "description": "Extracts author, hiring company, direct HR emails, phone numbers, tech stack, and tailored recruiter pitches from any LinkedIn /posts/ URL.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "post_url": { "type": "string", "description": "The direct LinkedIn post URL (e.g. https://www.linkedin.com/posts/...)" },
                                "candidate_name": { "type": "string", "description": "Candidate's full name for customized pitches", "default": "Candidate" },
                                "candidate_exp_years": { "type": "integer", "description": "Candidate's total years of experience", "default": 0 }
                            },
                            "required": ["post_url"]
                        }
                    },
                    {
                        "name": "search_posts",
                        "description": "Searches global LinkedIn /posts/ by keyword (the 'Posts' tab) with exact freshness filters ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d') and extracts HR contact emails, phone numbers, and tech stack. CRITICAL DISPLAY RULE: Always present results strictly as a horizontal Markdown table with columns: # | Company | Role | Experience | Location | Posted Time | HR Contact / Email | Direct Link. Never output vertical lists.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keywords": { "type": "string", "description": "Search query for LinkedIn posts (e.g. 'React Developer hiring Bangalore')" },
                                "date_posted": { "type": "string", "description": "Recency filter: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'", "default": "past-24h" },
                                "max_results": { "type": "integer", "description": "Max number of posts to fetch", "default": 23 }
                            },
                            "required": ["keywords"]
                        }
                    }
                ]
            }
        }

    # 5. Tools Call
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "search_opportunities":
            res = await service.search_opportunities_async(
                query=args.get("query", "React Developer"),
                location=args.get("location", "India"),
                timeframe=args.get("timeframe", "past-24h"),
                max_results=args.get("max_results", 10),
                remote_only=args.get("remote_only", False),
                candidate_profile_id=args.get("candidate_profile_id"),
                candidate_skills=args.get("candidate_skills"),
                candidate_exp_years=args.get("candidate_exp_years"),
                candidate_name=args.get("candidate_name")
            )
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, indent=2)}]}
            }

        elif tool_name == "upload_resume_text":
            resume_text = args.get("resume_text", "")
            res = service.upload_resume_text(resume_text)
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, indent=2)}]}
            }

        elif tool_name == "get_candidate_profile":
            prof = service.get_candidate_profile(args.get("candidate_profile_id", ""))
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(prof, indent=2)}]}
            }

        elif tool_name == "generate_recruiter_pitch":
            pitches = service.generate_pitch(
                job_title=args.get("job_title", "Software Engineer"),
                company_name=args.get("company_name", "Hiring Team"),
                matched_skills=[s.strip() for s in args.get("matched_skills", "React").split(",") if s.strip()],
                candidate_name=args.get("candidate_name", "Candidate"),
                candidate_exp_years=int(args.get("candidate_exp_years", 1)),
                recipient_name=args.get("recipient_name") or args.get("author"),
                recipient_email=args.get("recipient_email") or args.get("hr_email")
            )
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps({"status": "success", "pitches": pitches}, indent=2)}]}
            }

        elif tool_name == "parse_linkedin_post":
            post_data = await asyncio.to_thread(
                service.parse_linkedin_post,
                url=args.get("post_url", ""),
                candidate_profile_id=args.get("candidate_profile_id")
            )
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps({"status": "success", "post": post_data}, indent=2)}]}
            }

        elif tool_name == "search_posts":
            posts = await asyncio.to_thread(
                linkedin_finder.search_posts,
                keywords=args.get("keywords", "React Developer hiring"),
                date_posted=args.get("date_posted", "past-24h"),
                max_results=args.get("max_results", 23)
            )
            table = LinkedInFinder.format_as_markdown_table(posts)
            response_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps({"status": "success", "count": len(posts), "markdown_table": table, "posts": posts}, indent=2)}]}
            }

    try:
        if response_payload:
            session_id = request.query_params.get("session_id")
            if session_id and session_id in sessions:
                await sessions[session_id].put(response_payload)
                return Response(status_code=202)
            return JSONResponse(content=response_payload)

        return JSONResponse(
            content={"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}
        )
    except Exception as exc:
        logger.error(f"❌ [MCP Error] Exception during '{method}': {exc}")
        error_resp = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps({"status": "error", "error": str(exc)}, indent=2)}]}
        }
        session_id = request.query_params.get("session_id")
        if session_id and session_id in sessions:
            await sessions[session_id].put(error_resp)
            return Response(status_code=202)
        return JSONResponse(content=error_resp)


# ==========================================================
# 🟢 CANONICAL REST & CHATGPT OPENAPI ENDPOINTS
# ==========================================================

@app.post("/api/upload-resume", tags=["Resume"])
async def upload_resume_endpoint(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Uploads and parses candidate PDF resume, creating a persistent candidate profile."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        return service.upload_resume(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/api/upload-resume-text", tags=["Resume"])
async def upload_resume_text_endpoint(payload: Dict[str, str]) -> Dict[str, Any]:
    """Direct plain text resume ingestion."""
    text = payload.get("resume_text", "")
    return service.upload_resume_text(text)


@app.post("/api/create-candidate-profile", tags=["Resume"])
async def create_candidate_profile_endpoint(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates or updates a persistent candidate profile from JSON."""
    return service.create_candidate_profile(profile_data)


@app.get("/api/candidate-profile/{profile_id}", tags=["Resume"])
def get_candidate_profile_endpoint(profile_id: str) -> Dict[str, Any]:
    """Retrieves stored candidate profile by ID."""
    return service.get_candidate_profile(profile_id)


@app.get("/api/search-opportunities", tags=["Opportunities"])
@app.post("/api/search-opportunities", tags=["Opportunities"])
async def search_opportunities_endpoint(
    query: str = Query("React Developer", description="Role or tech stack"),
    location: str = Query("India", description="Target city/location"),
    timeframe: str = Query("past-24h", description="Freshness window ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d')"),
    max_results: int = Query(23, description="Max opportunities (1-30)"),
    remote_only: bool = Query(False, description="Filter for remote roles"),
    candidate_profile_id: Optional[str] = Query(None, description="Optional candidate profile ID"),
    candidate_skills: Optional[str] = Query(None, description="Comma-separated candidate skills"),
    candidate_exp_years: Optional[int] = Query(None, description="Candidate total years of experience"),
    candidate_name: Optional[str] = Query(None, description="Candidate name"),
    debug: bool = Query(False, description="Include funnel and latency metrics")
) -> Dict[str, Any]:
    """Canonical Opportunity Search endpoint."""
    try:
        return await service.search_opportunities_async(
            query=query,
            location=location,
            timeframe=timeframe,
            max_results=max_results,
            remote_only=remote_only,
            candidate_profile_id=candidate_profile_id,
            candidate_skills=candidate_skills,
            candidate_exp_years=candidate_exp_years,
            candidate_name=candidate_name,
            debug=debug
        )
    except Exception as e:
        logger.error(f"❌ [REST search-opportunities Error]: {e}")
        return {
            "status": "error",
            "query": query,
            "location": location,
            "timeframe": timeframe,
            "count": 0,
            "results": [],
            "message": f"Search encountered an exception: {str(e)}"
        }


@app.post("/api/generate-pitch", tags=["Outreach"])
def generate_pitch_endpoint(
    job_title: str = Form(..., description="Job role title"),
    company_name: str = Form("Hiring Team", description="Target company name"),
    matched_skills: str = Form("React, Node.js", description="Comma-separated matched skills"),
    candidate_name: str = Form("Candidate", description="Your name for sign-off"),
    candidate_exp_years: int = Form(2, description="Years of candidate experience"),
    recipient_email: Optional[str] = Form(None, description="Recruiter contact email")
) -> Dict[str, Any]:
    """Generates multi-persona outreach suite with 1-click mail deep links."""
    pitches = service.generate_pitch(
        job_title=job_title,
        company_name=company_name,
        matched_skills=[s.strip() for s in matched_skills.split(",") if s.strip()],
        candidate_name=candidate_name,
        candidate_exp_years=candidate_exp_years,
        recipient_email=recipient_email
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
    post_url: str = Query(..., description="Direct LinkedIn /posts/ URL"),
    candidate_name: str = Query("Candidate", description="Your name for outreach sign-off"),
    candidate_exp_years: int = Query(2, description="Your years of experience")
) -> Dict[str, Any]:
    """Extracts structured hiring intelligence from a LinkedIn post URL."""
    return service.parse_linkedin_post(
        url=post_url,
        candidate_profile_id=None
    )


@app.get("/api/search-posts", tags=["Post Search"])
@app.post("/api/search-posts", tags=["Post Search"])
def search_posts_endpoint(
    keywords: str = Query(..., description="Post keywords"),
    date_posted: str = Query("past-24h", description="Recency filter"),
    max_results: int = Query(10, description="Max posts to retrieve")
) -> Dict[str, Any]:
    """Searches LinkedIn /posts/ globally by keyword."""
    results = linkedin_finder.search_posts(
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


# ==========================================================
# 🟢 CHATGPT ACTIONS STRICT OPENAPI VALIDATION GENERATOR
# ==========================================================

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        servers=[
            {"url": "https://openfinder.onrender.com", "description": "Production OpenFinder API Server"}
        ]
    )

    def sanitize_schema(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                if "properties" not in node and "additionalProperties" not in node:
                    node["properties"] = {}
            for v in list(node.values()):
                sanitize_schema(v)
        elif isinstance(node, list):
            for item in node:
                sanitize_schema(item)

    sanitize_schema(schema)
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting OpenFinder v2.0 Universal Dual Protocol Server on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
