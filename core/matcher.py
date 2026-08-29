"""
core/matcher.py
===============
Production-grade Multi-Dimensional Candidate-Job Matching & ATS Resume Scoring Engine.

Features:
- Deep 6-Factor weighted scoring: Tech Stack (35%), Experience (20%), Role (15%), Domain (15%), Location (10%), Education (5%).
- Constant-time O(1) canonical skill normalization across 70+ technology ecosystems.
- Semantic skill proximity graph: Grants partial credit for related stacks (e.g. FastAPI <-> Django/Python, Next.js <-> React).
- Domain & industry taxonomy inference (FinTech, SaaS, Healthcare, AI/ML, EdTech, E-Commerce, etc.).
- Actionable ATS resume tailoring recommendations and candidate fit grading.
"""

from collections import defaultdict
from difflib import SequenceMatcher
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# ============================================================================
# 1. CANONICAL SKILL TAXONOMY (O(1) Constant-Time Lookup)
# ============================================================================

_RAW_SKILL_ALIASES: Dict[str, List[str]] = {
    # Frontend
    "react": ["react", "react.js", "reactjs", "react js"],
    "react native": ["react native", "reactnative", "rn"],
    "next.js": ["next", "next.js", "nextjs", "next js"],
    "vue.js": ["vue", "vue.js", "vuejs", "vue 3", "nuxt", "nuxtjs"],
    "angular": ["angular", "angular.js", "angularjs", "angular 2+"],
    "javascript": ["javascript", "js", "es6", "es6+", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "tailwind css": ["tailwind", "tailwindcss", "tailwind css", "tailwind-css"],
    "html/css": ["html", "html5", "css", "css3", "sass", "scss", "less"],
    "redux": ["redux", "redux toolkit", "rtk", "zustand", "mobx"],

    # Backend & Frameworks
    "python": ["python", "py", "python3", "python 3"],
    "fastapi": ["fastapi", "fast api", "fast-api"],
    "django": ["django", "django rest framework", "drf"],
    "flask": ["flask", "flask api"],
    "node.js": ["node", "node.js", "nodejs", "node js"],
    "express.js": ["express", "express.js", "expressjs"],
    "nestjs": ["nest", "nestjs", "nest.js"],
    "java": ["java", "j2ee", "core java", "java 8", "java 11", "java 17", "java 21"],
    "spring boot": ["spring", "spring boot", "springboot", "spring mvc"],
    "golang": ["go", "golang", "gin", "gorm"],
    "rust": ["rust", "actix", "tokio"],
    "c#": ["c#", "csharp", "c sharp"],
    ".net": [".net", "dotnet", ".net core", "asp.net", "asp.net core"],
    "c++": ["c++", "cpp", "c/c++"],
    "php": ["php", "laravel", "symfony", "codeigniter"],
    "ruby": ["ruby", "ruby on rails", "rails"],

    # APIs & Microservices
    "rest api": ["rest", "rest api", "restful", "restful apis", "rest apis", "web apis"],
    "graphql": ["graphql", "graph ql", "apollo"],
    "grpc": ["grpc", "protobuf", "protocol buffers"],
    "microservices": ["microservices", "microservice architecture", "distributed systems"],
    "websockets": ["websocket", "websockets", "socket.io"],

    # Databases & Caching
    "sql": ["sql", "rdbms", "relational database"],
    "postgresql": ["postgres", "postgresql", "psql"],
    "mysql": ["mysql", "mariadb"],
    "mongodb": ["mongo", "mongodb", "nosql"],
    "redis": ["redis", "in-memory cache", "memcached"],
    "elasticsearch": ["elasticsearch", "elastic search", "opensearch"],
    "dynamodb": ["dynamodb", "dynamo db"],
    "cassandra": ["cassandra", "scylladb"],

    # Cloud & DevOps
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda", "ecs", "eks"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "azure": ["azure", "microsoft azure"],
    "docker": ["docker", "containerization", "containers"],
    "kubernetes": ["kubernetes", "k8s", "helm"],
    "terraform": ["terraform", "iac", "infrastructure as code"],
    "ci/cd": ["ci/cd", "cicd", "github actions", "gitlab ci", "jenkins"],
    "linux": ["linux", "unix", "bash", "shell scripting"],

    # Messaging & Streaming
    "kafka": ["kafka", "apache kafka"],
    "rabbitmq": ["rabbitmq", "rabbit mq"],
    "celery": ["celery", "task queue"],

    # AI, ML & Data Science
    "ai/ml": ["ai", "ml", "machine learning", "deep learning", "artificial intelligence"],
    "llm": ["llm", "large language models", "generative ai", "genai", "gpt", "openai", "rag"],
    "langchain": ["langchain", "llamaindex", "vector db", "chromadb", "pinecone", "qdrant"],
    "pytorch": ["pytorch", "torch"],
    "tensorflow": ["tensorflow", "keras"],
    "data science": ["data science", "pandas", "numpy", "scikit-learn", "data analysis"],
    "data engineering": ["data engineer", "spark", "hadoop", "snowflake", "databricks", "dbt"],

    # Mobile
    "flutter": ["flutter", "dart"],
    "android": ["android", "kotlin", "java android"],
    "ios": ["ios", "swift", "swiftui", "objective-c"],

    # QA & Testing
    "unit testing": ["unit test", "unit testing", "pytest", "jest", "junit", "mocha"],
    "automation testing": ["selenium", "cypress", "playwright", "test automation", "sdet", "qa automation"],
}

# Pre-flatten lookup for O(1) canonical skill translation
_CANONICAL_LOOKUP: Dict[str, str] = {}
for canonical, variants in _RAW_SKILL_ALIASES.items():
    _CANONICAL_LOOKUP[canonical.lower()] = canonical
    for v in variants:
        _CANONICAL_LOOKUP[v.lower().strip()] = canonical


def canonicalize_skill(skill_str: str) -> str:
    """Normalizes skill string to canonical form in O(1) constant time."""
    if not skill_str or not isinstance(skill_str, str):
        return ""
    clean = skill_str.lower().strip()
    return _CANONICAL_LOOKUP.get(clean, clean)


# Semantic Proximity Matrix: Related skills yield partial credit (0.6 - 0.8)
_SKILL_PROXIMITY_GRAPH: Dict[str, Dict[str, float]] = {
    "fastapi": {"python": 0.85, "django": 0.75, "flask": 0.80, "rest api": 0.70},
    "django": {"python": 0.85, "fastapi": 0.75, "flask": 0.75, "rest api": 0.70},
    "flask": {"python": 0.85, "fastapi": 0.80, "django": 0.75, "rest api": 0.70},
    "next.js": {"react": 0.90, "typescript": 0.75, "javascript": 0.70},
    "react": {"next.js": 0.85, "redux": 0.75, "javascript": 0.80, "typescript": 0.75},
    "vue.js": {"javascript": 0.80, "typescript": 0.70, "html/css": 0.70},
    "angular": {"typescript": 0.85, "javascript": 0.75},
    "spring boot": {"java": 0.90, "microservices": 0.80, "rest api": 0.70},
    "docker": {"kubernetes": 0.80, "ci/cd": 0.70, "linux": 0.70},
    "kubernetes": {"docker": 0.85, "terraform": 0.75, "aws": 0.75},
    "aws": {"docker": 0.70, "kubernetes": 0.75, "terraform": 0.80, "gcp": 0.75, "azure": 0.75},
    "postgresql": {"sql": 0.85, "mysql": 0.80},
    "mysql": {"sql": 0.85, "postgresql": 0.80},
    "mongodb": {"sql": 0.60, "redis": 0.65},
    "langchain": {"llm": 0.85, "python": 0.75, "ai/ml": 0.80},
    "flutter": {"dart": 0.90, "react native": 0.75, "mobile": 0.80},
    "react native": {"flutter": 0.75, "react": 0.85, "javascript": 0.75},
}


# ============================================================================
# 2. JOB MATCHER ENGINE
# ============================================================================

class JobMatcher:
    """
    Enterprise-Grade Multi-Dimensional Match & ATS Resume Scoring Engine.
    
    Evaluates:
      1. Technical Stack Overlap (35%) - Exact match + semantic proximity graph
      2. Experience & Seniority Fit (20%) - Asymmetric tolerance curve
      3. Role & Title Alignment (15%) - Normalized title variants & token overlap
      4. Domain / Industry Relevance (15%) - Taxonomy inference
      5. Location & Remote Preferences (10%) - City/Regional/WFH alignment
      6. Education & Certifications (5%) - Degree compatibility
    """

    WEIGHTS = {
        "tech_stack": 0.35,
        "experience": 0.20,
        "role_alignment": 0.15,
        "domain": 0.15,
        "location": 0.10,
        "education": 0.05,
    }

    DOMAIN_KEYWORDS = {
        "fintech": ["payment", "banking", "finance", "trading", "crypto", "blockchain", "lending", "wallet", "upi"],
        "healthcare": ["health", "medical", "patient", "clinical", "hipaa", "emr", "telehealth", "pharma"],
        "ecommerce": ["ecommerce", "retail", "cart", "checkout", "shopify", "marketplace", "d2c", "orders"],
        "edtech": ["education", "learning", "student", "course", "lms", "classroom", "tutor"],
        "saas": ["saas", "subscription", "b2b", "enterprise software", "multi-tenant", "crm", "erp"],
        "ai/ml": ["machine learning", "deep learning", "nlp", "computer vision", "data science", "ai", "llm", "genai", "rag"],
        "iot": ["iot", "embedded", "sensors", "hardware", "firmware"],
        "cybersecurity": ["security", "infosec", "penetration testing", "soc", "compliance", "iam", "vulnerability"],
        "cloud/devops": ["aws", "azure", "gcp", "cloud", "serverless", "devops", "sre", "infrastructure"],
        "mobile": ["android", "ios", "mobile", "flutter", "react native", "swift", "kotlin"],
    }

    @staticmethod
    def _fuzzy_skill_match(skill_a: str, skill_b: str, threshold: float = 0.85) -> bool:
        """Checks if two canonical skill names are typographical fuzzy matches."""
        if not skill_a or not skill_b:
            return False
        if skill_a == skill_b:
            return True
        return SequenceMatcher(None, skill_a, skill_b).ratio() >= threshold

    @classmethod
    def _infer_domains(cls, text: str) -> List[str]:
        """Infers industry domains from raw job text."""
        if not text:
            return []
        text_lower = text.lower()
        domains = []
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                domains.append(domain)
        return domains

    @staticmethod
    def _extract_required_experience(exp_str: str) -> Tuple[Optional[int], Optional[int]]:
        """Extracts min and max experience years from strings like '3-5 years', '4+ yrs', 'freshers'."""
        if not exp_str:
            return None, None

        exp_lower = exp_str.lower()
        if any(w in exp_lower for w in ["fresher", "0-", "0 to 1", "0 year", "freshers", "intern", "entry level"]):
            return 0, 1
        if "junior" in exp_lower:
            return 0, 2
        if "lead" in exp_lower or "principal" in exp_lower:
            return 7, 12
        if "senior" in exp_lower or "sr." in exp_lower:
            return 4, 8

        # Range 'X-Y years' or 'X to Y years'
        match_range = re.search(r'(\d+)\s*(?:-|–|to)\s*(\d+)\s*(?:yrs?|years?)?', exp_lower)
        if match_range:
            return int(match_range.group(1)), int(match_range.group(2))

        # 'X+ years'
        match_plus = re.search(r'(\d+)\s*\+\s*(?:yrs?|years?)?', exp_lower)
        if match_plus:
            low = int(match_plus.group(1))
            return low, low + 3

        # 'At least X years' or 'Min X years'
        match_min = re.search(r'(?:at\s+least|min(?:imum)?)\s+(\d+)\s*(?:yrs?|years?)?', exp_lower)
        if match_min:
            low = int(match_min.group(1))
            return low, low + 2

        # Standalone digits
        numbers = [int(n) for n in re.findall(r'\b\d+\b', exp_lower)]
        if len(numbers) >= 2:
            return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        elif len(numbers) == 1:
            return numbers[0], numbers[0] + 2

        return None, None

    @classmethod
    def calculate_deep_match(
        cls,
        candidate_profile: Dict[str, Any],
        job_post: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Computes an exhaustive, multi-factor match evaluation between candidate and job posting.
        """
        # 1. Candidate Profile Extraction
        cand_skills_raw = candidate_profile.get("skills") or candidate_profile.get("top_skills", [])
        cand_exp_years = candidate_profile.get("years_of_experience") or candidate_profile.get("experience_years", 0)
        if isinstance(cand_exp_years, str):
            try:
                cand_exp_years = int(re.search(r'\d+', cand_exp_years).group(0))
            except Exception:
                cand_exp_years = 0

        cand_roles = (
            candidate_profile.get("target_roles")
            or candidate_profile.get("desired_roles")
            or [candidate_profile.get("primary_role", "")]
        )
        cand_domains = candidate_profile.get("desired_domains", [])
        cand_locations = candidate_profile.get("preferred_locations", [])
        cand_remote_pref = str(candidate_profile.get("remote_preference", "any")).lower()
        cand_education = candidate_profile.get("education", {})
        cand_degree = cand_education.get("degree", "") if isinstance(cand_education, dict) else str(cand_education)

        # 2. Job Posting Details Extraction
        req_skills_raw = (
            job_post.get("required_skills")
            or job_post.get("skills")
            or job_post.get("detected_skills", [])
        )
        exp_req_str = job_post.get("experience_required") or job_post.get("full_post_content", "")
        job_title = job_post.get("title") or job_post.get("role") or ""
        job_description = job_post.get("description") or job_post.get("full_post_content") or ""
        job_domains = job_post.get("domains", [])
        if not job_domains:
            job_domains = cls._infer_domains(job_description)
        job_location = job_post.get("location", "")
        job_remote = job_post.get("remote", False) or ("remote" in str(job_location).lower())
        job_edu_req = str(job_post.get("education_required", "")).lower()

        # 3. Canonicalize Skills in O(1)
        cand_skills_canon = [canonicalize_skill(s) for s in cand_skills_raw if s]
        req_skills_canon = [canonicalize_skill(s) for s in req_skills_raw if s]

        # -------------------------------------------------------------
        # Factor 1: Technical Stack Overlap (35%)
        # -------------------------------------------------------------
        matched_skills_set: Set[str] = set()
        missing_skills_set: Set[str] = set()
        tech_score = 70.0

        if req_skills_canon:
            cand_set = set(cand_skills_canon)
            req_set = set(req_skills_canon)

            exact_matches = cand_set.intersection(req_set)
            matched_skills_set.update(exact_matches)
            unmatched_req = req_set - exact_matches

            total_credit = float(len(exact_matches))

            for req_skill in unmatched_req:
                matched = False
                # A. Check Semantic Proximity Graph
                prox_map = _SKILL_PROXIMITY_GRAPH.get(req_skill, {})
                for cand_skill in cand_set:
                    if cand_skill in prox_map:
                        credit = prox_map[cand_skill]
                        total_credit += credit
                        matched_skills_set.add(req_skill)
                        matched = True
                        break

                # B. Check Fuzzy Typographical Match
                if not matched:
                    for cand_skill in cand_set:
                        if cls._fuzzy_skill_match(req_skill, cand_skill):
                            total_credit += 0.90
                            matched_skills_set.add(req_skill)
                            matched = True
                            break

                if not matched:
                    missing_skills_set.add(req_skill)

            tech_score = (total_credit / len(req_set)) * 100.0
            tech_score = max(0.0, min(100.0, tech_score))
        else:
            matched_skills_set.update(cand_skills_canon[:4])

        # -------------------------------------------------------------
        # Factor 2: Experience & Seniority Fit (20%)
        # -------------------------------------------------------------
        min_exp, max_exp = cls._extract_required_experience(exp_req_str)
        if min_exp is None:
            exp_score = 80.0
        else:
            if max_exp is None:
                if cand_exp_years >= min_exp:
                    exp_score = 100.0
                else:
                    diff = min_exp - cand_exp_years
                    exp_score = max(20.0, 100.0 - (diff * 25.0))
            else:
                if min_exp <= cand_exp_years <= max_exp:
                    exp_score = 100.0
                elif cand_exp_years < min_exp:
                    diff = min_exp - cand_exp_years
                    exp_score = max(20.0, 100.0 - (diff * 25.0))
                else:
                    diff = cand_exp_years - max_exp
                    exp_score = max(55.0, 100.0 - (diff * 12.0))

        # -------------------------------------------------------------
        # Factor 3: Role & Title Alignment (15%)
        # -------------------------------------------------------------
        role_score = 60.0
        if cand_roles and job_title:
            job_title_lower = job_title.lower()
            cand_roles_lower = [r.lower().strip() for r in cand_roles if r]
            for role in cand_roles_lower:
                if role == job_title_lower or role in job_title_lower or job_title_lower in role:
                    role_score = 100.0
                    break
                job_tokens = set(re.findall(r'\w+', job_title_lower)) - {"developer", "engineer", "lead", "senior", "junior"}
                role_tokens = set(re.findall(r'\w+', role)) - {"developer", "engineer", "lead", "senior", "junior"}
                if job_tokens and role_tokens and (job_tokens & role_tokens):
                    role_score = max(role_score, 85.0)
            if role_score == 60.0 and cand_roles_lower:
                best_sim = max(SequenceMatcher(None, job_title_lower, r).ratio() for r in cand_roles_lower)
                role_score = max(role_score, best_sim * 100.0)

        # -------------------------------------------------------------
        # Factor 4: Domain / Industry Relevance (15%)
        # -------------------------------------------------------------
        domain_score = 50.0
        if job_domains and cand_domains:
            overlap = set(job_domains).intersection(set(cand_domains))
            domain_score = 100.0 if overlap else 35.0

        # -------------------------------------------------------------
        # Factor 5: Location & Remote Preferences (10%)
        # -------------------------------------------------------------
        location_score = 50.0
        if job_remote:
            location_score = 100.0 if cand_remote_pref in ["remote", "any"] else 50.0
        elif job_location:
            if cand_locations:
                job_loc_lower = str(job_location).lower()
                for loc in cand_locations:
                    if loc.lower() in job_loc_lower or job_loc_lower in loc.lower():
                        location_score = 100.0
                        break
                else:
                    location_score = 40.0
            else:
                location_score = 65.0

        # -------------------------------------------------------------
        # Factor 6: Education & Certifications (5%)
        # -------------------------------------------------------------
        edu_score = 60.0
        if job_edu_req and cand_degree:
            cand_deg_lower = cand_degree.lower()
            if any(d in job_edu_req for d in ["bachelor", "btech", "be", "bs"]) and any(d in cand_deg_lower for d in ["bachelor", "btech", "be", "bs"]):
                edu_score = 100.0
            elif any(d in job_edu_req for d in ["master", "mtech", "ms"]) and any(d in cand_deg_lower for d in ["master", "mtech", "ms"]):
                edu_score = 100.0
            elif "or equivalent" in job_edu_req or "experience" in job_edu_req:
                edu_score = 85.0
            else:
                edu_score = 45.0

        # -------------------------------------------------------------
        # Weighted Overall Score Computation
        # -------------------------------------------------------------
        final_score = (
            tech_score * cls.WEIGHTS["tech_stack"] +
            exp_score * cls.WEIGHTS["experience"] +
            role_score * cls.WEIGHTS["role_alignment"] +
            domain_score * cls.WEIGHTS["domain"] +
            location_score * cls.WEIGHTS["location"] +
            edu_score * cls.WEIGHTS["education"]
        )
        final_score = int(max(10, min(round(final_score), 100)))

        # Candidate Fit Grade
        if final_score >= 85:
            grade = "🌟 Top Match (High Interview Probability)"
        elif final_score >= 70:
            grade = "⚡ Strong Match"
        elif final_score >= 50:
            grade = "⚠️ Moderate Match (Upskilling Advantage)"
        else:
            grade = "❌ Low Match"

        # Actionable ATS Tailoring Recommendations
        tailoring_advice: List[str] = []
        if missing_skills_set:
            missing_title = [s.title() for s in sorted(list(missing_skills_set))[:5]]
            tailoring_advice.append(f"Highlight any familiarity or project impact with: {', '.join(missing_title)}.")
        if min_exp is not None and cand_exp_years < min_exp:
            tailoring_advice.append(f"Emphasize high-complexity projects to bridge the {min_exp}+ yrs seniority expectation.")
        elif max_exp is not None and cand_exp_years > max_exp:
            tailoring_advice.append("Frame experience around hands-on execution to avoid overqualification perception.")
        if role_score < 75.0 and job_title:
            tailoring_advice.append(f"Align resume headline with target role '{job_title}'.")
        if domain_score < 50.0 and job_domains:
            tailoring_advice.append(f"Incorporate domain terminology for {', '.join(job_domains)} in project descriptions.")

        return {
            "match_score": final_score,
            "match_grade": grade,
            "matched_skills": [s.title() for s in sorted(list(matched_skills_set))],
            "missing_skills": [s.title() for s in sorted(list(missing_skills_set))],
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
        Adapter for OpportunityRanker callers.
        Delegates directly to calculate_deep_match.
        """
        candidate_profile = {
            "skills": candidate_skills,
            "years_of_experience": candidate_exp_years
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
        Evaluates and ranks a batch of job posts against a candidate profile.
        """
        results = []
        for post in posts:
            deep_result = cls.calculate_deep_match(candidate_profile, post)
            post_copy = post.copy()
            post_copy.update(deep_result)
            results.append(post_copy)

        results.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return [p for p in results if p.get("match_score", 0) >= min_score]
