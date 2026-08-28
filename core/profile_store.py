import sqlite3
import json
import time
import uuid
import threading
from typing import Optional, Dict, Any, List
from pathlib import Path
import sys

# Ensure root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CACHE_DB_PATH


class CandidateProfileStore:
    """
    Persistent SQLite Store for Normalized Candidate Resume Profiles.
    Allows ChatGPT Actions, Claude MCP, and CLI to reuse parsed candidate profiles
    across multiple conversational search turns without re-uploading the CV.
    """

    _lock = threading.Lock()
    _in_memory_fallback: Dict[str, Dict[str, Any]] = {}

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = db_path
        self._fallback_mode = False
        self._init_db()

    def _init_db(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=5.0) as conn:
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
                            target_locations_json TEXT
                        )
                    """)
                    conn.commit()
        except Exception:
            self._fallback_mode = True

    def save_profile(self, profile: Dict[str, Any], profile_id: Optional[str] = None) -> str:
        """
        Stores or updates a normalized candidate profile and returns the unique candidate_profile_id.
        """
        if not profile:
            raise ValueError("Cannot save an empty candidate profile.")

        pid = profile_id or f"prof_{uuid.uuid4().hex[:12]}"
        now = time.time()

        name = profile.get("candidate_name") or profile.get("name") or "Candidate"
        contact = profile.get("contact_info", {})
        email = contact.get("email") or profile.get("email")
        phone = contact.get("phone") or profile.get("phone")
        exp_years = profile.get("years_of_experience") or profile.get("experience_years") or 2
        if isinstance(exp_years, str):
            try:
                import re
                exp_years = int(re.search(r'\d+', exp_years).group(0))
            except Exception:
                exp_years = 2

        seniority = profile.get("seniority_level") or "Mid-Level"
        primary_role = profile.get("primary_role") or "Software Engineer"
        top_skills = profile.get("top_skills") or []
        skills_cat = profile.get("skills_categorized") or {}
        target_roles = profile.get("target_roles") or [primary_role]
        target_locations = profile.get("target_locations") or ["India"]

        normalized_data = {
            "candidate_profile_id": pid,
            "candidate_name": name,
            "email": email,
            "phone": phone,
            "years_of_experience": exp_years,
            "seniority_level": seniority,
            "primary_role": primary_role,
            "top_skills": top_skills,
            "skills_categorized": skills_cat,
            "target_roles": target_roles,
            "target_locations": target_locations,
            "created_at": profile.get("created_at", now),
            "updated_at": now
        }

        if self._fallback_mode:
            with self._lock:
                self._in_memory_fallback[pid] = normalized_data
            return pid

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO candidate_profiles (
                            profile_id, created_at, updated_at, candidate_name, email, phone,
                            years_of_experience, seniority_level, primary_role,
                            top_skills_json, skills_categorized_json, target_roles_json, target_locations_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(target_locations)
                    ))
                    conn.commit()
            return pid
        except Exception:
            with self._lock:
                self._in_memory_fallback[pid] = normalized_data
            return pid

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a candidate profile by its unique ID.
        """
        if not profile_id:
            return None

        clean_id = profile_id.strip()

        if self._fallback_mode:
            with self._lock:
                return self._in_memory_fallback.get(clean_id)

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT profile_id, created_at, updated_at, candidate_name, email, phone,
                               years_of_experience, seniority_level, primary_role,
                               top_skills_json, skills_categorized_json, target_roles_json, target_locations_json
                        FROM candidate_profiles WHERE profile_id = ?
                    """, (clean_id,))
                    row = cursor.fetchone()
                    if not row:
                        return None

                    (pid, c_at, u_at, name, email, phone, exp, sen, role,
                     top_sk, sk_cat, t_roles, t_locs) = row

                    return {
                        "candidate_profile_id": pid,
                        "candidate_name": name,
                        "email": email,
                        "phone": phone,
                        "years_of_experience": exp,
                        "seniority_level": sen,
                        "primary_role": role,
                        "top_skills": json.loads(top_sk) if top_sk else [],
                        "skills_categorized": json.loads(sk_cat) if sk_cat else {},
                        "target_roles": json.loads(t_roles) if t_roles else [],
                        "target_locations": json.loads(t_locs) if t_locs else [],
                        "created_at": c_at,
                        "updated_at": u_at
                    }
        except Exception:
            with self._lock:
                return self._in_memory_fallback.get(clean_id)

    def delete_profile(self, profile_id: str) -> bool:
        """
        Deletes a candidate profile.
        """
        if not profile_id:
            return False

        clean_id = profile_id.strip()
        with self._lock:
            self._in_memory_fallback.pop(clean_id, None)

        try:
            with self._lock:
                with sqlite3.connect(self.db_path, timeout=3.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM candidate_profiles WHERE profile_id = ?", (clean_id,))
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception:
            return False
