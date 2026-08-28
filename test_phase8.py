import sys
import os
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any
from fastapi.testclient import TestClient

# Ensure UTF-8 stdout on Windows
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

from core.service import OpenFinderService
from core.profile_store import CandidateProfileStore
from api_server import app


def test_resume_upload_and_profile_store():
    print("=" * 70)
    print("1. RUNNING RESUME UPLOAD & CANDIDATE PROFILE STORE TESTS")
    print("=" * 70)

    service = OpenFinderService()
    pdf_path = "sample_resume.pdf"
    assert os.path.exists(pdf_path), f"Sample resume not found: {pdf_path}"

    # 1. Upload and Parse
    res = service.upload_resume(pdf_path)
    assert res["status"] == "success", f"Resume upload failed: {res}"
    pid = res.get("candidate_profile_id")
    assert pid and pid.startswith("prof_"), f"Invalid candidate_profile_id: {pid}"
    assert "Thamodharan" in res.get("candidate_name", ""), f"Candidate name missed: {res}"
    assert len(res.get("top_skills", [])) > 0, "No skills extracted"
    print(f"  [PASS] Uploaded resume -> Created profile ID: {pid}")
    print(f"  [PASS] Candidate: {res['candidate_name']} ({res['seniority_level']}, {res['years_of_experience']} Yrs)")

    # 2. Retrieve Stored Profile
    fetched = service.get_candidate_profile(pid)
    assert fetched["status"] == "success", f"Profile fetch failed: {fetched}"
    prof = fetched["candidate_profile"]
    assert prof["candidate_profile_id"] == pid
    assert prof["candidate_name"] == res["candidate_name"]
    print(f"  [PASS] Successfully retrieved stored profile for ID: {pid}")

    print("✅ Resume Upload & Profile Store Tests: 100% PASSED\n")
    return pid


def test_search_with_and_without_profile(profile_id: str):
    print("=" * 70)
    print("2. RUNNING SEARCH WITH & WITHOUT CANDIDATE PROFILE")
    print("=" * 70)

    service = OpenFinderService()

    # 1. Search WITH Candidate Profile ID
    res_with_profile = service.search_opportunities(
        query="React Developer",
        location="Bangalore",
        timeframe="past-24h",
        max_results=3,
        candidate_profile_id=profile_id
    )
    assert res_with_profile["status"] == "success"
    assert res_with_profile["candidate_profile_id"] == profile_id
    assert res_with_profile["candidate_name"] is not None
    if res_with_profile["results"]:
        top = res_with_profile["results"][0]
        assert top["candidate_match_score"] is not None, "Candidate match score must be computed when profile provided"
        assert 0 <= top["candidate_match_score"] <= 100, f"Out of bounds match score: {top['candidate_match_score']}"
        assert 0 <= top["final_rank_score"] <= 100
        assert "https://www.linkedin.com/posts/" in top["post_url"]
        print(f"  [PASS] Search with Profile: Match Score: {top['candidate_match_score']}%, Final Rank: {top['final_rank_score']}/100")
        print(f"         Summary: {top['ranking_summary']}")

    # 2. Search WITHOUT Candidate Profile ID
    res_no_profile = service.search_opportunities(
        query="React Developer",
        location="Bangalore",
        timeframe="past-24h",
        max_results=3,
        candidate_profile_id=None
    )
    assert res_no_profile["status"] == "success"
    assert res_no_profile["candidate_profile_id"] is None
    assert res_no_profile["candidate_name"] is None
    if res_no_profile["results"]:
        top_no = res_no_profile["results"][0]
        assert top_no["candidate_match_score"] is None, "Candidate match score MUST be None when no profile provided"
        assert top_no["final_rank_score"] == top_no["post_quality_score"], "Final score must equal post quality score without profile"
        print(f"  [PASS] Search without Profile: Match Score is None, Final Rank: {top_no['final_rank_score']}/100 == Quality: {top_no['post_quality_score']}/100")

    print("✅ Search With & Without Profile Tests: 100% PASSED\n")


