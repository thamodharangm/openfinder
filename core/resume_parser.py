import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import pypdf
import sys

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SKILL_TAXONOMY, COMMON_SKILLS


class ResumeParser:
    """
    Advanced Professional-Grade Resume Parser.
    Extracts categorized technical skills, seniority level, contact info, 
    key project indicators, and target job profiles.
    """

    def __init__(self):
        self.taxonomy = SKILL_TAXONOMY

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extracts text from PDF resume with multi-page handling."""
        file_path = Path(pdf_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Resume file not found at: {pdf_path}")

        extracted_text = []
        try:
            reader = pypdf.PdfReader(str(file_path))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    extracted_text.append(text)
        except Exception as e:
            raise RuntimeError(f"Failed to read PDF resume: {str(e)}")

        full_text = "\n".join(extracted_text)
        if not full_text.strip():
            raise ValueError("The PDF contains no readable text (it may be a scanned image).")

        return full_text

    def extract_categorized_skills(self, text: str) -> Dict[str, List[str]]:
        """Categorizes all matched technical skills into domains."""
        text_lower = text.lower()
        categorized = {}

        for category, skills in self.taxonomy.items():
            matched = set()
            for skill in skills:
                pattern = r'(?:\b|\W)' + re.escape(skill) + r'(?:\b|\W)'
                if re.search(pattern, text_lower):
                    matched.add(skill.title())
            if matched:
                categorized[category] = sorted(list(matched))

        return categorized

    def extract_candidate_name_and_contact(self, text: str) -> Dict[str, Optional[str]]:
        """Extracts email, phone, and candidate name if present."""
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        github_pattern = r'github\.com/([a-zA-Z0-9_-]+)'
        linkedin_pattern = r'linkedin\.com/in/([a-zA-Z0-9_-]+)'

        emails = re.findall(email_pattern, text)
        phones = re.findall(phone_pattern, text)
        github = re.search(github_pattern, text, re.IGNORECASE)
        linkedin = re.search(linkedin_pattern, text, re.IGNORECASE)

        # First non-empty line is often the candidate's name
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        candidate_name = lines[0] if lines and len(lines[0]) < 40 and not re.search(r'[@/:]', lines[0]) else "Candidate"

        return {
            "name": candidate_name,
            "email": emails[0] if emails else None,
            "phone": phones[0] if phones else None,
            "github": f"https://github.com/{github.group(1)}" if github else None,
            "linkedin": f"https://linkedin.com/in/{linkedin.group(1)}" if linkedin else None
        }

    def estimate_experience_and_seniority(self, text: str) -> Dict[str, Any]:
        """Calculates years of experience and assigns a seniority band."""
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*experience',
            r'experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\+?\s*(?:years?|yrs?)\s*in\s*software'
        ]
        text_lower = text.lower()
        exp_years = None
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                try:
                    exp_years = int(match.group(1))
                    break
                except ValueError:
                    pass

        if exp_years is None:
            # Fallback estimation based on graduation year or keyword density
            if "intern" in text_lower or "fresher" in text_lower or "entry level" in text_lower:
                exp_years = 1
                seniority = "Junior / Entry-Level (0-2 Years)"
            elif "lead" in text_lower or "architect" in text_lower or "principal" in text_lower:
                exp_years = 6
                seniority = "Senior / Lead (5+ Years)"
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
        text_lower = text.lower()
        roles = set()

        all_skills_lower = {s.lower() for cat in categorized_skills.values() for s in cat}

        if {"react", "react.js", "next.js"}.intersection(all_skills_lower) and {"node.js", "nodejs", "express"}.intersection(all_skills_lower):
            roles.add("Full Stack MERN / React Developer")
        elif {"react", "react.js", "vue", "angular"}.intersection(all_skills_lower):
            roles.add("Frontend Engineer (React / UI)")
        elif {"node.js", "django", "fastapi", "spring boot", "golang"}.intersection(all_skills_lower):
            roles.add("Backend Engineer")
        elif {"python"}.intersection(all_skills_lower) and {"machine learning", "pytorch", "tensorflow", "llm"}.intersection(all_skills_lower):
            roles.add("AI / ML Engineer")
        elif {"docker", "kubernetes", "aws", "terraform"}.intersection(all_skills_lower):
            roles.add("DevOps / Cloud Engineer")
        elif {"flutter", "react native", "ios", "android"}.intersection(all_skills_lower):
            roles.add("Mobile App Developer")

        if not roles:
            roles.add("Software Engineer")

        return list(roles)

    def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        Main parser entrypoint.
        """
        text = self.extract_text_from_pdf(pdf_path)
        categorized_skills = self.extract_categorized_skills(text)
        flat_skills = [s for cat in categorized_skills.values() for s in cat]
        contact_info = self.extract_candidate_name_and_contact(text)
        exp_data = self.estimate_experience_and_seniority(text)
        target_roles = self.infer_target_roles(text, categorized_skills)

        return {
            "candidate_name": contact_info["name"],
            "contact_info": contact_info,
            "years_of_experience": exp_data["years"],
            "seniority_level": exp_data["seniority_level"],
            "target_roles": target_roles,
            "primary_role": target_roles[0] if target_roles else "Software Engineer",
            "skills_categorized": categorized_skills,
            "top_skills": flat_skills[:12],
            "total_skills_count": len(flat_skills),
            "raw_text_length": len(text)
        }
