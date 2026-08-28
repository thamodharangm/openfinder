import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DB_PATH = DATA_DIR / "cache.db"

# Search Settings
DEFAULT_TIMEFRAME = "past-24h"  # 'past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-7d'
DEFAULT_LOCATION = "India"
DEFAULT_MAX_RESULTS = 15
CACHE_TTL_SECONDS = 1800  # 30 minutes cache for web queries

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

# Spam & Engagement Bait Keywords (To filter out fake/low-quality posts)
SPAM_TRIGGERS = [
    "comment cfbr",
    "comment your email",
    "drop your email below",
    "interested in free course",
    "whatsapp group link",
    "telegram channel link",
    "like and share to get",
    "comment yes to receive",
    "tag 3 friends",
    "follow for more updates",
    "100% free giveaway",
    "guaranteed job referral",
    "dm for course link"
]
