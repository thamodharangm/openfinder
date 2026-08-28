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

from core.hiring_intent import (
    HiringIntentClassifier,
    RoleRelevanceMatcher,
    LocationRelevanceMatcher,
    ExperienceRelevanceMatcher,
    QualityScorer
)
from core.post_extractor import LinkedInPostExtractor
from core.linkedin_finder import LinkedInFinder


def test_hiring_intent_classification():
    print("=" * 70)
    print("1. RUNNING HIRING INTENT CLASSIFICATION TESTS")
    print("=" * 70)

    # 1. Genuine Hiring Posts (Must be HIRING)
    hiring_samples = [
        ("We are hiring React Developers. Send your resume to hr@example.com.", "Technical Recruiter", "HIRING"),
        ("React Developer required. Immediate joiners preferred. DM your CV.", "HR Manager", "HIRING"),
        ("Looking for a React Developer to join our team in Bangalore.", "Founder", "HIRING"),
        ("I am looking for a React Developer to work on our core product.", "Engineering Manager", "HIRING"),
        ("Urgent opening for MERN Stack Developer at Tech Corp. Experience: 1-3 years. Apply at careers@techcorp.com", "", "HIRING"),
        ("Walk-in interview for Frontend Engineers (React / Next.js) on Saturday.", "HR Team", "HIRING"),
    ]

    for text, author, expected in hiring_samples:
        res = HiringIntentClassifier.classify(text, author_headline=author)
        assert res["intent"] == expected, f"Failed genuine hiring case: '{text}' -> Got: {res['intent']} (Expected: {expected})"
        assert res["is_hiring"] is True, f"Failed is_hiring boolean on: '{text}'"
        print(f"  [PASS] Genuine Hiring ({res['confidence']}): \"{text[:50]}...\" -> {res['intent']}")

    # 2. Job Seeker Posts (Must be JOB_SEEKER - Negative Override)
    job_seeker_samples = [
        ("I am a React Developer looking for a job. Please refer me.", "Frontend Developer", "JOB_SEEKER"),
        ("Open to Work - React Developer seeking new opportunities in Bangalore.", "#OpenToWork", "JOB_SEEKER"),
        ("I am looking for opportunities as a Full Stack Engineer. Hiring managers please DM me.", "Software Engineer", "JOB_SEEKER"),
        ("#OpenToWork. Looking for my next opportunity in React/Node.", "Job Seeker", "JOB_SEEKER"),
        ("I am actively looking for a React Developer role. Any leads appreciated!", "", "JOB_SEEKER"),
        ("Fresher looking for job as React Developer. Please review my profile.", "Student", "JOB_SEEKER"),
    ]

    for text, author, expected in job_seeker_samples:
        res = HiringIntentClassifier.classify(text, author_headline=author)
        assert res["intent"] == expected, f"Failed job seeker case: '{text}' -> Got: {res['intent']} (Expected: {expected})"
        assert res["is_hiring"] is False, f"Failed is_hiring=False on: '{text}'"
        print(f"  [PASS] Job Seeker Detected ({res['confidence']}): \"{text[:50]}...\" -> {res['intent']}")

    # 3. Non-Hiring Educational / Advice / Marketing
    non_hiring_samples = [
        ("React developers are in high demand across tech companies in 2026. Here is why.", "Content Creator", "NON_HIRING"),
        ("5 tips to crack the React developer interview on your first attempt.", "Tech Mentor", "NON_HIRING"),
        ("Free webinar on React and Next.js this weekend. Register now at link below!", "Academy", "NON_HIRING"),
        ("Top 10 interview questions every React engineer must know.", "", "NON_HIRING"),
    ]

    for text, author, expected in non_hiring_samples:
        res = HiringIntentClassifier.classify(text, author_headline=author)
        assert res["intent"] in [expected, "AMBIGUOUS"], f"Failed non-hiring case: '{text}' -> Got: {res['intent']} (Expected: {expected})"
        assert res["is_hiring"] is False, f"Failed is_hiring=False on: '{text}'"
        print(f"  [PASS] Non-Hiring Filtered ({res['confidence']}): \"{text[:50]}...\" -> {res['intent']}")

    print("✅ Hiring Intent Classification Tests: 100% PASSED\n")


def test_author_classification():
    print("=" * 70)
    print("2. RUNNING AUTHOR TYPE CLASSIFICATION TESTS")
    print("=" * 70)

    author_cases = [
        ("Technical Recruiter at Google", "RECRUITER"),
        ("Senior Talent Acquisition Specialist", "RECRUITER"),
        ("HR Manager at Infosys", "HR"),
        ("Human Resources Executive", "HR"),
        ("Founder & CEO at Stealth Startup", "FOUNDER"),
        ("Co-Founder & CTO", "FOUNDER"),
        ("Engineering Manager at Uber", "HIRING_MANAGER"),
        ("Head of Engineering", "HIRING_MANAGER"),
        ("Open to Work | Frontend Engineer", "JOB_SEEKER"),
        ("#OpenToWork | React Developer", "JOB_SEEKER"),
        ("Senior Software Engineer", "EMPLOYEE"),
        ("", "UNKNOWN"),
    ]

    for headline, expected in author_cases:
        res = HiringIntentClassifier.detect_author_type(author_headline=headline)
        assert res == expected, f"Failed author case: '{headline}' -> Got: {res} (Expected: {expected})"
        print(f"  [PASS] Author Headline: \"{headline}\" -> {res}")

    print("✅ Author Type Classification Tests: 100% PASSED\n")


