import sys
import os
import time
import json
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

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

from config import CACHE_DB_PATH, ErrorCodes
from core.linkedin_urls import is_valid_linkedin_post_url
from core.time_utils import is_within_window, parse_timestamp, calculate_age
from core.hiring_intent import HiringIntentClassifier, RoleRelevanceMatcher, LocationRelevanceMatcher, ExperienceRelevanceMatcher
from core.ranking import OpportunityRanker
from core.cache import SearchCache
from core.post_extractor import LinkedInPostExtractor
from core.resume_parser import ResumeParser


def test_url_security_and_strict_rejection():
    print("=" * 70)
    print("1. RUNNING URL SECURITY & STRICT REJECTION TESTS")
    print("=" * 70)

    forbidden_urls = [
        "https://www.linkedin.com/jobs/view/123456789/",
        "https://www.linkedin.com/jobs/search/?keywords=react",
        "https://www.linkedin.com/feed/update/urn:li:activity:7498493404704591873/",
        "https://www.linkedin.com/activity-7498493404704591873/",
        "https://www.linkedin.com/company/google/jobs/",
        "https://www.linkedin.com/pulse/future-of-ai-article/",
        "https://www.linkedin.com/learning/react-essential-training/",
        "https://www.linkedin.com/school/stanford-university/",
        "https://www.linkedin.com/salary/software-engineer-salaries",
        "https://www.linkedin.com/directory/jobs/",
        "https://lnkd.in/p/xyz123"
    ]

    for u in forbidden_urls:
        assert not is_valid_linkedin_post_url(u), f"Security breach: forbidden URL accepted: {u}"
        print(f"  [PASS] Rejected forbidden pattern: {u}")

    allowed_urls = [
        "https://www.linkedin.com/posts/purva-sonwane-b71158333_hiring-reactjs-reactdeveloper-share-7498955579974066176-GGFJ",
        "https://in.linkedin.com/posts/swarna-m-568a462b6_applynow-share-7498954535663509504-YYRO",
        "https://www.linkedin.com/posts/astha-mishra-hr_devopsjobs-sre-cloudengineering-ugcPost-7498955040481677313-kDJ3"
    ]
    for u in allowed_urls:
        assert is_valid_linkedin_post_url(u), f"Valid /posts/ URL rejected: {u}"
        print(f"  [PASS] Accepted genuine /posts/ URL: {u}")

    print("✅ URL Security & Strict Rejection Tests: 100% PASSED\n")


def test_exact_freshness_boundary_conditions():
    print("=" * 70)
    print("2. RUNNING EXACT FRESHNESS BOUNDARY CONDITION TESTS")
    print("=" * 70)

    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Boundary for past-1h (60 minutes = 3600 seconds)
    t_59m59s = now - timedelta(minutes=59, seconds=59)
    t_60m00s = now - timedelta(minutes=60, seconds=0)
    t_60m01s = now - timedelta(minutes=60, seconds=1)

    assert is_within_window(t_59m59s, max_age_minutes=60, now=now), "59m 59s MUST be within past-1h"
    assert not is_within_window(t_60m00s, max_age_minutes=60, now=now), "60m 00s MUST be excluded from past-1h"
    assert not is_within_window(t_60m01s, max_age_minutes=60, now=now), "60m 01s MUST be excluded from past-1h"
    print("  [PASS] past-1h boundary: 59m59s ACCEPTED, 60m00s REJECTED")

    # 2. Boundary for past-24h (1440 minutes = 86400 seconds)
    t_23h59m59s = now - timedelta(hours=23, minutes=59, seconds=59)
    t_24h00m00s = now - timedelta(hours=24, minutes=0, seconds=0)

    assert is_within_window(t_23h59m59s, max_age_minutes=1440, now=now), "23h 59m 59s MUST be within past-24h"
    assert not is_within_window(t_24h00m00s, max_age_minutes=1440, now=now), "24h 00m 00s MUST be excluded from past-24h"
    print("  [PASS] past-24h boundary: 23h59m59s ACCEPTED, 24h00m00s REJECTED")

    # 3. Future timestamps (total_seconds < 0)
    t_future = now + timedelta(minutes=5)
    assert not is_within_window(t_future, max_age_minutes=60, now=now), "Future timestamp MUST be rejected"
    print("  [PASS] Future timestamp rejected safely")

    print("✅ Exact Freshness Boundary Tests: 100% PASSED\n")