def test_fastapi_rest_endpoints(profile_id: str):
    print("=" * 70)
    print("3. RUNNING FASTAPI REST API CONTRACT TESTS")
    print("=" * 70)

    client = TestClient(app)

    # 1. Health check
    h_resp = client.get("/")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "online"
    print("  [PASS] GET / -> HTTP 200 Online")

    # 2. Upload resume via HTTP POST multipart/form-data
    with open("sample_resume.pdf", "rb") as f:
        up_resp = client.post("/api/upload-resume", files={"file": ("sample_resume.pdf", f, "application/pdf")})
    assert up_resp.status_code == 200
    up_data = up_resp.json()
    assert up_data["status"] == "success"
    http_pid = up_data["candidate_profile_id"]
    print(f"  [PASS] POST /api/upload-resume -> HTTP 200 (Created: {http_pid})")

    # 3. Get candidate profile
    p_resp = client.get(f"/api/candidate-profile/{http_pid}")
    assert p_resp.status_code == 200
    assert p_resp.json()["status"] == "success"
    print(f"  [PASS] GET /api/candidate-profile/{http_pid} -> HTTP 200")

    # 4. Search opportunities via HTTP GET
    s_resp = client.get(f"/api/search-opportunities?query=React+Developer&location=Bangalore&timeframe=past-24h&candidate_profile_id={http_pid}&max_results=2")
    assert s_resp.status_code == 200
    s_data = s_resp.json()
    assert s_data["status"] == "success"
    print(f"  [PASS] GET /api/search-opportunities -> HTTP 200 (Count: {s_data['count']})")

    print("✅ FastAPI REST API Contract Tests: 100% PASSED\n")


def test_claude_mcp_jsonrpc_contract(profile_id: str):
    print("=" * 70)
    print("4. RUNNING CLAUDE MCP JSON-RPC CONTRACT TESTS")
    print("=" * 70)

    client = TestClient(app)

    # 1. tools/list
    list_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    l_resp = client.post("/mcp", json=list_payload)
    assert l_resp.status_code == 200
    tools = l_resp.json()["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "search_opportunities" in tool_names, f"search_opportunities missing from tools: {tool_names}"
    assert "get_candidate_profile" in tool_names, f"get_candidate_profile missing from tools: {tool_names}"
    print(f"  [PASS] POST /mcp (tools/list) -> Exposed {len(tools)} tools: {', '.join(tool_names[:4])}...")

    # 2. tools/call search_opportunities
    call_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "search_opportunities",
            "arguments": {
                "query": "React Developer",
                "location": "Bangalore",
                "timeframe": "past-24h",
                "max_results": 2,
                "candidate_profile_id": profile_id
            }
        }
    }
    c_resp = client.post("/mcp", json=call_payload)
    assert c_resp.status_code == 200
    c_data = c_resp.json()
    assert "result" in c_data and "content" in c_data["result"]
    tool_out = json.loads(c_data["result"]["content"][0]["text"])
    assert tool_out["status"] == "success"
    print(f"  [PASS] POST /mcp (tools/call search_opportunities) -> Returned status: success, count: {tool_out['count']}")

    print("✅ Claude MCP JSON-RPC Contract Tests: 100% PASSED\n")


def test_security_and_zero_credential_leakage(profile_id: str):
    print("=" * 70)
    print("5. RUNNING SECURITY & ZERO CREDENTIAL LEAKAGE AUDIT")
    print("=" * 70)

    service = OpenFinderService()
    res = service.search_opportunities(
        query="React Developer",
        location="Bangalore",
        timeframe="past-24h",
        max_results=2,
        candidate_profile_id=profile_id,
        debug=True
    )

    serialized = json.dumps(res)

    forbidden_tokens = ["li_at", "JSESSIONID", "csrf-token", "AQED", "ajax:", "session_key"]
    for token in forbidden_tokens:
        assert token not in serialized, f"Security Breach: credential '{token}' found in API output!"

    # Ensure no internal filesystem paths in output
    assert "d:\\projects" not in serialized.lower(), "Local filesystem directory leaked in output!"

    print("  [PASS] Zero session credentials (li_at, JSESSIONID, CSRF) detected in output")
    print("  [PASS] Zero internal local filesystem paths detected in output")
    print("✅ Security & Zero Credential Leakage Audit: 100% PASSED\n")


if __name__ == "__main__":
    pid = test_resume_upload_and_profile_store()
    test_search_with_and_without_profile(pid)
    test_fastapi_rest_endpoints(pid)
    test_claude_mcp_jsonrpc_contract(pid)
    test_security_and_zero_credential_leakage(pid)
    print("=" * 70)
    print("🎉 ALL PHASE 8 PRODUCT INTEGRATION TESTS PASSED WITH ZERO ERRORS!")
    print("=" * 70)
