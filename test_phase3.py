import sys
from pathlib import Path
from datetime import datetime, timezone

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
from core.hiring_intent import (
    JobRoleExtractor,
    HiringIntentClassifier,
    RoleRelevanceMatcher,
    LocationRelevanceMatcher,
    ExperienceRelevanceMatcher,
    QualityScorer
)


def test_search_intent_model():
    print("=" * 70)
    print("1. RUNNING SEARCH INTENT PARSING TESTS")
    print("=" * 70)

    # 1. Frontend React Family
    intent_react = SearchIntentParser.parse("React Developer hiring", location="Bangalore", timeframe="past-1h")
    assert intent_react.role_family == "FRONTEND_REACT", f"Failed: {intent_react.role_family}"
    assert "react" in intent_react.required_tech_signals, "Missing required tech signal 'react'"
    assert "coldfusion" in intent_react.negative_tech_signals, "Missing negative signal 'coldfusion'"
    assert intent_react.max_age_minutes == 60, f"Failed max_age_minutes: {intent_react.max_age_minutes}"
    assert "Bengaluru" in intent_react.location_variants, "Missing Bengaluru in location cluster"
    print(f"  [PASS] React Query -> Family: {intent_react.role_family} (Target: '{intent_react.target_role}')")

    # 2. Node Backend Family
    intent_node = SearchIntentParser.parse("Node.js Backend Developer", location="Remote", timeframe="past-24h")
    assert intent_node.role_family == "NODE_BACKEND", f"Failed: {intent_node.role_family}"
    print(f"  [PASS] Node Query -> Family: {intent_node.role_family}")

    # 3. Python Backend Family
    intent_py = SearchIntentParser.parse("Python Django Engineer", location="Chennai")
    assert intent_py.role_family == "PYTHON_BACKEND", f"Failed: {intent_py.role_family}"
    print(f"  [PASS] Python Query -> Family: {intent_py.role_family}")

    # 4. Java Backend Family
    intent_java = SearchIntentParser.parse("Java Spring Boot Developer", location="Hyderabad")
    assert intent_java.role_family == "JAVA_BACKEND", f"Failed: {intent_java.role_family}"
    print(f"  [PASS] Java Query -> Family: {intent_java.role_family}")

    # 5. Query Generation
    dorks = intent_react.generate_dork_queries()
    assert len(dorks) >= 3, "Failed to generate dork queries"
    assert 'site:linkedin.com/posts' in dorks[0], "Missing site:linkedin.com/posts in dorks"
    assert '"React Developer"' in dorks[0], "Missing exact quoted role in dorks"
    print(f"  [PASS] Generated Top Dork: {dorks[0]}")

    print("✅ Search Intent Model Tests: 100% PASSED\n")


def test_job_role_extraction():
    print("=" * 70)
    print("2. RUNNING JOB ROLE EXTRACTION TESTS")
    print("=" * 70)

    # 1. Multi-role bullet points
    text_multi = """
    We are hiring for multiple positions at our Bangalore office!
    • React Developer - 1 to 3 years
    • Node.js Backend Engineer - 2+ years
    • QA Automation Tester - 1+ years
    Send your resume to hr@acme.com
    """
    extracted = JobRoleExtractor.extract_roles(text_multi)
    assert any("React" in r for r in extracted), f"Failed to extract React role: {extracted}"
    assert any("Node" in r for r in extracted), f"Failed to extract Node role: {extracted}"
    assert any("Qa" in r or "QA" in r for r in extracted), f"Failed to extract QA role: {extracted}"
    print(f"  [PASS] Multi-Role Extraction: {extracted}")

    # 2. Key-value style
    text_kv = "We have an urgent opening.\nPosition: React.js Frontend Engineer\nLocation: Bangalore\nExp: 2 Yrs"
    extracted_kv = JobRoleExtractor.extract_roles(text_kv)
    assert any("React" in r for r in extracted_kv), f"Failed to extract KV role: {extracted_kv}"
    print(f"  [PASS] Key-Value Extraction: {extracted_kv}")

    print("✅ Job Role Extraction Tests: 100% PASSED\n")


