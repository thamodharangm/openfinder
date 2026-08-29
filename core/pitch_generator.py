"""
core/pitch_generator.py
=======================
Production-grade Cold Outreach & Recruiter Pitch Generation Engine.

Features:
- Multi-channel pitch suite:
  1. LinkedIn Connection Request Note (<300 chars, strictly length-validated).
  2. LinkedIn InMail / Recruiter Direct Message (Value-first bullet points).
  3. Executive Formal Cover Email (Complete subject + structured body).
  4. Founder / Early-Stage Startup Pitch (High velocity, product-impact oriented).
  5. Employee Internal Referral Request.
  6. Day-3 & Day-7 Polite Follow-up sequences.
- 1-Click Composer Deep Links (Native mailto, Gmail Web, and Outlook 365 Web).
- Smart recipient salutation and company name normalization.
- Seamless injection of candidate portfolio, GitHub, and contact coordinates.
"""

import re
from typing import Any, Dict, List, Optional, Union
import urllib.parse


class OutreachPitchGenerator:
    """
    Generates high-converting, professional cold outreach message suites
    specifically tailored to recruiter personas and candidate strengths,
    with 1-click 'Open in Mail' (mailto, Gmail, Outlook deep links) actions.
    """

    @classmethod
    def generate_all(cls, *args, **kwargs) -> Dict[str, Any]:
        """Alias for generate_suite."""
        return cls.generate_suite(*args, **kwargs)

    @classmethod
    def _clean_greeting_name(cls, recipient_name: Optional[str]) -> str:
        """Extracts a clean first name or returns a generic greeting."""
        if not recipient_name or not isinstance(recipient_name, str):
            return "there"

        clean = recipient_name.strip()
        # Filter out generic titles
        if clean.lower() in [
            "hiring manager", "recruiter", "talent acquisition", "hr", "hiring team",
            "hr manager", "talent lead", "talent partner", "admin", "recruitment", "team"
        ]:
            return "there"

        # Strip titles/credentials like (She/Her), PhD, etc.
        clean = re.sub(r'[\(\[].*?[\)\]]', '', clean).strip()
        clean = re.sub(r',\s*(?:phd|mba|pmp|recruiter|hr|talent).*$', '', clean, flags=re.IGNORECASE).strip()

        first_name = clean.split()[0].title() if clean else "there"
        return first_name if len(first_name) >= 2 else "there"

    @classmethod
    def _clean_company_name(cls, company_name: Optional[str]) -> str:
        """Cleans and formats company name."""
        if not company_name or not isinstance(company_name, str):
            return "your team"
        clean = company_name.strip()
        if clean.lower() in ["the hiring team", "hiring team", "unknown", "confidential"]:
            return "your team"
        return clean

    @classmethod
    def generate_suite(
        cls,
        job_title: str = "Software Engineer",
        company_name: str = "your team",
        matched_skills: Optional[Union[List[str], str]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        recipient_name: Optional[str] = None,
        recipient_email: Optional[str] = None,
        candidate_phone: Optional[str] = None,
        candidate_linkedin: Optional[str] = None,
        candidate_portfolio: Optional[str] = None,
        candidate_github: Optional[str] = None,
        key_achievement: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates an exhaustive suite of personalized outreach messages and 1-click email deep links.
        """
        # 1. Normalize parameters
        job_title = (job_title or "Software Engineer").strip()
        company_clean = cls._clean_company_name(company_name)
        greeting_name = cls._clean_greeting_name(recipient_name)
        formal_recipient = recipient_name.strip().title() if (recipient_name and cls._clean_greeting_name(recipient_name) != "there") else "Hiring Team"

        if isinstance(matched_skills, str):
            skills_list = [s.strip() for s in matched_skills.split(",") if s.strip()]
        elif isinstance(matched_skills, list):
            skills_list = [str(s).strip() for s in matched_skills if str(s).strip()]
        else:
            skills_list = []

        if not skills_list:
            skills_list = ["Full Stack Development", "System Design", "Cloud Services"]

        skills_str = ", ".join(skills_list[:3])
        primary_skill = skills_list[0] if skills_list else "Software Engineering"

        # 2. LinkedIn Connection Note (Strictly capped < 300 chars)
        connection_note = (
            f"Hi {greeting_name}! Noticed your opening for {job_title} at {company_clean}. "
            f"I bring {candidate_exp_years}+ yrs of hands-on experience in {skills_str}. "
            f"Would love to connect & share my resume!"
        )
        if len(connection_note) > 295:
            connection_note = (
                f"Hi {greeting_name}! Saw your {job_title} opening at {company_clean}. "
                f"I have {candidate_exp_years}+ yrs exp in {skills_str}. "
                f"Would love to connect!"
            )
        if len(connection_note) > 295:
            connection_note = connection_note[:292] + "..."

        # 3. LinkedIn InMail / Detailed DM
        linkedin_dm = (
            f"Hi {greeting_name},\n\n"
            f"I came across your recent hiring post regarding the {job_title} opportunity at {company_clean}. "
            f"With {candidate_exp_years}+ years of experience building reliable applications with {skills_str}, "
            f"my background strongly aligns with what your team is looking for.\n\n"
            f"Key highlights of my experience:\n"
            f"• Core Stack: {skills_str}\n"
            f"• Track record in clean code, performance optimization, and scalable architectures.\n"
        )
        if key_achievement:
            linkedin_dm += f"• Notable Impact: {key_achievement}\n"
        linkedin_dm += (
            f"\nI would welcome a brief 5-minute chat to discuss how I can contribute to {company_clean}'s engineering goals.\n\n"
            f"Best regards,\n{candidate_name}"
        )

        # 4. Founder / Startup Direct Pitch
        founder_pitch = (
            f"Hi {greeting_name},\n\n"
            f"Loved what you're building at {company_clean}! Saw your update for a {job_title} and wanted to reach out directly. "
            f"I specialize in {skills_str} and thrive in fast-paced startup environments where shipping high-quality features quickly is essential.\n\n"
            f"I have {candidate_exp_years}+ years of experience owning features from design to deployment.\n\n"
            f"Would you be open to a quick 5-minute intro call this week?\n\n"
            f"Cheers,\n{candidate_name}"
        )

        # 5. Internal Referral Request Pitch
        referral_pitch = (
            f"Hi {greeting_name},\n\n"
            f"Hope you are having a great week! I came across the {job_title} opening at {company_clean} and was really impressed by your team's work. "
            f"With {candidate_exp_years}+ years in {skills_str}, I believe my skillset would be a great fit.\n\n"
            f"Would you be open to reviewing my resume or passing along an internal referral? Happy to share my portfolio.\n\n"
            f"Thanks a lot for your time!\n{candidate_name}"
        )

        # 6. Formal Executive Cover Email
        email_subject = f"Application: {job_title} - {candidate_name} ({primary_skill})"
        email_signature_parts = [
            f"Sincerely,\n{candidate_name}",
            candidate_phone if candidate_phone else "[Your Phone Number]",
            f"LinkedIn: {candidate_linkedin}" if candidate_linkedin else "[LinkedIn Profile Link]",
        ]
        if candidate_portfolio:
            email_signature_parts.append(f"Portfolio: {candidate_portfolio}")
        if candidate_github:
            email_signature_parts.append(f"GitHub: {candidate_github}")

        signature_block = "\n".join(email_signature_parts)

        email_body = (
            f"Dear {formal_recipient},\n\n"
            f"I am writing to express my strong interest in the {job_title} role at {company_clean} as shared on LinkedIn.\n\n"
            f"With over {candidate_exp_years}+ years of professional experience specializing in {skills_str}, "
            f"I have delivered production-grade, scalable solutions with a consistent focus on code quality, performance, and agile delivery.\n\n"
            f"Core strengths I would bring to {company_clean}:\n"
            f"• Deep technical proficiency across {skills_str}.\n"
            f"• Strong experience designing maintainable backend architectures and responsive user experiences.\n"
            f"• Proven ability to collaborate cross-functionally and deliver impactful results under tight deadlines.\n\n"
            f"Please find my resume attached for your review. I would welcome the opportunity to discuss how my qualifications "
            f"align with your team's upcoming milestones.\n\n"
            f"{signature_block}"
        )

        formal_email = f"Subject: {email_subject}\n\n{email_body}"

        # 7. Day-3 & Day-7 Follow-up Sequences
        day3_follow_up = (
            f"Hi {greeting_name},\n\n"
            f"Hope you are having a great week! Following up on my application for the {job_title} position at {company_clean}. "
            f"I remain very enthusiastic about the opportunity to contribute with my {skills_str} background.\n\n"
            f"Please let me know if you need any additional project details or code samples.\n\n"
            f"Best regards,\n{candidate_name}"
        )

        day7_follow_up = (
            f"Hi {greeting_name},\n\n"
            f"I wanted to send a quick final note regarding the {job_title} opening at {company_clean}. "
            f"I understand you have a busy schedule. If the position is still open, I would be thrilled to connect for 5 minutes.\n\n"
            f"Thank you again for your time and consideration!\n\n"
            f"Best,\n{candidate_name}"
        )

        # 8. 1-Click Email Deep Links (Mailto, Gmail, Outlook)
        to_email = (recipient_email or "").strip()
        encoded_subject = urllib.parse.quote(email_subject)
        encoded_body = urllib.parse.quote(email_body)

        mailto_link = f"mailto:{to_email}?subject={encoded_subject}&body={encoded_body}"
        gmail_link = f"https://mail.google.com/mail/?view=cm&fs=1&to={to_email}&su={encoded_subject}&body={encoded_body}"
        outlook_link = f"https://outlook.office.com/mail/deeplink/compose?to={to_email}&subject={encoded_subject}&body={encoded_body}"

        open_in_mail_button = f"[✉️ Open in Mail App]({mailto_link})"
        open_in_gmail_button = f"[🌐 Open in Gmail Web]({gmail_link})"
        open_in_outlook_button = f"[💼 Open in Outlook Web]({outlook_link})"

        return {
            "connection_note": connection_note,
            "linkedin_connection_note": connection_note,
            "linkedin_connection_note_300_chars": connection_note,
            "linkedin_dm": linkedin_dm,
            "linkedin_inmail_dm": linkedin_dm,
            "founder_pitch": founder_pitch,
            "referral_pitch": referral_pitch,
            "formal_cover_email": formal_email,
            "email_subject": email_subject,
            "email_body": email_body,
            "recipient_email": to_email,
            "mailto_url": mailto_link,
            "gmail_web_url": gmail_link,
            "outlook_web_url": outlook_link,
            "open_in_mail_button": open_in_mail_button,
            "open_in_gmail_button": open_in_gmail_button,
            "open_in_outlook_button": open_in_outlook_button,
            "day3_follow_up": day3_follow_up,
            "day7_follow_up": day7_follow_up
        }
