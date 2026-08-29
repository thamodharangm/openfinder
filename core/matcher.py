import re
from typing import Dict, List, Any, Optional, Tuple
from difflib import SequenceMatcher
from collections import defaultdict


def canonicalize_skill(s: str) -> str:
    """Normalize skill strings for consistent comparison."""
    sl = s.lower().strip()
    # Common aliases
    aliases = {
        "react": ["react", "react.js", "reactjs"],
        "node": ["node", "node.js", "nodejs"],
        "express": ["express", "express.js", "expressjs"],
        "mongodb": ["mongo", "mongodb"],
        "react native": ["react native", "reactnative"],
        "next.js": ["next", "next.js", "nextjs"],
        "javascript": ["js", "javascript", "es6", "es6+"],
        "tailwind css": ["tailwind", "tailwindcss", "tailwind css"],
        "rest api": ["rest", "rest api", "restful", "restful apis"],
        "typescript": ["ts", "typescript"],
        "postgresql": ["postgres", "postgresql", "psql"],
        "aws": ["aws", "amazon web services"],
        "gcp": ["gcp", "google cloud"],
        "azure": ["azure", "microsoft azure"],
        "docker": ["docker", "containerization"],
        "kubernetes": ["kubernetes", "k8s"],
        "python": ["python", "py"],
        "django": ["django", "django rest framework"],
        "flask": ["flask", "flask api"],
        "sql": ["sql", "mysql", "sql server", "postgresql"],
    }
    for canonical, variants in aliases.items():
        if sl in variants:
            return canonical
    return sl


