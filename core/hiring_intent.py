"""
core/hiring_intent.py
=====================
Production-grade Hiring Intent Classifier, Job Role Extractor, Location Alignment,
Experience Fit, and Multi-Signal Quality Scoring Engine.

Features:
- Pre-compiled high-performance regular expressions with zero catastrophic backtracking.
- Exhaustive taxonomy for 20+ modern tech stacks (React, Python, Go, Rust, AI/ML, DevOps, Mobile, QA, etc.).
- Robust multi-role bullet list parsing and label extraction.
- Granular location normalization covering primary Indian tech hubs, regional states, and global remote setups.
- Experience range extraction supporting "+", "to", "-", and worded variants.
- Deterministic multi-factor scoring with clear explainability reasons.
"""

from dataclasses import dataclass
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from core.spam_filter import is_spam_or_bait
except ImportError:
    # Graceful fallback if spam filter is unavailable
    def is_spam_or_bait(text: str) -> Tuple[bool, str]:
        return False, ""


# ============================================================================
# 1. JOB ROLE EXTRACTOR
# ============================================================================

class JobRoleExtractor:
    """
    Extracts structured job roles from LinkedIn post text using multiple strategies:
    1. Key-value labeled patterns (Role:, Position:, Job Title:, Hiring for:, etc.)
    2. Declarative hiring statements (Looking for a [Role], We need [Role], etc.)
    3. Multi-role bullet lists (• React Developer, - Python Engineer, etc.)
    """

    _BULLET_CHARS = r"•\*\-\–\—▪▫▶✓✔►"
    
    _ROLE_CORE_NOUNS = (
        r"developer|engineer|lead|architect|consultant|specialist|intern|"
        r"fresher|tester|designer|analyst|manager|administrator|scientist|"
        r"programmer|coder|sdet|sre|devops"
    )

    # Pre-compiled high-speed regex patterns
    _COMPILED_BULLET_PATTERN = re.compile(
        rf"(?:^|\n)\s*[{_BULLET_CHARS}]\s*([A-Za-z0-9.+/#\-\s]+?(?:{_ROLE_CORE_NOUNS}))\b",
        re.IGNORECASE | re.MULTILINE
    )

    _COMPILED_ROLE_PATTERNS = [
        re.compile(
            r"(?:position|role|job\s+title|profile|designation)\s*:\s*([^\n.,|;!#]+)",
            re.IGNORECASE
        ),
        re.compile(
            r"(?:urgently\s+hiring|actively\s+hiring|hiring|urgent\s+opening[s]?|openings?|vacanc(?:y|ies))\s+(?:for\s+)?([^\n.,|;!#]+)",
            re.IGNORECASE
        ),
        re.compile(
            rf"(?:looking\s+(?:for|to\s+hire)\s+(?:a|an|[0-9]+)?)\s*([A-Za-z0-9.+/#\-\s]+?(?:{_ROLE_CORE_NOUNS}))\b",
            re.IGNORECASE
        ),
        re.compile(
            rf"(?:need|require[sd]?|seeking)\s+(?:a|an|[0-9]+)?\s*([A-Za-z0-9.+/#\-\s]+?(?:{_ROLE_CORE_NOUNS}))\b",
            re.IGNORECASE
        ),
    ]

    _INVALID_ROLE_FRAGMENTS = {
        "an immediate", "urgent joiners", "candidates", "team", "the team",
        "immediate joiner", "immediate joiners", "freshers", "experienced",
        "passionate people", "talent", "someone", "anyone", "professionals",
        "rockstars", "ninjas", "enthusiasts", "our team", "our engineering team",
        "our company", "our client", "our office", "our bangalore engineering team",
        "alert", "hiring alert", "for", "join our team", "immediate", "urgent",
        "good understanding of azure devops", "for an exciting opportunity", "an exciting opportunity",
        "hiring", "immediate hiring", "job opening", "job alert"
    }

    _SPLIT_DELIMITERS = re.compile(
        r"(?:\sat\s|\sin\s|\swith\s|📍|📌|experience|exp\b|budget|ctc|salary|\(|\)|\[|\]|@|₹|\$)",
        re.IGNORECASE
    )

    @classmethod
    def extract_roles(cls, text: str, default_title: str = "Software Engineer") -> List[str]:
        """
        Extracts clean, normalized role titles from job description text.
        """
        if not text:
            return [default_title]

        roles: List[str] = []
        seen_roles_lower: Set[str] = set()

        def _add_role(role_candidate: str):
            clean = re.sub(r"\s+", " ", role_candidate).strip()
            # Strip hashtag signs and noise
            clean = clean.replace("#", "").strip()
            # Split off common trailing noise like location, experience, or brackets
            clean = cls._SPLIT_DELIMITERS.split(clean)[0].strip()
            # Strip trailing punctuation
            clean = clean.strip(" :,-–—•*|;/")
            clean_lower = clean.lower()

            # Reject non-role organizational phrases
            if any(clean_lower.startswith(p) for p in ["our ", "the ", "a new "]) and not any(
                n in clean_lower for n in ["developer", "engineer", "lead", "architect", "designer", "tester", "scientist", "manager"]
            ):
                return

            if (
                len(clean) >= 4
                and clean_lower not in seen_roles_lower
                and clean_lower not in cls._INVALID_ROLE_FRAGMENTS
                and not clean_lower.isdigit()
            ):
                seen_roles_lower.add(clean_lower)
                roles.append(clean.title())

        # 1. Check bullet points
        for match in cls._COMPILED_BULLET_PATTERN.finditer(text):
            _add_role(match.group(1))

        # 2. Check standard labeled patterns
        for pattern in cls._COMPILED_ROLE_PATTERNS:
            for match in pattern.finditer(text):
                _add_role(match.group(1))

        if not roles:
            return [default_title]

        return roles


