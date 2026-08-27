import re
from typing import Dict, List, Any, Optional


class PostParser:
    """
    Parses raw text from LinkedIn posts to extract emails, application links, 
    recruiter contact methods, skills mentioned, and role titles.
    """

    EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'

    @staticmethod
    def extract_emails(text: str) -> List[str]:
        """Extracts valid email addresses from text."""
        emails = re.findall(PostParser.EMAIL_REGEX, text)
        # Filter out common false positives like image extensions or generic domains if any
        valid = [e for e in set(emails) if not e.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        return valid

    @staticmethod
    def extract_links(text: str) -> List[str]:
        """Extracts application links, google forms, career portal links."""
        urls = re.findall(PostParser.URL_REGEX, text)
        apply_links = []
        for url in urls:
            # Clean trailing punctuation
            url = url.rstrip('.,;:)')
            if any(domain in url for domain in ['forms.gle', 'docs.google.com/forms', 'linkedin.com', 'notion.site', 'lever.co', 'greenhouse.io', 'workable.com']):
                apply_links.append(url)
            elif "apply" in url or "career" in url or "jobs" in url:
                apply_links.append(url)
        return list(set(apply_links))

    @staticmethod
    def extract_skills_mentioned(text: str, skills_taxonomy: List[str]) -> List[str]:
        """Finds which known technical skills are required in the post."""
        text_lower = text.lower()
        skills = set()
        for skill in skills_taxonomy:
            pattern = r'(?:\b|\W)' + re.escape(skill) + r'(?:\b|\W)'
            if re.search(pattern, text_lower):
                skills.add(skill.title())
        return sorted(list(skills))

    @staticmethod
    def extract_experience_required(text: str) -> Optional[str]:
        """Finds experience requirements in the post (e.g. 2-4 years, 0-1 years)."""
        patterns = [
            r'(\d+\s*(?:to|-)\s*\d+\+?\s*(?:years?|yrs?))',
            r'(\d+\+?\s*(?:years?|yrs?)\s*(?:of)?\s*(?:exp|experience)?)',
            r'freshers?\s*(?:welcome|can apply)?',
            r'internship'
        ]
        text_lower = text.lower()
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                return match.group(0).strip()
        return "Not explicitly specified"

    @classmethod
    def parse(cls, post_data: Dict[str, Any], skills_taxonomy: List[str]) -> Dict[str, Any]:
        """
        Enriches a raw post dictionary with parsed metadata.
        """
        content = post_data.get("snippet", "") + "\n" + post_data.get("title", "")
        emails = cls.extract_emails(content)
        apply_links = cls.extract_links(content)
        skills = cls.extract_skills_mentioned(content, skills_taxonomy)
        exp = cls.extract_experience_required(content)

        return {
            "title": post_data.get("title", "LinkedIn Hiring Post"),
            "post_url": post_data.get("link", ""),
            "author": post_data.get("author", "LinkedIn User"),
            "published_time": post_data.get("published_time", "Recent"),
            "contact_emails": emails,
            "application_links": apply_links,
            "required_skills": skills,
            "experience_required": exp,
            "raw_snippet": content.strip()
        }
