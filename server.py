"""
server.py
=========
Production-grade Model Context Protocol (MCP) Stdio Server for OpenFinder.

Compatible with:
- Claude Desktop
- Antigravity IDE
- Cursor & VS Code MCP Extensions
- Any standard JSON-RPC 2.0 Stdio Client across Windows, macOS, and Linux.

Architecture:
- High-Performance Hybrid Runner:
  1. Direct in-process execution via `OpenFinderService` (Ultra-low latency, zero network hops).
  2. Automatic HTTP API fallback if remote endpoint is configured.
- Complete Tools Suite:
  - `search_opportunities`: Exact freshness (past-1h to past-7d), ATS resume matching, and opportunity ranking.
  - `upload_resume`: PDF CV parsing & persistent profile creation.
  - `upload_resume_text`: Direct plain-text CV ingestion without disk files.
  - `get_candidate_profile`: Retrieve stored candidate profiles across conversational turns.
  - `generate_recruiter_pitch`: 1-Click Mailto, Gmail, and Outlook deep links + 4 outreach formats.
  - `parse_linkedin_post`: Single post intelligence extractor.
  - `parse_resume`: Stateless resume parser.
  - `search_posts`: Global posts search with horizontal Markdown table formatting.
  - `search_jobs_by_resume`: Combined PDF upload + immediate matching.
- Robust stdio loop with UTF-8 encoding safeguards and graceful error isolation.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure UTF-8 stdout/stderr on Windows terminals
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

from dotenv import load_dotenv
load_dotenv()

from core.linkedin_finder import LinkedInFinder
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor
from core.resume_parser import ResumeParser
from core.service import OpenFinderService

# Initialize local in-process service engine
service = OpenFinderService()
resume_parser = ResumeParser()
linkedin_finder = LinkedInFinder()

# Optional remote fallback URL
REMOTE_URL = os.environ.get("OPENFINDER_REMOTE_URL", "").rstrip("/")

# ============================================================================
# 1. MCP TOOLS TAXONOMY SPECIFICATION
# ============================================================================

TOOLS = [
    {
        "name": "search_opportunities",
        "description": (
            "Canonical search tool discovering verified LinkedIn recruiter hiring /posts/ with exact "
            "freshness validation ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d', 'past-7d'), "
            "directional hiring intent, and opportunity ranking against candidate profile or inline skills."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Role or tech stack (e.g. 'React Developer', 'Python FastAPI')",
                    "default": "Software Engineer"
                },
                "location": {
                    "type": "string",
                    "description": "Target city/country (e.g. 'Bangalore', 'Remote', 'India')",
                    "default": "India"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Freshness window: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d', 'past-7d'",
                    "default": "past-24h"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max opportunities to return (default: 20)",
                    "default": 20
                },
                "remote_only": {
                    "type": "boolean",
                    "description": "Filter for remote positions only",
                    "default": False
                },
                "candidate_profile_id": {
                    "type": "string",
                    "description": "Optional stored profile ID for ATS skill & experience matching"
                },
                "candidate_skills": {
                    "type": "string",
                    "description": "Comma-separated technical skills for instant ATS matching (e.g. 'React, Node.js, Express')"
                },
                "candidate_exp_years": {
                    "type": "integer",
                    "description": "Candidate total years of experience"
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Candidate full name"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "upload_resume_text",
        "description": (
            "Parses candidate plain text CV and stores a persistent profile for ATS matching across search turns. "
            "Returns a candidate_profile_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "resume_text": {
                    "type": "string",
                    "description": "Plain text content of the candidate's resume/CV."
                }
            },
            "required": ["resume_text"]
        }
    },
    {
        "name": "upload_resume",
        "description": "Upload a PDF resume to OpenFinder. Returns a candidate_profile_id for personalized job searches.",
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
        "description": "Retrieve a stored candidate profile by its unique candidate_profile_id.",
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
        "name": "generate_recruiter_pitch",
        "description": (
            "Generates 4 personalized recruiter outreach formats (Connection Note <300 chars, InMail, Formal Cover Email, "
            "and 1-Click 'Open in Mail App', 'Open in Gmail Web', and 'Open in Outlook Web' deep links)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_title": {
                    "type": "string",
                    "description": "Target job title"
                },
                "company_name": {
                    "type": "string",
                    "description": "Target company name",
                    "default": "Hiring Team"
                },
                "matched_skills": {
                    "type": "string",
                    "description": "Comma-separated matched skills",
                    "default": "Python, FastAPI"
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Candidate full name",
                    "default": "Candidate"
                },
                "candidate_exp_years": {
                    "type": "integer",
                    "description": "Candidate years of experience",
                    "default": 2
                },
                "recipient_name": {
                    "type": "string",
                    "description": "Recruiter / Hiring Manager name"
                },
                "recipient_email": {
                    "type": "string",
                    "description": "Recruiter contact email (e.g. 'hr@company.com')"
                }
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
                "post_url": {
                    "type": "string",
                    "description": "Direct LinkedIn /posts/ URL"
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Candidate full name for sign-off",
                    "default": "Candidate"
                },
                "candidate_exp_years": {
                    "type": "integer",
                    "description": "Candidate years of experience",
                    "default": 2
                }
            },
            "required": ["post_url"]
        }
    },
    {
        "name": "parse_resume",
        "description": "Parse a PDF resume and extract structured candidate data without persisting a profile.",
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
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the PDF resume."
                },
                "location": {
                    "type": "string",
                    "description": "Target location",
                    "default": "India"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Freshness filter",
                    "default": "past-24h"
                },
                "remote_only": {
                    "type": "boolean",
                    "default": False
                },
                "min_match_score": {
                    "type": "integer",
                    "description": "Minimum ATS match score (0-100)",
                    "default": 35
                }
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
                "keywords": {
                    "type": "string",
                    "description": "Role or skill (e.g. 'React Developer')"
                },
                "location": {
                    "type": "string",
                    "description": "Location (e.g. 'Bangalore', 'Remote')",
                    "default": "India"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Freshness filter",
                    "default": "past-24h"
                },
                "remote_only": {
                    "type": "boolean",
                    "default": False
                },
                "max_results": {
                    "type": "integer",
                    "default": 20
                }
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "search_posts",
        "description": "Search LinkedIn Posts tab globally by keyword with freshness filters and horizontal Markdown table output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Search keywords (e.g. 'React Developer hiring Bangalore')"
                },
                "date_posted": {
                    "type": "string",
                    "description": "Recency: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'",
                    "default": "past-24h"
                },
                "max_results": {
                    "type": "integer",
                    "default": 20
                }
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "linkedin_resume_match",
        "description": (
            "LinkedIn-Session-Exclusive, Resume-Mandatory Opportunity Finder. "
            "Fetches ONLY live, authenticated LinkedIn /posts/ hiring announcements — "
            "NO curated repository, NO Yahoo/DuckDuckGo search engine fallbacks. "
            "Results are strictly filtered and ranked by 6-factor ATS match score computed from "
            "the candidate's uploaded resume. Each result includes matched skills, missing skills, "
            "projected score if upskilled, and auto-generated outreach pitches for posts with recruiter emails. "
            "Requires: (1) resume uploaded via upload_resume or upload_resume_text, "
            "(2) LINKEDIN_LI_AT session cookie configured in .env."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate_profile_id": {
                    "type": "string",
                    "description": "Mandatory — ID returned by upload_resume or upload_resume_text"
                },
                "location": {
                    "type": "string",
                    "description": "Target city/country (e.g. 'Bangalore', 'Remote', 'India')",
                    "default": "India"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Freshness window: 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'",
                    "default": "past-24h"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max opportunities to return (default: 20, max: 50)",
                    "default": 20
                },
                "min_match_score": {
                    "type": "integer",
                    "description": "Minimum ATS resume match score 0-100 to include a result (default: 40)",
                    "default": 40
                },
                "remote_only": {
                    "type": "boolean",
                    "description": "If true, return only remote-friendly positions",
                    "default": False
                }
            },
            "required": ["candidate_profile_id"]
        }
    },
    {
        "name": "bulk_harvest_opportunities",
        "description": "Performs wide-matrix parallel search and deep pagination to harvest 50-200+ verified hiring posts with composite deduplication, numerical intent scoring (>=60), and ATS ranking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "roles": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "List of job roles/titles to search (e.g. ['React Developer', 'MERN Stack'])"
                },
                "locations": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "List of locations to search (e.g. ['Bangalore', 'Chennai', 'Remote'])"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Freshness window ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d')",
                    "default": "past-7d"
                },
                "target_count": {
                    "type": "integer",
                    "description": "Target number of verified opportunities to return (default: 50, max: 200)",
                    "default": 50
                },
                "min_intent_score": {
                    "type": "integer",
                    "description": "Minimum numerical hiring intent score threshold 0-100 (default: 60)",
                    "default": 60
                },
                "max_time_seconds": {
                    "type": "integer",
                    "description": "Maximum execution time budget in seconds (default: 25)",
                    "default": 25
                },
                "adaptive_mode": {
                    "type": "boolean",
                    "description": "Enable autonomous keyword & location discovery wave (default: true)",
                    "default": True
                },
                "candidate_profile_id": {
                    "type": "string",
                    "description": "Optional stored candidate profile ID for ATS scoring"
                }
            }
        }
    },
    {
        "name": "classify_hiring_post",
        "description": "AI-powered Hiring Intent Classifier: Determines if a LinkedIn post is a genuine recruiter/founder hiring opportunity vs job-seeker outreach, edtech course promotion, or viral fluff with structured entity extraction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Full LinkedIn post text content"
                },
                "author": {
                    "type": "string",
                    "description": "Author name or headline",
                    "default": ""
                },
                "url": {
                    "type": "string",
                    "description": "Optional post URL for caching",
                    "default": ""
                },
                "target_role": {
                    "type": "string",
                    "description": "Expected target role",
                    "default": "Software Engineer"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "prewarm_cache",
        "description": "Autonomous cache pre-warmer: Pre-populates SQLite cache and curated repository for high-frequency queries to enable instant (<50ms) search responses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "roles": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Roles to pre-warm (e.g. ['React Developer', 'Python Developer'])"
                },
                "locations": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Locations to pre-warm (e.g. ['India', 'Bangalore', 'Remote'])"
                },
                "timeframe": {
                    "type": "string",
                    "default": "past-24h"
                }
            }
        }
    }
]

# ============================================================================
# 2. LOCAL IN-PROCESS & REMOTE TOOL HANDLER
# ============================================================================

async def handle_tool(name: str, args: Dict[str, Any]) -> str:
    """Executes requested tool directly in-process or via remote API."""
    if REMOTE_URL:
        # Remote Proxy Mode
        import httpx
        async with httpx.AsyncClient() as client:
            if name == "upload_resume":
                fp = Path(args["file_path"])
                with fp.open("rb") as f:
                    resp = await client.post(f"{REMOTE_URL}/api/upload-resume", files={"file": (fp.name, f, "application/pdf")}, timeout=60.0)
                return json.dumps(resp.json(), ensure_ascii=False, indent=2)

            elif name == "search_opportunities":
                params = {k: v for k, v in args.items() if v is not None}
                resp = await client.get(f"{REMOTE_URL}/api/search-opportunities", params=params, timeout=60.0)
                return json.dumps(resp.json(), ensure_ascii=False, indent=2)

    # In-Process Direct Execution Mode (Ultra-Fast & Reliable)
    if name == "search_opportunities":
        result = await service.search_opportunities_async(
            query=args.get("query", "Software Engineer"),
            location=args.get("location", "India"),
            timeframe=args.get("timeframe", "past-24h"),
            max_results=args.get("max_results", 20),
            remote_only=args.get("remote_only", False),
            candidate_profile_id=args.get("candidate_profile_id"),
            candidate_skills=args.get("candidate_skills"),
            candidate_exp_years=args.get("candidate_exp_years"),
            candidate_name=args.get("candidate_name")
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "upload_resume_text":
        result = service.upload_resume_text(args.get("resume_text", ""))
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "upload_resume":
        fp = Path(args["file_path"])
        if not fp.exists():
            return json.dumps({"status": "error", "error": f"File not found: {fp}"}, indent=2)
        result = service.upload_resume(str(fp), filename=fp.name)
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "get_candidate_profile":
        pid = args.get("profile_id") or args.get("candidate_profile_id", "")
        result = service.get_candidate_profile(pid)
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "generate_recruiter_pitch":
        matched = args.get("matched_skills", "Python, FastAPI")
        matched_list = [s.strip() for s in matched.split(",") if s.strip()] if isinstance(matched, str) else list(matched)
        result = OutreachPitchGenerator.generate_suite(
            job_title=args.get("job_title", "Software Engineer"),
            company_name=args.get("company_name", "Hiring Team"),
            matched_skills=matched_list,
            candidate_name=args.get("candidate_name", "Candidate"),
            candidate_exp_years=int(args.get("candidate_exp_years", 2)),
            recipient_name=args.get("recipient_name", "Hiring Manager"),
            recipient_email=args.get("recipient_email")
        )
        return json.dumps({"status": "success", "pitches": result}, ensure_ascii=False, indent=2)

    elif name == "parse_linkedin_post":
        result = await LinkedInPostExtractor.extract_from_url_async(
            url=args.get("url", ""),
            candidate_name=args.get("candidate_name", "Candidate"),
            candidate_exp_years=int(args.get("candidate_exp_years", 2)),
            target_role=args.get("target_role")
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "parse_resume":
        fp = Path(args["file_path"])
        if not fp.exists():
            return json.dumps({"status": "error", "error": f"File not found: {fp}"}, indent=2)
        result = resume_parser.parse(str(fp))
        return json.dumps({"status": "success", "profile": result}, ensure_ascii=False, indent=2)

    elif name == "search_jobs_by_resume":
        fp = Path(args["file_path"])
        if not fp.exists():
            return json.dumps({"status": "error", "error": f"File not found: {fp}"}, indent=2)
        profile = resume_parser.parse(str(fp))
        top_skills = profile.get("top_skills", [])
        primary_role = profile.get("primary_role", "Software Engineer")
        search_kw = f"{top_skills[0]} {top_skills[1]}" if len(top_skills) >= 2 else primary_role

        posts = linkedin_finder.search_hiring_posts(
            keywords=search_kw,
            location=args.get("location", "India"),
            timeframe=args.get("timeframe", "past-24h"),
            remote_only=args.get("remote_only", False),
            max_results=20
        )
        from core.matcher import JobMatcher
        ranked = JobMatcher.rank_and_score_posts(profile, posts, min_score=args.get("min_match_score", 30))
        return json.dumps({"status": "success", "candidate_profile": profile, "total_matches": len(ranked), "jobs": ranked}, ensure_ascii=False, indent=2)

    elif name in ["search_linkedin_hiring", "search_posts"]:
        kw = args.get("keywords") or args.get("query", "Software Engineer")
        dt = args.get("date_posted") or args.get("timeframe", "past-24h")
        posts = linkedin_finder.search_posts(
            keywords=kw,
            date_posted=dt,
            max_results=args.get("max_results", 20)
        )
        table = LinkedInFinder.format_as_markdown_table(posts)
        return json.dumps({"status": "success", "count": len(posts), "markdown_table": table, "posts": posts}, ensure_ascii=False, indent=2)

    elif name == "linkedin_resume_match":
        res = await service.linkedin_resume_match_async(
            candidate_profile_id=args.get("candidate_profile_id", ""),
            location=args.get("location", "India"),
            timeframe=args.get("timeframe", "past-24h"),
            max_results=int(args.get("max_results", 20)),
            min_match_score=int(args.get("min_match_score", 40)),
            remote_only=bool(args.get("remote_only", False)),
        )
        return json.dumps(res, ensure_ascii=False, indent=2)

    elif name == "bulk_harvest_opportunities":
        res = await service.bulk_harvest_opportunities_async(
            roles=args.get("roles"),
            locations=args.get("locations"),
            timeframe=args.get("timeframe", "past-7d"),
            target_count=int(args.get("target_count", 50)),
            min_intent_score=int(args.get("min_intent_score", 60)),
            max_time_seconds=int(args.get("max_time_seconds", 25)),
            adaptive_mode=bool(args.get("adaptive_mode", True)),
            candidate_profile_id=args.get("candidate_profile_id")
        )
        return json.dumps(res, ensure_ascii=False, indent=2)

    elif name == "classify_hiring_post":
        res = await service.classify_hiring_post_async(
            text=args.get("text", ""),
            author=args.get("author", ""),
            url=args.get("url", ""),
            target_role=args.get("target_role")
        )
        return json.dumps(res, ensure_ascii=False, indent=2)

    elif name == "prewarm_cache":
        res = await service.prewarm_cache_async(
            roles=args.get("roles"),
            locations=args.get("locations"),
            timeframe=args.get("timeframe", "past-24h")
        )
        return json.dumps(res, ensure_ascii=False, indent=2)

    else:
        raise ValueError(f"Unknown tool: {name}")


# ============================================================================
# 3. ROBUST CROSS-PLATFORM MCP STDIO SERVER LOOP
# ============================================================================

def send_response(obj: Dict[str, Any]):
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
                    "serverInfo": {"name": "openfinder", "version": "3.0.0"}
                }
            })

        # ── ping ──
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})

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

        # ── notifications ──
        elif method and method.startswith("notifications/"):
            pass

        # ── unknown method fallback ──
        elif req_id is not None:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            })


if __name__ == "__main__":
    asyncio.run(main())