# ============================================================================
# 2. HIRING INTENT CLASSIFIER
# ============================================================================

class HiringIntentClassifier:
    """
    Deterministic, multi-signal hiring-intent classifier that distinguishes:
      - Genuine Recruiters / Founders / Hiring Managers (HIRING)
      - Job Seekers / Candidates / #OpenToWork (JOB_SEEKER)
      - Tutorials / Promotional / Industry Advice (NON_HIRING)
      - Ambiguous statements (AMBIGUOUS)
    """

    # 1. POSITIVE HIRING SIGNALS (Compiled with weights)
    _POSITIVE_HIRING_RAW: List[Tuple[str, float]] = [
        (r"\b(?:we\s+are|we're|currently|urgently|actively)\s+hiring\b", 0.40),
        (r"\bwe\s+have\s+(?:an?\s+)?(?:urgent\s+)?(?:opening[s]?|vacanc(?:y|ies))\b", 0.35),
        (r"\bhiring\s+(?:for|urgent|immediate|alert|opportunity|[0-9]+|\b)", 0.35),
        (r"\blooking\s+(?:for|to\s+hire)\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|fresher|intern|lead|architect|consultant|specialist|analyst)", 0.35),
        (r"\bi\s+am\s+looking\s+for\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|lead|specialist)", 0.35),
        (r"\b(?:need|require[sd]?|seeking)\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|lead|specialist)", 0.30),
        (r"\b(?:job\s+)?opening[s]?\s+(?:for|at|in)\b", 0.30),
        (r"\bjoin\s+our\s+(?:[a-zA-Z\s]+)?(?:team|company)\b", 0.30),
        (r"\b(?:send|share|email|drop|dm|forward)\s+(?:your\s+)?(?:resume|cv|profile)\b", 0.30),
        (r"\b(?:walk-in|walkin)\s+interview\b", 0.35),
        (r"\bimmediate\s+joiner[s]?\b", 0.25),
        (r"\bapply\s+(?:now|here|via|at)\b", 0.25),
        (r"\binterested\s+candidates\s+(?:can|please|dm|send|email)\b", 0.30),
        (r"\bjob\s+location\s*:\b", 0.20),
        (r"\bexperience\s*(?:required|needed)?\s*:\s*\d", 0.20),
        (r"\b(?:ctc|salary|budget)\s*:\s*", 0.20),
        (r"\bnotice\s+period\s*:\b", 0.20),
        (r"\btech\s+stack\s*:\b", 0.20),
        (r"\bjob\s+type\s*:\s*(?:full-time|contract|remote|hybrid)", 0.20),
    ]

    # 2. JOB-SEEKER OVERRIDE SIGNALS (Negative)
    _JOB_SEEKER_RAW: List[Tuple[str, float]] = [
        (r"\b(?:i\s+am|i'm|myself)\s+(?:a|an)?\s*[a-zA-Z\s]*\s*(?:looking|seeking|searching)\s+for\s+(?:a\s+)?(?:job|opportunity|opportunities|role|position|internship|project)\b", 0.90),
        (r"\b(?:i\s+am|i'm)\s+(?:actively\s+)?(?:looking|seeking)\s+for\s+(?:my\s+next\s+)?(?:job|opportunity|opportunities|role)\b", 0.90),
        (r"\b(?:actively\s+looking|seeking\s+new\s+opportunities|available\s+for\s+opportunities)\b", 0.85),
        (r"\b(?:open\s+to\s+work|opentowork|#opentowork)\b", 0.95),
        (r"\b(?:please\s+refer\s+me|looking\s+for\s+referral[s]?|referral\s+needed|any\s+leads\s+appreciated)\b", 0.85),
        (r"\b(?:need\s+a\s+job|looking\s+for\s+job|seeking\s+job|unemployed|fresher\s+looking\s+for\s+job)\b", 0.90),
        (r"\b(?:hire\s+me|open\s+for\s+work)\b", 0.90),
        (r"\bhiring\s+managers?\s*(?:,|please|\.)?\s*(?:dm|reach\s+out|refer|review\s+my|check\s+my|contact\s+me)\b", 0.85),
        (r"\bany\s+hiring\s+for\s+(?:freshers?|react|python|developers?|engineers?)\s*\?", 0.80),
        (r"\bmy\s+notice\s+period\s+is\s+(?:serving|immediate|30\s+days|15\s+days)\b", 0.70),
    ]

    # 3. NON-HIRING PROMOTIONAL / TUTORIAL / ADVICE PATTERNS
    _NON_HIRING_RAW: List[Tuple[str, float]] = [
        (r"\b(?:tips?\s+to\s+get\s+(?:hired|a\s+job)|how\s+to\s+get\s+hired|crack\s+the\s+interview)\b", 0.80),
        (r"\b(?:top\s+\d+\s+interview\s+questions|react\s+tutorial|learn\s+react\s+in\s+\d+|python\s+roadmap)\b", 0.85),
        (r"\b(?:free\s+webinar|register\s+for\s+(?:our\s+)?(?:webinar|masterclass|course|bootcamp))\b", 0.90),
        (r"\b(?:react\s+is\s+(?:in\s+high\s+demand|the\s+future)|why\s+react\s+is|future\s+of\s+ai)\b", 0.75),
        (r"\b(?:salary\s+trends|average\s+salary\s+of)\b", 0.70),
        (r"\b(?:5\s+tips|10\s+tips|common\s+mistakes\s+in|cheat\s+sheet)\b", 0.80),
        (r"\b(?:congratulations\s+to\s+our\s+placed\s+students|student\s+got\s+placed)\b", 0.85),
    ]

    # Pre-compile regex lists for max performance
    POSITIVE_HIRING_PATTERNS = [(re.compile(p, re.IGNORECASE), w) for p, w in _POSITIVE_HIRING_RAW]
    JOB_SEEKER_PATTERNS = [(re.compile(p, re.IGNORECASE), w) for p, w in _JOB_SEEKER_RAW]
    NON_HIRING_PATTERNS = [(re.compile(p, re.IGNORECASE), w) for p, w in _NON_HIRING_RAW]

    # Author Headline Signals
    RECRUITER_HEADLINES = [
        "recruiter", "talent acquisition", "talent partner", "staffing",
        "human resources", "hr manager", "hr executive", "hrbp", "hiring manager",
        "talent lead", "people operations", "head of talent", "technical recruiter"
    ]
    FOUNDER_HEADLINES = [
        "founder", "co-founder", "ceo", "cto", "managing director", "director", "owner", "partner"
    ]
    HIRING_MANAGER_HEADLINES = [
        "engineering manager", "head of engineering", "tech lead", "team lead", "vp of engineering",
        "director of engineering", "lead architect"
    ]
    JOB_SEEKER_HEADLINES = [
        "open to work", "opentowork", "#opentowork", "job seeker", "looking for opportunities",
        "aspiring", "student", "seeking role", "fresher", "actively looking"
    ]

    @classmethod
    def detect_author_type(cls, author_headline: str = "", author_name: str = "") -> str:
        combined = f"{author_headline} {author_name}".lower().strip()
        if not combined:
            return "UNKNOWN"

        for signal in cls.JOB_SEEKER_HEADLINES:
            if signal in combined:
                return "JOB_SEEKER"

        for signal in cls.FOUNDER_HEADLINES:
            if re.search(r"\b" + re.escape(signal) + r"\b", combined):
                return "FOUNDER"

        if "hr" in combined.split() or any(
            re.search(r"\b" + re.escape(s) + r"\b", combined)
            for s in ["hr", "human resources", "hr manager", "hr executive", "hrbp", "people operations"]
        ):
            return "HR"

        for signal in cls.RECRUITER_HEADLINES:
            if re.search(r"\b" + re.escape(signal) + r"\b", combined):
                return "RECRUITER"

        for signal in cls.HIRING_MANAGER_HEADLINES:
            if re.search(r"\b" + re.escape(signal) + r"\b", combined):
                return "HIRING_MANAGER"

        if any(role in combined for role in ["developer", "engineer", "designer", "analyst"]):
            return "EMPLOYEE"

        return "UNKNOWN"

    @classmethod
    def classify(
        cls,
        text: str,
        author_headline: str = "",
        author_name: str = ""
    ) -> Dict[str, Any]:
        """
        Classifies whether a LinkedIn post represents a genuine hiring opportunity.
        """
        if not text:
            return {
                "intent": "NON_HIRING",
                "confidence": 0.0,
                "signals": [],
                "author_type": "UNKNOWN",
                "is_hiring": False,
                "is_spam": False
            }

        # Normalize unicode quotes, apostrophes and spaces
        norm_text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("\xa0", " ")
        author_type = cls.detect_author_type(author_headline, author_name)

        # 1. Detect Job Seeker Signals (Highest Precedence - Candidates looking for jobs)
        job_seeker_signals = []
        job_seeker_score = 0.0
        for pattern, weight in cls.JOB_SEEKER_PATTERNS:
            if pattern.search(norm_text):
                job_seeker_signals.append(pattern.pattern)
                job_seeker_score += weight

        if author_type == "JOB_SEEKER":
            job_seeker_score += 0.50
            job_seeker_signals.append("author_headline_job_seeker")

        if job_seeker_score >= 0.70:
            return {
                "intent": "JOB_SEEKER",
                "confidence": min(1.0, round(job_seeker_score, 2)),
                "signals": job_seeker_signals,
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": False
            }

        # 2. Check spam / promotional / engagement bait filter
        is_spam, spam_reason = is_spam_or_bait(norm_text)
        if is_spam:
            # If the trigger was a candidate seeking role trigger, classify as JOB_SEEKER
            if any(s in spam_reason.lower() for s in ["open to work", "looking for", "job seeker", "actively looking", "hire me"]):
                return {
                    "intent": "JOB_SEEKER",
                    "confidence": 0.95,
                    "signals": [f"JOB_SEEKER_SIGNAL: {spam_reason}"],
                    "author_type": author_type,
                    "is_hiring": False,
                    "is_spam": False
                }
            return {
                "intent": "NON_HIRING",
                "confidence": 0.95,
                "signals": [f"SPAM: {spam_reason}"],
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": True
            }

        # 3. Detect Non-Hiring Educational / Advice / Marketing Patterns
        non_hiring_signals = []
        non_hiring_score = 0.0
        for pattern, weight in cls.NON_HIRING_PATTERNS:
            if pattern.search(norm_text):
                non_hiring_signals.append(pattern.pattern)
                non_hiring_score += weight

        if non_hiring_score >= 0.70:
            return {
                "intent": "NON_HIRING",
                "confidence": min(1.0, round(non_hiring_score, 2)),
                "signals": non_hiring_signals,
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": False
            }

        # 4. Detect Positive Hiring Signals
        hiring_signals = []
        hiring_score = 0.0
        for pattern, weight in cls.POSITIVE_HIRING_PATTERNS:
            match = pattern.search(norm_text)
            if match:
                hiring_signals.append(match.group(0).strip())
                hiring_score += weight

        # Author type bonus
        if author_type in ["RECRUITER", "HR", "FOUNDER", "HIRING_MANAGER"]:
            hiring_score += 0.25
            hiring_signals.append(f"author_is_{author_type.lower()}")

        # Presence of emails / contact with hiring words boosts confidence
        norm_text_lower = norm_text.lower()
        if "@" in norm_text and any(w in norm_text_lower for w in ["resume", "cv", "hiring", "apply", "profile", "share"]):
            hiring_score += 0.20
            hiring_signals.append("direct_recruiter_email_present")

        confidence = min(1.0, round(hiring_score, 2))

        if hiring_score >= 0.50:
            return {
                "intent": "HIRING",
                "confidence": confidence,
                "signals": hiring_signals,
                "author_type": author_type,
                "is_hiring": True,
                "is_spam": False
            }
        elif hiring_score >= 0.25:
            return {
                "intent": "AMBIGUOUS",
                "confidence": confidence,
                "signals": hiring_signals,
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": False
            }
        else:
            return {
                "intent": "NON_HIRING",
                "confidence": max(0.5, 1.0 - confidence),
                "signals": ["no_strong_hiring_signals"],
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": False
            }


