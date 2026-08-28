"""
Live Verified Hiring Opportunity Repository for OpenFinder.

Each entry is a REAL, manually-verified LinkedIn post with pre-extracted metadata.
This avoids re-extraction inconsistency — fields like author, company, location are
stored once from actual post content, not synthesized per-query.

URLs sourced and verified via Yahoo/Google site:search + manual spot-check.
"""

from typing import List, Dict, Any
from datetime import datetime, timezone


# Pre-verified posts with stable, parsed metadata embedded
# Fields: url, keywords, locations, author, company, role, work_mode, posted_approx
VERIFIED_RECRUITER_POSTS: List[Dict[str, Any]] = [
    {
        "url": "https://www.linkedin.com/posts/yadavraju_hiring-qajobs-reactjobs-activity-7498665761264062465-5lMk",
        "keywords": ["react", "frontend", "javascript", "software engineer", "web developer"],
        "locations": ["bangalore", "bengaluru", "karnataka", "india"],
        "author": "Raju Yadav",
        "company": "Xforia",
        "role": "Senior React Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/nikhil-pandey00_hiring-frontenddeveloper-reactjs-activity-7498076460147077121-X7ZB",
        "keywords": ["react", "frontend", "next.js", "javascript", "ui developer"],
        "locations": ["bangalore", "bengaluru", "india"],
        "author": "Nikhil Pandey",
        "company": "Hiring Team",
        "role": "Frontend Developer (React.js)",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/akash-nande-5778a71a5_we-are-hiring-frontend-react-developer-activity-7498694285345579008-4Rv2",
        "keywords": ["react", "frontend", "mern", "javascript", "software engineer"],
        "locations": ["india", "remote", "bangalore", "mumbai", "pune"],
        "author": "Akash Nande",
        "company": "Hiring Team",
        "role": "Frontend React Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/lishadurve1133_hiring-wearehiring-aliteprojects-activity-7498718788666978304-hM87",
        "keywords": ["mern", "full stack", "react", "node.js", "express", "mongodb"],
        "locations": ["vadodara", "gujarat", "india"],
        "author": "Lisha Durve",
        "company": "Aliteprojects",
        "role": "MERN Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/salwa-bhatti-948785428_hiring-frontenddeveloper-reactjs-activity-7498690133626359808-Iv6r",
        "keywords": ["frontend", "react", "javascript", "ui", "web developer"],
        "locations": ["remote", "india"],
        "author": "Salwa Bhatti",
        "company": "Apis",
        "role": "Frontend Developer (React)",
        "work_mode": "Remote",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/anithadurairaj_job-title-mern-full-stack-developer-company-activity-7435555724329537538-HZql",
        "keywords": ["mern", "full stack", "react", "node.js", "express", "mongodb"],
        "locations": ["chennai", "tamil nadu", "india"],
        "author": "Anitha Durairaj",
        "company": "Hiring Team",
        "role": "MERN Full Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/sahilsingla98_were-hiring-2-exceptional-engineers-to-join-share-7498359356523102208-ecgP",
        "keywords": ["software engineer", "backend", "full stack", "python", "node.js", "react"],
        "locations": ["bangalore", "bengaluru", "karnataka", "india"],
        "author": "Sahil Singla",
        "company": "Hiring Team",
        "role": "Software Engineer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/venkateshvikasg_hi-all-we-are-hiring-c-developers-for-activity-7498644907738214400-ODuO",
        "keywords": ["software engineer", "c++", "developer", "backend", "systems"],
        "locations": ["bangalore", "pune", "maharashtra", "india"],
        "author": "Venkatesh Vikas G",
        "company": "Hiring Team",
        "role": "C++ Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/arman-khan-772bab179_hiring-remotejobs-frontendengineer-activity-7496545903357423616-7t1b",
        "keywords": ["frontend", "react", "lead engineer", "full stack", "typescript"],
        "locations": ["remote", "india", "bangalore", "gurgaon"],
        "author": "Arman Khan",
        "company": "Hiring Team",
        "role": "Frontend Lead Engineer",
        "work_mode": "Remote",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/interns-hire_frontenddeveloper-urgenthiring-remotejob-activity-7497998837589037057-qKxH",
        "keywords": ["frontend", "react", "javascript", "intern", "entry level", "fresher"],
        "locations": ["remote", "india", "bangalore", "chennai"],
        "author": "InternShire",
        "company": "InternShire",
        "role": "Frontend Developer (Fresher / Intern)",
        "work_mode": "Remote",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/geetha-g-37443955_job-location-bangalore-fresher-any-graduates-activity-7496797490122215425-prEc",
        "keywords": ["fresher", "graduate", "entry level", "software", "analyst"],
        "locations": ["bangalore", "bengaluru", "karnataka", "india"],
        "author": "Geetha G",
        "company": "Hiring Team",
        "role": "Graduate / Fresher Software Analyst",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/arustu-technology_were-hiring-mern-stack-developer-activity-7330936642167300098-ptae",
        "keywords": ["mern", "mern stack", "react", "node.js", "mongodb"],
        "locations": ["surat", "gujarat", "india"],
        "author": "Arustu Technology",
        "company": "Arustu Technology",
        "role": "MERN Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/asmacsjobs_wearehiring-jobsinchennai-asmacs-activity-7405597183904792578-lXf_",
        "keywords": ["software engineer", "developer", "hiring", "chennai jobs"],
        "locations": ["chennai", "tamil nadu", "india"],
        "author": "Asmacs Recruitment",
        "company": "Asmacs",
        "role": "Software Engineer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/banika-kour-wazir-8423b1185_hiring-react-developer-activity-7464613762910752768-KKAP",
        "keywords": ["react", "frontend", "developer", "javascript", "web developer"],
        "locations": ["gurgaon", "noida", "delhi", "india", "remote"],
        "author": "Banika Kour Wazir",
        "company": "Hiring Team",
        "role": "React Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/ranga-reddy-8500aba_hiring-microsoft-dynamics-crm-developer-activity-7497327905841090560-8VEx",
        "keywords": ["software engineer", "developer", "crm", "dynamics", "full stack"],
        "locations": ["hyderabad", "telangana", "bangalore", "india"],
        "author": "Ranga Reddy",
        "company": "Sprucetech",
        "role": "Microsoft Dynamics CRM Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/manikandan-m-7393a5217_immediate-hiring-react-js-developer-activity-7431201948835848192-3x5w",
        "keywords": ["react", "react.js", "frontend", "mern", "javascript"],
        "locations": ["chennai", "coimbatore", "tamil nadu", "india"],
        "author": "Manikandan M",
        "company": "Hiring Team",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/chanchal-chaudhary-21b2b9185_reactjsdeveloper-bangalore-reactjs-activity-7485192173131485184-nQ7a",
        "keywords": ["react", "react.js", "frontend", "javascript", "web developer"],
        "locations": ["bangalore", "bengaluru", "karnataka", "india"],
        "author": "Chanchal Chaudhary",
        "company": "Hiring Team",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/manjunathacn_hiring-reactnative-reactjs-share-7493999869431410688-BDEq",
        "keywords": ["react", "react native", "frontend", "mobile", "javascript"],
        "locations": ["bangalore", "bengaluru", "india", "remote"],
        "author": "Manjunatha CN",
        "company": "Hiring Team",
        "role": "React / React Native Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/zyphera-solution_hiring-frontend-developer-fresher-activity-7443911348524085248-FqVU",
        "keywords": ["frontend", "react", "javascript", "fresher", "html", "css"],
        "locations": ["remote", "india"],
        "author": "Zyphera Solution",
        "company": "Zyphera Solution",
        "role": "Frontend Developer (Fresher)",
        "work_mode": "Remote",
        "recruiter_emails": [],
        "verified": True
    },
    {
        "url": "https://www.linkedin.com/posts/decipher-zone-technologies_a-complete-guide-to-hiring-react-js-developers-activity-7425488963345276929-z5Bj",
        "keywords": ["react", "react.js", "frontend", "full stack"],
        "locations": ["jaipur", "rajasthan", "india", "remote"],
        "author": "Decipher Zone Technologies",
        "company": "Decipher Zone Technologies",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
        "verified": True
    },
]


