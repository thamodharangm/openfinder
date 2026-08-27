import sys
import argparse
from pathlib import Path

# Ensure UTF-8 stdout on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.linkedin_finder import LinkedInFinder
from core.resume_parser import ResumeParser
from core.matcher import JobMatcher
from core.pitch_generator import OutreachPitchGenerator


def main():
    parser = argparse.ArgumentParser(
        description="🎯 OpenFinder CLI - Search Live LinkedIn Jobs & Match Your Resume",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scout.py "React Developer" "Bangalore"
  python scout.py "Python FastAPI" "Remote" --results 5
  python scout.py --resume my_resume.pdf --location "Chennai"
        """
    )
    parser.add_argument("role", nargs="?", default="Software Engineer", help="Job role / keywords (e.g. 'React Developer', 'Python Django')")
    parser.add_argument("pos_location", nargs="?", default=None, help="Location positional arg (e.g. 'Bangalore', 'Chennai')")
    parser.add_argument("--location", "-l", type=str, default=None, help="Location (e.g. 'Bangalore', 'Chennai', 'Remote', 'India')")
    parser.add_argument("--resume", "-r", type=str, help="Path to candidate resume PDF for instant ATS match analysis")
    parser.add_argument("--results", "-n", type=int, default=5, help="Number of job posts to fetch (default: 5)")
    parser.add_argument("--remote", action="store_true", help="Filter for remote jobs only")

    args = parser.parse_args()
    finder = LinkedInFinder()
    target_location = args.location or args.pos_location or "India"

    # Mode 1: Resume Matcher
    if args.resume:
        pdf_path = Path(args.resume)
        if not pdf_path.exists():
            print(f"❌ Error: Resume file not found at '{pdf_path}'")
            sys.exit(1)

        print("=" * 65)
        print(f"📄 Analyzing Resume: {pdf_path.name}")
        print("=" * 65)
        parser_engine = ResumeParser()
        profile = parser_engine.parse(str(pdf_path))

        print(f"• Candidate: {profile.get('candidate_name', 'Candidate')}")
        print(f"• Experience: {profile.get('years_of_experience', 2)} Yrs ({profile.get('seniority_level', 'Mid-Level')})")
        print(f"• Target Roles: {', '.join(profile.get('target_roles', []))}")
        print(f"• Top Skills: {', '.join(profile.get('top_skills', [])[:8])}...")

        search_kw = profile.get("primary_role", args.role)
        top_skills = profile.get("top_skills", [])
        if len(top_skills) >= 2:
            search_kw = f"{top_skills[0]} {top_skills[1]}"

        print(f"\n🔍 Searching Live Matching Jobs ({search_kw} in {target_location})...")
        posts = finder.search_hiring_posts(
            keywords=search_kw,
            location=target_location,
            remote_only=args.remote,
            max_results=args.results * 2
        )

        ranked = JobMatcher.rank_and_score_posts(profile, posts, min_score=30)
        print(f"🎯 Found {len(ranked)} Matched Jobs:\n")

        for idx, job in enumerate(ranked[:args.results], 1):
            print(f"[{idx}] {job['title']} @ {job['company']}")
            print(f"    Match Score: {job['match_score']}% ({job['match_grade']})")
            print(f"    Matched Skills: {job.get('matched_skills', [])}")
            if job.get("missing_skills"):
                print(f"    Missing Skills: {job.get('missing_skills', [])}")
            print(f"    Apply Link: {job['post_url']}")
            print("-" * 65)

    # Mode 2: Direct Keyword Search
    else:
        print("=" * 65)
        print(f"🔍 Searching Live LinkedIn Jobs: '{args.role}' in '{target_location}'...")
        print("=" * 65)

        posts = finder.search_hiring_posts(
            keywords=args.role,
            location=target_location,
            remote_only=args.remote,
            max_results=args.results
        )

        if not posts:
            print("⚠️ No job posts found for this query. Try broader keywords or location.")
            return

        print(f"✅ Found {len(posts)} Verified Live Jobs:\n")
        for idx, post in enumerate(posts, 1):
            print(f"[{idx}] {post['title']}")
            print(f"    🏢 Company: {post['company']} | 📍 Mode: {post['work_mode']}")
            if post.get("required_skills"):
                print(f"    🛠️ Skills: {', '.join(post['required_skills'])}")
            print(f"    🔗 Apply Link: {post['post_url']}")
            print("-" * 65)


if __name__ == "__main__":
    main()
