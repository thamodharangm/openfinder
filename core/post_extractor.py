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
    Extracts structured hiring intelligence from any direct LinkedIn Post URL,
    Feed Update, Share, or Shortlink and matches it deeply against a candidate's resume.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    PHONE_REGEX = r'(?:\+91[\-\s]?)?[6789]\d{9}'

    @staticmethod
    def normalize_skills(skills: List[str]) -> List[str]:
        """Normalizes skill naming variants into clean, standard labels."""
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
            "git": "Git"
        }
        normalized = set()
        for s in skills:
            s_clean = s.strip().lower()
            if s_clean in mapping:
                normalized.add(mapping[s_clean])
            else:
                normalized.add(s.title())
        return sorted(list(normalized))

    @staticmethod
    def extract_company(text: str, emails: List[str], author: str) -> str:
        """Infers the hiring company name from email domains, author headline, or post text."""
        for e in emails:
            domain = e.split("@")[-1].split(".")[0].lower()
            if domain not in ["gmail", "yahoo", "outlook", "hotmail", "proton", "icloud", "rediffmail"]:
                return domain.capitalize()

        comp_patterns = [
            r'(?:at|@)\s+([A-Z][a-zA-Z0-9&]+)',
            r'company\s*:\s*([A-Za-z0-9& ]+)',
            r'hiring\s+(?:for\s+)([A-Z][a-zA-Z0-9&]+)'
        ]
        for pat in comp_patterns:
            match = re.search(pat, text)
            if match:
                c = match.group(1).strip()
                if c.lower() not in ["we", "the", "our", "an", "immediate", "urgent", "delhi", "bangalore", "mumbai", "chennai"]:
                    return c

        return "the Hiring Team"

    @classmethod
    def extract_from_url(
        cls, 
        url: str, 
        skills_taxonomy: Optional[List[str]] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2
    ) -> Dict[str, Any]:
        """
        Parses LinkedIn recruiter post URL, extracting author, company, HR emails, phones,
        skills, calculates resume match score % & gaps, and generates customized outreach pitches.
        """
        skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        clean_url = url.split("?")[0].strip()
        url_lower = clean_url.lower()

        # STRICT VALIDATION: Reject any corporate job board /jobs/view/ aggregator links
        forbidden_patterns = ['/jobs/', '/job/', '/directory/', '/salary/', '/school/', '/learning/', '/pulse/', '/company/', 'jobs/view', '/jobs/view/']
        if any(f in url_lower for f in forbidden_patterns) or ('/posts/' not in url_lower and '/feed/update/' not in url_lower and 'activity-' not in url_lower and 'lnkd.in/p/' not in url_lower):
            return {"error": "Invalid URL: Only genuine personal recruiter/founder hiring posts (/posts/ or /feed/update/) are allowed. Corporate job board aggregator listings (/jobs/view/) are completely rejected."}

        # If candidate_profile passed, extract candidate info
        if candidate_profile:
            candidate_name = candidate_profile.get("candidate_name", candidate_name)
            candidate_exp_years = candidate_profile.get("years_of_experience", candidate_exp_years)
            cand_skills = candidate_profile.get("top_skills", [])
        else:
            cand_skills = []

        try:
            with httpx.Client(headers=cls.HEADERS, timeout=12.0, follow_redirects=True) as client:
                resp = client.get(clean_url)
                if resp.status_code != 200:
                    return {"error": f"Failed to fetch post (HTTP {resp.status_code})"}

                soup = BeautifulSoup(resp.text, "html.parser")
                
                og_title = soup.find("meta", property="og:title")
                og_desc = soup.find("meta", property="og:description")
                og_url = soup.find("meta", property="og:url")
                canonical_tag = soup.find("link", rel="canonical")
                
                title_str = og_title.get("content", "").strip() if og_title else ""
                full_text = og_desc.get("content", "").strip() if og_desc else soup.get_text()

                # Strictly resolve clean standalone /posts/ URL (eliminate /feed/ links)
                canonical_url = ""
                if og_url and og_url.get("content"):
                    canonical_url = og_url.get("content").strip()
                elif canonical_tag and canonical_tag.get("href"):
                    canonical_url = canonical_tag.get("href").strip()

                if canonical_url and "/posts/" in canonical_url:
                    final_post_url = canonical_url.split("?")[0]
                elif "/posts/" in clean_url:
                    final_post_url = clean_url.split("?")[0]
                else:
                    final_post_url = canonical_url.split("?")[0] if canonical_url else clean_url

                # Author info from title (e.g. "Title ... | Author Name")
                author = "Hiring Manager / Recruiter"
                if "|" in title_str:
                    author = title_str.split("|")[-1].strip()

                # Extract emails
                emails = [e for e in set(re.findall(cls.EMAIL_REGEX, full_text)) if not e.endswith(('.png', '.jpg', '.jpeg', '.gif'))]

                # Extract phone numbers
                phones = list(set(re.findall(cls.PHONE_REGEX, full_text)))

                # Extract skills & normalize
                text_lower = (full_text + " " + title_str).lower()
                raw_skills = [
                    s.title() for s in skills_taxonomy 
                    if re.search(r'(?:\b|\W)' + re.escape(s) + r'(?:\b|\W)', text_lower)
                ]
                skills = cls.normalize_skills(raw_skills)

                # Extract company
                company = cls.extract_company(full_text, emails, author)

                # Extract location hints
                loc_match = re.search(r'(?:📍\s*location|location|city|in)\s*:\s*([A-Za-z\s]+)', full_text, re.IGNORECASE)
                location = loc_match.group(1).strip() if loc_match else "Unspecified / Remote"

                # Extract role title
                role_match = re.search(r'hiring\s+(?:for\s+)?([^\n!.,#]+)', full_text, re.IGNORECASE)
                role = role_match.group(1).strip() if role_match else (title_str.split("|")[0].strip() if title_str else "Software Engineer")

                # Match against Candidate Resume
                match_data = {}
                pitch_skills = skills
                if cand_skills:
                    match_data = JobMatcher.calculate_weighted_match(
                        candidate_skills=cand_skills,
                        candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
                        required_skills=skills,
                        experience_required_str=full_text
                    )
                    pitch_skills = match_data.get("matched_skills") or skills

                # Generate customized recruiter pitches
                pitches = OutreachPitchGenerator.generate_suite(
                    job_title=role,
                    company_name=company,
                    matched_skills=pitch_skills if pitch_skills else ["Full Stack Development"],
                    candidate_name=candidate_name,
                    candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
                    recipient_name=author
                )

                result = {
                    "status": "success",
                    "post_url": final_post_url,
                    "author": author,
                    "company": company,
                    "job_role": role,
                    "location": location,
                    "recruiter_emails": emails,
                    "contact_numbers": phones,
                    "detected_skills": skills,
                    "tailored_outreach_pitches": pitches,
                    "full_post_content": full_text
                }
                if match_data:
                    result["match_analysis"] = match_data

                return result
        except Exception as e:
            return {"error": f"Error parsing post: {str(e)}"}
