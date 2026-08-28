import re
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMMON_SKILLS, ErrorCodes, MAX_POST_PAYLOAD_BYTES
from core.linkedin_urls import is_valid_linkedin_post_url, normalize_linkedin_post_url
from core.time_utils import (
    parse_timestamp,
    calculate_age,
    is_within_window,
    get_max_age_minutes,
    FRESHNESS_WINDOWS
)
from core.hiring_intent import (
    JobRoleExtractor,
    HiringIntentClassifier,
    RoleRelevanceMatcher,
    LocationRelevanceMatcher,
    ExperienceRelevanceMatcher,
    QualityScorer
)
from core.pitch_generator import OutreachPitchGenerator
from core.matcher import JobMatcher


class LinkedInPostExtractor:
    """
    High-Performance Asynchronous & Synchronous Post Extraction Engine.
    Extracts structured hiring intelligence ONLY from genuine LinkedIn /posts/ URLs,
    validates exact publication time down to the minute, and classifies directional hiring intent.
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

    TIMEOUT_CONFIG = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)
    MAX_CONCURRENCY = 5

    EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    PHONE_REGEX = r"(?:\+91[\-\s]?)?[6789]\d{9}"

    @staticmethod
    def is_valid_post_url(url: str) -> bool:
        return is_valid_linkedin_post_url(url)

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
                normalized.add(skill.strip().title())
        return sorted(normalized)

    @staticmethod
    def extract_company(text: str, emails: List[str], author: str) -> str:
        for email in emails:
            try:
                domain = email.split("@")[1].lower()
                company_part = domain.split(".")[0]
                if company_part not in [
                    "gmail",
                    "yahoo",
                    "outlook",
                    "hotmail",
                    "protonmail",
                    "icloud",
                    "mail",
                    "rediffmail",
                ]:
                    return company_part.capitalize()
            except Exception:
                pass

        GENERIC_BLACKLIST = [
            "offer", "ux designers", "implement", "collaborate", "hiring", "immediate",
            "team", "experienced", "candidates", "developer", "engineer", "designers",
            "jobs", "process", "recruitment", "recruiting", "profile"
        ]

        if author and author not in ["Hiring Manager / Recruiter", "LinkedIn Member", "Recruiter"]:
            match = re.search(r"(?:at|@)\s+([A-Za-z0-9\s&.-]+)", author)
            if match:
                clean_name = match.group(1).strip()
                if len(clean_name) > 2 and not any(b in clean_name.lower() for b in GENERIC_BLACKLIST):
                    return clean_name.title()

        patterns = [
            r"(?:hiring|looking\s+for|join|at|with)\s+(?:our\s+team\s+at\s+)?([A-Z][A-Za-z0-9&.\s]{2,25}(?:Pvt|Ltd|Inc|LLC|Technologies|Solutions|Software|Labs|Studio|Media|Corp|Systems|AI|Health)?)",
            r"(?:company|organization)\s*:\s*([A-Za-z0-9&.\s]{2,25})",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                extracted = m.group(1).strip()
                extracted = re.sub(
                    r"\b(we|are|is|a|an|the|looking|for|candidates|immediate|experienced)\b",
                    "",
                    extracted,
                    flags=re.IGNORECASE,
                ).strip()
                if len(extracted) >= 3 and not any(
                    x in extracted.lower()
                    for x in GENERIC_BLACKLIST
                ):
                    return extracted.title()

        return "Hiring Team"

    @staticmethod
    def extract_location(text: str) -> str:
        KNOWN_LOCATIONS = [
            "Bangalore", "Bengaluru", "Chennai", "Hyderabad", "Pune", "Mumbai",
            "Delhi", "Gurgaon", "Gurugram", "Noida", "Coimbatore", "Kochi",
            "Trivandrum", "Vadodara", "Ahmedabad", "Kolkata", "Jaipur", "Chandigarh",
            "Indore", "Remote", "Work From Home", "Hybrid", "India"
        ]
        text_lower = text.lower()
        for loc in KNOWN_LOCATIONS:
            if re.search(r"(?:\b|\W)" + re.escape(loc.lower()) + r"(?:\b|\W)", text_lower):
                if loc.lower() in ["bangalore", "bengaluru"]:
                    return "Bangalore"
                elif loc.lower() in ["gurgaon", "gurugram"]:
                    return "Gurgaon (Delhi-NCR)"
                elif loc.lower() in ["work from home", "remote"]:
                    return "Remote"
                return loc

        loc_match = re.search(r"(?:📍\s*location|location|city)\s*:\s*([A-Za-z\s,]+)", text, re.IGNORECASE)
        if loc_match:
            cand = loc_match.group(1).strip().split("\n")[0].split(",")[0].strip()
            if len(cand) > 2 and cand.lower() not in ["in", "at", "as", "the", "for"]:
                return cand.title()

        return "Unspecified / Remote"

    @classmethod
    def _parse_html_to_post_data(
        cls,
        html_text: str,
        norm_url: str,
        skills_taxonomy: List[str],
        max_age_minutes: Optional[int],
        target_role: Optional[str],
        target_location: Optional[str],
        candidate_name: str,
        candidate_exp_years: int,
        cand_skills: List[str],
    ) -> Dict[str, Any]:
        """
        Pure deterministic parsing logic on downloaded HTML.
        """
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Timestamp Extraction & Freshness Verification
        published_at = parse_timestamp(soup_or_str=soup, url=norm_url)
        if published_at is None:
            return {
                "status": "rejected",
                "reason": "PUBLISHED_TIME_UNVERIFIED",
                "error": "Could not verify the post publication timestamp. Rejected for freshness safety.",
            }

        age_info = calculate_age(published_at)
        if not age_info["is_valid"]:
            return {
                "status": "rejected",
                "reason": "INVALID_TIMESTAMP",
                "published_at": published_at.isoformat(),
                "error": "Post has an invalid or future timestamp.",
            }

        if max_age_minutes is not None:
            if not is_within_window(published_at, max_age_minutes):
                return {
                    "status": "rejected",
                    "reason": "OLDER_THAN_REQUESTED_WINDOW",
                    "published_at": published_at.isoformat(),
                    "age_minutes": age_info["age_minutes"],
                    "max_age_minutes": max_age_minutes,
                    "error": f"Post age ({age_info['age_minutes']}m) exceeds requested freshness window ({max_age_minutes}m).",
                }

        # 2. Content Metadata Extraction
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")

        title_str = og_title.get("content", "").strip() if og_title else ""
        full_text = og_desc.get("content", "").strip() if og_desc else soup.get_text(" ", strip=True)

        author = "Hiring Manager / Recruiter"
        m_auth = re.search(r"^([^:|]+?)\s+on\s+LinkedIn", title_str, re.IGNORECASE)
        if m_auth:
            clean_a = m_auth.group(1).strip()
            if len(clean_a) > 2 and not any(x in clean_a.lower() for x in ["comment", "like", "post", "share", "reaction"]):
                author = clean_a.title()
        elif "|" in title_str:
            parts = [p.strip() for p in title_str.split("|") if p.strip()]
            for p in parts:
                if not re.search(r"\d+\s*(?:comment|like|reaction|repost)", p, re.IGNORECASE):
                    sub_m = re.search(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", p)
                    if sub_m:
                        author = sub_m.group(1).strip()
                        break

        # 3. Hiring Intent Classification & Spam Filter
        intent_res = HiringIntentClassifier.classify(
            text=full_text,
            author_headline=author,
            author_name=author
        )

        if intent_res.get("is_spam"):
            return {
                "status": "rejected",
                "reason": "SPAM_OR_BAIT",
                "signals": intent_res.get("signals", []),
                "error": "Post identified as spam, promotional engagement-bait, or non-job content."
            }

        if intent_res.get("intent") == "JOB_SEEKER":
            return {
                "status": "rejected",
                "reason": "JOB_SEEKER_POST",
                "intent": "JOB_SEEKER",
                "author_type": intent_res.get("author_type", "JOB_SEEKER"),
                "confidence": intent_res.get("confidence", 0.0),
                "signals": intent_res.get("signals", []),
                "error": "Post is from a job seeker / candidate looking for opportunities, not a hiring recruiter."
            }

        if intent_res.get("intent") == "NON_HIRING":
            return {
                "status": "rejected",
                "reason": "NON_HIRING_CONTENT",
                "intent": "NON_HIRING",
                "confidence": intent_res.get("confidence", 0.0),
                "signals": intent_res.get("signals", []),
                "error": "Post is non-hiring content (advice, tutorial, webinar, or discussion)."
            }

        # Emails & Phones
        emails = sorted(set(re.findall(cls.EMAIL_REGEX, full_text)))
        phones = sorted(set(re.findall(cls.PHONE_REGEX, full_text)))

        # Skills
        text_lower = (full_text + " " + title_str).lower()
        raw_skills = []
        for skill in skills_taxonomy:
            if re.search(r"(?:\b|\W)" + re.escape(skill.lower()) + r"(?:\b|\W)", text_lower):
                raw_skills.append(skill)
        skills = cls.normalize_skills(raw_skills)

        # Company & Location
        company = cls.extract_company(full_text, emails, author)
        location = cls.extract_location(full_text)

        # Roles
        extracted_roles = JobRoleExtractor.extract_roles(full_text, default_title=title_str.split("|")[0].strip() if title_str else "Software Engineer")
        role = extracted_roles[0] if extracted_roles else "Software Engineer"

        # 4. Relevance Scoring & Post Quality
        resolved_target_role = target_role or role
        resolved_target_loc = target_location or "India"

        role_match_res = RoleRelevanceMatcher.calculate_score_with_reason(
            target_role=resolved_target_role,
            post_role=role,
            post_content=full_text,
            extracted_roles=extracted_roles
        )
        role_score = role_match_res["score"]
        role_reason = role_match_res["reason"]

        loc_match_res = LocationRelevanceMatcher.match(resolved_target_loc, location, full_text)
        exp_match_res = ExperienceRelevanceMatcher.match(candidate_exp_years if isinstance(candidate_exp_years, int) else 2, full_text)

        quality_score = QualityScorer.calculate_quality_score(
            hiring_confidence=intent_res.get("confidence", 0.8),
            age_minutes=age_info["age_minutes"],
            max_age_minutes=max_age_minutes or 1440,
            role_score=role_score,
            location_score=loc_match_res.get("score", 100),
            experience_score=exp_match_res.get("score", 75),
            has_email=len(emails) > 0,
            has_phone=len(phones) > 0,
            has_apply_link=True
        )

        # 5. Resume Match & Outreach Pitches
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

        pitches = OutreachPitchGenerator.generate_suite(
            job_title=role,
            company_name=company,
            matched_skills=pitch_skills if pitch_skills else ["Full Stack Development"],
            candidate_name=candidate_name,
            candidate_exp_years=candidate_exp_years if isinstance(candidate_exp_years, int) else 2,
            recipient_name=author,
        )

        result = {
            "status": "success",
            "post_url": norm_url,
            "published_at": published_at.isoformat(),
            "age_minutes": age_info["age_minutes"],
            "age_hours": age_info["age_hours"],
            "age_text": age_info["age_text"],
            "author": author,
            "author_type": intent_res.get("author_type", "RECRUITER"),
            "company": company,
            "job_role": role,
            "extracted_roles": extracted_roles,
            "location": location,
            "location_match_type": loc_match_res.get("match_type", "EXACT"),
            "location_match_score": loc_match_res.get("score", 100),
            "role_match_score": role_score,
            "role_match_reason": role_reason,
            "experience_match_score": exp_match_res.get("score", 75),
            "experience_fit": exp_match_res.get("fit", "UNKNOWN"),
            "hiring_intent": intent_res.get("intent", "HIRING"),
            "hiring_confidence": intent_res.get("confidence", 0.9),
            "hiring_signals": intent_res.get("signals", []),
            "post_quality_score": quality_score,
            "is_spam": False,
            "recruiter_emails": emails,
            "contact_numbers": phones,
            "detected_skills": skills,
            "tailored_outreach_pitches": pitches,
            "full_post_content": full_text,
        }

        if match_data:
            result["match_score"] = match_data.get("match_score", 0)
            result["match_tier"] = match_data.get("match_tier", "Low Match")
            result["matched_skills"] = match_data.get("matched_skills", [])
            result["missing_skills"] = match_data.get("missing_skills", [])
            result["ats_recommendations"] = match_data.get("ats_recommendations", [])

        return result

    @classmethod
    async def extract_from_url_async(
        cls,
        url: str,
        client: Optional[httpx.AsyncClient] = None,
        skills_taxonomy: Optional[List[str]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
        timeframe: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously extracts structured hiring intelligence from a LinkedIn /posts/ URL.
        Features connection reuse, transient error retries, and bounded timeouts.
        """
        if timeframe and not max_age_minutes:
            try:
                max_age_minutes = get_max_age_minutes(timeframe)
            except ValueError:
                return {
                    "status": "rejected",
                    "reason": "INVALID_TIMEFRAME",
                    "error": f"Invalid timeframe '{timeframe}'."
                }
        norm_url = normalize_linkedin_post_url(url)
        if not norm_url:
            return {
                "status": "rejected",
                "reason": "NOT_A_LINKEDIN_POST",
                "error": f"Rejected URL '{url}'. OpenFinder strictly supports ONLY genuine LinkedIn /posts/ URLs.",
            }

        skills_taxonomy = skills_taxonomy or COMMON_SKILLS

        if candidate_profile:
            candidate_name = candidate_profile.get("candidate_name", candidate_name)
            candidate_exp_years = candidate_profile.get("years_of_experience", candidate_exp_years)
            cand_skills = candidate_profile.get("top_skills", [])
            target_role = target_role or candidate_profile.get("primary_role")
        else:
            cand_skills = []

        local_client = False
        if client is None:
            client = httpx.AsyncClient(
                headers=cls.HEADERS,
                timeout=cls.TIMEOUT_CONFIG,
                follow_redirects=True
            )
            local_client = True

        try:
            # Retry transient conditions (timeout, 502/503/504) once
            max_attempts = 2
            resp = None
            for attempt in range(max_attempts):
                try:
                    resp = await client.get(norm_url)
                    if resp.status_code in [502, 503, 504] and attempt < max_attempts - 1:
                        await asyncio.sleep(0.5)
                        continue
                    break
                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return {
                        "status": "error",
                        "reason": "NETWORK_TIMEOUT",
                        "error": str(net_err),
                    }

            if resp is None or resp.status_code != 200:
                code = resp.status_code if resp else "UNKNOWN"
                reason = ErrorCodes.FETCH_FAILED
                if code == 429:
                    reason = ErrorCodes.RATE_LIMITED
                elif code in [401, 403]:
                    reason = ErrorCodes.AUTH_REQUIRED

                return {
                    "status": "error",
                    "reason": reason,
                    "error": f"HTTP {code}",
                }

            if len(resp.content) > MAX_POST_PAYLOAD_BYTES:
                return {
                    "status": "rejected",
                    "reason": ErrorCodes.FILE_TOO_LARGE,
                    "error": f"Post payload exceeded size limit ({len(resp.content)} bytes)."
                }

            return cls._parse_html_to_post_data(
                html_text=resp.text,
                norm_url=norm_url,
                skills_taxonomy=skills_taxonomy,
                max_age_minutes=max_age_minutes,
                target_role=target_role,
                target_location=target_location,
                candidate_name=candidate_name,
                candidate_exp_years=candidate_exp_years,
                cand_skills=cand_skills
            )

        except Exception as e:
            return {
                "status": "error",
                "reason": "PARSER_ERROR",
                "error": str(e),
            }
        finally:
            if local_client:
                await client.aclose()

    @classmethod
    async def extract_batch_async(
        cls,
        urls: List[str],
        max_concurrency: int = MAX_CONCURRENCY,
        skills_taxonomy: Optional[List[str]] = None,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Concurrently extracts a batch of LinkedIn /posts/ URLs using a shared connection pool
        and bounded semaphore to ensure high performance with respectful rate limits.
        """
        if not urls:
            return []

        # Deduplicate input URLs while preserving order
        seen = set()
        deduped_urls = []
        for u in urls:
            norm = normalize_linkedin_post_url(u) or u
            if norm not in seen:
                seen.add(norm)
                deduped_urls.append(norm)

        sem = asyncio.Semaphore(max_concurrency)

        limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
        async with httpx.AsyncClient(
            headers=cls.HEADERS,
            timeout=cls.TIMEOUT_CONFIG,
            limits=limits,
            follow_redirects=True
        ) as client:

            async def sem_task(url: str) -> Dict[str, Any]:
                async with sem:
                    return await cls.extract_from_url_async(
                        url=url,
                        client=client,
                        skills_taxonomy=skills_taxonomy,
                        target_role=target_role,
                        target_location=target_location,
                        max_age_minutes=max_age_minutes,
                        candidate_profile=candidate_profile
                    )

            tasks = [sem_task(u) for u in deduped_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Error isolation: replace unhandled exceptions with error dicts
            cleaned_results = []
            for idx, res in enumerate(results):
                if isinstance(res, Exception):
                    cleaned_results.append({
                        "status": "error",
                        "reason": "UNHANDLED_EXCEPTION",
                        "post_url": deduped_urls[idx],
                        "error": str(res)
                    })
                else:
                    cleaned_results.append(res)

            return cleaned_results

    @classmethod
    def extract_from_url(
        cls,
        url: str,
        skills_taxonomy: Optional[List[str]] = None,
        candidate_name: str = "Candidate",
        candidate_exp_years: int = 2,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
        timeframe: Optional[str] = None,
        candidate_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous entrypoint. Preserves backward compatibility.
        """
        if timeframe and not max_age_minutes:
            try:
                max_age_minutes = get_max_age_minutes(timeframe)
            except ValueError:
                return {
                    "status": "rejected",
                    "reason": "INVALID_TIMEFRAME",
                    "error": f"Invalid timeframe '{timeframe}'."
                }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running inside existing event loop (e.g. FastAPI / Jupyter)
                # Use synchronous httpx.Client to prevent blocking the async event loop
                norm_url = normalize_linkedin_post_url(url)
                if not norm_url:
                    return {
                        "status": "rejected",
                        "reason": "NOT_A_LINKEDIN_POST",
                        "error": f"Rejected URL '{url}'. OpenFinder strictly supports ONLY genuine LinkedIn /posts/ URLs.",
                    }

                skills_taxonomy = skills_taxonomy or COMMON_SKILLS
                if candidate_profile:
                    candidate_name = candidate_profile.get("candidate_name", candidate_name)
                    candidate_exp_years = candidate_profile.get("years_of_experience", candidate_exp_years)
                    cand_skills = candidate_profile.get("top_skills", [])
                    target_role = target_role or candidate_profile.get("primary_role")
                else:
                    cand_skills = []

                with httpx.Client(headers=cls.HEADERS, timeout=cls.TIMEOUT_CONFIG, follow_redirects=True) as client:
                    resp = client.get(norm_url)
                    if resp.status_code != 200:
                        return {"status": "error", "reason": "FETCH_FAILED", "error": f"HTTP {resp.status_code}"}
                    return cls._parse_html_to_post_data(
                        html_text=resp.text,
                        norm_url=norm_url,
                        skills_taxonomy=skills_taxonomy,
                        max_age_minutes=max_age_minutes,
                        target_role=target_role,
                        target_location=target_location,
                        candidate_name=candidate_name,
                        candidate_exp_years=candidate_exp_years,
                        cand_skills=cand_skills
                    )
            else:
                return loop.run_until_complete(
                    cls.extract_from_url_async(
                        url=url,
                        skills_taxonomy=skills_taxonomy,
                        candidate_name=candidate_name,
                        candidate_exp_years=candidate_exp_years,
                        target_role=target_role,
                        target_location=target_location,
                        max_age_minutes=max_age_minutes,
                        candidate_profile=candidate_profile
                    )
                )
        except RuntimeError:
            return asyncio.run(
                cls.extract_from_url_async(
                    url=url,
                    skills_taxonomy=skills_taxonomy,
                    candidate_name=candidate_name,
                    candidate_exp_years=candidate_exp_years,
                    target_role=target_role,
                    target_location=target_location,
                    max_age_minutes=max_age_minutes,
                    candidate_profile=candidate_profile
                )
            )
