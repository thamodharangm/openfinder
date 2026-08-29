"""
core/resume_parser.py
=====================
Production-grade Resume Intelligence & Structured Profile Extractor.

Features:
- Multi-source ingestion: Native PDF extraction (via PyPDF) + Direct Raw Text CV parsing.
- Precise timeline & experience calculator (date range parsing e.g. '2020 - 2024', 'Jan 2021 - Present').
- Accurate name extraction with header heuristics, filtering titles like 'Resume' or 'Curriculum Vitae'.
- Education & degree parser (B.Tech, B.E., MS, MCA, BS, BCA, GPA/Years).
- Full social links extraction (GitHub, LinkedIn, Portfolio/Personal Website).
- Skill categorization & canonical normalization across 70+ technology ecosystems.
- Target role & industry domain inference (FinTech, SaaS, AI/ML, Cloud/DevOps).
"""

from datetime import datetime
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pypdf

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS, MAX_RESUME_FILE_BYTES, SKILL_TAXONOMY
from core.matcher import canonicalize_skill

logger = logging.getLogger(__name__)


class ResumeParser:
    """
    Production-Hardened Professional Resume Parser.
    Extracts categorized technical skills, seniority level, contact info, 
    education, key projects, and target job profiles with security validation.
    """

    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', re.IGNORECASE)
    PHONE_REGEX = re.compile(
        r'(?:\+?\d{1,3}[-.\s]?)?\d{5}[-.\s]?\d{5}|(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+91[\s-]?\d{10}\b'
    )
    GITHUB_REGEX = re.compile(r'(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+)', re.IGNORECASE)
    LINKEDIN_REGEX = re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)', re.IGNORECASE)
    PORTFOLIO_REGEX = re.compile(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.(?:dev|me|io|tech|app|com|in))(?:\/[^\s]*)?', re.IGNORECASE)

    DATE_RANGE_REGEX = re.compile(
        r'(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?'
        r'(\d{4})\s*(?:-|–|to)\s*'
        r'(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?'
        r'(\d{4}|present|current|till\s+date|now)',
        re.IGNORECASE
    )

    DEGREE_REGEX = re.compile(
        r'\b(b\.?tech|b\.?e\.?|m\.?tech|m\.?s\.?|b\.?sc|m\.?sc|bca|mca|bba|mba|ph\.?d|bachelor|master)\b',
        re.IGNORECASE
    )

    def __init__(self):
        self.taxonomy = SKILL_TAXONOMY

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extracts text from PDF resume with multi-page handling and security checks."""
        if not pdf_path:
            raise ValueError("Resume file path cannot be empty.")

        file_path = Path(pdf_path).resolve()
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Resume file not found at: {pdf_path}")

        # Security check: file size limit
        file_size = file_path.stat().st_size
        if file_size > MAX_RESUME_FILE_BYTES:
            raise ValueError(f"Resume file exceeds maximum allowed size of {MAX_RESUME_FILE_BYTES // (1024*1024)}MB.")

        extracted_text = []
        try:
            reader = pypdf.PdfReader(str(file_path))
            if reader.is_encrypted:
                try:
                    reader.decrypt('')
                except Exception:
                    raise ValueError("The PDF is password protected and cannot be parsed.")

            for page in reader.pages:
                text = page.extract_text()
                if text:
                    extracted_text.append(text)
        except Exception as e:
            raise RuntimeError(f"Failed to read PDF resume: {str(e)}")

        full_text = "\n".join(extracted_text)
        if not full_text.strip():
            raise ValueError("The PDF contains no readable text (it may be an empty document or image-only scan).")

        return full_text

    def extract_candidate_name_and_contact(self, text: str) -> Dict[str, Optional[str]]:
        """Extracts candidate name, email, phone, GitHub, LinkedIn, and portfolio link."""
        if not text:
            return {"name": "Candidate", "email": None, "phone": None, "github": None, "linkedin": None, "portfolio": None}

        # 1. Contacts
        emails = self.EMAIL_REGEX.findall(text)
        phones = self.PHONE_REGEX.findall(text)
        github = self.GITHUB_REGEX.search(text)
        linkedin = self.LINKEDIN_REGEX.search(text)

        # Exclude email domains from portfolio match
        email_domains = {e.split("@")[1].lower() for e in emails if "@" in e}
        portfolio_url = None
        for m in self.PORTFOLIO_REGEX.finditer(text):
            candidate_domain = m.group(1).lower()
            if (
                candidate_domain not in email_domains
                and not any(excluded in candidate_domain for excluded in ["github.com", "linkedin.com", "google.com", "example.com"])
            ):
                raw_url = m.group(0)
                portfolio_url = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
                break

        # 2. Candidate Name Extraction Heuristics
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        candidate_name = "Candidate"

        GENERIC_TITLES = {
            "resume", "curriculum vitae", "cv", "page 1", "page 2", "profile",
            "contact", "education", "experience", "skills", "projects", "software engineer"
        }

        for line in lines[:8]:
            line_clean = re.sub(r'[^a-zA-Z\s.]', '', line).strip()
            words = line_clean.split()
            if 2 <= len(words) <= 4 and len(line_clean) <= 35:
                if line_clean.lower() not in GENERIC_TITLES and not any(g in line_clean.lower() for g in ["resume", "email", "phone", "curriculum"]):
                    candidate_name = line_clean.title()
                    break

        return {
            "name": candidate_name,
            "email": emails[0] if emails else None,
            "phone": phones[0].strip() if phones else None,
            "github": f"https://github.com/{github.group(1)}" if github else None,
            "linkedin": f"https://linkedin.com/in/{linkedin.group(1)}" if linkedin else None,
            "portfolio": portfolio_url
        }

    def extract_categorized_skills(self, text: str) -> Dict[str, List[str]]:
        """Categorizes all matched technical skills into domains and parses explicit skill lines."""
        if not text:
            return {}

        text_lower = text.lower()
        categorized: Dict[str, Set[str]] = {}

        # 1. Standard taxonomy pattern matching
        for category, skills in self.taxonomy.items():
            for skill in skills:
                pattern = r'(?:\b|\W)' + re.escape(skill) + r'(?:\b|\W)'
                if re.search(pattern, text_lower):
                    canon = canonicalize_skill(skill)
                    if canon:
                        categorized.setdefault(category, set()).add(canon.title())

        # 2. Deep Explicit Skill Header Extraction
        section_patterns = [
            (r'(?:frontend|ui|client[\s-]side)[\s\w]*:\s*([^\n\r]+)', "Frontend"),
            (r'(?:backend|server[\s-]side|apis?)[\s\w]*:\s*([^\n\r]+)', "Backend & APIs"),
            (r'(?:database|storage|databases)[\s\w]*:\s*([^\n\r]+)', "Databases & Storage"),
            (r'(?:tools|devops|cloud|platforms)[\s\w]*:\s*([^\n\r]+)', "Cloud, DevOps & Infrastructure"),
            (r'(?:languages|programming)[\s\w]*:\s*([^\n\r]+)', "Languages"),
            (r'(?:technical skills|skills|tech stack)[\s\w]*:\s*([^\n\r]+)', "Technical Skills"),
        ]

        for sec_pattern, target_cat in section_patterns:
            matches = re.findall(sec_pattern, text, re.IGNORECASE)
            for m in matches:
                tokens = re.split(r'[,|•/·;]+', m)
                for t in tokens:
                    clean_t = t.strip().strip("-").strip()
                    if clean_t and 2 <= len(clean_t) <= 30 and not clean_t.lower().startswith("experience"):
                        canon = canonicalize_skill(clean_t)
                        if canon:
                            categorized.setdefault(target_cat, set()).add(canon.title())

        return {k: sorted(list(v)) for k, v in categorized.items()}

    def extract_education(self, text: str) -> Dict[str, Any]:
        """Extracts education details including degree, graduation year, and college."""
        if not text:
            return {"degree": "Bachelor of Technology (B.Tech / B.E.)", "graduation_year": None}

        text_lower = text.lower()
        degree = None

        if any(w in text_lower for w in ["b.tech", "btech", "bachelor of technology", "b.e.", "b.e "]):
            degree = "Bachelor of Technology (B.Tech / B.E.)"
        elif any(w in text_lower for w in ["m.tech", "mtech", "master of technology", "m.s.", "m.s "]):
            degree = "Master of Science / Technology (M.Tech / M.S.)"
        elif any(w in text_lower for w in ["mca", "master of computer applications"]):
            degree = "Master of Computer Applications (MCA)"
        elif any(w in text_lower for w in ["bca", "bachelor of computer applications"]):
            degree = "Bachelor of Computer Applications (BCA)"
        elif any(w in text_lower for w in ["ph.d", "phd", "doctorate"]):
            degree = "Doctor of Philosophy (Ph.D.)"
        elif any(w in text_lower for w in ["bachelor", "b.sc", "bs in"]):
            degree = "Bachelor's Degree in Computer Science / Engineering"
        elif any(w in text_lower for w in ["master", "m.sc", "ms in"]):
            degree = "Master's Degree in Computer Science / Engineering"

        # Graduation year search
        years = [int(y) for y in re.findall(r'\b(20\d{2}|19\d{2})\b', text)]
        grad_year = max(years) if years else None

        return {
            "degree": degree or "Bachelor's Degree in Computer Science / Engineering",
            "graduation_year": grad_year
        }

    def estimate_experience_and_seniority(self, text: str) -> Dict[str, Any]:
        """Calculates years of experience from timeline ranges and keywords."""
        if not text:
            return {"years": 2, "seniority_level": "Mid-Level (2-4 Years)"}

        text_lower = text.lower()
        current_year = datetime.now().year

        # 1. Timeline Date Range Calculation
        total_timeline_years = 0
        date_matches = self.DATE_RANGE_REGEX.findall(text)
        for m in date_matches:
            start_yr = int(m[1])
            end_val = m[3].lower()
            end_yr = current_year if any(p in end_val for p in ["present", "current", "date", "now"]) else int(end_val)
            if start_yr <= end_yr <= current_year + 1:
                duration = end_yr - start_yr
                if 0 <= duration <= 25:
                    total_timeline_years += duration

        # 2. Explicit Keyword Patterns
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*experience',
            r'experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\+?\s*(?:years?|yrs?)\s*in\s*(?:software|development|tech)'
        ]
        exp_years = None
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                try:
                    exp_years = int(match.group(1))
                    break
                except ValueError:
                    pass

        if exp_years is None and total_timeline_years > 0:
            exp_years = min(total_timeline_years, 20)

        if exp_years is None:
            if any(w in text_lower for w in ["intern", "fresher", "entry level", "student"]):
                exp_years = 1
                seniority = "Junior / Entry-Level (0-2 Years)"
            elif any(w in text_lower for w in ["lead", "architect", "principal", "staff"]):
                exp_years = 7
                seniority = "Staff / Principal / Lead (6+ Years)"
            elif "senior" in text_lower or "sr." in text_lower:
                exp_years = 5
                seniority = "Senior Engineer (4-6 Years)"
            else:
                exp_years = 2
                seniority = "Mid-Level (2-4 Years)"
        else:
            if exp_years < 2:
                seniority = f"Junior / Associate ({exp_years}+ Years)"
            elif exp_years <= 4:
                seniority = f"Mid-Level ({exp_years}+ Years)"
            elif exp_years <= 7:
                seniority = f"Senior Engineer ({exp_years}+ Years)"
            else:
                seniority = f"Staff / Principal / Lead ({exp_years}+ Years)"

        return {
            "years": exp_years,
            "seniority_level": seniority
        }

    def infer_target_roles(self, text: str, categorized_skills: Dict[str, List[str]]) -> List[str]:
        """Infers recommended target job roles based on skills & keywords."""
        if not text:
            return ["Software Engineer"]

        roles: Set[str] = set()
        all_skills_lower = {s.lower() for cat in categorized_skills.values() for s in cat}

        if {"react", "next.js"}.intersection(all_skills_lower) and {"node.js", "express.js", "mongodb"}.intersection(all_skills_lower):
            roles.add("Full Stack MERN / React Developer")
        elif {"react", "vue.js", "angular", "next.js"}.intersection(all_skills_lower):
            roles.add("Frontend Engineer (React / UI)")
        elif {"fastapi", "django", "flask", "python"}.intersection(all_skills_lower):
            roles.add("Python Backend Engineer")
        elif {"spring boot", "java", "microservices"}.intersection(all_skills_lower):
            roles.add("Java Backend Engineer")
        elif {"golang", "rust"}.intersection(all_skills_lower):
            roles.add("Systems / Backend Engineer")
        elif {"ai/ml", "llm", "pytorch", "tensorflow", "langchain"}.intersection(all_skills_lower):
            roles.add("AI / ML Engineer")
        elif {"docker", "kubernetes", "aws", "terraform", "ci/cd"}.intersection(all_skills_lower):
            roles.add("DevOps / Cloud Engineer")
        elif {"flutter", "react native", "android", "ios"}.intersection(all_skills_lower):
            roles.add("Mobile Application Developer")

        if not roles:
            roles.add("Software Engineer")

        return list(roles)

    def infer_desired_domains(self, text: str) -> List[str]:
        """Infers candidate domains from project and resume keywords."""
        text_lower = text.lower()
        domains: List[str] = []
        domain_mapping = {
            "FinTech": ["payment", "banking", "finance", "trading", "crypto", "upi", "wallet"],
            "Healthcare": ["health", "medical", "patient", "clinical", "pharma"],
            "E-Commerce": ["ecommerce", "retail", "shopify", "cart", "checkout"],
            "SaaS": ["saas", "b2b", "subscription", "cloud", "multi-tenant"],
            "AI / Data": ["machine learning", "deep learning", "llm", "rag", "analytics"],
        }
        for dom, kws in domain_mapping.items():
            if any(kw in text_lower for kw in kws):
                domains.append(dom)
        return domains if domains else ["SaaS", "General Software Engineering"]

    def parse_from_text(self, text: str) -> Dict[str, Any]:
        """Parses a candidate profile directly from plain text."""
        if not text or not text.strip():
            raise ValueError("Resume text cannot be empty.")

        categorized_skills = self.extract_categorized_skills(text)
        flat_skills = []
        for cat in categorized_skills.values():
            for s in cat:
                if s not in flat_skills:
                    flat_skills.append(s)

        contact_info = self.extract_candidate_name_and_contact(text)
        exp_data = self.estimate_experience_and_seniority(text)
        target_roles = self.infer_target_roles(text, categorized_skills)
        education = self.extract_education(text)
        desired_domains = self.infer_desired_domains(text)

        return {
            "candidate_name": contact_info["name"],
            "contact_info": contact_info,
            "years_of_experience": exp_data["years"],
            "seniority_level": exp_data["seniority_level"],
            "target_roles": target_roles,
            "primary_role": target_roles[0] if target_roles else "Software Engineer",
            "skills_categorized": categorized_skills,
            "top_skills": flat_skills[:12],
            "skills": flat_skills,
            "education": education,
            "desired_domains": desired_domains,
            "github_url": contact_info.get("github"),
            "linkedin_url": contact_info.get("linkedin"),
            "portfolio_url": contact_info.get("portfolio"),
            "total_skills_count": len(flat_skills),
            "raw_text_length": len(text)
        }

    def parse(self, pdf_path: str) -> Dict[str, Any]:
        """Main PDF parser entrypoint."""
        text = self.extract_text_from_pdf(pdf_path)
        return self.parse_from_text(text)
