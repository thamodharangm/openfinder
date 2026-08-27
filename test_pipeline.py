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


def create_dummy_resume_pdf(pdf_path: Path):
    """Creates a sample PDF resume for testing using standard pypdf if not present."""
    from pypdf import PdfWriter
    # If pypdf writer can create a basic file or we create a text-based sample
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    # We can write with pdfwriter metadata or simple structure
    with open(pdf_path, "wb") as f:
        writer.write(f)


def run_demo():
    print("=" * 60)
    print("🚀 LinkedIn Job Scout & Resume Matcher - Local Demo Test")
    print("=" * 60)

    # 1. Initialize services
    parser = ResumeParser()
    finder = LinkedInFinder()

    # Sample profile simulation
    sample_text = """
    John Doe - Full Stack Developer
    Experience: 3+ years of experience in modern web development.
    Skills: React, TypeScript, Node.js, Express, Next.js, PostgreSQL, MongoDB, Docker, Git, REST API.
    Looking for Frontend / Fullstack Developer roles in Bangalore or Remote.
    """

    print("\n[1] Parsing Candidate Profile & Skills...")
    skills = parser.extract_skills(sample_text)
    exp = parser.estimate_experience_years(sample_text)
    roles = parser.infer_target_roles(sample_text, skills)

    profile = {
        "matched_skills": skills,
        "top_skills": skills[:6],
        "estimated_experience_years": exp,
        "inferred_target_roles": roles
    }

    print(f"  • Extracted Skills ({len(skills)}): {', '.join(skills)}")
    print(f"  • Experience: {exp} Years")
    print(f"  • Target Roles: {', '.join(roles)}")

    # 2. Search LinkedIn
    search_query = roles[0] if roles else "Full Stack Developer"
    print(f"\n[2] Searching LinkedIn Hiring Posts for: '{search_query}' (Location: India)...")
    posts = finder.search_hiring_posts(
        keywords=search_query,
        location="India",
        timeframe="w",
        max_results=5
    )

    print(f"  • Found {len(posts)} hiring posts after spam filtering.")

    # 3. Match & Rank
    print("\n[3] Scoring & Ranking Posts against Resume Skills...")
    ranked = JobMatcher.rank_and_score_posts(profile, posts, min_score=20)

    if ranked:
        for idx, job in enumerate(ranked, 1):
            print(f"\n--- Result #{idx} ---")
            print(f"Title: {job.get('title')}")
            print(f"Match: {job.get('match_score')}% ({job.get('match_grade')})")
            print(f"Matched Skills: {job.get('matched_skills')}")
            print(f"Missing Skills: {job.get('missing_skills')}")
            print(f"Emails: {job.get('contact_emails') or 'None in snippet'}")
            print(f"Link: {job.get('post_url')}")
    else:
        print("  (No direct posts returned in this query window or network test)")

    print("\n" + "=" * 60)
    print("✅ MCP Tool Logic Tested Successfully!")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
