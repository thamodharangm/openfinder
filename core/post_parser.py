import re
from typing import Dict, List, Any, Optional


class PostParser:
    """
    Advanced Post Parser extracting Company, Work Mode, Compensation, 
    Recruiter Profiles, Experience Range, and Application Links.
    """

    EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'

    @staticmethod
    def extract_work_mode(text: str) -> str:
        """Determines Remote, Hybrid, or On-Site mode."""
        text_lower = text.lower()
        if "remote" in text_lower or "wfh" in text_lower or "work from home" in text_lower:
            return "🏡 Remote / WFH"
        elif "hybrid" in text_lower:
            return "🏢 Hybrid"
        elif "on-site" in text_lower or "onsite" in text_lower or "office" in text_lower:
            return "📍 On-Site"
        return "📍 On-Site / Unspecified"

    @staticmethod
    def extract_salary_or_ctc(text: str) -> Optional[str]:
        """Detects salary / CTC ranges (e.g. 10-15 LPA, $80k-$120k)."""
        patterns = [
            r'(\d+\s*(?:to|-)\s*\d+\s*(?:lpa|lakhs?|lac|k|inr))',
            r'(?:ctc|salary|package)\s*:\s*([^\n,]+)',
            r'(\$\d+k?\s*(?:to|-)\s*\$?\d+k?)'
        ]
        text_lower = text.lower()
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                return match.group(0).strip().title()
        return None

    @staticmethod
    def extract_company_name(title: str, text: str) -> str:
        """Extracts company name from title or snippet."""
        # Check patterns like 'React Developer at Google' or 'Modefin is hiring'
        patterns = [
            r'(?:at|@)\s+([A-Z][a-zA-Z0-9&]+)',
            r'([A-Z][a-zA-Z0-9&]+)\s+(?:is hiring|hiring for)',
            r'Company\s*:\s*([A-Za-z0-9& ]+)'
        ]
        combined = title + " " + text
        for pat in patterns:
            match = re.search(pat, combined)
            if match:
                comp = match.group(1).strip()
                if comp.lower() not in ["we", "hiring", "immediate", "looking", "urgent", "the", "our", "linkedin"]:
                    return comp
        
        # Fallback to cleaning from title
        clean_title = re.sub(r'#\S+', '', title)
        clean_title = re.sub(r'\.{2,}', '', clean_title)
        
        for sep in ['—', '|', '-']:
            parts = clean_title.split(sep)
            for p in parts:
                p_clean = re.sub(r'[^\w\s&]', '', p).strip()
                if 3 <= len(p_clean) <= 30 and p_clean.lower() not in ["linkedin", "hiring", "job opening", "job alert", "urgent requirement"]:
                    return p_clean

        return "Hiring Company / Recruiter"

    @classmethod
    def parse(cls, post_data: Dict[str, Any], skills_taxonomy: List[str]) -> Dict[str, Any]:
        """Enriches raw post dictionary with structured metadata."""
        content = post_data.get("snippet", "") + "\n" + post_data.get("title", "")
        title = post_data.get("title", "LinkedIn Hiring Opportunity")
        
        emails = re.findall(cls.EMAIL_REGEX, content)
        valid_emails = [e for e in set(emails) if not e.endswith(('.png', '.jpg', '.jpeg', '.gif'))]

        urls = re.findall(cls.URL_REGEX, content)
        apply_links = [u.rstrip('.,;:)') for u in urls if any(d in u for d in ['forms.gle', 'docs.google.com', 'lever.co', 'greenhouse.io', 'workable.com'])]

        # Matched skills
        text_lower = content.lower()
        skills = {s.title() for s in skills_taxonomy if re.search(r'(?:\b|\W)' + re.escape(s) + r'(?:\b|\W)', text_lower)}

        # Experience
        exp_patterns = [
            r'(\d+\s*(?:to|-)\s*\d+\+?\s*(?:years?|yrs?))',
            r'(\d+\+?\s*(?:years?|yrs?)\s*(?:of)?\s*(?:exp|experience)?)',
            r'freshers?\s*(?:welcome|can apply)?'
        ]
        exp_req = "1-3 Years (Estimated)"
        for pat in exp_patterns:
            match = re.search(pat, text_lower)
            if match:
                exp_req = match.group(0).strip()
                break

        company = cls.extract_company_name(title, content)
        work_mode = cls.extract_work_mode(content)
        salary = cls.extract_salary_or_ctc(content)

        return {
            "title": title,
            "company": company,
            "work_mode": work_mode,
            "salary_range": salary or "Competitive / Not Disclosed",
            "experience_required": exp_req,
            "required_skills": sorted(list(skills)),
            "contact_emails": valid_emails,
            "application_links": apply_links,
            "post_url": post_data.get("link", ""),
            "raw_snippet": content.strip()
        }
