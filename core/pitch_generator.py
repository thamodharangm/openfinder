import urllib.parse
from typing import Dict, Any, Optional, List


class OutreachPitchGenerator:
    """
    Generates high-converting, professional cold outreach message suites
    specifically tailored to recruiter personas and candidate strengths,
    with 1-click 'Open in Mail' (mailto / Gmail deep link) actions.
    """

    @classmethod
    def generate_all(cls, *args, **kwargs) -> Dict[str, Any]:
        """Alias for generate_suite."""
        return cls.generate_suite(*args, **kwargs)

    @staticmethod
    def generate_suite(
        job_title: str,
        company_name: str = "the Hiring Team",
        matched_skills: Optional[List[str]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        recipient_name: Optional[str] = None,
        recipient_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates 4 tailored outreach message variations plus 1-click email launch links.
        """
        matched_skills = matched_skills or ["Full Stack Development"]
        skills_str = ", ".join(matched_skills[:3]) if matched_skills else "modern software engineering"
        greeting_name = recipient_name.split()[0] if (recipient_name and recipient_name.lower() not in ["hiring manager", "recruiter", "hiring manager / recruiter"]) else "there"

        # 1. LinkedIn Connection Note (< 300 characters limit)
        connection_note = (
            f"Hi {greeting_name}! Noticed your opening for {job_title} at {company_name}. "
            f"I have {candidate_exp_years}+ yrs experience specializing in {skills_str}. "
            f"Would love to connect & share my resume!"
        )
        if len(connection_note) > 295:
            connection_note = connection_note[:292] + "..."

        # 2. LinkedIn InMail / Detailed DM
        linkedin_dm = (
            f"Hi {greeting_name},\n\n"
            f"I saw your recent LinkedIn hiring post regarding the {job_title} opportunity at {company_name}. "
            f"With {candidate_exp_years}+ years of hands-on experience delivering scalable applications with {skills_str}, "
            f"my background closely matches what your team is building.\n\n"
            f"A few quick highlights of my background:\n"
            f"• Core Stack: {skills_str}\n"
            f"• Strong focus on clean code, performance optimization, and agile delivery.\n\n"
            f"I've attached my resume and would welcome a brief 5-minute chat to see how I can add value to {company_name}.\n\n"
            f"Best regards,\n{candidate_name}"
        )

        # 3. Formal Executive Cover Email
        email_subject = f"Application: {job_title} - {candidate_name} ({skills_str})"
        email_body = (
            f"Dear {recipient_name or 'Hiring Team'},\n\n"
            f"I am writing to express my enthusiastic interest in the {job_title} opening at {company_name} as shared on LinkedIn.\n\n"
            f"Having worked extensively with {skills_str} for over {candidate_exp_years}+ years, I have successfully engineered "
            f"reliable, production-grade solutions with a strong emphasis on scalable architecture and clean code.\n\n"
            f"Key strengths I bring to {company_name}:\n"
            f"• Proficiency across {skills_str} and modern software best practices.\n"
            f"• Track record of rapid problem solving, collaboration, and high-impact delivery.\n\n"
            f"Please find my resume attached for your consideration. I look forward to the opportunity to discuss my qualifications.\n\n"
            f"Sincerely,\n{candidate_name}\n[Your Phone Number]\n[LinkedIn Profile Link]"
        )

        formal_email = f"Subject: {email_subject}\n\n{email_body}"

        # 4. 1-Click Deep Links (mailto & Gmail Web)
        to_email = (recipient_email or "").strip()
        encoded_subject = urllib.parse.quote(email_subject)
        encoded_body = urllib.parse.quote(email_body)

        mailto_link = f"mailto:{to_email}?subject={encoded_subject}&body={encoded_body}"
        gmail_link = f"https://mail.google.com/mail/?view=cm&fs=1&to={to_email}&su={encoded_subject}&body={encoded_body}"

        open_in_mail_button = f"[✉️ Open in Mail App]({mailto_link})"
        open_in_gmail_button = f"[🌐 Open in Gmail Web]({gmail_link})"

        # 5. Day-3 Follow-Up Note
        follow_up = (
            f"Hi {greeting_name},\n\n"
            f"I hope you are having a productive week! Following up on my application for the {job_title} position at {company_name}. "
            f"I remain very interested in contributing with my {skills_str} expertise. "
            f"Please let me know if you need any additional portfolio or project details.\n\n"
            f"Best,\n{candidate_name}"
        )

        return {
            "connection_note": connection_note,
            "linkedin_connection_note": connection_note,
            "linkedin_connection_note_300_chars": connection_note,
            "linkedin_dm": linkedin_dm,
            "linkedin_inmail_dm": linkedin_dm,
            "formal_cover_email": formal_email,
            "email_subject": email_subject,
            "email_body": email_body,
            "recipient_email": to_email,
            "mailto_url": mailto_link,
            "gmail_web_url": gmail_link,
            "open_in_mail_button": open_in_mail_button,
            "open_in_gmail_button": open_in_gmail_button,
            "day3_follow_up": follow_up
        }
