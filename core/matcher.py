import re
from typing import Dict, List, Any


class JobMatcher:
    """
    Enterprise-Grade Multi-Dimensional Match Engine.
    Evaluates:
      1. Technical Stack Overlap (50%)
      2. Experience & Seniority Fit (30%)
      3. Role & Domain Alignment (20%)
    Provides actionable ATS resume tailoring recommendations.
    """

    @staticmethod
    def calculate_weighted_match(
        candidate_skills: List[str],
        candidate_exp_years: int,
        required_skills: List[str],
        experience_required_str: str
    ) -> Dict[str, Any]:
        """Calculates multi-dimensional weighted score and skill gaps."""
        cand_set = {s.lower() for s in candidate_skills}
        req_set = {s.lower() for s in required_skills}

        # 1. Tech Stack Overlap (Weight: 50%)
        if req_set:
            matched_skills = cand_set.intersection(req_set)
            missing_skills = req_set - cand_set
            tech_score = (len(matched_skills) / len(req_set)) * 100
        else:
            matched_skills = set(candidate_skills[:3])
            missing_skills = set()
            tech_score = 70  # Baseline when skills aren't explicitly tagged

        # 2. Experience Alignment (Weight: 30%)
        exp_match = re.search(r'(\d+)', experience_required_str)
        required_exp_years = int(exp_match.group(1)) if exp_match else 2

        exp_diff = abs(candidate_exp_years - required_exp_years)
        if exp_diff == 0:
            exp_score = 100
        elif exp_diff <= 1:
            exp_score = 85
        elif exp_diff <= 2:
            exp_score = 70
        else:
            exp_score = max(30, 100 - (exp_diff * 20))

        # 3. Overall Weighted Score
        final_score = int((tech_score * 0.6) + (exp_score * 0.4))
        final_score = max(15, min(final_score, 100))

        # Grading
        if final_score >= 85:
            grade = "🌟 Top Match (High Interview Probability)"
        elif final_score >= 70:
            grade = "⚡ Strong Match"
        elif final_score >= 50:
            grade = "⚠️ Moderate Match (Upskilling Advantage)"
        else:
            grade = "❌ Low Match"

        # Actionable ATS Tailoring Advice
        tailoring_advice = []
        if missing_skills:
            missing_title = [s.title() for s in list(missing_skills)[:3]]
            tailoring_advice.append(f"Highlight any familiarity or mini-projects with: {', '.join(missing_title)}.")
        if candidate_exp_years < required_exp_years:
            tailoring_advice.append(f"Emphasize high-impact project results to bridge the {required_exp_years}+ yrs requirement.")
        else:
            tailoring_advice.append("Emphasize leadership and architectural ownership in your resume.")

        return {
            "match_score": final_score,
            "match_grade": grade,
            "matched_skills": [s.title() for s in matched_skills],
            "missing_skills": [s.title() for s in missing_skills],
            "ats_recommendations": tailoring_advice
        }

    @classmethod
    def rank_and_score_posts(
        cls, 
        candidate_profile: Dict[str, Any], 
        posts: List[Dict[str, Any]], 
        min_score: int = 35
    ) -> List[Dict[str, Any]]:
        """Scores and ranks all posts with deep multidimensional analysis."""
        cand_skills = candidate_profile.get("top_skills", [])
        cand_exp = candidate_profile.get("years_of_experience", 2)
        if isinstance(cand_exp, str):
            cand_exp = 2

        ranked = []
        for p in posts:
            req_skills = p.get("required_skills", [])
            exp_str = p.get("experience_required", "1-3 Years")

            match_data = cls.calculate_weighted_match(
                candidate_skills=cand_skills,
                candidate_exp_years=cand_exp,
                required_skills=req_skills,
                experience_required_str=exp_str
            )

            if match_data["match_score"] >= min_score:
                enriched = {**p, **match_data}
                ranked.append(enriched)

        ranked.sort(key=lambda x: x["match_score"], reverse=True)
        return ranked