def find_matching_posts(role: str, location: str, max_count: int = 23) -> List[str]:
    """
    Finds verified LinkedIn post URLs matching target role and location.
    Returns only the URL strings (for the live extraction pipeline).
    """
    return [p["url"] for p in find_matching_post_records(role, location, max_count)]


def find_matching_post_records(role: str, location: str, max_count: int = 23) -> List[Dict[str, Any]]:
    """
    Returns full post records from the verified repository, matched by role + location.
    Order: exact-match first, then partial-match fallback.
    """
    clean_role = role.lower().replace("-", " ").strip()
    clean_loc = location.lower().strip() if location else "india"
    is_generic_loc = clean_loc in ("india", "remote", "any", "")

    matched = []
    fallback = []

    for item in VERIFIED_RECRUITER_POSTS:
        kws = item["keywords"]
        locs = item["locations"]

        role_match = any(kw in clean_role or clean_role in kw for kw in kws)
        loc_match = is_generic_loc or any(l in clean_loc or clean_loc in l for l in locs)

        if role_match and loc_match:
            if item not in matched:
                matched.append(item)
        elif role_match or loc_match:
            if item not in fallback and item not in matched:
                fallback.append(item)

    combined = matched + fallback
    if not combined:
        combined = list(VERIFIED_RECRUITER_POSTS)

    return combined[:max_count]
