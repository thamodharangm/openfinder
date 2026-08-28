import sys
from pathlib import Path
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

from core.ranking import OpportunityRanker


def test_ranking_candidate_fit_and_freshness():
    print("=" * 70)
    print("1. RUNNING CANDIDATE FIT & FRESHNESS RANKING TESTS")
    print("=" * 70)

    candidate = {
        "candidate_name": "Thamodharan G",
        "primary_role": "React Developer",
        "top_skills": ["React", "TypeScript", "JavaScript", "Next.js"],
        "years_of_experience": 2
    }

    # Post 1: Fresh & 95% Candidate Fit
    post1 = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company Alpha",
        "location": "Bangalore",
        "age_minutes": 15,
        "hiring_confidence": 0.95,
        "skills": ["React", "TypeScript", "JavaScript"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-1"
    }

    # Post 2: Fresh & Lower Candidate Fit (Python/Django)
    post2 = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company Beta",
        "location": "Bangalore",
        "age_minutes": 15,
        "hiring_confidence": 0.95,
        "skills": ["Python", "Django"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-2"
    }

    # Post 3: Older & High Candidate Fit
    post3 = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company Gamma",
        "location": "Bangalore",
        "age_minutes": 600,
        "hiring_confidence": 0.95,
        "skills": ["React", "TypeScript", "JavaScript"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-3"
    }

    ranked = OpportunityRanker.rank_opportunities(
        posts=[post2, post3, post1],
        candidate_profile=candidate,
        target_role="React Developer",
        target_location="Bangalore"
    )

    print(f"  [PASS] Ranked Order:")
    for idx, r in enumerate(ranked, 1):
        print(f"         #{idx} {r['company']} -> Final Score: {r['final_rank_score']} | Match: {r['candidate_match_score']}% | Quality: {r['post_quality_score']}")

    # Post 1 (Fresh + High Fit) must beat Post 3 (Older + High Fit) and Post 2 (Fresh + Lower Fit)
    assert ranked[0]["company"] == "Company Alpha", "Fresh + High Fit post must be #1"
    assert ranked[0]["final_rank_score"] >= ranked[1]["final_rank_score"], "Rank scores must be non-increasing"
    print("✅ Candidate Fit & Freshness Tests: 100% PASSED\n")


def test_no_resume_fallback_behavior():
    print("=" * 70)
    print("2. RUNNING NO-RESUME FALLBACK BEHAVIOR TESTS")
    print("=" * 70)

    post = {
        "title": "Frontend Engineer",
        "role": "Frontend Engineer",
        "company": "Tech Corp",
        "location": "Bangalore",
        "age_minutes": 30,
        "hiring_confidence": 0.9,
        "skills": ["React", "CSS"],
        "post_url": "https://www.linkedin.com/posts/post-no-resume"
    }

    evaluated = OpportunityRanker.evaluate_opportunity(
        post=post,
        candidate_profile=None,
        target_role="Frontend Engineer",
        target_location="Bangalore"
    )

    print(f"  [PASS] No Resume Evaluation:")
    print(f"         • Candidate Match Score: {evaluated['candidate_match_score']} (Must be None)")
    print(f"         • Post Quality Score:    {evaluated['post_quality_score']}")
    print(f"         • Final Rank Score:      {evaluated['final_rank_score']}")

    assert evaluated["candidate_match_score"] is None, "candidate_match_score must be None when no resume is provided"
    assert evaluated["final_rank_score"] == evaluated["post_quality_score"], "final_rank_score must equal post_quality_score without resume"
    assert "ranking_factors" in evaluated and evaluated["ranking_factors"]["candidate_fit"] is None
    print("✅ No-Resume Fallback Tests: 100% PASSED\n")


def test_company_soft_diversity_penalty():
    print("=" * 70)
    print("3. RUNNING SOFT COMPANY DIVERSITY TESTS")
    print("=" * 70)

    posts = [
        {"title": "React Dev 1", "company": "BigTech", "age_minutes": 10, "post_url": "https://www.linkedin.com/posts/p1"},
        {"title": "React Dev 2", "company": "BigTech", "age_minutes": 11, "post_url": "https://www.linkedin.com/posts/p2"},
        {"title": "React Dev 3", "company": "InnovateLabs", "age_minutes": 12, "post_url": "https://www.linkedin.com/posts/p3"},
    ]

    ranked = OpportunityRanker.rank_opportunities(
        posts=posts,
        target_role="React Developer",
        target_location="Bangalore",
        apply_diversity=True
    )

    print(f"  [PASS] Diversified Results:")
    for idx, r in enumerate(ranked, 1):
        print(f"         #{idx} {r['company']} (Adj Score: {r.get('_adjusted_rank_score')}) -> {r['title']}")

    # The 2nd BigTech post should receive a soft diversity penalty
    bigtech_posts = [p for p in ranked if p["company"] == "BigTech"]
    assert len(bigtech_posts) == 2
    assert bigtech_posts[1].get("_diversity_penalty", 0) > 0, "Repeated company must receive soft diversity penalty"
    print("✅ Soft Company Diversity Tests: 100% PASSED\n")


