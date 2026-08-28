import re
from typing import Dict, Any, List, Optional, Tuple, Set
import sys
from pathlib import Path

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.spam_filter import is_spam_or_bait


class JobRoleExtractor:
    """
    Extracts structured job roles from LinkedIn post text using multiple strategies:
    1. Labeled key-value patterns (Position:, Role:, Job Title:, etc.)
    2. Declarative hiring statements (Looking for a ..., Hiring for ..., etc.)
    3. Multi-role bullet lists (• React Developer, - Node.js Developer, etc.)
    """

    ROLE_PATTERNS = [
        r"(?:position|role|job\s+title|profile|designation)\s*:\s*([^\n.,|;!#]+)",
        r"(?:hiring|urgent\s+opening|openings?|vacanc(?:y|ies))\s+(?:for\s+)?([^\n.,|;!#]+)",
        r"(?:looking\s+(?:for|to\s+hire)\s+(?:a|an|[0-9]+)?)\s*([A-Za-z0-9.+/\-\s]+(?:developer|engineer|lead|specialist|architect|intern|fresher|consultant|tester))",
        r"(?:need|require[sd]?)\s+(?:a|an|[0-9]+)?\s*([A-Za-z0-9.+/\-\s]+(?:developer|engineer|lead))",
    ]

    BULLET_ROLE_PATTERN = r"(?:^|\n)\s*[-•*–]\s*([A-Za-z0-9.+/\-\s]+(?:developer|engineer|tester|designer|lead|architect))"

    @classmethod
    def extract_roles(cls, text: str, default_title: str = "Software Engineer") -> List[str]:
        if not text:
            return [default_title]

        roles: List[str] = []

        # 1. Check bullet points
        bullet_matches = re.findall(cls.BULLET_ROLE_PATTERN, text, re.IGNORECASE)
        for b in bullet_matches:
            clean_b = b.strip().title()
            if len(clean_b) > 3 and clean_b not in roles:
                roles.append(clean_b)

        # 2. Check standard patterns
        for pattern in cls.ROLE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                clean_m = re.sub(r'\s+', ' ', m).strip().title()
                # Clean invalid fragments
                clean_m = re.split(r'(?:\sat\s|\sin\s|\swith\s|📍|experience|exp)', clean_m, flags=re.IGNORECASE)[0].strip()
                if len(clean_m) >= 4 and clean_m not in roles and clean_m.lower() not in {"an immediate", "urgent joiners", "candidates", "team", "the team"}:
                    roles.append(clean_m)

        if not roles:
            return [default_title]

        return roles


