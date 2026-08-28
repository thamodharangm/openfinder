import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMMON_SKILLS
from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.time_utils import (
    parse_timestamp,
    calculate_age,
    is_within_window,
    get_max_age_minutes,
    FRESHNESS_WINDOWS
)
from core.pitch_generator import OutreachPitchGenerator
from core.matcher import JobMatcher


class LinkedInPostExtractor:
    """
    Extracts structured hiring intelligence ONLY from genuine LinkedIn /posts/ URLs
    AND validates exact publication time down to the minute.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    PHONE_REGEX = r"(?:\+91[\-\s]?)?[6789]\d{9}"

    # Delegate URL validation to single source of truth
    @staticmethod
    def is_valid_post_url(url: str) -> bool:
        return is_valid_linkedin_post_url(url)

    # ---------------------------------------------------------
    # Normalize skills
    # ---------------------------------------------------------
    @staticmethod
    def normalize_skills(skills: List[str]) -> List[str]:
        mapping = {
            "react.js": "React",
            "reactjs": "React",
            "react": "React",
            "node.js": "Node.js",
            "nodejs": "Node.js",
            "express.js": "Express.js",
            "expressjs": "Express.js",
            "express": "Express.js",
            "next.js": "Next.js",
            "nextjs": "Next.js",
            "vue.js": "Vue.js",
            "vuejs": "Vue.js",
            "angular.js": "Angular",
            "angularjs": "Angular",
            "tailwindcss": "Tailwind CSS",
            "tailwind": "Tailwind CSS",
            "mongodb": "MongoDB",
            "postgresql": "PostgreSQL",
            "postgres": "PostgreSQL",
            "mysql": "MySQL",
            "fastapi": "FastAPI",
            "django": "Django",
            "flask": "Flask",
            "typescript": "TypeScript",
            "javascript": "JavaScript",
            "python": "Python",
            "docker": "Docker",
            "kubernetes": "Kubernetes",
            "git": "Git",
        }

        normalized = set()
        for skill in skills:
            clean = skill.strip().lower()
            if clean in mapping:
                normalized.add(mapping[clean])
            else:
                normalized.add(skill.title())

        return sorted(normalized)

    # ---------------------------------------------------------
    # Extract company
    # ---------------------------------------------------------
    @staticmethod
    def extract_company(
        text: str,
        emails: List[str],
        author: str
    ) -> str:
        ignored_domains = {
            "gmail",
            "yahoo",
            "outlook",
            "hotmail",
            "proton",
            "icloud",
            "rediffmail",
        }

        for email in emails:
            domain = email.split("@")[-1].split(".")[0].lower()
            if domain not in ignored_domains:
                return domain.capitalize()

        patterns = [
            r"(?:at|@)\s+([A-Z][a-zA-Z0-9&]+)",
            r"company\s*:\s*([A-Za-z0-9& ]+)",
            r"hiring\s+(?:for\s+)([A-Z][a-zA-Z0-9&]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                company = match.group(1).strip()
                if company.lower() not in {
                    "we",
                    "the",
                    "our",
                    "an",
                    "immediate",
                    "urgent",
                    "delhi",
                    "bangalore",
                    "mumbai",
                    "chennai",
                }:
                    return company

        return "the Hiring Team"

    # ---------------------------------------------------------
    # Main extractor
    # ---------------------------------------------------------
    @classmethod
    def extract_from_url(
        cls,
        url: str,
        skills_taxonomy: Optional[List[str]] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        max_age_minutes: Optional[int] = None,
        timeframe: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extracts intelligence strictly from a valid LinkedIn /posts/ URL.
        Enforces exact minute-level freshness window.
        """
        norm_url = normalize_linkedin_post_url(url)

        # -----------------------------------------------------
        # 1. STRICT URL CHECK
        # -----------------------------------------------------
        if not norm_url:
            return {
                "status": "rejected",
                "reason": "NOT_A_LINKEDIN_POST",
                "error": "Only genuine https://*.linkedin.com/posts/... URLs are accepted.",
            }

        # Resolve max_age_minutes
        if max_age_minutes is None and timeframe:
            try:
                max_age_minutes = get_max_age_minutes(timeframe)
            except ValueError as e:
                return {
                    "status": "rejected",
                    "reason": "INVALID_TIMEFRAME",
                    "error": str(e)
                }

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS

        # Candidate profile
        if candidate_profile:
            candidate_name = candidate_profile.get("candidate_name", candidate_name)
            candidate_exp_years = candidate_profile.get("years_of_experience", candidate_exp_years)
            cand_skills = candidate_profile.get("top_skills", [])
        else:
            cand_skills = []

        try:
            with httpx.Client(
                headers=cls.HEADERS,
                timeout=12.0,
                follow_redirects=True
            ) as client:

                response = client.get(norm_url)
                if response.status_code != 200:
                    return {
                        "status": "error",
                        "reason": "FETCH_FAILED",
                        "error": f"HTTP {response.status_code}",
                    }

                soup = BeautifulSoup(response.text, "html.parser")

                # =================================================
                # 2. Timestamp Extraction & Freshness Verification
                # =================================================
                published_at = parse_timestamp(soup_or_str=soup, url=norm_url)
                if published_at is None:
                    return {
                        "status": "rejected",
                        "reason": "PUBLISHED_TIME_UNVERIFIED",
                        "error": "Could not verify the post publication timestamp. Rejected for freshness safety.",
                    }

                # Age analysis
                age_info = calculate_age(published_at)
                if not age_info["is_valid"]:
                    return {
                        "status": "rejected",
                        "reason": "INVALID_TIMESTAMP",
                        "published_at": published_at.isoformat(),
                        "error": "Post has an invalid or future timestamp.",
                    }

                # Window check
                if max_age_minutes is not None:
                    if not is_within_window(published_at, max_age_minutes):
                        return {
                            "status": "rejected",
                            "reason": "OLDER_THAN_REQUESTED_WINDOW",
                            "published_at": published_at.isoformat(),
                            "age_minutes": age_info["age_minutes"],
                            "max_age_minutes": max_age_minutes,
                            "error": f"Post age ({age_info['age_minutes']}m) exceeds requested freshness window ({max_age_minutes}m).",
                        }

                # =================================================
                # 3. Content Metadata Extraction
                # =================================================
                og_title = soup.find("meta", property="og:title")
                og_desc = soup.find("meta", property="og:description")

                title_str = og_title.get("content", "").strip() if og_title else ""
                full_text = og_desc.get("content", "").strip() if og_desc else soup.get_text(" ", strip=True)

                # Author
                author = "Hiring Manager / Recruiter"
                if "|" in title_str:
                    author = title_str.split("|")[-1].strip()

                # Emails & Phones
                emails = sorted(set(re.findall(cls.EMAIL_REGEX, full_text)))
                phones = sorted(set(re.findall(cls.PHONE_REGEX, full_text)))

                # Skills
                text_lower = (full_text + " " + title_str).lower()
                raw_skills = []
                for skill in skills_taxonomy:
                    if re.search(r"(?:\b|\W)" + re.escape(skill.lower()) + r"(?:\b|\W)", text_lower):
                        raw_skills.append(skill)
                skills = cls.normalize_skills(raw_skills)

                # Company & Location
                company = cls.extract_company(full_text, emails, author)
                loc_match = re.search(r"(?:📍\s*location|location|city|in)\s*:\s*([A-Za-z\s]+)", full_text, re.IGNORECASE)
                location = loc_match.group(1).strip() if loc_match else "Unspecified / Remote"

                # Role
                role_match = re.search(r"hiring\s+(?:for\s+)?([^\n!.,#]+)", full_text, re.IGNORECASE)
                role = role_match.group(1).strip() if role_match else (title_str.split("|")[0].strip() if title_str else "Software Engineer")

                # =================================================
                # 4. Resume Match & Outreach Pitches
                # =================================================
                match_data = {}
                pitch_skills = skills
                if cand_skills:
                    match_data = JobMatcher.calculate_weighted_match(
                        candidate_skills=cand_skills,
                        candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
                        required_skills=skills,
                        experience_required_str=full_text,
                    )
                    pitch_skills = match_data.get("matched_skills") or skills

                pitches = OutreachPitchGenerator.generate_suite(
                    job_title=role,
                    company_name=company,
                    matched_skills=pitch_skills if pitch_skills else ["Full Stack Development"],
                    candidate_name=candidate_name,
                    candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
                    recipient_name=author,
                )

                # =================================================
                # 5. Guaranteed /posts/ Output Contract
                # =================================================
                result = {
                    "status": "success",
                    "post_url": norm_url,
                    "published_at": published_at.isoformat(),
                    "age_minutes": age_info["age_minutes"],
                    "age_hours": age_info["age_hours"],
                    "age_text": age_info["age_text"],
                    "author": author,
                    "company": company,
                    "job_role": role,
                    "location": location,
                    "recruiter_emails": emails,
                    "contact_numbers": phones,
                    "detected_skills": skills,
                    "tailored_outreach_pitches": pitches,
                    "full_post_content": full_text,
                }

                if match_data:
                    result["match_analysis"] = match_data

                return result

        except Exception as exc:
            return {
                "status": "error",
                "reason": "PARSER_ERROR",
                "error": str(exc),
            }
