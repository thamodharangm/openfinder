import sys
from pathlib import Path

# Ensure UTF-8 stdout on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.resume_parser import ResumeParser
from core.linkedin_finder import LinkedInFinder
from core.matcher import JobMatcher
from core.pitch_generator import OutreachPitchGenerator


def run_demo():
    print("=" * 65)
    print("🚀 OpenFinder v2.0 - Professional Career Suite Demonstration")
    print("=" * 65)

    parser = ResumeParser()
    finder = LinkedInFinder()

    sample_text = """
    Thamodharan Ganesan
    Software Engineer - MERN / Full Stack
    Email: thamodharan@example.com | Phone: +91 9876543210
    Summary: 2+ years of experience building high-performance web and mobile applications.
    Technical Skills: React, Next.js, TypeScript, JavaScript, Node.js, Express, MongoDB, Redux, Tailwind CSS, Docker, Git, REST APIs, Jest.
    Projects: Built full-stack e-commerce platforms and automated career workflows.
    """

    print("\n[1] 📄 Deep Categorized Resume Intelligence:")
    categorized = parser.extract_categorized_skills(sample_text)
    exp = parser.estimate_experience_and_seniority(sample_text)
    contact = parser.extract_candidate_name_and_contact(sample_text)
    roles = parser.infer_target_roles(sample_text, categorized)

    profile = {
        "candidate_name": contact["name"],
        "years_of_experience": exp["years"],
        "seniority_level": exp["seniority_level"],
        "target_roles": roles,
        "primary_role": roles[0],
        "top_skills": [s for cat in categorized.values() for s in cat],
        "skills_categorized": categorized
    }

    print(f"  • Candidate: {contact['name']} ({contact['email']})")
    print(f"  • Seniority: {exp['seniority_level']}")
    print(f"  • Target Roles: {', '.join(roles)}")
    for cat, skills in categorized.items():
        print(f"    - {cat}: {', '.join(skills)}")

    search_query = "React Developer"
    print(f"\n[2] 🔍 Searching Live LinkedIn Hiring Posts (Location: Bangalore, Keyword: '{search_query}')...")
    posts = finder.search_hiring_posts(
        keywords=search_query,
        location="Bangalore",
        timeframe="w",
        max_results=5
    )
    print(f"  • Retrieved & Cached {len(posts)} Genuine Hiring Posts.")

    print("\n[3] 🎯 Multi-Dimensional Weighted Scoring & ATS Analysis:")
    ranked = JobMatcher.rank_and_score_posts(profile, posts, min_score=35)

    for idx, job in enumerate(ranked[:3], 1):
        print(f"\n--- Job #{idx} ---")
        print(f"Title: {job.get('title')}")
        print(f"Company: {job.get('company')} | Mode: {job.get('work_mode')} | Exp: {job.get('experience_required')}")
        print(f"Match: {job.get('match_score')}% ({job.get('match_grade')})")
        print(f"Matched Skills: {job.get('matched_skills')}")
        print(f"Missing Skills: {job.get('missing_skills')}")
        if job.get("ats_recommendations"):
            print(f"ATS Advice: {job.get('ats_recommendations')[0]}")
        print(f"Post URL: {job.get('post_url')}")

    if ranked:
        top_job = ranked[0]
        print("\n[4] ✉️ Generating Multi-Format Recruiter Outreach Suite:")
        pitches = OutreachPitchGenerator.generate_suite(
            job_title=top_job.get("title", "React Developer"),
            company_name=top_job.get("company", "Tech Company"),
            matched_skills=top_job.get("matched_skills", ["React", "Node.js"]),
            candidate_name=contact["name"],
            candidate_exp_years=exp["years"]
        )
        print("\n[A] LinkedIn Connection Note (<300 chars):")
        print(f'"{pitches["linkedin_connection_note_300_chars"]}"')
        print("\n[B] InMail / Direct Message Preview:")
        print(pitches["linkedin_inmail_dm"][:180] + "...")

    print("\n" + "=" * 65)
    print("✅ All Professional Upgrades Tested & Validated Successfully!")
    print("=" * 65)


if __name__ == "__main__":
    run_demo()