class HiringIntentClassifier:
    """
    Deterministic hiring-intent classifier that distinguishes:
      - Genuine Recruiters / Founders / Hiring Managers (HIRING)
      - Job Seekers / Candidates / #OpenToWork (JOB_SEEKER)
      - Tutorials / Advice / Industry News (NON_HIRING)
      - Unclear statements (AMBIGUOUS)
    """

    # 1. POSITIVE HIRING SIGNALS (Weighted)
    POSITIVE_HIRING_PATTERNS: List[Tuple[str, float]] = [
        (r"\b(?:we\s+are|we're|currently|urgently|actively)\s+hiring\b", 0.40),
        (r"\bwe\s+have\s+(?:an?\s+)?(?:urgent\s+)?(?:opening[s]?|vacanc(?:y|ies))\b", 0.35),
        (r"\bhiring\s+(?:for|urgent|immediate|alert)\b", 0.35),
        (r"\blooking\s+(?:for|to\s+hire)\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|fresher|intern|lead|architect|consultant)", 0.35),
        (r"\bi\s+am\s+looking\s+for\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|lead|specialist)", 0.35),
        (r"\b(?:need|require[sd]?|seeking)\s+(?:a|an|[0-9]+)?\s*([a-zA-Z\s]+developer|engineer|lead)", 0.30),
        (r"\b(?:job\s+)?opening[s]?\s+(?:for|at|in)\b", 0.30),
        (r"\bjoin\s+our\s+team\b", 0.25),
        (r"\b(?:send|share|email|drop|dm|forward)\s+(?:your\s+)?(?:resume|cv|profile)\b", 0.30),
        (r"\b(?:walk-in|walkin)\s+interview\b", 0.35),
        (r"\bimmediate\s+joiner[s]?\b", 0.25),
        (r"\bapply\s+(?:now|here|via|at)\b", 0.25),
        (r"\binterested\s+candidates\s+(?:can|please|dm|send|email)\b", 0.30),
        (r"\bjob\s+location\s*:\b", 0.20),
        (r"\bexperience\s*(?:required|needed)?\s*:\s*\d", 0.20),
        (r"\b(?:ctc|salary|budget)\s*:\s*", 0.20),
        (r"\bnotice\s+period\s*:\b", 0.20),
    ]

    # 2. JOB-SEEKER OVERRIDE SIGNALS (Negative)
    JOB_SEEKER_PATTERNS: List[Tuple[str, float]] = [
        (r"\b(?:i\s+am|i'm|myself)\s+(?:a|an)?\s*[a-zA-Z\s]*\s*(?:looking|seeking|searching)\s+for\s+(?:a\s+)?(?:job|opportunity|opportunities|role|position|internship|project)\b", 0.90),
        (r"\b(?:i\s+am|i'm)\s+(?:actively\s+)?(?:looking|seeking)\s+for\s+(?:my\s+next\s+)?(?:job|opportunity|opportunities|role)\b", 0.90),
        (r"\b(?:actively\s+looking|seeking\s+new\s+opportunities|available\s+for\s+opportunities)\b", 0.85),
        (r"\b(?:open\s+to\s+work|opentowork|#opentowork)\b", 0.95),
        (r"\b(?:please\s+refer\s+me|looking\s+for\s+referral[s]?|referral\s+needed|any\s+leads\s+appreciated)\b", 0.85),
        (r"\b(?:need\s+a\s+job|looking\s+for\s+job|seeking\s+job|unemployed|fresher\s+looking\s+for\s+job)\b", 0.90),
        (r"\b(?:hire\s+me|open\s+for\s+work)\b", 0.90),
        (r"\bhiring\s+managers?\s*(?:,|please|\.)?\s*(?:dm|reach\s+out|refer|review\s+my|check\s+my|contact\s+me)\b", 0.85),
        (r"\bany\s+hiring\s+for\s+(?:freshers?|react|python|developers?)\s*\?", 0.80),
    ]

    # 3. NON-HIRING PROMOTIONAL / TUTORIAL / ADVICE PATTERNS
    NON_HIRING_PATTERNS: List[Tuple[str, float]] = [
        (r"\b(?:tips?\s+to\s+get\s+(?:hired|a\s+job)|how\s+to\s+get\s+hired|crack\s+the\s+interview)\b", 0.80),
        (r"\b(?:top\s+\d+\s+interview\s+questions|react\s+tutorial|learn\s+react\s+in\s+\d+)\b", 0.85),
        (r"\b(?:free\s+webinar|register\s+for\s+(?:our\s+)?(?:webinar|masterclass|course|bootcamp))\b", 0.90),
        (r"\b(?:react\s+is\s+(?:in\s+high\s+demand|the\s+future)|why\s+react\s+is)\b", 0.75),
        (r"\b(?:salary\s+trends|average\s+salary\s+of)\b", 0.70),
        (r"\b(?:5\s+tips|10\s+tips|common\s+mistakes\s+in)\b", 0.80),
    ]

    # 4. AUTHOR HEADLINE SIGNALS
    RECRUITER_HEADLINES = [
        "recruiter", "talent acquisition", "talent partner", "staffing",
        "human resources", "hr manager", "hr executive", "hrbp", "hiring manager",
        "talent lead", "people operations", "head of talent"
    ]
    FOUNDER_HEADLINES = [
        "founder", "co-founder", "ceo", "cto", "managing director", "director", "owner"
    ]
    HIRING_MANAGER_HEADLINES = [
        "engineering manager", "head of engineering", "tech lead", "team lead", "vp of engineering"
    ]
    JOB_SEEKER_HEADLINES = [
        "open to work", "opentowork", "#opentowork", "job seeker", "looking for opportunities",
        "aspiring", "student", "seeking role", "fresher"
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

        if "hr" in combined.split() or any(re.search(r"\b" + re.escape(s) + r"\b", combined) for s in ["hr", "human resources", "hr manager", "hr executive", "hrbp", "people operations"]):
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
        if not text:
            return {
                "intent": "NON_HIRING",
                "confidence": 0.0,
                "signals": [],
                "author_type": "UNKNOWN",
                "is_hiring": False,
                "is_spam": False
            }

        text_lower = text.lower()
        author_type = cls.detect_author_type(author_headline, author_name)

        # Check spam filter integration first
        is_spam, spam_reason = is_spam_or_bait(text)
        if is_spam:
            return {
                "intent": "NON_HIRING",
                "confidence": 0.95,
                "signals": [f"SPAM: {spam_reason}"],
                "author_type": author_type,
                "is_hiring": False,
                "is_spam": True
            }

        # 1. Detect Job Seeker Signals (Highest Precedence)
        job_seeker_signals = []
        job_seeker_score = 0.0
        for pattern, weight in cls.JOB_SEEKER_PATTERNS:
            if re.search(pattern, text_lower):
                job_seeker_signals.append(pattern)
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

        # 2. Detect Non-Hiring Educational / Advice / Marketing Patterns
        non_hiring_signals = []
        non_hiring_score = 0.0
        for pattern, weight in cls.NON_HIRING_PATTERNS:
            if re.search(pattern, text_lower):
                non_hiring_signals.append(pattern)
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

        # 3. Detect Positive Hiring Signals
        hiring_signals = []
        hiring_score = 0.0
        for pattern, weight in cls.POSITIVE_HIRING_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                hiring_signals.append(match.group(0).strip())
                hiring_score += weight

        # Author type bonus
        if author_type in ["RECRUITER", "HR", "FOUNDER", "HIRING_MANAGER"]:
            hiring_score += 0.25
            hiring_signals.append(f"author_is_{author_type.lower()}")

        # Presence of emails / phones boosts confidence
        if "@" in text and ("resume" in text_lower or "cv" in text_lower or "hiring" in text_lower):
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


class RoleRelevanceMatcher:
    """
    Computes deterministic role relevance scores (0–100) and explanations.
    Features:
      1. Exact and normalized title matching
      2. Multi-role detection (e.g. React Developer listed in a multi-hire post)
      3. Negative technology dominance penalties
    """

    ROLE_SYNONYMS = {
        "react": ["react", "react.js", "reactjs", "frontend", "front-end", "ui", "mern"],
        "node": ["node", "node.js", "nodejs", "backend", "back-end", "express", "mern"],
        "python": ["python", "django", "fastapi", "flask", "py"],
        "java": ["java", "spring", "springboot", "j2ee", "hibernate"],
        "dotnet": [".net", "dotnet", "c#", "asp.net"],
        "mern": ["mern", "react", "node", "express", "mongodb"],
        "mean": ["mean", "angular", "node", "express", "mongodb"],
        "angular": ["angular", "angularjs", "frontend", "front-end", "mean"],
        "vue": ["vue", "vue.js", "vuejs", "frontend", "front-end"],
    }

    CONFUSTION_STACKS = {
        "react": ["coldfusion", "php", "laravel", "django", "java", "spring", "dotnet", "c#", "ruby", "rails", "sap", "oracle", "devops", "sre", "qa", "tester"],
        "node": ["coldfusion", "php", "django", "java", "dotnet", "c#", "sap", "devops", "qa"],
        "python": ["php", "coldfusion", "java", "dotnet", "c#", "ruby", "devops"],
        "java": ["php", "coldfusion", "python", "ruby", "dotnet", "devops"],
    }

    @classmethod
    def calculate_score_with_reason(
        cls,
        target_role: str,
        post_role: str,
        post_content: str = "",
        extracted_roles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        if not target_role:
            return {"score": 80, "reason": "No target role specified; generic developer baseline"}

        target_clean = target_role.lower().strip()
        post_clean = (post_role or "").lower().strip()
        content_clean = (post_content or "").lower()

        # 1. Check all extracted roles in multi-role posts
        all_candidate_roles = [post_clean]
        if extracted_roles:
            all_candidate_roles.extend([r.lower().strip() for r in extracted_roles])

        # Exact Match in any extracted role
        for cr in all_candidate_roles:
            if target_clean == cr:
                return {"score": 100, "reason": f"Exact match for '{target_role}'"}

        # 2. Check Variant Normalization (e.g. React.js Developer vs React Developer)
        t_core = re.sub(r'\b(developer|engineer|lead|senior|junior|fresher|specialist|stack)\b', '', target_clean).strip()
        for cr in all_candidate_roles:
            p_core = re.sub(r'\b(developer|engineer|lead|senior|junior|fresher|specialist|stack)\b', '', cr).strip()
            if t_core and (t_core == p_core or t_core in cr or p_core in target_clean):
                return {"score": 95, "reason": f"Standardized title variant for '{target_role}' ({cr.title()})"}

        # 3. Check Tech Tokens Overlap
        target_tokens = set(re.findall(r'[a-zA-Z0-9.+]+', target_clean))
        generic_words = {"developer", "engineer", "lead", "senior", "junior", "specialist", "stack", "full", "software"}
        tech_target = target_tokens - generic_words

        # Check if requested tech is absent but conflicting tech dominates
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

        # Check direct tech token overlap in extracted roles
        for cr in all_candidate_roles:
            post_tokens = set(re.findall(r'[a-zA-Z0-9.+]+', cr))
            tech_post = post_tokens - generic_words
            if tech_target and tech_post and tech_target.intersection(tech_post):
                return {"score": 90, "reason": f"Tech stack overlap in role '{cr.title()}'"}

        # 4. Check domain synonym groups (e.g. react in target and mern in post)
        for syn_key, syn_list in cls.ROLE_SYNONYMS.items():
            has_target_syn = any(syn in target_clean for syn in syn_list)
            for cr in all_candidate_roles:
                has_post_syn = any(syn in cr for syn in syn_list)
                if has_target_syn and has_post_syn:
                    return {"score": 80, "reason": f"Related role domain '{cr.title()}' ({syn_key.upper()})"}

        # 5. Check Content Tech Overlap
        content_tokens = set(re.findall(r'[a-zA-Z0-9.+]+', content_clean))
        if tech_target and tech_target.intersection(content_tokens):
            return {"score": 70, "reason": f"Required tech stack '{list(tech_target)[0]}' found in post description"}

        # 6. Generic overlap only
        return {"score": 25, "reason": f"Generic title overlap without required {target_role} skills"}

    @classmethod
    def calculate_score(cls, target_role: str, post_role: str, post_content: str = "") -> int:
        res = cls.calculate_score_with_reason(target_role, post_role, post_content)
        return res["score"]


class LocationRelevanceMatcher:
    """
    Normalizes and computes location alignment (EXACT, REGIONAL, REMOTE, UNKNOWN, MISMATCH).
    Supports Bangalore tech hubs (Electronic City, Whitefield, Hebbal, Koramangala, etc.).
    """

    CITY_PRIMARY_SYNONYMS = {
        "bangalore": {"bangalore", "bengaluru", "electronic city", "whitefield", "koramangala", "indiranagar", "hebbal", "hsr layout", "marathahalli"},
        "chennai": {"chennai", "madras", "omr", "sholinganallur", "guindy", "t nagar", "velachery"},
        "mumbai": {"mumbai", "bombay", "navi mumbai", "thane", "andheri", "bandra"},
        "gurgaon": {"gurgaon", "gurugram"},
        "delhi": {"delhi", "noida", "gurgaon", "gurugram", "ncr", "faridabad"},
        "hyderabad": {"hyderabad", "secunderabad", "hitec city", "gachibowli", "madhapur"},
        "pune": {"pune", "hinjewadi", "magarpatta", "kharadi"},
        "madurai": {"madurai"},
        "coimbatore": {"coimbatore", "peelamedu", "saravanampatti"},
    }

    LOCATION_REGIONS = {
        "bangalore": {"bangalore", "bengaluru", "karnataka"},
        "chennai": {"chennai", "madras", "tamil nadu"},
        "madurai": {"madurai", "tamil nadu"},
        "coimbatore": {"coimbatore", "tamil nadu"},
        "hyderabad": {"hyderabad", "telangana"},
        "mumbai": {"mumbai", "bombay", "maharashtra"},
        "pune": {"pune", "maharashtra"},
        "delhi": {"delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad"},
    }

    @classmethod
    def match(cls, target_location: str, post_location: str, post_content: str = "") -> Dict[str, Any]:
        target = (target_location or "").lower().strip()
        post_loc = (post_location or "").lower().strip()
        content = (post_content or "").lower()

        if not target or target == "india":
            return {"match_type": "EXACT", "score": 100, "normalized": "India"}

        if "remote" in target or "remote" in post_loc or "wfh" in post_loc or "work from home" in content:
            return {"match_type": "REMOTE", "score": 95, "normalized": "Remote / WFH"}

        # Direct Substring Exact Match
        if target in post_loc or post_loc in target:
            return {"match_type": "EXACT", "score": 100, "normalized": target.capitalize()}

        # Primary City & Hub Synonyms Match (e.g. Bangalore == Bengaluru == Electronic City)
        for city_key, city_syns in cls.CITY_PRIMARY_SYNONYMS.items():
            if target in city_syns or any(syn in target for syn in city_syns):
                if any(syn in post_loc for syn in city_syns) or any(syn in content for syn in city_syns):
                    return {"match_type": "EXACT", "score": 100, "normalized": city_key.capitalize()}

        # Regional check (e.g. Bangalore vs Karnataka, or Madurai vs Tamil Nadu)
        for city_key, aliases in cls.LOCATION_REGIONS.items():
            if target in aliases or any(alias in target for alias in aliases):
                if any(alias in post_loc for alias in aliases) or any(alias in content for alias in aliases):
                    return {"match_type": "REGIONAL", "score": 75, "normalized": f"Regional ({city_key.capitalize()})"}

        if not post_loc or post_loc in ["unspecified / remote", "unspecified", "india"]:
            return {"match_type": "UNKNOWN", "score": 50, "normalized": "Unspecified"}

        return {"match_type": "MISMATCH", "score": 15, "normalized": post_loc.title()}


class ExperienceRelevanceMatcher:
    """
    Calculates experience fit between candidate years and post requirement.
    """

    @classmethod
    def match(cls, candidate_exp_years: int, required_exp_str: str) -> Dict[str, Any]:
        if not required_exp_str:
            return {"fit": "UNKNOWN", "score": 75, "min_exp": 0, "max_exp": 3}

        exp_lower = required_exp_str.lower()
        if "fresher" in exp_lower or "0-" in exp_lower or "0 to 1" in exp_lower or "0 year" in exp_lower:
            min_exp, max_exp = 0, 1
        elif "junior" in exp_lower:
            min_exp, max_exp = 0, 2
        elif "senior" in exp_lower:
            min_exp, max_exp = 4, 8
        elif "lead" in exp_lower or "principal" in exp_lower:
            min_exp, max_exp = 7, 12
        else:
            numbers = [int(n) for n in re.findall(r'\b\d+\b', required_exp_str)]
            if len(numbers) >= 2:
                min_exp, max_exp = numbers[0], numbers[1]
            elif len(numbers) == 1:
                min_exp, max_exp = numbers[0], numbers[0] + 2
            else:
                return {"fit": "UNKNOWN", "score": 75, "min_exp": 1, "max_exp": 3}

        if min_exp <= candidate_exp_years <= max_exp:
            return {"fit": "PERFECT", "score": 100, "min_exp": min_exp, "max_exp": max_exp}
        elif candidate_exp_years > max_exp and (candidate_exp_years - max_exp) <= 2:
            # Slightly over-qualified: still a good fit
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
            score = max(10, 40 - (gap * 10))  # 30 for 2yr gap, 20 for 3yr gap, etc.
            return {"fit": "MISMATCH", "score": score, "min_exp": min_exp, "max_exp": max_exp}


class QualityScorer:
    """
    Computes overall Post Quality Score and final ranking score.
    Phase 3 Formula (Weighted for High Role Precision):
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
        intent_pts = hiring_confidence * 100 * 0.25

        # 2. Freshness (20%)
        if max_age_minutes > 0 and age_minutes >= 0:
            freshness_ratio = max(0.0, 1.0 - (age_minutes / max_age_minutes))
        else:
            freshness_ratio = 0.5
        freshness_pts = freshness_ratio * 100 * 0.20

        # 3. Role Relevance (30%) - Higher weight to reject unrelated roles
        role_pts = role_score * 0.30

        # 4. Location Relevance (10%)
        location_pts = location_score * 0.10

        # 5. Experience Relevance (10%)
        exp_pts = experience_score * 0.10

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
