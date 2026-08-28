import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Any
import sys
from pathlib import Path

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.time_utils import get_max_age_minutes, FRESHNESS_WINDOWS


@dataclass
class SearchIntent:
    raw_query: str
    target_role: str
    role_family: str
    required_tech_signals: List[str]
    negative_tech_signals: List[str]
    role_variants: List[str]
    target_location: str
    location_variants: List[str]
    timeframe: str
    max_age_minutes: int
    candidate_exp_years: int = 2
    remote_only: bool = False

    def generate_dork_queries(self, max_queries: int = 5) -> List[str]:
        """
        Generates precision search engine mirror dorks targeting ONLY site:linkedin.com/posts.
        Uses high-recall natural queries and quoted variants for maximum discovery.
        """
        loc_str = f" {self.target_location}" if self.target_location and self.target_location.lower() != "india" else ""
        p_role = self.target_role.replace('"', '').strip()
        
        queries = [
            f'site:linkedin.com/posts hiring {p_role}{loc_str}'.strip(),
            f'site:linkedin.com/posts {p_role} hiring{loc_str}'.strip(),
            f'site:linkedin.com/posts "{p_role}" "we are hiring"{loc_str}'.strip(),
            f'site:linkedin.com/posts {p_role} "send resume"{loc_str}'.strip(),
            f'site:linkedin.com/posts hiring {self.target_location}'.strip() if self.target_location and self.target_location.lower() != "india" else f'site:linkedin.com/posts {p_role} opening',
            f'site:linkedin.com/posts "{p_role}" hiring'.strip(),
        ]
        
        if self.role_variants and len(self.role_variants) > 1:
            v_role = self.role_variants[1].replace('"', '').strip()
            queries.insert(1, f'site:linkedin.com/posts hiring {v_role}{loc_str}'.strip())

        seen = set()
        deduped = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                deduped.append(q)

        return deduped[:max_queries]

    def generate_diverse_session_queries(self, max_queries: int = 4) -> List[str]:
        """
        Generates a balanced set of distinct high-intent queries for LinkedIn content search.
        Covers:
          1. Exact Role Quoted: '"React Developer" hiring'
          2. Action Statement: 'React Developer "we are hiring"'
          3. Resume Call: 'React Developer "send resume"'
          4. Role Variant: 'React.js Developer hiring' or 'Frontend Developer React hiring'
        """
        p_role = self.target_role.replace('"', '').strip()
        loc_term = self.location_variants[0] if self.location_variants and self.location_variants[0].lower() != "india" else ""
        loc_suffix = f" {loc_term}" if loc_term else ""

        queries = [
            f'"{p_role}" hiring{loc_suffix}'.strip(),
            f'{p_role} "we are hiring"{loc_suffix}'.strip(),
            f'{p_role} "send resume"{loc_suffix}'.strip(),
        ]

        if self.role_variants and len(self.role_variants) > 1:
            v_role = self.role_variants[1].replace('"', '').strip()
            queries.append(f'{v_role} hiring{loc_suffix}'.strip())

        if len(self.location_variants) > 1 and self.location_variants[1].lower() != "india":
            alt_loc = self.location_variants[1]
            queries.append(f'{p_role} {alt_loc}'.strip())
        elif len(self.role_variants) > 2:
            v2_role = self.role_variants[2].replace('"', '').strip()
            queries.append(f'{v2_role} hiring{loc_suffix}'.strip())
        else:
            queries.append(f'{p_role} "urgent opening"{loc_suffix}'.strip())

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                deduped.append(q)

        return deduped[:max_queries]

    def generate_session_keywords(self) -> str:
        """
        Primary query string for single-query compatibility.
        """
        loc_str = f" {self.target_location}" if self.target_location and self.target_location.lower() != "india" else ""
        return f"{self.target_role} hiring{loc_str}".strip()


