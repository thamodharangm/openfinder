import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DB_PATH = DATA_DIR / "cache.db"

# Search & Timeframe Defaults
DEFAULT_TIMEFRAME = "past-24h"  # 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'
DEFAULT_LOCATION = "India"
DEFAULT_MAX_RESULTS = 23

# Performance & Network Configuration
MAX_POST_EXTRACTION_CONCURRENCY = int(os.environ.get("OPENFINDER_CONCURRENCY", 5))
HTTP_CONNECT_TIMEOUT = 5.0
HTTP_READ_TIMEOUT = 10.0
HTTP_WRITE_TIMEOUT = 5.0
HTTP_POOL_TIMEOUT = 10.0
MAX_RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5
MAX_DISCOVERY_CANDIDATES = 40
MAX_POST_PAYLOAD_BYTES = 5 * 1024 * 1024    # 5MB protection limit
MAX_RESUME_FILE_BYTES = 10 * 1024 * 1024    # 10MB protection limit

# Timeframe Cache TTLs (Seconds)
TIMEFRAME_TTLS = {
    "past-1h": 60,       # 1 minute (ultra-fresh live polling)
    "past-4h": 300,      # 5 minutes
    "past-12h": 900,     # 15 minutes
    "past-24h": 1800,    # 30 minutes
    "past-7d": 7200,     # 2 hours
    "w": 7200,
    "past-week": 7200,
    "default": 1800
}

# Standard Internal Error Codes
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

# Categorized Technical Taxonomy
SKILL_TAXONOMY = {
    "Languages": [
        "python", "javascript", "typescript", "java", "c++", "c#", "golang", "go", "ruby", 
        "rust", "php", "swift", "kotlin", "sql", "r", "dart", "scala", "shell", "bash"
    ],
    "Frontend": [
        "react", "react.js", "react native", "next.js", "vue", "vue.js", "angular", "html", "html5", 
        "css", "css3", "tailwind", "tailwindcss", "redux", "zustand", "bootstrap", "material-ui", 
        "sass", "webpack", "vite", "flutter"
    ],
    "Backend & APIs": [
        "node.js", "nodejs", "express", "express.js", "django", "fastapi", "flask", "spring boot", 
        "spring", "asp.net", ".net core", "laravel", "graphql", "rest api", "restful", "grpc", 
        "microservices", "websockets", "celery", "rabbitmq", "kafka"
    ],
    "Databases & Storage": [
        "mongodb", "postgresql", "postgres", "mysql", "redis", "elasticsearch", "cassandra", 
        "dynamodb", "sqlite", "mariadb", "firebase", "supabase", "prisma", "sequelize"
    ],
    "Cloud, DevOps & Infrastructure": [
        "aws", "amazon web services", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s", 
        "terraform", "ci/cd", "jenkins", "github actions", "gitlab ci", "linux", "serverless", 
        "nginx", "helm", "prometheus", "grafana"
    ],
    "AI, ML & Data": [
        "machine learning", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision", 
        "llm", "langchain", "llamaindex", "openai", "pytorch", "tensorflow", "pandas", "numpy", 
        "scikit-learn", "huggingface", "vector db"
    ],
    "Architecture & Methodologies": [
        "git", "github", "jira", "agile", "scrum", "system design", "distributed systems", 
        "oop", "solid principles", "design patterns", "clean architecture", "tdd"
    ],
    "Testing & QA": [
        "unit testing", "jest", "cypress", "playwright", "selenium", "mocha", "pytest", "postman"
    ]
}

# Flattened list for quick lookups
COMMON_SKILLS = [skill for cat_skills in SKILL_TAXONOMY.values() for skill in cat_skills]

# Spam & Engagement Bait Keywords
SPAM_TRIGGERS = [
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