def test_hiring_intent_and_directional_safety():
    print("=" * 70)
    print("3. RUNNING HIRING INTENT DIRECTIONAL SAFETY TESTS")
    print("=" * 70)

    seeker_text = "I am a Full Stack React Developer actively looking for immediate job opportunities. #OpenToWork #JobSeeker"
    seeker_res = HiringIntentClassifier.classify(seeker_text, "Software Engineer", "John Doe")
    assert seeker_res["intent"] == "JOB_SEEKER", f"Candidate post misclassified: {seeker_res}"
    print(f"  [PASS] Candidate #OpenToWork post classified: {seeker_res['intent']}")

    hiring_text = "We are hiring Senior React Developers for our Bangalore office. Send your resume to hr@techcorp.com"
    hiring_res = HiringIntentClassifier.classify(hiring_text, "HR Talent Acquisition", "Jane Smith")
    assert hiring_res["intent"] == "HIRING", f"Recruiter post misclassified: {hiring_res}"
    print(f"  [PASS] Recruiter post classified: {hiring_res['intent']}")

    print("✅ Hiring Intent Directional Safety Tests: 100% PASSED\n")


def test_cache_corruption_and_recovery():
    print("=" * 70)
    print("4. RUNNING CACHE CORRUPTION RECOVERY & ISOLATION TESTS")
    print("=" * 70)

    cache = SearchCache()
    cache.clear()

    # Insert valid entry
    key = "test_key"
    cache.set(key, [{"title": "Valid Post"}], timeframe="past-24h")
    assert cache.get(key, timeframe="past-24h") is not None

    # Inject corrupt JSON directly into database row
    with sqlite3.connect(cache.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE search_cache SET data_json = '{malformed json!}' WHERE query_key = ?", (key,))
        conn.commit()

    # Must recover gracefully without raising exception (treats as cache miss and purges corrupted row)
    recovered = cache.get(key, timeframe="past-24h")
    assert recovered is None, "Corrupt cache must return None gracefully"
    print("  [PASS] Corrupted cache record gracefully handled as cache miss and evicted")

    cache.clear()
    print("✅ Cache Corruption Recovery Tests: 100% PASSED\n")


def test_resume_parser_security_and_edge_cases():
    print("=" * 70)
    print("5. RUNNING RESUME PARSER SECURITY & EDGE CASE TESTS")
    print("=" * 70)

    parser = ResumeParser()

    # 1. Non-existent path
    try:
        parser.parse("non_existent_file_path_12345.pdf")
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        print("  [PASS] Non-existent file raises FileNotFoundError")

    # 2. Empty string path
    try:
        parser.parse("")
        assert False, "Should raise ValueError for empty path"
    except ValueError:
        print("  [PASS] Empty path raises ValueError")

    print("✅ Resume Parser Security Tests: 100% PASSED\n")


def test_ranking_determinism_and_tie_breaking():
    print("=" * 70)
    print("6. RUNNING RANKING DETERMINISM TESTS (5 REPEATED RUNS)")
    print("=" * 70)

    posts = [
        {"title": "Role A", "company": "Comp A", "age_minutes": 10, "post_url": "https://www.linkedin.com/posts/a"},
        {"title": "Role B", "company": "Comp B", "age_minutes": 20, "post_url": "https://www.linkedin.com/posts/b"},
        {"title": "Role C", "company": "Comp C", "age_minutes": 10, "post_url": "https://www.linkedin.com/posts/c"},
    ]

    first_order = None
    for run in range(5):
        ranked = OpportunityRanker.rank_opportunities(posts=posts, target_role="Developer", target_location="India")
        order = [p["post_url"] for p in ranked]
        if first_order is None:
            first_order = order
        else:
            assert order == first_order, f"Non-deterministic ordering detected on run #{run+1}: {order} vs {first_order}"

    print(f"  [PASS] 5 consecutive runs produced 100% identical ranking: {first_order}")
    print("✅ Ranking Determinism Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_url_security_and_strict_rejection()
    test_exact_freshness_boundary_conditions()
    test_hiring_intent_and_directional_safety()
    test_cache_corruption_and_recovery()
    test_resume_parser_security_and_edge_cases()
    test_ranking_determinism_and_tie_breaking()
    print("=" * 70)
    print("🎉 ALL PHASE 7 PRODUCTION HARDENING TESTS PASSED WITH ZERO ERRORS!")
    print("=" * 70)