class JobMatcher:
    """
    Deep Multi-Dimensional Match Engine.
    
    Evaluates:
      1. Technical Stack Overlap (35%) - exact + semantic similarity
      2. Experience & Seniority Fit (20%)
      3. Role & Title Alignment (15%)
      4. Domain / Industry Relevance (15%)
      5. Location & Remote Preferences (10%)
      6. Education & Certifications (5%)
    
    Provides actionable ATS resume tailoring recommendations.
    """

    # Configurable weights (sum to 1.00)
    WEIGHTS = {
        "tech_stack": 0.35,
        "experience": 0.20,
        "role_alignment": 0.15,
        "domain": 0.15,
        "location": 0.10,
        "education": 0.05,
    }

    # Domain keyword mapping for industry inference
    DOMAIN_KEYWORDS = {
        "fintech": ["payment", "banking", "finance", "trading", "crypto", "blockchain"],
        "healthcare": ["health", "medical", "patient", "clinical", "hipaa", "emr"],
        "ecommerce": ["ecommerce", "retail", "cart", "checkout", "shopify", "marketplace"],
        "edtech": ["education", "learning", "student", "course", "lms"],
        "saas": ["saas", "subscription", "b2b", "enterprise software"],
        "ai/ml": ["machine learning", "deep learning", "nlp", "computer vision", "data science", "ai"],
        "iot": ["iot", "embedded", "sensors", "hardware"],
        "cybersecurity": ["security", "infosec", "penetration testing", "soc", "compliance"],
        "cloud": ["aws", "azure", "gcp", "cloud", "serverless"],
        "mobile": ["android", "ios", "mobile", "flutter", "react native"],
    }

    @staticmethod
    def _fuzzy_skill_match(skill_a: str, skill_b: str, threshold: float = 0.85) -> bool:
        """Check if two canonical skills are fuzzy similar."""
        if skill_a == skill_b:
            return True
        similarity = SequenceMatcher(None, skill_a, skill_b).ratio()
        return similarity >= threshold

    @classmethod
    def _infer_domains(cls, text: str) -> List[str]:
        """Infer potential domains from a text blob."""
        text_lower = text.lower()
        domains = []
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                domains.append(domain)
        return domains

    @staticmethod
    def _extract_required_experience(exp_str: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract min and max years from string like '3-5 years' or '5+ years'."""
        if not exp_str:
            return None, None
        exp_str_lower = exp_str.lower()
        # Pattern for range "X-Y years"
        match_range = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*years?', exp_str_lower)
        if match_range:
            return int(match_range.group(1)), int(match_range.group(2))
        # Pattern for "X+ years"
        match_plus = re.search(r'(\d+)\s*\+\s*years?', exp_str_lower)
        if match_plus:
            return int(match_plus.group(1)), None
        # Pattern for "at least X years"
        match_at_least = re.search(r'at least\s+(\d+)\s+years?', exp_str_lower)
        if match_at_least:
            return int(match_at_least.group(1)), None
        # Pattern for "X years"
        match_single = re.search(r'(\d+)\s*years?', exp_str_lower)
        if match_single:
            return int(match_single.group(1)), int(match_single.group(1))
        # Fallback single digit search
        match_any = re.search(r'(\d+)', exp_str_lower)
        if match_any:
            return int(match_any.group(1)), None
        return None, None

    @classmethod
    def calculate_deep_match(
        cls,
        candidate_profile: Dict[str, Any],
        job_post: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compute deep match score using candidate profile and job posting details.
        """
        # Extract candidate info
        cand_skills_raw = candidate_profile.get("skills") or candidate_profile.get("top_skills", [])
        cand_exp_years = candidate_profile.get("years_of_experience") or candidate_profile.get("experience_years", 0)
        cand_roles = candidate_profile.get("target_roles") or candidate_profile.get("desired_roles") or [candidate_profile.get("primary_role", "")]
        cand_domains = candidate_profile.get("desired_domains", [])
        cand_locations = candidate_profile.get("preferred_locations", [])
        cand_remote_pref = str(candidate_profile.get("remote_preference", "any")).lower()
        cand_education = candidate_profile.get("education", {})
        cand_degree = cand_education.get("degree", "") if isinstance(cand_education, dict) else str(cand_education)

        # Extract job info
        req_skills_raw = job_post.get("required_skills") or job_post.get("skills") or job_post.get("detected_skills", [])
        exp_req_str = job_post.get("experience_required") or job_post.get("full_post_content", "")
        job_title = job_post.get("title") or job_post.get("role") or ""
        job_description = job_post.get("description") or job_post.get("full_post_content") or ""
        job_domains = job_post.get("domains", [])
        if not job_domains:
            job_domains = cls._infer_domains(job_description)
        job_location = job_post.get("location", "")
        job_remote = job_post.get("remote", False) or ("remote" in job_location.lower())
        job_edu_req = str(job_post.get("education_required", "")).lower()

        # Canonicalize skills
        cand_skills_canon = [canonicalize_skill(s) for s in cand_skills_raw if s]
        req_skills_canon = [canonicalize_skill(s) for s in req_skills_raw if s]

        # -------------------------------
        # 1. Technical Stack Overlap (35%)
        # -------------------------------
        if req_skills_canon:
            exact_matches = set(cand_skills_canon) & set(req_skills_canon)
            missing_exact = set(req_skills_canon) - set(cand_skills_canon)
            
            fuzzy_matched_req = set()
            for req_skill in missing_exact:
                for cand_skill in set(cand_skills_canon) - exact_matches:
                    if cls._fuzzy_skill_match(req_skill, cand_skill):
                        fuzzy_matched_req.add(req_skill)
                        break
            
            total_effective = len(exact_matches) + len(fuzzy_matched_req)
            tech_score = (total_effective / len(req_skills_canon)) * 100
            matched_skills = set(req_skills_canon) - (missing_exact - fuzzy_matched_req)
            missing_skills = set(req_skills_canon) - matched_skills
        else:
            tech_score = 70
            matched_skills = set(cand_skills_canon[:3])
            missing_skills = set()

        # -------------------------------
        # 2. Experience & Seniority Fit (20%)
        # -------------------------------
        min_exp, max_exp = cls._extract_required_experience(exp_req_str)
        if min_exp is None:
            exp_score = 80
        else:
            if max_exp is None:
                if cand_exp_years >= min_exp:
                    exp_score = 100
                else:
                    diff = min_exp - cand_exp_years
                    exp_score = max(20, 100 - diff * 25)
            else:
                if min_exp <= cand_exp_years <= max_exp:
                    exp_score = 100
                elif cand_exp_years < min_exp:
                    diff = min_exp - cand_exp_years
                    exp_score = max(20, 100 - diff * 30)
                else:
                    diff = cand_exp_years - max_exp
                    exp_score = max(50, 100 - diff * 15)

        # -------------------------------
        # 3. Role & Title Alignment (15%)
        # -------------------------------
        role_score = 0
        if cand_roles and job_title:
            job_title_lower = job_title.lower()
            cand_roles_lower = [r.lower() for r in cand_roles if r]
            for role in cand_roles_lower:
                if role in job_title_lower or job_title_lower in role:
                    role_score = 100
                    break
                job_tokens = set(re.findall(r'\w+', job_title_lower))
                role_tokens = set(re.findall(r'\w+', role))
                if job_tokens & role_tokens:
                    role_score = max(role_score, 70)
            if role_score == 0 and cand_roles_lower:
                best_sim = max(
                    SequenceMatcher(None, job_title_lower, role).ratio()
                    for role in cand_roles_lower
                )
                role_score = best_sim * 100
        else:
            role_score = 60

        # -------------------------------
        # 4. Domain / Industry Relevance (15%)
        # -------------------------------
        if job_domains and cand_domains:
            overlap = set(job_domains) & set(cand_domains)
            domain_score = 100 if overlap else 30
        else:
            domain_score = 50

        # -------------------------------
        # 5. Location & Remote Preferences (10%)
        # -------------------------------
        location_score = 50
        if job_remote is True:
            if cand_remote_pref in ["remote", "any"]:
                location_score = 100
            else:
                location_score = 40
        elif job_location:
            if cand_locations:
                job_loc_lower = job_location.lower()
                for loc in cand_locations:
                    if loc.lower() in job_loc_lower or job_loc_lower in loc.lower():
                        location_score = 100
                        break
                else:
                    location_score = 40
            else:
                location_score = 60

        # -------------------------------
        # 6. Education & Certifications (5%)
        # -------------------------------
        edu_score = 50
        if job_edu_req and cand_degree:
            if any(deg in job_edu_req for deg in ["bachelor", "btech", "be", "bs"]) and any(deg in cand_degree.lower() for deg in ["bachelor", "btech", "be", "bs"]):
                edu_score = 100
            elif any(deg in job_edu_req for deg in ["master", "mtech", "ms"]) and any(deg in cand_degree.lower() for deg in ["master", "mtech", "ms"]):
                edu_score = 100
            elif "or equivalent" in job_edu_req or "experience" in job_edu_req:
                edu_score = 80
            else:
                edu_score = 40
        else:
            edu_score = 60

        # -------------------------------
        # Weighted Final Score
        # -------------------------------
        final_score = (
            tech_score * cls.WEIGHTS["tech_stack"] +
            exp_score * cls.WEIGHTS["experience"] +
            role_score * cls.WEIGHTS["role_alignment"] +
            domain_score * cls.WEIGHTS["domain"] +
            location_score * cls.WEIGHTS["location"] +
            edu_score * cls.WEIGHTS["education"]
        )
        final_score = int(max(10, min(final_score, 100)))

        # Grading
        if final_score >= 85:
            grade = "🌟 Top Match (High Interview Probability)"
        elif final_score >= 70:
            grade = "⚡ Strong Match"
        elif final_score >= 50:
            grade = "⚠️ Moderate Match (Upskilling Advantage)"
        else:
            grade = "❌ Low Match"

        # ATS Tailoring Recommendations
        tailoring_advice = []
        if missing_skills:
            missing_title = [s.title() for s in list(missing_skills)[:5]]
            tailoring_advice.append(f"Highlight any familiarity or mini-projects with: {', '.join(missing_title)}.")
        if min_exp and cand_exp_years < min_exp:
            tailoring_advice.append(f"Emphasize high-impact project results to bridge the {min_exp}+ yrs requirement.")
        elif max_exp and cand_exp_years > max_exp:
            tailoring_advice.append("Consider downplaying years to avoid overqualification perception.")
        if role_score < 70 and job_title:
            tailoring_advice.append(f"Tailor your resume title/headline to align with '{job_title}'.")
        if domain_score < 50:
            tailoring_advice.append("Add relevant domain-specific projects or keywords from the job description.")
        if location_score < 50:
            tailoring_advice.append("Address location preference in cover letter or mention willingness to relocate/remote.")

        return {
            "match_score": final_score,
            "match_grade": grade,
            "matched_skills": [s.title() for s in matched_skills],
            "missing_skills": [s.title() for s in missing_skills],
            "tech_score": round(tech_score, 1),
            "exp_score": round(exp_score, 1),
            "role_score": round(role_score, 1),
            "domain_score": round(domain_score, 1),
            "location_score": round(location_score, 1),
            "education_score": round(edu_score, 1),
            "ats_recommendations": tailoring_advice
        }

    @classmethod
    def calculate_weighted_match(
        cls,
        candidate_skills: List[str],
        candidate_exp_years: int,
        required_skills: List[str],
        experience_required_str: str
    ) -> Dict[str, Any]:
        """
        Legacy adapter for existing OpportunityRanker callers.
        Uses calculate_deep_match under the hood.
        """
        candidate_profile = {
            "skills": candidate_skills,
            "experience_years": candidate_exp_years
        }
        job_post = {
            "required_skills": required_skills,
            "experience_required": experience_required_str
        }
        return cls.calculate_deep_match(candidate_profile, job_post)

    @classmethod
    def rank_and_score_posts_deep(
        cls,
        candidate_profile: Dict[str, Any],
        posts: List[Dict[str, Any]],
        min_score: int = 35
    ) -> List[Dict[str, Any]]:
        """
        Score all posts using deep match and rank by score.
        """
        results = []
        for post in posts:
            deep_result = cls.calculate_deep_match(candidate_profile, post)
            post_copy = post.copy()
            post_copy.update(deep_result)
            results.append(post_copy)

        results.sort(key=lambda x: x["match_score"], reverse=True)
        return [p for p in results if p["match_score"] >= min_score]
