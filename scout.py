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
from core.post_extractor import LinkedInPostExtractor


def main():
    parser = argparse.ArgumentParser(
        description="🎯 OpenFinder CLI - Search Live LinkedIn Jobs & Match Your Resume",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scout.py "React Developer" "Bangalore"
  python scout.py "Python FastAPI" "Remote" --results 5
  python scout.py --resume my_resume.pdf --location "Chennai"
  python scout.py --post "https://www.linkedin.com/posts/..."
        """
    )
    parser.add_argument("role", nargs="?", default="Software Engineer", help="Job role / keywords (e.g. 'React Developer', 'Python Django')")
    parser.add_argument("pos_location", nargs="?", default=None, help="Location positional arg (e.g. 'Bangalore', 'Chennai')")
    parser.add_argument("--location", "-l", type=str, default=None, help="Location (e.g. 'Bangalore', 'Chennai', 'Remote', 'India')")
    parser.add_argument("--resume", "-r", type=str, help="Path to candidate resume PDF for instant ATS match analysis")
    parser.add_argument("--post", "-p", type=str, help="Direct LinkedIn post URL to extract HR email, phone & generate pitch")
    parser.add_argument("--results", "-n", type=int, default=5, help="Number of job posts to fetch (default: 5)")
    parser.add_argument("--remote", action="store_true", help="Filter for remote jobs only")

    args = parser.parse_args()
    finder = LinkedInFinder()
    target_location = args.location or args.pos_location or "India"

    # Mode 0: Direct LinkedIn Post URL Extractor
    if args.post:
        candidate_profile = None
        if args.resume:
            pdf_path = Path(args.resume)
            if pdf_path.exists():
                print(f"📄 Parsing Candidate Resume: {pdf_path.name}...")
                candidate_profile = ResumeParser().parse(str(pdf_path))
                print(f"   Candidate: {candidate_profile.get('candidate_name')} | Exp: {candidate_profile.get('years_of_experience')} Yrs")

        print("=" * 65)
        print(f"🔗 Extracting Intelligence from LinkedIn Post...")
        print("=" * 65)
        post_data = LinkedInPostExtractor.extract_from_url(
            url=args.post,
            candidate_profile=candidate_profile
        )
        if "error" in post_data:
            print(f"❌ {post_data['error']}")
            return

        print(f"• Author: {post_data.get('author')}")
        print(f"• Role: {post_data.get('job_role')}")
        print(f"• Location: {post_data.get('location')}")
        print(f"• Recruiter Emails: {', '.join(post_data.get('recruiter_emails', [])) or 'None found'}")
        print(f"• Contact Phone: {', '.join(post_data.get('contact_numbers', [])) or 'None found'}")
        print(f"• Post Skills Required: {', '.join(post_data.get('detected_skills', []))}")

        # If matched against resume, show ATS match data
        if "match_analysis" in post_data:
            ma = post_data["match_analysis"]
            print("\n🎯 ATS Match Analysis against Your Resume:")
            print(f"  • Match Score: {ma['match_score']}% ({ma['match_grade']})")
            print(f"  • Matched Skills: {', '.join(ma.get('matched_skills', []))}")
            if ma.get("missing_skills"):
                print(f"  • Missing Skills to Highlight: {', '.join(ma.get('missing_skills', []))}")
            if ma.get("ats_recommendations"):
                print(f"  • ATS Advice: {ma['ats_recommendations'][0]}")

        print("\n✉️ Customized Outreach Pitch:")
        print(f"\"{post_data.get('tailored_outreach_pitches', {}).get('linkedin_connection_note_300_chars')}\"")
        return

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
