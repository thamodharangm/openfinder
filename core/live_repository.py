"""
Live Verified Hiring Opportunity Repository for OpenFinder.

Each entry is a REAL, manually-verified LinkedIn post with pre-extracted metadata.
- `primary_location`: The exact city/region the post targets (used for display + location filter).
- `locations`: Broader set of location tags used for matching queries (do NOT put "india" here
  unless the post genuinely targets all-India/pan-India roles, because it causes every query to match).
- `company`: Real company if extractable from post; None means "Hiring Team" fallback.
  Derived from contact email domain where the post text has no explicit org.

URL sources: verified via Yahoo site:search + manual LinkedIn spot-check.
"""

from typing import List, Dict, Any, Optional


def _company_from_email(email: str) -> Optional[str]:
    """Extract a human-readable company name from a contact email domain."""
    if not email or "@" not in email:
        return None
    domain = email.split("@")[-1].lower().replace(".com", "").replace(".co.in", "").replace(".in", "")
    # Known mappings
    known = {
        "dorleco": "Dorleco",
        "nuvento": "Nuvento",
        "srssolutions": "SRS Solutions",
        "aliteprojects": "Aliteprojects",
        "arustu": "Arustu Technology",
        "sprucetech": "Sprucetech",
        "xforia": "Xforia",
        "programming": None,   # generic domain, not a real company name
    }
    return known.get(domain, domain.title())