def test_role_precision_and_negative_penalties():
    print("=" * 70)
    print("3. RUNNING ROLE PRECISION & NEGATIVE PENALTY TESTS")
    print("=" * 70)

    target = "React Developer"

    # A. React Positives (Must score >= 80)
    positives = [
        ("React Developer", "Exact match", 100, 100),
        ("React.js Developer", "Variant", 90, 100),
        ("ReactJS Developer", "Variant", 90, 100),
        ("Frontend Developer (React)", "Token match", 80, 100),
        ("MERN Developer", "Synonym group", 80, 95),
        ("React + Node.js Developer", "Combined stack", 85, 100),
    ]

    for role_str, desc, min_s, max_s in positives:
        res = RoleRelevanceMatcher.calculate_score_with_reason(target, role_str, post_content=role_str)
        assert min_s <= res["score"] <= max_s, f"Failed positive '{role_str}': {res['score']} (Expected: {min_s}-{max_s})"
        print(f"  [PASS] Positive '{role_str}' ({res['score']}/100) -> Reason: {res['reason']}")

    # B. React Negatives (Must score <= 30)
    negatives = [
        ("ColdFusion Developer", "Unrelated legacy stack", 0, 25),
        ("Java Spring Developer", "Conflicting backend stack", 0, 25),
        ("PHP Laravel Developer", "Conflicting PHP stack", 0, 25),
        ("Python Backend Developer", "Conflicting Python stack", 0, 25),
        ("DevOps Engineer", "Different discipline", 0, 30),
    ]

    for role_str, desc, min_s, max_s in negatives:
        res = RoleRelevanceMatcher.calculate_score_with_reason(target, role_str, post_content=f"We are hiring {role_str} for our team.")
        assert min_s <= res["score"] <= max_s, f"Failed negative '{role_str}': {res['score']} (Expected: {min_s}-{max_s})"
        print(f"  [PASS] Negative '{role_str}' ({res['score']}/100) -> Reason: {res['reason']}")

    # C. Multi-Role Post with React Present (Must pass!)
    multi_content = "We are hiring React Developers, Node.js Developers and QA Engineers. Drop CV."
    multi_roles = ["React Developer", "Node.js Developer", "QA Engineer"]
    multi_res = RoleRelevanceMatcher.calculate_score_with_reason(target, "Multi-Role Opening", post_content=multi_content, extracted_roles=multi_roles)
    assert multi_res["score"] >= 90, f"Failed multi-role match with React: {multi_res}"
    print(f"  [PASS] Multi-Role with React Included ({multi_res['score']}/100) -> {multi_res['reason']}")

    # D. Multi-Role Post WITHOUT React (Must be penalized!)
    unrelated_multi = "We are hiring Java Developers and ColdFusion Developers. Apply now."
    unrelated_roles = ["Java Developer", "ColdFusion Developer"]
    unrelated_res = RoleRelevanceMatcher.calculate_score_with_reason(target, "Java Developer", post_content=unrelated_multi, extracted_roles=unrelated_roles)
    assert unrelated_res["score"] <= 25, f"Failed unrelated multi-role penalty: {unrelated_res}"
    print(f"  [PASS] Multi-Role without React ({unrelated_res['score']}/100) -> {unrelated_res['reason']}")

    print("✅ Role Precision & Negative Penalty Tests: 100% PASSED\n")


def test_location_neighborhoods_and_clusters():
    print("=" * 70)
    print("4. RUNNING LOCATION NEIGHBORHOOD & CLUSTER TESTS")
    print("=" * 70)

    target = "Bangalore"
    cases = [
        ("Bangalore, India", "EXACT", 100),
        ("Bengaluru", "EXACT", 100),
        ("Electronic City", "EXACT", 100),
        ("Whitefield", "EXACT", 100),
        ("Koramangala", "EXACT", 100),
        ("Hebbal, Bangalore", "EXACT", 100),
        ("Chennai, Tamil Nadu", "MISMATCH", 15),
        ("Remote / Work From Home", "REMOTE", 95),
    ]

    for loc_str, exp_type, exp_score in cases:
        res = LocationRelevanceMatcher.match(target, loc_str)
        assert res["match_type"] == exp_type, f"Failed location type for '{loc_str}': {res['match_type']} (Expected: {exp_type})"
        assert res["score"] == exp_score, f"Failed location score for '{loc_str}': {res['score']} (Expected: {exp_score})"
        print(f"  [PASS] '{target}' vs '{loc_str}' -> {res['match_type']} ({res['score']}/100)")

    print("✅ Location Neighborhood & Cluster Tests: 100% PASSED\n")


def test_experience_precision_for_freshers():
    print("=" * 70)
    print("5. RUNNING EXPERIENCE PRECISION TESTS (0–1 YR CANDIDATE)")
    print("=" * 70)

    cand_exp = 0  # Fresher

    cases = [
        ("Fresher / Entry Level", "PERFECT", 100),
        ("0-1 years required", "PERFECT", 100),
        ("0 to 1 yrs", "PERFECT", 100),
        ("1-2 years experience", "ACCEPTABLE", 70),
        ("3-5 years experience", "MISMATCH", 25),
        ("8+ years experience (Senior Lead)", "MISMATCH", 25),
    ]

    for exp_text, exp_fit, min_s in cases:
        res = ExperienceRelevanceMatcher.match(cand_exp, exp_text)
        assert res["fit"] == exp_fit, f"Failed exp fit for '{exp_text}': {res['fit']} (Expected: {exp_fit})"
        print(f"  [PASS] Fresher vs '{exp_text}' -> {res['fit']} ({res['score']}/100)")

    print("✅ Experience Precision Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_search_intent_model()
    test_job_role_extraction()
    test_role_precision_and_negative_penalties()
    test_location_neighborhoods_and_clusters()
    test_experience_precision_for_freshers()
    print("=" * 70)
    print("🎉 ALL PHASE 3 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
