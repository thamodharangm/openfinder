"""
tests/test_profile_store.py
============================
Tests for CandidateProfileStore SQLite persistence and connection safety.
"""

from pathlib import Path
import sys
import tempfile
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.profile_store import CandidateProfileStore


class TestProfileStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_profiles.db"
        self.store = CandidateProfileStore(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_retrieve_profile(self):
        profile_data = {
            "candidate_name": "Karthik Kumar",
            "email": "karthik@example.com",
            "phone": "+919876543210",
            "years_of_experience": 4,
            "seniority_level": "MID",
            "primary_role": "Full Stack Developer",
            "top_skills": ["python", "react", "fastapi", "docker", "postgresql"],
            "target_roles": ["Backend Developer", "Full Stack Engineer"],
            "target_locations": ["Bangalore", "Remote"]
        }

        pid = self.store.save_profile(profile_data)
        self.assertIsNotNone(pid)

        # Retrieve profile
        fetched = self.store.get_profile(pid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["candidate_name"], "Karthik Kumar")
        self.assertEqual(fetched["years_of_experience"], 4)
        self.assertIn("python", fetched["top_skills"])
        self.assertIn("react", fetched["top_skills"])

    def test_list_and_delete_profiles(self):
        pid1 = self.store.save_profile({
            "candidate_name": "Dev One",
            "email": "dev1@test.com",
            "top_skills": ["golang", "kubernetes", "docker"]
        })
        pid2 = self.store.save_profile({
            "candidate_name": "Dev Two",
            "email": "dev2@test.com",
            "top_skills": ["python", "fastapi", "react"]
        })

        profiles = self.store.list_profiles(limit=10)
        self.assertEqual(len(profiles), 2)

        stats = self.store.get_stats()
        self.assertEqual(stats["total_saved_profiles"], 2)

        # Delete profile
        deleted = self.store.delete_profile(pid1)
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_profile(pid1))


if __name__ == "__main__":
    unittest.main()