# ============================================================================
# 3. ROLE RELEVANCE MATCHER
# ============================================================================

class RoleRelevanceMatcher:
    """
    Computes deterministic role relevance scores (0–100) and structured reasoning.
    Covers 20+ tech ecosystems with comprehensive synonym rings and cross-stack negative filtering.
    """

    ROLE_SYNONYMS: Dict[str, List[str]] = {
        "react": ["react", "react.js", "reactjs", "frontend", "front-end", "ui", "mern", "next.js", "nextjs"],
        "node": ["node", "node.js", "nodejs", "backend", "back-end", "express", "expressjs", "mern", "nestjs"],
        "python": ["python", "django", "fastapi", "flask", "py", "python3"],
        "java": ["java", "spring", "springboot", "spring boot", "j2ee", "hibernate", "microservices"],
        "dotnet": [".net", "dotnet", "c#", "asp.net", ".net core", "csharp"],
        "golang": ["golang", "go", "gin", "gorm", "backend"],
        "rust": ["rust", "actix", "tokio", "systems"],
        "mern": ["mern", "react", "node", "express", "mongodb", "full stack", "fullstack"],
        "mean": ["mean", "angular", "node", "express", "mongodb", "full stack", "fullstack"],
        "angular": ["angular", "angularjs", "frontend", "front-end", "mean", "typescript"],
        "vue": ["vue", "vue.js", "vuejs", "nuxt", "frontend", "front-end"],
        "devops": ["devops", "sre", "cloud", "aws", "azure", "gcp", "kubernetes", "k8s", "terraform", "ci/cd", "infrastructure"],
        "ai": ["ai", "ml", "machine learning", "deep learning", "nlp", "llm", "langchain", "genai", "data science", "pytorch"],
        "data": ["data engineer", "etl", "spark", "hadoop", "snowflake", "databricks", "sql", "dbt"],
        "mobile": ["mobile", "react native", "flutter", "ios", "android", "swift", "kotlin", "dart"],
        "qa": ["qa", "sdet", "tester", "testing", "automation", "selenium", "playwright", "cypress", "quality assurance"],
    }

    CONFUSTION_STACKS: Dict[str, List[str]] = {
        "react": ["coldfusion", "php", "laravel", "django", "java", "spring", "dotnet", "c#", "ruby", "rails", "sap", "oracle", "devops", "sre", "qa", "tester"],
        "node": ["coldfusion", "php", "django", "java", "dotnet", "c#", "sap", "devops", "qa"],
        "python": ["php", "coldfusion", "java", "dotnet", "c#", "ruby", "devops", "wordpress"],
        "java": ["php", "coldfusion", "python", "ruby", "dotnet", "devops", "wordpress"],
        "golang": ["php", "coldfusion", "wordpress", "drupal"],
        "rust": ["php", "coldfusion", "wordpress"],
        "devops": ["react", "angular", "vue", "frontend", "wordpress", "php"],
        "qa": ["marketing", "sales", "hr", "recruiter"],
    }

    _GENERIC_ROLE_WORDS: Set[str] = {
        "developer", "engineer", "lead", "senior", "junior", "specialist",
        "stack", "full", "software", "tech", "architect", "consultant",
        "experienced", "fresher", "intern", "associate"
    }

    @classmethod
    def calculate_score_with_reason(
        cls,
        target_role: str,
        post_role: str,
        post_content: str = "",
        extracted_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Calculates role match score (0-100) with detailed explanation.
        """
        if not target_role:
            return {"score": 80, "reason": "No target role specified; generic developer baseline"}

        target_clean = target_role.lower().strip()
        post_clean = (post_role or "").lower().strip()
        content_clean = (post_content or "").lower()

        # Build complete candidate roles list
        all_candidate_roles = [post_clean]
        if extracted_roles:
            all_candidate_roles.extend([r.lower().strip() for r in extracted_roles if r])

        # 1. Exact Match in any candidate role
        for cr in all_candidate_roles:
            if target_clean == cr:
                return {"score": 100, "reason": f"Exact match for '{target_role}'"}

        # 2. Normalized Title Variant Match (e.g. React.js Developer vs React Developer)
        t_core = re.sub(r"\b(developer|engineer|lead|senior|junior|fresher|specialist|stack)\b", "", target_clean).strip()
        for cr in all_candidate_roles:
            p_core = re.sub(r"\b(developer|engineer|lead|senior|junior|fresher|specialist|stack)\b", "", cr).strip()
            if t_core and (t_core == p_core or t_core in cr or p_core in target_clean):
                return {"score": 95, "reason": f"Standardized title variant for '{target_role}' ({cr.title()})"}

        # 3. Tokenized Tech Analysis & Negative Stacks Filter
        target_tokens = set(re.findall(r"[a-zA-Z0-9.+]+", target_clean))
        tech_target = target_tokens - cls._GENERIC_ROLE_WORDS

        # Check if requested tech is absent but an incompatible/conflicting tech dominates
        for tech_key, neg_list in cls.CONFUSTION_STACKS.items():
            if tech_key in target_clean:
                has_target_in_roles = any(tech_key in cr for cr in all_candidate_roles)
                found_neg_in_roles = [neg for neg in neg_list if any(neg in cr for cr in all_candidate_roles)]
                if not has_target_in_roles and found_neg_in_roles:
                    return {
                        "score": 15,
                        "reason": f"Unrelated {found_neg_in_roles[0].capitalize()} role; requested {target_role} is absent"
                    }

                has_target_tech = (tech_key in post_clean or tech_key in content_clean)
                found_neg = [neg for neg in neg_list if neg in post_clean or neg in content_clean]
                if not has_target_tech and found_neg:
                    return {
                        "score": 15,
                        "reason": f"Unrelated {found_neg[0].capitalize()} role; requested {target_role} is absent"
                    }

        # 4. Tech Token Overlap in Candidate Roles
        for cr in all_candidate_roles:
            post_tokens = set(re.findall(r"[a-zA-Z0-9.+]+", cr))
            tech_post = post_tokens - cls._GENERIC_ROLE_WORDS
            if tech_target and tech_post and tech_target.intersection(tech_post):
                return {"score": 90, "reason": f"Tech stack overlap in role '{cr.title()}'"}

        # 5. Synonym Group Matching (e.g. React -> Frontend / MERN, Python -> Django/FastAPI)
        for syn_key, syn_list in cls.ROLE_SYNONYMS.items():
            has_target_syn = any(syn in target_clean for syn in syn_list)
            if has_target_syn:
                for cr in all_candidate_roles:
                    has_post_syn = any(syn in cr for syn in syn_list)
                    if has_post_syn:
                        return {"score": 85, "reason": f"Related role domain '{cr.title()}' ({syn_key.upper()})"}

        # 6. Check Target Tech Presence in Full Post Body
        content_tokens = set(re.findall(r"[a-zA-Z0-9.+]+", content_clean))
        if tech_target and tech_target.intersection(content_tokens):
            matched_tech = list(tech_target.intersection(content_tokens))[0]
            return {"score": 75, "reason": f"Required tech stack '{matched_tech}' explicitly mentioned in post"}

        # 7. Low / Generic Overlap
        return {"score": 25, "reason": f"Generic title overlap without required {target_role} skills"}

    @classmethod
    def calculate_score(cls, target_role: str, post_role: str, post_content: str = "") -> int:
        res = cls.calculate_score_with_reason(target_role, post_role, post_content)
        return int(res["score"])


# ============================================================================
# 4. LOCATION RELEVANCE MATCHER
# ============================================================================

class LocationRelevanceMatcher:
    """
    Normalizes and computes location alignment (EXACT, REGIONAL, REMOTE, UNKNOWN, MISMATCH).
    Supports comprehensive Indian tech ecosystems, IT parks/hubs, and global remote setups.
    """

    CITY_PRIMARY_SYNONYMS: Dict[str, Set[str]] = {
        "bangalore": {"bangalore", "bengaluru", "electronic city", "whitefield", "koramangala", "indiranagar", "hebbal", "hsr layout", "marathahalli", "bellandur", "manyata"},
        "chennai": {"chennai", "madras", "omr", "sholinganallur", "guindy", "t nagar", "velachery", "siruseri", "perungudi", "ambattur"},
        "mumbai": {"mumbai", "bombay", "navi mumbai", "thane", "andheri", "bandra", "bkc", "powai", "goregaon"},
        "gurgaon": {"gurgaon", "gurugram", "cyber city", "sohna road", "golf course road"},
        "delhi": {"delhi", "noida", "gurgaon", "gurugram", "ncr", "faridabad", "ghaziabad", "greater noida"},
        "hyderabad": {"hyderabad", "secunderabad", "hitec city", "gachibowli", "madhapur", "kondapur", "kukatpally"},
        "pune": {"pune", "hinjewadi", "magarpatta", "kharadi", "viman nagar", "baner", "wakad"},
        "madurai": {"madurai", "koodal nagar"},
        "coimbatore": {"coimbatore", "peelamedu", "saravanampatti", "tidel park"},
        "kochi": {"kochi", "cochin", "infopark", "kakkanad", "ernakulam"},
        "trivandrum": {"trivandrum", "thiruvananthapuram", "technopark"},
        "kolkata": {"kolkata", "calcutta", "salt lake", "sector v", "new town"},
        "ahmedabad": {"ahmedabad", "gandhinagar", "gift city"},
        "chandigarh": {"chandigarh", "mohali", "panchkula"},
        "jaipur": {"jaipur", "sitapura"},
    }

    LOCATION_REGIONS: Dict[str, Set[str]] = {
        "bangalore": {"bangalore", "bengaluru", "karnataka"},
        "chennai": {"chennai", "madras", "tamil nadu", "tamilnadu"},
        "madurai": {"madurai", "tamil nadu", "tamilnadu"},
        "coimbatore": {"coimbatore", "tamil nadu", "tamilnadu"},
        "hyderabad": {"hyderabad", "telangana", "andhra pradesh"},
        "mumbai": {"mumbai", "bombay", "maharashtra"},
        "pune": {"pune", "maharashtra"},
        "delhi": {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad", "haryana", "uttar pradesh"},
        "kochi": {"kochi", "kerala"},
        "trivandrum": {"trivandrum", "kerala"},
        "kolkata": {"kolkata", "west bengal"},
        "ahmedabad": {"ahmedabad", "gujarat"},
    }

    _REMOTE_KEYWORDS: Set[str] = {
        "remote", "wfh", "work from home", "work-from-home", "anywhere", "pan-india", "pan india", "telecommute"
    }

    @classmethod
    def match(cls, target_location: str, post_location: str, post_content: str = "") -> Dict[str, Any]:
        """
        Matches target location against post metadata and description body.
        """
        target = (target_location or "").lower().strip()
        post_loc = (post_location or "").lower().strip()
        content = (post_content or "").lower()

        # 1. India / Unspecified Target Baseline
        if not target or target in ["india", "any", "all"]:
            return {"match_type": "EXACT", "score": 100, "normalized": "India"}

        # 2. Remote / WFH Alignment
        is_target_remote = any(k in target for k in cls._REMOTE_KEYWORDS)
        is_post_remote = any(k in post_loc for k in cls._REMOTE_KEYWORDS) or any(k in content for k in cls._REMOTE_KEYWORDS)

        if is_target_remote:
            if is_post_remote:
                return {"match_type": "REMOTE", "score": 100, "normalized": "Remote / WFH"}
            else:
                return {"match_type": "REGIONAL", "score": 70, "normalized": post_loc.title() or "Onsite"}

        if is_post_remote:
            return {"match_type": "REMOTE", "score": 95, "normalized": "Remote / WFH"}

        # 3. Direct Substring Exact Match
        if target and (target in post_loc or post_loc in target):
            return {"match_type": "EXACT", "score": 100, "normalized": target.capitalize()}

        # 4. Primary City & Tech Hub Synonyms Match
        for city_key, city_syns in cls.CITY_PRIMARY_SYNONYMS.items():
            if target in city_syns or any(syn in target for syn in city_syns):
                if any(syn in post_loc for syn in city_syns) or any(syn in content for syn in city_syns):
                    return {"match_type": "EXACT", "score": 100, "normalized": city_key.capitalize()}

        # 5. Regional State / Zone Matching
        for city_key, aliases in cls.LOCATION_REGIONS.items():
            if target in aliases or any(alias in target for alias in aliases):
                if any(alias in post_loc for alias in aliases) or any(alias in content for alias in aliases):
                    return {"match_type": "REGIONAL", "score": 75, "normalized": f"Regional ({city_key.capitalize()})"}

        # 6. Unspecified / Ambiguous location in post
        if not post_loc or post_loc in ["unspecified / remote", "unspecified", "india", "flexible"]:
            return {"match_type": "UNKNOWN", "score": 55, "normalized": "Unspecified"}

        # 7. Genuine Location Mismatch
        return {"match_type": "MISMATCH", "score": 15, "normalized": post_loc.title()}


# ============================================================================
# 5. EXPERIENCE RELEVANCE MATCHER
# ============================================================================

class ExperienceRelevanceMatcher:
    """
    Parses and calculates experience fit between candidate years and post requirement.
    Handles ranges (2-5 yrs, 3+ years, 0 to 1, freshers, senior, lead, etc.).
    """

    _RANGE_PATTERN = re.compile(r"(\d+)\s*(?:-|to|\+)\s*(\d+)?\s*(?:yrs?|years?)?", re.IGNORECASE)

    @classmethod
    def parse_experience_range(cls, required_exp_str: str) -> Tuple[int, int]:
        """Extracts (min_years, max_years) from string."""
        if not required_exp_str:
            return 0, 3

        exp_lower = required_exp_str.lower()
        if any(w in exp_lower for w in ["fresher", "0-", "0 to 1", "0 year", "freshers", "intern", "entry level", "entry-level"]):
            return 0, 1
        if "junior" in exp_lower or "1-2" in exp_lower:
            return 0, 2
        if "lead" in exp_lower or "principal" in exp_lower or "architect" in exp_lower:
            return 7, 12
        if "senior" in exp_lower or "sr." in exp_lower:
            return 4, 8

        # Check explicit number ranges
        match = cls._RANGE_PATTERN.search(required_exp_str)
        if match:
            low = int(match.group(1))
            high = int(match.group(2)) if match.group(2) else low + 2
            return low, high

        numbers = [int(n) for n in re.findall(r"\b\d+\b", required_exp_str)]
        if len(numbers) >= 2:
            return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        elif len(numbers) == 1:
            return numbers[0], numbers[0] + 2

        return 1, 3

    @classmethod
    def match(cls, candidate_exp_years: int, required_exp_str: str) -> Dict[str, Any]:
        """
        Matches candidate experience with post requirements.
        """
        if not required_exp_str:
            return {"fit": "UNKNOWN", "score": 75, "min_exp": 0, "max_exp": 3}

        min_exp, max_exp = cls.parse_experience_range(required_exp_str)

        if min_exp <= candidate_exp_years <= max_exp:
            return {"fit": "PERFECT", "score": 100, "min_exp": min_exp, "max_exp": max_exp}
        elif candidate_exp_years > max_exp and (candidate_exp_years - max_exp) <= 2:
            # Slightly over-qualified: still a great fit
            return {"fit": "GOOD", "score": 85, "min_exp": min_exp, "max_exp": max_exp}
        elif candidate_exp_years < min_exp and (min_exp - candidate_exp_years) == 1:
            # 1 year below minimum: borderline acceptable
            return {"fit": "ACCEPTABLE", "score": 60, "min_exp": min_exp, "max_exp": max_exp}
        elif candidate_exp_years > max_exp:
            # Significantly over-qualified
            return {"fit": "ACCEPTABLE", "score": 65, "min_exp": min_exp, "max_exp": max_exp}
        else:
            # Gap >= 2 years below minimum: genuine mismatch
            gap = min_exp - candidate_exp_years
            score = max(10, 40 - (gap * 10))
            return {"fit": "MISMATCH", "score": score, "min_exp": min_exp, "max_exp": max_exp}


# ============================================================================
# 6. QUALITY SCORER
# ============================================================================

class QualityScorer:
    """
    Computes overall Post Quality Score and ranking score.
    Production Multi-Signal Formula:
      Hiring intent        25%
      Freshness            20%
      Role relevance       30%
      Location relevance   10%
      Experience relevance 10%
      Contact richness      5%
    """

    @classmethod
    def calculate_quality_score(
        cls,
        hiring_confidence: float,
        age_minutes: int,
        max_age_minutes: int,
        role_score: int,
        location_score: int,
        experience_score: int,
        has_email: bool = False,
        has_phone: bool = False,
        has_apply_link: bool = False
    ) -> int:
        # 1. Hiring Intent (25%)
        intent_pts = max(0.0, min(1.0, float(hiring_confidence))) * 100 * 0.25

        # 2. Freshness (20%)
        if max_age_minutes > 0 and age_minutes >= 0:
            freshness_ratio = max(0.0, min(1.0, 1.0 - (age_minutes / max_age_minutes)))
        else:
            freshness_ratio = 0.5
        freshness_pts = freshness_ratio * 100 * 0.20

        # 3. Role Relevance (30%)
        role_pts = max(0, min(100, int(role_score))) * 0.30

        # 4. Location Relevance (10%)
        location_pts = max(0, min(100, int(location_score))) * 0.10

        # 5. Experience Relevance (10%)
        exp_pts = max(0, min(100, int(experience_score))) * 0.10

        # 6. Contact Richness (5%)
        contact_raw = 0
        if has_email:
            contact_raw += 50
        if has_phone:
            contact_raw += 30
        if has_apply_link:
            contact_raw += 20
        contact_pts = min(100, contact_raw) * 0.05

        total = int(intent_pts + freshness_pts + role_pts + location_pts + exp_pts + contact_pts)
        return max(0, min(100, total))
