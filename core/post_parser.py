"""
core/post_parser.py
===================
Production-grade Snippet & Post Parser for LinkedIn Hiring Intelligence.

Features:
- Entity extraction: Company name, job title, work mode, salary/CTC range, experience range.
- Contact extraction: Clean email addresses, WhatsApp/phone numbers, and third-party ATS application links.
- Pre-compiled high-performance regular expressions for fast multi-post parsing.
- Integration with canonical skill normalization.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

from core.matcher import canonicalize_skill

logger = logging.getLogger(__name__)


class PostParser:
    """
    Advanced Post Parser extracting Company, Work Mode, Compensation, 
    Recruiter Profiles, Experience Range, and Application Links.
    """

    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', re.IGNORECASE)
    PHONE_REGEX = re.compile(r'(?:\+91[\-\s]?)?[6789]\d{9}\b')
    URL_REGEX = re.compile(r'(?:https?://|www\.|forms\.gle/|bit\.ly/)[^\s<>"\']+', re.IGNORECASE)

    # ATS & Form application link domains
    _ATS_DOMAINS = {
        'forms.gle', 'docs.google.com/forms', 'lever.co', 'greenhouse.io',
        'workable.com', 'typeform.com', 'ashbyhq.com', 'smartrecruiters.com',
        'myworkdayjobs.com', 'taleo.net', 'breezy.hr', 'notion.site', 'airtable.com'
    }

    _SALARY_PATTERNS = [
        re.compile(r'(\b\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lac|inr)\b)', re.IGNORECASE),
        re.compile(r'(\$\s*\d+k?\s*(?:to|-)\s*\$?\s*\d+k?\b)', re.IGNORECASE),
        re.compile(r'(\b₹\s*[0-9.,]+\s*(?:-|to)\s*₹?\s*[0-9.,]+\s*(?:lakhs?|lpa|pm|per\s+month|per\s+annum)?\b)', re.IGNORECASE),
        re.compile(r'(\b(?:ctc|salary|package|budget|stipend)\s*:\s*[^\n,;|.!?]+)', re.IGNORECASE),
        re.compile(r'(\b\d+\s*lpa\b)', re.IGNORECASE),
    ]

    _EXP_PATTERNS = [
        re.compile(r'(\d+\s*(?:to|-)\s*\d+\+?\s*(?:years?|yrs?))', re.IGNORECASE),
        re.compile(r'(\d+\+?\s*(?:years?|yrs?)\s*(?:of)?\s*(?:exp|experience)?)', re.IGNORECASE),
        re.compile(r'(?:min(?:imum)?|at\s+least)\s+(\d+)\s*(?:years?|yrs?)', re.IGNORECASE),
        re.compile(r'\b(?:freshers?|0\s*-\s*1\s*yrs?|entry\s+level)\b', re.IGNORECASE),
    ]

    _COMPANY_PATTERNS = [
        re.compile(r'(?:company|organization)\s*:\s*([A-Za-z0-9&.\s]{2,30})', re.IGNORECASE),
        re.compile(r'(?:at|@)\s+([A-Z][a-zA-Z0-9&.\s]{2,25}(?:Pvt|Ltd|Inc|LLC|Technologies|Solutions|Software|Labs|Corp)?)', re.IGNORECASE),
        re.compile(r'([A-Z][a-zA-Z0-9&.\s]{2,25})\s+(?:is\s+hiring|urgently\s+hiring|hiring\s+for)', re.IGNORECASE),
    ]

    _GENERIC_COMPANY_WORDS = {
        "we", "hiring", "immediate", "looking", "urgent", "the", "our", "linkedin",
        "candidates", "developer", "engineer", "team", "experienced", "someone", "anyone"
    }

    @staticmethod
    def extract_work_mode(text: str) -> str:
        """Determines Remote, Hybrid, or On-Site mode with clean badges."""
        if not text:
            return "📍 On-Site / Unspecified"

        text_lower = text.lower()
        if "hybrid" in text_lower or "flexible" in text_lower:
            return "🏢 Hybrid"
        elif any(w in text_lower for w in ["remote", "wfh", "work from home", "work-from-home", "anywhere in india", "pan-india", "telecommute"]):
            return "🏡 Remote / WFH"
        elif any(w in text_lower for w in ["on-site", "onsite", "in-office", "work from office"]):
            return "📍 On-Site"

        return "📍 On-Site / Unspecified"

    @classmethod
    def extract_salary_or_ctc(cls, text: str) -> Optional[str]:
        """Detects salary / CTC ranges (e.g. 10-15 LPA, $80k-$120k, ₹18,00,000)."""
        if not text:
            return None

        for pat in cls._SALARY_PATTERNS:
            match = pat.search(text)
            if match:
                res = match.group(1).strip()
                # Clean prefix noise if any
                res = re.sub(r'^(?:ctc|salary|package|budget|stipend)\s*:\s*', '', res, flags=re.IGNORECASE).strip()
                if len(res) >= 3 and not res.isdigit():
                    return res.title()

        return None

    @classmethod
    def extract_company_name(cls, title: str = "", text: str = "", emails: Optional[List[str]] = None) -> str:
        """Extracts company name with fallback to email domain."""
        # 1. Check email domain if available
        if emails:
            for email in emails:
                try:
                    domain = email.split("@")[1].lower()
                    company_part = domain.split(".")[0]
                    if company_part not in [
                        "gmail", "yahoo", "outlook", "hotmail", "protonmail",
                        "icloud", "mail", "rediffmail", "zoho"
                    ] and len(company_part) >= 3:
                        return company_part.capitalize()
                except Exception:
                    pass

        # 2. Check regex patterns on combined text
        combined = f"{title}\n{text}"
        for pat in cls._COMPANY_PATTERNS:
            match = pat.search(combined)
            if match:
                comp = match.group(1).strip()
                comp_clean = re.sub(r'\s+', ' ', comp).strip(" :,-–—")
                if len(comp_clean) >= 3 and comp_clean.lower() not in cls._GENERIC_COMPANY_WORDS:
                    return comp_clean.title()

        # 3. Clean from title separators (e.g. 'Python Developer | AcmeTech Solutions')
        clean_title = re.sub(r'#\S+', '', title)
        clean_title = re.sub(r'\.{2,}', '', clean_title)

        ROLE_WORDS = {
            "developer", "engineer", "lead", "architect", "intern", "fresher",
            "designer", "tester", "manager", "specialist", "hiring", "job",
            "urgent opening", "requirement", "openings", "full stack", "frontend", "backend"
        }

        for sep in ['—', '|', '-', ':']:
            if sep in clean_title:
                parts = clean_title.split(sep)
                # Check from last part to first part (companies usually appear after separator)
                for p in reversed(parts):
                    p_clean = re.sub(r'[^\w\s&.]', '', p).strip()
                    p_clean_lower = p_clean.lower()
                    if (
                        3 <= len(p_clean) <= 35
                        and p_clean_lower not in cls._GENERIC_COMPANY_WORDS
                        and not any(rw in p_clean_lower for rw in ROLE_WORDS)
                    ):
                        return p_clean.title()

        return "Hiring Team"

    @classmethod
    def extract_experience(cls, text: str) -> str:
        """Extracts experience requirement string."""
        if not text:
            return "1-3 Years (Estimated)"

        for pat in cls._EXP_PATTERNS:
            match = pat.search(text)
            if match:
                res = match.group(0).strip()
                if "fresher" in res.lower():
                    return "Fresher / Entry Level"
                return res.title()

        return "1-3 Years (Estimated)"

    @classmethod
    def parse(cls, post_data: Dict[str, Any], skills_taxonomy: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Enriches a raw post dictionary or snippet with structured hiring intelligence.
        """
        content = (post_data.get("snippet", "") + "\n" + post_data.get("title", "") + "\n" + post_data.get("full_post_content", "")).strip()
        title = post_data.get("title", "LinkedIn Hiring Opportunity")
        post_url = post_data.get("link") or post_data.get("post_url", "")

        # 1. Emails & Phones
        raw_emails = cls.EMAIL_REGEX.findall(content)
        valid_emails = sorted(list({
            e for e in raw_emails
            if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))
        }))

        phones = sorted(list(set(cls.PHONE_REGEX.findall(content))))

        # 2. ATS Application Links
        urls = cls.URL_REGEX.findall(content)
        apply_links = []
        for u in urls:
            clean_u = u.rstrip('.,;:)"\'')
            if any(dom in clean_u.lower() for dom in cls._ATS_DOMAINS):
                apply_links.append(clean_u)

        # 3. Canonicalized Skills
        skills_tax = skills_taxonomy or []
        text_lower = content.lower()
        matched_skills: Set[str] = set()

        for s in skills_tax:
            if re.search(r'(?:\b|\W)' + re.escape(s.lower()) + r'(?:\b|\W)', text_lower):
                canon = canonicalize_skill(s)
                if canon:
                    matched_skills.add(canon.title())

        # 4. Entities: Company, Work Mode, Salary, Experience
        company = cls.extract_company_name(title=title, text=content, emails=valid_emails)
        work_mode = cls.extract_work_mode(content)
        salary = cls.extract_salary_or_ctc(content)
        exp_req = cls.extract_experience(content)

        return {
            "title": title,
            "company": company,
            "work_mode": work_mode,
            "salary_range": salary or "Competitive / Not Disclosed",
            "experience_required": exp_req,
            "required_skills": sorted(list(matched_skills)),
            "contact_emails": valid_emails,
            "contact_phones": phones,
            "application_links": sorted(list(set(apply_links))),
            "post_url": post_url,
            "raw_snippet": content[:500].strip()
        }