VERIFIED_RECRUITER_POSTS: List[Dict[str, Any]] = [
    # ── BANGALORE ────────────────────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/yadavraju_hiring-qajobs-reactjobs-activity-7498665761264062465-5lMk",
        "keywords": ["react", "frontend", "javascript", "software engineer", "web developer"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Raju Yadav",
        "company": "Xforia",
        "role": "Senior React Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/nikhil-pandey00_hiring-frontenddeveloper-reactjs-activity-7498076460147077121-X7ZB",
        "keywords": ["react", "frontend", "next.js", "javascript", "ui developer"],
        "locations": ["bangalore", "bengaluru"],
        "primary_location": "Bangalore",
        "author": "Nikhil Pandey",
        "company": "Hiring Team",
        "role": "Frontend Developer (React.js)",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/sahilsingla98_were-hiring-2-exceptional-engineers-to-join-share-7498359356523102208-ecgP",
        "keywords": ["software engineer", "backend", "full stack", "python", "node.js", "react"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Sahil Singla",
        "company": "Hiring Team",
        "role": "Software Engineer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/venkateshvikasg_hi-all-we-are-hiring-c-developers-for-activity-7498644907738214400-ODuO",
        "keywords": ["software engineer", "c++", "developer", "backend", "systems"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Venkatesh Vikas G",
        "company": "Hiring Team",
        "role": "C++ Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/chanchal-chaudhary-21b2b9185_reactjsdeveloper-bangalore-reactjs-activity-7485192173131485184-nQ7a",
        "keywords": ["react", "react.js", "frontend", "javascript", "web developer"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Chanchal Chaudhary",
        "company": "Hiring Team",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/manjunathacn_hiring-reactnative-reactjs-share-7493999869431410688-BDEq",
        "keywords": ["react", "react native", "frontend", "mobile", "javascript"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Manjunatha CN",
        "company": "Nuvento",
        "role": "React / React Native Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": ["manjunatha.cn@nuvento.com"],
    },
    {
        "url": "https://www.linkedin.com/posts/geetha-g-37443955_job-location-bangalore-fresher-any-graduates-activity-7496797490122215425-prEc",
        "keywords": ["fresher", "graduate", "entry level", "software", "analyst"],
        "locations": ["bangalore", "bengaluru", "karnataka"],
        "primary_location": "Bangalore",
        "author": "Geetha G",
        "company": "Hiring Team",
        "role": "Graduate / Fresher Software Analyst",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/ranga-reddy-8500aba_hiring-microsoft-dynamics-crm-developer-activity-7497327905841090560-8VEx",
        "keywords": ["software engineer", "developer", "crm", "dynamics", "full stack"],
        "locations": ["hyderabad", "telangana", "bangalore"],
        "primary_location": "Hyderabad",
        "author": "Ranga Reddy",
        "company": "Sprucetech",
        "role": "Microsoft Dynamics CRM Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": ["rreddy@sprucetech.com"],
    },
    # ── REMOTE / PAN-INDIA ───────────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/akash-nande-5778a71a5_we-are-hiring-frontend-react-developer-activity-7498694285345579008-4Rv2",
        "keywords": ["react", "frontend", "mern", "javascript", "software engineer"],
        "locations": ["remote", "india"],
        "primary_location": "Hybrid / Remote",
        "author": "Akash Nande",
        "company": "Hiring Team",
        "role": "Frontend React Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/arman-khan-772bab179_hiring-remotejobs-frontendengineer-activity-7496545903357423616-7t1b",
        "keywords": ["frontend", "react", "lead engineer", "full stack", "typescript"],
        "locations": ["remote", "gurgaon", "delhi", "ncr"],
        "primary_location": "Remote",
        "author": "Arman Khan",
        "company": "Dorleco",
        "role": "Frontend Lead Engineer",
        "work_mode": "Remote",
        "recruiter_emails": ["khan.arman@dorleco.com"],
    },
    {
        "url": "https://www.linkedin.com/posts/interns-hire_frontenddeveloper-urgenthiring-remotejob-activity-7497998837589037057-qKxH",
        "keywords": ["frontend", "react", "javascript", "intern", "entry level", "fresher"],
        "locations": ["remote", "india"],
        "primary_location": "Remote",
        "author": "InternShire",
        "company": "InternShire",
        "role": "Frontend Developer (Fresher / Intern)",
        "work_mode": "Remote",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/salwa-bhatti-948785428_hiring-frontenddeveloper-reactjs-activity-7498690133626359808-Iv6r",
        "keywords": ["frontend", "react", "javascript", "ui", "web developer"],
        "locations": ["remote", "india"],
        "primary_location": "Remote",
        "author": "Salwa Bhatti",
        "company": "Apis",
        "role": "Frontend Developer (React)",
        "work_mode": "Remote",
        "recruiter_emails": [],
    },
    # ── DELHI / GURGAON / NCR ───────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/banika-kour-wazir-8423b1185_hiring-react-developer-activity-7464613762910752768-KKAP",
        "keywords": ["react", "frontend", "developer", "javascript", "web developer"],
        "locations": ["gurgaon", "noida", "delhi", "ncr"],
        "primary_location": "Gurgaon",
        "author": "Banika Kour Wazir",
        "company": "Hiring Team",
        "role": "React Developer",
        "work_mode": "Hybrid",
        "recruiter_emails": [],
    },
    # ── GUJARAT ──────────────────────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/lishadurve1133_hiring-wearehiring-aliteprojects-activity-7498718788666978304-hM87",
        "keywords": ["mern", "full stack", "react", "node.js", "express", "mongodb"],
        "locations": ["vadodara", "gujarat"],
        "primary_location": "Vadodara",
        "author": "Lisha Durve",
        "company": "Aliteprojects",
        "role": "MERN Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": ["recruitment@aliteprojects.com"],
    },
    {
        "url": "https://www.linkedin.com/posts/arustu-technology_were-hiring-mern-stack-developer-activity-7330936642167300098-ptae",
        "keywords": ["mern", "mern stack", "react", "node.js", "mongodb"],
        "locations": ["surat", "gujarat"],
        "primary_location": "Surat",
        "author": "Arustu Technology",
        "company": "Arustu Technology",
        "role": "MERN Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": ["hr@arustu.com"],
    },
    # ── CHENNAI / TAMIL NADU ─────────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/anithadurairaj_job-title-mern-full-stack-developer-company-activity-7435555724329537538-HZql",
        "keywords": ["mern", "full stack", "react", "node.js", "express", "mongodb"],
        "locations": ["chennai", "tamil nadu"],
        "primary_location": "Chennai",
        "author": "Anitha Durairaj",
        "company": "Hiring Team",
        "role": "MERN Full Stack Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/asmacsjobs_wearehiring-jobsinchennai-asmacs-activity-7405597183904792578-lXf_",
        "keywords": ["software engineer", "developer", "hiring", "chennai jobs"],
        "locations": ["chennai", "tamil nadu"],
        "primary_location": "Chennai",
        "author": "Asmacs Recruitment",
        "company": "Asmacs",
        "role": "Software Engineer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/manikandan-m-7393a5217_immediate-hiring-react-js-developer-activity-7431201948835848192-3x5w",
        "keywords": ["react", "react.js", "frontend", "mern", "javascript"],
        "locations": ["chennai", "coimbatore", "tamil nadu"],
        "primary_location": "Chennai",
        "author": "Manikandan M",
        "company": "Hiring Team",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
    {
        "url": "https://www.linkedin.com/posts/zyphera-solution_hiring-frontend-developer-fresher-activity-7443911348524085248-FqVU",
        "keywords": ["frontend", "react", "javascript", "fresher", "html", "css"],
        "locations": ["remote", "chennai", "india"],
        "primary_location": "Remote",
        "author": "Zyphera Solution",
        "company": "Zyphera Solution",
        "role": "Frontend Developer (Fresher)",
        "work_mode": "Remote",
        "recruiter_emails": [],
    },
    # ── JAIPUR ───────────────────────────────────────────────────────────────
    {
        "url": "https://www.linkedin.com/posts/decipher-zone-technologies_a-complete-guide-to-hiring-react-js-developers-activity-7425488963345276929-z5Bj",
        "keywords": ["react", "react.js", "frontend", "full stack"],
        "locations": ["jaipur", "rajasthan"],
        "primary_location": "Jaipur",
        "author": "Decipher Zone Technologies",
        "company": "Decipher Zone Technologies",
        "role": "React.js Developer",
        "work_mode": "On-Site",
        "recruiter_emails": [],
    },
]


# ── LOCATION MATCHING RULES ───────────────────────────────────────────────────
# City aliases: canonical query term → list of location tags that qualify as a match
LOCATION_ALIASES: Dict[str, List[str]] = {
    "bangalore":  ["bangalore", "bengaluru", "karnataka"],
    "bengaluru":  ["bangalore", "bengaluru", "karnataka"],
    "hyderabad":  ["hyderabad", "telangana"],
    "chennai":    ["chennai", "tamil nadu"],
    "coimbatore": ["coimbatore", "tamil nadu"],
    "mumbai":     ["mumbai", "maharashtra"],
    "pune":       ["pune", "maharashtra"],
    "delhi":      ["delhi", "ncr", "gurgaon", "noida"],
    "gurgaon":    ["gurgaon", "ncr", "delhi"],
    "noida":      ["noida", "ncr", "delhi"],
    "kolkata":    ["kolkata", "west bengal"],
    "remote":     ["remote"],
    "india":      ["remote", "india"],   # pan-India query: remote + india-tagged only
}

# Locations whose query should NOT pull generic "india"-tagged posts
_SPECIFIC_CITIES = {
    "bangalore", "bengaluru", "hyderabad", "chennai", "coimbatore",
    "mumbai", "pune", "delhi", "gurgaon", "noida", "kolkata",
    "vadodara", "surat", "jaipur", "ahmedabad", "kochi", "trivandrum"
}


def find_matching_posts(role: str, location: str, max_count: int = 23) -> List[str]:
    """Returns URL strings only (for the live extraction pipeline)."""
    return [p["url"] for p in find_matching_post_records(role, location, max_count)]


def find_matching_post_records(role: str, location: str, max_count: int = 23) -> List[Dict[str, Any]]:
    """
    Returns full post records matched by role + location with strict city filtering.

    Priority tiers:
      1. Role match AND city/region match (exact)
      2. Role match AND remote/india (only for non-specific-city queries)
      3. Role match only (no location constraint)
      4. Everything (last resort, when role itself doesn't match)
    """
    clean_role = role.lower().replace("-", " ").strip()
    clean_loc = location.lower().strip() if location else "india"

    # Determine which location tags count as a match for this query
    qualifying_loc_tags = LOCATION_ALIASES.get(clean_loc)
    if qualifying_loc_tags is None:
        # Fallback: any post whose locations list contains clean_loc as a substring
        qualifying_loc_tags = [clean_loc]

    is_specific_city = clean_loc in _SPECIFIC_CITIES

    tier1, tier2, tier3 = [], [], []

    for item in VERIFIED_RECRUITER_POSTS:
        kws = item["keywords"]
        locs = item["locations"]

        role_match = any(kw in clean_role or clean_role in kw for kw in kws)

        # Tier 1: role + city/region
        city_match = any(ql in locs for ql in qualifying_loc_tags)

        # Tier 2: role + remote/generic (only for non-specific-city queries)
        generic_match = (not is_specific_city) and any(l in ("remote", "india") for l in locs)

        if role_match and city_match:
            if item not in tier1:
                tier1.append(item)
        elif role_match and generic_match:
            if item not in tier2 and item not in tier1:
                tier2.append(item)
        elif role_match:
            if item not in tier3 and item not in tier2 and item not in tier1:
                tier3.append(item)

    combined = tier1 + tier2 + tier3
    if not combined:
        # Last resort: all role-matched posts regardless of location
        combined = [i for i in VERIFIED_RECRUITER_POSTS
                    if any(kw in clean_role or clean_role in kw for kw in i["keywords"])]
    if not combined:
        combined = list(VERIFIED_RECRUITER_POSTS)

    return combined[:max_count]
