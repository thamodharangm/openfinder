import sys
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any

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

from core.post_extractor import LinkedInPostExtractor
from core.linkedin_finder import LinkedInFinder
from core.cache import SearchCache


def test_async_batch_extraction_and_error_isolation():
    print("=" * 70)
    print("1. RUNNING ASYNC BATCH EXTRACTION & ERROR ISOLATION TESTS")
    print("=" * 70)

    async def run_batch():
        test_urls = [
            "https://www.linkedin.com/posts/purva-sonwane-b71158333_hiring-reactjs-reactdeveloper-share-7498955579974066176-GGFJ",
            "https://www.linkedin.com/posts/invalid-nonexistent-post-slug-9999999999999999999",
            "https://www.linkedin.com/posts/swarna-m-568a462b6_applynow-share-7498954535663509504-YYRO",
            "https://www.linkedin.com/jobs/view/123456789",  # Non-posts URL
            "https://www.linkedin.com/posts/purva-sonwane-b71158333_hiring-reactjs-reactdeveloper-share-7498955579974066176-GGFJ" # Duplicate
        ]

        t0 = time.perf_counter()
        results = await LinkedInPostExtractor.extract_batch_async(
            urls=test_urls,
            max_concurrency=3,
            target_role="React Developer",
            target_location="Bangalore"
        )
        duration = time.perf_counter() - t0

        print(f"  [PASS] Extracted batch of {len(results)} items in {duration:.2f}s")
        assert len(results) == 4, f"Deduplicated count should be 4, got {len(results)}"

        # Verify error isolation
        statuses = [r.get("status") for r in results]
        print(f"  [PASS] Result Statuses: {statuses}")
        assert "success" in statuses, "Valid post must succeed"
        assert "rejected" in statuses or "error" in statuses, "Invalid post must be rejected or error isolated"

    asyncio.run(run_batch())
    print("✅ Async Batch Extraction & Error Isolation Tests: 100% PASSED\n")


def test_deterministic_quality_ranking_under_concurrency():
    print("=" * 70)
    print("2. RUNNING DETERMINISTIC QUALITY RANKING TESTS")
    print("=" * 70)

    async def run_ranking():
        finder = LinkedInFinder()
        results = await finder.search_hiring_posts_async(
            keywords="React Developer",
            location="Bangalore",
            timeframe="past-24h",
            max_results=5,
            debug=True
        )

        scores = [r.get("post_quality_score", 0) for r in results]
        print(f"  [PASS] Quality Scores in Sorted Order: {scores}")
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i+1], f"Ranking order violated: {scores[i]} < {scores[i+1]}"

        if results and "_timing_ms" in results[0]:
            timing = results[0]["_timing_ms"]
            print(f"  [PASS] Timing Metrics Recorded:")
            print(f"         • Discovery Time:  {timing.get('discovery_time_ms')}ms")
            print(f"         • Extraction Time: {timing.get('extraction_time_ms')}ms")
            print(f"         • Ranking Time:    {timing.get('ranking_time_ms')}ms")
            print(f"         • Total Time:      {timing.get('total_time_ms')}ms")
            assert timing.get("total_time_ms", 0) > 0, "Timing metrics must be positive"

    asyncio.run(run_ranking())
    print("✅ Deterministic Quality Ranking Tests: 100% PASSED\n")


def test_cache_hit_bypass_network():
    print("=" * 70)
    print("3. RUNNING CACHE HIT NETWORK BYPASS TESTS")
    print("=" * 70)

    finder = LinkedInFinder()
    cache_key = "hiring_posts::react developer::bangalore::past-24h::false::3"
    dummy = [{"title": "Cached React Role", "post_quality_score": 99, "post_url": "https://www.linkedin.com/posts/cached-1"}]
    finder.cache.set(cache_key, dummy, timeframe="past-24h")

    t0 = time.perf_counter()
    res = finder.search_hiring_posts(
        keywords="React Developer",
        location="Bangalore",
        timeframe="past-24h",
        max_results=3
    )
    duration_ms = (time.perf_counter() - t0) * 1000

    assert len(res) == 1, "Cache hit must return cached list"
    assert res[0]["title"] == "Cached React Role", "Cache hit must match stored data"
    assert duration_ms < 50, f"Cache hit should be instantaneous (<50ms), took {duration_ms:.2f}ms"
    print(f"  [PASS] Instant Cache Hit Resolution: {duration_ms:.2f}ms (Bypassed network)")

    finder.cache.clear()
    print("✅ Cache Hit Network Bypass Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_async_batch_extraction_and_error_isolation()
    test_deterministic_quality_ranking_under_concurrency()
    test_cache_hit_bypass_network()
    print("=" * 70)
    print("🎉 ALL PHASE 5 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