class SearchIntentParser:
    """
    Parses and normalizes unstructured search inputs into structured, deterministic SearchIntent.
    """

    ROLE_FAMILIES: Dict[str, Dict[str, Any]] = {
        "FRONTEND_REACT": {
            "triggers": ["react", "react.js", "reactjs", "react native", "next.js", "nextjs"],
            "required": ["react", "react.js", "reactjs", "next.js"],
            "negatives": ["coldfusion", "php", "laravel", "django", "java", "spring", "dotnet", "c#", "ruby", "rails", "sap", "oracle", "salesforce", "devops", "qa"],
            "variants": ["React Developer", "React.js Developer", "ReactJS Developer", "Frontend Developer (React)", "Frontend Engineer React", "MERN Developer", "Full Stack React Developer"]
        },
        "MERN_FULLSTACK": {
            "triggers": ["mern", "full stack react", "fullstack react"],
            "required": ["mern", "react", "node", "express", "mongodb"],
            "negatives": ["coldfusion", "php", "django", "java", "dotnet", "c#", "sap", "devops"],
            "variants": ["MERN Stack Developer", "MERN Developer", "Full Stack Developer (MERN)", "React Node Developer"]
        },
        "NODE_BACKEND": {
            "triggers": ["node", "node.js", "nodejs", "express.js", "expressjs"],
            "required": ["node", "node.js", "nodejs", "express"],
            "negatives": ["php", "django", "java", "dotnet", "c#", "coldfusion", "devops"],
            "variants": ["Node.js Developer", "NodeJS Developer", "Backend Developer (Node.js)", "Node.js Engineer"]
        },
        "PYTHON_BACKEND": {
            "triggers": ["python", "django", "fastapi", "flask"],
            "required": ["python", "django", "fastapi", "flask"],
            "negatives": ["php", "coldfusion", "java", "dotnet", "c#", "ruby", "devops"],
            "variants": ["Python Developer", "Python Backend Developer", "Django Developer", "FastAPI Developer"]
        },
        "JAVA_BACKEND": {
            "triggers": ["java", "spring", "springboot", "j2ee", "hibernate"],
            "required": ["java", "spring", "springboot"],
            "negatives": ["php", "coldfusion", "python", "ruby", "dotnet", "devops"],
            "variants": ["Java Developer", "Java Spring Boot Developer", "Java Backend Developer", "Java Engineer"]
        },
        "DOTNET_BACKEND": {
            "triggers": [".net", "dotnet", "c#", "asp.net"],
            "required": [".net", "dotnet", "c#"],
            "negatives": ["php", "coldfusion", "python", "ruby", "java", "devops"],
            "variants": [".NET Developer", "Dotnet Developer", "C# Developer", "ASP.NET Developer"]
        },
        "FRONTEND_GENERAL": {
            "triggers": ["frontend", "front-end", "ui developer", "ui engineer", "vue", "angular"],
            "required": ["frontend", "front-end", "ui", "javascript", "vue", "angular"],
            "negatives": ["coldfusion", "sap", "oracle", "embedded"],
            "variants": ["Frontend Developer", "Frontend Engineer", "UI Developer", "Web Developer"]
        },
        "DEVOPS": {
            "triggers": ["devops", "sre", "cloud engineer", "kubernetes", "aws", "terraform"],
            "required": ["devops", "sre", "kubernetes", "docker", "aws", "cloud"],
            "negatives": ["frontend", "react", "ui developer", "graphic designer"],
            "variants": ["DevOps Engineer", "Site Reliability Engineer", "Cloud Engineer", "SRE"]
        },
        "DATA": {
            "triggers": ["data analyst", "data engineer", "data scientist", "machine learning", "ai engineer"],
            "required": ["data", "sql", "python", "machine learning", "analytics"],
            "negatives": ["frontend", "react", "ui developer"],
            "variants": ["Data Analyst", "Data Engineer", "Data Scientist", "ML Engineer"]
        },
        "QA": {
            "triggers": ["qa", "tester", "quality assurance", "selenium", "automation tester"],
            "required": ["qa", "test", "tester", "selenium", "automation"],
            "negatives": ["graphic designer", "sales"],
            "variants": ["QA Engineer", "Automation Test Engineer", "Software Tester", "SDET"]
        },
        "MOBILE": {
            "triggers": ["flutter", "react native", "android", "ios", "swift", "kotlin"],
            "required": ["flutter", "react native", "android", "ios", "swift", "kotlin"],
            "negatives": ["php", "coldfusion", "sap"],
            "variants": ["Flutter Developer", "React Native Developer", "Android Developer", "iOS Developer"]
        }
    }

    LOCATION_CLUSTERS: Dict[str, List[str]] = {
        "bangalore": ["Bangalore", "Bengaluru", "Electronic City", "Whitefield", "Koramangala", "Indiranagar", "Hebbal", "HSR Layout", "Marathahalli", "Karnataka"],
        "chennai": ["Chennai", "Madras", "OMR", "Sholinganallur", "Guindy", "T Nagar", "Velachery", "Tamil Nadu"],
        "coimbatore": ["Coimbatore", "Kovai", "Peelamedu", "Saravanampatti", "Tamil Nadu"],
        "madurai": ["Madurai", "Mattuthavani", "KK Nagar", "Tamil Nadu"],
        "trichy": ["Trichy", "Tiruchirappalli", "Tamil Nadu"],
        "theni": ["Theni", "Tamil Nadu", "Chennai", "Coimbatore"],
        "salem": ["Salem", "Tamil Nadu"],
        "hyderabad": ["Hyderabad", "HITEC City", "Gachibowli", "Madhapur", "Secunderabad", "Telangana"],
        "mumbai": ["Mumbai", "Bombay", "Navi Mumbai", "Thane", "Andheri", "Bandra", "Maharashtra"],
        "pune": ["Pune", "Hinjewadi", "Magarpatta", "Viman Nagar", "Kharadi", "Maharashtra"],
        "delhi": ["Delhi", "NCR", "Noida", "Gurgaon", "Gurugram", "Faridabad", "Delhi NCR"],
        "remote": ["Remote", "WFH", "Work From Home", "Anywhere", "Pan India"]
    }

    @classmethod
    def parse(
        cls,
        keywords: str,
        location: str = "India",
        timeframe: str = "past-24h",
        candidate_exp_years: int = 2,
        remote_only: bool = False
    ) -> SearchIntent:
        clean_kw = keywords.strip()
        kw_lower = clean_kw.lower()

        # 1. Detect Role Family
        matched_family = "GENERAL_SOFTWARE"
        required_tech = []
        negative_tech = []
        variants = [clean_kw]

        for fam_name, fam_data in cls.ROLE_FAMILIES.items():
            if any(re.search(r"\b" + re.escape(trig) + r"\b", kw_lower) for trig in fam_data["triggers"]):
                matched_family = fam_name
                required_tech = fam_data["required"]
                negative_tech = fam_data["negatives"]
                variants = fam_data["variants"]
                break

        if matched_family == "GENERAL_SOFTWARE":
            tokens = [t for t in re.findall(r'[a-zA-Z0-9.+]+', kw_lower) if t not in ["developer", "engineer", "hiring", "lead", "senior", "junior"]]
            required_tech = tokens if tokens else [clean_kw]
            variants = [clean_kw, f"{clean_kw} Developer", f"{clean_kw} Engineer"]

        # 2. Location Normalization & Clusters
        loc_clean = location.strip()
        loc_lower = loc_clean.lower()
        loc_variants = [loc_clean]

        for city_key, cluster in cls.LOCATION_CLUSTERS.items():
            if city_key in loc_lower or any(alias.lower() in loc_lower for alias in cluster):
                loc_variants = cluster
                loc_clean = cluster[0]
                break

        # 3. Resolve Timeframe
        max_age = get_max_age_minutes(timeframe)

        # 4. Standardize Target Role Name
        target_role = clean_kw
        target_role = re.sub(r'\b(hiring|urgent|immediate|jobs?|openings?)\b', '', target_role, flags=re.IGNORECASE).strip()
        if not target_role:
            target_role = clean_kw

        return SearchIntent(
            raw_query=keywords,
            target_role=target_role,
            role_family=matched_family,
            required_tech_signals=required_tech,
            negative_tech_signals=negative_tech,
            role_variants=variants,
            target_location=loc_clean,
            location_variants=loc_variants,
            timeframe=timeframe,
            max_age_minutes=max_age,
            candidate_exp_years=candidate_exp_years,
            remote_only=remote_only
        )
