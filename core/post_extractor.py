import re
import urllib.parse
from typing import Dict, Any, Optional, List
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
    Extracts structured hiring intelligence ONLY from genuine LinkedIn /posts/ URLs.
    All other LinkedIn URL types are rejected.
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

    # ---------------------------------------------------------
    # ONLY /posts/ URL validation
    # ---------------------------------------------------------
    @staticmethod
    def is_valid_post_url(url: str) -> bool:
        """
        Accept ONLY:
            https://www.linkedin.com/posts/... (or *.linkedin.com/posts/...)

        Reject:
            /jobs/
            /jobs/view/
            /feed/update/
            /activity-
            /company/
            /pulse/
            /learning/
            /school/
            /salary/
            /directory/
            lnkd.in/p/
            any non-LinkedIn URL
        """
        if not url:
            return False

        clean_url = url.split("?")[0].strip()
        parsed = urllib.parse.urlparse(clean_url)

        # Must be LinkedIn (including all subdomains like in.linkedin.com, www.linkedin.com)
        hostname = parsed.netloc.lower()
        if hostname != "linkedin.com" and not hostname.endswith(".linkedin.com"):
            return False

        # Path MUST start with /posts/
        path = parsed.path.rstrip("/")
        if not path.lower().startswith("/posts/"):
            return False

        # Must contain something after /posts/
        post_slug = path[len("/posts/"):].strip("/")
        if not post_slug:
            return False

        # Explicitly reject other URL patterns
        forbidden_patterns = [
            "/jobs/",
            "/job/",
            "/jobs/view/",
            "/feed/update/",
            "/company/",
            "/pulse/",
            "/learning/",
            "/school/",
            "/salary/",
            "/directory/",
            "/activity-",
        ]

        url_lower = clean_url.lower()
        if any(pattern in url_lower for pattern in forbidden_patterns):
            return False

        return True

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
        # Try email domain first
        for email in emails:
            domain = email.split("@")[-1].split(".")[0].lower()
            ignored_domains = {
                "gmail",
                "yahoo",
                "outlook",
                "hotmail",
                "proton",
                "icloud",
                "rediffmail",
            }
            if domain not in ignored_domains:
                return domain.capitalize()

        comp_patterns = [
            r"(?:at|@)\s+([A-Z][a-zA-Z0-9&]+)",
            r"company\s*:\s*([A-Za-z0-9& ]+)",
            r"hiring\s+(?:for\s+)([A-Z][a-zA-Z0-9&]+)",
        ]

        for pattern in comp_patterns:
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
    # Extract ONLY genuine /posts/ URL
    # ---------------------------------------------------------
    @classmethod
    def extract_from_url(
        cls,
        url: str,
        skills_taxonomy: Optional[List[str]] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
    ) -> Dict[str, Any]:

        # =====================================================
        # STRICT /posts/ VALIDATION
        # =====================================================
        clean_url = url.split("?")[0].strip()

        # If it's an internal activity link being resolved, fetch to get canonical /posts/ URL
        is_internal_activity = bool("/feed/update/" in clean_url or "urn:li:activity:" in clean_url)
        
        if not cls.is_valid_post_url(clean_url) and not is_internal_activity:
            return {
                "status": "rejected",
                "error": (
                    "Invalid LinkedIn URL. "
                    "ONLY genuine /posts/ URLs are accepted."
                ),
                "accepted_format": (
                    "https://www.linkedin.com/posts/..."
                ),
                "rejected_types": [
                    "/jobs/",
                    "/jobs/view/",
                    "/feed/update/",
                    "/activity-",
                    "/company/",
                    "/pulse/",
                    "/learning/",
                    "/school/",
                    "/salary/",
                    "/directory/",
                    "lnkd.in/p/",
                ],
            }

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS

        # Candidate profile
        if candidate_profile:
            candidate_name = candidate_profile.get(
                "candidate_name",
                candidate_name
            )
            candidate_exp_years = candidate_profile.get(
                "years_of_experience",
                candidate_exp_years
            )
            cand_skills = candidate_profile.get(
                "top_skills",
                []
            )
        else:
            cand_skills = []

        try:
            # =================================================
            # Fetch URL
            # =================================================
            with httpx.Client(
                headers=cls.HEADERS,
                timeout=12.0,
                follow_redirects=True
            ) as client:

                response = client.get(clean_url)
                if response.status_code != 200:
                    return {
                        "status": "error",
                        "error": (
                            f"Failed to fetch LinkedIn post "
                            f"(HTTP {response.status_code})"
                        ),
                    }

                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )

                # =================================================
                # Metadata
                # =================================================
                og_title = soup.find(
                    "meta",
                    property="og:title"
                )
                og_desc = soup.find(
                    "meta",
                    property="og:description"
                )
                og_url = soup.find(
                    "meta",
                    property="og:url"
                )
                canonical_tag = soup.find(
                    "link",
                    rel="canonical"
                )

                title_str = (
                    og_title.get("content", "").strip()
                    if og_title
                    else ""
                )

                full_text = (
                    og_desc.get("content", "").strip()
                    if og_desc
                    else soup.get_text(" ", strip=True)
                )

                # =================================================
                # Resolve final URL
                # BUT FINAL URL MUST ALWAYS BE /posts/
                # =================================================
                canonical_url = ""
                if og_url and og_url.get("content"):
                    canonical_url = og_url.get("content").strip()
                elif canonical_tag and canonical_tag.get("href"):
                    canonical_url = canonical_tag.get("href").strip()

                canonical_url = canonical_url.split("?")[0]

                # Prefer canonical only if canonical is /posts/
                if cls.is_valid_post_url(canonical_url):
                    final_post_url = canonical_url
                elif cls.is_valid_post_url(clean_url):
                    final_post_url = clean_url
                else:
                    return {
                        "status": "rejected",
                        "error": (
                            "Resolved URL is not a genuine "
                            "LinkedIn /posts/ URL."
                        ),
                    }

                # =================================================
                # Author
                # =================================================
                author = "Hiring Manager / Recruiter"
                if "|" in title_str:
                    author = title_str.split("|")[-1].strip()

                # =================================================
                # Emails
                # =================================================
                emails = sorted(set(
                    re.findall(
                        cls.EMAIL_REGEX,
                        full_text
                    )
                ))

                # =================================================
                # Phones
                # =================================================
                phones = sorted(set(
                    re.findall(
                        cls.PHONE_REGEX,
                        full_text
                    )
                ))

                # =================================================
                # Skills
                # =================================================
                text_lower = (
                    full_text + " " + title_str
                ).lower()

                raw_skills = []
                for skill in skills_taxonomy:
                    pattern = (
                        r"(?:\b|\W)"
                        + re.escape(skill.lower())
                        + r"(?:\b|\W)"
                    )
                    if re.search(
                        pattern,
                        text_lower
                    ):
                        raw_skills.append(skill)

                skills = cls.normalize_skills(
                    raw_skills
                )

                # =================================================
                # Company
                # =================================================
                company = cls.extract_company(
                    full_text,
                    emails,
                    author
                )

                # =================================================
                # Location
                # =================================================
                loc_match = re.search(
                    r"(?:📍\s*location|location|city|in)"
                    r"\s*:\s*([A-Za-z\s]+)",
                    full_text,
                    re.IGNORECASE
                )

                location = (
                    loc_match.group(1).strip()
                    if loc_match
                    else "Unspecified / Remote"
                )

                # =================================================
                # Role
                # =================================================
                role_match = re.search(
                    r"hiring\s+(?:for\s+)?"
                    r"([^\n!.,#]+)",
                    full_text,
                    re.IGNORECASE
                )

                role = (
                    role_match.group(1).strip()
                    if role_match
                    else (
                        title_str.split("|")[0].strip()
                        if title_str
                        else "Software Engineer"
                    )
                )

                # =================================================
                # Resume Match
                # =================================================
                match_data = {}
                pitch_skills = skills

                if cand_skills:
                    match_data = (
                        JobMatcher.calculate_weighted_match(
                            candidate_skills=cand_skills,
                            candidate_exp_years=(
                                candidate_exp_years
                                if isinstance(
                                    candidate_exp_years,
                                    int
                                )
                                else 2
                            ),
                            required_skills=skills,
                            experience_required_str=full_text,
                        )
                    )

                    pitch_skills = (
                        match_data.get("matched_skills")
                        or skills
                    )

                # =================================================
                # Outreach Pitches
                # =================================================
                pitches = (
                    OutreachPitchGenerator.generate_suite(
                        job_title=role,
                        company_name=company,
                        matched_skills=(
                            pitch_skills
                            if pitch_skills
                            else ["Full Stack Development"]
                        ),
                        candidate_name=candidate_name,
                        candidate_exp_years=(
                            candidate_exp_years
                            if isinstance(
                                candidate_exp_years,
                                int
                            )
                            else 2
                        ),
                        recipient_name=author,
                    )
                )

                # =================================================
                # Final result
                # =================================================
                result = {
                    "status": "success",
                    # GUARANTEED /posts/ ONLY
                    "post_url": final_post_url,
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
                "error": f"Error parsing post: {str(exc)}",
            }


# =============================================================
# TEST
# =============================================================
if __name__ == "__main__":
    test_urls = [
        # ✅ ACCEPT
        "https://www.linkedin.com/posts/siva-raja-lingam-12ab4a223_we-are-hiring-egrove-systems-is-looking-activity-7498493404704591873-1z9G",

        # ❌ REJECT
        "https://www.linkedin.com/jobs/view/123456789",
        "https://www.linkedin.com/company/example/",
        "https://www.linkedin.com/pulse/example-post/",
        "https://lnkd.in/p/abcdef",
    ]

    for test_url in test_urls:
        print("\n" + "=" * 80)
        print("URL:", test_url)

        result = LinkedInPostExtractor.extract_from_url(test_url)
        print("STATUS:", result.get("status"))
        print("POST URL:", result.get("post_url"))
        print("ERROR:", result.get("error"))
