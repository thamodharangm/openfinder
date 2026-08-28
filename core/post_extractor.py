import re
import urllib.parse
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMMON_SKILLS
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

    # =========================================================
    # 1. ONLY /posts/ URLs
    # =========================================================
    @staticmethod
    def is_valid_post_url(url: str) -> bool:
        if not url:
            return False

        clean_url = url.split("?")[0].strip()
        parsed = urllib.parse.urlparse(clean_url)

        # Only LinkedIn (support all subdomains like in.linkedin.com, www.linkedin.com)
        hostname = parsed.netloc.lower()
        if hostname != "linkedin.com" and not hostname.endswith(".linkedin.com"):
            return False

        # ONLY /posts/
        if not parsed.path.lower().startswith("/posts/"):
            return False

        # Must contain slug after /posts/
        post_slug = parsed.path[len("/posts/"):].strip("/")
        if not post_slug:
            return False

        # Explicitly reject non-post paths
        forbidden = [
            "/jobs/", "/job/", "/jobs/view/", "/company/",
            "/pulse/", "/learning/", "/school/", "/salary/",
            "/directory/", "/feed/update/", "/activity-"
        ]
        if any(f in clean_url.lower() for f in forbidden):
            return False

        return True

    # =========================================================
    # 2. Extract actual publication datetime
    # =========================================================
    @classmethod
    def extract_published_datetime(cls, soup: BeautifulSoup, url: str = "") -> Optional[datetime]:
        """
        Extracts exact publication timestamp from JSON-LD schema,
        HTML metadata tags, and URL snowflake activity ID.
        """
        candidates = []

        # -----------------------------------------------------
        # JSON-LD (Primary & Most Accurate for LinkedIn)
        # -----------------------------------------------------
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            for key in ["datePublished", "dateCreated", "uploadDate"]:
                match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
                if match:
                    candidates.append(match.group(1))

        # -----------------------------------------------------
        # <meta property="article:published_time">
        # -----------------------------------------------------
        meta_published = soup.find("meta", attrs={"property": "article:published_time"})
        if meta_published and meta_published.get("content"):
            candidates.append(meta_published.get("content"))

        # -----------------------------------------------------
        # <meta name="date">
        # -----------------------------------------------------
        meta_date = soup.find("meta", attrs={"name": "date"})
        if meta_date and meta_date.get("content"):
            candidates.append(meta_date.get("content"))

        # -----------------------------------------------------
        # <time datetime="...">
        # -----------------------------------------------------
        for time_tag in soup.find_all("time"):
            val = time_tag.get("datetime")
            if val:
                candidates.append(val)

        # Parse collected ISO string candidates
        for value in candidates:
            try:
                val = value.strip()
                if val.endswith("Z"):
                    val = val[:-1] + "+00:00"
                dt = datetime.fromisoformat(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue

        # -----------------------------------------------------
        # Snowflake Activity ID Fallback (Fail-safe 64-bit TS)
        # -----------------------------------------------------
        if url:
            match = re.search(r'(?:activity|share)[:-](\d{15,})', url)
            if match:
                aid = int(match.group(1))
                ts_sec = (aid >> 22) / 1000.0
                return datetime.fromtimestamp(ts_sec, tz=timezone.utc)

        return None

    # =========================================================
    # 3. Check post age & recency helpers
    # =========================================================
    @staticmethod
    def is_within_last_hour(published_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        age = now - published_at
        return timedelta(0) <= age < timedelta(hours=1)

    @staticmethod
    def get_post_age_minutes(published_at: datetime) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        age = now - published_at
        total_minutes = int(age.total_seconds() // 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return {
            "hours": hours,
            "minutes": minutes,
            "total_minutes": total_minutes,
            "age_text": f"{hours}h {minutes}m ago" if hours > 0 else f"{minutes}m ago",
            "is_within_last_hour": timedelta(0) <= age < timedelta(hours=1)
        }

    @staticmethod
    def get_post_age(published_at: datetime, max_age_hours: Optional[int] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        age = now - published_at

        # Future timestamp = invalid
        if age.total_seconds() < 0:
            return None

        # Filter by max_age_hours if specified
        if max_age_hours is not None and age >= timedelta(hours=max_age_hours):
            return None

        total_minutes = int(age.total_seconds() // 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60

        if hours < 1:
            age_text = f"{minutes}m ago"
        elif hours < 24:
            age_text = f"{hours}h {minutes}m ago"
        else:
            days = hours // 24
            age_text = f"{days}d {hours % 24}h ago"

        return {
            "age_hours": hours,
            "age_minutes": minutes,
            "total_minutes": total_minutes,
            "is_within_last_hour": timedelta(0) <= age < timedelta(hours=1),
            "age_text": age_text,
            "published_at_utc": published_at.isoformat(),
        }

    # =========================================================
    # 4. Normalize skills
    # =========================================================
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

    # =========================================================
    # 5. Company extraction
    # =========================================================
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

    # =========================================================
    # 6. Main extractor
    # =========================================================
    @classmethod
    def extract_from_url(
        cls,
        url: str,
        skills_taxonomy: Optional[List[str]] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        max_age_hours: Optional[int] = None,
    ) -> Dict[str, Any]:

        clean_url = url.split("?")[0].strip()

        # -----------------------------------------------------
        # STRICT URL CHECK
        # -----------------------------------------------------
        is_internal_activity = bool("/feed/update/" in clean_url or "urn:li:activity:" in clean_url)
        if not cls.is_valid_post_url(clean_url) and not is_internal_activity:
            return {
                "status": "rejected",
                "reason": "NOT_A_LINKEDIN_POST",
                "error": "Only https://www.linkedin.com/posts/... URLs are accepted.",
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

                response = client.get(clean_url)
                if response.status_code != 200:
                    return {
                        "status": "error",
                        "reason": "FETCH_FAILED",
                        "error": f"HTTP {response.status_code}",
                    }

                soup = BeautifulSoup(response.text, "html.parser")

                # =================================================
                # Publication Timestamp Validation
                # =================================================
                published_at = cls.extract_published_datetime(soup, url=clean_url)
                if published_at is None:
                    return {
                        "status": "rejected",
                        "reason": "PUBLISHED_TIME_NOT_FOUND",
                        "error": "Could not verify the post publication time.",
                    }

                # Post Age Filter
                age_info = cls.get_post_age(published_at, max_age_hours=max_age_hours)
                if age_info is None:
                    return {
                        "status": "rejected",
                        "reason": "EXCEEDED_MAX_AGE",
                        "published_at_utc": published_at.isoformat(),
                        "error": f"Post exceeds maximum age limit ({max_age_hours}h)." if max_age_hours else "Invalid post age.",
                    }

                # =================================================
                # Metadata
                # =================================================
                og_title = soup.find("meta", property="og:title")
                og_desc = soup.find("meta", property="og:description")
                og_url = soup.find("meta", property="og:url")
                canonical_tag = soup.find("link", rel="canonical")

                title_str = og_title.get("content", "").strip() if og_title else ""
                full_text = og_desc.get("content", "").strip() if og_desc else soup.get_text(" ", strip=True)

                # =================================================
                # FINAL URL (STRICT /posts/ ONLY)
                # =================================================
                canonical_url = ""
                if og_url and og_url.get("content"):
                    canonical_url = og_url.get("content").strip().split("?")[0]
                elif canonical_tag and canonical_tag.get("href"):
                    canonical_url = canonical_tag.get("href").strip().split("?")[0]

                if cls.is_valid_post_url(canonical_url):
                    final_post_url = canonical_url
                elif cls.is_valid_post_url(clean_url):
                    final_post_url = clean_url
                else:
                    return {
                        "status": "rejected",
                        "reason": "INVALID_FINAL_URL",
                        "error": "Resolved URL is not a genuine LinkedIn /posts/ URL.",
                    }

                # =================================================
                # Author
                # =================================================
                author = "Hiring Manager / Recruiter"
                if "|" in title_str:
                    author = title_str.split("|")[-1].strip()

                # =================================================
                # Emails & Phones
                # =================================================
                emails = sorted(set(re.findall(cls.EMAIL_REGEX, full_text)))
                phones = sorted(set(re.findall(cls.PHONE_REGEX, full_text)))

                # =================================================
                # Skills
                # =================================================
                text_lower = (full_text + " " + title_str).lower()
                raw_skills = []
                for skill in skills_taxonomy:
                    if re.search(r"(?:\b|\W)" + re.escape(skill.lower()) + r"(?:\b|\W)", text_lower):
                        raw_skills.append(skill)
                skills = cls.normalize_skills(raw_skills)

                # =================================================
                # Company & Location
                # =================================================
                company = cls.extract_company(full_text, emails, author)
                loc_match = re.search(r"(?:📍\s*location|location|city|in)\s*:\s*([A-Za-z\s]+)", full_text, re.IGNORECASE)
                location = loc_match.group(1).strip() if loc_match else "Unspecified / Remote"

                # =================================================
                # Role
                # =================================================
                role_match = re.search(r"hiring\s+(?:for\s+)?([^\n!.,#]+)", full_text, re.IGNORECASE)
                role = role_match.group(1).strip() if role_match else (title_str.split("|")[0].strip() if title_str else "Software Engineer")

                # =================================================
                # Resume Match
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

                # =================================================
                # Outreach Pitches
                # =================================================
                pitches = OutreachPitchGenerator.generate_suite(
                    job_title=role,
                    company_name=company,
                    matched_skills=pitch_skills if pitch_skills else ["Full Stack Development"],
                    candidate_name=candidate_name,
                    candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
                    recipient_name=author,
                )

                # =================================================
                # SUCCESS RESULT
                # =================================================
                result = {
                    "status": "success",
                    "post_url": final_post_url,
                    "author": author,
                    "company": company,
                    "job_role": role,
                    "location": location,
                    "published_at": published_at.isoformat(),
                    "post_age": age_info["age_text"],
                    "age_hours": age_info["age_hours"],
                    "age_minutes": age_info["age_minutes"],
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


# =============================================================
# TEST
# =============================================================
if __name__ == "__main__":
    test_url = "https://www.linkedin.com/posts/siva-raja-lingam-12ab4a223_we-are-hiring-egrove-systems-is-looking-activity-7498493404704591873-1z9G"
    print("Testing post extractor with timestamp analysis on:", test_url)
    res = LinkedInPostExtractor.extract_from_url(test_url)
    print("\nStatus:", res.get("status"))
    print("Post Age:", res.get("post_age"))
    print("Published At:", res.get("published_at"))
    print("Company:", res.get("company"))
    print("Role:", res.get("job_role"))
    print("Post URL:", res.get("post_url"))
