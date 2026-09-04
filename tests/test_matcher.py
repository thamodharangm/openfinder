"""
tests/test_matcher.py
======================
Tests for Canonical Skill Normalization and ATS Job Matching.
"""

from pathlib import Path
import sys
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.matcher import JobMatcher, canonicalize_skill


class TestJobMatcher(unittest.TestCase):

    def test_canonicalize_skill_aliases(self):
        self.assertEqual(canonicalize_skill("React.js"), "react")
        self.assertEqual(canonicalize_skill("reactjs"), "react")
        self.assertEqual(canonicalize_skill("FastAPI"), "fastapi")
        self.assertEqual(canonicalize_skill("NodeJS"), "node.js")
        self.assertEqual(canonicalize_skill("K8s"), "kubernetes")
        self.assertEqual(canonicalize_skill("Postgres"), "postgresql")

    def test_calculate_deep_match_high_fit(self):
        candidate_profile = {
            "top_skills": ["python", "fastapi", "docker", "postgresql", "redis"],
            "years_of_experience": 3,
            "target_locations": ["Bangalore", "Remote"],
            "primary_role": "Backend Engineer"
        }

        job_post = {
            "title": "Senior Python Backend Engineer",
            "required_skills": ["python", "fastapi", "postgresql"],
            "preferred_skills": ["docker", "kubernetes"],
            "location": "Bangalore",
            "is_remote": True,
            "content": "Looking for Backend Engineer with 3+ years experience in Python and FastAPI"
        }

        match_res = JobMatcher.calculate_deep_match(candidate_profile, job_post)
        self.assertIn("match_score", match_res)
        self.assertTrue(match_res["match_score"] >= 65, f"Expected high score, got {match_res['match_score']}")
        self.assertIn("Python", match_res["matched_skills"])
        self.assertIn("Fastapi", match_res["matched_skills"])


if __name__ == "__main__":
    unittest.main()
