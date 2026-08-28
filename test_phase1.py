import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# Ensure UTF-8 stdout
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

from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.time_utils import (
    FRESHNESS_WINDOWS,
    get_max_age_minutes,
    extract_snowflake_timestamp,
    parse_timestamp,
    calculate_age,
    is_within_window,
    format_age
)
from core.post_extractor import LinkedInPostExtractor
from core.linkedin_finder import LinkedInFinder


def test_url_validation():
    print("=" * 70)
    print("1. RUNNING URL VALIDATION TESTS")
    print("=" * 70)

    # 1. Valid URLs that MUST pass
    valid_urls = [
        "https://www.linkedin.com/posts/john-doe_hiring-react-developer-activity-123456789",
        "https://in.linkedin.com/posts/jane-recruiter_mern-stack-opening-12345",
        "https://linkedin.com/posts/techlead_we-are-hiring-67890",
        "http://www.linkedin.com/posts/founder_join-our-team-11111?utm_source=chatgpt",
        "https://www.linkedin.com/posts/company-slug_engineering-role-99999/#comments"
    ]

    for url in valid_urls:
        assert is_valid_linkedin_post_url(url) is True, f"Failed: Valid URL rejected: {url}"
        norm = normalize_linkedin_post_url(url)
        assert norm is not None and "/posts/" in norm and "?" not in norm, f"Failed normalization on: {url}"
        print(f"  [PASS] Valid URL: {url[:60]}... -> {norm}")

    # 2. Invalid URLs that MUST fail
    invalid_urls = [
        "https://www.linkedin.com/jobs/view/123456789",
        "https://www.linkedin.com/jobs/collections/recommended/",
        "https://www.linkedin.com/feed/update/urn:li:activity:7498493404704591873/",
        "https://www.linkedin.com/feed/update/urn:li:share:123456789/",
        "https://www.linkedin.com/activity-7498493404704591873",
        "https://www.linkedin.com/company/google/jobs/",
        "https://www.linkedin.com/pulse/why-react-is-great-john-doe",
        "https://www.linkedin.com/learning/react-essential-training",
        "https://www.linkedin.com/school/stanford-university/",
        "https://www.linkedin.com/salary/software-engineer-salaries",
        "https://www.linkedin.com/directory/people-a/",
        "https://lnkd.in/p/abcdef",
        "https://example.com/posts/not-linkedin",
        "https://linkedin.com/posts/",  # Empty slug
        "",
        None
    ]

    for url in invalid_urls:
        assert is_valid_linkedin_post_url(url) is False, f"Failed: Forbidden URL allowed: {url}"
        assert normalize_linkedin_post_url(url) is None, f"Failed: Forbidden URL normalized: {url}"
        print(f"  [PASS] Rejected Forbidden URL: {str(url)[:60]}")

    print("✅ URL Validation Tests: 100% PASSED\n")


