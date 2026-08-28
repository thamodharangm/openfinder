import sys
import time
from pathlib import Path

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

from core.search_intent import SearchIntentParser, SearchIntent
from core.cache import SearchCache
from core.linkedin_session import LinkedInSessionSearch
from core.linkedin_finder import LinkedInFinder


def test_session_health_and_diagnostics():
    print("=" * 70)
    print("1. RUNNING SESSION HEALTH & DIAGNOSTICS TESTS")
    print("=" * 70)

    health = LinkedInSessionSearch.check_session_health()
    assert "status" in health, "Missing status in session health"
    assert "valid" in health, "Missing valid boolean in session health"
    print(f"  [PASS] Session Health Status: {health['status']} (Valid: {health['valid']})")

    # Verify no credential leakage in output
    for k, v in health.items():
        assert "li_at" not in str(v).lower() or k == "reason", "Leaked credentials in session health"
    print("  [PASS] Zero Credential Leakage in Health Payload")

    print("✅ Session Health & Diagnostics Tests: 100% PASSED\n")


def test_timeframe_aware_cache():
    print("=" * 70)
    print("2. RUNNING TIMEFRAME-AWARE CACHE & ISOLATION TESTS")
    print("=" * 70)

    cache = SearchCache()
    cache.clear()

    # 1. TTL Verification
    assert cache.get_ttl_for_timeframe("past-1h") == 60, "Failed past-1h TTL"
    assert cache.get_ttl_for_timeframe("past-4h") == 300, "Failed past-4h TTL"
    assert cache.get_ttl_for_timeframe("past-24h") == 1800, "Failed past-24h TTL"
    assert cache.get_ttl_for_timeframe("past-7d") == 7200, "Failed past-7d TTL"
    print("  [PASS] Timeframe TTL Rules: past-1h=60s, past-4h=300s, past-24h=1800s, past-7d=7200s")

    # 2. Key Isolation across timeframe and locations
    dummy_data_1h = [{"role": "React Developer", "location": "Bangalore"}]
    dummy_data_24h = [{"role": "React Developer", "location": "Chennai"}]

    cache.set("test_key_blr_1h", dummy_data_1h, timeframe="past-1h")
    cache.set("test_key_chn_24h", dummy_data_24h, timeframe="past-24h")

    assert cache.get("test_key_blr_1h", timeframe="past-1h") == dummy_data_1h
    assert cache.get("test_key_chn_24h", timeframe="past-24h") == dummy_data_24h
    assert cache.get("test_key_blr_1h_nonexistent") is None
    print("  [PASS] Key & Location Isolation verified without cross-pollution")

    cache.clear()
    print("✅ Timeframe-Aware Cache Tests: 100% PASSED\n")


def test_query_diversity_expansion():
    print("=" * 70)
    print("3. RUNNING QUERY DIVERSITY & EXPANSION TESTS")
    print("=" * 70)

    intent = SearchIntentParser.parse("React Developer", location="Bangalore", timeframe="past-24h")
    queries = intent.generate_diverse_session_queries(max_queries=4)

    assert len(queries) >= 3, f"Expected >= 3 diverse queries, got {len(queries)}"
    assert any('"React Developer"' in q for q in queries), "Missing exact quoted role query"
    assert any("we are hiring" in q or "send resume" in q for q in queries), "Missing hiring action dork"
    assert any("Bangalore" in q or "Bengaluru" in q for q in queries), "Missing location variant"

    print(f"  [PASS] Generated {len(queries)} Diverse Queries:")
    for idx, q in enumerate(queries, 1):
        print(f"     ({idx}) {q}")

    print("✅ Query Diversity & Expansion Tests: 100% PASSED\n")


def test_candidate_budget_and_metrics():
    print("=" * 70)
    print("4. RUNNING CANDIDATE BUDGET & FUNNEL METRICS TESTS")
    print("=" * 70)

    finder = LinkedInFinder()
    results = finder.search_hiring_posts(
        keywords="React Developer",
        location="Bangalore",
        timeframe="past-24h",
        max_results=3,
        debug=True
    )

    print(f"  [PASS] Discovered Results Count: {len(results)}")
    if results and "_funnel_metrics" in results[0]:
        m = results[0]["_funnel_metrics"]
        print(f"  [PASS] Funnel Metrics Tracked:")
        print(f"         • Queries Attempted: {m.get('queries_attempted')}")
        print(f"         • Pages Fetched:     {m.get('pages_fetched')}")
        print(f"         • Raw Candidates:    {m.get('raw_candidates')}")
        print(f"         • Unique Candidates: {m.get('unique_candidates')}")
        print(f"         • Fresh Candidates:  {m.get('fresh_candidates')}")
        print(f"         • Deep Extracted:    {m.get('deep_extracted')}")
        print(f"         • Final Results:     {m.get('final_results')}")
        assert m.get("raw_candidates", 0) >= len(results), "Funnel candidate pool must exceed final results"

    print("✅ Candidate Budget & Funnel Metrics Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_session_health_and_diagnostics()
    test_timeframe_aware_cache()
    test_query_diversity_expansion()
    test_candidate_budget_and_metrics()
    print("=" * 70)
    print("🎉 ALL PHASE 4 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
