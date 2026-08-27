import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Search Settings
DEFAULT_TIMEFRAME = "w"  # 'd' for past 24 hours, 'w' for past week, 'm' for past month
DEFAULT_LOCATION = "India"
DEFAULT_MAX_RESULTS = 15

# Common Technical Skills Taxonomy for Matcher
COMMON_SKILLS = [
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "golang", "go", "ruby", "rust", "php", "swift", "kotlin", "sql", "r", "dart",
    # Frontend
    "react", "react.js", "react native", "next.js", "vue", "vue.js", "angular", "html", "css", "tailwind", "redux", "bootstrap", "flutter",
    # Backend & Frameworks
    "node.js", "nodejs", "express", "django", "fastapi", "flask", "spring boot", "spring", "asp.net", "laravel", "graphql", "rest api", "grpc",
    # Cloud & DevOps
    "aws", "azure", "gcp", "docker", "kubernetes", "k8s", "terraform", "ci/cd", "jenkins", "github actions", "linux", "serverless",
    # Databases
    "mongodb", "postgresql", "postgres", "mysql", "redis", "elasticsearch", "cassandra", "dynamodb", "sqlite",
    # AI / ML / Data
    "machine learning", "deep learning", "ai", "nlp", "computer vision", "llm", "langchain", "pytorch", "tensorflow", "pandas", "numpy", "scikit-learn",
    # General / QA / Management
    "git", "github", "jira", "agile", "scrum", "selenium", "cypress", "playwright", "unit testing", "system design", "microservices"
]

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
    "100% free giveaway"
]