def test_freshness_calculations():
    print("=" * 70)
    print("2. RUNNING EXACT FRESHNESS & TIMESTAMP TESTS")
    print("=" * 70)

    # Fixed reference time: 2026-08-28 10:00:00 UTC
    ref_now = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    print(f"• Fixed reference time: {ref_now.isoformat()}")

    # A. Window Tests for past-1h (max 60 minutes)
    one_hour_cases = [
        # (published_at, expected_is_within, desc)
        (datetime(2026, 8, 28, 9, 59, 59, tzinfo=timezone.utc), True, "09:59:59 (1 sec old) -> ACCEPT"),
        (datetime(2026, 8, 28, 9, 30, 0, tzinfo=timezone.utc), True, "09:30:00 (30 mins old) -> ACCEPT"),
        (datetime(2026, 8, 28, 9, 1, 0, tzinfo=timezone.utc), True, "09:01:00 (59 mins old) -> ACCEPT"),
        (datetime(2026, 8, 28, 9, 0, 1, tzinfo=timezone.utc), True, "09:00:01 (59m 59s old) -> ACCEPT"),
        (datetime(2026, 8, 28, 9, 0, 0, tzinfo=timezone.utc), False, "09:00:00 (Exactly 60m old) -> REJECT"),
        (datetime(2026, 8, 28, 8, 59, 59, tzinfo=timezone.utc), False, "08:59:59 (60m 1s old) -> REJECT"),
    ]

    for pub, expected, desc in one_hour_cases:
        res = is_within_window(pub, max_age_minutes=60, now=ref_now)
        assert res == expected, f"Failed past-1h case: {desc} (Got: {res})"
        print(f"  [PASS] {desc}")

    # B. Window Tests for past-24h (max 1440 minutes)
    twenty_four_hour_cases = [
        (datetime(2026, 8, 27, 10, 0, 1, tzinfo=timezone.utc), True, "2026-08-27 10:00:01 (23h 59m 59s old) -> ACCEPT"),
        (datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc), False, "2026-08-27 10:00:00 (Exactly 24h old) -> REJECT"),
        (datetime(2026, 8, 27, 9, 59, 59, tzinfo=timezone.utc), False, "2026-08-27 09:59:59 (24h 1s old) -> REJECT"),
    ]

    for pub, expected, desc in twenty_four_hour_cases:
        res = is_within_window(pub, max_age_minutes=1440, now=ref_now)
        assert res == expected, f"Failed past-24h case: {desc} (Got: {res})"
        print(f"  [PASS] {desc}")

    # C. Future Timestamp Test
    future_dt = datetime(2026, 8, 28, 10, 0, 1, tzinfo=timezone.utc)
    assert is_within_window(future_dt, max_age_minutes=60, now=ref_now) is False, "Failed: Future timestamp allowed!"
    age_calc = calculate_age(future_dt, now=ref_now)
    assert age_calc["is_valid"] is False and age_calc["is_future"] is True, "Failed: Future timestamp marked valid!"
    print("  [PASS] Future timestamp (10:00:01) -> Correctly REJECTED")

    # D. Snowflake Activity ID Timestamp Decoding
    # Activity ID: 7498493404704591873 -> 2026-08-26 21:35:42.951 UTC
    snowflake_url = "https://www.linkedin.com/posts/author_slug-activity-7498493404704591873-abcd"
    snow_dt = extract_snowflake_timestamp(snowflake_url)
    assert snow_dt is not None, "Failed: Snowflake timestamp was not extracted!"
    assert snow_dt.year == 2026 and snow_dt.month == 8 and snow_dt.day == 26, f"Incorrect snowflake date: {snow_dt}"
    print(f"  [PASS] Snowflake ID 7498493404704591873 -> {snow_dt.isoformat()}")

    # E. JSON-LD Date Parsing
    json_ld_html = """
    <html><head>
    <script type="application/ld+json">
    {"@context":"http://schema.org","@type":"SocialMediaPosting","datePublished":"2026-08-28T09:15:30.000Z"}
    </script>
    </head></html>
    """
    soup = BeautifulSoup(json_ld_html, "html.parser")
    json_dt = parse_timestamp(soup_or_str=soup)
    assert json_dt is not None, "Failed: JSON-LD date not parsed!"
    assert json_dt.minute == 15 and json_dt.hour == 9, f"Incorrect parsed time: {json_dt}"
    print(f"  [PASS] JSON-LD schema datePublished -> {json_dt.isoformat()}")

    print("✅ Freshness & Timestamp Calculations: 100% PASSED\n")


