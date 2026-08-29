"""
OpenFinder MCP Stdio Server
Proxies Model Context Protocol (MCP) tool requests to the OpenFinder engine.
Compatible with Claude Desktop, Cursor, and Antigravity across Windows, macOS, and Linux.
"""

import sys
import json
import asyncio
import httpx
from pathlib import Path

# Ensure UTF-8 stdout/stderr on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

BASE_URL = "https://openfinder.onrender.com"

# ────────────────────────────────────────────────
# Tool definitions
# ────────────────────────────────────────────────
TOOLS = [
    {
        "name": "upload_resume",
        "description": "Upload a PDF resume to OpenFinder. Returns a candidate_profile_id for personalised job searches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the candidate's PDF resume on disk."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "get_candidate_profile",
        "description": "Retrieve a stored candidate profile by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "string",
                    "description": "The candidate_profile_id returned by upload_resume."
                }
            },
            "required": ["profile_id"]
        }
    },
    {
        "name": "search_opportunities",
        "description": (
            "Search verified LinkedIn hiring posts with ATS skill matching and freshness filters. "
            "Optionally pass a candidate_profile_id or inline skills for ranked results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Role or tech stack (e.g. 'React Developer', 'Python FastAPI')", "default": "Software Engineer"},
                "location": {"type": "string", "description": "Target city/country (e.g. 'Bangalore', 'Remote', 'India')", "default": "India"},
                "timeframe": {"type": "string", "description": "Freshness: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d'", "default": "past-24h"},
                "max_results": {"type": "integer", "description": "Max opportunities (1-30)", "default": 20},
                "remote_only": {"type": "boolean", "description": "Filter remote roles only", "default": False},
                "candidate_profile_id": {"type": "string", "description": "Optional profile ID for ATS matching"},
                "candidate_skills": {"type": "string", "description": "Comma-separated skills (e.g. 'React.js, Node.js, MongoDB')"},
                "candidate_exp_years": {"type": "integer", "description": "Candidate total years of experience"},
                "candidate_name": {"type": "string", "description": "Candidate name"}
            },
            "required": []
        }
    },
    {
        "name": "parse_resume",
        "description": "Parse a PDF resume and extract structured candidate data (skills, experience, roles) without persisting a profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the candidate's PDF resume on disk."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "search_jobs_by_resume",
        "description": "Upload a resume PDF and immediately search for matching jobs. Returns ranked opportunities based on ATS skill fit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the PDF resume."},
                "location": {"type": "string", "description": "Target location", "default": "India"},
                "timeframe": {"type": "string", "description": "Freshness filter", "default": "past-24h"},
                "remote_only": {"type": "boolean", "default": False},
                "min_match_score": {"type": "integer", "description": "Minimum ATS match score (0-100)", "default": 35}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "search_linkedin_hiring",
        "description": "Search LinkedIn hiring posts by keywords and location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Role or skill (e.g. 'React Developer')"},
                "location": {"type": "string", "description": "Location (e.g. 'Bangalore', 'Remote')", "default": "India"},
                "timeframe": {"type": "string", "description": "Freshness filter", "default": "past-24h"},
                "remote_only": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 20}
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "generate_recruiter_pitch",
        "description": "Generate a personalized recruiter outreach pitch (LinkedIn note + cover email).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_title": {"type": "string", "description": "Target job role"},
                "company_name": {"type": "string", "default": "Hiring Team"},
                "matched_skills": {"type": "string", "description": "Comma-separated matched skills", "default": "Python, FastAPI"},
                "candidate_name": {"type": "string", "default": "Candidate"},
                "candidate_exp_years": {"type": "integer", "default": 2}
            },
            "required": ["job_title"]
        }
    },
    {
        "name": "parse_linkedin_post",
        "description": "Extract structured hiring data (HR email, phone, skills, role) from a LinkedIn post URL and generate outreach pitches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_url": {"type": "string", "description": "Direct LinkedIn /posts/ URL"},
                "candidate_name": {"type": "string", "default": "Candidate"},
                "candidate_exp_years": {"type": "integer", "default": 2}
            },
            "required": ["post_url"]
        }
    },
    {
        "name": "search_posts",
        "description": "Search LinkedIn Posts tab globally by keyword with freshness filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Search keywords (e.g. 'React Developer hiring Bangalore')"},
                "date_posted": {"type": "string", "description": "Recency: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'", "default": "past-24h"},
                "max_results": {"type": "integer", "default": 20}
            },
            "required": ["keywords"]
        }
    }
]


# ────────────────────────────────────────────────
# Tool handlers
# ────────────────────────────────────────────────
async def call_api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    url = f"{BASE_URL}{path}"
    resp = await client.request(method, url, timeout=60.0, **kwargs)
    resp.raise_for_status()
    return resp.json()


async def handle_tool(name: str, args: dict) -> str:
    async with httpx.AsyncClient() as client:
        if name == "upload_resume":
            fp = Path(args["file_path"])
            with fp.open("rb") as f:
                result = await call_api(client, "POST", "/api/upload-resume",
                                        files={"file": (fp.name, f, "application/pdf")})
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "get_candidate_profile":
            result = await call_api(client, "GET", f"/api/candidate-profile/{args['profile_id']}")
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "search_opportunities":
            params = {k: v for k, v in args.items() if v is not None}
            result = await call_api(client, "GET", "/api/search-opportunities", params=params)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "parse_resume":
            fp = Path(args["file_path"])
            with fp.open("rb") as f:
                result = await call_api(client, "POST", "/api/parse-resume",
                                        files={"file": (fp.name, f, "application/pdf")})
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "search_jobs_by_resume":
            fp = Path(args["file_path"])
            extra = {k: v for k, v in args.items() if k != "file_path"}
            with fp.open("rb") as f:
                result = await call_api(client, "POST", "/api/search-jobs-by-resume",
                                        files={"file": (fp.name, f, "application/pdf")},
                                        data=extra)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "search_linkedin_hiring":
            params = {k: v for k, v in args.items() if v is not None}
            result = await call_api(client, "GET", "/api/search-hiring-posts", params=params)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "generate_recruiter_pitch":
            result = await call_api(client, "POST", "/api/generate-pitch", data=args)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "parse_linkedin_post":
            params = {k: v for k, v in args.items() if v is not None}
            result = await call_api(client, "GET", "/api/parse-post", params=params)
            return json.dumps(result, ensure_ascii=False, indent=2)

        elif name == "search_posts":
            params = {k: v for k, v in args.items() if v is not None}
            result = await call_api(client, "GET", "/api/search-posts", params=params)
            return json.dumps(result, ensure_ascii=False, indent=2)

        else:
            raise ValueError(f"Unknown tool: {name}")


# ────────────────────────────────────────────────
# Robust Cross-Platform MCP stdio loop
# ────────────────────────────────────────────────
def send_response(obj: dict):
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


async def main():
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line_clean = line.strip()
        if not line_clean:
            continue
        try:
            msg = json.loads(line_clean)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        req_id = msg.get("id")

        # ── initialize ──
        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "openfinder", "version": "2.0.0"}
                }
            })

        # ── tools/list ──
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS}
            })

        # ── tools/call ──
        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name")
            tool_args = msg.get("params", {}).get("arguments", {})
            try:
                result_text = await handle_tool(tool_name, tool_args)
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}],
                        "isError": False
                    }
                })
            except Exception as e:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True
                    }
                })

        # ── notifications (no response needed) ──
        elif method and method.startswith("notifications/"):
            pass

        # ── unknown ──
        elif req_id is not None:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            })


if __name__ == "__main__":
    asyncio.run(main())
