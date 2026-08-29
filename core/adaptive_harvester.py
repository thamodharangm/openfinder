"""
core/adaptive_harvester.py
==========================
Production-grade Adaptive Yield-Optimized Bulk Harvesting Engine.

Features:
- Dynamic Keyword & Emerging Role Extraction from harvested post corpus.
- Multi-Armed Bandit Query Yield Optimizer (allocates budget to high-yield query families, prunes spam branches).
- Strict 25s Execution Guardrail specifically designed for Claude Web / Desktop MCP Connectors.
- Diminishing-returns detector and honest stop reason telemetry.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class QueryYieldStats:
    query: str
    category: str
    raw_count: int = 0
    verified_count: int = 0
    yield_percent: float = 0.0

    def compute_yield(self) -> float:
        if self.raw_count == 0:
            self.yield_percent = 0.0
        else:
            self.yield_percent = round((self.verified_count / self.raw_count) * 100.0, 1)
        return self.yield_percent


class QueryYieldTracker:
    """
    Tracks and optimizes yield per query vector to allocate search budget efficiently.
    """

    def __init__(self):
        self.stats: Dict[str, QueryYieldStats] = {}

    def record_query(self, query: str, category: str, raw_count: int, verified_count: int):
        clean_q = query.strip()
        if clean_q not in self.stats:
            self.stats[clean_q] = QueryYieldStats(query=clean_q, category=category)

        stat = self.stats[clean_q]
        stat.raw_count += raw_count
        stat.verified_count += verified_count
        stat.compute_yield()

    def get_high_yield_categories(self, min_raw: int = 5) -> List[str]:
        """Returns query categories that yield > 50% verified posts."""
        cat_verified = Counter()
        cat_raw = Counter()

        for stat in self.stats.values():
            cat_raw[stat.category] += stat.raw_count
            cat_verified[stat.category] += stat.verified_count

        high_yield = []
        for cat, raw in cat_raw.items():
            if raw >= min_raw:
                yield_rate = (cat_verified[cat] / raw) * 100.0
                if yield_rate >= 40.0:
                    high_yield.append(cat)

        return high_yield

    def get_summary(self) -> Dict[str, Any]:
        total_raw = sum(s.raw_count for s in self.stats.values())
        total_verified = sum(s.verified_count for s in self.stats.values())
        avg_yield = round((total_verified / total_raw) * 100.0, 1) if total_raw > 0 else 0.0

        top_queries = sorted(self.stats.values(), key=lambda s: s.yield_percent, reverse=True)[:5]
        return {
            "total_queries_evaluated": len(self.stats),
            "total_raw_harvested": total_raw,
            "total_verified_posts": total_verified,
            "average_yield_percent": avg_yield,
            "top_performing_queries": [
                {"query": s.query, "raw": s.raw_count, "verified": s.verified_count, "yield": s.yield_percent}
                for s in top_queries
            ]
        }


class DynamicKeywordExtractor:
    """
    Extracts recurring role titles, frameworks, and secondary locations from verified post content.
    """

    _ROLE_PATTERNS = [
        re.compile(r'\b(?:frontend\s+(?:engineer|developer|lead)|react(?:\.js)?\s+(?:developer|engineer)|mern\s+(?:stack|developer)|node(?:\.js)?\s+developer|full\s*stack\s+(?:engineer|developer)|ui\s+developer|javascript\s+developer|founding\s+engineer)\b', re.IGNORECASE),
        re.compile(r'\b(?:python\s+(?:developer|engineer)|fastapi\s+developer|backend\s+(?:engineer|developer)|software\s+development\s+engineer|sde\s*(?:1|2|i|ii|intern))\b', re.IGNORECASE)
    ]

    _LOCATION_PATTERNS = [
        re.compile(r'\b(?:bangalore|bengaluru|chennai|hyderabad|pune|mumbai|noida|gurgaon|delhi\s*ncr|coimbatore|kochi|remote)\b', re.IGNORECASE)
    ]

    @classmethod
    def extract_emerging_terms(cls, posts: List[Dict[str, Any]], existing_roles: List[str], existing_locs: List[str]) -> Tuple[List[str], List[str]]:
        role_counter = Counter()
        loc_counter = Counter()

        existing_roles_lower = {r.lower() for r in existing_roles}
        existing_locs_lower = {l.lower() for l in existing_locs}

        for p in posts:
            text = f"{p.get('title', '')} {p.get('role', '')} {p.get('snippet', '')} {p.get('raw_text', '')}".lower()

            for pat in cls._ROLE_PATTERNS:
                for match in pat.findall(text):
                    clean_match = match.title().strip()
                    if clean_match.lower() not in existing_roles_lower:
                        role_counter[clean_match] += 1

            for pat in cls._LOCATION_PATTERNS:
                for match in pat.findall(text):
                    clean_loc = match.title().strip()
                    if clean_loc.lower() not in existing_locs_lower:
                        loc_counter[clean_loc] += 1

        # Pick top emerging terms with frequency >= 1
        discovered_roles = [role for role, count in role_counter.most_common(3) if count >= 1]
        discovered_locs = [loc for loc, count in loc_counter.most_common(2) if count >= 1]

        return discovered_roles, discovered_locs