def test_post_extractor_contract():
    print("=" * 70)
    print("3. RUNNING POST EXTRACTOR CONTRACT & REJECTION TESTS")
    print("=" * 70)

    # 1. Reject non-LinkedIn / non-/posts/ URL
    bad_res = LinkedInPostExtractor.extract_from_url("https://www.linkedin.com/jobs/view/123456")
    assert bad_res["status"] == "rejected" and bad_res["reason"] == "NOT_A_LINKEDIN_POST", f"Failed: {bad_res}"
    print("  [PASS] Rejected /jobs/view/ URL with reason: NOT_A_LINKEDIN_POST")

    feed_res = LinkedInPostExtractor.extract_from_url("https://www.linkedin.com/feed/update/urn:li:activity:12345")
    assert feed_res["status"] == "rejected" and feed_res["reason"] == "NOT_A_LINKEDIN_POST", f"Failed: {feed_res}"
    print("  [PASS] Rejected /feed/update/ URL with reason: NOT_A_LINKEDIN_POST")

    # 2. Reject with invalid timeframe
    invalid_tf_res = LinkedInPostExtractor.extract_from_url(
        "https://www.linkedin.com/posts/valid_author-activity-123456789-abcd",
        timeframe="past-100years"
    )
    assert invalid_tf_res["status"] == "rejected" and invalid_tf_res["reason"] == "INVALID_TIMEFRAME", f"Failed: {invalid_tf_res}"
    print("  [PASS] Rejected invalid timeframe with reason: INVALID_TIMEFRAME")

    # 3. Live Verified /posts/ Test (if network reachable)
    live_url = "https://www.linkedin.com/posts/siva-raja-lingam-12ab4a223_we-are-hiring-egrove-systems-is-looking-activity-7498493404704591873-1z9G"
    live_res = LinkedInPostExtractor.extract_from_url(live_url, timeframe="past-7d")
    if live_res.get("status") == "success":
        assert live_res["post_url"] == live_url, "Failed: Post URL modified!"
        assert "published_at" in live_res, "Failed: Missing published_at"
        assert "age_minutes" in live_res, "Failed: Missing age_minutes"
        assert "age_hours" in live_res, "Failed: Missing age_hours"
        assert "age_text" in live_res, "Failed: Missing age_text"
        assert "company" in live_res, "Failed: Missing company"
        assert "job_role" in live_res, "Failed: Missing job_role"
        print(f"  [PASS] Live Extractor Success: {live_res['job_role']} @ {live_res['company']} ({live_res['age_text']})")
    else:
        print(f"  [INFO] Live fetch test returned: {live_res.get('reason', live_res.get('status'))}")

    print("✅ Post Extractor Contract Tests: 100% PASSED\n")


def test_markdown_table_formatting():
    print("=" * 70)
    print("4. RUNNING MARKDOWN TABLE FORMATTING TESTS")
    print("=" * 70)

    sample_posts = [
        {
            "company": "Tech Corp",
            "role": "React Developer",
            "experience": "1–3 Yrs",
            "location": "Bangalore",
            "posted_time": "38m ago",
            "recruiter_emails": ["hr@techcorp.com"],
            "contact_phones": ["+91 9876543210"],
            "post_url": "https://www.linkedin.com/posts/recruiter_hiring-react-activity-12345"
        },
        {
            "company": "StartupX",
            "role": "MERN Stack Engineer",
            "experience": "1–2 Yrs",
            "location": "Remote",
            "posted_time": "3h 12m ago",
            "recruiter_emails": [],
            "contact_phones": [],
            "post_url": "https://www.linkedin.com/posts/founder_join-us-activity-67890"
        }
    ]

    table = LinkedInFinder.format_as_markdown_table(sample_posts)
    print(table)
    assert "| #" in table and "Company" in table and "Direct Link" in table, "Failed: Table headers missing"
    assert "https://www.linkedin.com/posts/recruiter_hiring-react-activity-12345" in table, "Failed: Link missing"
    assert "38m ago" in table, "Failed: Minute age missing"
    print("✅ Markdown Table Formatting Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_url_validation()
    test_freshness_calculations()
    test_post_extractor_contract()
    test_markdown_table_formatting()
    print("=" * 70)
    print("🎉 ALL PHASE 1 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
