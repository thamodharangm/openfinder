"""
core/profile_store.py
=====================
Production-grade Persistent & Memory-Tiered Candidate Resume Profile Store for OpenFinder.

Features:
- Two-tier architecture: Fast L1 In-Memory LRU Cache + L2 Persistent SQLite Database with WAL mode.
- Thread-safe concurrency via threading.RLock().
- Dynamic schema auto-migration supporting rich candidate metadata:
  (Education, Work Experience, Projects, GitHub/LinkedIn/Portfolio links, Desired Domains, Salary, Notice Period).
- Conversational reuse across ChatGPT Actions, Claude MCP, FastAPI, and CLI.
- Search by skills, profile listing, and self-healing error recovery.
"""

from collections import OrderedDict
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CACHE_DB_PATH

logger = logging.getLogger(__name__)


class CandidateProfileStore:
    """
    Persistent SQLite & Memory-Tiered Store for Normalized Candidate Resume Profiles.
    Allows ChatGPT Actions, Claude MCP, FastAPI, and CLI to reuse parsed candidate profiles
    across multiple conversational search turns without re-uploading the CV.
    """

    def __init__(self, db_path: Union[str, Path] = CACHE_DB_PATH, max_l1_entries: int = 200):
        self.db_path = Path(db_path)
        self.max_l1_entries = max_l1_entries
        self._lock = threading.RLock()
        self._l1_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._fallback_mode = False

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Opens a SQLite connection tuned for high performance."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False
        )
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _init_db(self) -> None:
        """Initializes table schema and handles seamless column auto-migrations."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS candidate_profiles (
                            profile_id TEXT PRIMARY KEY,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            candidate_name TEXT,
                            email TEXT,
                            phone TEXT,
                            years_of_experience INTEGER,
                            seniority_level TEXT,
                            primary_role TEXT,
                            top_skills_json TEXT,
                            skills_categorized_json TEXT,
                            target_roles_json TEXT,
                            target_locations_json TEXT,
                            education_json TEXT,
                            work_experience_json TEXT,
                            projects_json TEXT,
                            certifications_json TEXT,
                            portfolio_url TEXT,
                            github_url TEXT,
                            linkedin_url TEXT,
                            desired_domains_json TEXT,
                            remote_preference TEXT,
                            expected_salary TEXT,
                            notice_period TEXT
                        )
                    """)
                    conn.commit()

                    # Schema auto-migration check for existing databases
                    cursor.execute("PRAGMA table_info(candidate_profiles)")
                    existing_cols = {row[1] for row in cursor.fetchall()}

                    new_cols = [
                        ("education_json", "TEXT"),
                        ("work_experience_json", "TEXT"),
                        ("projects_json", "TEXT"),
                        ("certifications_json", "TEXT"),
                        ("portfolio_url", "TEXT"),
                        ("github_url", "TEXT"),
                        ("linkedin_url", "TEXT"),
                        ("desired_domains_json", "TEXT"),
                        ("remote_preference", "TEXT"),
                        ("expected_salary", "TEXT"),
                        ("notice_period", "TEXT"),
                    ]
                    for col_name, col_type in new_cols:
                        if col_name not in existing_cols:
                            try:
                                cursor.execute(f"ALTER TABLE candidate_profiles ADD COLUMN {col_name} {col_type}")
                                conn.commit()
                            except Exception as alt_err:
                                logger.debug("Column %s already exists or failed: %s", col_name, alt_err)

        except Exception as e:
            logger.warning("Failed to initialize profile store SQLite at %s: %s. Enabling in-memory mode.", self.db_path, e)
            self._fallback_mode = True

    def save_profile(self, profile: Dict[str, Any], profile_id: Optional[str] = None) -> str:
        """
        Stores or updates a normalized candidate profile and returns the unique candidate_profile_id.
        """
        if not profile or not isinstance(profile, dict):
            raise ValueError("Cannot save an empty or invalid candidate profile.")

        pid = (profile_id or profile.get("candidate_profile_id") or f"prof_{uuid.uuid4().hex[:12]}").strip()
        now = time.time()

        # Extract core fields
        name = profile.get("candidate_name") or profile.get("name") or "Candidate"
        contact = profile.get("contact_info", {}) if isinstance(profile.get("contact_info"), dict) else {}
        email = contact.get("email") or profile.get("email")
        phone = contact.get("phone") or profile.get("phone")
        
        # Experience parsing
        exp_years = profile.get("years_of_experience") or profile.get("experience_years") or 2
        if isinstance(exp_years, str):
            try:
                m = re.search(r'\d+', exp_years)
                exp_years = int(m.group(0)) if m else 2
            except Exception:
                exp_years = 2

        seniority = profile.get("seniority_level") or "Mid-Level"
        primary_role = profile.get("primary_role") or "Software Engineer"
        top_skills = profile.get("top_skills") or profile.get("skills") or []
        if isinstance(top_skills, str):
            top_skills = [s.strip() for s in top_skills.split(",") if s.strip()]

        skills_cat = profile.get("skills_categorized") or {}
        target_roles = profile.get("target_roles") or profile.get("desired_roles") or [primary_role]
        target_locations = profile.get("target_locations") or profile.get("preferred_locations") or ["India"]

        # Rich profile attributes
        education = profile.get("education") or {}
        work_exp = profile.get("work_experience") or profile.get("experience") or []
        projects = profile.get("projects") or []
        certs = profile.get("certifications") or []
        portfolio = profile.get("portfolio_url") or profile.get("portfolio")
        github = profile.get("github_url") or profile.get("github")
        linkedin = profile.get("linkedin_url") or profile.get("linkedin")
        desired_domains = profile.get("desired_domains") or []
        remote_pref = profile.get("remote_preference") or "any"
        expected_salary = profile.get("expected_salary") or profile.get("salary_expectation")
        notice_period = profile.get("notice_period")

        normalized_data: Dict[str, Any] = {
            "candidate_profile_id": pid,
            "candidate_name": name,
            "email": email,
            "phone": phone,
            "years_of_experience": exp_years,
            "seniority_level": seniority,
            "primary_role": primary_role,
            "top_skills": top_skills,
            "skills": top_skills,  # Dual mapping for JobMatcher compatibility
            "skills_categorized": skills_cat,
            "target_roles": target_roles,
            "target_locations": target_locations,
            "education": education,
            "work_experience": work_exp,
            "projects": projects,
            "certifications": certs,
            "portfolio_url": portfolio,
            "github_url": github,
            "linkedin_url": linkedin,
            "desired_domains": desired_domains,
            "remote_preference": remote_pref,
            "expected_salary": expected_salary,
            "notice_period": notice_period,
            "created_at": profile.get("created_at", now),
            "updated_at": now
        }

        # Update L1 Memory Cache
        with self._lock:
            if pid in self._l1_cache:
                del self._l1_cache[pid]
            elif len(self._l1_cache) >= self.max_l1_entries:
                self._l1_cache.popitem(last=False)
            self._l1_cache[pid] = normalized_data

        if self._fallback_mode:
            return pid

        # Update L2 SQLite Storage
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO candidate_profiles (
                            profile_id, created_at, updated_at, candidate_name, email, phone,
                            years_of_experience, seniority_level, primary_role,
                            top_skills_json, skills_categorized_json, target_roles_json, target_locations_json,
                            education_json, work_experience_json, projects_json, certifications_json,
                            portfolio_url, github_url, linkedin_url, desired_domains_json,
                            remote_preference, expected_salary, notice_period
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pid,
                        normalized_data["created_at"],
                        now,
                        name,
                        email,
                        phone,
                        exp_years,
                        seniority,
                        primary_role,
                        json.dumps(top_skills),
                        json.dumps(skills_cat),
                        json.dumps(target_roles),
                        json.dumps(target_locations),
                        json.dumps(education),
                        json.dumps(work_exp),
                        json.dumps(projects),
                        json.dumps(certs),
                        portfolio,
                        github,
                        linkedin,
                        json.dumps(desired_domains),
                        remote_pref,
                        expected_salary,
                        notice_period
                    ))
                    conn.commit()
            return pid
        except Exception as e:
            logger.error("Failed writing candidate profile %s to SQLite: %s", pid, e)
            return pid

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a candidate profile by its unique ID.
        Checks L1 Memory Cache first, then falls back to L2 SQLite.
        """
        if not profile_id or not isinstance(profile_id, str):
            return None

        clean_id = profile_id.strip()

        # 1. Check L1 Memory Cache
        with self._lock:
            if clean_id in self._l1_cache:
                self._l1_cache.move_to_end(clean_id)
                return self._l1_cache[clean_id]

        if self._fallback_mode:
            return None

        # 2. Check L2 SQLite
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT profile_id, created_at, updated_at, candidate_name, email, phone,
                               years_of_experience, seniority_level, primary_role,
                               top_skills_json, skills_categorized_json, target_roles_json, target_locations_json,
                               education_json, work_experience_json, projects_json, certifications_json,
                               portfolio_url, github_url, linkedin_url, desired_domains_json,
                               remote_preference, expected_salary, notice_period
                        FROM candidate_profiles WHERE profile_id = ?
                    """, (clean_id,))
                    row = cursor.fetchone()
                    if not row:
                        return None

                    (pid, c_at, u_at, name, email, phone, exp, sen, role,
                     top_sk, sk_cat, t_roles, t_locs,
                     edu, wexp, proj, cert, port, gh, li, doms, rem_pref, exp_sal, not_per) = row

                    def _safe_json(val, default):
                        if not val:
                            return default
                        try:
                            return json.loads(val)
                        except Exception:
                            return default

                    top_skills_list = _safe_json(top_sk, [])

                    profile_data = {
                        "candidate_profile_id": pid,
                        "candidate_name": name,
                        "email": email,
                        "phone": phone,
                        "years_of_experience": exp,
                        "seniority_level": sen,
                        "primary_role": role,
                        "top_skills": top_skills_list,
                        "skills": top_skills_list,
                        "skills_categorized": _safe_json(sk_cat, {}),
                        "target_roles": _safe_json(t_roles, []),
                        "target_locations": _safe_json(t_locs, []),
                        "education": _safe_json(edu, {}),
                        "work_experience": _safe_json(wexp, []),
                        "projects": _safe_json(proj, []),
                        "certifications": _safe_json(cert, []),
                        "portfolio_url": port,
                        "github_url": gh,
                        "linkedin_url": li,
                        "desired_domains": _safe_json(doms, []),
                        "remote_preference": rem_pref or "any",
                        "expected_salary": exp_sal,
                        "notice_period": not_per,
                        "created_at": c_at,
                        "updated_at": u_at
                    }

                    # Populate L1 Cache
                    self._l1_cache[clean_id] = profile_data
                    return profile_data

        except Exception as e:
            logger.error("Error retrieving candidate profile %s from SQLite: %s", clean_id, e)
            return None

    def delete_profile(self, profile_id: str) -> bool:
        """
        Deletes a candidate profile from both L1 memory and L2 SQLite.
        """
        if not profile_id or not isinstance(profile_id, str):
            return False

        clean_id = profile_id.strip()
        with self._lock:
            self._l1_cache.pop(clean_id, None)

        if self._fallback_mode:
            return True

        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM candidate_profiles WHERE profile_id = ?", (clean_id,))
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error("Error deleting candidate profile %s: %s", clean_id, e)
            return False

    def list_profiles(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Lists recent candidate profiles with high-level summary info."""
        results: List[Dict[str, Any]] = []
        if self._fallback_mode:
            with self._lock:
                for p in list(self._l1_cache.values())[-limit:]:
                    results.append({
                        "candidate_profile_id": p.get("candidate_profile_id"),
                        "candidate_name": p.get("candidate_name"),
                        "primary_role": p.get("primary_role"),
                        "years_of_experience": p.get("years_of_experience"),
                        "top_skills": p.get("top_skills", [])[:5],
                        "updated_at": p.get("updated_at")
                    })
            return results

        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT profile_id, candidate_name, primary_role, years_of_experience, top_skills_json, updated_at
                        FROM candidate_profiles
                        ORDER BY updated_at DESC
                        LIMIT ?
                    """, (limit,))
                    for row in cursor.fetchall():
                        pid, name, role, exp, sk_json, u_at = row
                        try:
                            skills = json.loads(sk_json) if sk_json else []
                        except Exception:
                            skills = []
                        results.append({
                            "candidate_profile_id": pid,
                            "candidate_name": name,
                            "primary_role": role,
                            "years_of_experience": exp,
                            "top_skills": skills[:5],
                            "updated_at": u_at
                        })
            return results
        except Exception as e:
            logger.error("Failed listing candidate profiles: %s", e)
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Returns storage diagnostics and metrics."""
        count = 0
        if not self._fallback_mode:
            try:
                with self._lock:
                    with self._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM candidate_profiles")
                        count = cursor.fetchone()[0]
            except Exception:
                count = len(self._l1_cache)
        else:
            count = len(self._l1_cache)

        return {
            "total_saved_profiles": count,
            "l1_memory_cached_profiles": len(self._l1_cache),
            "storage_path": str(self.db_path),
            "fallback_mode": self._fallback_mode
        }
