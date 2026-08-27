import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import pypdf
import sys

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS


class ResumeParser:
    """
    Parses PDF resumes, extracts text, identifies key technical skills, 
    estimates experience level, and infers target job search roles.
    """

    def __init__(self, skills_taxonomy: Optional[List[str]] = None):
        self.skills_taxonomy = skills_taxonomy or COMMON_SKILLS

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extracts all clean text from a given PDF file."""
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
            raise ValueError("The provided PDF appears to be empty or scanned images without readable text.")

        return full_text

    def extract_skills(self, text: str) -> List[str]:
        """Extracts matched skills from taxonomy."""
        text_lower = text.lower()
        matched_skills = set()

        for skill in self.skills_taxonomy:
            # Word boundary check or exact matching
            pattern = r'(?:\b|\W)' + re.escape(skill) + r'(?:\b|\W)'
            if re.search(pattern, text_lower):
                matched_skills.add(skill.title())

        return sorted(list(matched_skills))

    def estimate_experience_years(self, text: str) -> Optional[int]:
        """Estimates total years of experience using regex patterns."""
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of)?\s*experience',
            r'experience\s*:\s*(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\s*(?:years?|yrs?)\s*in\s*software'
        ]
        text_lower = text.lower()
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass
        return None

    def infer_target_roles(self, text: str, matched_skills: List[str]) -> List[str]:
        """Infers suitable job titles based on resume keywords & skills."""
        text_lower = text.lower()
        roles = set()

        role_keywords = {
            "Full Stack Developer": ["full stack", "fullstack", "mern", "mean"],
            "Frontend Developer": ["frontend", "front-end", "react", "vue", "angular", "next.js", "tailwind"],
            "Backend Developer": ["backend", "back-end", "node.js", "django", "fastapi", "spring boot", "golang"],
            "Python Developer": ["python developer", "python engineer", "django", "fastapi"],
            "DevOps Engineer": ["devops", "kubernetes", "docker", "terraform", "ci/cd", "aws", "gcp"],
            "Mobile App Developer": ["react native", "flutter", "ios", "android", "swift", "kotlin"],
            "Data Scientist / AI Engineer": ["machine learning", "deep learning", "nlp", "llm", "data scientist", "pytorch"],
            "QA / Test Automation Engineer": ["qa engineer", "selenium", "cypress", "automation tester", "playwright"]
        }

        for role_name, kws in role_keywords.items():
            for kw in kws:
                if kw in text_lower:
                    roles.add(role_name)
                    break

        if not roles:
            # Fallback if no specific role title is matched
            if "React" in matched_skills or "Javascript" in matched_skills:
                roles.add("Frontend / Fullstack Developer")
            elif "Python" in matched_skills:
                roles.add("Python Developer")
            else:
                roles.add("Software Engineer")

        return list(roles)

    def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        Main entrypoint: parses PDF, extracts text, skills, estimated experience,
        and target roles.
        """
        text = self.extract_text_from_pdf(pdf_path)
        skills = self.extract_skills(text)
        exp_years = self.estimate_experience_years(text)
        target_roles = self.infer_target_roles(text, skills)

        return {
            "file_path": str(Path(pdf_path).resolve()),
            "total_character_count": len(text),
            "estimated_experience_years": exp_years or "Not explicitly specified (Estimated Entry/Mid)",
            "matched_skills": skills,
            "top_skills": skills[:10],
            "inferred_target_roles": target_roles,
            "raw_text_snippet": text[:500] + "..." if len(text) > 500 else text
        }
