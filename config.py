"""
config.py
=========
Production-grade Central Configuration & Environmental Taxonomy for OpenFinder.

Features:
- Environmental variable overrides with robust typing and safe defaults.
- Enterprise directory management and SQLite database path resolution.
- Granular cache TTLs for live polling (1h) to archive searching (7d).
- Expanded technical skill taxonomy across 9 modern engineering domains.
- Exhaustive spam & engagement-bait negative trigger lists.
- Unified error codes enum for standardized cross-protocol reporting.
"""

from enum import Enum
import os
from pathlib import Path
from typing import Dict, List, Set, Union

# ============================================================================
# 1. APPLICATION METADATA & ENVIRONMENT
# ============================================================================

APP_NAME = "OpenFinder"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Universal MCP Job Connector for Freshers & Experienced Candidates via Claude & ChatGPT"

APP_ENV = os.environ.get("OPENFINDER_ENV", "production").lower()
IS_PROD = APP_ENV == "production"
IS_DEV = APP_ENV == "development"

# Server configuration
SERVER_HOST = os.environ.get("OPENFINDER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("OPENFINDER_PORT", os.environ.get("PORT", 8000)))
PUBLIC_URL = os.environ.get("OPENFINDER_PUBLIC_URL", "https://openfinder.onrender.com")

# Base Directory Resolution
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("OPENFINDER_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DB_PATH = Path(os.environ.get("OPENFINDER_CACHE_DB", DATA_DIR / "cache.db"))

# ============================================================================
# 2. SEARCH & TIMEFRAME DEFAULTS
# ============================================================================

DEFAULT_TIMEFRAME = "past-24h"  # 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d', 'past-7d'
DEFAULT_LOCATION = "India"
DEFAULT_MAX_RESULTS = 20

# ============================================================================
# 3. PERFORMANCE & NETWORK CONFIGURATION
# ============================================================================

MAX_POST_EXTRACTION_CONCURRENCY = int(os.environ.get("OPENFINDER_CONCURRENCY", 5))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("OPENFINDER_CONNECT_TIMEOUT", 5.0))
HTTP_READ_TIMEOUT = float(os.environ.get("OPENFINDER_READ_TIMEOUT", 8.0))
HTTP_WRITE_TIMEOUT = 5.0
HTTP_POOL_TIMEOUT = 8.0
MAX_RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5
MAX_DISCOVERY_CANDIDATES = 40

# File size & payload safety limits
MAX_POST_PAYLOAD_BYTES = 5 * 1024 * 1024     # 5MB protection limit
MAX_RESUME_FILE_BYTES = 10 * 1024 * 1024     # 10MB protection limit

# ============================================================================
# 4. TIMEFRAME CACHE TTLS (Seconds)
# ============================================================================

TIMEFRAME_TTLS: Dict[str, int] = {
    "past-1h": 60,       # 1 minute (ultra-fresh live polling)
    "past-4h": 300,      # 5 minutes
    "past-12h": 900,     # 15 minutes
    "past-24h": 1800,    # 30 minutes
    "past-3d": 3600,     # 1 hour
    "3d": 3600,
    "past-7d": 3600,     # 1 hour
    "w": 3600,
    "past-week": 3600,
    "default": 1800
}

# ============================================================================
# 5. ERROR CODES
# ============================================================================

class ErrorCodes:
    INVALID_URL = "INVALID_URL"
    FETCH_FAILED = "FETCH_FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PUBLISHED_TIME_UNVERIFIED = "PUBLISHED_TIME_UNVERIFIED"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    OLDER_THAN_REQUESTED_WINDOW = "OLDER_THAN_REQUESTED_WINDOW"
    NON_HIRING_POST = "NON_HIRING_POST"
    JOB_SEEKER = "JOB_SEEKER"
    ROLE_MISMATCH = "ROLE_MISMATCH"
    SPAM_OR_BAIT = "SPAM_OR_BAIT"
    PARSER_ERROR = "PARSER_ERROR"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    DATABASE_ERROR = "DATABASE_ERROR"

# ============================================================================
# 6. EXPANDED TECHNICAL SKILL TAXONOMY
# ============================================================================

SKILL_TAXONOMY: Dict[str, List[str]] = {
    "Languages": [
        "python", "javascript", "typescript", "java", "c++", "c#", "golang", "go", "ruby", 
        "rust", "php", "swift", "kotlin", "sql", "r", "dart", "scala", "shell", "bash"
    ],
    "Frontend": [
        "react", "react.js", "react native", "next.js", "vue", "vue.js", "angular", "html", "html5", 
        "css", "css3", "tailwind", "tailwindcss", "redux", "zustand", "bootstrap", "material-ui", 
        "sass", "webpack", "vite", "flutter", "astro", "remix", "svelte"
    ],
    "Backend & APIs": [
        "node.js", "nodejs", "express", "express.js", "django", "fastapi", "flask", "spring boot", 
        "spring", "asp.net", ".net core", "laravel", "graphql", "rest api", "restful", "grpc", 
        "microservices", "websockets", "celery", "rabbitmq", "kafka", "nest.js", "gin"
    ],
    "Databases & Storage": [
        "mongodb", "postgresql", "postgres", "mysql", "redis", "elasticsearch", "cassandra", 
        "dynamodb", "sqlite", "mariadb", "firebase", "supabase", "prisma", "sequelize"
    ],
    "Cloud, DevOps & Infrastructure": [
        "aws", "amazon web services", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s", 
        "terraform", "ci/cd", "jenkins", "github actions", "gitlab ci", "linux", "serverless", 
        "nginx", "helm", "prometheus", "grafana", "argo cd", "datadog", "opentelemetry"
    ],
    "AI, ML & LLMs": [
        "machine learning", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision", 
        "llm", "langchain", "llamaindex", "openai", "pytorch", "tensorflow", "pandas", "numpy", 
        "scikit-learn", "huggingface", "vector db", "chromadb", "pinecone", "qdrant", "rag", "genai"
    ],
    "Architecture & Methodologies": [
        "git", "github", "jira", "agile", "scrum", "system design", "distributed systems", 
        "oop", "solid principles", "design patterns", "clean architecture", "tdd"
    ],
    "Testing & QA": [
        "unit testing", "jest", "cypress", "playwright", "selenium", "mocha", "pytest", "postman", "sdet"
    ]
}

# Flattened list for O(1) quick lookups
COMMON_SKILLS: List[str] = sorted(list({
    skill for cat_skills in SKILL_TAXONOMY.values() for skill in cat_skills
}))

# ============================================================================
# 7. SPAM & ENGAGEMENT BAIT TRIGGERS
# ============================================================================

SPAM_TRIGGERS: List[str] = [
    "comment cfbr",
    "cfbr",
    "comment interested",
    "drop your email",
    "drop your resume in comments",
    "follow me for more",
    "like and comment",
    "100% free course",
    "free certificate",
    "giveaway",
    "whatsapp group link",
    "telegram group link",
    "dm me for link",
    "typing 'yes'",
    "say 'interested'",
    "tag 3 friends",
    "comment 'hire me'",
    "open to work",
    "looking for new opportunities",
    "actively looking for a job",
    "immediate joiner looking for role",
]
