import re
from typing import Dict, List, Any, Optional, Tuple
from core.hiring_intent import (
    RoleRelevanceMatcher,
    LocationRelevanceMatcher,
    ExperienceRelevanceMatcher,
    QualityScorer
)
from core.matcher import JobMatcher


class OpportunityRanker:
    """
    Enterprise-Grade Multi-Signal Opportunity Ranking Layer.
    Combines Post Credibility (Quality), Candidate Profile Fit (ATS Matching),
    Timeframe Decay, Role Precision, Location Alignment, and Soft Company Diversity
    into an explainable, deterministic ranking system.
    """

    POST_QUALITY_WEIGHT = 0.45
    CANDIDATE_MATCH_WEIGHT = 0.55

    @classmethod
    def calculate_post_quality(
        cls,
        post: Dict[str, Any],
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        candidate_exp_years: int = 2,
        max_age_minutes: int = 1440
    ) -> Tuple[int, Dict[str, int]]:
        """
        Calculates pure post quality and returns score along with component factor scores.
        """
        # 1. Intent Factor
        hiring_conf = post.get("hiring_confidence", 0.9)
        intent_score = int(hiring_conf * 100)

        # 2. Freshness Factor (Linear decay within window)
        age_minutes = post.get("age_minutes", 0)
        if max_age_minutes > 0 and age_minutes >= 0:
            freshness_ratio = max(0.0, 1.0 - (age_minutes / max_age_minutes))
            freshness_score = int(freshness_ratio * 100)
        else:
            freshness_score = 50

        # 3. Role Factor
        role_score = post.get("role_match_score")
        if role_score is None:
            resolved_role = target_role or post.get("role") or post.get("title") or "Software Engineer"
            role_res = RoleRelevanceMatcher.calculate_score_with_reason(
                target_role=resolved_role,
                post_role=post.get("role") or post.get("title") or "Software Engineer",
                post_content=post.get("full_post_content", "") or post.get("raw_snippet", ""),
                extracted_roles=post.get("extracted_roles", [])
            )
            role_score = role_res["score"]

        # 4. Location Factor
        loc_score = post.get("location_match_score")
        if loc_score is None:
            loc_res = LocationRelevanceMatcher.match(
                target_location=target_location or "India",
                post_location=post.get("location", "Unspecified / Remote"),
                post_content=post.get("full_post_content", "") or post.get("raw_snippet", "")
            )
            loc_score = loc_res.get("score", 100)

        # 5. Experience Factor
        exp_score = post.get("experience_match_score")
        if exp_score is None:
            exp_res = ExperienceRelevanceMatcher.match(
                candidate_exp_years=candidate_exp_years,
                required_exp_str=post.get("experience_required", "") or post.get("full_post_content", "")
            )
            exp_score = exp_res.get("score", 75)

        # 6. Contact Factor
        emails = post.get("recruiter_emails") or post.get("contact_emails") or []
        phones = post.get("contact_phones") or post.get("contact_numbers") or []
        contact_raw = 0
        if emails:
            contact_raw += 50
        if phones:
            contact_raw += 30
        if post.get("post_url"):
            contact_raw += 20
        contact_score = min(100, contact_raw)

        # Overall Post Quality (Intent 25%, Freshness 20%, Role 30%, Location 15%, Experience 5%, Contact 5%)
        # If specific city requested and post location is a mismatch (score < 50), apply a penalty
        loc_penalty = 25 if (target_location and target_location.lower() not in ["india", "remote", "any", ""] and loc_score < 50) else 0

        total_quality = int(
            (intent_score * 0.25) +
            (freshness_score * 0.20) +
            (role_score * 0.30) +
            (loc_score * 0.15) +
            (exp_score * 0.05) +
            (contact_score * 0.05)
        ) - loc_penalty
        total_quality = max(0, min(100, total_quality))

        factors = {
            "hiring_intent": intent_score,
            "freshness": freshness_score,
            "role_relevance": role_score,
            "location_relevance": loc_score,
            "experience_relevance": exp_score,
            "contact_richness": contact_score
        }

        return total_quality, factors

    @classmethod
    def evaluate_opportunity(
        cls,
        post: Dict[str, Any],
        candidate_profile: Optional[Dict[str, Any]] = None,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_age_minutes: int = 1440
    ) -> Dict[str, Any]:
        """
        Evaluates a single post, returning distinct post_quality_score, candidate_match_score,
        final_rank_score, ranking_factors, and evidence-based ranking_reasons.
        """
        cand_exp = 2
        if candidate_profile:
            cand_exp = candidate_profile.get("years_of_experience", 2)
            if isinstance(cand_exp, str):
                try:
                    cand_exp = int(re.search(r'\d+', cand_exp).group(0))
                except Exception:
                    cand_exp = 2

        # 1. Calculate Post Quality
        post_quality, factors = cls.calculate_post_quality(
            post=post,
            target_role=target_role,
            target_location=target_location,
            candidate_exp_years=cand_exp,
            max_age_minutes=max_age_minutes
        )

        # 2. Calculate Candidate Fit Score
        candidate_match_score = None
        match_data = {}
        if candidate_profile and (candidate_profile.get("top_skills") or candidate_profile.get("primary_role")):
            cand_skills = candidate_profile.get("top_skills", [])
            req_skills = post.get("skills") or post.get("required_skills") or post.get("detected_skills") or []
            exp_str = post.get("experience_required") or post.get("full_post_content") or ""

            match_data = JobMatcher.calculate_weighted_match(
                candidate_skills=cand_skills,
                candidate_exp_years=cand_exp,
                required_skills=req_skills,
                experience_required_str=exp_str
            )
            candidate_match_score = match_data.get("match_score", 70)
            factors["candidate_fit"] = candidate_match_score
        else:
            factors["candidate_fit"] = None

        # 3. Compute Final Opportunity Rank Score
        if candidate_match_score is not None:
            final_rank_score = int(round(
                (post_quality * cls.POST_QUALITY_WEIGHT) +
                (candidate_match_score * cls.CANDIDATE_MATCH_WEIGHT)
            ))
        else:
            final_rank_score = post_quality

        final_rank_score = max(0, min(100, final_rank_score))

        # 4. Generate Explainable Evidence Reasons
        reasons = []
        role_name = post.get("role") or post.get("job_role") or post.get("title") or "Developer"
        role_reason = post.get("role_match_reason") or f"{factors['role_relevance']}% role match"
        reasons.append(f"{role_name} ({role_reason})")

        posted_time = post.get("posted_time") or post.get("age_text") or f"{post.get('age_minutes', 0)}m ago"
        reasons.append(f"Posted {posted_time} (Freshness: {factors['freshness']}/100)")

        loc_name = post.get("location", "Unspecified")
        reasons.append(f"Location: {loc_name} ({factors['location_relevance']}/100)")

        if candidate_match_score is not None:
            matched_skills_str = ", ".join(match_data.get("matched_skills", [])[:3])
            if matched_skills_str:
                reasons.append(f"{candidate_match_score}% candidate fit (Matched: {matched_skills_str})")
            else:
                reasons.append(f"{candidate_match_score}% candidate fit")

        emails = post.get("recruiter_emails") or post.get("contact_emails") or []
        if emails:
            reasons.append(f"Direct contact: {emails[0]}")

        # Summary line
        company_name = post.get("company", "Hiring Team")
        if candidate_match_score is not None:
            summary = f"{final_rank_score}/100 — {role_name} @ {company_name}, {posted_time}, {loc_name}, {candidate_match_score}% candidate fit."
        else:
            summary = f"{final_rank_score}/100 — {role_name} @ {company_name}, {posted_time}, {loc_name} (Quality: {post_quality}/100)."

        result = dict(post)
        result["post_quality_score"] = post_quality
        result["candidate_match_score"] = candidate_match_score
        result["final_rank_score"] = final_rank_score
        result["ranking_factors"] = factors
        result["ranking_reasons"] = reasons
        result["ranking_summary"] = summary

        if match_data:
            result["match_grade"] = match_data.get("match_grade")
            result["matched_skills"] = match_data.get("matched_skills", [])
            result["missing_skills"] = match_data.get("missing_skills", [])
            result["ats_recommendations"] = match_data.get("ats_recommendations", [])

        return result

    @classmethod
    def rank_opportunities(
        cls,
        posts: List[Dict[str, Any]],
        candidate_profile: Optional[Dict[str, Any]] = None,
        target_role: Optional[str] = None,
        target_location: Optional[str] = None,
        max_age_minutes: int = 1440,
        apply_diversity: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Scores, diversifies, and deterministically ranks a collection of candidate posts.
        Enforces tie-breakers:
          1. final_rank_score DESC
          2. post_quality_score DESC
          3. candidate_match_score DESC (or 0)
          4. age_minutes ASC
          5. post_url ASC
        """
        if not posts:
            return []

        # Strict Freshness Enforcement
        fresh_posts = []
        for p in posts:
            age_m = p.get("age_minutes")
            if age_m is not None and max_age_minutes > 0:
                if age_m > max_age_minutes:
                    continue
            fresh_posts.append(p)

        if not fresh_posts:
            fresh_posts = posts  # Safety fallback only if no timestamps present

        evaluated_posts = [
            cls.evaluate_opportunity(
                post=p,
                candidate_profile=candidate_profile,
                target_role=target_role,
                target_location=target_location,
                max_age_minutes=max_age_minutes
            )
            for p in fresh_posts
        ]

        # Initial deterministic sort:
        # If target location is a specific city, prioritize matching location posts (score >= 70) first
        evaluated_posts.sort(
            key=lambda x: (
                (1 if (x.get("ranking_factors", {}).get("location_relevance", 100) >= 70) else 0) if (target_location and target_location.lower() not in ["india", "remote", "any", ""]) else 1,
                x.get("final_rank_score", 0),
                x.get("post_quality_score", 0),
                x.get("candidate_match_score") or 0,
                -(x.get("age_minutes", 99999)),
                x.get("post_url", "")
            ),
            reverse=True
        )

        if not apply_diversity or len(evaluated_posts) <= 1:
            return evaluated_posts

        # Soft Company Diversity: apply -3 penalty for repeated company appearances
        company_counts: Dict[str, int] = {}
        for item in evaluated_posts:
            comp = (item.get("company") or "Hiring Team").strip().lower()
            count = company_counts.get(comp, 0)
            company_counts[comp] = count + 1

            if count >= 1 and comp not in ["hiring team", "unspecified"]:
                penalty = min(6, count * 3)
                item["_diversity_penalty"] = penalty
                item["_adjusted_rank_score"] = max(0, item["final_rank_score"] - penalty)
            else:
                item["_adjusted_rank_score"] = item["final_rank_score"]

        # Final re-sort by adjusted rank score with full deterministic tie-breakers
        evaluated_posts.sort(
            key=lambda x: (
                x.get("_adjusted_rank_score", x.get("final_rank_score", 0)),
                x.get("post_quality_score", 0),
                x.get("candidate_match_score") or 0,
                -(x.get("age_minutes", 99999)),
                x.get("post_url", "")
            ),
            reverse=True
        )

        return evaluated_posts
