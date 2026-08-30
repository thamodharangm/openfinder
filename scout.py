"""
scout.py
========
Production-grade Command Line Interface (CLI) for OpenFinder.

Capabilities:
- Live LinkedIn Recruiter Hiring Posts Discovery (`--search-posts`, `--role`, `--location`, `--timeframe`).
- Direct LinkedIn /posts/ URL Analyzer & Intelligence Extractor (`--post <url>`).
- Candidate Resume Parser & Instant ATS Match Scoring (`--resume <path.pdf>` or `--resume-text <text>`).
- Standalone Recruiter Pitch Generator (`--pitch`).
- Script-friendly structured JSON output mode (`--json`).
- Cross-platform UTF-8 terminal encoding and graceful error boundaries.
"""

import argparse
import json
import logging
from pathlib import Path
import sys

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

from dotenv import load_dotenv
load_dotenv()

from core.linkedin_finder import LinkedInFinder
from core.pitch_generator import OutreachPitchGenerator
from core.post_extractor import LinkedInPostExtractor
from core.service import OpenFinderService

logging.basicConfig(level=logging.WARNING)


def format_cli_banner():
    print("=" * 75)
    print("🎯 OpenFinder - Universal MCP Connector for Freshers & Experienced (Claude & ChatGPT)")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(
        description="🎯 OpenFinder CLI - Real-Time LinkedIn Hiring Scout & ATS Matcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Search fresh live hiring posts:
  python scout.py "React Developer" "Bangalore" --timeframe past-24h

  # 2. Search with candidate resume PDF for ATS match scoring:
  python scout.py "Python FastAPI" "Remote" --resume my_resume.pdf

  # 3. Analyze a single LinkedIn post URL:
  python scout.py --post "https://www.linkedin.com/posts/..." --resume my_resume.pdf

  # 4. Generate multi-persona recruiter pitches:
  python scout.py --pitch --role "Senior Python Engineer" --company "AcmeTech" --skills "Python, FastAPI, Docker"

  # 5. Output raw JSON for script piping:
  python scout.py "Golang Developer" "Hyderabad" --json
        """
    )
    parser.add_argument("pos_role", nargs="?", default=None, help="Job role or technical skills (e.g. 'React Developer', 'Python FastAPI')")
    parser.add_argument("pos_location", nargs="?", default=None, help="Location positional argument (e.g. 'Bangalore', 'Chennai')")
    parser.add_argument("--role", type=str, default=None, help="Target job role (e.g. 'React Developer', 'Senior Python Engineer')")
    parser.add_argument("--location", "-l", type=str, default=None, help="Target city / location (e.g. 'Bangalore', 'Remote', 'India')")
    parser.add_argument("--timeframe", "-t", "--date-posted", "-d", type=str, default="past-24h", help="Freshness filter ('past-1h', 'past-4h', 'past-12h', 'past-24h', 'past-3d', 'past-7d')")
    parser.add_argument("--resume", "-r", type=str, default=None, help="Path to candidate resume PDF for ATS match scoring")
    parser.add_argument("--resume-text", type=str, default=None, help="Plain text candidate CV content for ATS scoring")
    parser.add_argument("--post", "-p", type=str, default=None, help="Direct LinkedIn post URL to extract intelligence & pitch")
    parser.add_argument("--search-posts", "--sp", type=str, default=None, help="Search global LinkedIn /posts/ by raw keyword query")
    parser.add_argument("--pitch", action="store_true", help="Generate 1-click recruiter outreach pitch suite")
    parser.add_argument("--company", type=str, default="Hiring Team", help="Company name for pitch generation")
    parser.add_argument("--skills", type=str, default="React, TypeScript", help="Matched skills for pitch generation")
    parser.add_argument("--candidate-name", type=str, default="Candidate", help="Candidate full name")
    parser.add_argument("--exp-years", type=int, default=2, help="Candidate years of experience")
    parser.add_argument("--results", "-n", type=int, default=10, help="Number of opportunities to return (default: 10)")
    parser.add_argument("--remote", action="store_true", help="Filter for remote jobs only")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()
    service = OpenFinderService()
    target_role = args.role or args.pos_role or "Software Engineer"
    target_location = args.location or args.pos_location or ("Remote" if args.remote else "India")

    # =========================================================================
    # Mode 1: Recruiter Pitch Suite Generator (--pitch)
    # =========================================================================
    if args.pitch:
        skills_list = [s.strip() for s in args.skills.split(",") if s.strip()]
        pitches = OutreachPitchGenerator.generate_suite(
            job_title=target_role,
            company_name=args.company,
            matched_skills=skills_list,
            candidate_name=args.candidate_name,
            candidate_exp_years=args.exp_years
        )
        if args.json:
            print(json.dumps({"status": "success", "pitches": pitches}, indent=2))
            return

        format_cli_banner()
        print(f"✉️ Recruiter Outreach Suite for '{target_role}' @ '{args.company}'\n")
        print("📌 [1] LinkedIn Connection Note (<300 chars):")
        print(f"\"{pitches['linkedin_connection_note_300_chars']}\"\n")
        print("📌 [2] LinkedIn InMail / Direct Message:")
        print(f"{pitches['linkedin_inmail_dm']}\n")
        print("📌 [3] Formal Cover Email:")
        print("-" * 50)
        print(f"Subject: {pitches['email_subject']}")
        print(pitches['formal_cover_email'])
        print("-" * 50)
        print("📌 [4] 1-Click Mailbox Deep Links:")
        print(f" • Native Mail:   {pitches['mailto_url']}")
        print(f" • Gmail Web:     {pitches['gmail_web_url']}")
        print(f" • Outlook Web:   {pitches['outlook_web_url']}")
        return

    # =========================================================================
    # Mode 2: Direct LinkedIn Post URL Analyzer (--post)
    # =========================================================================
    if args.post:
        candidate_profile = None
        if args.resume:
            pdf_path = Path(args.resume)
            if pdf_path.exists():
                candidate_profile = service.resume_parser.parse(str(pdf_path))
        elif args.resume_text:
            candidate_profile = service.resume_parser.parse_from_text(args.resume_text)

        post_data = LinkedInPostExtractor.extract_from_url(
            url=args.post,
            target_role=target_role,
            target_location=target_location,
            candidate_profile=candidate_profile
        )

        if args.json:
            print(json.dumps(post_data, indent=2))
            return

        format_cli_banner()
        print("🔗 Extracting Intelligence from LinkedIn Post...\n")
        print(f"• Poster / Recruiter: {post_data.get('author')}")
        print(f"• Hiring Company:     {post_data.get('company')}")
        print(f"• Job Role:           {post_data.get('job_role')}")
        print(f"• Location:           {post_data.get('location')}")
        print(f"• Posted:             {post_data.get('posted_time', 'Recently')}")
        print(f"• Recruiter Emails:   {', '.join(post_data.get('recruiter_emails', [])) or 'None found (DM required)'}")
        print(f"• Contact Phone:      {', '.join(post_data.get('contact_numbers', [])) or 'None found'}")
        print(f"• Required Skills:    {', '.join(post_data.get('detected_skills', []))}")

        if "match_analysis" in post_data:
            ma = post_data["match_analysis"]
            print("\n🎯 ATS Match Analysis against Your Resume:")
            print(f"  • Match Score:    {ma['match_score']}% ({ma.get('match_grade', 'B')})")
            print(f"  • Matched Skills: {', '.join(ma.get('matched_skills', []))}")
            if ma.get("missing_skills"):
                print(f"  • Missing Skills: {', '.join(ma.get('missing_skills', []))}")
            if ma.get("ats_recommendations"):
                print(f"  • ATS Advice:     {ma['ats_recommendations'][0]}")

        pitches = post_data.get('tailored_outreach_pitches', {})
        if pitches:
            print("\n✉️ Tailored Outreach Connection Note:")
            print(f"\"{pitches.get('linkedin_connection_note_300_chars')}\"")
        return

    # =========================================================================
    # Mode 3: Opportunity Search with Resume or Query
    # =========================================================================
    candidate_profile = None
    if args.resume:
        pdf_path = Path(args.resume)
        if not pdf_path.exists():
            print(f"❌ Error: Resume file not found at '{pdf_path}'")
            sys.exit(1)
        if not args.json:
            format_cli_banner()
            print(f"📄 Analyzing Candidate Resume: {pdf_path.name}")
        candidate_profile = service.resume_parser.parse(str(pdf_path))
        if not args.json:
            print(f"• Candidate:  {candidate_profile.get('candidate_name', 'Candidate')}")
            print(f"• Experience: {candidate_profile.get('years_of_experience', 2)} Yrs ({candidate_profile.get('seniority_level', 'Mid-Level')})")
            print(f"• Top Skills: {', '.join(candidate_profile.get('top_skills', [])[:8])}")

        if not args.role and candidate_profile.get("primary_role"):
            target_role = candidate_profile["primary_role"]

    elif args.resume_text:
        candidate_profile = service.resume_parser.parse_from_text(args.resume_text)

    search_query = args.search_posts or target_role

    if not args.json:
        if not args.resume:
            format_cli_banner()
        print(f"🔍 Searching Verified LinkedIn Hiring Posts: '{search_query}' in '{target_location}' (Window: {args.timeframe})...\n")

    res = service.search_opportunities(
        query=search_query,
        location=target_location,
        timeframe=args.timeframe,
        max_results=args.results,
        remote_only=args.remote,
        candidate_profile=candidate_profile
    )

    if args.json:
        print(json.dumps(res, indent=2))
        return

    opportunities = res.get("results", [])
    if not opportunities:
        print("⚠️ No direct recruiter posts found in the requested timeframe.")
        print(f"Message: {res.get('message')}")
        return

    print(f"✅ Found {len(opportunities)} Verified Live Recruiter Opportunities:\n")
    print(LinkedInFinder.format_as_markdown_table(opportunities))
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
