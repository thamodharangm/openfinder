"""
tests/test_scout_features.py
=============================
Automated test suite verifying the 7 Pillars & AI Hiring Intent Classifier.
"""

from pathlib import Path
import sys
import unittest

# Ensure root in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.ai_classifier import AIHiringIntentClassifier
from core.linkedin_urls import compute_post_fingerprint
from core.post_extractor import LinkedInPostExtractor
from core.search_intent import SearchIntentParser
from core.service import OpenFinderService
from core.time_utils import calculate_freshness_score


class TestScoutFeatures(unittest.TestCase):

    def test_search_intent_negative_dorks(self):
        intent = SearchIntentParser.parse("React Developer", location="Bangalore")
        dorks = intent.generate_dork_queries()
        self.assertTrue(len(dorks) >= 3)
        self.assertTrue(any('-("open to work"' in d for d in dorks))

    def test_freshness_half_life_scoring(self):
        score_15m = calculate_freshness_score(15, max_age_minutes=1440)
        score_2h = calculate_freshness_score(120, max_age_minutes=1440)
        score_8h = calculate_freshness_score(480, max_age_minutes=1440)
        score_20h = calculate_freshness_score(1200, max_age_minutes=1440)

        self.assertTrue(score_15m >= 95)
        self.assertTrue(score_2h >= 85 and score_2h < 95)
        self.assertTrue(score_8h >= 70 and score_8h < 85)
        self.assertTrue(score_20h >= 30 and score_20h < 70)

    def test_post_fingerprint_dedup(self):
        fp1 = compute_post_fingerprint(
            url="https://www.linkedin.com/posts/acme-activity-7123456789012345678-abcd",
            company="Acme Corp",
            role="React Developer",
            contact_email="hr@acme.com"
        )
        fp2 = compute_post_fingerprint(
            url="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/",
            company="Acme Corp",
            role="React Developer",
            contact_email="hr@acme.com"
        )
        self.assertEqual(fp1, fp2)

    def test_serp_snippet_extraction(self):
        res = LinkedInPostExtractor.extract_from_serp_snippet(
            url="https://www.linkedin.com/posts/techcorp-react-activity-7123456789012345678-abcd",
            title="TechCorp is hiring React Developer",
            snippet="We are looking for a Senior React Engineer in Bangalore. CTC: 20 LPA. Send resume to hr@techcorp.com."
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("hr@techcorp.com", res["recruiter_emails"])
        self.assertEqual(res["company"], "Techcorp")

    def test_ai_classifier_recruiter_vs_jobseeker(self):
        clf = AIHiringIntentClassifier()

        recruiter_res = clf.classify("We are hiring Python developers for Bangalore office. Email resume to jobs@fintech.io")
        self.assertTrue(recruiter_res.is_hiring)
        self.assertIn("jobs@fintech.io", recruiter_res.recruiter_emails)

        seeker_res = clf.classify("I am actively looking for React roles with 2 yrs exp #opentowork")
        self.assertFalse(seeker_res.is_hiring)
        self.assertEqual(seeker_res.hiring_type, "JOB_SEEKER_OUTREACH")

    def test_service_prewarm_and_classify(self):
        service = OpenFinderService()
        clf_res = service.classify_hiring_post("Hiring Full Stack developer at Acme Labs. Send CV to careers@acmelabs.com")
        self.assertEqual(clf_res["status"], "success")
        self.assertTrue(clf_res["classification"]["is_hiring"])


if __name__ == "__main__":
    unittest.main()