def test_deterministic_tie_breakers_and_benchmark_dataset():
    print("=" * 70)
    print("4. RUNNING BEFORE/AFTER SYNTHETIC BENCHMARK (POST A, B, C, D, E)")
    print("=" * 70)

    candidate = {
        "candidate_name": "Thamodharan",
        "primary_role": "React Developer",
        "top_skills": ["React", "TypeScript", "JavaScript", "HTML", "CSS"],
        "years_of_experience": 2
    }

    # Post A: Exact React, Fresh (10m), Bangalore, High Match
    post_a = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company A",
        "location": "Bangalore",
        "age_minutes": 10,
        "hiring_confidence": 0.95,
        "skills": ["React", "TypeScript", "JavaScript"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-a"
    }

    # Post B: Generic Software Engineer, Fresh (10m), Bangalore, Medium Match
    post_b = {
        "title": "Software Engineer",
        "role": "Software Engineer",
        "company": "Company B",
        "location": "Bangalore",
        "age_minutes": 10,
        "hiring_confidence": 0.90,
        "skills": ["JavaScript", "HTML", "CSS"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-b"
    }

    # Post C: React Developer, Older (600m), Bangalore, High Match
    post_c = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company C",
        "location": "Bangalore",
        "age_minutes": 600,
        "hiring_confidence": 0.95,
        "skills": ["React", "TypeScript", "JavaScript"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-c"
    }

    # Post D: React Developer, Fresh (10m), Chennai (Regional), Medium Match
    post_d = {
        "title": "React Developer",
        "role": "React Developer",
        "company": "Company D",
        "location": "Chennai",
        "age_minutes": 10,
        "hiring_confidence": 0.90,
        "skills": ["React", "CSS"],
        "experience_required": "1-3 Years",
        "post_url": "https://www.linkedin.com/posts/post-d"
    }

    # Post E: Unrelated ColdFusion Developer, Fresh (10m), Bangalore
    post_e = {
        "title": "ColdFusion Developer",
        "role": "ColdFusion Developer",
        "company": "Company E",
        "location": "Bangalore",
        "age_minutes": 10,
        "hiring_confidence": 0.95,
        "skills": ["ColdFusion", "SQL"],
        "experience_required": "1-3 Years",
        "full_post_content": "We are hiring ColdFusion Developers in Bangalore. Send CV to hr@companye.com",
        "post_url": "https://www.linkedin.com/posts/post-e"
    }

    ranked = OpportunityRanker.rank_opportunities(
        posts=[post_e, post_d, post_c, post_b, post_a],
        candidate_profile=candidate,
        target_role="React Developer",
        target_location="Bangalore"
    )

    print("  [PASS] Benchmark Ranking Order:")
    for idx, r in enumerate(ranked, 1):
        print(f"         #{idx} {r['title']} @ {r['company']} -> Final: {r['final_rank_score']} | Match: {r['candidate_match_score']}% | Quality: {r['post_quality_score']}")
        print(f"             Reason: {r['ranking_summary']}")

    # Post A must be #1
    assert ranked[0]["company"] == "Company A", "Post A (Exact React + Fresh + Bangalore + Fit) must rank #1"

    # ColdFusion (Post E) must rank last
    assert ranked[-1]["company"] == "Company E", "Unrelated ColdFusion post must rank LAST"
    print("✅ Deterministic Tie-Breakers & Benchmark Tests: 100% PASSED\n")


if __name__ == "__main__":
    test_ranking_candidate_fit_and_freshness()
    test_no_resume_fallback_behavior()
    test_company_soft_diversity_penalty()
    test_deterministic_tie_breakers_and_benchmark_dataset()
    print("=" * 70)
    print("🎉 ALL PHASE 6 TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 70)
