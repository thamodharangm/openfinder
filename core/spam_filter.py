"""
core/spam_filter.py
===================
Production-grade Multi-Category Spam & Engagement-Bait Detection Engine.

Features:
- Multi-vector spam classification:
  1. Engagement Bait & Follower Farming ('Comment interested', 'Drop email below 👇', 'Repost to get link').
  2. EdTech / Bootcamp / Course Sales ('Register for masterclass', 'Coupon code', 'Enroll in batch').
  3. Job Seeker Reverse-Outreach ('Open to work', 'Actively looking for role', 'Please refer me').
  4. Career Advice / Motivational Fluff ('10 tips to crack FAANG', 'Agree or disagree?', 'My journey to Google').
  5. Work-from-Home / MLM / Crypto Scams ('Earn $500/day', 'Data entry typing job').
- Pre-compiled regex patterns for microsecond throughput.
- Legitimate recruiter post exception scoring (whitelisting genuine hiring with verified contact emails).
- Backward-compatible `is_spam_or_bait` helper + enterprise `SpamClassifier` class.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SPAM_TRIGGERS

logger = logging.getLogger(__name__)


@dataclass
class SpamEvaluationResult:
    is_spam: bool
    spam_score: int  # 0 (Clean) - 100 (Blatant Spam)
    spam_category: Optional[str]
    matched_triggers: List[str]
    reason: str
    is_job_seeker: bool = False
    is_promotional: bool = False

    def to_tuple(self) -> Tuple[bool, str]:
        """Backward compatibility tuple return."""
        return self.is_spam, self.reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_spam": self.is_spam,
            "spam_score": self.spam_score,
            "spam_category": self.spam_category,
            "matched_triggers": self.matched_triggers,
            "reason": self.reason,
            "is_job_seeker": self.is_job_seeker,
            "is_promotional": self.is_promotional,
        }


class SpamClassifier:
    """
    Enterprise-Grade Multi-Vector Spam Classifier for LinkedIn Posts.
    """

    # 1. Engagement Bait Patterns
    _ENGAGEMENT_BAIT_PATTERNS = [
        re.compile(r'comment\s+(?:your\s+)?(?:email|interested|yes|hi|below|cv|resume)', re.IGNORECASE),
        re.compile(r'(?:drop|type)\s+(?:your\s+)?(?:email|interested|yes|me|below|resume|cv)', re.IGNORECASE),
        re.compile(r'(?:repost|share|like)\s+(?:and|to)\s+(?:get|receive|win|access)', re.IGNORECASE),
        re.compile(r'follow\s+(?:me\s+)?(?:and|to\s+get|for\s+more)', re.IGNORECASE),
        re.compile(r'tag\s+(?:3|\d+)\s+(?:friends|connections|job\s*seekers)', re.IGNORECASE),
        re.compile(r'100%\s+free\s+(?:resume\s+review|referral|guide)\s+if\s+you', re.IGNORECASE),
        re.compile(r'sending\s+(?:the\s+link|sheet|referral)\s+in\s+(?:dm|inbox)', re.IGNORECASE),
    ]

    # 2. Promotional Courses, Masterclasses & Bootcamps
    _COURSE_PROMO_PATTERNS = [
        re.compile(r'(?:register|join|enroll)\s+(?:for\s+)?(?:our\s+|the\s+|free\s+)?(?:masterclass|webinar|bootcamp|workshop|session|course)', re.IGNORECASE),
        re.compile(r'(?:batch\s+starts|seats\s+filling|limited\s+seats|early\s+bird)', re.IGNORECASE),
        re.compile(r'(?:flat\s+\d+%\s+off|use\s+coupon\s+code|discount\s+code)', re.IGNORECASE),
        re.compile(r'(?:buy\s+this\s+course|get\s+certified|guaranteed\s+placement)', re.IGNORECASE),
        re.compile(r'(?:pay\s+after\s+placement|isa\s+model|100%\s+placement\s+assistance)', re.IGNORECASE),
    ]

    # 3. Job Seeker Reverse-Outreach (Candidate looking for job, not recruiter)
    _JOB_SEEKER_PATTERNS = [
        re.compile(r'\b(?:actively\s+looking|seeking\s+new|open\s+to\s+work|looking\s+for\s+(?:a\s+)?(?:job|opportunity|role|internship|position|openings))\b', re.IGNORECASE),
        re.compile(r'\b(?:laid\s+off|recently\s+graduated\s+and\s+looking|available\s+for\s+immediate\s+joining|ready\s+to\s+join\s+immediately)\b', re.IGNORECASE),
        re.compile(r'\b(?:please\s+refer\s+me|any\s+leads\s+appreciated|help\s+me\s+find|review\s+my\s+profile|share\s+my\s+resume|need\s+referral)\b', re.IGNORECASE),
        re.compile(r'\b(?:here\s+is\s+my\s+resume|attaching\s+my\s+resume\s+for\s+reference|sharing\s+my\s+updated\s+resume|my\s+portfolio\s+link\s+below)\b', re.IGNORECASE),
        re.compile(r'\b(?:i\s+am\s+looking\s+for|i\'m\s+seeking|completed\s+my\s+b\.?tech\s+looking|fresher\s+looking\s+for)\b', re.IGNORECASE),
        re.compile(r'#opentowork|#jobseeker|#lookingforjob|#needjob|#readytowork|#hireme', re.IGNORECASE),
    ]

    # 4. Scams, MLMs & Unrealistic Schemes
    _SCAM_PATTERNS = [
        re.compile(r'(?:earn|make)\s+(?:\$|₹)?\s*\d+\s*(?:per\s+day|daily|hourly|from\s+home\s+without\s+investment)', re.IGNORECASE),
        re.compile(r'(?:data\s+entry|typing|form\s+filling)\s+job\s+from\s+home', re.IGNORECASE),
        re.compile(r'(?:dm\s+on\s+whatsapp\s+to\s+earn|crypto\s+trading\s+bot)', re.IGNORECASE),
    ]

    # 5. Generic Fluff / Viral Engagement
    _FLUFF_PATTERNS = [
        re.compile(r'(?:agree\s+or\s+disagree\?|thoughts\?|what\s+do\s+you\s+think\?)', re.IGNORECASE),
        re.compile(r'(?:how\s+i\s+cracked\s+faang|my\s+journey\s+from\s+\w+\s+to\s+google)', re.IGNORECASE),
        re.compile(r'(?:toxic\s+work\s+culture\s+story|unpopular\s+opinion:)', re.IGNORECASE),
    ]

    # Genuine Recruiter Signals (Overrides weak engagement false positives)
    _GENUINE_HIRING_PATTERNS = [
        re.compile(r'\b(?:we\s+are\s+hiring|urgently\s+hiring|hiring\s+for\s+our\s+team|job\s+opening\s+at)\b', re.IGNORECASE),
        re.compile(r'\b(?:send\s+(?:your\s+)?(?:resume|cv)\s+to|drop\s+(?:your\s+)?(?:resume|cv)\s+at)\s+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', re.IGNORECASE),
        re.compile(r'\b(?:experience\s*:\s*\d+\s*(?:-|to)\s*\d+\s*years?|ctc\s*:\s*\d+\s*lpa)\b', re.IGNORECASE),
    ]

    @classmethod
    def evaluate(cls, text: str, author: str = "") -> SpamEvaluationResult:
        """
        Evaluates post text against multi-vector spam signals and returns a comprehensive SpamEvaluationResult.
        """
        if not text or len(text.strip()) < 25:
            return SpamEvaluationResult(
                is_spam=True,
                spam_score=100,
                spam_category="TOO_SHORT",
                matched_triggers=["Length < 25 chars"],
                reason="Post text too short to be a valid hiring opportunity"
            )

        text_clean = text.strip()
        text_lower = text_clean.lower()
        matched_triggers: List[str] = []

        # 1. Check Config SPAM_TRIGGERS
        for trigger in SPAM_TRIGGERS:
            if trigger in text_lower:
                matched_triggers.append(trigger)

        # 2. Check Engagement Bait
        for pat in cls._ENGAGEMENT_BAIT_PATTERNS:
            m = pat.search(text_lower)
            if m:
                matched_triggers.append(m.group(0))

        # Check excessive finger pointer emojis combined with comment
        if (text_lower.count("👇") >= 3 or text_lower.count("👉") >= 4) and "comment" in text_lower:
            matched_triggers.append("Excessive pointer emojis with comment call")

        if matched_triggers:
            # Check if there is an explicit genuine hiring override (e.g. legitimate email present)
            is_genuine = any(pat.search(text_lower) for pat in cls._GENUINE_HIRING_PATTERNS)
            has_official_email = bool(re.search(r'[a-zA-Z0-9_.+-]+@(?!gmail|yahoo|hotmail)[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text_lower))

            if is_genuine and has_official_email and len(matched_triggers) == 1:
                # Weak single trigger in a genuine recruiter post - forgive
                pass
            else:
                return SpamEvaluationResult(
                    is_spam=True,
                    spam_score=85,
                    spam_category="ENGAGEMENT_BAIT",
                    matched_triggers=matched_triggers,
                    reason=f"Engagement-bait pattern detected: {', '.join(matched_triggers[:2])}"
                )

        # 3. Check Promotional Course / Bootcamp Sales
        promo_triggers = []
        for pat in cls._COURSE_PROMO_PATTERNS:
            m = pat.search(text_lower)
            if m:
                promo_triggers.append(m.group(0))

        if promo_triggers:
            return SpamEvaluationResult(
                is_spam=True,
                spam_score=90,
                spam_category="PROMOTIONAL_COURSE",
                matched_triggers=promo_triggers,
                reason=f"Course/Bootcamp promotional content detected: {', '.join(promo_triggers[:2])}",
                is_promotional=True
            )

        # 4. Check Job Seeker Post (Reverse direction)
        job_seeker_triggers = []
        for pat in cls._JOB_SEEKER_PATTERNS:
            m = pat.search(text_lower)
            if m:
                job_seeker_triggers.append(m.group(0))

        if job_seeker_triggers:
            return SpamEvaluationResult(
                is_spam=True,
                spam_score=95,
                spam_category="JOB_SEEKER_POST",
                matched_triggers=job_seeker_triggers,
                reason=f"Post is from a job seeker/candidate looking for work: {', '.join(job_seeker_triggers[:2])}",
                is_job_seeker=True
            )

        # 5. Check Scams & MLMs
        scam_triggers = []
        for pat in cls._SCAM_PATTERNS:
            m = pat.search(text_lower)
            if m:
                scam_triggers.append(m.group(0))

        if scam_triggers:
            return SpamEvaluationResult(
                is_spam=True,
                spam_score=100,
                spam_category="SCAM_SCHEME",
                matched_triggers=scam_triggers,
                reason=f"Unrealistic work-from-home or financial scam detected: {', '.join(scam_triggers[:2])}"
            )

        # 6. Check Fluff / Viral Discussions
        fluff_triggers = []
        for pat in cls._FLUFF_PATTERNS:
            m = pat.search(text_lower)
            if m:
                fluff_triggers.append(m.group(0))

        if fluff_triggers and not any(pat.search(text_lower) for pat in cls._GENUINE_HIRING_PATTERNS):
            return SpamEvaluationResult(
                is_spam=True,
                spam_score=75,
                spam_category="VIRAL_DISCUSSION",
                matched_triggers=fluff_triggers,
                reason=f"Non-hiring viral discussion/advice post: {', '.join(fluff_triggers[:2])}"
            )

        return SpamEvaluationResult(
            is_spam=False,
            spam_score=0,
            spam_category=None,
            matched_triggers=[],
            reason="Genuine hiring post"
        )


@dataclass
class HiringIntentResult:
    score: int  # 0 to 100
    is_hiring_intent: bool  # score >= 60
    hiring_type: str  # DIRECT_HIRING, RECRUITER_HIRING, REFERRAL_HIRING, AGENCY_HIRING, JOB_LINK_POST, NON_HIRING
    signals: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    has_contact_email: bool = False
    has_role_stack: bool = False
    has_apply_link: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "is_hiring_intent": self.is_hiring_intent,
            "hiring_type": self.hiring_type,
            "signals": self.signals,
            "penalties": self.penalties,
            "has_contact_email": self.has_contact_email,
            "has_role_stack": self.has_role_stack,
            "has_apply_link": self.has_apply_link,
        }


class HiringIntentScorer:
    """
    Two-Stage Deterministic Numerical Hiring Intent & Classification Engine.
    """

    _HIRING_VERBS = [
        re.compile(r'\b(?:we\s+are\s+hiring|urgently\s+hiring|hiring\s+for|hiring|open\s+position|join\s+our\s+team|developer\s+required|walk-?in\s+drive|immediate\s+hiring|we\'re\s+looking\s+for)\b', re.IGNORECASE),
        re.compile(r'\b(?:looking\s+for\s+(?:a|an|[0-9]+)?\s*(?:senior|junior|lead|founding|staff)?\s*(?:[a-z0-9.+/#\- ]{1,25})?(?:developer|engineer|builder|architect|coder|specialist|designer|intern|sde|sdet))\b', re.IGNORECASE),
        re.compile(r'\b(?:hiring\s+alert|careers\s+opportunity|talent\s+search|job\s+opportunity|dm\s+me\s+if\s+you|send\s+(?:your\s+)?(?:cv|resume)|scaling\s+(?:the|our)\s+team|growing\s+(?:the|our)\s+team)\b', re.IGNORECASE),
    ]

    _DIRECT_HIRING_AUTHORS = [
        re.compile(r'\b(?:founder|co-founder|ceo|cto|vp\s+of\s+engineering|director\s+of\s+engineering|engineering\s+manager|tech\s+lead|head\s+of\s+engineering)\b', re.IGNORECASE),
    ]

    _RECRUITER_AUTHORS = [
        re.compile(r'\b(?:recruiter|talent\s+acquisition|hr\s+manager|talent\s+partner|human\s+resources|people\s+partner|talent\s+lead|hiring\s+manager)\b', re.IGNORECASE),
    ]

    _AGENCY_AUTHORS = [
        re.compile(r'\b(?:staffing|consultancy|placement|talent\s+solutions|recruitment\s+agency|manpower|consulting)\b', re.IGNORECASE),
    ]

    _REFERRAL_SIGNALS = [
        re.compile(r'\b(?:happy\s+to\s+refer|dm\s+for\s+referral|internal\s+referral|my\s+team\s+is\s+hiring|my\s+company\s+is\s+hiring)\b', re.IGNORECASE),
    ]

    _EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    _APPLY_LINK_PATTERN = re.compile(r'(?:https?://|www\.)(?:[a-zA-Z0-9-]+\.)*(?:bit\.ly|forms\.gle|t\.co|tinyurl|linkedin\.com/jobs|lever\.co|greenhouse\.io|workable\.com|notion\.site|ashbyhq\.com|[a-zA-Z0-9-]+\.com/(?:careers|jobs))', re.IGNORECASE)
    _ROLE_STACK_PATTERN = re.compile(r'\b(?:react|next\.?js|node\.?js|python|django|fastapi|mern|typescript|javascript|frontend|backend|full\s*stack|software\s*engineer|developer|founding\s*engineer)\b', re.IGNORECASE)
    _CRITERIA_PATTERN = re.compile(r'\b(?:\d+\s*(?:-|to|\+)\s*\d*\s*years?|ctc|lpa|notice\s+period|hybrid|remote|on-?site|bangalore|chennai|hyderabad|pune)\b', re.IGNORECASE)

    @classmethod
    def evaluate(cls, text: str, author_title: str = "", author_name: str = "") -> HiringIntentResult:
        if not text or len(text.strip()) < 20:
            return HiringIntentResult(
                score=0,
                is_hiring_intent=False,
                hiring_type="NON_HIRING",
                penalties=["Post text too short (<20 chars)"]
            )

        text_clean = text.strip()
        text_lower = text_clean.lower()
        title_lower = (author_title or "").lower()

        # Step 1: Run spam classifier
        spam_res = SpamClassifier.evaluate(text_clean, author=author_name)
        if spam_res.is_spam:
            return HiringIntentResult(
                score=max(0, 100 - spam_res.spam_score),
                is_hiring_intent=False,
                hiring_type="NON_HIRING",
                penalties=spam_res.matched_triggers or [spam_res.reason]
            )

        # Step 2: Calculate Positive Signals
        score = 0
        signals = []
        penalties = []

        # Signal 1: Hiring Verbs (+30)
        hiring_match = any(pat.search(text_lower) for pat in cls._HIRING_VERBS)
        if hiring_match:
            score += 30
            signals.append("Explicit hiring intent verbs (+30)")

        # Signal 2: Contact Email (+25)
        has_email = bool(cls._EMAIL_PATTERN.search(text_clean))
        if has_email:
            score += 25
            signals.append("Direct recruiter email present (+25)")

        # Signal 3: Specific Tech Stack / Role (+20)
        has_role_stack = bool(cls._ROLE_STACK_PATTERN.search(text_lower))
        if has_role_stack:
            score += 20
            signals.append("Specific role & tech stack mention (+20)")

        # Signal 4: Job Criteria / Compensation / Location (+15)
        has_criteria = bool(cls._CRITERIA_PATTERN.search(text_lower))
        if has_criteria:
            score += 15
            signals.append("Experience/CTC/Location criteria specified (+15)")

        # Signal 5: Direct Apply Link / Careers Page (+15)
        has_apply_link = bool(cls._APPLY_LINK_PATTERN.search(text_lower))
        if has_apply_link:
            score += 15
            signals.append("Direct application link or ATS form (+15)")

        # Signal 6: Author Credibility Bonus (+15)
        is_credible_author = any(pat.search(title_lower) for pat in (cls._DIRECT_HIRING_AUTHORS + cls._RECRUITER_AUTHORS))
        if is_credible_author:
            score += 15
            signals.append("Author is verified hiring decision maker (+15)")

        # Check job seeker penalty (-45)
        for pat in SpamClassifier._JOB_SEEKER_PATTERNS:
            if pat.search(text_lower):
                score -= 45
                penalties.append("Candidate reverse job seeking penalty (-45)")
                break

        # Check viral advice penalty (-35)
        for pat in SpamClassifier._FLUFF_PATTERNS:
            if pat.search(text_lower) and not hiring_match:
                score -= 35
                penalties.append("Viral discussion/advice penalty (-35)")
                break

        final_score = max(0, min(100, score))
        is_hiring = final_score >= 50 and (hiring_match or has_email or has_apply_link)

        # Step 3: Classify Post Type
        if not is_hiring:
            hiring_type = "NON_HIRING"
        elif any(pat.search(text_lower) for pat in cls._REFERRAL_SIGNALS):
            hiring_type = "REFERRAL_HIRING"
        elif any(pat.search(title_lower) for pat in cls._DIRECT_HIRING_AUTHORS):
            hiring_type = "DIRECT_HIRING"
        elif any(pat.search(title_lower) for pat in cls._AGENCY_AUTHORS):
            hiring_type = "AGENCY_HIRING"
        elif any(pat.search(title_lower) for pat in cls._RECRUITER_AUTHORS) or has_email:
            hiring_type = "RECRUITER_HIRING"
        elif has_apply_link and len(text_clean) < 150:
            hiring_type = "JOB_LINK_POST"
        else:
            hiring_type = "RECRUITER_HIRING"

        return HiringIntentResult(
            score=final_score,
            is_hiring_intent=is_hiring,
            hiring_type=hiring_type,
            signals=signals,
            penalties=penalties,
            has_contact_email=has_email,
            has_role_stack=has_role_stack,
            has_apply_link=has_apply_link
        )


def calculate_hiring_intent_score(text: str, author_title: str = "", author_name: str = "") -> Tuple[int, str, Dict[str, Any]]:
    """
    Calculates numerical hiring intent score (0-100) and post classification.
    Returns:
        (score: int, hiring_type: str, details: dict)
    """
    res = HiringIntentScorer.evaluate(text, author_title, author_name)
    return res.score, res.hiring_type, res.to_dict()


def classify_post_type(text: str, author_title: str = "", author_name: str = "") -> str:
    """Classifies post into DIRECT_HIRING, RECRUITER_HIRING, REFERRAL_HIRING, AGENCY_HIRING, JOB_LINK_POST, or NON_HIRING."""
    res = HiringIntentScorer.evaluate(text, author_title, author_name)
    return res.hiring_type


def is_spam_or_bait(text: str) -> Tuple[bool, str]:
    """
    Checks if a LinkedIn post is spam, engagement bait, or non-job content.
    Returns:
        (is_spam: bool, reason: str)
    """
    eval_res = SpamClassifier.evaluate(text)
    return eval_res.to_tuple()