def test_role_relevance():
    print("=" * 70)
    print("3. RUNNING ROLE RELEVANCE MATCHING TESTS")
    print("=" * 70)

    target = "React Developer"
    role_cases = [
        ("React Developer", "Exact match", 100, 100),
        ("React.js Developer", "Prefix/suffix normalization", 90, 100),
        ("ReactJS Developer", "Acronym normalization", 90, 100),
        ("Frontend Developer (React)", "Domain match with React token", 80, 100),
        ("MERN Stack Developer", "Adjacent stack", 60, 95),
        ("Python Backend Developer", "Different technical domain", 0, 45),
    ]

    for post_role, desc, min_score, max_score in role_cases:
        score = RoleRelevanceMatcher.calculate_score(target, post_role)
        assert min_score <= score <= max_score, f"Failed role case: '{post_role}' -> Got: {score} (Expected: {min_score}–{max_score})"
        print(f"  [PASS] Role Match ({score}/100): Target '{target}' vs '{post_role}' ({desc})")

    print("✅ Role Relevance Matching Tests: 100% PASSED\n")


def test_location_relevance():
    print("=" * 70)
    print("4. RUNNING LOCATION RELEVANCE MATCHING TESTS")
    print("=" * 70)

    target = "Bangalore"
    loc_cases = [
        ("Bangalore, Karnataka", "EXACT", 100),
        ("Bengaluru, India", "EXACT", 100),
        ("Remote / Work From Home", "REMOTE", 95),
        ("Electronic City, Bangalore", "EXACT", 100),
        ("Chennai, Tamil Nadu", "MISMATCH", 15),
        ("Unspecified", "UNKNOWN", 50),
    ]

    for post_loc, expected_type, expected_score in loc_cases:
        res = LocationRelevanceMatcher.match(target, post_loc)
        assert res["match_type"] == expected_type, f"Failed location type: '{post_loc}' -> Got: {res['match_type']} (Expected: {expected_type})"
        assert res["score"] == expected_score, f"Failed location score: '{post_loc}' -> Got: {res['score']} (Expected: {expected_score})"
        print(f"  [PASS] Location Match ({res['score']}/100 - {res['match_type']}): '{target}' vs '{post_loc}'")

    print("✅ Location Relevance Matching Tests: 100% PASSED\n")


def test_experience_relevance():
    print("=" * 70)
    print("5. RUNNING EXPERIENCE RELEVANCE MATCHING TESTS")
    print("=" * 70)

    candidate_exp = 2
    exp_cases = [
        ("1-3 years experience required", "PERFECT", 100),
        ("2 years experience needed", "PERFECT", 100),
        ("0-1 years (Freshers welcome)", "GOOD", 85),
        ("3-5 years experience", "ACCEPTABLE", 70),
        ("8+ years experience (Tech Lead)", "MISMATCH", 25),
        ("", "UNKNOWN", 75),
    ]

    for exp_str, expected_fit, expected_score in exp_cases:
        res = ExperienceRelevanceMatcher.match(candidate_exp, exp_str)
        assert res["fit"] == expected_fit, f"Failed exp fit: '{exp_str}' -> Got: {res['fit']} (Expected: {expected_fit})"
        assert res["score"] == expected_score, f"Failed exp score: '{exp_str}' -> Got: {res['score']} (Expected: {expected_score})"
        print(f"  [PASS] Experience Fit ({res['score']}/100 - {res['fit']}): Cand {candidate_exp}y vs '{exp_str}'")

    print("✅ Experience Relevance Matching Tests: 100% PASSED\n")


def test_quality_scorer_ranking():
    print("=" * 70)
    print("6. RUNNING QUALITY SCORER & RANKING FORMULA TESTS")
    print("=" * 70)

    # Top quality post: High confidence, 10m old (out of 1440m), perfect role, perfect location, perfect exp, contact info
    top_score = QualityScorer.calculate_quality_score(
        hiring_confidence=0.95,
        age_minutes=10,
        max_age_minutes=1440,
        role_score=100,
        location_score=100,
        experience_score=100,
        has_email=True,
        has_phone=True,
        has_apply_link=True
    )
    assert top_score >= 90, f"Failed top quality score: {top_score}"
    print(f"  [PASS] Top Recruiter Post Quality Score: {top_score}/100")

    # Stale, mismatched post
    low_score = QualityScorer.calculate_quality_score(
        hiring_confidence=0.50,
        age_minutes=1400,
        max_age_minutes=1440,
        role_score=30,
        location_score=15,
        experience_score=25,
        has_email=False,
        has_phone=False,
        has_apply_link=False
    )
    assert low_score <= 40, f"Failed low quality score: {low_score}"
    print(f"  [PASS] Low Quality Post Score: {low_score}/100")

    print("✅ Quality Scorer Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_hiring_intent_classification()
    test_author_classification()
    test_role_relevance()
    test_location_relevance()
    test_experience_relevance()
    test_quality_scorer_ranking()
    print("=" * 70)
    print("🎉 ALL PHASE 2 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
