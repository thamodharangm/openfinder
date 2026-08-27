from typing import Dict, List, Any


class JobMatcher:
    """
    Computes match score and skill gap between candidate's resume and LinkedIn hiring posts.
    """

    @staticmethod
    def calculate_match(candidate_skills: List[str], required_skills: List[str]) -> Dict[str, Any]:
        """
        Calculates match percentage and skill breakdown.
        """
        cand_set = {s.lower() for s in candidate_skills}
        req_set = {s.lower() for s in required_skills}

        if not req_set:
            # If the post doesn't list specific technical skills from taxonomy, give a baseline score
            return {
                "match_score": 65,
                "matched_skills": list(candidate_skills[:3]),
                "missing_skills": [],
                "match_grade": "Moderate (General Match)"
            }

        matched = cand_set.intersection(req_set)
        missing = req_set - cand_set

        match_score = int((len(matched) / len(req_set)) * 100)
        # Cap score between 0 and 100
        match_score = max(10, min(match_score, 100))

        if match_score >= 80:
            grade = "🌟 Excellent Match"
        elif match_score >= 60:
            grade = "⚡ Good Match"
        elif match_score >= 40:
            grade = "⚠️ Partial Match"
        else:
            grade = "❌ Low Match"

        # Convert sets back to title case for display
        return {
            "match_score": match_score,
            "matched_skills": [s.title() for s in matched],
            "missing_skills": [s.title() for s in missing],
            "match_grade": grade
        }

    @classmethod
    def rank_and_score_posts(
        cls, 
        candidate_profile: Dict[str, Any], 
        posts: List[Dict[str, Any]], 
        min_score: int = 40
    ) -> List[Dict[str, Any]]:
        """
        Scores all posts against candidate's profile and returns sorted results.
        """
        candidate_skills = candidate_profile.get("matched_skills", [])
        ranked_posts = []

        for post in posts:
            req_skills = post.get("required_skills", [])
            match_data = cls.calculate_match(candidate_skills, req_skills)

            if match_data["match_score"] >= min_score:
                enriched_post = {**post, **match_data}
                ranked_posts.append(enriched_post)

        # Sort descending by match score
        ranked_posts.sort(key=lambda x: x["match_score"], reverse=True)
        return ranked_posts
